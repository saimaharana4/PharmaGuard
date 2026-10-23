"""Idempotent bounded-batch relational loading and stable content identities."""

import hashlib
import zipfile
from itertools import islice
from uuid import NAMESPACE_URL, uuid5

from pharmaguard.db import (
    Dataset,
    DatasetChunk,
    Entity,
    EvidenceChunk,
    FaersDeletion,
    FaersDrug,
    FaersReaction,
    FaersReport,
    SourceDocument,
)
from pharmaguard.signals import normalize
from sqlalchemy import select
from sqlalchemy.orm import Session

from ingestion.sources.faers import Release, report_date, rows


def stable_id(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, "pharmaguard:" + "\x1f".join(parts)))


def batches(items, size: int = 1000):
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def upsert(session: Session, model, values: list[dict], update: bool = False) -> int:
    if not values:
        return 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(model).values(values)
    primary = [col.name for col in model.__table__.primary_key.columns]
    if update:
        statement = statement.on_conflict_do_update(
            index_elements=primary,
            set_={
                col.name: getattr(statement.excluded, col.name)
                for col in model.__table__.columns
                if col.name not in primary
            },
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=primary)
    session.execute(statement)
    return len(values)


def bulk_insert(session: Session, model, values: list[dict]) -> int:
    """COPY into transaction-local staging, then enforce canonical keys and FKs."""
    if session.bind.dialect.name != "postgresql":
        return upsert(session, model, values)
    if not values:
        return 0
    from psycopg import sql

    connection = session.connection().connection.driver_connection
    columns = list(values[0])
    fields = sql.SQL(", ").join(map(sql.Identifier, columns))
    target = sql.Identifier(model.__tablename__)
    primary = sql.SQL(", ").join(
        sql.Identifier(column.name) for column in model.__table__.primary_key.columns
    )
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE TEMP TABLE pg_ingest_stage ON COMMIT DROP AS SELECT {} FROM {} WITH NO DATA"
            ).format(fields, target)
        )
        with cursor.copy(sql.SQL("COPY pg_ingest_stage ({}) FROM STDIN").format(fields)) as copy:
            for row in values:
                copy.write_row(tuple(row[column] for column in columns))
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} ({}) SELECT {} FROM pg_ingest_stage ON CONFLICT ({}) DO NOTHING"
            ).format(target, fields, fields, primary)
        )
    return len(values)


def load_faers(sessions, dataset_id: str, path, release: Release) -> dict:
    counts = {}
    for prefix, model, convert in [
        (
            "DEMO",
            FaersReport,
            lambda row: {
                "dataset_id": dataset_id,
                "primary_id": row["primaryid"],
                "case_id": row["caseid"],
                "case_version": int(row["caseversion"]),
                "received_at": report_date(row["fda_dt"]),
                "available_at": release.available_at,
                "release": release.release,
            },
        ),
        (
            "DRUG",
            FaersDrug,
            lambda row: {
                "dataset_id": dataset_id,
                "primary_id": row["primaryid"],
                "sequence": row["drug_seq"],
                "name": normalize(row.get("prod_ai") or row["drugname"]),
                "role": row["role_cod"],
            },
        ),
        (
            "REAC",
            FaersReaction,
            lambda row: {
                "dataset_id": dataset_id,
                "primary_id": row["primaryid"],
                "term": normalize(row["pt"]),
            },
        ),
    ]:
        count = 0
        for batch in batches((convert(row) for row in rows(path, prefix)), 10000):
            with sessions.begin() as session:
                count += bulk_insert(session, model, batch)
        counts[prefix.lower()] = count
    with zipfile.ZipFile(path) as archive:
        deletion_files = [
            name
            for name in archive.namelist()
            if name.rsplit("/", 1)[-1].upper().startswith("DELETE")
            and name.lower().endswith(".txt")
        ]
    counts["deleted_cases"] = 0
    if deletion_files:
        for batch in batches(
            (
                {
                    "dataset_id": dataset_id,
                    "case_id": row["caseid"],
                    "available_at": release.available_at,
                    "release": release.release,
                }
                for row in rows(path, "DELETE")
            ),
            10000,
        ):
            with sessions.begin() as session:
                counts["deleted_cases"] += bulk_insert(session, FaersDeletion, batch)
    return counts


def chunks(text: str, max_chars: int = 1200):
    """Bounded paragraphs/sentences, below the 512-token article encoder budget."""
    import re

    pieces = re.split(r"(?<=[.!?])\s+|\n\s*\n", text)
    current = ""
    for piece in pieces:
        for start in range(0, len(piece), max_chars):
            segment = piece[start : start + max_chars]
            if len(current) + len(segment) + 1 > max_chars and current:
                yield current.strip()
                current = ""
            current += " " + segment
    if current.strip():
        yield current.strip()


def load_documents(
    session: Session, dataset_id: str, documents: list[dict], drug: str, event: str
) -> int:
    count = 0
    for document in documents:
        text = document["text"]
        digest = hashlib.sha256(text.encode()).hexdigest()
        document_id = stable_id(
            document["source_type"], document["external_id"], document["version"], digest
        )
        existing = session.get(SourceDocument, document_id)
        if existing and existing.available_at != document["available_at"]:
            published_reference = session.scalar(
                select(Dataset.id)
                .join(DatasetChunk, DatasetChunk.dataset_id == Dataset.id)
                .join(EvidenceChunk, EvidenceChunk.id == DatasetChunk.chunk_id)
                .where(EvidenceChunk.document_id == document_id, Dataset.status == "ready")
                .limit(1)
            )
            if published_reference:
                raise ValueError("Published document availability is immutable")
            existing.available_at = document["available_at"]
        upsert(
            session,
            SourceDocument,
            [
                {
                    key: value
                    for key, value in {**document, "id": document_id}.items()
                    if key not in ["text", "locator"]
                }
            ],
        )
        for index, chunk in enumerate(chunks(text)):
            chunk_id = stable_id(document_id, str(index), chunk)
            upsert(
                session,
                EvidenceChunk,
                [
                    {
                        "id": chunk_id,
                        "document_id": document_id,
                        "text": chunk,
                        "locator": f"{document['locator']}#chunk-{index}",
                        "drug_id": drug,
                        "event_id": event,
                        "polarity": "context",
                    }
                ],
            )
            upsert(session, DatasetChunk, [{"dataset_id": dataset_id, "chunk_id": chunk_id}])
            count += 1
    return count


def seed_entities(session: Session, drug: str, event: str) -> None:
    # Reviewed aliases, not fuzzy model guesses or assumptions about causality.
    aliases = {
        "semaglutide": ["ozempic", "wegovy", "rybelsus"],
        "pancreatitis": ["pancreatitis acute", "acute pancreatitis"],
    }
    for kind, canonical in [("drug", drug), ("event", event)]:
        if not session.scalar(
            select(Entity).where(Entity.kind == kind, Entity.canonical == canonical)
        ):
            session.add(Entity(kind=kind, canonical=canonical, aliases=aliases.get(canonical, [])))
