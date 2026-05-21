"""Testes do ``story_walker`` com XML sintético."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from idml_to_md.mathml_to_latex import EquationConverter
from idml_to_md.models import (
    AdmonitionBlock,
    Blockquote,
    Caption,
    CodeBlock,
    EquationBlock,
    Heading,
    ImageBlock,
    ListBlock,
    Paragraph,
    ReferenceEntry,
    TextRun,
)
from idml_to_md.models import (
    InlineKind as IK,
)
from idml_to_md.story_walker import _clean_content, walk_story
from idml_to_md.style_mapper import build_style_map

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def story_xml(*paragraphs: str) -> etree._Element:
    """Monta uma Story XML mínima envolvendo os ParagraphStyleRanges fornecidos."""
    body = "\n".join(paragraphs)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <Story Self="u1">
    {body}
  </Story>
</idPkg:Story>"""
    return etree.fromstring(xml.encode("utf-8"))


def psr(style: str, *children: str) -> str:
    body = "\n".join(children)
    return f'<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/{style}">{body}</ParagraphStyleRange>'


def csr(text: str, *, font_style: str = "", char_style: str = "$ID/[No character style]") -> str:
    fs_attr = f' FontStyle="{font_style}"' if font_style else ""
    return (
        f'<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/{char_style}"{fs_attr}>'
        f"<Content>{text}</Content><Br/></CharacterStyleRange>"
    )


# ---------------------------------------------------------------------------
# basic
# ---------------------------------------------------------------------------


class TestHeadingsAndParagraphs:
    def test_heading_t1(self) -> None:
        root = story_xml(psr("Títulos%3aT1", csr("Capítulo 1")))
        result = walk_story(root, build_style_map())
        assert len(result.body) == 1
        h = result.body[0]
        assert isinstance(h, Heading)
        assert h.level == 1
        text = "".join(r.text for r in h.inlines if isinstance(r, TextRun))
        assert text == "Capítulo 1"

    def test_heading_levels(self) -> None:
        root = story_xml(
            psr("Títulos%3aT1", csr("h1")),
            psr("Títulos%3aT2", csr("h2")),
            psr("Títulos%3aT3", csr("h3")),
            psr("Títulos%3aT4", csr("h4")),
        )
        result = walk_story(root, build_style_map())
        levels = [b.level for b in result.body if isinstance(b, Heading)]
        assert levels == [1, 2, 3, 4]

    def test_paragraph_collects_text(self) -> None:
        root = story_xml(psr("Texto principal", csr("Olá mundo")))
        result = walk_story(root, build_style_map())
        assert isinstance(result.body[0], Paragraph)
        assert any(isinstance(i, TextRun) and i.text == "Olá mundo" for i in result.body[0].inlines)

    def test_empty_paragraph_skipped(self) -> None:
        root = story_xml(
            psr(
                "Texto principal",
                '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]"><Br/></CharacterStyleRange>',
            ),
        )
        result = walk_story(root, build_style_map())
        assert result.body == []

    def test_drop_kind_removed(self) -> None:
        root = story_xml(psr("Rodapé", csr("número da página")))
        result = walk_story(root, build_style_map())
        assert result.body == []


class TestInlineFormatting:
    def test_bold_via_font_style(self) -> None:
        root = story_xml(psr("Texto principal", csr("destaque", font_style="Bold")))
        result = walk_story(root, build_style_map())
        runs = result.body[0].inlines
        bold_runs = [r for r in runs if isinstance(r, TextRun) and r.kind == IK.BOLD]
        assert any(r.text == "destaque" for r in bold_runs)

    def test_italic(self) -> None:
        root = story_xml(psr("Texto principal", csr("ênfase", font_style="Italic")))
        result = walk_story(root, build_style_map())
        italic = [
            r for r in result.body[0].inlines if isinstance(r, TextRun) and r.kind == IK.ITALIC
        ]
        assert italic and italic[0].text == "ênfase"

    def test_bold_italic(self) -> None:
        root = story_xml(psr("Texto principal", csr("forte", font_style="Bold Italic")))
        result = walk_story(root, build_style_map())
        bi = [
            r for r in result.body[0].inlines if isinstance(r, TextRun) and r.kind == IK.BOLD_ITALIC
        ]
        assert bi and bi[0].text == "forte"

    def test_superscript_position(self) -> None:
        psr_xml = (
            '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">'
            '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]" Position="Superscript">'
            "<Content>2</Content></CharacterStyleRange>"
            "</ParagraphStyleRange>"
        )
        root = story_xml(psr_xml)
        result = walk_story(root, build_style_map())
        sup = [
            r for r in result.body[0].inlines if isinstance(r, TextRun) and r.kind == IK.SUPERSCRIPT
        ]
        assert sup and sup[0].text == "2"


class TestLists:
    def test_consecutive_bullets_merge(self) -> None:
        root = story_xml(
            psr("Bullet", csr("primeiro")),
            psr("Bullet", csr("segundo")),
            psr("Bullet", csr("terceiro")),
        )
        result = walk_story(root, build_style_map())
        assert len(result.body) == 1
        lb = result.body[0]
        assert isinstance(lb, ListBlock)
        assert len(lb.items) == 3
        assert not lb.ordered

    def test_marker_change_starts_new_block(self) -> None:
        root = story_xml(
            psr("Bullet Números", csr("a")),
            psr("Bullet Números I, II, III", csr("b")),
        )
        result = walk_story(root, build_style_map())
        # Dois ListBlocks porque marker mudou de decimal para upper-roman
        lists = [b for b in result.body if isinstance(b, ListBlock)]
        assert len(lists) == 2
        assert lists[0].marker == "decimal"
        assert lists[1].marker == "upper-roman"

    def test_psr_with_multiple_br_splits_into_items(self) -> None:
        # Bullet ABC vem como uma única PSR com 4 alternativas separadas por <Br/>
        psr_xml = """
<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Bullet ABC">
  <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
    <Content>alt 1</Content><Br/>
    <Content>alt 2</Content><Br/>
    <Content>alt 3</Content><Br/>
    <Content>alt 4</Content>
  </CharacterStyleRange>
</ParagraphStyleRange>"""
        root = story_xml(psr_xml)
        result = walk_story(root, build_style_map())
        # Bullet ABC é nested, então a lista vai estar como sublist de uma
        # ListBlock pai (se existir). Sem pai, será top-level com 4 itens.
        lists = [b for b in result.body if isinstance(b, ListBlock)]
        assert len(lists) == 1
        assert len(lists[0].items) == 4

    def test_nested_list_continues_parent_numbering(self) -> None:
        # Bullet Números pai → Bullet ABC nested → Bullet Números continua (2)
        root = story_xml(
            psr("Bullet Números", csr("Pergunta 1")),
            psr("Bullet ABC", csr("alt A1")),
            psr("Bullet Números", csr("Pergunta 2")),
            psr("Bullet ABC", csr("alt A2")),
        )
        result = walk_story(root, build_style_map())
        lists = [b for b in result.body if isinstance(b, ListBlock)]
        # Uma única ListBlock pai, com 2 itens (Pergunta 1, Pergunta 2)
        assert len(lists) == 1
        assert len(lists[0].items) == 2
        # Cada item tem sublist com a alternativa
        assert lists[0].items[0].sublist is not None
        assert len(lists[0].items[0].sublist.items) == 1
        assert lists[0].items[1].sublist is not None

    def test_paragraph_breaks_list(self) -> None:
        root = story_xml(
            psr("Bullet", csr("a")),
            psr("Texto principal", csr("between")),
            psr("Bullet", csr("b")),
        )
        result = walk_story(root, build_style_map())
        kinds = [type(b).__name__ for b in result.body]
        assert kinds == ["ListBlock", "Paragraph", "ListBlock"]


class TestAdmonitions:
    def test_title_then_body_combine(self) -> None:
        root = story_xml(
            psr("Título texto BOX", csr("VOCÊ SABIA?")),
            psr("Texto BOX", csr("Conteúdo da caixa.")),
        )
        result = walk_story(root, build_style_map())
        ad = [b for b in result.body if isinstance(b, AdmonitionBlock)]
        assert len(ad) == 1
        assert ad[0].title == "VOCÊ SABIA?"
        assert len(ad[0].children) == 1

    def test_multiple_paragraphs_in_same_admonition(self) -> None:
        root = story_xml(
            psr("Texto BOX", csr("primeiro")),
            psr("Texto BOX", csr("segundo")),
        )
        result = walk_story(root, build_style_map())
        ad = [b for b in result.body if isinstance(b, AdmonitionBlock)]
        assert len(ad) == 1
        assert len(ad[0].children) == 2


class TestSpecialBlocks:
    def test_blockquote(self) -> None:
        root = story_xml(psr("Citação", csr("citado aqui")))
        result = walk_story(root, build_style_map())
        assert isinstance(result.body[0], Blockquote)

    def test_code_block(self) -> None:
        root = story_xml(psr("Programação Box", csr("print('hi')")))
        result = walk_story(root, build_style_map())
        cb = result.body[0]
        assert isinstance(cb, CodeBlock)
        assert cb.language == "python"
        assert "print" in cb.code

    def test_caption(self) -> None:
        root = story_xml(psr("Legenda", csr("Fonte: autor")))
        result = walk_story(root, build_style_map())
        assert isinstance(result.body[0], Caption)

    def test_front_matter_collected_separately(self) -> None:
        root = story_xml(psr("AUTORIA", csr("Fulano de Tal")))
        result = walk_story(root, build_style_map())
        assert result.body == []
        assert len(result.front_matter) == 1

    def test_reference_collected_separately(self) -> None:
        root = story_xml(psr("Referências", csr("OBRA, A. (2020).")))
        result = walk_story(root, build_style_map())
        assert result.body == []
        assert len(result.references) == 1
        assert isinstance(result.references[0], ReferenceEntry)


class TestImages:
    def test_extracts_image_from_anchored_rectangle(self) -> None:
        psr_xml = """
<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
  <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
    <Rectangle Self="rect1">
      <Image Self="img1">
        <Link Self="link1" LinkResourceURI="file:C:/x/Links/foo.jpg" />
      </Image>
    </Rectangle>
    <Content>texto</Content>
  </CharacterStyleRange>
</ParagraphStyleRange>"""
        root = story_xml(psr_xml)
        result = walk_story(root, build_style_map())
        imgs = [b for b in result.body if isinstance(b, ImageBlock)]
        assert len(imgs) == 1
        assert imgs[0].src == "foo.jpg"
        assert "foo.jpg" in result.image_basenames

    def test_ignores_image_with_non_raster_extension(self) -> None:
        psr_xml = """
<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
  <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
    <Rectangle><Image><Link LinkResourceURI="file:Links/equation.eps"/></Image></Rectangle>
    <Content>x</Content>
  </CharacterStyleRange>
</ParagraphStyleRange>"""
        root = story_xml(psr_xml)
        result = walk_story(root, build_style_map())
        assert all(not isinstance(b, ImageBlock) for b in result.body)


class TestHelpers:
    def test_clean_content_passthrough(self) -> None:
        assert _clean_content("simple text") == "simple text"
        assert _clean_content("") == ""

    def test_clean_content_strips_soft_hyphen(self) -> None:
        assert _clean_content("a­b") == "ab"

    def test_clean_content_strips_bom(self) -> None:
        assert _clean_content("﻿hello") == "hello"


# ---------------------------------------------------------------------------
# F2: equações
# ---------------------------------------------------------------------------


EPS_EQN_TEMPLATE = (
    "%!PS\n"
    "%%Creator: MathType\n"
    "%MathType!MathML!1!1!+-\n"
    "%<mathxmlns='http://www.w3.org/1998/Math/MathML'>\n"
    "%<mrow><mfrac><mn>1</mn><mn>2</mn></mfrac></mrow></math>\n"
)


@pytest.fixture
def links_dir_with_eq(tmp_path: Path) -> Path:
    links = tmp_path / "Links"
    links.mkdir()
    (links / "eq1.eps").write_text(EPS_EQN_TEMPLATE, encoding="latin-1")
    return links


class TestEquationsInWalker:
    def test_inline_equation_when_paragraph_has_text(self, links_dir_with_eq: Path) -> None:
        psr_xml = """
<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
  <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
    <Content>Considere </Content>
    <Rectangle><Image><Link LinkResourceURI="file:Links/eq1.eps"/></Image></Rectangle>
    <Content> como exemplo.</Content>
  </CharacterStyleRange>
</ParagraphStyleRange>"""
        root = story_xml(psr_xml)
        conv = EquationConverter()
        result = walk_story(root, build_style_map(), converter=conv, links_dir=links_dir_with_eq)
        # Não há EquationBlock display: tudo virou inline dentro do parágrafo
        assert not any(isinstance(b, EquationBlock) for b in result.body)
        para = [b for b in result.body if isinstance(b, Paragraph)]
        assert para, "esperava 1 Paragraph"
        inlines = para[0].inlines
        # Há ao menos um TextRun com kind=EQUATION_INLINE e LaTeX dentro
        eqs = [r for r in inlines if isinstance(r, TextRun) and r.kind == IK.EQUATION_INLINE]
        assert eqs and r"\frac{1}{2}" in eqs[0].text
        assert "eq1.eps" in result.equation_basenames

    def test_display_equation_when_paragraph_is_only_equation(
        self, links_dir_with_eq: Path
    ) -> None:
        psr_xml = """
<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
  <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
    <Rectangle><Image><Link LinkResourceURI="file:Links/eq1.eps"/></Image></Rectangle>
  </CharacterStyleRange>
</ParagraphStyleRange>"""
        root = story_xml(psr_xml)
        conv = EquationConverter()
        result = walk_story(root, build_style_map(), converter=conv, links_dir=links_dir_with_eq)
        # Não deve haver Paragraph vazio
        assert not any(isinstance(b, Paragraph) for b in result.body)
        eq_blocks = [b for b in result.body if isinstance(b, EquationBlock)]
        assert len(eq_blocks) == 1
        assert eq_blocks[0].latex == r"\frac{1}{2}"
        assert eq_blocks[0].source == "eq1.eps"

    def test_missing_eps_is_recorded_as_failed(self, tmp_path: Path) -> None:
        links = tmp_path / "Links"
        links.mkdir()  # vazia
        psr_xml = """
<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
  <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
    <Content>x </Content>
    <Rectangle><Image><Link LinkResourceURI="file:Links/missing.eps"/></Image></Rectangle>
  </CharacterStyleRange>
</ParagraphStyleRange>"""
        root = story_xml(psr_xml)
        conv = EquationConverter()
        result = walk_story(root, build_style_map(), converter=conv, links_dir=links)
        assert result.failed_equations == ["missing.eps"]

    def test_no_converter_silently_skips_equations(self, links_dir_with_eq: Path) -> None:
        psr_xml = """
<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
  <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
    <Content>texto </Content>
    <Rectangle><Image><Link LinkResourceURI="file:Links/eq1.eps"/></Image></Rectangle>
  </CharacterStyleRange>
</ParagraphStyleRange>"""
        root = story_xml(psr_xml)
        # converter=None / links_dir=None → pula silenciosamente
        result = walk_story(root, build_style_map(), converter=None, links_dir=None)
        assert result.equation_basenames == []
        assert result.failed_equations == []
        # texto preservado
        para = [b for b in result.body if isinstance(b, Paragraph)]
        assert para


class TestEmptyStory:
    def test_empty_story_returns_empty_result(self) -> None:
        root = etree.fromstring(
            b'<?xml version="1.0"?><idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"></idPkg:Story>'
        )
        result = walk_story(root, build_style_map())
        assert result.body == []
        assert result.front_matter == []
        assert result.references == []
