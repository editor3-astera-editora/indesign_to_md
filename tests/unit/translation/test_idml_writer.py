"""Testes do idml_writer."""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

from idml_to_md.style_mapper import build_style_map
from idml_to_md.translation.idml_writer import (
    _replace_runs_in_psr,
    copy_xml_original,
    write_translated_idml,
)
from idml_to_md.translation.models import SegmentRun, Translation
from idml_to_md.translation.segment_extractor import extract_segments


def _psr(inner: str) -> etree._Element:
    return etree.fromstring(f"<ParagraphStyleRange>{inner}</ParagraphStyleRange>")


def _tr(runs: list[SegmentRun]) -> Translation:
    return Translation(segment_id="u:0", source_text="", target_runs=runs)


class TestWriteIDML:
    def test_writes_idml_with_translations(self, minimal_idml: Path, tmp_path: Path) -> None:
        segments = extract_segments(minimal_idml, build_style_map())
        # Cria translations para os 2 primeiros segmentos (cabeçalho + parágrafo)
        translations = [
            Translation(
                segment_id=segments[0].segment_id,
                source_text=segments[0].plain_text,
                target_text="Matemáticas Financieras",
                target_runs=[
                    SegmentRun(
                        run_idx=0,
                        content_idx=0,
                        text="Matemáticas Financieras",
                    )
                ],
                model="gpt-4o-mini",
            ),
            Translation(
                segment_id=segments[1].segment_id,
                source_text=segments[1].plain_text,
                target_text="Los intereses simples se calculan sobre el capital inicial.",
                target_runs=[
                    SegmentRun(run_idx=0, content_idx=0, text="Los "),
                    SegmentRun(
                        run_idx=1,
                        content_idx=0,
                        text="intereses simples",
                        bold=True,
                    ),
                    SegmentRun(
                        run_idx=2,
                        content_idx=0,
                        text=" se calculan sobre el capital inicial.",
                    ),
                ],
                model="gpt-4o-mini",
            ),
        ]

        target = tmp_path / "translated.idml"
        stats = write_translated_idml(
            source_idml=minimal_idml,
            target_idml=target,
            segments=segments,
            translations=translations,
        )
        assert target.exists()
        assert stats["stories_modified"] == 1
        assert stats["contents_replaced"] >= 2

    def test_preserves_mimetype_first(self, minimal_idml: Path, tmp_path: Path) -> None:
        segments = extract_segments(minimal_idml, build_style_map())
        translations = [
            Translation(
                segment_id=segments[0].segment_id,
                source_text=segments[0].plain_text,
                target_text="X",
                target_runs=[SegmentRun(run_idx=0, content_idx=0, text="X")],
            )
        ]
        target = tmp_path / "translated.idml"
        write_translated_idml(
            source_idml=minimal_idml,
            target_idml=target,
            segments=segments,
            translations=translations,
        )
        with zipfile.ZipFile(target, "r") as zf:
            names = zf.namelist()
            assert names[0] == "mimetype"
            info = zf.getinfo("mimetype")
            assert info.compress_type == zipfile.ZIP_STORED

    def test_dumps_translated_xml_when_dir_given(
        self, minimal_idml: Path, tmp_path: Path
    ) -> None:
        segments = extract_segments(minimal_idml, build_style_map())
        translations = [
            Translation(
                segment_id=segments[0].segment_id,
                source_text=segments[0].plain_text,
                target_text="X",
                target_runs=[SegmentRun(run_idx=0, content_idx=0, text="X")],
            )
        ]
        target = tmp_path / "translated.idml"
        dump = tmp_path / "xml_traduzido"
        write_translated_idml(
            source_idml=minimal_idml,
            target_idml=target,
            segments=segments,
            translations=translations,
            xml_dump_dir=dump,
        )
        files = sorted(p.name for p in dump.iterdir())
        # Apenas Story_ust1 foi modificada (segment[0] está nela)
        assert "Story_ust1.xml" in files

    def test_translation_appears_in_xml(
        self, minimal_idml: Path, tmp_path: Path
    ) -> None:
        segments = extract_segments(minimal_idml, build_style_map())
        translations = [
            Translation(
                segment_id=segments[0].segment_id,
                source_text=segments[0].plain_text,
                target_text="Matemáticas Financieras",
                target_runs=[
                    SegmentRun(
                        run_idx=0,
                        content_idx=0,
                        text="Matemáticas Financieras",
                    )
                ],
            )
        ]
        target = tmp_path / "translated.idml"
        write_translated_idml(
            source_idml=minimal_idml,
            target_idml=target,
            segments=segments,
            translations=translations,
        )
        with zipfile.ZipFile(target, "r") as zf, zf.open("Stories/Story_ust1.xml") as fh:
            content = fh.read().decode("utf-8")
        assert "Matemáticas Financieras" in content
        # texto original NÃO deve mais aparecer no nó do cabeçalho
        # (mas pode aparecer em outros parágrafos não traduzidos)
        # Verifica especificamente que o título foi substituído procurando
        # ambos: o novo texto presente E o texto antigo "Matemática Financeira" não estar no primeiro PSR
        assert content.count("Matemática Financeira") == 0


class TestReplaceRunsInPsr:
    """Escrita posicional por (csr_idx, content_idx) — sem consolidar no 1º."""

    def test_three_contents_written_individually(self) -> None:  # bug #1
        psr = _psr(
            "<CharacterStyleRange><Content>Um.</Content><Br/>"
            "<Content>Dois.</Content><Br/><Content>Tres.</Content><Br/>"
            "</CharacterStyleRange>"
        )
        n = _replace_runs_in_psr(
            psr,
            _tr(
                [
                    SegmentRun(run_idx=0, content_idx=0, text="Uno."),
                    SegmentRun(run_idx=0, content_idx=1, text="Dos."),
                    SegmentRun(run_idx=0, content_idx=2, text="Tres."),
                ]
            ),
        )
        assert n == 3
        assert [c.text for c in psr.findall(".//Content")] == ["Uno.", "Dos.", "Tres."]
        # quebras preservadas (estrutura intacta)
        assert len(psr.findall(".//Br")) == 3

    def test_bullet_second_item_not_emptied(self) -> None:  # bug #3 / regressão
        psr = _psr(
            "<CharacterStyleRange><Content>Item 1</Content><Br/>"
            "<Content>Item 2</Content></CharacterStyleRange>"
        )
        _replace_runs_in_psr(
            psr,
            _tr(
                [
                    SegmentRun(run_idx=0, content_idx=0, text="Punto 1"),
                    SegmentRun(run_idx=0, content_idx=1, text="Punto 2"),
                ]
            ),
        )
        assert [c.text for c in psr.findall(".//Content")] == ["Punto 1", "Punto 2"]

    def test_anchored_object_untouched(self) -> None:  # bug #8/#9
        psr = _psr(
            "<CharacterStyleRange><Content>A fração </Content></CharacterStyleRange>"
            '<CharacterStyleRange><Rectangle Self="r1"/></CharacterStyleRange>'
            "<CharacterStyleRange><Content> é menor.</Content></CharacterStyleRange>"
        )
        n = _replace_runs_in_psr(
            psr,
            _tr(
                [
                    SegmentRun(run_idx=0, content_idx=0, text="La fracción "),
                    SegmentRun(run_idx=2, content_idx=0, text=" es menor."),
                ]
            ),
        )
        assert n == 2
        assert [c.text for c in psr.findall(".//Content")] == [
            "La fracción ",
            " es menor.",
        ]
        # a fórmula (Rectangle) continua presente e entre os textos
        assert psr.find(".//Rectangle") is not None

    def test_slot_without_translation_left_intact(self) -> None:
        psr = _psr(
            "<CharacterStyleRange><Content>A</Content><Content>B</Content>"
            "</CharacterStyleRange>"
        )
        n = _replace_runs_in_psr(
            psr, _tr([SegmentRun(run_idx=0, content_idx=0, text="X")])
        )
        assert n == 1
        contents = psr.findall(".//Content")
        assert contents[0].text == "X"
        assert contents[1].text == "B"  # sem slot → preservado

    def test_hyperlink_text_source_content_replaced(self) -> None:
        # Round-trip do sumário: o texto está dentro de <HyperlinkTextSource>;
        # o writer deve escrever no <Content> aninhado e preservar o wrapper.
        psr = _psr(
            "<CharacterStyleRange>"
            '<HyperlinkTextSource Self="h1"><Properties/>'
            "<Content>Conjuntos\t16</Content></HyperlinkTextSource><Br/>"
            '<HyperlinkTextSource Self="h2">'
            "<Content>Estatística\t33</Content></HyperlinkTextSource>"
            "</CharacterStyleRange>"
        )
        n = _replace_runs_in_psr(
            psr,
            _tr(
                [
                    SegmentRun(run_idx=0, content_idx=0, text="Conjuntos\t16"),
                    SegmentRun(run_idx=0, content_idx=1, text="Estadística\t33"),
                ]
            ),
        )
        assert n == 2
        assert [c.text for c in psr.findall(".//Content")] == [
            "Conjuntos\t16",
            "Estadística\t33",
        ]
        # wrappers e Self preservados (InDesign valida os IDs)
        sources = psr.findall(".//HyperlinkTextSource")
        assert [s.get("Self") for s in sources] == ["h1", "h2"]


class TestTableCellWriteback:
    """Fase 2: escrita em parágrafos de célula localizados pelo Self da Cell."""

    def test_writes_table_cell_translation(
        self, table_idml: Path, tmp_path: Path
    ) -> None:
        segments = extract_segments(table_idml, build_style_map())
        target = next(s for s in segments if s.cell_self == "utbl1c0")
        translations = [
            Translation(
                segment_id=target.segment_id,
                source_text=target.plain_text,
                target_text="Parte entera",
                target_runs=[SegmentRun(run_idx=0, content_idx=0, text="Parte entera")],
            )
        ]
        out = tmp_path / "tbl_es.idml"
        write_translated_idml(
            source_idml=table_idml,
            target_idml=out,
            segments=segments,
            translations=translations,
        )
        with zipfile.ZipFile(out, "r") as zf:
            story = zf.read("Stories/Story_ust1.xml").decode("utf-8")
        assert "Parte entera" in story
        assert "Parte inteira" not in story
        # célula numérica intacta
        assert "<Content>42</Content>" in story

    def test_locate_psr_missing_cell_returns_none(self) -> None:
        from idml_to_md.translation.idml_writer import _locate_psr
        from idml_to_md.translation.models import Segment

        story = _psr("<CharacterStyleRange><Content>x</Content></CharacterStyleRange>")
        seg = Segment(
            segment_id="u:naoexiste:0",
            story_id="u",
            paragraph_idx=0,
            cell_self="naoexiste",
        )
        assert _locate_psr(story, [], seg) is None


class TestCopyOriginal:
    def test_copies_all_stories(self, minimal_idml: Path, tmp_path: Path) -> None:
        dump = tmp_path / "original"
        n = copy_xml_original(minimal_idml, dump)
        assert n == 2
        files = sorted(p.name for p in dump.iterdir())
        assert files == ["Story_ust1.xml", "Story_ust2.xml"]
