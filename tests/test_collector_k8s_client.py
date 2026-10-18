import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kubernetes import config

from my_agent_app.collector import k8s_client


def test_list_warning_events_usa_field_selector_e_json_cru(monkeypatch):
    payload = {
        "kind": "EventList",
        "items": [
            {
                "metadata": {"uid": "u1", "namespace": "prod"},
                "type": "Warning",
                "eventTime": None,
                "deprecatedLastTimestamp": "2026-10-18T10:00:00Z",
            }
        ],
    }
    api = MagicMock()
    api.list_event_for_all_namespaces.return_value = SimpleNamespace(data=json.dumps(payload).encode())
    monkeypatch.setattr(k8s_client.client, "EventsV1Api", lambda: api)

    items = k8s_client.list_warning_events()

    api.list_event_for_all_namespaces.assert_called_once_with(
        field_selector="type=Warning", _preload_content=False
    )
    assert items == payload["items"]
    assert items[0]["eventTime"] is None


def test_list_warning_events_lista_vazia(monkeypatch):
    api = MagicMock()
    api.list_event_for_all_namespaces.return_value = SimpleNamespace(data=b'{"items": null}')
    monkeypatch.setattr(k8s_client.client, "EventsV1Api", lambda: api)
    assert k8s_client.list_warning_events() == []


def test_load_config_prefere_in_cluster(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "load_incluster_config", lambda: calls.append("incluster"))
    monkeypatch.setattr(config, "load_kube_config", lambda: calls.append("kubeconfig"))
    k8s_client.load_k8s_config()
    assert calls == ["incluster"]


def test_load_config_fallback_para_kubeconfig(monkeypatch):
    calls = []

    def incluster():
        calls.append("incluster")
        raise config.ConfigException("fora do cluster")

    monkeypatch.setattr(config, "load_incluster_config", incluster)
    monkeypatch.setattr(config, "load_kube_config", lambda: calls.append("kubeconfig"))
    k8s_client.load_k8s_config()
    assert calls == ["incluster", "kubeconfig"]


def test_load_config_sem_nenhuma_config_propaga_erro(monkeypatch):
    def fail():
        raise config.ConfigException("sem config")

    monkeypatch.setattr(config, "load_incluster_config", fail)
    monkeypatch.setattr(config, "load_kube_config", fail)
    with pytest.raises(config.ConfigException):
        k8s_client.load_k8s_config()
