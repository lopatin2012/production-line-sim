from printer_sim.state import PrinterState


def _text(payload: bytes) -> str:
    return payload.decode("latin-1")


def test_host_identification():
    printer = PrinterState(name="p", model="ZEBRA ZD421-203dpi ZPL", firmware="V83.20.07Z")
    assert _text(printer.host_identification()) == (
        "\x02ZEBRA ZD421-203dpi ZPL,V83.20.07Z,8,4096KB,X\x03\r\n"
    )


def test_host_status_reflects_faults_and_counters():
    printer = PrinterState(name="p")
    printer.paper_out = True
    printer.head_up = True
    printer.ribbon_out = True
    printer.labels_remaining = 42

    lines = [line for line in _text(printer.host_status()).split("\r\n") if line]
    assert len(lines) == 3
    string1 = lines[0].strip("\x02\x03").split(",")
    string2 = lines[1].strip("\x02\x03").split(",")
    assert string1[1] == "1"
    assert string2[2] == "1"
    assert string2[3] == "1"
    assert string2[8] == "00000042"


def test_host_query_error_status_bits():
    printer = PrinterState(name="p")
    printer.paper_out = True
    printer.bad_head_elements = True
    printer.clean_printhead = True

    text = _text(printer.host_query_error_status())
    assert "ERRORS:   1 00000000 00000041" in text
    assert "WARNINGS: 1 00000000 00000002" in text


def test_print_labels_respects_faults():
    printer = PrinterState(name="p")
    assert printer.print_labels(5) == 5
    assert printer.total_labels == 5
    assert printer.total_print_length_mm > 0

    printer.paper_out = True
    assert printer.print_labels(5) == 0
    assert printer.total_labels == 5


def test_labels_remaining_decrements():
    printer = PrinterState(name="p", labels_remaining=10)
    printer.print_labels(4)
    assert printer.labels_remaining == 6
    printer.print_labels(100)
    assert printer.labels_remaining == 0


def test_apply_ignores_unknown_fields():
    printer = PrinterState(name="p")
    printer.apply({"paper_out": True, "nonsense": 1})
    assert printer.paper_out is True
    assert not hasattr(printer, "nonsense")


def test_reset_clears_faults_and_counters():
    printer = PrinterState(name="p", labels_remaining=3)
    printer.paper_out = True
    printer.bad_head_elements = True
    printer.total_labels = 9
    printer.reset()
    assert printer.paper_out is False
    assert printer.bad_head_elements is False
    assert printer.total_labels == 0
    assert printer.labels_remaining == 0
