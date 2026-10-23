import zipfile
from datetime import date, datetime
from urllib.parse import urlencode

import httpx
from defusedxml import ElementTree as ET

from ingestion.sources.pubmed import node_text
from ingestion.storage import RawStore, get

BASE = "https://dailymed.nlm.nih.gov/dailymed/"
NS = {"h": "urn:hl7-org:v3"}


def label_date(value: str) -> date:
    return datetime.strptime(value, "%b %d, %Y").date()


def fetch(
    store: RawStore, drug: str, start: date, end: date, limit: int = 3, version_limit: int = 3
):
    assets, documents = [], []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        labels = get(
            client,
            BASE + "services/v2/spls.json",
            params={
                "drug_name": drug,
                "pagesize": limit,
            },
        ).json()["data"]
        for label in labels[:limit]:
            setid = label["setid"]
            history = get(client, BASE + f"services/v2/spls/{setid}/history.json").json()
            entries = history["data"]["history"]
            # Keep dated versions in the window, not a future latest-label substitution.
            versions = [
                entry for entry in entries if start <= label_date(entry["published_date"]) <= end
            ]
            for entry in versions[:version_limit]:
                version = str(entry["spl_version"])
                url = (
                    BASE
                    + "getFile.cfm?"
                    + urlencode({"type": "zip", "setid": setid, "version": version})
                )
                path, asset = store.download(url, "dailymed")
                assets.append(asset)
                with zipfile.ZipFile(path) as archive:
                    xmls = [name for name in archive.namelist() if name.lower().endswith(".xml")]
                    if len(xmls) != 1:
                        raise ValueError("DailyMed archive must contain one SPL XML document")
                    root = ET.fromstring(archive.read(xmls[0]))
                sections = []
                for section in root.findall(".//h:section", NS):
                    title = node_text(section.find("h:title", NS))
                    text = node_text(section.find("h:text", NS))
                    if text and any(
                        term in (title + " " + text).lower()
                        for term in [
                            "pancreat",
                            "warning",
                            "adverse",
                            "contraindication",
                        ]
                    ):
                        sections.append((title or "Label section") + "\n" + text)
                if not sections:
                    continue
                published = label_date(entry["published_date"])
                documents.append(
                    {
                        "source_type": "dailymed",
                        "external_id": setid,
                        "version": version,
                        "title": label["title"],
                        "text": "\n\n".join(sections),
                        "source_date": published,
                        "available_at": published,
                        "url": BASE + f"drugInfo.cfm?setid={setid}&version={version}",
                        "locator": f"SPL:{setid}:v{version}",
                        "raw_uri": asset["uri"],
                        "checksum": asset["sha256"],
                    }
                )
    return documents, assets
