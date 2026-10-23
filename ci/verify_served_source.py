"""Require the HTTPS edge to serve this pipeline's actual application source."""

import json
import os
from pathlib import Path

from ci.protect_production import read_version


def verify(output: Path = Path("deployment/edge-version.json")) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    version = read_version(os.environ["WEB_URL"])
    if version["git_sha"] != os.environ["CI_COMMIT_SHA"]:
        raise ValueError("HTTPS edge source does not match this pipeline")
    output.write_text(json.dumps(version, indent=2), encoding="utf-8")


if __name__ == "__main__":
    verify()
