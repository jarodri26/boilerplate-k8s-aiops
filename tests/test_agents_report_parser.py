import pytest

from my_agent_app.agents.report_parser import parse_problems

RESPOSTA = """# Relatorio de Diagnostico Kubernetes

## Resumo
| Total | Criticos | Altos | Medios | Baixos |
|-------|----------|-------|--------|--------|
| 2     | 1        | 1     | 0      | 0      |

---

## Problema 1: Imagem inexistente no deployment api
- **Severidade:** CRITICO
- **Namespace:** prod
- **Recursos Afetados:** pod/api-1, deployment/api
- **Eventos:** u1, u2

### Causa Raiz
A tag `v9` da imagem nao existe no registry.

### Evidencias
- ErrImagePull no describe do pod

### Solucao Recomendada
Corrigir a tag da imagem.

### Comando Sugerido
kubectl patch deployment api -n prod --type=merge -p '{"spec":{}}'

---

## Problema 2: OOMKilled no worker
- **Severidade:** ALTO
- **Namespace:** jobs
- **Recursos Afetados:** pod/worker-0
- **Eventos:** u3

### Causa Raiz
Limite de memoria de 128Mi abaixo do consumo do processo.

### Evidencias
- lastState.terminated.reason=OOMKilled

### Solucao Recomendada
Aumentar o limite de memoria.

### Comando Sugerido
kubectl set resources deployment worker -n jobs --limits=memory=512Mi
"""


def _secao(titulo="Problema 1: x", severidade="ALTO", eventos="u1", causa="Algo concreto."):
    return (
        f"## {titulo}\n- **Severidade:** {severidade}\n- **Eventos:** {eventos}\n\n"
        f"### Causa Raiz\n{causa}\n\n### Evidencias\n- e1\n"
    )


# --- 4.1 secoes, uids e warnings ---------------------------------------------------


def test_dois_problemas_geram_dois_relatorios():
    result = parse_problems(RESPOSTA, ["u1", "u2", "u3"])

    assert [p.event_uids for p in result.problems] == [["u1", "u2"], ["u3"]]
    assert [p.severity for p in result.problems] == ["CRITICO", "ALTO"]
    assert [p.status for p in result.problems] == ["COMPLETO", "COMPLETO"]
    assert result.warnings == []


def test_markdown_contem_apenas_a_secao_do_problema():
    p1, p2 = parse_problems(RESPOSTA, ["u1", "u2", "u3"]).problems

    assert p1.markdown.startswith("## Problema 1: Imagem inexistente")
    assert "Resumo" not in p1.markdown and "Problema 2" not in p1.markdown
    assert not p1.markdown.rstrip().endswith("---")
    assert "kubectl patch deployment api" in p1.markdown
    assert p2.markdown.startswith("## Problema 2: OOMKilled")
    assert p2.markdown.endswith("--limits=memory=512Mi")


def test_uid_fora_do_batch_e_ignorado():
    result = parse_problems(_secao(eventos="u1, intruso"), ["u1"])

    assert result.problems[0].event_uids == ["u1"]


def test_uid_em_duas_secoes_fica_na_primeira():
    md = _secao("Problema 1: a", eventos="u1, u2") + _secao("Problema 2: b", eventos="u2, u3")

    result = parse_problems(md, ["u1", "u2", "u3"])

    assert [p.event_uids for p in result.problems] == [["u1", "u2"], ["u3"]]
    assert any("u2" in w and "mais de um problema" in w for w in result.warnings)


def test_secao_sem_uid_do_batch_e_descartada():
    md = _secao("Problema 1: a", eventos="u1") + _secao("Problema 2: b", eventos="desconhecido")

    result = parse_problems(md, ["u1"])

    assert len(result.problems) == 1
    assert any("Problema 2: b" in w for w in result.warnings)


def test_uid_nao_referenciado_gera_warning():
    result = parse_problems(_secao(eventos="u1"), ["u1", "u2"])

    assert result.warnings == ["evento u2 nao referenciado em nenhum problema"]


@pytest.mark.parametrize(
    "md",
    ["", "   ", "Nao consegui investigar.", "# Relatorio\n\n## Resumo\n| 0 |"],
)
def test_resposta_sem_secoes_devolve_lista_vazia(md):
    result = parse_problems(md, ["u1"])

    assert result.problems == []


# --- 4.2 status e normalizacao ------------------------------------------------------


def test_severidade_valida_e_causa_descritiva_e_completo():
    (p,) = parse_problems(_secao(severidade="ALTO"), ["u1"]).problems

    assert (p.status, p.severity) == ("COMPLETO", "ALTO")


@pytest.mark.parametrize(
    "causa", ["Inconclusiva: limite de investigacao atingido", "Causa INCONCLUSIVO."]
)
def test_causa_inconclusiva_e_incompleto(causa):
    (p,) = parse_problems(_secao(causa=causa), ["u1"]).problems

    assert p.status == "INCOMPLETO"


def test_causa_vazia_e_incompleto():
    md = "## Problema 1: x\n- **Severidade:** ALTO\n- **Eventos:** u1\n\n### Causa Raiz\n\n### Evidencias\n- e\n"

    (p,) = parse_problems(md, ["u1"]).problems

    assert p.status == "INCOMPLETO"


@pytest.mark.parametrize("severidade", ["URGENTE", ""])
def test_severidade_invalida_e_incompleto_sem_severidade(severidade):
    (p,) = parse_problems(_secao(severidade=severidade), ["u1"]).problems

    assert (p.status, p.severity) == ("INCOMPLETO", None)


def test_severidade_ausente_e_incompleto():
    md = "## Problema 1: x\n- **Eventos:** u1\n\n### Causa Raiz\nAlgo.\n"

    (p,) = parse_problems(md, ["u1"]).problems

    assert (p.status, p.severity) == ("INCOMPLETO", None)


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [("MÉDIO", "MEDIO"), ("CRÍTICO", "CRITICO"), ("baixo", "BAIXO"), ("ALTO | MEDIO", "ALTO")],
)
def test_severidade_normalizada(bruto, esperado):
    (p,) = parse_problems(_secao(severidade=bruto), ["u1"]).problems

    assert p.severity == esperado


def test_uids_entre_crases_e_separadores_variados():
    uid1 = "3f1c2a9e-0b7d-4c55-9d2e-6a1b8c7d9e01"
    uid2 = "a8e7d6c5-b4a3-4921-8f7e-6d5c4b3a2918"

    (p,) = parse_problems(_secao(eventos=f"`{uid1}`;  `{uid2}`."), [uid1, uid2]).problems

    assert p.event_uids == [uid1, uid2]


# --- robustez-agente-analise: fim da secao -------------------------------------------

RESPOSTA_COM_RESUMO_FINAL = """## Resumo
| Total | Criticos |
|-------|----------|
| 2     | 2        |

---

## Problema 1: Imagem inexistente
- **Severidade:** CRITICO
- **Eventos:** u1

### Causa Raiz
Tag inexistente.

---

## Problema 2: Registry invalido
- **Severidade:** CRITICO
- **Eventos:** u2

### Causa Raiz
Registry nao resolve.

### Comando Sugerido
```bash
## comentario com dois cerquilhas dentro do bloco
kubectl set image deployment/web web=nginx:1.27 -n prod
```

---

## Resumo de Acoes Recomendadas

| Problema | Acao |
|----------|------|
| web-imagem | Usar tag valida |
"""


def test_titulo_de_nivel_2_apos_o_ultimo_problema_nao_entra_no_relatorio():
    result = parse_problems(RESPOSTA_COM_RESUMO_FINAL, ["u1", "u2"])

    primeiro, ultimo = (p.markdown for p in result.problems)
    assert "Resumo de Acoes Recomendadas" not in ultimo and "web-imagem" not in ultimo
    assert ultimo.endswith("```")
    assert "### Comando Sugerido" in ultimo
    assert "## comentario com dois cerquilhas dentro do bloco" in ultimo
    assert "| Total |" not in primeiro and primeiro.startswith("## Problema 1")
    assert primeiro.endswith("Tag inexistente.")
