"""Drop-in async helper for calling the Gemini Decisions API inside ADK 2.x.

Why use httpx directly inside an ADK 2.x project today?
1. `google-adk==2.14.x` currently pins `google-genai>=2.30,<3.0`, whereas
   `client.decisions.create` was introduced in `google-genai>=3.2.0`. Calling
   `POST /v1beta/decisions` with `httpx` (already installed by `google-adk`)
   avoids any dependency conflict.
2. Using a persistent `httpx.Client` pool via `asyncio.to_thread` preserves warm
   TLS keep-alive sockets across separate ADK `Runner` / `anyio` task scopes.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional, Union

import httpx

DECISIONS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/decisions"
DEFAULT_DECISION_MODEL = "gemini-decision-1"


class DecisionsHelper:
    """Connection-pooled client for Gemini Decision 1 inside ADK FunctionNodes."""

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or os.getenv("GEMINI_DECISION_MODEL", DEFAULT_DECISION_MODEL)
        self._client: Optional[httpx.Client] = None

    def _get_api_key(self) -> str:
        key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is required. Export GEMINI_API_KEY from Google AI Studio "
                "(https://aistudio.google.com/api-keys) before running."
            )
        return key

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=30.0,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    def _post_sync(
        self,
        api_key: str,
        input_payload: Union[str, list[Dict[str, Any]]],
        questions: Dict[str, Any],
    ) -> tuple[Dict[str, Any], float]:
        client = self._get_client()
        start = time.perf_counter()
        resp = client.post(
            DECISIONS_ENDPOINT,
            headers={"x-goog-api-key": api_key},
            json={
                "model": self.model,
                "input": input_payload,
                "questions": questions,
            },
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        resp.raise_for_status()
        return resp.json(), latency_ms

    async def evaluate(
        self,
        input_payload: Union[str, list[Dict[str, Any]]],
        questions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Scores 1..1,000 isolated questions in a single pass (0 output tokens)."""
        api_key = self._get_api_key()
        data, latency_ms = await asyncio.to_thread(
            self._post_sync, api_key, input_payload, questions
        )
        usage = data.get("usage", {})
        in_tok = int(usage.get("total_input_tokens", 0))
        out_tok = int(usage.get("total_output_tokens", 0))

        return {
            "answers": data.get("answers", {}),
            "latency_ms": round(latency_ms, 2),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": round((in_tok / 1_000_000) * 0.10, 7),
        }

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()
