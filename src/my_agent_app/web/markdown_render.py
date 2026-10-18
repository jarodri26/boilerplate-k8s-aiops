"""Markdown -> HTML sanitizado para exibir os relatorios (PRD 003).

O conteudo vem do LLM, que leu logs e eventos do cluster (texto controlavel por
workloads), e a biblioteca `markdown` repassa HTML cru. Toda saida passa pelo `nh3`.
"""

import markdown
import nh3
from markupsafe import Markup

MARKDOWN_EXTENSIONS = ["tables", "fenced_code"]


def render_markdown(text: str) -> Markup:
    html = markdown.markdown(text or "", extensions=MARKDOWN_EXTENSIONS)
    return Markup(nh3.clean(html))
