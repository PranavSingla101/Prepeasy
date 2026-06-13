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


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------

def _init_question_banks_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS question_banks (
            session_id    TEXT PRIMARY KEY,
            resume_name   TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            created_at    REAL NOT NULL
        )
    """)


def save_question_bank(bank) -> None:
    """Persist a QuestionBank to SQLite. Raises if session_id already exists."""
    import time
    from backend.schemas.questions import QuestionBank
    with _connect() as conn:
        _init_question_banks_table(conn)
        existing = conn.execute(
            "SELECT 1 FROM question_banks WHERE session_id = ?", (bank.session_id,)
        ).fetchone()
        if existing:
            raise ValueError(f"question_bank for session_id '{bank.session_id}' already exists")
        conn.execute(
            "INSERT INTO question_banks (session_id, resume_name, questions_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                bank.session_id,
                bank.resume_name,
                json.dumps(bank.model_dump()["questions"]),
                time.time(),
            ),
        )
        conn.commit()


def get_question_bank(session_id: str):
    """Fetch and validate a QuestionBank from SQLite by session_id."""
    from backend.schemas.questions import QuestionBank
    with _connect() as conn:
        _init_question_banks_table(conn)
        row = conn.execute(
            "SELECT * FROM question_banks WHERE session_id = ?", (session_id,)
        ).fetchone()
    if row is None:
        raise KeyError(f"No question_bank found for session_id '{session_id}'")
    return QuestionBank.model_validate({
        "session_id": row["session_id"],
        "resume_name": row["resume_name"],
        "questions": json.loads(row["questions_json"]),
    })


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------

def _ensure_scores_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            question_id TEXT NOT NULL,
            skipped     INTEGER NOT NULL,
            scores_json TEXT NOT NULL,
            ts          REAL NOT NULL,
            UNIQUE (session_id, question_id)
        )
    """)


def save_score(session_id: str, question_id: str, score_result) -> None:
    """Persist a ScoreResult to SQLite. Raises sqlite3.IntegrityError on duplicate."""
    import time
    ts = time.time()
    with _connect() as conn:
        _ensure_scores_table(conn)
        conn.execute(
            "INSERT INTO scores (session_id, question_id, skipped, scores_json, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                question_id,
                1 if score_result.skipped else 0,
                score_result.model_dump_json(),
                ts,
            ),
        )
        conn.commit()


def get_scores(session_id: str) -> list:
    """Return all ScoreResult objects for a session, ordered by ts ASC."""
    from backend.schemas.scoring import ScoreResult
    with _connect() as conn:
        _ensure_scores_table(conn)
        rows = conn.execute(
            "SELECT scores_json FROM scores WHERE session_id = ? ORDER BY ts ASC",
            (session_id,),
        ).fetchall()
    return [ScoreResult.model_validate_json(row["scores_json"]) for row in rows]


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------

def _ensure_transcripts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            question_id TEXT NOT NULL,
            speaker     TEXT NOT NULL,
            text        TEXT NOT NULL,
            ts          REAL NOT NULL
        )
    """)


def save_transcript_entry(session_id: str, entry) -> None:
    """Persist one TranscriptEntry to SQLite."""
    with _connect() as conn:
        _ensure_transcripts_table(conn)
        conn.execute(
            "INSERT INTO transcripts (session_id, question_id, speaker, text, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, entry.question_id, entry.speaker, entry.text, entry.ts),
        )
        conn.commit()


def get_transcripts(session_id: str) -> list:
    """Return TranscriptEntry rows for a session in chronological order."""
    from backend.schemas.session import TranscriptEntry
    with _connect() as conn:
        _ensure_transcripts_table(conn)
        rows = conn.execute(
            "SELECT speaker, text, question_id, ts FROM transcripts "
            "WHERE session_id = ? ORDER BY ts ASC, id ASC",
            (session_id,),
        ).fetchall()
    return [TranscriptEntry.model_validate(dict(row)) for row in rows]
