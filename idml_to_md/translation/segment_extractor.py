"""Extrai Segmentos traduzíveis das Stories de um IDML.

Cada parágrafo (``ParagraphStyleRange``) vira um ``Segment`` com:
- Identificador estável (story_id + paragraph_idx) que o ``idml_writer`` usa
  para localizar de volta o nó XML correto durante a injeção.
- Lista ordenada de runs (CSR/Content) preservando posição e atributos
  de formatação (bold/italic/sub/sup).

Salva também uma cópia dos XMLs originais das Stories em
``out/<book>/xml_original/`` para auditoria — o usuário pediu para ter
os XMLs originais e traduzidos lado a lado.
"""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path

from loguru import logger
from lxml import etree

from idml_to_md.idml_reader import IDMLDocument
from idml_to_md.style_mapper import StyleMap, normalize_style_name
from idml_to_md.thread_resolver import resolve_reading_order
from idml_to_md.translation.models import (
    Segment,
    SegmentBoundary,
    SegmentRun,
    SkipReason,
)
from idml_to_md.utils.xml import iter_csr_text_nodes

# Caracteres de controle do InDesign descartáveis ao montar plain_text.
_INVISIBLE_CHARS = {chr(0x00AD), chr(0xFEFF)}

# Tags de objetos ancorados inline (fórmula EPS, imagem, etc.). Um CSR que
# contém uma destas e nenhum <Content> é tratado como uma "âncora" posicional —
# nunca traduzida, mas marcada para a LLM preservar a posição.
_ANCHOR_TAGS = frozenset(
    {
        "Rectangle",
        "Group",
        "TextFrame",
        "Table",
        "Polygon",
        "Oval",
        "GraphicLine",
        "EPS",
        "Image",
        "PDF",
        "ImportedPage",
        "Button",
        "MultiStateObject",
    }
)


def extract_segments(
    idml_path: Path,
    style_map: StyleMap,
    *,
    xml_dump_dir: Path | None = None,
    force_translate_styles: frozenset[str] = frozenset(),
    include_master_spreads: bool = False,
    master_cover_styles: frozenset[str] = frozenset(),
) -> list[Segment]:
    """Percorre todas as Stories e produz a lista global de ``Segment``.

    Args:
        idml_path: caminho do .idml fonte.
        style_map: para classificar paragraph_kind e nome normalizado do estilo.
        xml_dump_dir: se fornecido, copia cada ``Stories/Story_*.xml`` aqui
            (preservando o nome original). O usuário pediu esse output para
            comparar com o XML traduzido.
        force_translate_styles: nomes normalizados de ParagraphStyle que, mesmo
            mapeados como ``kind: drop`` no ``styles.default.yaml`` (decisão do
            pipeline Markdown), DEVEM ser traduzidos aqui — ex.: título da capa
            e entradas do sumário manual. Para esses, o segmento não é pulado e
            o ``paragraph_kind`` vira ``paragraph``.
        include_master_spreads: quando ``True``, também extrai Stories que só
            existem em MasterSpreads (ex.: o título "UNIDADE" da capa da Unidade 1,
            que nunca foi sobreposto numa página). Essas Stories são extraídas SÓ
            quanto a ``master_cover_styles``.
        master_cover_styles: nomes normalizados de ParagraphStyle (capa) que
            podem ser extraídos de Stories de master. Sem isso, nenhum parágrafo
            de master é emitido (evita traduzir cabeçalhos/rodapés/numeração).

    Returns:
        Lista plana de Segments em ordem global de leitura (Story por Story,
        parágrafo a parágrafo).
    """
    if xml_dump_dir is not None:
        xml_dump_dir.mkdir(parents=True, exist_ok=True)

    segments: list[Segment] = []
    with IDMLDocument(idml_path) as doc:
        order = resolve_reading_order(doc, include_master_spreads=include_master_spreads)
        logger.info("Stories em ordem: {}", len(order))

        for entry in order:
            story_id = entry.story_id
            story_root = doc.get_story_root(story_id)
            if story_root is None:
                logger.warning("Story ausente: {}", story_id)
                continue

            if xml_dump_dir is not None:
                _dump_story_xml(idml_path, story_id, xml_dump_dir)

            # Stories só-de-master: extrair apenas os parágrafos de capa.
            restrict_styles = master_cover_styles if entry.is_master else frozenset()
            segments.extend(
                _walk_story(
                    story_root,
                    story_id,
                    style_map,
                    force_translate_styles,
                    restrict_styles=restrict_styles,
                )
            )

    logger.info("Segments extraídos: {}", len(segments))
    return segments


def _dump_story_xml(idml_path: Path, story_id: str, dump_dir: Path) -> None:
    """Copia ``Stories/Story_<id>.xml`` do ZIP IDML para ``dump_dir``."""
    member = f"Stories/Story_{story_id}.xml"
    target = dump_dir / f"Story_{story_id}.xml"
    with zipfile.ZipFile(idml_path, "r") as zf, zf.open(member) as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)


def _walk_story(
    root: etree._Element,
    story_id: str,
    style_map: StyleMap,
    force_translate_styles: frozenset[str] = frozenset(),
    *,
    restrict_styles: frozenset[str] = frozenset(),
) -> Iterator[Segment]:
    """Itera ``ParagraphStyleRange`` da Story emitindo Segments.

    Após cada PSR de topo, desce em qualquer ``<Table>`` ali dentro e emite
    também os parágrafos das células (recursivo p/ tabelas aninhadas).

    Quando ``restrict_styles`` é não-vazio (Stories só-de-master), só os PSR cujo
    ``paragraph_style`` normalizado está na allowlist são emitidos; tabelas são
    ignoradas (capa de unidade não tem tabela).
    """
    story = root.find(".//Story")
    if story is None:
        return

    for paragraph_idx, psr in enumerate(story.findall("ParagraphStyleRange")):
        segment = _build_segment(
            psr,
            story_id,
            style_map,
            paragraph_idx=paragraph_idx,
            force_translate_styles=force_translate_styles,
        )
        if restrict_styles:
            if segment.paragraph_style in restrict_styles:
                yield segment
            continue
        yield segment
        yield from _emit_table_segments(psr, story_id, style_map, force_translate_styles)


def _build_segment(
    psr: etree._Element,
    story_id: str,
    style_map: StyleMap,
    *,
    paragraph_idx: int,
    table_self: str = "",
    cell_self: str = "",
    force_translate_styles: frozenset[str] = frozenset(),
) -> Segment:
    """Monta um ``Segment`` a partir de um ``ParagraphStyleRange``.

    Quando ``cell_self`` é informado, o parágrafo vive numa célula de tabela; o
    ``segment_id`` usa o ``Self`` da célula (único) e ``paragraph_idx`` é o índice
    do PSR dentro da célula.
    """
    applied = psr.get("AppliedParagraphStyle") or ""
    style_name = normalize_style_name(applied)
    rule = style_map.lookup_paragraph(applied)
    paragraph_kind = rule.kind if rule is not None else "drop"

    runs, boundaries = _extract_inline(psr)
    plain = "".join(r.text for r in runs)

    # Limpa chars invisíveis para o plain_text que vai à tradução
    plain_clean = "".join(c for c in plain if c not in _INVISIBLE_CHARS).strip()

    seg_id = f"{story_id}:{cell_self}:{paragraph_idx}" if cell_self else f"{story_id}:{paragraph_idx}"
    segment = Segment(
        segment_id=seg_id,
        story_id=story_id,
        paragraph_idx=paragraph_idx,
        paragraph_style=style_name,
        paragraph_kind=paragraph_kind,
        runs=runs,
        boundaries=boundaries,
        plain_text=plain_clean,
        table_self=table_self,
        cell_self=cell_self,
    )

    if not plain_clean:
        segment.skip = True
        segment.skip_reason = SkipReason.EMPTY
    elif paragraph_kind == "drop":
        if style_name in force_translate_styles:
            # Estilo descartado no Markdown mas que deve ser traduzido no IDML
            # (capa/sumário). Vira ``paragraph`` para o classifier não re-pular;
            # o nome original fica em ``paragraph_style`` (rastreabilidade).
            segment.paragraph_kind = "paragraph"
            segment.notes.append(f"drop→traduzir (forçado: {style_name})")
        else:
            segment.skip = True
            segment.skip_reason = SkipReason.PARAGRAPH_STYLE
            segment.notes.append(f"paragraph_kind=drop ({style_name})")

    return segment


def _emit_table_segments(
    container: etree._Element,
    story_id: str,
    style_map: StyleMap,
    force_translate_styles: frozenset[str] = frozenset(),
) -> Iterator[Segment]:
    """Emite Segments para os parágrafos das células de tabelas em ``container``.

    ``container`` é um PSR (de topo ou de célula). Encontra ``<Table>`` filhas dos
    ``<CharacterStyleRange>`` e, para cada ``<Cell>``, emite um Segment por PSR.
    Recursivo: parágrafos de célula podem conter tabelas aninhadas.
    """
    for csr in container.findall("CharacterStyleRange"):
        for table in csr.findall("Table"):
            table_self = table.get("Self") or ""
            for cell in table.findall("Cell"):
                cell_self = cell.get("Self") or ""
                for cell_para_idx, cell_psr in enumerate(
                    cell.findall("ParagraphStyleRange")
                ):
                    yield _build_segment(
                        cell_psr,
                        story_id,
                        style_map,
                        paragraph_idx=cell_para_idx,
                        table_self=table_self,
                        cell_self=cell_self,
                        force_translate_styles=force_translate_styles,
                    )
                    # tabelas aninhadas dentro de um parágrafo de célula
                    yield from _emit_table_segments(
                        cell_psr, story_id, style_map, force_translate_styles
                    )


def _extract_inline(
    psr: etree._Element,
) -> tuple[list[SegmentRun], list[SegmentBoundary]]:
    """Extrai runs de texto e fronteiras (Br/âncora) de uma ParagraphStyleRange.

    Caminha os nós de texto de cada ``<CharacterStyleRange>`` em ORDEM DE
    DOCUMENTO via :func:`iter_csr_text_nodes` (que desce em wrappers inline como
    ``HyperlinkTextSource`` — texto do sumário e de hyperlinks):

    - cada ``<Content>`` não-vazio vira um ``SegmentRun``. A posição do run na
      lista é o ordinal usado nos marcadores ``§tN§``. O ``content_idx`` é a
      posição do ``<Content>`` dentro do CSR (conta inclusive os vazios) na MESMA
      travessia usada pelo writer, para a escrita casar de volta.
    - cada ``<Br/>`` vira uma fronteira ``br`` (após o último run visto).
    - um CSR sem ``<Content>`` mas com objeto ancorado vira uma fronteira
      ``anchor``.

    Outras tags (``<Properties>``, etc.) são ignoradas aqui e preservadas
    intactas na escrita (o writer só toca o ``text`` dos ``<Content>``).
    """
    runs: list[SegmentRun] = []
    boundaries: list[SegmentBoundary] = []
    anchor_ord = 0

    for csr_idx, csr in enumerate(psr.findall("CharacterStyleRange")):
        text_nodes = list(iter_csr_text_nodes(csr))
        has_content = any(kind == "content" for kind, _ in text_nodes)
        if not has_content and _is_anchor_csr(csr):
            boundaries.append(
                SegmentBoundary(
                    kind="anchor",
                    after_text_ord=len(runs) - 1,
                    csr_idx=csr_idx,
                    anchor_ord=anchor_ord,
                )
            )
            anchor_ord += 1
            continue

        char_style_raw = csr.get("AppliedCharacterStyle") or ""
        char_style = normalize_style_name(char_style_raw) if char_style_raw else ""
        font_style = (csr.get("FontStyle") or "").lower()
        position = (csr.get("Position") or "").lower()

        is_bold = "bold" in font_style or "black" in font_style or "heavy" in font_style
        is_italic = "italic" in font_style or "oblique" in font_style
        is_sup = "superscript" in position
        is_sub = "subscript" in position

        # CharacterStyle pode forçar formatação além do FontStyle
        # (ex: estilo "Bold" no Astera).
        if char_style and char_style not in ("$ID/[No character style]",):
            lower_cs = char_style.lower()
            if "bold" in lower_cs:
                is_bold = True
            if "italic" in lower_cs:
                is_italic = True
            if "sobrescrito" in lower_cs or "superscript" in lower_cs:
                is_sup = True
            if "subscrito" in lower_cs or "subscript" in lower_cs:
                is_sub = True

        content_idx = 0
        for kind, el in text_nodes:
            if kind == "content":
                text = el.text or ""
                if text:
                    runs.append(
                        SegmentRun(
                            run_idx=csr_idx,
                            content_idx=content_idx,
                            text=text,
                            bold=is_bold,
                            italic=is_italic,
                            superscript=is_sup,
                            subscript=is_sub,
                            character_style=char_style,
                        )
                    )
                content_idx += 1
            else:  # "br"
                boundaries.append(SegmentBoundary(kind="br", after_text_ord=len(runs) - 1))

    return runs, boundaries


def _is_anchor_csr(csr: etree._Element) -> bool:
    """True se o CSR não tem texto mas contém um objeto ancorado inline."""
    for child in csr:
        tag = child.tag
        if isinstance(tag, str) and tag in _ANCHOR_TAGS:
            return True
    return False


