import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from my_agent_app.agents import config as agent_config
from my_agent_app.agents.analyzer import RootCauseAnalyzer
from my_agent_app.api.router import router as api_router
from my_agent_app.collector.config import get_collection_interval_seconds
from my_agent_app.collector.handler import EventHandler
from my_agent_app.collector.loop import EventCollector
from my_agent_app.database import get_database_url
from my_agent_app.models.repository import ReportRepository
from my_agent_app.web.router import router as web_router

logger = logging.getLogger(__name__)


async def recover_interrupted_analyses(repository: ReportRepository) -> None:
    """Relatorios EM_ANALISE orfaos (crash/restart) viram INCOMPLETO antes da 1a coleta."""
    try:
        recovered = await repository.recover_on_startup()
    except Exception:
        logger.exception("Banco indisponivel na recuperacao de analises interrompidas")
        return
    logger.info("Recuperacao no startup: %d analise(s) interrompida(s) marcada(s) INCOMPLETO", recovered)


def build_event_handler(repository: ReportRepository) -> EventHandler:
    stale_seconds = agent_config.get_analysis_stale_timeout_seconds()
    analyzer = RootCauseAnalyzer(
        model_name=agent_config.get_agent_model_name(),
        max_iterations=agent_config.get_agent_max_iterations(),
        mcp_server_url=agent_config.get_mcp_server_url(),
    )
    return EventHandler(
        repository,
        analyzer,
        stale_seconds=stale_seconds,
        timeout_seconds=agent_config.get_agent_timeout_seconds(stale_seconds),
        max_concurrency=agent_config.get_analysis_max_concurrency(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_async_engine(get_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    app.state.sessionmaker = sessionmaker

    repository = ReportRepository(sessionmaker)
    await recover_interrupted_analyses(repository)

    collector = EventCollector(build_event_handler(repository), get_collection_interval_seconds())
    collector.start()
    app.state.collector = collector

    yield

    await collector.stop()
    await engine.dispose()


app = FastAPI(title="My Agent App", lifespan=lifespan)
app.include_router(api_router)
app.include_router(web_router)
