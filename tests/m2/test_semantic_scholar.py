"""Offline tests: no network needed (requests.get is mocked)."""
import requests

import semantic_scholar as s2


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


PAPER = {
    "paperId": "abc123",
    "title": "Attention Is All You Need",
    "year": 2017,
    "authors": [{"name": "Ashish Vaswani"}],
    "abstract": "The dominant sequence transduction models...",
    "venue": "NeurIPS",
    "externalIds": {"DOI": "10.5555/3295222.3295349"},
    "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762"},
}


def setup_function(_):
    s2._cache.clear()
    s2._MIN_INTERVAL = 0  # no sleeping in tests


def test_lookup_doi_ok(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(200, PAPER))
    out = s2.s2_lookup_doi("https://doi.org/10.5555/3295222.3295349")
    assert out["title"] == "Attention Is All You Need"
    assert out["pdf_url"].endswith("1706.03762")
    assert out["source_database"] == "semantic_scholar"


def test_lookup_doi_404_returns_none(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(404))
    assert s2.s2_lookup_doi("10.1/nope") is None


def test_network_error_returns_none(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    assert s2.s2_lookup_doi("10.1/x") is None


def test_429_retries_once(monkeypatch):
    monkeypatch.setattr(s2.time, "sleep", lambda *_: None)
    calls = []

    def fake_get(*a, **k):
        calls.append(1)
        return FakeResp(429) if len(calls) == 1 else FakeResp(200, PAPER)

    monkeypatch.setattr(requests, "get", fake_get)
    assert s2.s2_lookup_doi("10.1/retry")["title"]
    assert len(calls) == 2


def test_key_sent_in_header_not_url(monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "secret")
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return FakeResp(200, PAPER)

    monkeypatch.setattr(requests, "get", fake_get)
    s2.s2_lookup_doi("10.1/key")
    assert seen["headers"] == {"x-api-key": "secret"}
    assert "secret" not in seen["url"]


def test_search_title(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: FakeResp(200, {"data": [PAPER]})
    )
    assert s2.s2_search_title("Attention is all you need")["year"] == 2017


def test_empty_inputs():
    assert s2.s2_lookup_doi("") is None
    assert s2.s2_search_title("  ") is None