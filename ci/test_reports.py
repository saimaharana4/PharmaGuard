"""Translate existing deterministic results to JUnit without rerunning or relabeling cases."""

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from evaluation.core import MIN_RECALL


def rag_junit(report: dict) -> ET.Element:
    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("RAG report must contain executed cases")
    ids = [case.get("case_id") for case in cases]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError("RAG case identifiers must be nonempty and unique")
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", name="frozen-rag", tests=str(len(cases) * 5))
    failures = 0
    all_passed = True
    for case in cases:
        recall = case.get("recall_at_5")
        if type(recall) not in (int, float) or not math.isfinite(recall) or not 0 <= recall <= 1:
            raise ValueError("Invalid recall result")
        for field in [
            "critical_hit",
            "citation_integrity",
            "temporal_leakage",
            "facts_match",
            "passed",
        ]:
            if type(case.get(field)) is not bool:
                raise ValueError(f"Invalid boolean result: {field}")
        checks = {
            "recall_at_5": recall >= MIN_RECALL,
            "critical_evidence": case["critical_hit"],
            "canonical_citations": case["citation_integrity"],
            "no_temporal_leakage": not case["temporal_leakage"],
            "exact_facts": case["facts_match"],
        }
        passed = all(checks.values())
        if case["passed"] != passed:
            raise ValueError("RAG summary contradicts its measured checks")
        all_passed &= passed
        for name, valid in checks.items():
            test = ET.SubElement(suite, "testcase", classname=case["case_id"], name=name)
            if not valid:
                failures += 1
                ET.SubElement(
                    test, "failure", message=f"Reviewed gate failed: {name}"
                ).text = json.dumps(case, sort_keys=True)
    if type(report.get("passed")) is not bool or report["passed"] != all_passed:
        raise ValueError("Overall RAG summary contradicts the executed cases")
    suite.set("failures", str(failures))
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = rag_junit(json.loads(args.report.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(args.output, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
