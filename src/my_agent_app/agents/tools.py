import logging
from collections.abc import Callable

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

# Unicas tools do MCP Server Kubernetes expostas ao agente de analise (somente leitura)
READ_ONLY_TOOLS = ("kubectl_get", "kubectl_describe", "kubectl_logs")

# Tools que alteram o estado do proprio MCP Server (compartilhado com a analise): fora do
# agente de correcao, que de resto tem acesso irrestrito ao cluster (PRD 004, D1)
EXCLUDED_CORRECTION_TOOLS = ("kubectl_context", "port_forward", "stop_port_forward", "cleanup")


class NoReadOnlyToolsError(RuntimeError):
    pass


class NoCorrectionToolsError(RuntimeError):
    pass


def filter_read_only_tools(tools: list[BaseTool]) -> list[BaseTool]:
    by_name = {tool.name: tool for tool in tools}
    missing = [name for name in READ_ONLY_TOOLS if name not in by_name]
    if missing:
        logger.warning("MCP Server nao expoe as tools de leitura: %s", ", ".join(missing))
    selected = [by_name[name] for name in READ_ONLY_TOOLS if name in by_name]
    if not selected:
        raise NoReadOnlyToolsError("MCP Server nao expoe nenhuma tool de leitura do Kubernetes")
    return selected


async def load_read_only_tools(
    url: str, client_factory: Callable[[dict], MultiServerMCPClient] = MultiServerMCPClient
) -> list[BaseTool]:
    """Conecta ao MCP Server via HTTP e devolve apenas as tools de leitura.

    Falhas de conexao/sessao levantam excecao (tratadas pelo pipeline como INCOMPLETO);
    erros de execucao de tool voltam ao modelo pelo ToolErrorMiddleware do agente
    (ver agents/tool_errors.py).
    """
    client = client_factory({"kubernetes": {"transport": "http", "url": url}})
    return filter_read_only_tools(await client.get_tools())


def filter_correction_tools(tools: list[BaseTool]) -> list[BaseTool]:
    selected = [tool for tool in tools if tool.name not in EXCLUDED_CORRECTION_TOOLS]
    if not selected:
        logger.warning("MCP Server nao expoe nenhuma tool utilizavel pela correcao")
        raise NoCorrectionToolsError("MCP Server nao expoe nenhuma tool para a correcao")
    return selected


async def load_correction_tools(
    url: str, client_factory: Callable[[dict], MultiServerMCPClient] = MultiServerMCPClient
) -> list[BaseTool]:
    """Conecta ao MCP Server via HTTP e devolve todas as tools menos as excluidas.

    Falhas de conexao/sessao levantam excecao (tratadas pelo runner como FALHA_CORRECAO).
    """
    client = client_factory({"kubernetes": {"transport": "http", "url": url}})
    return filter_correction_tools(await client.get_tools())
