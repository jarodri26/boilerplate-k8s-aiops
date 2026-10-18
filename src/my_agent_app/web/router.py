import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from my_agent_app.correction.runner import CorrectionRunner
from my_agent_app.models.report import ReportStatus
from my_agent_app.models.repository import CORRECTION_ELIGIBLE, ReportRepository
from my_agent_app.web.markdown_render import render_markdown

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

STATUS_BADGES = {
    ReportStatus.EM_ANALISE: "badge-processing",
    ReportStatus.COMPLETO: "badge-complete",
    ReportStatus.INCOMPLETO: "badge-incomplete",
    ReportStatus.CORRIGINDO: "badge-executing",
    ReportStatus.CORRIGIDO: "badge-executed",
    ReportStatus.FALHA_CORRECAO: "badge-execution-failed",
}

# Mensagens da recusa do POST /fix (409, PRD 004 D2)
FIX_IN_PROGRESS_MESSAGE = "Correção já em andamento"
FIX_NOT_ALLOWED_MESSAGE = "Correção não permitida para relatórios com status {status}"

DB_UNAVAILABLE_ERRORS = (SQLAlchemyError, OSError)
DB_UNAVAILABLE_MESSAGE = "Banco de dados indisponível, tente novamente em instantes"
NOT_FOUND_MESSAGE = "Relatório não encontrado"


def _datetime_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


templates.env.filters["datetime_utc"] = _datetime_utc
templates.env.globals["status_badges"] = STATUS_BADGES


def get_report_repository(request: Request) -> ReportRepository:
    return ReportRepository(request.app.state.sessionmaker)


def get_correction_runner(request: Request) -> CorrectionRunner:
    return request.app.state.correction_runner


def render_error(request: Request, status_code: int, message: str, title: str = "Erro"):
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": status_code, "message": message, "title": title},
        status_code=status_code,
    )


def _db_unavailable(request: Request):
    logger.exception("Banco de dados indisponivel ao consultar relatorios")
    return render_error(request, 503, DB_UNAVAILABLE_MESSAGE, "Banco indisponível")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "home.html")


@router.get("/reports", response_class=HTMLResponse)
async def list_reports(
    request: Request, repository: ReportRepository = Depends(get_report_repository)
):
    try:
        reports = await repository.list_reports()
    except DB_UNAVAILABLE_ERRORS:
        return _db_unavailable(request)
    return templates.TemplateResponse(request, "reports_list.html", {"reports": reports})


def _render_detail(request: Request, report, fix_message: str | None = None, status_code=200):
    return templates.TemplateResponse(
        request,
        "report_detail.html",
        {
            "report": report,
            "content": render_markdown(report.markdown),
            "correction_result": (
                render_markdown(report.correction_result) if report.correction_result else None
            ),
            "can_fix": report.status in CORRECTION_ELIGIBLE,
            "fix_message": fix_message,
        },
        status_code=status_code,
    )


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(
    request: Request,
    report_id: uuid.UUID,
    repository: ReportRepository = Depends(get_report_repository),
):
    try:
        report = await repository.get_report(report_id)
    except DB_UNAVAILABLE_ERRORS:
        return _db_unavailable(request)
    if report is None:
        return render_error(request, 404, NOT_FOUND_MESSAGE, "Não encontrado")
    return _render_detail(request, report)


@router.post("/reports/{report_id}/fix")
async def fix_report(
    request: Request,
    report_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    repository: ReportRepository = Depends(get_report_repository),
    runner: CorrectionRunner = Depends(get_correction_runner),
):
    """Aciona a correcao (PRD 004): CORRIGINDO atomico no request, agente em background."""
    try:
        if await repository.start_correction(report_id):
            background_tasks.add_task(runner.run, report_id)
            return RedirectResponse(f"/reports/{report_id}", status_code=303)
        # recusa: so agora le o relatorio, para distinguir 404 de 409 e escolher a mensagem
        report = await repository.get_report(report_id)
    except DB_UNAVAILABLE_ERRORS:
        return _db_unavailable(request)

    if report is None:
        return render_error(request, 404, NOT_FOUND_MESSAGE, "Não encontrado")
    if report.status == ReportStatus.CORRIGINDO:
        message = FIX_IN_PROGRESS_MESSAGE
    else:
        message = FIX_NOT_ALLOWED_MESSAGE.format(status=report.status)
    return _render_detail(request, report, message, status_code=409)
