from datetime import date

import pytest
from pharmaguard.db import Dataset, FaersDrug, FaersReaction, FaersReport
from pharmaguard.schemas import Cells
from pharmaguard.signals import formulas, resolve_entity, signal_facts

from tests.conftest import DATASET


def test_hand_calculated_formulas():
    ror, prr = formulas(Cells(a=10, b=20, c=30, d=100))
    assert ror == pytest.approx(1000 / 600)
    assert prr == pytest.approx((10 / 30) / (30 / 130))


@pytest.mark.parametrize("cells", [Cells(a=0, b=0, c=0, d=0), Cells(a=4, b=1, c=0, d=7)])
def test_invalid_denominators_are_not_zero(cells):
    assert formulas(cells) == (None, None)


def test_partial_unavailability():
    assert formulas(Cells(a=4, b=0, c=2, d=8)) == (None, 5.0)


def add_report(
    session, primary, case, version, exposed, event, available="2026-01-01", received="2026-01-01"
):
    session.add(
        FaersReport(
            dataset_id=DATASET,
            primary_id=primary,
            case_id=case,
            case_version=version,
            received_at=date.fromisoformat(received),
            available_at=date.fromisoformat(available),
            release="test-only",
        )
    )
    session.flush()
    if exposed:
        session.add(
            FaersDrug(
                dataset_id=DATASET, primary_id=primary, sequence="1", name="semaglutide", role="PS"
            )
        )
    if event:
        session.add(FaersReaction(dataset_id=DATASET, primary_id=primary, term="pancreatitis"))


def test_case_dedup_and_temporal_versions(sessions):
    with sessions.begin() as session:
        add_report(session, "1", "a", 1, True, True)
        add_report(session, "2", "a", 2, True, False, available="2026-09-01")
        add_report(session, "3", "b", 1, True, False)
        add_report(session, "4", "c", 1, False, True)
        add_report(session, "5", "d", 1, False, False)
        # Multiple drug rows must not multiply a case in the contingency table.
        session.add(
            FaersDrug(
                dataset_id=DATASET, primary_id="1", sequence="2", name="semaglutide", role="SS"
            )
        )
    with sessions() as session:
        dataset = session.get(Dataset, DATASET)
        past = signal_facts(session, dataset, date(2026, 6, 1), "semaglutide", "pancreatitis")
        present = signal_facts(session, dataset, date(2026, 10, 18), "semaglutide", "pancreatitis")
        assert past.cells == Cells(a=1, b=1, c=1, d=1)
        assert past.ror == 1
        assert present.cells == Cells(a=0, b=2, c=1, d=1)
        assert present.case_count == 0


def test_aliases_and_ambiguity(sessions):
    with sessions() as session:
        assert resolve_entity(session, "drug", None, "What about Ozempic?") == "semaglutide"
        assert resolve_entity(session, "drug", "unknown drug", "semaglutide") is None
        assert resolve_entity(session, "event", None, "acute pancreatitis") == "pancreatitis"
        facts = signal_facts(session, session.get(Dataset, DATASET), date(2026, 10, 18), None, None)
        assert facts.case_count is None and facts.reason


def test_historical_fact_lineage_does_not_include_future_releases(sessions):
    with sessions.begin() as session:
        dataset = session.get(Dataset, DATASET)
        dataset.coverage = {
            "background_complete": True,
            "releases": ["old", "future"],
            "release_availability": {"old": "2026-01-01", "future": "2026-09-01"},
        }
        facts = signal_facts(session, dataset, date(2026, 6, 1), "semaglutide", "pancreatitis")
        assert facts.source_releases == ["old"]
