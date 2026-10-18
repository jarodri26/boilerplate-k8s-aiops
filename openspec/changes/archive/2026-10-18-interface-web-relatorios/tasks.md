# Tasks

## 1. Dependência e leituras do repositório

- [x] 1.1 Adicionar `nh3` como dependência de runtime (`uv add nh3`) e verificar que `uv run python -c "import nh3; print(nh3.clean('<script>x</script>ok'))"` imprime `ok`
- [x] 1.2 Adicionar `list_reports()` (ordem `created_at` decrescente) e `get_report(id)` ao `ReportRepository`, e verificar com testes de integração em `tests/integration/test_report_repository.py`: ordem da listagem, relatório encontrado e UUID inexistente devolvendo `None`

## 2. Render seguro do Markdown

- [x] 2.1 Criar `web/markdown_render.py` com `render_markdown(text) -> Markup` (`markdown` com extensões `tables` e `fenced_code` seguido de `nh3.clean`), e verificar com testes: tabela e bloco de código viram `<table>`/`<pre><code>`; `<script>`, `onerror` e `javascript:` são removidos com o texto ao redor preservado; Markdown malformado não levanta exceção

## 3. Navegação e páginas de erro

- [x] 3.1 Trocar o link "Tasks" por "Relatórios" (`/reports`) em `base.html` e o botão de `error.html` por "Voltar para relatórios" (`/reports`), e verificar com teste do `TestClient` que `/` contém o link para `/reports` e não contém "Tasks"
- [x] 3.2 Registrar em `main.py` o handler de `RequestValidationError` que renderiza `error.html` 404 para paths `/reports/...` e delega ao handler padrão nos demais, e verificar com testes: `/reports/abc` responde 404 em HTML e uma rota fora de `/reports` com parâmetro inválido continua respondendo 422 em JSON

## 4. Listagem

- [x] 4.1 Implementar `GET /reports` em `web/router.py` (dependência `get_report_repository`, `STATUS_BADGES`, filtro `datetime_utc`) e o template `reports_list.html`, e verificar com testes usando `FakeReportRepository` via `dependency_overrides`: ordem, link de cada item para `/reports/{id}`, badge com a classe de cada um dos 6 status, "—" para severidade nula e "Nenhum relatório encontrado" quando a lista está vazia
- [x] 4.2 Tratar banco indisponível na listagem (`SQLAlchemyError`/`OSError` → `error.html` 503 com log), e verificar com teste em que o fake levanta `OperationalError` e outro com `ConnectionRefusedError`, conferindo status 503 e a mensagem do PRD

## 5. Detalhe e botão de correção

- [x] 5.1 Implementar `GET /reports/{report_id}` e o template `report_detail.html` (badge, severidade, `markdown-body` com `render_markdown`, CSS no bloco `extra_style`), e verificar com testes: Markdown renderizado na página, `<script>` do conteúdo ausente no HTML, 404 com "Relatório não encontrado" para UUID inexistente e 503 com banco indisponível
- [x] 5.2 Exibir o botão "Executar correção" (form POST para `/reports/{id}/fix`) apenas para COMPLETO e FALHA_CORRECAO, e as mensagens de `FIX_MESSAGES` via `?fix=`, e verificar com testes parametrizados pelos 6 status, `?fix=indisponivel`, `?fix=em_andamento` e chave desconhecida (nenhuma mensagem e sem eco do valor recebido)
- [x] 5.3 Implementar o stub `POST /reports/{report_id}/fix` (303 para `/reports/{id}?fix=indisponivel`, 404 se o relatório não existe, nenhuma escrita), e verificar com testes que conferem o `Location`, o 404 e que o fake não recebeu chamadas de escrita

## 6. Documentação e verificação

- [x] 6.1 Documentar as rotas `/reports` no `README.md` e na seção de Arquitetura do `CLAUDE.md` (incluindo que a v1 não tem autenticação e que o acesso deve ser restrito pela rede), e verificar que as rotas documentadas existem em `web/router.py`
- [x] 6.2 Rodar `uv run pytest` com o Postgres no ar e verificar que toda a suíte passa
- [x] 6.3 Verificação manual no navegador com os relatórios reais do banco: subir a aplicação, abrir `/reports` pelo link do cabeçalho, abrir um relatório COMPLETO e conferir tabelas, listas e o bloco de código legíveis no tema escuro, clicar em "Executar correção" e ver "Correção ainda não disponível"

## Workflow follow-up

- Arquivar o change depois da revisão (`/opsx:archive`).
