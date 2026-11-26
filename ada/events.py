"""In-process event bus for Ada's live dashboard."""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from contextlib import contextmanager

HISTORY_LIMIT = 400


class EventBus:
    def __init__(self, history_limit: int = HISTORY_LIMIT):
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue] = set()
        self._history: deque[dict] = deque(maxlen=history_limit)
        self._seq = 0

    def publish(self, event_type: str, **data) -> dict:
        with self._lock:
            self._seq += 1
            event = {
                "id": self._seq,
                "ts": time.time(),
                "type": event_type,
                "data": data,
            }
            if event_type != "token":
                self._history.append(event)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                pass
        return event

    def subscribe(self, after: int = 0) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(subscriber)
            for event in self._history:
                if event["id"] > after:
                    try:
                        subscriber.put_nowait(event)
                    except queue.Full:
                        break
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def snapshot(self) -> dict:
        with self._lock:
            events = list(self._history)
        states = [event for event in events if event["type"] == "state"]
        state = states[-1]["data"].get("state", "idle") if states else "idle"
        detail = states[-1]["data"].get("detail", "") if states else ""
        return {"state": state, "detail": detail, "events": events}


bus = EventBus()

# Per-thread suppression: sub-agents run in their own threads and should not
# flood the dashboard with their internal tool/state events. Lifecycle events
# are published with force=True from those threads.
_quiet = threading.local()


def set_quiet(quiet: bool) -> bool:
    """Enable/disable event suppression on the current thread; return previous state."""
    previous = bool(getattr(_quiet, "active", False))
    _quiet.active = bool(quiet)
    return previous


@contextmanager
def quiet_events():
    """Temporarily suppress ordinary events emitted on this thread."""
    previous = set_quiet(True)
    try:
        yield
    finally:
        set_quiet(previous)


def emit(event_type: str, *, force: bool = False, **data) -> dict | None:
    if getattr(_quiet, "active", False) and not force:
        return None
    return bus.publish(event_type, **data)


def emit_assistant(text: str, **extra) -> dict | None:
    """A finished assistant turn. The dashboard only leaves THINKING on these."""
    return emit("assistant", text=text, final=True, **extra)
