# Spec Delta

## Purpose

Executar no cluster Kubernetes, sob demanda do operador, a correção descrita em um relatório de diagnóstico, verificar se o recurso afetado ficou saudável e registrar o resultado da correção no relatório.

## ADDED Requirements

### Requirement: Acionamento da correção
`POST /reports/{id}/fix` SHALL, para um relatório COMPLETO ou FALHA_CORRECAO, passar o relatório a CORRIGINDO antes de responder, com uma operação atômica que só tem efeito se o status ainda for COMPLETO ou FALHA_CORRECAO, e então responder `303 See Other` para `/reports/{id}`. A correção SHALL ser executada de forma assíncrona, depois da resposta.

#### Scenario: Relatório completo
- **WHEN** o usuário clica em "Executar correção" em um relatório COMPLETO
- **THEN** a resposta é 303 para `/reports/{id}`, o detalhe exibe o status CORRIGINDO e a correção é iniciada em segundo plano

#### Scenario: Nova tentativa após falha
- **WHEN** é enviado `POST /reports/{id}/fix` para um relatório FALHA_CORRECAO
- **THEN** o relatório passa a CORRIGINDO e uma nova correção é iniciada

### Requirement: Recusa do acionamento
Quando o relatório existe mas não pode passar a CORRIGINDO, `POST /reports/{id}/fix` SHALL responder `409 Conflict` com a página de detalhe do relatório e uma mensagem, sem iniciar a correção: "Correção já em andamento" se o status atual é CORRIGINDO, e "Correção não permitida para relatórios com status X" (X = status atual) nos demais casos.

#### Scenario: Correção já em andamento
- **WHEN** é enviado `POST /reports/{id}/fix` para um relatório CORRIGINDO
- **THEN** a resposta tem status 409, é a página de detalhe e exibe "Correção já em andamento"

#### Scenario: Status não elegível
- **WHEN** é enviado `POST /reports/{id}/fix` para um relatório EM_ANALISE, INCOMPLETO ou CORRIGIDO
- **THEN** a resposta tem status 409 e exibe "Correção não permitida para relatórios com status " seguido do status atual

#### Scenario: Requisições concorrentes
- **WHEN** duas requisições `POST /reports/{id}/fix` chegam ao mesmo tempo para um relatório COMPLETO
- **THEN** exatamente uma responde 303 e inicia a correção, e a outra responde 409

### Requirement: Erros do acionamento
`POST /reports/{id}/fix` SHALL responder com a página HTML de status 404 "Relatório não encontrado" para ID inexistente ou malformado, e com a página de status 503 "Banco de dados indisponível, tente novamente em instantes" quando o banco não responde. Em ambos os casos nenhuma correção é iniciada.

#### Scenario: Relatório inexistente
- **WHEN** é enviado `POST /reports/{id}/fix` para um UUID que não existe
- **THEN** a resposta tem status 404

#### Scenario: Banco indisponível
- **WHEN** é enviado `POST /reports/{id}/fix` com o PostgreSQL indisponível
- **THEN** a resposta tem status 503 e nenhuma correção é iniciada

### Requirement: Ferramentas do agente de correção
O agente de correção SHALL acessar o cluster pelo MCP Server Kubernetes com todas as ferramentas que ele expõe, exceto `kubectl_context`, `port_forward`, `stop_port_forward` e `cleanup`, que alteram o estado do próprio MCP Server. Não há whitelist de ações, dry-run nem restrição por namespace.

#### Scenario: Ferramentas expostas
- **WHEN** o MCP Server expõe `kubectl_get`, `kubectl_patch`, `kubectl_delete`, `kubectl_context`, `port_forward`, `stop_port_forward` e `cleanup`
- **THEN** o agente de correção recebe `kubectl_get`, `kubectl_patch` e `kubectl_delete`, e não recebe as outras quatro

### Requirement: Execução da correção a partir do relatório
O agente de correção SHALL receber o conteúdo Markdown integral do relatório e executar no cluster a solução e o comando sugerido nele, verificando o estado do recurso antes de agir e validando sua saúde depois. A resposta final SHALL conter um veredito `CORRIGIDO:` ou `FALHA:` e a seção de ações executadas.

#### Scenario: Correção previsível
- **WHEN** um relatório COMPLETO diagnostica um Deployment com imagem inexistente e sugere trocar a tag para uma existente
- **THEN** o agente aplica a troca via MCP, verifica que os pods ficam Running e Ready e responde com `CORRIGIDO:`

#### Scenario: Problema persiste
- **WHEN** a ação executada não deixa o recurso afetado saudável
- **THEN** o agente responde com `FALHA:` explicando o que ficou pendente

### Requirement: Erro de ferramenta durante a correção
Quando a execução de uma ferramenta do cluster falha durante a correção (comando rejeitado, recurso inexistente, argumentos inválidos), o erro SHALL ser devolvido ao agente como resultado daquela ferramenta e a correção SHALL continuar, para que o agente tente outra abordagem ou registre a falha. Perda de conexão com o MCP Server SHALL encerrar a correção como FALHA_CORRECAO.

#### Scenario: Comando rejeitado pelo cluster
- **WHEN** o agente chama uma ferramenta com um comando kubectl malformado e o MCP Server responde com erro
- **THEN** o agente recebe a mensagem de erro, a correção continua e o resultado final vem da resposta do agente

#### Scenario: MCP Server cai no meio da correção
- **WHEN** a conexão com o MCP Server é perdida durante a correção
- **THEN** a correção termina e o relatório passa a FALHA_CORRECAO

### Requirement: Classificação do resultado
O status final SHALL ser CORRIGIDO quando a resposta do agente contém uma linha iniciada (ignorando marcação Markdown `-`, `*`, `#`, `>` e negrito) por `CORRIGIDO:` e nenhuma iniciada por `FALHA:`. Em qualquer outro caso, inclusive sem veredito ou com os dois, SHALL ser FALHA_CORRECAO, com warning no log quando não houver veredito único.

#### Scenario: Veredito após um parágrafo
- **WHEN** a resposta começa com um parágrafo de resumo e depois tem a linha `CORRIGIDO: imagem atualizada`
- **THEN** o status final é CORRIGIDO

#### Scenario: Veredito com marcação
- **WHEN** a resposta tem a linha `**FALHA:** pod continua em CrashLoopBackOff`
- **THEN** o status final é FALHA_CORRECAO

#### Scenario: Menção no meio da frase
- **WHEN** a única ocorrência de `CORRIGIDO:` está no meio de uma frase
- **THEN** o status final é FALHA_CORRECAO e um warning é registrado

#### Scenario: Veredito ambíguo
- **WHEN** a resposta tem uma linha `CORRIGIDO: ...` e outra `FALHA: ...`
- **THEN** o status final é FALHA_CORRECAO

### Requirement: Limites da correção
Uma correção SHALL fazer no máximo `CORRECTION_MAX_ITERATIONS` chamadas ao modelo (padrão 25) e durar no máximo `CORRECTION_TIMEOUT_MINUTES` minutos (padrão 10). Atingir o limite de chamadas sem veredito, esgotar o prazo, o MCP Server indisponível ou erro persistente da API do modelo SHALL resultar em FALHA_CORRECAO. Valor não numérico, zero ou negativo SHALL resultar no padrão, com warning.

#### Scenario: Prazo esgotado
- **WHEN** a correção ainda não terminou após `CORRECTION_TIMEOUT_MINUTES` minutos
- **THEN** ela é interrompida e o relatório passa a FALHA_CORRECAO

#### Scenario: MCP Server indisponível
- **WHEN** o MCP Server não responde ao iniciar a correção
- **THEN** o relatório passa a FALHA_CORRECAO

#### Scenario: Valor inválido
- **WHEN** `CORRECTION_TIMEOUT_MINUTES` vale `abc`
- **THEN** o prazo usado é 10 minutos e um warning é registrado

### Requirement: Modelo do agente de correção
O modelo do agente de correção SHALL ser o definido em `CORRECTION_MODEL_NAME`; sem essa variável, SHALL ser o mesmo modelo do agente de análise (`AGENT_MODEL_NAME`, padrão `claude-haiku-4-5`).

#### Scenario: Sem configuração específica
- **WHEN** `CORRECTION_MODEL_NAME` não está definida e `AGENT_MODEL_NAME` vale `claude-sonnet-4-5`
- **THEN** o agente de correção usa `claude-sonnet-4-5`

### Requirement: Registro do resultado da correção
Ao fim de toda correção, o relatório SHALL receber o status final e um resultado da correção em texto: a resposta do agente ou, sem ela, uma mensagem que indique a causa do término (sem resposta final, prazo esgotado ou erro de MCP/API), sem stack trace. A gravação SHALL ocorrer só se o relatório ainda estiver CORRIGINDO; senão o resultado é descartado com warning.

#### Scenario: Correção concluída
- **WHEN** o agente responde `CORRIGIDO: ...` com a seção de ações executadas
- **THEN** o relatório fica CORRIGIDO e o resultado da correção é a resposta do agente

#### Scenario: Limite de chamadas atingido
- **WHEN** a correção termina por limite de chamadas ao modelo sem resposta final
- **THEN** o relatório fica FALHA_CORRECAO e o resultado da correção informa que não houve resposta final

#### Scenario: Relatório já recuperado
- **WHEN** a correção termina depois que o relatório deixou de estar CORRIGINDO
- **THEN** o relatório não é alterado e o descarte é registrado no log
