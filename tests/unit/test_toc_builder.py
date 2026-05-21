"""Testes do ``toc_builder``."""

from __future__ import annotations

from idml_to_md.models import Document, Heading, InlineKind, LineBreak, Paragraph, TextRun
from idml_to_md.toc_builder import build_toc, render_toc


def t(s: str) -> TextRun:
    return TextRun(text=s, kind=InlineKind.TEXT)


def make_doc(*blocks: object) -> Document:
    return Document(title="X", slug="x", blocks=list(blocks))  # type: ignore[arg-type]


class TestBuildToc:
    def test_collects_h1_h2(self) -> None:
        doc = make_doc(
            Heading(level=1, inlines=[t("Cap 1")]),
            Heading(level=2, inlines=[t("Sec 1.1")]),
            Heading(level=3, inlines=[t("Sub")]),  # default max_level=2 → ignora
            Heading(level=1, inlines=[t("Cap 2")]),
        )
        entries = build_toc(doc)
        assert [e.text for e in entries] == ["Cap 1", "Sec 1.1", "Cap 2"]

    def test_max_level_override(self) -> None:
        doc = make_doc(
            Heading(level=1, inlines=[t("a")]),
            Heading(level=3, inlines=[t("b")]),
        )
        entries = build_toc(doc, max_level=3)
        assert [e.level for e in entries] == [1, 3]

    def test_disambiguates_duplicate_slugs(self) -> None:
        doc = make_doc(
            Heading(level=1, inlines=[t("Conjuntos")]),
            Heading(level=1, inlines=[t("Conjuntos")]),
        )
        entries = build_toc(doc)
        slugs = [e.slug for e in entries]
        assert slugs == ["conjuntos", "conjuntos-1"]

    def test_skips_non_heading_blocks(self) -> None:
        doc = make_doc(
            Paragraph(inlines=[t("texto")]),
            Heading(level=1, inlines=[t("Cap")]),
        )
        entries = build_toc(doc)
        assert len(entries) == 1
        assert entries[0].text == "Cap"

    def test_skips_empty_heading(self) -> None:
        doc = make_doc(Heading(level=1, inlines=[t("")]))
        assert build_toc(doc) == []

    def test_inlines_with_line_break_collapse_to_space(self) -> None:
        doc = make_doc(Heading(level=1, inlines=[t("A"), LineBreak(), t("B")]))
        entries = build_toc(doc)
        assert entries[0].text == "A B"

    def test_empty_text_after_slugify_uses_fallback(self) -> None:
        # Heading com apenas pontuação que slugify reduz a vazio
        doc = make_doc(Heading(level=1, inlines=[t("???!!!")]))
        entries = build_toc(doc)
        # slugify produz "" → fallback "heading-1"
        assert entries[0].slug == "heading-1"


class TestRenderToc:
    def test_empty_renders_empty_string(self) -> None:
        assert render_toc([]) == ""

    def test_renders_with_indentation(self) -> None:
        doc = make_doc(
            Heading(level=1, inlines=[t("Cap")]),
            Heading(level=2, inlines=[t("Sec")]),
        )
        out = render_toc(build_toc(doc))
        assert "## Sumário" in out
        assert "- [Cap](#cap)" in out
        assert "  - [Sec](#sec)" in out
