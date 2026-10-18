# Design

## Context

Motivação em `proposal.md`. Requisitos em `specs/interface-web-relatorios/spec.md`.

Estado atual relevante:
- `web/router.py` tem só `GET /` (`home.html`), com `Jinja2Templates` apontando para `src/my_agent_app/templates/`.
- `base.html` já define as classes `badge-*` do mapeamento do PRD, `.btn`, `.btn-primary`, `.empty-state` e os blocos `title`, `extra_style` e `content`. O nav tem "Tasks" (`/`) e "Health".
- `error.html` recebe `status_code`, `message` e `title`, e tem o botão "Voltar para tasks", que aponta para `/`.
- `main.py` publica `app.state.sessionmaker`. `models/repository.py` (`ReportRepository`) só tem as queries do pipeline, sem leituras para a interface.
- O modelo `Report` tem `id` UUID, `markdown`, `status`, `severity` (nullable), `event_uids` e `created_at`/`updated_at` em timestamptz.
- Verificado na versão instalada: `markdown.markdown()` repassa HTML cru sem alteração (`<script>`, `onerror=`, `href="javascript:"`). `nh3` não está instalado.
- Os testes usam `fastapi.testclient.TestClient` (como em `tests/test_main_lifespan.py`). Sem o `with`, o lifespan não roda, então não há coletor nem engine.

## Goals / Non-Goals

**Goals:**
- Rotas testáveis sem banco, com o repositório injetado como dependência do FastAPI e substituído nos testes via `app.dependency_overrides`.
- A sanitização como única passagem entre o Markdown e o HTML sem escape, numa função pura com testes próprios.
- O contrato do botão de correção (form POST, redirect, mensagens) pronto para que o PRD 004 só troque o handler.

**Non-Goals:**
- Paginação, filtros, busca e autenticação, que estão fora do escopo do PRD.
- Executar a correção ou alterar o status do relatório.
- JavaScript no cliente. Tudo é server-side, com form POST e redirect.
- Mudar a página inicial `/`, que continua como está.

## Decisions

### D1. Rotas em `web/router.py` e repositório como dependência

```
GET  /reports                 -> reports_list.html
GET  /reports/{report_id}     -> report_detail.html      (report_id: uuid.UUID)
POST /reports/{report_id}/fix -> 303 /reports/{id}?fix=indisponivel   (stub)
```

`get_report_repository(request) -> ReportRepository(request.app.state.sessionmaker)` é injetado com `Depends`. O `ReportRepository` existente ganha duas leituras: `list_reports()`, com `ORDER BY created_at DESC`, e `get_report(id)`, que devolve `Report | None`. Assim todas as consultas à tabela `reports` ficam num só lugar e não há SQL espalhado no router.

*Alternativa:* um repositório só de leitura, separado. Descartada porque seria uma segunda classe sobre a mesma tabela sem ganho.

### D2. Render seguro: `web/markdown_render.py`

`render_markdown(text: str) -> markupsafe.Markup`:
1. `markdown.markdown(text, extensions=["tables", "fenced_code"])`. A extensão `tables` é necessária porque os relatórios do agente têm tabelas, e `fenced_code` porque os "Comando Sugerido" vêm entre ```` ``` ````.
2. `nh3.clean(html)` com a allowlist padrão. Ela mantém títulos, listas, `table/thead/tbody/tr/th/td`, `pre/code`, `a`, `strong/em` e `blockquote`, e remove `script`, `style`, atributos `on*` e esquemas de URL não permitidos, como `javascript:`. Links recebem `rel="noopener noreferrer"`.
3. Devolve `Markup(...)`, então o template não usa `|safe` diretamente. Com isso, o único caminho de HTML sem escape passa pelo sanitizador.

*Alternativas:*
- `bleach`: descartada porque está depreciada.
- Escapar todo o HTML antes do Markdown: descartada porque quebra conteúdo legítimo como `<none>` nos logs e não protege contra links `javascript:`.
- Allowlist própria: descartada porque aumenta a superfície de erro.

### D3. Apresentação

- **Badges**: um dict `STATUS_BADGES` (status → classe CSS) no router é passado aos templates. Status desconhecido cai na classe neutra `badge`.
- **Datas**: exibidas em UTC no formato `dd/mm/aaaa HH:MM UTC`, por um filtro Jinja `datetime_utc` registrado em `templates.env`.
- **Listagem**: uma tabela com uma linha por relatório. O ID aparece completo, em fonte monoespaçada para facilitar a cópia, e é o link para o detalhe. Sem relatórios, usa `.empty-state`.
- **Detalhe**: cabeçalho com ID, badge de status e severidade; mensagem opcional do fluxo de correção; o conteúdo em `<article class="markdown-body">`; e o botão. O CSS de `.markdown-body` fica no bloco `extra_style` do template de detalhe: `h1`–`h3`, `ul/ol`, `table` com bordas, `pre` com rolagem horizontal e `code`.
- **Botão**: `FIX_ELIGIBLE = {COMPLETO, FALHA_CORRECAO}` decide se ele é exibido.

### D4. Mensagens do fluxo de correção por query string com lista fechada

`/reports/{id}?fix=<chave>`, com `FIX_MESSAGES = {"indisponivel": "Correção ainda não disponível", "em_andamento": "Correção já em andamento"}`. Chave desconhecida é ignorada.

O texto **nunca** vem do query string. Isso impede injetar conteúdo arbitrário na página (reflected XSS ou phishing) e dispensa session ou cookie para guardar a mensagem. O PRD 004 só precisa redirecionar com `fix=em_andamento` quando receber 409.

O stub responde `303 See Other`, para o navegador voltar com GET. Antes de redirecionar, ele confirma que o relatório existe (404 se não existir) e não escreve nada no banco.

### D5. Erros: 404 e 503

- **Não encontrado**: `get_report` devolve `None` → `error.html` com status 404 e a mensagem "Relatório não encontrado".
- **ID malformado**: o FastAPI rejeita o `uuid.UUID` com `RequestValidationError` (422 em JSON). Um handler para essa exceção é registrado em `main.py` e, **somente para paths que começam com `/reports/`**, responde `error.html` com 404. Nos demais paths ele delega a `fastapi.exception_handlers.request_validation_exception_handler`, então o resto da API continua respondendo JSON. A validação UUID exigida pelo PRD é mantida.
- **Banco indisponível**: as chamadas ao repositório ficam dentro de `except (SQLAlchemyError, OSError)`. O `OSError` cobre o `ConnectionRefusedError` que o asyncpg levanta antes de o SQLAlchemy encapsular. A resposta é `error.html` com 503 e a mensagem do PRD, e o erro é registrado no log.

### D6. Navegação

No `base.html`, o link `Tasks` (`/`) é trocado por `Relatórios` (`/reports`), e `Health` continua. No `error.html`, o botão passa a ser "Voltar para relatórios" (`/reports`). O título do site continua apontando para `/`.

### D7. Estratégia de testes

- **Unit de `markdown_render`**:
  - tabela e bloco de código são renderizados;
  - `<script>`, `onerror` e `javascript:` são removidos;
  - Markdown malformado não levanta exceção.
- **Rotas com `TestClient` e `FakeReportRepository`** via `dependency_overrides`:
  - listagem: ordem, lista vazia, "—" na severidade nula, badges e links;
  - detalhe: render, botão conforme o status, mensagens de `fix` (chave desconhecida ignorada);
  - 404 para UUID inexistente e para ID malformado;
  - 503 quando o fake levanta `OperationalError` ou `ConnectionRefusedError`;
  - stub do POST: 303 para o detalhe com a chave, nenhuma escrita, e 404 quando o relatório não existe;
  - nav com "Relatórios" e sem "Tasks";
  - rotas fora de `/reports` continuam respondendo 422 em JSON.
- **Integração**: `list_reports` (ordem) e `get_report` (encontrado e inexistente) contra o Postgres, usando a fixture de schema temporário que já existe.

## Risks / Trade-offs

- **[Risco] Interface sem autenticação exposta na rede** → Decisão aceita do PRD. Mitigação: o README documenta que o acesso deve ser restrito pela rede (VPN, ingress interno). A sanitização impede que um workload malicioso ataque quem abre a página.
- **[Risco] A allowlist padrão do `nh3` muda entre versões** → Mitigação: os testes de render fixam o que precisa aparecer (tabela, código) e o que precisa ser removido.
- **[Trade-off] Listagem sem paginação carrega todos os relatórios** → Aceito pelo escopo (§2 do PRD), já que o volume esperado na v1 é baixo. Paginação fica para o futuro.
- **[Trade-off] Handler de `RequestValidationError` global, mas filtrado por prefixo** → Coberto por um teste que garante que rotas fora de `/reports/` continuam com o 422 em JSON.
- **[Risco] CSS do Markdown conflitar com o tema escuro** → Mitigação: usar as mesmas cores de `base.html` (`#1e293b`, `#334155`, `#e2e8f0`) e verificar manualmente com os relatórios reais que já estão no banco.

## Migration Plan

Sem migração de dados. Basta rodar `uv sync` para instalar o `nh3`. O rollback é reverter o código, já que a tabela `reports` não muda.
