"""Maintain one private dashboard for existing services; create no telemetry backend or alerts."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import google.auth
from google.auth.transport.requests import AuthorizedSession

PROJECT = "project-bb13ecd8-9d67-408d-9a7"
TITLE = "PharmaGuard release operations"
API = "https://monitoring.googleapis.com/v1/projects/" + PROJECT


def dashboard() -> dict:
    widgets = [
        {
            "title": "Release and privacy boundaries",
            "text": {
                "format": "MARKDOWN",
                "content": "Existing VM and Cloud Run telemetry. No prompts, answers, "
                "session tokens or secret values are collected. Smoke reports are "
                "point-in-time checks, "
                "not an uptime SLA. [Release evidence](https://gitlab.com/"
                "gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/wikis/Release-evidence).",
            },
        }
    ]
    charts = [
        (
            "VM CPU utilization",
            "compute.googleapis.com/instance/cpu/utilization",
            "gce_instance",
            'resource.labels.instance_id="5885510090940336572"',
            "ALIGN_MEAN",
            "10^2.%",
        ),
        (
            "VM memory utilization (Ops Agent)",
            "agent.googleapis.com/memory/percent_used",
            "gce_instance",
            'resource.labels.instance_id="5885510090940336572" AND metric.labels.state="used"',
            "ALIGN_MEAN",
            "%",
        ),
        (
            "Production requests / second",
            "run.googleapis.com/request_count",
            "cloud_run_revision",
            'resource.labels.service_name="pharmaguard-web"',
            "ALIGN_RATE",
            "1/s",
        ),
        (
            "Production 5xx / second",
            "run.googleapis.com/request_count",
            "cloud_run_revision",
            'resource.labels.service_name="pharmaguard-web" AND '
            'metric.labels.response_code_class="5xx"',
            "ALIGN_RATE",
            "1/s",
        ),
        (
            "Production p95 request latency",
            "run.googleapis.com/request_latencies",
            "cloud_run_revision",
            'resource.labels.service_name="pharmaguard-web"',
            "ALIGN_PERCENTILE_95",
            "ms",
        ),
        (
            "Staging requests / second",
            "run.googleapis.com/request_count",
            "cloud_run_revision",
            'resource.labels.service_name="pharmaguard-vm-preview"',
            "ALIGN_RATE",
            "1/s",
        ),
    ]
    for title, metric, resource, conditions, aligner, unit in charts:
        widgets.append(
            {
                "title": title,
                "xyChart": {
                    "dataSets": [
                        {
                            "plotType": "LINE",
                            "timeSeriesQuery": {
                                "unitOverride": unit,
                                "timeSeriesFilter": {
                                    "filter": f'metric.type="{metric}" '
                                    f'AND resource.type="{resource}" AND {conditions}',
                                    "aggregation": {
                                        "alignmentPeriod": "60s",
                                        "perSeriesAligner": aligner,
                                    },
                                },
                            },
                        }
                    ],
                    "timeshiftDuration": "0s",
                    "yAxis": {"label": unit, "scale": "LINEAR"},
                },
            }
        )
    return {"displayName": TITLE, "gridLayout": {"columns": "2", "widgets": widgets}}


def apply(session: AuthorizedSession) -> dict:
    response = session.get(API + "/dashboards", timeout=45)
    response.raise_for_status()
    matches = [d for d in response.json().get("dashboards", []) if d["displayName"] == TITLE]
    if len(matches) > 1:
        raise RuntimeError("Multiple managed dashboards exist; reconcile before updating")
    body = dashboard()
    if matches:
        body.update({k: matches[0][k] for k in ("name", "etag") if k in matches[0]})
        response = session.patch(
            "https://monitoring.googleapis.com/v1/" + body["name"], json=body, timeout=45
        )
    else:
        response = session.post(API + "/dashboards", json=body, timeout=45)
    response.raise_for_status()
    saved = response.json()
    end = datetime.now(UTC)
    evidence = []
    for widget in body["gridLayout"]["widgets"][1:]:
        query = widget["xyChart"]["dataSets"][0]["timeSeriesQuery"]["timeSeriesFilter"]
        response = session.get(
            API.replace("/v1/", "/v3/") + "/timeSeries",
            params={
                "filter": query["filter"],
                "interval.startTime": (end - timedelta(days=1)).isoformat(),
                "interval.endTime": end.isoformat(),
                "view": "FULL",
                "pageSize": 100,
            },
            timeout=45,
        )
        response.raise_for_status()
        series = response.json().get("timeSeries", [])
        evidence.append(
            {
                "title": widget["title"],
                "series": len(series),
                "points": sum(len(s.get("points", [])) for s in series),
                "more_series": bool(response.json().get("nextPageToken")),
            }
        )
    return {
        "name": saved["name"],
        "verified_at": end.isoformat(),
        "queries": evidence,
        "url": "https://console.cloud.google.com/monitoring/dashboards/builder/"
        + saved["name"].split("/")[-1]
        + "?project="
        + PROJECT,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(".data/monitoring.json"))
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(dashboard(), indent=2))
        return
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    result = apply(AuthorizedSession(credentials))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
