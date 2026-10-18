# Design

## Context

- O pipeline de análise (`collector/handler.py` + `agents/analyzer.py`) já define os padrões a reaproveitar: agente LangChain `create_agent` + `ChatAnthropic(max_retries=3)` + `ModelCallLimitMiddleware(exit_behavior="end")`, cliente MCP por execução (`MultiServerMCPClient`, transport `http`), `asyncio.wait_for` para o prazo total, transições de status por `UPDATE`/`DELETE ... WHERE status = ...` e injeção de fakes pelo construtor.
- `POST /reports/{id}/fix` é hoje um stub em `web/router.py` que redireciona com `?fix=indisponivel`; o detalhe mapeia `?fix=` para mensagens por uma lista fechada (`FIX_MESSAGES`).
- A tabela `reports` não tem coluna de resultado da correção. `ACTIVE_STATUSES` já inclui CORRIGINDO e FALHA_CORRECAO, então o coletor não reanalisa eventos durante a correção; CORRIGIDO libera os eventos para nova análise se o problema voltar.
- O MCP Server (Flux159) expõe 23 tools e é **compartilhado** pelos dois agentes.
- Requisitos em `specs/correcao-automatica`, `specs/relatorios-diagnostico` e `specs/interface-web-relatorios`; decisões de produto no §9 do PRD 004 (D1–D8).

## Goals / Non-Goals

**Goals:**
- Endpoint que decide 303/409/404 de forma atômica dentro do request e só então delega a correção.
- Pipeline de correção que **nunca** deixa o relatório preso em CORRIGINDO enquanto a aplicação estiver de pé, e que sempre grava um resultado legível.
- Peças puras e testáveis sem LLM nem cluster: parser de veredito, filtro de tools, render do prompt.

**Non-Goals:**
- Fila externa, retomada da correção após restart, histórico de tentativas.
- Espera ativa por estabilização dos pods (limitação conhecida do PRD).
- Mudar o prompt de análise (o exemplo `--type=merge` do "Comando Sugerido" fica; o prompt de correção instrui a traduzir para patch estratégico).

## Decisions

### Módulos

```
web/router.py            POST /reports/{id}/fix  --start_correction-->  ReportRepository
      |  BackgroundTasks.add_task(runner.run, report_id)
      v
correction/runner.py     CorrectionRunner.run(report_id)   (nunca levanta)
      |  get_report -> markdown
      |  wait_for(agent.run(markdown), timeout)
      |  parse_verdict(text)
      v  finish_correction(id, status, result)
agents/corrector.py      CorrectionAgent.run(report_markdown) -> str
agents/correction_prompt.py   CORRECTION_PROMPT (texto do PRD) + render
agents/verdict.py        parse_verdict(text) -> CORRIGIDO | FALHA_CORRECAO (+ warning)
agents/tools.py          EXCLUDED_CORRECTION_TOOLS + load_correction_tools
agents/config.py         CORRECTION_MODEL_NAME / _MAX_ITERATIONS / _TIMEOUT_MINUTES
```

- `CorrectionAgent` espelha `RootCauseAnalyzer` (mesmo construtor com `tools_loader`/`agent_factory` injetáveis) e reutiliza `final_text` de `analyzer.py`. **Alternativa**: generalizar `RootCauseAnalyzer` com parâmetros de tools/prompt. Rejeitada: a decisão-chave 1 do PRD quer os agentes evoluindo separados; a duplicação é de ~20 linhas.
- `CorrectionRunner` fica num pacote `correction/` paralelo a `collector/`, porque orquestra banco + agente como o `EventHandler`. É criado no `lifespan` e guardado em `app.state.correction_runner`; o router o obtém por uma dependência (`get_correction_runner`) sobrescrevível nos testes.

### Acionamento: UPDATE primeiro, leitura só na recusa

`start_correction(id)` executa `UPDATE reports SET status='CORRIGINDO', correction_result=NULL, updated_at=now() WHERE id=:id AND status IN ('COMPLETO','FALHA_CORRECAO') RETURNING id`. Se retornar linha → `add_task` + 303. Se não → `get_report(id)`: `None` → 404; senão → 409 renderizando `report_detail.html` com a mensagem conforme o status lido. **Alternativa**: ler, checar o status e depois atualizar. Rejeitada: duas idas ao banco no caminho feliz e a checagem não substitui a condição do UPDATE (TOCTOU). Erros `SQLAlchemyError`/`OSError` → 503, como nas demais rotas.

### Fim do mecanismo `?fix=`

O 409 renderiza o detalhe diretamente com a mensagem no contexto do template, então o parâmetro `fix`, `FIX_MESSAGES` e a chave `indisponivel` saem. **Alternativa**: manter o redirect com `?fix=em_andamento`. Rejeitada pela D2 do PRD (o critério de aceite exige 409). Consequência: um F5 na página do 409 re-envia o POST (o navegador avisa) e recebe de novo 409 — inofensivo.

### Runner: um único ponto de escrita do final

```
run(report_id):
  report = get_report(id)            # falha de banco -> log, sai (fica CORRIGINDO; startup recupera)
  try:
      text = await wait_for(agent.run(report.markdown), timeout)
      status = parse_verdict(text);  result = text or MSG_SEM_RESPOSTA
  except TimeoutError:   status = FALHA_CORRECAO; result = MSG_PRAZO
  except Exception:      status = FALHA_CORRECAO; result = MSG_ERRO (log com stack)
  finish_correction(id, status, result)   # UPDATE ... WHERE status='CORRIGINDO'; 0 linhas -> warning
```

Mensagens fixas em constantes, sem detalhes da exceção (o stack vai só para o log). A gravação final tenta de novo com o mesmo backoff do PRD 002 (`RETRYABLE_DB_ERRORS`, atrasos 1/2/4 s); falha definitiva → log com o resultado. `CancelledError` (shutdown) não é capturado: o relatório fica CORRIGINDO e a recuperação de startup o leva a FALHA_CORRECAO.

### Ferramentas: exclusão por nome

`EXCLUDED_CORRECTION_TOOLS = ("kubectl_context", "port_forward", "stop_port_forward", "cleanup")`; `load_correction_tools` devolve `client.get_tools()` menos esses nomes, com warning se a lista final vier vazia (e exceção, que vira FALHA_CORRECAO). Denylist e não allowlist: novas tools de versões futuras do MCP Server entram automaticamente, coerente com o "acesso irrestrito" do PRD.

### Erros de tool voltam ao modelo

Por padrão o LangGraph só devolve ao modelo erros de validação de argumentos; qualquer outra exceção de tool aborta o run. Na 7.2, um `kubectl_generic` malformado (`McpError`) encerrou a correção na primeira ação, contra a regra do prompt "se falhar, leia a mensagem de erro e tente uma abordagem diferente". O `CorrectionAgent` passa a usar `ToolErrorMiddleware` com um `on_error` que converte `McpError` (erro reportado pelo servidor ao executar a tool) e `ToolException` em `ToolMessage` de erro ("Erro ao executar <tool>: <mensagem>") e devolve `None` para o resto — falhas de transporte/conexão continuam propagando e viram FALHA_CORRECAO. **Alternativa**: capturar `Exception`. Rejeitada: transformaria queda do MCP em dezenas de chamadas inúteis ao modelo até o limite. O agente de análise tem a mesma limitação; fica fora deste change (capability `analise-causa-raiz`).

### Parser de veredito

Regex multiline ancorada no início da linha, tolerando prefixos `-`, `*`, `#`, `>` e negrito antes/depois do token e do `:` (cobre `**FALHA:**` e `- **CORRIGIDO**:`). Coleta os tokens encontrados: exatamente `{CORRIGIDO}` → CORRIGIDO; `{FALHA}` → FALHA_CORRECAO; vazio ou ambos → FALHA_CORRECAO com warning. Função pura, como `parse_problems`.

### Prompt

Texto do PRD literal em `CORRECTION_PROMPT`, com `{report_markdown}` substituído por `str.replace` (o Markdown do relatório contém chaves JSON). O Markdown injetado é só a seção do problema daquele relatório, que é o que `parse_problems` já grava.

### Config

`get_correction_model_name()` = `CORRECTION_MODEL_NAME` or `get_agent_model_name()`; `CORRECTION_MAX_ITERATIONS` (25) e `CORRECTION_TIMEOUT_MINUTES` (10) via o `_positive_number` existente. O prazo da correção não tem relação com o stale da análise, então não há teto como em `get_agent_timeout_seconds`.

### Startup

`recover_on_startup` passa a fazer, na mesma transação, EM_ANALISE → INCOMPLETO e CORRIGINDO → FALHA_CORRECAO (com `correction_result` = mensagem de interrupção) e devolve as duas contagens; o log do `lifespan` mostra ambas.

### Testes

- Unitários: `parse_verdict`, filtro de tools, config, render do prompt, `CorrectionAgent` com `agent_factory` fake, `CorrectionRunner` com repositório e agente fakes (veredito, timeout, exceção, finish sem linhas, retry do banco), rotas `/fix` com repositório e runner fakes (o `TestClient` executa a background task antes de devolver a resposta, então o fake registra a chamada).
- Integração (PostgreSQL real, schema temporário): `start_correction`/`finish_correction`/recuperação e a corrida — duas `start_correction` simultâneas via `asyncio.gather` com sessões distintas, exatamente uma `True`.
- Manual (cluster kind + MCP + Claude): Deployment com tag de imagem inexistente → análise → "Executar correção" → CORRIGIDO e pods Ready; e um cenário que não tem correção possível (ex.: nodeSelector sem nó) → FALHA_CORRECAO com resultado legível.

## Risks / Trade-offs

- [Agente com escrita irrestrita age sobre um diagnóstico errado] → risco aceito (decisão-chave 2); o relatório fica visível para revisão antes do clique e o resultado registra o que foi feito.
- [Haiku comete erros de patch (ex.: merge patch apagando env)] → regras explícitas no prompt; `CORRECTION_MODEL_NAME` permite subir o modelo só para a correção.
- [Correção perdida em restart] → recuperação de startup leva a FALHA_CORRECAO, re-acionável.
- [Falso FALHA_CORRECAO por pods ainda inicializando] → limitação conhecida do PRD; o operador pode re-acionar.
- [Duas correções de relatórios diferentes no mesmo recurso] → permitido (D8), registrado como limitação.
- [POST sem autenticação nem CSRF agora dispara escrita no cluster] → IDs são UUID aleatórios e nenhum site externo consegue lê-los; a recomendação de restringir o acesso pela rede (README) fica mais importante e será reforçada na documentação.
- [Kubeconfig sem permissão de escrita] → as tools retornam erro ao modelo, que responde FALHA; documentar o requisito.

## Migration Plan

1. `uv run alembic upgrade head` (adiciona `reports.correction_result TEXT NULL`; não toca linhas existentes).
2. Subir a aplicação; o startup já recupera CORRIGINDO órfãos (não deve haver nenhum antes deste change).
3. Rollback: reverter o código e `uv run alembic downgrade -1`. Relatórios CORRIGIDO/FALHA_CORRECAO criados no meio continuam válidos para o código antigo (status já existiam).
