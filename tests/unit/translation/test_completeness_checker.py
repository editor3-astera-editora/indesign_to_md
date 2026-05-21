"""Testes do completeness_checker.

Monta IDMLs-zip mínimos em memória (source + variantes traduzidas mutadas) e
verifica que cada tipo de perda de conteúdo é detectado, e que um traduzido
estruturalmente íntegro (mesmo mais longo) passa.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from idml_to_md.translation.completeness_checker import check_completeness

MIMETYPE = b"application/vnd.adobe.indesign-idml-package"

_HDR = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_NS = 'xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"'

DESIGNMAP = (
    f"{_HDR}<Document {_NS} Self=\"doc1\">"
    '<idPkg:Spread src="Spreads/Spread_us1.xml"/></Document>'
)

STYLES = (
    f"{_HDR}<idPkg:Styles {_NS} DOMVersion=\"18.0\">"
    '<RootParagraphStyleGroup Self="ups">'
    '<ParagraphStyle Self="ParagraphStyle/Texto" Name="Texto"/>'
    "</RootParagraphStyleGroup></idPkg:Styles>"
)

SPREAD = (
    f"{_HDR}<idPkg:Spread {_NS} DOMVersion=\"18.0\">"
    '<Spread Self="us1" PageCount="1"><Page Self="up1" Name="1"/>'
    '<TextFrame Self="utf1" ParentStory="ust1"/>'
    '<TextFrame Self="utf2" ParentStory="ust2"/></Spread></idPkg:Spread>'
)

# Story 1: título (1 parágrafo) + corpo com run em negrito e uma quebra.
STORY1 = (
    f"{_HDR}<idPkg:Story {_NS} DOMVersion=\"18.0\"><Story Self=\"ust1\">"
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto">'
    '<CharacterStyleRange Self="cs1"><Content>Título</Content></CharacterStyleRange>'
    "</ParagraphStyleRange>"
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto">'
    '<CharacterStyleRange Self="cs2"><Content>Os </Content></CharacterStyleRange>'
    '<CharacterStyleRange Self="cs3"><Content>juros simples</Content><Br/></CharacterStyleRange>'
    '<CharacterStyleRange Self="cs4"><Content> são fáceis.</Content></CharacterStyleRange>'
    "</ParagraphStyleRange></Story></idPkg:Story>"
)

# Story 2: parágrafo único.
STORY2 = (
    f"{_HDR}<idPkg:Story {_NS} DOMVersion=\"18.0\"><Story Self=\"ust2\">"
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto">'
    '<CharacterStyleRange Self="cs5"><Content>Texto da segunda story.</Content>'
    "</CharacterStyleRange></ParagraphStyleRange></Story></idPkg:Story>"
)


def _base_members() -> dict[str, bytes]:
    """Membros de um IDML mínimo válido (cópia nova a cada chamada)."""
    return {
        "designmap.xml": DESIGNMAP.encode("utf-8"),
        "Resources/Styles.xml": STYLES.encode("utf-8"),
        "Spreads/Spread_us1.xml": SPREAD.encode("utf-8"),
        "Stories/Story_ust1.xml": STORY1.encode("utf-8"),
        "Stories/Story_ust2.xml": STORY2.encode("utf-8"),
    }


def _build(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, MIMETYPE)
        for name, data in members.items():
            zf.writestr(name, data)
    return path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return _build(tmp_path / "src.idml", _base_members())


def _translated(tmp_path: Path, members: dict[str, bytes]) -> Path:
    return _build(tmp_path / "trad.idml", members)


class TestPass:
    def test_identical_is_ok(self, source: Path, tmp_path: Path) -> None:
        trad = _translated(tmp_path, _base_members())
        report = check_completeness(source, trad)
        assert report.ok
        assert report.package_match
        assert report.text_ratio == 1.0
        assert "OK" in report.summary
        assert report.lost_paragraphs == []

    def test_longer_translation_still_ok(self, source: Path, tmp_path: Path) -> None:
        m = _base_members()
        # ES costuma ser mais longo: expande textos preservando a estrutura.
        m["Stories/Story_ust2.xml"] = STORY2.replace(
            "Texto da segunda story.",
            "Texto bastante mais largo de la segunda historia traducida.",
        ).encode("utf-8")
        trad = _translated(tmp_path, m)
        report = check_completeness(source, trad)
        assert report.ok
        assert report.text_ratio > 1.0
        assert report.translated_text_len > report.source_text_len


class TestContentLoss:
    def test_lost_paragraph_detected(self, source: Path, tmp_path: Path) -> None:
        m = _base_members()
        # Esvazia o Content do título (parágrafo 0 da story 1), preservando a tag.
        m["Stories/Story_ust1.xml"] = STORY1.replace(
            "<Content>Título</Content>", "<Content></Content>"
        ).encode("utf-8")
        trad = _translated(tmp_path, m)
        report = check_completeness(source, trad)
        assert not report.ok
        assert any("Story_ust1.xml#0" in p for p in report.lost_paragraphs)
        assert "PERDIDO" in report.summary

    def test_missing_story_inventory_mismatch(self, source: Path, tmp_path: Path) -> None:
        m = _base_members()
        del m["Stories/Story_ust2.xml"]
        trad = _translated(tmp_path, m)
        report = check_completeness(source, trad)
        assert not report.ok
        assert not report.package_match
        assert report.source_stories == 2
        assert report.translated_stories == 1
        assert any("ausente" in d for d in report.story_count_diffs)


class TestIntegrity:
    def test_self_id_missing_and_extra(self, source: Path, tmp_path: Path) -> None:
        m = _base_members()
        # Renomeia um Self → vira 1 ausente + 1 extra, sem mudar contagens.
        m["Spreads/Spread_us1.xml"] = SPREAD.replace(
            'Self="utf2"', 'Self="utfX"'
        ).encode("utf-8")
        trad = _translated(tmp_path, m)
        report = check_completeness(source, trad)
        assert not report.ok
        assert "utf2" in report.self_ids_missing
        assert "utfX" in report.self_ids_extra

    def test_self_id_duplicate(self, source: Path, tmp_path: Path) -> None:
        m = _base_members()
        # Duplica utf1 (utf2 passa a ter o mesmo Self).
        m["Spreads/Spread_us1.xml"] = SPREAD.replace(
            'Self="utf2"', 'Self="utf1"'
        ).encode("utf-8")
        trad = _translated(tmp_path, m)
        report = check_completeness(source, trad)
        assert not report.ok
        assert "utf1" in report.self_ids_new_duplicates

    def test_structural_count_diff(self, source: Path, tmp_path: Path) -> None:
        m = _base_members()
        # Remove a quebra <Br/> da story 1.
        m["Stories/Story_ust1.xml"] = STORY1.replace("<Br/>", "").encode("utf-8")
        trad = _translated(tmp_path, m)
        report = check_completeness(source, trad)
        assert not report.ok
        assert any("Br" in d and "Story_ust1.xml" in d for d in report.story_count_diffs)

    def test_malformed_xml_detected(self, source: Path, tmp_path: Path) -> None:
        m = _base_members()
        m["Stories/Story_ust2.xml"] = b"<idPkg:Story><Story Self='ust2'><broken>"
        trad = _translated(tmp_path, m)
        report = check_completeness(source, trad)
        assert not report.ok
        assert "Stories/Story_ust2.xml" in report.malformed_xml
        # não pode estourar ao tentar comparar a story malformada
        assert any("malformado" in d for d in report.story_count_diffs)
