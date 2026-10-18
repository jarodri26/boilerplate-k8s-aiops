from fastapi.testclient import TestClient

from my_agent_app import main
from my_agent_app.collector.handler import EventHandler

main_events: list[str] = []


class FakeCollector:
    instances = []

    def __init__(self, handler, interval_seconds):
        self.handler = handler
        self.interval_seconds = interval_seconds
        self.started = False
        self.stopped = False
        FakeCollector.instances.append(self)

    def start(self):
        self.started = True
        main_events.append("collector.start")

    async def stop(self):
        self.stopped = True


def _patch(monkeypatch, recover):
    main_events.clear()
    FakeCollector.instances.clear()

    class FakeRepository:
        def __init__(self, sessionmaker):
            self.sessionmaker = sessionmaker

        async def recover_on_startup(self):
            main_events.append("recover")
            return await recover()

    monkeypatch.setattr(main, "ReportRepository", FakeRepository)
    monkeypatch.setattr(main, "EventCollector", FakeCollector)


def test_recuperacao_acontece_antes_do_coletor(monkeypatch):
    async def recover():
        return 2

    _patch(monkeypatch, recover)

    with TestClient(main.app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}

    assert main_events == ["recover", "collector.start"]
    (collector,) = FakeCollector.instances
    assert isinstance(collector.handler, EventHandler)
    assert collector.stopped


def test_app_sobe_mesmo_com_falha_na_recuperacao(monkeypatch, caplog):
    async def recover():
        raise ConnectionRefusedError("banco fora do ar")

    _patch(monkeypatch, recover)

    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200

    assert main_events == ["recover", "collector.start"]
    assert "recuperacao de analises interrompidas" in caplog.text


def test_handler_usa_a_configuracao_do_ambiente(monkeypatch):
    monkeypatch.setenv("ANALYSIS_STALE_TIMEOUT_MINUTES", "10")
    monkeypatch.setenv("AGENT_TIMEOUT_MINUTES", "15")
    monkeypatch.setenv("ANALYSIS_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "8")
    monkeypatch.setenv("AGENT_MODEL_NAME", "claude-x")

    handler = main.build_event_handler(repository=object())

    assert handler.stale_seconds == 600
    assert handler.timeout_seconds == 540  # limitado a stale - 1 min
    assert handler.analyzer.max_iterations == 8
    assert handler.analyzer.model_name == "claude-x"
