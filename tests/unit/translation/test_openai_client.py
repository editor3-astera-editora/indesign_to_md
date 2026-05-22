"""Testes do TranslatorClient com OpenAI mocada."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from idml_to_md.translation.models import Segment, SegmentBoundary, SegmentRun, SkipReason
from idml_to_md.translation.openai_client import (
    TranslatorClient,
    TranslatorConfig,
    _distribute_runs,
    _estimate_cost,
)

# ---------------------------------------------------------------------------
# Helpers / mocks
# ---------------------------------------------------------------------------


@dataclass
class _Usage:
    prompt_tokens: int = 50
    completion_tokens: int = 30


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Completion:
    choices: list[_Choice]
    usage: _Usage


class _FakeCompletions:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Completion:
        self.calls.append(kwargs)
        return _Completion(
            choices=[_Choice(message=_Message(content=self.response_text))],
            usage=_Usage(),
        )


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeOpenAI:
    def __init__(self, response_text: str) -> None:
        self.chat = _FakeChat(_FakeCompletions(response_text))


def _seg(
    text: str,
    sid: str = "u:0",
    runs: list[SegmentRun] | None = None,
    boundaries: list[SegmentBoundary] | None = None,
) -> Segment:
    if runs is None:
        runs = [SegmentRun(run_idx=0, content_idx=0, text=text)]
    return Segment(
        segment_id=sid,
        story_id="u",
        paragraph_idx=int(sid.split(":")[1]),
        runs=runs,
        boundaries=boundaries or [],
        plain_text=text,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_known_model(self) -> None:
        cost = _estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        # 0.15 + 0.60 = 0.75
        assert cost == pytest.approx(0.75)

    def test_unknown_model_zero(self) -> None:
        assert _estimate_cost("nonexistent", 1000, 1000) == 0.0


class TestDistributeRuns:
    def test_plain_text(self) -> None:
        seg = _seg("Hello")
        new_runs, warnings = _distribute_runs(seg, "Hola")
        assert len(new_runs) == 1
        assert new_runs[0].text == "Hola"
        assert warnings == []

    def test_with_bold_placeholder(self) -> None:
        seg = _seg(
            "Os juros simples são fixos.",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="Os "),
                SegmentRun(run_idx=1, content_idx=0, text="juros simples", bold=True),
                SegmentRun(run_idx=2, content_idx=0, text=" são fixos."),
            ],
        )
        # Tradução respeitando os marcadores posicionais §tN§…§/tN§
        target = (
            "§t0§Los §/t0§§t1§intereses simples§/t1§§t2§ son fijos.§/t2§"
        )
        new_runs, warnings = _distribute_runs(seg, target)
        # Cada run vai para o seu lugar; o negrito NÃO salta para o fim
        assert [r.text for r in new_runs] == [
            "Los ",
            "intereses simples",
            " son fijos.",
        ]
        bolds = [r for r in new_runs if r.bold]
        assert len(bolds) == 1
        assert bolds[0].text == "intereses simples"
        assert warnings == []

    def test_missing_placeholder_fallback(self) -> None:
        seg = _seg(
            "A B C",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="A "),
                SegmentRun(run_idx=1, content_idx=0, text="B", bold=True),
                SegmentRun(run_idx=2, content_idx=0, text=" C"),
            ],
        )
        target = "X Y Z sem marcadores"
        new_runs, warnings = _distribute_runs(seg, target)
        assert warnings and "fallback" in warnings[0].lower()
        assert new_runs[0].text == target
        assert new_runs[1].text == ""
        assert new_runs[2].text == ""

    def test_keeps_order_when_model_reorders_markers(self) -> None:
        seg = _seg(
            "A B",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="A "),
                SegmentRun(run_idx=1, content_idx=0, text="B", bold=True),
            ],
        )
        # A LLM emite o run 1 ANTES do run 0 — a remontagem deve ignorar a ordem
        target = "§t1§B!§/t1§§t0§A! §/t0§"
        new_runs, warnings = _distribute_runs(seg, target)
        assert [r.text for r in new_runs] == ["A! ", "B!"]
        assert warnings == []

    def test_three_contents_each_mapped(self) -> None:  # bug #1
        # 3 Contents separados por <Br/> → fronteiras impedem o agrupamento
        # (mesmo "colados", a quebra os separa em runs lógicos distintos).
        seg = _seg(
            "UmDoisTres",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="Um."),
                SegmentRun(run_idx=0, content_idx=1, text="Dois."),
                SegmentRun(run_idx=0, content_idx=2, text="Tres."),
            ],
            boundaries=[
                SegmentBoundary(kind="br", after_text_ord=0),
                SegmentBoundary(kind="br", after_text_ord=1),
            ],
        )
        target = "§t0§Uno.§/t0§§br§§t1§Dos.§/t1§§br§§t2§Tres.§/t2§"
        new_runs, warnings = _distribute_runs(seg, target)
        assert [r.text for r in new_runs] == ["Uno.", "Dos.", "Tres."]
        assert [(r.run_idx, r.content_idx) for r in new_runs] == [(0, 0), (0, 1), (0, 2)]
        assert warnings == []

    def test_missing_one_marker_keeps_that_run_original(self) -> None:
        seg = _seg(
            "A B C",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="A "),
                SegmentRun(run_idx=1, content_idx=0, text="B", bold=True),
                SegmentRun(run_idx=2, content_idx=0, text=" C"),
            ],
        )
        target = "§t0§X §/t0§§t2§ Z§/t2§"  # falta §t1§
        new_runs, warnings = _distribute_runs(seg, target)
        assert new_runs[0].text == "X "
        assert new_runs[1].text == "B"  # original mantido (não some, não duplica)
        assert new_runs[2].text == " Z"
        assert any("§t1§" in w for w in warnings)

    def test_midword_split_merged_and_distributed(self) -> None:
        # "Sistema " + "circulat"(bold) + "ório"(bold): os 2 colados + mesma
        # formatação = 1 grupo lógico. A tradução vai no 1º run, 2º esvaziado.
        seg = _seg(
            "Sistema circulatório",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="Sistema "),
                SegmentRun(run_idx=1, content_idx=0, text="circulat", bold=True),
                SegmentRun(run_idx=2, content_idx=0, text="ório", bold=True),
            ],
        )
        target = "§t0§Sistema §/t0§§t1§circulatorio§/t1§"
        new_runs, warnings = _distribute_runs(seg, target)
        assert [r.text for r in new_runs] == ["Sistema ", "circulatorio", ""]
        assert warnings == []

    def test_missing_marker_recovers_bare_translation(self) -> None:
        # A LLM traduziu mas "esqueceu" o §t1§: o texto solto é recuperado
        # (mantém a tradução em vez de cair para o PT).
        seg = _seg(
            "Sistema circulatório",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="Sistema "),
                SegmentRun(run_idx=1, content_idx=0, text="circulat", bold=True),
                SegmentRun(run_idx=2, content_idx=0, text="ório", bold=True),
            ],
        )
        target = "§t0§Sistema §/t0§circulatorio"  # §t1§ perdido, mas tradução presente
        new_runs, warnings = _distribute_runs(seg, target)
        assert [r.text for r in new_runs] == ["Sistema ", "circulatorio", ""]
        assert any("recuperado" in w for w in warnings)

    def test_missing_marker_recovers_bare_in_order(self) -> None:
        # Dois grupos sem marcador, dois trechos soltos → casa por ordem.
        seg = _seg(
            "A B C",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="A "),
                SegmentRun(run_idx=1, content_idx=0, text="B", bold=True),
                SegmentRun(run_idx=2, content_idx=0, text=" C"),
            ],
        )
        target = "X §t1§Y§/t1§ Z"  # t0 e t2 perdidos; "X" e "Z" soltos, na ordem
        new_runs, _ = _distribute_runs(seg, target)
        assert [r.text for r in new_runs] == ["X", "Y", "Z"]

    def test_midword_group_missing_marker_consolidates(self) -> None:
        # Grupo lógico sem marcador → consolida o ORIGINAL no 1º run e esvazia o
        # resto (nunca deixa fragmento PT solto: evita "circulatorioório").
        seg = _seg(
            "Sistema circulatório",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="Sistema "),
                SegmentRun(run_idx=1, content_idx=0, text="circulat", bold=True),
                SegmentRun(run_idx=2, content_idx=0, text="ório", bold=True),
            ],
        )
        target = "§t0§Sistema §/t0§"  # falta o marcador do grupo [circulat+ório]
        new_runs, warnings = _distribute_runs(seg, target)
        assert [r.text for r in new_runs] == ["Sistema ", "circulatório", ""]
        assert any("§t1§" in w for w in warnings)

    def test_empty_inner_marker_yields_empty_run(self) -> None:
        seg = _seg(
            "A B",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="A"),
                SegmentRun(run_idx=1, content_idx=0, text="B"),
            ],
        )
        target = "§t0§A§/t0§§t1§§/t1§"  # run 1 deliberadamente vazio
        new_runs, warnings = _distribute_runs(seg, target)
        assert new_runs[0].text == "A"
        assert new_runs[1].text == ""
        assert warnings == []

    def test_br_and_anchor_markers_ignored_for_text(self) -> None:  # bug #8/#9
        seg = _seg(
            "A B",
            runs=[
                SegmentRun(run_idx=0, content_idx=0, text="A fração "),
                SegmentRun(run_idx=2, content_idx=0, text=" é menor."),
            ],
        )
        target = "§t0§La fracción §/t0§§a0§§t1§ es menor.§/t1§§br§"
        new_runs, warnings = _distribute_runs(seg, target)
        assert new_runs[0].text == "La fracción "
        assert new_runs[1].text == " es menor."
        assert warnings == []


class TestTranslatorClient:
    def test_translates_with_fake_client(self) -> None:
        fake = _FakeOpenAI("[[1]] Hola\n[[2]] Mundo")
        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
            client=fake,
        )
        segments = [_seg("Olá", sid="u:0"), _seg("Mundo", sid="u:1")]
        translations = client.translate_segments(segments)
        assert len(translations) == 2
        assert translations[0].target_text == "Hola"
        assert translations[1].target_text == "Mundo"
        assert client.stats.translated == 2
        assert client.stats.estimated_cost_usd >= 0

    def test_skipped_segments_not_translated(self) -> None:
        fake = _FakeOpenAI("[[1]] Hola")
        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini"),
            client=fake,
        )
        seg_ok = _seg("Olá", sid="u:0")
        seg_skip = _seg("R$ 100", sid="u:1")
        seg_skip.skip = True
        seg_skip.skip_reason = SkipReason.NUMERIC_LITERAL

        translations = client.translate_segments([seg_ok, seg_skip])
        assert len(translations) == 1
        assert translations[0].segment_id == "u:0"

    def test_chunking_by_story(self) -> None:
        fake = _FakeOpenAI("[[1]] X")
        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=100),
            client=fake,
        )
        seg_a = _seg("a", sid="A:0")
        seg_a.story_id = "A"
        seg_b = _seg("b", sid="B:0")
        seg_b.story_id = "B"
        batches = client._chunk_batches([seg_a, seg_b])
        assert len(batches) == 2  # quebra na mudança de story

    def test_chunking_by_count(self) -> None:
        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=2),
            client=_FakeOpenAI(""),
        )
        segs = [_seg(f"s{i}", sid=f"u:{i}") for i in range(5)]
        for s in segs:
            s.story_id = "u"
        batches = client._chunk_batches(segs)
        # Com batch_max=2 e 5 segments, devem virar 3 lotes (2,2,1)
        assert [len(b) for b in batches] == [2, 2, 1]

    def test_glossary_hit_is_deterministic_no_api_call(self) -> None:
        fake = _FakeOpenAI("SHOULD NOT BE USED")
        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini", glossary={"UNIDADE": "UNIDAD"}),
            client=fake,
        )
        translations = client.translate_segments([_seg("UNIDADE", sid="u:0")])
        assert len(translations) == 1
        t = translations[0]
        assert t.target_text == "UNIDAD"
        assert t.target_runs[0].text == "UNIDAD"
        assert t.model == "glossary"
        # Nenhuma chamada à API foi feita.
        assert fake.chat.completions.calls == []
        assert client.stats.translated == 1
        assert client.stats.estimated_cost_usd == 0.0

    def test_glossary_matches_stripped_text(self) -> None:
        fake = _FakeOpenAI("x")
        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini", glossary={"UNIDADE": "UNIDAD"}),
            client=fake,
        )
        seg = _seg("  UNIDADE  ", sid="u:0")
        translations = client.translate_segments([seg])
        assert translations[0].target_text == "UNIDAD"
        assert fake.chat.completions.calls == []

    def test_glossary_mixed_with_llm(self) -> None:
        fake = _FakeOpenAI("[[1]] Hola")
        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini", glossary={"UNIDADE": "UNIDAD"}),
            client=fake,
        )
        segs = [_seg("UNIDADE", sid="u:0"), _seg("Olá", sid="u:1")]
        translations = client.translate_segments(segs)
        by_id = {t.segment_id: t for t in translations}
        assert by_id["u:0"].target_text == "UNIDAD"
        assert by_id["u:0"].model == "glossary"
        assert by_id["u:1"].target_text == "Hola"
        # Só o segmento não-glossário foi à API.
        assert len(fake.chat.completions.calls) == 1

    def test_no_glossary_all_go_to_llm(self) -> None:
        fake = _FakeOpenAI("[[1]] Hola")
        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini"),
            client=fake,
        )
        client.translate_segments([_seg("Olá", sid="u:0")])
        assert len(fake.chat.completions.calls) == 1

    def test_api_failure_keeps_originals(self) -> None:
        class _BrokenChat:
            class completions:
                @staticmethod
                def create(**kwargs: Any) -> Any:
                    raise RuntimeError("API down")

        class _BrokenOpenAI:
            chat = _BrokenChat()

        client = TranslatorClient(
            config=TranslatorConfig(model="gpt-4o-mini"),
            client=_BrokenOpenAI(),
        )
        # Reduzimos retry para o teste rodar rápido
        client._call_api.retry.stop = lambda *a, **kw: True  # type: ignore[attr-defined]

        segments = [_seg("Olá", sid="u:0")]
        translations = client.translate_segments(segments)
        assert len(translations) == 1
        assert translations[0].target_text == ""
        assert any("failed" in w.lower() for w in translations[0].warnings)
