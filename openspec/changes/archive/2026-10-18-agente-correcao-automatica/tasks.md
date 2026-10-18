# Tasks

## 1. Modelo e migration

- [x] 1.1 Adicionar `correction_result: Mapped[str | None]` (TEXT, nulo) ao modelo `Report` e gerar a migration Alembic `adiciona_correction_result`, e verificar que `uv run alembic upgrade head` aplica, `uv run alembic check` não acusa drift e `uv run alembic downgrade -1 && uv run alembic upgrade head` funciona

## 2. Repositório: transições de correção

- [x] 2.1 Adicionar ao `ReportRepository` `start_correction(id) -> bool` (UPDATE condicional COMPLETO/FALHA_CORRECAO → CORRIGINDO, zera `correction_result`, renova `updated_at`, `RETURNING id`) e `finish_correction(id, status, result) -> bool` (só se CORRIGINDO), e verificar com testes de integração: transição de COMPLETO e de FALHA_CORRECAO, recusa para EM_ANALISE/INCOMPLETO/CORRIGINDO/CORRIGIDO, resultado anterior zerado, finish ignorado quando o status já mudou, e duas `start_correction` simultâneas (`asyncio.gather`, sessões distintas) com exatamente uma `True`
- [x] 2.2 Estender `recover_on_startup` para também levar CORRIGINDO → FALHA_CORRECAO com a mensagem de interrupção no `correction_result`, na mesma transação, devolvendo as duas contagens; ajustar o log de `recover_interrupted_analyses` em `main.py`, e verificar com teste de integração (um EM_ANALISE e um CORRIGINDO → INCOMPLETO e FALHA_CORRECAO com resultado preenchido) e com `tests/test_main_lifespan.py` atualizado

## 3. Peças puras do agente de correção

- [x] 3.1 Adicionar a `agents/config.py` `get_correction_model_name()` (padrão = `get_agent_model_name()`), `get_correction_max_iterations()` (25) e `get_correction_timeout_seconds()` (10 min), e verificar com testes em `tests/test_agents_config.py`: padrões, fallback para `AGENT_MODEL_NAME`, e `abc`/`0`/`-5` caindo no padrão com warning
- [x] 3.2 Criar `agents/verdict.py` com `parse_verdict(text)` (ver design: ancorado no início da linha, tolera `-`, `*`, `#`, `>` e negrito; vazio ou ambíguo → FALHA_CORRECAO com warning), e verificar com `tests/test_agents_verdict.py` cobrindo os cenários da spec "Classificação do resultado" mais `**FALHA:**`, `- **CORRIGIDO**:`, texto vazio e veredito em minúsculas não reconhecido
- [x] 3.3 Criar `agents/correction_prompt.py` com `CORRECTION_PROMPT` (texto literal do PRD 004) e `render_correction_prompt(markdown)` via `str.replace`, e verificar com teste que o Markdown com chaves JSON aparece intacto e o placeholder não sobra
- [x] 3.4 Adicionar a `agents/tools.py` `EXCLUDED_CORRECTION_TOOLS`, `filter_correction_tools` e `load_correction_tools(url, client_factory)`, e verificar com testes em `tests/test_agents_tools.py`: as 4 tools excluídas somem, as demais (incluindo `kubectl_delete` e `kubectl_patch`) ficam, lista final vazia levanta exceção

## 4. Agente e runner

- [x] 4.1 Criar `agents/corrector.py` com `CorrectionAgent(model_name, max_iterations, mcp_server_url, tools_loader, agent_factory)` e `run(report_markdown) -> str` (reutiliza `final_text`, `ModelCallLimitMiddleware(exit_behavior="end")`, `max_retries=3`), e verificar com `tests/test_agents_corrector.py` usando fakes: prompt renderizado enviado ao agente, middleware com o limite configurado, tools do loader repassadas e falha do loader propagada
- [x] 4.2 Criar `correction/runner.py` com `CorrectionRunner(repository, agent, *, timeout_seconds, sleep)` e `run(report_id)` que nunca levanta (fluxo e mensagens fixas do design; retry 1/2/4 s na gravação final), e verificar com `tests/test_correction_runner.py`: CORRIGIDO com a resposta do agente, FALHA_CORRECAO por veredito ausente, resposta vazia → mensagem "sem resposta final", timeout → mensagem de prazo, exceção do agente → mensagem de erro sem stack trace, `finish_correction` retornando `False` → warning, erro transitório do banco repetido e relatório inexistente apenas logado

- [x] 4.3 Adicionar ao `CorrectionAgent` o `ToolErrorMiddleware` com `on_error` que devolve ao modelo `McpError`/`ToolException` e deixa propagar o resto, e verificar com testes em `tests/test_agents_corrector.py`: middleware presente, `McpError` e `ToolException` viram texto com o nome da tool e a mensagem, `httpx.ConnectError` devolve `None`

## 5. Web e wiring

- [x] 5.1 Criar o `CorrectionRunner` no `lifespan` (`app.state.correction_runner`, `CorrectionAgent` com a config de correção) e a dependência `get_correction_runner` em `web/router.py`, e verificar que `tests/test_main_lifespan.py` cobre a criação sem conectar ao MCP no startup
- [x] 5.2 Substituir o stub de `POST /reports/{report_id}/fix`: `start_correction` → `BackgroundTasks.add_task(runner.run, id)` + 303; recusa → `get_report` → 404 ou 409 renderizando `report_detail.html` com "Correção já em andamento" (CORRIGINDO) ou "Correção não permitida para relatórios com status X"; banco → 503; remover o parâmetro `fix`, `FIX_MESSAGES` e a chave `indisponivel`, e verificar reescrevendo os testes de `/fix` em `tests/test_web_reports.py`: 303 com runner chamado com o UUID, 409 para cada status não elegível com a mensagem certa e runner não chamado, 404 para inexistente/malformado e 503 com banco fora
- [x] 5.3 Exibir em `report_detail.html` a seção "Resultado da Correção" com `render_markdown(report.correction_result)` só quando preenchido, e verificar com testes: seção presente e formatada para CORRIGIDO, `<script>` do resultado removido e seção ausente quando `correction_result` é nulo

## 6. Documentação

- [x] 6.1 Documentar `CORRECTION_MODEL_NAME`, `CORRECTION_MAX_ITERATIONS` e `CORRECTION_TIMEOUT_MINUTES` em `.env.example`, `CLAUDE.md` e `README.md`; descrever o pipeline de correção na Arquitetura do `CLAUDE.md`; registrar no README que a correção escreve no cluster sem restrição (risco aceito), que o kubeconfig do MCP precisa de permissão de escrita e que o acesso à interface deve ser restrito pela rede; e verificar que os nomes e padrões documentados batem com `agents/config.py`

## 7. Verificação de ponta a ponta

- [x] 7.1 Rodar `uv run pytest` com o PostgreSQL do docker-compose no ar e verificar que toda a suíte passa sem testes de integração pulados
- [x] 7.2 Teste manual com cluster, MCP Server e Claude reais: criar um Deployment com tag de imagem inexistente, aguardar o relatório COMPLETO, clicar em "Executar correção" e verificar o badge CORRIGINDO, depois CORRIGIDO com pods Ready e a seção "Resultado da Correção"; repetir com um cenário sem correção possível pelo relatório e verificar FALHA_CORRECAO com resultado legível; um segundo clique durante CORRIGINDO deve responder 409 "Correção já em andamento"; remover os recursos de teste ao final

## Workflow follow-up

- Arquivar o change com `/opsx:archive` após a revisão, sincronizando as specs.
