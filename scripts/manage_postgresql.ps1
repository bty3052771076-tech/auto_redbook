param(
    [string]$RuntimeRoot = '',
    [ValidateSet('start', 'stop', 'status', 'sql', 'backup')][string]$Action = 'status',
    [ValidateSet('app', 'migration', 'admin')][string]$Role = 'app',
    [string]$Sql = 'SELECT current_database(), current_user, version();'
)
$ErrorActionPreference = 'Stop'
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $PSScriptRoot '..' }
$root = (Resolve-Path -LiteralPath $RuntimeRoot).Path
if ([IO.Path]::GetPathRoot($root) -ne 'E:\') { throw 'Expected E: deployment.' }
$bin = Join-Path (Join-Path $PSScriptRoot '..') 'tools/postgresql/18.6/pgsql/bin'
$private = Join-Path $root 'data/knowledge/postgresql-local'
$data = Join-Path $private 'pgdata'
$log = Join-Path $root 'data/logs/postgresql/bootstrap.log'
$env:TEMP = Join-Path $root 'data/tmp/postgresql'
$env:TMP = $env:TEMP
$env:PGCLIENTENCODING = 'UTF8'
$env:PGCONNECT_TIMEOUT = '5'
$OutputEncoding = New-Object Text.UTF8Encoding($false)
if (!(Test-Path "$data/PG_VERSION")) { throw 'PostgreSQL has not been initialized.' }

if ($Action -eq 'status') {
    & "$bin/pg_ctl.exe" status -D $data
    exit $LASTEXITCODE
}
if ($Action -in @('start', 'stop')) {
    & "$bin/pg_ctl.exe" status -D $data *> $null
    $running = $LASTEXITCODE -eq 0
    if (($Action -eq 'start' -and $running) -or ($Action -eq 'stop' -and !$running)) {
        Write-Host "PostgreSQL is already $(if ($running) {'running'} else {'stopped'})."
        exit 0
    }
    $arguments = @($Action, '-D', "`"$data`"", '-w', '-t', '30')
    if ($Action -eq 'start') { $arguments += @('-l', "`"$log`"") } else { $arguments += @('-m', 'fast') }
    try {
        $process = Start-Process -FilePath "$bin/pg_ctl.exe" -ArgumentList $arguments -WindowStyle Hidden -PassThru
    } catch {
        if ($Action -eq 'start') { throw "PostgreSQL start could not launch pg_ctl. Inspect $log. $($_.Exception.Message)" }
        throw "PostgreSQL stop could not launch pg_ctl. $($_.Exception.Message)"
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline) {
        & "$bin/pg_ctl.exe" status -D $data *> $null
        $serviceRunning = $LASTEXITCODE -eq 0

        if ($Action -eq 'start' -and $serviceRunning) {
            $connectionProbe = Get-Content -Raw -Encoding utf8 "$private/connection.json" | ConvertFrom-Json
            & "$bin/pg_isready.exe" -h $connectionProbe.host -p ([string]$connectionProbe.port) -t 2 *> $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host 'PostgreSQL start completed; the service accepts connections.'
                exit 0
            }
        }
        if ($Action -eq 'stop' -and !$serviceRunning) {
            Write-Host 'PostgreSQL stop completed; the service is stopped.'
            exit 0
        }

        $process.Refresh()
        if ($process.HasExited -and $process.ExitCode -ne 0) {
            if ($Action -eq 'start') { throw "PostgreSQL start failed with exit code $($process.ExitCode). Inspect $log" }
            throw "PostgreSQL stop failed with exit code $($process.ExitCode). Inspect $log"
        }
        Start-Sleep -Milliseconds 250
    }

    if (!$process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    if ($Action -eq 'start') { throw "PostgreSQL start timed out before the service became ready. Inspect $log" }
    throw 'PostgreSQL stop timed out before the service stopped.'
}
$connection = Get-Content -Raw -Encoding utf8 "$private/connection.json" | ConvertFrom-Json
$previousPassword = $env:PGPASSWORD
try {
    if ($Action -eq 'backup') { $Role = 'admin' }
    $user = $connection."${Role}_user"
    $env:PGPASSWORD = $connection."${Role}_password"
    $arguments = @('-h', $connection.host, '-p', [string]$connection.port, '-U', $user, '-d', $connection.database, '-w')
    if ($Action -eq 'sql') {
        $Sql | & "$bin/psql.exe" @arguments -X -v ON_ERROR_STOP=1
        if ($LASTEXITCODE -ne 0) { throw 'SQL failed.' }
    } else {
        $target = Join-Path $root ("data/knowledge/backups/postgresql/redbook_knowledge-{0}.dump" -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
        & "$bin/pg_dump.exe" @arguments -Fc -f $target
        if ($LASTEXITCODE -ne 0) { throw 'Backup failed; any partial dump must not be used.' }
        Write-Host "Backup created: $target"
    }
} finally {
    $env:PGPASSWORD = $previousPassword
    $connection = $null
}
