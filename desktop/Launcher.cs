// JobWatcher.exe: starts desktop\app.py with the backend venv Python and exits.
// It loads nothing from Job Watcher itself, so code changes never require
// recompiling it. scripts\desktop.bat compiles it with the csc shipped in Windows.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static void Main(string[] args)
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        string root = Path.GetFullPath(Path.Combine(folder, ".."));
        // pythonw, not python: no console window behind the app.
        string python = Path.Combine(root, @"backend\.venv\Scripts\pythonw.exe");
        string app = Path.Combine(folder, "app.py");

        if (!File.Exists(python))
        {
            MessageBox.Show(
                "Virtual environment not found at\n" + python + "\n\nRun scripts\\desktop.bat again.",
                "Job Watcher", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        string extra = string.Join(" ", args.Select(a => "\"" + a.Replace("\"", "") + "\""));
        var start = new ProcessStartInfo(python, "\"" + app + "\" " + extra);
        start.WorkingDirectory = Path.Combine(root, "backend");
        start.UseShellExecute = false;
        Process.Start(start);
    }
}
