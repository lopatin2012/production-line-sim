from __future__ import annotations

import contextlib
import socket
import struct
import threading
from typing import Any

from .tags import BOOL, INT, REAL, STR, Tag, TagRegistry

READ_COILS = 0x01
READ_DISCRETE = 0x02
READ_HOLDING = 0x03
READ_INPUT = 0x04
WRITE_COIL = 0x05
WRITE_REGISTER = 0x06
WRITE_COILS = 0x0F
WRITE_REGISTERS = 0x10

ILLEGAL_FUNCTION = 0x01
ILLEGAL_ADDRESS = 0x02
ILLEGAL_VALUE = 0x03


class ModbusServer:
    def __init__(
        self,
        tags: TagRegistry,
        host: str = "127.0.0.1",
        port: int = 502,
        unit_id: int = 1,
    ) -> None:
        self.tags = tags
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._build_maps()

    def _build_maps(self) -> None:
        self.coils: dict[int, Tag] = {}
        self.discrete: dict[int, Tag] = {}
        self.holding: dict[int, tuple[Tag, int]] = {}
        self.input: dict[int, tuple[Tag, int]] = {}
        for tag in self.tags.all():
            if tag.kind == BOOL:
                table = self.coils if tag.table == "coil" else self.discrete
                table[tag.ref] = tag
                continue
            table = self.holding if tag.table == "holding" else self.input
            for offset in range(tag.size):
                table[tag.ref + offset] = (tag, offset)

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(5)
        self.port = sock.getsockname()[1]
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None

    def _accept_loop(self) -> None:
        while self._running and self._sock is not None:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._client_loop, args=(conn,), daemon=True).start()

    def _client_loop(self, conn: socket.socket) -> None:
        with conn:
            while self._running:
                header = _recv_exact(conn, 7)
                if not header:
                    return
                transaction, protocol, length, unit = struct.unpack(">HHHB", header)
                if unit != self.unit_id and self.unit_id != 0:
                    return
                pdu = _recv_exact(conn, length - 1)
                if not pdu:
                    return
                response = self._handle(pdu)
                if response is not None:
                    frame = struct.pack(">HHHB", transaction, protocol, len(response) + 1, unit)
                    with contextlib.suppress(OSError):
                        conn.sendall(frame + response)

    def _handle(self, pdu: bytes) -> bytes | None:
        function = pdu[0]
        if function == READ_COILS:
            return self._read_bits(self.coils, function, pdu)
        if function == READ_DISCRETE:
            return self._read_bits(self.discrete, function, pdu)
        if function == READ_HOLDING:
            return self._read_registers(self.holding, function, pdu)
        if function == READ_INPUT:
            return self._read_registers(self.input, function, pdu)
        if function == WRITE_COIL:
            return self._write_coil(pdu)
        if function == WRITE_REGISTER:
            return self._write_register(pdu)
        if function == WRITE_COILS:
            return self._write_coils(pdu)
        if function == WRITE_REGISTERS:
            return self._write_registers(pdu)
        return _error(function, ILLEGAL_FUNCTION)

    def _read_bits(self, table: dict[int, Tag], function: int, pdu: bytes) -> bytes:
        start, count = struct.unpack(">HH", pdu[1:5])
        if not 1 <= count <= 2000:
            return _error(function, ILLEGAL_VALUE)
        bits = []
        for address in range(start, start + count):
            tag = table.get(address)
            bits.append(bool(tag.value) if tag is not None else False)
        payload = bytearray((count + 7) // 8)
        for index, bit in enumerate(bits):
            if bit:
                payload[index // 8] |= 1 << (index % 8)
        return bytes([function, len(payload), *payload])

    def _read_registers(
        self, table: dict[int, tuple[Tag, int]], function: int, pdu: bytes
    ) -> bytes:
        start, count = struct.unpack(">HH", pdu[1:5])
        if not 1 <= count <= 125:
            return _error(function, ILLEGAL_VALUE)
        words: list[int] = []
        for address in range(start, start + count):
            entry = table.get(address)
            if entry is None:
                words.append(0)
                continue
            tag, offset = entry
            words.append(_tag_words(tag)[offset])
        body = struct.pack(">" + "H" * len(words), *words)
        return bytes([function, len(body)]) + body

    def _write_coil(self, pdu: bytes) -> bytes:
        address, value = struct.unpack(">HH", pdu[1:5])
        tag = self.coils.get(address)
        if tag is None:
            return _error(WRITE_COIL, ILLEGAL_ADDRESS)
        self.tags.set(tag.name, value == 0xFF00)
        return pdu[:5]

    def _write_register(self, pdu: bytes) -> bytes:
        address, value = struct.unpack(">HH", pdu[1:5])
        entry = self.holding.get(address)
        if entry is None:
            return _error(WRITE_REGISTER, ILLEGAL_ADDRESS)
        tag, offset = entry
        if tag.kind == INT and offset == 0:
            self.tags.set(tag.name, _to_signed(value))
            return pdu[:5]
        return _error(WRITE_REGISTER, ILLEGAL_ADDRESS)

    def _write_coils(self, pdu: bytes) -> bytes:
        start, count, _byte_count = struct.unpack(">HHB", pdu[1:6])
        data = pdu[6:]
        for index in range(count):
            tag = self.coils.get(start + index)
            if tag is None:
                continue
            bit = bool(data[index // 8] & (1 << (index % 8)))
            self.tags.set(tag.name, bit)
        return pdu[:5]

    def _write_registers(self, pdu: bytes) -> bytes:
        start, count, _byte_count = struct.unpack(">HHB", pdu[1:6])
        registers = struct.unpack(">" + "H" * count, pdu[6 : 6 + count * 2])
        index = 0
        while index < count:
            entry = self.holding.get(start + index)
            if entry is None:
                index += 1
                continue
            tag, offset = entry
            if offset == 0 and index + tag.size <= count:
                self._set_tag(tag, list(registers[index : index + tag.size]))
                index += tag.size
            else:
                index += 1
        return pdu[:5]

    def _set_tag(self, tag: Tag, words: list[int]) -> None:
        if tag.kind == INT:
            self.tags.set(tag.name, _to_signed(words[0]))
        elif tag.kind == REAL:
            raw = bytes(
                [words[0] >> 8, words[0] & 0xFF, words[1] >> 8, words[1] & 0xFF]
            )
            self.tags.set(tag.name, struct.unpack(">f", raw)[0])
        elif tag.kind == STR:
            raw = b"".join(bytes([word >> 8, word & 0xFF]) for word in words)
            self.tags.set(tag.name, raw.split(b"\x00", 1)[0].decode("utf-8", "ignore"))


def _tag_words(tag: Tag) -> list[int]:
    value: Any = tag.value
    if tag.kind == BOOL:
        return [1 if value else 0]
    if tag.kind == INT:
        return [int(value or 0) & 0xFFFF]
    if tag.kind == REAL:
        raw = struct.pack(">f", float(value or 0.0))
        return [raw[0] << 8 | raw[1], raw[2] << 8 | raw[3]]
    if tag.kind == STR:
        raw = str(value or "").encode("utf-8")[: tag.size * 2]
        raw = raw.ljust(tag.size * 2, b"\x00")
        return [raw[i] << 8 | raw[i + 1] for i in range(0, tag.size * 2, 2)]
    return [0]


def _to_signed(value: int) -> int:
    return value - 0x10000 if value > 0x7FFF else value


def _error(function: int, code: int) -> bytes:
    return bytes([function | 0x80, code])


def _recv_exact(conn: socket.socket, size: int) -> bytes | None:
    buffer = b""
    while len(buffer) < size:
        try:
            chunk = conn.recv(size - len(buffer))
        except OSError:
            return None
        if not chunk:
            return None
        buffer += chunk
    return buffer
