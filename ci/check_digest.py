import json
import os

for app in ["api", "web"]:
    with open(f"{app}-deployment.json") as handle:
        service = json.load(handle)
    expected = os.environ[f"{app.upper()}_IMAGE"]
    actual = service["spec"]["template"]["spec"]["containers"][0]["image"]
    if actual != expected or "@sha256:" not in actual:
        raise SystemExit(f"{app} deployment differs from the approved artifact")
    status = service["status"]
    if status.get("latestCreatedRevisionName") != status.get("latestReadyRevisionName"):
        raise SystemExit(f"{app} revision is not ready")
print("Both deployed services reference the approved immutable images")
