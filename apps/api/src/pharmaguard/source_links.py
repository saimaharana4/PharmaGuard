"""Human-readable links derived from canonical version metadata, never from model output."""

from urllib.parse import parse_qs, urlencode, urlsplit


def readable_source_url(value: str) -> str:
    url = urlsplit(value)
    if url.scheme == "https" and url.hostname == "dailymed.nlm.nih.gov":
        query = parse_qs(url.query)
        if url.path == "/dailymed/getFile.cfm" and query.get("setid") and query.get("version"):
            return "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?" + urlencode(
                {
                    "setid": query["setid"][0],
                    "version": query["version"][0],
                }
            )
    return value
