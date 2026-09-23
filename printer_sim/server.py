from __future__ import annotations

import asyncio
import contextlib
import re

from .state import PrinterState, Simulator

IDLE_TIMEOUT = 0.4
STATUS_COMMANDS = ("~HQES", "~HI", "~HS")


def _label_quantity(data: str) -> int:
    explicit = [int(value) for value in re.findall(r"\^PQ(\d+)", data)]
    if explicit:
        return sum(explicit)
    return max(data.count("^XZ"), data.count("^XA"))


class PrinterServer:
    def __init__(
        self, simulator: Simulator, printer: PrinterState, host: str = "127.0.0.1"
    ) -> None:
        self.simulator = simulator
        self.printer = printer
        self.host = host
        self.port = printer.port
        self._server: asyncio.AbstractServer | None = None
        self.printed: list[int] = []

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.printer.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(4096), timeout=IDLE_TIMEOUT)
                except TimeoutError:
                    break
                if not data:
                    break
                response = self.process(data.decode("latin-1", errors="replace"))
                if response:
                    writer.write(response)
                    await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def process(self, data: str) -> bytes:
        response = b""
        with self.simulator.lock:
            if "~HQES" in data:
                response += self.printer.host_query_error_status()
            if "~HI" in data:
                response += self.printer.host_identification()
            if "~HS" in data:
                response += self.printer.host_status()
            quantity = _label_quantity(data)
            if quantity:
                printed = self.printer.print_labels(quantity)
                if printed:
                    self.printed.append(printed)
        return response
