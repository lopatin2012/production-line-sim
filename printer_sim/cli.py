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


async def _sync_adapter(adapter) -> None:
    import inspect

    for method_name in ("poll", "publish"):
        method = getattr(adapter, method_name, None)
        if method is None:
            continue
        result = method()
        if inspect.isawaitable(result):
            await result


async def _tick_loop(
    line: LineEngine, plc: SoftPlc, adapters=None, dt: float = TICK_SECONDS
) -> None:
    adapters = [adapter for adapter in (adapters or []) if adapter is not None]
    while True:
        await asyncio.sleep(dt)
        plc.tick(dt)
        line.tick(dt)
        for adapter in adapters:
            try:
                await _sync_adapter(adapter)
            except Exception:
                pass


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
    adapters: list = []
    modbus = None
    if args.modbus:
        modbus = ModbusServer(line.tags, args.modbus_host, args.modbus_port, args.modbus_unit)
        try:
            modbus.start()
            adapters.append(modbus)
            logger.info(
                "Modbus TCP on %s:%s (unit %s)", args.modbus_host, modbus.port, args.modbus_unit
            )
        except OSError as exc:
            logger.warning("Modbus TCP не запущен: %s", exc)
            modbus = None
    opcua = None
    if args.opcua:
        try:
            from .opcua import OpcUaServer

            opcua = OpcUaServer(line.tags, args.opcua_host, args.opcua_port)
            await opcua.start()
            adapters.append(opcua)
            logger.info(
                "OPC UA on opc.tcp://%s:%s (ns=%s, node ns=%s;s=<tag>)",
                args.opcua_host,
                args.opcua_port,
                opcua.namespace_index,
                opcua.namespace_index,
            )
        except ImportError:
            logger.warning("OPC UA: не установлен asyncua (pip install '.[opcua]')")
            opcua = None
        except Exception as exc:
            logger.warning("OPC UA не запущен: %s", exc)
            opcua = None
    s7 = None
    if args.s7:
        try:
            from .s7 import S7Server

            s7 = S7Server(line.tags, args.s7_host, args.s7_port, args.s7_db)
            s7.start()
            adapters.append(s7)
            logger.info(
                "S7 on %s:%s (DB%s, %s bytes)",
                args.s7_host,
                s7.port,
                s7.db_number,
                s7.size,
            )
        except ImportError:
            logger.warning("S7: не установлен python-snap7 (pip install '.[s7]')")
            s7 = None
        except Exception as exc:
            logger.warning("S7 не запущен: %s", exc)
            s7 = None
    httpd = start_control(
        simulator,
        args.control_host,
        args.control_port,
        line=line,
        plc=plc,
        adapters=adapters,
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    logger.info("control API + HMI on http://%s:%s", args.control_host, args.control_port)
    ticker = asyncio.create_task(_tick_loop(line, plc, adapters))
    try:
        await asyncio.gather(*(server.serve_forever() for server in servers))
    finally:
        ticker.cancel()
        if opcua is not None:
            await opcua.stop()
        if s7 is not None:
            s7.stop()
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
    parser.add_argument(
        "--opcua",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="поднимать OPC UA сервер (нужен asyncua)",
    )
    parser.add_argument("--opcua-host", default="127.0.0.1")
    parser.add_argument("--opcua-port", type=int, default=4840)
    parser.add_argument(
        "--s7",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="поднимать S7 сервер (нужен python-snap7)",
    )
    parser.add_argument("--s7-host", default="0.0.0.0")
    parser.add_argument("--s7-port", type=int, default=10102)
    parser.add_argument("--s7-db", type=int, default=1)
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
