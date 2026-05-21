# API — Core

Módulos centrais do pipeline de conversão.

---

## `idml_to_md`

```python
__version__: str  # "0.1.0"
```

## `idml_to_md.cli`

Entrypoint Typer registrado como `idml2md` (em `pyproject.toml`).

```python
app: typer.Typer
```

Subcomandos:

```python
@app.command()
def version() -> None: ...

@app.command()
def convert(
    idml_path: Path,
    output_dir: Path = Path("out"),
    overlay: Path | None = None,
    title: str | None = None,
    links: Path | None = None,
    inkscape: Path | None = None,
    verbose: bool = False,
) -> None: ...

@app.command()
def inspect(
    idml_path: Path,
    top: int = 0,
) -> None: ...
```

Veja [cli.md](../cli.md) para descrição completa das flags. A função `_setup_logging(verbose)` (privada) configura `loguru` para stderr no nível `DEBUG` ou `INFO`.

## `idml_to_md.pipeline`

Orquestrador da conversão.

```python
@dataclass(slots=True)
class ConversionResult:
    markdown_path: Path
    report_path: Path
    report: ConversionReport
    output_dir: Path


def convert_idml(
    idml_path: Path,
    output_dir: Path,
    overlay_path: Path | None = None,
    book_title: str | None = None,
    links_dir: Path | None = None,
    inkscape_path: Path | None = None,
) -> ConversionResult: ...


def inspect_styles(idml_path: Path) -> Counter[str]: ...
```

**`convert_idml`** executa: abrir IDML → ordem de leitura → mapa de estilos → walker por Story → assets raster → assets vetoriais → reescrita de paths em `ImageBlock` → TOC + render → relatório. Grava `out/<slug>/<slug>.md` e `_report.json`. Cache de equações em `.cache/idml2md/equations/` (configurável via `equations.cache_dir` no YAML de estilos).

**`inspect_styles`** retorna um `Counter[nome_normalizado] → uso` percorrendo todas as Stories sem renderizar nada.

## `idml_to_md.config`

```python
DEFAULT_STYLES_PATH: Path  # <repo>/config/styles.default.yaml

def load_default_styles(path: Path | None = None) -> dict[str, Any]: ...
```

Loader simples (YAML → dict). Valida que o root é um mapping; lança `TypeError` caso contrário.

## `idml_to_md.models`

Modelos de dados (DocAST) compartilhados pelo pipeline.

### Enums

```python
class BlockKind(StrEnum):
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
    TEXT = "text"
    BOLD = "bold"
    ITALIC = "italic"
    BOLD_ITALIC = "bold_italic"
    SUPERSCRIPT = "superscript"
    SUBSCRIPT = "subscript"
    LINK = "link"
    EQUATION_INLINE = "equation_inline"
    LINE_BREAK = "line_break"
```

### Inline

```python
@dataclass(slots=True)
class TextRun:
    text: str
    kind: InlineKind = InlineKind.TEXT

@dataclass(slots=True)
class LineBreak:
    kind: InlineKind = InlineKind.LINE_BREAK

Inline = TextRun | LineBreak
```

### Blocks

```python
@dataclass(slots=True)
class Heading:
    level: int
    inlines: list[Inline] = []
    kind: BlockKind = BlockKind.HEADING

@dataclass(slots=True)
class Paragraph:
    inlines: list[Inline] = []
    kind: BlockKind = BlockKind.PARAGRAPH

@dataclass(slots=True)
class ListItem:
    inlines: list[Inline] = []
    level: int = 1
    sublist: ListBlock | None = None

@dataclass(slots=True)
class ListBlock:
    ordered: bool
    items: list[ListItem] = []
    marker: str = "decimal"  # decimal | upper-roman | upper-alpha | bullet
    kind: BlockKind = BlockKind.LIST

@dataclass(slots=True)
class AdmonitionBlock:
    variant: str   # note | tip | warning | important | caution
    title: str | None = None
    children: list[Block] = []
    kind: BlockKind = BlockKind.ADMONITION

@dataclass(slots=True)
class Blockquote:
    inlines: list[Inline] = []
    kind: BlockKind = BlockKind.BLOCKQUOTE

@dataclass(slots=True)
class CodeBlock:
    code: str
    language: str = ""
    kind: BlockKind = BlockKind.CODE_BLOCK

@dataclass(slots=True)
class ImageBlock:
    src: str
    alt: str = ""
    caption: str | None = None
    kind: BlockKind = BlockKind.IMAGE

@dataclass(slots=True)
class EquationBlock:
    latex: str
    source: str = ""           # basename do EPS original (auditoria)
    kind: BlockKind = BlockKind.EQUATION_DISPLAY

@dataclass(slots=True)
class TableCell:
    blocks: list[Block] = []
    column_span: int = 1
    row_span: int = 1
    is_header: bool = False

@dataclass(slots=True)
class TableBlock:
    rows: list[list[TableCell]] = []
    header_row_count: int = 0
    kind: BlockKind = BlockKind.TABLE

@dataclass(slots=True)
class Caption:
    inlines: list[Inline] = []
    role: str = "caption"     # caption | source_line | image_credit | infographic_label
    kind: BlockKind = BlockKind.CAPTION

@dataclass(slots=True)
class FrontMatterBlock:
    role: str                  # title | authors | imprint | cover_page | unit_title
    inlines: list[Inline] = []
    kind: BlockKind = BlockKind.FRONT_MATTER

@dataclass(slots=True)
class ReferenceEntry:
    inlines: list[Inline] = []
    kind: BlockKind = BlockKind.REFERENCE_ENTRY

Block = (
    Heading | Paragraph | ListBlock | AdmonitionBlock | Blockquote
    | CodeBlock | ImageBlock | EquationBlock | TableBlock
    | Caption | FrontMatterBlock | ReferenceEntry
)
```

### Document

```python
@dataclass(slots=True)
class Document:
    title: str
    slug: str
    front_matter: list[Block] = []
    blocks: list[Block] = []
    references: list[ReferenceEntry] = []
```

O `Document` é o resultado final do parsing antes da renderização. O writer ordena: `front_matter` → TOC → `blocks` → `references`.

## `idml_to_md.report`

```python
@dataclass(slots=True)
class ConversionReport:
    tool_version: str = __version__
    book_slug: str = ""
    book_title: str = ""
    seen_paragraph_styles: dict[str, int] = {}
    unmapped_paragraph_styles: dict[str, int] = {}
    seen_character_styles: dict[str, int] = {}
    unmapped_character_styles: dict[str, int] = {}
    block_counts: dict[str, int] = {}
    missing_assets: list[str] = []
    copied_assets: int = 0
    front_matter_blocks: int = 0
    body_blocks: int = 0
    reference_entries: int = 0
    equations_total: int = 0
    equations_failed: list[str] = []
    equation_cache_hits: int = 0
    equation_cache_misses: int = 0
    vector_converted: list[str] = []
    vector_failed: list[str] = []

    def to_dict(self) -> dict[str, Any]: ...
    def to_json(self, indent: int = 2) -> str: ...
    def write(self, path: Path) -> None: ...


def count_blocks(blocks: list[Block]) -> dict[str, int]: ...

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
) -> ConversionReport: ...
```

`count_blocks` agrupa por `block.kind` (chave do enum). `build_report` agrega todas as fontes em um `ConversionReport` pronto para `.write(path)`.

## Próximo

[idml-parsing.md](idml-parsing.md) — leitura e walking do XML IDML.
