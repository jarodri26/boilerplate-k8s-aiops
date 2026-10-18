import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from my_agent_app.models.report import ACTIVE_STATUSES, Report, ReportStatus


class ReportDraft(Protocol):
    """Relatorio por problema a gravar no swap (ver agents/report_parser.py)."""

    markdown: str
    event_uids: list[str]
    severity: str | None
    status: str


class ReportRepository:
    """Queries da tabela reports: pipeline de analise (PRD 002) e interface web (PRD 003)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]):
        self._sessionmaker = sessionmaker

    async def list_reports(self) -> list[Report]:
        async with self._sessionmaker() as session:
            result = await session.execute(select(Report).order_by(Report.created_at.desc()))
            return list(result.scalars())

    async def get_report(self, report_id: uuid.UUID) -> Report | None:
        async with self._sessionmaker() as session:
            return await session.get(Report, report_id)

    async def recover_on_startup(self) -> int:
        """Analises interrompidas por crash/restart: EM_ANALISE -> INCOMPLETO."""
        async with self._sessionmaker.begin() as session:
            result = await session.execute(
                update(Report)
                .where(Report.status == ReportStatus.EM_ANALISE)
                .values(status=ReportStatus.INCOMPLETO, updated_at=func.now())
            )
            return result.rowcount

    async def register_batch(
        self, uids: Sequence[str], stale_seconds: float
    ) -> tuple[uuid.UUID | None, list[str]]:
        """Libera estagnados, deduplica e grava o EM_ANALISE do batch, em uma transacao.

        Retorna o id do relatorio do batch (None se todos os eventos ja estao em
        tratamento) e os uids novos, na ordem recebida.
        """
        async with self._sessionmaker.begin() as session:
            await session.execute(
                update(Report)
                .where(
                    Report.status == ReportStatus.EM_ANALISE,
                    Report.updated_at < func.now() - timedelta(seconds=stale_seconds),
                )
                .values(status=ReportStatus.INCOMPLETO, updated_at=func.now())
            )

            # Existencia de QUALQUER relatorio ativo com o uid (D4), nunca o mais recente
            active = set(
                (
                    await session.execute(
                        select(func.unnest(Report.event_uids)).where(
                            Report.status.in_(ACTIVE_STATUSES),
                            Report.event_uids.overlap(list(uids)),
                        )
                    )
                ).scalars()
            )
            new_uids = list(dict.fromkeys(uid for uid in uids if uid not in active))
            if not new_uids:
                return None, []

            batch_id = uuid.uuid4()
            session.add(
                Report(
                    id=batch_id,
                    markdown="",
                    status=ReportStatus.EM_ANALISE,
                    event_uids=new_uids,
                )
            )
            return batch_id, new_uids

    async def start_analysis(self, batch_id: uuid.UUID) -> bool:
        """Renova updated_at ao iniciar a investigacao; False se o batch ja foi liberado."""
        async with self._sessionmaker.begin() as session:
            result = await session.execute(
                update(Report)
                .where(Report.id == batch_id, Report.status == ReportStatus.EM_ANALISE)
                .values(updated_at=func.now())
            )
            return result.rowcount == 1

    async def mark_incomplete(self, batch_id: uuid.UUID) -> bool:
        async with self._sessionmaker.begin() as session:
            result = await session.execute(
                update(Report)
                .where(Report.id == batch_id, Report.status == ReportStatus.EM_ANALISE)
                .values(status=ReportStatus.INCOMPLETO, updated_at=func.now())
            )
            return result.rowcount == 1

    async def replace_batch(self, batch_id: uuid.UUID, drafts: Sequence[ReportDraft]) -> bool:
        """Swap condicional (D3/D5): so substitui se o batch ainda estiver EM_ANALISE."""
        async with self._sessionmaker.begin() as session:
            deleted = (
                await session.execute(
                    delete(Report)
                    .where(Report.id == batch_id, Report.status == ReportStatus.EM_ANALISE)
                    .returning(Report.id)
                )
            ).first()
            if deleted is None:
                # nada foi alterado: a transacao vazia so e encerrada
                return False

            if drafts:
                await session.execute(
                    insert(Report),
                    [
                        {
                            "id": uuid.uuid4(),
                            "markdown": d.markdown,
                            "status": d.status,
                            "severity": d.severity,
                            "event_uids": list(d.event_uids),
                        }
                        for d in drafts
                    ],
                )
            return True
