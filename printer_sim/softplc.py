from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .line import LineEngine

OPS = ("==", "!=", "<", "<=", ">", ">=")


class SoftPlc:
    def __init__(
        self,
        line: LineEngine,
        *,
        rules: list[dict[str, Any]] | None = None,
        enabled: bool = True,
        file: str | Path | None = None,
    ) -> None:
        self.line = line
        self.tags = line.tags
        self.rules: list[dict[str, Any]] = list(rules or [])
        self.enabled = enabled
        self.file = Path(file) if file else None
        self.stats: dict[str, dict[str, Any]] = {}
        self._last: dict[str, bool] = {}
        self._lock = threading.Lock()
        if self.file and self.file.exists():
            self.load_json(self.file.read_text(encoding="utf-8"))

    def load_json(self, text: str) -> list[dict[str, Any]]:
        data = json.loads(text)
        rules = data.get("rules", data) if isinstance(data, dict) else data
        with self._lock:
            self.rules = list(rules or [])
            self._reset()
        self.save()
        return self.rules

    def export_json(self) -> str:
        return json.dumps({"rules": self.rules}, ensure_ascii=False, indent=2)

    def replace(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._lock:
            self.rules = list(rules)
            self._reset()
        self.save()
        return self.rules

    def upsert(self, rule: dict[str, Any]) -> dict[str, Any]:
        name = rule.get("name") or f"rule-{len(self.rules) + 1}"
        rule["name"] = name
        with self._lock:
            self.rules = [existing for existing in self.rules if existing.get("name") != name]
            self.rules.append(rule)
            self._last.pop(name, None)
        self.save()
        return rule

    def remove(self, name: str) -> bool:
        with self._lock:
            before = len(self.rules)
            self.rules = [rule for rule in self.rules if rule.get("name") != name]
            self._last.pop(name, None)
        self.save()
        return len(self.rules) != before

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def _reset(self) -> None:
        self._last.clear()
        self.stats = {}

    def save(self) -> None:
        if self.file:
            self.file.write_text(self.export_json(), encoding="utf-8")

    def tick(self, dt: float) -> None:
        if not self.enabled:
            return
        for rule in list(self.rules):
            name = str(rule.get("name", ""))
            if not rule.get("enabled", True):
                continue
            result = self._eval_when(rule.get("when", []))
            previous = self._last.get(name, False)
            self._last[name] = result
            fire = (result and not previous) if rule.get("edge") else result
            if fire:
                self._apply(rule.get("then", []))
                stat = self.stats.setdefault(name, {"fired": 0, "last": None, "active": False})
                stat["fired"] += 1
                stat["last"] = time.time()
            stat = self.stats.setdefault(name, {"fired": 0, "last": None, "active": False})
            stat["active"] = result

    def _eval_when(self, conditions: list[dict[str, Any]]) -> bool:
        if not conditions:
            return False
        for condition in conditions:
            actual = self.tags.get(str(condition.get("tag", "")))
            if not _compare(actual, condition.get("value"), str(condition.get("op", "=="))):
                return False
        return True

    def _apply(self, actions: list[dict[str, Any]]) -> None:
        for action in actions:
            if "set" in action:
                self.tags.set(
                    str(action["set"]), action.get("value"), force=bool(action.get("force"))
                )
            elif "control" in action:
                payload = {key: value for key, value in action.items() if key != "control"}
                self.line.control(str(action["control"]), payload)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "rules": self.rules,
                "stats": self.stats,
            }


def _compare(actual: Any, expected: Any, op: str) -> bool:
    if op not in OPS:
        return False
    try:
        if op == "==":
            return actual == expected
        if op == "!=":
            return actual != expected
        if op == "<":
            return actual < expected
        if op == "<=":
            return actual <= expected
        if op == ">":
            return actual > expected
        return actual >= expected
    except TypeError:
        return False
