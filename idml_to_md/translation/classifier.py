"""Classifica Segmentos que NÃO devem ser traduzidos.

Aplica heurísticas em cima do segmento já produzido pelo extractor:

- ``paragraph_kind == "code_block"`` → não traduzir (código).
- Plain text é puramente numérico/símbolos (``"3.14"``, ``"R$ 1.500,00"``,
  ``"x = y + z"`` sem palavras) → não traduzir.
- Variável matemática isolada (``"M"``, ``"V"``, ``"i"``) → não traduzir.
- Marca/nome próprio configurável (lista em ``config/translation.yaml``) → não traduzir.

Marcas e nomes próprios são identificados por correspondência simples
(case-sensitive) com a lista carregada. A v1 não usa NER.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from idml_to_md.translation.models import Segment, SkipReason

# Regex: tudo que é símbolo, número, pontuação, espaço — sem letras.
_NO_LETTERS_RE = re.compile(r"^[\s\W\d]+$", re.UNICODE)

# Regex: variável matemática isolada — 1 a 3 letras, possivelmente com índice
# (numérico, subscrito Unicode ou alfabético curto após "_"). Ex: "M", "VP", "i_n",
# "C0", "M_t", "V₁".
_VARIABLE_RE = re.compile(
    r"^[A-Za-z]{1,3}(?:[₀₁₂₃₄₅₆₇₈₉]{1,3}|\d{1,3}|_[A-Za-z\d]{1,3})?$"
)

# Regex: literal numérico isolado, possivelmente formatado.
# Ex: "1.234,56", "R$ 1.500,00", "3.14", "100%", "1/2".
_NUMERIC_LITERAL_RE = re.compile(
    r"^(?:R\$\s*)?[\d.,/%\s\-+×÷=]+$",
    re.UNICODE,
)

# Kinds cujo conteúdo é sempre código / símbolos / não-texto.
# Obs.: células de tabela são extraídas individualmente (cada parágrafo de célula
# vira um Segment com seu próprio kind — caption/paragraph), então NÃO há kind
# "table" aqui; números/variáveis dentro de células ainda caem nas regras abaixo.
NON_TRANSLATABLE_KINDS: frozenset[str] = frozenset(
    {
        "code_block",
        "drop",
        "equation_display",
        "image",
    }
)


def classify(
    segments: Iterable[Segment],
    *,
    brand_names: Iterable[str] = (),
    extra_non_translatable_styles: Iterable[str] = (),
) -> list[Segment]:
    """Marca cada Segment com ``skip=True`` quando aplicável.

    Segments já marcados com skip (por estar vazio ou em estilo drop) não
    são reclassificados. A função muta os Segments in-place e também
    retorna a lista para encadeamento fluente.
    """
    brand_set = {b.strip() for b in brand_names if b.strip()}
    skip_styles = {s.strip() for s in extra_non_translatable_styles if s.strip()}
    seg_list = list(segments)

    for seg in seg_list:
        if seg.skip:
            continue

        if seg.paragraph_kind in NON_TRANSLATABLE_KINDS:
            seg.skip = True
            seg.skip_reason = _reason_for_kind(seg.paragraph_kind)
            seg.notes.append(f"kind={seg.paragraph_kind}")
            continue

        if seg.paragraph_style in skip_styles:
            seg.skip = True
            seg.skip_reason = SkipReason.PARAGRAPH_STYLE
            seg.notes.append(f"style listada em translation.yaml: {seg.paragraph_style}")
            continue

        text = seg.plain_text.strip()
        if not text:
            seg.skip = True
            seg.skip_reason = SkipReason.EMPTY
            continue

        # Brand/nome próprio: o segment INTEIRO é uma marca → pular.
        if text in brand_set:
            seg.skip = True
            seg.skip_reason = SkipReason.BRAND_OR_PROPER_NAME
            continue

        # Ordem importa: numeric ANTES de pure_symbols (números entram em ambos
        # se aceitarmos vírgulas/pontos como "símbolos").
        if _is_numeric_literal(text):
            seg.skip = True
            seg.skip_reason = SkipReason.NUMERIC_LITERAL
            continue

        if _is_pure_symbols(text):
            seg.skip = True
            seg.skip_reason = SkipReason.PURE_SYMBOLS
            continue

        if _is_pure_variable(text):
            seg.skip = True
            seg.skip_reason = SkipReason.PURE_VARIABLE

    return seg_list


def _reason_for_kind(kind: str) -> SkipReason:
    """Mapeia paragraph_kind para o SkipReason mais apropriado."""
    if kind == "code_block":
        return SkipReason.CODE_BLOCK
    return SkipReason.PARAGRAPH_STYLE


def _is_pure_symbols(text: str) -> bool:
    """True se ``text`` não contém nenhuma letra (símbolos/números/pontuação)."""
    return bool(_NO_LETTERS_RE.match(text))


def _is_numeric_literal(text: str) -> bool:
    """True se ``text`` é apenas número formatado (com moeda, percent, etc.)."""
    return bool(_NUMERIC_LITERAL_RE.match(text))


def _is_pure_variable(text: str) -> bool:
    """True se ``text`` é uma variável matemática isolada (``M``, ``V0``, ``i_n``)."""
    return bool(_VARIABLE_RE.match(text))
