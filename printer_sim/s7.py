from __future__ import annotations

import contextlib
import struct
import threading
from typing import Any

from .tags import BOOL, INT, REAL, STR, TagRegistry


class S7Server:
    protocol = "s7"

    def __init__(
        self,
        tags: TagRegistry,
        host: str = "0.0.0.0",
        port: int = 10102,
        db_number: int = 1,
    ) -> None:
        self.tags = tags
        self.host = host
        self.port = port
        self.db_number = db_number
        self.layout: dict[str, tuple[int, int, str]] = {}
        self.size = 1
        self._lock = threading.Lock()
        self._server: Any = None
        self._last: dict[str, Any] = {}
        self._build()

    def _build(self) -> None:
        offset = 0
        for tag in self.tags.all():
            align = 4 if tag.kind == REAL else (2 if tag.kind == INT else 1)
            offset = (offset + align - 1) & ~(align - 1)
            size = _size(tag.kind, tag.size)
            self.layout[tag.name] = (offset, size, tag.kind)
            offset += size
        self.size = max(offset, 1)
        self._data = bytearray(self.size)

    def start(self) -> None:
        import snap7.server
        import snap7.type

        server = snap7.server.Server()
        server.register_area(snap7.type.SrvArea.DB, self.db_number, self._data)
        if self.host in ("", "0.0.0.0"):
            server.start(self.port)
        else:
            server.start_to(self.host, self.port)
        self._server = server

    def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(Exception):
                self._server.stop()
            with contextlib.suppress(Exception):
                self._server.destroy()
            self._server = None

    def publish(self) -> None:
        with self._lock:
            for name, (offset, size, kind) in self.layout.items():
                tag = self.tags.tag(name)
                _encode(self._data, offset, size, kind, tag.value)
            self._last = {name: self.tags.get(name) for name in self.layout}

    def poll(self) -> None:
        with self._lock:
            for name, (offset, size, kind) in self.layout.items():
                tag = self.tags.tag(name)
                if tag is None or tag.access != "rw":
                    continue
                value = _decode(self._data, offset, size, kind)
                if value != self._last.get(name):
                    self.tags.set(name, value)
                    self._last[name] = value

    def describe(self) -> dict[str, Any]:
        return {
            "endpoint": f"{self.host}:{self.port}",
            "db": self.db_number,
            "size": self.size,
            "tags": {
                name: {"offset": offset, "size": size, "kind": kind}
                for name, (offset, size, kind) in self.layout.items()
            },
        }


def _size(kind: str, tag_size: int) -> int:
    if kind == BOOL:
        return 1
    if kind == INT:
        return 2
    if kind == REAL:
        return 4
    if kind == STR:
        return tag_size
    return tag_size


def _encode(buffer: bytearray, offset: int, size: int, kind: str, value: Any) -> None:
    if kind == BOOL:
        buffer[offset] = 1 if value else 0
    elif kind == INT:
        struct.pack_into(">h", buffer, offset, int(value or 0))
    elif kind == REAL:
        struct.pack_into(">f", buffer, offset, float(value or 0.0))
    elif kind == STR:
        raw = str(value or "").encode("utf-8")[:size].ljust(size, b"\x00")
        buffer[offset : offset + size] = raw


def _decode(buffer: bytearray, offset: int, size: int, kind: str) -> Any:
    if kind == BOOL:
        return bool(buffer[offset])
    if kind == INT:
        return struct.unpack_from(">h", buffer, offset)[0]
    if kind == REAL:
        return struct.unpack_from(">f", buffer, offset)[0]
    if kind == STR:
        return bytes(buffer[offset : offset + size]).split(b"\x00", 1)[0].decode("utf-8", "ignore")
    return None
