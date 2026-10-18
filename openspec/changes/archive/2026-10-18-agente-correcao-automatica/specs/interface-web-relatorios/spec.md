# Spec Delta

## ADDED Requirements

### Requirement: Resultado da correção no detalhe
Quando o relatório tem resultado da correção, a página de detalhe SHALL exibi-lo numa seção "Resultado da Correção", renderizado de Markdown para HTML com a mesma sanitização do conteúdo do relatório. Sem resultado da correção, a seção SHALL não ser exibida.

#### Scenario: Correção concluída
- **WHEN** o usuário abre o detalhe de um relatório CORRIGIDO cujo resultado da correção contém a seção "Acoes Executadas"
- **THEN** a página exibe a seção "Resultado da Correção" com esse conteúdo formatado

#### Scenario: Resultado com script
- **WHEN** o resultado da correção contém `<script>alert(1)</script>`
- **THEN** o HTML da página não contém esse elemento `<script>`

#### Scenario: Sem correção
- **WHEN** o usuário abre o detalhe de um relatório COMPLETO que nunca foi corrigido
- **THEN** a seção "Resultado da Correção" não aparece

## REMOVED Requirements

### Requirement: Acionamento da correção antes do agente de correção
**Reason**: o agente de correção existe; o acionamento real e suas recusas passam a ser definidos pela capability `correcao-automatica` ("Acionamento da correção", "Recusa do acionamento" e "Erros do acionamento").
**Migration**: a mensagem "Correção ainda não disponível" e a chave `?fix=indisponivel` deixam de existir; "Correção já em andamento" passa a ser exibida pela resposta 409 de `POST /reports/{id}/fix`.
