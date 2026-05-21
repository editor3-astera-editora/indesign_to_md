"""Verifica se TUDO do IDML original está presente no IDML traduzido.

Gate de QA estrutural (não avalia a qualidade da tradução). Use antes de abrir
o ``.idml`` traduzido no InDesign / exportar o PDF.

Uso:

    python scripts/verify_translation_completeness.py \\
        --source "Indesign_exemplos/81_Matemática Financeira.idml" \\
        --translated "out/81-matematica-financeira/81-matematica-financeira_es.idml" \\
        --json out/_completeness.json

Sai com código 0 se PASS (nada faltando) e 1 se FAIL (algo divergiu), para uso
em CI/scripts de entrega.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from idml_to_md.translation.completeness_checker import check_completeness


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, type=Path, help="IDML original (PT)")
    ap.add_argument("--translated", required=True, type=Path, help="IDML traduzido")
    ap.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Se fornecido, grava o relatório completo em JSON neste caminho.",
    )
    args = ap.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> | {message}")

    for label, path in (("--source", args.source), ("--translated", args.translated)):
        if not path.is_file():
            logger.error("Arquivo {} não encontrado: {}", label, path)
            return 2

    report = check_completeness(args.source, args.translated)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Relatório gravado em {}", args.json)

    # Detalhes acionáveis (limitados para não inundar o terminal)
    def _show(title: str, items: list[str], limit: int = 15) -> None:
        if not items:
            return
        logger.warning("{} ({}):", title, len(items))
        for item in items[:limit]:
            logger.warning("    {}", item)
        if len(items) > limit:
            logger.warning("    … (+{} mais)", len(items) - limit)

    _show("Stories com estrutura divergente", report.story_count_diffs)
    _show("Parágrafos com texto PERDIDO", report.lost_paragraphs)
    _show("Self ausentes no traduzido", report.self_ids_missing)
    _show("Self extras no traduzido", report.self_ids_extra)
    _show("Self duplicados no traduzido", report.self_ids_new_duplicates)
    _show("XML malformado", report.malformed_xml)

    if report.ok:
        logger.success("PASS — {}", report.summary)
        return 0
    logger.error("{}", report.summary)
    return 1


if __name__ == "__main__":
    sys.exit(main())
