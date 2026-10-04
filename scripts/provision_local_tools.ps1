param(
    [string]$ProjectRoot = '',
    [string]$WorldMonitorSource = 'E:\AI\codex\worldmonitor',
    [string]$RSSHubSource = 'E:\AI\tools\RSSHub',
    [string]$AIHOTSource = 'E:\AI\codex\AIHOT',
    [string]$OpenCodexSource = (Join-Path $env:APPDATA 'npm/node_modules/@bitkyc08/opencodex'),
    [string]$PostgreSQLSource = 'E:\AI\codex\redbook_runtime\data\runtime\postgresql\18.6\pgsql'
)
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Join-Path $PSScriptRoot '..' }
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([IO.Path]::GetPathRoot($root) -ne 'E:\') { throw 'Project must be on E:.' }
$tools = Join-Path $root 'tools'
New-Item -ItemType Directory -Path $tools -Force | Out-Null

function Copy-Tool([string]$Name, [string]$Source, [string]$RelativeTarget, [bool]$GitClone) {
    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\')
    $target = [IO.Path]::GetFullPath((Join-Path $tools $RelativeTarget)).TrimEnd('\')
    if (-not $target.StartsWith("$tools\", [StringComparison]::OrdinalIgnoreCase) -or
        $target -eq $sourceRoot -or $target.StartsWith("$sourceRoot\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe copy destination for $Name"
    }
    if ($GitClone -and -not (Test-Path -LiteralPath $target)) {
        & git clone --quiet --no-hardlinks -- $sourceRoot $target
        if ($LASTEXITCODE -ne 0) { throw "Local clone failed: $Name" }
    }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    $excluded = @('.git', '.pw-browsers', '.audit', '.agents', '.pytest_cache', '.venv', 'logs') |
        ForEach-Object { Join-Path $sourceRoot $_ }
    & robocopy $sourceRoot $target /E /XJ /R:1 /W:1 /NFL /NDL /NJH /NJS /NP `
        /XD $excluded __pycache__ `
        /XF '*.log' '*.pyc' '.local-smoke.png' | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Tool copy failed: $Name (robocopy=$LASTEXITCODE)" }

    # pnpm creates absolute NTFS Junctions; keep every dependency inside its copy.
    $queue = New-Object 'Collections.Generic.Stack[string]'
    $queue.Push($sourceRoot)
    $links = 0
    while ($queue.Count) {
        $directory = $queue.Pop()
        foreach ($entry in Get-ChildItem -LiteralPath $directory -Directory -Force) {
            if ($entry.FullName -in $excluded -or $entry.Name -eq '__pycache__') { continue }
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                $linkTarget = [IO.Path]::GetFullPath([string]$entry.Target[0]).TrimEnd('\')
                if (-not $linkTarget.StartsWith("$sourceRoot\", [StringComparison]::OrdinalIgnoreCase)) {
                    throw "External dependency link in $Name`: $($entry.FullName)"
                }
                $relative = $entry.FullName.Substring($sourceRoot.Length + 1)
                $newLink = Join-Path $target $relative
                $newTarget = Join-Path $target $linkTarget.Substring($sourceRoot.Length + 1)
                if (-not (Test-Path -LiteralPath $newTarget)) { throw "Missing copied link target: $relative" }
                if (Test-Path -LiteralPath $newLink) {
                    $existing = Get-Item -LiteralPath $newLink -Force
                    if (-not ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                        [IO.Path]::GetFullPath([string]$existing.Target[0]) -ne $newTarget) {
                        throw "Existing dependency differs; refusing to overwrite: $newLink"
                    }
                } else {
                    New-Item -ItemType Directory -Path (Split-Path -Parent $newLink) -Force | Out-Null
                    New-Item -ItemType Junction -Path $newLink -Target $newTarget | Out-Null
                }
                $links++
            } else { $queue.Push($entry.FullName) }
        }
    }
    $commit = ''
    if ($GitClone) {
        $commit = (& git -C $sourceRoot rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Could not record source revision: $Name" }
    }
    Write-Host "$Name copied; internal links=$links"
    return @{name=$Name; source=$sourceRoot; target=$target; commit=$commit; links=$links}
}

$rows = @(
    Copy-Tool 'worldmonitor' $WorldMonitorSource 'worldmonitor' $true
    Copy-Tool 'RSSHub' $RSSHubSource 'RSSHub' $true
    Copy-Tool 'AIHOT' $AIHOTSource 'AIHOT' $true
    Copy-Tool 'opencodex' $OpenCodexSource 'opencodex' $false
    Copy-Tool 'postgresql' $PostgreSQLSource 'postgresql/18.6/pgsql' $false
)
$manifest = @{version=1; copied_at=[DateTime]::UtcNow.ToString('o'); tools=$rows}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $tools 'manifest.local.json') -Encoding utf8
Write-Host 'Local tools ready. Original directories and data were retained.'
