import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolErrorMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from my_agent_app.agents.corrector import CorrectionAgent

REPORT = "## Problema 1: Imagem inexistente\n### Comando Sugerido\nkubectl set image ..."


@tool("kubectl_patch")
def _kubectl_patch(name: str = "") -> str:
    """fake"""
    return name


class FakeAgent:
    def __init__(self, messages):
        self.messages = messages
        self.inputs = None

    async def ainvoke(self, inputs):
        self.inputs = inputs
        return {"messages": self.messages}


def _corrector(monkeypatch, messages, captured, loader=None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = FakeAgent(messages)

    async def default_loader(url):
        captured["url"] = url
        return [_kubectl_patch]

    def factory(**kwargs):
        captured.update(kwargs)
        return agent

    corrector = CorrectionAgent(
        "claude-test", 9, "http://mcp/mcp", tools_loader=loader or default_loader,
        agent_factory=factory,
    )
    return corrector, agent


async def test_configuracao_e_prompt_repassados(monkeypatch):
    captured = {}
    corrector, agent = _corrector(monkeypatch, [AIMessage(content="CORRIGIDO: ok")], captured)

    out = await corrector.run(REPORT)

    assert out == "CORRIGIDO: ok"
    assert captured["url"] == "http://mcp/mcp"
    assert [t.name for t in captured["tools"]] == ["kubectl_patch"]
    model = captured["model"]
    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-test" and model.max_retries == 3
    limit, tool_errors = captured["middleware"]
    assert isinstance(limit, ModelCallLimitMiddleware)
    assert isinstance(tool_errors, ToolErrorMiddleware)
    assert limit.run_limit == 9 and limit.exit_behavior == "end"
    (msg,) = agent.inputs["messages"]
    assert msg["role"] == "user"
    assert REPORT in msg["content"] and "agente AIOps especializado em correcao" in msg["content"]


async def test_limite_atingido_sem_resposta_final(monkeypatch):
    msg = AIMessage(content="", tool_calls=[{"name": "kubectl_get", "args": {}, "id": "1"}])
    corrector, _ = _corrector(monkeypatch, [msg], {})

    assert await corrector.run(REPORT) == ""


async def test_falha_do_loader_propaga(monkeypatch):
    async def loader(url):
        raise ConnectionRefusedError("MCP fora do ar")

    corrector, _ = _corrector(monkeypatch, [], {}, loader=loader)

    with pytest.raises(ConnectionRefusedError):
        await corrector.run(REPORT)


class _FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def test_erro_de_tool_nao_aborta_a_correcao(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    @tool("kubectl_generic")
    async def failing(command: str) -> str:
        """fake"""
        raise McpError(ErrorData(code=-32603, message="unknown command"))

    async def loader(url):
        return [failing]

    responses = iter(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "kubectl_generic", "args": {"command": "x"}, "id": "1"}],
            ),
            AIMessage(content="FALHA: comando rejeitado pelo cluster"),
        ]
    )

    def factory(**kwargs):
        # agente real com os middlewares do CorrectionAgent, so o modelo e falso
        return create_agent(**{**kwargs, "model": _FakeToolModel(messages=responses)})

    corrector = CorrectionAgent("claude-test", 5, "http://mcp", tools_loader=loader,
                                agent_factory=factory)

    assert await corrector.run(REPORT) == "FALHA: comando rejeitado pelo cluster"
