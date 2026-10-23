import calendar
import hashlib
from datetime import UTC, date, datetime
from urllib.parse import urlencode

import httpx
from defusedxml import ElementTree as ET

from ingestion.storage import RawStore, get

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


def node_text(node) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def parse_date(node, conservative: bool = True) -> date | None:
    if node is None:
        return None
    year = node.findtext("Year")
    if not year:
        return None
    month_value = node.findtext("Month")
    if not month_value:
        return date(int(year), 12 if conservative else 1, 31 if conservative else 1)
    try:
        month = int(month_value)
    except ValueError:
        month = datetime.strptime(month_value[:3], "%b").month
    day = node.findtext("Day")
    return date(int(year), month, int(day) if day else calendar.monthrange(int(year), month)[1])


def fetch(store: RawStore, drug: str, event: str, start: date, end: date, limit: int = 40):
    term = (
        f'"{drug}" AND "{event}" AND ("{start}"[Date - Publication] : "{end}"[Date - Publication])'
    )
    with httpx.Client(timeout=60) as client:
        search = get(
            client,
            BASE + "esearch.fcgi",
            params={
                "db": "pubmed",
                "term": term,
                "retmode": "json",
                "retmax": limit,
                "sort": "pub date",
                "tool": "PharmaGuard",
            },
        ).json()
    ids = search["esearchresult"]["idlist"]
    if not ids:
        raise ValueError("No PubMed records match the configured source window and entities")
    url = (
        BASE
        + "efetch.fcgi?"
        + urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml", "tool": "PharmaGuard"})
    )
    path, asset = store.download(url, "pubmed")
    root = ET.parse(path).getroot()
    documents = []
    for article in root.findall("PubmedArticle"):
        citation = article.find("MedlineCitation")
        pmid = citation.findtext("PMID")
        title = node_text(citation.find("Article/ArticleTitle"))
        body = "\n".join(
            node_text(item) for item in citation.findall("Article/Abstract/AbstractText")
        )
        if not body:
            continue
        publication = parse_date(citation.find("Article/Journal/JournalIssue/PubDate"))
        electronic = [parse_date(item) for item in citation.findall("Article/ArticleDate")]
        publication_dates = [x for x in [publication, *electronic] if x]
        if not publication_dates:
            continue  # Ambiguous dates are quarantined by exclusion, never fabricated.
        published = min(publication_dates)
        indexed_dates = [
            parse_date(item)
            for item in article.findall("PubmedData/History/PubMedPubDate")
            if item.attrib.get("PubStatus") in ["pubmed", "entrez"]
        ]
        indexed = [x for x in indexed_dates if x]
        known = version_available_at(citation, published, indexed)
        if start <= published <= end and known <= end:
            documents.append(
                {
                    "source_type": "pubmed",
                    "external_id": pmid,
                    "version": hashlib.sha256(ET.tostring(article)).hexdigest(),
                    "title": title,
                    "text": title + "\n" + body,
                    "source_date": published,
                    "available_at": known,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "locator": f"PMID:{pmid}",
                    "raw_uri": asset["uri"],
                    "checksum": asset["sha256"],
                }
            )
    return documents, [asset]


def version_available_at(citation, published: date, indexed: list[date]) -> date:
    """Current XML cannot be backdated before its last documented record revision."""
    first_indexed = min(indexed) if indexed else datetime.now(UTC).date()
    revised = parse_date(citation.find("DateRevised"))
    # Without revision metadata, conservatively use the first verified retrieval date.
    return max(published, first_indexed, revised or datetime.now(UTC).date())
