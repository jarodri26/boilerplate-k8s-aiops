# CLAUDE.md

## Sobre o projeto

<!-- TODO: Descreva o proposito do seu agente aqui -->
Boilerplate para agente inteligente com FastAPI + LangChain + MCP Server.

## Comandos

```bash
# Instalar dependencias
uv sync

# Executar aplicacao
uv run uvicorn my_agent_app.main:app --host 0.0.0.0 --port 8000

# Subir o banco de dados (Docker so provisiona PostgreSQL + pgAdmin)
docker compose up -d

# Subir o MCP Server Kubernetes localmente via npx (transport HTTP/streamable, porta 3001)
# Requer Node.js/npx instalado e kubeconfig em ~/.kube/config
ENABLE_UNSAFE_STREAMABLE_HTTP_TRANSPORT=1 PORT=3001 npx mcp-server-kubernetes

# Aplicar migrations do banco de dados (antes de subir a aplicacao; URL via DATABASE_URL)
uv run alembic upgrade head

# Gerar uma nova migration a partir dos modelos
uv run alembic revision --autogenerate -m "descricao"
```

A aplicacao roda localmente via `uv`; o Docker e usado apenas para o banco de dados.
O MCP Server roda localmente via `npx` expondo transport HTTP, e o LangChain conecta por HTTP (`MCP_SERVER_URL`).

Testes com pytest + pytest-asyncio (em `tests/`): `uv run pytest`. Nao ha linter configurado ainda.
Os testes de `tests/integration/` usam PostgreSQL real (`TEST_DATABASE_URL`, padrao = banco do docker-compose) em um schema temporario por teste; sem banco acessivel, sao pulados.

## Arquitetura

O codigo da aplicacao fica em `src/my_agent_app/` e e empacotado via hatchling (`pyproject.toml`).

- **Database** (`database.py`) — `Base` declarativo e `DATABASE_URL`. O engine async (SQLAlchemy + asyncpg) e criado uma unica vez no `lifespan`. Schema versionado com Alembic (`alembic/`)
- **API** (`api/router.py`) — Health check
- **Interface Web** (`web/router.py`) — Pagina inicial. Templates Jinja2 em `src/my_agent_app/templates/`
- **Collector** (`collector/`) — Loop periodico (iniciado no `lifespan`) que coleta eventos Warning do cluster via SDK `kubernetes` (`events.k8s.io/v1`, JSON cru) e despacha o batch fire-and-forget ao `EventHandler` (`collector/handler.py`), que e o pipeline de analise do PRD 002: descarta uid vazio, deduplica, grava EM_ANALISE, investiga (semaforo + prazo total) e substitui o relatorio do batch pelos relatorios por problema
- **Agents** (`agents/`) — `RootCauseAnalyzer` (LangChain `create_agent` + Claude, `ModelCallLimitMiddleware`), conectado ao MCP Server Kubernetes por HTTP com apenas as tools `kubectl_get`/`kubectl_describe`/`kubectl_logs` (`tools.py`); prompt do PRD em `prompt.py`; parse da resposta Markdown em relatorios por problema em `report_parser.py` (funcao pura); config por env var em `config.py`
- **Models** (`models/`) — Modelo `Report` (tabela `reports`, status com CHECK, `event_uids` `TEXT[]` com GIN) e `ReportRepository` (dedup, stale, recuperacao no startup, swap condicional via `DELETE ... RETURNING`)

No startup, o `lifespan` marca como INCOMPLETO os relatorios EM_ANALISE orfaos antes de iniciar o coletor.

## Variaveis de ambiente

| Variavel | Descricao | Padrao |
|----------|-----------|--------|
| `ANTHROPIC_API_KEY` | Chave de API da Anthropic | (obrigatorio) |
| `DATABASE_URL` | Connection string PostgreSQL async | `postgresql+asyncpg://aiops:aiops123@localhost:5432/aiops_k8s` |
| `MCP_SERVER_URL` | Endpoint HTTP do MCP Server Kubernetes (via npx) | `http://localhost:3001/mcp` |
| `EVENT_COLLECTION_INTERVAL_MINUTES` | Intervalo do loop de coleta de eventos Warning do cluster, em minutos (aceita fracoes) | `3` |
| `AGENT_MODEL_NAME` | Modelo Claude do agente de analise de causa raiz | `claude-haiku-4-5` |
| `AGENT_MAX_ITERATIONS` | Maximo de chamadas ao modelo por analise | `25` |
| `AGENT_TIMEOUT_MINUTES` | Prazo total de uma analise, em minutos (deve ser menor que `ANALYSIS_STALE_TIMEOUT_MINUTES`; senao usa stale - 1) | `20` |
| `ANALYSIS_MAX_CONCURRENCY` | Maximo de analises simultaneas | `1` |
| `ANALYSIS_STALE_TIMEOUT_MINUTES` | Relatorio EM_ANALISE sem atualizacao ha mais que isso e marcado INCOMPLETO | `30` |
| `TEST_DATABASE_URL` | Banco dos testes de integracao (schema temporario por teste) | valor padrao de `DATABASE_URL` |

## Infraestrutura (docker-compose)

O Docker provisiona **apenas o banco de dados** (PostgreSQL + pgAdmin). A aplicacao e o MCP Server rodam localmente.

| Servico | Porta | Credenciais |
|---------|-------|-------------|
| PostgreSQL 17 | 5432 | aiops / aiops123 / aiops_k8s |
| pgAdmin | 5050 | admin@admin.com / admin123 |
