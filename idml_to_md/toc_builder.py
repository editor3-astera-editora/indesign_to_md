"""Constrói uma Table of Contents (TOC) com links âncora GFM.

Percorre ``Document.blocks`` coletando ``Heading`` de nível 1 e 2 e gera
uma lista markdown:

```
- [Capítulo 1](#capitulo-1)
  - [Seção 1.1](#secao-1-1)
- [Capítulo 2](#capitulo-2)
```

Os slugs seguem a convenção de âncora do GitHub: lowercase, espaços viram
hífens, acentos preservados (não normalizados) e duplicatas recebem
sufixo ``-1``, ``-2``. Para evitar dependências, geramos o slug com
``utils.slugify`` (que remove acentos) — slightly diferente do GitHub
mas garantido único e estável.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from idml_to_md.models import Document, Heading, Inline, LineBreak, TextRun
from idml_to_md.utils.slugify import slugify


@dataclass(slots=True, frozen=True)
class TocEntry:
    level: int
    text: str
    slug: str


def build_toc(doc: Document, max_level: int = 2) -> list[TocEntry]:
    """Coleta entries de TOC em ordem de aparição.

    ``max_level`` limita até qual nível incluir (default: H1 + H2).
    Slugs duplicados ganham sufixo numérico.
    """
    entries: list[TocEntry] = []
    used_slugs: dict[str, int] = {}

    for block in doc.blocks:
        if not isinstance(block, Heading):
            continue
        if block.level > max_level:
            continue
        text = _inline_to_plain(block.inlines).strip()
        if not text:
            continue
        base = slugify(text) or f"heading-{len(entries) + 1}"
        slug = _disambiguate(base, used_slugs)
        entries.append(TocEntry(level=block.level, text=text, slug=slug))
    return entries


def render_toc(entries: list[TocEntry]) -> str:
    """Renderiza a TOC como markdown. Vazio → string vazia (omite seção)."""
    if not entries:
        return ""
    lines: list[str] = ["## Sumário", ""]
    for entry in entries:
        indent = "  " * (entry.level - 1)
        lines.append(f"{indent}- [{entry.text}](#{entry.slug})")
    lines.append("")
    return "\n".join(lines)


def _inline_to_plain(inlines: Iterable[Inline]) -> str:
    parts: list[str] = []
    for inl in inlines:
        if isinstance(inl, TextRun):
            parts.append(inl.text)
        elif isinstance(inl, LineBreak):
            parts.append(" ")
    return "".join(parts)


def _disambiguate(base: str, used: dict[str, int]) -> str:
    n = used.get(base, 0)
    used[base] = n + 1
    return base if n == 0 else f"{base}-{n}"
