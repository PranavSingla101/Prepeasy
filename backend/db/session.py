import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "interviews.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id              TEXT PRIMARY KEY,
                filename        TEXT NOT NULL,
                raw_text        TEXT NOT NULL,
                structured_json TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
        """)
        conn.commit()


def save_resume(filename: str, raw_text: str, structured: dict) -> str:
    """Insert a resume row and return its UUID."""
    init_db()
    resume_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO resumes (id, filename, raw_text, structured_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (resume_id, filename, raw_text, json.dumps(structured), created_at),
        )
        conn.commit()
    return resume_id


def get_resume(resume_id: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["structured_json"] = json.loads(result["structured_json"])
    return result
