import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from my_agent_app import main
from my_agent_app.models.report import ReportStatus
from my_agent_app.web.router import get_correction_runner, get_report_repository

NOW = datetime(2026, 10, 18, 20, 30, tzinfo=timezone.utc)

MARKDOWN = """## Problema 1: Imagem inexistente
- **Severidade:** CRITICO
- **Eventos:** u1

### Causa Raiz
A tag `v9` nao existe.

| Campo | Valor |
|-------|-------|
| pod   | api-1 |

```bash
kubectl set image deployment/api api=registry/api:v8 -n prod
```

<script>alert('xss')</script>
"""


@dataclass
class FakeReport:
    status: str
    severity: str | None = "ALTO"
    markdown: str = MARKDOWN
    created_at: datetime = NOW
    correction_result: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


class FakeReportRepository:
    def __init__(self, reports=(), error=None):
        self.reports = list(reports)
        self.error = error
        self.calls = []

    async def list_reports(self):
        self.calls.append("list_reports")
        if self.error:
            raise self.error
        return sorted(self.reports, key=lambda r: r.created_at, reverse=True)

    async def get_report(self, report_id):
        self.calls.append("get_report")
        if self.error:
            raise self.error
        return next((r for r in self.reports if r.id == report_id), None)

    async def start_correction(self, report_id):
        self.calls.append("start_correction")
        if self.error:
            raise self.error
        report = next((r for r in self.reports if r.id == report_id), None)
        if report is None or report.status not in (
            ReportStatus.COMPLETO,
            ReportStatus.FALHA_CORRECAO,
        ):
            return False
        report.status = ReportStatus.CORRIGINDO
        return True


class FakeRunner:
    def __init__(self):
        self.runs = []

    async def run(self, report_id):
        self.runs.append(report_id)


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def client_with(runner):
    def _make(repo):
        main.app.dependency_overrides[get_report_repository] = lambda: repo
        main.app.dependency_overrides[get_correction_runner] = lambda: runner
        # sem "with": o lifespan (engine, coletor) nao roda
        return TestClient(main.app)

    yield _make
    main.app.dependency_overrides.clear()


def _db_down():
    return OperationalError("SELECT", {}, Exception("conexao recusada"))


# --- 3.1 navegacao ----------------------------------------------------------------------


def test_cabecalho_tem_link_relatorios_e_nao_tasks(client_with):
    html = client_with(FakeReportRepository()).get("/").text

    assert '<a href="/reports">Relatórios</a>' in html
    assert "Tasks" not in html


# --- 3.2 ID malformado ------------------------------------------------------------------


def test_id_malformado_responde_404_em_html(client_with):
    resp = client_with(FakeReportRepository()).get("/reports/abc")

    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    assert "Relatório não encontrado" in resp.text
    assert "Voltar para relatórios" in resp.text


def test_fix_com_id_malformado_responde_404(client_with):
    assert client_with(FakeReportRepository()).post("/reports/abc/fix").status_code == 404


def test_rotas_fora_de_reports_continuam_com_422_json():
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, main.validation_error_handler)

    @app.get("/api/items/{n}")
    async def item(n: int):
        return {"n": n}

    resp = TestClient(app).get("/api/items/abc")

    assert resp.status_code == 422
    assert resp.headers["content-type"] == "application/json"


# --- 4.1 listagem -----------------------------------------------------------------------


def test_listagem_ordena_e_linka_cada_relatorio(client_with):
    antigo = FakeReport("COMPLETO", created_at=NOW - timedelta(hours=1))
    novo = FakeReport("INCOMPLETO", created_at=NOW)

    html = client_with(FakeReportRepository([antigo, novo])).get("/reports").text

    assert html.index(str(novo.id)) < html.index(str(antigo.id))
    assert f'href="/reports/{novo.id}"' in html and f'href="/reports/{antigo.id}"' in html
    assert "18/10/2026 20:30 UTC" in html


@pytest.mark.parametrize(
    ("status", "css"),
    [
        ("EM_ANALISE", "badge-processing"),
        ("COMPLETO", "badge-complete"),
        ("INCOMPLETO", "badge-incomplete"),
        ("CORRIGINDO", "badge-executing"),
        ("CORRIGIDO", "badge-executed"),
        ("FALHA_CORRECAO", "badge-execution-failed"),
    ],
)
def test_badge_de_cada_status(client_with, status, css):
    report = FakeReport(status)
    client = client_with(FakeReportRepository([report]))

    assert f'<span class="badge {css}">{status}</span>' in client.get("/reports").text
    assert f'<span class="badge {css}">{status}</span>' in client.get(f"/reports/{report.id}").text


def test_severidade_nula_aparece_como_travessao(client_with):
    html = client_with(FakeReportRepository([FakeReport("EM_ANALISE", severity=None)])).get(
        "/reports"
    ).text

    assert "<td>—</td>" in html


def test_listagem_vazia(client_with):
    resp = client_with(FakeReportRepository()).get("/reports")

    assert resp.status_code == 200
    assert "Nenhum relatório encontrado" in resp.text


# --- 4.2 / 5.1 banco indisponivel ---------------------------------------------------------


@pytest.mark.parametrize("error", [_db_down(), ConnectionRefusedError("recusado")])
@pytest.mark.parametrize("path", ["/reports", f"/reports/{uuid.uuid4()}"])
def test_banco_indisponivel_responde_503(client_with, error, path):
    resp = client_with(FakeReportRepository(error=error)).get(path)

    assert resp.status_code == 503
    assert "Banco de dados indisponível, tente novamente em instantes" in resp.text


# --- 5.1 detalhe ------------------------------------------------------------------------


def test_detalhe_renderiza_markdown_sanitizado(client_with):
    report = FakeReport("COMPLETO", severity="CRITICO")

    html = client_with(FakeReportRepository([report])).get(f"/reports/{report.id}").text

    assert "<h2>Problema 1: Imagem inexistente</h2>" in html
    assert "<table>" in html and "<td>api-1</td>" in html
    assert "<pre><code" in html and "kubectl set image" in html
    assert "alert('xss')" not in html and "<script>alert" not in html
    assert "Severidade: CRITICO" in html


def test_detalhe_uuid_inexistente_responde_404(client_with):
    resp = client_with(FakeReportRepository([FakeReport("COMPLETO")])).get(
        f"/reports/{uuid.uuid4()}"
    )

    assert resp.status_code == 404
    assert "Relatório não encontrado" in resp.text


# --- 5.2 botao e mensagens ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "visible"),
    [
        ("COMPLETO", True),
        ("FALHA_CORRECAO", True),
        ("EM_ANALISE", False),
        ("INCOMPLETO", False),
        ("CORRIGINDO", False),
        ("CORRIGIDO", False),
    ],
)
def test_botao_de_correcao_conforme_status(client_with, status, visible):
    report = FakeReport(status)

    html = client_with(FakeReportRepository([report])).get(f"/reports/{report.id}").text

    assert ("Executar correção" in html) is visible
    assert (f'action="/reports/{report.id}/fix"' in html) is visible


# --- PRD 004: POST /fix -------------------------------------------------------------


@pytest.mark.parametrize("status", ["COMPLETO", "FALHA_CORRECAO"])
def test_fix_aciona_a_correcao_e_redireciona(client_with, runner, status):
    report = FakeReport(status)
    repo = FakeReportRepository([report])
    client = client_with(repo)

    resp = client.post(f"/reports/{report.id}/fix", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == f"/reports/{report.id}"
    assert repo.calls == ["start_correction"]
    assert runner.runs == [report.id]  # TestClient executa a background task antes de responder
    assert report.status == "CORRIGINDO"

    detalhe = client.get(resp.headers["location"]).text
    assert '<span class="badge badge-executing">CORRIGINDO</span>' in detalhe
    assert "Executar correção" not in detalhe


def test_fix_em_corrigindo_responde_409_em_andamento(client_with, runner):
    report = FakeReport("CORRIGINDO")

    resp = client_with(FakeReportRepository([report])).post(
        f"/reports/{report.id}/fix", follow_redirects=False
    )

    assert resp.status_code == 409
    assert resp.headers["content-type"].startswith("text/html")
    assert "Correção já em andamento" in resp.text
    assert str(report.id) in resp.text  # e a pagina de detalhe
    assert runner.runs == []


@pytest.mark.parametrize("status", ["EM_ANALISE", "INCOMPLETO", "CORRIGIDO"])
def test_fix_em_status_nao_elegivel_responde_409(client_with, runner, status):
    report = FakeReport(status)

    resp = client_with(FakeReportRepository([report])).post(f"/reports/{report.id}/fix")

    assert resp.status_code == 409
    assert f"Correção não permitida para relatórios com status {status}" in resp.text
    assert runner.runs == []


def test_fix_para_relatorio_inexistente_responde_404(client_with, runner):
    resp = client_with(FakeReportRepository()).post(
        f"/reports/{uuid.uuid4()}/fix", follow_redirects=False
    )

    assert resp.status_code == 404
    assert "Relatório não encontrado" in resp.text
    assert runner.runs == []


@pytest.mark.parametrize("error", [_db_down(), ConnectionRefusedError("recusado")])
def test_fix_com_banco_indisponivel_responde_503(client_with, runner, error):
    resp = client_with(FakeReportRepository(error=error)).post(f"/reports/{uuid.uuid4()}/fix")

    assert resp.status_code == 503
    assert "Banco de dados indisponível, tente novamente em instantes" in resp.text
    assert runner.runs == []


def test_parametro_fix_antigo_e_ignorado(client_with):
    report = FakeReport("COMPLETO")

    html = client_with(FakeReportRepository([report])).get(
        f"/reports/{report.id}?fix=indisponivel"
    ).text

    assert 'class="flash"' not in html
    assert "Correção ainda não disponível" not in html


# --- PRD 004: resultado da correcao no detalhe ---------------------------------------


def test_detalhe_exibe_resultado_da_correcao(client_with):
    report = FakeReport(
        "CORRIGIDO",
        correction_result=(
            "CORRIGIDO: imagem trocada\n\n## Acoes Executadas\n\n### Problema 1: Imagem\n"
            "- **Status:** Corrigido\n\n<script>alert('r')</script>"
        ),
    )

    html = client_with(FakeReportRepository([report])).get(f"/reports/{report.id}").text

    assert "Resultado da Correção" in html
    assert "<h2>Acoes Executadas</h2>" in html
    assert "<strong>Status:</strong> Corrigido" in html
    assert "alert('r')" not in html and "<script>alert" not in html


def test_detalhe_sem_correcao_nao_exibe_a_secao(client_with):
    report = FakeReport("COMPLETO")

    html = client_with(FakeReportRepository([report])).get(f"/reports/{report.id}").text

    assert "Resultado da Correção" not in html
