from printer_sim.line import LineEngine
from printer_sim.softplc import SoftPlc
from printer_sim.state import PrinterState


def make_line() -> LineEngine:
    printer = PrinterState(name="p1", port=0)
    line = LineEngine([printer])
    line.generation_interval = 0.1
    line.control("speed", {"speed": 2.0})
    return line


def test_rule_sets_command_tag():
    line = make_line()
    plc = SoftPlc(
        line,
        rules=[
            {
                "name": "jam_on_produce",
                "when": [{"tag": "line.produced", "op": ">=", "value": 1}],
                "then": [{"set": "line.jam", "value": True}],
            }
        ],
    )
    line.control("start")
    for _ in range(30):
        plc.tick(0.1)
        line.tick(0.1)
    assert line.jam is True
    assert plc.stats["jam_on_produce"]["fired"] >= 1


def test_edge_fires_once():
    line = make_line()
    plc = SoftPlc(
        line,
        rules=[
            {
                "name": "once",
                "edge": True,
                "when": [{"tag": "line.produced", "op": ">=", "value": 1}],
                "then": [{"control": "changeover", "product": "Кефир 0,5 л"}],
            }
        ],
    )
    line.control("start")
    for _ in range(20):
        plc.tick(0.1)
        line.tick(0.1)
    assert plc.stats["once"]["fired"] == 1
    assert line.current_product.name == "Кефир 0,5 л"


def test_disabled_plc_does_not_act():
    line = make_line()
    plc = SoftPlc(
        line,
        enabled=False,
        rules=[
            {
                "name": "x",
                "when": [{"tag": "line.produced", "op": ">=", "value": 1}],
                "then": [{"set": "line.jam", "value": True}],
            }
        ],
    )
    line.control("start")
    for _ in range(20):
        plc.tick(0.1)
        line.tick(0.1)
    assert line.jam is False


def test_replace_upsert_remove_and_persistence(tmp_path):
    line = make_line()
    path = tmp_path / "plc.json"
    plc = SoftPlc(line, file=path)

    plc.replace([{"name": "a", "when": [], "then": []}])
    assert path.exists()

    plc.upsert({"name": "b", "when": [], "then": []})
    assert {rule["name"] for rule in plc.rules} == {"a", "b"}

    assert plc.remove("a") is True
    assert plc.remove("zzz") is False
    assert [rule["name"] for rule in plc.rules] == ["b"]

    reloaded = SoftPlc(line, file=path)
    assert [rule["name"] for rule in reloaded.rules] == ["b"]
