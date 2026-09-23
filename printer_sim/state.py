from __future__ import annotations

import dataclasses
import threading
from typing import Any

PRINT_MODE_CODES: dict[str, str] = {
    "Rewind": "0",
    "Peel-Off": "1",
    "Tear-Off": "2",
    "Cutter": "3",
    "Applicator": "4",
    "Delayed cut": "5",
    "Linerless Peel": "6",
    "Linerless Rewind": "7",
    "Partial Cutter": "8",
    "RFID": "9",
    "Kiosk": "K",
}

STATUS_FIELDS = frozenset(
    {
        "model",
        "firmware",
        "dots_per_mm",
        "memory_kb",
        "options",
        "comm_settings",
        "label_length_dots",
        "print_mode",
        "print_width_mode",
        "images_in_memory",
        "paper_out",
        "paused",
        "head_up",
        "ribbon_out",
        "buffer_full",
        "corrupt_ram",
        "under_temperature",
        "over_temperature",
        "cutter_fault",
        "head_over_temperature",
        "motor_over_temperature",
        "bad_head_elements",
        "head_detection_error",
        "clean_printhead",
        "thermal_transfer",
        "label_waiting",
        "labels_remaining",
        "total_labels",
        "total_print_length_mm",
    }
)

_FAULT_FIELDS = (
    "paper_out",
    "paused",
    "head_up",
    "ribbon_out",
    "buffer_full",
    "corrupt_ram",
    "under_temperature",
    "over_temperature",
    "cutter_fault",
    "head_over_temperature",
    "motor_over_temperature",
    "bad_head_elements",
    "head_detection_error",
    "clean_printhead",
    "label_waiting",
)


@dataclasses.dataclass
class PrinterState:
    name: str = "printer"
    port: int = 9100
    model: str = "ZEBRA ZD421-203dpi ZPL"
    firmware: str = "V83.20.07Z"
    dots_per_mm: int = 8
    memory_kb: int = 4096
    options: str = "X"
    comm_settings: int = 6
    label_length_dots: int = 1576
    print_mode: str = "2"
    print_width_mode: int = 0
    images_in_memory: int = 0
    paper_out: bool = False
    paused: bool = False
    head_up: bool = False
    ribbon_out: bool = False
    buffer_full: bool = False
    corrupt_ram: bool = False
    under_temperature: bool = False
    over_temperature: bool = False
    cutter_fault: bool = False
    head_over_temperature: bool = False
    motor_over_temperature: bool = False
    bad_head_elements: bool = False
    head_detection_error: bool = False
    clean_printhead: bool = False
    thermal_transfer: bool = True
    label_waiting: bool = False
    labels_remaining: int = 0
    total_labels: int = 0
    total_print_length_mm: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def apply(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in STATUS_FIELDS:
                setattr(self, key, value)

    def reset(self) -> None:
        for field in _FAULT_FIELDS:
            setattr(self, field, False)
        self.thermal_transfer = True
        self.labels_remaining = 0
        self.total_labels = 0
        self.total_print_length_mm = 0

    def can_print(self) -> bool:
        return not (self.paper_out or self.head_up or self.ribbon_out or self.paused)

    def host_identification(self) -> bytes:
        text = (
            f"{self.model},{self.firmware},{self.dots_per_mm},"
            f"{self.memory_kb}KB,{self.options}"
        )
        return _frame(text)

    def host_status(self) -> bytes:
        string1 = (
            f"{self.comm_settings:03d},{int(self.paper_out)},{int(self.paused)},"
            f"{self.label_length_dots:04d},000,{int(self.buffer_full)},0,0,000,"
            f"{int(self.corrupt_ram)},{int(self.under_temperature)},{int(self.over_temperature)}"
        )
        string2 = (
            f"000,0,{int(self.head_up)},{int(self.ribbon_out)},{int(self.thermal_transfer)},"
            f"{self.print_mode},{self.print_width_mode},{int(self.label_waiting)},"
            f"{self.labels_remaining:08d},1,{self.images_in_memory:03d}"
        )
        string3 = "4230,0"
        return _frame(string1) + _frame(string2) + _frame(string3)

    def error_bits(self) -> int:
        bits = 0
        if self.paper_out:
            bits |= 0x01
        if self.ribbon_out:
            bits |= 0x02
        if self.head_up:
            bits |= 0x04
        if self.cutter_fault:
            bits |= 0x08
        if self.head_over_temperature:
            bits |= 0x10
        if self.motor_over_temperature:
            bits |= 0x20
        if self.bad_head_elements:
            bits |= 0x40
        if self.head_detection_error:
            bits |= 0x80
        return bits

    def warning_bits(self) -> int:
        return 0x02 if self.clean_printhead else 0

    def host_query_error_status(self) -> bytes:
        errors = self.error_bits()
        warnings = self.warning_bits()
        text = (
            "PRINTER STATUS\r\n"
            f"ERRORS:   {int(bool(errors))} 00000000 {errors:08X}\r\n"
            f"WARNINGS: {int(bool(warnings))} 00000000 {warnings:08X}\r\n"
        )
        return _frame(text)

    def print_labels(self, quantity: int) -> int:
        if quantity <= 0 or not self.can_print():
            return 0
        self.total_labels += quantity
        self.total_print_length_mm += quantity * self.label_length_dots // max(self.dots_per_mm, 1)
        self.labels_remaining = max(self.labels_remaining - quantity, 0)
        return quantity


def _frame(text: str) -> bytes:
    return b"\x02" + text.encode("latin-1", "replace") + b"\x03\r\n"


class Simulator:
    def __init__(self, printers: list[PrinterState]) -> None:
        self._printers: dict[str, PrinterState] = {printer.name: printer for printer in printers}
        self.lock = threading.Lock()

    def names(self) -> list[str]:
        return list(self._printers)

    def get(self, name: str) -> PrinterState | None:
        return self._printers.get(name)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            return {name: printer.to_dict() for name, printer in self._printers.items()}
