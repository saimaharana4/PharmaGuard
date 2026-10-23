from unittest.mock import Mock

import pytest

from operations.evidence import reject_secrets
from operations.monitoring import dashboard
from operations.wiki import publish
from operations.workspace import Workspace, reviewed_cases


def test_planning_rerun_preserves_existing_item_and_user_edits():
    api = Mock()
    workspace = Workspace(api)
    record = {"description": "Human notes\n<!-- pharmaguard-operations:stable-key -->"}
    workspace.items = {"namespace": [record]}
    assert workspace.item("namespace", "stable-key", "Title", "Issue", "New text") is record
    api.graphql.assert_not_called()


def test_unapproved_snapshot_is_rejected_before_reading_cases(tmp_path):
    path = tmp_path / "unreviewed.zip"
    path.write_bytes(b"not the immutable reviewed corpus")
    with pytest.raises(ValueError, match="approved frozen corpus"):
        reviewed_cases(path)


def test_wiki_publisher_does_not_overwrite_unmanaged_page(tmp_path):
    (tmp_path / "Home.md").write_text("New page")
    api = Mock()
    api.pages.return_value = [{"slug": "Home"}]
    api.request.return_value = {"content": "Maintainer's existing page"}
    with pytest.raises(ValueError, match="not managed"):
        publish(api, tmp_path)
    assert api.request.call_count == 1
    assert api.request.call_args.args[0] == "GET"


@pytest.mark.parametrize(
    "value",
    [{"nested": {"access_token": "redacted"}}, {"api_key": "redacted"}, {"password": "redacted"}],
)
def test_evidence_rejects_credential_fields_at_any_depth(value):
    with pytest.raises(ValueError, match="Credential"):
        reject_secrets(value)


def test_dashboard_only_reads_existing_service_metrics():
    body = dashboard()
    charts = body["gridLayout"]["widgets"][1:]
    assert len(charts) == 6
    for chart in charts:
        query = chart["xyChart"]["dataSets"][0]["timeSeriesQuery"]["timeSeriesFilter"]
        assert 'resource.type="gce_instance"' in query["filter"] or (
            'resource.type="cloud_run_revision"' in query["filter"]
        )
