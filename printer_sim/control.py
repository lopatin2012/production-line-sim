from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .line import LineEngine
from .softplc import SoftPlc
from .state import Simulator

CONTROL_ACTIONS = ("faults", "reset", "print", "config")
WEBUI_PATH = Path(__file__).resolve().parent / "webui.html"


def _webui() -> bytes:
    try:
        return WEBUI_PATH.read_bytes()
    except OSError:
        return b"<h1>production-line-sim</h1><p>Web UI is not bundled.</p>"


def make_handler(
    simulator: Simulator,
    line: LineEngine | None = None,
    plc: SoftPlc | None = None,
    adapters: list | None = None,
):
    adapters = list(adapters or [])
    class ControlHandler(BaseHTTPRequestHandler):
        server_version = "production-line-sim"

        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _parts(self) -> list[str]:
            return [unquote(part) for part in urlparse(self.path).path.split("/") if part]

        def _query(self) -> dict[str, str]:
            values = parse_qs(urlparse(self.path).query)
            return {key: items[0] for key, items in values.items() if items}

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw or b"{}")
            except ValueError:
                return {}
            return parsed if isinstance(parsed, dict) else {}

        def do_GET(self) -> None:
            parts = self._parts()
            if parts in ([], ["ui"]):
                self._send_html(_webui())
                return
            if parts == ["health"]:
                self._send(200, {"ok": True, "printers": simulator.names()})
                return
            if parts == ["state"]:
                self._send(200, simulator.snapshot())
                return
            if parts == ["printers"]:
                self._send(200, simulator.names())
                return
            if parts == ["tags"] and line is not None:
                self._send(200, line.tags.snapshot())
                return
            if parts == ["events"] and line is not None:
                query = self._query()
                self._send(
                    200,
                    line.events_recent(
                        limit=int(query.get("limit", "50")),
                        after=int(query.get("after", "0")),
                    ),
                )
                return
            if parts == ["line", "state"] and line is not None:
                self._send(200, line.state())
                return
            if parts == ["plc"] and plc is not None:
                self._send(200, plc.snapshot())
                return
            if parts == ["protocols"]:
                self._send(
                    200,
                    {
                        adapter.protocol: adapter.describe()
                        for adapter in adapters
                        if hasattr(adapter, "describe")
                    },
                )
                return
            if len(parts) == 2 and parts[0] == "printers":
                printer = simulator.get(parts[1])
                if printer is None:
                    self._send(404, {"error": "unknown printer"})
                    return
                with simulator.lock:
                    self._send(200, printer.to_dict())
                return
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            parts = self._parts()
            body = self._body()
            if parts == ["line", "control"] and line is not None:
                result = line.control(str(body.get("action", "")), body)
                result["state"] = line.state()
                self._send(200 if result.get("ok") else 400, result)
                return
            if parts == ["tags"] and line is not None:
                name = str(body.get("name", ""))
                if line.tags.tag(name) is None:
                    self._send(404, {"error": "unknown tag"})
                    return
                line.tags.set(name, body.get("value"), force=True)
                self._send(200, line.tags.tag(name).to_dict())
                return
            if parts == ["plc", "rules"] and plc is not None:
                if "rules" in body:
                    plc.replace(list(body.get("rules") or []))
                elif "rule" in body:
                    plc.upsert(dict(body.get("rule") or {}))
                self._send(200, plc.snapshot())
                return
            if parts == ["plc", "enable"] and plc is not None:
                plc.set_enabled(bool(body.get("enabled", True)))
                self._send(200, plc.snapshot())
                return
            if len(parts) != 3 or parts[0] != "printers" or parts[2] not in CONTROL_ACTIONS:
                self._send(404, {"error": "not found"})
                return
            printer = simulator.get(parts[1])
            if printer is None:
                self._send(404, {"error": "unknown printer"})
                return
            action = parts[2]
            with simulator.lock:
                if action == "reset":
                    printer.reset()
                elif action in ("faults", "config"):
                    printer.apply(body)
                elif action == "print":
                    printer.print_labels(int(body.get("quantity", 1)))
                self._send(200, printer.to_dict())

        def do_DELETE(self) -> None:
            parts = self._parts()
            if len(parts) == 3 and parts[:2] == ["plc", "rules"] and plc is not None:
                removed = plc.remove(parts[2])
                self._send(200 if removed else 404, {"ok": removed, "state": plc.snapshot()})
                return
            self._send(404, {"error": "not found"})

    return ControlHandler


def start_control(
    simulator: Simulator,
    host: str,
    port: int,
    line: LineEngine | None = None,
    plc: SoftPlc | None = None,
    adapters: list | None = None,
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(simulator, line, plc, adapters))
    return httpd
