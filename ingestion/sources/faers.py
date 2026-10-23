"""Discover and stream FDA quarterly ASCII extracts without sampling the background."""

import calendar
import csv
import io
import re
import zipfile
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from ingestion.storage import get

FDA_PAGE = (
    "https://www.fda.gov/drugs/fda-adverse-event-monitoring-system-aems/"
    "fda-adverse-event-monitoring-system-aems-latest-quarterly-data-files"
)


class Release(BaseModel):
    release: str
    url: str
    quarter_end: date
    available_at: date
    availability_basis: str = "first_verified_download"


def quarter_end(year: int, quarter: int) -> date:
    month = quarter * 3
    return date(year, month, calendar.monthrange(year, month)[1])


def discover(start: date, end: date, availability: dict[str, str] | None = None) -> list[Release]:
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        try:
            response = get(client, FDA_PAGE)
        except httpx.HTTPError:
            return discover_from_bulk_manifest(client, start, end, availability)
    soup = BeautifulSoup(response.text, "html.parser")
    releases = {}
    for link in soup.select("a[href]"):
        url = urljoin(FDA_PAGE, link["href"])
        match = re.search(r"faers_ascii_(\d{4})q([1-4])\.zip", url, re.I)
        if not match:
            continue
        year, quarter = map(int, match.groups())
        final = quarter_end(year, quarter)
        if final < start or final > end:
            continue
        name = f"{year}Q{quarter}"
        known = (availability or {}).get(name)
        releases[name] = Release(
            release=name,
            url=url,
            quarter_end=final,
            available_at=date.fromisoformat(known) if known else datetime.now(UTC).date(),
            availability_basis="reviewed_source_manifest" if known else "first_verified_download",
        )
    if not releases:
        with httpx.Client(timeout=45, follow_redirects=True) as client:
            return discover_from_bulk_manifest(client, start, end, availability)
    return sorted(releases.values(), key=lambda item: item.quarter_end)


def discover_from_bulk_manifest(
    client: httpx.Client, start: date, end: date, availability: dict[str, str] | None = None
) -> list[Release]:
    """The official openFDA manifest identifies published quarters when the page moves.

    Probe the FDA's ASCII assets for those quarters; a missing archive is not invented.
    Last-Modified is a conservative availability bound for the exact downloaded asset.
    """
    manifest = get(client, "https://api.fda.gov/download.json").json()
    quarters = set()
    for partition in manifest["results"]["drug"]["event"]["partitions"]:
        match = re.match(r"(\d{4}) Q([1-4])", partition["display_name"])
        if match:
            year, quarter = map(int, match.groups())
            if start <= quarter_end(year, quarter) <= end:
                quarters.add((year, quarter))
    releases = []
    for year, quarter in sorted(quarters):
        name = f"{year}Q{quarter}"
        url = f"https://fis.fda.gov/content/Exports/faers_ascii_{year}q{quarter}.zip"
        response = client.head(url)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        if "zip" not in response.headers.get("content-type", ""):
            raise ValueError("FDA ASCII asset did not return a ZIP content type")
        known = (availability or {}).get(name)
        modified = response.headers.get("last-modified")
        available = (
            date.fromisoformat(known)
            if known
            else parsedate_to_datetime(modified).date()
            if modified
            else datetime.now(UTC).date()
        )
        releases.append(
            Release(
                release=name,
                url=url,
                quarter_end=quarter_end(year, quarter),
                available_at=available,
                availability_basis=(
                    "reviewed_source_manifest"
                    if known
                    else "object_last_modified"
                    if modified
                    else "first_verified_download"
                ),
            )
        )
    if not releases:
        raise ValueError("No verified FDA ASCII releases are available for the configured window")
    return releases


def rows(path: Path, prefix: str):
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if Path(name).name.upper().startswith(prefix.upper()) and name.lower().endswith(".txt")
        ]
        if len(names) != 1:
            raise ValueError(f"Expected exactly one {prefix} ASCII file")
        with archive.open(names[0]) as raw:
            handle = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="strict")
            if prefix.upper() == "DELETE":
                # FDA deletion notices are one ID per line, often with a blank header.
                for line, value in enumerate(handle, 1):
                    value = value.strip()
                    if not value or value.lower() == "caseid":
                        continue
                    if not value.isdigit():
                        raise ValueError(f"Malformed DELETE case ID at line {line}")
                    yield {"caseid": value}
                return
            reader = csv.DictReader(handle, delimiter="$", quoting=csv.QUOTE_NONE)
            if not reader.fieldnames:
                raise ValueError(f"Missing {prefix} headers")
            reader.fieldnames = [field.strip().lower() for field in reader.fieldnames]
            for line, row in enumerate(reader, 2):
                if None in row:
                    raise ValueError(f"Malformed {prefix} row at line {line}")
                yield {key: (value or "").strip() for key, value in row.items()}


def report_date(value: str) -> date:
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError("FAERS FDA_DT requires an unambiguous YYYYMMDD date")
    return datetime.strptime(value, "%Y%m%d").date()
