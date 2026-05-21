# API — TOC e renderização Markdown

Construção do Table of Contents e serialização final do `Document` em string Markdown.

---

## `idml_to_md.toc_builder`

```python
@dataclass(slots=True, frozen=True)
class TocEntry:
    level: int
    text: str
    slug: str


def build_toc(doc: Document, max_level: int = 2) -> list[TocEntry]: ...

def render_toc(entries: list[TocEntry]) -> str: ...
```

**`build_toc`** percorre `doc.blocks`, coleta `Heading` com `level <= max_level`, gera slug via `idml_to_md.utils.slugify.slugify(text)` e desambiguiza duplicatas com sufixo numérico (`-1`, `-2`, ...).

Default `max_level=2` inclui apenas H1 e H2 (capítulos e seções). Aumente para 3 ou 4 para TOC mais granular.

**`render_toc`** produz markdown:

```markdown
## Sumário

- [Capítulo 1](#capitulo-1)
  - [Seção 1.1](#secao-1-1)
- [Capítulo 2](#capitulo-2)
```

Indentação = `"  " * (level - 1)`. Retorna string vazia se `entries` for vazio (omite a seção inteira do MD).

## `idml_to_md.md_writer`

Renderer final.

```python
def render_document(doc: Document) -> str: ...
```

**Layout.**

```
# <doc.title>

<front matter (FrontMatterBlock como **title**, *authors/imprint*, etc.)>

## Sumário
<toc>

<body: cada Block renderizado em sequência separado por linha em branco>

## Referências
<reference entries>
```

`## Referências` é omitido se `doc.references` estiver vazio.

**Mapeamento Block → Markdown.**

| Block | Render |
|---|---|
| `Heading(level=N, inlines)` | `"#" * N + " " + inlines` |
| `Paragraph(inlines)` | linha com inlines + espaço, sem rstrip de quebra interna |
| `ListBlock(ordered, items, marker)` | `-` (não-ordenada), `1.` (decimal), `I.`/`II.` (upper-roman), `A.`/`B.` (upper-alpha); sublistas indentadas com 2 espaços por nível |
| `AdmonitionBlock(variant, title, children)` | `> [!NOTE]` + title em `**...**` + children prefixados com `> ` |
| `Blockquote(inlines)` | `> ` + inlines com substituição `\n` → `\n> ` |
| `CodeBlock(code, language)` | ` ```<language>\n<code>\n``` ` |
| `ImageBlock(src, alt, caption)` | `![alt](src)` + opcional `\n\n*caption*` |
| `EquationBlock(latex)` | `$$\n<latex>\n$$` (omitido se LaTeX vazio) |
| `TableBlock` | delegado a `idml_to_md.table_renderer.render_table` |
| `Caption(inlines)` | `*<inlines>*` |
| `FrontMatterBlock(role, inlines)` | tratado em `_render_front_matter` antes do body |
| `ReferenceEntry(inlines)` | linha de parágrafo (sob `## Referências`) |

**Inline.**

| `InlineKind` | Markdown |
|---|---|
| `TEXT` | texto com escape mínimo |
| `BOLD` | `**texto**` |
| `ITALIC` | `*texto*` |
| `BOLD_ITALIC` | `***texto***` |
| `SUPERSCRIPT` | `<sup>texto</sup>` |
| `SUBSCRIPT` | `<sub>texto</sub>` |
| `EQUATION_INLINE` | `$texto$` (espaço de separação adicionado automaticamente se vier colado a texto/equação anterior) |
| `LINE_BREAK` | `"  \n"` (2 espaços + newline = quebra dura em Markdown) |

**Escape.** `_escape_md` aplica apenas o mínimo necessário: `\` → `\\`, `<` → `&lt;`, `>` → `&gt;`. LaTeX inline **NÃO é escapado** — vai cru entre `$...$`.

**Marcadores de admonition (GH-style).** Constante `_GH_TAGS`:

```python
{
    "note": "NOTE",
    "tip": "TIP",
    "warning": "WARNING",
    "important": "IMPORTANT",
    "caution": "CAUTION",
}
```

Variant fora desta tabela cai em `"NOTE"`.

**Limpeza final.** `_join_clean(chunks)` junta os chunks com `\n` e colapsa runs de 3+ newlines em 2 para evitar lacunas excessivas no MD.

## Próximo

[utils.md](utils.md) — utilitários compartilhados.
