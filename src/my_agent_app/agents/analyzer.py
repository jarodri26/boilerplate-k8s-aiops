import logging
from collections.abc import Awaitable, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from my_agent_app.agents.prompt import render_prompt
from my_agent_app.agents.tools import load_read_only_tools

logger = logging.getLogger(__name__)

MODEL_MAX_RETRIES = 3


def final_text(messages: list) -> str:
    """Texto da resposta final do agente; "" se o run encerrou sem resposta em texto."""
    if not messages:
        return ""
    last = messages[-1]
    # Limite de iteracoes com exit_behavior="end" pode encerrar apos uma chamada de tool
    if not isinstance(last, AIMessage) or last.tool_calls:
        return ""
    return last.text.strip()


class RootCauseAnalyzer:
    """Agente LangChain + Claude que investiga os eventos via MCP (somente leitura)."""

    def __init__(
        self,
        model_name: str,
        max_iterations: int,
        mcp_server_url: str,
        tools_loader: Callable[[str], Awaitable[list[BaseTool]]] = load_read_only_tools,
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
                ModelCallLimitMiddleware(run_limit=self.max_iterations, exit_behavior="end")
            ],
        )

    async def run(self, events: list[dict]) -> str:
        # cliente MCP por analise: indisponibilidade vira excecao aqui (-> INCOMPLETO)
        tools = await self._tools_loader(self.mcp_server_url)
        agent = self._build_agent(tools)
        logger.info(
            "Iniciando analise de %d evento(s) com %s (tools: %s)",
            len(events),
            self.model_name,
            ", ".join(t.name for t in tools),
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": render_prompt(events)}]}
        )
        return final_text(result.get("messages", []))
