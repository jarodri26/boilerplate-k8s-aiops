import logging

import pytest
from langchain_core.tools import tool

from my_agent_app.agents.tools import (
    READ_ONLY_TOOLS,
    NoReadOnlyToolsError,
    load_read_only_tools,
)


def _fake_tool(name: str):
    @tool(name)
    def _t(x: str = "") -> str:
        """fake"""
        return x

    return _t


class FakeClient:
    def __init__(self, names):
        self.names = names
        self.connections = None

    def __call__(self, connections):
        self.connections = connections
        return self

    async def get_tools(self):
        return [_fake_tool(n) for n in self.names]


async def test_devolve_apenas_tools_de_leitura():
    client = FakeClient(
        ["kubectl_apply", "kubectl_get", "kubectl_delete", "kubectl_logs", "kubectl_describe",
         "kubectl_patch", "exec_in_pod"]
    )

    tools = await load_read_only_tools("http://mcp:3001/mcp", client_factory=client)

    assert [t.name for t in tools] == list(READ_ONLY_TOOLS)
    assert client.connections == {
        "kubernetes": {"transport": "http", "url": "http://mcp:3001/mcp"}
    }


async def test_tool_ausente_gera_warning(caplog):
    client = FakeClient(["kubectl_get", "kubectl_describe", "kubectl_apply"])

    with caplog.at_level(logging.WARNING):
        tools = await load_read_only_tools("http://x/mcp", client_factory=client)

    assert [t.name for t in tools] == ["kubectl_get", "kubectl_describe"]
    assert "kubectl_logs" in caplog.text


async def test_nenhuma_tool_de_leitura_levanta_erro():
    client = FakeClient(["kubectl_apply", "kubectl_delete"])

    with pytest.raises(NoReadOnlyToolsError):
        await load_read_only_tools("http://x/mcp", client_factory=client)


async def test_falha_de_conexao_propaga():
    class Down:
        def __init__(self, _):
            pass

        async def get_tools(self):
            raise ConnectionError("MCP fora do ar")

    with pytest.raises(ConnectionError):
        await load_read_only_tools("http://x/mcp", client_factory=Down)
