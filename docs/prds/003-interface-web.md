---
prd_number: "003"
status: rascunho
priority: alta
created: 2026-06-16
issue:
depends_on: ["002"]
references: []
---

# PRD 003: Interface Web de Relatórios

## 1. Contexto

- **Sistema/produto**: Agente AIOps para Kubernetes — aplicação Python com FastAPI. O PRD 002 gera relatórios de análise de causa raiz e os persiste no PostgreSQL. Stack: Python, FastAPI, Jinja2, PostgreSQL.
- **Estado atual**: Os relatórios são gerados e armazenados no banco, mas não há forma de visualizá-los. O operador precisaria consultar o banco diretamente para acessar os resultados da análise.
- **Problema**: Sem interface de visualização, os relatórios não chegam a quem precisa agir. Além disso, não há ponto de acionamento para a correção (PRD 004) — o operador não consegue revisar o diagnóstico e disparar a resolução.

## 2. Solução Proposta

### Visão geral

- Interface web server-side renderizada com Jinja2 pela própria API FastAPI
- Página de listagem com todos os relatórios e seus status
- Página de detalhe com renderização do Markdown completo e botão para acionar correção (PRD 004)

### Decisões-chave

1. **Jinja2 para interface web** — Interface server-side renderizada pela própria API FastAPI, sem necessidade de frontend separado (React, Vue, etc.)
2. **Sem autenticação na v1** — Não haverá controle de acesso. Decisão aceita para simplificar a primeira entrega.

### Fora do escopo

- **Autenticação e autorização** — Não contemplado nesta versão
- **Filtros avançados ou busca na listagem** — Listagem simples sem paginação ou filtro
- **Dashboard com métricas agregadas** — Apenas listagem e detalhe de relatórios
- **Execução da correção** — O botão aciona o agente do PRD 004; a lógica de correção não é responsabilidade deste PRD

## 3. Funcionalidades

### US01: Listagem de relatórios

Como engenheiro de plataforma, quero acessar uma página web com a listagem de todos os relatórios de análise, para ter visibilidade do histórico de problemas investigados no cluster.

**Rules:**
- A página exibe todos os relatórios ordenados por `created_at` decrescente (mais recente primeiro)
- Cada item da lista exibe: ID, data de criação (`created_at`), status e a severidade do problema, lida da coluna `severity` do relatório (preenchida pelo PRD 002 a partir do campo `**Severidade:**`; cada relatório corresponde a um único problema). Severidade nula (ex.: relatório EM_ANALISE ou não parseável) é exibida como "—"
- Cada item é clicável e leva à página de detalhe
- A página é servida pela própria API FastAPI com template Jinja2
- A listagem é alcançável a partir de qualquer página por um link "Relatórios" no cabeçalho comum (`base.html`), que substitui o link "Tasks" atual
- O status é exibido como badge com mapeamento para classes CSS do `base.html`: EM_ANALISE → `badge-processing`, COMPLETO → `badge-complete`, INCOMPLETO → `badge-incomplete`, CORRIGINDO → `badge-executing`, CORRIGIDO → `badge-executed`, FALHA_CORRECAO → `badge-execution-failed`

**Edge cases:**
- Nenhum relatório no banco → exibir página com mensagem informativa ("Nenhum relatório encontrado")
- Erro de conexão com o PostgreSQL → capturar exceção SQLAlchemy e renderizar `error.html` com `status_code=503` e mensagem "Banco de dados indisponível, tente novamente em instantes"

### US02: Visualização detalhada do relatório

Como engenheiro de plataforma, quero visualizar o conteúdo completo de um relatório, para avaliar a causa raiz identificada e os passos de correção recomendados.

**Rules:**
- A página renderiza o conteúdo Markdown completo do relatório em HTML
- O HTML gerado pela biblioteca `markdown` é sanitizado com `nh3` antes de ser inserido no template (`|safe` apenas sobre o HTML sanitizado). Motivo: o conteúdo vem do LLM, que leu logs e mensagens de eventos do cluster (texto controlável por workloads), e a biblioteca `markdown` repassa HTML cru — sem sanitização há XSS armazenado em uma interface sem autenticação
- Enquanto o PRD 004 não estiver implementado, a rota `POST /reports/{id}/fix` é um stub que redireciona para a página de detalhe exibindo a mensagem "Correção ainda não disponível". O PRD 004 substitui o stub pela implementação real (incluindo a resposta 409)
- Exibe o status atual do relatório
- Inclui botão "Executar correção" que aciona o agente de correção (PRD 004)
- O botão de correção é exibido para relatórios com status COMPLETO ou FALHA_CORRECAO (FALHA_CORRECAO permite nova tentativa após falha de correção)
- O `id` do relatório é do tipo UUID; o parâmetro `{id}` na rota é validado pelo FastAPI como `uuid.UUID`

**Edge cases:**
- Relatório com Markdown malformado → comportamento nativo da biblioteca `markdown`: produz HTML parcial sem lançar exceção; nenhuma lógica adicional necessária
- Relatório contendo HTML/script embutido (ex.: `<script>` vindo de log de container) → removido pela sanitização `nh3`; o restante do conteúdo é exibido normalmente
- Relatório não encontrado (ID inválido) → retornar página 404 com mensagem informativa
- Usuário clica em "Executar correção" com correção já em andamento → botão não é exibido para status diferente de COMPLETO/FALHA_CORRECAO (regra acima); se `POST /reports/{id}/fix` retornar 409 (PRD 004), exibir mensagem "Correção já em andamento" na página de detalhe

## 4. Critérios de Aceite

### Técnicos

| Critério | Método de verificação |
|----------|----------------------|
| Interface web lista todos os relatórios com status | Teste manual em navegador |
| Página de detalhe renderiza Markdown completo | Teste manual com relatórios de diferentes complexidades |
| Botão de correção aparece para relatórios COMPLETO ou FALHA_CORRECAO | Teste manual com relatórios em diferentes status |
| HTML/script embutido no Markdown não é executado na página de detalhe | Teste automatizado com relatório contendo `<script>` validando que o HTML renderizado não o contém |

### De negócio

Este PRD é um habilitador de visualização; não possui métrica de negócio própria na v1. O valor é viabilizar o acesso aos relatórios gerados pelo PRD 002 e o acionamento da correção (PRD 004).

## 5. Milestones

### Milestone 1: Implementar Interface Web

**Objetivo:** Permitir visualização dos relatórios via navegador.

**Funcionalidades:** US01, US02

- [ ] Criar template Jinja2 de listagem de relatórios (US01)
- [ ] Criar rota FastAPI para listagem (`GET /reports`) (US01)
- [ ] Criar template Jinja2 de detalhe do relatório com renderização Markdown (US02)
- [ ] Criar rota FastAPI para detalhe (`GET /reports/{id: UUID}`) (US02)
- [ ] Sanitizar o HTML do Markdown renderizado com `nh3` (US02)
- [ ] Adicionar botão "Executar correção" com controle de estado e stub de `POST /reports/{id}/fix` até o PRD 004 (US02)
- [ ] Tratar cenários de erro (banco indisponível, relatório não encontrado) (US01, US02)
- [ ] Adicionar estilos CSS para conteúdo Markdown renderizado no template de detalhe (US02)
- [ ] Adicionar link "Relatórios" no cabeçalho (`base.html`) para tornar a listagem alcançável pela navegação (US01)

**Critério de conclusão:**
- Condição: Interface web exibe listagem e detalhe dos relatórios corretamente
- Verificação: Demo em navegador com relatórios reais gerados pelo PRD 002
- Aprovador: Time de SRE

## 6. Riscos e Dependências

| Risco | Impacto | Mitigação | Status |
|-------|---------|-----------|--------|
| Interface sem autenticação exposta indevidamente | Médio | Restringir acesso via rede (VPN, ingress interno). Documentar que v1 não tem auth | Pendente |

**Dependências:**

| Dependência | Tipo | Status | Impacto se bloqueado |
|-------------|------|--------|----------------------|
| PRD 002 — Relatórios no PostgreSQL | Interna | Em desenvolvimento | Sem relatórios, não há o que exibir |
| Jinja2 | Externa | Disponível | Renderização dos templates |
| Biblioteca de renderização Markdown → HTML (`markdown`) | Externa | Disponível — `markdown>=3.7` declarado em `pyproject.toml` | Necessária para exibir relatórios formatados |
| Sanitizador de HTML (`nh3`) | Externa | A adicionar ao `pyproject.toml` | Sem sanitização, a página de detalhe fica exposta a XSS armazenado |

## 7. Referências

- [PRD 002 - Agente de Análise](./002-agente-analise-causa-raiz.md) — fornece os relatórios exibidos
- [PRD 004 - Agente de Correção](./004-agente-correcao-automatica.md) — acionado pelo botão de correção na interface

## 8. Registro de Decisões

- **2026-07-23** — Adicionado link "Relatórios" no cabeçalho (`base.html`). Durante a validação manual (Milestone 1), constatou-se que a listagem só era acessível digitando a URL `/reports`: a navegação não oferecia caminho até ela. O menu comum passa a expor o link, tornando a feature alcançável a partir de qualquer página.
- **2026-10-18** — Severidade lida da coluna `severity` (PRD 002, decisão D8) em vez de reparsear o Markdown a cada listagem; nula exibida como "—".
- **2026-10-18** — HTML do Markdown sanitizado com `nh3`: o conteúdo deriva de logs/eventos do cluster via LLM e a biblioteca `markdown` repassa HTML cru; sem autenticação, isso seria XSS armazenado.
- **2026-10-18** — Stub de `POST /reports/{id}/fix` redirecionando ao detalhe com "Correção ainda não disponível", para o botão não levar a 404/405 antes do PRD 004 existir. O PRD 004 substitui o stub.
- **2026-10-18** — O link "Tasks" do cabeçalho é substituído por "Relatórios" (a página inicial não lista tasks).
