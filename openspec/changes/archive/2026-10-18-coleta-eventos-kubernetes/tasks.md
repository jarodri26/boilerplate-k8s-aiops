# Tasks

## 1. Setup

- [x] 1.1 Adicionar a dependência `kubernetes` (`uv add kubernetes`) e verificar que `uv run python -c "from kubernetes.client import EventsV1Api"` executa sem erro
- [x] 1.2 Adicionar `pytest` e `pytest-asyncio` como dependências de dev (`uv add --dev`), configurar `[tool.pytest.ini_options]` no `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`), criar `tests/` e verificar que `uv run pytest` executa (0 testes coletados sem erro)

## 2. Configuração do intervalo

- [x] 2.1 Criar `collector/config.py` com `get_collection_interval_seconds()` (lê `EVENT_COLLECTION_INTERVAL_MINUTES`, aceita inteiro/fracionário positivo, padrão 3, warning em valor inválido) e verificar com testes cobrindo ausente, `5`, `0.5`, `abc`, `0` e `-2`
- [x] 2.2 Documentar `EVENT_COLLECTION_INTERVAL_MINUTES` em `.env.example`, na tabela de env vars do `CLAUDE.md` e no `README.md`, e verificar que as três referências citam o padrão de 3 minutos

## 3. Transformação e recência

- [x] 3.1 Criar `collector/transform.py` com `event_recency(ev: dict)` sobre o JSON cru da API (precedência `series.lastObservedTime` → `eventTime` → `deprecatedLastTimestamp`, `null`/ausente/inválido = não presente, strings RFC 3339 convertidas para `datetime` UTC, `None` se nenhum) e verificar com testes para: evento com series e `event_time` antigo, evento só com `event_time`, evento legado só com `deprecated_last_timestamp` e evento sem timestamp
- [x] 3.2 Implementar `to_contract(ev: dict, recency)` sobre o JSON cru, mapeando `note` → `message` e `regarding` → `involved_object`, com `""` para `regarding.namespace` ausente e campos textuais nulos, e `timestamp` em ISO 8601. Verificar com testes do contrato completo (chaves e tipos), de um evento de `Node` cluster-scoped e de um evento legado

## 4. Janela de coleta e registro de UIDs

- [x] 4.1 Criar `collector/window.py` com `CollectionWindow` (marca d'água inicial `start − interval`, `MARGIN = 60s`, método que filtra eventos pela janela e pelo registro `uid → recência`, `commit(t0)` que avança a marca d'água e poda o registro). Verificar com testes para: evento dentro e fora da janela, evento publicado atrasado dentro da margem, mesmo uid com mesma recência (não reenvia), mesmo uid com recência maior (reenvia), descarte com warning de evento sem timestamp, poda de entradas antigas e marca d'água inalterada sem `commit`

## 5. Cliente Kubernetes e handler

- [x] 5.1 Criar `collector/k8s_client.py` com `load_k8s_config()` (in-cluster com fallback para kubeconfig) e `list_warning_events()` usando `EventsV1Api.list_event_for_all_namespaces(field_selector="type=Warning", _preload_content=False)` e retornando `json.loads(resp.data)["items"]` (dicts crus, ver design D2), e verificar com teste que usa mock do SDK e confere o `field_selector`, o `_preload_content=False`, que um item com `eventTime: null` é retornado sem erro e a ordem do fallback
- [x] 5.2 Criar `collector/handler.py` com `EventHandler.handle(events: list[dict]) -> None` assíncrono que imprime os eventos no stdout, e verificar com teste usando `capsys`

## 6. Loop de coleta

- [x] 6.1 Criar `collector/loop.py` com `EventCollector` (`start()`, `stop()`, `run_cycle()`): primeira coleta imediata, `asyncio.to_thread` na listagem, `t0` capturado antes da chamada, carregamento tardio da config K8s, despacho fire-and-forget com referência das tasks guardada e `_safe_handle` capturando exceções. Verificar com testes usando uma função de listagem falsa: primeira coleta antes do primeiro sleep, batch vazio não aciona o handler, batch entregue como lista única, ciclo seguinte não espera um handler lento e exceção do handler é logada sem parar o loop
- [x] 6.2 Implementar o tratamento de erros do ciclo (403 com mensagem da permissão necessária, demais `ApiException`, erro de conexão e falha de config) sem avançar a marca d'água, e verificar com testes que simulam cada erro e conferem o log, a marca d'água inalterada e a continuidade do loop
- [x] 6.3 Integrar `EventCollector` ao `lifespan` em `main.py` (start após o engine, stop antes do `dispose`) e verificar que `uv run uvicorn my_agent_app.main:app` sobe sem kubeconfig (erro logado, `/api/health` responde 200) e encerra sem tracebacks

## 7. RBAC e verificação integrada

- [x] 7.1 Documentar no `README.md` a ClusterRole/ClusterRoleBinding mínima (`list` em `events.events.k8s.io`, cluster-wide) para execução in-cluster e verificar o YAML com `kubectl apply --dry-run=client -f -`
- [x] 7.2 Verificação manual com cluster real (ex.: kind ou o cluster do kubeconfig): aplicar `manifestos-k8s/` ou um pod com imagem inexistente para gerar Warnings, subir a aplicação com `EVENT_COLLECTION_INTERVAL_MINUTES=0.5` e confirmar no stdout a primeira coleta imediata, eventos `Warning` de mais de um namespace no formato do contrato e ausência de reenvio de eventos sem recorrência entre ciclos
