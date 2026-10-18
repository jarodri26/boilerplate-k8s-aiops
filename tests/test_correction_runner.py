import asyncio
import logging
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy.exc import OperationalError

from my_agent_app.correction.runner import (
    ERROR_MESSAGE,
    NO_RESPONSE_MESSAGE,
    CorrectionRunner,
)
from my_agent_app.models.report import ReportStatus

MARKDOWN = "## Problema 1: Imagem inexistente"
RESPOSTA = "CORRIGIDO: imagem trocada\n\n## Acoes Executadas\n### Problema 1: Imagem inexistente"


@dataclass
class FakeReport:
    status: str = ReportStatus.CORRIGINDO
    markdown: str = MARKDOWN


class FakeRepository:
    def __init__(self, report=None, finish_results=(True,), get_error=None):
        self.report = report if report is not None else FakeReport()
        self.finish_results = list(finish_results)
        self.get_error = get_error
        self.finished = []

    async def get_report(self, report_id):
        if self.get_error:
            raise self.get_error
        return self.report

    async def finish_correction(self, report_id, status, result):
        outcome = self.finish_results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        self.finished.append((report_id, status, result))
        return outcome


class FakeAgent:
    def __init__(self, response="", error=None, delay=0):
        self.response = response
        self.error = error
        self.delay = delay
        self.inputs = []

    async def run(self, report_markdown):
        self.inputs.append(report_markdown)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.response


def _runner(repo, agent, timeout=60, sleeps=None):
    async def sleep(delay):
        if sleeps is not None:
            sleeps.append(delay)

    return CorrectionRunner(repo, agent, timeout_seconds=timeout, sleep=sleep)


async def test_corrigido_grava_a_resposta_do_agente():
    repo, agent = FakeRepository(), FakeAgent(RESPOSTA)
    report_id = uuid.uuid4()

    await _runner(repo, agent).run(report_id)

    assert agent.inputs == [MARKDOWN]
    assert repo.finished == [(report_id, ReportStatus.CORRIGIDO, RESPOSTA)]


async def test_sem_veredito_vira_falha_com_a_resposta():
    repo = FakeRepository()

    await _runner(repo, FakeAgent("Apliquei o patch.")).run(uuid.uuid4())

    ((_, status, result),) = repo.finished
    assert status == ReportStatus.FALHA_CORRECAO and result == "Apliquei o patch."


async def test_resposta_vazia_grava_mensagem_sem_resposta():
    repo = FakeRepository()

    await _runner(repo, FakeAgent("")).run(uuid.uuid4())

    assert repo.finished[0][1:] == (ReportStatus.FALHA_CORRECAO, NO_RESPONSE_MESSAGE)


async def test_prazo_esgotado(caplog):
    repo = FakeRepository()

    await _runner(repo, FakeAgent(RESPOSTA, delay=1), timeout=0.6).run(uuid.uuid4())

    ((_, status, result),) = repo.finished
    assert status == ReportStatus.FALHA_CORRECAO
    assert result == "FALHA: prazo de 0.01 min da correção esgotado."
    assert "excedeu o prazo" in caplog.text


async def test_erro_do_agente_grava_mensagem_sem_stack_trace(caplog):
    repo = FakeRepository()

    await _runner(repo, FakeAgent(error=ConnectionRefusedError("segredo-interno"))).run(uuid.uuid4())

    ((_, status, result),) = repo.finished
    assert status == ReportStatus.FALHA_CORRECAO and result == ERROR_MESSAGE
    assert "segredo-interno" not in result and "Traceback" not in result
    assert "segredo-interno" in caplog.text  # stack so no log


async def test_finish_sem_linhas_registra_descarte(caplog):
    repo = FakeRepository(finish_results=(False,))

    with caplog.at_level(logging.WARNING):
        await _runner(repo, FakeAgent(RESPOSTA)).run(uuid.uuid4())

    assert "resultado da correcao descartado" in caplog.text


async def test_erro_transitorio_do_banco_e_repetido():
    erro = OperationalError("UPDATE", {}, Exception("conexao perdida"))
    repo, sleeps = FakeRepository(finish_results=(erro, erro, True)), []

    await _runner(repo, FakeAgent(RESPOSTA), sleeps=sleeps).run(uuid.uuid4())

    assert sleeps == [1, 2]
    assert repo.finished[0][1] == ReportStatus.CORRIGIDO


async def test_falha_definitiva_do_banco_loga_o_resultado(caplog):
    erro = OperationalError("UPDATE", {}, Exception("fora do ar"))
    repo, sleeps = FakeRepository(finish_results=(erro,) * 4), []

    await _runner(repo, FakeAgent(RESPOSTA), sleeps=sleeps).run(uuid.uuid4())

    assert sleeps == [1, 2, 4]
    assert "Falha definitiva" in caplog.text and "CORRIGIDO: imagem trocada" in caplog.text


@pytest.mark.parametrize(
    "repo",
    [
        FakeRepository(report=FakeReport(status=ReportStatus.FALHA_CORRECAO)),
        FakeRepository(get_error=OperationalError("SELECT", {}, Exception("x"))),
    ],
)
async def test_nao_executa_sem_relatorio_em_corrigindo(repo):
    agent = FakeAgent(RESPOSTA)

    await _runner(repo, agent).run(uuid.uuid4())

    assert agent.inputs == [] and repo.finished == []


async def test_relatorio_inexistente_apenas_logado(caplog):
    repo = FakeRepository()
    repo.report = None
    agent = FakeAgent(RESPOSTA)

    with caplog.at_level(logging.WARNING):
        await _runner(repo, agent).run(uuid.uuid4())

    assert agent.inputs == [] and "inexistente" in caplog.text
