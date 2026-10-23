$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pgCtl = Join-Path $root '.tools/postgres/pgsql/bin/pg_ctl.exe'
$pgData = Join-Path $root '.data/postgres'
if (Test-Path -LiteralPath $pgCtl) { & $pgCtl stop -D $pgData -m fast -w }
$statePath = Join-Path $root '.data/native-processes.json'
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $process = Get-Process -Id $state.qdrant_pid -ErrorAction SilentlyContinue
    if ($process -and $process.Path -eq (Join-Path $root '.tools/qdrant/qdrant.exe')) {
        Stop-Process -Id $process.Id
    }
}
Write-Host 'Native dependencies stopped. Data files are retained.'
