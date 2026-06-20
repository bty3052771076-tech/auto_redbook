$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $PSScriptRoot "AutoRedbookGuiLauncher.cs"
$Output = Join-Path $Root "AutoRedbookGUI-Launcher.exe"

if (-not (Test-Path -LiteralPath $Source)) {
    Write-Host "ERROR: launcher source not found: $Source"
    exit 1
}

$CscCandidates = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v3.5\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v3.5\csc.exe")
)

$Csc = $CscCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Csc) {
    Write-Host "ERROR: .NET Framework csc.exe not found."
    Write-Host "Fallback: use Start-GUI.cmd or run .\.venv\Scripts\python.exe -m apps.gui"
    exit 1
}

Write-Host "Building lightweight GUI launcher..."
& $Csc /nologo /target:winexe /out:$Output /reference:System.Windows.Forms.dll $Source

if (-not (Test-Path -LiteralPath $Output)) {
    Write-Host "ERROR: launcher build finished but exe not found: $Output"
    exit 1
}

Write-Host ""
Write-Host "OK: $Output"
Write-Host "This exe launches: .\.venv\Scripts\pythonw.exe -m apps.gui"
Write-Host "It does not bundle the GUI and does not install dependencies."
