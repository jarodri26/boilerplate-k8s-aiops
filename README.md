# Boilerplate: FastAPI + LangChain Agent + MCP

Boilerplate para criar agentes inteligentes com:

- **FastAPI** (async) como backend
- **LangChain + Claude Sonnet** como framework de agentes (padrao ReAct)
- **MCP Server** para integracao com ferramentas externas
- **PostgreSQL** + SQLAlchemy async para persistencia
- **Alembic** para migrations
- **Jinja2** para interface web com dark theme

## Como usar

### 1. Copiar o boilerplate

```bash
cp -r boilerplate/ ~/projetos/meu-novo-agente/
cd ~/projetos/meu-novo-agente/
```

### 2. Renomear o package

Renomeie `my_agent_app` para o nome do seu projeto em todos os arquivos:

```bash
# Renomear diretorio
mv src/my_agent_app src/meu_agente

# Substituir em todos os arquivos
find . -type f -name "*.py" -o -name "*.toml" -o -name "*.ini" -o -name "*.md" -o -name "*.html" | \
  xargs sed -i 's/my_agent_app/meu_agente/g; s/my-agent-app/meu-agente/g; s/My Agent App/Meu Agente/g'
```

### 3. Configurar ambiente

```bash
cp .env.example .env
# Edite .env com suas configuracoes (ANTHROPIC_API_KEY, etc)
```

O coletor de eventos do cluster roda a cada `EVENT_COLLECTION_INTERVAL_MINUTES` minutos (padrao: 3; aceita fracoes, ex: `0.5`). Valores invalidos usam o padrao de 3 minutos.

#### Permissoes do coletor no cluster (RBAC)

O coletor lista eventos `Warning` de todos os namespaces via API `events.k8s.io/v1`. Localmente ele usa o kubeconfig (`~/.kube/config` ou `KUBECONFIG`); dentro do cluster, a ServiceAccount do pod. Em ambos os casos a identidade precisa da permissao minima abaixo (ajuste `namespace` e nome da ServiceAccount):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aiops-event-collector
rules:
  - apiGroups: ["events.k8s.io"]
    resources: ["events"]
    verbs: ["list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: aiops-event-collector
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: aiops-event-collector
subjects:
  - kind: ServiceAccount
    name: aiops-agent
    namespace: aiops
```

Sem essa permissao, a API responde 403 e o coletor registra no log a permissao necessaria, tentando novamente no proximo ciclo. A aplicacao assume **uma unica instancia** (um worker uvicorn / uma replica): multiplas instancias duplicariam a coleta.

### 4. Subir o banco de dados

O Docker provisiona **apenas o banco** (PostgreSQL + pgAdmin):

```bash
docker compose up -d
```

### 5. Instalar dependencias

```bash
uv sync
```

### 6. Subir o MCP Server (via npx)

O MCP Server Kubernetes roda localmente via `npx` expondo transport HTTP (streamable). Requer **Node.js/npx** instalado e um **kubeconfig** valido em `~/.kube/config`:

```bash
ENABLE_UNSAFE_STREAMABLE_HTTP_TRANSPORT=1 PORT=3001 npx mcp-server-kubernetes
```

O agente LangChain conecta a esse servidor por HTTP em `http://localhost:3001/mcp` (`MCP_SERVER_URL`).

### 7. Executar

A aplicacao roda localmente via `uv`:

```bash
uv run uvicorn meu_agente.main:app --host 0.0.0.0 --port 8000
```

## Estrutura

```
src/my_agent_app/
├── main.py              # FastAPI + lifespan
├── database.py          # SQLAlchemy async engine
├── api/router.py        # Health check
├── web/router.py        # Pagina inicial (Jinja2)
├── templates/           # Templates HTML (dark theme)
├── agents/              # (placeholder) Agentes LangChain + MCP
├── collector/           # Loop de coleta de eventos Warning do cluster
└── models/              # (placeholder) Modelos e queries
```

## Stack

| Tecnologia | Uso |
|------------|-----|
| FastAPI + Uvicorn | Backend async |
| SQLAlchemy 2.0 + asyncpg | ORM async com PostgreSQL |
| Alembic | Migrations |
| LangChain + Claude Sonnet | Framework de agentes IA |
| MCP Server | Integracao com ferramentas externas |
| Jinja2 | Interface web server-side |
| Docker Compose | Banco de dados local (PostgreSQL + pgAdmin) |
| Node.js + npx | Runtime do MCP Server Kubernetes (transport HTTP) |
| UV + hatchling | Package manager + build system |
