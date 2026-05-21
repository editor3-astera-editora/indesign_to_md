"""Orquestrador da conversão IDML → Markdown único.

Fluxo:

1. Abre o IDML.
2. Resolve a ordem de leitura das Stories (thread_resolver).
3. Para cada Story em ordem: ``story_walker`` extrai blocos + front matter +
   referências.
4. ``asset_processor`` copia imagens raster referenciadas.
5. ``md_writer`` serializa o ``Document``; ``toc_builder`` insere TOC.
6. Grava ``<book_slug>.md`` + ``_report.json``.

API:

>>> from pathlib import Path
>>> from idml_to_md.pipeline import convert_idml
>>> result = convert_idml(Path("livro.idml"), Path("out"))
>>> result.markdown_path.exists()
True
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from idml_to_md.asset_processor import process_raster_assets, process_vector_assets
from idml_to_md.idml_reader import IDMLDocument
from idml_to_md.mathml_to_latex import EquationConverter
from idml_to_md.md_writer import render_document
from idml_to_md.models import Document, ImageBlock
from idml_to_md.report import ConversionReport, build_report
from idml_to_md.story_walker import walk_story
from idml_to_md.style_mapper import build_style_map, normalize_style_name
from idml_to_md.thread_resolver import resolve_reading_order
from idml_to_md.utils.slugify import slugify


@dataclass(slots=True)
class ConversionResult:
    """Caminhos finais e métricas da conversão."""

    markdown_path: Path
    report_path: Path
    report: ConversionReport
    output_dir: Path


def convert_idml(
    idml_path: Path,
    output_dir: Path,
    overlay_path: Path | None = None,
    book_title: str | None = None,
    links_dir: Path | None = None,
    inkscape_path: Path | None = None,
) -> ConversionResult:
    """Converte um arquivo .idml e seus assets em um único Markdown.

    Args:
        idml_path: caminho do .idml.
        output_dir: pasta-pai do output. Será criado ``output_dir/<slug>/``.
        overlay_path: YAML opcional de override sobre ``styles.default.yaml``.
        book_title: título do livro. Default: stem do arquivo .idml.
        links_dir: pasta ``Links/`` do projeto editorial. Default:
            ``idml_path.parent / "Links"``.
        inkscape_path: caminho explícito para ``inkscape.exe``. Default:
            env var ``IDML2MD_INKSCAPE_PATH``, PATH ou caminhos comuns.
    """
    idml_path = Path(idml_path).resolve()
    output_dir = Path(output_dir).resolve()
    links_dir = links_dir or (idml_path.parent / "Links")

    title = book_title or _derive_title(idml_path)
    slug = slugify(title)
    book_out = output_dir / slug
    book_out.mkdir(parents=True, exist_ok=True)
    raster_dir = book_out / "assets" / "img"
    vector_dir = book_out / "assets" / "vector"

    style_map = build_style_map(overlay_path=overlay_path)
    cache_rel = style_map.equations_config.get("cache_dir") or ".cache/idml2md/equations"
    cache_dir = Path(cache_rel)
    converter = EquationConverter(cache_dir=cache_dir)

    logger.info("Abrindo IDML: {}", idml_path.name)
    with IDMLDocument(idml_path) as doc:
        order = resolve_reading_order(doc)
        logger.info("Stories em ordem: {}", len(order))

        document = Document(title=title, slug=slug)
        requested_rasters: list[str] = []
        requested_vectors: list[str] = []
        equation_count = 0
        failed_equations: list[str] = []

        for entry in order:
            story_root = doc.get_story_root(entry.story_id)
            if story_root is None:
                logger.warning("Story ausente: {}", entry.story_id)
                continue
            result = walk_story(story_root, style_map, converter=converter, links_dir=links_dir)
            document.front_matter.extend(result.front_matter)
            document.blocks.extend(result.body)
            document.references.extend(result.references)
            requested_rasters.extend(result.image_basenames)
            requested_vectors.extend(result.vector_basenames)
            equation_count += len(result.equation_basenames)
            failed_equations.extend(result.failed_equations)

        raster_map = process_raster_assets(
            requested_basenames=requested_rasters,
            links_dir=links_dir,
            output_assets_dir=raster_dir,
        )
        vector_map = process_vector_assets(
            requested_basenames=requested_vectors,
            links_dir=links_dir,
            output_vector_dir=vector_dir,
            inkscape_path=inkscape_path,
        )

    # Merge dos mapeamentos para reescrita de paths das imagens
    combined_paths = {**raster_map.output_relative, **vector_map.output_relative}
    _rewrite_image_paths(document, combined_paths)

    markdown = render_document(document)
    md_path = book_out / f"{slug}.md"
    md_path.write_text(markdown, encoding="utf-8")

    report = build_report(
        doc=document,
        seen_paragraph=style_map.seen_paragraph_styles,
        unmapped_paragraph=style_map.unmapped_paragraph_styles,
        seen_character=style_map.seen_character_styles,
        unmapped_character=style_map.unmapped_character_styles,
        missing_assets=[*raster_map.missing, *vector_map.missing],
        copied_assets=len(raster_map.output_relative) + len(vector_map.output_relative),
        equations_total=equation_count,
        equations_failed=failed_equations,
        equation_cache_hits=converter.stats.cache_hits,
        equation_cache_misses=converter.stats.cache_misses,
        vector_converted=vector_map.vector_converted,
        vector_failed=vector_map.vector_failed,
    )
    report_path = book_out / "_report.json"
    report.write(report_path)

    logger.info("Conversão concluída → {}", md_path)
    return ConversionResult(
        markdown_path=md_path,
        report_path=report_path,
        report=report,
        output_dir=book_out,
    )


def _derive_title(idml_path: Path) -> str:
    """Limpa o stem: remove prefixos numéricos comuns (``81_``, ``v3_``)."""
    stem = idml_path.stem
    # mantém o nome o mais editorial possível
    return stem.replace("_", " ").strip()


def _rewrite_image_paths(document: Document, mapping: dict[str, str]) -> None:
    """Substitui ``src`` dos ``ImageBlock`` pelo caminho relativo final."""
    for block in document.blocks:
        if isinstance(block, ImageBlock):
            block.src = mapping.get(block.src, block.src)


def inspect_styles(idml_path: Path) -> Counter[str]:
    """Lista ParagraphStyles encontrados no IDML com contagem por uso real.

    Útil para criar overlays YAML por coleção sem adivinhar.
    """
    counter: Counter[str] = Counter()
    with IDMLDocument(Path(idml_path).resolve()) as doc:
        for path in doc.story_paths():
            story_id = path.removeprefix("Stories/Story_").removesuffix(".xml")
            root = doc.get_story_root(story_id)
            if root is None:
                continue
            for psr in root.iter("ParagraphStyleRange"):
                applied = psr.get("AppliedParagraphStyle") or ""
                counter[normalize_style_name(applied)] += 1
    return counter
