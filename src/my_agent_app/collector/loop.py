import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from my_agent_app.collector.handler import EventHandler
from my_agent_app.collector.k8s_client import list_warning_events, load_k8s_config
from my_agent_app.collector.window import CollectionWindow

logger = logging.getLogger(__name__)

RBAC_HINT = (
    "Permissao insuficiente para listar eventos: e necessaria permissao de 'list' em "
    "'events.events.k8s.io' em todos os namespaces (ClusterRole + ClusterRoleBinding)"
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventCollector:
    """Loop periodico de coleta de eventos Warning do cluster (PRD 001)."""

    def __init__(
        self,
        handler: EventHandler,
        interval_seconds: float,
        list_events: Callable[[], list[dict]] = list_warning_events,
        load_config: Callable[[], None] = load_k8s_config,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self.handler = handler
        self.interval_seconds = interval_seconds
        self._list_events = list_events
        self._load_config = load_config
        self._clock = clock
        self._config_loaded = False
        self.window = CollectionWindow(clock(), timedelta(seconds=interval_seconds))
        self._task: asyncio.Task | None = None
        self._handler_tasks: set[asyncio.Task] = set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        logger.info("Coletor de eventos iniciado (intervalo: %ss)", self.interval_seconds)

    async def stop(self) -> None:
        tasks = [t for t in (self._task, *self._handler_tasks) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Coletor de eventos parado")

    async def _run(self) -> None:
        while True:
            try:
                await self.run_cycle()
            except Exception:
                logger.exception("Erro inesperado no ciclo de coleta de eventos")
            await asyncio.sleep(self.interval_seconds)

    async def run_cycle(self) -> None:
        collection_start = self._clock()
        try:
            if not self._config_loaded:
                await asyncio.to_thread(self._load_config)
                self._config_loaded = True
            raw_events = await asyncio.to_thread(self._list_events)
        except ConfigException as e:
            logger.error("Configuracao do cluster Kubernetes indisponivel: %s", e)
            return
        except ApiException as e:
            if e.status == 403:
                logger.error("%s (%s)", RBAC_HINT, e.reason)
            else:
                logger.error("Erro da API Kubernetes ao listar eventos: %s %s", e.status, e.reason)
            return
        except Exception as e:
            logger.error("Falha ao comunicar com o cluster Kubernetes: %s", e)
            return

        selection = self.window.select(raw_events)
        self.window.commit(collection_start, selection)
        logger.info("Coleta concluida: %d evento(s) Warning a entregar", len(selection.events))
        if selection.events:
            self._dispatch(selection.events)

    def _dispatch(self, events: list[dict]) -> None:
        # fire-and-forget: guarda a referencia para a task nao ser coletada pelo GC
        task = asyncio.create_task(self._safe_handle(events))
        self._handler_tasks.add(task)
        task.add_done_callback(self._handler_tasks.discard)

    async def _safe_handle(self, events: list[dict]) -> None:
        try:
            await self.handler.handle(events)
        except Exception:
            logger.exception("Erro no EventHandler ao processar batch de %d evento(s)", len(events))
