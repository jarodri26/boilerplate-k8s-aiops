# Proposal

## Why

Os eventos Warning já são coletados automaticamente (PRD 001), mas o diagnóstico de causa raiz continua manual. Ele leva de 30 min a 2 h, depende da experiência do operador e não deixa registro padronizado. Este change implementa o PRD 002 (`docs/prds/002-agente-analise-causa-raiz.md`), incluindo as decisões D1–D9 do §9. O `EventHandler` placeholder passa a ser um pipeline que deduplica os eventos, investiga a causa raiz com um agente LLM somente leitura e persiste um relatório Markdown por problema no PostgreSQL. Esses relatórios são a entrada dos PRDs 003 (interface web) e 004 (correção).

## What Changes

- **Persistência de relatórios**: tabela `reports` (id UUID, markdown, status, severity nullable, event_uids `TEXT[]` com GIN index, `created_at`, `updated_at`). O schema é versionado com Alembic, configurado neste change com migration inicial. O engine async fica concentrado no `lifespan`: o engine de nível de módulo de `database.py` é removido e o `sessionmaker` é injetado no handler.
- **Ciclo de vida do relatório**: status EM_ANALISE, COMPLETO, INCOMPLETO, CORRIGINDO, CORRIGIDO e FALHA_CORRECAO. Este change produz apenas as transições de análise (EM_ANALISE → COMPLETO | INCOMPLETO); as de correção ficam para o PRD 004.
- **Deduplicação por `metadata.uid`**: eventos com uid vinculado a um relatório ativo (EM_ANALISE, COMPLETO, CORRIGINDO ou FALHA_CORRECAO) são ignorados. A consulta avalia a existência de qualquer relatório ativo com aquele uid, não o status do relatório mais recente. Eventos vinculados apenas a relatórios CORRIGIDO ou INCOMPLETO são reanalisados. Eventos com uid vazio são descartados com warning.
- **Insert-first**: o relatório EM_ANALISE do batch é gravado antes de qualquer chamada ao agente.
- **Recuperação de análises órfãs**: no startup, relatórios EM_ANALISE viram INCOMPLETO. Durante a deduplicação, viram INCOMPLETO os relatórios EM_ANALISE cujo `updated_at` é mais antigo que `ANALYSIS_STALE_TIMEOUT_MINUTES` (padrão 30).
- **Agente de análise**: LangChain `create_agent` com Claude (`AGENT_MODEL_NAME`, padrão `claude-haiku-4-5`, `max_retries=3`). Conecta ao MCP Server Kubernetes via `langchain-mcp-adapters` (HTTP, `MCP_SERVER_URL`), com acesso restrito às tools `kubectl_get`, `kubectl_describe` e `kubectl_logs`. O prompt é o do PRD.
- **Limites de execução**:
  - `AGENT_MAX_ITERATIONS` (padrão 25) via `ModelCallLimitMiddleware`.
  - Prazo total `AGENT_TIMEOUT_MINUTES` (padrão 20), que deve ficar abaixo do stale timeout.
  - Concorrência `ANALYSIS_MAX_CONCURRENCY` (padrão 1). O semáforo é adquirido depois do insert e renova `updated_at` ao ser adquirido.
- **Parse da resposta**:
  - A resposta Markdown é dividida em uma seção por problema, com mapeamento dos uids pelo campo **Eventos** e extração da severidade.
  - Status por problema: COMPLETO quando a severidade é válida e a causa raiz não é vazia nem inconclusiva; caso contrário, INCOMPLETO.
  - O Resumo é descartado.
  - Evento do batch não referenciado em nenhum problema gera warning.
- **Swap atômico**: na mesma transação, `DELETE ... WHERE id = :batch AND status = 'EM_ANALISE' RETURNING id` seguido dos INSERTs por problema. Se o DELETE não retornar linha, faz rollback e descarta o resultado.
- **Falhas**: MCP indisponível, erro esgotado da API Claude, timeout ou resposta sem seções marcam o relatório do batch como INCOMPLETO e são registrados no log. Falha de banco na persistência tem retry com backoff e depois log com o Markdown gerado. Nenhuma falha é propagada ao coletor.
- Documentação das novas variáveis de ambiente e do comando de migration.

## Capabilities

### New Capabilities
- `analise-causa-raiz`: pipeline que recebe o batch de eventos do coletor, filtra os eventos já em tratamento, investiga a causa raiz com um agente somente leitura sob limites de iterações, tempo e concorrência, e transforma a resposta em relatórios por problema.
- `relatorios-diagnostico`: armazenamento dos relatórios de diagnóstico e seu ciclo de vida de status (campos persistidos, transições da análise, substituição condicional do relatório do batch e recuperação de análises interrompidas ou estagnadas). Os PRDs 003 e 004 consomem essa capability.

### Modified Capabilities
- `coleta-eventos-cluster`: o requisito "Despacho assíncrono do batch ao handler", que previa o handler placeholder imprimindo no stdout, é substituído por "Despacho assíncrono do batch ao pipeline de análise". O comportamento de despacho continua o mesmo, mas o destino passa a ser o pipeline de análise.

## Impact

- **Código**:
  - Novos módulos em `src/my_agent_app/models/` (modelo `Report` e queries) e em `src/my_agent_app/agents/` (agente, prompt, tools MCP e parse da resposta).
  - `collector/handler.py` vira o ponto de entrada do pipeline.
  - `main.py` passa a fazer a recuperação no startup antes de iniciar o coletor e a injetar as dependências no handler.
  - `database.py` perde o engine de nível de módulo.
- **Banco**: novo diretório `alembic/` e `alembic.ini`. É preciso rodar `uv run alembic upgrade head` antes de subir a aplicação.
- **Dependências**: nenhuma nova de runtime (`langchain[anthropic]`, `langchain-mcp-adapters`, `alembic`, `sqlalchemy` e `asyncpg` já estão declaradas).
- **Configuração**: novas env vars `AGENT_MODEL_NAME`, `AGENT_MAX_ITERATIONS`, `AGENT_TIMEOUT_MINUTES`, `ANALYSIS_MAX_CONCURRENCY` e `ANALYSIS_STALE_TIMEOUT_MINUTES` (`.env.example`, `CLAUDE.md`, `README.md`). Passam a ser usadas de fato `ANTHROPIC_API_KEY` e `MCP_SERVER_URL`.
- **Externos**: o MCP Server Kubernetes precisa estar rodando localmente (`npx mcp-server-kubernetes` com transport HTTP) e a API da Anthropic precisa estar acessível. Sem eles, os relatórios ficam INCOMPLETO, mas a aplicação continua de pé.
- **Premissa operacional**: continua valendo uma única instância da aplicação, a mesma premissa do PRD 001.
- **PRDs 003/004**: consomem a tabela `reports`, inclusive a coluna `severity`, que o PRD 003 usa na listagem.
