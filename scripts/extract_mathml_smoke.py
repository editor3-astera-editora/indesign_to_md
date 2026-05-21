"""Smoke test: extrai MathML e converte para LaTeX em todos os EPS de uma pasta.

Uso:

    python scripts/extract_mathml_smoke.py <pasta_com_eps>

Critério F2: ≥ 95% dos EPS MathType convertem com sucesso.

Exit code:
- 0 se taxa OK
- 1 se taxa abaixo do limite ou se nenhum EPS for encontrado
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from idml_to_md.equation_extractor import (
    EquationExtractionError,
    extract_mathml,
)
from idml_to_md.mathml_to_latex import EquationConverter, MathMLConversionError

THRESHOLD = 0.95


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("links_dir", type=Path, help="Pasta com arquivos .eps")
    parser.add_argument("--verbose", action="store_true", help="Mostra cada equação")
    parser.add_argument(
        "--threshold",
        type=float,
        default=THRESHOLD,
        help=f"Taxa mínima de sucesso (default {THRESHOLD})",
    )
    args = parser.parse_args()

    if not args.links_dir.is_dir():
        print(f"ERRO: pasta inexistente: {args.links_dir}", file=sys.stderr)
        return 1

    eps_files = sorted(args.links_dir.glob("*.eps"))
    if not eps_files:
        print(f"ERRO: nenhum .eps em {args.links_dir}", file=sys.stderr)
        return 1

    conv = EquationConverter()
    ok = skip = fail = 0
    failures: list[tuple[str, str]] = []

    for eps in eps_files:
        try:
            extracted = extract_mathml(eps)
        except EquationExtractionError:
            skip += 1
            if args.verbose:
                print(f"SKIP {eps.name} (sem MathType)")
            continue
        try:
            latex = conv.convert(extracted.mathml)
        except MathMLConversionError as exc:
            fail += 1
            failures.append((eps.name, str(exc)))
            continue
        ok += 1
        if args.verbose:
            print(f"OK   {eps.name} -> {latex[:80]}")

    total = ok + skip + fail
    mathtype_total = ok + fail
    rate = ok / mathtype_total if mathtype_total else 0.0

    print()
    print(f"Total EPS:           {total}")
    print(f"  OK (MathML→LaTeX): {ok}")
    print(f"  SKIP (sem MathType): {skip}")
    print(f"  FAIL:              {fail}")
    if mathtype_total:
        print(f"Taxa sobre MathType: {rate * 100:.1f}%")
    print(f"Cache hits/misses:   {conv.stats.cache_hits}/{conv.stats.cache_misses}")

    if failures:
        print()
        print("Falhas:")
        for name, msg in failures[:20]:
            print(f"  {name}: {msg[:120]}")

    if rate < args.threshold:
        print(f"\nFAIL: taxa {rate * 100:.1f}% < threshold {args.threshold * 100:.0f}%")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
