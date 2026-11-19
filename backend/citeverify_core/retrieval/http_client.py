"""
M2 – HTTP session factory with retry/backoff and timeout.
"""
from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import HTTP_BACKOFF_FACTOR, HTTP_MAX_RETRIES, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


def build_session(*, extra_headers: dict[str, str] | None = None) -> requests.Session:
    """Return a :class:`requests.Session` with retry logic and a default timeout.

    Parameters
    ----------
    extra_headers:
        Additional HTTP headers to merge into the session defaults.
    """
    retry = Retry(
        total=HTTP_MAX_RETRIES,
        backoff_factor=HTTP_BACKOFF_FACTOR,
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET", "HEAD"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if extra_headers:
        session.headers.update(extra_headers)
    # Store timeout so callers can pass it to request()
    session.timeout = HTTP_TIMEOUT  # type: ignore[attr-defined]
    return session


_SESSION: requests.Session | None = None


def get_session() -> requests.Session:
    """Return the module-level shared session (created lazily)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = build_session()
    return _SESSION
