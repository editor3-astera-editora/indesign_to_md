"""Testes da sincronização sumário↔títulos de capítulo (função pura).

Monta ``Segment``/``Translation`` em memória — sem IDML, sem OpenAI.
"""

from __future__ import annotations

from idml_to_md.translation.models import Segment, SegmentBoundary, SegmentRun, Translation
from idml_to_md.translation.title_consistency import (
    _split_page_suffix,
    sync_toc_with_headings,
)

CHAPTER_STYLES = ["Títulos:T1", "Títulos:Titulo capítulos"]
TOC_STYLES = ["Sumario:Item 1"]


# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #


def _run(text: str, run_idx: int = 0, content_idx: int = 0) -> SegmentRun:
    return SegmentRun(run_idx=run_idx, content_idx=content_idx, text=text)


def _heading(
    seg_id: str,
    source_runs: list[SegmentRun],
    target_runs: list[SegmentRun],
    *,
    style: str = "Títulos:T1",
    boundaries: list[SegmentBoundary] | None = None,
    warnings: list[str] | None = None,
) -> tuple[Segment, Translation]:
    seg = Segment(
        segment_id=seg_id,
        story_id="s",
        paragraph_idx=0,
        paragraph_style=style,
        paragraph_kind="heading",
        runs=source_runs,
        boundaries=boundaries or [],
        plain_text="".join(r.text for r in source_runs),
    )
    trans = Translation(
        segment_id=seg_id,
        source_text=seg.plain_text,
        target_text="".join(r.text for r in target_runs),
        target_runs=target_runs,
        warnings=warnings or [],
    )
    return seg, trans


def _toc(
    seg_id: str,
    source_runs: list[SegmentRun],
    target_runs: list[SegmentRun],
    *,
    style: str = "Sumario:Item 1",
    boundaries: list[SegmentBoundary] | None = None,
) -> tuple[Segment, Translation]:
    seg = Segment(
        segment_id=seg_id,
        story_id="s",
        paragraph_idx=1,
        paragraph_style=style,
        paragraph_kind="paragraph",
        runs=source_runs,
        boundaries=boundaries or [],
        plain_text="".join(r.text for r in source_runs),
    )
    trans = Translation(
        segment_id=seg_id,
        source_text=seg.plain_text,
        target_text="".join(r.text for r in target_runs),
        target_runs=target_runs,
    )
    return seg, trans


def _sync(segments, translations):
    return sync_toc_with_headings(
        segments,
        translations,
        chapter_title_styles=CHAPTER_STYLES,
        toc_entry_styles=TOC_STYLES,
    )


# --------------------------------------------------------------------------- #
# Casos                                                                        #
# --------------------------------------------------------------------------- #


def test_overrides_divergent_toc_entry_keeping_page() -> None:
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    t_seg, t_trans = _toc("t", [_run("Conjuntos\t16")], [_run("Tradução divergente\t16")])

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "Conjuntos ES\t16"
    assert report.synced == 1
    assert report.unmatched_toc_titles == []
    assert report.conflicting_headings == []


def test_multi_run_toc_paragraph_matches_per_run() -> None:
    # Capítulo multi-run com <Br/> final → canônico concatenado corretamente.
    h1_seg, h1_trans = _heading(
        "h1",
        [_run("Operações Fundamentais e ", content_idx=0), _run("Frações", run_idx=1)],
        [_run("Operaciones Fundamentales y ", content_idx=0), _run("Fracciones", run_idx=1)],
        boundaries=[SegmentBoundary(kind="br", after_text_ord=1)],
    )
    h2_seg, h2_trans = _heading("h2", [_run("Conjuntos")], [_run("Conjuntos")])

    # Um único PSR de sumário empacota 3 capítulos, separados por <Br/>.
    src = [
        _run("Operações Fundamentais e Frações\t7", run_idx=0, content_idx=0),
        _run("Conjuntos\t16", run_idx=0, content_idx=1),
        _run("Capítulo Inexistente\t99", run_idx=0, content_idx=2),
    ]
    tgt = [
        _run("DIVERGENTE A\t7", run_idx=0, content_idx=0),
        _run("DIVERGENTE B\t16", run_idx=0, content_idx=1),
        _run("DIVERGENTE C\t99", run_idx=0, content_idx=2),
    ]
    bnds = [
        SegmentBoundary(kind="br", after_text_ord=0),
        SegmentBoundary(kind="br", after_text_ord=1),
    ]
    t_seg, t_trans = _toc("t", src, tgt, boundaries=bnds)

    report = _sync([h1_seg, h2_seg, t_seg], [h1_trans, h2_trans, t_trans])

    assert t_trans.target_runs[0].text == "Operaciones Fundamentales y Fracciones\t7"
    assert t_trans.target_runs[1].text == "Conjuntos\t16"
    # Sem correspondência: mantém a tradução da LLM e reporta.
    assert t_trans.target_runs[2].text == "DIVERGENTE C\t99"
    assert report.synced == 2
    assert report.unmatched_toc_titles == ["Capítulo Inexistente"]


def test_unmatched_toc_entry_unchanged() -> None:
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    t_seg, t_trans = _toc("t", [_run("Outra coisa\t5")], [_run("Algo más\t5")])

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "Algo más\t5"
    assert report.synced == 0
    assert report.unmatched_toc_titles == ["Outra coisa"]


def test_duplicate_headings_conflict_first_wins() -> None:
    h1_seg, h1_trans = _heading("h1", [_run("Capítulo")], [_run("Primeira")])
    h2_seg, h2_trans = _heading("h2", [_run("Capítulo")], [_run("Segunda")])
    t_seg, t_trans = _toc("t", [_run("Capítulo\t3")], [_run("X\t3")])

    report = _sync([h1_seg, h2_seg, t_seg], [h1_trans, h2_trans, t_trans])

    assert t_trans.target_runs[0].text == "Primeira\t3"
    assert report.conflicting_headings == ["Capítulo"]
    assert report.synced == 1


def test_identical_duplicate_headings_no_conflict() -> None:
    h1_seg, h1_trans = _heading("h1", [_run("Capítulo")], [_run("Igual")])
    h2_seg, h2_trans = _heading("h2", [_run("Capítulo")], [_run("Igual")])
    t_seg, t_trans = _toc("t", [_run("Capítulo\t3")], [_run("X\t3")])

    report = _sync([h1_seg, h2_seg, t_seg], [h1_trans, h2_trans, t_trans])

    assert t_trans.target_runs[0].text == "Igual\t3"
    assert report.conflicting_headings == []


def test_failed_heading_translation_not_used() -> None:
    # batch_failed → não sobrescreve o sumário com o título do corpo.
    h_seg, h_trans = _heading(
        "h", [_run("Conjuntos")], [_run("Conjuntos")], warnings=["batch_failed: boom"]
    )
    t_seg, t_trans = _toc("t", [_run("Conjuntos\t16")], [_run("Conjuntos ES_toc\t16")])

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "Conjuntos ES_toc\t16"
    assert report.synced == 0


def test_missing_in_response_heading_not_used() -> None:
    h_seg, h_trans = _heading(
        "h",
        [_run("Conjuntos")],
        [_run("Conjuntos")],
        warnings=["missing in response — kept original"],
    )
    t_seg, t_trans = _toc("t", [_run("Conjuntos\t16")], [_run("Conjuntos ES_toc\t16")])

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "Conjuntos ES_toc\t16"
    assert report.synced == 0


def test_toc_entry_without_page_suffix() -> None:
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    t_seg, t_trans = _toc("t", [_run("Conjuntos")], [_run("Algo\t")])  # sem página

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "Conjuntos ES"
    assert report.synced == 1


def test_whitespace_insensitive_match() -> None:
    # Título do corpo com espaço duplo; sumário com espaço simples → casa.
    h_seg, h_trans = _heading("h", [_run("Bens  e  Serviços")], [_run("Bienes y Servicios")])
    t_seg, t_trans = _toc("t", [_run("Bens e Serviços\t40")], [_run("X\t40")])

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "Bienes y Servicios\t40"
    assert report.synced == 1


def test_disabled_when_styles_empty() -> None:
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    t_seg, t_trans = _toc("t", [_run("Conjuntos\t16")], [_run("Divergente\t16")])

    report = sync_toc_with_headings(
        [h_seg, t_seg],
        [h_trans, t_trans],
        chapter_title_styles=[],
        toc_entry_styles=TOC_STYLES,
    )

    assert t_trans.target_runs[0].text == "Divergente\t16"
    assert report.synced == 0


def test_report_warnings_text() -> None:
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    t_seg, t_trans = _toc("t", [_run("Inexistente\t9")], [_run("X\t9")])

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    joined = " ".join(report.warnings)
    assert "Inexistente" in joined


# --------------------------------------------------------------------------- #
# _split_page_suffix                                                           #
# --------------------------------------------------------------------------- #


def test_conflict_warning_text() -> None:
    h1_seg, h1_trans = _heading("h1", [_run("Capítulo")], [_run("Primeira")])
    h2_seg, h2_trans = _heading("h2", [_run("Capítulo")], [_run("Segunda")])
    t_seg, t_trans = _toc("t", [_run("Capítulo\t3")], [_run("X\t3")])

    report = _sync([h1_seg, h2_seg, t_seg], [h1_trans, h2_trans, t_trans])

    assert any("duplicado" in w for w in report.warnings)


def test_blank_heading_and_blank_translation_skipped() -> None:
    # Heading com texto-fonte em branco (mas tradução não-falha) → ignorado
    # porque o source_key fica vazio.
    blank_seg, blank_trans = _heading("hb", [_run("   ")], [_run("algo")])
    # Heading válido no texto, mas tradução só com espaços → canonical vazio.
    empty_tgt_seg, empty_tgt_trans = _heading(
        "he", [_run("Algo")], [_run("   ")]
    )
    empty_tgt_trans.target_text = "x"  # passa pelo guard de falha, canonical vazio
    t_seg, t_trans = _toc("t", [_run("Algo\t1")], [_run("Trad\t1")])

    report = _sync(
        [blank_seg, empty_tgt_seg, t_seg],
        [blank_trans, empty_tgt_trans, t_trans],
    )

    # Nenhum heading entrou no mapa → sumário inalterado.
    assert t_trans.target_runs[0].text == "Trad\t1"
    assert report.synced == 0


def test_blank_toc_run_skipped() -> None:
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    # Run em branco isolado por um <Br/> (não faz parte da entrada seguinte).
    t_seg, t_trans = _toc(
        "t",
        [_run("   ", content_idx=0), _run("Conjuntos\t16", content_idx=1)],
        [_run("   ", content_idx=0), _run("X\t16", content_idx=1)],
        boundaries=[SegmentBoundary(kind="br", after_text_ord=0)],
    )

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "   "  # run em branco intacto
    assert t_trans.target_runs[1].text == "Conjuntos ES\t16"
    assert report.synced == 1


def test_split_title_across_runs_synced() -> None:
    # Caso real "Mundo do trabalho": título partido em 2 runs (2 CSRs dentro de
    # um HyperlinkTextSource filho-direto do PSR), sem <Br/> interno.
    h_seg, h_trans = _heading(
        "h", [_run("Mundo do trabalho")], [_run("Mundo del trabajo")]
    )
    t_seg, t_trans = _toc(
        "t",
        [_run("Mundo do ", content_idx=0), _run("trabalho \t59", run_idx=1)],
        [_run("DIVERG ", content_idx=0), _run("ENTE \t59", run_idx=1)],
        boundaries=[SegmentBoundary(kind="br", after_text_ord=1)],
    )

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    # Título canônico + página vão no 1º run; o 2º run é esvaziado.
    assert t_trans.target_runs[0].text == "Mundo del trabajo\t59"
    assert t_trans.target_runs[1].text == ""
    assert report.synced == 1
    assert report.unmatched_toc_titles == []


def test_mixed_normal_and_split_entries_in_one_paragraph() -> None:
    # Um único parágrafo de sumário com entradas normais + uma partida.
    h_a = _heading("ha", [_run("Eu consumidor")], [_run("Yo consumidor")])
    h_b = _heading("hb", [_run("Mundo do trabalho")], [_run("Mundo del trabajo")])
    src = [
        _run("Eu consumidor\t55", content_idx=0),
        _run("Mundo do ", run_idx=1),
        _run("trabalho \t59", run_idx=2),
    ]
    tgt = [
        _run("Yo consumidor\t55", content_idx=0),
        _run("Mundo do ", run_idx=1),
        _run("trabalho \t59", run_idx=2),
    ]
    bnds = [
        SegmentBoundary(kind="br", after_text_ord=0),
        SegmentBoundary(kind="br", after_text_ord=2),
    ]
    t_seg, t_trans = _toc("t", src, tgt, boundaries=bnds)

    report = _sync([h_a[0], h_b[0], t_seg], [h_a[1], h_b[1], t_trans])

    assert t_trans.target_runs[0].text == "Yo consumidor\t55"
    assert t_trans.target_runs[1].text == "Mundo del trabajo\t59"
    assert t_trans.target_runs[2].text == ""
    assert report.synced == 2


def test_toc_without_translation_is_safe() -> None:
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    t_seg, _ = _toc("t", [_run("Conjuntos\t16")], [_run("X\t16")])

    # Só a tradução do heading é fornecida; a do sumário está ausente.
    report = _sync([h_seg, t_seg], [h_trans])

    assert report.synced == 0


def test_already_consistent_toc_counts_as_synced() -> None:
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    # Sumário já idêntico ao corpo: sem mudança, mas conta como sincronizado.
    t_seg, t_trans = _toc("t", [_run("Conjuntos\t16")], [_run("Conjuntos ES\t16")])

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "Conjuntos ES\t16"
    assert report.synced == 1


def test_entry_skipped_when_target_runs_misaligned() -> None:
    # Defesa: target_runs menor que os runs da entrada → não arrisca reescrever.
    h_seg, h_trans = _heading("h", [_run("Conjuntos")], [_run("Conjuntos ES")])
    t_seg, t_trans = _toc(
        "t",
        [_run("Mundo do ", content_idx=0), _run("trabalho \t59", run_idx=1)],
        [_run("só um run\t59", content_idx=0)],  # target_runs com 1 só
        boundaries=[SegmentBoundary(kind="br", after_text_ord=1)],
    )

    report = _sync([h_seg, t_seg], [h_trans, t_trans])

    assert t_trans.target_runs[0].text == "só um run\t59"  # intacto
    assert report.synced == 0


def test_split_page_suffix_variants() -> None:
    assert _split_page_suffix("Título\t7") == ("Título", "\t7")
    assert _split_page_suffix("Título\t\t148") == ("Título", "\t\t148")
    assert _split_page_suffix("Título\t 23 ") == ("Título", "\t 23 ")
    # Sem TAB → não separa, mesmo terminando em número (ex.: "Capítulo 2").
    assert _split_page_suffix("Capítulo 2") == ("Capítulo 2", "")
    assert _split_page_suffix("Conjuntos") == ("Conjuntos", "")
