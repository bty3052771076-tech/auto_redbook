$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([IO.Path]::GetPathRoot($repoRoot) -ne 'E:\') {
    throw "This test must run from the E: workspace; found $repoRoot"
}

$testRoot = Join-Path $repoRoot ("data/tmp/postgresql-manage-test-{0}" -f [guid]::NewGuid().ToString('N'))
$manageRoot = Join-Path $testRoot 'data/runtime/postgresql'
$binRoot = Join-Path $manageRoot '18.6/pgsql/bin'
$dataRoot = Join-Path $testRoot 'data/knowledge/postgresql-local/pgdata'
$logRoot = Join-Path $testRoot 'data/logs/postgresql'
$fakeRoot = Join-Path $testRoot 'fake-pg-ctl'
$manageScript = Join-Path $manageRoot 'manage.ps1'
$fakeExecutable = Join-Path $binRoot 'pg_ctl.exe'
$stateFile = Join-Path $dataRoot 'FAKE_RUNNING'
$serverPidFile = Join-Path $fakeRoot 'server.pid'
$visibilityFile = Join-Path $fakeRoot 'start-window-visible.txt'

function Invoke-ManageAction {
    param(
        [Parameter(Mandatory = $true)][string]$Action,
        [int]$TimeoutSeconds = 8
    )

    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = Join-Path $PSHOME 'powershell.exe'
    $startInfo.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" {1}' -f $manageScript, $Action
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    $timer = [Diagnostics.Stopwatch]::StartNew()
    if (!$process.Start()) { throw "Could not start isolated manage.ps1 action '$Action'." }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $finished = $process.WaitForExit($TimeoutSeconds * 1000)
    if (!$finished) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F *> $null
        $null = $process.WaitForExit(5000)
    }
    $timer.Stop()

    [pscustomobject]@{
        Action = $Action
        ExitCode = if ($finished) { $process.ExitCode } else { $null }
        TimedOut = !$finished
        Elapsed = $timer.Elapsed
        StdOut = $stdoutTask.Result
        StdErr = $stderrTask.Result
    }
}

$fakeSource = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

public static class FakePgCtl {
    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    private static string ArgAfter(string[] args, string name) {
        for (int i = 0; i + 1 < args.Length; i++) {
            if (args[i] == name) return args[i + 1].Trim('"');
        }
        return null;
    }

    public static int Main(string[] args) {
        string root = Environment.GetEnvironmentVariable("FAKE_PGCTL_ROOT");
        string state = ArgAfter(args, "-D");
        if (args.Length > 0 && args[0] == "--server") {
            string marker = args[1];
            File.WriteAllText(args[2], Process.GetCurrentProcess().Id.ToString());
            while (File.Exists(marker)) Thread.Sleep(50);
            return 0;
        }

        string action = args.Length == 0 ? "" : args[0];
        if (action == "status") return File.Exists(Path.Combine(state, "FAKE_RUNNING")) ? 0 : 3;
        if (action == "start") {
            if (Environment.GetEnvironmentVariable("FAKE_PGCTL_FAIL_START") == "1") {
                string log = ArgAfter(args, "-l");
                if (!String.IsNullOrEmpty(log)) {
                    Directory.CreateDirectory(Path.GetDirectoryName(log));
                    File.WriteAllText(log, "simulated startup failure");
                }
                return 17;
            }

            string marker = Path.Combine(state, "FAKE_RUNNING");
            File.WriteAllText(marker, "running");
            IntPtr window = GetConsoleWindow();
            bool visible = window != IntPtr.Zero && IsWindowVisible(window);
            File.WriteAllText(Path.Combine(root, "start-window-visible.txt"), visible.ToString());

            ProcessStartInfo child = new ProcessStartInfo();
            child.FileName = Process.GetCurrentProcess().MainModule.FileName;
            child.Arguments = "--server \"" + marker + "\" \"" + Path.Combine(root, "server.pid") + "\"";
            child.UseShellExecute = false;
            child.CreateNoWindow = true;
            Process.Start(child);
            Thread.Sleep(300);
            return 0;
        }

        if (action == "stop") {
            Thread.Sleep(1300);
            string marker = Path.Combine(state, "FAKE_RUNNING");
            if (File.Exists(marker)) File.Delete(marker);
            return 0;
        }
        return 2;
    }
}
'@

try {
    New-Item -ItemType Directory -Path $binRoot, $dataRoot, $logRoot, $fakeRoot -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $dataRoot 'PG_VERSION') -Value '18' | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot 'data/runtime/postgresql/manage.ps1') -Destination $manageScript
    Add-Type -TypeDefinition $fakeSource -Language CSharp -OutputType ConsoleApplication -OutputAssembly $fakeExecutable
    $env:FAKE_PGCTL_ROOT = $fakeRoot

    $start = Invoke-ManageAction -Action 'start'
    if ($start.TimedOut) {
        throw 'Expected start to return when the isolated service is ready; it waited on the fake pg_ctl child process.'
    }
    if ($start.ExitCode -ne 0) {
        throw "Expected start exit 0, got $($start.ExitCode). stdout=$($start.StdOut) stderr=$($start.StdErr)"
    }
    if (!(Test-Path -LiteralPath $stateFile)) { throw 'start returned before the isolated service became ready.' }
    if (!(Test-Path -LiteralPath $visibilityFile) -or (Get-Content -Raw $visibilityFile).Trim() -ne 'False') {
        throw 'The isolated pg_ctl start process was not confirmed hidden.'
    }

    $stop = Invoke-ManageAction -Action 'stop'
    if ($stop.TimedOut -or $stop.ExitCode -ne 0) {
        throw "Expected stop to complete successfully; exit=$($stop.ExitCode) timedOut=$($stop.TimedOut). stdout=$($stop.StdOut) stderr=$($stop.StdErr)"
    }
    if (Test-Path -LiteralPath $stateFile) { throw 'stop returned before the isolated service stopped.' }
    if ($stop.Elapsed.TotalMilliseconds -lt 1000) { throw 'stop did not wait for the simulated service shutdown.' }

    $env:FAKE_PGCTL_FAIL_START = '1'
    $failure = Invoke-ManageAction -Action 'start'
    Remove-Item Env:\FAKE_PGCTL_FAIL_START -ErrorAction SilentlyContinue
    $failureText = $failure.StdOut + $failure.StdErr
    if ($failure.TimedOut -or $failure.ExitCode -eq 0) {
        throw "Expected startup failure to return nonzero promptly; exit=$($failure.ExitCode) timedOut=$($failure.TimedOut). $failureText"
    }
    $expectedLog = Join-Path $testRoot 'data/logs/postgresql/bootstrap.log'
    $normalizedFailureText = [regex]::Replace($failureText, '\s+', '')
    $normalizedExpectedLog = [regex]::Replace($expectedLog, '\s+', '')
    if (!$normalizedFailureText.Contains($normalizedExpectedLog)) {
        throw "Startup failure did not direct the operator to the log '$expectedLog'. Output: $failureText"
    }

    Write-Host ("PASS: isolated start returned in {0:N0} ms after readiness." -f $start.Elapsed.TotalMilliseconds)
    Write-Host ("PASS: stop waited {0:N0} ms for service shutdown." -f $stop.Elapsed.TotalMilliseconds)
    Write-Host 'PASS: startup failures return nonzero, include the log path, and start is hidden.'
} finally {
    Remove-Item Env:\FAKE_PGCTL_FAIL_START -ErrorAction SilentlyContinue
    if ($env:FAKE_PGCTL_ROOT) { Remove-Item Env:\FAKE_PGCTL_ROOT -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $stateFile) { Remove-Item -LiteralPath $stateFile -Force }
    if (Test-Path -LiteralPath $serverPidFile) {
        $serverPid = 0
        if ([int]::TryParse((Get-Content -Raw $serverPidFile).Trim(), [ref]$serverPid)) {
            $server = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
            if ($server) { Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue }
        }
    }
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
