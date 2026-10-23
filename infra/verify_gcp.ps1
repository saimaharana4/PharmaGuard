param([string]$ProjectId = 'project-bb13ecd8-9d67-408d-9a7', [string]$Region = 'asia-south1')
$ErrorActionPreference = 'Stop'
$gcloudCommand = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
$gcloudPath = if ($gcloudCommand) { $gcloudCommand.Source } else { Join-Path $env:LOCALAPPDATA 'Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' }
$commands = @(
    @('projects', 'describe', $ProjectId, '--format=json'),
    @('sql', 'instances', 'describe', 'pg-pharmaguard-hackathon', '--format=json'),
    @('sql', 'databases', 'describe', 'pharmaguard', '--instance=pg-pharmaguard-hackathon', '--format=json'),
    @('artifacts', 'repositories', 'describe', 'pharmaguard-hackathon', "--location=$Region", '--format=json'),
    @('storage', 'buckets', 'describe', "gs://pharmaguard-hackathon-$ProjectId", '--format=json'),
    @('iam', 'service-accounts', 'list', '--filter=email:pg-', '--format=json'),
    @('secrets', 'list', '--filter=name:pg-', '--format=json'),
    @('projects', 'get-iam-policy', $ProjectId, '--format=json')
)
$root = Split-Path $PSScriptRoot -Parent
$reportDirectory = Join-Path $root '.data/gcp-inventory'
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$index = 0
foreach ($command in $commands) {
    $index++
    $output = & $gcloudPath @command "--project=$ProjectId" --quiet
    if ($LASTEXITCODE) { throw "GCP verification failed at check $index" }
    $output | Set-Content -LiteralPath (Join-Path $reportDirectory "$index.json") -Encoding utf8
    Write-Host "Verified GCP inventory check $index"
}
Write-Host "Saved metadata only to $reportDirectory. No secret values were accessed."
