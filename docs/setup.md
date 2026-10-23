# Setup and ingestion

## Configuration

`scripts/setup.ps1` installs dependencies without creating an environment file. Credentials
and model settings load from pinned Secret Manager versions. Local and Cloud SQL passwords
are held in separate secrets.
Configuration is centralized in `pharmaguard.config.Settings`; The typed settings module defines the inputs.
Python and frontend dependency versions are resolved in `uv.lock` and `apps/web/pnpm-lock.yaml`.
PyTorch uses CPU wheels, avoiding CUDA dependencies on Cloud Run.

The web application proxies only the four known API endpoints. `API_INTERNAL_URL` is server-only
runtime configuration; credentials never belong in public Next.js environment variables.

## Real-data stages

```powershell
$dataset = uv run pharmaguard-ingest create
uv run pharmaguard-ingest discover-faers .data/releases.json
uv run pharmaguard-ingest load-faers $dataset .data/releases.json
uv run pharmaguard-ingest load-evidence $dataset --pubmed-limit 40 --label-limit 3
uv run pharmaguard-ingest index $dataset
uv run pharmaguard-ingest publish $dataset
uv run pharmaguard-ingest status
```

The equivalent single command is `pharmaguard-ingest run --release-manifest .data/releases.json`.
Pass `--dataset-id` to resume an unpublished dataset. Published datasets cannot be edited by
ingestion. Repeated upserts preserve natural identities; failed runs record their stage and
exception type without serializing credential-bearing exceptions.

The discovery adapter uses the FDA release page, with an official openFDA manifest fallback
when that page is unavailable. The fallback verifies the quarterly ASCII ZIP assets with
HEAD requests. Reviewed publication dates can be supplied as a JSON map to
`discover-faers --availability FILE`. Otherwise verified object Last-Modified is a conservative
availability bound, or first retrieval is used when that metadata is absent. Quarter end is
never substituted for publication date.

Source files are streamed, checksummed, and stored under content-addressed paths. Every
completed stage writes a manifest. Malformed input fails explicitly. `background_complete`
means all report rows from the selected releases were loaded; it does not mean an unavailable
quarter has been filled or the entire FDA history was loaded. Missing quarters remain visible.

PubMed and DailyMed are a bounded source subset. Partial publication dates are conservatively
resolved to the end of their known month/year. PubMed availability also checks database history.
DailyMed downloads version-specific archived SPLs. Current label text is never substituted
for an unavailable historical version. Source polarity defaults to neutral `context`.

Each staging dataset gets its own Qdrant collection. Publishing changes the active dataset
pointer in PostgreSQL only after successful source stages and canonical/index count agreement.
Old datasets and collections remain available for investigation and rollback.

## Google authentication

```powershell
gcloud.cmd auth login --update-adc
gcloud.cmd auth application-default set-quota-project YOUR_PROJECT
powershell.exe -NoProfile -ExecutionPolicy Bypass -File infra/verify_gcp.ps1
```

For local access to the managed Qdrant cluster without saving its key, set:

```text
QDRANT_URL=https://YOUR_CLUSTER
QDRANT_SECRET_VERSION=projects/PROJECT_NUMBER/secrets/pg-qdrant-api-key/versions/1
```

The client accesses that pinned secret with ADC and retains the key in memory. Cloud Run instead
receives a pinned configuration resource reference and fetches secret values in memory.

## Native Windows fallback

Docker Compose is the intended reproducible local environment. Docker Desktop may require WSL,
Windows virtualization features, and a restart; the setup scripts do not restart the computer.

For PostgreSQL-only native development, official binaries are available from
[EDB](https://www.enterprisedb.com/download-postgresql-binaries). The optional scripts expect
PostgreSQL under `.tools/postgres/pgsql` and the official
[Qdrant Windows release](https://github.com/qdrant/qdrant/releases/tag/v1.19.0) under `.tools/qdrant`.
`scripts/start-native-deps.ps1` initializes a separate local database with the local database password fetched from Secret Manager;
`scripts/stop-native-deps.ps1` stops it without deleting data.

The native Windows Qdrant build can fail on deeply nested payload-index paths. Use Linux Qdrant
in Docker or the configured managed cluster rather than disabling payload indexes to conceal
that failure. Passing managed-cluster integration checks does not validate the Windows build.


## Inspect Cloud SQL from Windows

Use the signed Google Cloud SQL Auth Proxy with ADC on a loopback-only port. Supply the
pinned ingestion or runtime configuration reference as `APP_CONFIG_SECRET`, set
`DB_USE_TCP=true`, `DB_HOST=127.0.0.1`, and `DB_PORT` to the proxy port. This explicit transport
switch overrides the Cloud Run Unix socket without copying passwords into files or commands.
`OMP_NUM_THREADS=2`, `MKL_NUM_THREADS=2`, and `HF_HUB_OFFLINE=1` avoid CPU oversubscription and
runtime model downloads after the pinned models are cached.

Current PubMed XML is eligible only on or after its documented record revision date, not
merely its original publication or indexing date. Missing revision dates use first verified
retrieval conservatively. DailyMed uses archived SPL versions and their publication dates.


The Compose launcher accepts either an `APP_CONFIG_SECRET` resource reference or the
ignored `config/bootstrap.local.json` pointer. Neither contains a credential value.
It derives local host ports, database name, and collection namespace from that secret.
The container uses PostgreSQL's internal port 5432; host ports can differ. The web
container waits for API health, including optional model initialization. Shutdown
retains both persistent volumes.
