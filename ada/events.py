"""In-process event bus for Ada's live dashboard."""

from __future__ import annotations

import queue
import threading
import time
from collections import deque

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


def emit(event_type: str, **data) -> dict:
    return bus.publish(event_type, **data)
