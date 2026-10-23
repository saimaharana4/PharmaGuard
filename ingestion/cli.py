"""Explicit ingestion stages; no long-running ingestion in HTTP handlers."""

import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import typer
from pharmaguard.config import load_settings
from pharmaguard.db import (
    ActiveDataset,
    Dataset,
    DatasetChunk,
    EvidenceChunk,
    FaersReport,
    IngestionRun,
    SourceDocument,
    session_factory,
)
from pharmaguard.observability import event
from pharmaguard.retrieval import EMBEDDING_INPUT_VERSION, MedCPT, qdrant_client
from sqlalchemy import delete, func, select

from ingestion.index import index_dataset
from ingestion.loader import load_documents, load_faers, seed_entities
from ingestion.sources import dailymed, faers, pubmed
from ingestion.storage import RawStore

app = typer.Typer(no_args_is_help=True)


def editable_dataset(session, dataset_id: str) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise ValueError("Unknown dataset ID")
    if dataset.status == "ready":
        raise ValueError("Published datasets are immutable; create a new staging dataset")
    return dataset


def run_stage(dataset_id: str, stage: str, operation) -> None:
    settings = load_settings()
    sessions = session_factory(settings)
    run_id = str(uuid4())
    started = perf_counter()
    event(
        "ingestion_stage_started",
        run_id=run_id,
        dataset_id=dataset_id,
        stage=stage,
        git_sha=settings.git_sha,
        status="running",
    )
    with sessions.begin() as session:
        dataset = editable_dataset(session, dataset_id)
        session.add(
            IngestionRun(
                id=run_id,
                dataset_id=dataset_id,
                stage=stage,
                status="running",
                started_at=datetime.now(UTC),
                details={},
            )
        )
    store = RawStore(settings)
    try:
        details = operation(settings, sessions, store, dataset)
        details.update(
            {
                "dataset_id": dataset_id,
                "stage": stage,
                "window_start": str(dataset.window_start),
                "as_of_date": str(dataset.as_of_date),
            }
        )
        uri = store.manifest(run_id, details)
        with sessions.begin() as session:
            run = session.get(IngestionRun, run_id)
            run.status, run.details, run.finished_at = (
                "completed",
                {**details, "manifest": uri},
                datetime.now(UTC),
            )
        typer.echo(json.dumps({"run_id": run_id, "status": "completed", "manifest": uri}))
        event(
            "ingestion_stage_completed",
            run_id=run_id,
            dataset_id=dataset_id,
            stage=stage,
            status="completed",
            manifest=uri,
            duration_ms=round((perf_counter() - started) * 1000),
        )
    except Exception as exc:
        event(
            "ingestion_stage_failed",
            run_id=run_id,
            dataset_id=dataset_id,
            stage=stage,
            status="failed",
            error_type=type(exc).__name__,
            duration_ms=round((perf_counter() - started) * 1000),
        )
        with sessions.begin() as session:
            run = session.get(IngestionRun, run_id)
            run.status, run.finished_at = "failed", datetime.now(UTC)
            run.details = {"error_type": type(exc).__name__, "stage": stage}
        # Do not print credential-bearing provider exceptions.
        typer.echo(f"Stage {stage} failed ({type(exc).__name__}); run_id={run_id}", err=True)
        raise typer.Exit(1) from None


@app.command()
def create() -> str:
    """Create a new staging dataset. Print its ID for subsequent stages."""
    settings = load_settings()
    dataset_id = str(uuid4())
    with session_factory(settings).begin() as session:
        session.add(
            Dataset(
                id=dataset_id,
                status="loading",
                window_start=settings.window_start,
                as_of_date=settings.effective_date,
                coverage={},
                model_revision="",
            )
        )
        seed_entities(session, settings.demo_drug, settings.demo_event)
    typer.echo(dataset_id)
    return dataset_id


@app.command("discover-faers")
def discover_faers(output: Path, availability: Path | None = None) -> None:
    """Save discovered source URLs; review this manifest before loading."""
    settings = load_settings()
    known = json.loads(availability.read_text()) if availability else {}
    releases = faers.discover(settings.window_start, settings.effective_date, known)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([r.model_dump(mode="json") for r in releases], indent=2))
    typer.echo(f"Discovered {len(releases)} FDA releases; inspect {output}")


@app.command("load-faers")
def load_faers_command(dataset_id: str, release_manifest: Path) -> None:
    """Load every report/drug/reaction from the selected completed FDA quarters."""
    releases = [
        faers.Release.model_validate(row) for row in json.loads(release_manifest.read_text())
    ]
    if not releases:
        raise typer.BadParameter("A non-empty reviewed release manifest is required")

    def operation(settings, sessions, store, dataset):
        assets, counts = [], {}
        expected = set()
        year, quarter = dataset.window_start.year, (dataset.window_start.month - 1) // 3 + 1
        while faers.quarter_end(year, quarter) <= dataset.as_of_date:
            expected.add(f"{year}Q{quarter}")
            quarter += 1
            if quarter == 5:
                quarter, year = 1, year + 1
        selected = {release.release for release in releases}
        if len(selected) != len(releases) or not selected <= expected:
            raise ValueError("Manifest has duplicate, future, or out-of-window quarters")
        for release in releases:
            if release.available_at > dataset.as_of_date:
                raise ValueError("A release was unavailable at the dataset cutoff")
            path, asset = store.download(release.url, "faers")
            assets.append({**asset, **release.model_dump(mode="json")})
            counts[release.release] = load_faers(sessions, dataset_id, path, release)
        missing = sorted(expected - selected)
        warnings = [
            "FAERS metrics use distinct latest-known cases and suspect-drug exposure (PS/SS).",
            "Unknown release dates use first verified download. "
            "Historical queries may have no eligible reports.",
        ]
        if missing:
            warnings.append("FAERS quarters absent from this dataset: " + ", ".join(missing))
        with sessions.begin() as session:
            current = editable_dataset(session, dataset_id)
            current.coverage = {
                **current.coverage,
                "releases": sorted(selected),
                "missing_quarters": missing,
                "background_complete": True,
                "release_availability": {r.release: str(r.available_at) for r in releases},
                "warnings": warnings,
            }
        return {"assets": assets, "counts": counts, "missing_quarters": missing}

    run_stage(dataset_id, "faers", operation)


@app.command("load-evidence")
def load_evidence(dataset_id: str, pubmed_limit: int = 40, label_limit: int = 3) -> None:
    """Download real PubMed abstracts and versioned DailyMed label sections."""
    if not 1 <= pubmed_limit <= 200 or not 1 <= label_limit <= 10:
        raise typer.BadParameter("Use 1–200 PubMed records and 1–10 labels")

    def operation(settings, sessions, store, dataset):
        articles, article_assets = pubmed.fetch(
            store,
            settings.demo_drug,
            settings.demo_event,
            dataset.window_start,
            dataset.as_of_date,
            pubmed_limit,
        )
        labels, label_assets = dailymed.fetch(
            store, settings.demo_drug, dataset.window_start, dataset.as_of_date, label_limit
        )
        documents = articles + labels
        if not articles or not labels:
            raise ValueError("Both PubMed and DailyMed evidence are required")
        with sessions.begin() as session:
            editable_dataset(session, dataset_id)
            session.execute(delete(DatasetChunk).where(DatasetChunk.dataset_id == dataset_id))
            count = load_documents(
                session, dataset_id, documents, settings.demo_drug, settings.demo_event
            )
        return {
            "assets": article_assets + label_assets,
            "documents": len(documents),
            "chunks": count,
        }

    run_stage(dataset_id, "evidence", operation)


@app.command("index")
def index_command(dataset_id: str) -> None:
    """Build/rebuild only this staging dataset's Qdrant collection."""

    def operation(settings, sessions, store, dataset):
        with closing(qdrant_client(settings)) as client:
            count = index_dataset(
                sessions, settings, client, MedCPT(settings), dataset_id, rebuild=True
            )
        with sessions.begin() as session:
            current = editable_dataset(session, dataset_id)
            current.model_revision = settings.embedding_document_revision
        return {
            "indexed_chunks": count,
            "model_revision": settings.embedding_document_revision,
            "embedding_input_version": EMBEDDING_INPUT_VERSION,
        }

    run_stage(dataset_id, "index", operation)


@app.command()
def publish(dataset_id: str) -> None:
    """Atomically activate a complete dataset; preserves the old dataset for rollback."""
    settings = load_settings()
    sessions = session_factory(settings)
    with sessions.begin() as session:
        dataset = editable_dataset(session, dataset_id)
        for stage in ["faers", "evidence", "index"]:
            latest = session.scalar(
                select(IngestionRun)
                .where(
                    IngestionRun.dataset_id == dataset_id,
                    IngestionRun.stage == stage,
                )
                .order_by(IngestionRun.started_at.desc())
                .limit(1)
            )
            if not latest or latest.status != "completed":
                raise typer.BadParameter(
                    f"Stage {stage} must finish successfully before publication"
                )
            if stage == "index" and latest.details.get("embedding_input_version") != (
                EMBEDDING_INPUT_VERSION
            ):
                raise typer.BadParameter(
                    "The index input version changed; rebuild before publishing"
                )
        faers_count = session.scalar(
            select(func.count())
            .select_from(FaersReport)
            .where(FaersReport.dataset_id == dataset_id)
        )
        chunk_count = session.scalar(
            select(func.count())
            .select_from(DatasetChunk)
            .where(DatasetChunk.dataset_id == dataset_id)
        )
        if not faers_count or not chunk_count:
            raise typer.BadParameter("A dataset must contain real reports and evidence")
        from pharmaguard.retrieval import collection_name

        with closing(qdrant_client(settings)) as client:
            if client.count(collection_name(settings, dataset_id), exact=True).count != chunk_count:
                raise typer.BadParameter("Index membership does not match canonical evidence")
        dataset.status = "ready"
        source_coverage = {}
        for source, documents, first, last, available_first, available_last in session.execute(
            select(
                SourceDocument.source_type,
                func.count(func.distinct(SourceDocument.id)),
                func.min(SourceDocument.source_date),
                func.max(SourceDocument.source_date),
                func.min(SourceDocument.available_at),
                func.max(SourceDocument.available_at),
            )
            .join(EvidenceChunk, EvidenceChunk.document_id == SourceDocument.id)
            .join(DatasetChunk, DatasetChunk.chunk_id == EvidenceChunk.id)
            .where(DatasetChunk.dataset_id == dataset_id)
            .group_by(SourceDocument.source_type)
        ):
            source_coverage[source] = {
                "documents": documents,
                "first_source_date": str(first),
                "last_source_date": str(last),
                "first_available_date": str(available_first),
                "last_available_date": str(available_last),
                "scope": "bounded subset",
            }
        warnings = [
            warning.replace(
                "Unavailable completed quarters:", "FAERS quarters absent from this dataset:"
            )
            for warning in dataset.coverage.get("warnings", [])
        ]
        for source, coverage in source_coverage.items():
            warnings.append(
                f"{source}: {coverage['documents']} document versions dated "
                f"{coverage['first_source_date']} to {coverage['last_source_date']}; "
                "a bounded subset, not complete literature or label history."
            )
        dataset.coverage = {
            **dataset.coverage,
            "evidence_sources": source_coverage,
            "warnings": list(dict.fromkeys(warnings)),
        }
        active = session.get(ActiveDataset, 1)
        if active:
            active.dataset_id = dataset_id
        else:
            session.add(ActiveDataset(id=1, dataset_id=dataset_id))
    typer.echo(f"Published dataset {dataset_id}")


@app.command()
def status() -> None:
    """Show non-secret ingestion state."""
    with session_factory(load_settings())() as session:
        for dataset in session.scalars(select(Dataset)):
            typer.echo(
                json.dumps(
                    {
                        "dataset_id": dataset.id,
                        "status": dataset.status,
                        "coverage": dataset.coverage,
                    }
                )
            )


@app.command("run")
def full_run(
    release_manifest: str = typer.Option(..., envvar="FAERS_RELEASE_MANIFEST"),
    dataset_id: str | None = typer.Option(None),
    recover_interrupted: bool = typer.Option(False),
) -> None:
    """Run all stages from a reviewed local/GCS release manifest; supports staging resume."""
    settings = load_settings()
    resuming = dataset_id is not None
    dataset_id = dataset_id or create()
    if release_manifest.startswith("gs://"):
        from urllib.parse import urlparse

        from google.cloud import storage

        parsed = urlparse(release_manifest)
        manifest_path = settings.raw_directory / "release-manifests" / f"{dataset_id}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        storage.Client(project=settings.gcp_project_id).bucket(parsed.netloc).blob(
            parsed.path.lstrip("/")
        ).download_to_filename(str(manifest_path))
    else:
        manifest_path = Path(release_manifest)
    if not manifest_path.is_file():
        raise typer.BadParameter("The reviewed release manifest is missing")
    reuse_faers = False
    if resuming:
        with session_factory(settings).begin() as session:
            editable_dataset(session, dataset_id)
            interrupted = list(
                session.scalars(
                    select(IngestionRun).where(
                        IngestionRun.dataset_id == dataset_id, IngestionRun.status == "running"
                    )
                )
            )
            if interrupted and not recover_interrupted:
                raise typer.BadParameter("Stop the old execution, then use --recover-interrupted")
            for previous in interrupted:
                previous.status = "failed"
                previous.finished_at = datetime.now(UTC)
                previous.details = {"error_type": "InterruptedExecution", "stage": previous.stage}
            latest = session.scalar(
                select(IngestionRun)
                .where(IngestionRun.dataset_id == dataset_id, IngestionRun.stage == "faers")
                .order_by(IngestionRun.started_at.desc())
                .limit(1)
            )
            if latest and latest.status == "completed":
                expected = [
                    faers.Release.model_validate(row).model_dump(mode="json")
                    for row in json.loads(manifest_path.read_text())
                ]
                loaded = [
                    {key: asset[key] for key in faers.Release.model_fields}
                    for asset in latest.details["assets"]
                ]
                if sorted(expected, key=lambda x: x["release"]) != sorted(
                    loaded, key=lambda x: x["release"]
                ):
                    raise typer.BadParameter("Resume manifest differs from completed FAERS loading")
                reuse_faers = True
    if reuse_faers:
        typer.echo("Reusing completed FAERS stage with the identical reviewed release manifest")
    else:
        load_faers_command(dataset_id, manifest_path)
    load_evidence(dataset_id)
    index_command(dataset_id)
    publish(dataset_id)


if __name__ == "__main__":
    app()
