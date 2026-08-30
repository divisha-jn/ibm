"""
backend/api/chat.py

Persistent conversation memory backed by SQLite.

Stores one ChatTurn per row — the user query and the assistant response
(either a plain explanation string or a serialised WhatIfResponse JSON).
On page refresh the frontend calls GET /chat/history/{session_id} to
reload the full turn list and render it exactly as before.

No Granite calls here — this is pure storage.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

DB_PATH = Path(__file__).resolve().parents[2] / "backend" / "data" / "chat.db"

router = APIRouter()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_turns (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL,
                query           TEXT NOT NULL,
                type            TEXT NOT NULL,
                explanation     TEXT,
                whatif_response TEXT,
                risk_response   TEXT,
                error           TEXT,
                created_at      TEXT NOT NULL
            )
        """)
        # Add risk_response column to existing DBs that predate this migration
        try:
            conn.execute("ALTER TABLE chat_turns ADD COLUMN risk_response TEXT")
        except Exception:  # noqa: BLE001
            pass  # column already exists
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session "
            "ON chat_turns(session_id, id)"
        )
        conn.commit()


_ensure_schema()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SaveTurnRequest(BaseModel):
    session_id: str
    query: str
    type: str                          # "explain" | "whatif" | "risk"
    explanation: str | None = None     # set when type == "explain"
    whatif_response: dict[str, Any] | None = None  # set when type == "whatif"
    risk_response: dict[str, Any] | None = None    # set when type == "risk"
    error: str | None = None


class ChatTurnOut(BaseModel):
    query: str
    type: str
    explanation: str | None
    whatif_response: dict[str, Any] | None
    risk_response: dict[str, Any] | None
    error: str | None
    created_at: str


class HistoryResponse(BaseModel):
    session_id: str
    turns: list[ChatTurnOut]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/chat/history")
def save_turn(request: SaveTurnRequest) -> dict:
    """Persist one completed chat turn to SQLite."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chat_turns "
            "(session_id, query, type, explanation, whatif_response, risk_response, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.session_id,
                request.query,
                request.type,
                request.explanation,
                json.dumps(request.whatif_response) if request.whatif_response else None,
                json.dumps(request.risk_response) if request.risk_response else None,
                request.error,
                now,
            ),
        )
        conn.commit()
    return {"saved": True}


@router.get("/chat/history/{session_id}", response_model=HistoryResponse)
def get_history(session_id: str) -> HistoryResponse:
    """Return all turns for a session, oldest-first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT query, type, explanation, whatif_response, risk_response, error, created_at "
            "FROM chat_turns WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()

    turns = []
    for row in rows:
        whatif = None
        if row["whatif_response"]:
            try:
                whatif = json.loads(row["whatif_response"])
            except (json.JSONDecodeError, TypeError):
                pass
        risk = None
        if row["risk_response"]:
            try:
                risk = json.loads(row["risk_response"])
            except (json.JSONDecodeError, TypeError):
                pass
        turns.append(ChatTurnOut(
            query=row["query"],
            type=row["type"],
            explanation=row["explanation"],
            whatif_response=whatif,
            risk_response=risk,
            error=row["error"],
            created_at=row["created_at"],
        ))

    return HistoryResponse(session_id=session_id, turns=turns)
