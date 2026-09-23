import socket
import struct

from printer_sim.modbus import ModbusServer
from printer_sim.tags import BOOL, INT, REAL, STR, TagRegistry


def _registry() -> TagRegistry:
    tags = TagRegistry()
    tags.add("cmd", BOOL, "rw")
    tags.add("state", BOOL, "ro")
    tags.add("count", INT, "rw")
    tags.add("sensor", INT, "ro")
    tags.add("speed", REAL, "rw")
    tags.add("product", STR, "rw")
    return tags


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    buffer = b""
    while len(buffer) < size:
        chunk = sock.recv(size - len(buffer))
        if not chunk:
            break
        buffer += chunk
    return buffer


def _call(sock: socket.socket, pdu: bytes) -> bytes:
    sock.sendall(struct.pack(">HHHB", 1, 0, len(pdu) + 1, 1) + pdu)
    header = _recv_exact(sock, 7)
    _tid, _pid, length, _unit = struct.unpack(">HHHB", header)
    return _recv_exact(sock, length - 1)


def test_modbus_read_write():
    tags = _registry()
    server = ModbusServer(tags, "127.0.0.1", 0)
    server.start()
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=5) as sock:
            response = _call(sock, struct.pack(">BHH", 0x01, 0, 1))
            assert response[0] == 0x01
            assert response[2] == 0x00

            response = _call(sock, struct.pack(">BHH", 0x05, 0, 0xFF00))
            assert response == struct.pack(">BHH", 0x05, 0, 0xFF00)
            assert tags.get("cmd") is True

            tags.set("state", True, force=True)
            response = _call(sock, struct.pack(">BHH", 0x02, 0, 1))
            assert response[2] == 0x01

            response = _call(sock, struct.pack(">BHH", 0x06, 0, 5))
            assert response[0] == 0x06
            assert tags.get("count") == 5
            response = _call(sock, struct.pack(">BHH", 0x03, 0, 1))
            assert struct.unpack(">H", response[2:4])[0] == 5

            tags.set("speed", 1.5)
            response = _call(sock, struct.pack(">BHH", 0x03, 1, 2))
            assert abs(struct.unpack(">f", response[2:6])[0] - 1.5) < 1e-6

            body = struct.pack(">f", 0.25)
            words = struct.unpack(">HH", body)
            pdu = struct.pack(">BHHB", 0x10, 1, 2, 4) + struct.pack(">HH", *words)
            _call(sock, pdu)
            assert abs(tags.get("speed") - 0.25) < 1e-6

            tags.set("sensor", 42, force=True)
            response = _call(sock, struct.pack(">BHH", 0x04, 0, 1))
            assert struct.unpack(">H", response[2:4])[0] == 42

            text = "Молоко".encode().ljust(32, b"\x00")
            words = [text[i] << 8 | text[i + 1] for i in range(0, 32, 2)]
            pdu = struct.pack(">BHHB", 0x10, 3, 16, 32) + struct.pack(">16H", *words)
            _call(sock, pdu)
            assert tags.get("product") == "Молоко"

            response = _call(sock, struct.pack(">BHH", 0x63, 0, 1))
            assert response[0] == 0xE3
            assert response[1] == 0x01
    finally:
        server.stop()


def test_modbus_illegal_address():
    tags = _registry()
    server = ModbusServer(tags, "127.0.0.1", 0)
    server.start()
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=5) as sock:
            response = _call(sock, struct.pack(">BHH", 0x05, 900, 0xFF00))
            assert response[0] == 0x85
            assert response[1] == 0x02
    finally:
        server.stop()
