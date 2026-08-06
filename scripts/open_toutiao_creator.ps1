$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Url = "https://mp.toutiao.com/profile_v4/graphic/publish"
$ProfileDir = Join-Path $Root "data\browser\chrome-profile"
$ProfileName = "Default"
$CdpPort = if ($env:TOUTIAO_CDP_PORT) { [int]$env:TOUTIAO_CDP_PORT } else { 9223 }
if ($CdpPort -lt 1024 -or $CdpPort -gt 65535) {
    throw "TOUTIAO_CDP_PORT must be between 1024 and 65535."
}
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$ChromeCandidates = @(
    (Join-Path ${env:ProgramFiles} "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)
$Chrome = $ChromeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1

if (-not $Chrome) {
    throw "Google Chrome not found. Open $Url manually or install Chrome."
}

Start-Process -FilePath $Chrome -ArgumentList @(
    "--user-data-dir=$ProfileDir",
    "--profile-directory=$ProfileName",
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=$CdpPort",
    $Url
)

Write-Host "Toutiao profile opened: $ProfileDir (CDP 127.0.0.1:$CdpPort)"
