import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from my_agent_app import main
from my_agent_app.web.router import get_report_repository

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


@pytest.fixture
def client_with():
    def _make(repo):
        main.app.dependency_overrides[get_report_repository] = lambda: repo
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


@pytest.mark.parametrize(
    ("key", "message"),
    [("indisponivel", "Correção ainda não disponível"), ("em_andamento", "Correção já em andamento")],
)
def test_mensagens_do_fluxo_de_correcao(client_with, key, message):
    report = FakeReport("COMPLETO")

    html = client_with(FakeReportRepository([report])).get(f"/reports/{report.id}?fix={key}").text

    assert message in html


def test_chave_desconhecida_nao_exibe_nem_ecoa_o_valor(client_with):
    report = FakeReport("COMPLETO")

    html = client_with(FakeReportRepository([report])).get(
        f"/reports/{report.id}?fix=%3Cb%3Einjetado%3C%2Fb%3E"
    ).text

    assert 'class="flash"' not in html
    assert "injetado" not in html


# --- 5.3 stub do POST /fix ----------------------------------------------------------------


def test_stub_redireciona_para_o_detalhe_com_aviso(client_with):
    report = FakeReport("COMPLETO")
    repo = FakeReportRepository([report])
    client = client_with(repo)

    resp = client.post(f"/reports/{report.id}/fix", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == f"/reports/{report.id}?fix=indisponivel"
    assert repo.calls == ["get_report"]  # nenhuma escrita
    assert report.status == "COMPLETO"

    followed = client.post(f"/reports/{report.id}/fix")
    assert "Correção ainda não disponível" in followed.text


def test_stub_para_relatorio_inexistente_responde_404(client_with):
    resp = client_with(FakeReportRepository()).post(
        f"/reports/{uuid.uuid4()}/fix", follow_redirects=False
    )

    assert resp.status_code == 404
