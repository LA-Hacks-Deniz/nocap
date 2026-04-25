# Owner: CLAUDE — Phase 2 task T2.4
"""MongoDB Atlas trace logger — persists every council verdict.

Public API
----------

``log_verdict(verdict_dict: dict) -> str``

Stores the orchestrator's augmented verdict dict (see
``orchestrator.verify`` return shape) as a single document in
``nocap.traces`` and returns the inserted document's ``_id`` as a
string. The full verdict_dict is preserved verbatim; ``created_at``
(UTC ISO timestamp) plus the verdict's natural fields (``arxiv_id``,
``function_name``, ``verdict``, ``confidence``) are surfaced as
top-level fields so Atlas can index them without a custom projection.

The pymongo ``MongoClient`` is a module-level singleton — orchestrator
runs that log multiple verdicts (e.g. the smoke-adam clean+buggy pair)
share the same connection pool. ``MONGODB_URI`` is read from the
repo-root ``.env`` via ``python-dotenv``, mirroring ``client.py``.

Failure mode
------------

The orchestrator wraps ``log_verdict`` in a try/except and never lets
logging failures break a verification run; this module raises plain
exceptions on connect / insert errors.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient

_REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_REPO_ROOT_ENV)

_DB_NAME = "nocap"
_COLLECTION_NAME = "traces"
_SERVER_SELECTION_TIMEOUT_MS = 60_000

_client: MongoClient | None = None


def _get_collection():
    global _client
    if _client is None:
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI not set in environment (.env)")
        _client = MongoClient(uri, serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS)
    return _client[_DB_NAME][_COLLECTION_NAME]


def log_verdict(verdict_dict: dict[str, Any]) -> str:
    """Persist ``verdict_dict`` to ``nocap.traces``; return the inserted ``_id``.

    The full verdict_dict is stored verbatim; ``created_at`` (UTC ISO)
    is added so Atlas sorts by ingest time without parsing the
    document body.
    """
    doc: dict[str, Any] = {
        **verdict_dict,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "arxiv_id": verdict_dict.get("arxiv_id"),
        "function_name": verdict_dict.get("function_name"),
        "verdict": verdict_dict.get("verdict"),
        "confidence": verdict_dict.get("confidence"),
    }
    result = _get_collection().insert_one(doc)
    return str(result.inserted_id)
