import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from musichub import db
from musichub.backup import export_bundle, import_bundle
from musichub.config import ensure_dirs, get_paths


def test_export_import_bundle_roundtrip():
    old_home = os.environ.get("MUSICHUB_HOME")
    base = Path(__file__).parent.parent / "data" / "_test_backup_roundtrip"
    if base.exists():
        shutil.rmtree(base)
    os.environ["MUSICHUB_HOME"] = str(base)

    try:
        paths = get_paths()
        ensure_dirs(paths)
        db.init_db(paths)
        conn = db.connect(paths.db_path)
        try:
            conn.execute(
                "INSERT INTO feedback_events(occurred_at, kind, note) VALUES (?, ?, ?)",
                ("2026-02-27T10:00:00Z", "good", "cli:good"),
            )
            conn.commit()
        finally:
            conn.close()

        out_zip = base / "backup.zip"
        exported = export_bundle(paths, out_file=out_zip, include_events=False)
        assert exported["ok"] is True
        assert out_zip.exists()

        # overwrite DB with empty one, then import backup and verify content recovers
        paths.db_path.unlink()
        db.init_db(paths)
        imported = import_bundle(paths, in_file=out_zip, mode="replace")
        assert imported["ok"] is True

        conn = db.connect(paths.db_path)
        try:
            c = conn.execute("SELECT COUNT(*) AS c FROM feedback_events").fetchone()["c"]
            assert int(c) == 1
        finally:
            conn.close()
    finally:
        if old_home is None:
            os.environ.pop("MUSICHUB_HOME", None)
        else:
            os.environ["MUSICHUB_HOME"] = old_home
        if base.exists():
            shutil.rmtree(base)
