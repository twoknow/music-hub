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


def test_save_load_list_delete_session_roundtrip():
    conn = _conn()
    try:
        payload = {
            "0": {
                "path": "https://youtu.be/test",
                "media_title": "Test Song",
            }
        }
        db.save_session(conn, "work", payload)

        loaded = db.load_session(conn, "work")
        assert loaded == payload

        names = db.list_sessions(conn)
        assert names == ["work"]

        db.delete_session(conn, "work")
        assert db.load_session(conn, "work") is None
        assert db.list_sessions(conn) == []
    finally:
        conn.close()
