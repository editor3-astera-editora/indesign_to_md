"""Testes do renderer Markdown."""

from __future__ import annotations

from idml_to_md.md_writer import (
    _escape_md,
    _list_marker,
    _render_admonition,
    _render_inlines,
    _render_list,
    render_document,
)
from idml_to_md.models import (
    AdmonitionBlock,
    Blockquote,
    Caption,
    CodeBlock,
    Document,
    EquationBlock,
    FrontMatterBlock,
    Heading,
    ImageBlock,
    InlineKind,
    LineBreak,
    ListBlock,
    ListItem,
    Paragraph,
    ReferenceEntry,
    TableBlock,
    TableCell,
    TextRun,
)


def text(s: str, kind: InlineKind = InlineKind.TEXT) -> TextRun:
    return TextRun(text=s, kind=kind)


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------


class TestRenderInlines:
    def test_plain_text(self) -> None:
        assert _render_inlines([text("hello")]) == "hello"

    def test_bold(self) -> None:
        assert _render_inlines([text("forte", InlineKind.BOLD)]) == "**forte**"

    def test_italic(self) -> None:
        assert _render_inlines([text("it", InlineKind.ITALIC)]) == "*it*"

    def test_bold_italic(self) -> None:
        assert _render_inlines([text("bi", InlineKind.BOLD_ITALIC)]) == "***bi***"

    def test_superscript(self) -> None:
        assert _render_inlines([text("2", InlineKind.SUPERSCRIPT)]) == "<sup>2</sup>"

    def test_subscript(self) -> None:
        assert _render_inlines([text("n", InlineKind.SUBSCRIPT)]) == "<sub>n</sub>"

    def test_line_break(self) -> None:
        out = _render_inlines([text("a"), LineBreak(), text("b")])
        assert out == "a  \nb"

    def test_escape_md_lt_gt(self) -> None:
        assert _escape_md("<x>") == "&lt;x&gt;"

    def test_mixed_run(self) -> None:
        runs = [text("o valor é "), text("R$ 10", InlineKind.BOLD), text(" hoje.")]
        assert _render_inlines(runs) == "o valor é **R$ 10** hoje."

    def test_skips_empty_text_runs(self) -> None:
        assert _render_inlines([text("")]) == ""


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


class TestLists:
    def test_bullet_marker(self) -> None:
        lb = ListBlock(ordered=False, items=[ListItem(inlines=[text("a")])])
        assert _list_marker(lb, 1) == "-"

    def test_decimal_marker(self) -> None:
        lb = ListBlock(ordered=True, marker="decimal", items=[])
        assert _list_marker(lb, 3) == "3."

    def test_roman_marker(self) -> None:
        lb = ListBlock(ordered=True, marker="upper-roman", items=[])
        assert _list_marker(lb, 1) == "I."
        assert _list_marker(lb, 3) == "III."

    def test_alpha_marker(self) -> None:
        lb = ListBlock(ordered=True, marker="upper-alpha", items=[])
        assert _list_marker(lb, 2) == "B."

    def test_render_full_list(self) -> None:
        lb = ListBlock(
            ordered=True,
            marker="decimal",
            items=[
                ListItem(inlines=[text("um")]),
                ListItem(inlines=[text("dois")]),
            ],
        )
        out = _render_list(lb)
        assert out == "1. um\n2. dois"

    def test_nested_level_indents(self) -> None:
        lb = ListBlock(
            ordered=False,
            items=[ListItem(inlines=[text("a")], level=2)],
        )
        out = _render_list(lb)
        assert out == "  - a"

    def test_nested_sublist_renders_indented(self) -> None:
        from idml_to_md.md_writer import _render_list

        sub = ListBlock(
            ordered=True,
            marker="upper-alpha",
            items=[ListItem(inlines=[text("alt 1")]), ListItem(inlines=[text("alt 2")])],
        )
        parent = ListBlock(
            ordered=True,
            marker="decimal",
            items=[
                ListItem(inlines=[text("Pergunta 1")], sublist=sub),
                ListItem(inlines=[text("Pergunta 2")]),
            ],
        )
        out = _render_list(parent)
        lines = out.splitlines()
        assert lines[0] == "1. Pergunta 1"
        assert lines[1] == "  A. alt 1"
        assert lines[2] == "  B. alt 2"
        assert lines[3] == "2. Pergunta 2"

    def test_roman_overflow_falls_back_to_decimal(self) -> None:
        lb = ListBlock(ordered=True, marker="upper-roman", items=[])
        assert _list_marker(lb, 50) == "50."

    def test_alpha_overflow_falls_back_to_decimal(self) -> None:
        lb = ListBlock(ordered=True, marker="upper-alpha", items=[])
        assert _list_marker(lb, 30) == "30."


# ---------------------------------------------------------------------------
# Admonition
# ---------------------------------------------------------------------------


class TestAdmonition:
    def test_note_with_title(self) -> None:
        ad = AdmonitionBlock(
            variant="note",
            title="VOCÊ SABIA?",
            children=[Paragraph(inlines=[text("conteúdo")])],
        )
        out = _render_admonition(ad)
        assert out.startswith("> [!NOTE]")
        assert "> **VOCÊ SABIA?**" in out
        assert "> conteúdo" in out

    def test_tip_variant(self) -> None:
        ad = AdmonitionBlock(variant="tip", children=[Paragraph(inlines=[text("dica")])])
        out = _render_admonition(ad)
        assert out.startswith("> [!TIP]")

    def test_unknown_variant_falls_back_to_note(self) -> None:
        ad = AdmonitionBlock(variant="weird", children=[Paragraph(inlines=[text("x")])])
        out = _render_admonition(ad)
        assert out.startswith("> [!NOTE]")


# ---------------------------------------------------------------------------
# Full document
# ---------------------------------------------------------------------------


def make_doc(**kwargs) -> Document:  # type: ignore[no-untyped-def]
    return Document(title="Livro", slug="livro", **kwargs)


class TestRenderDocument:
    def test_minimal(self) -> None:
        out = render_document(make_doc())
        assert out.startswith("# Livro")

    def test_heading_and_paragraph(self) -> None:
        doc = make_doc(
            blocks=[
                Heading(level=1, inlines=[text("Cap")]),
                Paragraph(inlines=[text("texto.")]),
            ]
        )
        out = render_document(doc)
        assert "# Cap" in out
        assert "texto." in out

    def test_toc_inserted(self) -> None:
        doc = make_doc(
            blocks=[
                Heading(level=1, inlines=[text("Cap 1")]),
                Heading(level=2, inlines=[text("Sec A")]),
                Heading(level=1, inlines=[text("Cap 2")]),
            ]
        )
        out = render_document(doc)
        assert "## Sumário" in out
        assert "[Cap 1](#cap-1)" in out
        assert "[Sec A](#sec-a)" in out
        assert "[Cap 2](#cap-2)" in out

    def test_references_section(self) -> None:
        doc = make_doc(references=[ReferenceEntry(inlines=[text("LIVRO, A. (2020).")])])
        out = render_document(doc)
        assert "## Referências" in out
        assert "LIVRO, A. (2020)." in out

    def test_blockquote(self) -> None:
        doc = make_doc(blocks=[Blockquote(inlines=[text("citado")])])
        out = render_document(doc)
        assert "> citado" in out

    def test_code_block(self) -> None:
        doc = make_doc(blocks=[CodeBlock(code="print(1)", language="python")])
        out = render_document(doc)
        assert "```python" in out
        assert "print(1)" in out

    def test_image_with_caption(self) -> None:
        doc = make_doc(blocks=[ImageBlock(src="assets/img/foo.jpg", alt="foo", caption="Figura 1")])
        out = render_document(doc)
        assert "![foo](assets/img/foo.jpg)" in out
        assert "*Figura 1*" in out

    def test_image_without_caption(self) -> None:
        doc = make_doc(blocks=[ImageBlock(src="x.png")])
        out = render_document(doc)
        assert "![](x.png)" in out

    def test_caption_block(self) -> None:
        doc = make_doc(blocks=[Caption(inlines=[text("legenda x")])])
        out = render_document(doc)
        assert "*legenda x*" in out

    def test_front_matter_authors_italic(self) -> None:
        doc = make_doc(front_matter=[FrontMatterBlock(role="authors", inlines=[text("Autor 1")])])
        out = render_document(doc)
        assert "*Autor 1*" in out

    def test_front_matter_title_bold(self) -> None:
        doc = make_doc(front_matter=[FrontMatterBlock(role="title", inlines=[text("Sub")])])
        out = render_document(doc)
        assert "**Sub**" in out

    def test_collapses_blank_lines(self) -> None:
        # Garante que não há triplas em branco no output
        doc = make_doc(
            blocks=[Heading(level=1, inlines=[text("a")]), Paragraph(inlines=[text("b")])]
        )
        out = render_document(doc)
        assert "\n\n\n" not in out

    def test_equation_display_block(self) -> None:
        doc = make_doc(blocks=[EquationBlock(latex=r"\frac{1}{2}")])
        out = render_document(doc)
        assert "$$\n\\frac{1}{2}\n$$" in out

    def test_equation_display_empty_omitted(self) -> None:
        doc = make_doc(
            blocks=[
                Heading(level=1, inlines=[text("X")]),
                EquationBlock(latex=""),
                Paragraph(inlines=[text("y")]),
            ]
        )
        out = render_document(doc)
        # Não há `$$\n\n$$` no output
        assert "$$\n\n$$" not in out

    def test_equation_inline_in_paragraph(self) -> None:
        doc = make_doc(
            blocks=[
                Paragraph(
                    inlines=[
                        text("Considere "),
                        text(r"\frac{a}{b}", InlineKind.EQUATION_INLINE),
                        text(" como exemplo."),
                    ]
                ),
            ]
        )
        out = render_document(doc)
        assert "$\\frac{a}{b}$" in out
        # Não deve escapar `\` ou `{`
        assert "\\\\" not in out

    def test_table_block_renders_gfm(self) -> None:
        doc = make_doc(
            blocks=[
                TableBlock(
                    rows=[
                        [
                            TableCell(blocks=[Paragraph(inlines=[text("A")])]),
                            TableCell(blocks=[Paragraph(inlines=[text("B")])]),
                        ]
                    ]
                ),
            ]
        )
        out = render_document(doc)
        assert "| --- | --- |" in out
        assert "A" in out and "B" in out

    def test_equation_inline_separated_by_space(self) -> None:
        # Texto sem espaço final + equação inline → renderer injeta espaço
        doc = make_doc(
            blocks=[
                Paragraph(
                    inlines=[
                        text("Fórmula:"),
                        text(r"\frac{a}{b}", InlineKind.EQUATION_INLINE),
                    ]
                ),
            ]
        )
        out = render_document(doc)
        assert "Fórmula: $\\frac{a}{b}$" in out

    def test_full_render_with_admonition_inside_body(self) -> None:
        doc = make_doc(
            blocks=[
                Heading(level=1, inlines=[text("Cap")]),
                AdmonitionBlock(
                    variant="tip",
                    title="Dica",
                    children=[Paragraph(inlines=[text("útil")])],
                ),
            ]
        )
        out = render_document(doc)
        assert "# Cap" in out
        assert "> [!TIP]" in out
        assert "> **Dica**" in out
