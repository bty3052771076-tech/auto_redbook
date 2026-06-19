$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $root ".venv\\Scripts\\python.exe"
$env:PIP_CACHE_DIR = Join-Path $root ".pip-cache"

if (!(Test-Path $venvPy)) {
  Write-Host "ERROR: venv python not found: $venvPy"
  Write-Host "Create venv first: python -m venv .venv"
  exit 1
}

Write-Host "[1/3] Ensure PyInstaller installed..."
& $venvPy -m pip install -q --upgrade pip pyinstaller

Write-Host "[2/3] Build exe (onefile, windowed)..."
Push-Location $root
try {
  & $venvPy -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoRedbookGUI "apps\\gui.py"
} finally {
  Pop-Location
}

$distExe = Join-Path $root "dist\\AutoRedbookGUI.exe"
if (!(Test-Path $distExe)) {
  Write-Host "ERROR: build succeeded but exe not found: $distExe"
  exit 1
}

Write-Host "[3/3] Copy to project root for quick launch..."
$rootExe = Join-Path $root "AutoRedbookGUI.exe"
Copy-Item -Force $distExe $rootExe

Write-Host ""
Write-Host "OK: $rootExe"
Write-Host "Tip: place this exe in the repo root so it can find .venv and run the CLI."
