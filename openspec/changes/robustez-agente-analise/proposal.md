# Proposal

## Why

A prova de ponta a ponta do PRD 004 revelou que a implementação do agente de análise viola dois requisitos já vigentes de `analise-causa-raiz`:

1. **"Erro de execução de uma tool → devolvido ao agente e a investigação continua"**: hoje qualquer erro que não seja de validação de argumentos (ex.: `McpError` de um `kubectl_get` sobre recurso inexistente) aborta o run e o batch vira INCOMPLETO. O comentário de `agents/tools.py` afirma o contrário.
2. **"Cada relatório contém apenas o Markdown daquela seção"**: a última seção `## Problema N` se estende até o fim da resposta, arrastando títulos de nível 2 posteriores (ex.: "## Resumo de Ações Recomendadas", com os outros problemas) para o último relatório — que depois é injetado inteiro no prompt do agente de correção.

## What Changes

- O `RootCauseAnalyzer` passa a usar `ToolErrorMiddleware` com o mesmo tratamento do agente de correção: `McpError`/`ToolException` voltam ao modelo como resultado de erro da tool; falhas de conexão continuam abortando a análise (INCOMPLETO). O comentário de `agents/tools.py` é corrigido.
- `report_parser` passa a encerrar cada seção de problema no próximo título de nível 2 (`## ...`), e não só no próximo `## Problema`. Subtítulos `###` do problema não são afetados.
- O handler de erro de tool hoje em `agents/corrector.py` passa a ser compartilhado pelos dois agentes.

## Capabilities

### New Capabilities
<!-- Nenhuma. -->

### Modified Capabilities
- `analise-causa-raiz`: o requisito "Relatório por problema a partir da resposta do agente" ganha um cenário explícito para conteúdo de nível 2 após a última seção de problema. O comportamento de erro de tool já está especificado; só a implementação muda.

## Impact

- **Código**: `agents/analyzer.py` (middleware), `agents/corrector.py` → handler movido para módulo compartilhado (`agents/tool_errors.py`), `agents/tools.py` (comentário), `agents/report_parser.py` (fim de seção).
- **Comportamento**: menos análises INCOMPLETO por erros pontuais de tool; relatórios por problema sem conteúdo alheio. Relatórios já gravados não são alterados.
- **Dependências / banco / config**: nenhuma mudança.
