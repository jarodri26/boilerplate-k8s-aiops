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

O agente de analise de causa raiz e configurado por:

| Variavel | Descricao | Padrao |
|----------|-----------|--------|
| `AGENT_MODEL_NAME` | Modelo Claude do agente | `claude-haiku-4-5` |
| `AGENT_MAX_ITERATIONS` | Maximo de chamadas ao modelo por analise | `25` |
| `AGENT_TIMEOUT_MINUTES` | Prazo total de uma analise (deve ser menor que o stale timeout; senao usa stale - 1) | `20` |
| `ANALYSIS_MAX_CONCURRENCY` | Maximo de analises simultaneas | `1` |
| `ANALYSIS_STALE_TIMEOUT_MINUTES` | Relatorio EM_ANALISE sem atualizacao ha mais que isso e marcado INCOMPLETO | `30` |

O agente de correcao automatica (PRD 004) e configurado por:

| Variavel | Descricao | Padrao |
|----------|-----------|--------|
| `CORRECTION_MODEL_NAME` | Modelo Claude do agente de correcao | valor de `AGENT_MODEL_NAME` |
| `CORRECTION_MAX_ITERATIONS` | Maximo de chamadas ao modelo por correcao | `25` |
| `CORRECTION_TIMEOUT_MINUTES` | Prazo total de uma correcao; estouro marca FALHA_CORRECAO | `10` |

Valores invalidos (nao numericos, zero ou negativos) usam o padrao, com warning no log.

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
    namespace: aiops-system
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

### 5.1. Aplicar as migrations

O schema do banco (tabela `reports`) e versionado com Alembic. Com o banco no ar, aplique as migrations antes de subir a aplicacao:

```bash
uv run alembic upgrade head
```

A URL do banco vem de `DATABASE_URL` (a mesma da aplicacao).

### 6. Subir o MCP Server (via npx)

O MCP Server Kubernetes roda localmente via `npx` expondo transport HTTP (streamable). Requer **Node.js/npx** instalado e um **kubeconfig** valido em `~/.kube/config`:

```bash
ENABLE_UNSAFE_STREAMABLE_HTTP_TRANSPORT=1 PORT=3001 npx mcp-server-kubernetes
```

O agente LangChain conecta a esse servidor por HTTP em `http://localhost:3001/mcp` (`MCP_SERVER_URL`).

### 7. Executar

A aplicacao roda localmente via `uv`:

```bash
uv run uvicorn my_agent_app.main:app --host 0.0.0.0 --port 8000
```

## Deploy no Kubernetes

A imagem da aplicacao e gerada pelo `Dockerfile` (multi-stage com `uv`, usuario sem privilegios) e os manifestos ficam em `deploy/k8s/` (namespace `aiops-system`):

| Arquivo | Conteudo |
|---------|----------|
| `rbac.yaml` | ServiceAccount `aiops-agent` (so `list` em events) e ServiceAccount `aiops-mcp` com **cluster-admin** (escrita do agente de correcao) |
| `mcp.yaml` | MCP Server (`flux159/mcp-server-kubernetes`) como Deployment + Service `aiops-mcp:3001` + NetworkPolicy (so a aplicacao acessa) |
| `app.yaml` | ConfigMap, Deployment (1 replica, `Recreate`, initContainer `alembic upgrade head`) e Service ClusterIP |
| `postgres/` | Postgres em StatefulSet, opcional para testes (em producao prefira um banco gerenciado) |

Os segredos nao sao versionados; crie-os antes do deploy:

```bash
kubectl apply -f deploy/k8s/namespace.yaml

# Somente se for usar o Postgres do cluster (deploy/k8s/postgres)
kubectl -n aiops-system create secret generic aiops-postgres-secrets \
  --from-literal=POSTGRES_USER=aiops \
  --from-literal=POSTGRES_PASSWORD='<senha>' \
  --from-literal=POSTGRES_DB=aiops_k8s

kubectl -n aiops-system create secret generic aiops-agent-secrets \
  --from-literal=ANTHROPIC_API_KEY='sk-ant-...' \
  --from-literal=DATABASE_URL='postgresql+asyncpg://aiops:<senha>@aiops-postgres:5432/aiops_k8s'
```

Build e deploy (exemplo com kind; em outro cluster, publique a imagem num registry e ajuste `image:` em `app.yaml`):

```bash
docker build -t aiops-agent:dev .
kind load docker-image aiops-agent:dev --name <cluster>

kubectl apply -k deploy/k8s/postgres   # opcional
kubectl apply -k deploy/k8s
kubectl -n aiops-system rollout status deploy/aiops-agent
```

O Service e ClusterIP porque a v1 nao tem autenticacao. Acesse por port-forward (ou VPN/ingress interno):

```bash
kubectl -n aiops-system port-forward svc/aiops-agent 8000:8000
```

As variaveis nao secretas ficam no ConfigMap `aiops-agent-config` (em `app.yaml`); apos altera-lo, rode `kubectl -n aiops-system rollout restart deploy/aiops-agent`. O MCP Server so aceita requisicoes com Host `aiops-mcp:3001` (`DNS_REBINDING_ALLOWED_HOST`); se mudar o nome do Service ou a porta, ajuste essa variavel e `MCP_SERVER_URL` juntos.

## Interface web

Com a aplicacao no ar, os relatorios de diagnostico ficam em `http://localhost:8000/reports` (link "Relatorios" no cabecalho):

| Rota | Descricao |
|------|-----------|
| `GET /reports` | Listagem de todos os relatorios (mais recentes primeiro) com status e severidade |
| `GET /reports/{id}` | Detalhe com o Markdown do relatorio renderizado (HTML sanitizado com `nh3`) |
| `POST /reports/{id}/fix` | Botao "Executar correcao" (COMPLETO ou FALHA_CORRECAO): passa o relatorio a CORRIGINDO e volta ao detalhe (303); a correcao roda em segundo plano. Outro status responde 409 ("Correcao ja em andamento" ou "Correcao nao permitida...") |

O detalhe mostra o status atual (atualize a pagina para acompanhar CORRIGINDO → CORRIGIDO/FALHA_CORRECAO) e, ao fim da correcao, a secao "Resultado da Correcao" com a resposta do agente. FALHA_CORRECAO pode ser re-acionado; uma correcao interrompida por restart vira FALHA_CORRECAO no startup.

**A correcao escreve no cluster sem restricao (risco aceito na v1).** O agente de correcao recebe todas as tools do MCP Server, exceto `kubectl_context`, `port_forward`, `stop_port_forward` e `cleanup`: pode aplicar patches, escalar, reiniciar e deletar recursos, sem whitelist, dry-run ou aprovacao alem do clique. Revise o relatorio antes de acionar. O kubeconfig usado pelo MCP Server precisa de permissao de escrita nos recursos a corrigir.

**A v1 nao tem autenticacao.** Como o botao dispara escrita no cluster, nao exponha a aplicacao publicamente: restrinja o acesso pela rede (VPN, ingress interno, port-forward).

## Testes

```bash
uv run pytest
```

Os testes em `tests/integration/` rodam contra um PostgreSQL real, em um schema temporario criado e removido a cada teste (os dados de desenvolvimento nao sao tocados). A URL vem de `TEST_DATABASE_URL` (padrao: o banco do docker-compose); sem banco acessivel, esses testes sao pulados.

## Estrutura

```
src/my_agent_app/
├── main.py              # FastAPI + lifespan
├── database.py          # Base declarativa + DATABASE_URL
├── api/router.py        # Health check
├── web/                 # Pagina inicial e relatorios (Jinja2 + Markdown sanitizado)
├── templates/           # Templates HTML (dark theme)
├── agents/              # Agente de analise de causa raiz (LangChain + Claude + MCP)
├── collector/           # Coleta de eventos Warning + pipeline de analise (handler)
└── models/              # Modelo Report e ReportRepository

alembic/                 # Migrations do banco
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
| Docker + Kustomize | Imagem da aplicacao e deploy no Kubernetes (`deploy/k8s/`) |
| Node.js + npx | Runtime do MCP Server Kubernetes (transport HTTP) |
| UV + hatchling | Package manager + build system |
