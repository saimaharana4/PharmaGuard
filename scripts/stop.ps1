$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& '.venv/Scripts/python.exe' infra/run_compose.py stop
if ($LASTEXITCODE) { throw 'Compose shutdown failed' }
Write-Host 'Containers stopped. Persistent database and index volumes are retained.'
