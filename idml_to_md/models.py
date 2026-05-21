"""Modelos de dados (DocAST) compartilhados pelo pipeline.

O ``Document`` é o resultado final do parsing antes da renderização Markdown.
Cada Story do IDML produz uma sequência de ``Block``; cada bloco de texto
contém uma sequência de ``Inline`` (TextRun).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BlockKind(StrEnum):
    """Tipos semânticos de bloco que o ``story_walker`` produz."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    ADMONITION = "admonition"
    BLOCKQUOTE = "blockquote"
    CODE_BLOCK = "code_block"
    TABLE = "table"
    IMAGE = "image"
    EQUATION_DISPLAY = "equation_display"
    CAPTION = "caption"
    FRONT_MATTER = "front_matter"
    REFERENCE_ENTRY = "reference_entry"
    DROP = "drop"


class InlineKind(StrEnum):
    """Tipos semânticos de inline dentro de um bloco."""

    TEXT = "text"
    BOLD = "bold"
    ITALIC = "italic"
    BOLD_ITALIC = "bold_italic"
    SUPERSCRIPT = "superscript"
    SUBSCRIPT = "subscript"
    LINK = "link"
    EQUATION_INLINE = "equation_inline"
    LINE_BREAK = "line_break"


# ---------------------------------------------------------------------------
# Inline
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TextRun:
    """Trecho de texto com formatação inline.

    Apenas um ``kind`` por TextRun; combinações (negrito + itálico) viram
    ``BOLD_ITALIC``. Sobrescritos/subscritos viram ``<sup>``/``<sub>`` HTML
    no renderer.
    """

    text: str
    kind: InlineKind = InlineKind.TEXT


@dataclass(slots=True)
class LineBreak:
    """Quebra de linha dura (``<Br/>``) dentro de um parágrafo. Vira ``  \\n`` em Markdown."""

    kind: InlineKind = InlineKind.LINE_BREAK


Inline = TextRun | LineBreak


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Heading:
    """Heading 1..6. Em F1 produzimos no máximo nível 4."""

    level: int
    inlines: list[Inline] = field(default_factory=list)
    kind: BlockKind = BlockKind.HEADING


@dataclass(slots=True)
class Paragraph:
    """Parágrafo de texto corrente."""

    inlines: list[Inline] = field(default_factory=list)
    kind: BlockKind = BlockKind.PARAGRAPH


@dataclass(slots=True)
class ListItem:
    """Item de lista (parágrafo único + nível de aninhamento + sublist opcional).

    ``sublist`` permite expressar alternativas A/B/C/D aninhadas sob cada
    pergunta de um questionário (``Bullet ABC`` debaixo de ``Bullet Números``).
    """

    inlines: list[Inline] = field(default_factory=list)
    level: int = 1
    sublist: ListBlock | None = None


@dataclass(slots=True)
class ListBlock:
    """Bloco de lista ordenada/não-ordenada.

    Item adjacentes com o mesmo ``ordered``/``marker`` se agrupam neste
    mesmo bloco. Mudanças disparam um novo ``ListBlock``.
    """

    ordered: bool
    items: list[ListItem] = field(default_factory=list)
    marker: str = "decimal"  # decimal | upper-roman | upper-alpha
    kind: BlockKind = BlockKind.LIST


@dataclass(slots=True)
class AdmonitionBlock:
    """Caixa de destaque (``> [!NOTE]`` GFM por default)."""

    variant: str  # note | tip | warning | important | caution
    title: str | None = None
    children: list[Block] = field(default_factory=list)
    kind: BlockKind = BlockKind.ADMONITION


@dataclass(slots=True)
class Blockquote:
    """Citação."""

    inlines: list[Inline] = field(default_factory=list)
    kind: BlockKind = BlockKind.BLOCKQUOTE


@dataclass(slots=True)
class CodeBlock:
    """Fenced code block."""

    code: str
    language: str = ""
    kind: BlockKind = BlockKind.CODE_BLOCK


@dataclass(slots=True)
class ImageBlock:
    """Imagem raster (ou vetorial convertida) com path relativo no MD."""

    src: str
    alt: str = ""
    caption: str | None = None
    kind: BlockKind = BlockKind.IMAGE


@dataclass(slots=True)
class EquationBlock:
    """Equação em modo display (``$$...$$``).

    O campo ``source`` guarda o basename do EPS original para auditoria/fallback.
    """

    latex: str
    source: str = ""
    kind: BlockKind = BlockKind.EQUATION_DISPLAY


@dataclass(slots=True)
class TableCell:
    """Célula de tabela. Pode conter múltiplos blocos (parágrafos, imagens, eqs).

    ``column_span``/``row_span`` > 1 sinalizam células mescladas; o renderer
    pode então optar pelo fallback HTML.
    """

    blocks: list[Block] = field(default_factory=list)
    column_span: int = 1
    row_span: int = 1
    is_header: bool = False


@dataclass(slots=True)
class TableBlock:
    """Tabela com cabeçalho opcional. ``rows[0]`` pode ser linha de cabeçalho."""

    rows: list[list[TableCell]] = field(default_factory=list)
    header_row_count: int = 0
    kind: BlockKind = BlockKind.TABLE


@dataclass(slots=True)
class Caption:
    """Legenda/fonte abaixo de imagem ou tabela. Renderiza em itálico pequeno."""

    inlines: list[Inline] = field(default_factory=list)
    role: str = "caption"  # caption | source_line | image_credit | infographic_label
    kind: BlockKind = BlockKind.CAPTION


@dataclass(slots=True)
class FrontMatterBlock:
    """Conteúdo de front matter (capa, autoria, ficha técnica)."""

    role: str  # title | authors | imprint | unit_title | ...
    inlines: list[Inline] = field(default_factory=list)
    kind: BlockKind = BlockKind.FRONT_MATTER


@dataclass(slots=True)
class ReferenceEntry:
    """Item da seção de Referências (vai para o fim do livro)."""

    inlines: list[Inline] = field(default_factory=list)
    kind: BlockKind = BlockKind.REFERENCE_ENTRY


Block = (
    Heading
    | Paragraph
    | ListBlock
    | AdmonitionBlock
    | Blockquote
    | CodeBlock
    | ImageBlock
    | EquationBlock
    | TableBlock
    | Caption
    | FrontMatterBlock
    | ReferenceEntry
)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Document:
    """Livro completo, antes da serialização Markdown."""

    title: str
    slug: str
    front_matter: list[Block] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    references: list[ReferenceEntry] = field(default_factory=list)
