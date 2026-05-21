"""Parser e renderer de tabelas IDML.

Pipeline em duas etapas:

1. ``parse_table(table_el, walk_paragraph_fn)`` percorre a estrutura XML
   ``<Table>/<Row>/<Cell>``, extrai metadados (HeaderRowCount, RowSpan,
   ColumnSpan, Name="row:col") e delega o conteúdo de cada célula para a
   função de walking de parágrafos (passada via callback para evitar
   import circular com ``story_walker``). Retorna um ``TableBlock``.

2. ``render_table(block)`` serializa em Markdown — GFM por default; HTML
   ``<table>`` se houver merged cells, tabelas aninhadas, ou conteúdo
   complexo (mais de 1 bloco / bloco display) nas células.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from idml_to_md.models import (
    Block,
    EquationBlock,
    ImageBlock,
    Inline,
    InlineKind,
    LineBreak,
    Paragraph,
    TableBlock,
    TableCell,
    TextRun,
)

if TYPE_CHECKING:
    from lxml import etree


# Callback: dado um <ParagraphStyleRange>, retorna (inlines, extra_blocks).
# Definido como Callable simples (não Protocol) para aceitar covariância
# natural do retorno (subclasses de Block).
_ParagraphWalker = Callable[["etree._Element"], "tuple[list[Inline], list[Block]]"]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_table(table_el: etree._Element, walk_paragraph: _ParagraphWalker) -> TableBlock:
    """Constrói ``TableBlock`` a partir do elemento ``<Table>``."""
    header_count = int(table_el.get("HeaderRowCount", "0"))
    body_count = int(table_el.get("BodyRowCount", "0"))
    column_count = int(table_el.get("ColumnCount", "0"))
    total_rows = header_count + body_count

    # Grade vazia
    grid: list[list[TableCell | None]] = [[None] * column_count for _ in range(total_rows)]

    for cell_el in table_el.findall("Cell"):
        name = cell_el.get("Name") or "0:0"
        try:
            row_str, col_str = name.split(":")
            row, col = int(row_str), int(col_str)
        except ValueError:
            continue  # malformed; skip
        if row >= total_rows or col >= column_count:
            continue

        row_span = int(cell_el.get("RowSpan", "1"))
        col_span = int(cell_el.get("ColumnSpan", "1"))

        # Coleta blocos do conteúdo da célula
        cell_blocks: list[Block] = []
        # cada Cell tem ParagraphStyleRange como filho direto
        for psr in cell_el.findall("ParagraphStyleRange"):
            inlines, extras = walk_paragraph(psr)
            if inlines:
                cell_blocks.append(Paragraph(inlines=inlines))
            cell_blocks.extend(extras)

        is_header = row < header_count
        cell = TableCell(
            blocks=cell_blocks,
            column_span=col_span,
            row_span=row_span,
            is_header=is_header,
        )
        grid[row][col] = cell

    # Filtra None (cells "ocupadas" por span de outra célula).
    # Renderer usa column_span para skippar lugares apropriadamente.
    rows: list[list[TableCell]] = [[c for c in row if c is not None] for row in grid]
    return TableBlock(rows=rows, header_row_count=header_count)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_table(block: TableBlock) -> str:
    """Renderiza a tabela em GFM ou HTML conforme complexidade."""
    if not block.rows:
        return ""
    if _needs_html_fallback(block):
        return _render_html(block)
    return _render_gfm(block)


def _needs_html_fallback(block: TableBlock) -> bool:
    """Falamos HTML quando GFM não consegue representar o conteúdo."""
    for row in block.rows:
        for cell in row:
            if cell.column_span > 1 or cell.row_span > 1:
                return True
            if _cell_has_block_content(cell):
                return True
    return False


def _cell_has_block_content(cell: TableCell) -> bool:
    """Célula tem conteúdo que GFM não suporta (imagem, equação, múltiplos parágrafos)."""
    if len(cell.blocks) > 1:
        return True
    if not cell.blocks:
        return False
    only = cell.blocks[0]
    return isinstance(only, (ImageBlock, EquationBlock, TableBlock))


# --------------------------------------------------------------------- GFM


def _render_gfm(block: TableBlock) -> str:
    if not block.rows:
        return ""
    cols = max(len(row) for row in block.rows)
    if cols == 0:
        return ""

    lines: list[str] = []
    rows = block.rows
    header_count = block.header_row_count

    # Garante que sempre há linha de header (GFM exige)
    if header_count == 0:
        header_cells = [TableCell() for _ in range(cols)]
        lines.append(_gfm_row(header_cells, cols))
        lines.append(_gfm_separator(cols))
        data_start = 0
    else:
        for r in range(header_count):
            lines.append(_gfm_row(rows[r], cols))
        lines.append(_gfm_separator(cols))
        data_start = header_count

    for r in range(data_start, len(rows)):
        lines.append(_gfm_row(rows[r], cols))

    return "\n".join(lines)


def _gfm_row(cells: list[TableCell], cols: int) -> str:
    parts = ["| "]
    for i in range(cols):
        text = _cell_to_inline_text(cells[i]) if i < len(cells) else ""
        # GFM não suporta '|' literal nem newlines dentro da cell — sanitiza
        text = text.replace("|", r"\|").replace("\n", " ").strip()
        parts.append(text)
        parts.append(" | ")
    return "".join(parts).rstrip()


def _gfm_separator(cols: int) -> str:
    return "|" + "|".join([" --- "] * cols) + "|"


def _cell_to_inline_text(cell: TableCell) -> str:
    """Concatena texto plano da célula (para GFM 1-line)."""
    if not cell.blocks:
        return ""
    paragraph = cell.blocks[0]
    if not isinstance(paragraph, Paragraph):
        return ""
    return _inlines_to_plain(paragraph.inlines)


def _inlines_to_plain(inlines: list[Inline]) -> str:
    out: list[str] = []
    for inl in inlines:
        if isinstance(inl, LineBreak):
            out.append(" ")
            continue
        if not isinstance(inl, TextRun) or not inl.text:
            continue
        text = inl.text
        if inl.kind == InlineKind.BOLD:
            out.append(f"**{text}**")
        elif inl.kind == InlineKind.ITALIC:
            out.append(f"*{text}*")
        elif inl.kind == InlineKind.BOLD_ITALIC:
            out.append(f"***{text}***")
        elif inl.kind == InlineKind.SUPERSCRIPT:
            out.append(f"<sup>{text}</sup>")
        elif inl.kind == InlineKind.SUBSCRIPT:
            out.append(f"<sub>{text}</sub>")
        elif inl.kind == InlineKind.EQUATION_INLINE:
            out.append(f"${text}$")
        else:
            out.append(text)
    return "".join(out)


# --------------------------------------------------------------------- HTML


def _render_html(block: TableBlock) -> str:
    lines: list[str] = ["<table>"]
    for r_idx, row in enumerate(block.rows):
        lines.append("  <tr>")
        for cell in row:
            tag = "th" if cell.is_header or r_idx < block.header_row_count else "td"
            attrs: list[str] = []
            if cell.row_span > 1:
                attrs.append(f'rowspan="{cell.row_span}"')
            if cell.column_span > 1:
                attrs.append(f'colspan="{cell.column_span}"')
            attr_str = (" " + " ".join(attrs)) if attrs else ""
            content = _cell_to_html_content(cell)
            lines.append(f"    <{tag}{attr_str}>{content}</{tag}>")
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _cell_to_html_content(cell: TableCell) -> str:
    if not cell.blocks:
        return ""
    parts: list[str] = []
    for block in cell.blocks:
        if isinstance(block, Paragraph):
            parts.append(_inlines_to_plain(block.inlines))
        elif isinstance(block, ImageBlock):
            parts.append(f'<img src="{block.src}" alt="{block.alt}" />')
        elif isinstance(block, EquationBlock):
            parts.append(f"$${block.latex}$$")
        # outros tipos: silencia em F3
    return "<br />".join(p for p in parts if p)
