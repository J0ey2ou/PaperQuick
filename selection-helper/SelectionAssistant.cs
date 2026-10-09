// .NET Framework 4.x：托盘快捷键选词查询，不监听鼠标、不创建跟随浮窗。
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using System.Collections.Generic;
using System.Web.Script.Serialization;

internal sealed class Shortcut {
    internal string Name; internal uint Modifiers; internal uint Key;
    internal static bool Parse(string text, out Shortcut shortcut) {
        shortcut = null;
        string[] parts = (text ?? "").Split('+');
        if (parts.Length < 3 || parts.Length > 4) return false;
        uint modifiers = 0;
        for (int i = 0; i < parts.Length - 1; i++) {
            string modifier = parts[i].Trim();
            uint flag = modifier == "Ctrl" ? 2u : modifier == "Alt" ? 1u : modifier == "Shift" ? 4u : 0u;
            if (flag == 0 || (modifiers & flag) != 0) return false;
            modifiers |= flag;
        }
        string key = parts[parts.Length - 1].Trim().ToUpperInvariant();
        uint code; int function;
        if (key.Length == 1 && ((key[0] >= 'A' && key[0] <= 'Z') || (key[0] >= '0' && key[0] <= '9'))) code = key[0];
        else if (key.StartsWith("F") && Int32.TryParse(key.Substring(1), out function) && function >= 1 && function <= 24 && key == "F" + function) code = (uint)(0x70 + function - 1);
        else return false;
        shortcut = new Shortcut { Modifiers = modifiers, Key = code, Name = ((modifiers & 2) != 0 ? "Ctrl + " : "") + ((modifiers & 1) != 0 ? "Alt + " : "") + ((modifiers & 4) != 0 ? "Shift + " : "") + key };
        return true;
    }
}

internal static class Program {
    [STAThread]
    static void Main(string[] args) {
        try { Native.SetProcessDPIAware(); } catch { }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if (args.Length > 0 && args[0] == "--exit") {
            try { using (var signal = System.Threading.EventWaitHandle.OpenExisting("Local\\PaperQuick.SelectionExit")) signal.Set(); } catch (System.Threading.WaitHandleCannotBeOpenedException) { }
            return;
        }
        if (args.Length == 2 && args[0] == "--verify-helper") {
            bool quote = Quote("a \"b\" c\\") == "\"a \\\"b\\\" c\\\\\"";
            bool abi = Marshal.SizeOf(typeof(Native.Input)) == (IntPtr.Size == 8 ? 40 : 28);
            Shortcut parsed;
            bool parser = Shortcut.Parse("Shift + Ctrl + J", out parsed) && parsed.Name == "Ctrl + Shift + J" && parsed.Modifiers == 6 && parsed.Key == 0x4A && !Shortcut.Parse("Ctrl + Ctrl + J", out parsed) && !Shortcut.Parse("Ctrl + Alt + F25", out parsed);
            using (var dispatcher = new Dispatcher()) {
                bool key = Native.RegisterHotKey(dispatcher.Handle, 72, 0x4000 | 3, 0x87);
                if (key) Native.UnregisterHotKey(dispatcher.Handle, 72);
                File.WriteAllText(args[1], "{\"passed\":" + (quote && abi && key && parser ? "true" : "false") + ",\"quoting\":" + (quote ? "true" : "false") + ",\"inputABI\":" + (abi ? "true" : "false") + ",\"shortcutParser\":" + (parser ? "true" : "false") + ",\"hotkeyRegistration\":" + (key ? "true" : "false") + ",\"mouseFollowing\":false}");
                Environment.Exit(quote && abi && key && parser ? 0 : 4);
            }
            return;
        }
        bool created;
        using (var mutex = new System.Threading.Mutex(true, "Local\\PaperQuick.SelectionAssistant", out created)) {
            if (!created) return;
            string app = args.Length > 0 ? args[0] : Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "文献直达.exe");
            if (!File.Exists(app)) { MessageBox.Show("请将全局选词助手.exe 与文献直达.exe 放在同一目录。", "文献直达"); return; }
            using (var context = new Assistant(app, args.Length > 1 ? args[1] : null)) Application.Run(context);
        }
    }
    internal static string Quote(string value) {
        var b = new StringBuilder("\""); int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { b.Append('\\', slashes * 2 + 1); b.Append(c); }
            else { b.Append('\\', slashes); b.Append(c); }
            slashes = 0;
        }
        b.Append('\\', slashes * 2); b.Append('"'); return b.ToString();
    }
}

internal class Dispatcher : Form {
    internal Action Hotkey;
    protected override void WndProc(ref Message m) {
        if (m.Msg == 0x0312 && Hotkey != null) Hotkey();
        base.WndProc(ref m);
    }
}

internal sealed class Assistant : ApplicationContext {
    readonly string app;
    readonly string diagnostics;
    readonly Dispatcher dispatcher = new Dispatcher();
    readonly NotifyIcon tray = new NotifyIcon();
    readonly Timer timer = new Timer { Interval = 40 };
    readonly Timer configTimer = new Timer { Interval = 1500 };
    readonly System.Threading.EventWaitHandle exitSignal = new System.Threading.EventWaitHandle(false, System.Threading.EventResetMode.AutoReset, "Local\\PaperQuick.SelectionExit");
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    readonly string configPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "shortcut.json");
    string observedConfig = "";
    string configError = "";
    ToolStripMenuItem shortcutItem;
    Form shortcutDialog;
    int hotkeyId = 71;
    IntPtr sourceWindow;
    uint clipboardBefore;
    long deadline;
    int stage;
    bool registered;
    int triggerKey = 0x46;
    string shortcut = "Ctrl + Alt + F";

    internal Assistant(string executable, string diagnosticFile = null) {
        app = executable;
        diagnostics = diagnosticFile;
        dispatcher.Hotkey = BeginQuery;
        string configured = ReadConfig();
        observedConfig = configured;
        var names = new List<string>();
        if (!String.IsNullOrEmpty(configured)) names.Add(configured);
        names.AddRange(new[] { "Ctrl + Alt + F", "Ctrl + Alt + Shift + F", "Ctrl + Alt + F8" });
        foreach (string name in names) { if (ApplyShortcut(name)) break; }
        if (!String.IsNullOrEmpty(configured) && shortcut != configured) configError = "自定义快捷键不可用，已尝试备用组合。";
        Trace("registered=" + registered + "; shortcut=" + shortcut);
        var menu = new ContextMenuStrip();
        shortcutItem = new ToolStripMenuItem("选中文字后按 " + shortcut); shortcutItem.Enabled = false;
        menu.Items.Add(shortcutItem);
        menu.Items.Add("自定义快捷键…", null, delegate { ConfigureShortcut(); });
        menu.Items.Add("打开文献直达", null, delegate { Process.Start(new ProcessStartInfo(app) { UseShellExecute = true }); });
        menu.Items.Add("文献分类", null, delegate { Launch("--library"); });
        menu.Items.Add("设置 / 登录 Windows 后启动", null, delegate { Launch("--settings"); });
        menu.Items.Add("使用说明", null, delegate {
            string path = Path.Combine(Path.GetDirectoryName(app), "右键插件安装.html");
            if (File.Exists(path)) Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
        });
        menu.Items.Add("退出程序", null, delegate { Launch("--quit"); });
        try { tray.Icon = System.Drawing.Icon.ExtractAssociatedIcon(app); } catch { tray.Icon = System.Drawing.SystemIcons.Information; }
        tray.Text = "文献直达 · " + shortcut;
        tray.ContextMenuStrip = menu;
        tray.Visible = true;
        tray.DoubleClick += delegate { Launch(""); };
        Heartbeat();
        timer.Tick += Tick;
        configTimer.Tick += delegate {
            if (exitSignal.WaitOne(0)) { ExitThread(); return; }
            Heartbeat();
            if (stage != 0) return;
            string desired = ReadConfig();
            if (desired == observedConfig) return;
            observedConfig = desired;
            if (ApplyShortcut(String.IsNullOrEmpty(desired) ? "Ctrl + Alt + F" : desired)) configError = "";
            else configError = "快捷键已被占用或格式不正确，继续使用 " + shortcut;
            UpdateStatus();
        };
        configTimer.Start();
        UpdateStatus();
        if (!registered) Error("可用的快捷键都被其他软件占用。请使用浏览器右键菜单，或手动复制后粘贴查询。", "快捷键未能启用");
    }

    void Launch(string arguments) { Process.Start(new ProcessStartInfo(app, arguments) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Path.GetDirectoryName(app) }); }
    void Heartbeat() { try { string folder = Path.Combine(Path.GetDirectoryName(app), "runtime"); Directory.CreateDirectory(folder); File.WriteAllText(Path.Combine(folder, "tray-ready"), Process.GetCurrentProcess().Id.ToString()); } catch { } }

    string ReadConfig() {
        try { var data = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(configPath)); return Convert.ToString(data["shortcut"]); }
        catch { return ""; }
    }
    bool ApplyShortcut(string text) {
        Shortcut desired;
        if (!Shortcut.Parse(text, out desired)) return false;
        if (registered && shortcut == desired.Name) return true;
        int candidateId = hotkeyId == 71 ? 72 : 71;
        if (!Native.RegisterHotKey(dispatcher.Handle, candidateId, 0x4000 | desired.Modifiers, desired.Key)) return false;
        if (registered) Native.UnregisterHotKey(dispatcher.Handle, hotkeyId);
        hotkeyId = candidateId; registered = true; shortcut = desired.Name; triggerKey = (int)desired.Key;
        return true;
    }
    void UpdateStatus() {
        if (shortcutItem != null) shortcutItem.Text = "选中文字后按 " + shortcut;
        tray.Text = "文献直达 · " + shortcut;
        try {
            File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "shortcut-status.json"), json.Serialize(new { registered = registered, shortcut = shortcut, pid = Process.GetCurrentProcess().Id, error = configError }));
        } catch { }
    }
    void ConfigureShortcut() {
        if (shortcutDialog != null) { shortcutDialog.Activate(); return; }
        Finish();
        using (var dialog = new Form { Text = "文献直达 · 自定义快捷键", ClientSize = new System.Drawing.Size(440, 215), FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, MinimizeBox = false, StartPosition = FormStartPosition.CenterScreen }) {
            shortcutDialog = dialog;
            var hint = new Label { Text = "点击输入框后，按下你想使用的快捷键。\r\n至少两个修饰键（Ctrl / Alt / Shift）+ 字母、数字或 F1–F24。", AutoSize = false, Left = 20, Top = 18, Width = 400, Height = 48 };
            var input = new TextBox { Left = 20, Top = 75, Width = 400, ReadOnly = true, Text = shortcut };
            var message = new Label { Left = 20, Top = 110, Width = 400, Height = 35, Text = "保存成功后立即生效，下次启动继续使用。" };
            var save = new Button { Left = 290, Top = 160, Width = 130, Height = 32, Text = "保存快捷键" };
            input.KeyDown += delegate(object sender, KeyEventArgs e) {
                e.SuppressKeyPress = true;
                string key = e.KeyCode.ToString();
                if (key.Length == 2 && key[0] == 'D' && Char.IsDigit(key[1])) key = key.Substring(1);
                string value = (e.Control ? "Ctrl + " : "") + (e.Alt ? "Alt + " : "") + (e.Shift ? "Shift + " : "") + key;
                Shortcut parsed; if (Shortcut.Parse(value, out parsed)) { input.Text = parsed.Name; message.Text = "待保存：" + parsed.Name; }
            };
            save.Click += delegate {
                if (!ApplyShortcut(input.Text)) { message.Text = "这个组合已被占用，请换一个。原快捷键仍然可用。"; return; }
                try { File.WriteAllText(configPath, json.Serialize(new { shortcut = shortcut })); observedConfig = shortcut; configError = ""; UpdateStatus(); dialog.Close(); }
                catch { UpdateStatus(); message.Text = "当前会话已生效，但目录无法写入，未能保存。"; }
            };
            dialog.Controls.AddRange(new Control[] { hint, input, message, save });
            dialog.Shown += delegate { input.Focus(); };
            try { dialog.ShowDialog(); } finally { shortcutDialog = null; }
        }
    }

    void BeginQuery() {
        Trace("hotkey; stage=" + stage);
        if (stage != 0 || !registered || shortcutDialog != null) return;
        sourceWindow = Native.GetForegroundWindow();
        if (sourceWindow == IntPtr.Zero) return;
        stage = 1; deadline = Now() + 2500L; timer.Start();
    }

    static long Now() { return System.Diagnostics.Stopwatch.GetTimestamp() * 1000 / System.Diagnostics.Stopwatch.Frequency; }

    void Tick(object sender, EventArgs args) {
        try {
            if (!Native.IsWindow(sourceWindow) || Native.GetForegroundWindow() != sourceWindow)
                throw new Exception("查询时原窗口失去了焦点。请回到原软件，重新选中文字后按 " + shortcut + "。");
            if (stage == 1) {
                // Alt / Ctrl 松开后才发送复制，避免误触应用命令。
                if (Native.Down(0x11) || Native.Down(0x12) || Native.Down(0x10) || Native.Down(triggerKey)) {
                    if (Now() > deadline) throw new Exception("请松开快捷键后重试。");
                    return;
                }
                var info = new Native.GuiThreadInfo { cbSize = Marshal.SizeOf(typeof(Native.GuiThreadInfo)) };
                if (Native.GetGUIThreadInfo(0, ref info) && (info.flags & 4) != 0) {
                    if (Now() > deadline) throw new Exception("请关闭原应用菜单后重新按快捷键。");
                    Native.SendKeys(new ushort[] { 0x1B });
                    return;
                }
                clipboardBefore = Native.GetClipboardSequenceNumber();
                Native.Copy();
                Trace("copy sent");
                stage = 2; deadline = Now() + 1200L;
                return;
            }
            if (stage == 2) {
                if (Native.GetClipboardSequenceNumber() != clipboardBefore) {
                    try {
                        if (Clipboard.ContainsText(TextDataFormat.UnicodeText)) {
                            string text = Clipboard.GetText(TextDataFormat.UnicodeText).Trim();
                            if (!String.IsNullOrWhiteSpace(text)) {
                                if (text.Length > 8000) throw new Exception("选中文字过长，请只选择论文标题、DOI 或文献引用段落。");
                                Finish();
                                Trace("selection copied; length=" + text.Length);
                                Process.Start(new ProcessStartInfo(app, "--query " + Program.Quote(text) + " --auto-open") { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Path.GetDirectoryName(app) });
                                return;
                            }
                        }
                    } catch (ExternalException) { }
                }
                if (Now() > deadline) throw new Exception("未复制到新的选中文字。请先选中可复制的论文标题 / DOI 后重试；扫描版 PDF 需要 OCR，禁复制或管理员权限窗口可能无法读取。不会查询旧剪贴板内容。");
            }
        } catch (Exception error) { Finish(); Error(error.Message, "选词查询未完成"); }
    }
    void Finish() { timer.Stop(); stage = 0; }
    void Error(string text, string title) { Trace("error=" + text); tray.ShowBalloonTip(5000, title, text, ToolTipIcon.Warning); }
    void Trace(string text) { if (diagnostics != null) { try { File.AppendAllText(diagnostics, text + "\r\n"); } catch { } } }
    protected override void ExitThreadCore() {
        timer.Stop(); timer.Dispose();
        configTimer.Stop(); configTimer.Dispose();
        if (registered) Native.UnregisterHotKey(dispatcher.Handle, hotkeyId);
        tray.Visible = false; tray.Dispose(); dispatcher.Dispose();
        exitSignal.Dispose();
        base.ExitThreadCore();
    }
}

internal static class Native {
    [DllImport("user32.dll")] internal static extern bool SetProcessDPIAware();
    [StructLayout(LayoutKind.Sequential)] internal struct Rect { internal int left, top, right, bottom; }
    [StructLayout(LayoutKind.Sequential)] internal struct GuiThreadInfo { internal int cbSize, flags; internal IntPtr active, focus, capture, menuOwner, moveSize, caret; internal Rect caretRect; }
    [StructLayout(LayoutKind.Sequential)] internal struct Keyboard { internal ushort vk, scan; internal uint flags, time; internal UIntPtr extra; }
    [StructLayout(LayoutKind.Sequential)] internal struct MouseInput { internal int dx, dy; internal uint data, flags, time; internal UIntPtr extra; }
    [StructLayout(LayoutKind.Explicit)] internal struct InputUnion { [FieldOffset(0)] internal Keyboard keyboard; [FieldOffset(0)] internal MouseInput sizePadding; }
    [StructLayout(LayoutKind.Sequential)] internal struct Input { internal uint type; internal InputUnion data; }
    [DllImport("user32.dll")] internal static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] internal static extern bool IsWindow(IntPtr window);
    [DllImport("user32.dll")] internal static extern bool RegisterHotKey(IntPtr window, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] internal static extern bool UnregisterHotKey(IntPtr window, int id);
    [DllImport("user32.dll")] internal static extern uint GetClipboardSequenceNumber();
    [DllImport("user32.dll")] internal static extern bool GetGUIThreadInfo(uint thread, ref GuiThreadInfo info);
    [DllImport("user32.dll")] internal static extern short GetAsyncKeyState(int vk);
    [DllImport("user32.dll", SetLastError = true)] internal static extern uint SendInput(uint count, Input[] inputs, int size);
    internal static bool Down(int vk) { return (GetAsyncKeyState(vk) & 0x8000) != 0; }
    static Input Key(ushort vk, bool up) { return new Input { type = 1, data = new InputUnion { keyboard = new Keyboard { vk = vk, flags = up ? 2u : 0u } } }; }
    internal static void Copy() {
        Send(new[] { Key(0x11, false), Key(0x43, false), Key(0x43, true), Key(0x11, true) });
    }
    internal static void SendKeys(ushort[] keys) {
        var inputs = new Input[keys.Length * 2];
        for (int i = 0; i < keys.Length; i++) { inputs[i * 2] = Key(keys[i], false); inputs[i * 2 + 1] = Key(keys[i], true); }
        Send(inputs);
    }
    static void Send(Input[] inputs) {
        if (SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(Input))) != inputs.Length)
            throw new Exception("无法向原应用复制选词。请使用普通权限运行软件，或手动复制后粘贴查询。");
    }
}
