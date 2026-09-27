from contextlib import closing, contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import time


class EventStore:
    """Persistent local metadata only. Raw audio is never stored here."""

    def __init__(self, path, retention_days=1, max_events=1000, clock=time.time):
        if retention_days not in (1, 7):
            raise ValueError("Retention must be 1 or 7 days.")
        if max_events < 1:
            raise ValueError("max_events must be positive.")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = retention_days * 86400
        self.max_events = max_events
        self.clock = clock
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, event_json TEXT NOT NULL,
                occurred_at REAL NOT NULL, expires_at REAL NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS events_time ON events(occurred_at, event_id)")
            # Shortening applies to old records; extending never renews them.
            db.execute("UPDATE events SET expires_at = MIN(expires_at, occurred_at + ?)", (self.retention_seconds,))
            self._prune(db)

    @contextmanager
    def connection(self):
        # Each thread owns its connection; transactions are serialized by SQLite.
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            with db:
                yield db

    def _prune(self, db):
        db.execute("DELETE FROM events WHERE expires_at <= ?", (self.clock(),))
        db.execute("""DELETE FROM events WHERE event_id IN (
            SELECT event_id FROM events ORDER BY occurred_at DESC, event_id DESC LIMIT -1 OFFSET ?
        )""", (self.max_events,))

    def purge(self):
        with self.connection() as db:
            self._prune(db)

    def save_event(self, event):
        event_json = json.dumps(event, allow_nan=False, sort_keys=True)
        timestamp = event.get("occurred_at") or event.get("captured_at") or event["processed_at"]
        occurred = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if occurred.tzinfo is None:
            raise ValueError("Event timestamp must include a timezone.")
        occurred_at = occurred.timestamp()
        with self.connection() as db:
            db.execute("""INSERT INTO events VALUES (?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING""", (
                event["event_id"], event_json, occurred_at, occurred_at + self.retention_seconds,
            ))
            existing = db.execute("SELECT event_json FROM events WHERE event_id = ?", (event["event_id"],)).fetchone()
            if existing[0] != event_json:
                raise ValueError("An event ID cannot be reused for different content.")
            self._prune(db)

    def get_events(self):
        with self.connection() as db:
            self._prune(db)
            rows = db.execute("""SELECT event_json FROM events WHERE expires_at > ?
                ORDER BY occurred_at DESC, event_id DESC LIMIT ?""", (self.clock(), self.max_events)).fetchall()
        return [json.loads(row[0]) for row in rows]
