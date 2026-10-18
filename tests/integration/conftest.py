"""Testes de integracao contra PostgreSQL real.

Cada sessao de testes usa um schema temporario (`test_<hex>`) via search_path, entao os
dados de desenvolvimento nao sao tocados. Sem banco acessivel, os testes sao pulados.
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from my_agent_app.database import DEFAULT_DATABASE_URL, Base
from my_agent_app.models import report  # noqa: F401  (registra o modelo no metadata)


def _test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


@pytest.fixture
async def engine():
    schema = f"test_{uuid.uuid4().hex[:12]}"
    url = _test_database_url()

    admin = create_async_engine(url)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as e:  # asyncpg/SQLAlchemy/OSError: qualquer falha de conexao pula
        await admin.dispose()
        pytest.skip(f"PostgreSQL de teste inacessivel ({url}): {e}")

    eng = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    await eng.dispose()
    async with admin.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await admin.dispose()


@pytest.fixture
def sessionmaker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)
