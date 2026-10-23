import hashlib
import json
import zipfile
from collections.abc import Iterable
from pathlib import Path

from pharmaguard.schemas import EvidenceHit, SignalFacts

from evaluation.schemas import BenchmarkCase, CaseResult, Snapshot

MIN_RECALL = 0.80


def compare(case: BenchmarkCase, hits: list[EvidenceHit], facts: SignalFacts) -> CaseResult:
    ids = [hit.chunk_id for hit in hits[:5]]
    required = set(case.required_evidence_ids)
    recalled = len(required.intersection(ids)) / len(required)
    critical = set(case.critical_evidence_ids) <= set(ids)
    # Deterministic gate tests citation eligibility, not semantic entailment or live LLM prose.
    citation_integrity = all(hit.chunk_id in ids and hit.document_id for hit in hits)
    leakage = any(
        hit.source_date > case.cutoff_date
        or hit.available_at > case.cutoff_date
        or hit.source_date < facts.period_start
        for hit in hits
    )
    match = facts.model_dump(mode="json") == case.expected_facts.model_dump(mode="json")
    return CaseResult(
        case_id=case.case_id,
        recall_at_5=recalled,
        critical_hit=critical,
        citation_integrity=bool(citation_integrity),
        temporal_leakage=leakage,
        facts_match=match,
        retrieved_ids=ids,
        missing_ids=sorted(required - set(ids)),
        passed=recalled >= MIN_RECALL and critical and citation_integrity and not leakage and match,
    )


def canonical_bytes(snapshot: Snapshot) -> bytes:
    return json.dumps(
        snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def archive_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_snapshot(
    path: Path, snapshot: Snapshot, tables: dict[str, Iterable[dict]] | None = None
) -> str:
    """Stream full background tables to deterministic compressed JSONL members."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", allowZip64=True) as archive:
        archive.writestr(archive_info("manifest.json"), canonical_bytes(snapshot))
        for name, rows in sorted((tables or {}).items()):
            count = 0
            with archive.open(archive_info(name + ".jsonl"), "w", force_zip64=True) as output:
                for row in rows:
                    output.write(
                        (
                            json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
                            + "\n"
                        ).encode()
                    )
                    count += 1
            if count != snapshot.table_counts[name]:
                raise ValueError("Snapshot row count changed while exporting")
    digest = file_digest(path)
    path.with_suffix(path.suffix + ".sha256").write_text(digest + "\n")
    return digest


def read_snapshot(path: Path, expected_sha256: str | None = None) -> Snapshot:
    actual = file_digest(path)
    expected = expected_sha256 or path.with_suffix(path.suffix + ".sha256").read_text().strip()
    if actual != expected:
        raise ValueError("Evaluation snapshot checksum mismatch")
    with zipfile.ZipFile(path) as archive:
        return Snapshot.model_validate_json(archive.read("manifest.json"))
