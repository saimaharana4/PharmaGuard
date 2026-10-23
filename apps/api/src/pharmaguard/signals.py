"""Report-level disproportionality; a drug-only sample is never the background."""

import re
from datetime import date

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from pharmaguard.db import Dataset, Entity, FaersDeletion, FaersDrug, FaersReaction, FaersReport
from pharmaguard.schemas import Cells, SignalFacts


def normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value.lower()).split())


def resolve_entity(session: Session, kind: str, explicit: str | None, question: str) -> str | None:
    text = normalize(explicit or question)
    matches = set()
    for entity in session.scalars(select(Entity).where(Entity.kind == kind)):
        for alias in [entity.canonical, *entity.aliases]:
            term = normalize(alias)
            if (explicit and text == term) or (
                not explicit and re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text)
            ):
                matches.add(entity.canonical)
    return next(iter(matches)) if len(matches) == 1 else None


def formulas(cells: Cells) -> tuple[float | None, float | None]:
    a, b, c, d = cells.a, cells.b, cells.c, cells.d
    ror = (a * d) / (b * c) if b > 0 and c > 0 else None
    prr = (a / (a + b)) / (c / (c + d)) if a + b > 0 and c > 0 else None
    return ror, prr


def signal_facts(
    session: Session,
    dataset: Dataset,
    cutoff: date,
    drug: str | None,
    event: str | None,
) -> SignalFacts:
    facts = SignalFacts(
        period_start=dataset.window_start,
        period_end=cutoff,
        dataset_id=dataset.id,
        drug=drug,
        event=event,
        source_releases=[
            release
            for release in dataset.coverage.get("releases", [])
            if not dataset.coverage.get("release_availability", {}).get(release)
            or date.fromisoformat(dataset.coverage["release_availability"][release]) <= cutoff
        ],
    )
    if not drug or not event:
        facts.reason = "Specify one recognized drug and event to calculate report-level metrics."
        return facts
    if not dataset.coverage.get("background_complete", False):
        facts.reason = "The full comparison population has not been loaded for this dataset."
        return facts
    # Rank versions known by the historical cutoff BEFORE filtering the reporting window.
    ranked = (
        select(
            FaersReport.primary_id,
            FaersReport.case_id,
            FaersReport.received_at,
            func.row_number()
            .over(
                partition_by=FaersReport.case_id,
                order_by=(FaersReport.case_version.desc(), FaersReport.primary_id.desc()),
            )
            .label("position"),
        )
        .where(
            FaersReport.dataset_id == dataset.id,
            FaersReport.available_at <= cutoff,
            FaersReport.received_at <= cutoff,
        )
        .subquery()
    )
    aliases = session.get(Entity, ("drug", drug))
    names = [normalize(x) for x in [drug, *(aliases.aliases if aliases else [])]]
    event_entity = session.get(Entity, ("event", event))
    terms = [normalize(x) for x in [event, *(event_entity.aliases if event_entity else [])]]
    exposed = (
        select(FaersDrug.primary_id)
        .where(
            FaersDrug.dataset_id == dataset.id,
            FaersDrug.name.in_(names),
            FaersDrug.role.in_(["PS", "SS"]),
        )
        .distinct()
        .subquery()
    )
    reacted = (
        select(FaersReaction.primary_id)
        .where(
            FaersReaction.dataset_id == dataset.id,
            FaersReaction.term.in_(terms),
        )
        .distinct()
        .subquery()
    )
    deleted = (
        select(FaersDeletion.case_id)
        .where(FaersDeletion.dataset_id == dataset.id, FaersDeletion.available_at <= cutoff)
        .distinct()
        .subquery()
    )
    flags = (
        select(
            exposed.c.primary_id.is_not(None).label("drug"),
            reacted.c.primary_id.is_not(None).label("event"),
        )
        .select_from(ranked)
        .outerjoin(exposed, exposed.c.primary_id == ranked.c.primary_id)
        .outerjoin(reacted, reacted.c.primary_id == ranked.c.primary_id)
        .outerjoin(deleted, deleted.c.case_id == ranked.c.case_id)
        .where(
            ranked.c.position == 1,
            ranked.c.received_at >= dataset.window_start,
            deleted.c.case_id.is_(None),
        )
        .subquery()
    )
    counts = session.execute(
        select(
            *[
                func.coalesce(func.sum(case((condition, 1), else_=0)), 0)
                for condition in [
                    and_(flags.c.drug, flags.c.event),
                    and_(flags.c.drug, ~flags.c.event),
                    and_(~flags.c.drug, flags.c.event),
                    and_(~flags.c.drug, ~flags.c.event),
                ]
            ]
        )
    ).one()
    if sum(counts) == 0:
        facts.reason = "No eligible background reports were available by the requested cutoff."
        return facts
    facts.cells = Cells(**dict(zip(["a", "b", "c", "d"], counts, strict=True)))
    facts.case_count = facts.cells.a
    facts.ror, facts.prr = formulas(facts.cells)
    if facts.ror is not None and facts.prr is not None:
        facts.status = "available"
    else:
        facts.reason = "One or more contingency-table denominators are zero."
    return facts
