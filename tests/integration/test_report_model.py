import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from my_agent_app.models.report import Report, ReportStatus, Severity


async def test_grava_e_le_relatorio(sessionmaker):
    async with sessionmaker() as session:
        report = Report(
            markdown="## Problema 1: x",
            status=ReportStatus.COMPLETO,
            severity=Severity.ALTO,
            event_uids=["u1", "u2"],
        )
        session.add(report)
        await session.commit()
        report_id = report.id

    async with sessionmaker() as session:
        saved = (await session.execute(select(Report).where(Report.id == report_id))).scalar_one()

    assert saved.status == "COMPLETO"
    assert saved.severity == "ALTO"
    assert saved.event_uids == ["u1", "u2"]
    assert saved.created_at is not None and saved.updated_at is not None


async def test_status_invalido_e_rejeitado(sessionmaker):
    async with sessionmaker() as session:
        session.add(Report(markdown="", status="QUALQUER", event_uids=["u1"]))
        with pytest.raises(IntegrityError, match="ck_reports_status"):
            await session.commit()


async def test_severidade_invalida_e_rejeitada(sessionmaker):
    async with sessionmaker() as session:
        session.add(
            Report(markdown="", status=ReportStatus.COMPLETO, severity="URGENTE", event_uids=["u1"])
        )
        with pytest.raises(IntegrityError, match="ck_reports_severity"):
            await session.commit()
