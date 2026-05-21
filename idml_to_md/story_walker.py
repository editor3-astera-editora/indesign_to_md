"""Percorre cada Story XML emitindo o ``Document`` parcial (blocos).

Escopo F2 (cumulativo sobre F1):
- ``ParagraphStyleRange`` → Heading / Paragraph / ListItem / AdmonitionBlock /
  Blockquote / CodeBlock / Caption / FrontMatterBlock / ReferenceEntry / drop.
- ``CharacterStyleRange`` → run de texto com formatação inline (Bold/Italic/
  Sup/Sub via FontStyle ou CharacterStyle).
- ``<Content>`` e ``<Br/>``.
- ``AnchoredObject`` (Group/Rectangle dentro do fluxo):
  - Rectangle > Image > Link com raster → ``ImageBlock``.
  - Rectangle > Image > Link apontando para ``.eps`` MathType → extrai MathML,
    converte para LaTeX e emite como ``EquationBlock`` (display) ou TextRun
    com ``InlineKind.EQUATION_INLINE`` (inline) dependendo do contexto.
  - Outros (Polygon decorativo, ilustração vetorial) → silenciosamente ignorados.

Fora de escopo (F3): Tables, Footnotes, Hyperlinks ricos, caixas Polygon-based,
SVG via Inkscape para `.ai`/`.eps` ilustrativos.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from idml_to_md.anchored_resolver import AnchoredKind, classify_anchored
from idml_to_md.equation_extractor import (
    EquationExtractionError,
    extract_mathml,
)
from idml_to_md.mathml_to_latex import EquationConverter, MathMLConversionError
from idml_to_md.models import (
    AdmonitionBlock,
    Block,
    Blockquote,
    Caption,
    CodeBlock,
    EquationBlock,
    FrontMatterBlock,
    Heading,
    ImageBlock,
    Inline,
    LineBreak,
    ListBlock,
    ListItem,
    Paragraph,
    ReferenceEntry,
    TableBlock,
    TextRun,
)
from idml_to_md.models import (
    InlineKind as IK,
)
from idml_to_md.table_renderer import parse_table

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from lxml import etree

    from idml_to_md.style_mapper import StyleMap

# Caracteres especiais InDesign (control chars) com sentido semantico.
# Chaves intencionalmente sao LINE/PARAGRAPH SEPARATOR (U+2028/U+2029).
_SPECIAL_CHARS = {
    chr(0x2028): "\n",  # LINE SEPARATOR
    chr(0x2029): "\n\n",  # PARAGRAPH SEPARATOR
    chr(0x00AD): "",  # SOFT HYPHEN
    chr(0xFEFF): "",  # BOM
}
_SPECIAL_CHARS_RE = re.compile("|".join(re.escape(c) for c in _SPECIAL_CHARS))


def _clean_content(text: str) -> str:
    """Normaliza caracteres especiais e colapsa espaços invisíveis."""
    if not text:
        return ""
    return _SPECIAL_CHARS_RE.sub(lambda m: _SPECIAL_CHARS[m.group(0)], text)


@dataclass(slots=True)
class WalkResult:
    """Resultado de percorrer uma Story: blocos do corpo + front matter + refs."""

    body: list[Block] = field(default_factory=list)
    front_matter: list[Block] = field(default_factory=list)
    references: list[ReferenceEntry] = field(default_factory=list)
    image_basenames: list[str] = field(default_factory=list)
    vector_basenames: list[str] = field(default_factory=list)
    equation_basenames: list[str] = field(default_factory=list)
    failed_equations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tipos internos para coletar anchored mid-paragraph
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _AnchoredImage:
    basename: str


@dataclass(slots=True, frozen=True)
class _AnchoredEquation:
    latex: str
    basename: str


@dataclass(slots=True)
class _ParagraphCollect:
    """Buffer intermediário: o que foi coletado de uma ParagraphStyleRange."""

    inlines: list[Inline] = field(default_factory=list)
    anchored: list[_AnchoredImage | _AnchoredEquation] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Walker principal
# ---------------------------------------------------------------------------


def walk_story(  # noqa: PLR0912, PLR0915
    root: etree._Element,
    style_map: StyleMap,
    *,
    converter: EquationConverter | None = None,
    links_dir: Path | None = None,
) -> WalkResult:
    """Percorre uma Story (root é ``<idPkg:Story>``) e retorna blocos.

    Args:
        root: root XML da Story.
        style_map: mapeamento de estilos (paragraph/character).
        converter: cache compartilhado de conversão MathML→LaTeX (F2). Se
            ``None``, equações são silenciosamente puladas.
        links_dir: pasta ``Links/`` para resolver EPS. Necessária para extrair
            equações.
    """
    result = WalkResult()
    stream = _BlockStream(result)
    story = root.find(".//Story")
    if story is None:
        return result

    pending_admonition_title: str | None = None

    for psr in story.findall("ParagraphStyleRange"):
        applied = psr.get("AppliedParagraphStyle") or ""
        rule = style_map.lookup_paragraph(applied)
        if rule is None:
            continue

        kind = rule.kind
        collected = _walk_paragraph(
            psr, style_map, converter=converter, links_dir=links_dir, result=result
        )

        # Decide inline vs. display para equações neste parágrafo.
        inlines, display_blocks = _resolve_equations_inline_or_display(collected)
        plain = _flatten_text(inlines).strip()

        # Parágrafos só com whitespace ou puramente <Br/> e sem display → ignorar
        if not plain and not display_blocks and kind != "drop":
            continue

        if kind == "drop":
            continue

        if kind == "heading":
            stream.flush()
            level = int(rule.get("level", 1))
            stream.add(Heading(level=level, inlines=inlines))

        elif kind == "paragraph":
            stream.flush()
            # Se o parágrafo é APENAS equação display, não cria parágrafo vazio
            if plain:
                stream.add(Paragraph(inlines=inlines))

        elif kind == "list":
            ordered = bool(rule.get("ordered", False))
            marker = str(rule.get("marker", "decimal" if ordered else "bullet"))
            level = int(rule.get("level", 1))
            nested = bool(rule.get("nested", False))
            # Uma única PSR de lista pode conter múltiplos itens separados por <Br/>
            # (padrão "Bullet ABC" do InDesign quando o designer não quebrou em PSRs).
            for item_inlines in _split_inlines_by_break(inlines):
                stream.add_list_item(
                    ordered=ordered,
                    marker=marker,
                    nested=nested,
                    item=ListItem(inlines=item_inlines, level=level),
                )

        elif kind == "admonition":
            stream.add_to_admonition(
                variant=str(rule.get("variant", "note")),
                title=pending_admonition_title or rule.get("title"),
                block=Paragraph(inlines=inlines),
            )
            pending_admonition_title = None

        elif kind == "admonition_title":
            pending_admonition_title = plain

        elif kind == "blockquote":
            stream.flush()
            stream.add(Blockquote(inlines=inlines))

        elif kind == "code_block":
            stream.flush()
            stream.add(CodeBlock(code=plain, language=str(rule.get("language", ""))))

        elif kind == "caption":
            stream.flush()
            stream.add(Caption(inlines=inlines, role=str(rule.get("role", "caption"))))

        elif kind == "front_matter":
            stream.flush()
            result.front_matter.append(
                FrontMatterBlock(role=str(rule.get("role", "info")), inlines=inlines)
            )

        elif kind == "reference_entry":
            stream.flush()
            result.references.append(ReferenceEntry(inlines=inlines))

        else:
            stream.flush()
            if plain:
                stream.add(Paragraph(inlines=inlines))

        # Emitir blocks display (imagens e equações display) após o parágrafo
        for block in display_blocks:
            stream.flush()
            stream.add(block)

    stream.flush()
    return result


# ---------------------------------------------------------------------------
# Paragraph walker
# ---------------------------------------------------------------------------


def _walk_paragraph(
    psr: etree._Element,
    style_map: StyleMap,
    *,
    converter: EquationConverter | None,
    links_dir: Path | None,
    result: WalkResult,
) -> _ParagraphCollect:
    """Coleta inlines e anchored objects de uma ParagraphStyleRange."""
    collected = _ParagraphCollect()

    for csr in psr.findall("CharacterStyleRange"):
        applied_char = csr.get("AppliedCharacterStyle") or ""
        style_map.lookup_character(applied_char)
        inline_kind = _detect_inline_kind(csr)

        for child in csr:
            tag = child.tag
            if tag == "Content":
                text = _clean_content(child.text or "")
                if text:
                    collected.inlines.append(TextRun(text=text, kind=inline_kind))
            elif tag == "Br":
                collected.inlines.append(LineBreak())
            elif tag in ("Rectangle", "Group"):
                _handle_anchored(
                    child, collected, converter=converter, links_dir=links_dir, result=result
                )
            elif tag == "Table":
                # Parse e reuse o próprio walker via callback (mesmos kwargs)
                table = parse_table(
                    child,
                    walk_paragraph=lambda psr_in: _walk_paragraph_for_cell(
                        psr_in, style_map, converter=converter, links_dir=links_dir, result=result
                    ),
                )
                collected.tables.append(table)

    while collected.inlines and isinstance(collected.inlines[-1], LineBreak):
        collected.inlines.pop()

    return collected


def _walk_paragraph_for_cell(
    psr: etree._Element,
    style_map: StyleMap,
    *,
    converter: EquationConverter | None,
    links_dir: Path | None,
    result: WalkResult,
) -> tuple[list[Inline], list[Block]]:
    """Adaptador para o callback do ``table_renderer.parse_table``.

    Retorna ``(inlines, extra_blocks)`` no formato esperado: extras incluem
    ImageBlock/EquationBlock detectados; tabelas aninhadas viram extras também.
    """
    collected = _walk_paragraph(
        psr, style_map, converter=converter, links_dir=links_dir, result=result
    )
    # Aplica a mesma decisão inline/display que o walker faria fora de tabela
    inlines, blocks = _resolve_equations_inline_or_display(collected)
    blocks.extend(collected.tables)
    return inlines, blocks


def _handle_anchored(  # noqa: PLR0911
    el: etree._Element,
    collected: _ParagraphCollect,
    *,
    converter: EquationConverter | None,
    links_dir: Path | None,
    result: WalkResult,
) -> None:
    """Classifica o anchored e registra no collector ou em listas auxiliares."""
    info = classify_anchored(el)
    if info.kind == AnchoredKind.IMAGE_RASTER:
        collected.anchored.append(_AnchoredImage(basename=info.basename))
        result.image_basenames.append(info.basename)
        return

    if info.kind == AnchoredKind.IMAGE_VECTOR:
        collected.anchored.append(_AnchoredImage(basename=info.basename))
        result.vector_basenames.append(info.basename)
        return

    if info.kind == AnchoredKind.EQUATION_EPS:
        if converter is None or links_dir is None:
            return
        eps_path = links_dir / info.basename
        if not eps_path.exists():
            logger.debug("EPS de equação ausente: {}", info.basename)
            result.failed_equations.append(info.basename)
            return
        try:
            extracted = extract_mathml(eps_path)
            latex = converter.convert(extracted.mathml)
        except EquationExtractionError as exc:
            # EPS sem marcador MathType → é ilustração vetorial, não equação
            logger.debug(
                "EPS sem MathType (tratado como ilustração): {} ({})",
                info.basename,
                exc,
            )
            collected.anchored.append(_AnchoredImage(basename=info.basename))
            result.vector_basenames.append(info.basename)
            return
        except MathMLConversionError as exc:
            logger.debug("Falha conversão MathML {}: {}", info.basename, exc)
            result.failed_equations.append(info.basename)
            return
        collected.anchored.append(_AnchoredEquation(latex=latex, basename=info.basename))
        result.equation_basenames.append(info.basename)
        return

    # AnchoredKind.OTHER → silencia (decoração Polygon, etc.)
    return


def _resolve_equations_inline_or_display(
    collected: _ParagraphCollect,
) -> tuple[list[Inline], list[Block]]:
    """Decide se cada anchored vira inline ou display block.

    Regra: se o parágrafo tem texto não-vazio além das equações, todas as
    equações dele viram inline (TextRun ``$latex$``). Caso contrário, equações
    viram blocos de display e imagens viram ImageBlock.

    Sem anchored, retorna ``(inlines, [])``.
    """
    inlines = list(collected.inlines)
    if not collected.anchored and not collected.tables:
        return inlines, []

    has_text = any(
        isinstance(i, TextRun) and i.text.strip() and i.kind != IK.EQUATION_INLINE for i in inlines
    )

    blocks: list[Block] = []
    for anchor in collected.anchored:
        if isinstance(anchor, _AnchoredImage):
            # Imagens são SEMPRE block-level (em F2). F3 pode revisitar.
            blocks.append(
                ImageBlock(
                    src=anchor.basename,
                    alt=os.path.splitext(anchor.basename)[0],
                )
            )
        elif isinstance(anchor, _AnchoredEquation):
            if has_text:
                # Inline: injeta um TextRun(latex, EQUATION_INLINE) no fim do parágrafo
                inlines.append(TextRun(text=anchor.latex, kind=IK.EQUATION_INLINE))
            else:
                blocks.append(EquationBlock(latex=anchor.latex, source=anchor.basename))
    blocks.extend(collected.tables)
    return inlines, blocks


# ---------------------------------------------------------------------------
# Inline detection
# ---------------------------------------------------------------------------


def _detect_inline_kind(csr: etree._Element) -> IK:
    """Resolve negrito/itálico/sup/sub combinando ``FontStyle`` e ``Position``."""
    font_style = (csr.get("FontStyle") or "").lower()
    position = (csr.get("Position") or "").lower()

    if "superscript" in position:
        return IK.SUPERSCRIPT
    if "subscript" in position:
        return IK.SUBSCRIPT

    is_bold = "bold" in font_style or "black" in font_style or "heavy" in font_style
    is_italic = "italic" in font_style or "oblique" in font_style
    if is_bold and is_italic:
        return IK.BOLD_ITALIC
    if is_bold:
        return IK.BOLD
    if is_italic:
        return IK.ITALIC
    return IK.TEXT


def _flatten_text(inlines: Iterable[Inline]) -> str:
    out: list[str] = []
    for inl in inlines:
        if isinstance(inl, TextRun):
            out.append(inl.text)
        elif isinstance(inl, LineBreak):
            out.append("\n")
    return "".join(out)


def _split_inlines_by_break(inlines: list[Inline]) -> list[list[Inline]]:
    """Divide uma lista de inlines em segmentos separados por ``LineBreak``.

    Útil para PSRs de lista que contêm múltiplos itens "achatados" via ``<Br/>``
    em vez de PSRs separadas. Segmentos vazios são descartados.
    """
    segments: list[list[Inline]] = []
    current: list[Inline] = []
    for inl in inlines:
        if isinstance(inl, LineBreak):
            if current and any(isinstance(i, TextRun) and i.text.strip() for i in current):
                segments.append(current)
            current = []
        else:
            current.append(inl)
    if current and any(isinstance(i, TextRun) and i.text.strip() for i in current):
        segments.append(current)
    return segments or [inlines]  # se nada coletado, devolve o original


# ---------------------------------------------------------------------------
# Block stream — agrupa list items e admonitions adjacentes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _BlockStream:
    """Buffer de blocos com merge para listas e admonitions adjacentes."""

    result: WalkResult
    _open_list: ListBlock | None = None
    _open_admonition: AdmonitionBlock | None = None

    def add(self, block: Block) -> None:
        self.result.body.append(block)

    def add_list_item(
        self, ordered: bool, marker: str, item: ListItem, *, nested: bool = False
    ) -> None:
        # Nested: aninha SOMENTE se a lista pai aberta for de tipo DIFERENTE
        # (caso típico: alternativas A/B/C/D dentro de pergunta numerada).
        # Quando o item nested chega sem pai compatível, vira lista normal.
        should_nest = (
            nested
            and self._open_list is not None
            and self._open_list.items
            and (self._open_list.ordered != ordered or self._open_list.marker != marker)
        )
        if should_nest:
            assert self._open_list is not None
            parent_item = self._open_list.items[-1]
            sub = parent_item.sublist
            if sub is None or sub.ordered != ordered or sub.marker != marker:
                sub = ListBlock(ordered=ordered, marker=marker)
                parent_item.sublist = sub
            sub.items.append(item)
            return

        if (
            self._open_list is None
            or self._open_list.ordered != ordered
            or self._open_list.marker != marker
        ):
            self.flush()
            self._open_list = ListBlock(ordered=ordered, marker=marker)
            self.result.body.append(self._open_list)
        self._open_list.items.append(item)

    def add_to_admonition(self, variant: str, title: str | None, block: Block) -> None:
        if self._open_admonition is None or self._open_admonition.variant != variant:
            self.flush()
            self._open_admonition = AdmonitionBlock(variant=variant, title=title)
            self.result.body.append(self._open_admonition)
        elif title and not self._open_admonition.title:
            self._open_admonition.title = title
        self._open_admonition.children.append(block)

    def flush(self) -> None:
        self._open_list = None
        self._open_admonition = None
