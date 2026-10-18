# Tasks

## 1. Erros de tool no agente de análise

- [x] 1.1 Mover `tool_error_to_model` de `agents/corrector.py` para `agents/tool_errors.py` (mensagem de log neutra, sem "durante a correcao") e importá-lo no `CorrectionAgent`, e verificar que `tests/test_agents_corrector.py` continua passando com os testes do handler movidos para `tests/test_agents_tool_errors.py`
- [x] 1.2 Adicionar `ToolErrorMiddleware(on_error=tool_error_to_model)` ao `RootCauseAnalyzer` e corrigir o docstring de `load_read_only_tools` em `agents/tools.py`, e verificar com testes em `tests/test_agents_analyzer.py`: middleware presente junto do `ModelCallLimitMiddleware`, e um agente real (`create_agent` com modelo falso) cuja tool levanta `McpError` segue até a resposta final em vez de abortar

## 2. Fim de seção no parser

- [x] 2.1 Fazer `_split_sections` em `agents/report_parser.py` encerrar cada seção de problema no próximo título `## ` (nível 2, qualquer texto) além do próximo `## Problema`, e verificar com testes em `tests/test_agents_report_parser.py`: `## Resumo de Ações Recomendadas` após o último problema não entra no relatório, subtítulos `###` e blocos de código com `#` continuam no relatório, e um `## Resumo` antes do primeiro problema continua descartado

## 3. Verificação

- [x] 3.1 Rodar `uv run pytest` com o PostgreSQL no ar e verificar que toda a suíte passa sem testes pulados

## Workflow follow-up

- Arquivar o change com `/opsx:archive` após a revisão, sincronizando as specs.
