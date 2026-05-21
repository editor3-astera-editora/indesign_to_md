"""Testes do ``report``."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from idml_to_md.models import Document, Heading, InlineKind, Paragraph, ReferenceEntry, TextRun
from idml_to_md.report import ConversionReport, build_report, count_blocks


def t(s: str) -> TextRun:
    return TextRun(text=s, kind=InlineKind.TEXT)


class TestCountBlocks:
    def test_empty(self) -> None:
        assert count_blocks([]) == {}

    def test_mixed(self) -> None:
        blocks = [
            Heading(level=1, inlines=[t("a")]),
            Paragraph(inlines=[t("b")]),
            Paragraph(inlines=[t("c")]),
        ]
        counts = count_blocks(blocks)
        assert counts == {"heading": 1, "paragraph": 2}


class TestBuildReport:
    def test_basic(self) -> None:
        doc = Document(title="L", slug="l")
        doc.blocks.append(Heading(level=1, inlines=[t("h")]))
        doc.references.append(ReferenceEntry(inlines=[t("r")]))

        r = build_report(
            doc=doc,
            seen_paragraph=Counter({"Texto": 5}),
            unmapped_paragraph=Counter({"WeirdStyle": 1}),
            seen_character=Counter(),
            unmapped_character=Counter(),
            missing_assets=["x.jpg"],
            copied_assets=3,
        )
        assert isinstance(r, ConversionReport)
        assert r.book_slug == "l"
        assert r.book_title == "L"
        assert r.seen_paragraph_styles == {"Texto": 5}
        assert r.unmapped_paragraph_styles == {"WeirdStyle": 1}
        assert r.missing_assets == ["x.jpg"]
        assert r.copied_assets == 3
        assert r.reference_entries == 1
        assert r.body_blocks == 1


class TestSerialize:
    def test_to_json_includes_tool_version(self) -> None:
        r = ConversionReport()
        data = json.loads(r.to_json())
        assert "tool_version" in data
        assert isinstance(data["tool_version"], str)

    def test_write(self, tmp_path: Path) -> None:
        r = ConversionReport(book_slug="abc", book_title="ABC")
        out = tmp_path / "subdir" / "_report.json"
        r.write(out)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["book_slug"] == "abc"
        assert data["book_title"] == "ABC"
