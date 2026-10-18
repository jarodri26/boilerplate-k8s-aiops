import json
import logging

from kubernetes import client, config

logger = logging.getLogger(__name__)


def load_k8s_config() -> None:
    """Carrega a config do cluster: in-cluster (ServiceAccount) com fallback para kubeconfig."""
    try:
        config.load_incluster_config()
        logger.info("Config Kubernetes carregada (in-cluster)")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Config Kubernetes carregada (kubeconfig)")


def list_warning_events() -> list[dict]:
    """Lista eventos Warning de todos os namespaces (events.k8s.io/v1) como dicts crus.

    A resposta nao e desserializada nos modelos do SDK: eles exigem eventTime nao nulo,
    o que quebra a lista inteira com eventos legados (eventTime: null). Ver design D2.
    """
    resp = client.EventsV1Api().list_event_for_all_namespaces(
        field_selector="type=Warning",
        _preload_content=False,
    )
    return json.loads(resp.data).get("items") or []
