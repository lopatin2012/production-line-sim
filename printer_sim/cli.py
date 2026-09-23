from __future__ import annotations

import argparse
import asyncio
import json
import logging
import threading
from pathlib import Path

from .control import start_control
from .line import LineEngine
from .modbus import ModbusServer
from .server import PrinterServer
from .softplc import SoftPlc
from .state import PrinterState, Simulator

logger = logging.getLogger("printer_sim")
TICK_SECONDS = 0.1


async def _tick_loop(line: LineEngine, plc: SoftPlc, dt: float = TICK_SECONDS) -> None:
    while True:
        await asyncio.sleep(dt)
        plc.tick(dt)
        line.tick(dt)


def load_printers(args: argparse.Namespace) -> list[PrinterState]:
    printers: list[PrinterState] = []
    if args.config:
        data = json.loads(Path(args.config).read_text(encoding="utf-8"))
        for entry in data.get("printers", []):
            printers.append(PrinterState(**entry))
    for index in range(args.printers):
        name = f"sim-{index + 1}"
        if all(printer.name != name for printer in printers):
            printers.append(PrinterState(name=name, port=args.base_port + index))
    if not printers:
        printers.append(PrinterState(name="sim-1", port=args.base_port))
    return printers


async def run(args: argparse.Namespace) -> None:
    printers = load_printers(args)
    simulator = Simulator(printers)
    line = LineEngine(printers)
    plc = SoftPlc(line, enabled=args.plc, file=args.plc_file)
    servers: list[PrinterServer] = []
    for printer in printers:
        server = PrinterServer(simulator, printer, host=args.host)
        await server.start()
        servers.append(server)
        logger.info("printer %s on %s:%s", printer.name, args.host, server.port)
    if args.autostart:
        line.control("start")
    line.events.publish("boot", "Симулятор линии запущен")
    httpd = start_control(
        simulator, args.control_host, args.control_port, line=line, plc=plc
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    logger.info("control API + HMI on http://%s:%s", args.control_host, args.control_port)
    modbus = None
    if args.modbus:
        modbus = ModbusServer(line.tags, args.modbus_host, args.modbus_port, args.modbus_unit)
        try:
            modbus.start()
            logger.info(
                "Modbus TCP on %s:%s (unit %s)", args.modbus_host, modbus.port, args.modbus_unit
            )
        except OSError as exc:
            logger.warning("Modbus TCP не запущен: %s", exc)
            modbus = None
    ticker = asyncio.create_task(_tick_loop(line, plc))
    try:
        await asyncio.gather(*(server.serve_forever() for server in servers))
    finally:
        ticker.cancel()
        if modbus is not None:
            modbus.stop()
        httpd.shutdown()
        for server in servers:
            await server.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printer_sim", description="ZPL/TSC printer simulator for the Etiketron playground"
    )
    parser.add_argument("--config", help="JSON config with a list of printers")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--printers", type=int, default=0, help="spawn N printers on consecutive ports"
    )
    parser.add_argument("--base-port", type=int, default=9100)
    parser.add_argument("--control-host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=9200)
    parser.add_argument(
        "--autostart",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="запускать линию сразу при старте",
    )
    parser.add_argument(
        "--modbus",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="поднимать Modbus TCP сервер",
    )
    parser.add_argument("--modbus-host", default="127.0.0.1")
    parser.add_argument("--modbus-port", type=int, default=5020)
    parser.add_argument("--modbus-unit", type=int, default=1)
    parser.add_argument(
        "--plc",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="включить встроенный soft-PLC",
    )
    parser.add_argument("--plc-file", default=None, help="JSON-файл с правилами soft-PLC")
    parser.add_argument("--log-level", default="info")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
