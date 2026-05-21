"""Coleta e serializa métricas de auditoria de uma conversão.

Gera um ``_report.json`` ao lado do MD com:
- Estilos não mapeados (ParagraphStyle e CharacterStyle) com contagem
- Estilos vistos (auditoria positiva)
- Assets faltando
- Contagem de blocos por tipo
- Versão da ferramenta usada
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from idml_to_md import __version__
from idml_to_md.models import Block, Document


@dataclass(slots=True)
class ConversionReport:
    """Estrutura serializável do relatório."""

    tool_version: str = __version__
    book_slug: str = ""
    book_title: str = ""
    seen_paragraph_styles: dict[str, int] = field(default_factory=dict)
    unmapped_paragraph_styles: dict[str, int] = field(default_factory=dict)
    seen_character_styles: dict[str, int] = field(default_factory=dict)
    unmapped_character_styles: dict[str, int] = field(default_factory=dict)
    block_counts: dict[str, int] = field(default_factory=dict)
    missing_assets: list[str] = field(default_factory=list)
    copied_assets: int = 0
    front_matter_blocks: int = 0
    body_blocks: int = 0
    reference_entries: int = 0
    equations_total: int = 0
    equations_failed: list[str] = field(default_factory=list)
    equation_cache_hits: int = 0
    equation_cache_misses: int = 0
    vector_converted: list[str] = field(default_factory=list)
    vector_failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")


def count_blocks(blocks: list[Block]) -> dict[str, int]:
    """Conta blocos por ``kind`` (chave do enum)."""
    counter: Counter[str] = Counter()
    for block in blocks:
        kind = getattr(block, "kind", None)
        if kind is not None:
            counter[str(kind)] += 1
    return dict(counter)


def build_report(
    doc: Document,
    seen_paragraph: Counter[str],
    unmapped_paragraph: Counter[str],
    seen_character: Counter[str],
    unmapped_character: Counter[str],
    missing_assets: list[str],
    copied_assets: int,
    equations_total: int = 0,
    equations_failed: list[str] | None = None,
    equation_cache_hits: int = 0,
    equation_cache_misses: int = 0,
    vector_converted: list[str] | None = None,
    vector_failed: list[str] | None = None,
) -> ConversionReport:
    """Monta um ``ConversionReport`` a partir das peças do pipeline."""
    return ConversionReport(
        book_slug=doc.slug,
        book_title=doc.title,
        seen_paragraph_styles=dict(seen_paragraph),
        unmapped_paragraph_styles=dict(unmapped_paragraph),
        seen_character_styles=dict(seen_character),
        unmapped_character_styles=dict(unmapped_character),
        block_counts=count_blocks(doc.blocks),
        missing_assets=list(missing_assets),
        copied_assets=copied_assets,
        front_matter_blocks=len(doc.front_matter),
        body_blocks=len(doc.blocks),
        reference_entries=len(doc.references),
        equations_total=equations_total,
        equations_failed=list(equations_failed or []),
        equation_cache_hits=equation_cache_hits,
        equation_cache_misses=equation_cache_misses,
        vector_converted=list(vector_converted or []),
        vector_failed=list(vector_failed or []),
    )
