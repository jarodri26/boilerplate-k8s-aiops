# Design

## Context

A motivação está em `proposal.md`. Os requisitos estão em `specs/analise-causa-raiz/spec.md`, `specs/relatorios-diagnostico/spec.md` e `specs/coleta-eventos-cluster/spec.md`. As decisões de produto vêm do §9 do PRD 002 (D1–D9).

Estado atual relevante:
- `collector/loop.py` chama `EventHandler.handle(events)` em uma task fire-and-forget (`_safe_handle` captura exceções). O contrato do evento é o dict de `collector/transform.py:to_contract`, e `uid` pode vir `""`.
- `collector/handler.py` é um placeholder que só imprime os eventos, e `main.py` o constrói sem argumentos.
- `main.py` (lifespan) cria um engine e um `async_sessionmaker` e os publica em `app.state`. `database.py` cria **outro** engine no nível de módulo, que não é usado por ninguém.
- `agents/` e `models/` são pacotes vazios. Alembic está nas dependências, mas não foi configurado (não há `alembic.ini` nem `alembic/`).
- A configuração por env var segue o padrão de `collector/config.py`: constante `DEFAULT_*`, função `get_*()`, warning e uso do padrão quando o valor é inválido.
- Versões instaladas: `langchain` 1.3.14, com `create_agent` e `ModelCallLimitMiddleware(run_limit=..., exit_behavior="end")` disponíveis; `langchain-mcp-adapters` 0.3.0, com `MultiServerMCPClient.get_tools()`.
- Os testes usam pytest + pytest-asyncio (`asyncio_mode = "auto"`), com funções falsas injetadas pelo construtor (por exemplo `EventCollector(list_events=..., clock=...)`).

## Goals / Non-Goals

**Goals:**
- Manter o pipeline testável sem LLM, MCP ou cluster: o agente e o repositório são injetados, e o parse da resposta é uma função pura.
- Fazer a semântica de deduplicação e do swap (overlap de arrays, `DELETE ... RETURNING`) ser testada contra um PostgreSQL real, sem tocar nos dados de desenvolvimento.
- Preservar o contrato com o coletor: `async def handle(events: list[dict]) -> None`, que nunca propaga exceção.

**Non-Goals:**
- Trava atômica de concorrência no banco (constraint ou `SELECT ... FOR UPDATE`). A premissa de instância única e de ciclos espaçados (PRD 002, decisão 6) continua valendo.
- Saída estruturada (`ProviderStrategy`). Fica a saída em Markdown puro, conforme o D1 do PRD.
- Transições de correção e endpoints HTTP de relatório, que pertencem aos PRDs 003/004.
- Deduplicação por `involvedObject` + `reason` (risco aceito no PRD).

## Decisions

### D1. Estrutura dos módulos

```
database.py            Base, get_database_url()           (sem engine de modulo)
models/
  report.py            Report (ORM), ReportStatus, Severity, ACTIVE_STATUSES
  repository.py        ReportRepository(sessionmaker): queries da tabela reports
agents/
  config.py            get_agent_model_name(), get_agent_max_iterations(),
                       get_analysis_stale_timeout_seconds(), get_agent_timeout_seconds(stale),
                       get_analysis_max_concurrency(), get_mcp_server_url()
  prompt.py            ANALYSIS_PROMPT (texto do PRD) + render_prompt(events)
  tools.py             READ_ONLY_TOOLS + load_read_only_tools(url)
  analyzer.py          RootCauseAnalyzer: run(events) -> str  (create_agent + MCP)
  report_parser.py     parse_problems(markdown, batch_uids) -> ParseResult   (puro)
collector/handler.py   EventHandler(repository, analyzer, config): o pipeline
```

O `EventHandler` continua sendo o nome e o ponto de entrada que o coletor conhece, e passa a orquestrar o pipeline. A lógica com efeitos colaterais fica em dois colaboradores injetáveis: `ReportRepository` (banco) e `RootCauseAnalyzer` (LLM + MCP). O que é pura regra de negócio (parse, critério de status, validação de config) não tem I/O.

*Alternativa:* um módulo `pipeline.py` separado, com o handler só delegando. Foi descartada porque seria uma camada a mais sem ganho, já que o handler não tem outra responsabilidade.

### D2. Engine único e Alembic assíncrono

- `database.py` passa a ter apenas `Base` e `get_database_url()`. O engine continua sendo criado no `lifespan`, como hoje.
- O Alembic é configurado com o template `async`. O `env.py` usa `get_database_url()` (que respeita `DATABASE_URL`) e `target_metadata = Base.metadata`, importando `models.report`. A migration inicial cria a tabela `reports` e o índice GIN.
- O comando é `uv run alembic upgrade head`, e passa a ser documentado no `CLAUDE.md` e no `README.md`.

*Alternativa:* `Base.metadata.create_all` no startup. Foi descartada porque não versiona o schema, e os PRDs 003/004 vão evoluir a tabela.

### D3. Schema da tabela `reports`

| Coluna | Tipo | Observação |
|---|---|---|
| `id` | `UUID` PK | `uuid.uuid4` gerado na aplicação |
| `markdown` | `TEXT NOT NULL` | `''` no relatório EM_ANALISE do batch |
| `status` | `TEXT NOT NULL` + `CHECK (status IN (...6 valores))` | |
| `severity` | `TEXT NULL` + `CHECK (severity IN ('CRITICO','ALTO','MEDIO','BAIXO'))` | |
| `event_uids` | `TEXT[] NOT NULL` | índice `GIN` |
| `created_at` / `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | `updated_at` atualizado explicitamente em cada UPDATE |

O status é guardado como `TEXT` com `CHECK`, e não como `ENUM` nativo do PostgreSQL. Alterar um ENUM nativo exige `ALTER TYPE` fora de transação, enquanto um CHECK é trocado por uma migration comum. Na aplicação, `ReportStatus` e `Severity` são `StrEnum`.

O stale é medido por `updated_at` e não por `created_at` (decisão D7 do PRD). O repositório atualiza `updated_at` com `now()` em toda transição, sem depender de `onupdate` implícito.

### D4. `ReportRepository`: as operações e suas transações

| Método | SQL essencial | Retorno |
|---|---|---|
| `recover_on_startup()` | `UPDATE ... SET status='INCOMPLETO' WHERE status='EM_ANALISE'` | nº de linhas |
| `register_batch(uids, stale_seconds)` | **uma transação**: (1) UPDATE stale → INCOMPLETO onde `status='EM_ANALISE' AND updated_at < now() - interval`; (2) `SELECT DISTINCT unnest(event_uids) FROM reports WHERE status = ANY(:ativos) AND event_uids && :uids`; (3) se sobrar uid novo, `INSERT` EM_ANALISE com os uids novos | `(batch_id \| None, novos_uids)` |
| `start_analysis(batch_id)` | `UPDATE ... SET updated_at=now() WHERE id=:id AND status='EM_ANALISE'` | `bool` (linha afetada) |
| `mark_incomplete(batch_id)` | `UPDATE ... SET status='INCOMPLETO' WHERE id=:id AND status='EM_ANALISE'` | `bool` |
| `replace_batch(batch_id, problems)` | **uma transação**: `DELETE ... WHERE id=:id AND status='EM_ANALISE' RETURNING id`; se não houver linha, ROLLBACK; senão `INSERT` de cada problema | `bool` (swap aplicado) |

O passo (2) de `register_batch` usa `&&` (overlap) para que o GIN index seja aproveitado, e o `unnest` devolve exatamente quais uids estão ativos. Assim a semântica de existência (D4 do PRD) fica em uma única query. Juntar stale, dedup e insert na mesma transação reduz ao mínimo a janela entre a leitura e o insert-first. A janela não é zero, o que é aceito pela premissa de instância única.

`mark_incomplete` é condicional pelo mesmo motivo do swap: ele nunca sobrescreve um status que outro fluxo já alterou.

### D5. Fluxo do `EventHandler.handle`

```
handle(events)
  |-- descarta uid "" (warning)                  -> vazio? return
  |-- repo.register_batch(uids)                  -> erro de banco? log + return (batch descartado)
  |      (batch_id, novos) ; batch_id None?      -> return (tudo em tratamento)
  |-- async with semaphore:                      (ANALYSIS_MAX_CONCURRENCY)
  |      repo.start_analysis(batch_id)           -> False? log "liberado enquanto aguardava" + return
  |      md = await wait_for(analyzer.run(eventos_novos), AGENT_TIMEOUT)
  |           TimeoutError / erro MCP / erro API / outro -> repo.mark_incomplete + log + return
  |      result = parse_problems(md, novos)
  |           sem problemas                      -> repo.mark_incomplete + log + return
  |           warnings: uid nao referenciado, uid duplicado, secao sem uid valido
  |      repo.replace_batch(batch_id, result.problems)   (com retry, D8)
  |           False                              -> log "resultado descartado (D3)"
```

- O semáforo é criado no `__init__` do handler, que é instanciado uma vez no `lifespan`, e é adquirido **depois** do `register_batch`. Assim, um batch na fila fica protegido pela dedup.
- Se o batch esperar na fila além do stale timeout, a dedup de outro ciclo o libera, `start_analysis` devolve `False` e a análise nem começa. Esse comportamento é coerente com o swap condicional.
- O agente recebe apenas os eventos novos (os que passaram pela dedup), e não o batch inteiro.
- O `handle` envolve tudo em `try/except Exception` com log. O `_safe_handle` do coletor continua lá como segunda rede de proteção.

### D6. `RootCauseAnalyzer`: agente, MCP e limites

- **Cliente MCP**: um `MultiServerMCPClient({"kubernetes": {"transport": "http", "url": MCP_SERVER_URL}})` por análise. O `get_tools()` é chamado dentro de `run()`, então uma falha de conexão vira exceção e o relatório vai para INCOMPLETO. As sessões são abertas por chamada de tool (modo padrão, stateless), o que basta para tools de leitura.
- **Filtro somente leitura**: `load_read_only_tools` filtra pelo nome em `READ_ONLY_TOOLS = {"kubectl_get", "kubectl_describe", "kubectl_logs"}`. Se faltar alguma, o sistema registra um warning e segue com as que existem. Se não restar nenhuma, levanta erro e a análise fica INCOMPLETO. Erros de execução de tool voltam ao modelo como `ToolMessage(status="error")`, que é o padrão (`handle_tool_errors=True`) da versão 0.3.0.
- **Agente**: `create_agent(model=ChatAnthropic(model=AGENT_MODEL_NAME, max_retries=3), tools=..., middleware=[ModelCallLimitMiddleware(run_limit=AGENT_MAX_ITERATIONS, exit_behavior="end")])`. É construído a cada análise, o que é barato, e assim a lista de tools reflete o MCP do momento.
- **Prompt**: o texto do PRD fica em `prompt.py`. O placeholder `{events}` é preenchido com `json.dumps(eventos, ensure_ascii=False, indent=2)`, e o prompt completo é enviado como uma única mensagem `user`. A substituição é feita com `str.replace`, não com `str.format`, porque o próprio prompt contém `{"spec":...}`.
- **Resposta**: o texto da última `AIMessage`. Se o `content` vier em blocos, os blocos de texto são concatenados. Se o limite de iterações encerrar o run com a última mensagem sendo uma chamada de tool ou um texto vazio, o resultado é `""`, que o parse trata como "sem problemas" e leva o batch a INCOMPLETO.
- O `analyzer` é injetado no handler como um objeto com `async run(events) -> str`. Nos testes do handler ele é trocado por um fake.

*Alternativa:* um único `MultiServerMCPClient` criado no lifespan. Foi descartada porque, com o MCP fora do ar no startup, a aplicação teria de tratar a reconexão. Criar o cliente por análise já cobre a indisponibilidade e a recuperação sem lógica extra.

### D7. `parse_problems`: regras do parse

Função pura que recebe o Markdown e o conjunto de uids do batch e devolve `problems: list[ParsedProblem(markdown, event_uids, severity, status)]` e `warnings: list[str]`.

- **Seções**: as seções começam em linhas que casam `^##\s+Problema\b` e vão até a próxima seção de problema ou até o fim do texto. Separadores `---` nas pontas são removidos. Tudo o que vem antes da primeira seção (título, Resumo) é descartado.
- **Severidade**: primeira palavra depois de `**Severidade:**`, em maiúsculas e sem acentos (`MÉDIO` vira `MEDIO`, `CRÍTICO` vira `CRITICO`). Valor fora da lista resulta em `None`.
- **Eventos**: o texto depois de `**Eventos:**` é dividido por vírgula ou espaço, e crases e pontuação são removidas. Só entram os uids que pertencem ao batch. Se um uid aparecer em mais de uma seção, ele fica na primeira e o sistema registra um warning.
- **Seção sem nenhum uid válido**: é descartada com warning. Assim fica garantido o invariante de que todo relatório tem ao menos um uid, e a dedup nunca vê relatórios que não deduplicam nada.
- **Causa Raiz**: o texto entre `### Causa Raiz` e o próximo `###`. Um problema é COMPLETO quando tem severidade válida e a Causa Raiz não é vazia nem contém `inconclusiv` (sem distinção de maiúsculas). Caso contrário, é INCOMPLETO.
- **Uids não referenciados**: os uids do batch que não aparecem em nenhum problema aceito geram um warning por uid.

O handler registra cada item de `warnings` no log com nível WARNING.

### D8. Retry da persistência

`replace_batch` é repetido até 3 vezes após a primeira tentativa (4 no total), com esperas de 1 s, 2 s e 4 s, para `sqlalchemy.exc.OperationalError`, `sqlalchemy.exc.InterfaceError` e `OSError`. Como cada tentativa é uma transação nova e o DELETE é condicional, repetir a operação é seguro: se uma tentativa anterior chegou a dar commit, a seguinte só não encontra a linha. Esgotadas as tentativas, o sistema registra um ERROR com o `batch_id` e o Markdown completo da resposta.

`register_batch` **não** tem retry: falhou, o batch é descartado (PRD US01). As outras operações (`start_analysis`, `mark_incomplete`) também não têm retry, porque a recuperação por stale e no startup cobre esses casos.

### D9. Startup

No `lifespan`, depois de criar o engine: monta o `ReportRepository`, chama `recover_on_startup()` (loga a quantidade de relatórios recuperados), constrói o `RootCauseAnalyzer` e o `EventHandler`, e só então inicia o coletor. Se o banco estiver indisponível no startup, o sistema registra um ERROR e a aplicação sobe mesmo assim, como no PRD 001 com o cluster. A recuperação por stale cobre esse caso depois.

A config é lida uma única vez no startup. O valor efetivo de `AGENT_TIMEOUT_MINUTES` é calculado a partir do stale efetivo.

### D10. Estratégia de testes

- **Unit (sem I/O)**: `agents/config.py`, `report_parser.py`, `prompt.render_prompt`, o filtro de `tools.py` (com objetos de tool falsos) e o `EventHandler` com `FakeRepository` e `FakeAnalyzer`. Cobrem: uid vazio, tudo em tratamento, semáforo (dois batches com o primeiro analyzer bloqueado num `asyncio.Event`), `start_analysis` falso, timeout (prazo curto e analyzer que dorme), exceção do analyzer, resposta vazia, swap recusado e retry do swap.
- **Integração com PostgreSQL** (`tests/integration/`): usa a URL de `TEST_DATABASE_URL`, cujo padrão é a do docker-compose. A fixture cria um **schema temporário** (`test_<hex>`), aponta o `search_path` via `connect_args={"server_settings": {"search_path": ...}}`, roda `Base.metadata.create_all`, e no fim faz `DROP SCHEMA ... CASCADE`. Se o banco não estiver acessível, o módulo é pulado com `pytest.skip`. Cobre: dedup em todos os status (incluindo CORRIGIDO antigo junto com EM_ANALISE atual), stale por `updated_at`, recuperação no startup, swap aplicado, swap recusado e o CHECK de status.
- **Agente**: um teste unitário verifica que `RootCauseAnalyzer` monta o `create_agent` com as três tools e com o `ModelCallLimitMiddleware(run_limit=N, exit_behavior="end")`, usando `create_agent` e o cliente MCP substituídos por monkeypatch. A execução real contra cluster e LLM fica como verificação manual de ponta a ponta (critério do Milestone 2 do PRD).

## Risks / Trade-offs

- **[Risco] O LLM omite ou reformata uids no campo Eventos** → Aceito pelo D1 do PRD. O sistema registra um warning por uid não referenciado, e o evento é reanalisado se recorrer. A mitigação futura é saída estruturada.
- **[Risco] O parse em Markdown quebra com variações de formato do modelo (Haiku)** → Mitigação: regex tolerantes (espaços, acentos, crases), testes com variações reais e, no pior caso, o problema fica INCOMPLETO em vez de causar erro.
- **[Trade-off] Semáforo 1 serializa as análises** → Numa tempestade de eventos os batches se acumulam como EM_ANALISE. Os que esperarem além do stale são liberados e reanalisados na recorrência. O custo e o rate limit ficam controlados, e a latência pode ser aumentada via `ANALYSIS_MAX_CONCURRENCY`.
- **[Trade-off] Um cliente MCP por análise** → Há o overhead de handshake HTTP a cada análise, que é desprezível perto das chamadas ao LLM.
- **[Risco] Janela entre a dedup e o insert sem lock** → A janela fica no mínimo, dentro de uma transação. Duplicar exigiria dois `handle` simultâneos com o mesmo uid, o que não acontece com instância única e ciclos de cerca de 3 min.
- **[Risco] Cancelamento no shutdown durante uma análise** → `collector.stop()` cancela as tasks do handler, e o relatório fica EM_ANALISE no banco. Mitigação: o `recover_on_startup` do próximo boot leva esse relatório a INCOMPLETO.
- **[Risco] Testes de integração dependem do Postgres local** → Eles são pulados quando o banco não está acessível, então a suíte unitária continua rodando sem Docker.

## Migration Plan

1. Subir o banco (`docker compose up -d`) e rodar `uv run alembic upgrade head`.
2. Subir o MCP Server (`ENABLE_UNSAFE_STREAMABLE_HTTP_TRANSPORT=1 PORT=3001 npx mcp-server-kubernetes`) e definir `ANTHROPIC_API_KEY`.
3. Subir a aplicação.

**Rollback**: reverter o código, voltando ao handler placeholder, e rodar `uv run alembic downgrade base` para remover a tabela. Não há dados prévios a migrar.
