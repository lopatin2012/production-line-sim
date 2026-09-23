import socket
import struct
import time

import pytest

from printer_sim.s7 import S7Server
from printer_sim.tags import BOOL, INT, REAL, TagRegistry

pytest.importorskip("snap7")
import snap7  # noqa: E402


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _connect(port: int) -> snap7.client.Client:
    client = snap7.client.Client()
    for _ in range(20):
        try:
            client.connect("127.0.0.1", 0, 1, tcp_port=port)
            return client
        except Exception:
            time.sleep(0.2)
    raise AssertionError("S7 client could not connect")


def test_s7_read_and_write():
    tags = TagRegistry()
    tags.add("cmd", BOOL, "rw")
    tags.add("state", BOOL, "ro")
    tags.add("count", INT, "rw")
    tags.add("speed", REAL, "rw")

    server = S7Server(tags, "127.0.0.1", _free_port())
    server.start()
    client = _connect(server.port)
    try:
        tags.set("state", True, force=True)
        tags.set("count", 7)
        tags.set("speed", 1.5)
        server.publish()

        layout = server.layout
        data = client.db_read(server.db_number, 0, server.size)
        assert data[layout["state"][0]] == 1
        assert struct.unpack_from(">h", data, layout["count"][0])[0] == 7
        assert abs(struct.unpack_from(">f", data, layout["speed"][0])[0] - 1.5) < 1e-6

        client.db_write(server.db_number, layout["cmd"][0], bytearray([1]))
        server.poll()
        assert tags.get("cmd") is True

        client.db_write(server.db_number, layout["count"][0], struct.pack(">h", 42))
        server.poll()
        assert tags.get("count") == 42
    finally:
        client.disconnect()
        server.stop()
