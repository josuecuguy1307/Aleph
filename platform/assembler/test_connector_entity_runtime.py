from __future__ import annotations

from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from assembler import MCPServer, ToolRegistry  # noqa: E402
from recipe_assembler import LazyToolRegistry  # noqa: E402


class FakeServer:
    def __init__(self, name: str, tools: list[str]):
        self.name = name
        self._tools = tools
        self.calls = []

    def list_tools(self):
        return [
            {
                "name": name,
                "description": f"{self.name}:{name}",
                "inputSchema": {"type": "object", "properties": {}},
            }
            for name in self._tools
        ]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return f"{self.name}:{name}"


FILTERS = {
    "alpha": ["search", "alpha_only"],
    "beta": ["search", "beta_only"],
}
ALIASES = {
    "alpha": {"search": "alpha__search", "alpha_only": "alpha_only"},
    "beta": {"search": "beta__search", "beta_only": "beta_only"},
}


def test_entidad_cablea_todos_los_servidores_y_rutea_al_nombre_crudo():
    alpha = FakeServer("alpha", ["search", "alpha_only"])
    beta = FakeServer("beta", ["search", "beta_only"])
    registry = LazyToolRegistry(
        [alpha, beta], FILTERS, tool_aliases=ALIASES,
    )

    assert registry.tool_names() == [
        "alpha__search", "alpha_only", "beta__search", "beta_only",
    ]
    assert registry.raw_for("alpha__search") == "search"
    assert registry.server_for("beta__search") == "beta"
    assert registry.call("beta__search", {"q": "x"}) == "beta:search"
    assert beta.calls == [("search", {"q": "x"})]
    assert registry.cabled_origins == [
        {"name": "alpha__search", "server": "alpha", "raw_name": "search"},
        {"name": "alpha_only", "server": "alpha", "raw_name": "alpha_only"},
        {"name": "beta__search", "server": "beta", "raw_name": "search"},
        {"name": "beta_only", "server": "beta", "raw_name": "beta_only"},
    ]


def test_degradacion_conserva_tools_sanas_y_alias_estable():
    alpha = FakeServer("alpha", ["search", "alpha_only"])
    partial = LazyToolRegistry(
        [alpha], FILTERS, tool_aliases=ALIASES,
    )
    assert partial.tool_names() == ["alpha__search", "alpha_only"]
    assert partial.call("alpha__search", {}) == "alpha:search"
    assert partial.dropped == [{
        "server": "beta",
        "tool": "*",
        "reason": "server requested by recipe but not booted",
    }]

    again = LazyToolRegistry(
        [FakeServer("alpha", ["search", "alpha_only"])],
        FILTERS,
        tool_aliases=ALIASES,
    )
    assert again.tool_names() == partial.tool_names()


def test_alias_derivado_tambien_es_determinista_sin_mapa_explicito():
    alpha = FakeServer("alpha", ["search"])
    beta = FakeServer("beta", ["search"])
    registry = LazyToolRegistry([alpha, beta], FILTERS)
    assert registry.tool_names() == ["alpha__search", "beta__search"]


def test_cliente_acepta_la_revision_que_negocia_fred():
    server = MCPServer("fred", "npx", [])
    server._record_protocol_response({
        "result": {"protocolVersion": "2025-03-26"},
    })
    assert server.diagnostico()["protocolo"] == {
        "cliente": "2024-11-05",
        "servidor": "2025-03-26",
        "negociacion": "aceptada",
    }

    future = MCPServer("future", "npx", [])
    future._record_protocol_response({
        "result": {"protocolVersion": "2099-01-01"},
    })
    assert future.diagnostico()["protocolo"]["incompatible"] is True


def test_registro_generico_tampoco_renombra_al_degradarse():
    partial = ToolRegistry(
        [FakeServer("alpha", ["search", "alpha_only"])],
        FILTERS,
        tool_aliases=ALIASES,
    )
    assert [row["function"]["name"] for row in partial.schema()] == [
        "alpha__search", "alpha_only",
    ]
