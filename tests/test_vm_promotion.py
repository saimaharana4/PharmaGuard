import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def promote(tmp_path):
    """Exercise the real script with an SDK that models a pinned rollback route."""
    if os.name == "nt":
        git = Path(shutil.which("git")).resolve()
        bash = git.parent.parent / "bin" / "bash.exe"
    else:
        bash = shutil.which("bash")
    assert bash, "Bash is required to verify the deployment script"
    (tmp_path / "gcloud").write_text(
        r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$PROMOTION_STUB_DIR/calls"
case "$1 $2 $3" in
  'run deploy pharmaguard-web') [[ "$PROMOTION_FAILURE" != deploy ]] ;;
  'run services describe')
    if [[ "$PROMOTION_FAILURE" == revision ]]; then echo invalid;
    elif [[ "$*" == *latestCreatedRevisionName* ]]; then echo pharmaguard-web-00010-new;
    else echo pharmaguard-web-00008-old; fi ;;
  'run revisions describe')
    if [[ "$*" == *'json(status.conditions)'* ]]; then
      case "$PROMOTION_FAILURE" in
        malformed) echo not-json ;;
        missing) echo '{"status":{"conditions":[]}}' ;;
        False|Unknown)
          printf '{"status":{"conditions":[{"type":"Ready","status":"%s"}]}}' \
            "$PROMOTION_FAILURE" ;;
        *) echo '{"status":{"conditions":[{"type":"Ready","status":"True","reason":"Retired"}]}}' ;;
      esac
    elif [[ "$4" == pharmaguard-web-00008-old || "$PROMOTION_FAILURE" == digest ]]; then
      echo wrong-image
    else echo "$EDGE_IMAGE"; fi ;;
  'run services update-traffic')
    [[ "$*" == *'--to-revisions=pharmaguard-web-00010-new=100'* ]] || exit 98
    [[ "$PROMOTION_FAILURE" != traffic ]] || exit 43
    echo new > "$PROMOTION_STUB_DIR/edge" ;;
  'compute scp '*) : ;;
  'compute ssh pharmaguard-hackathon')
    [[ "$*" == *'--promote'* ]] || exit 97
    [[ "$PROMOTION_FAILURE" != vm ]] || exit 46
    echo new > "$PROMOTION_STUB_DIR/traffic" ;;
  *) exit 99 ;;
esac
""",
        encoding="utf-8",
        newline="\n",
    )
    (tmp_path / "python3").write_text(
        '#!/usr/bin/env bash\nexec "$PROMOTION_PYTHON" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    for name in ("gcloud", "python3"):
        (tmp_path / name).chmod(0o700)
    script = Path(__file__).resolve().parents[1] / "ci/promote_vm_edge.sh"

    def run(failure="none"):
        (tmp_path / "traffic").write_text("old")
        env = os.environ.copy()
        env.update(
            PROMOTION_FAILURE=failure,
            GCP_PROJECT_ID="test-project",
            GCP_REGION="test-region",
            WEB_URL="https://example.invalid",
            EDGE_IMAGE="registry.example/test/edge@sha256:" + "a" * 64,
            API_IMAGE="registry.example/test/api@sha256:" + "a" * 64,
            WEB_IMAGE="registry.example/test/web@sha256:" + "a" * 64,
            SQL_PROXY_IMAGE="registry.example/test/proxy@sha256:" + "a" * 64,
            RUNTIME_CONFIG_REFERENCE="projects/test/secrets/pg-config-runtime/versions/1",
            CLOUD_SQL_CONNECTION_NAME="project:region:database",
            VM_EXPIRES_AT="2100-01-01T00:00:00Z",
            CI_COMMIT_SHA="a" * 40,
            CI_JOB_ID="12345",
            GCP_ZONE="test-zone",
            PYTHONPATH=str(script.parents[1]),
        )
        wrapper = r"""
set -euo pipefail
if command -v cygpath >/dev/null; then
  export PROMOTION_STUB_DIR="$(cygpath -u "$1")"
  target="$(cygpath -u "$2")"
  export PROMOTION_PYTHON="$(cygpath -u "$3")"
else
  export PROMOTION_STUB_DIR="$1" PROMOTION_PYTHON="$3"
  target="$2"
fi
export PATH="$PROMOTION_STUB_DIR:$PATH"
[[ "$(command -v gcloud)" == "$PROMOTION_STUB_DIR/gcloud" ]]
bash "$target"
"""
        result = subprocess.run(
            [
                str(bash),
                "-c",
                wrapper,
                "promotion-test",
                str(tmp_path),
                str(script),
                sys.executable,
            ],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
        calls = (tmp_path / "calls").read_text()
        traffic = (tmp_path / "traffic").read_text().strip()
        return result, calls, traffic

    return run


def test_promotes_new_digest_when_latest_ready_is_an_older_revision(promote):
    result, _, traffic = promote()
    assert result.returncode == 0, result.stderr
    assert traffic == "new"


@pytest.mark.parametrize(
    "failure",
    ["deploy", "revision", "digest", "False", "Unknown", "missing", "malformed"],
)
def test_invalid_target_cannot_change_rollback_traffic(promote, failure):
    result, calls, traffic = promote(failure)
    assert result.returncode != 0
    assert traffic == "old"
    assert "services update-traffic" not in calls


def test_traffic_update_failure_remains_a_failed_job(promote):
    result, calls, traffic = promote("traffic")
    assert result.returncode != 0
    assert "services update-traffic" in calls
    assert traffic == "old"


def test_vm_promotion_failure_leaves_the_old_application_serving(promote):
    result, calls, traffic = promote("vm")
    assert result.returncode != 0
    assert "services update-traffic" in calls
    assert "--promote" in calls
    assert traffic == "old"
