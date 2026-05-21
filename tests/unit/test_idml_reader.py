"""Testes do ``idml_reader`` usando um IDML sintético em ZIP."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from idml_to_md.idml_reader import IDMLDocument

DESIGNMAP = """<?xml version="1.0"?>
<Document xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <idPkg:Spread src="Spreads/Spread_A.xml" />
  <idPkg:Spread src="Spreads/Spread_B.xml" />
  <idPkg:MasterSpread src="MasterSpreads/MasterSpread_M.xml" />
  <idPkg:Styles src="Resources/Styles.xml" />
</Document>
"""

MASTER_SPREAD_M = """<?xml version="1.0"?>
<idPkg:MasterSpread xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <MasterSpread Self="M">
    <TextFrame Self="fm1" ParentStory="sm1" PreviousTextFrame="n" NextTextFrame="n" />
  </MasterSpread>
</idPkg:MasterSpread>
"""

SPREAD_A = """<?xml version="1.0"?>
<idPkg:Spread xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <Spread Self="A">
    <TextFrame Self="f1" ParentStory="s1" PreviousTextFrame="n" NextTextFrame="f2" />
    <TextFrame Self="f2" ParentStory="s1" PreviousTextFrame="f1" NextTextFrame="n" />
  </Spread>
</idPkg:Spread>
"""

SPREAD_B = """<?xml version="1.0"?>
<idPkg:Spread xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <Spread Self="B">
    <TextFrame Self="f3" ParentStory="s2" PreviousTextFrame="n" NextTextFrame="n" />
  </Spread>
</idPkg:Spread>
"""

STORY_S1 = """<?xml version="1.0"?>
<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <Story Self="s1">
    <ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/X">
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content>Hello</Content>
      </CharacterStyleRange>
    </ParagraphStyleRange>
  </Story>
</idPkg:Story>
"""

STYLES_XML = """<?xml version="1.0"?>
<idPkg:Styles xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <RootParagraphStyleGroup>
    <ParagraphStyle Self="ParagraphStyle/My%3aStyle" Name="My:Style" />
    <ParagraphStyle Self="ParagraphStyle/Other" Name="Other" />
  </RootParagraphStyleGroup>
  <RootCharacterStyleGroup>
    <CharacterStyle Self="CharacterStyle/Bold" Name="Bold" />
  </RootCharacterStyleGroup>
</idPkg:Styles>
"""


@pytest.fixture
def synthetic_idml(tmp_path: Path) -> Path:
    p = tmp_path / "test.idml"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("designmap.xml", DESIGNMAP)
        z.writestr("Spreads/Spread_A.xml", SPREAD_A)
        z.writestr("Spreads/Spread_B.xml", SPREAD_B)
        z.writestr("MasterSpreads/MasterSpread_M.xml", MASTER_SPREAD_M)
        z.writestr("Stories/Story_s1.xml", STORY_S1)
        z.writestr("Resources/Styles.xml", STYLES_XML)
        z.writestr("mimetype", "application/vnd.adobe.indesign-idml-package")
    return p


class TestEnumeration:
    def test_spread_paths_in_designmap_order(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            assert doc.spread_paths() == ["Spreads/Spread_A.xml", "Spreads/Spread_B.xml"]

    def test_story_paths_lists_all(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            assert doc.story_paths() == ["Stories/Story_s1.xml"]

    def test_master_spread_paths(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            assert doc.master_spread_paths() == ["MasterSpreads/MasterSpread_M.xml"]

    def test_iter_master_spreads_index_continues(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            items = list(doc.iter_master_spreads())
        # 2 spreads normais (0,1) → master começa em 2
        assert [i for i, _, _ in items] == [2]
        assert [p for _, p, _ in items] == ["MasterSpreads/MasterSpread_M.xml"]

    def test_iter_spreads_returns_index_path_root(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            items = list(doc.iter_spreads())
        assert [i for i, _, _ in items] == [0, 1]
        assert [p for _, p, _ in items] == ["Spreads/Spread_A.xml", "Spreads/Spread_B.xml"]


class TestStoryAccess:
    def test_get_story_root_returns_root(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            root = doc.get_story_root("s1")
        assert root is not None
        story = root.find(".//Story")
        assert story is not None
        assert story.get("Self") == "s1"

    def test_get_story_root_missing_returns_none(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            assert doc.get_story_root("nonexistent") is None


class TestStyleNames:
    def test_paragraph_style_names_url_decoded(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            names = doc.paragraph_style_names()
        assert "My:Style" in names
        assert "Other" in names

    def test_character_style_names(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            names = doc.character_style_names()
        assert names == ["Bold"]


class TestTextFrames:
    def test_iter_text_frames_includes_all(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            frames = list(doc.iter_text_frames())
        ids = [f.self_id for f in frames]
        assert ids == ["f1", "f2", "f3"]

    def test_text_frame_chain_attrs(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            frames = {f.self_id: f for f in doc.iter_text_frames()}
        assert frames["f1"].previous_text_frame == "n"
        assert frames["f1"].next_text_frame == "f2"
        assert frames["f2"].previous_text_frame == "f1"
        assert frames["f1"].parent_story == "s1"

    def test_spread_index_set(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            frames = list(doc.iter_text_frames())
        assert frames[0].spread_index == 0
        assert frames[2].spread_index == 1

    def test_masters_excluded_by_default(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            frames = list(doc.iter_text_frames())
        assert [f.self_id for f in frames] == ["f1", "f2", "f3"]
        assert all(not f.is_master for f in frames)

    def test_masters_included_when_requested(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            frames = list(doc.iter_text_frames(include_masters=True))
        ids = [f.self_id for f in frames]
        assert ids == ["f1", "f2", "f3", "fm1"]  # master vem por último
        master = frames[-1]
        assert master.self_id == "fm1"
        assert master.is_master is True
        assert master.parent_story == "sm1"
        assert master.spread_index == 2  # após os 2 spreads normais


class TestContextManager:
    def test_close_via_context(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            assert doc.designmap() is not None
        # após sair, .close() foi chamado; uma segunda chamada não levanta
        doc.close()

    def test_caches_designmap(self, synthetic_idml: Path) -> None:
        with IDMLDocument(synthetic_idml) as doc:
            first = doc.designmap()
            second = doc.designmap()
        assert first is second
