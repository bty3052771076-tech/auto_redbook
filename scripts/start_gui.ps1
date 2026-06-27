$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -lt 6) {
    $PSDefaultParameterValues["Invoke-WebRequest:UseBasicParsing"] = $true
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (Test-Path -LiteralPath $Pythonw) {
    Start-Process -FilePath $Pythonw -ArgumentList @("-m", "apps.gui") -WorkingDirectory $Root -WindowStyle Hidden
    exit 0
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

& $Python -m apps.gui
