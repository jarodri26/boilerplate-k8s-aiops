import json

from my_agent_app.agents.prompt import ANALYSIS_PROMPT, render_prompt

EVENTS = [
    {"uid": "u-123", "reason": "BackOff", "message": "Back-off restarting"},
    {"uid": "u-456", "reason": "FailedScheduling", "message": "0/3 nodes disponíveis"},
]


def test_eventos_aparecem_no_prompt_como_json():
    prompt = render_prompt(EVENTS)

    assert "{events}" not in prompt
    assert json.dumps(EVENTS, ensure_ascii=False, indent=2) in prompt
    assert "u-123" in prompt and "u-456" in prompt
    assert "disponíveis" in prompt  # sem escape \\u


def test_chaves_literais_do_prompt_permanecem():
    prompt = render_prompt(EVENTS)

    assert """-p '{"spec":...}'""" in prompt
    assert prompt.count("## REGRAS") == 1


def test_prompt_traz_as_regras_do_prd():
    assert "NUNCA execute kubectl_patch, kubectl_apply ou kubectl_delete" in ANALYSIS_PROMPT
    assert "liste o uid de CADA evento recebido em exatamente um problema" in ANALYSIS_PROMPT
    assert ANALYSIS_PROMPT.rstrip().endswith("Responda APENAS com o relatorio markdown.")
