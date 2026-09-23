from printer_sim.events import EventBus


def test_publish_and_recent_after_seq():
    bus = EventBus(limit=10)
    bus.publish("a", "one")
    second = bus.publish("b", "two", x=1)
    assert second.seq == 2
    assert [event.message for event in bus.recent(after=1)] == ["two"]
    assert second.data == {"x": 1}


def test_limit_and_clear():
    bus = EventBus(limit=2)
    for index in range(5):
        bus.publish("x", str(index))
    assert [event.message for event in bus.recent()] == ["3", "4"]
    bus.clear()
    assert bus.recent() == []
