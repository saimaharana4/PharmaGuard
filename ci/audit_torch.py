"""Audit the upstream version when the advisory database skips a CPU-local wheel tag."""

import subprocess
import tempfile
import tomllib
from pathlib import Path

packages = tomllib.loads(Path("uv.lock").read_text())["package"]
versions = {item["version"].split("+", 1)[0] for item in packages if item["name"] == "torch"}
if len(versions) != 1:
    raise SystemExit("Exactly one locked upstream PyTorch version is required")
with tempfile.TemporaryDirectory(prefix="pharmaguard-audit-") as directory:
    requirement = Path(directory) / "torch.txt"
    requirement.write_text("torch==" + versions.pop() + "\n")
    subprocess.run(
        ["uv", "run", "pip-audit", "--disable-pip", "--no-deps", "-r", str(requirement)],
        check=True,
    )
