"""Testes do ``style_mapper``."""

from __future__ import annotations

import pytest

from idml_to_md.style_mapper import (
    StyleMap,
    _deep_merge,
    build_style_map,
    normalize_style_name,
)


class TestNormalize:
    def test_strips_paragraph_prefix(self) -> None:
        assert normalize_style_name("ParagraphStyle/Texto principal") == "Texto principal"

    def test_decodes_colon(self) -> None:
        assert normalize_style_name("ParagraphStyle/Títulos%3aT1") == "Títulos:T1"

    def test_decodes_uppercase_colon(self) -> None:
        assert normalize_style_name("ParagraphStyle/Sumario%3AItem 1") == "Sumario:Item 1"

    def test_handles_id_prefix(self) -> None:
        assert (
            normalize_style_name("CharacterStyle/$ID/[No character style]")
            == "$ID/[No character style]"
        )

    def test_no_prefix(self) -> None:
        assert normalize_style_name("plain") == "plain"


class TestDeepMerge:
    def test_overlay_overrides(self) -> None:
        base = {"a": 1, "b": 2}
        out = _deep_merge(base, {"b": 3, "c": 4})
        assert out == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        base = {"styles": {"T1": {"level": 1}, "T2": {"level": 2}}}
        overlay = {"styles": {"T1": {"level": 0}, "T3": {"level": 3}}}
        out = _deep_merge(base, overlay)
        assert out == {"styles": {"T1": {"level": 0}, "T2": {"level": 2}, "T3": {"level": 3}}}

    def test_scalar_replaces_dict(self) -> None:
        out = _deep_merge({"x": {"a": 1}}, {"x": "replaced"})
        assert out == {"x": "replaced"}


class TestBuildStyleMap:
    def test_default_loads(self) -> None:
        sm = build_style_map()
        assert isinstance(sm, StyleMap)
        assert "Títulos:T1" in sm.paragraph_rules
        assert sm.paragraph_rules["Títulos:T1"].kind == "heading"
        assert sm.character_rules["Bold"].wrap == "**"

    def test_overlay_data_added(self) -> None:
        overlay = {
            "paragraph_styles": {
                "MyCustomStyle": {"kind": "paragraph"},
            }
        }
        sm = build_style_map(overlay_data=overlay)
        assert "MyCustomStyle" in sm.paragraph_rules

    def test_overlay_overrides(self) -> None:
        overlay = {
            "paragraph_styles": {
                "Títulos:T1": {"kind": "paragraph"},
            }
        }
        sm = build_style_map(overlay_data=overlay)
        assert sm.paragraph_rules["Títulos:T1"].kind == "paragraph"

    def test_overlay_path(self, tmp_path) -> None:
        f = tmp_path / "ov.yaml"
        f.write_text("paragraph_styles:\n  XYZ: {kind: heading, level: 5}\n", encoding="utf-8")
        sm = build_style_map(overlay_path=f)
        assert sm.paragraph_rules["XYZ"].kind == "heading"

    def test_rejects_non_dict_spec(self) -> None:
        overlay = {"paragraph_styles": {"X": "not a dict"}}
        with pytest.raises(TypeError, match="paragraph_styles"):
            build_style_map(overlay_data=overlay)

    def test_rejects_non_dict_character_spec(self) -> None:
        overlay = {"character_styles": {"Bold2": ["nope"]}}
        with pytest.raises(TypeError, match="character_styles"):
            build_style_map(overlay_data=overlay)


class TestLookup:
    def test_lookup_known_paragraph(self) -> None:
        sm = build_style_map()
        rule = sm.lookup_paragraph("ParagraphStyle/Texto principal")
        assert rule is not None
        assert rule.kind == "paragraph"
        assert sm.seen_paragraph_styles["Texto principal"] == 1
        assert "Texto principal" not in sm.unmapped_paragraph_styles

    def test_unknown_paragraph_passthrough(self) -> None:
        sm = build_style_map()
        rule = sm.lookup_paragraph("ParagraphStyle/CompletelyNewStyle")
        assert rule is not None
        assert rule.kind == "paragraph"
        assert sm.unmapped_paragraph_styles["CompletelyNewStyle"] == 1

    def test_unknown_paragraph_drop_policy(self) -> None:
        sm = build_style_map(overlay_data={"defaults": {"unknown_paragraph_style": "drop"}})
        rule = sm.lookup_paragraph("ParagraphStyle/Unknown")
        assert rule is None
        assert sm.unmapped_paragraph_styles["Unknown"] == 1

    def test_lookup_known_character_style(self) -> None:
        sm = build_style_map()
        rule = sm.lookup_character("CharacterStyle/Bold")
        assert rule is not None
        assert rule.wrap == "**"

    def test_unknown_character_returns_none(self) -> None:
        sm = build_style_map()
        rule = sm.lookup_character("CharacterStyle/MyCustomChar")
        assert rule is None
        assert sm.unmapped_character_styles["MyCustomChar"] == 1

    def test_id_character_style_silent(self) -> None:
        sm = build_style_map()
        rule = sm.lookup_character("CharacterStyle/$ID/[No character style]")
        assert rule is None
        # $ID/ não vai para unmapped
        assert "$ID/[No character style]" not in sm.unmapped_character_styles

    def test_paragraph_rule_get_with_default(self) -> None:
        sm = build_style_map()
        rule = sm.lookup_paragraph("ParagraphStyle/Títulos%3aT1")
        assert rule is not None
        assert rule.get("level") == 1
        assert rule.get("missing_key", "fallback") == "fallback"
