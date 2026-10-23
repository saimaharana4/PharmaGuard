from datetime import date

import pytest
from pharmaguard.db import ActiveDataset, Base, Dataset, Entity
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DATASET = "33409c64-8893-4434-92ef-376eb38d4b07"


@pytest.fixture()
def sessions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Dataset(
                id=DATASET,
                status="ready",
                window_start=date(2024, 10, 18),
                as_of_date=date(2026, 10, 18),
                model_revision="test",
                coverage={"background_complete": True, "releases": ["test-only"]},
            )
        )
        session.add_all(
            [
                Entity(kind="drug", canonical="semaglutide", aliases=["ozempic"]),
                Entity(kind="event", canonical="pancreatitis", aliases=["acute pancreatitis"]),
            ]
        )
        session.flush()
        session.add(ActiveDataset(id=1, dataset_id=DATASET))
    yield factory
    engine.dispose()
