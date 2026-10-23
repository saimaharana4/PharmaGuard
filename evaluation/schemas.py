from datetime import date

from pharmaguard.schemas import SignalFacts
from pydantic import BaseModel, Field


class BenchmarkCase(BaseModel):
    case_id: str
    question: str
    drug: str | None = None
    event: str | None = None
    cutoff_date: date
    required_evidence_ids: list[str] = Field(min_length=1)
    critical_evidence_ids: list[str] = Field(min_length=1)
    expected_facts: SignalFacts
    reviewed_by: str = Field(min_length=1)
    review_note: str = Field(min_length=10)
    expected_answer_points: list[str] = Field(default_factory=list)


class Snapshot(BaseModel):
    schema_version: int = 1
    dataset_id: str
    dataset_version: str
    query_model_revision: str
    document_model_revision: str
    reranker_model_revision: str = ""
    reranker_quantization: str = "dynamic-int8-onednn"
    dataset: dict
    entities: list[dict]
    documents: list[dict]
    chunks: list[dict]
    table_counts: dict[str, int]
    ingestion_runs: list[dict] = Field(default_factory=list)
    cases: list[BenchmarkCase] = Field(min_length=10, max_length=20)


class CaseResult(BaseModel):
    case_id: str
    recall_at_5: float
    critical_hit: bool
    citation_integrity: bool
    temporal_leakage: bool
    facts_match: bool
    retrieved_ids: list[str]
    missing_ids: list[str]
    passed: bool
