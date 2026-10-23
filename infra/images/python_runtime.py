"""Assemble a Python 3.12 service runtime with auditable native package metadata.

Interactive terminal, Tk and system UUID extensions are not service dependencies.
Python's uuid module retains its standard OS-random implementation.
"""

import json
import shutil
import subprocess
from pathlib import Path


def assemble() -> None:
    root = Path("/runtime")
    local = root / "usr/local"
    shutil.copytree(
        "/usr/local",
        local,
        ignore=shutil.ignore_patterns(
            "__pycache__", "pip", "pip-*", "uv", "uv-*", "include", "share"
        ),
    )
    excluded = ["_curses*", "readline*", "_tkinter*", "_uuid*"]
    for pattern in excluded:
        for path in (local / "lib/python3.12/lib-dynload").glob(pattern):
            path.unlink()
    packages = [
        "libbz2-1.0",
        "libcrypt1",
        "libdb5.3t64",
        "libffi8",
        "libgdbm6t64",
        "liblzma5",
        "libsqlite3-0",
    ]
    metadata = root / "var/lib/dpkg/status.d"
    metadata.mkdir(parents=True)
    for package in packages:
        files = subprocess.check_output(["dpkg-query", "-L", package], text=True).splitlines()
        for filename in files:
            source = Path(filename)
            if ".so" in source.name and source.is_file():
                target = root / source.relative_to("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target, follow_symlinks=True)
        status = subprocess.check_output(["dpkg-query", "-s", package], text=True)
        (metadata / package).write_text(status + "\n")
        copyright_file = Path("/usr/share/doc") / package / "copyright"
        if copyright_file.exists():
            target = root / copyright_file.relative_to("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copyright_file, target)
    manifest = root / "usr/share/pharmaguard/runtime-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"native_packages": packages, "excluded_extensions": excluded}))


if __name__ == "__main__":
    assemble()
