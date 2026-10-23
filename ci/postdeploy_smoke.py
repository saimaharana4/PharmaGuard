import json
import os
import time
from pathlib import Path

import httpx
from pharmaguard.schemas import InvestigateResponse


def main() -> None:
    started = time.monotonic()
    base = os.environ["WEB_URL"].rstrip("/")
    expected = set(json.loads(os.environ["SMOKE_REQUIRED_EVIDENCE_IDS"]))
    if not expected:
        raise ValueError("A reviewed smoke-case evidence expectation is required")
    checks = {}
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for route in ["health", "ready"]:
            response = client.get(f"{base}/api/{route}")
            response.raise_for_status()
            checks[route] = response.json()
        client.post(f"{base}/api/session", headers={"Origin": base}).raise_for_status()
        response = client.post(
            f"{base}/api/investigate",
            headers={"Origin": base},
            json={
                "question": os.environ["SMOKE_QUESTION"],
                "drug": "semaglutide",
                "event": "pancreatitis",
                **(
                    {"cutoff_date": os.environ["SMOKE_CUTOFF_DATE"]}
                    if os.environ.get("SMOKE_CUTOFF_DATE")
                    else {}
                ),
            },
        )
        response.raise_for_status()
        result = InvestigateResponse.model_validate(response.json())
        cited = {hit.chunk_id for hit in result.citations}
        if result.insufficient_evidence or not expected <= cited:
            raise ValueError("Smoke case did not cite the approved required evidence")
        checks["request_id"] = result.request_id
        checks["citation_ids"] = sorted(cited)
        checks["dataset_id"] = result.data_window.dataset_id
    elapsed = time.monotonic() - started
    if elapsed >= 60:
        raise ValueError("Smoke test exceeded the 60-second target")
    Path("postdeploy-report.json").write_text(
        json.dumps(
            {
                "passed": True,
                "duration_seconds": elapsed,
                "checks": checks,
                "git_sha": os.environ.get("CI_COMMIT_SHA"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
