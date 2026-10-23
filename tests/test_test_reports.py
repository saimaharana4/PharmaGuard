import copy

import pytest

from ci.test_reports import rag_junit


def report():
    return {
        "passed": True,
        "cases": [
            {
                "case_id": "reviewed-a",
                "recall_at_5": 1.0,
                "critical_hit": True,
                "citation_integrity": True,
                "temporal_leakage": False,
                "facts_match": True,
                "passed": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("recall_at_5", 0.5),
        ("critical_hit", False),
        ("citation_integrity", False),
        ("temporal_leakage", True),
        ("facts_match", False),
    ],
)
def test_failed_measured_gate_remains_a_junit_failure(field, value):
    data = report()
    data["cases"][0].update({field: value, "passed": False})
    data["passed"] = False
    root = rag_junit(data)
    assert len(root.findall(".//testcase")) == 5
    assert len(root.findall(".//failure")) == 1


def test_report_cannot_claim_success_after_regression():
    data = report()
    data["cases"][0]["recall_at_5"] = 0.5
    with pytest.raises(ValueError, match="contradicts"):
        rag_junit(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1.1, True, "1"])
def test_rejects_invalid_recall(value):
    data = report()
    data["cases"][0]["recall_at_5"] = value
    with pytest.raises(ValueError):
        rag_junit(data)


def test_rejects_missing_duplicate_or_non_boolean_results():
    for mutate in [
        lambda d: d.update(cases=[]),
        lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])),
        lambda d: d["cases"][0].update(temporal_leakage="false"),
        lambda d: d.update(passed=False),
    ]:
        data = report()
        mutate(data)
        with pytest.raises(ValueError):
            rag_junit(data)
