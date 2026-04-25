# Owner: CLAUDE — Phase 1 task T1.2
"""Minimal Google GenAI client for No Cap.

Drop-in from research.md [H1] §10. Routes to Gemma 4 (free, no system_instruction
config field, no response_schema) and Gemini 2.5 Flash-Lite (system_instruction +
response_schema supported).
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

# Load repo-root .env (one level up from nocap-council/) before reading env vars.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_REPO_ROOT_ENV)

log = logging.getLogger("nocap.client")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
if not _API_KEY:
    raise RuntimeError("Set GOOGLE_API_KEY (free tier from https://ai.dev)")

_client = genai.Client(api_key=_API_KEY)
_GEMMA_PREFIX = "gemma-"


def _is_gemma(model: str) -> bool:
    return model.startswith(_GEMMA_PREFIX)


def _build_config(model: str, system: str, json_schema: dict | None):
    if _is_gemma(model):
        return None
    cfg: dict[str, Any] = {"temperature": 0.2}
    if system:
        cfg["system_instruction"] = system
    if json_schema:
        cfg["response_mime_type"] = "application/json"
        cfg["response_schema"] = json_schema
    return types.GenerateContentConfig(**cfg)


def _build_contents(model: str, system: str, user: str):
    if _is_gemma(model) and system:
        return f"SYSTEM: {system}\n\nUSER: {user}"
    return user


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)


def call(
    model: str,
    system: str,
    user: str,
    json_schema: dict | None = None,
    max_retries: int = 5,
) -> str:
    cfg = _build_config(model, system, json_schema)
    contents = _build_contents(model, system, user)
    for attempt in range(max_retries):
        try:
            resp = _client.models.generate_content(model=model, contents=contents, config=cfg)
            text = resp.text or ""
            if json_schema or _is_gemma(model):
                text = _strip_fences(text)
            return text
        except errors.APIError as e:
            code = getattr(e, "code", None)
            if code == 429 and attempt < max_retries - 1:
                delay = getattr(e, "retry_delay_seconds", None) or (2**attempt + random.random())
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(f"call() exhausted {max_retries} retries for {model}")


def call_json(model: str, system: str, user: str, schema: dict) -> dict:
    raw = call(model, system, user, json_schema=schema)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raw = call(model, f"{system}\n\nReturn ONLY valid JSON, no prose.", user, json_schema=schema)
        return json.loads(raw)


if __name__ == "__main__":
    print("Gemma 4:", call("gemma-4-26b-a4b-it", "Be terse.", "Reply with exactly one word: ready"))
    print("Flash-Lite:", call("gemini-2.5-flash-lite", "Be terse.", "Reply with exactly one word: ready"))
