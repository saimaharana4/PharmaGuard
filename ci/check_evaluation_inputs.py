"""Input acceleration must use immutable artifacts, never a cached gate result."""

import os
import re

for field in ["EVAL_RUNTIME_IMAGE", "EVAL_DATABASE_IMAGE"]:
    reference = os.environ[field]
    prefix = os.environ["CI_REGISTRY_IMAGE"] + "/evaluation-"
    if not reference.startswith(prefix) or not re.fullmatch(
        r"[a-z0-9./_-]+@sha256:[a-f0-9]{64}", reference
    ):
        raise SystemExit("Evaluation input images must be project-owned immutable digests")
print("Prepared evaluation input image references verified; gate results are never reused.")
