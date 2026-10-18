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

# Aplicar migrations do banco de dados (apos criar modelos e configurar Alembic)
# uv run alembic upgrade head
```

A aplicacao roda localmente via `uv`; o Docker e usado apenas para o banco de dados.
O MCP Server roda localmente via `npx` expondo transport HTTP, e o LangChain conecta por HTTP (`MCP_SERVER_URL`).

Testes com pytest + pytest-asyncio (em `tests/`): `uv run pytest`. Nao ha linter configurado ainda.

## Arquitetura

O codigo da aplicacao fica em `src/my_agent_app/` e e empacotado via hatchling (`pyproject.toml`).

- **Database** (`database.py`) — Engine async SQLAlchemy + asyncpg, configurado via `DATABASE_URL`
- **API** (`api/router.py`) — Health check
- **Interface Web** (`web/router.py`) — Pagina inicial. Templates Jinja2 em `src/my_agent_app/templates/`
- **Collector** (`collector/`) — Loop periodico (iniciado no `lifespan`) que coleta eventos Warning do cluster via SDK `kubernetes` (`events.k8s.io/v1`, JSON cru) e despacha o batch fire-and-forget ao `EventHandler` (placeholder do PRD 002)

### Modulos placeholder (a implementar)

- **Agents** (`agents/`) — Agentes LangChain + MCP Server
- **Models** (`models/`) — Modelos SQLAlchemy e queries

## Variaveis de ambiente

| Variavel | Descricao | Padrao |
|----------|-----------|--------|
| `ANTHROPIC_API_KEY` | Chave de API da Anthropic | (obrigatorio) |
| `DATABASE_URL` | Connection string PostgreSQL async | `postgresql+asyncpg://aiops:aiops123@localhost:5432/aiops_k8s` |
| `MCP_SERVER_URL` | Endpoint HTTP do MCP Server Kubernetes (via npx) | `http://localhost:3001/mcp` |
| `EVENT_COLLECTION_INTERVAL_MINUTES` | Intervalo do loop de coleta de eventos Warning do cluster, em minutos (aceita fracoes) | `3` |

## Infraestrutura (docker-compose)

O Docker provisiona **apenas o banco de dados** (PostgreSQL + pgAdmin). A aplicacao e o MCP Server rodam localmente.

| Servico | Porta | Credenciais |
|---------|-------|-------------|
| PostgreSQL 17 | 5432 | aiops / aiops123 / aiops_k8s |
| pgAdmin | 5050 | admin@admin.com / admin123 |
