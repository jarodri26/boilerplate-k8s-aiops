from my_agent_app.agents.correction_prompt import CORRECTION_PROMPT, render_correction_prompt

REPORT = """## Problema 1: Imagem inexistente
- **Severidade:** CRITICO

### Comando Sugerido
kubectl patch deployment api -n prod --type=merge -p '{"spec":{"replicas":2}}'
"""


def test_markdown_do_relatorio_aparece_intacto():
    prompt = render_correction_prompt(REPORT)

    assert "{report_markdown}" not in prompt
    assert REPORT in prompt
    assert """-p '{"spec":{"replicas":2}}'""" in prompt


def test_prompt_traz_as_regras_e_o_formato_do_prd():
    assert CORRECTION_PROMPT.count("{report_markdown}") == 1
    assert "NUNCA use merge patch simples sobre a lista `containers`" in CORRECTION_PROMPT
    assert "NUNCA delete namespaces, PersistentVolumeClaims ou recursos em kube-system." in CORRECTION_PROMPT
    assert "- CORRIGIDO: [resumo de uma linha]" in CORRECTION_PROMPT
    assert CORRECTION_PROMPT.rstrip().endswith("- Total: X")
