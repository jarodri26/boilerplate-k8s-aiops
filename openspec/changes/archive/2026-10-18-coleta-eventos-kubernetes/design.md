# Design

## Context

Motivação em `proposal.md`. Requisitos em `specs/coleta-eventos-cluster/spec.md`.

Estado atual relevante:
- `src/my_agent_app/collector/` existe só como pacote vazio.
- `main.py` tem um `lifespan` que cria o engine SQLAlchemy e o publica em `app.state`. É o ponto natural para iniciar e cancelar o loop.
- A configuração por env var segue o padrão de `database.py`: constante `DEFAULT_*` e função `get_*()` lendo `os.environ`.
- Não há testes nem pytest configurado.
- O SDK `kubernetes` é síncrono (HTTP bloqueante).

## Goals / Non-Goals

**Goals:**
- Loop de coleta isolado em módulos pequenos e testáveis sem cluster real (lógica de janela, dedup e transformação são funções puras).
- Nenhum bloqueio do event loop do FastAPI.
- Fronteira estável com o PRD 002: o contrato do dict e a assinatura `async def handle(events: list[dict]) -> None`.

**Non-Goals:**
- Paginação da listagem, `watch` da API, persistência de eventos, multi-cluster e multi-instância.
- Limite de concorrência das tasks do handler. O placeholder é instantâneo. O PRD 002 decide se precisa de semáforo.

## Decisions

### D1. Estrutura do módulo `collector/`

```
collector/
  config.py        get_collection_interval_seconds()  (env var + validação)
  k8s_client.py    load_k8s_config(); list_warning_events() -> list[dict]  (JSON cru)
  transform.py     event_recency(ev: dict) -> datetime | None; to_contract(ev, ts) -> dict
  window.py        CollectionWindow: watermark, margem, registro uid -> recência
  handler.py       EventHandler.handle(events) (placeholder, stdout)
  loop.py          EventCollector: run() / start() / stop(); despacho fire-and-forget
```

Separar `window.py` e `transform.py` deixa o núcleo da regra de negócio testável com objetos falsos, sem SDK nem rede.

### D2. Listagem: `EventsV1Api.list_event_for_all_namespaces(field_selector="type=Warning", _preload_content=False)` + JSON cru

O filtro por tipo é feito no servidor e reduz o volume transferido (eventos têm TTL de ~1 h). Não há filtro temporal no servidor, então a janela é aplicada no cliente. A chamada roda via `asyncio.to_thread`.

A resposta **não** é desserializada nos modelos do SDK: usamos `_preload_content=False` e `json.loads(resp.data)`, trabalhando com os itens como dicts (chaves camelCase da API). Motivo: no `kubernetes` 37.x os modelos são pydantic e declaram `eventTime` como `datetime` obrigatório. Um único evento com `eventTime: null` faz a desserialização da lista inteira falhar com `ValidationError`, e esse é justamente o caso da maioria dos Warnings reais (eventos do kubelet emitidos pelo recorder legado, ver D4). O SDK continua sendo usado para transporte, autenticação e `field_selector`.

*Alternativas:* modelos tipados do SDK (quebram com `eventTime` nulo, como verificado na implementação); versões antigas do SDK (mesmo defeito via `client_side_validation`); `kubernetes_asyncio` (dependência a mais, e o PRD já fixou `to_thread`); `CoreV1Api` (API antiga; o PRD fixou `events.k8s.io/v1`).

### D3. Janela = marca d'água − margem, com registro de UIDs (refinamento do PRD)

```
 ciclo k:  t0 = now()                       (antes da chamada a API)
           lower = watermark - MARGIN       (MARGIN = 60s)
           para cada evento: r = recency(ev)
               r is None                     -> descarta + warning
               r <= lower                    -> fora da janela
               sent.get(uid) >= r            -> ja enviado, sem recorrencia
               senao                         -> entrega; sent[uid] = r
           sucesso -> watermark = t0 ; poda sent onde r <= lower
           falha   -> watermark inalterada
 inicial:  watermark = startup - interval
```

- `t0` é capturado **antes** da listagem, para que eventos que aparecem durante a chamada fiquem dentro da próxima janela.
- A margem absorve dois efeitos: publicação tardia do evento (o timestamp é anterior ao momento em que ele fica visível na API) e diferença de relógio entre a aplicação e o cluster. A comparação mistura o relógio da aplicação (`t0`) com o do cluster (recência).
- O registro `sent` impede que o solape da margem chegue ao PRD 002 como falsa reincidência: no PRD 002, um UID vinculado a um relatório CORRIGIDO/INCOMPLETO é reanalisado.
- O registro só é atualizado depois de o batch ser montado com sucesso. A poda mantém o tamanho limitado aos eventos da janela.

*Alternativas:* marca d'água exata do PRD (perde eventos one-shot na fronteira do ciclo); marca d'água pelo maior timestamp observado (elimina a diferença de relógio, mas não a publicação tardia); `watch` com `resourceVersion` (mais robusto, porém mais complexo e fora do escopo do PRD).

### D4. Recência e contrato

`event_recency` lê o dict cru na ordem `series.lastObservedTime` → `eventTime` → `deprecatedLastTimestamp`, tratando ausência e `null` como "não presente". As strings da API (RFC 3339: `...Z` ou `...ssssssZ` em MicroTime) são convertidas para `datetime` com fuso UTC via `datetime.fromisoformat`. Um valor que não pode ser convertido conta como ausente. O `timestamp` do contrato é gerado com `.isoformat()` sobre esse `datetime`. `namespace` do contrato = `metadata.namespace`. `involved_object.namespace` = `regarding.namespace` ou `""`. Campos textuais ausentes (`reason`, `note`) viram `""`, para manter o contrato com `str`.

Na prática, os eventos do kubelet (BackOff, Unhealthy, FailedMount) chegam pelo recorder legado: `eventTime: null`, sem `series`, com `deprecatedLastTimestamp`. Os testes devem cobrir esse caminho como o principal, não como exceção.

### D5. Autenticação e configuração tardia

`load_k8s_config()` tenta `config.load_incluster_config()` e, se falhar, `config.load_kube_config()`. É chamado no início de cada ciclo enquanto ainda não houver sucesso. Assim, a falta de kubeconfig no startup não derruba a aplicação e o ciclo seguinte tenta de novo. Após o sucesso, o `ApiClient` é reutilizado.

### D6. Ciclo de vida e fire-and-forget

- `EventCollector.start()` cria a task do loop com `asyncio.create_task`. `stop()` a cancela e aguarda. Ambos são chamados no `lifespan` de `main.py`.
- O loop executa o ciclo e depois faz `asyncio.sleep(interval)`. A primeira iteração roda imediatamente.
- Despacho: `asyncio.create_task(self._safe_handle(batch))`, com referência guardada em um `set` e removida via `add_done_callback`. Sem isso, a task pode ser coletada pelo garbage collector durante a execução. `_safe_handle` captura e loga qualquer exceção do handler.
- No shutdown, as tasks do handler em andamento são canceladas. O PRD 002 já recupera relatórios EM_ANALISE órfãos no startup.

### D7. Tratamento de erros

- `ApiException` com status 403 → log de erro com a permissão necessária (`list` em `events.events.k8s.io`, cluster-wide).
- Demais `ApiException`, erros de conexão (`urllib3`) e falha de config → log de erro com a causa.
- Em qualquer falha do ciclo, a marca d'água não avança e o loop segue.

### D8. Testes

`pytest` + `pytest-asyncio` como dependências de dev (`uv add --dev`). Os testes unitários usam dicts no formato JSON da API `events.k8s.io/v1` e um `list_warning_events` falso injetado no `EventCollector`. O teste de integração com cluster real (ex.: kind) é manual e documentado, não roda por padrão.

## Risks / Trade-offs

- [Diferença de relógio maior que a margem (60 s)] → os eventos dessa faixa podem se perder. Mitigação: NTP no host. A margem é uma constante fácil de ajustar.
- [Restart esvazia o registro `sent`] → os eventos da janela inicial (≈ intervalo + margem) podem chegar de novo ao PRD 002, e os vinculados a CORRIGIDO/INCOMPLETO serão reanalisados. Aceito: janela pequena e escolha explícita do usuário.
- [Múltiplas instâncias/workers] → coleta e análise duplicadas. Premissa documentada: uma instância.
- [Volume alto sem paginação] → listagem grande em memória. Aceito no PRD. O filtro `type=Warning` no servidor reduz o volume.
- [Tasks do handler sem limite] → irrelevante com o placeholder. Fica como ponto de atenção para o PRD 002.

## Migration Plan

Mudança puramente aditiva. Para fazer o deploy, basta adicionar a dependência e, em cluster, aplicar a ClusterRole/Binding documentada. Rollback: remover a inicialização do coletor no `lifespan`.
