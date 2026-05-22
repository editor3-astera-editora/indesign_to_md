"""Sincroniza as entradas do sumário com os títulos de capítulo traduzidos.

Passo determinístico pós-tradução (sem custo de API): o título traduzido no
**corpo** do livro (estilos de título de capítulo) é a fonte da verdade; cada
entrada correspondente no **sumário** é reescrita para ficar idêntica a ele,
preservando o sufixo de página (``\\t<página>``).

Motivação: o pipeline traduz cada Segment isoladamente, sem deduplicar por texto
(ver ``openai_client.translate_segments``). A LLM pode então traduzir o mesmo
título de formas diferentes no corpo (``Títulos:T1``) e no sumário
(``Sumario:Item 1``), deixando os dois divergentes. Como o sumário deste tipo de
livro é manual e copia o texto do título verbatim, casamos pelo texto-FONTE
(PT→PT — confiável) e forçamos a consistência usando a tradução do corpo.

Granularidade: um único parágrafo ``Sumario:Item 1`` empacota vários capítulos,
cada um num ``<HyperlinkTextSource>`` separado por ``<Br/>`` — ou seja, vários
runs por Segment. A reescrita é feita **por run**.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from idml_to_md.translation.models import Segment, SegmentBoundary, SegmentRun, Translation

# Sufixo de página numa entrada de sumário: um ou mais TABs seguidos do número
# da página (com possíveis pontos/espaços de leaders). Capturado do texto-FONTE
# para ser reaplicado intacto após a tradução (a página nunca muda PT→ES).
_PAGE_SUFFIX_RE = re.compile(r"(?P<suffix>\t+[\d.\s]*\d\s*)$")

# Avisos da LLM que indicam tradução inválida — uma entrada assim NÃO deve
# sobrescrever o sumário (evita propagar o texto PT original para o sumário).
_FAILED_WARNING_MARKERS = ("batch_failed", "missing in response")


@dataclass(slots=True)
class TocSyncReport:
    """Resultado da sincronização sumário↔títulos de capítulo."""

    synced: int = 0
    unmatched_toc_titles: list[str] = field(default_factory=list)
    conflicting_headings: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        """Avisos legíveis para o relatório de auditoria."""
        msgs: list[str] = []
        for t in self.unmatched_toc_titles:
            msgs.append(f"sumário: entrada sem título de capítulo correspondente: {t!r}")
        for t in self.conflicting_headings:
            msgs.append(
                f"título de capítulo duplicado com traduções divergentes: {t!r}"
            )
        return msgs


def sync_toc_with_headings(
    segments: list[Segment],
    translations: list[Translation],
    *,
    chapter_title_styles: Iterable[str],
    toc_entry_styles: Iterable[str],
) -> TocSyncReport:
    """Reescreve as entradas do sumário para casarem os títulos de capítulo.

    Muta ``translations`` in place (apenas o ``.text`` dos ``target_runs`` das
    entradas de sumário casadas) e retorna um :class:`TocSyncReport`.

    Args:
        segments: todos os segmentos extraídos (fornecem texto-FONTE e estilo).
        translations: traduções produzidas (fornecem o texto traduzido e são
            mutadas no lugar).
        chapter_title_styles: nomes normalizados de ``ParagraphStyle`` que são
            título de capítulo (fonte canônica) — ex.: ``Títulos:T1``.
        toc_entry_styles: nomes normalizados de ``ParagraphStyle`` das entradas
            de sumário a sincronizar — ex.: ``Sumario:Item 1``.
    """
    report = TocSyncReport()
    chapter_styles = {s for s in chapter_title_styles if s}
    toc_styles = {s for s in toc_entry_styles if s}
    if not chapter_styles or not toc_styles:
        return report  # feature desligada (lista vazia de um dos lados)

    trans_by_id = {t.segment_id: t for t in translations}

    title_map = _build_title_map(segments, trans_by_id, chapter_styles, report)
    if not title_map:
        return report

    _rewrite_toc_entries(segments, trans_by_id, toc_styles, title_map, report)
    return report


def _build_title_map(
    segments: list[Segment],
    trans_by_id: dict[str, Translation],
    chapter_styles: set[str],
    report: TocSyncReport,
) -> dict[str, str]:
    """Mapa título-de-capítulo (PT normalizado) → texto traduzido canônico.

    Conflitos (mesmo título-fonte com traduções divergentes) são registrados no
    relatório; o primeiro vence, deterministicamente.
    """
    title_map: dict[str, str] = {}
    conflicts: set[str] = set()

    for seg in segments:
        if seg.paragraph_style not in chapter_styles:
            continue
        trans = trans_by_id.get(seg.segment_id)
        if trans is None or _translation_failed(trans):
            continue
        source_key = _normalize(_join_runs(seg.runs, seg.boundaries))
        if not source_key:
            continue
        canonical = _normalize(_join_runs(trans.target_runs, seg.boundaries))
        if not canonical:
            continue
        existing = title_map.get(source_key)
        if existing is not None and existing != canonical:
            conflicts.add(source_key)
            continue  # mantém o primeiro
        title_map.setdefault(source_key, canonical)

    report.conflicting_headings = sorted(conflicts)
    return title_map


def _rewrite_toc_entries(
    segments: list[Segment],
    trans_by_id: dict[str, Translation],
    toc_styles: set[str],
    title_map: dict[str, str],
    report: TocSyncReport,
) -> None:
    """Para cada ENTRADA de sumário casada, força o texto traduzido do corpo.

    Uma entrada pode abranger VÁRIOS runs (o título às vezes é partido em mais de
    um ``<Content>``/CSR — ex.: "Mundo do " + "trabalho \\t59"). Por isso os runs
    são agrupados em entradas pelo terminador ``\\t<página>`` e pelas quebras
    ``<Br/>`` antes de casar. O texto canônico + sufixo vai no primeiro run da
    entrada; os demais runs da entrada são esvaziados.
    """
    for seg in segments:
        if seg.paragraph_style not in toc_styles:
            continue
        trans = trans_by_id.get(seg.segment_id)
        if trans is None or not trans.target_runs:
            continue
        n = len(trans.target_runs)

        for indices, title, suffix in _group_runs_into_entries(seg.runs, seg.boundaries):
            if indices[-1] >= n:  # target_runs desalinhado — não arrisca
                continue
            key = _normalize(title)
            if not key:
                continue  # entrada vazia / só leaders → não é título de capítulo
            canonical = title_map.get(key)
            if canonical is None:
                report.unmatched_toc_titles.append(key)
                continue
            _set_entry_text(trans, indices, canonical + suffix)
            report.synced += 1


def _group_runs_into_entries(
    runs: list[SegmentRun], boundaries: list[SegmentBoundary]
) -> list[tuple[list[int], str, str]]:
    """Agrupa os runs de um parágrafo de sumário em entradas (1 por capítulo).

    Cada entrada termina num run cujo texto acaba em ``\\t<página>`` ou numa
    fronteira ``<Br/>`` logo após o run. Retorna ``(índices, título, sufixo)``:
    ``índices`` posições dos runs da entrada (na ordem da lista), ``título`` o
    texto concatenado sem a página, ``sufixo`` o ``\\t<página>`` (ou ``""``).
    """
    br_after = {b.after_text_ord for b in boundaries if b.kind == "br"}
    entries: list[tuple[list[int], str, str]] = []
    cur_idx: list[int] = []
    cur_text: list[str] = []
    cur_suffix = ""

    for i, run in enumerate(runs):
        title_part, suffix = _split_page_suffix(run.text)
        cur_idx.append(i)
        cur_text.append(title_part)
        if suffix:
            cur_suffix = suffix
        if suffix or i in br_after:
            entries.append((cur_idx, "".join(cur_text), cur_suffix))
            cur_idx, cur_text, cur_suffix = [], [], ""

    if cur_idx:
        entries.append((cur_idx, "".join(cur_text), cur_suffix))
    return entries


def _set_entry_text(trans: Translation, indices: list[int], text: str) -> None:
    """Põe ``text`` no primeiro run da entrada e esvazia os demais."""
    first = indices[0]
    if trans.target_runs[first].text != text:
        trans.target_runs[first] = trans.target_runs[first].model_copy(
            update={"text": text}
        )
    for j in indices[1:]:
        if trans.target_runs[j].text != "":
            trans.target_runs[j] = trans.target_runs[j].model_copy(update={"text": ""})


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _translation_failed(trans: Translation) -> bool:
    """True quando a tradução do título não é confiável (não usar como canônica)."""
    if any(marker in w for w in trans.warnings for marker in _FAILED_WARNING_MARKERS):
        return True
    # Sem texto algum traduzido também é falha.
    return not trans.target_text.strip() and not any(
        r.text.strip() for r in trans.target_runs
    )


def _split_page_suffix(text: str) -> tuple[str, str]:
    """Separa ``"Título\\t7"`` em ``("Título", "\\t7")``; sem página → ``(text, "")``."""
    match = _PAGE_SUFFIX_RE.search(text)
    if match is None:
        return text, ""
    return text[: match.start()], match.group("suffix")


def _join_runs(runs: list[SegmentRun], boundaries: list[SegmentBoundary]) -> str:
    """Concatena os textos dos runs inserindo um espaço em cada fronteira ``br``.

    As ``boundaries`` (do Segment-FONTE) registram, por ``after_text_ord``, o
    índice do run que cada quebra segue. ``target_runs`` preserva a mesma
    ordem/quantidade de runs, então as mesmas fronteiras valem para os dois.
    """
    br_after = {b.after_text_ord for b in boundaries if b.kind == "br"}
    parts: list[str] = []
    for i, run in enumerate(runs):
        parts.append(run.text)
        if i in br_after:
            parts.append(" ")
    return "".join(parts)


def _normalize(text: str) -> str:
    """Normaliza para casamento/saída: NFC, espaços colapsados, ``strip``.

    Preserva maiúsculas/minúsculas e acentos (NFC) — só uniformiza espaços em
    branco (inclui o espaço inserido nas quebras ``<Br/>``).
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()
