"""Prepare immutable benchmark inputs, never cached evaluation outcomes."""

import argparse
import json
from pathlib import Path

from pharmaguard.config import Settings, load_settings
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
    session_factory,
)
from sqlalchemy import func, select, text

from evaluation.core import file_digest, read_snapshot
from evaluation.schemas import Snapshot

TABLES = [FaersReport, FaersDrug, FaersReaction, FaersDeletion]


def verify(snapshot: Snapshot, settings: Settings, checksum: str) -> None:
    """Fail closed if a seeded database is not the approved full-population input."""
    with session_factory(settings)() as session:
        stored = session.execute(text("SELECT snapshot_sha256 FROM evaluation_input")).scalar_one()
        if stored != checksum:
            raise ValueError("Prepared database does not match the approved snapshot")
        for model, expected in [
            (Dataset, [snapshot.dataset]),
            (Entity, snapshot.entities),
            (SourceDocument, snapshot.documents),
            (EvidenceChunk, snapshot.chunks),
        ]:
            actual = [
                {column.name: getattr(row, column.name) for column in model.__table__.columns}
                for row in session.scalars(select(model))
            ]

            def canonical(rows):
                return sorted(
                    json.dumps(row, sort_keys=True, default=lambda value: value.isoformat())
                    for row in rows
                )

            if canonical(actual) != canonical(expected):
                raise ValueError("Prepared canonical evidence differs from the approved snapshot")
        members = set(session.scalars(select(DatasetChunk.chunk_id)))
        if members != {row["id"] for row in snapshot.chunks}:
            raise ValueError("Prepared evidence membership mismatch")
        for model in TABLES:
            count = session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.dataset_id == snapshot.dataset_id)
            )
            if count != snapshot.table_counts[model.__tablename__]:
                raise ValueError("Prepared comparison population count mismatch")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    settings = load_settings()
    snapshot = read_snapshot(args.snapshot, args.sha256)
    from evaluation.cli import restore

    restore(snapshot, settings, args.snapshot)
    engine = session_factory(settings).kw["bind"]
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE evaluation_input (snapshot_sha256 text PRIMARY KEY)"))
        connection.execute(
            text("INSERT INTO evaluation_input VALUES (:checksum)"), {"checksum": args.sha256}
        )
    # Prepared statistics and frozen pages are inputs; every gate still executes live SQL.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("SET max_parallel_maintenance_workers = 0"))
        connection.execute(text("VACUUM (FREEZE, ANALYZE, PARALLEL 0)"))
    verify(snapshot, settings, file_digest(args.snapshot))
    print(json.dumps({"prepared": True, "snapshot_sha256": args.sha256}), flush=True)


if __name__ == "__main__":
    main()
