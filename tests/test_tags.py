from printer_sim.tags import BOOL, INT, STR, TagRegistry


def test_addresses_are_unique_per_table():
    registry = TagRegistry()
    coil = registry.add("cmd", BOOL, "rw")
    discrete = registry.add("state", BOOL, "ro")
    holding = registry.add("count", INT, "rw")
    inputs = registry.add("sensor", INT, "ro")
    assert (coil.table, coil.ref) == ("coil", 0)
    assert (discrete.table, discrete.ref) == ("discrete", 0)
    assert (holding.table, holding.ref) == ("holding", 0)
    assert (inputs.table, inputs.ref) == ("input", 0)
    assert registry.add("cmd2", BOOL, "rw").ref == 1


def test_set_respects_access_and_force():
    registry = TagRegistry()
    registry.add("ro", INT, "ro")
    registry.add("rw", INT, "rw")
    registry.set("ro", 5)
    assert registry.get("ro") == 0
    registry.set("ro", 5, force=True)
    assert registry.get("ro") == 5
    registry.set("rw", 7)
    assert registry.get("rw") == 7


def test_snapshot_contains_metadata():
    registry = TagRegistry()
    registry.add("product", STR, "ro", label="Продукт", initial="Молоко")
    snapshot = registry.snapshot()
    assert snapshot["product"]["value"] == "Молоко"
    assert snapshot["product"]["table"] == "input"
    assert snapshot["product"]["size"] == 16
    assert snapshot["product"]["access"] == "ro"
