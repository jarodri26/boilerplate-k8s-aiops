# Proposal

## Why

Hoje a descoberta de problemas no cluster é manual (`kubectl get events`, dashboards), o que deixa warnings passarem despercebidos por 30 min–2 h. Este change implementa o PRD 001 (`docs/prds/001-coleta-eventos-kubernetes.md`): uma coleta automática e periódica de eventos Warning, que é a entrada obrigatória do pipeline de análise do PRD 002.

## What Changes

- Novo loop assíncrono dentro do processo FastAPI que coleta eventos `Warning` de todos os namespaces via API `events.k8s.io/v1` (Python SDK `kubernetes`).
- **Primeira coleta imediata no startup** da aplicação. Os ciclos seguintes respeitam `EVENT_COLLECTION_INTERVAL_MINUTES` (padrão 3; valor inválido → padrão + warning no log).
- Recência de cada evento determinada pela precedência `series.lastObservedTime` → `eventTime` → `deprecatedLastTimestamp`. Eventos sem nenhum dos três são descartados com warning.
- Janela de consulta baseada em marca d'água **com margem de segurança** (refinamento do PRD): a janela recua uma margem fixa (~60 s) para absorver publicação tardia de eventos e diferença de relógio entre a aplicação e o cluster. Um registro em memória `uid → última recência enviada` evita reenviar eventos cuja recência não avançou. Assim, eventos one-shot não se perdem e o solape não gera falsa reincidência no PRD 002.
- A primeira coleta usa como janela o intervalo configurado (mais a margem). Estado da marca d'água e do registro de UIDs fica apenas em memória.
- Transformação para um contrato de saída próprio (`uid`, `type`, `reason`, `message`, `namespace`, `involved_object{kind,name,namespace}`, `timestamp` ISO 8601), desacoplado do SDK.
- Despacho do batch de forma assíncrona (fire-and-forget) a um `EventHandler` placeholder que imprime os eventos no stdout. Batch vazio não é despachado.
- Tratamento resiliente de erros: cluster inacessível, RBAC insuficiente e exceções do handler são logados e não interrompem o loop.
- Infraestrutura de testes (pytest) adicionada ao projeto, que hoje não tem nenhuma.
- Documentação da ClusterRole necessária (`list` em `events.events.k8s.io`) e da nova variável de ambiente.

## Capabilities

### New Capabilities
- `coleta-eventos-cluster`: coleta periódica de eventos Warning do cluster Kubernetes, incluindo janela temporal/marca d'água, precedência de timestamps, contrato de saída, despacho assíncrono ao handler e resiliência a falhas.

### Modified Capabilities
<!-- Nenhuma: não existem specs no projeto. -->

## Impact

- **Código**: novo módulo em `src/my_agent_app/collector/` (cliente K8s, loop, transformação, handler); `src/my_agent_app/main.py` (`lifespan` inicia e cancela o loop).
- **Dependências**: `kubernetes` (runtime); `pytest` e `pytest-asyncio` (dev).
- **Configuração**: nova env var `EVENT_COLLECTION_INTERVAL_MINUTES` (`.env.example`, `CLAUDE.md`, `README.md`).
- **Cluster**: requer acesso via kubeconfig (local) ou ServiceAccount (in-cluster) com permissão de `list` em eventos de todos os namespaces.
- **Premissa operacional**: uma única instância da aplicação (um worker uvicorn / uma réplica). Múltiplas instâncias duplicariam a coleta.
- **PRD 002**: consome o contrato de saída e a assinatura `async def handle(events: list[dict]) -> None` definidos aqui.
