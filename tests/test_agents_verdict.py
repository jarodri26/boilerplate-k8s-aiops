import logging

import pytest

from my_agent_app.agents.verdict import parse_verdict
from my_agent_app.models.report import ReportStatus

CORRIGIDO = ReportStatus.CORRIGIDO
FALHA = ReportStatus.FALHA_CORRECAO


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CORRIGIDO: imagem atualizada\n\n## Acoes Executadas", CORRIGIDO),
        ("FALHA: pod continua em CrashLoopBackOff", FALHA),
        ("Revisei o deployment e apliquei o patch.\n\nCORRIGIDO: imagem atualizada", CORRIGIDO),
        ("**FALHA:** pod continua em CrashLoopBackOff", FALHA),
        ("- **CORRIGIDO**: tag trocada para v8", CORRIGIDO),
        ("## CORRIGIDO: tag trocada", CORRIGIDO),
        ("> CORRIGIDO: tag trocada", CORRIGIDO),
        ("  CORRIGIDO: com indentacao", CORRIGIDO),
    ],
)
def test_veredito_reconhecido(text, expected):
    assert parse_verdict(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "O recurso foi marcado como CORRIGIDO: imagem atualizada",  # meio da frase
        "corrigido: em minusculas nao vale",
        "CORRIGIDOS: plural nao e o token",
        "Sem veredito nenhum",
    ],
)
def test_sem_veredito_vira_falha_com_warning(caplog, text):
    with caplog.at_level(logging.WARNING):
        assert parse_verdict(text) == FALHA
    assert "sem veredito" in caplog.text


def test_veredito_ambiguo_vira_falha(caplog):
    text = "- CORRIGIDO: [resumo de uma linha]\n- FALHA: [resumo de uma linha]"
    with caplog.at_level(logging.WARNING):
        assert parse_verdict(text) == FALHA
    assert "CORRIGIDO e FALHA" in caplog.text


def test_none_vira_falha():
    assert parse_verdict(None) == FALHA
