import logging
from collections.abc import Awaitable, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolErrorMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import BaseTool

from my_agent_app.agents.analyzer import MODEL_MAX_RETRIES, final_text
from my_agent_app.agents.correction_prompt import render_correction_prompt
from my_agent_app.agents.tool_errors import tool_error_to_model
from my_agent_app.agents.tools import load_correction_tools

logger = logging.getLogger(__name__)


class CorrectionAgent:
    """Agente LangChain + Claude que executa a correcao do relatorio via MCP (PRD 004).

    Separado do RootCauseAnalyzer (decisao-chave 1): acesso de escrita ao cluster.
    """

    def __init__(
        self,
        model_name: str,
        max_iterations: int,
        mcp_server_url: str,
        tools_loader: Callable[[str], Awaitable[list[BaseTool]]] = load_correction_tools,
        agent_factory: Callable = create_agent,
    ):
        self.model_name = model_name
        self.max_iterations = max_iterations
        self.mcp_server_url = mcp_server_url
        self._tools_loader = tools_loader
        self._agent_factory = agent_factory

    def _build_agent(self, tools: list[BaseTool]):
        model = ChatAnthropic(model=self.model_name, max_retries=MODEL_MAX_RETRIES)
        return self._agent_factory(
            model=model,
            tools=tools,
            middleware=[
                ModelCallLimitMiddleware(run_limit=self.max_iterations, exit_behavior="end"),
                ToolErrorMiddleware(on_error=tool_error_to_model),
            ],
        )

    async def run(self, report_markdown: str) -> str:
        # cliente MCP por correcao: indisponibilidade vira excecao aqui (-> FALHA_CORRECAO)
        tools = await self._tools_loader(self.mcp_server_url)
        agent = self._build_agent(tools)
        logger.info(
            "Iniciando correcao com %s (%d tools: %s)",
            self.model_name,
            len(tools),
            ", ".join(t.name for t in tools),
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": render_correction_prompt(report_markdown)}]}
        )
        return final_text(result.get("messages", []))
