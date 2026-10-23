from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class InvestigateRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    drug: str | None = Field(default=None, max_length=200)
    event: str | None = Field(default=None, max_length=200)
    cutoff_date: date | None = None

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a question of at least three characters")
        return value


class Cells(BaseModel):
    a: int = Field(ge=0)
    b: int = Field(ge=0)
    c: int = Field(ge=0)
    d: int = Field(ge=0)


class SignalFacts(BaseModel):
    period_start: date
    period_end: date
    case_count: int | None = None
    cells: Cells | None = None
    ror: float | None = None
    prr: float | None = None
    status: Literal["available", "insufficient_data"] = "insufficient_data"
    reason: str | None = None
    drug: str | None = None
    event: str | None = None
    dataset_id: str
    source_releases: list[str] = Field(default_factory=list)


class EvidenceHit(BaseModel):
    chunk_id: str
    document_id: str
    score: float
    rank: int
    source_type: str
    source_date: date
    available_at: date
    title: str
    locator: str
    polarity: Literal["support", "contradict", "context"]
    text: str
    url: str
    retrieval_method: str = "dense"
    rerank_score: float | None = None


class Synthesis(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)
    cited_chunk_ids: list[str] = Field(max_length=20)
    insufficient_evidence: bool = False
    provider: str = "none"
    model: str = ""
    fallback_used: bool = False


class RetrievalMetadata(BaseModel):
    top_k: int
    returned: int
    collection: str
    config_version: str
    query_model_revision: str


class DataWindow(BaseModel):
    lookback_months: int
    window_start: date
    as_of_date: date
    cutoff_date: date
    dataset_id: str
    coverage: dict


class InvestigateResponse(BaseModel):
    request_id: str
    answer: str
    facts: SignalFacts
    citations: list[EvidenceHit]
    retrieved_evidence_ids: list[str]
    retrieved_evidence: list[EvidenceHit] = Field(default_factory=list)
    retrieval: RetrievalMetadata
    data_window: DataWindow
    warnings: list[str]
    insufficient_evidence: bool
    synthesis: dict[str, str | bool] = Field(default_factory=dict)
    session_id: str | None = None
    cache_status: Literal["hit", "miss", "disabled"] = "disabled"
