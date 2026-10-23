import pytest

from ci.security_policy import REQUIRED, assess


def reports():
    return [
        {"scan": {"type": kind, "status": "success"}, "vulnerabilities": []}
        for kind in sorted(REQUIRED)
    ]


def test_missing_scan_cannot_be_a_clean_result():
    with pytest.raises(ValueError, match="missing"):
        assess(reports()[:-1])


@pytest.mark.parametrize(
    "severity,blocks", [("Critical", True), ("High", True), ("Unknown", True), ("Medium", False)]
)
def test_measured_findings_are_retained_and_block_by_policy(severity, blocks):
    data = reports()
    data[0]["vulnerabilities"] = [{"id": "advisory-id", "severity": severity}]
    result = assess(data)
    assert result["passed"] is not blocks
    assert result["severity_counts"][severity.lower()] == 1


def test_any_secret_finding_blocks_even_at_low_severity():
    data = reports()
    next(r for r in data if r["scan"]["type"] == "secret_detection")["vulnerabilities"] = [
        {"id": "redacted-finding", "severity": "Low"}
    ]
    assert not assess(data)["passed"]


def test_failed_or_malformed_scans_cannot_pass():
    data = reports()
    data[0]["scan"]["status"] = "failure"
    with pytest.raises(ValueError):
        assess(data)
