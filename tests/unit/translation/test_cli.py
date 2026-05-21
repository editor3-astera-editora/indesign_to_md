"""Testes do CLI ``idml-translate``."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from idml_to_md.translation.cli import app


def test_translate_dry_run(minimal_idml: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            str(minimal_idml),
            "--output",
            str(tmp_path / "out"),
            "--target-lang",
            "es",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output.lower()
    out_dir = tmp_path / "out"
    slugs = list(out_dir.iterdir())
    assert slugs, "esperava criar pelo menos um subdiretório do livro"
    assert (slugs[0] / "segments.json").exists()
    assert (slugs[0] / "xml_original").is_dir()


def test_translate_with_config(
    minimal_idml: Path, tmp_path: Path, project_root: Path
) -> None:
    runner = CliRunner()
    config_path = project_root / "config" / "translation.yaml"
    result = runner.invoke(
        app,
        [
            str(minimal_idml),
            "--output",
            str(tmp_path / "out"),
            "--config",
            str(config_path),
            "--dry-run",
            "--verbose",
        ],
    )
    assert result.exit_code == 0, result.output


def test_translate_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Quando há só um comando, Typer expõe seus options diretamente no root
    assert "idml" in result.output.lower() or "translate" in result.output.lower()
