"""
M2 – Reference-to-metadata fetchers.

Priority order per retrieve_source():
  1. Crossref  (DOI resolve or title search)
  2. OpenAlex  (title search)
  3. arXiv     (title search)
  4. Unpaywall (DOI -> open-access PDF URL)
  5. Semantic Scholar (optional key)

All functions return raw dicts or None.  The caller (matcher.py / __init__.py) normalises
the result into a Source model.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any

from .config import CONTACT_EMAIL, S2_API_KEY
from .http_client import get_session

logger = logging.getLogger(__name__)

_CROSSREF_BASE = "https://api.crossref.org/works"
_OPENALEX_BASE = "https://api.openalex.org/works"
_ARXIV_BASE = "https://export.arxiv.org/api/query"
_UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
_S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    """Perform a GET request; return parsed JSON or None on error."""
    session = get_session()
    try:
        resp = session.get(url, params=params, headers=headers, timeout=session.timeout)  # type: ignore[attr-defined]
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("GET %s failed: %s", url, exc)
        return None


def _mailto_params(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"mailto": CONTACT_EMAIL}
    if extra:
        params.update(extra)
    return params


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------

def crossref_by_doi(doi: str) -> dict[str, Any] | None:
    """Fetch a Crossref work record by DOI."""
    url = f"{_CROSSREF_BASE}/{urllib.parse.quote(doi, safe='')}"
    data = _get(url, params=_mailto_params())
    if data and data.get("status") == "ok":
        return data.get("message")
    return None


def crossref_search_title(title: str) -> dict[str, Any] | None:
    """Return the top Crossref work matching *title*, or None."""
    params = _mailto_params({"query.title": title, "rows": 1, "select": "DOI,title,author,published,container-title,type,is-referenced-by-count,update-to"})
    data = _get(_CROSSREF_BASE, params=params)
    if not data:
        return None
    items = data.get("message", {}).get("items", [])
    return items[0] if items else None


def crossref_normalize(work: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a Crossref work record."""
    title_list = work.get("title") or []
    title = title_list[0] if title_list else ""
    authors: list[str] = []
    for a in work.get("author", []):
        given = a.get("given", "")
        family = a.get("family", "")
        authors.append(f"{given} {family}".strip() if given else family)
    year: int | None = None
    pub = work.get("published") or work.get("published-print") or work.get("published-online")
    if pub:
        dp = pub.get("date-parts", [[]])
        if dp and dp[0]:
            year = int(dp[0][0])
    doi = work.get("DOI")
    venue_list = work.get("container-title") or []
    venue = venue_list[0] if venue_list else None
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "venue": venue,
        "source_database": "crossref",
        "_raw": work,
    }


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

def openalex_search_title(title: str) -> dict[str, Any] | None:
    """Return the top OpenAlex work matching *title*, or None."""
    params = {
        "search": title,
        "per-page": 1,
        "mailto": CONTACT_EMAIL,
        "select": "id,doi,title,authorships,publication_year,primary_location,open_access",
    }
    data = _get(_OPENALEX_BASE, params=params)
    if not data:
        return None
    results = data.get("results", [])
    return results[0] if results else None


def openalex_normalize(work: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from an OpenAlex work record."""
    title = work.get("title", "")
    authors: list[str] = []
    for auth in work.get("authorships", []):
        name = auth.get("author", {}).get("display_name", "")
        if name:
            authors.append(name)
    year = work.get("publication_year")
    doi: str | None = None
    raw_doi = work.get("doi")  # "https://doi.org/10.xxx/yyy"
    if raw_doi:
        doi = raw_doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    # Open-access PDF
    oa = work.get("open_access", {})
    oa_url = oa.get("oa_url")
    loc = work.get("primary_location") or {}
    source_name = (loc.get("source") or {}).get("display_name")
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": oa_url,
        "venue": source_name,
        "source_database": "openalex",
        "_raw": work,
    }


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

def arxiv_search_title(title: str) -> dict[str, Any] | None:
    """Return the top arXiv result for *title*, or None."""
    import xml.etree.ElementTree as ET

    params = {
        "search_query": f"ti:{urllib.parse.quote(title)}",
        "max_results": 1,
        "sortBy": "relevance",
    }
    session = get_session()
    try:
        resp = session.get(_ARXIV_BASE, params=params, timeout=session.timeout)  # type: ignore[attr-defined]
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("arXiv search failed: %s", exc)
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", ns)
        if not entries:
            return None
        entry = entries[0]
        return {"_entry": entry, "_ns": ns}
    except ET.ParseError as exc:
        logger.warning("arXiv XML parse error: %s", exc)
        return None


def arxiv_normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from an arXiv API entry dict."""
    entry = raw["_entry"]
    ns = raw["_ns"]
    title = (entry.findtext("atom:title", default="", namespaces=ns) or "").replace("\n", " ").strip()
    authors = [
        (a.findtext("atom:name", default="", namespaces=ns) or "").strip()
        for a in entry.findall("atom:author", ns)
    ]
    year: int | None = None
    published = entry.findtext("atom:published", default="", namespaces=ns) or ""
    if published:
        try:
            year = int(published[:4])
        except ValueError:
            pass
    # arXiv ID and PDF
    arxiv_id = ""
    for link in entry.findall("atom:link", ns):
        if link.get("type") == "application/pdf":
            pdf_link = link.get("href", "")
            # e.g. https://arxiv.org/pdf/2301.00234v1
            arxiv_id = pdf_link.split("/pdf/")[-1].split("v")[0] if "/pdf/" in pdf_link else ""
            break
    id_url = entry.findtext("atom:id", default="", namespaces=ns) or ""
    if not arxiv_id and id_url:
        arxiv_id = id_url.rstrip("/").split("/")[-1].split("v")[0]
    doi: str | None = None
    doi_text = entry.findtext("{http://arxiv.org/schemas/atom}doi", default="", namespaces={}) or ""
    if doi_text:
        doi = doi_text.strip()
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": pdf_url,
        "venue": "arXiv",
        "source_database": "arxiv",
        "_raw": raw,
    }


# ---------------------------------------------------------------------------
# Unpaywall
# ---------------------------------------------------------------------------

def unpaywall_by_doi(doi: str) -> dict[str, Any] | None:
    """Return Unpaywall record for *doi*, or None."""
    url = f"{_UNPAYWALL_BASE}/{urllib.parse.quote(doi, safe='')}"
    data = _get(url, params={"email": CONTACT_EMAIL})
    return data  # already a dict or None


def unpaywall_pdf_url(record: dict[str, Any]) -> str | None:
    """Extract the best open-access PDF URL from an Unpaywall record."""
    best = record.get("best_oa_location") or {}
    url = best.get("url_for_pdf") or best.get("url")
    if url:
        return url
    for loc in record.get("oa_locations", []):
        u = loc.get("url_for_pdf") or loc.get("url")
        if u:
            return u
    return None


# ---------------------------------------------------------------------------
# Semantic Scholar (optional)
# ---------------------------------------------------------------------------

def s2_by_doi(doi: str) -> dict[str, Any] | None:
    """Fetch a Semantic Scholar paper record by DOI (optional key)."""
    url = f"{_S2_BASE}/DOI:{urllib.parse.quote(doi, safe='')}"
    headers: dict[str, str] = {}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY
    params = {"fields": "title,authors,year,externalIds,openAccessPdf,venue,isOpenAccess"}
    return _get(url, params=params, headers=headers or None)


def s2_search_title(title: str) -> dict[str, Any] | None:
    """Return the top Semantic Scholar result for *title*."""
    url = f"{_S2_BASE}/search"
    headers: dict[str, str] = {}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY
    params = {
        "query": title,
        "limit": 1,
        "fields": "title,authors,year,externalIds,openAccessPdf,venue,isOpenAccess",
    }
    data = _get(url, params=params, headers=headers or None)
    if not data:
        return None
    items = data.get("data", [])
    return items[0] if items else None


def s2_normalize(work: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical fields from a Semantic Scholar record."""
    title = work.get("title", "")
    authors = [a.get("name", "") for a in work.get("authors", [])]
    year = work.get("year")
    ext = work.get("externalIds", {})
    doi = ext.get("DOI")
    oa = work.get("openAccessPdf") or {}
    url = oa.get("url")
    venue = work.get("venue")
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": url,
        "venue": venue,
        "source_database": "semantic_scholar",
        "_raw": work,
    }
