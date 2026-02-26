PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    artist TEXT,
    duration_sec REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS track_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_id TEXT,
    source_url TEXT,
    source_title TEXT,
    source_artist TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_kind, source_url)
);

CREATE TABLE IF NOT EXISTS raw_mpv_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_hash TEXT NOT NULL UNIQUE,
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_name TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS play_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    source_url TEXT,
    source_kind TEXT,
    action TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    playback_time_sec REAL,
    duration_sec REAL,
    session_id TEXT
);

CREATE TABLE IF NOT EXISTS feedback_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    source_url TEXT,
    source_kind TEXT,
    kind TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    session_id TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS ingest_state (
    source_name TEXT PRIMARY KEY,
    offset_bytes INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_track_sources_track_id ON track_sources(track_id);
CREATE INDEX IF NOT EXISTS idx_play_events_track_id ON play_events(track_id);
CREATE INDEX IF NOT EXISTS idx_feedback_events_track_id ON feedback_events(track_id);
CREATE INDEX IF NOT EXISTS idx_feedback_events_kind ON feedback_events(kind);

