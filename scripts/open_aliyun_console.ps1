$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Url = "https://bailian.console.aliyun.com/cn-beijing/?tab=costing-balance"
$ProfileDir = if ($env:ALIYUN_CONSOLE_USER_DATA_DIR) {
    $env:ALIYUN_CONSOLE_USER_DATA_DIR
} else {
    Join-Path $Root "data\browser\aliyun-console-profile"
}
$ProfileName = if ($env:ALIYUN_CHROME_PROFILE) {
    $env:ALIYUN_CHROME_PROFILE
} else {
    "Default"
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$ChromeCandidates = @()
if ($env:ALIYUN_CHROME_PATH) {
    $ChromeCandidates += $env:ALIYUN_CHROME_PATH
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

$Chrome = $ChromeCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Select-Object -First 1

if (-not $Chrome) {
    throw "Google Chrome not found. Set ALIYUN_CHROME_PATH to the project browser executable."
}

Start-Process -FilePath $Chrome -WindowStyle Normal -ArgumentList @(
    "--user-data-dir=$ProfileDir",
    "--profile-directory=$ProfileName",
    "--no-first-run",
    "--no-default-browser-check",
    "--new-window",
    $Url
)

Write-Host "Aliyun console profile opened: $ProfileDir"
