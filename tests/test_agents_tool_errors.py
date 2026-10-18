from types import SimpleNamespace

import httpx
import pytest
from langchain_core.tools import ToolException
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from my_agent_app.agents.tool_errors import tool_error_to_model


def _request(name="kubectl_generic"):
    return SimpleNamespace(tool_call={"name": name, "args": {}, "id": "1"})


@pytest.mark.parametrize(
    "error",
    [
        McpError(ErrorData(code=-32603, message='error: unknown command "deployment web"')),
        ToolException('error: unknown command "deployment web"'),
    ],
)
def test_erro_de_execucao_da_tool_volta_ao_modelo(error):
    content = tool_error_to_model(error, _request())

    assert content.startswith("Erro ao executar kubectl_generic:")
    assert 'unknown command "deployment web"' in content


def test_falha_de_conexao_propaga():
    assert tool_error_to_model(httpx.ConnectError("conexao recusada"), _request()) is None
