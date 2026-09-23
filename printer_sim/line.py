from __future__ import annotations

import dataclasses
import random
import threading
import time
from typing import Any

from .events import EventBus
from .state import PrinterState
from .tags import BOOL, INT, REAL, STR, TagRegistry

VERIFY_FAIL_RATE = 0.03


@dataclasses.dataclass
class ProductDef:
    name: str
    color: str = "#2f81f7"
    gtin: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Item:
    id: int
    product: ProductDef
    pos: float = 0.0
    prev: float = 0.0
    printed: bool = False
    applied: bool = False
    inspected: bool = False
    verified: bool | None = None
    rejected: bool = False
    removed: bool = False


@dataclasses.dataclass
class Station:
    name: str
    kind: str
    pos: float
    label: str = ""
    printer: PrinterState | None = None
    capacity: int = 6
    last_active: float = 0.0


def default_products() -> list[ProductDef]:
    return [
        ProductDef("Молоко 1 л", "#2f81f7", "04600000000012"),
        ProductDef("Кефир 0,5 л", "#3fb950", "04600000000029"),
        ProductDef("Сметана 0,3 л", "#d29922", "04600000000036"),
    ]


def build_stations(printers: list[PrinterState]) -> list[Station]:
    stations: list[Station] = [Station("infeed", "sensor", 0.08, "Датчик входа")]
    count = max(len(printers), 1)
    for index, printer in enumerate(printers):
        base = 0.3 + (0.16 * index if count > 1 else 0.0)
        stations.append(
            Station(f"sensor-{printer.name}", "sensor", base - 0.05, f"Датчик {printer.name}")
        )
        stations.append(
            Station(f"printer-{printer.name}", "printer", base, printer.name, printer=printer)
        )
    stations.append(Station("applicator", "applicator", 0.7, "Аппликатор"))
    stations.append(Station("camera", "camera", 0.77, "Камера"))
    stations.append(Station("scanner", "scanner", 0.84, "Сканер DataMatrix"))
    stations.append(Station("reject", "reject", 0.9, "Отвод брака"))
    stations.append(Station("accumulator", "accumulator", 0.96, "Накопитель", capacity=6))
    return sorted(stations, key=lambda station: station.pos)


class LineEngine:
    def __init__(
        self,
        printers: list[PrinterState],
        *,
        events: EventBus | None = None,
        tags: TagRegistry | None = None,
        products: list[ProductDef] | None = None,
        seed: int = 1234,
    ) -> None:
        self.events = events or EventBus()
        self.tags = tags or TagRegistry()
        self.products = products or default_products()
        self.current_product = self.products[0]
        self.printers = list(printers)
        self.stations = build_stations(self.printers)
        self.items: list[Item] = []
        self.running = False
        self.jam = False
        self.scanner_fault = False
        self.speed = 0.16
        self.generation_interval = 1.1
        self.counters = {"produced": 0, "passed": 0, "rejected": 0, "printed": 0}
        self._gen_timer = 0.0
        self._changeover_timer = 0.0
        self._next_item_id = 0
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._register_tags()
        self._sync_readonly_tags()

    def _register_tags(self) -> None:
        self.tags.add("line.start", BOOL, "rw", "Пуск")
        self.tags.add("line.stop", BOOL, "rw", "Стоп")
        self.tags.add("line.jam", BOOL, "rw", "Замятие")
        self.tags.add("line.scanner_fault", BOOL, "rw", "Отказ сканера")
        self.tags.add("line.changeover", BOOL, "rw", "Смена продукта (импульс)")
        self.tags.add("line.speed", REAL, "rw", "Скорость, 1/с", initial=self.speed)
        self.tags.add("line.running", BOOL, "ro", "Линия работает")
        self.tags.add("line.jam_state", BOOL, "ro", "Состояние замятия")
        self.tags.add(
            "line.product", STR, "ro", "Текущий продукт", initial=self.current_product.name
        )
        self.tags.add("line.produced", INT, "ro", "Выпущено")
        self.tags.add("line.passed", INT, "ro", "Прошло")
        self.tags.add("line.rejected", INT, "ro", "Отбраковано")
        self.tags.add("line.printed", INT, "ro", "Напечатано")
        self.tags.add("line.items_on_line", INT, "ro", "Изделий на линии")
        self.tags.add("line.accumulator_full", BOOL, "ro", "Накопитель полон")
        for station in self.stations:
            if station.kind == "sensor":
                self.tags.add(f"{station.name}.active", BOOL, "ro", station.label)
        for printer in self.printers:
            self.tags.add(f"printer.{printer.name}.online", BOOL, "ro", "Онлайн", initial=True)
            self.tags.add(f"printer.{printer.name}.fault", BOOL, "ro", "Неисправность")
            self.tags.add(f"printer.{printer.name}.printed", INT, "ro", "Напечатано")

    def control(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if action == "start":
            self.tags.set("line.start", True, force=True)
        elif action == "stop":
            self.tags.set("line.stop", True, force=True)
        elif action == "jam":
            self.tags.set("line.jam", True, force=True)
        elif action == "clear":
            self.tags.set("line.jam", False, force=True)
            self.tags.set("line.scanner_fault", False, force=True)
        elif action == "scanner_fault":
            self.tags.set("line.scanner_fault", bool(payload.get("value", True)), force=True)
        elif action == "speed":
            self.tags.set("line.speed", float(payload.get("speed", self.speed)), force=True)
        elif action == "changeover":
            self.changeover(payload.get("product"))
        else:
            return {"ok": False, "error": f"unknown action: {action}"}
        return {"ok": True, "action": action}

    def changeover(self, product_name: str | None = None) -> ProductDef | None:
        with self._lock:
            product = self._pick_product(product_name)
            if product is None:
                return None
            self.current_product = product
            self._changeover_timer = 2.5
            self.tags.set("line.product", product.name, force=True)
        self.events.publish(
            "changeover", f"Смена продукта: {product.name}", product=product.name, gtin=product.gtin
        )
        return product

    def _pick_product(self, product_name: str | None) -> ProductDef | None:
        if not product_name:
            index = self.products.index(self.current_product)
            return self.products[(index + 1) % len(self.products)]
        return next((item for item in self.products if item.name == product_name), None)

    def tick(self, dt: float) -> None:
        with self._lock:
            self._apply_command_tags()
            if self._changeover_timer > 0:
                self._changeover_timer = max(self._changeover_timer - dt, 0.0)
            if self.running and not self.jam and self._changeover_timer == 0:
                self._generate(dt)
            if not self.jam:
                self._advance(dt)
            self._sync_readonly_tags()

    def _apply_command_tags(self) -> None:
        if self.tags.get("line.start"):
            self.tags.set("line.start", False, force=True)
            if not self.running:
                self.running = True
                self.events.publish("start", "Линия запущена")
        if self.tags.get("line.stop"):
            self.tags.set("line.stop", False, force=True)
            if self.running:
                self.running = False
                self.events.publish("stop", "Линия остановлена")
        was_jam = self.jam
        self.jam = bool(self.tags.get("line.jam"))
        if self.jam != was_jam:
            self.events.publish("jam" if self.jam else "jam_cleared",
                                "Замятие на линии" if self.jam else "Замятие устранено")
        self.scanner_fault = bool(self.tags.get("line.scanner_fault"))
        if self.tags.get("line.changeover"):
            self.tags.set("line.changeover", False, force=True)
            self.changeover(None)
        speed = self.tags.get("line.speed")
        if isinstance(speed, (int, float)) and speed > 0:
            self.speed = float(speed)

    def _generate(self, dt: float) -> None:
        if self._accumulator_full():
            return
        self._gen_timer -= dt
        if self._gen_timer > 0:
            return
        self._gen_timer = self.generation_interval
        self._next_item_id += 1
        self.counters["produced"] += 1
        self.items.append(Item(id=self._next_item_id, product=self.current_product))

    def _advance(self, dt: float) -> None:
        for item in self.items:
            item.prev = item.pos
            item.pos += self.speed * dt
        now = time.time()
        for station in self.stations:
            for item in self.items:
                if item.removed:
                    continue
                if item.prev <= station.pos < item.pos:
                    self._trigger(station, item, now)
        remaining: list[Item] = []
        for item in self.items:
            if item.removed:
                continue
            if item.pos >= 1.0:
                if not item.rejected:
                    self.counters["passed"] += 1
                continue
            remaining.append(item)
        self.items = remaining

    def _trigger(self, station: Station, item: Item, now: float) -> None:
        station.last_active = now
        if station.kind == "printer":
            printer = station.printer
            if printer is not None and printer.can_print():
                printer.print_labels(1)
                item.printed = True
                self.counters["printed"] += 1
                self.events.publish("print", f"Печать {printer.name} · изделие {item.id}",
                                    item=item.id, printer=printer.name)
            else:
                name = printer.name if printer else station.name
                self.events.publish(
                    "print_error",
                    f"{name}: печать не выполнена · изделие {item.id}",
                    item=item.id,
                )
        elif station.kind == "applicator":
            if item.printed:
                item.applied = True
                self.events.publish("apply", f"Наклейка этикетки · изделие {item.id}", item=item.id)
        elif station.kind == "camera":
            item.inspected = True
            self.events.publish("inspect", f"Инспекция · изделие {item.id}", item=item.id)
        elif station.kind == "scanner":
            self._verify(item)
        elif station.kind == "reject" and item.rejected:
            item.removed = True
            self.counters["rejected"] += 1
            self.events.publish("reject", f"Отбраковка изделия {item.id}", item=item.id)

    def _verify(self, item: Item) -> None:
        failed = (
            self.scanner_fault
            or not item.printed
            or not item.applied
            or self._rng.random() < VERIFY_FAIL_RATE
        )
        item.verified = not failed
        item.rejected = failed
        if failed:
            self.events.publish("verify_fail", f"Код не прочитан · изделие {item.id}", item=item.id)
        else:
            self.events.publish("verify_ok", f"Код подтверждён · изделие {item.id}", item=item.id)

    def _items_in_accumulator(self) -> int:
        accumulator = next((s for s in self.stations if s.kind == "accumulator"), None)
        if accumulator is None:
            return 0
        return sum(1 for item in self.items if item.pos >= accumulator.pos)

    def _accumulator_full(self) -> bool:
        accumulator = next((s for s in self.stations if s.kind == "accumulator"), None)
        if accumulator is None:
            return False
        return self._items_in_accumulator() >= accumulator.capacity

    def _sync_readonly_tags(self) -> None:
        now = time.time()
        self.tags.set("line.running", self.running, force=True)
        self.tags.set("line.jam_state", self.jam, force=True)
        self.tags.set("line.product", self.current_product.name, force=True)
        self.tags.set("line.produced", self.counters["produced"], force=True)
        self.tags.set("line.passed", self.counters["passed"], force=True)
        self.tags.set("line.rejected", self.counters["rejected"], force=True)
        self.tags.set("line.printed", self.counters["printed"], force=True)
        self.tags.set("line.items_on_line", len(self.items), force=True)
        self.tags.set("line.accumulator_full", self._accumulator_full(), force=True)
        for station in self.stations:
            if station.kind == "sensor":
                active = (now - station.last_active) < 0.6
                self.tags.set(f"{station.name}.active", active, force=True)
        for printer in self.printers:
            self.tags.set(f"printer.{printer.name}.online", True, force=True)
            self.tags.set(f"printer.{printer.name}.fault", not printer.can_print(), force=True)
            self.tags.set(f"printer.{printer.name}.printed", printer.total_labels, force=True)

    def _station_status(self, station: Station, now: float) -> str:
        if station.kind == "printer" and station.printer is not None:
            if not station.printer.can_print():
                return "fault"
        if station.kind == "scanner" and self.scanner_fault:
            return "fault"
        if station.kind == "accumulator" and self._accumulator_full():
            return "warn"
        if now - station.last_active < 0.6:
            return "active"
        return "ok"

    def state(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            stations = []
            for station in self.stations:
                stations.append(
                    {
                        "name": station.name,
                        "kind": station.kind,
                        "pos": station.pos,
                        "label": station.label,
                        "status": self._station_status(station, now),
                    }
                )
            items = [
                {
                    "id": item.id,
                    "pos": round(item.pos, 4),
                    "product": item.product.name,
                    "color": item.product.color,
                    "rejected": item.rejected,
                    "printed": item.printed,
                }
                for item in self.items
            ]
            return {
                "running": self.running,
                "jam": self.jam,
                "scanner_fault": self.scanner_fault,
                "speed": self.speed,
                "product": self.current_product.name,
                "products": [product.to_dict() for product in self.products],
                "counters": dict(self.counters),
                "stations": stations,
                "items": items,
                "accumulator_full": self._accumulator_full(),
            }

    def events_recent(self, limit: int = 50, after: int = 0) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events.recent(limit=limit, after=after)]
