"""Parse da resposta Markdown do agente em relatorios por problema (PRD 002, D1/D8).

Funcao pura: nao loga nem acessa banco; os avisos voltam em `ParseResult.warnings`.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from my_agent_app.models.report import ReportStatus, Severity

_SECTION_RE = re.compile(r"^##\s+Problema\b", re.IGNORECASE)
_H2_RE = re.compile(r"^##(?!#)\s")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SEVERITY_RE = re.compile(r"\*\*Severidade:?\*\*:?\s*([^\s|*]+)", re.IGNORECASE)
_EVENTS_RE = re.compile(r"\*\*Eventos:?\*\*:?\s*(.*)$", re.MULTILINE | re.IGNORECASE)
_ROOT_CAUSE_RE = re.compile(
    r"^###\s+Causa\s+Raiz\s*$(.*?)(?=^###\s|\Z)", re.MULTILINE | re.DOTALL | re.IGNORECASE
)
_UID_SPLIT_RE = re.compile(r"[,\s;]+")
_UID_STRIP = "`'\"[]()<>.:"


@dataclass
class ParsedProblem:
    markdown: str
    event_uids: list[str]
    severity: str | None
    status: str


@dataclass
class ParseResult:
    problems: list[ParsedProblem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _h2_headings(markdown: str) -> list[tuple[int, bool]]:
    """(offset, e_problema) de cada titulo de nivel 2 fora de blocos de codigo."""
    headings, offset, in_fence = [], 0, False
    for line in markdown.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence and _H2_RE.match(line):
            headings.append((offset, bool(_SECTION_RE.match(line))))
        offset += len(line)
    return headings


def _split_sections(markdown: str) -> list[str]:
    # a secao do problema termina no proximo titulo "## " de qualquer tipo: resumos
    # finais da resposta (ex.: "## Resumo de Acoes") nao entram no ultimo relatorio
    headings = _h2_headings(markdown)
    sections = []
    for i, (start, is_problem) in enumerate(headings):
        if not is_problem:
            continue
        end = headings[i + 1][0] if i + 1 < len(headings) else len(markdown)
        section = markdown[start:end].strip()
        # separadores horizontais entre secoes nao fazem parte do problema
        section = re.sub(r"(\n\s*-{3,}\s*)+$", "", section).strip()
        sections.append(section)
    return sections


def _parse_severity(section: str) -> str | None:
    match = _SEVERITY_RE.search(section)
    if not match:
        return None
    value = _strip_accents(match.group(1)).upper().strip(_UID_STRIP)
    return value if value in Severity.__members__ else None


def _parse_uids(section: str) -> list[str]:
    match = _EVENTS_RE.search(section)
    if not match:
        return []
    tokens = (t.strip(_UID_STRIP) for t in _UID_SPLIT_RE.split(match.group(1)))
    return [t for t in tokens if t]


def _root_cause(section: str) -> str:
    match = _ROOT_CAUSE_RE.search(section)
    return match.group(1).strip() if match else ""


def _status(severity: str | None, root_cause: str) -> str:
    conclusive = root_cause and "inconclusiv" not in root_cause.lower()
    return ReportStatus.COMPLETO if severity and conclusive else ReportStatus.INCOMPLETO


def parse_problems(markdown: str, batch_uids: Iterable[str]) -> ParseResult:
    batch = list(dict.fromkeys(batch_uids))
    batch_set = set(batch)
    result = ParseResult()
    assigned: set[str] = set()

    for section in _split_sections(markdown or ""):
        title = section.splitlines()[0].strip()
        uids = []
        for uid in _parse_uids(section):
            if uid not in batch_set:
                continue
            if uid in assigned:
                result.warnings.append(
                    f"uid {uid} citado em mais de um problema; mantido apenas no primeiro"
                )
                continue
            if uid not in uids:
                uids.append(uid)

        if not uids:
            result.warnings.append(f"secao sem nenhum uid do batch descartada: {title!r}")
            continue

        assigned.update(uids)
        severity = _parse_severity(section)
        result.problems.append(
            ParsedProblem(
                markdown=section,
                event_uids=uids,
                severity=severity,
                status=_status(severity, _root_cause(section)),
            )
        )

    if result.problems:
        for uid in batch:
            if uid not in assigned:
                result.warnings.append(f"evento {uid} nao referenciado em nenhum problema")

    return result
