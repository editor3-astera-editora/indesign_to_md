"""Testes da fila de tradução em lote (``queue_runner``).

A função de tradução é injetada (fake), então estes testes exercitam só a
orquestração da fila: descoberta, montagem da entrega, gate de completude e
arquivamento em FEITOS/FALHAS — sem OpenAI nem IDML real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from idml_to_md.translation import queue_runner
from idml_to_md.translation.pipeline import TranslationConfig, TranslationResult
from idml_to_md.translation.queue_runner import (
    BookJob,
    BookStatus,
    discover_books,
    process_book,
    run_queue,
)

CONFIG = TranslationConfig(target_lang="es")


# --------------------------------------------------------------------------- #
# Fakes injetáveis
# --------------------------------------------------------------------------- #
class _FakeCompleteness:
    """Stub mínimo de ``CompletenessReport`` (só o que ``process_book`` usa)."""

    def __init__(self, ok: bool) -> None:
        self.ok = ok
        self.summary = "OK — nada faltando." if ok else "FALHA — texto perdido"

    def model_dump_json(self, indent: int = 2) -> str:
        return json.dumps({"ok": self.ok, "summary": self.summary}, indent=indent)


def _verify(ok: bool) -> queue_runner.VerifyFn:
    def _fn(source: Path, translated: Path) -> _FakeCompleteness:  # type: ignore[return-value]
        return _FakeCompleteness(ok)

    return _fn  # type: ignore[return-value]


def _verify_fail_for(substr: str) -> queue_runner.VerifyFn:
    def _fn(source: Path, translated: Path) -> _FakeCompleteness:  # type: ignore[return-value]
        return _FakeCompleteness(substr not in str(source))

    return _fn  # type: ignore[return-value]


def _fake_translate(
    idml_path: Path,
    output_dir: Path,
    *,
    config: TranslationConfig,
    styles_overlay: Path | None = None,
    dry_run: bool = False,
) -> TranslationResult:
    """Imita ``translate_idml``: escreve em ``output_dir/<slug>/`` e retorna paths."""
    slug = "the-book"
    slug_dir = Path(output_dir) / slug
    slug_dir.mkdir(parents=True, exist_ok=True)

    segments_path = slug_dir / "segments.json"
    segments_path.write_text("[]", encoding="utf-8")
    (slug_dir / "xml_original").mkdir(exist_ok=True)
    target_idml = slug_dir / f"{slug}_{config.target_lang}.idml"
    translations_path = slug_dir / "translations.json"
    report_path = slug_dir / "_translation_report.json"

    if not dry_run:
        translations_path.write_text("[]", encoding="utf-8")
        report_path.write_text("{}", encoding="utf-8")
        (slug_dir / "xml_traduzido").mkdir(exist_ok=True)
        target_idml.write_bytes(b"PKfakeidml")

    return TranslationResult(
        target_idml=target_idml,
        segments_path=segments_path,
        translations_path=translations_path,
        report_path=report_path,
        report=None,  # type: ignore[arg-type]  # não lido por process_book
        output_dir=slug_dir,
    )


def _raising_translate(*args: object, **kwargs: object) -> TranslationResult:
    raise RuntimeError("boom na tradução")


# --------------------------------------------------------------------------- #
# Helpers de fixture
# --------------------------------------------------------------------------- #
def _make_book(input_dir: Path, name: str, *, with_assets: bool = True) -> Path:
    folder = input_dir / name
    folder.mkdir(parents=True)
    (folder / f"{name}.idml").write_bytes(b"PKsource")  # conteúdo irrelevante (fake)
    (folder / f"{name}.indd").write_bytes(b"indd")
    if with_assets:
        (folder / "Links").mkdir()
        (folder / "Links" / "img.jpg").write_bytes(b"jpg")
        (folder / "Document fonts").mkdir()
        (folder / "Document fonts" / "font.otf").write_bytes(b"otf")
    return folder


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    return tmp_path / "Output", tmp_path / "FEITOS", tmp_path / "FALHAS"


def _job(folder: Path) -> BookJob:
    idml = next(folder.glob("*.idml"))
    return BookJob(name=folder.name, folder=folder, idml_path=idml)


# --------------------------------------------------------------------------- #
# discover_books
# --------------------------------------------------------------------------- #
def test_discover_books_orders_and_skips(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    inp.mkdir()
    _make_book(inp, "b")
    _make_book(inp, "a")
    (inp / "sem-idml").mkdir()  # subpasta sem .idml → pulada
    (inp / "solto.txt").write_text("x")  # arquivo solto → ignorado

    jobs = discover_books(inp)

    assert [j.name for j in jobs] == ["a", "b"]
    assert jobs[0].idml_path.name == "a.idml"


def test_discover_books_multiple_idml_uses_first(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    folder = inp / "livro"
    folder.mkdir(parents=True)
    (folder / "a2.idml").write_bytes(b"x")
    (folder / "a1.idml").write_bytes(b"x")

    jobs = discover_books(inp)

    assert len(jobs) == 1
    assert jobs[0].idml_path.name == "a1.idml"


# --------------------------------------------------------------------------- #
# process_book
# --------------------------------------------------------------------------- #
def test_process_book_success(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    folder = _make_book(inp, "livro")
    output, done, failed = _roots(tmp_path)

    outcome = process_book(
        _job(folder),
        output,
        done,
        failed,
        config=CONFIG,
        translate_fn=_fake_translate,
        verify_fn=_verify(True),
    )

    assert outcome.status is BookStatus.DONE
    assert outcome.completeness_ok is True

    delivery = output / "livro"
    assert (delivery / "livro_es.idml").is_file()
    # Artefatos achatados em out/ (sem subpasta <slug>)
    out = delivery / "out"
    for artifact in ("segments.json", "translations.json", "_translation_report.json"):
        assert (out / artifact).is_file()
    assert (out / "xml_original").is_dir()
    assert (out / "xml_traduzido").is_dir()
    assert (out / "_completeness.json").is_file()
    assert not (out / "the-book").exists()
    # Assets copiados
    assert (delivery / "Links" / "img.jpg").is_file()
    assert (delivery / "Document fonts" / "font.otf").is_file()
    # Original arquivado em FEITOS, removido de Input
    assert not folder.exists()
    assert (done / "livro" / "livro.idml").is_file()
    assert not failed.exists() or not any(failed.iterdir())


def test_process_book_completeness_fail_goes_to_falhas(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    folder = _make_book(inp, "livro")
    output, done, failed = _roots(tmp_path)

    outcome = process_book(
        _job(folder),
        output,
        done,
        failed,
        config=CONFIG,
        translate_fn=_fake_translate,
        verify_fn=_verify(False),
    )

    assert outcome.status is BookStatus.FAILED
    assert outcome.completeness_ok is False
    assert outcome.error and "FALHA" in outcome.error
    # Output parcial preservado
    assert (output / "livro" / "livro_es.idml").is_file()
    # Original em FALHAS, não em FEITOS
    assert (failed / "livro").is_dir()
    assert not (done / "livro").exists()
    assert not folder.exists()


def test_process_book_translate_raises_goes_to_falhas(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    folder = _make_book(inp, "livro")
    output, done, failed = _roots(tmp_path)

    outcome = process_book(
        _job(folder),
        output,
        done,
        failed,
        config=CONFIG,
        translate_fn=_raising_translate,
        verify_fn=_verify(True),
    )

    assert outcome.status is BookStatus.FAILED
    assert outcome.error and "boom" in outcome.error
    assert (failed / "livro").is_dir()
    assert not (done / "livro").exists()


def test_process_book_dry_run(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    folder = _make_book(inp, "livro")
    output, done, failed = _roots(tmp_path)

    outcome = process_book(
        _job(folder),
        output,
        done,
        failed,
        config=CONFIG,
        dry_run=True,
        translate_fn=_fake_translate,
        verify_fn=_verify(True),
    )

    assert outcome.status is BookStatus.SKIPPED
    out = output / "livro" / "out"
    assert (out / "segments.json").is_file()
    assert not (output / "livro" / "livro_es.idml").exists()
    # Nada movido no dry-run
    assert folder.exists()
    assert not (done / "livro").exists()
    assert not (failed / "livro").exists()


def test_process_book_missing_assets_still_succeeds(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    folder = _make_book(inp, "livro", with_assets=False)
    output, done, failed = _roots(tmp_path)

    outcome = process_book(
        _job(folder),
        output,
        done,
        failed,
        config=CONFIG,
        translate_fn=_fake_translate,
        verify_fn=_verify(True),
    )

    assert outcome.status is BookStatus.DONE
    assert not (output / "livro" / "Links").exists()


def test_process_book_cleans_existing_delivery(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    folder = _make_book(inp, "livro")
    output, done, failed = _roots(tmp_path)
    stale = output / "livro" / "out" / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("antigo")

    process_book(
        _job(folder),
        output,
        done,
        failed,
        config=CONFIG,
        translate_fn=_fake_translate,
        verify_fn=_verify(True),
    )

    assert not stale.exists()


# --------------------------------------------------------------------------- #
# run_queue
# --------------------------------------------------------------------------- #
def test_run_queue_mixed_continues_on_failure(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    inp.mkdir()
    _make_book(inp, "ok1")
    _make_book(inp, "bad")
    _make_book(inp, "ok2")
    output, done, failed = _roots(tmp_path)

    result = run_queue(
        inp,
        output,
        done,
        failed,
        config=CONFIG,
        translate_fn=_fake_translate,
        verify_fn=_verify_fail_for("bad"),
    )

    assert {o.name for o in result.done} == {"ok1", "ok2"}
    assert {o.name for o in result.failed} == {"bad"}
    assert result.skipped == []
    assert (done / "ok1").is_dir()
    assert (done / "ok2").is_dir()
    assert (failed / "bad").is_dir()


def test_run_queue_empty_input(tmp_path: Path) -> None:
    inp = tmp_path / "Input"
    inp.mkdir()
    output, done, failed = _roots(tmp_path)

    result = run_queue(inp, output, done, failed, config=CONFIG)

    assert result.outcomes == []
    assert output.is_dir() and done.is_dir() and failed.is_dir()


# --------------------------------------------------------------------------- #
# Helpers privados
# --------------------------------------------------------------------------- #
def test_move_folder_collision_suffixes(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("novo")
    dst_parent = tmp_path / "dst"
    existing = dst_parent / "src"
    existing.mkdir(parents=True)
    (existing / "old.txt").write_text("antigo")

    moved = queue_runner._move_folder(src, dst_parent / "src")

    assert moved != existing
    assert moved.name.startswith("src__")
    assert (moved / "f.txt").read_text() == "novo"
    assert (existing / "old.txt").read_text() == "antigo"  # arquivo anterior intacto
    assert not src.exists()


def test_flatten_slug_dir_overwrites_existing(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "f.txt").write_text("antigo")
    (dest / "d").mkdir()
    (dest / "d" / "x").write_text("x antigo")

    slug = dest / "slug"
    slug.mkdir()
    (slug / "f.txt").write_text("novo")
    (slug / "d").mkdir()
    (slug / "d" / "y").write_text("y novo")

    queue_runner._flatten_slug_dir(slug, dest)

    assert not slug.exists()
    assert (dest / "f.txt").read_text() == "novo"
    assert (dest / "d" / "y").read_text() == "y novo"
    assert not (dest / "d" / "x").exists()  # dir antigo substituído


@pytest.mark.parametrize("scenario", ["missing", "equal"])
def test_flatten_slug_dir_noop(tmp_path: Path, scenario: str) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    slug = (dest / "nope") if scenario == "missing" else dest
    queue_runner._flatten_slug_dir(slug, dest)  # não deve levantar
    assert dest.is_dir()
