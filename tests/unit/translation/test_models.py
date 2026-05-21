"""Smoke tests dos modelos pydantic."""

from __future__ import annotations

from idml_to_md.translation.models import (
    AuditReport,
    EquationAlert,
    Segment,
    SegmentBoundary,
    SegmentRun,
    SkipReason,
    Translation,
    TranslationBatch,
)


class TestSegmentBoundary:
    def test_defaults(self) -> None:
        b = SegmentBoundary(kind="br")
        assert b.kind == "br"
        assert b.after_text_ord == -1
        assert b.anchor_ord == -1

    def test_segment_carries_boundaries(self) -> None:
        seg = Segment(
            segment_id="u:0",
            story_id="u",
            paragraph_idx=0,
            runs=[SegmentRun(run_idx=0, content_idx=0, text="A")],
            boundaries=[SegmentBoundary(kind="anchor", after_text_ord=0, anchor_ord=0)],
        )
        assert seg.boundaries[0].kind == "anchor"


class TestSegmentRun:
    def test_defaults(self) -> None:
        run = SegmentRun(run_idx=0, content_idx=0, text="hi")
        assert not run.bold
        assert not run.italic
        assert run.character_style == ""

    def test_serializes(self) -> None:
        run = SegmentRun(run_idx=1, content_idx=0, text="bold", bold=True)
        d = run.model_dump()
        assert d["bold"] is True
        assert d["run_idx"] == 1


class TestSegment:
    def test_basic(self) -> None:
        seg = Segment(
            segment_id="ust1:0",
            story_id="ust1",
            paragraph_idx=0,
            paragraph_style="Títulos:T1",
            paragraph_kind="heading",
            runs=[SegmentRun(run_idx=0, content_idx=0, text="Cap")],
            plain_text="Cap",
        )
        assert seg.skip is False
        assert seg.skip_reason == SkipReason.NONE
        assert seg.segment_id == "ust1:0"

    def test_skip_reason(self) -> None:
        seg = Segment(segment_id="x:0", story_id="x", paragraph_idx=0)
        seg.skip = True
        seg.skip_reason = SkipReason.EMPTY
        assert seg.skip_reason.value == "empty"


class TestTranslation:
    def test_defaults_empty(self) -> None:
        t = Translation(segment_id="ust1:0", source_text="Hi")
        assert t.target_text == ""
        assert t.warnings == []


class TestTranslationBatch:
    def test_holds_collections(self) -> None:
        batch = TranslationBatch(batch_id="b1", story_id="ust1")
        assert batch.segments == []
        assert batch.translations == []


class TestAuditReport:
    def test_minimal(self) -> None:
        report = AuditReport(
            source_idml="a.idml",
            target_idml="a_es.idml",
            target_lang="es",
        )
        assert report.equation_alerts == []
        assert report.estimated_cost_usd == 0.0

    def test_with_alerts(self) -> None:
        report = AuditReport(
            source_idml="a.idml",
            target_idml="a_es.idml",
            target_lang="es",
            equation_alerts=[EquationAlert(eps_basename="eq1.eps", terms_found=["Juros"])],
        )
        assert len(report.equation_alerts) == 1
        assert report.equation_alerts[0].terms_found == ["Juros"]
