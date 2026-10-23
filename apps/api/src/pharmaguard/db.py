"""Canonical relational schema. Schema creation is owned by Alembic."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from pharmaguard.config import Settings


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "dataset"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(default="loading")
    window_start: Mapped[date]
    as_of_date: Mapped[date]
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    model_revision: Mapped[str] = mapped_column(default="")


class ActiveDataset(Base):
    __tablename__ = "active_dataset"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.id"))


class IngestionRun(Base):
    __tablename__ = "ingestion_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.id"), index=True)
    stage: Mapped[str]
    status: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceDocument(Base):
    __tablename__ = "source_document"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_type: Mapped[str] = mapped_column(index=True)
    external_id: Mapped[str] = mapped_column(index=True)
    version: Mapped[str]
    title: Mapped[str]
    source_date: Mapped[date] = mapped_column(index=True)
    available_at: Mapped[date] = mapped_column(index=True)
    url: Mapped[str]
    checksum: Mapped[str]
    raw_uri: Mapped[str]


class EvidenceChunk(Base):
    __tablename__ = "evidence_chunk"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_document.id"), index=True)
    text: Mapped[str]
    locator: Mapped[str]
    drug_id: Mapped[str] = mapped_column(index=True)
    event_id: Mapped[str] = mapped_column(index=True)
    polarity: Mapped[str] = mapped_column(default="context")


class DatasetChunk(Base):
    __tablename__ = "dataset_chunk"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.id"), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("evidence_chunk.id"), primary_key=True)


class FaersReport(Base):
    __tablename__ = "faers_report"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.id"), primary_key=True)
    primary_id: Mapped[str] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(index=True)
    case_version: Mapped[int]
    received_at: Mapped[date] = mapped_column(index=True)
    available_at: Mapped[date] = mapped_column(index=True)
    release: Mapped[str]
    __table_args__ = (Index("ix_report_case_version", "dataset_id", "case_id", "case_version"),)


class FaersDrug(Base):
    __tablename__ = "faers_drug"
    dataset_id: Mapped[str] = mapped_column(primary_key=True)
    primary_id: Mapped[str] = mapped_column(primary_key=True)
    sequence: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(index=True)
    role: Mapped[str]
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "primary_id"], ["faers_report.dataset_id", "faers_report.primary_id"]
        ),
    )


class FaersReaction(Base):
    __tablename__ = "faers_reaction"
    dataset_id: Mapped[str] = mapped_column(primary_key=True)
    primary_id: Mapped[str] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "primary_id"], ["faers_report.dataset_id", "faers_report.primary_id"]
        ),
        Index("ix_reaction_term", "term"),
    )


class Entity(Base):
    __tablename__ = "entity"
    kind: Mapped[str] = mapped_column(primary_key=True)
    canonical: Mapped[str] = mapped_column(primary_key=True)
    aliases: Mapped[list] = mapped_column(JSON)


class EvaluationCase(Base):
    __tablename__ = "evaluation_case"
    id: Mapped[str] = mapped_column(primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.id"), index=True)
    question: Mapped[str]
    drug: Mapped[str | None]
    event: Mapped[str | None]
    cutoff_date: Mapped[date]
    expected_facts: Mapped[dict] = mapped_column(JSON)
    reviewed_by: Mapped[str]
    review_note: Mapped[str]
    expected_answer_points: Mapped[list] = mapped_column(JSON, default=list)


class EvaluationRelevance(Base):
    __tablename__ = "evaluation_relevance"
    case_id: Mapped[str] = mapped_column(ForeignKey("evaluation_case.id"), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("evidence_chunk.id"), primary_key=True)
    critical: Mapped[bool]


def session_factory(settings: Settings) -> sessionmaker:
    engine = create_engine(
        settings.database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=2,
        connect_args={"connect_timeout": 5},
    )
    return sessionmaker(engine, expire_on_commit=False)


class FaersDeletion(Base):
    __tablename__ = "faers_deletion"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.id"), primary_key=True)
    case_id: Mapped[str] = mapped_column(primary_key=True)
    available_at: Mapped[date] = mapped_column(primary_key=True)
    release: Mapped[str]


class RequestBudget(Base):
    __tablename__ = "request_budget"
    day: Mapped[date] = mapped_column(primary_key=True)
    used: Mapped[int]


class ChatSession(Base):
    __tablename__ = "chat_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    history: Mapped[list] = mapped_column(JSON, default=list)
    answers: Mapped[list] = mapped_column(JSON, default=list)
