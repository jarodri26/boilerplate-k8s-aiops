import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.exc import InterfaceError, OperationalError

from my_agent_app.agents.report_parser import ParsedProblem, parse_problems
from my_agent_app.models.repository import ReportRepository

logger = logging.getLogger(__name__)

# Falhas transitorias de banco que justificam repetir o swap (D8)
RETRYABLE_DB_ERRORS = (OperationalError, InterfaceError, OSError)
REPLACE_RETRY_DELAYS = (1, 2, 4)


class Analyzer(Protocol):
    async def run(self, events: list[dict]) -> str: ...


class EventHandler:
    """Pipeline de analise de causa raiz dos eventos coletados (PRD 002).

    Nunca propaga excecao ao coletor: toda falha e registrada no log.
    """

    def __init__(
        self,
        repository: ReportRepository,
        analyzer: Analyzer,
        *,
        stale_seconds: float,
        timeout_seconds: float,
        max_concurrency: int,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.repository = repository
        self.analyzer = analyzer
        self.stale_seconds = stale_seconds
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._sleep = sleep

    async def handle(self, events: list[dict]) -> None:
        try:
            await self._handle(events)
        except Exception:
            logger.exception("Erro no pipeline de analise de %d evento(s)", len(events))

    async def _handle(self, events: list[dict]) -> None:
        with_uid = [ev for ev in events if ev.get("uid")]
        if len(with_uid) < len(events):
            logger.warning(
                "%d evento(s) sem uid descartado(s) antes da analise", len(events) - len(with_uid)
            )
        if not with_uid:
            return

        try:
            batch_id, new_uids = await self.repository.register_batch(
                [ev["uid"] for ev in with_uid], self.stale_seconds
            )
        except Exception:
            logger.exception(
                "Banco indisponivel na deduplicacao; batch de %d evento(s) descartado",
                len(with_uid),
            )
            return

        if batch_id is None:
            logger.info("Todos os %d evento(s) do batch ja estao em tratamento", len(with_uid))
            return

        new_set = set(new_uids)
        new_events = [ev for ev in with_uid if ev["uid"] in new_set]
        logger.info("Batch %s registrado com %d evento(s) novo(s)", batch_id, len(new_uids))

        # Semaforo adquirido depois do insert: na fila o batch ja conta como "em tratamento"
        async with self._semaphore:
            await self._analyze(batch_id, new_uids, new_events)

    async def _analyze(self, batch_id: uuid.UUID, uids: list[str], events: list[dict]) -> None:
        if not await self.repository.start_analysis(batch_id):
            logger.warning(
                "Batch %s liberado (estagnado) enquanto aguardava vaga; analise nao iniciada",
                batch_id,
            )
            return

        try:
            markdown = await asyncio.wait_for(self.analyzer.run(events), self.timeout_seconds)
        except TimeoutError:
            logger.error(
                "Analise do batch %s excedeu o prazo de %s min", batch_id, self.timeout_seconds / 60
            )
            await self._mark_incomplete(batch_id)
            return
        except Exception:
            logger.exception("Falha na analise do batch %s", batch_id)
            await self._mark_incomplete(batch_id)
            return

        result = parse_problems(markdown, uids)
        for warning in result.warnings:
            logger.warning("Batch %s: %s", batch_id, warning)

        if not result.problems:
            logger.error(
                "Resposta do agente sem secoes de problema para o batch %s; marcado INCOMPLETO",
                batch_id,
            )
            await self._mark_incomplete(batch_id)
            return

        applied = await self._replace_with_retry(batch_id, result.problems, markdown)
        if applied is False:
            logger.warning(
                "Batch %s ja nao estava EM_ANALISE; resultado da analise descartado", batch_id
            )
        elif applied:
            logger.info("Batch %s substituido por %d relatorio(s)", batch_id, len(result.problems))

    async def _replace_with_retry(
        self, batch_id: uuid.UUID, problems: list[ParsedProblem], markdown: str
    ) -> bool | None:
        """True/False = resultado do swap; None = falha definitiva de banco."""
        for attempt, delay in enumerate((*REPLACE_RETRY_DELAYS, None)):
            try:
                return await self.repository.replace_batch(batch_id, problems)
            except RETRYABLE_DB_ERRORS as e:
                if delay is None:
                    logger.error(
                        "Falha definitiva ao persistir relatorios do batch %s (%s). "
                        "Markdown gerado:\n%s",
                        batch_id,
                        e,
                        markdown,
                    )
                    return None
                logger.warning(
                    "Falha ao persistir relatorios do batch %s (tentativa %d): %s",
                    batch_id,
                    attempt + 1,
                    e,
                )
                await self._sleep(delay)
        return None

    async def _mark_incomplete(self, batch_id: uuid.UUID) -> None:
        try:
            await self.repository.mark_incomplete(batch_id)
        except Exception:
            logger.exception("Falha ao marcar o batch %s como INCOMPLETO", batch_id)
