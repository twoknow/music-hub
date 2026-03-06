import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub import db


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = (Path(__file__).parent.parent / "musichub" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    return conn


def test_undo_feedback_event():
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO feedback_events(occurred_at, kind, note) VALUES (?, ?, ?)",
            ("2026-02-27T10:00:00Z", "good", "cli:good"),
        )
        undone = db.undo_last_user_action(conn)
        assert undone is not None
        assert undone["source_table"] == "feedback_events"
        left = conn.execute("SELECT COUNT(*) AS c FROM feedback_events").fetchone()["c"]
        assert int(left) == 0
    finally:
        conn.close()


def test_undo_next_event():
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO play_events(occurred_at, action, reason) VALUES (?, ?, ?)",
            ("2026-02-27T10:00:00Z", "next", "manual_next_cli"),
        )
        undone = db.undo_last_user_action(conn)
        assert undone is not None
        assert undone["source_table"] == "play_events"
        left = conn.execute("SELECT COUNT(*) AS c FROM play_events").fetchone()["c"]
        assert int(left) == 0
    finally:
        conn.close()
