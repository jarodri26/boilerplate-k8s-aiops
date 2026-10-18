import asyncio
import logging
import uuid

import pytest
from sqlalchemy.exc import OperationalError

from my_agent_app.collector.handler import EventHandler

RESPOSTA = """# Relatorio

## Problema 1: Imagem inexistente
- **Severidade:** CRITICO
- **Eventos:** u1, u2

### Causa Raiz
Tag da imagem nao existe.

## Problema 2: OOMKilled
- **Severidade:** ALTO
- **Eventos:** u3

### Causa Raiz
Limite de memoria baixo.
"""


def _ev(uid):
    return {"uid": uid, "reason": "BackOff", "message": "m"}


class FakeRepository:
    def __init__(self, active=(), started=True, replace_results=(True,)):
        self.active = set(active)
        self.started = started
        self.replace_results = list(replace_results)
        self.registered = []
        self.incomplete = []
        self.replaced = []
        self.register_error = None

    async def register_batch(self, uids, stale_seconds):
        if self.register_error:
            raise self.register_error
        self.registered.append((list(uids), stale_seconds))
        new = [u for u in uids if u not in self.active]
        return (uuid.uuid4() if new else None), new

    async def start_analysis(self, batch_id):
        return self.started

    async def mark_incomplete(self, batch_id):
        self.incomplete.append(batch_id)
        return True

    async def replace_batch(self, batch_id, drafts):
        result = self.replace_results.pop(0)
        if isinstance(result, Exception):
            raise result
        self.replaced.append((batch_id, list(drafts)))
        return result


class FakeAnalyzer:
    def __init__(self, response=RESPOSTA, error=None, delay=0.0):
        self.response = response
        self.error = error
        self.delay = delay
        self.calls = []

    async def run(self, events):
        self.calls.append(events)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.response


def _handler(repo, analyzer, timeout=60.0, concurrency=1, sleeps=None):
    async def fake_sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    return EventHandler(
        repo,
        analyzer,
        stale_seconds=1800,
        timeout_seconds=timeout,
        max_concurrency=concurrency,
        sleep=fake_sleep,
    )


def _db_error():
    return OperationalError("UPDATE", {}, Exception("conexao perdida"))


# --- 6.1 fluxo principal -------------------------------------------------------------


async def test_eventos_sem_uid_sao_descartados(caplog):
    repo, analyzer = FakeRepository(), FakeAnalyzer()

    with caplog.at_level(logging.WARNING):
        await _handler(repo, analyzer).handle([_ev(""), _ev("u1"), {"reason": "x"}])

    assert repo.registered == [(["u1"], 1800)]
    assert "2 evento(s) sem uid" in caplog.text


async def test_batch_so_com_eventos_sem_uid_nao_consulta_o_banco():
    repo, analyzer = FakeRepository(), FakeAnalyzer()

    await _handler(repo, analyzer).handle([_ev("")])

    assert repo.registered == [] and analyzer.calls == []


async def test_batch_todo_em_tratamento_nao_chama_o_agente():
    repo, analyzer = FakeRepository(active={"u1", "u2"}), FakeAnalyzer()

    await _handler(repo, analyzer).handle([_ev("u1"), _ev("u2")])

    assert analyzer.calls == []


async def test_erro_de_banco_na_deduplicacao_descarta_o_batch(caplog):
    repo, analyzer = FakeRepository(), FakeAnalyzer()
    repo.register_error = _db_error()

    with caplog.at_level(logging.ERROR):
        await _handler(repo, analyzer).handle([_ev("u1")])

    assert analyzer.calls == []
    assert "batch de 1 evento(s) descartado" in caplog.text


async def test_agente_recebe_apenas_os_eventos_novos():
    repo, analyzer = FakeRepository(active={"u9"}), FakeAnalyzer()

    await _handler(repo, analyzer).handle([_ev("u1"), _ev("u9"), _ev("u2"), _ev("u3")])

    assert [ev["uid"] for ev in analyzer.calls[0]] == ["u1", "u2", "u3"]


async def test_sucesso_substitui_o_batch_pelos_problemas():
    repo, analyzer = FakeRepository(), FakeAnalyzer()

    await _handler(repo, analyzer).handle([_ev("u1"), _ev("u2"), _ev("u3")])

    (_, drafts), = repo.replaced
    assert [(d.event_uids, d.severity, d.status) for d in drafts] == [
        (["u1", "u2"], "CRITICO", "COMPLETO"),
        (["u3"], "ALTO", "COMPLETO"),
    ]
    assert repo.incomplete == []


async def test_evento_nao_referenciado_gera_warning(caplog):
    repo, analyzer = FakeRepository(), FakeAnalyzer()

    with caplog.at_level(logging.WARNING):
        await _handler(repo, analyzer).handle([_ev("u1"), _ev("u2"), _ev("u3"), _ev("u4")])

    assert "evento u4 nao referenciado" in caplog.text
    assert len(repo.replaced) == 1


@pytest.mark.parametrize(
    "analyzer",
    [
        FakeAnalyzer(error=ConnectionError("MCP fora do ar")),
        FakeAnalyzer(error=RuntimeError("API esgotada")),
        FakeAnalyzer(response=""),
        FakeAnalyzer(response="Nao consegui investigar."),
    ],
    ids=["mcp-indisponivel", "erro-api", "resposta-vazia", "sem-secoes"],
)
async def test_falhas_marcam_o_batch_incompleto(analyzer):
    repo = FakeRepository()

    await _handler(repo, analyzer).handle([_ev("u1")])

    assert len(repo.incomplete) == 1
    assert repo.replaced == []


async def test_timeout_marca_o_batch_incompleto(caplog):
    repo, analyzer = FakeRepository(), FakeAnalyzer(delay=5)

    with caplog.at_level(logging.ERROR):
        await _handler(repo, analyzer, timeout=0.05).handle([_ev("u1")])

    assert len(repo.incomplete) == 1
    assert "excedeu o prazo" in caplog.text


async def test_nenhuma_excecao_chega_ao_coletor():
    class Broken(FakeRepository):
        async def start_analysis(self, batch_id):
            raise RuntimeError("bug inesperado")

    await _handler(Broken(), FakeAnalyzer()).handle([_ev("u1")])  # nao levanta


# --- 6.2 retry do swap ---------------------------------------------------------------


async def test_swap_com_sucesso_na_segunda_tentativa():
    sleeps = []
    repo = FakeRepository(replace_results=[_db_error(), True])

    await _handler(repo, FakeAnalyzer(), sleeps=sleeps).handle([_ev("u1"), _ev("u3")])

    assert len(repo.replaced) == 1
    assert sleeps == [1]


async def test_falha_definitiva_do_swap_loga_o_markdown(caplog):
    sleeps = []
    repo = FakeRepository(replace_results=[_db_error()] * 4)

    with caplog.at_level(logging.ERROR):
        await _handler(repo, FakeAnalyzer(), sleeps=sleeps).handle([_ev("u1")])

    assert sleeps == [1, 2, 4]
    assert "Falha definitiva" in caplog.text
    assert "## Problema 1: Imagem inexistente" in caplog.text


async def test_swap_recusado_loga_o_descarte(caplog):
    repo = FakeRepository(replace_results=[False])

    with caplog.at_level(logging.WARNING):
        await _handler(repo, FakeAnalyzer()).handle([_ev("u1")])

    assert "resultado da analise descartado" in caplog.text
    assert repo.incomplete == []


# --- 6.3 semaforo e relogio do stale ---------------------------------------------------


async def test_semaforo_serializa_as_analises():
    gate = asyncio.Event()
    order = []

    class Gated(FakeAnalyzer):
        async def run(self, events):
            uid = events[0]["uid"]
            order.append(f"inicio-{uid}")
            if uid == "u1":
                await gate.wait()
            order.append(f"fim-{uid}")
            return RESPOSTA

    repo = FakeRepository(replace_results=[True, True])
    handler = _handler(repo, Gated(), concurrency=1)

    first = asyncio.create_task(handler.handle([_ev("u1")]))
    second = asyncio.create_task(handler.handle([_ev("u3")]))
    await asyncio.sleep(0.05)

    assert order == ["inicio-u1"]  # o segundo batch aguarda vaga
    assert len(repo.registered) == 2  # mas ja foi registrado EM_ANALISE

    gate.set()
    await asyncio.gather(first, second)
    assert order == ["inicio-u1", "fim-u1", "inicio-u3", "fim-u3"]


async def test_concorrencia_maior_permite_analises_em_paralelo():
    gate = asyncio.Event()
    started = []

    class Gated(FakeAnalyzer):
        async def run(self, events):
            started.append(events[0]["uid"])
            await gate.wait()
            return RESPOSTA

    handler = _handler(FakeRepository(replace_results=[True, True]), Gated(), concurrency=2)
    tasks = [asyncio.create_task(handler.handle([_ev(u)])) for u in ("u1", "u3")]
    await asyncio.sleep(0.05)

    assert sorted(started) == ["u1", "u3"]
    gate.set()
    await asyncio.gather(*tasks)


async def test_batch_liberado_na_fila_nao_e_analisado(caplog):
    repo, analyzer = FakeRepository(started=False), FakeAnalyzer()

    with caplog.at_level(logging.WARNING):
        await _handler(repo, analyzer).handle([_ev("u1")])

    assert analyzer.calls == []
    assert "aguardava vaga" in caplog.text
