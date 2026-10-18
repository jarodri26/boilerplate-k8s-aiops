# Tasks

## 1. Banco de dados e Alembic

- [x] 1.1 Remover o engine e o `async_session` de nível de módulo de `database.py` (mantendo `Base` e `get_database_url()`) e verificar que `uv run pytest` continua passando e que `grep -rn "async_session\b\|database import engine" src` não retorna nada
- [x] 1.2 Criar `models/report.py` com `ReportStatus` e `Severity` (`StrEnum`), `ACTIVE_STATUSES` e o modelo `Report` conforme o design D3 (UUID, markdown, status e severity com CHECK, `event_uids` `ARRAY(Text)` com índice GIN, `created_at`/`updated_at` timestamptz), e verificar com `uv run python -c "from my_agent_app.models.report import Report"`
- [x] 1.3 Inicializar o Alembic com template async (`alembic.ini` + `alembic/`), com o `env.py` usando `get_database_url()` e `Base.metadata`, gerar a migration inicial da tabela `reports` e verificar que `uv run alembic upgrade head` seguido de `uv run alembic downgrade base` roda sem erro no banco do docker-compose
- [x] 1.4 Criar a infraestrutura de testes de integração em `tests/integration/conftest.py` (URL de `TEST_DATABASE_URL`, schema temporário via `search_path`, `create_all`, `DROP SCHEMA ... CASCADE`, skip se o banco estiver inacessível) e verificar com um teste que grava um `Report`, confere que um status inválido é rejeitado pelo CHECK, e que é pulado quando o Postgres está parado
- [x] 1.5 Documentar `uv run alembic upgrade head` (sem o comentário de "após configurar") e `TEST_DATABASE_URL` no `CLAUDE.md` e no `README.md`, e verificar que o comando documentado roda como está escrito

## 2. Repositório de relatórios

- [x] 2.1 Criar `models/repository.py` com `ReportRepository(sessionmaker)` e `recover_on_startup()`, e verificar com teste de integração que relatórios EM_ANALISE passam a INCOMPLETO e que os demais status não mudam
- [x] 2.2 Implementar `register_batch(uids, stale_seconds)` em uma transação (stale por `updated_at` → INCOMPLETO, dedup por `&&` + `unnest` nos status ativos, insert EM_ANALISE dos uids novos) e verificar com testes de integração: evento novo, cada status ativo ignorado, CORRIGIDO e INCOMPLETO reanalisados, CORRIGIDO antigo + EM_ANALISE atual ignorado, batch parcial, batch inteiro em tratamento (sem insert), stale de 31 min liberado e EM_ANALISE de 10 min mantido
- [x] 2.3 Implementar `start_analysis`, `mark_incomplete` e `replace_batch` (`DELETE ... RETURNING` condicional + inserts na mesma transação) e verificar com testes de integração: `start_analysis` renova `updated_at` e devolve `False` se o status não é EM_ANALISE; `mark_incomplete` não sobrescreve outro status; o swap substitui o relatório do batch pelos relatórios por problema; o swap recusado (batch já INCOMPLETO) não cria nada

## 3. Configuração do agente

- [x] 3.1 Criar `agents/config.py` com `get_agent_model_name()`, `get_mcp_server_url()`, `get_agent_max_iterations()`, `get_analysis_max_concurrency()`, `get_analysis_stale_timeout_seconds()` e `get_agent_timeout_seconds(stale_seconds)` no padrão de `collector/config.py`, e verificar com testes: ausente usa o padrão, valor válido, `abc`/`0`/negativo usa o padrão com warning, e timeout maior ou igual ao stale vira `stale - 1 min` com warning
- [x] 3.2 Documentar `AGENT_MODEL_NAME`, `AGENT_MAX_ITERATIONS`, `AGENT_TIMEOUT_MINUTES`, `ANALYSIS_MAX_CONCURRENCY` e `ANALYSIS_STALE_TIMEOUT_MINUTES` no `.env.example`, na tabela de env vars do `CLAUDE.md` e no `README.md`, e verificar que as três referências citam os mesmos padrões (`claude-haiku-4-5`, 25, 20, 1, 30)

## 4. Parse da resposta do agente

- [x] 4.1 Criar `agents/report_parser.py` com `parse_problems(markdown, batch_uids)` conforme o design D7, e verificar com testes usando a resposta-modelo do prompt: dois problemas geram dois `ParsedProblem` com Markdown só da seção (sem Resumo), uids e severidade; uid fora do batch é ignorado; uid em duas seções fica na primeira com warning; seção sem uid válido é descartada com warning; uid não referenciado gera warning; resposta vazia ou sem seções devolve lista vazia
- [x] 4.2 Implementar o critério de status e a normalização de severidade, e verificar com testes: `ALTO` + causa descritiva é COMPLETO; "Inconclusiva" é INCOMPLETO; severidade ausente ou inválida é INCOMPLETO com severidade `None`; `MÉDIO`/`CRÍTICO` acentuados e uids entre crases são normalizados

## 5. Agente de análise

- [x] 5.1 Criar `agents/prompt.py` com o prompt do PRD e `render_prompt(events)` (substituição de `{events}` por JSON via `str.replace`), e verificar com teste que os uids aparecem no texto e que o trecho `{"spec":...}` permanece intacto
- [x] 5.2 Criar `agents/tools.py` com `READ_ONLY_TOOLS` e `load_read_only_tools(url)` (`MultiServerMCPClient` com `transport: "http"`, filtro por nome, warning para tool ausente, erro se não sobrar nenhuma), e verificar com testes usando um cliente falso: a lista com tools de escrita devolve só as três de leitura, uma ausente gera warning, e nenhuma levanta erro
- [x] 5.3 Criar `agents/analyzer.py` com `RootCauseAnalyzer.run(events) -> str` (`ChatAnthropic(max_retries=3)`, `create_agent` com `ModelCallLimitMiddleware(run_limit, exit_behavior="end")`, extração do texto da última `AIMessage`, `""` quando não há texto final), e verificar com testes que substituem `create_agent` e o loader de tools por monkeypatch: o modelo e o `run_limit` configurados são repassados, as tools são as três de leitura, e content em blocos é concatenado

## 6. Pipeline no EventHandler

- [x] 6.1 Reescrever `collector/handler.py`: `EventHandler(repository, analyzer, *, stale_seconds, timeout_seconds, max_concurrency)` com o fluxo do design D5 (descarte de uid vazio, `register_batch`, semáforo, `start_analysis`, `wait_for`, parse, `replace_batch`, `mark_incomplete` nas falhas, nenhuma exceção propagada). Substituir `tests/test_collector_handler.py` por testes com `FakeRepository`/`FakeAnalyzer` cobrindo: uid vazio descartado, batch todo em tratamento não chama o analyzer, erro de banco no `register_batch` descarta o batch, analyzer recebe só os eventos novos, sucesso chama `replace_batch` com os problemas, e as falhas (exceção, timeout, resposta vazia) chamam `mark_incomplete`
- [x] 6.2 Implementar o retry de `replace_batch` (até 3 novas tentativas após a primeira, esperas de 1/2/4 s, para `OperationalError`/`InterfaceError`/`OSError`) e o log do swap recusado, e verificar com testes (sleep substituído): sucesso na segunda tentativa, falha definitiva loga ERROR com o Markdown, e swap `False` loga o descarte
- [x] 6.3 Verificar o semáforo e o relógio do stale com testes: com `max_concurrency=1`, o segundo batch só chama o analyzer depois que o primeiro termina (analyzer bloqueado num `asyncio.Event`), e `start_analysis` devolvendo `False` impede a chamada ao analyzer

## 7. Integração no startup

- [x] 7.1 Atualizar o `lifespan` em `main.py` conforme o design D9 (repositório, `recover_on_startup` com log da contagem, config lida uma vez, `RootCauseAnalyzer` e `EventHandler` injetados no `EventCollector`, banco indisponível só gera log), e verificar com teste usando `TestClient` e repositório/coletor substituídos que a recuperação acontece antes do `collector.start()` e que `/api/health` responde mesmo quando a recuperação falha
- [x] 7.2 Atualizar a descrição do Collector e dos módulos Agents/Models na seção de Arquitetura do `CLAUDE.md` (o handler deixa de ser placeholder) e verificar que o texto descreve os módulos criados

## 8. Verificação de ponta a ponta

- [x] 8.1 Rodar `uv run pytest` com o Postgres no ar e verificar que toda a suíte passa, incluindo `tests/integration/`
- [x] 8.2 Verificação manual com cluster de teste: subir banco, MCP Server e aplicação, aplicar um pod com imagem inexistente (`ImagePullBackOff`) e verificar que em até um ciclo de coleta mais a análise surge no banco um relatório COMPLETO com severidade, causa raiz e o uid do evento, e que o ciclo seguinte não cria um relatório duplicado
- [x] 8.3 Verificação manual de falha: com o MCP Server parado, provocar um evento e verificar que o relatório do batch fica INCOMPLETO, que o erro aparece no log e que a coleta continua

## Workflow follow-up

- Arquivar o change depois da revisão (`/opsx:archive`).
- Em seguida, abrir o change `interface-web-relatorios` (PRD 003).
