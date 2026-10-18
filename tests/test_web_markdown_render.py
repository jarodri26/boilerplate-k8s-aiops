from markupsafe import Markup

from my_agent_app.web.markdown_render import render_markdown


def test_tabela_e_bloco_de_codigo():
    md = (
        "| Total | Criticos |\n|-------|----------|\n| 2     | 1        |\n\n"
        "```bash\nkubectl get pods -n prod\n```\n"
    )

    html = render_markdown(md)

    assert isinstance(html, Markup)
    assert "<table>" in html and "<td>2</td>" in html
    assert "<pre><code" in html and "kubectl get pods -n prod" in html


def test_titulos_listas_e_negrito():
    html = render_markdown("## Problema 1: x\n\n- **Severidade:** ALTO\n- item")

    assert "<h2>Problema 1: x</h2>" in html
    assert "<li><strong>Severidade:</strong> ALTO</li>" in html


def test_script_e_removido_e_texto_ao_redor_preservado():
    html = render_markdown("antes\n\n<script>alert(1)</script>\n\ndepois")

    assert "<script" not in html and "alert(1)" not in html
    assert "antes" in html and "depois" in html


def test_atributo_de_evento_e_removido():
    html = render_markdown('<img src="x" onerror="alert(1)"> texto')

    assert "onerror" not in html
    assert "texto" in html


def test_link_javascript_e_removido():
    html = render_markdown("[clique](javascript:alert(1)) e [ok](https://example.com)")

    assert "javascript:" not in html
    assert 'href="https://example.com"' in html
    assert "clique" in html


def test_markdown_malformado_nao_levanta_excecao():
    html = render_markdown("**negrito sem fechar\n\n| a | b\n|--\n```sem fechar")

    assert "negrito sem fechar" in html


def test_texto_vazio():
    assert render_markdown("") == ""
