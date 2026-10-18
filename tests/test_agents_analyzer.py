import pytest
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from my_agent_app.agents.analyzer import RootCauseAnalyzer, final_text


@tool("kubectl_get")
def _kubectl_get(name: str = "") -> str:
    """fake"""
    return name


class FakeAgent:
    def __init__(self, messages):
        self.messages = messages
        self.inputs = None

    async def ainvoke(self, inputs):
        self.inputs = inputs
        return {"messages": self.messages}


def _analyzer(monkeypatch, messages, captured):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = FakeAgent(messages)

    async def loader(url):
        captured["url"] = url
        return [_kubectl_get]

    def factory(**kwargs):
        captured.update(kwargs)
        return agent

    analyzer = RootCauseAnalyzer(
        "claude-test", 7, "http://mcp/mcp", tools_loader=loader, agent_factory=factory
    )
    return analyzer, agent


async def test_configuracao_repassada_ao_create_agent(monkeypatch):
    captured = {}
    analyzer, agent = _analyzer(monkeypatch, [AIMessage(content="## Problema 1: x")], captured)

    out = await analyzer.run([{"uid": "u1"}])

    assert out == "## Problema 1: x"
    assert captured["url"] == "http://mcp/mcp"
    assert [t.name for t in captured["tools"]] == ["kubectl_get"]
    model = captured["model"]
    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-test" and model.max_retries == 3
    (limit,) = captured["middleware"]
    assert isinstance(limit, ModelCallLimitMiddleware)
    assert limit.run_limit == 7 and limit.exit_behavior == "end"
    (msg,) = agent.inputs["messages"]
    assert msg["role"] == "user" and '"uid": "u1"' in msg["content"]


async def test_falha_do_loader_propaga(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    async def loader(url):
        raise ConnectionError("MCP fora")

    analyzer = RootCauseAnalyzer("m", 1, "http://x", tools_loader=loader)
    with pytest.raises(ConnectionError):
        await analyzer.run([{"uid": "u1"}])


def test_final_text_concatena_blocos():
    msg = AIMessage(content=[{"type": "text", "text": "## Problema"}, {"type": "text", "text": " 1"}])

    assert final_text([HumanMessage(content="p"), msg]) == "## Problema 1"


def test_final_text_vazio_quando_run_termina_em_chamada_de_tool():
    pendente = AIMessage(content="", tool_calls=[{"name": "kubectl_get", "args": {}, "id": "1"}])

    assert final_text([pendente]) == ""
    assert final_text([pendente, ToolMessage(content="x", tool_call_id="1")]) == ""
    assert final_text([]) == ""
