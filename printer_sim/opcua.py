from __future__ import annotations

import contextlib
from typing import Any

from .tags import BOOL, INT, REAL, Tag, TagRegistry


def _variant_type(tag: Tag) -> Any:
    from asyncua import ua

    if tag.kind == BOOL:
        return ua.VariantType.Boolean
    if tag.kind == INT:
        return ua.VariantType.Int32
    if tag.kind == REAL:
        return ua.VariantType.Double
    return ua.VariantType.String


class OpcUaServer:
    def __init__(
        self,
        tags: TagRegistry,
        host: str = "127.0.0.1",
        port: int = 4840,
        name: str = "ProductionLine",
    ) -> None:
        self.tags = tags
        self.host = host
        self.port = port
        self.name = name
        self.namespace_index = 2
        self._server: Any = None
        self._nodes: dict[str, Any] = {}
        self._last: dict[str, Any] = {}

    async def start(self) -> None:
        from asyncua import Server, ua

        server = Server()
        await server.init()
        server.set_endpoint(f"opc.tcp://{self.host}:{self.port}")
        server.set_server_name(self.name)
        index = await server.register_namespace(self.name)
        self.namespace_index = index
        line = await server.nodes.objects.add_object(index, "Line")
        for tag in self.tags.all():
            value = tag.value
            node = await line.add_variable(
                ua.NodeId(tag.name, index), tag.name, value, varianttype=_variant_type(tag)
            )
            if tag.access == "rw":
                await node.set_writable()
            self._nodes[tag.name] = node
            self._last[tag.name] = value
        await server.start()
        self._server = server

    async def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.stop()
            self._server = None

    async def publish(self) -> None:
        from asyncua import ua

        for name, node in self._nodes.items():
            value = self.tags.get(name)
            if value == self._last.get(name):
                continue
            tag = self.tags.tag(name)
            with contextlib.suppress(Exception):
                await node.write_value(ua.Variant(value, _variant_type(tag)))
                self._last[name] = value

    async def poll(self) -> None:
        for name, node in self._nodes.items():
            tag = self.tags.tag(name)
            if tag is None or tag.access != "rw":
                continue
            try:
                value = await node.read_value()
            except Exception:
                continue
            if value != self._last.get(name):
                self.tags.set(name, value)
                self._last[name] = value
