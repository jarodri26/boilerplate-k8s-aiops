import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from my_agent_app.agents.verdict import parse_verdict
from my_agent_app.collector.handler import REPLACE_RETRY_DELAYS, RETRYABLE_DB_ERRORS
from my_agent_app.models.report import ReportStatus
from my_agent_app.models.repository import ReportRepository

logger = logging.getLogger(__name__)

# Resultado gravado quando nao ha resposta do agente (PRD 004, D4): sem detalhes da excecao
NO_RESPONSE_MESSAGE = (
    "FALHA: correção encerrada sem resposta final do agente "
    "(limite de chamadas ao modelo atingido ou resposta vazia)."
)
TIMEOUT_MESSAGE = "FALHA: prazo de {minutes:g} min da correção esgotado."
ERROR_MESSAGE = (
    "FALHA: erro ao executar a correção (MCP Server ou API do modelo indisponível). "
    "Detalhes no log da aplicação."
)


class Corrector(Protocol):
    async def run(self, report_markdown: str) -> str: ...


class CorrectionRunner:
    """Pipeline de correcao de um relatorio ja em CORRIGINDO (PRD 004).

    Roda como background task do POST /reports/{id}/fix; nunca propaga excecao.
    """

    def __init__(
        self,
        repository: ReportRepository,
        agent: Corrector,
        *,
        timeout_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.repository = repository
        self.agent = agent
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep

    async def run(self, report_id: uuid.UUID) -> None:
        try:
            await self._run(report_id)
        except Exception:
            logger.exception("Erro no pipeline de correcao do relatorio %s", report_id)

    async def _run(self, report_id: uuid.UUID) -> None:
        try:
            report = await self.repository.get_report(report_id)
        except Exception:
            # fica CORRIGINDO; a recuperacao de startup leva a FALHA_CORRECAO
            logger.exception("Banco indisponivel ao ler o relatorio %s para correcao", report_id)
            return
        if report is None or report.status != ReportStatus.CORRIGINDO:
            logger.warning(
                "Relatorio %s nao esta mais CORRIGINDO (%s); correcao nao iniciada",
                report_id,
                report.status if report else "inexistente",
            )
            return

        logger.info("Correcao do relatorio %s iniciada", report_id)
        try:
            text = await asyncio.wait_for(self.agent.run(report.markdown), self.timeout_seconds)
        except TimeoutError:
            logger.error(
                "Correcao do relatorio %s excedeu o prazo de %s min",
                report_id,
                self.timeout_seconds / 60,
            )
            status = ReportStatus.FALHA_CORRECAO
            result = TIMEOUT_MESSAGE.format(minutes=self.timeout_seconds / 60)
        except Exception:
            logger.exception("Falha na correcao do relatorio %s", report_id)
            status, result = ReportStatus.FALHA_CORRECAO, ERROR_MESSAGE
        else:
            status = parse_verdict(text)
            result = text or NO_RESPONSE_MESSAGE

        applied = await self._finish_with_retry(report_id, status, result)
        if applied is False:
            logger.warning(
                "Relatorio %s ja nao estava CORRIGINDO; resultado da correcao descartado",
                report_id,
            )
        elif applied:
            logger.info("Correcao do relatorio %s terminou com %s", report_id, status)

    async def _finish_with_retry(
        self, report_id: uuid.UUID, status: str, result: str
    ) -> bool | None:
        """True/False = resultado do UPDATE condicional; None = falha definitiva de banco."""
        for attempt, delay in enumerate((*REPLACE_RETRY_DELAYS, None)):
            try:
                return await self.repository.finish_correction(report_id, status, result)
            except RETRYABLE_DB_ERRORS as e:
                if delay is None:
                    logger.error(
                        "Falha definitiva ao gravar o resultado da correcao do relatorio %s (%s). "
                        "Status %s, resultado:\n%s",
                        report_id,
                        e,
                        status,
                        result,
                    )
                    return None
                logger.warning(
                    "Falha ao gravar o resultado da correcao do relatorio %s (tentativa %d): %s",
                    report_id,
                    attempt + 1,
                    e,
                )
                await self._sleep(delay)
        return None
