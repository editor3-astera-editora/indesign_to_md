"""Testes do prompt_builder."""

from __future__ import annotations

from idml_to_md.translation.models import Segment, SegmentBoundary, SegmentRun
from idml_to_md.translation.prompt_builder import (
    PH_BR,
    PH_CLOSE,
    PH_OPEN,
    build_batch_prompt,
    build_segment_text_with_placeholders,
    group_logical_runs,
    parse_batch_response,
)


def _seg_with_runs(
    runs: list[SegmentRun],
    sid: str = "u:0",
    boundaries: list[SegmentBoundary] | None = None,
) -> Segment:
    return Segment(
        segment_id=sid,
        story_id="u",
        paragraph_idx=0,
        runs=runs,
        boundaries=boundaries or [],
        plain_text="".join(r.text for r in runs),
    )


class TestPlaceholders:
    def test_plain_text_no_placeholders(self) -> None:
        seg = _seg_with_runs([SegmentRun(run_idx=0, content_idx=0, text="Hello world")])
        out = build_segment_text_with_placeholders(seg)
        assert out == "Hello world"

    def test_bold_run_wrapped(self) -> None:
        seg = _seg_with_runs([
            SegmentRun(run_idx=0, content_idx=0, text="Os "),
            SegmentRun(run_idx=1, content_idx=0, text="juros simples", bold=True),
            SegmentRun(run_idx=2, content_idx=0, text=" são fixos."),
        ])
        out = build_segment_text_with_placeholders(seg)
        # Esquema novo: TODO run vira §tN§…§/tN§ (N = índice do run em seg.runs)
        assert f"{PH_OPEN}t1{PH_OPEN}juros simples{PH_CLOSE}/t1{PH_CLOSE}" in out
        assert out.startswith(f"{PH_OPEN}t0{PH_OPEN}Os {PH_CLOSE}/t0{PH_CLOSE}")
        assert out.endswith(f"{PH_OPEN}t2{PH_OPEN} são fixos.{PH_CLOSE}/t2{PH_CLOSE}")

    def test_br_between_runs_is_marked(self) -> None:  # bug #1
        seg = _seg_with_runs(
            [
                SegmentRun(run_idx=0, content_idx=0, text="Um."),
                SegmentRun(run_idx=0, content_idx=1, text="Dois."),
            ],
            boundaries=[SegmentBoundary(kind="br", after_text_ord=0)],
        )
        out = build_segment_text_with_placeholders(seg)
        assert out == (
            f"{PH_OPEN}t0{PH_OPEN}Um.{PH_CLOSE}/t0{PH_CLOSE}"
            f"{PH_BR}"
            f"{PH_OPEN}t1{PH_OPEN}Dois.{PH_CLOSE}/t1{PH_CLOSE}"
        )

    def test_midword_glued_same_format_runs_merged(self) -> None:
        # "Sistema " + "circulat"(bold) + "ório"(bold): os 2 últimos colados e
        # com a mesma formatação viram UM marcador (palavra partida pela InDesign).
        seg = _seg_with_runs([
            SegmentRun(run_idx=0, content_idx=0, text="Sistema "),
            SegmentRun(run_idx=1, content_idx=0, text="circulat", bold=True),
            SegmentRun(run_idx=2, content_idx=0, text="ório", bold=True),
        ])
        out = build_segment_text_with_placeholders(seg)
        assert out == (
            f"{PH_OPEN}t0{PH_OPEN}Sistema {PH_CLOSE}/t0{PH_CLOSE}"
            f"{PH_OPEN}t1{PH_OPEN}circulatório{PH_CLOSE}/t1{PH_CLOSE}"
        )

    def test_superscript_not_merged(self) -> None:
        # "m" + "2"(sobrescrito) colados mas formatação distinta → NÃO junta.
        seg = _seg_with_runs([
            SegmentRun(run_idx=0, content_idx=0, text="m"),
            SegmentRun(run_idx=1, content_idx=0, text="2", superscript=True),
        ])
        out = build_segment_text_with_placeholders(seg)
        assert f"{PH_OPEN}t0{PH_OPEN}m{PH_CLOSE}/t0{PH_CLOSE}" in out
        assert f"{PH_OPEN}t1{PH_OPEN}2{PH_CLOSE}/t1{PH_CLOSE}" in out

    def test_anchor_between_runs_is_marked(self) -> None:  # bug #8/#9
        seg = _seg_with_runs(
            [
                SegmentRun(run_idx=0, content_idx=0, text="A fração "),
                SegmentRun(run_idx=2, content_idx=0, text=" é menor."),
            ],
            boundaries=[SegmentBoundary(kind="anchor", after_text_ord=0, anchor_ord=0)],
        )
        out = build_segment_text_with_placeholders(seg)
        # âncora §a0§ fica ENTRE os dois runs (ordinal = índice na lista de runs)
        assert out == (
            f"{PH_OPEN}t0{PH_OPEN}A fração {PH_CLOSE}/t0{PH_CLOSE}"
            f"{PH_OPEN}a0{PH_CLOSE}"
            f"{PH_OPEN}t1{PH_OPEN} é menor.{PH_CLOSE}/t1{PH_CLOSE}"
        )

    def test_single_run_with_trailing_br_is_raw(self) -> None:
        # Caso comum: 1 run + Br final → NÃO estruturado → texto cru, sem marcadores
        seg = _seg_with_runs(
            [SegmentRun(run_idx=0, content_idx=0, text="Frase comum.")],
            boundaries=[SegmentBoundary(kind="br", after_text_ord=0)],
        )
        out = build_segment_text_with_placeholders(seg)
        assert out == "Frase comum."

    def test_system_prompt_documents_markers(self) -> None:
        seg = _seg_with_runs([SegmentRun(run_idx=0, content_idx=0, text="A")])
        prompt = build_batch_prompt([seg])
        assert PH_BR in prompt.system
        assert f"{PH_OPEN}t" in prompt.system
        assert f"{PH_OPEN}a" in prompt.system


class TestGroupLogicalRuns:
    def _runs(self, *specs: tuple) -> list[SegmentRun]:
        out = []
        for i, spec in enumerate(specs):
            text, bold = (spec if isinstance(spec, tuple) else (spec, False))
            out.append(SegmentRun(run_idx=i, content_idx=0, text=text, bold=bold))
        return out

    def test_no_merge_when_space_separated(self) -> None:
        runs = self._runs("Sistema ", ("circulatório", True))
        assert group_logical_runs(runs, []) == [[0], [1]]

    def test_merge_glued_same_format(self) -> None:
        runs = self._runs("Sistema ", ("circulat", True), ("ório", True))
        assert group_logical_runs(runs, []) == [[0], [1, 2]]

    def test_no_merge_different_format(self) -> None:
        # "Mus" normal + "cular" bold colados → formatação difere → não junta.
        runs = self._runs("Mus", ("cular", True))
        assert group_logical_runs(runs, []) == [[0], [1]]

    def test_no_merge_across_boundary(self) -> None:
        runs = self._runs("Um.", "Dois.")
        bnds = [SegmentBoundary(kind="br", after_text_ord=0)]
        assert group_logical_runs(runs, bnds) == [[0], [1]]

    def test_three_glued_merge_into_one(self) -> None:
        runs = self._runs("Articul", "ações do ")  # colados, mesmo formato
        assert group_logical_runs(runs, []) == [[0, 1]]

    def test_empty_runs(self) -> None:
        assert group_logical_runs([], []) == []


class TestBuildBatchPrompt:
    def test_numbers_segments(self) -> None:
        segs = [
            _seg_with_runs([SegmentRun(run_idx=0, content_idx=0, text="A")], sid="u:0"),
            _seg_with_runs([SegmentRun(run_idx=0, content_idx=0, text="B")], sid="u:1"),
        ]
        prompt = build_batch_prompt(segs, target_lang="es")
        assert "[[1]] A" in prompt.user
        assert "[[2]] B" in prompt.user
        assert prompt.segment_order == ["u:0", "u:1"]
        assert "espanhol" in prompt.system

    def test_target_lang_en(self) -> None:
        segs = [_seg_with_runs([SegmentRun(run_idx=0, content_idx=0, text="A")])]
        prompt = build_batch_prompt(segs, target_lang="en")
        assert "inglês" in prompt.system


class TestParseResponse:
    def test_parses_simple(self) -> None:
        order = ["u:0", "u:1"]
        text = "[[1]] Olá\n[[2]] Mundo"
        out = parse_batch_response(text, order)
        assert out == {"u:0": "Olá", "u:1": "Mundo"}

    def test_handles_multiline(self) -> None:
        order = ["u:0", "u:1"]
        text = "[[1]] Linha 1\nLinha 2 continua\n\n[[2]] Outra"
        out = parse_batch_response(text, order)
        assert "Linha 1\nLinha 2 continua" in out["u:0"]
        assert out["u:1"] == "Outra"

    def test_handles_missing(self) -> None:
        order = ["u:0", "u:1"]
        text = "[[1]] Apenas o primeiro"
        out = parse_batch_response(text, order)
        assert "u:0" in out
        assert "u:1" not in out

    def test_ignores_out_of_range(self) -> None:
        order = ["u:0"]
        text = "[[1]] OK\n[[5]] Estranho"
        out = parse_batch_response(text, order)
        assert out == {"u:0": "OK"}
