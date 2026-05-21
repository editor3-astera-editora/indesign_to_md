"""Testes do CLI ``idml-queue`` (fila de tradução em lote)."""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from idml_to_md.translation.queue_cli import app


def test_queue_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "input" in result.output.lower() or "queue" in result.output.lower()


def test_queue_missing_input_dir(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--input", str(tmp_path / "naoexiste")])
    assert result.exit_code == 2


def test_queue_dry_run_end_to_end(minimal_idml: Path, tmp_path: Path) -> None:
    """Dry-run real (sem OpenAI): usa o caminho de extração de ``translate_idml``."""
    inp = tmp_path / "Input"
    book = inp / "livro"
    (book / "Links").mkdir(parents=True)
    (book / "Document fonts").mkdir(parents=True)
    shutil.copy(minimal_idml, book / "livro.idml")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--input",
            str(inp),
            "--output",
            str(tmp_path / "Output"),
            "--done",
            str(tmp_path / "FEITOS"),
            "--failed",
            str(tmp_path / "FALHAS"),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "Output" / "livro" / "out" / "segments.json").is_file()
    # Dry-run não arquiva nem gera IDML traduzido
    assert book.exists()
    assert not (tmp_path / "FEITOS" / "livro").exists()
    assert not (tmp_path / "Output" / "livro" / "livro_es.idml").exists()
