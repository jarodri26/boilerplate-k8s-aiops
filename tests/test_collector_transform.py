from datetime import datetime, timezone

from my_agent_app.collector.transform import event_recency, to_contract


def make_event(**overrides) -> dict:
    ev = {
        "metadata": {"uid": "uid-1", "namespace": "prod", "name": "api-1.abc"},
        "type": "Warning",
        "reason": "BackOff",
        "note": "Back-off restarting failed container",
        "regarding": {"kind": "Pod", "name": "api-1", "namespace": "prod"},
        "eventTime": None,
        "series": None,
        "deprecatedLastTimestamp": None,
    }
    ev.update(overrides)
    return ev


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_recencia_series_prevalece_sobre_event_time_antigo():
    ev = make_event(
        eventTime="2026-10-18T09:00:00.000000Z",
        series={"count": 5, "lastObservedTime": "2026-10-18T10:00:00.123456Z"},
    )
    assert event_recency(ev) == utc(2026, 10, 18, 10, 0, 0, 123456)


def test_recencia_so_event_time():
    ev = make_event(eventTime="2026-10-18T09:30:00.000000Z")
    assert event_recency(ev) == utc(2026, 10, 18, 9, 30)


def test_recencia_evento_legado_usa_deprecated_last_timestamp():
    ev = make_event(deprecatedLastTimestamp="2026-10-18T10:05:00Z")
    assert event_recency(ev) == utc(2026, 10, 18, 10, 5)


def test_recencia_sem_timestamp_retorna_none():
    assert event_recency(make_event()) is None


def test_recencia_campo_ausente_ou_invalido_e_ignorado():
    ev = {"deprecatedLastTimestamp": "2026-10-18T10:05:00Z", "eventTime": "lixo"}
    assert event_recency(ev) == utc(2026, 10, 18, 10, 5)


def test_contrato_completo():
    ts = utc(2026, 10, 18, 10, 5)
    result = to_contract(make_event(deprecatedLastTimestamp="2026-10-18T10:05:00Z"), ts)
    assert result == {
        "uid": "uid-1",
        "type": "Warning",
        "reason": "BackOff",
        "message": "Back-off restarting failed container",
        "namespace": "prod",
        "involved_object": {"kind": "Pod", "name": "api-1", "namespace": "prod"},
        "timestamp": "2026-10-18T10:05:00+00:00",
    }
    assert all(isinstance(v, str) for k, v in result.items() if k != "involved_object")
    assert all(isinstance(v, str) for v in result["involved_object"].values())


def test_contrato_recurso_cluster_scoped():
    ev = make_event(
        metadata={"uid": "uid-node", "namespace": "default"},
        regarding={"kind": "Node", "name": "worker-1"},
        reason="NodeNotReady",
    )
    result = to_contract(ev, utc(2026, 10, 18, 10, 0))
    assert result["involved_object"] == {"kind": "Node", "name": "worker-1", "namespace": ""}


def test_contrato_campos_textuais_nulos_viram_string_vazia():
    ev = make_event(reason=None, note=None)
    result = to_contract(ev, utc(2026, 10, 18, 10, 0))
    assert result["reason"] == ""
    assert result["message"] == ""
