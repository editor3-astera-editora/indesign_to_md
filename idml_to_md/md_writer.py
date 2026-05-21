"""Renderiza um ``Document`` em Markdown único.

Layout do arquivo:

```
# <Título do livro>

<front matter — título capa, autores, ficha técnica>

## Sumário
<TOC com links âncora>

<corpo: headings, parágrafos, listas, imagens, admonitions, …>

## Referências
<reference entries>
```

Formatação:
- Headings: ``#``..``####``
- Inline: ``**``, ``*``, ``***``, ``<sup>``, ``<sub>``
- Listas: ``-`` (não-ordenada), ``1.`` (ordenada decimal), `I.`/`II.` (roman),
  ``A.``/``B.`` (alpha)
- Admonition: GFM ``> [!NOTE]``
- Code: fence ```` ``` ````
- Caption: ``*texto*`` em linha própria
- Imagens: ``![alt](path)``
"""

from __future__ import annotations

from collections.abc import Iterable

from idml_to_md.models import (
    AdmonitionBlock,
    Block,
    Blockquote,
    Caption,
    CodeBlock,
    Document,
    EquationBlock,
    FrontMatterBlock,
    Heading,
    ImageBlock,
    Inline,
    InlineKind,
    LineBreak,
    ListBlock,
    Paragraph,
    ReferenceEntry,
    TableBlock,
    TextRun,
)
from idml_to_md.table_renderer import render_table
from idml_to_md.toc_builder import build_toc, render_toc


def render_document(doc: Document) -> str:
    """Serializa o documento como string Markdown completa."""
    parts: list[str] = []

    parts.append(f"# {doc.title}")
    parts.append("")

    fm_md = _render_front_matter(doc.front_matter)
    if fm_md:
        parts.append(fm_md)
        parts.append("")

    toc_md = render_toc(build_toc(doc))
    if toc_md:
        parts.append(toc_md)

    body_md = _render_blocks(doc.blocks)
    if body_md:
        parts.append(body_md)

    if doc.references:
        parts.append("## Referências")
        parts.append("")
        for ref in doc.references:
            parts.append(_render_paragraph_line(ref.inlines))
            parts.append("")

    return _join_clean(parts)


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------


def _render_front_matter(blocks: list[Block]) -> str:
    if not blocks:
        return ""
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, FrontMatterBlock):
            continue
        text = _render_inlines(block.inlines)
        if not text.strip():
            continue
        if block.role == "title":
            # Já temos o título do livro; front_matter "title" vira subtítulo bold
            lines.append(f"**{text}**")
        elif block.role in ("authors", "imprint", "cover_page", "unit_title"):
            lines.append(f"*{text}*")
        else:
            lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------


def _render_blocks(blocks: list[Block]) -> str:
    chunks: list[str] = []
    for block in blocks:
        rendered = _render_block(block)
        if rendered:
            chunks.append(rendered)
    return "\n\n".join(chunks)


def _render_block(block: Block) -> str:  # noqa: PLR0911, PLR0912 — dispatcher por tipo

    if isinstance(block, Heading):
        hashes = "#" * max(1, min(block.level, 6))
        return f"{hashes} {_render_inlines(block.inlines)}".rstrip()
    if isinstance(block, Paragraph):
        return _render_paragraph_line(block.inlines)
    if isinstance(block, ListBlock):
        return _render_list(block)
    if isinstance(block, AdmonitionBlock):
        return _render_admonition(block)
    if isinstance(block, Blockquote):
        return "> " + _render_paragraph_line(block.inlines).replace("\n", "\n> ")
    if isinstance(block, CodeBlock):
        fence = "```"
        lang = block.language or ""
        return f"{fence}{lang}\n{block.code}\n{fence}"
    if isinstance(block, ImageBlock):
        line = f"![{block.alt}]({block.src})"
        if block.caption:
            line += f"\n\n*{block.caption}*"
        return line
    if isinstance(block, EquationBlock):
        if not block.latex.strip():
            return ""
        return f"$$\n{block.latex}\n$$"
    if isinstance(block, TableBlock):
        return render_table(block)
    if isinstance(block, Caption):
        return f"*{_render_inlines(block.inlines)}*"
    if isinstance(block, FrontMatterBlock):
        # Front matter no corpo (caso o walker não tenha redirecionado)
        return _render_paragraph_line(block.inlines)
    if isinstance(block, ReferenceEntry):
        return _render_paragraph_line(block.inlines)
    msg = f"bloco desconhecido: {type(block).__name__}"  # pragma: no cover
    raise TypeError(msg)


def _render_paragraph_line(inlines: list[Inline]) -> str:
    return _render_inlines(inlines).rstrip()


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
_ALPHA = tuple(chr(ord("A") + i) for i in range(26))


def _render_list(block: ListBlock, base_indent: int = 0) -> str:
    lines: list[str] = []
    for idx, item in enumerate(block.items, start=1):
        item_indent_level = base_indent + max(item.level, 1) - 1
        indent = "  " * item_indent_level
        marker = _list_marker(block, idx)
        line = f"{indent}{marker} {_render_inlines(item.inlines)}".rstrip()
        lines.append(line)
        if item.sublist is not None and item.sublist.items:
            sub = _render_list(item.sublist, base_indent=item_indent_level + 1)
            lines.append(sub)
    return "\n".join(lines)


def _list_marker(block: ListBlock, idx: int) -> str:
    if not block.ordered:
        return "-"
    if block.marker == "upper-roman":
        token = _ROMAN[idx - 1] if idx - 1 < len(_ROMAN) else str(idx)
        return f"{token}."
    if block.marker == "upper-alpha":
        token = _ALPHA[idx - 1] if idx - 1 < len(_ALPHA) else str(idx)
        return f"{token}."
    return f"{idx}."


# ---------------------------------------------------------------------------
# Admonition
# ---------------------------------------------------------------------------

_GH_TAGS = {
    "note": "NOTE",
    "tip": "TIP",
    "warning": "WARNING",
    "important": "IMPORTANT",
    "caution": "CAUTION",
}


def _render_admonition(block: AdmonitionBlock) -> str:
    tag = _GH_TAGS.get(block.variant, "NOTE")
    lines: list[str] = [f"> [!{tag}]"]
    if block.title:
        lines.append(f"> **{block.title}**")
    for child in block.children:
        rendered = _render_block(child)
        for ln in rendered.splitlines() or [""]:
            lines.append(f"> {ln}" if ln else ">")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------


def _render_inlines(inlines: Iterable[Inline]) -> str:
    out: list[str] = []
    for inl in inlines:
        if isinstance(inl, LineBreak):
            out.append("  \n")
            continue
        if not isinstance(inl, TextRun) or not inl.text:
            continue
        # LaTeX inline NÃO é escapado — é entregue cru entre $...$
        if inl.kind == InlineKind.EQUATION_INLINE:
            # Garante um espaço de separação antes da equação se vier colada
            # a texto ou a outra equação.
            if out and not out[-1].endswith((" ", "\n", "(", "[", "{")):
                out.append(" ")
            out.append(f"${inl.text}$")
            continue
        text = _escape_md(inl.text)
        out.append(_wrap_text_run(text, inl.kind))
    return "".join(out)


def _wrap_text_run(text: str, kind: InlineKind) -> str:
    if kind == InlineKind.BOLD:
        return f"**{text}**"
    if kind == InlineKind.ITALIC:
        return f"*{text}*"
    if kind == InlineKind.BOLD_ITALIC:
        return f"***{text}***"
    if kind == InlineKind.SUPERSCRIPT:
        return f"<sup>{text}</sup>"
    if kind == InlineKind.SUBSCRIPT:
        return f"<sub>{text}</sub>"
    return text


def _escape_md(text: str) -> str:
    """Escapa apenas o mínimo: ``*``/``_`` quando isolados, ``\\`` e ``<``/``>``."""
    return text.replace("\\", "\\\\").replace("<", "&lt;").replace(">", "&gt;")


def _join_clean(chunks: list[str]) -> str:
    """Junta chunks com newlines; colapsa runs de 3+ newlines em 2."""
    raw = "\n".join(c for c in chunks if c is not None) + "\n"
    while "\n\n\n" in raw:
        raw = raw.replace("\n\n\n", "\n\n")
    return raw
