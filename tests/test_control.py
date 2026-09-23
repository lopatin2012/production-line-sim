import json
import threading
import urllib.request

from printer_sim.control import start_control
from printer_sim.line import LineEngine
from printer_sim.softplc import SoftPlc
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


def test_line_api():
    printer = PrinterState(name="sim", port=0)
    simulator = Simulator([printer])
    line = LineEngine([printer])
    httpd = start_control(simulator, "127.0.0.1", 0, line=line)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        state = _request("GET", f"{base}/line/state")
        assert "stations" in state and "counters" in state
        assert any(station["kind"] == "printer" for station in state["stations"])

        _request("POST", f"{base}/line/control", {"action": "start"})
        line.tick(0.1)
        assert _request("GET", f"{base}/line/state")["running"] is True

        tags = _request("GET", f"{base}/tags")
        assert "line.running" in tags and tags["line.running"]["table"] == "discrete"

        _request("POST", f"{base}/tags", {"name": "line.speed", "value": 0.3})
        assert _request("GET", f"{base}/tags")["line.speed"]["value"] == 0.3

        assert isinstance(_request("GET", f"{base}/events"), list)

        _request(
            "POST", f"{base}/line/control", {"action": "changeover", "product": "Кефир 0,5 л"}
        )
        assert _request("GET", f"{base}/line/state")["product"] == "Кефир 0,5 л"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_protocols_endpoint():
    from printer_sim.modbus import ModbusServer

    printer = PrinterState(name="sim", port=0)
    simulator = Simulator([printer])
    line = LineEngine([printer])
    modbus = ModbusServer(line.tags, "127.0.0.1", 15020)
    httpd = start_control(simulator, "127.0.0.1", 0, line=line, adapters=[modbus])
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        protocols = _request("GET", f"{base}/protocols")
        assert protocols["modbus"]["tags"]["line.start"]["table"] == "coil"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_plc_api():
    printer = PrinterState(name="sim", port=0)
    simulator = Simulator([printer])
    line = LineEngine([printer])
    plc = SoftPlc(line)
    httpd = start_control(simulator, "127.0.0.1", 0, line=line, plc=plc)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        snapshot = _request("GET", f"{base}/plc")
        assert snapshot["enabled"] is True

        _request(
            "POST",
            f"{base}/plc/rules",
            {"rules": [{"name": "r1", "when": [], "then": []}]},
        )
        assert len(_request("GET", f"{base}/plc")["rules"]) == 1

        _request("POST", f"{base}/plc/enable", {"enabled": False})
        assert _request("GET", f"{base}/plc")["enabled"] is False

        _request("DELETE", f"{base}/plc/rules/r1")
        assert _request("GET", f"{base}/plc")["rules"] == []
    finally:
        httpd.shutdown()
        httpd.server_close()
