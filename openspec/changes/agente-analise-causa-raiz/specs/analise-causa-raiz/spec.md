# Spec Delta

## Purpose

Investigar automaticamente a causa raiz dos eventos Warning coletados do cluster, sem reprocessar eventos já em tratamento, e transformar o diagnóstico em relatórios estruturados por problema.

## ADDED Requirements

### Requirement: Descarte de eventos sem uid
O pipeline SHALL descartar, antes de qualquer outra etapa, os eventos do batch cujo `uid` é vazio, registrando um warning no log. Se nenhum evento restar, o pipeline SHALL encerrar sem consultar o banco.

#### Scenario: Evento sem uid no batch
- **WHEN** o batch contém um evento com `uid=""` e outro com `uid="u1"`
- **THEN** apenas o evento `u1` segue para a deduplicação e um warning é registrado no log

#### Scenario: Batch só com eventos sem uid
- **WHEN** todos os eventos do batch têm `uid=""`
- **THEN** nenhuma análise é iniciada e nenhum relatório é criado

### Requirement: Filtragem de eventos já em tratamento
O pipeline SHALL ignorar todo evento cujo `uid` esteja contido em ao menos um relatório com status ativo (EM_ANALISE, COMPLETO, CORRIGINDO ou FALHA_CORRECAO), mesmo que outros relatórios com o mesmo uid estejam em CORRIGIDO ou INCOMPLETO. Eventos vinculados apenas a relatórios CORRIGIDO ou INCOMPLETO, ou a nenhum relatório, SHALL ser analisados.

#### Scenario: Evento novo
- **WHEN** o uid do evento não aparece em nenhum relatório
- **THEN** o evento é analisado

#### Scenario: Evento em relatório ativo
- **WHEN** o uid do evento aparece em um relatório EM_ANALISE, COMPLETO, CORRIGINDO ou FALHA_CORRECAO
- **THEN** o evento é ignorado

#### Scenario: Reincidência após correção
- **WHEN** o uid do evento aparece apenas em um relatório CORRIGIDO
- **THEN** o evento é analisado e gera um novo relatório

#### Scenario: Reanálise de análise inconclusiva
- **WHEN** o uid do evento aparece apenas em um relatório INCOMPLETO
- **THEN** o evento é analisado

#### Scenario: Relatório antigo corrigido e relatório atual ativo
- **WHEN** o uid do evento aparece em um relatório CORRIGIDO antigo e em um relatório EM_ANALISE atual
- **THEN** o evento é ignorado

#### Scenario: Batch parcialmente em tratamento
- **WHEN** o batch contém os eventos `u1` (em relatório COMPLETO) e `u2` (novo)
- **THEN** apenas `u2` é analisado

#### Scenario: Batch inteiramente em tratamento
- **WHEN** todos os eventos do batch estão em relatórios ativos
- **THEN** nenhuma análise é iniciada e nenhum relatório é criado

#### Scenario: Banco indisponível na deduplicação
- **WHEN** o banco está indisponível durante a consulta de deduplicação
- **THEN** o erro é registrado no log, o batch é descartado e o coletor não é afetado

### Requirement: Registro do batch antes da investigação
Antes de qualquer chamada ao modelo ou ao MCP Server, o pipeline SHALL criar um único relatório EM_ANALISE contendo os uids de todos os eventos a analisar do batch.

#### Scenario: Ciclo seguinte durante a análise
- **WHEN** um evento do batch em análise é reentregue pelo coletor antes do fim da análise
- **THEN** o evento é ignorado pela deduplicação

### Requirement: Investigação somente leitura via MCP
O agente SHALL investigar o cluster exclusivamente pelas operações de leitura `kubectl_get`, `kubectl_describe` e `kubectl_logs` do MCP Server Kubernetes, em `MCP_SERVER_URL` (padrão `http://localhost:3001/mcp`). Nenhuma operação de escrita do MCP Server SHALL ficar disponível ao agente.

#### Scenario: Tools disponíveis ao agente
- **WHEN** o MCP Server expõe tools de leitura e de escrita (`kubectl_apply`, `kubectl_patch`, `kubectl_delete` etc.)
- **THEN** o agente recebe apenas `kubectl_get`, `kubectl_describe` e `kubectl_logs`

#### Scenario: Erro de execução de uma tool
- **WHEN** uma tool retorna erro de execução (ex.: recurso inexistente ou parâmetro inválido)
- **THEN** o erro é devolvido ao agente como resultado da tool e a investigação continua

#### Scenario: MCP Server indisponível
- **WHEN** o MCP Server não responde ao iniciar a análise ou durante ela
- **THEN** a análise é abortada, o relatório do batch passa a INCOMPLETO e o erro é registrado no log

### Requirement: Modelo configurável
O agente SHALL usar o modelo Claude indicado em `AGENT_MODEL_NAME` (padrão `claude-haiku-4-5`) e SHALL repetir chamadas que falham por erro transitório da API (rate limit, timeout) até 3 vezes com backoff exponencial antes de desistir.

#### Scenario: Modelo padrão
- **WHEN** `AGENT_MODEL_NAME` não está definido
- **THEN** a análise usa `claude-haiku-4-5`

#### Scenario: Erro da API esgotado
- **WHEN** a API do Claude falha em todas as tentativas
- **THEN** a análise é abortada, o relatório do batch passa a INCOMPLETO e o erro é registrado no log

### Requirement: Limite de iterações do agente
O agente SHALL fazer no máximo `AGENT_MAX_ITERATIONS` chamadas ao modelo por análise (padrão 25). Ao atingir o limite, o run SHALL encerrar sem uma chamada extra ao modelo. Valor não numérico, zero ou negativo SHALL resultar no padrão, com warning no log.

#### Scenario: Limite configurado
- **WHEN** `AGENT_MAX_ITERATIONS` vale `5` e o agente ainda não respondeu após 5 chamadas ao modelo
- **THEN** o run encerra sem uma sexta chamada

#### Scenario: Valor inválido
- **WHEN** `AGENT_MAX_ITERATIONS` vale `abc`, `0` ou `-3`
- **THEN** o limite usado é 25 e um warning é registrado no log

### Requirement: Prazo total da análise
Cada análise SHALL ter prazo total de `AGENT_TIMEOUT_MINUTES` minutos (padrão 20), contado a partir do início efetivo da investigação. O prazo SHALL ser menor que `ANALYSIS_STALE_TIMEOUT_MINUTES`. Se o valor configurado for maior ou igual, o sistema SHALL usar `ANALYSIS_STALE_TIMEOUT_MINUTES - 1` e registrar um warning. Estourado o prazo, a análise SHALL ser abortada e o relatório do batch SHALL passar a INCOMPLETO.

#### Scenario: Análise excede o prazo
- **WHEN** a investigação ainda está em andamento após `AGENT_TIMEOUT_MINUTES`
- **THEN** a análise é abortada, o relatório do batch passa a INCOMPLETO e o erro é registrado no log

#### Scenario: Prazo maior que o stale timeout
- **WHEN** `AGENT_TIMEOUT_MINUTES` vale `40` e `ANALYSIS_STALE_TIMEOUT_MINUTES` vale `30`
- **THEN** o prazo usado é 29 minutos e um warning é registrado no log

#### Scenario: Valor inválido
- **WHEN** `AGENT_TIMEOUT_MINUTES` vale `abc`, `0` ou `-1`
- **THEN** o prazo usado é o padrão e um warning é registrado no log

### Requirement: Limite de análises simultâneas
O sistema SHALL executar no máximo `ANALYSIS_MAX_CONCURRENCY` investigações ao mesmo tempo (padrão 1). Um batch que aguarda vaga SHALL permanecer registrado como EM_ANALISE e SHALL ter seu `updated_at` renovado no momento em que a investigação efetivamente começa. Valor não numérico, zero ou negativo SHALL resultar no padrão, com warning no log.

#### Scenario: Segundo batch aguarda
- **WHEN** `ANALYSIS_MAX_CONCURRENCY` vale `1` e um novo batch chega enquanto outra investigação está em andamento
- **THEN** o novo batch fica registrado como EM_ANALISE e sua investigação só começa quando a anterior termina

#### Scenario: Espera na fila não causa estagnação
- **WHEN** um batch aguarda vaga por um tempo próximo de `ANALYSIS_STALE_TIMEOUT_MINUTES` e então começa a ser investigado
- **THEN** o relatório não é marcado como estagnado durante a investigação, porque `updated_at` foi renovado no início

#### Scenario: Valor inválido
- **WHEN** `ANALYSIS_MAX_CONCURRENCY` vale `abc`, `0` ou `-1`
- **THEN** o limite usado é 1 e um warning é registrado no log

### Requirement: Relatório por problema a partir da resposta do agente
A resposta Markdown do agente SHALL ser dividida em uma seção por problema (`## Problema N: ...`). Cada seção SHALL virar um relatório próprio, contendo apenas o Markdown daquela seção, os uids listados em seu campo **Eventos** que pertencem ao batch e a severidade do campo **Severidade:**. A tabela Resumo SHALL ser descartada.

#### Scenario: Batch com dois problemas independentes
- **WHEN** a resposta contém duas seções de problema, cada uma listando uids distintos do batch
- **THEN** são criados dois relatórios, cada um com seu Markdown, seus uids e sua severidade

#### Scenario: Uid fora do batch
- **WHEN** o campo **Eventos** de uma seção cita um uid que não pertence ao batch
- **THEN** esse uid não é gravado no relatório

#### Scenario: Seção sem nenhum uid do batch
- **WHEN** uma seção de problema não lista nenhum uid pertencente ao batch
- **THEN** a seção não gera relatório e um warning é registrado no log

#### Scenario: Uid citado em duas seções
- **WHEN** o mesmo uid do batch aparece no campo **Eventos** de duas seções
- **THEN** o uid é gravado apenas no relatório da primeira seção e um warning é registrado no log

#### Scenario: Evento do batch não referenciado
- **WHEN** um evento do batch não aparece no campo **Eventos** de nenhuma seção
- **THEN** um warning com o uid é registrado no log e o evento fica sem relatório

#### Scenario: Resposta sem seções de problema
- **WHEN** a resposta do agente é vazia ou não contém nenhuma seção de problema identificável
- **THEN** o relatório do batch passa a INCOMPLETO e nenhum relatório por problema é criado

### Requirement: Status de cada relatório por problema
Um relatório por problema SHALL receber status COMPLETO quando sua severidade é CRITICO, ALTO, MEDIO ou BAIXO e sua seção de Causa Raiz não é vazia nem contém o termo "inconclusiv" (sem distinção de maiúsculas). Caso contrário, SHALL receber INCOMPLETO. O critério SHALL valer também quando o agente atingiu o limite de iterações.

#### Scenario: Problema diagnosticado
- **WHEN** a seção tem `**Severidade:** ALTO` e uma Causa Raiz descritiva
- **THEN** o relatório é COMPLETO com severidade ALTO

#### Scenario: Causa raiz inconclusiva
- **WHEN** a seção tem a Causa Raiz "Inconclusiva: limite de investigação atingido"
- **THEN** o relatório é INCOMPLETO

#### Scenario: Severidade ausente ou inválida
- **WHEN** a seção não tem o campo Severidade ou ele tem um valor fora da lista
- **THEN** o relatório é INCOMPLETO e sua severidade fica vazia

### Requirement: Falhas do pipeline não afetam o coletor
Nenhuma falha do pipeline de análise SHALL ser propagada ao coletor de eventos. Toda falha SHALL ser registrada no log.

#### Scenario: Falha durante a análise
- **WHEN** a análise de um batch falha por qualquer motivo
- **THEN** o erro é registrado no log e o próximo ciclo de coleta ocorre normalmente
