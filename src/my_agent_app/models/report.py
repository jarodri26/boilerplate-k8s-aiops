import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from my_agent_app.database import Base


class ReportStatus(StrEnum):
    EM_ANALISE = "EM_ANALISE"
    COMPLETO = "COMPLETO"
    INCOMPLETO = "INCOMPLETO"
    CORRIGINDO = "CORRIGINDO"
    CORRIGIDO = "CORRIGIDO"
    FALHA_CORRECAO = "FALHA_CORRECAO"


class Severity(StrEnum):
    CRITICO = "CRITICO"
    ALTO = "ALTO"
    MEDIO = "MEDIO"
    BAIXO = "BAIXO"


# Relatorios que mantem seus eventos "em tratamento" (nao reanalisados)
ACTIVE_STATUSES = (
    ReportStatus.EM_ANALISE,
    ReportStatus.COMPLETO,
    ReportStatus.CORRIGINDO,
    ReportStatus.FALHA_CORRECAO,
)


def _in_list(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(str(v)) for v in values)})"


class Report(Base):
    """Relatorio de diagnostico de causa raiz (PRD 002)."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(_in_list("status", ReportStatus), name="ck_reports_status"),
        CheckConstraint(_in_list("severity", Severity), name="ck_reports_severity"),
        Index("ix_reports_event_uids", "event_uids", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_uids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
