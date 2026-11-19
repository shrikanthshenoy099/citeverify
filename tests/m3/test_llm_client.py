"""
tests/m3/test_llm_client.py – Unit tests for common/llm_client.py.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.common.llm_client import (
    LLMError,
    LLMSchemaError,
    MockLLMClient,
    get_llm_client,
)


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string"},
        "explanation": {"type": "string"},
        "llm_certainty": {"type": "number"},
        "time_sensitive": {"type": "boolean"},
        "numbers_match": {"type": "boolean"},
    },
    "required": ["verdict", "explanation", "llm_certainty", "time_sensitive", "numbers_match"],
    "additionalProperties": False,
}


class TestMockLLMClient:
    def test_returns_dict(self):
        client = MockLLMClient()
        result = client.complete_json(
            system="sys",
            user="user prompt",
            schema=SIMPLE_SCHEMA,
        )
        assert isinstance(result, dict)

    def test_default_verdict_is_needs_review(self):
        client = MockLLMClient()
        result = client.complete_json("sys", "some query", SIMPLE_SCHEMA)
        assert result["verdict"] == "needs_review"

    def test_register_mock_key_match(self):
        client = MockLLMClient()
        custom = {
            "verdict": "supported",
            "explanation": "Direct support found.",
            "llm_certainty": 0.9,
            "time_sensitive": False,
            "numbers_match": True,
        }
        client.register_mock("MAGIC_KEYWORD", custom)
        result = client.complete_json("sys", "MAGIC_KEYWORD in user", SIMPLE_SCHEMA)
        assert result["verdict"] == "supported"

    def test_schema_validation_failure_raises(self):
        client = MockLLMClient()
        client.register_mock(
            "BAD_KEY",
            {
                "verdict": "supported",
                # missing required fields: explanation, llm_certainty, etc.
            },
        )
        with pytest.raises(LLMSchemaError):
            client.complete_json("sys", "BAD_KEY", SIMPLE_SCHEMA)

    def test_no_network_calls(self, monkeypatch):
        """MockLLMClient must never open a socket."""
        import socket

        original_connect = socket.socket.connect

        def fail_connect(self, *args, **kwargs):
            raise AssertionError("MockLLMClient must not make network calls")

        monkeypatch.setattr(socket.socket, "connect", fail_connect)
        client = MockLLMClient()
        client.complete_json("sys", "user", SIMPLE_SCHEMA)  # must not raise


class TestGetLlmClient:
    def test_default_is_mock(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        client = get_llm_client()
        assert isinstance(client, MockLLMClient)

    def test_invalid_provider_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "nonexistent_provider")
        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            get_llm_client()

    def test_http_provider_requires_env(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "http")
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        with pytest.raises(KeyError):
            get_llm_client()
