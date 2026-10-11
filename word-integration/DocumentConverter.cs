// Local conversion in a new, hidden Microsoft Word process. Never attach to an
// active user application and never save or overwrite the source document.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class DocumentConverter {
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 1000000 };
    static Process ownedWord;
    static long ownedStart;
    static string responsePath;
    static string currentPhase = "startup";
    static string phase {
        get { return currentPhase; }
        set {
            currentPhase = value;
            try { File.WriteAllText(responsePath + ".progress", value); } catch { }
        }
    }
    static readonly object responseLock = new object();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    static Dictionary<string, object> Obj(params object[] pairs) {
        var result = new Dictionary<string, object>();
        for (int i = 0; i < pairs.Length; i += 2) result[(string)pairs[i]] = pairs[i + 1];
        return result;
    }
    static void Need(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
    static void Release(object value) { try { if (value != null && Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value); } catch { } }
    static void Respond(object answer) {
        lock (responseLock) {
            try { File.WriteAllText(responsePath, Json.Serialize(answer), new UTF8Encoding(false)); } catch { }
        }
    }
    static void StopOwnedWord() {
        try {
            Process process = ownedWord;
            if (process != null && !process.HasExited && process.StartTime.ToUniversalTime().Ticks == ownedStart && String.IsNullOrEmpty(process.MainWindowTitle)) {
                process.Kill(); process.WaitForExit(5000);
            }
        } catch { }
    }
    static void Deadline(object unused) {
        string stalledPhase = phase;
        StopOwnedWord();
        Respond(Obj("ok", false, "error", "转换等待时间较长，已停止本次转换。请先用 Word 检查文件是否能正常打开。", "detail", stalledPhase));
        Environment.Exit(3);
    }
    [STAThread]
    static int Main(string[] args) {
        if (args.Length != 2) return 2;
        responsePath = args[1];
        try {
            var request = (Dictionary<string, object>)Json.DeserializeObject(File.ReadAllText(args[0], Encoding.UTF8));
            string action = Convert.ToString(request["action"]);
            Type wordType = Type.GetTypeFromProgID("Word.Application");
            if (action == "health") {
                Respond(Obj("ok", true, "result", Obj("installed", wordType != null,
                    "platform", "Windows desktop Word", "message", wordType != null ? "本机已安装 Microsoft Word。" : "Word 导入与转 PDF 需要安装 Microsoft Word；PDF 转 Word 可直接使用。")));
                return 0;
            }
            Need(action == "convert", "不支持的转换操作。");
            Need(wordType != null, "Word 导入与转 PDF 需要安装 Windows 桌面版 Microsoft Word。");
            int timeoutMs = (int)Math.Max(1000, Math.Min(1800000, Convert.ToDouble(request["timeout_seconds"]) * 1000));
            using (var deadline = new Timer(Deadline, null, timeoutMs, Timeout.Infinite))
            using (var mutex = new Mutex(false, "Local\\PaperQuick.DocumentConverter")) {
                bool acquired = false;
                try {
                    try { acquired = mutex.WaitOne(timeoutMs); } catch (AbandonedMutexException) { acquired = true; }
                    Need(acquired, "正在转换另一份文档，请稍后重试。");
                    object result = ConvertFile(wordType, request);
                    deadline.Change(Timeout.Infinite, Timeout.Infinite);
                    Respond(Obj("ok", true, "result", result));
                } finally { if (acquired) mutex.ReleaseMutex(); }
            }
            return 0;
        } catch (Exception error) {
            string message = error is InvalidOperationException ? error.Message : "Word 无法转换这份文件。请确认文件未加密、未损坏，且本机 Word 能正常打开它。";
            Respond(Obj("ok", false, "error", message, "detail", error.ToString()));
            return 1;
        }
    }
    static object ConvertFile(Type wordType, Dictionary<string, object> request) {
        string source = Path.GetFullPath(Convert.ToString(request["source"]));
        string target = Path.GetFullPath(Convert.ToString(request["destination"]));
        string sourceExt = Path.GetExtension(source).ToLowerInvariant(), targetExt = Path.GetExtension(target).ToLowerInvariant();
        Need(File.Exists(source), "找不到原文件，请重新选择。");
        Need(!File.Exists(target) && !Directory.Exists(target), "保存位置已有同名文件，请换一个名称。");
        Need(!String.Equals(source, target, StringComparison.OrdinalIgnoreCase), "请将转换结果保存为一个新文件。");
        Need((sourceExt == ".doc" || sourceExt == ".docx") && targetExt == ".pdf", "这个组件用于 Word 转 PDF。请在阅读页面选择 PDF 转 Word。");
        var priorPids = new HashSet<int>(Process.GetProcessesByName("WINWORD").Select(p => p.Id));
        dynamic app = null, document = null, options = null, documents = null, probe = null;
        bool owns = false, isolatedEmptyInstance = false;
        bool updateLinks = false, updateFieldsPrint = false, updateLinksPrint = false;
        bool optionsCaptured = false;
        int security = 3;
        string version = "";
        int pages = 0;
        try {
            phase = "create Word";
            app = Activator.CreateInstance(wordType);
            documents = app.Documents;
            Need((int)documents.Count == 0, "独立 Word 窗口中已有文档，本次转换已取消。");
            isolatedEmptyInstance = true;
            security = (int)app.AutomationSecurity;
            app.AutomationSecurity = 3; // msoAutomationSecurityForceDisable
            // Word exposes HWND on Window, not Application. A hidden, unsaved
            // probe gives the exact process identity without attaching to ROT.
            probe = documents.Add(Visible: false);
            uint pid;
            GetWindowThreadProcessId(new IntPtr((int)probe.ActiveWindow.Hwnd), out pid);
            if (pid > 0 && priorPids.Contains((int)pid)) isolatedEmptyInstance = false;
            Need(pid > 0 && !priorPids.Contains((int)pid), "无法建立独立的 Word 转换窗口，请关闭转换任务后重试。");
            ownedWord = Process.GetProcessById((int)pid);
            ownedStart = ownedWord.StartTime.ToUniversalTime().Ticks;
            owns = true;
            app.Visible = false;
            app.DisplayAlerts = 0;
            app.ScreenUpdating = false;
            version = Convert.ToString(app.Version);
            options = app.Options;
            updateLinks = (bool)options.UpdateLinksAtOpen;
            updateFieldsPrint = (bool)options.UpdateFieldsAtPrint;
            updateLinksPrint = (bool)options.UpdateLinksAtPrint;
            optionsCaptured = true;
            options.UpdateLinksAtOpen = false;
            options.UpdateFieldsAtPrint = false;
            options.UpdateLinksAtPrint = false;
            string noPassword = Guid.NewGuid().ToString("N");
            phase = "open " + sourceExt;
            document = documents.OpenNoRepairDialog(FileName: source, ConfirmConversions: false, ReadOnly: true,
                AddToRecentFiles: false, PasswordDocument: noPassword, PasswordTemplate: noPassword,
                WritePasswordDocument: noPassword, WritePasswordTemplate: noPassword,
                Revert: false, Visible: false, OpenAndRepair: false, NoEncodingDialog: true);
            phase = "close probe";
            probe.Close(0); Release((object)probe); probe = null;
            Need((int)app.Documents.Count == 1, "Word 中出现了其他文档，本次转换已取消。");
            phase = "page count";
            pages = (int)document.ComputeStatistics(2); // wdStatisticPages
            phase = "export PDF";
            document.ExportAsFixedFormat(OutputFileName: target, ExportFormat: 17,
                OpenAfterExport: false, OptimizeFor: 0, Range: 0, Item: 0,
                IncludeDocProps: true, KeepIRM: true, CreateBookmarks: 1,
                DocStructureTags: true, BitmapMissingFonts: true, UseISO19005_1: false);
            Need(File.Exists(target) && new FileInfo(target).Length > 0, "Word 没有生成完整的转换文件，请检查原文件后重试。");
            return Obj("path", target, "pages", pages, "word_version", version, "owned_pid", (int)pid);
        } catch (Exception error) {
            phase = phase + ": " + error.Message;
            throw;
        } finally {
            if (owns || isolatedEmptyInstance) {
                phase = "close documents after " + phase;
                if (optionsCaptured) {
                    try { options.UpdateLinksAtOpen = updateLinks; options.UpdateFieldsAtPrint = updateFieldsPrint; options.UpdateLinksAtPrint = updateLinksPrint; } catch { }
                }
                try { app.AutomationSecurity = security; } catch { }
                try { if (probe != null) probe.Close(0); } catch { }
                try { if (document != null) document.Close(0); } catch { }
                try { app.NormalTemplate.Saved = true; } catch { }
                phase = "quit Word";
                try {
                    // If a user opened another document in this newly created
                    // instance while conversion ran, preserve that document.
                    if ((int)app.Documents.Count == 0) app.Quit(0);
                    else { owns = false; ownedWord = null; }
                } catch { }
            }
            Release((object)probe); Release((object)document); Release((object)documents); Release((object)options); Release((object)app);
            GC.Collect(); GC.WaitForPendingFinalizers();
            if (owns) {
                try { if (!ownedWord.WaitForExit(6000)) StopOwnedWord(); } catch { }
            }
        }
    }
}
