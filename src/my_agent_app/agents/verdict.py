import logging
import re

from my_agent_app.models.report import ReportStatus

logger = logging.getLogger(__name__)

# Token no inicio da linha, tolerando marcacao Markdown antes (lista, titulo, citacao,
# negrito) e negrito entre o token e o ":" -- ex.: "**FALHA:**", "- **CORRIGIDO**:"
_VERDICT_RE = re.compile(r"^[\s>#*_-]*(CORRIGIDO|FALHA)[*_]*:", re.MULTILINE)


def parse_verdict(text: str) -> ReportStatus:
    """Veredito da resposta do agente de correcao (PRD 004, D6).

    CORRIGIDO so quando ha linha(s) CORRIGIDO: e nenhuma FALHA:; ausente ou ambiguo -> falha.
    """
    tokens = set(_VERDICT_RE.findall(text or ""))
    if tokens == {"CORRIGIDO"}:
        return ReportStatus.CORRIGIDO
    if tokens == {"FALHA"}:
        return ReportStatus.FALHA_CORRECAO

    if tokens:
        logger.warning("Resposta da correcao com vereditos CORRIGIDO e FALHA; tratada como falha")
    else:
        logger.warning("Resposta da correcao sem veredito CORRIGIDO:/FALHA:; tratada como falha")
    return ReportStatus.FALHA_CORRECAO
