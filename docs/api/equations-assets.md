# API — Equações e assets

Extração e conversão de equações MathType, processamento de imagens, parse e render de tabelas.

---

## `idml_to_md.equation_extractor`

Extrai MathML embutido nos comentários PostScript dos EPS gerados pela MathType.

```python
@dataclass(slots=True, frozen=True)
class ExtractedMathML:
    mathml: str
    source_eps: Path
    has_mtef_only: bool = False     # True quando achamos MTEF mas não MathML


class EquationExtractionError(Exception):
    """EPS sem marcador MathType, MTEF sem MathML, ou bloco malformado."""


def extract_mathml(eps_path: Path) -> ExtractedMathML: ...
```

**Algoritmo.**

1. Lê o EPS em `latin-1` (PostScript é byte-safe; MathML é ASCII puro).
2. Localiza `%MathType!MathML![^\n]*\n` (regex).
3. Concatena linhas subsequentes começando com `%` (decapando o `%`).
4. Recorta de `<math` até `</math>` inclusivo.
5. Normaliza bugs conhecidos do MathType:
   - `<?xmlversion` → `<?xml version`
   - `<mathxmlns` → `<math xmlns`
   - `<mathdisplay` → `<math display`
   - `<mostretchy` → `<mo stretchy`
   - `<munderaccentunder` → `<munder accentunder`
   - `<moverlace`, `<mfencedclose`, `<mfencedopen`, `<mfencedseparators`
   - Atributos colados (`display='block'xmlns="..."`) recebem espaço via regex.
   - Aspas simples em `xmlns` viram aspas duplas.

Erros:
- Sem `MathType` no texto → `EquationExtractionError("... sem marcador MathType")`.
- Com `MathType!MTEF!` mas sem MathML → `"... contém MTEF mas não MathML embutido"`.
- `<math>...</math>` não localizado → `"... <math>...</math> não localizado"`.

A função `_extract_from_text(text, source)` (privada) é exposta para teste do conteúdo já lido — também usada em `audit_reporter` para evitar redundância de I/O.

## `idml_to_md.mathml_to_latex`

Converte MathML em LaTeX puro (sem `$`), em Python puro, com cache.

```python
class MathMLConversionError(Exception):
    """MathML não pôde ser convertido (XML inválido ou erro de render)."""


@dataclass(slots=True)
class _Stats:                           # privado, mas .stats é exposto
    cache_hits: int = 0
    cache_misses: int = 0
    failures: int = 0


@dataclass(slots=True)
class EquationConverter:
    cache_dir: Path | None = None
    _memory_cache: dict[str, str]
    stats: _Stats

    def convert(self, mathml: str) -> str: ...
```

**Uso.**

```python
converter = EquationConverter(cache_dir=Path(".cache/eqs"))
latex = converter.convert(mathml_str)
# 'V = C \\cdot (1+i)^{n}'
```

O retorno é **sem `$`** — quem chama decide inline (`$...$`) vs. display (`$$...$$`).

**Cache.**

- Chave = `hashlib.sha1(mathml.encode("utf-8")).hexdigest()`.
- Memória: dict `_memory_cache` (instância).
- Disco (opcional): se `cache_dir` for fornecido, grava `{cache_dir}/{sha1}.tex`.

**Elementos MathML suportados.**

| Elemento | Render |
|---|---|
| `mi` (1 letra latina) | variável (itálico padrão) |
| `mi` (multi-letra) | `\mathrm{...}` se não plausível palavra; `\text{...}` se palavra natural |
| `mn` | número literal |
| `mo` | operador (mapeado via `_OPERATOR_MAP`) |
| `mtext`, `ms` | `\text{...}` com escape LaTeX |
| `mspace` | `\,` |
| `mrow`, `mstyle`, `mphantom`, `merror` | conteúdo dos filhos |
| `mfrac` | `\frac{num}{den}` |
| `msqrt` | `\sqrt{...}` |
| `mroot` | `\sqrt[idx]{base}` |
| `msup`, `msub`, `msubsup` | `base^{sup}`, `base_{sub}`, `base_{sub}^{sup}` |
| `munder`, `mover`, `munderover` | `\underset{}{}`, `\overset{}{}` |
| `mfenced` | `\left<open>...\right<close>` com separadores |
| `mtable`/`mtr`/`mtd` | `\begin{matrix} ... \end{matrix}` |

**Mapas de tradução.**

- `_OPERATOR_MAP` — Unicode → macro LaTeX (`×` → `\times`, `≤` → `\leq`, `∑` → `\sum`, `∫` → `\int`, `√` → `\sqrt{}`, etc.). Inclui ` ` (NBSP) → `" "` e `​` (ZWSP) → `""`.
- `_GREEK_MAP` — letras gregas → macros (`α` → `\alpha`, `Γ` → `\Gamma`, etc.).

**Heurística de "palavra vs. variável"** (importante para textos como `M = C + J` vs. `ou seja`):

- Run de `<mi>` single-letter consecutivos vira um token.
- Token de 1 letra: variável em itálico padrão.
- Token de 2 letras: `\mathrm{...}` (variável composta tipo `VP`, `FV`) **a menos que** esteja em `_TWO_LETTER_WORDS` (`ou`, `de`, `da`, `no`, `na`, `em`, `se`, `ao`, `às`, `há`) — nesse caso, `\text{...}`.
- Token de 3+ letras: `\text{...}` se tem ≥1 vogal e não é tudo a mesma letra; `\mathrm{...}` caso contrário.

**Pós-processamento.** `_post_process` insere espaço entre macros conhecidas e letras subsequentes para evitar `\cdota` → mantém `\cdot a`.

## `idml_to_md.asset_processor`

Copia raster e converte vetorial.

```python
RASTER_EXTENSIONS: frozenset[str]   # {.jpg, .jpeg, .png, .gif, .tif, .tiff, .webp}
VECTOR_EXTENSIONS: frozenset[str]   # {.ai, .eps}


def resolve_inkscape_path(explicit: Path | None = None) -> Path | None: ...


@dataclass(slots=True)
class AssetMap:
    output_relative: dict[str, str]   # basename → caminho relativo no MD
    missing: list[str]
    skipped_non_raster: list[str]
    vector_converted: list[str]
    vector_failed: list[str]


def process_raster_assets(
    requested_basenames: list[str],
    links_dir: Path,
    output_assets_dir: Path,
) -> AssetMap: ...


def process_vector_assets(
    requested_basenames: list[str],
    links_dir: Path,
    output_vector_dir: Path,
    *,
    inkscape_path: Path | None = None,
) -> AssetMap: ...
```

**`resolve_inkscape_path`.** Ordem de prioridade:

1. `explicit` (argumento), se existir.
2. `os.environ["IDML2MD_INKSCAPE_PATH"]`, se existir.
3. `shutil.which("inkscape")`.
4. Caminhos típicos no Windows: `~/Inkscape/bin/inkscape.exe`, `~/Inkscape/PFiles64/Inkscape/bin/inkscape.exe`, `C:\Program Files\Inkscape\bin\inkscape.exe`, `C:\Program Files (x86)\Inkscape\bin\inkscape.exe`.

Retorna `None` se nada for encontrado.

**`process_raster_assets`.**

- Dedup por SHA-1 do conteúdo do arquivo (chunked, 64 KB).
- Conflito de nome com hash diferente → sufixo `_1`, `_2`, etc. (`_disambiguate`).
- Em `output_relative`, todos os basenames apontam para `assets/img/<final>.ext`.
- Extensões fora de `RASTER_EXTENSIONS` vão para `skipped_non_raster`.
- Ausentes em `links_dir` vão para `missing`.

**`process_vector_assets`.**

- Tenta primeiro Inkscape headless: `inkscape <src> --export-type=svg --export-filename=<dest.svg>`, timeout 60s.
- Se Inkscape falhar (binário ausente, retorno != 0, ou destino não criado), fallback para Ghostscript: `gs -sDEVICE=png16m -r300 -dEPSCrop -dNOPAUSE -dBATCH -dQUIET -sOutputFile=<dest.png> <src>`, timeout 30s.
- Sucesso (SVG ou PNG) → `output_relative[basename] = "assets/vector/<final>"` e `vector_converted.append(basename)`.
- Ambos falham → `vector_failed.append(basename)`.

Exceções `BinaryNotFoundError`, `FileNotFoundError`, `OSError` e exceções genéricas são todas tratadas como falha (não propagadas), com log DEBUG.

## `idml_to_md.table_renderer`

Parse e render de tabelas IDML.

```python
def parse_table(
    table_el: etree._Element,
    walk_paragraph: Callable[[etree._Element], tuple[list[Inline], list[Block]]],
) -> TableBlock: ...


def render_table(block: TableBlock) -> str: ...
```

**`parse_table`.**

1. Lê atributos `HeaderRowCount`, `BodyRowCount`, `ColumnCount` do `<Table>`.
2. Cria grade `total_rows × column_count`.
3. Para cada `<Cell Name="row:col" RowSpan="N" ColumnSpan="M">`:
   - Chama `walk_paragraph(psr)` para cada `<ParagraphStyleRange>` filho.
   - Combina inlines em `Paragraph` + extras (imagens, equações, sub-tabelas).
4. Retorna `TableBlock(rows, header_row_count)`.

`walk_paragraph` é injetado para evitar import circular com `story_walker`.

**`render_table`.**

- Decide HTML fallback se: alguma célula tem `column_span > 1` ou `row_span > 1`, ou conteúdo "complexo" (mais de 1 bloco, ou bloco é `ImageBlock`/`EquationBlock`/`TableBlock`).
- Caso contrário, GFM:
  - Linha vazia de header sintetizada se `header_row_count == 0` (GFM exige header).
  - Pipes (`|`) literais no texto são escapados (`\|`).
  - Quebras de linha dentro da célula viram espaço.
  - Inlines formatados são preservados (`**bold**`, `*italic*`, `<sup>`, etc.).

HTML usa `<table>` / `<tr>` / `<th>` / `<td>` com `rowspan` / `colspan`. Conteúdo de célula com múltiplos blocos é unido por `<br />`.

## Próximo

[output.md](output.md) — geração do TOC e renderização Markdown.
