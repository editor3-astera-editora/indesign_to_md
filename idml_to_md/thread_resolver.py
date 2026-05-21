"""Determina a ordem de leitura das Stories no IDML.

Algoritmo:

1. Itera todos os TextFrames de todas as Spreads (em ordem de página).
2. Agrupa em "threads": sequências encadeadas via ``PreviousTextFrame`` /
   ``NextTextFrame``. Uma raiz é um TextFrame cujo ``PreviousTextFrame``
   é ``"n"`` ou ``""``.
3. A ordem das Stories é a ordem da raiz da thread em que aparecem
   pela primeira vez. Stories isoladas (raiz sem next) também entram
   pela posição da raiz na página.

Saída: lista ordenada de ``story_id`` únicos.

Stories referenciadas via ``ParentStory`` em frames "órfãos" (sem
encadeamento detectável) entram pela ordem em que apareceram nas Spreads.
"""

from __future__ import annotations

from dataclasses import dataclass

from idml_to_md.idml_reader import IDMLDocument, TextFrameInfo


@dataclass(slots=True, frozen=True)
class StoryOrderEntry:
    """Entrada na ordem global de leitura."""

    story_id: str
    first_frame_id: str
    spread_index: int
    order_in_spread: int
    is_master: bool = False  # True quando a Story só existe num MasterSpread


def resolve_reading_order(
    doc: IDMLDocument,
    *,
    include_master_spreads: bool = False,
) -> list[StoryOrderEntry]:
    """Retorna a ordem global de leitura das Stories.

    A ordem usa a primeira raiz de cada thread como ponto de ancoragem.
    Stories já vistas em raízes anteriores não voltam (uma mesma Story
    pode aparecer em N TextFrames; só conta a primeira raiz).

    Quando ``include_master_spreads`` é ``True``, Stories que só existem em
    MasterSpreads (nunca sobrepostas numa página) são anexadas no FIM da ordem,
    com ``is_master=True``. Como os Spreads normais são iterados primeiro, a
    dedup por ``story_id`` garante que overrides de página tenham prioridade —
    só o que é exclusivamente de master entra como master. Default ``False``
    preserva o comportamento do pipeline Markdown.
    """
    frames: list[TextFrameInfo] = list(
        doc.iter_text_frames(include_masters=include_master_spreads)
    )
    by_id = {f.self_id: f for f in frames}

    # 1. Mapa story_id → primeiro frame que a contém (em ordem de página)
    first_seen: dict[str, TextFrameInfo] = {}
    for f in frames:
        if not f.parent_story:
            continue
        first_seen.setdefault(f.parent_story, f)

    # 2. Para cada story, achar a RAIZ da thread (subir via PreviousTextFrame)
    seen_stories: set[str] = set()
    entries: list[StoryOrderEntry] = []

    # Ordem de processamento: pela primeira aparição (página + posição no spread)
    sortable = sorted(
        first_seen.items(),
        key=lambda kv: (kv[1].spread_index, kv[1].order_in_spread),
    )

    for story_id, first_frame in sortable:
        if story_id in seen_stories:
            continue

        root_frame = _walk_to_root(first_frame, by_id)
        entries.append(
            StoryOrderEntry(
                story_id=story_id,
                first_frame_id=root_frame.self_id,
                spread_index=root_frame.spread_index,
                order_in_spread=root_frame.order_in_spread,
                # A Story é "de master" só quando nenhum frame de página normal a
                # referenciou (first_frame é o frame âncora pós-dedup).
                is_master=first_frame.is_master,
            )
        )
        seen_stories.add(story_id)

    # Reordena pelo frame RAIZ — mais correto que pelo first_seen quando
    # a thread começa numa página posterior por escolha do designer.
    entries.sort(key=lambda e: (e.spread_index, e.order_in_spread))
    return entries


def _walk_to_root(frame: TextFrameInfo, by_id: dict[str, TextFrameInfo]) -> TextFrameInfo:
    """Sobe pela cadeia ``PreviousTextFrame`` até a raiz."""
    current = frame
    safety = 0
    while current.previous_text_frame not in ("n", ""):
        prev_id = current.previous_text_frame
        prev = by_id.get(prev_id)
        if prev is None:
            # Referência quebrada (frame em master spread, página não exportada, etc.)
            return current
        current = prev
        safety += 1
        if safety > 10_000:  # ciclo proibitivo — desistir
            return current
    return current
