import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from time import perf_counter

import typer
from pharmaguard.config import Settings, load_settings
from pharmaguard.db import (
    Dataset,
    DatasetChunk,
    Entity,
    EvaluationCase,
    EvaluationRelevance,
    EvidenceChunk,
    FaersDeletion,
    FaersDrug,
    FaersReaction,
    FaersReport,
    IngestionRun,
    SourceDocument,
    session_factory,
)
from pharmaguard.retrieval import MedCPT, Retriever, qdrant_client
from pharmaguard.signals import signal_facts
from sqlalchemy import func, select
from sqlalchemy.schema import CreateIndex, DropIndex

from evaluation.core import compare, file_digest, read_snapshot, write_snapshot
from evaluation.schemas import BenchmarkCase, Snapshot
from ingestion.index import index_dataset
from ingestion.loader import bulk_insert, upsert

app = typer.Typer(no_args_is_help=True)


def record(row) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@app.command("import-cases")
def import_cases(dataset_id: str, path: Path) -> None:
    """Import independently reviewed labels. Never derive required IDs from current ranks."""
    cases = [BenchmarkCase.model_validate(row) for row in json.loads(path.read_text())]
    if not 10 <= len(cases) <= 20 or len({case.case_id for case in cases}) != len(cases):
        raise typer.BadParameter("Supply 10–20 distinct reviewed real-corpus cases")
    with session_factory(load_settings()).begin() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset or dataset.status != "ready":
            raise typer.BadParameter("Benchmark requires a published dataset")
        for case in cases:
            if (
                case.expected_facts.dataset_id != dataset_id
                or not dataset.window_start <= case.cutoff_date <= dataset.as_of_date
            ):
                raise typer.BadParameter("Case facts/window do not match the benchmark dataset")
            if not set(case.critical_evidence_ids) <= set(case.required_evidence_ids):
                raise typer.BadParameter(
                    "Critical IDs must be independently labeled required evidence"
                )
            for chunk_id in case.required_evidence_ids:
                member = session.get(DatasetChunk, (dataset_id, chunk_id))
                chunk = session.get(EvidenceChunk, chunk_id)
                doc = session.get(SourceDocument, chunk.document_id) if chunk else None
                if (
                    not member
                    or not doc
                    or not dataset.window_start <= doc.source_date <= case.cutoff_date
                    or doc.available_at > case.cutoff_date
                ):
                    raise typer.BadParameter(
                        "Required evidence is missing or temporally ineligible"
                    )
            if session.get(EvaluationCase, case.case_id):
                raise typer.BadParameter("Case IDs are immutable; create a new version instead")
            session.add(
                EvaluationCase(
                    id=case.case_id,
                    dataset_id=dataset_id,
                    question=case.question,
                    drug=case.drug,
                    event=case.event,
                    cutoff_date=case.cutoff_date,
                    expected_facts=case.expected_facts.model_dump(mode="json"),
                    reviewed_by=case.reviewed_by,
                    review_note=case.review_note,
                    expected_answer_points=case.expected_answer_points,
                )
            )
            session.flush()
            for chunk_id in case.required_evidence_ids:
                session.add(
                    EvaluationRelevance(
                        case_id=case.case_id,
                        chunk_id=chunk_id,
                        critical=chunk_id in case.critical_evidence_ids,
                    )
                )
    typer.echo(f"Imported {len(cases)} reviewed cases")


@app.command()
def export(dataset_id: str, version: str, output: Path) -> None:
    """Export canonical labels and a complete reproducible background/evidence snapshot."""
    settings = load_settings()
    with session_factory(settings)() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset or dataset.status != "ready":
            raise typer.BadParameter("A published dataset is required")
        memberships = list(
            session.scalars(
                select(DatasetChunk.chunk_id).where(DatasetChunk.dataset_id == dataset_id)
            )
        )
        chunk_rows = list(
            session.scalars(select(EvidenceChunk).where(EvidenceChunk.id.in_(memberships)))
        )
        doc_ids = {chunk.document_id for chunk in chunk_rows}
        cases = []
        for row in session.scalars(
            select(EvaluationCase)
            .where(EvaluationCase.dataset_id == dataset_id)
            .order_by(EvaluationCase.id)
        ):
            relevance = list(
                session.scalars(
                    select(EvaluationRelevance)
                    .where(EvaluationRelevance.case_id == row.id)
                    .order_by(EvaluationRelevance.chunk_id)
                )
            )
            cases.append(
                BenchmarkCase(
                    case_id=row.id,
                    question=row.question,
                    drug=row.drug,
                    event=row.event,
                    cutoff_date=row.cutoff_date,
                    expected_facts=row.expected_facts,
                    required_evidence_ids=[r.chunk_id for r in relevance],
                    critical_evidence_ids=[r.chunk_id for r in relevance if r.critical],
                    reviewed_by=row.reviewed_by,
                    review_note=row.review_note,
                    expected_answer_points=row.expected_answer_points,
                )
            )

        def all_rows(model, condition=None):
            statement = select(model).order_by(*model.__table__.primary_key.columns)
            if condition is not None:
                statement = statement.where(condition)
            return [record(row) for row in session.scalars(statement)]

        snapshot = Snapshot(
            dataset_id=dataset_id,
            dataset_version=version,
            dataset=record(dataset),
            query_model_revision=settings.embedding_query_revision,
            document_model_revision=dataset.model_revision,
            reranker_model_revision=settings.reranker_revision,
            entities=all_rows(Entity),
            documents=all_rows(SourceDocument, SourceDocument.id.in_(doc_ids)),
            chunks=sorted([record(row) for row in chunk_rows], key=lambda row: row["id"]),
            table_counts={
                model.__tablename__: session.scalar(
                    select(func.count()).select_from(model).where(model.dataset_id == dataset_id)
                )
                for model in [FaersReport, FaersDrug, FaersReaction, FaersDeletion]
            },
            ingestion_runs=all_rows(
                IngestionRun,
                (IngestionRun.dataset_id == dataset_id) & (IngestionRun.status == "completed"),
            ),
            cases=cases,
        )

        def stream_rows(model):
            statement = (
                select(model)
                .where(model.dataset_id == dataset_id)
                .order_by(*model.__table__.primary_key.columns)
            )
            for row in session.scalars(statement).yield_per(1000):
                yield record(row)

        digest = write_snapshot(
            output,
            snapshot,
            {
                model.__tablename__: stream_rows(model)
                for model in [FaersReport, FaersDrug, FaersReaction, FaersDeletion]
            },
        )
    typer.echo(json.dumps({"sha256": digest, "cases": len(cases), "output": str(output)}))


def restore(snapshot: Snapshot, settings: Settings, archive_path: Path) -> None:
    """Restore only into an empty evaluation database, never an existing live dataset."""
    from datetime import date, datetime

    from ingestion.loader import batches

    sessions = session_factory(settings)
    with sessions.begin() as session:
        if session.scalar(select(Dataset.id).limit(1)):
            raise ValueError("Evaluation restore requires an empty database")
        for model, rows in [
            (Dataset, [snapshot.dataset]),
            (Entity, snapshot.entities),
            (SourceDocument, snapshot.documents),
            (EvidenceChunk, snapshot.chunks),
            (IngestionRun, snapshot.ingestion_runs),
        ]:
            for batch in batches(rows, 500):
                converted = []
                for row in batch:
                    values = dict(row)
                    for col in model.__table__.columns:
                        if col.type.python_type in (date, datetime) and isinstance(
                            values.get(col.name), str
                        ):
                            values[col.name] = col.type.python_type.fromisoformat(values[col.name])
                    converted.append(values)
                upsert(session, model, converted)
        upsert(
            session,
            DatasetChunk,
            [
                {"dataset_id": snapshot.dataset_id, "chunk_id": chunk["id"]}
                for chunk in snapshot.chunks
            ],
        )
    postgres = sessions.kw["bind"].dialect.name == "postgresql"
    indexes = (
        [
            index
            for model in [FaersReport, FaersDrug, FaersReaction, FaersDeletion]
            for index in model.__table__.indexes
            if not index.unique
        ]
        if postgres
        else []
    )
    # Only empty disposable databases reach this point. Keep PK/FK enforcement; build
    # non-unique lookup indexes once after COPY instead of updating them millions of times.
    with sessions.begin() as session:
        for index in indexes:
            session.execute(DropIndex(index))
    with zipfile.ZipFile(archive_path) as archive:
        for model in [FaersReport, FaersDrug, FaersReaction, FaersDeletion]:
            count = 0
            table_started = perf_counter()
            typer.echo(
                json.dumps({"event": "evaluation_restore_started", "table": model.__tablename__})
            )
            with archive.open(model.__tablename__ + ".jsonl") as handle:
                for batch in batches((json.loads(line) for line in handle), 100000):
                    for row in batch:
                        if row["dataset_id"] != snapshot.dataset_id:
                            raise ValueError("Snapshot contains a different dataset")
                        if not postgres:
                            for column in model.__table__.columns:
                                if column.type.python_type is date:
                                    row[column.name] = date.fromisoformat(row[column.name])
                    with sessions.begin() as session:
                        if postgres:
                            from psycopg import sql

                            columns = list(batch[0])
                            statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
                                sql.Identifier(model.__tablename__),
                                sql.SQL(",").join(map(sql.Identifier, columns)),
                            )
                            connection = session.connection().connection.driver_connection
                            with connection.cursor().copy(statement) as copy:
                                for row in batch:
                                    copy.write_row(tuple(row[column] for column in columns))
                        else:
                            bulk_insert(session, model, batch)
                    count += len(batch)
            if count != snapshot.table_counts[model.__tablename__]:
                raise ValueError("Snapshot table count mismatch")
            typer.echo(
                json.dumps(
                    {
                        "event": "evaluation_restore_completed",
                        "table": model.__tablename__,
                        "rows": count,
                        "duration_seconds": round(perf_counter() - table_started, 3),
                    }
                )
            )
    with sessions.begin() as session:
        for index in indexes:
            session.execute(CreateIndex(index))


@app.command()
def run(
    snapshot_path: Path,
    output: Path = Path("evaluation/report.json"),
    restore_data: bool = False,
    expected_sha256: str | None = None,
    prepared_data: bool = False,
    embedding_inputs: Path | None = None,
    embedding_sha256: str | None = None,
    workers: int = 1,
) -> None:
    """Run the real retrieval and fact services; fail closed without a valid snapshot."""
    started = perf_counter()
    settings = load_settings()
    snapshot = read_snapshot(snapshot_path, expected_sha256)
    snapshot_sha256 = expected_sha256 or file_digest(snapshot_path)
    if not 1 <= workers <= 4:
        raise typer.BadParameter("Evaluation concurrency must be between one and four")
    if (
        snapshot.query_model_revision != settings.embedding_query_revision
        or snapshot.document_model_revision != settings.embedding_document_revision
        or snapshot.reranker_model_revision != settings.reranker_revision
    ):
        raise typer.BadParameter("Embedding revisions differ from the approved benchmark")
    if restore_data and prepared_data:
        raise typer.BadParameter("Choose fresh restore or verified prepared inputs, not both")
    if prepared_data:
        from evaluation.prepared import verify

        verify(snapshot, settings, expected_sha256 or file_digest(snapshot_path))
    if restore_data:
        # A local/CI restoration must never overwrite the live dataset's managed index.
        settings = settings.model_copy(update={"qdrant_collection": "pharmaguard_evaluation_v1"})
        restore(snapshot, settings, snapshot_path)
    inputs_ready = perf_counter()
    sessions = session_factory(settings)
    embedder = MedCPT(settings)
    article_inputs_enabled = False
    if embedding_inputs is not None:
        from evaluation.embedding_inputs import ArticleInputs

        if not embedding_sha256:
            raise typer.BadParameter("Prepared article inputs require an approved checksum")
        embedder = ArticleInputs(
            embedder,
            embedding_inputs,
            embedding_sha256,
            expected_sha256 or file_digest(snapshot_path),
        )
        article_inputs_enabled = embedder.enabled
    results = []
    retrieval_seconds = 0.0
    fact_seconds = 0.0
    indexing_started = perf_counter()
    with closing(qdrant_client(settings)) as client:
        if restore_data or prepared_data:
            settings = settings.model_copy(
                update={"qdrant_collection": "pharmaguard_evaluation_v1"}
            )
            index_dataset(sessions, settings, client, embedder, snapshot.dataset_id)
        indexing_seconds = perf_counter() - indexing_started
        retriever = Retriever(settings, client, embedder)
        fact_keys = list(dict.fromkeys((c.cutoff_date, c.drug, c.event) for c in snapshot.cases))

        def calculate_facts(key):
            with sessions() as session:
                dataset = session.get(Dataset, snapshot.dataset_id)
                if not dataset:
                    raise typer.BadParameter("Benchmark dataset is absent")
                return key, signal_facts(session, dataset, *key)

        fact_started = perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            facts_by_input = dict(executor.map(calculate_facts, fact_keys))
        fact_seconds = perf_counter() - fact_started
        model_started = perf_counter()
        if workers > 1:
            embedder.preload()
            from evaluation.embedding_inputs import ConcurrentEncoders

            retriever.embedder = ConcurrentEncoders(embedder)
        model_seconds = perf_counter() - model_started

        def evaluate_case(case):
            with sessions() as session:
                dataset = session.get(Dataset, snapshot.dataset_id)
                hits = retriever.search(
                    session, dataset, case.question, case.cutoff_date, case.drug, case.event
                )
                fact_key = (case.cutoff_date, case.drug, case.event)
                facts = facts_by_input[fact_key]
                result = compare(case, hits, facts)
                typer.echo(
                    json.dumps(
                        {
                            "event": "evaluation_case_completed",
                            "case_id": case.case_id,
                            "passed": result.passed,
                        }
                    )
                )
                return result

        retrieval_started = perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(evaluate_case, snapshot.cases))
        retrieval_seconds = perf_counter() - retrieval_started
    passed = all(result.passed for result in results)
    report = {
        "passed": passed,
        "git_sha": settings.git_sha,
        "dataset_id": snapshot.dataset_id,
        "dataset_version": snapshot.dataset_version,
        "snapshot_sha256": snapshot_sha256,
        "embedding_inputs_sha256": embedding_sha256,
        "query_model_revision": settings.embedding_query_revision,
        "document_model_revision": settings.embedding_document_revision,
        "reranker_model_revision": settings.reranker_revision,
        "reranker_precision": "float32",
        "retrieval": settings.retrieval().model_dump(),
        "cases": [result.model_dump(mode="json") for result in results],
        "timing_seconds": {
            "input_preparation": round(inputs_ready - started, 3),
            "indexing": round(indexing_seconds, 3),
            "retrieval": round(retrieval_seconds, 3),
            "facts": round(fact_seconds, 3),
            "model_startup": round(model_seconds, 3),
            "total": round(perf_counter() - started, 3),
        },
        "input_mode": "prepared" if prepared_data else "restored" if restore_data else "existing",
        "distinct_fact_inputs": len(facts_by_input),
        "article_inputs_compatible": article_inputs_enabled,
        "article_vectors_reused": getattr(embedder, "hits", 0),
        "workers": workers,
        "scope": "Deterministic retrieval, citation eligibility, temporal safety, and facts. "
        "Live LLM synthesis is checked separately.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    typer.echo(json.dumps({"passed": passed, "cases": len(results), "report": str(output)}))
    raise typer.Exit(0 if passed else 1)


@app.command("judge")
def judge_command(
    snapshot_path: Path, output: Path = Path(".data/evaluation/live-report.json")
) -> None:
    """Generate real answers and assess them with a separate LLM and reviewed reference points."""
    from evaluation.judge import run_judge

    raise typer.Exit(0 if run_judge(snapshot_path, output) else 1)


if __name__ == "__main__":
    app()
