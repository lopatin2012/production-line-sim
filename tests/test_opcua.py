import socket

import pytest

from printer_sim.opcua import OpcUaServer
from printer_sim.tags import BOOL, REAL, TagRegistry

pytest.importorskip("asyncua")


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def test_opcua_read_and_write_tags():
    from asyncua import Client, ua

    tags = TagRegistry()
    tags.add("cmd", BOOL, "rw")
    tags.add("state", BOOL, "ro")
    tags.add("speed", REAL, "rw")

    server = OpcUaServer(tags, "127.0.0.1", _free_port())
    await server.start()
    try:
        async with Client(f"opc.tcp://127.0.0.1:{server.port}") as client:
            index = server.namespace_index

            state = client.get_node(ua.NodeId("state", index))
            assert await state.read_value() is False
            tags.set("state", True, force=True)
            await server.publish()
            assert await state.read_value() is True

            cmd = client.get_node(ua.NodeId("cmd", index))
            await cmd.write_value(ua.Variant(True, ua.VariantType.Boolean))
            await server.poll()
            assert tags.get("cmd") is True

            speed = client.get_node(ua.NodeId("speed", index))
            await speed.write_value(ua.Variant(1.25, ua.VariantType.Double))
            await server.poll()
            assert abs(tags.get("speed") - 1.25) < 1e-6
    finally:
        await server.stop()
