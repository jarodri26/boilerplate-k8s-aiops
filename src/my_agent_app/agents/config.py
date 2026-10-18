import logging
import math
import os

logger = logging.getLogger(__name__)

DEFAULT_AGENT_MODEL_NAME = "claude-haiku-4-5"
DEFAULT_MCP_SERVER_URL = "http://localhost:3001/mcp"
DEFAULT_AGENT_MAX_ITERATIONS = 25
DEFAULT_AGENT_TIMEOUT_MINUTES = 20
DEFAULT_ANALYSIS_MAX_CONCURRENCY = 1
DEFAULT_ANALYSIS_STALE_TIMEOUT_MINUTES = 30
DEFAULT_CORRECTION_MAX_ITERATIONS = 25
DEFAULT_CORRECTION_TIMEOUT_MINUTES = 10


def _positive_number(env: str, default: float, integer: bool = False) -> float:
    raw = os.environ.get(env)
    if raw is None or raw.strip() == "":
        return default

    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        value = None

    if value is None or not math.isfinite(value) or value <= 0:
        logger.warning("%s invalido (%r); usando o padrao de %s", env, raw, default)
        return default

    return value


def get_agent_model_name() -> str:
    return os.environ.get("AGENT_MODEL_NAME") or DEFAULT_AGENT_MODEL_NAME


def get_mcp_server_url() -> str:
    return os.environ.get("MCP_SERVER_URL") or DEFAULT_MCP_SERVER_URL


def get_agent_max_iterations() -> int:
    return int(_positive_number("AGENT_MAX_ITERATIONS", DEFAULT_AGENT_MAX_ITERATIONS, integer=True))


def get_analysis_max_concurrency() -> int:
    return int(
        _positive_number("ANALYSIS_MAX_CONCURRENCY", DEFAULT_ANALYSIS_MAX_CONCURRENCY, integer=True)
    )


def get_analysis_stale_timeout_seconds() -> float:
    minutes = _positive_number(
        "ANALYSIS_STALE_TIMEOUT_MINUTES", DEFAULT_ANALYSIS_STALE_TIMEOUT_MINUTES
    )
    return minutes * 60


def get_agent_timeout_seconds(stale_seconds: float) -> float:
    """Prazo total do run do agente; precisa ficar abaixo do stale timeout (PRD 002, D6)."""
    timeout = _positive_number("AGENT_TIMEOUT_MINUTES", DEFAULT_AGENT_TIMEOUT_MINUTES) * 60
    if timeout >= stale_seconds:
        capped = max(stale_seconds - 60, stale_seconds / 2)
        logger.warning(
            "AGENT_TIMEOUT_MINUTES (%s min) deve ser menor que ANALYSIS_STALE_TIMEOUT_MINUTES "
            "(%s min); usando %s min",
            timeout / 60,
            stale_seconds / 60,
            capped / 60,
        )
        return capped
    return timeout


def get_correction_model_name() -> str:
    """Modelo do agente de correcao (PRD 004, D7); sem override, o mesmo da analise."""
    return os.environ.get("CORRECTION_MODEL_NAME") or get_agent_model_name()


def get_correction_max_iterations() -> int:
    return int(
        _positive_number(
            "CORRECTION_MAX_ITERATIONS", DEFAULT_CORRECTION_MAX_ITERATIONS, integer=True
        )
    )


def get_correction_timeout_seconds() -> float:
    """Prazo total de uma correcao (PRD 004, D3)."""
    return _positive_number("CORRECTION_TIMEOUT_MINUTES", DEFAULT_CORRECTION_TIMEOUT_MINUTES) * 60
