"""Testes do orquestrador ``pipeline`` com IDML sintético."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from idml_to_md.pipeline import convert_idml, inspect_styles

# --- Reusa o template de teste do IDML reader, mas com conteúdo mais rico ---

DESIGNMAP = """<?xml version="1.0"?>
<Document xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <idPkg:Spread src="Spreads/Spread_A.xml" />
  <idPkg:Styles src="Resources/Styles.xml" />
</Document>
"""

SPREAD_A = """<?xml version="1.0"?>
<idPkg:Spread xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <Spread Self="A">
    <TextFrame Self="f1" ParentStory="story1" PreviousTextFrame="n" NextTextFrame="n" />
  </Spread>
</idPkg:Spread>
"""

STORY_S1 = """<?xml version="1.0"?>
<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <Story Self="story1">
    <ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/T%C3%ADtulos%3aT1">
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content>Cap%C3%ADtulo 1</Content>
      </CharacterStyleRange>
    </ParagraphStyleRange>
    <ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content>Lorem ipsum</Content>
      </CharacterStyleRange>
    </ParagraphStyleRange>
  </Story>
</idPkg:Story>
"""

STYLES = """<?xml version="1.0"?>
<idPkg:Styles xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <RootParagraphStyleGroup>
    <ParagraphStyle Self="ParagraphStyle/T%C3%ADtulos%3aT1" Name="Títulos:T1" />
  </RootParagraphStyleGroup>
</idPkg:Styles>
"""


@pytest.fixture
def synthetic_book(tmp_path: Path) -> Path:
    p = tmp_path / "MeuLivro.idml"
    # IDML uses %3a not properly url-decoded in our test content; we'll fix below
    fixed_story = STORY_S1.replace("T%C3%ADtulos", "Títulos").replace("Cap%C3%ADtulo", "Capítulo")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("designmap.xml", DESIGNMAP)
        z.writestr("Spreads/Spread_A.xml", SPREAD_A)
        z.writestr("Stories/Story_story1.xml", fixed_story)
        z.writestr("Resources/Styles.xml", STYLES)
        z.writestr("mimetype", "application/vnd.adobe.indesign-idml-package")
    # Cria pasta Links/ vazia
    (tmp_path / "Links").mkdir()
    return p


class TestConvertIdml:
    def test_produces_markdown_and_report(self, synthetic_book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        result = convert_idml(synthetic_book, out)
        assert result.markdown_path.exists()
        assert result.report_path.exists()
        md = result.markdown_path.read_text(encoding="utf-8")
        assert "# MeuLivro" in md
        assert "Capítulo 1" in md
        assert "Lorem ipsum" in md

    def test_creates_book_slug_directory(self, synthetic_book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        result = convert_idml(synthetic_book, out)
        assert result.output_dir.name == "meulivro"
        assert (out / "meulivro").is_dir()

    def test_report_json_valid(self, synthetic_book: Path, tmp_path: Path) -> None:
        result = convert_idml(synthetic_book, tmp_path / "out")
        data = json.loads(result.report_path.read_text(encoding="utf-8"))
        assert data["book_slug"] == "meulivro"
        assert data["block_counts"]["heading"] == 1
        assert data["block_counts"]["paragraph"] == 1
        # nenhum estilo unmapped pois todos estão no default
        assert data["unmapped_paragraph_styles"] == {}

    def test_explicit_title(self, synthetic_book: Path, tmp_path: Path) -> None:
        result = convert_idml(synthetic_book, tmp_path / "out", book_title="Custom Title")
        assert "# Custom Title" in result.markdown_path.read_text(encoding="utf-8")

    def test_overlay_yaml_is_applied(self, synthetic_book: Path, tmp_path: Path) -> None:
        overlay = tmp_path / "overlay.yaml"
        overlay.write_text(
            "paragraph_styles:\n  'Texto principal': { kind: blockquote }\n",
            encoding="utf-8",
        )
        result = convert_idml(synthetic_book, tmp_path / "out", overlay_path=overlay)
        md = result.markdown_path.read_text(encoding="utf-8")
        assert "> Lorem ipsum" in md


class TestInspectStyles:
    def test_lists_styles_used_in_stories(self, synthetic_book: Path) -> None:
        counts = inspect_styles(synthetic_book)
        assert counts["Títulos:T1"] == 1
        assert counts["Texto principal"] == 1
