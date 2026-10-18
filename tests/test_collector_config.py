import logging

import pytest

from my_agent_app.collector.config import get_collection_interval_seconds

ENV = "EVENT_COLLECTION_INTERVAL_MINUTES"


def test_ausente_usa_padrao(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert get_collection_interval_seconds() == 180


@pytest.mark.parametrize(("raw", "expected"), [("5", 300), ("0.5", 30)])
def test_valor_valido(monkeypatch, raw, expected):
    monkeypatch.setenv(ENV, raw)
    assert get_collection_interval_seconds() == expected


@pytest.mark.parametrize("raw", ["abc", "0", "-2", "nan", "inf"])
def test_valor_invalido_usa_padrao_com_warning(monkeypatch, caplog, raw):
    monkeypatch.setenv(ENV, raw)
    with caplog.at_level(logging.WARNING):
        assert get_collection_interval_seconds() == 180
    assert ENV in caplog.text
