"""
common/llm_client.py – LLM adapter layer (owned by M3).

All CiteVerify code that needs an LLM must call this module.
Never import a model SDK directly in any other module.

Three concrete clients are provided:

  MockLLMClient         – deterministic, no network, default for tests.
  GenericHTTPLLMClient  – OpenAI-compatible chat/completions endpoint.
                          Configured via LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
  BobLLMClient          – IBM Bob adapter. ⚠️  NOT FINISHED.
                          Bob's exact API shape is not yet confirmed; this file
                          contains TODOs and will be completed once the details
                          are provided. All other modules keep working with
                          MockLLMClient or GenericHTTPLLMClient until then.

Client selection (env var LLM_PROVIDER):
  mock  → MockLLMClient           (default)
  http  → GenericHTTPLLMClient
  bob   → BobLLMClient

Public API
----------
Every client exposes exactly one method:

    complete_json(
        system: str,
        user: str,
        schema: dict,
        temperature: float = 0,
    ) -> dict

The returned dict is validated against *schema* (a JSON Schema object).
If the LLM returns invalid JSON or the dict does not conform to the schema,
LLMError is raised so callers can decide how to handle it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

import jsonschema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Raised when the LLM client cannot produce a valid response."""


class LLMTimeoutError(LLMError):
    """Raised when an LLM request times out."""


class LLMSchemaError(LLMError):
    """Raised when the LLM response does not match the expected JSON schema."""


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------


class LLMClient(ABC):
    """Abstract base class for all LLM adapters."""

    @abstractmethod
    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        temperature: float = 0,
    ) -> dict:
        """
        Call the language model and return a JSON-decoded dict.

        Parameters
        ----------
        system:      System / instruction prompt.
        user:        User / content prompt.
        schema:      JSON Schema dict the response MUST conform to.
        temperature: Sampling temperature (0 = deterministic).

        Returns
        -------
        A Python dict that validates against *schema*.

        Raises
        ------
        LLMSchemaError  – response is not valid JSON or violates the schema.
        LLMTimeoutError – request timed out.
        LLMError        – any other failure.
        """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_against_schema(data: Any, schema: dict) -> None:
    """Raise LLMSchemaError if *data* does not conform to *schema*."""
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise LLMSchemaError(f"LLM response schema mismatch: {exc.message}") from exc


def _parse_json_from_text(text: str) -> Any:
    """
    Extract JSON from a model reply that may wrap it in markdown code fences.

    Raises LLMSchemaError on parse failure.
    """
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (``` or ```json) and last line (```)
        inner = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        text = inner.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMSchemaError(f"LLM returned non-JSON text: {exc}") from exc


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------

# Default mock responses keyed by a substring present in the user prompt.
# The verification engine uses these keys to get predictable test output.
_MOCK_RESPONSES: dict[str, dict] = {
    "__default__": {
        "verdict": "needs_review",
        "explanation": (
            "Mock LLM response. No real analysis performed. "
            "This response is used in tests and when LLM_PROVIDER=mock."
        ),
        "llm_certainty": 0.5,
        "time_sensitive": False,
        "numbers_match": True,
        "scope_mismatch": False,
    }
}


class MockLLMClient(LLMClient):
    """
    Deterministic mock client for unit tests and local development.

    Returns pre-defined responses based on a simple keyword match in
    the *user* prompt. Falls back to a generic 'needs_review' verdict.
    You can inject custom responses via ``register_mock``.
    """

    def __init__(self) -> None:
        self._responses: dict[str, dict] = dict(_MOCK_RESPONSES)

    def register_mock(self, key: str, response: dict) -> None:
        """Register a mock response returned when *key* appears in the user prompt."""
        self._responses[key] = response

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        temperature: float = 0,
    ) -> dict:
        logger.debug("MockLLMClient.complete_json called (no network request).")
        for key, response in self._responses.items():
            if key != "__default__" and key in user:
                data = dict(response)
                break
        else:
            data = dict(self._responses["__default__"])

        _validate_against_schema(data, schema)
        return data


# ---------------------------------------------------------------------------
# GenericHTTPLLMClient  (OpenAI-compatible)
# ---------------------------------------------------------------------------


class GenericHTTPLLMClient(LLMClient):
    """
    Client for any OpenAI-compatible chat-completions endpoint.

    Env vars (all required when LLM_PROVIDER=http):
      LLM_BASE_URL  – e.g. "https://api.openai.com/v1"
      LLM_API_KEY   – bearer token
      LLM_MODEL     – model name, e.g. "gpt-4o-mini"

    Optional:
      LLM_TIMEOUT   – request timeout in seconds (default: 60)
      LLM_MAX_RETRIES – number of retries on 429/5xx (default: 3)
    """

    def __init__(self) -> None:
        self.base_url = os.environ["LLM_BASE_URL"].rstrip("/")
        self.api_key = os.environ["LLM_API_KEY"]
        self.model = os.environ["LLM_MODEL"]
        self.timeout = float(os.environ.get("LLM_TIMEOUT", "60"))
        self.max_retries = int(os.environ.get("LLM_MAX_RETRIES", "3"))

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        temperature: float = 0,
    ) -> dict:
        import urllib.request
        import urllib.error

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
        ).encode()

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read())

                content = body["choices"][0]["message"]["content"]
                data = _parse_json_from_text(content)
                _validate_against_schema(data, schema)
                return data

            except urllib.error.HTTPError as exc:
                status = exc.code
                if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "HTTP %d from LLM endpoint, retrying in %ds (attempt %d/%d).",
                        status, wait, attempt, self.max_retries,
                    )
                    time.sleep(wait)
                    last_exc = exc
                    continue
                raise LLMError(f"HTTP {status} from LLM endpoint: {exc.reason}") from exc

            except TimeoutError as exc:
                raise LLMTimeoutError(f"LLM request timed out after {self.timeout}s") from exc

            except LLMSchemaError:
                raise

            except Exception as exc:  # noqa: BLE001
                raise LLMError(f"Unexpected error calling LLM: {exc}") from exc

        raise LLMError(f"LLM request failed after {self.max_retries} retries.") from last_exc


# ---------------------------------------------------------------------------
# BobLLMClient  ⚠️  INCOMPLETE – awaiting IBM Bob API details
# ---------------------------------------------------------------------------


class BobLLMClient(LLMClient):
    """
    IBM Bob LLM adapter.

    ⚠️  THIS CLIENT IS NOT FINISHED.

    Bob's exact API shape (endpoint, auth mechanism, request/response format)
    has not been confirmed as of this writing.  The TODOs below mark every place
    that needs to be filled in once the details are available.

    Do NOT use LLM_PROVIDER=bob in production until the TODOs are resolved
    and the client has been tested end-to-end.

    Env vars (expected once Bob details are known):
      BOB_ENDPOINT – base URL of the Bob API  (TODO: confirm)
      BOB_API_KEY  – authentication token     (TODO: confirm auth mechanism)
    """

    def __init__(self) -> None:
        # TODO: confirm env var names and authentication mechanism with the team.
        self.endpoint = os.environ.get("BOB_ENDPOINT", "")
        self.api_key = os.environ.get("BOB_API_KEY", "")
        if not self.endpoint:
            raise LLMError(
                "BOB_ENDPOINT is not set. BobLLMClient cannot be used until "
                "IBM Bob API details are confirmed. Set LLM_PROVIDER=mock or "
                "LLM_PROVIDER=http in the meantime."
            )

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        temperature: float = 0,
    ) -> dict:
        # TODO: implement once IBM Bob's API contract is confirmed.
        #
        # Questions that need answers before this can be finished:
        #   1. Is Bob's endpoint OpenAI-compatible (/chat/completions)?
        #      If yes, GenericHTTPLLMClient already works; just configure env.
        #   2. What authentication header does Bob use (Bearer, x-api-key, …)?
        #   3. Does Bob support response_format: json_object?  If not, how do
        #      we reliably extract JSON from the reply?
        #   4. What are the rate limits and error codes to handle?
        #
        # Once answered, replace this NotImplementedError with the real call,
        # or simply subclass/delegate to GenericHTTPLLMClient if the endpoint
        # is OpenAI-compatible.
        raise NotImplementedError(
            "BobLLMClient is not yet implemented. "
            "See docstring and TODO comments in common/llm_client.py."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_llm_client() -> LLMClient:
    """
    Return the configured LLM client.

    Reads LLM_PROVIDER from the environment (default: "mock").
    """
    provider = os.environ.get("LLM_PROVIDER", "mock").lower().strip()
    if provider == "mock":
        logger.info("LLM provider: MockLLMClient (no network calls).")
        return MockLLMClient()
    if provider == "http":
        logger.info("LLM provider: GenericHTTPLLMClient (%s).", os.environ.get("LLM_BASE_URL", "?"))
        return GenericHTTPLLMClient()
    if provider == "bob":
        logger.info("LLM provider: BobLLMClient (⚠️  incomplete).")
        return BobLLMClient()
    raise ValueError(
        f"Unknown LLM_PROVIDER={provider!r}. Valid values: mock | http | bob"
    )
