// Integration test against our own helper and temporary config, never user documents.
using System;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
internal static class ShortcutRuntimeCheck {
    static string Current(Assistant assistant) { return (string)typeof(Assistant).GetField("shortcut", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(assistant); }
    static bool Change(Assistant assistant, string shortcut) { return (bool)typeof(Assistant).GetMethod("ApplyShortcut", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(assistant, new object[] { shortcut }); }
    static void Assert(bool condition, string name) { if (!condition) throw new Exception(name); }
    [STAThread] static void Main() {
        string directory = AppDomain.CurrentDomain.BaseDirectory;
        string path = Path.Combine(directory, "shortcut.json");
        string app = Path.Combine(directory, "文献直达.exe");
        File.WriteAllText(path, "{\"shortcut\":\"Ctrl + Alt + Shift + F20\"}");
        try {
            using (var assistant = new Assistant(app)) {
                Assert(Current(assistant) == "Ctrl + Alt + Shift + F20", "custom startup registration");
                using (var blocker = new Dispatcher()) {
                    Assert(Native.RegisterHotKey(blocker.Handle, 101, 0x4000 | 7, 0x84), "isolated conflict registration");
                    Assert(!Change(assistant, "Ctrl + Alt + Shift + F21"), "occupied shortcut rejected");
                    Assert(Current(assistant) == "Ctrl + Alt + Shift + F20", "old shortcut retained");
                    Native.UnregisterHotKey(blocker.Handle, 101);
                }
                File.WriteAllText(path, "{\"shortcut\":\"Ctrl + Alt + Shift + F22\"}");
                DateTime deadline = DateTime.UtcNow.AddSeconds(3);
                while (Current(assistant) != "Ctrl + Alt + Shift + F22" && DateTime.UtcNow < deadline) { Application.DoEvents(); Thread.Sleep(10); }
                Assert(Current(assistant) == "Ctrl + Alt + Shift + F22", "live config reload");
                assistant.ExitThread();
            }
            using (var restarted = new Assistant(app)) {
                Assert(Current(restarted) == "Ctrl + Alt + Shift + F22", "config survives restart");
                restarted.ExitThread();
            }
            File.WriteAllText(Path.Combine(directory, "runtime-check.json"), "{\"passed\":true,\"customRegistration\":true,\"conflictKeepsPrevious\":true,\"liveReload\":true,\"restartPersistence\":true}");
        } catch (Exception error) {
            File.WriteAllText(Path.Combine(directory, "runtime-check.json"), "{\"passed\":false,\"error\":\"" + error.Message + "\"}");
            Environment.Exit(1);
        }
    }
}
