import os

from sqlalchemy.orm import DeclarativeBase

DEFAULT_DATABASE_URL = "postgresql+asyncpg://aiops:aiops123@localhost:5432/aiops_k8s"


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


class Base(DeclarativeBase):
    pass
