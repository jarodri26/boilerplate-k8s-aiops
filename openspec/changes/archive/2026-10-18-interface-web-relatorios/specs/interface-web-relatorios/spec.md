# Spec Delta

## Purpose

Permitir que engenheiros de plataforma consultem pelo navegador os relatórios de diagnóstico gerados pela análise de causa raiz e, a partir deles, acionem a correção.

## ADDED Requirements

### Requirement: Listagem de relatórios
O sistema SHALL servir em `GET /reports` uma página HTML com todos os relatórios, ordenados por data de criação decrescente. Cada item SHALL exibir o ID, a data de criação, o status e a severidade, e SHALL levar à página de detalhe daquele relatório.

#### Scenario: Ordem da listagem
- **WHEN** existem relatórios criados às 10:00 e às 11:00
- **THEN** o relatório das 11:00 aparece antes do das 10:00

#### Scenario: Item leva ao detalhe
- **WHEN** o usuário clica em um item da listagem
- **THEN** o navegador abre `/reports/{id}` daquele relatório

#### Scenario: Severidade ausente
- **WHEN** um relatório não tem severidade (ex.: EM_ANALISE)
- **THEN** a coluna de severidade exibe "—"

#### Scenario: Nenhum relatório
- **WHEN** não há relatórios no banco
- **THEN** a página exibe a mensagem "Nenhum relatório encontrado"

### Requirement: Badge de status
O status de um relatório SHALL ser exibido, na listagem e no detalhe, como um badge com a classe CSS correspondente: EM_ANALISE → `badge-processing`, COMPLETO → `badge-complete`, INCOMPLETO → `badge-incomplete`, CORRIGINDO → `badge-executing`, CORRIGIDO → `badge-executed`, FALHA_CORRECAO → `badge-execution-failed`.

#### Scenario: Relatório completo
- **WHEN** um relatório COMPLETO é exibido
- **THEN** seu status aparece em um elemento com a classe `badge badge-complete`

#### Scenario: Falha de correção
- **WHEN** um relatório FALHA_CORRECAO é exibido
- **THEN** seu status aparece em um elemento com a classe `badge badge-execution-failed`

### Requirement: Navegação até os relatórios
O cabeçalho comum de todas as páginas SHALL conter um link "Relatórios" para `/reports`, no lugar do link "Tasks". A página de erro SHALL oferecer um botão de volta para `/reports`.

#### Scenario: Link no cabeçalho
- **WHEN** o usuário está em qualquer página da aplicação
- **THEN** o cabeçalho tem um link "Relatórios" que leva a `/reports` e não tem mais o link "Tasks"

### Requirement: Detalhe do relatório
O sistema SHALL servir em `GET /reports/{id}` uma página HTML com o status atual do relatório e seu conteúdo Markdown renderizado em HTML. Markdown malformado SHALL ser exibido como HTML parcial, sem erro.

#### Scenario: Relatório renderizado
- **WHEN** o usuário abre o detalhe de um relatório cujo Markdown contém títulos, listas, uma tabela e um bloco de código
- **THEN** a página exibe esses elementos formatados em HTML e o badge do status atual

#### Scenario: Markdown malformado
- **WHEN** o Markdown do relatório tem marcação incompleta (ex.: `**negrito sem fechar`)
- **THEN** a página é exibida com status 200 e o texto aparece sem formatação quebrada

### Requirement: Renderização segura do conteúdo
O HTML gerado a partir do Markdown SHALL ser sanitizado antes de ser exibido: scripts, handlers de evento (`on*`), `javascript:` em links e demais elementos ou atributos não seguros SHALL ser removidos. O restante do conteúdo SHALL continuar sendo exibido.

#### Scenario: Script embutido no relatório
- **WHEN** o Markdown do relatório contém `<script>alert(1)</script>` copiado de um log de container
- **THEN** o HTML da página não contém o elemento `<script>` desse conteúdo e o restante do relatório é exibido

#### Scenario: Atributo de evento e link javascript
- **WHEN** o Markdown contém `<img src=x onerror=alert(1)>` e `[clique](javascript:alert(1))`
- **THEN** o HTML da página não contém `onerror` nem `javascript:`

### Requirement: Relatório não encontrado
`GET /reports/{id}` SHALL responder com uma página HTML de status 404 e mensagem informativa quando não existe relatório com o ID informado ou quando o ID não é um UUID válido.

#### Scenario: UUID inexistente
- **WHEN** o usuário abre `/reports/` seguido de um UUID que não existe no banco
- **THEN** a resposta tem status 404 e exibe "Relatório não encontrado"

#### Scenario: ID malformado
- **WHEN** o usuário abre `/reports/abc`
- **THEN** a resposta tem status 404 e é uma página HTML, não um erro JSON de validação

### Requirement: Botão de correção
A página de detalhe SHALL exibir o botão "Executar correção", que envia `POST /reports/{id}/fix`, somente para relatórios com status COMPLETO ou FALHA_CORRECAO.

#### Scenario: Relatório elegível
- **WHEN** o relatório está COMPLETO ou FALHA_CORRECAO
- **THEN** o botão "Executar correção" é exibido

#### Scenario: Relatório não elegível
- **WHEN** o relatório está EM_ANALISE, INCOMPLETO, CORRIGINDO ou CORRIGIDO
- **THEN** o botão "Executar correção" não é exibido

### Requirement: Acionamento da correção antes do agente de correção
Enquanto o agente de correção não existir, `POST /reports/{id}/fix` SHALL redirecionar para a página de detalhe do relatório exibindo a mensagem "Correção ainda não disponível", sem alterar o relatório. O detalhe SHALL também saber exibir a mensagem "Correção já em andamento", usada quando a correção recusa o pedido por já estar em curso.

#### Scenario: Clique no botão
- **WHEN** o usuário clica em "Executar correção" em um relatório COMPLETO
- **THEN** o navegador volta ao detalhe do relatório com a mensagem "Correção ainda não disponível" e o status continua COMPLETO

#### Scenario: Correção já em andamento
- **WHEN** a página de detalhe é aberta indicando que a correção já está em curso
- **THEN** a página exibe a mensagem "Correção já em andamento"

#### Scenario: Correção para relatório inexistente
- **WHEN** é enviado `POST /reports/{id}/fix` para um ID que não existe
- **THEN** a resposta tem status 404

### Requirement: Banco de dados indisponível
Quando o banco de dados não responde, a listagem e o detalhe SHALL exibir a página de erro com status 503 e a mensagem "Banco de dados indisponível, tente novamente em instantes".

#### Scenario: Listagem com banco fora do ar
- **WHEN** o usuário abre `/reports` com o PostgreSQL indisponível
- **THEN** a resposta tem status 503 e exibe "Banco de dados indisponível, tente novamente em instantes"

#### Scenario: Detalhe com banco fora do ar
- **WHEN** o usuário abre `/reports/{id}` com o PostgreSQL indisponível
- **THEN** a resposta tem status 503 e exibe a mesma mensagem
