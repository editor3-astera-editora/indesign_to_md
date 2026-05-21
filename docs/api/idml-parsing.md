# API — Parsing IDML

Módulos que abrem o IDML, decidem a ordem de leitura e percorrem as Stories.

---

## `idml_to_md.idml_reader`

Wrapper de baixo nível sobre o ZIP IDML. Opera diretamente com `zipfile` + `lxml`.

```python
@dataclass(slots=True)
class TextFrameInfo:
    self_id: str
    parent_story: str
    previous_text_frame: str   # "n" se raiz, "" se ausente
    next_text_frame: str
    spread_index: int
    order_in_spread: int


class IDMLDocument:
    path: Path

    def __init__(self, path: Path) -> None: ...
    def __enter__(self) -> IDMLDocument: ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def close(self) -> None: ...

    def designmap(self) -> etree._Element: ...
    def styles_root(self) -> etree._Element: ...

    def spread_paths(self) -> list[str]: ...
    def story_paths(self) -> list[str]: ...

    def iter_spreads(self) -> Iterator[tuple[int, str, etree._Element]]: ...
    def get_story_root(self, story_id: str) -> etree._Element | None: ...

    def paragraph_style_names(self) -> list[str]: ...
    def character_style_names(self) -> list[str]: ...

    def iter_text_frames(self) -> Iterator[TextFrameInfo]: ...
```

**Uso típico**

```python
with IDMLDocument(Path("livro.idml")) as doc:
    for idx, path, root in doc.iter_spreads():
        ...
    story = doc.get_story_root("u1f81d")
```

- `spread_paths()` usa regex sobre o `designmap.xml` para preservar a ordem exata.
- `iter_spreads()` retorna `(index, path, root)` na ordem do designmap = ordem de página.
- `story_paths()` retorna **todos** os Stories no ZIP — não é ordem de leitura. Use o `thread_resolver` para isso.
- `get_story_root("u1f81d")` retorna `None` se a Story foi referenciada mas removida.
- Os helpers `paragraph_style_names()` / `character_style_names()` extraem nomes de `Resources/Styles.xml` decodificados (URL-decode aplicado).

## `idml_to_md.thread_resolver`

Determina a ordem global de leitura das Stories.

```python
@dataclass(slots=True, frozen=True)
class StoryOrderEntry:
    story_id: str
    first_frame_id: str
    spread_index: int
    order_in_spread: int


def resolve_reading_order(doc: IDMLDocument) -> list[StoryOrderEntry]: ...
```

Algoritmo:

1. Itera todos os `TextFrame` (`doc.iter_text_frames()`) já em ordem de página.
2. Para cada Story, identifica o **primeiro** frame que a referencia.
3. Sobe pela cadeia `PreviousTextFrame` até a raiz da thread (safety break em 10.000 iterações).
4. Ordena Stories por `(spread_index, order_in_spread)` da raiz.

Stories já vistas em raízes anteriores não voltam; uma Story que aparece em N frames conta uma única vez.

## `idml_to_md.anchored_resolver`

Classifica `Group`/`Rectangle` ancorados dentro de uma CharacterStyleRange.

```python
class AnchoredKind(StrEnum):
    IMAGE_RASTER = "image_raster"
    IMAGE_VECTOR = "image_vector"   # .ai e .eps NÃO-MathType
    EQUATION_EPS = "equation_eps"
    OTHER = "other"


@dataclass(slots=True, frozen=True)
class AnchoredInfo:
    kind: AnchoredKind
    basename: str = ""              # só para image_raster e equation_eps


def classify_anchored(el: etree._Element) -> AnchoredInfo: ...
```

**Heurística.** Procura o primeiro `<Link LinkResourceURI=...>` descendente e decide pela extensão:

| Extensão | Kind |
|---|---|
| `.jpg`, `.jpeg`, `.png`, `.gif`, `.tif`, `.tiff`, `.webp` | `IMAGE_RASTER` |
| `.ai` | `IMAGE_VECTOR` |
| `.eps` | `EQUATION_EPS` (mais tarde, se `extract_mathml` falhar, é tratado como `IMAGE_VECTOR`) |
| outras | `OTHER` (silenciado) |

URIs sem `Links/` ou começando com `file:` são descartadas (assets embutidos).

## `idml_to_md.story_walker`

Coração do parser: percorre o XML de uma Story e produz blocos DocAST.

```python
@dataclass(slots=True)
class WalkResult:
    body: list[Block] = []
    front_matter: list[Block] = []
    references: list[ReferenceEntry] = []
    image_basenames: list[str] = []
    vector_basenames: list[str] = []
    equation_basenames: list[str] = []
    failed_equations: list[str] = []


def walk_story(
    root: etree._Element,
    style_map: StyleMap,
    *,
    converter: EquationConverter | None = None,
    links_dir: Path | None = None,
) -> WalkResult: ...
```

**O que ele faz.**

Para cada `<ParagraphStyleRange>` da Story:
1. Resolve a rule via `style_map.lookup_paragraph()`.
2. Coleta inlines + anchored + tabelas via `_walk_paragraph` (privado).
3. Decide inline-vs-display para equações via `_resolve_equations_inline_or_display` (privado).
4. Despacha para o tipo correto (heading/paragraph/list/admonition/...) via `_BlockStream` (privado, agrupa lista/admonitions adjacentes).

**Caracteres especiais tratados** (constante `_SPECIAL_CHARS`):

| Codepoint | Substituição |
|---|---|
| `U+2028` LINE SEPARATOR | `\n` |
| `U+2029` PARAGRAPH SEPARATOR | `\n\n` |
| `U+00AD` SOFT HYPHEN | (removido) |
| `U+FEFF` BOM | (removido) |

**Detecção de formatação inline** (`_detect_inline_kind`):

Lê `FontStyle` e `Position` do `<CharacterStyleRange>`:
- `Position` contém `superscript` → `SUPERSCRIPT`.
- `Position` contém `subscript` → `SUBSCRIPT`.
- `FontStyle` contém `bold`/`black`/`heavy` → `BOLD`.
- `FontStyle` contém `italic`/`oblique` → `ITALIC`.
- Bold + Italic combinam para `BOLD_ITALIC`.

**Inline vs. display de equações.**

- Parágrafo tem TextRun com texto não-vazio **além** das equações → todas as equações viram **inline** (`TextRun(latex, EQUATION_INLINE)` no fim do parágrafo).
- Parágrafo só tem equação → vira `EquationBlock` **block-level** logo após o parágrafo.

## `idml_to_md.style_mapper`

Mapeia nomes de ParagraphStyle/CharacterStyle do IDML para kinds semânticos Markdown.

```python
def normalize_style_name(raw: str) -> str: ...


@dataclass(slots=True, frozen=True)
class ParagraphRule:
    kind: str
    raw: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any: ...


@dataclass(slots=True, frozen=True)
class CharacterRule:
    wrap: str | None = None
    html: str | None = None


UnknownPolicy = Literal["passthrough", "warn", "drop"]


@dataclass(slots=True)
class StyleMap:
    paragraph_rules: dict[str, ParagraphRule]
    character_rules: dict[str, CharacterRule]
    unknown_paragraph_policy: UnknownPolicy
    unknown_character_policy: UnknownPolicy
    admonitions_config: dict[str, Any]
    tables_config: dict[str, Any]
    equations_config: dict[str, Any]
    images_config: dict[str, Any]
    seen_paragraph_styles: Counter[str]
    seen_character_styles: Counter[str]
    unmapped_paragraph_styles: Counter[str]
    unmapped_character_styles: Counter[str]

    def lookup_paragraph(self, raw_name: str) -> ParagraphRule | None: ...
    def lookup_character(self, raw_name: str) -> CharacterRule | None: ...


def build_style_map(
    overlay_path: Path | None = None,
    overlay_data: dict[str, Any] | None = None,
) -> StyleMap: ...
```

**`normalize_style_name`** remove prefixo (`ParagraphStyle/`, `CharacterStyle/`) e aplica URL-decode:

```python
normalize_style_name("ParagraphStyle/Títulos%3aT1")  # → "Títulos:T1"
```

**`build_style_map`** carrega `config/styles.default.yaml` e aplica overlay (parâmetro `overlay_data` tem precedência sobre `overlay_path` — usado em testes). Deep-merge não-destrutivo.

**`lookup_paragraph`** sempre conta em `seen_paragraph_styles`; quando não há rule, conta em `unmapped_paragraph_styles` e retorna:
- `None` se a política for `drop`.
- `ParagraphRule(kind="paragraph", raw={"kind": "paragraph"})` em `passthrough`/`warn`.

**`lookup_character`** conta vistos, mas silencia nomes começando com `$ID/` (não aparecem em `unmapped_character_styles`).

## Próximo

[equations-assets.md](equations-assets.md) — equações MathType e processamento de assets.
