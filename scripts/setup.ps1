$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
uv sync --frozen --extra embeddings
if ($LASTEXITCODE) { throw 'Python dependency installation failed' }
Push-Location apps/web
try {
    npm.cmd exec --yes --package=pnpm@12.14.0 -- pnpm install --frozen-lockfile
    if ($LASTEXITCODE) { throw 'Frontend dependency installation failed' }
} finally { Pop-Location }
if (-not (Test-Path -LiteralPath 'config/bootstrap.local.json') -and -not $env:APP_CONFIG_SECRET) {
    Write-Host 'Authenticate with gcloud auth login --update-adc and set APP_CONFIG_SECRET to a pinned configuration secret version.'
}
Write-Host 'No .env file was created. Credentials and model configuration load from Secret Manager.'
Write-Host 'Start containers: uv run python infra/run_compose.py up -d postgres qdrant'
Write-Host 'Migrate: uv run alembic upgrade head'
