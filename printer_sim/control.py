from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .state import Simulator

CONTROL_ACTIONS = ("faults", "reset", "print", "config")
WEBUI_PATH = Path(__file__).resolve().parent / "webui.html"


def _webui() -> bytes:
    try:
        return WEBUI_PATH.read_bytes()
    except OSError:
        return b"<h1>production-line-sim</h1><p>Web UI is not bundled.</p>"


def make_handler(simulator: Simulator):
    class ControlHandler(BaseHTTPRequestHandler):
        server_version = "printer-sim"

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
            if len(parts) != 3 or parts[0] != "printers" or parts[2] not in CONTROL_ACTIONS:
                self._send(404, {"error": "not found"})
                return
            printer = simulator.get(parts[1])
            if printer is None:
                self._send(404, {"error": "unknown printer"})
                return
            body = self._body()
            action = parts[2]
            with simulator.lock:
                if action == "reset":
                    printer.reset()
                elif action == "faults":
                    printer.apply(body)
                elif action == "config":
                    printer.apply(body)
                elif action == "print":
                    printer.print_labels(int(body.get("quantity", 1)))
                self._send(200, printer.to_dict())

    return ControlHandler


def start_control(simulator: Simulator, host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(simulator))
    return httpd
