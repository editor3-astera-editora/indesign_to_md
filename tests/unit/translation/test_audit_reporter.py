"""Testes do audit_reporter."""

from __future__ import annotations

import json
from pathlib import Path

from idml_to_md.translation.audit_reporter import build_audit_report, save_report
from idml_to_md.translation.models import (
    Segment,
    SegmentRun,
    SkipReason,
    Translation,
)
from idml_to_md.translation.openai_client import TranslatorStats


def _seg(text: str, sid: str, skip: bool = False, reason: SkipReason = SkipReason.NONE) -> Segment:
    s = Segment(
        segment_id=sid,
        story_id="u",
        paragraph_idx=int(sid.split(":")[1]),
        runs=[SegmentRun(run_idx=0, content_idx=0, text=text)],
        plain_text=text,
    )
    s.skip = skip
    s.skip_reason = reason
    return s


class TestBuildReport:
    def test_basic(self, tmp_path: Path) -> None:
        segs = [
            _seg("Olá", "u:0"),
            _seg("R$ 100", "u:1", skip=True, reason=SkipReason.NUMERIC_LITERAL),
        ]
        trans = [
            Translation(
                segment_id="u:0",
                source_text="Olá",
                target_text="Hola",
            )
        ]
        stats = TranslatorStats(
            total_segments=1,
            translated=1,
            prompt_tokens=100,
            completion_tokens=20,
            estimated_cost_usd=0.0001,
        )
        idml_path = tmp_path / "a.idml"
        idml_path.write_bytes(b"PK")  # placeholder; auditor é tolerante

        report = build_audit_report(
            source_idml=idml_path,
            target_idml=tmp_path / "a_es.idml",
            target_lang="es",
            segments=segs,
            translations=trans,
            stats=stats,
        )
        assert report.total_segments == 2
        assert report.translated_segments == 1
        assert report.skipped_segments == 1
        assert report.skip_breakdown == {"numeric_literal": 1}
        assert report.estimated_cost_usd == 0.0001

    def test_warnings_collected(self, tmp_path: Path) -> None:
        idml_path = tmp_path / "a.idml"
        idml_path.write_bytes(b"PK")
        trans = [
            Translation(
                segment_id="u:0",
                source_text="A",
                target_text="A",
                warnings=["placeholder missing"],
            )
        ]
        stats = TranslatorStats(warnings=["one batch slow"])
        report = build_audit_report(
            source_idml=idml_path,
            target_idml=idml_path,
            target_lang="es",
            segments=[_seg("A", "u:0")],
            translations=trans,
            stats=stats,
        )
        assert "one batch slow" in report.warnings
        assert any("placeholder" in w for w in report.warnings)

    def test_save_creates_file(self, tmp_path: Path) -> None:
        idml_path = tmp_path / "a.idml"
        idml_path.write_bytes(b"PK")
        report = build_audit_report(
            source_idml=idml_path,
            target_idml=idml_path,
            target_lang="es",
            segments=[],
            translations=[],
            stats=TranslatorStats(),
        )
        out = tmp_path / "report.json"
        save_report(report, out)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["target_lang"] == "es"
