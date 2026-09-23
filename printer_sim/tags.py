from __future__ import annotations

import dataclasses
import threading
from typing import Any

BOOL = "bool"
INT = "int"
REAL = "real"
STR = "str"

_TABLES = ("coil", "discrete", "holding", "input")


@dataclasses.dataclass
class Tag:
    name: str
    kind: str
    access: str
    table: str
    ref: int
    size: int = 1
    label: str = ""
    unit: str = ""
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _size(kind: str) -> int:
    if kind == REAL:
        return 2
    if kind == STR:
        return 16
    return 1


class TagRegistry:
    def __init__(self) -> None:
        self._tags: dict[str, Tag] = {}
        self._counters = {table: 0 for table in _TABLES}
        self._lock = threading.Lock()

    def add(
        self,
        name: str,
        kind: str = BOOL,
        access: str = "rw",
        label: str = "",
        unit: str = "",
        initial: Any = None,
    ) -> Tag:
        table = self._table(kind, access)
        size = 1 if table in ("coil", "discrete") else _size(kind)
        ref = self._counters[table]
        self._counters[table] += size
        tag = Tag(
            name=name,
            kind=kind,
            access=access,
            table=table,
            ref=ref,
            size=size,
            label=label,
            unit=unit,
            value=initial if initial is not None else _default(kind),
        )
        self._tags[name] = tag
        return tag

    @staticmethod
    def _table(kind: str, access: str) -> str:
        if kind == BOOL:
            return "coil" if access == "rw" else "discrete"
        return "holding" if access == "rw" else "input"

    def set(self, name: str, value: Any, force: bool = False) -> None:
        with self._lock:
            tag = self._tags.get(name)
            if tag is None:
                return
            if tag.access == "ro" and not force:
                return
            tag.value = value

    def get(self, name: str) -> Any:
        with self._lock:
            tag = self._tags.get(name)
            return tag.value if tag is not None else None

    def tag(self, name: str) -> Tag | None:
        return self._tags.get(name)

    def all(self) -> list[Tag]:
        return list(self._tags.values())

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: tag.to_dict() for name, tag in self._tags.items()}


def _default(kind: str) -> Any:
    if kind == BOOL:
        return False
    if kind == INT:
        return 0
    if kind == REAL:
        return 0.0
    return ""
