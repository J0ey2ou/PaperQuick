using System;
using System.IO;
using System.Drawing;
using System.Windows.Forms;
internal static class SelectionFixture {
    [STAThread] static void Main(string[] args) {
        if (args.Length > 0) {
            File.WriteAllLines(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "selection-result.txt"), args);
            return;
        }
        Application.EnableVisualStyles();
        var form = new Form { Text = "文献直达 · 独立选词测试窗口", Width = 760, Height = 300 };
        var text = new RichTextBox { Dock = DockStyle.Fill, Font = new Font("Segoe UI", 14), Text = "Highly accurate protein structure prediction with AlphaFold", ReadOnly = true };
        var menu = new ContextMenuStrip(); menu.Items.Add("复制", null, delegate { text.Copy(); });
        text.ContextMenuStrip = menu; form.Controls.Add(text);
        form.Shown += delegate { text.Focus(); text.SelectAll(); };
        var showTimer = new Timer { Interval = 1200 };
        showTimer.Tick += delegate { showTimer.Stop(); form.Hide(); form.Show(); text.Focus(); text.SelectAll(); };
        showTimer.Start();
        Application.Run(form);
    }
}
