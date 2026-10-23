import json
from datetime import date
from types import SimpleNamespace

import pytest
from pharmaguard.config import Settings
from pharmaguard.db import Dataset, Entity, FaersReport
from sqlalchemy import select, text

from evaluation import prepared
from tests.conftest import DATASET


@pytest.mark.parametrize("corruption", [None, "checksum", "evidence", "population"])
def test_prepared_inputs_fail_closed_on_drift(sessions, monkeypatch, corruption):
    with sessions.begin() as session:
        session.execute(text("CREATE TABLE evaluation_input (snapshot_sha256 text PRIMARY KEY)"))
        session.execute(text("INSERT INTO evaluation_input VALUES ('approved-synthetic-checksum')"))

        def records(model):
            return [
                {c.name: getattr(row, c.name) for c in model.__table__.columns}
                for row in session.scalars(select(model))
            ]

        snapshot = SimpleNamespace(
            dataset_id=DATASET,
            dataset=records(Dataset)[0],
            entities=json.loads(json.dumps(records(Entity))),
            documents=[],
            chunks=[],
            table_counts={model.__tablename__: 0 for model in prepared.TABLES},
        )
        if corruption == "checksum":
            session.execute(text("UPDATE evaluation_input SET snapshot_sha256='different-input'"))
        elif corruption == "evidence":
            session.get(Entity, ("drug", "semaglutide")).aliases = ["incorrect synthetic alias"]
        elif corruption == "population":
            session.add(
                FaersReport(
                    dataset_id=DATASET,
                    primary_id="synthetic",
                    case_id="synthetic",
                    case_version=1,
                    received_at=date(2025, 1, 1),
                    available_at=date(2025, 1, 1),
                    release="test-only",
                )
            )
    monkeypatch.setattr(prepared, "session_factory", lambda _: sessions)
    if corruption:
        with pytest.raises(ValueError, match="match|differs|count"):
            prepared.verify(snapshot, Settings(), "approved-synthetic-checksum")
    else:
        prepared.verify(snapshot, Settings(), "approved-synthetic-checksum")
