# Proposal

## Why

Os relatórios do PRD 002 trazem causa raiz, solução e comando sugerido, e o PRD 003 já exibe o botão "Executar correção", mas o `POST /reports/{id}/fix` ainda é um stub: o operador continua lendo o relatório e executando os comandos à mão, o que soma tempo ao MTTR e abre espaço para erro de execução. Este change implementa o PRD 004 (`docs/prds/004-agente-correcao-automatica.md`), incluindo as decisões D1–D8 do seu §9.

## What Changes

- **`POST /reports/{id}/fix` real** (substitui o stub): transição atômica COMPLETO/FALHA_CORRECAO → CORRIGINDO por UPDATE condicional dentro do request, depois `303 See Other` para o detalhe e a correção roda em background (`BackgroundTasks`), com sessão própria e recebendo só o `report_id`.
- **Recusa com 409 em HTML**: relatório em outro status (ou corrida perdida) responde `409 Conflict` renderizando o detalhe com "Correção já em andamento" (CORRIGINDO) ou "Correção não permitida para relatórios com status X". Inexistente → 404; banco indisponível → 503.
- **Agente de correção** separado do de análise: LangChain `create_agent` + Claude (`CORRECTION_MODEL_NAME`, padrão = `AGENT_MODEL_NAME`, `max_retries=3`), conectado ao MCP Server Kubernetes por HTTP com **todas as tools exceto** `kubectl_context`, `port_forward`, `stop_port_forward` e `cleanup`; prompt do PRD com o Markdown do relatório injetado; limite `CORRECTION_MAX_ITERATIONS` (padrão 25) via `ModelCallLimitMiddleware`; prazo total `CORRECTION_TIMEOUT_MINUTES` (padrão 10).
- **Veredito**: parser puro procura `CORRIGIDO:`/`FALHA:` ancorado no início de qualquer linha; ausente ou ambíguo → FALHA_CORRECAO.
- **Resultado persistido**: nova coluna `correction_result` (zerada ao entrar em CORRIGINDO, sempre preenchida ao final com a resposta do agente ou uma mensagem fixa); status final gravado só se o relatório ainda estiver CORRIGINDO.
- **Recuperação no startup**: relatórios CORRIGINDO órfãos viram FALHA_CORRECAO (re-acionáveis).
- **Detalhe**: nova seção "Resultado da Correção" com o Markdown sanitizado de `correction_result`.
- **BREAKING (interno)**: a mensagem "Correção ainda não disponível" e a chave `?fix=indisponivel` deixam de existir.
- **Risco aceito (decisão-chave 2 do PRD)**: o agente pode alterar e deletar recursos do cluster sem whitelist, dry-run ou aprovação extra; o clique no botão é a aprovação.

## Capabilities

### New Capabilities
- `correcao-automatica`: acionamento da correção de um relatório, execução pelo agente de correção via MCP, verificação pós-correção e classificação do resultado em CORRIGIDO ou FALHA_CORRECAO.

### Modified Capabilities
- `relatorios-diagnostico`: o relatório ganha o campo de resultado da correção; novas regras de transição condicional de correção e de recuperação de correções interrompidas no startup.
- `interface-web-relatorios`: remove o stub de acionamento da correção; o detalhe passa a exibir o resultado da correção.

## Impact

- **Código**: novo `agents/corrector.py` (agente), `agents/correction_prompt.py`, `agents/verdict.py` (parser), filtro de tools em `agents/tools.py`, config em `agents/config.py`; novo pacote `correction/` com o runner do pipeline de correção; métodos de correção no `ReportRepository`; `recover_on_startup` estendido; `web/router.py` (rota `/fix` real e renderização do 409); `report_detail.html` (seção de resultado); `main.py` (wiring do agente de correção no `app.state`).
- **Banco**: migration Alembic adicionando `reports.correction_result TEXT NULL`.
- **Configuração**: novas env vars `CORRECTION_MODEL_NAME`, `CORRECTION_MAX_ITERATIONS`, `CORRECTION_TIMEOUT_MINUTES` (documentadas em `.env.example`, `CLAUDE.md`, `README.md`).
- **Cluster**: primeira funcionalidade que **escreve** no cluster; requer que o kubeconfig usado pelo MCP Server tenha permissões de escrita.
- **Dependências**: nenhuma nova.
