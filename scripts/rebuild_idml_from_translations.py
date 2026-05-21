"""Regenera o .idml traduzido a partir dos JSONs já gerados.

Útil quando:
- O .idml foi gerado mas tem algum problema na escrita (ex: bug do writer).
- Você quer reaplicar correções no idml_writer sem pagar OpenAI de novo.

Uso:

    python scripts/rebuild_idml_from_translations.py \\
        --source "Indesign_exemplos/81_Matemática Financeira.idml" \\
        --out-dir out/81-matematica-financeira

Procura ``segments.json`` e ``translations.json`` em ``--out-dir`` e regrava
o ``<slug>_<lang>.idml`` no mesmo lugar.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from idml_to_md.translation.idml_writer import write_translated_idml
from idml_to_md.translation.models import Segment, Translation


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, type=Path, help="IDML original")
    ap.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Pasta com segments.json e translations.json",
    )
    ap.add_argument(
        "--lang",
        default="es",
        help="Sufixo do .idml de saída (default: es)",
    )
    args = ap.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> | {message}")

    segments_path = args.out_dir / "segments.json"
    translations_path = args.out_dir / "translations.json"
    if not segments_path.exists() or not translations_path.exists():
        logger.error(
            "Faltam arquivos: {} ou {}",
            segments_path,
            translations_path,
        )
        return 1

    segments = [
        Segment(**s)
        for s in json.loads(segments_path.read_text(encoding="utf-8"))
    ]
    translations = [
        Translation(**t)
        for t in json.loads(translations_path.read_text(encoding="utf-8"))
    ]
    logger.info(
        "Carregados: {} segmentos, {} traduções",
        len(segments),
        len(translations),
    )

    slug = args.out_dir.name
    target = args.out_dir / f"{slug}_{args.lang}.idml"
    xml_dump = args.out_dir / "xml_traduzido"

    stats = write_translated_idml(
        source_idml=args.source,
        target_idml=target,
        segments=segments,
        translations=translations,
        xml_dump_dir=xml_dump,
    )
    logger.info(
        "IDML regravado em {} (stories={}, contents={})",
        target,
        stats["stories_modified"],
        stats["contents_replaced"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
