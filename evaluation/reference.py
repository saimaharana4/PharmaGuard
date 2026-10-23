"""Independent PostgreSQL reference cells for source-reviewed benchmark preparation.

This uses DISTINCT ON and set joins instead of the product's window-based aggregation.
It is an offline review tool, never an alternative chatbot metric path.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from pharmaguard.config import load_settings
from pharmaguard.db import Dataset, Entity, session_factory
from pharmaguard.schemas import Cells, SignalFacts
from pharmaguard.signals import normalize
from sqlalchemy import text

REFERENCE_SQL = text("""
WITH latest AS (
  SELECT DISTINCT ON (case_id) case_id, primary_id, received_at
  FROM faers_report
  WHERE dataset_id=:dataset AND available_at<=:cutoff AND received_at<=:cutoff
  ORDER BY case_id, case_version DESC, primary_id DESC
), eligible AS (
  SELECT latest.* FROM latest
  LEFT JOIN (SELECT DISTINCT case_id FROM faers_deletion
             WHERE dataset_id=:dataset AND available_at<=:cutoff) deleted
    ON latest.case_id=deleted.case_id
  WHERE received_at>=:start AND deleted.case_id IS NULL
), exposed AS (
  SELECT DISTINCT primary_id FROM faers_drug
  WHERE dataset_id=:dataset AND name=ANY(:drug_names) AND role IN ('PS','SS')
), reacted AS (
  SELECT DISTINCT primary_id FROM faers_reaction
  WHERE dataset_id=:dataset AND term=ANY(:event_names)
)
SELECT count(*) FILTER (
         WHERE exposed.primary_id IS NOT NULL AND reacted.primary_id IS NOT NULL) AS a,
       count(*) FILTER (WHERE exposed.primary_id IS NOT NULL AND reacted.primary_id IS NULL) AS b,
       count(*) FILTER (WHERE exposed.primary_id IS NULL AND reacted.primary_id IS NOT NULL) AS c,
       count(*) FILTER (WHERE exposed.primary_id IS NULL AND reacted.primary_id IS NULL) AS d
FROM eligible LEFT JOIN exposed USING(primary_id) LEFT JOIN reacted USING(primary_id)
""")


def reference_facts(session, dataset: Dataset, cutoff: date) -> SignalFacts:
    drug, event = "semaglutide", "pancreatitis"
    names = {}
    for kind, canonical in [("drug", drug), ("event", event)]:
        entity = session.get(Entity, (kind, canonical))
        if not entity:
            raise ValueError("Reviewed canonical entities are required")
        names[kind] = [normalize(name) for name in [canonical, *entity.aliases]]
    row = (
        session.execute(
            REFERENCE_SQL,
            {
                "dataset": dataset.id,
                "cutoff": cutoff,
                "start": dataset.window_start,
                "drug_names": names["drug"],
                "event_names": names["event"],
            },
        )
        .mappings()
        .one()
    )
    cells = Cells(**row)
    facts = SignalFacts(
        dataset_id=dataset.id,
        period_start=dataset.window_start,
        period_end=cutoff,
        drug=drug,
        event=event,
        source_releases=[
            release
            for release in dataset.coverage["releases"]
            if not dataset.coverage.get("release_availability", {}).get(release)
            or date.fromisoformat(dataset.coverage["release_availability"][release]) <= cutoff
        ],
    )
    if not sum(row.values()):
        facts.reason = "No eligible background reports were available by the requested cutoff."
        return facts
    facts.cells, facts.case_count = cells, cells.a
    if cells.b and cells.c:
        facts.ror = (cells.a * cells.d) / (cells.b * cells.c)
    if cells.a + cells.b and cells.c:
        facts.prr = (cells.a / (cells.a + cells.b)) / (cells.c / (cells.c + cells.d))
    if facts.ror is not None and facts.prr is not None:
        facts.status = "available"
    else:
        facts.reason = "One or more contingency-table denominators are zero."
    return facts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from evaluation.schemas import BenchmarkCase

    labels = json.loads(args.labels.read_text())
    cases, facts_by_cutoff = [], {}
    with session_factory(load_settings())() as session:
        dataset = session.get(Dataset, args.dataset_id)
        if (
            not dataset
            or dataset.status != "ready"
            or not dataset.coverage.get("background_complete")
        ):
            raise ValueError("A published full-background dataset is required")
        for label in labels:
            cutoff = date.fromisoformat(label["cutoff_date"])
            if cutoff not in facts_by_cutoff:
                facts_by_cutoff[cutoff] = reference_facts(session, dataset, cutoff)
                print(json.dumps(facts_by_cutoff[cutoff].model_dump(mode="json")), flush=True)
            case = BenchmarkCase(
                **{key: value for key, value in label.items() if key != "source"},
                drug="semaglutide",
                event="pancreatitis",
                critical_evidence_ids=label["required_evidence_ids"],
                expected_facts=facts_by_cutoff[cutoff],
            )
            cases.append(case.model_dump(mode="json"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, indent=2))
    print(f"Prepared {len(cases)} source-reviewed cases using independent reference SQL")


if __name__ == "__main__":
    main()
