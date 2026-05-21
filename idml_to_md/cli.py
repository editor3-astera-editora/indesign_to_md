"""Entry-point CLI (Typer)."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from idml_to_md import __version__
from idml_to_md.pipeline import convert_idml, inspect_styles

app = typer.Typer(
    name="idml2md",
    help="Converte livros do Adobe InDesign (.idml) para Markdown estruturado.",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="<level>{level: <7}</level> | {message}")


@app.command()
def version() -> None:
    """Mostra a versão instalada."""
    typer.echo(__version__)


@app.command()
def convert(
    idml_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output_dir: Path = typer.Option(
        Path("out"), "--output", "-o", file_okay=False, help="Pasta-pai do output."
    ),
    overlay: Path | None = typer.Option(
        None, "--config", "-c", exists=True, dir_okay=False, help="YAML overlay de estilos."
    ),
    title: str | None = typer.Option(
        None, "--title", "-t", help="Título do livro. Default: nome do arquivo."
    ),
    links: Path | None = typer.Option(
        None, "--links", file_okay=False, help='Pasta Links/. Default: "<idml>/../Links".'
    ),
    inkscape: Path | None = typer.Option(
        None,
        "--inkscape",
        exists=True,
        dir_okay=False,
        help="Caminho do inkscape.exe (override de PATH e IDML2MD_INKSCAPE_PATH).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Converte um IDML para um único arquivo Markdown."""
    _setup_logging(verbose)
    result = convert_idml(
        idml_path=idml_path,
        output_dir=output_dir,
        overlay_path=overlay,
        book_title=title,
        links_dir=links,
        inkscape_path=inkscape,
    )
    console.print(f"[green]OK[/] {result.markdown_path}")
    console.print(f"[dim]report:[/] {result.report_path}")
    if result.report.unmapped_paragraph_styles:
        n = len(result.report.unmapped_paragraph_styles)
        console.print(f"[yellow]Aviso:[/] {n} ParagraphStyles não mapeados (ver report)")
    if result.report.missing_assets:
        console.print(f"[yellow]Aviso:[/] {len(result.report.missing_assets)} assets faltando")


@app.command()
def inspect(
    idml_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    top: int = typer.Option(0, "--top", help="Mostrar apenas os N mais usados. 0 = todos."),
) -> None:
    """Lista ParagraphStyles encontrados no IDML, com contagem de uso."""
    counts = inspect_styles(idml_path)
    items = counts.most_common(top or None)

    table = Table(title=f"ParagraphStyles em {idml_path.name}")
    table.add_column("Estilo", overflow="fold")
    table.add_column("Uso", justify="right")
    for name, n in items:
        table.add_row(name, str(n))
    console.print(table)
    console.print(f"[dim]Total de estilos distintos:[/] {len(counts)}")


if __name__ == "__main__":  # pragma: no cover
    app()
