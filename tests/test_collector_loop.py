import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest
from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException
from urllib3.exceptions import MaxRetryError

from my_agent_app.collector.loop import EventCollector

START = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)


def make_event(uid: str, seconds: int = -30) -> dict:
    return {
        "metadata": {"uid": uid, "namespace": "prod"},
        "type": "Warning",
        "reason": "BackOff",
        "note": "msg",
        "regarding": {"kind": "Pod", "name": "p", "namespace": "prod"},
        "eventTime": None,
        "deprecatedLastTimestamp": (START + timedelta(seconds=seconds)).isoformat(),
    }


class FakeClock:
    def __init__(self):
        self.now = START

    def __call__(self) -> datetime:
        return self.now


class RecordingHandler:
    def __init__(self):
        self.batches: list[list[dict]] = []

    async def handle(self, events: list[dict]) -> None:
        self.batches.append(events)


class FakeLister:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self) -> list[dict]:
        self.calls += 1
        response = self.responses.pop(0) if self.responses else []
        if isinstance(response, Exception):
            raise response
        return response


def make_collector(lister, handler=None, interval=180.0, load_config=lambda: None):
    return EventCollector(
        handler=handler or RecordingHandler(),
        interval_seconds=interval,
        list_events=lister,
        load_config=load_config,
        clock=FakeClock(),
    )


async def drain(collector: EventCollector) -> None:
    await asyncio.gather(*collector._handler_tasks)


async def wait_until(predicate, timeout=2.0):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


async def test_primeira_coleta_imediata_no_start():
    lister = FakeLister([make_event("u1")])
    collector = make_collector(lister, interval=3600)
    collector.start()
    try:
        await wait_until(lambda: lister.calls == 1)
    finally:
        await collector.stop()


async def test_ciclos_seguintes_respeitam_intervalo():
    lister = FakeLister()
    collector = make_collector(lister, interval=0.02)
    collector.start()
    try:
        await wait_until(lambda: lister.calls >= 3)
    finally:
        await collector.stop()


async def test_stop_interrompe_o_loop():
    lister = FakeLister()
    collector = make_collector(lister, interval=0.01)
    collector.start()
    await wait_until(lambda: lister.calls >= 1)
    await collector.stop()
    calls = lister.calls
    await asyncio.sleep(0.05)
    assert lister.calls == calls


async def test_batch_entregue_como_lista_unica():
    handler = RecordingHandler()
    collector = make_collector(FakeLister([make_event("u1"), make_event("u2"), make_event("u3")]), handler)
    await collector.run_cycle()
    await drain(collector)
    assert [[e["uid"] for e in b] for b in handler.batches] == [["u1", "u2", "u3"]]


async def test_batch_vazio_nao_aciona_handler():
    handler = RecordingHandler()
    collector = make_collector(FakeLister([]), handler)
    await collector.run_cycle()
    assert not collector._handler_tasks
    assert handler.batches == []


async def test_coletor_nao_espera_handler_lento():
    release = asyncio.Event()

    class SlowHandler:
        async def handle(self, events):
            await release.wait()

    lister = FakeLister([make_event("u1")], [make_event("u2")])
    collector = make_collector(lister, SlowHandler())
    await asyncio.wait_for(collector.run_cycle(), 1)
    await asyncio.wait_for(collector.run_cycle(), 1)
    assert lister.calls == 2
    pending = set(collector._handler_tasks)
    assert len(pending) == 2
    assert not any(t.done() for t in pending)
    await collector.stop()
    assert all(t.cancelled() for t in pending)
    assert not collector._handler_tasks


async def test_erro_no_handler_e_logado_e_nao_afeta_coletor(caplog):
    class FailingHandler:
        async def handle(self, events):
            raise RuntimeError("pipeline fora")

    lister = FakeLister([make_event("u1")], [make_event("u2", seconds=-10)])
    collector = make_collector(lister, FailingHandler())
    with caplog.at_level(logging.ERROR):
        await collector.run_cycle()
        await drain(collector)
        watermark = collector.window.watermark
        await collector.run_cycle()
        await drain(collector)
    assert "pipeline fora" in caplog.text
    assert collector.window.watermark == watermark == START
    assert lister.calls == 2


@pytest.mark.parametrize(
    ("error", "expected_log"),
    [
        (ApiException(status=403, reason="Forbidden"), "events.events.k8s.io"),
        (ApiException(status=500, reason="Internal Server Error"), "500"),
        (MaxRetryError(None, "https://cluster:6443", "connection refused"), "comunicar com o cluster"),
    ],
)
async def test_erro_de_listagem_logado_sem_avancar_marca_dagua(caplog, error, expected_log):
    handler = RecordingHandler()
    lister = FakeLister(error, [make_event("u1")])
    collector = make_collector(lister, handler)
    watermark = collector.window.watermark
    collector._clock.now = START + timedelta(minutes=3)

    with caplog.at_level(logging.ERROR):
        await collector.run_cycle()
    assert expected_log in caplog.text
    assert collector.window.watermark == watermark
    assert handler.batches == []

    # o loop segue: proximo ciclo coleta normalmente
    await collector.run_cycle()
    await drain(collector)
    assert collector.window.watermark == START + timedelta(minutes=3)
    assert [e["uid"] for e in handler.batches[0]] == ["u1"]


async def test_falha_de_config_e_retentada_no_ciclo_seguinte(caplog):
    attempts = []

    def load_config():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConfigException("sem kubeconfig")

    lister = FakeLister([make_event("u1")])
    collector = make_collector(lister, load_config=load_config)
    with caplog.at_level(logging.ERROR):
        await collector.run_cycle()
    assert "sem kubeconfig" in caplog.text
    assert lister.calls == 0

    await collector.run_cycle()
    await collector.run_cycle()
    assert len(attempts) == 2  # config carregada uma vez com sucesso e reutilizada
    assert lister.calls == 2


async def test_erro_inesperado_no_ciclo_nao_derruba_o_loop(caplog):
    lister = FakeLister([{"metadata": "invalido", "deprecatedLastTimestamp": "2026-10-18T10:00:00Z"}])
    collector = make_collector(lister, interval=0.01)
    with caplog.at_level(logging.ERROR):
        collector.start()
        try:
            await wait_until(lambda: lister.calls >= 2)
        finally:
            await collector.stop()
    assert "Erro inesperado no ciclo" in caplog.text
