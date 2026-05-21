"""CLI Typer ``idml-queue``: traduz uma pasta de livros IDML em lote.

Lê ``Input/<Livro>/`` (cada um com ``.idml`` + ``Links/`` + ``Document fonts/``),
gera ``Output/<Livro>/`` pronto para o InDesign e arquiva o original em
``FEITOS/`` (sucesso) ou ``FALHAS/`` (falha). Ver :mod:`queue_runner`.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from idml_to_md.translation.pipeline import TranslationConfig
from idml_to_md.translation.queue_runner import BookStatus, QueueResult, run_queue

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

app = typer.Typer(
    name="idml-queue",
    help="Traduz uma pasta de livros IDML em lote (Input → Output, arquiva em FEITOS/FALHAS).",
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
def queue(
    input_dir: Path = typer.Option(
        Path("Input"),
        "--input",
        "-i",
        file_okay=False,
        help="Pasta com uma subpasta por livro a traduzir.",
    ),
    output_dir: Path = typer.Option(
        Path("Output"),
        "--output",
        "-o",
        file_okay=False,
        help="Pasta-raiz de entrega (uma subpasta por livro).",
    ),
    done_dir: Path = typer.Option(
        Path("FEITOS"),
        "--done",
        file_okay=False,
        help="Pasta para onde o livro original vai após sucesso.",
    ),
    failed_dir: Path = typer.Option(
        Path("FALHAS"),
        "--failed",
        file_okay=False,
        help="Pasta para onde o livro original vai após falha.",
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
    only: list[str] | None = typer.Option(
        None,
        "--only",
        help=(
            "Processa só o(s) livro(s) com esse nome de subpasta em --input "
            "(repetível). Sem --only, processa todos."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Só extrai segmentos por livro; NÃO chama a OpenAI, não gera .idml nem arquiva.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Processa todos os livros de ``--input`` e imprime o resumo da fila."""
    _setup_logging(verbose)
    _load_env_file()

    if not input_dir.is_dir():
        console.print(f"[red]Pasta de input não encontrada:[/] {input_dir}")
        raise typer.Exit(code=2)

    cfg = TranslationConfig.from_yaml(config) if config else TranslationConfig()
    if target_lang:
        cfg = _override(cfg, target_lang=target_lang)
    if model:
        cfg = _override(cfg, model=model)

    result = run_queue(
        input_dir=input_dir,
        output_root=output_dir,
        done_root=done_dir,
        failed_root=failed_dir,
        config=cfg,
        styles_overlay=styles_overlay,
        only=only,
        dry_run=dry_run,
    )

    _print_summary(result)
    if result.failed:
        raise typer.Exit(code=1)


def _override(cfg: TranslationConfig, **kwargs: object) -> TranslationConfig:
    """Cria uma cópia da config com campos sobrescritos."""
    return replace(cfg, **kwargs)  # type: ignore[arg-type]


_STATUS_STYLE: dict[BookStatus, str] = {
    BookStatus.DONE: "green",
    BookStatus.FAILED: "red",
    BookStatus.SKIPPED: "yellow",
}


def _print_summary(result: QueueResult) -> None:
    table = Table(title="Fila de tradução")
    table.add_column("Livro", overflow="fold")
    table.add_column("Status")
    table.add_column("Completude")
    table.add_column("Detalhe", overflow="fold")

    for o in result.outcomes:
        style = _STATUS_STYLE.get(o.status, "white")
        completeness = "—" if o.completeness_ok is None else ("OK" if o.completeness_ok else "FALHA")
        table.add_row(
            o.name,
            f"[{style}]{o.status.value}[/]",
            completeness,
            o.error or "",
        )

    console.print(table)
    console.print(
        f"[bold]Total:[/] {len(result.done)} feitos, "
        f"{len(result.failed)} falhas, {len(result.skipped)} pulados"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
