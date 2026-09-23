import json
import threading
import urllib.request

from printer_sim.control import start_control
from printer_sim.state import PrinterState, Simulator


def _request(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def test_web_ui_served():
    printer = PrinterState(name="sim", port=0)
    simulator = Simulator([printer])
    httpd = start_control(simulator, "127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert "<!DOCTYPE html>" in body
            assert "Production Line Simulator" in body
        assert _request("GET", f"http://127.0.0.1:{port}/health")["ok"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_control_api():
    printer = PrinterState(name="sim", port=0)
    simulator = Simulator([printer])
    httpd = start_control(simulator, "127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        assert _request("GET", f"{base}/health")["ok"] is True
        assert "sim" in _request("GET", f"{base}/state")
        assert _request("GET", f"{base}/printers") == ["sim"]

        updated = _request("POST", f"{base}/printers/sim/faults", {"paper_out": True})
        assert updated["paper_out"] is True

        blocked = _request("POST", f"{base}/printers/sim/print", {"quantity": 4})
        assert blocked["total_labels"] == 0

        _request("POST", f"{base}/printers/sim/reset")
        printed = _request("POST", f"{base}/printers/sim/print", {"quantity": 4})
        assert printed["total_labels"] == 4

        reconfigured = _request(
            "POST", f"{base}/printers/sim/config", {"model": "ZEBRA ZT411-300dpi ZPL"}
        )
        assert reconfigured["model"] == "ZEBRA ZT411-300dpi ZPL"
    finally:
        httpd.shutdown()
        httpd.server_close()
