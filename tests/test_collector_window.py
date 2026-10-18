import logging
from datetime import datetime, timedelta, timezone

from my_agent_app.collector.window import CollectionWindow

START = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
INTERVAL = timedelta(minutes=3)


def at(**delta) -> datetime:
    return START + timedelta(**delta)


def make_event(uid: str, ts: datetime | None) -> dict:
    return {
        "metadata": {"uid": uid, "namespace": "prod"},
        "type": "Warning",
        "reason": "BackOff",
        "note": "msg",
        "regarding": {"kind": "Pod", "name": "p", "namespace": "prod"},
        "eventTime": None,
        "deprecatedLastTimestamp": ts.isoformat() if ts else None,
    }


def uids(selection) -> list[str]:
    return [e["uid"] for e in selection.events]


def test_primeira_janela_e_intervalo_mais_margem():
    window = CollectionWindow(START, INTERVAL)
    sel = window.select([
        make_event("dentro", at(minutes=-3, seconds=-30)),
        make_event("fora", at(minutes=-4, seconds=-1)),
    ])
    assert uids(sel) == ["dentro"]


def test_evento_publicado_atrasado_dentro_da_margem_e_coletado():
    window = CollectionWindow(START, INTERVAL)
    window.commit(START, window.select([]))
    # recencia 10s anterior a marca d'agua, so visivel no ciclo seguinte
    sel = window.select([make_event("atrasado", at(seconds=-10))])
    assert uids(sel) == ["atrasado"]


def test_evento_antigo_fora_da_janela_nao_e_entregue():
    window = CollectionWindow(START, INTERVAL)
    window.commit(START, window.select([]))
    sel = window.select([make_event("antigo", at(seconds=-61))])
    assert uids(sel) == []


def test_mesmo_uid_mesma_recencia_nao_reenvia():
    window = CollectionWindow(START, INTERVAL)
    ev = make_event("u1", at(seconds=-30))
    window.commit(START, window.select([ev]))
    assert uids(window.select([ev])) == []


def test_mesmo_uid_recencia_maior_reenvia():
    window = CollectionWindow(START, INTERVAL)
    window.commit(START, window.select([make_event("u1", at(seconds=-30))]))
    sel = window.select([make_event("u1", at(minutes=2))])
    assert uids(sel) == ["u1"]
    assert sel.events[0]["timestamp"] == at(minutes=2).isoformat()


def test_evento_sem_timestamp_descartado_com_warning(caplog):
    window = CollectionWindow(START, INTERVAL)
    with caplog.at_level(logging.WARNING):
        sel = window.select([make_event("sem-ts", None)])
    assert uids(sel) == []
    assert "sem-ts" in caplog.text


def test_commit_poda_entradas_fora_da_janela():
    window = CollectionWindow(START, INTERVAL)
    window.commit(START, window.select([
        make_event("velho", at(minutes=-3)),
        make_event("novo", at(seconds=-5)),
    ]))
    assert set(window.sent) == {"novo"}
    window.commit(at(minutes=3), window.select([]))
    assert window.sent == {}


def test_sem_commit_marca_dagua_e_registro_inalterados():
    window = CollectionWindow(START, INTERVAL)
    watermark = window.watermark
    window.select([make_event("u1", at(seconds=-30))])
    assert window.watermark == watermark
    assert window.sent == {}
