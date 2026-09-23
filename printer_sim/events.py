from __future__ import annotations

import collections
import dataclasses
import threading
import time
from typing import Any


@dataclasses.dataclass
class Event:
    seq: int
    ts: float
    category: str
    message: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class EventBus:
    def __init__(self, limit: int = 300) -> None:
        self._events: collections.deque[Event] = collections.deque(maxlen=limit)
        self._seq = 0
        self._lock = threading.Lock()

    def publish(self, category: str, message: str, **data: Any) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(
                seq=self._seq,
                ts=time.time(),
                category=category,
                message=message,
                data=data,
            )
            self._events.append(event)
            return event

    def recent(self, limit: int = 50, after: int = 0) -> list[Event]:
        with self._lock:
            items = [event for event in self._events if event.seq > after]
        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
