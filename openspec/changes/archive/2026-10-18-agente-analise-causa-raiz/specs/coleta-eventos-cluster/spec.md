# Spec Delta

## ADDED Requirements

### Requirement: Despacho assíncrono do batch ao pipeline de análise
Os eventos de um ciclo SHALL ser entregues juntos, como uma única lista, ao pipeline de análise de causa raiz, sem limite de quantidade. O despacho SHALL ser fire-and-forget: o coletor não aguarda o processamento. Se não houver eventos a entregar, o pipeline SHALL NOT ser acionado.

#### Scenario: Batch entregue sem bloquear o coletor
- **WHEN** um ciclo coleta 3 eventos e a análise demora mais que o intervalo para processá-los
- **THEN** o pipeline recebe uma única lista com os 3 eventos e o próximo ciclo de coleta inicia no horário previsto

#### Scenario: Nenhum evento no ciclo
- **WHEN** um ciclo não encontra eventos a entregar
- **THEN** o pipeline de análise não é acionado

#### Scenario: Batch encaminhado à análise
- **WHEN** um ciclo coleta eventos
- **THEN** os eventos são encaminhados ao pipeline de análise de causa raiz, e não mais impressos no stdout

## REMOVED Requirements

### Requirement: Despacho assíncrono do batch ao handler
**Reason**: o handler placeholder que imprimia os eventos no stdout foi substituído pelo pipeline de análise de causa raiz (PRD 002).
**Migration**: o comportamento de despacho (lista única, fire-and-forget, batch vazio não despachado) continua no requisito "Despacho assíncrono do batch ao pipeline de análise".
