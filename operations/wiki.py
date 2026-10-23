"""Publish managed Wiki pages; leave independently edited/unmanaged pages untouched."""

import argparse
from pathlib import Path
from urllib.parse import quote

from operations.gitlab import GitLab
from operations.workspace import PROJECT_ID

MARKER = "<!-- pharmaguard-managed-wiki -->"


def publish(api: GitLab, directory: Path) -> list[str]:
    endpoint = f"projects/{PROJECT_ID}/wikis"
    existing = {page["slug"]: page for page in api.pages(endpoint)}
    urls = []
    for path in sorted(directory.glob("*.md")):
        slug = path.stem
        content = MARKER + "\n\n" + path.read_text(encoding="utf-8")
        body = {"title": slug, "format": "markdown", "content": content}
        if slug in existing:
            detail = api.request("GET", endpoint + "/" + quote(slug, safe=""))
            if MARKER not in detail["content"]:
                raise ValueError(f"Wiki page is not managed by this publisher: {slug}")
            if detail["content"] != content:
                api.request("PUT", endpoint + "/" + quote(slug, safe=""), body)
        else:
            api.request("POST", endpoint, body)
        urls.append(slug)
    return urls


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--directory", type=Path, default=Path("docs/gitlab/wiki"))
    args = parser.parse_args()
    if args.apply:
        print(publish(GitLab(), args.directory))
    else:
        print([p.stem for p in args.directory.glob("*.md")])


if __name__ == "__main__":
    main()
