$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Url = "https://creator.xiaohongshu.com/publish/publish?target=image"
$ProfileDir = Join-Path $Root "data\browser\chrome-profile"
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$ChromeCandidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe")
)

$Chrome = $ChromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($Chrome) {
    Start-Process -FilePath $Chrome -ArgumentList @(
        "--user-data-dir=$ProfileDir",
        "--profile-directory=Default",
        $Url
    )
} else {
    Start-Process $Url
}
