"""Testes do ``thread_resolver``."""

from __future__ import annotations

from typing import cast

from idml_to_md.idml_reader import IDMLDocument, TextFrameInfo
from idml_to_md.thread_resolver import _walk_to_root, resolve_reading_order


class _FakeDoc:
    """Doppelgänger de IDMLDocument só com ``iter_text_frames``."""

    def __init__(self, frames: list[TextFrameInfo]) -> None:
        self._frames = frames

    def iter_text_frames(self):  # type: ignore[no-untyped-def]
        return iter(self._frames)


def tf(self_id: str, story: str, prev: str, nxt: str, spread: int, order: int) -> TextFrameInfo:
    return TextFrameInfo(
        self_id=self_id,
        parent_story=story,
        previous_text_frame=prev,
        next_text_frame=nxt,
        spread_index=spread,
        order_in_spread=order,
    )


class TestWalkToRoot:
    def test_single_frame_is_root(self) -> None:
        a = tf("A", "s1", "n", "n", 0, 0)
        root = _walk_to_root(a, {"A": a})
        assert root.self_id == "A"

    def test_follows_previous(self) -> None:
        a = tf("A", "s1", "n", "B", 0, 0)
        b = tf("B", "s1", "A", "C", 0, 1)
        c = tf("C", "s1", "B", "n", 0, 2)
        root = _walk_to_root(c, {"A": a, "B": b, "C": c})
        assert root.self_id == "A"

    def test_broken_chain_stops_safely(self) -> None:
        # B aponta para X que não existe — deve retornar B sem crashar
        b = tf("B", "s1", "X", "n", 0, 0)
        root = _walk_to_root(b, {"B": b})
        assert root.self_id == "B"


class TestResolveReadingOrder:
    def test_orders_by_root_position(self) -> None:
        # Thread A→B na página 1 (frame A começa)
        # Thread C isolada na página 0 — vem primeiro
        a = tf("A", "story_ab", "n", "B", 1, 0)
        b = tf("B", "story_ab", "A", "n", 1, 1)
        c = tf("C", "story_c", "n", "n", 0, 0)
        fake = _FakeDoc([c, a, b])
        order = resolve_reading_order(cast(IDMLDocument, fake))

        story_ids = [e.story_id for e in order]
        assert story_ids == ["story_c", "story_ab"]

    def test_dedupes_story_across_frames(self) -> None:
        # Story X aparece em vários frames; só conta uma vez
        a = tf("A", "story_x", "n", "B", 0, 0)
        b = tf("B", "story_x", "A", "n", 1, 0)
        fake = _FakeDoc([a, b])
        order = resolve_reading_order(cast(IDMLDocument, fake))
        assert len(order) == 1
        assert order[0].story_id == "story_x"
        # first_frame_id é a raiz da thread (A)
        assert order[0].first_frame_id == "A"

    def test_ignores_frames_without_parent_story(self) -> None:
        a = tf("A", "", "n", "n", 0, 0)
        b = tf("B", "story_b", "n", "n", 1, 0)
        fake = _FakeDoc([a, b])
        order = resolve_reading_order(cast(IDMLDocument, fake))
        assert [e.story_id for e in order] == ["story_b"]

    def test_empty_input(self) -> None:
        fake = _FakeDoc([])
        assert resolve_reading_order(cast(IDMLDocument, fake)) == []

    def test_reordered_by_root_not_first_seen(self) -> None:
        # First seen for story_y é frame B na página 0; mas a raiz é A na página 2
        a = tf("A", "story_y", "n", "B", 2, 0)
        b = tf("B", "story_y", "A", "n", 0, 0)
        c = tf("C", "story_z", "n", "n", 1, 0)
        fake = _FakeDoc([b, c, a])
        order = resolve_reading_order(cast(IDMLDocument, fake))
        # story_z (página 1) antes de story_y (raiz na página 2)
        assert [e.story_id for e in order] == ["story_z", "story_y"]


class TestCycleSafety:
    def test_cycle_eventually_returns(self) -> None:
        # A→B→A→B em loop. _walk_to_root tem safety counter interno (10_000);
        # o teste só verifica que a função não trava e devolve um TextFrameInfo.
        a = tf("A", "s", "B", "B", 0, 0)
        b = tf("B", "s", "A", "A", 0, 1)
        root = _walk_to_root(a, {"A": a, "B": b})
        assert root.self_id in {"A", "B"}
