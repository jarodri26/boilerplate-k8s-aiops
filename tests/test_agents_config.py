import logging

import pytest

from my_agent_app.agents import config

ENVS = [
    "AGENT_MODEL_NAME",
    "MCP_SERVER_URL",
    "AGENT_MAX_ITERATIONS",
    "AGENT_TIMEOUT_MINUTES",
    "ANALYSIS_MAX_CONCURRENCY",
    "ANALYSIS_STALE_TIMEOUT_MINUTES",
]


@pytest.fixture(autouse=True)
def _limpa_env(monkeypatch):
    for env in ENVS:
        monkeypatch.delenv(env, raising=False)


def test_padroes():
    assert config.get_agent_model_name() == "claude-haiku-4-5"
    assert config.get_mcp_server_url() == "http://localhost:3001/mcp"
    assert config.get_agent_max_iterations() == 25
    assert config.get_analysis_max_concurrency() == 1
    assert config.get_analysis_stale_timeout_seconds() == 30 * 60
    assert config.get_agent_timeout_seconds(30 * 60) == 20 * 60


def test_valores_validos(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL_NAME", "claude-sonnet-4-5")
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "5")
    monkeypatch.setenv("ANALYSIS_MAX_CONCURRENCY", "3")
    monkeypatch.setenv("ANALYSIS_STALE_TIMEOUT_MINUTES", "45")
    monkeypatch.setenv("AGENT_TIMEOUT_MINUTES", "0.5")
    assert config.get_agent_model_name() == "claude-sonnet-4-5"
    assert config.get_agent_max_iterations() == 5
    assert config.get_analysis_max_concurrency() == 3
    assert config.get_analysis_stale_timeout_seconds() == 45 * 60
    assert config.get_agent_timeout_seconds(45 * 60) == 30


@pytest.mark.parametrize(
    ("env", "getter", "expected"),
    [
        ("AGENT_MAX_ITERATIONS", config.get_agent_max_iterations, 25),
        ("ANALYSIS_MAX_CONCURRENCY", config.get_analysis_max_concurrency, 1),
        ("ANALYSIS_STALE_TIMEOUT_MINUTES", config.get_analysis_stale_timeout_seconds, 1800),
        ("AGENT_TIMEOUT_MINUTES", lambda: config.get_agent_timeout_seconds(1800), 1200),
    ],
)
@pytest.mark.parametrize("raw", ["abc", "0", "-3"])
def test_valor_invalido_usa_padrao_com_warning(monkeypatch, caplog, env, getter, expected, raw):
    monkeypatch.setenv(env, raw)
    with caplog.at_level(logging.WARNING):
        assert getter() == expected
    assert env in caplog.text


def test_iteracoes_fracionarias_sao_invalidas(monkeypatch, caplog):
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "2.5")
    with caplog.at_level(logging.WARNING):
        assert config.get_agent_max_iterations() == 25


@pytest.mark.parametrize("raw", ["30", "40"])
def test_timeout_maior_ou_igual_ao_stale_e_limitado(monkeypatch, caplog, raw):
    monkeypatch.setenv("AGENT_TIMEOUT_MINUTES", raw)
    with caplog.at_level(logging.WARNING):
        assert config.get_agent_timeout_seconds(30 * 60) == 29 * 60
    assert "AGENT_TIMEOUT_MINUTES" in caplog.text
