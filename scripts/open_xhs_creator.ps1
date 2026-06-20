$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Url = "https://creator.xiaohongshu.com/publish/publish?target=image"
$ProfileDir = if ($env:XHS_CHROME_USER_DATA_DIR) {
    $env:XHS_CHROME_USER_DATA_DIR
} else {
    Join-Path $Root "data\browser\chrome-profile"
}
$ProfileName = if ($env:XHS_CHROME_PROFILE) { $env:XHS_CHROME_PROFILE } else { "Default" }
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$ChromeCandidates = @()
if ($env:XHS_CHROME_PATH) {
    $ChromeCandidates += $env:XHS_CHROME_PATH
}
if ($env:ProgramFiles) {
    $ChromeCandidates += (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe")
}
if (${env:ProgramFiles(x86)}) {
    $ChromeCandidates += (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe")
}
if ($env:LOCALAPPDATA) {
    $ChromeCandidates += (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
}

$Chrome = $ChromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($Chrome) {
    Start-Process -FilePath $Chrome -ArgumentList @(
        "--user-data-dir=$ProfileDir",
        "--profile-directory=$ProfileName",
        $Url
    )
} else {
    Start-Process $Url
}
