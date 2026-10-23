# Optional Windows development alternative when Docker/WSL is unavailable.
# Expects the official PostgreSQL and Qdrant binaries in ignored .tools/.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$pgBin = Join-Path $root '.tools/postgres/pgsql/bin'
$qdrantExe = Join-Path $root '.tools/qdrant/qdrant.exe'
if (-not (Test-Path -LiteralPath (Join-Path $pgBin 'initdb.exe')) -or -not (Test-Path -LiteralPath $qdrantExe)) {
    throw 'Native binaries are missing. Use Docker Compose, or install the official binaries listed in docs/setup.md.'
}
$dataDirectory = Join-Path $root '.data/postgres'
$logDirectory = Join-Path $root '.logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $dataDirectory 'PG_VERSION'))) {
    & '.venv/Scripts/python.exe' infra/init_native_db.py
    if ($LASTEXITCODE) { throw 'PostgreSQL initialization failed' }
}
& (Join-Path $pgBin 'pg_ctl.exe') status -D $dataDirectory *> $null
if ($LASTEXITCODE -ne 0) {
    & (Join-Path $pgBin 'pg_ctl.exe') start -D $dataDirectory -l (Join-Path $logDirectory 'postgres.log') -o '-p 5432 -h 127.0.0.1' -w
    if ($LASTEXITCODE) { throw 'PostgreSQL startup failed' }
}
$config = Join-Path $root '.data/qdrant.yaml'
$storage = (Join-Path $root '.data/qdrant-storage').Replace('\', '/')
@"
storage:
  storage_path: "$storage"
service:
  host: "127.0.0.1"
  enable_cors: false
telemetry_disabled: true
"@ | Set-Content -LiteralPath $config -Encoding utf8
$existing = Get-NetTCPConnection -LocalPort 6333 -State Listen -ErrorAction SilentlyContinue
if (-not $existing) {
    $process = Start-Process -FilePath $qdrantExe -ArgumentList @('--config-path', "`"$config`"", '--disable-telemetry') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'qdrant.log') -RedirectStandardError (Join-Path $logDirectory 'qdrant-error.log')
    @{qdrant_pid = $process.Id} | ConvertTo-Json | Set-Content -LiteralPath '.data/native-processes.json'
}
& '.venv/Scripts/python.exe' scripts/create_local_db.py
if ($LASTEXITCODE) { throw 'Database creation failed' }
