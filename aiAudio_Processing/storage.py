import base64
import binascii
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
import uuid


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
                occurred_at REAL NOT NULL, expires_at REAL NOT NULL,
                event_kind TEXT NOT NULL DEFAULT 'legacy',
                acknowledged_at REAL
            )""")
            self._migrate(db)
            db.execute("CREATE INDEX IF NOT EXISTS events_time ON events(occurred_at, event_id)")
            # Shortening applies to old records; extending never renews them.
            db.execute("UPDATE events SET expires_at = MIN(expires_at, occurred_at + ?)", (self.retention_seconds,))
            self._prune(db)

    def _migrate(self, db):
        # Databases created before the live pipeline lack these columns.
        columns = {row[1] for row in db.execute("PRAGMA table_info(events)").fetchall()}
        if "event_kind" not in columns:
            db.execute("ALTER TABLE events ADD COLUMN event_kind TEXT NOT NULL DEFAULT 'legacy'")
        if "acknowledged_at" not in columns:
            db.execute("ALTER TABLE events ADD COLUMN acknowledged_at REAL")

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

    def save_event(self, event, kind="legacy"):
        event_json = json.dumps(event, allow_nan=False, sort_keys=True)
        timestamp = event.get("occurred_at") or event.get("captured_at") or event["processed_at"]
        occurred = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if occurred.tzinfo is None:
            raise ValueError("Event timestamp must include a timezone.")
        occurred_at = occurred.timestamp()
        with self.connection() as db:
            db.execute("""INSERT INTO events
                (event_id, event_json, occurred_at, expires_at, event_kind)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING""", (
                event["event_id"], event_json, occurred_at,
                occurred_at + self.retention_seconds, kind,
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

    def get_event(self, event_id):
        with self.connection() as db:
            self._prune(db)
            row = db.execute(
                "SELECT event_json FROM events WHERE event_id = ? AND event_kind = 'live'",
                (event_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def get_live_events(self, limit=50, before=None):
        where = "event_kind = ? AND expires_at > ?"
        params = ["live", self.clock()]
        if before is not None:
            occurred_at, event_id = decode_event_cursor(before)
            where += " AND (occurred_at < ? OR (occurred_at = ? AND event_id < ?))"
            params.extend([occurred_at, occurred_at, event_id])
        params.append(limit)
        with self.connection() as db:
            self._prune(db)
            rows = db.execute(f"""SELECT event_json, acknowledged_at, occurred_at, event_id
                FROM events WHERE {where}
                ORDER BY occurred_at DESC, event_id DESC LIMIT ?""", params).fetchall()
        items = [
            {"event": json.loads(row[0]), "acknowledged_at": format_epoch_utc(row[1])}
            for row in rows
        ]
        next_cursor = None
        if len(rows) == limit and rows:
            next_cursor = encode_event_cursor(rows[-1][2], rows[-1][3])
        return items, next_cursor

    def acknowledge(self, event_id):
        """Return (acknowledged_at, created); repeated acks keep the first time."""
        with self.connection() as db:
            self._prune(db)
            row = db.execute("SELECT acknowledged_at FROM events WHERE event_id = ?", (event_id,)).fetchone()
            if row is None:
                return None
            if row[0] is not None:
                return format_epoch_utc(row[0]), False
            now = self.clock()
            db.execute("UPDATE events SET acknowledged_at = ? WHERE event_id = ?", (now, event_id))
        return format_epoch_utc(now), True

    def clear_history(self):
        """Delete every stored event (local history privacy control)."""
        with self.connection() as db:
            return db.execute("DELETE FROM events").rowcount


DEFAULT_COOLDOWN_SECONDS = 10


@dataclass(frozen=True)
class Settings:
    revision: int
    capture_enabled: bool
    cloud_storage_enabled: bool
    analytics_enabled: bool
    speech_enabled: bool
    retention_days: int
    cooldown_seconds: int
    muted_until: str | None


class SettingsStore:
    """Single-row authoritative settings (architecture plan 5.5 and 7).

    Preferences persist, but native capture resets to disabled on every
    application launch even if it was previously enabled.
    """

    def __init__(self, path, retention_days=1, cooldown_seconds=DEFAULT_COOLDOWN_SECONDS):
        if retention_days not in (1, 7):
            raise ValueError("Retention must be 1 or 7 days.")
        if not 5 <= cooldown_seconds <= 60:
            raise ValueError("Cooldown must be between 5 and 60 seconds.")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                revision INTEGER NOT NULL,
                capture_enabled INTEGER NOT NULL,
                cloud_storage_enabled INTEGER NOT NULL,
                analytics_enabled INTEGER NOT NULL,
                speech_enabled INTEGER NOT NULL,
                retention_days INTEGER NOT NULL,
                cooldown_seconds INTEGER NOT NULL,
                muted_until TEXT
            )""")
            db.execute(
                "INSERT OR IGNORE INTO settings VALUES (1, 1, 0, 0, 0, 0, ?, ?, NULL)",
                (retention_days, cooldown_seconds),
            )
            # Native capture must be re-enabled explicitly on each launch.
            db.execute("UPDATE settings SET capture_enabled = 0 WHERE id = 1")

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            with db:
                yield db

    def get(self):
        with self.connection() as db:
            row = db.execute("""SELECT revision, capture_enabled, cloud_storage_enabled,
                analytics_enabled, speech_enabled, retention_days, cooldown_seconds, muted_until
                FROM settings WHERE id = 1""").fetchone()
        return Settings(
            revision=int(row[0]),
            capture_enabled=bool(row[1]),
            cloud_storage_enabled=bool(row[2]),
            analytics_enabled=bool(row[3]),
            speech_enabled=bool(row[4]),
            retention_days=int(row[5]),
            cooldown_seconds=int(row[6]),
            muted_until=row[7],
        )

    def set_capture_enabled(self, enabled):
        with self.connection() as db:
            db.execute(
                "UPDATE settings SET capture_enabled = ?, revision = revision + 1 WHERE id = 1",
                (1 if enabled else 0,),
            )
        return self.get()

    _WRITABLE = frozenset({
        "capture_enabled", "cloud_storage_enabled", "analytics_enabled",
        "speech_enabled", "retention_days", "cooldown_seconds", "muted_until",
    })

    def update(self, changes):
        fields = {key: value for key, value in changes.items() if key in self._WRITABLE}
        if not fields:
            return self.get()
        values = [int(value) if isinstance(value, bool) else value for value in fields.values()]
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.connection() as db:
            db.execute(
                f"UPDATE settings SET {assignments}, revision = revision + 1 WHERE id = 1",
                values,
            )
        return self.get()


class DeviceStore:
    """Minimal persistent device metadata: analytics identity and policy epoch.

    The analytics device ID is independent of any profile or user ID and is the
    only key the Snowflake adapter receives. The policy epoch advances whenever
    external consent changes or history is deleted (architecture plan 5.6).
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS device_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )""")

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            with db:
                yield db

    def _read(self, db, key):
        row = db.execute("SELECT value FROM device_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def analytics_device_id(self):
        with self.connection() as db:
            # INSERT OR IGNORE keeps one persistent ID even under races.
            db.execute(
                "INSERT OR IGNORE INTO device_meta (key, value) VALUES ('analytics_device_id', ?)",
                (str(uuid.uuid4()),),
            )
            return self._read(db, "analytics_device_id")

    def policy_epoch(self):
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO device_meta (key, value) VALUES ('policy_epoch', '0')")
            return int(self._read(db, "policy_epoch"))

    def advance_policy_epoch(self):
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO device_meta (key, value) VALUES ('policy_epoch', '0')")
            current = int(self._read(db, "policy_epoch"))
            db.execute("UPDATE device_meta SET value = ? WHERE key = 'policy_epoch'", (str(current + 1),))
        return current + 1


def format_epoch_utc(value):
    if value is None:
        return None
    moment = datetime.fromtimestamp(value, timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def encode_event_cursor(occurred_at, event_id):
    raw = f"{occurred_at:.6f}|{event_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_event_cursor(cursor):
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        occurred, _, event_id = raw.partition("|")
        return float(occurred), event_id
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise ValueError("Invalid cursor.") from None
