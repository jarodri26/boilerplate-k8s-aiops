import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from my_agent_app.models.report import Report, ReportStatus
from my_agent_app.models.repository import (
    CORRECTION_INTERRUPTED_MESSAGE,
    ReportRepository,
    StartupRecovery,
)

STALE = 30 * 60


@dataclass
class Draft:
    markdown: str
    event_uids: list[str]
    severity: str | None
    status: str


@pytest.fixture
def repo(sessionmaker):
    return ReportRepository(sessionmaker)


async def _add(sessionmaker, status, uids, age: timedelta = timedelta(0)) -> uuid.UUID:
    when = datetime.now(timezone.utc) - age
    async with sessionmaker.begin() as session:
        report = Report(markdown="", status=status, event_uids=uids, created_at=when, updated_at=when)
        session.add(report)
    return report.id


async def _all(sessionmaker) -> list[Report]:
    async with sessionmaker() as session:
        return list((await session.execute(select(Report).order_by(Report.created_at))).scalars())


async def _get(sessionmaker, report_id) -> Report | None:
    async with sessionmaker() as session:
        return await session.get(Report, report_id)


# --- 2.1 recover_on_startup ---------------------------------------------------------


async def test_recover_on_startup_marca_orfaos(sessionmaker, repo):
    orfao = await _add(sessionmaker, ReportStatus.EM_ANALISE, ["u1"])
    completo = await _add(sessionmaker, ReportStatus.COMPLETO, ["u2"])
    corrigindo = await _add(sessionmaker, ReportStatus.CORRIGINDO, ["u3"])

    assert await repo.recover_on_startup() == StartupRecovery(analyses=1, corrections=1)

    assert (await _get(sessionmaker, orfao)).status == ReportStatus.INCOMPLETO
    assert (await _get(sessionmaker, completo)).status == ReportStatus.COMPLETO
    recuperado = await _get(sessionmaker, corrigindo)
    assert recuperado.status == ReportStatus.FALHA_CORRECAO
    assert recuperado.correction_result == CORRECTION_INTERRUPTED_MESSAGE


# --- 2.2 register_batch -----------------------------------------------------------


async def test_evento_novo_gera_relatorio_em_analise(sessionmaker, repo):
    batch_id, novos = await repo.register_batch(["u1", "u2"], STALE)

    assert novos == ["u1", "u2"]
    batch = await _get(sessionmaker, batch_id)
    assert batch.status == ReportStatus.EM_ANALISE
    assert batch.event_uids == ["u1", "u2"]
    assert batch.severity is None


@pytest.mark.parametrize(
    "status",
    [
        ReportStatus.EM_ANALISE,
        ReportStatus.COMPLETO,
        ReportStatus.CORRIGINDO,
        ReportStatus.FALHA_CORRECAO,
    ],
)
async def test_evento_em_relatorio_ativo_e_ignorado(sessionmaker, repo, status):
    await _add(sessionmaker, status, ["u1"])

    batch_id, novos = await repo.register_batch(["u1"], STALE)

    assert batch_id is None and novos == []
    assert len(await _all(sessionmaker)) == 1  # nenhum insert


@pytest.mark.parametrize("status", [ReportStatus.CORRIGIDO, ReportStatus.INCOMPLETO])
async def test_evento_em_relatorio_corrigido_ou_incompleto_e_reanalisado(sessionmaker, repo, status):
    await _add(sessionmaker, status, ["u1"])

    batch_id, novos = await repo.register_batch(["u1"], STALE)

    assert batch_id is not None and novos == ["u1"]


async def test_corrigido_antigo_e_em_analise_atual_e_ignorado(sessionmaker, repo):
    await _add(sessionmaker, ReportStatus.CORRIGIDO, ["u1"], age=timedelta(days=1))
    await _add(sessionmaker, ReportStatus.EM_ANALISE, ["u1"])

    batch_id, novos = await repo.register_batch(["u1"], STALE)

    assert batch_id is None and novos == []


async def test_batch_parcialmente_em_tratamento(sessionmaker, repo):
    await _add(sessionmaker, ReportStatus.COMPLETO, ["u1", "outro"])

    batch_id, novos = await repo.register_batch(["u1", "u2"], STALE)

    assert novos == ["u2"]
    assert (await _get(sessionmaker, batch_id)).event_uids == ["u2"]


async def test_em_analise_estagnado_e_liberado(sessionmaker, repo):
    estagnado = await _add(sessionmaker, ReportStatus.EM_ANALISE, ["u1"], age=timedelta(minutes=31))

    batch_id, novos = await repo.register_batch(["u1"], STALE)

    assert novos == ["u1"]
    assert (await _get(sessionmaker, estagnado)).status == ReportStatus.INCOMPLETO
    assert (await _get(sessionmaker, batch_id)).status == ReportStatus.EM_ANALISE


async def test_em_analise_dentro_do_prazo_e_mantido(sessionmaker, repo):
    recente = await _add(sessionmaker, ReportStatus.EM_ANALISE, ["u1"], age=timedelta(minutes=10))

    batch_id, _ = await repo.register_batch(["u1"], STALE)

    assert batch_id is None
    assert (await _get(sessionmaker, recente)).status == ReportStatus.EM_ANALISE


async def test_stale_e_medido_por_updated_at(sessionmaker, repo):
    # criado ha muito tempo, mas renovado agora (inicio efetivo da investigacao)
    report_id = await _add(sessionmaker, ReportStatus.EM_ANALISE, ["u1"], age=timedelta(hours=2))
    assert await repo.start_analysis(report_id)

    batch_id, _ = await repo.register_batch(["u1"], STALE)

    assert batch_id is None
    assert (await _get(sessionmaker, report_id)).status == ReportStatus.EM_ANALISE


# --- 2.3 start_analysis, mark_incomplete, replace_batch ------------------------------


async def test_start_analysis_renova_updated_at(sessionmaker, repo):
    report_id = await _add(sessionmaker, ReportStatus.EM_ANALISE, ["u1"], age=timedelta(minutes=20))
    antes = (await _get(sessionmaker, report_id)).updated_at

    assert await repo.start_analysis(report_id) is True

    assert (await _get(sessionmaker, report_id)).updated_at > antes


async def test_start_analysis_falso_se_batch_liberado(sessionmaker, repo):
    report_id = await _add(sessionmaker, ReportStatus.INCOMPLETO, ["u1"])

    assert await repo.start_analysis(report_id) is False


async def test_mark_incomplete(sessionmaker, repo):
    report_id = await _add(sessionmaker, ReportStatus.EM_ANALISE, ["u1"])

    assert await repo.mark_incomplete(report_id) is True
    assert (await _get(sessionmaker, report_id)).status == ReportStatus.INCOMPLETO


async def test_mark_incomplete_nao_sobrescreve_outro_status(sessionmaker, repo):
    report_id = await _add(sessionmaker, ReportStatus.COMPLETO, ["u1"])

    assert await repo.mark_incomplete(report_id) is False
    assert (await _get(sessionmaker, report_id)).status == ReportStatus.COMPLETO


async def test_replace_batch_substitui_pelos_relatorios_por_problema(sessionmaker, repo):
    batch_id, _ = await repo.register_batch(["u1", "u2", "u3"], STALE)
    drafts = [
        Draft("## Problema 1: a", ["u1", "u2"], "ALTO", ReportStatus.COMPLETO),
        Draft("## Problema 2: b", ["u3"], None, ReportStatus.INCOMPLETO),
    ]

    assert await repo.replace_batch(batch_id, drafts) is True

    assert await _get(sessionmaker, batch_id) is None
    reports = {r.markdown: r for r in await _all(sessionmaker)}
    assert set(reports) == {"## Problema 1: a", "## Problema 2: b"}
    assert reports["## Problema 1: a"].event_uids == ["u1", "u2"]
    assert reports["## Problema 1: a"].severity == "ALTO"
    assert reports["## Problema 1: a"].status == ReportStatus.COMPLETO
    assert reports["## Problema 2: b"].status == ReportStatus.INCOMPLETO
    assert len({r.id for r in reports.values()}) == 2


async def test_replace_batch_recusado_se_batch_ja_liberado(sessionmaker, repo):
    batch_id, _ = await repo.register_batch(["u1"], STALE)
    async with sessionmaker.begin() as session:
        await session.execute(
            update(Report).where(Report.id == batch_id).values(status=ReportStatus.INCOMPLETO)
        )

    drafts = [Draft("## Problema 1: a", ["u1"], "ALTO", ReportStatus.COMPLETO)]
    assert await repo.replace_batch(batch_id, drafts) is False

    reports = await _all(sessionmaker)
    assert [(r.id, r.status) for r in reports] == [(batch_id, ReportStatus.INCOMPLETO)]


# --- leituras da interface web (PRD 003) ------------------------------------------------


async def test_list_reports_ordena_por_created_at_decrescente(sessionmaker, repo):
    antigo = await _add(sessionmaker, ReportStatus.COMPLETO, ["u1"], age=timedelta(hours=2))
    novo = await _add(sessionmaker, ReportStatus.INCOMPLETO, ["u2"])
    meio = await _add(sessionmaker, ReportStatus.CORRIGIDO, ["u3"], age=timedelta(hours=1))

    assert [r.id for r in await repo.list_reports()] == [novo, meio, antigo]


async def test_list_reports_vazio(repo):
    assert await repo.list_reports() == []


async def test_get_report(sessionmaker, repo):
    report_id = await _add(sessionmaker, ReportStatus.COMPLETO, ["u1"])

    report = await repo.get_report(report_id)

    assert report.id == report_id and report.status == ReportStatus.COMPLETO
    assert await repo.get_report(uuid.uuid4()) is None


# --- PRD 004: transicoes de correcao ----------------------------------------------


async def _set_result(sessionmaker, report_id, result):
    async with sessionmaker.begin() as session:
        await session.execute(
            update(Report).where(Report.id == report_id).values(correction_result=result)
        )


@pytest.mark.parametrize("status", [ReportStatus.COMPLETO, ReportStatus.FALHA_CORRECAO])
async def test_start_correction_de_status_elegivel(sessionmaker, repo, status):
    report_id = await _add(sessionmaker, status, ["u1"], age=timedelta(hours=1))
    await _set_result(sessionmaker, report_id, "FALHA: tentativa anterior")
    before = (await _get(sessionmaker, report_id)).updated_at

    assert await repo.start_correction(report_id) is True

    report = await _get(sessionmaker, report_id)
    assert report.status == ReportStatus.CORRIGINDO
    assert report.correction_result is None
    assert report.updated_at > before


@pytest.mark.parametrize(
    "status",
    [
        ReportStatus.EM_ANALISE,
        ReportStatus.INCOMPLETO,
        ReportStatus.CORRIGINDO,
        ReportStatus.CORRIGIDO,
    ],
)
async def test_start_correction_recusa_status_nao_elegivel(sessionmaker, repo, status):
    report_id = await _add(sessionmaker, status, ["u1"])

    assert await repo.start_correction(report_id) is False
    assert (await _get(sessionmaker, report_id)).status == status


async def test_start_correction_de_relatorio_inexistente(repo):
    assert await repo.start_correction(uuid.uuid4()) is False


async def test_start_correction_concorrente_so_uma_vence(sessionmaker, repo):
    report_id = await _add(sessionmaker, ReportStatus.COMPLETO, ["u1"])
    other = ReportRepository(sessionmaker)  # cada chamada abre sua propria sessao

    results = await asyncio.gather(repo.start_correction(report_id), other.start_correction(report_id))

    assert sorted(results) == [False, True]


async def test_finish_correction_grava_status_e_resultado(sessionmaker, repo):
    report_id = await _add(sessionmaker, ReportStatus.CORRIGINDO, ["u1"])

    assert await repo.finish_correction(report_id, ReportStatus.CORRIGIDO, "CORRIGIDO: ok") is True

    report = await _get(sessionmaker, report_id)
    assert report.status == ReportStatus.CORRIGIDO
    assert report.correction_result == "CORRIGIDO: ok"


async def test_finish_correction_ignorado_se_status_mudou(sessionmaker, repo):
    report_id = await _add(sessionmaker, ReportStatus.FALHA_CORRECAO, ["u1"])
    await _set_result(sessionmaker, report_id, CORRECTION_INTERRUPTED_MESSAGE)

    assert await repo.finish_correction(report_id, ReportStatus.CORRIGIDO, "CORRIGIDO: ok") is False

    report = await _get(sessionmaker, report_id)
    assert report.status == ReportStatus.FALHA_CORRECAO
    assert report.correction_result == CORRECTION_INTERRUPTED_MESSAGE
