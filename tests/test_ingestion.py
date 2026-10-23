import importlib.util
from datetime import date
from pathlib import Path

import pytest
from pharmaguard.config import Settings
from pharmaguard.db import EvidenceChunk, SourceDocument
from sqlalchemy import create_engine, func, select

from ingestion.loader import chunks, load_documents, stable_id
from ingestion.sources.faers import quarter_end, report_date
from ingestion.sources.pubmed import parse_date
from ingestion.storage import RawStore
from tests.conftest import DATASET


def test_window_and_stable_ids():
    assert Settings(as_of_date=date(2024, 2, 29)).window_start == date(2022, 2, 28)
    assert stable_id("source", "version", "text") == stable_id("source", "version", "text")
    assert stable_id("source", "v2", "text") != stable_id("source", "version", "text")
    assert quarter_end(2024, 1) == date(2024, 3, 31)
    assert report_date("20260130") == date(2026, 1, 30)


def test_conservative_partial_publication_date():
    from defusedxml import ElementTree as ET

    assert parse_date(ET.fromstring("<PubDate><Year>2025</Year></PubDate>")) == date(2025, 12, 31)
    assert parse_date(
        ET.fromstring("<PubDate><Year>2024</Year><Month>Feb</Month></PubDate>")
    ) == date(2024, 2, 29)


def test_current_pubmed_xml_cannot_predate_its_revision():
    from defusedxml import ElementTree as ET

    from ingestion.sources.pubmed import version_available_at

    citation = ET.fromstring(
        "<MedlineCitation><DateRevised><Year>2026</Year><Month>3</Month>"
        "<Day>26</Day></DateRevised></MedlineCitation>"
    )
    assert version_available_at(citation, date(2025, 5, 13), [date(2025, 5, 13)]) == (
        date(2026, 3, 26)
    )


def test_ingestion_idempotency(sessions):
    docs = [
        {
            "source_type": "pubmed",
            "external_id": "test-source-not-real",
            "version": "test-v1",
            "title": "Synthetic integration fixture",
            "text": "Synthetic evidence only. Not production.",
            "source_date": date(2026, 1, 1),
            "available_at": date(2026, 1, 2),
            "url": "https://pubmed.ncbi.nlm.nih.gov/",
            "locator": "test-only",
            "checksum": "fixture",
            "raw_uri": "fixture://test",
        }
    ]
    with sessions.begin() as session:
        load_documents(session, DATASET, docs, "semaglutide", "pancreatitis")
        load_documents(session, DATASET, docs, "semaglutide", "pancreatitis")
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceChunk)) == 1


def test_chunk_boundaries_and_immutable_storage(tmp_path):
    assert all(len(chunk) <= 1200 for chunk in chunks("a" * 5000))
    store = RawStore(Settings(raw_directory=tmp_path / "raw"))
    source = tmp_path / "input.txt"
    source.write_text("source artifact")
    uri = store.put(source, "raw/test/checksum.txt")
    assert Path(uri).read_text() == "source artifact"
    assert store.put(source, "raw/test/checksum.txt") == uri
    source.write_text("changed")
    import pytest

    with pytest.raises(ValueError, match="checksum mismatch"):
        store.put(source, "raw/test/checksum.txt")


def test_migration_is_frozen_and_reversible():
    spec = importlib.util.spec_from_file_location("initial", "migrations/versions/0001_initial.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    metadata = module.schema()
    metadata.create_all(engine)
    from sqlalchemy import inspect

    assert "evidence_chunk" in inspect(engine).get_table_names()
    metadata.drop_all(engine)
    assert inspect(engine).get_table_names() == []


@pytest.mark.parametrize("deletion_header", ["CASEID\n", " \n", ""])
def test_faers_ascii_loading_and_deleted_case_cutoff(sessions, tmp_path, deletion_header):
    import zipfile

    from pharmaguard.db import Dataset
    from pharmaguard.signals import signal_facts

    from ingestion.loader import load_faers
    from ingestion.sources.faers import Release

    path = tmp_path / "synthetic-faers.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ASCII/DEMO26Q1.txt",
            "PRIMARYID$CASEID$CASEVERSION$FDA_DT\n"
            "1$1001$1$20260101\n2$1002$1$20260101\n"
            "3$1003$1$20260101\n4$1004$1$20260101\n",
        )
        archive.writestr(
            "ASCII/DRUG26Q1.txt",
            "PRIMARYID$DRUG_SEQ$DRUGNAME$PROD_AI$ROLE_COD\n1$1$Ozempic$SEMAGLUTIDE$PS\n2$1$Ozempic$SEMAGLUTIDE$PS\n",
        )
        archive.writestr("ASCII/REAC26Q1.txt", "PRIMARYID$PT\n1$Pancreatitis\n3$Pancreatitis\n")
        archive.writestr("ASCII/DELETE26Q1.txt", deletion_header + "1001\n")
    release = Release(
        release="test-only",
        url="https://example.invalid/test.zip",
        quarter_end=date(2026, 3, 31),
        available_at=date(2026, 4, 1),
    )
    assert load_faers(sessions, DATASET, path, release)["deleted_cases"] == 1
    load_faers(sessions, DATASET, path, release)
    with sessions() as session:
        result = signal_facts(
            session, session.get(Dataset, DATASET), date(2026, 5, 1), "semaglutide", "pancreatitis"
        )
        assert result.cells.a == 0
        assert result.cells.b == result.cells.c == result.cells.d == 1


def test_fda_archive_validates_and_orders_byte_ranges(monkeypatch):
    import io

    import httpx

    import ingestion.storage as storage

    monkeypatch.setattr(storage, "FDA_RANGE_BYTES", 8)
    source = b"a real archive would contain ZIP bytes across these ranges"

    def respond(request):
        start, end = map(int, request.headers["range"].removeprefix("bytes=").split("-"))
        end = min(end, len(source) - 1)
        return httpx.Response(
            206,
            headers={"Content-Range": f"bytes {start}-{end}/{len(source)}"},
            content=source[start : end + 1],
        )

    output = io.BytesIO()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        storage.download_fda_archive(client, "https://fis.fda.gov/test.zip", output)
    assert output.getvalue() == source
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=source))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ValueError, match="partial-content"):
            storage.download_fda_archive(client, "https://fis.fda.gov/test.zip", io.BytesIO())
