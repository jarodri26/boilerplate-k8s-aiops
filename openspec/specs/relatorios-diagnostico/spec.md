# relatorios-diagnostico Specification

## Purpose

Armazenar os relatórios de diagnóstico produzidos pela análise de causa raiz e governar seu ciclo de vida de status, servindo de fonte única para a interface web e para a correção.

## Requirements

### Requirement: Campos do relatório
Cada relatório SHALL ser persistido no PostgreSQL com: identificador UUID único, conteúdo Markdown, status, severidade (CRITICO, ALTO, MEDIO, BAIXO ou vazia), lista de uids de eventos Kubernetes e os instantes de criação e de última atualização.

#### Scenario: Relatório por problema persistido
- **WHEN** a análise de um batch termina com um problema diagnosticado
- **THEN** o relatório gravado tem UUID próprio, o Markdown da seção, status, severidade, os uids daquele problema e `created_at`/`updated_at` preenchidos

#### Scenario: Relatório do batch em análise
- **WHEN** um batch começa a ser analisado
- **THEN** o relatório EM_ANALISE gravado tem os uids de todos os eventos a analisar e severidade vazia

### Requirement: Status do relatório
O status de um relatório SHALL ser um entre EM_ANALISE, COMPLETO, INCOMPLETO, CORRIGINDO, CORRIGIDO e FALHA_CORRECAO. As transições de análise SHALL ser EM_ANALISE → COMPLETO e EM_ANALISE → INCOMPLETO. As transições de correção (COMPLETO → CORRIGINDO → CORRIGIDO | FALHA_CORRECAO, FALHA_CORRECAO → CORRIGINDO) são reservadas para a correção.

#### Scenario: Status fora da lista
- **WHEN** se tenta gravar um relatório com status diferente dos seis definidos
- **THEN** a gravação é rejeitada

### Requirement: Substituição condicional do relatório do batch
Ao fim de uma análise, o relatório EM_ANALISE do batch SHALL ser substituído pelos relatórios por problema em uma única operação atômica, somente se ainda estiver EM_ANALISE. Se já tiver mudado de status, o resultado da análise SHALL ser descartado sem criar relatórios, e o descarte SHALL ser registrado no log.

#### Scenario: Substituição bem-sucedida
- **WHEN** a análise termina e o relatório do batch ainda está EM_ANALISE
- **THEN** o relatório do batch deixa de existir e os relatórios por problema passam a existir, sem estado intermediário visível

#### Scenario: Batch já liberado por estagnação
- **WHEN** a análise termina depois que o relatório do batch foi marcado INCOMPLETO por estagnação
- **THEN** nenhum relatório por problema é criado, o relatório INCOMPLETO permanece e o descarte é registrado no log

#### Scenario: Banco indisponível na persistência
- **WHEN** o banco está indisponível ao gravar o resultado
- **THEN** a gravação é repetida com backoff e, após a falha definitiva, o erro é registrado no log junto com o Markdown gerado

### Requirement: Recuperação de análises interrompidas no startup
No startup da aplicação, antes da primeira coleta, todo relatório EM_ANALISE SHALL passar a INCOMPLETO.

#### Scenario: Restart durante uma análise
- **WHEN** a aplicação reinicia com um relatório EM_ANALISE no banco
- **THEN** o relatório passa a INCOMPLETO e seus eventos voltam a ser elegíveis para análise

### Requirement: Recuperação de análises estagnadas
A cada consulta de deduplicação, todo relatório EM_ANALISE cuja última atualização é mais antiga que `ANALYSIS_STALE_TIMEOUT_MINUTES` minutos (padrão 30) SHALL passar a INCOMPLETO antes da avaliação dos eventos. Valor não numérico, zero ou negativo SHALL resultar no padrão, com warning no log.

#### Scenario: Análise estagnada
- **WHEN** existe um relatório EM_ANALISE atualizado pela última vez há 31 minutos e um batch novo é deduplicado
- **THEN** o relatório passa a INCOMPLETO e seus eventos, se presentes no batch, são analisados

#### Scenario: Análise dentro do prazo
- **WHEN** existe um relatório EM_ANALISE atualizado há 10 minutos
- **THEN** o relatório permanece EM_ANALISE

#### Scenario: Valor inválido
- **WHEN** `ANALYSIS_STALE_TIMEOUT_MINUTES` vale `abc`, `0` ou `-5`
- **THEN** o timeout usado é 30 minutos e um warning é registrado no log
