# Spec Delta

## MODIFIED Requirements

### Requirement: Campos do relatório
Cada relatório SHALL ser persistido no PostgreSQL com: identificador UUID único, conteúdo Markdown, status, severidade (CRITICO, ALTO, MEDIO, BAIXO ou vazia), lista de uids de eventos Kubernetes, resultado da correção (texto, vazio enquanto nenhuma correção terminou) e os instantes de criação e de última atualização.

#### Scenario: Relatório por problema persistido
- **WHEN** a análise de um batch termina com um problema diagnosticado
- **THEN** o relatório gravado tem UUID próprio, o Markdown da seção, status, severidade, os uids daquele problema, resultado da correção vazio e `created_at`/`updated_at` preenchidos

#### Scenario: Relatório do batch em análise
- **WHEN** um batch começa a ser analisado
- **THEN** o relatório EM_ANALISE gravado tem os uids de todos os eventos a analisar e severidade vazia

## ADDED Requirements

### Requirement: Transições de correção condicionais
A passagem a CORRIGINDO SHALL ser atômica e só ocorrer se o status for COMPLETO ou FALHA_CORRECAO, zerando o resultado da correção anterior. A passagem de CORRIGINDO a CORRIGIDO ou FALHA_CORRECAO SHALL só ocorrer se o relatório ainda estiver CORRIGINDO. Toda transição de correção SHALL atualizar o instante de última atualização.

#### Scenario: Reacionamento zera o resultado anterior
- **WHEN** um relatório FALHA_CORRECAO com resultado da correção preenchido passa a CORRIGINDO
- **THEN** o resultado da correção fica vazio

#### Scenario: Transição a partir de status não elegível
- **WHEN** se tenta passar a CORRIGINDO um relatório CORRIGIDO
- **THEN** nada é alterado e a operação indica que não houve transição

#### Scenario: Final após recuperação
- **WHEN** se tenta gravar CORRIGIDO em um relatório que já está FALHA_CORRECAO
- **THEN** nada é alterado

### Requirement: Recuperação de correções interrompidas no startup
No startup da aplicação, todo relatório CORRIGINDO SHALL passar a FALHA_CORRECAO, com um resultado da correção informando que a correção foi interrompida pelo reinício da aplicação.

#### Scenario: Restart durante uma correção
- **WHEN** a aplicação reinicia com um relatório CORRIGINDO no banco
- **THEN** o relatório passa a FALHA_CORRECAO e a correção pode ser acionada novamente
