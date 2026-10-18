import logging

from langchain.agents.middleware import ToolCallRequest
from langchain_core.tools import ToolException
from mcp.shared.exceptions import McpError

logger = logging.getLogger(__name__)


def tool_error_to_model(error: Exception, request: ToolCallRequest) -> str | None:
    """`on_error` do ToolErrorMiddleware usado pelos agentes de analise e de correcao.

    Erro reportado ao executar a tool volta ao modelo, que tenta outra abordagem.
    Falhas de transporte/conexao devolvem None e propagam (analise -> INCOMPLETO,
    correcao -> FALHA_CORRECAO).
    """
    if isinstance(error, (McpError, ToolException)):
        name = request.tool_call.get("name", "?")
        logger.warning("Tool %s falhou: %s", name, error)
        return f"Erro ao executar {name}: {error}"
    return None
