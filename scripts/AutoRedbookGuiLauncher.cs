using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class AutoRedbookGuiLauncher
{
    [STAThread]
    private static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
            Path.DirectorySeparatorChar,
            Path.AltDirectorySeparatorChar
        );
        string scriptsDir = Path.Combine(root, ".venv", "Scripts");
        string pythonw = Path.Combine(scriptsDir, "pythonw.exe");
        string python = Path.Combine(scriptsDir, "python.exe");
        string executable = File.Exists(pythonw) ? pythonw : python;

        if (!File.Exists(executable))
        {
            MessageBox.Show(
                "未找到工作区虚拟环境：.venv\\Scripts\\pythonw.exe 或 python.exe\n\n请先在项目根目录创建 .venv 并安装依赖。",
                "Auto Redbook GUI 启动失败",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return;
        }

        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = executable,
                Arguments = "-m apps.gui",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            Process.Start(startInfo);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "启动 GUI 失败：\n" + ex.Message,
                "Auto Redbook GUI 启动失败",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }
    }
}
