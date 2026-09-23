from printer_sim.line import LineEngine
from printer_sim.state import PrinterState


def make_line() -> tuple[LineEngine, PrinterState]:
    printer = PrinterState(name="p1", port=0)
    line = LineEngine([printer])
    line.generation_interval = 0.1
    line.control("speed", {"speed": 2.0})
    return line, printer


def test_run_produces_prints_and_passes():
    line, printer = make_line()
    line.control("start")
    for _ in range(40):
        line.tick(0.1)

    assert line.counters["produced"] > 0
    assert line.counters["printed"] > 0
    assert line.counters["passed"] > 0
    assert printer.total_labels == line.counters["printed"]
    assert line.running is True


def test_scanner_fault_rejects_items():
    line, _ = make_line()
    line.control("start")
    line.control("scanner_fault", {"value": True})
    for _ in range(40):
        line.tick(0.1)
    assert line.counters["rejected"] > 0
    assert any(event.category == "reject" for event in line.events.recent())


def test_printer_fault_emits_print_error():
    line, printer = make_line()
    printer.paper_out = True
    line.control("start")
    for _ in range(40):
        line.tick(0.1)
    assert line.counters["printed"] == 0
    assert any(event.category == "print_error" for event in line.events.recent())


def test_jam_freezes_items():
    line, _ = make_line()
    line.control("start")
    for _ in range(8):
        line.tick(0.1)
    line.control("jam")
    line.tick(0.1)
    frozen = [item.pos for item in line.items]
    line.tick(0.1)
    assert [item.pos for item in line.items] == frozen
    assert line.jam is True


def test_changeover_updates_product_and_emits_event():
    line, _ = make_line()
    product = line.changeover("Кефир 0,5 л")
    assert product is not None
    assert line.current_product.name == "Кефир 0,5 л"
    assert line.tags.get("line.product") == "Кефир 0,5 л"
    assert any(event.category == "changeover" for event in line.events.recent())


def test_state_shape():
    line, _ = make_line()
    line.control("start")
    line.tick(0.1)
    state = line.state()
    assert state["running"] is True
    assert state["product"] == line.current_product.name
    assert any(station["kind"] == "printer" for station in state["stations"])
    assert set(state["counters"]) == {"produced", "passed", "rejected", "printed"}
