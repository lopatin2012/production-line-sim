import asyncio

from printer_sim.server import PrinterServer
from printer_sim.state import PrinterState, Simulator


async def _query(host: str, port: int, payload: bytes, timeout: float = 2.0) -> bytes:
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(payload)
    await writer.drain()
    chunks: list[bytes] = []
    try:
        while True:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\x03" in chunk:
                break
    except TimeoutError:
        pass
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return b"".join(chunks)


async def _start(printer: PrinterState):
    simulator = Simulator([printer])
    server = PrinterServer(simulator, printer, host="127.0.0.1")
    await server.start()
    return server


async def test_status_commands_and_printing():
    printer = PrinterState(name="sim", port=0)
    server = await _start(printer)
    try:
        hi = await _query("127.0.0.1", server.port, b"~HI")
        assert b"ZEBRA ZD421-203dpi ZPL" in hi
        assert b"V83.20.07Z" in hi

        hs = await _query("127.0.0.1", server.port, b"~HS")
        assert hs.count(b"\x02") == 3

        hqes = await _query("127.0.0.1", server.port, b"~HQES")
        assert b"PRINTER STATUS" in hqes

        await _query("127.0.0.1", server.port, b"^XA^PQ3^XZ")
        await _query("127.0.0.1", server.port, b"~HI")
        assert printer.total_labels == 3
    finally:
        await server.stop()


async def test_faults_are_reported():
    printer = PrinterState(name="sim", port=0, paper_out=True, bad_head_elements=True)
    server = await _start(printer)
    try:
        hs = (await _query("127.0.0.1", server.port, b"~HS")).decode("latin-1")
        first_line = [line for line in hs.splitlines() if line][0]
        fields = first_line.strip("\x02\x03").split(",")
        assert fields[1] == "1"

        hqes = (await _query("127.0.0.1", server.port, b"~HQES")).decode("latin-1")
        assert "00000041" in hqes
    finally:
        await server.stop()
