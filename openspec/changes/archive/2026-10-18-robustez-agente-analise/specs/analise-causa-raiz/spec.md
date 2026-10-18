# Spec Delta

## MODIFIED Requirements

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

#### Scenario: Conteúdo após a última seção de problema
- **WHEN** a resposta termina com um título de nível 2 que não é de problema (ex.: `## Resumo de Ações Recomendadas`) depois da última seção `## Problema N`
- **THEN** o relatório do último problema não contém esse título nem o conteúdo abaixo dele, e mantém seus subtítulos `###`
