"""Slugify para nomes de pastas e âncoras Markdown.

Mantém apenas ASCII alfanumérico + ``-``. Acentos são removidos por
NFKD-decompose; pontuação vira hífen; hífens consecutivos colapsam.
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_COLLAPSE_HYPHEN = re.compile(r"-{2,}")


def slugify(value: str) -> str:
    """Converte texto livre em slug seguro para path ou âncora.

    Exemplo: ``"81_Matemática Financeira"`` → ``"81-matematica-financeira"``.
    """
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower()
    hyphenated = _NON_ALNUM.sub("-", lower)
    collapsed = _COLLAPSE_HYPHEN.sub("-", hyphenated)
    return collapsed.strip("-")
