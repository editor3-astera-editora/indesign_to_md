"""Testes do extractor de segmentos."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from idml_to_md.style_mapper import build_style_map
from idml_to_md.translation.classifier import classify
from idml_to_md.translation.models import SkipReason
from idml_to_md.translation.segment_extractor import (
    _build_segment,
    _extract_inline,
    extract_segments,
)


def _psr(inner: str) -> etree._Element:
    """Parseia um ``<ParagraphStyleRange>`` isolado para testar _extract_inline."""
    return etree.fromstring(
        '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">'
        f"{inner}</ParagraphStyleRange>"
    )


def _styled_psr(applied_style: str, content: str) -> etree._Element:
    """PSR com ``AppliedParagraphStyle`` arbitrário e um único Content."""
    return etree.fromstring(
        f'<ParagraphStyleRange AppliedParagraphStyle="{applied_style}">'
        '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
        f"<Content>{content}</Content></CharacterStyleRange></ParagraphStyleRange>"
    )


class TestExtract:
    def test_extracts_two_stories(self, minimal_idml: Path) -> None:
        segments = extract_segments(minimal_idml, build_style_map())
        # Story 1 tem 2 PSRs; Story 2 tem 2 PSRs → 4 segments
        assert len(segments) == 4

    def test_first_segment_is_heading(self, minimal_idml: Path) -> None:
        segments = extract_segments(minimal_idml, build_style_map())
        first = segments[0]
        assert first.paragraph_kind == "heading"
        assert first.plain_text == "Matemática Financeira"
        assert first.paragraph_style == "Títulos:T1"

    def test_segment_id_is_stable(self, minimal_idml: Path) -> None:
        segments = extract_segments(minimal_idml, build_style_map())
        ids = [s.segment_id for s in segments]
        assert len(ids) == len(set(ids))  # únicos
        assert all(":" in i for i in ids)

    def test_bold_run_detected(self, minimal_idml: Path) -> None:
        segments = extract_segments(minimal_idml, build_style_map())
        # Segundo parágrafo de Story 1 tem 3 runs (texto, bold, texto)
        body_segments = [s for s in segments if s.story_id == "ust1"]
        para = body_segments[1]
        assert len(para.runs) == 3
        bold_runs = [r for r in para.runs if r.bold]
        assert len(bold_runs) == 1
        assert bold_runs[0].text == "juros simples"

    def test_dumps_xml_when_dir_given(self, minimal_idml: Path, tmp_path: Path) -> None:
        dump = tmp_path / "xml_original"
        extract_segments(minimal_idml, build_style_map(), xml_dump_dir=dump)
        files = sorted(p.name for p in dump.iterdir())
        assert files == ["Story_ust1.xml", "Story_ust2.xml"]

    def test_skip_empty_paragraphs(self, tmp_path: Path) -> None:
        import zipfile

        from tests.unit.translation.conftest import (
            DESIGNMAP_TEMPLATE,
            MIMETYPE,
            SPREAD_TEMPLATE,
            STYLES_XML,
        )

        idml = tmp_path / "empty.idml"
        with zipfile.ZipFile(idml, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            info = zipfile.ZipInfo("mimetype")
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, MIMETYPE)
            zf.writestr("designmap.xml", DESIGNMAP_TEMPLATE)
            zf.writestr("Resources/Styles.xml", STYLES_XML)
            zf.writestr("Spreads/Spread_us1.xml", SPREAD_TEMPLATE)
            empty_story = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="18.0">'
                '<Story Self="ust1">'
                '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">'
                '<CharacterStyleRange><Content>   </Content></CharacterStyleRange>'
                "</ParagraphStyleRange>"
                "</Story></idPkg:Story>"
            )
            zf.writestr("Stories/Story_ust1.xml", empty_story)
            zf.writestr(
                "Stories/Story_ust2.xml",
                empty_story.replace("ust1", "ust2"),
            )

        segments = extract_segments(idml, build_style_map())
        assert all(s.skip for s in segments)
        assert all(s.skip_reason == SkipReason.EMPTY for s in segments)


class TestMasterCoverExtraction:
    """Capa de unidade ("UNIDADE") que vive só num MasterSpread (Unidade 1)."""

    _COVER_STYLES = frozenset({"Título capa", "ESTILOS PRINCIPAIS:Título capa"})

    def test_master_ignored_by_default(self, master_cover_idml: Path) -> None:
        # Sem o flag, masters não são vistos → só o corpo do Spread normal.
        segments = extract_segments(master_cover_idml, build_style_map())
        story_ids = {s.story_id for s in segments}
        assert story_ids == {"ust1"}
        assert not any(s.story_id == "umcover" for s in segments)

    def test_master_cover_extracted_when_enabled(self, master_cover_idml: Path) -> None:
        segments = extract_segments(
            master_cover_idml,
            build_style_map(),
            include_master_spreads=True,
            master_cover_styles=self._COVER_STYLES,
        )
        classify(segments)
        by_story = {s.story_id: s for s in segments}

        # "UNIDADE" extraído e traduzível.
        assert "umcover" in by_story
        cover = by_story["umcover"]
        assert cover.plain_text == "UNIDADE"
        assert cover.paragraph_style == "Título capa"
        assert cover.skip is False

        # número "1" extraído (é capa) mas pulado pelo classifier (numérico).
        assert "umnum" in by_story
        assert by_story["umnum"].plain_text == "1"
        assert by_story["umnum"].skip is True
        assert by_story["umnum"].skip_reason == SkipReason.NUMERIC_LITERAL

    def test_master_non_cover_style_excluded(self, master_cover_idml: Path) -> None:
        # Cabeçalho corrido (Texto principal) no master NÃO entra na allowlist.
        segments = extract_segments(
            master_cover_idml,
            build_style_map(),
            include_master_spreads=True,
            master_cover_styles=self._COVER_STYLES,
        )
        assert not any(s.story_id == "umhdr" for s in segments)

    def test_master_cover_appended_after_body(self, master_cover_idml: Path) -> None:
        # Stories de master entram DEPOIS das de página normal.
        segments = extract_segments(
            master_cover_idml,
            build_style_map(),
            include_master_spreads=True,
            master_cover_styles=self._COVER_STYLES,
        )
        order = [s.story_id for s in segments]
        assert order.index("ust1") < order.index("umcover")

    def test_end_to_end_writes_unidad(self, master_cover_idml: Path, tmp_path: Path) -> None:
        # extract (master) → glossário determinístico → writer → "UNIDAD" no XML.
        import zipfile

        from idml_to_md.translation.idml_writer import write_translated_idml
        from idml_to_md.translation.openai_client import TranslatorClient, TranslatorConfig

        segments = extract_segments(
            master_cover_idml,
            build_style_map(),
            include_master_spreads=True,
            master_cover_styles=self._COVER_STYLES,
        )
        classify(segments)
        cover = [s for s in segments if not s.skip and s.plain_text.strip() == "UNIDADE"]
        # client=object(): o glossário não chama API, então não é tocado.
        client = TranslatorClient(
            TranslatorConfig(glossary={"UNIDADE": "UNIDAD"}), client=object()
        )
        translations = client.translate_segments(cover)

        out = tmp_path / "out.idml"
        stats = write_translated_idml(
            source_idml=master_cover_idml,
            target_idml=out,
            segments=cover,
            translations=translations,
        )
        assert stats["contents_replaced"] == 1
        with zipfile.ZipFile(out) as zf:
            xml = zf.read("Stories/Story_umcover.xml").decode("utf-8")
        assert "<Content>UNIDAD</Content>" in xml


class TestExtractInline:
    """Runs em ordem de documento + fronteiras (Br/âncora)."""

    def test_three_contents_split_by_br(self) -> None:  # bug #1
        psr = _psr(
            '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
            "<Content>Um.</Content><Br/><Content>Dois.</Content><Br/><Content>Tres.</Content><Br/>"
            "</CharacterStyleRange>"
        )
        runs, boundaries = _extract_inline(psr)
        assert [r.text for r in runs] == ["Um.", "Dois.", "Tres."]
        # content_idx físico distinto para cada Content do MESMO CSR
        assert [(r.run_idx, r.content_idx) for r in runs] == [(0, 0), (0, 1), (0, 2)]
        brs = [b for b in boundaries if b.kind == "br"]
        assert [b.after_text_ord for b in brs] == [0, 1, 2]

    def test_bullet_two_items_split_by_br(self) -> None:  # bug #3
        psr = _psr(
            "<CharacterStyleRange><Content>Item um?</Content><Br/>"
            "<Content>Item dois?</Content><Br/></CharacterStyleRange>"
        )
        runs, boundaries = _extract_inline(psr)
        assert [r.text for r in runs] == ["Item um?", "Item dois?"]
        assert sum(1 for b in boundaries if b.kind == "br") == 2

    def test_anchor_between_two_text_runs(self) -> None:  # bug #8/#9
        psr = _psr(
            "<CharacterStyleRange><Content>A fração </Content></CharacterStyleRange>"
            '<CharacterStyleRange><Rectangle Self="r1"/></CharacterStyleRange>'
            "<CharacterStyleRange><Content> é menor que 1.</Content></CharacterStyleRange>"
        )
        runs, boundaries = _extract_inline(psr)
        assert [r.text for r in runs] == ["A fração ", " é menor que 1."]
        anchors = [b for b in boundaries if b.kind == "anchor"]
        assert len(anchors) == 1
        assert anchors[0].after_text_ord == 0  # entre run0 e run1
        assert anchors[0].anchor_ord == 0

    def test_empty_content_keeps_physical_content_idx(self) -> None:
        psr = _psr(
            "<CharacterStyleRange><Content>A</Content><Content></Content>"
            "<Content>C</Content></CharacterStyleRange>"
        )
        runs, _ = _extract_inline(psr)
        # O Content vazio não vira run, mas o "C" mantém content_idx físico = 2
        assert [(r.run_idx, r.content_idx, r.text) for r in runs] == [
            (0, 0, "A"),
            (0, 2, "C"),
        ]

    def test_consecutive_br(self) -> None:
        psr = _psr(
            "<CharacterStyleRange><Content>X</Content><Br/><Br/>"
            "<Content>Y</Content></CharacterStyleRange>"
        )
        _, boundaries = _extract_inline(psr)
        brs = [b for b in boundaries if b.kind == "br"]
        assert len(brs) == 2
        assert all(b.after_text_ord == 0 for b in brs)

    def test_hyperlink_text_source_content_extracted(self) -> None:
        # Entradas de sumário/hyperlinks: o <Content> fica DENTRO do
        # <HyperlinkTextSource>; o extractor deve descer e ler o texto.
        psr = _psr(
            "<CharacterStyleRange>"
            '<HyperlinkTextSource Self="h1"><Properties/>'
            "<Content>Conjuntos\t16</Content></HyperlinkTextSource><Br/>"
            '<HyperlinkTextSource Self="h2">'
            "<Content>Porcentagem\t23</Content></HyperlinkTextSource><Br/>"
            "</CharacterStyleRange>"
        )
        runs, boundaries = _extract_inline(psr)
        assert [r.text for r in runs] == ["Conjuntos\t16", "Porcentagem\t23"]
        # content_idx conta os dois Content aninhados no mesmo CSR, em ordem
        assert [(r.run_idx, r.content_idx) for r in runs] == [(0, 0), (0, 1)]
        brs = [b for b in boundaries if b.kind == "br"]
        assert [b.after_text_ord for b in brs] == [0, 1]


class TestExtractTables:
    """Fase 2: parágrafos de células de tabela viram Segments (bugs #4/#5)."""

    def test_extracts_cell_segments(self, table_idml: Path) -> None:
        segments = extract_segments(table_idml, build_style_map())
        cell_segs = [s for s in segments if s.cell_self]
        assert {s.cell_self for s in cell_segs} == {"utbl1c0", "utbl1c1"}

        by_cell = {s.cell_self: s for s in cell_segs}
        assert by_cell["utbl1c0"].plain_text == "Parte inteira"
        assert by_cell["utbl1c0"].table_self == "utbl1"
        assert by_cell["utbl1c0"].segment_id == "ust1:utbl1c0:0"
        assert by_cell["utbl1c0"].paragraph_idx == 0
        assert by_cell["utbl1c1"].plain_text == "42"

    def test_numeric_cell_skipped_text_cell_not(self, table_idml: Path) -> None:
        segments = classify(extract_segments(table_idml, build_style_map()))
        by_cell = {s.cell_self: s for s in segments if s.cell_self}
        assert not by_cell["utbl1c0"].skip  # "Parte inteira" → traduzível
        assert by_cell["utbl1c1"].skip  # "42" → numérico, pulado
        assert by_cell["utbl1c1"].skip_reason == SkipReason.NUMERIC_LITERAL


# Estilo da capa: drop no styles.default.yaml. ``%3a`` = ":" URL-encoded.
_COVER_STYLE = "ParagraphStyle/Sumario%3aFolha de rosto"
_TOC_ITEM_STYLE = "ParagraphStyle/Sumario%3aItem 1"


class TestForceTranslateDroppedStyles:
    """Estilos ``kind: drop`` forçados a traduzir (título da capa / sumário)."""

    def test_dropped_style_skipped_by_default(self) -> None:
        psr = _styled_psr(_COVER_STYLE, "Matemática Financeira")
        seg = _build_segment(psr, "ued8d", build_style_map(), paragraph_idx=0)
        assert seg.paragraph_style == "Sumario:Folha de rosto"
        assert seg.skip is True
        assert seg.skip_reason == SkipReason.PARAGRAPH_STYLE

    def test_dropped_style_translated_when_forced(self) -> None:
        psr = _styled_psr(_COVER_STYLE, "Matemática Financeira")
        seg = _build_segment(
            psr,
            "ued8d",
            build_style_map(),
            paragraph_idx=0,
            force_translate_styles=frozenset({"Sumario:Folha de rosto"}),
        )
        assert seg.skip is False
        # vira ``paragraph`` para o classifier não re-pular; nome original mantido
        assert seg.paragraph_kind == "paragraph"
        assert seg.paragraph_style == "Sumario:Folha de rosto"
        assert any("drop→traduzir" in n for n in seg.notes)

    def test_classifier_keeps_forced_segment(self) -> None:
        psr = _styled_psr(_COVER_STYLE, "Matemática Financeira")
        seg = _build_segment(
            psr,
            "ued8d",
            build_style_map(),
            paragraph_idx=0,
            force_translate_styles=frozenset({"Sumario:Folha de rosto"}),
        )
        # classifier não deve re-pular (kind=paragraph, texto com letras)
        classify([seg])
        assert seg.skip is False

    def test_empty_forced_dropped_style_still_skipped(self) -> None:
        psr = _styled_psr(_COVER_STYLE, "   ")
        seg = _build_segment(
            psr,
            "ued8d",
            build_style_map(),
            paragraph_idx=0,
            force_translate_styles=frozenset({"Sumario:Folha de rosto"}),
        )
        # vazio tem precedência sobre o override
        assert seg.skip is True
        assert seg.skip_reason == SkipReason.EMPTY

    def test_force_threads_through_extract_segments(self, tmp_path: Path) -> None:
        from tests.unit.translation.conftest import build_idml_single_story

        inner = (
            '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Sumario%3aFolha de rosto">'
            "<CharacterStyleRange><Content>Matemática Financeira</Content></CharacterStyleRange>"
            "</ParagraphStyleRange>"
        )
        idml = build_idml_single_story(tmp_path / "cover.idml", inner)

        skipped = extract_segments(idml, build_style_map())
        assert skipped[0].skip is True

        forced = extract_segments(
            idml,
            build_style_map(),
            force_translate_styles=frozenset({"Sumario:Folha de rosto"}),
        )
        assert forced[0].skip is False
        assert forced[0].plain_text == "Matemática Financeira"

    def test_force_threads_into_table_cells(self, tmp_path: Path) -> None:
        from tests.unit.translation.conftest import build_idml_single_story

        inner = (
            '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">'
            "<CharacterStyleRange>"
            '<Table Self="utbl1" ColumnCount="1" BodyRowCount="1">'
            '<Row Self="utbl1Row0"/><Column Self="utbl1Col0"/>'
            '<Cell Self="utbl1c0" Name="0:0">'
            f'<ParagraphStyleRange AppliedParagraphStyle="{_TOC_ITEM_STYLE}">'
            "<CharacterStyleRange><Content>Conjuntos</Content></CharacterStyleRange>"
            "</ParagraphStyleRange></Cell>"
            "</Table></CharacterStyleRange></ParagraphStyleRange>"
        )
        idml = build_idml_single_story(tmp_path / "toc_table.idml", inner)

        forced = extract_segments(
            idml,
            build_style_map(),
            force_translate_styles=frozenset({"Sumario:Item 1"}),
        )
        cell = next(s for s in forced if s.cell_self == "utbl1c0")
        assert cell.skip is False
        assert cell.paragraph_kind == "paragraph"
        assert cell.plain_text == "Conjuntos"
