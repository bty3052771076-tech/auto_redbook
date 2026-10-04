param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('init', 'start', 'stop', 'status')]
    [string]$Action,
    [switch]$Worker,
    [string]$RuntimeRoot = '',
    [string]$DataRoot = 'E:\AI\codex\AIHOT-data'
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $RuntimeRoot) { $RuntimeRoot = $project }
$repo = (Resolve-Path (Join-Path $project 'tools/AIHOT')).Path
$root = [IO.Path]::GetFullPath($DataRoot)
$pgBin = Join-Path $project 'tools/postgresql/18.6/pgsql/bin'
$pgData = Join-Path $root 'pgdata'
$credentialsPath = Join-Path $root 'connection.json'
$pidPath = Join-Path $root 'processes.json'
$logDir = Join-Path $root 'logs'
$env:TEMP = Join-Path $root 'tmp'
$env:TMP = $env:TEMP
$env:PGCLIENTENCODING = 'UTF8'

if ([IO.Path]::GetPathRoot($repo) -ne 'E:\' -or [IO.Path]::GetPathRoot($root) -ne 'E:\') {
    throw 'AIHOT checkout and data must remain on E:.'
}

function Get-Connection {
    if (-not (Test-Path -LiteralPath $credentialsPath)) { throw 'Run local-stack.ps1 init first.' }
    return Get-Content -LiteralPath $credentialsPath -Raw -Encoding utf8 | ConvertFrom-Json
}

function Set-DatabaseEnvironment {
    $connection = Get-Connection
    $password = [Uri]::EscapeDataString($connection.password)
    $env:DATABASE_URL = "postgres://$($connection.user):${password}@127.0.0.1:5434/$($connection.database)"
    $env:PGPASSWORD = $connection.password
}

function Start-Database {
    $status = & (Join-Path $pgBin 'pg_ctl.exe') status -D $pgData 2>&1
    if ($LASTEXITCODE -eq 0) { return }
    $process = Start-Process -FilePath (Join-Path $pgBin 'pg_ctl.exe') `
        -ArgumentList @('start', '-D', "`"$pgData`"", '-l', "`"$(Join-Path $logDir 'postgresql.log')`"", '-w', '-t', '30') `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'pg_ctl.out.log') `
        -RedirectStandardError (Join-Path $logDir 'pg_ctl.err.log') -PassThru
    if (-not $process.WaitForExit(35000)) {
        throw 'AIHOT PostgreSQL start timed out; inspect logs.'
    }
    $status = & (Join-Path $pgBin 'pg_ctl.exe') status -D $pgData 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'AIHOT PostgreSQL did not start; inspect E:\AI\codex\AIHOT-data\logs.'
    }
}

function Start-NodeService([string]$name, [string]$entry) {
    $stdout = Join-Path $logDir "$name.out.log"
    $stderr = Join-Path $logDir "$name.err.log"
    $process = Start-Process -FilePath (Get-Command node.exe).Source `
        -ArgumentList @('--env-file=.env', $entry) -WorkingDirectory $repo `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    return $process.Id
}

New-Item -ItemType Directory -Path $root, $logDir, $env:TEMP -Force | Out-Null

switch ($Action) {
    'init' {
        if ((Test-Path -LiteralPath $credentialsPath) -or (Test-Path -LiteralPath $pgData)) {
            throw 'AIHOT PostgreSQL already initialized; refusing to overwrite data.'
        }
        if (Get-NetTCPConnection -State Listen -LocalPort 5434 -ErrorAction SilentlyContinue) {
            throw 'Port 5434 is already occupied.'
        }
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $password = ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
        $pwFile = Join-Path $env:TEMP 'init-password.tmp'
        try {
            [IO.File]::WriteAllText($pwFile, $password, (New-Object Text.UTF8Encoding($false)))
            & (Join-Path $pgBin 'initdb.exe') -D $pgData -U aihot_admin --encoding=UTF8 --locale=C --auth=scram-sha-256 "--pwfile=$pwFile" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'initdb failed.' }
        } finally {
            if (Test-Path -LiteralPath $pwFile) { Remove-Item -LiteralPath $pwFile }
        }
        [IO.File]::AppendAllText((Join-Path $pgData 'postgresql.conf'), "`nlisten_addresses = '127.0.0.1'`nport = 5434`npassword_encryption = 'scram-sha-256'`n")
        [IO.File]::WriteAllText((Join-Path $pgData 'pg_hba.conf'), "host all aihot_admin 127.0.0.1/32 scram-sha-256`nhost all all 0.0.0.0/0 reject`nhost all all ::0/0 reject`n")
        $connection = @{ host = '127.0.0.1'; port = 5434; database = 'aihot_local'; user = 'aihot_admin'; password = $password }
        [IO.File]::WriteAllText($credentialsPath, ($connection | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
        Start-Database
        Set-DatabaseEnvironment
        & (Join-Path $pgBin 'createdb.exe') -h 127.0.0.1 -p 5434 -U aihot_admin aihot_local
        if ($LASTEXITCODE -ne 0) { throw 'Could not create aihot_local database.' }
        Write-Output 'AIHOT PostgreSQL initialized on 127.0.0.1:5434.'
    }
    'start' {
        if (Test-Path -LiteralPath $pidPath) {
            $record = Get-Content -LiteralPath $pidPath -Raw -Encoding utf8 | ConvertFrom-Json
            foreach ($name in @('api', 'web')) {
                $entry = @{ api = 'apps/api/src/main.ts'; web = 'apps/web/server.ts' }[$name]
                $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.$name)" -ErrorAction SilentlyContinue
                if (-not $process -or $process.Name -ne 'node.exe' -or $process.CommandLine -notlike "*$entry*") {
                    throw "Stale AIHOT $name process record; inspect and stop the local stack before restarting."
                }
            }
            if ($Worker) {
                $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.worker)" -ErrorAction SilentlyContinue
                if (-not $process -or $process.Name -ne 'node.exe' -or $process.CommandLine -notlike '*apps/worker/src/main.ts*') {
                    throw 'AIHOT is running without a worker; stop it before starting with -Worker.'
                }
            }
            Write-Output 'AIHOT local stack is already running.'
            break
        }
        Start-Database
        Set-DatabaseEnvironment
        $env:AIHOT_DATA_DIR = Join-Path $root 'files'
        $env:TEMP = Join-Path $root 'tmp'
        $env:TMP = $env:TEMP
        $processes = @{ api = Start-NodeService 'api' 'apps/api/src/main.ts'; web = Start-NodeService 'web' 'apps/web/server.ts' }
        if ($Worker) {
            if ((Get-Content -LiteralPath (Join-Path $repo '.env') -Raw -Encoding utf8) -match '(?m)^MODEL_CALLS_ENABLED=true\s*$') {
                $runtimeEnv = Join-Path $RuntimeRoot '.env.gui'
                $keyLine = Get-Content -LiteralPath $runtimeEnv -Encoding utf8 | Where-Object { $_ -match '^MINIMAX_TOKEN_PLAN_API_KEY=' } | Select-Object -First 1
                if (-not $keyLine) { throw 'MiniMax Token Plan key is not configured in the private runtime.' }
                $env:LLM_API_KEY = ($keyLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
            }
            $processes.worker = Start-NodeService 'worker' 'apps/worker/src/main.ts'
        }
        [IO.File]::WriteAllText($pidPath, ($processes | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
        Write-Output ("AIHOT started: api={0} web={1} worker={2}" -f $processes.api, $processes.web, $processes.worker)
    }
    'stop' {
        if (Test-Path -LiteralPath $pidPath) {
            $processes = Get-Content -LiteralPath $pidPath -Raw -Encoding utf8 | ConvertFrom-Json
            foreach ($name in @('worker', 'web', 'api')) {
                $id = $processes.$name
                if (-not $id) { continue }
                $process = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
                $entry = @{ worker = 'apps/worker/src/main.ts'; web = 'apps/web/server.ts'; api = 'apps/api/src/main.ts' }[$name]
                if ($process -and $process.Name -eq 'node.exe' -and $process.CommandLine -like "*$entry*") {
                    Stop-Process -Id $id -ErrorAction SilentlyContinue
                }
            }
            Remove-Item -LiteralPath $pidPath
        }
        if (Test-Path -LiteralPath $pgData) {
            $process = Start-Process -FilePath (Join-Path $pgBin 'pg_ctl.exe') `
                -ArgumentList @('stop', '-D', "`"$pgData`"", '-m', 'fast', '-w', '-t', '30') `
                -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'pg_ctl.out.log') `
                -RedirectStandardError (Join-Path $logDir 'pg_ctl.err.log') -PassThru
            if (-not $process.WaitForExit(35000)) {
                throw 'AIHOT PostgreSQL stop timed out; inspect logs.'
            }
            $status = & (Join-Path $pgBin 'pg_ctl.exe') status -D $pgData 2>&1
            if ($LASTEXITCODE -eq 0) {
                throw 'AIHOT PostgreSQL did not stop cleanly; inspect logs.'
            }
        }
        Write-Output 'AIHOT local stack stopped.'
    }
    'status' {
        $pg = 1
        if (Test-Path -LiteralPath $pgData) {
            $null = & (Join-Path $pgBin 'pg_ctl.exe') status -D $pgData 2>&1
            $pg = $LASTEXITCODE
        }
        Write-Output ("postgres_running={0} process_record={1}" -f ($pg -eq 0), (Test-Path -LiteralPath $pidPath))
    }
}
