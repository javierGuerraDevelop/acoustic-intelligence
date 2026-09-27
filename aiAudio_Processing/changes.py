"""In-memory change buffer backing GET /v1/state (architecture plan 5.4)."""

from __future__ import annotations

import threading
import uuid
from collections import deque

MAX_CHANGES = 500
MAX_RETURNED = 100


class ChangeBuffer:
    """Cursor changes for the polling dashboard; resets when state expires."""

    def __init__(self):
        self.instance_id = str(uuid.uuid4())
        self._lock = threading.Lock()
        self._cursor = 0
        self._changes: deque[dict] = deque(maxlen=MAX_CHANGES)

    def append(self, change_type, data, event_id=None):
        with self._lock:
            self._cursor += 1
            change = {"cursor": self._cursor, "type": change_type, "data": data}
            if event_id is not None:
                change["event_id"] = event_id
            self._changes.append(change)
            return self._cursor

    def poll(self, after, instance_id):
        """Return (changes, cursor, reset_required) for one state request."""
        with self._lock:
            if instance_id != self.instance_id or after is None or after > self._cursor:
                return [], self._cursor, True
            if after < self._cursor - len(self._changes):
                # The requested cursor fell out of the retained window.
                return [], self._cursor, True
            changes = [change for change in self._changes if change["cursor"] > after][:MAX_RETURNED]
            cursor = changes[-1]["cursor"] if changes else self._cursor
            return changes, cursor, False
