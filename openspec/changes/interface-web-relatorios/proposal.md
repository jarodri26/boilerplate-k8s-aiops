# Proposal

## Why

O pipeline de análise (PRD 002) já grava relatórios de causa raiz no PostgreSQL, mas a única forma de lê-los é consultar o banco diretamente. Sem uma interface, o diagnóstico não chega a quem precisa agir, e não existe um ponto de partida para a correção (PRD 004). Este change implementa o PRD 003 (`docs/prds/003-interface-web.md`), incluindo as decisões registradas no seu §8.

## What Changes

- **Listagem `GET /reports`**: todos os relatórios, do mais recente para o mais antigo. Cada linha mostra ID, data de criação, badge de status e severidade (lida da coluna `severity`; "—" quando nula) e leva ao detalhe. Sem relatórios, aparece a mensagem "Nenhum relatório encontrado".
- **Detalhe `GET /reports/{id}`**: o Markdown do relatório é renderizado em HTML e **sanitizado com `nh3`** antes de ir para o template, o que remove scripts e HTML perigoso vindos de logs do cluster. A página mostra o status atual e o botão "Executar correção" apenas para relatórios COMPLETO ou FALHA_CORRECAO. ID inexistente ou malformado mostra uma página 404.
- **Stub `POST /reports/{id}/fix`**: redireciona para o detalhe com a mensagem "Correção ainda não disponível" até o PRD 004 substituí-lo. A página de detalhe também já sabe exibir "Correção já em andamento", que o PRD 004 vai usar quando a correção responder 409.
- **Banco indisponível**: listagem e detalhe mostram `error.html` com status 503 e a mensagem "Banco de dados indisponível, tente novamente em instantes".
- **Navegação**: o link "Tasks" do cabeçalho (`base.html`) dá lugar a "Relatórios" (`/reports`), e o botão de `error.html` passa a voltar para os relatórios.
- Estilos para o Markdown renderizado (títulos, listas, tabelas, blocos de código) na página de detalhe.
- Nova dependência de runtime: `nh3`.

## Capabilities

### New Capabilities
- `interface-web-relatorios`: interface web server-side para consultar os relatórios de diagnóstico (listagem e detalhe), com renderização segura do Markdown e o ponto de partida da correção.

### Modified Capabilities
<!-- Nenhuma: a interface só lê relatórios; os requisitos de relatorios-diagnostico não mudam. -->

## Impact

- **Código**: `web/router.py` ganha as rotas `/reports`; novo módulo de renderização Markdown→HTML sanitizado; novos templates `reports_list.html` e `report_detail.html`; ajustes em `base.html` e `error.html`; consultas de leitura (`list_reports`, `get_report`) no `ReportRepository`; handler de 404 para ID malformado nas rotas de relatório em `main.py`.
- **Dependências**: `nh3` (runtime).
- **Segurança**: sem autenticação na v1 (decisão do PRD). O acesso deve ser restrito pela rede, e isso fica documentado no README.
- **PRD 004**: vai substituir o stub de `POST /reports/{id}/fix` e reutilizar a mensagem de "correção em andamento" já prevista no detalhe.
