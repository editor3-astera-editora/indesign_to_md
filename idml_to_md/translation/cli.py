"""CLI Typer ``idml-translate``.

Comandos:
- ``translate`` — pipeline completo (PT→ES) gerando .idml + XMLs.
- ``extract`` — só extração de segmentos (atalho para inspeção).
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console

from idml_to_md.translation.pipeline import (
    TranslationConfig,
    translate_idml,
)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

app = typer.Typer(
    name="idml-translate",
    help="Traduz livros IDML preservando layout para reabrir no InDesign.",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="<level>{level: <7}</level> | {message}")


def _load_env_file() -> None:
    """Carrega variáveis do .env do cwd (ou raiz do projeto), se existir."""
    if load_dotenv is None:
        return
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


@app.command()
def translate(
    idml_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output_dir: Path = typer.Option(
        Path("out"), "--output", "-o", file_okay=False, help="Pasta-pai do output."
    ),
    target_lang: str = typer.Option(
        "es", "--target-lang", "-l", help="Código do idioma destino (es, en, fr…)."
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        exists=True,
        dir_okay=False,
        help="YAML de configuração da tradução (modelo, batch_size, marcas, etc.).",
    ),
    styles_overlay: Path | None = typer.Option(
        None,
        "--styles",
        exists=True,
        dir_okay=False,
        help="Overlay YAML para style_mapper (usado para classificar paragraph_kind).",
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Override do modelo OpenAI (default: do config)."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Só extrai segmentos e gera relatório; NÃO chama a OpenAI nem grava .idml.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Traduz um IDML completo e gera o .idml em ``out/<slug>/<slug>_<lang>.idml``."""
    _setup_logging(verbose)
    _load_env_file()

    cfg = TranslationConfig.from_yaml(config) if config else TranslationConfig()
    if target_lang:
        cfg = _override(cfg, target_lang=target_lang)
    if model:
        cfg = _override(cfg, model=model)

    result = translate_idml(
        idml_path=idml_path,
        output_dir=output_dir,
        config=cfg,
        styles_overlay=styles_overlay,
        dry_run=dry_run,
    )

    if dry_run:
        console.print(f"[yellow]dry-run[/] — segmentos em {result.segments_path}")
    else:
        console.print(f"[green]OK[/] {result.target_idml}")
    console.print(f"[dim]segments:[/] {result.segments_path}")
    console.print(f"[dim]translations:[/] {result.translations_path}")
    console.print(f"[dim]report:[/] {result.report_path}")
    console.print(
        f"[dim]xmls:[/] {result.output_dir / 'xml_original'} | "
        f"{result.output_dir / 'xml_traduzido'}"
    )

    report = result.report
    console.print(
        f"[bold]Segments:[/] {report.total_segments} totais, "
        f"{report.translated_segments} traduzidos, {report.skipped_segments} pulados"
    )
    if not dry_run:
        console.print(
            f"[bold]Custo estimado:[/] US$ {report.estimated_cost_usd:.4f} "
            f"({report.total_prompt_tokens}+{report.total_completion_tokens} tokens)"
        )
    if report.equation_alerts:
        console.print(
            f"[yellow]Aviso:[/] {len(report.equation_alerts)} equações com termos PT — revisar MathType"
        )
    if report.warnings:
        console.print(f"[yellow]Avisos diversos:[/] {len(report.warnings)} (ver report)")


def _override(cfg: TranslationConfig, **kwargs: object) -> TranslationConfig:
    """Cria uma cópia da config com campos sobrescritos."""
    return replace(cfg, **kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    app()
