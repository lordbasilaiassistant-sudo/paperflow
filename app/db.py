import json
import sqlite3
import uuid
from datetime import UTC, datetime

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing',
    -- processing | auto_accepted | needs_review | approved | failed
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_type TEXT,
    page_count INTEGER,
    raw_text TEXT,
    extraction TEXT,        -- JSON: normalized fields
    model_confidence TEXT,  -- JSON: per-field self-reported confidence
    field_confidence TEXT,  -- JSON: blended per-field confidence
    validation_issues TEXT, -- JSON: list of issues
    doc_confidence REAL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    error TEXT
);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_document(conn: sqlite3.Connection, filename: str) -> str:
    doc_id = uuid.uuid4().hex[:12]
    now = _now()
    conn.execute(
        "INSERT INTO documents (id, filename, status, created_at, updated_at) VALUES (?, ?, 'processing', ?, ?)",
        (doc_id, filename, now, now),
    )
    conn.commit()
    return doc_id


def update_document(conn: sqlite3.Connection, doc_id: str, **fields) -> None:
    for key in ("extraction", "model_confidence", "field_confidence", "validation_issues"):
        if key in fields and not isinstance(fields[key], (str, type(None))):
            fields[key] = json.dumps(fields[key])
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE documents SET {cols} WHERE id = ?", (*fields.values(), doc_id))
    conn.commit()


def _hydrate(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    doc = dict(row)
    for key in ("extraction", "model_confidence", "field_confidence", "validation_issues"):
        if doc.get(key):
            doc[key] = json.loads(doc[key])
    return doc


def get_document(conn: sqlite3.Connection, doc_id: str) -> dict | None:
    return _hydrate(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())


def list_documents(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM documents WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [_hydrate(r) for r in rows]
