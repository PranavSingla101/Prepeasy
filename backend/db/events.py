import json
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "interviews.db"

# Canonical event type constants — always import these, never write the string inline
EVT_VAD_START = "vad_start"
EVT_VAD_END = "vad_end"
EVT_TRANSCRIPT_RECEIVED = "transcript_received"
EVT_QUESTION_ASKED = "question_asked"
EVT_INTERRUPTION = "interruption"
EVT_TTS_COMPLETE = "tts_complete"
EVT_SCORING_COMPLETE = "scoring_complete"
EVT_SESSION_END = "session_end"
EVT_DECISION_MADE = "decision_made"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            ts          REAL NOT NULL,
            payload     TEXT NOT NULL
        )
    """)


def log_event(session_id: str, event_type: str, payload: dict) -> None:
    """Write a session event row. Never raises — a write failure must not crash the voice pipeline."""
    try:
        payload_json = json.dumps(payload)
        ts = time.time()
        with _connect() as conn:
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO events (session_id, event_type, ts, payload) VALUES (?, ?, ?, ?)",
                (session_id, event_type, ts, payload_json),
            )
            conn.commit()
    except Exception as exc:
        logger.error(
            "log_event failed: session=%s type=%s error=%s", session_id, event_type, exc
        )
