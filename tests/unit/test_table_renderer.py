"""Testes do ``table_renderer``."""

from __future__ import annotations

from lxml import etree

from idml_to_md.models import (
    EquationBlock,
    ImageBlock,
    InlineKind,
    Paragraph,
    TableBlock,
    TableCell,
    TextRun,
)
from idml_to_md.table_renderer import (
    _needs_html_fallback,
    parse_table,
    render_table,
)


def _walk_text(psr: etree._Element):  # type: ignore[no-untyped-def]
    """Mock callback simples: extrai texto de <Content> nos CSR filhos."""
    inlines = []
    for csr in psr.findall("CharacterStyleRange"):
        for content in csr.findall("Content"):
            text = content.text or ""
            if text:
                inlines.append(TextRun(text=text))
    return inlines, []


# ---------------------------------------------------------------------------
# parse_table
# ---------------------------------------------------------------------------


TABLE_2X2 = b"""
<Table HeaderRowCount="0" BodyRowCount="2" ColumnCount="2">
  <Cell Name="0:0" RowSpan="1" ColumnSpan="1">
    <ParagraphStyleRange>
      <CharacterStyleRange><Content>A1</Content></CharacterStyleRange>
    </ParagraphStyleRange>
  </Cell>
  <Cell Name="0:1" RowSpan="1" ColumnSpan="1">
    <ParagraphStyleRange>
      <CharacterStyleRange><Content>B1</Content></CharacterStyleRange>
    </ParagraphStyleRange>
  </Cell>
  <Cell Name="1:0" RowSpan="1" ColumnSpan="1">
    <ParagraphStyleRange>
      <CharacterStyleRange><Content>A2</Content></CharacterStyleRange>
    </ParagraphStyleRange>
  </Cell>
  <Cell Name="1:1" RowSpan="1" ColumnSpan="1">
    <ParagraphStyleRange>
      <CharacterStyleRange><Content>B2</Content></CharacterStyleRange>
    </ParagraphStyleRange>
  </Cell>
</Table>
"""


TABLE_WITH_HEADER = b"""
<Table HeaderRowCount="1" BodyRowCount="1" ColumnCount="2">
  <Cell Name="0:0"><ParagraphStyleRange><CharacterStyleRange><Content>Col1</Content></CharacterStyleRange></ParagraphStyleRange></Cell>
  <Cell Name="0:1"><ParagraphStyleRange><CharacterStyleRange><Content>Col2</Content></CharacterStyleRange></ParagraphStyleRange></Cell>
  <Cell Name="1:0"><ParagraphStyleRange><CharacterStyleRange><Content>X</Content></CharacterStyleRange></ParagraphStyleRange></Cell>
  <Cell Name="1:1"><ParagraphStyleRange><CharacterStyleRange><Content>Y</Content></CharacterStyleRange></ParagraphStyleRange></Cell>
</Table>
"""


TABLE_MERGED = b"""
<Table HeaderRowCount="0" BodyRowCount="2" ColumnCount="2">
  <Cell Name="0:0" RowSpan="1" ColumnSpan="2">
    <ParagraphStyleRange><CharacterStyleRange><Content>span</Content></CharacterStyleRange></ParagraphStyleRange>
  </Cell>
  <Cell Name="1:0"><ParagraphStyleRange><CharacterStyleRange><Content>a</Content></CharacterStyleRange></ParagraphStyleRange></Cell>
  <Cell Name="1:1"><ParagraphStyleRange><CharacterStyleRange><Content>b</Content></CharacterStyleRange></ParagraphStyleRange></Cell>
</Table>
"""


class TestParseTable:
    def test_parses_simple_table(self) -> None:
        el = etree.fromstring(TABLE_2X2)
        tb = parse_table(el, _walk_text)
        assert tb.header_row_count == 0
        assert len(tb.rows) == 2
        assert len(tb.rows[0]) == 2
        # cell content
        first_cell = tb.rows[0][0]
        assert isinstance(first_cell.blocks[0], Paragraph)
        assert first_cell.blocks[0].inlines[0].text == "A1"

    def test_parses_header(self) -> None:
        el = etree.fromstring(TABLE_WITH_HEADER)
        tb = parse_table(el, _walk_text)
        assert tb.header_row_count == 1
        # cell de header marca is_header
        assert tb.rows[0][0].is_header
        assert not tb.rows[1][0].is_header

    def test_parses_merged_cell(self) -> None:
        el = etree.fromstring(TABLE_MERGED)
        tb = parse_table(el, _walk_text)
        # row 0 tem apenas 1 cell (com column_span=2)
        assert len(tb.rows[0]) == 1
        assert tb.rows[0][0].column_span == 2
        assert len(tb.rows[1]) == 2


# ---------------------------------------------------------------------------
# render_table
# ---------------------------------------------------------------------------


def make_cell(text: str, **kw) -> TableCell:  # type: ignore[no-untyped-def]
    return TableCell(blocks=[Paragraph(inlines=[TextRun(text=text)])], **kw)


class TestRenderGfm:
    def test_simple_2x2_with_synth_header(self) -> None:
        tb = TableBlock(
            rows=[
                [make_cell("A1"), make_cell("B1")],
                [make_cell("A2"), make_cell("B2")],
            ]
        )
        out = render_table(tb)
        assert "| --- | --- |" in out
        assert "A1" in out and "B2" in out

    def test_with_header_row(self) -> None:
        tb = TableBlock(
            rows=[
                [make_cell("Col1"), make_cell("Col2")],
                [make_cell("x"), make_cell("y")],
            ],
            header_row_count=1,
        )
        out = render_table(tb)
        lines = out.splitlines()
        # Linha do separador vem DEPOIS do header (linha 1)
        assert "| --- | --- |" in lines[1]
        assert "Col1" in lines[0]
        assert "x" in lines[2]

    def test_pipe_in_cell_escaped(self) -> None:
        tb = TableBlock(rows=[[make_cell("a|b"), make_cell("c")]])
        out = render_table(tb)
        assert r"a\|b" in out

    def test_inline_formatting_preserved(self) -> None:
        tb = TableBlock(
            rows=[
                [
                    TableCell(
                        blocks=[Paragraph(inlines=[TextRun(text="bold", kind=InlineKind.BOLD)])]
                    ),
                    make_cell("plain"),
                ]
            ]
        )
        out = render_table(tb)
        assert "**bold**" in out


class TestRenderHtmlFallback:
    def test_merged_cell_uses_html(self) -> None:
        tb = TableBlock(
            rows=[
                [TableCell(blocks=[Paragraph(inlines=[TextRun(text="wide")])], column_span=2)],
                [make_cell("a"), make_cell("b")],
            ]
        )
        out = render_table(tb)
        assert "<table>" in out
        assert 'colspan="2"' in out

    def test_image_in_cell_uses_html(self) -> None:
        tb = TableBlock(
            rows=[[TableCell(blocks=[ImageBlock(src="x.jpg", alt="x")]), make_cell("y")]]
        )
        out = render_table(tb)
        assert "<table>" in out
        assert '<img src="x.jpg"' in out

    def test_equation_in_cell_uses_html(self) -> None:
        tb = TableBlock(
            rows=[[TableCell(blocks=[EquationBlock(latex=r"\frac{1}{2}")]), make_cell("y")]]
        )
        out = render_table(tb)
        assert "<table>" in out
        assert "$$\\frac{1}{2}$$" in out

    def test_multi_block_cell_uses_html(self) -> None:
        tb = TableBlock(
            rows=[
                [
                    TableCell(
                        blocks=[
                            Paragraph(inlines=[TextRun(text="line1")]),
                            Paragraph(inlines=[TextRun(text="line2")]),
                        ]
                    ),
                    make_cell("b"),
                ]
            ]
        )
        out = render_table(tb)
        assert "<table>" in out
        assert "line1<br />line2" in out


class TestEdgeCases:
    def test_empty_table_renders_empty(self) -> None:
        assert render_table(TableBlock()) == ""

    def test_needs_html_returns_false_for_simple(self) -> None:
        tb = TableBlock(rows=[[make_cell("a"), make_cell("b")]])
        assert not _needs_html_fallback(tb)

    def test_needs_html_true_for_row_span(self) -> None:
        tb = TableBlock(rows=[[TableCell(blocks=[], row_span=2)]])
        assert _needs_html_fallback(tb)
