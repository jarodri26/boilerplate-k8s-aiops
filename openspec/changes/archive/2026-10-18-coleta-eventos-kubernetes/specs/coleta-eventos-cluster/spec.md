# Spec Delta

## Purpose

Coletar automaticamente, em intervalos regulares, os eventos Warning do cluster Kubernetes e entregá-los em lote, num contrato estável, ao pipeline de análise, sem intervenção manual do operador.

## ADDED Requirements

### Requirement: Coleta periódica com primeira execução no startup
O sistema SHALL executar uma coleta assim que a aplicação inicia e, a partir daí, repetir a coleta a cada `EVENT_COLLECTION_INTERVAL_MINUTES` minutos (padrão: 3). A coleta SHALL rodar dentro do processo da aplicação, sem job externo, e SHALL parar quando a aplicação é encerrada.

#### Scenario: Primeira coleta no startup
- **WHEN** a aplicação inicia
- **THEN** uma coleta é executada imediatamente, sem aguardar o primeiro intervalo

#### Scenario: Ciclos seguintes respeitam o intervalo
- **WHEN** `EVENT_COLLECTION_INTERVAL_MINUTES` vale `5`
- **THEN** após a primeira coleta, as coletas seguintes ocorrem a cada 5 minutos

#### Scenario: Encerramento da aplicação
- **WHEN** a aplicação é encerrada
- **THEN** o loop de coleta é interrompido e nenhum novo ciclo é iniciado

### Requirement: Validação do intervalo configurado
O sistema SHALL aceitar como intervalo um número positivo de minutos (inteiro ou fracionário). Valor ausente usa o padrão de 3 minutos. Valor não numérico, zero ou negativo SHALL resultar no padrão de 3 minutos com um warning no log.

#### Scenario: Valor não numérico
- **WHEN** `EVENT_COLLECTION_INTERVAL_MINUTES` vale `abc`
- **THEN** o intervalo usado é 3 minutos e um warning é registrado no log

#### Scenario: Valor zero ou negativo
- **WHEN** `EVENT_COLLECTION_INTERVAL_MINUTES` vale `0` ou `-2`
- **THEN** o intervalo usado é 3 minutos e um warning é registrado no log

#### Scenario: Valor fracionário
- **WHEN** `EVENT_COLLECTION_INTERVAL_MINUTES` vale `0.5`
- **THEN** o intervalo usado é 30 segundos

### Requirement: Escopo dos eventos coletados
O sistema SHALL coletar apenas eventos do tipo `Warning`, de todos os namespaces do cluster, a partir da API `events.k8s.io/v1`. Eventos do tipo `Normal` SHALL ser ignorados.

#### Scenario: Apenas Warning
- **WHEN** o cluster contém eventos `Normal` e `Warning` na janela de coleta
- **THEN** apenas os eventos `Warning` são entregues

#### Scenario: Todos os namespaces
- **WHEN** existem eventos `Warning` nos namespaces `default` e `kube-system`
- **THEN** os eventos de ambos os namespaces são entregues

### Requirement: Recência do evento por precedência de timestamps
O sistema SHALL determinar a recência de cada evento pelo primeiro campo presente na ordem `series.lastObservedTime` → `eventTime` → `deprecatedLastTimestamp`. Eventos sem nenhum desses campos SHALL ser descartados com um warning no log.

#### Scenario: Evento recorrente com series
- **WHEN** um evento tem `series.lastObservedTime` recente e `eventTime` anterior à janela de coleta
- **THEN** a recência é `series.lastObservedTime` e o evento é coletado

#### Scenario: Evento legado sem eventTime
- **WHEN** um evento não tem `series` nem `eventTime`, mas tem `deprecatedLastTimestamp`
- **THEN** a recência é `deprecatedLastTimestamp`

#### Scenario: Evento sem timestamp
- **WHEN** um evento não tem `series.lastObservedTime`, `eventTime` nem `deprecatedLastTimestamp`
- **THEN** o evento é descartado e um warning é registrado no log

### Requirement: Janela de coleta com margem de segurança
Cada coleta SHALL considerar eventos com recência posterior a `marca d'água − margem`, em que a marca d'água é o início da última coleta bem-sucedida e a margem é um valor fixo (60 s). Na primeira coleta após o startup, a marca d'água SHALL ser `início da coleta − intervalo configurado`. A marca d'água SHALL avançar a cada coleta bem-sucedida, independentemente do processamento pelo handler.

#### Scenario: Evento publicado com atraso
- **WHEN** um evento com recência 10 s anterior à marca d'água só se torna visível na API após a coleta que definiu essa marca
- **THEN** o evento é coletado no ciclo seguinte

#### Scenario: Evento antigo fora da janela
- **WHEN** um evento tem recência anterior a `marca d'água − margem`
- **THEN** o evento não é entregue

#### Scenario: Janela da primeira coleta
- **WHEN** a aplicação inicia com intervalo de 3 minutos
- **THEN** a primeira coleta considera eventos com recência nos últimos 3 minutos mais a margem

#### Scenario: Marca d'água não avança em coleta falha
- **WHEN** uma coleta falha por erro de comunicação com o cluster
- **THEN** a marca d'água permanece a da última coleta bem-sucedida

### Requirement: Não reenvio de eventos sem recorrência
O sistema SHALL entregar um evento somente se seu `uid` ainda não foi entregue ou se sua recência é posterior à última recência entregue para aquele `uid`. Esse registro SHALL ser mantido apenas em memória e SHALL descartar entradas que já saíram da janela de coleta.

#### Scenario: Evento visto de novo sem mudança
- **WHEN** um evento já entregue aparece novamente na janela de solape com a mesma recência
- **THEN** o evento não é entregue de novo

#### Scenario: Evento recorrente
- **WHEN** um evento já entregue aparece com recência posterior à última entregue (ex.: `deprecatedLastTimestamp` ou `series.lastObservedTime` avançou)
- **THEN** o evento é entregue novamente com o novo `timestamp`

#### Scenario: Restart da aplicação
- **WHEN** a aplicação reinicia
- **THEN** o registro de UIDs começa vazio e eventos da janela da primeira coleta podem ser entregues novamente

### Requirement: Contrato de saída do evento
Cada evento entregue SHALL ser um dict com as chaves `uid`, `type`, `reason`, `message`, `namespace`, `involved_object` (`kind`, `name`, `namespace`) e `timestamp`, mapeados de `events.k8s.io/v1` (`note` → `message`, `regarding` → `involved_object`). `timestamp` SHALL ser a recência do evento em ISO 8601.

#### Scenario: Mapeamento dos campos
- **WHEN** um evento com `note="Back-off restarting"` e `regarding={kind: Pod, name: api-1, namespace: prod}` é coletado
- **THEN** o dict entregue tem `message="Back-off restarting"` e `involved_object={"kind": "Pod", "name": "api-1", "namespace": "prod"}`

#### Scenario: Recurso cluster-scoped
- **WHEN** o evento se refere a um recurso sem namespace (ex.: `Node`)
- **THEN** `involved_object.namespace` é a string vazia

#### Scenario: Timestamp em ISO 8601
- **WHEN** a recência do evento é `deprecatedLastTimestamp`
- **THEN** `timestamp` contém esse valor formatado em ISO 8601

### Requirement: Despacho assíncrono do batch ao handler
Os eventos de um ciclo SHALL ser entregues juntos, como uma única lista, ao handler de eventos, sem limite de quantidade. O despacho SHALL ser fire-and-forget: o coletor não aguarda o processamento. Se não houver eventos a entregar, o handler SHALL NOT ser acionado. Nesta fase, o handler imprime os eventos no stdout.

#### Scenario: Batch entregue sem bloquear o coletor
- **WHEN** um ciclo coleta 3 eventos e o handler demora mais que o intervalo para processá-los
- **THEN** o handler recebe uma única lista com os 3 eventos e o próximo ciclo de coleta inicia no horário previsto

#### Scenario: Nenhum evento no ciclo
- **WHEN** um ciclo não encontra eventos a entregar
- **THEN** o handler não é acionado

#### Scenario: Handler placeholder
- **WHEN** o handler recebe um batch
- **THEN** os eventos são impressos no stdout

### Requirement: Resiliência a falhas
Falhas na comunicação com o cluster, falta de permissão (RBAC) ou erros do handler SHALL ser registrados no log sem interromper o loop de coleta. Erros do handler SHALL NOT afetar a marca d'água.

#### Scenario: Cluster inacessível
- **WHEN** o cluster está inacessível durante uma coleta
- **THEN** o erro é registrado no log e o próximo ciclo ocorre normalmente

#### Scenario: Permissão insuficiente
- **WHEN** a API retorna 403 ao listar eventos
- **THEN** o log indica que é necessária permissão de `list` em `events.events.k8s.io` em todos os namespaces, e o loop continua

#### Scenario: Erro no handler
- **WHEN** o handler lança exceção ao processar um batch
- **THEN** a exceção é registrada no log, não chega ao coletor e a marca d'água já avançada permanece

#### Scenario: Configuração do cluster indisponível no startup
- **WHEN** a aplicação inicia sem kubeconfig válido e fora do cluster
- **THEN** a aplicação continua de pé (API e interface web respondem), o erro é registrado no log e a coleta é tentada novamente no ciclo seguinte
