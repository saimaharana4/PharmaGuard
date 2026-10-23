"""Initial canonical schema.

Revision ID: 0001
"""

from alembic import op
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
)

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def schema() -> MetaData:
    """Frozen migration definitions, independent of future ORM changes."""
    m = MetaData()
    Table(
        "dataset",
        m,
        Column("id", String(36), primary_key=True),
        Column("status", String, nullable=False),
        Column("window_start", Date, nullable=False),
        Column("as_of_date", Date, nullable=False),
        Column("coverage", JSON, nullable=False),
        Column("model_revision", String, nullable=False),
    )
    Table(
        "active_dataset",
        m,
        Column("id", Integer, primary_key=True),
        Column("dataset_id", ForeignKey("dataset.id"), nullable=False),
    )
    Table(
        "ingestion_run",
        m,
        Column("id", String(36), primary_key=True),
        Column("dataset_id", ForeignKey("dataset.id"), nullable=False, index=True),
        Column("stage", String, nullable=False),
        Column("status", String, nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False),
        Column("finished_at", DateTime(timezone=True)),
        Column("details", JSON, nullable=False),
    )
    Table(
        "source_document",
        m,
        Column("id", String(36), primary_key=True),
        Column("source_type", String, nullable=False, index=True),
        Column("external_id", String, nullable=False, index=True),
        Column("version", String, nullable=False),
        Column("title", String, nullable=False),
        Column("source_date", Date, nullable=False, index=True),
        Column("available_at", Date, nullable=False, index=True),
        Column("url", String, nullable=False),
        Column("checksum", String, nullable=False),
        Column("raw_uri", String, nullable=False),
    )
    Table(
        "evidence_chunk",
        m,
        Column("id", String(36), primary_key=True),
        Column("document_id", ForeignKey("source_document.id"), nullable=False, index=True),
        Column("text", String, nullable=False),
        Column("locator", String, nullable=False),
        Column("drug_id", String, nullable=False, index=True),
        Column("event_id", String, nullable=False, index=True),
        Column("polarity", String, nullable=False),
    )
    Table(
        "dataset_chunk",
        m,
        Column("dataset_id", ForeignKey("dataset.id"), primary_key=True),
        Column("chunk_id", ForeignKey("evidence_chunk.id"), primary_key=True),
    )
    report = Table(
        "faers_report",
        m,
        Column("dataset_id", ForeignKey("dataset.id"), primary_key=True),
        Column("primary_id", String, primary_key=True),
        Column("case_id", String, nullable=False, index=True),
        Column("case_version", Integer, nullable=False),
        Column("received_at", Date, nullable=False, index=True),
        Column("available_at", Date, nullable=False, index=True),
        Column("release", String, nullable=False),
    )
    from sqlalchemy import Index

    Index("ix_report_case_version", report.c.dataset_id, report.c.case_id, report.c.case_version)
    for table_name, extra in [
        (
            "faers_drug",
            [
                Column("sequence", String, primary_key=True),
                Column("name", String, nullable=False, index=True),
                Column("role", String, nullable=False),
            ],
        ),
        ("faers_reaction", [Column("term", String, primary_key=True)]),
    ]:
        table = Table(
            table_name,
            m,
            Column("dataset_id", String(36), primary_key=True),
            Column("primary_id", String, primary_key=True),
            *extra,
            ForeignKeyConstraint(
                ["dataset_id", "primary_id"], ["faers_report.dataset_id", "faers_report.primary_id"]
            ),
        )
        if table_name == "faers_reaction":
            Index("ix_reaction_term", table.c.term)
    Table(
        "entity",
        m,
        Column("kind", String, primary_key=True),
        Column("canonical", String, primary_key=True),
        Column("aliases", JSON, nullable=False),
    )
    Table(
        "evaluation_case",
        m,
        Column("id", String, primary_key=True),
        Column("dataset_id", ForeignKey("dataset.id"), nullable=False, index=True),
        Column("question", String, nullable=False),
        Column("drug", String),
        Column("event", String),
        Column("cutoff_date", Date, nullable=False),
        Column("expected_facts", JSON, nullable=False),
        Column("reviewed_by", String, nullable=False),
        Column("review_note", String, nullable=False),
    )
    Table(
        "evaluation_relevance",
        m,
        Column("case_id", ForeignKey("evaluation_case.id"), primary_key=True),
        Column("chunk_id", ForeignKey("evidence_chunk.id"), primary_key=True),
        Column("critical", Boolean, nullable=False),
    )
    return m


def upgrade() -> None:
    schema().create_all(op.get_bind())


def downgrade() -> None:
    schema().drop_all(op.get_bind())
