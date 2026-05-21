# API — Subpacote `idml_to_md.translation`

Pipeline paralelo de tradução IDML → IDML traduzido via OpenAI. Visão alto-nível em [pipeline-translation.md](../pipeline-translation.md).

---

## `idml_to_md.translation`

`__init__.py` re-exporta os modelos públicos:

```python
from idml_to_md.translation import (
    AuditReport,
    Segment,
    SegmentRun,
    SkipReason,
    Translation,
    TranslationBatch,
)
```

## `idml_to_md.translation.models`

Schemas Pydantic serializáveis. Cada fase grava JSON inspecionável.

```python
class SkipReason(StrEnum):
    NONE = "none"
    EMPTY = "empty"
    PARAGRAPH_STYLE = "paragraph_style"
    CODE_BLOCK = "code_block"
    PURE_SYMBOLS = "pure_symbols"
    PURE_VARIABLE = "pure_variable"
    BRAND_OR_PROPER_NAME = "brand_or_proper_name"
    NUMERIC_LITERAL = "numeric_literal"
    ALREADY_TRANSLATED = "already_translated"


class SegmentRun(BaseModel):
    run_idx: int
    content_idx: int
    text: str
    bold: bool = False
    italic: bool = False
    superscript: bool = False
    subscript: bool = False
    character_style: str = ""


class Segment(BaseModel):
    segment_id: str            # "<story_id>:<paragraph_idx>"
    story_id: str
    paragraph_idx: int
    paragraph_style: str = ""
    paragraph_kind: str = "paragraph"
    runs: list[SegmentRun] = []
    plain_text: str = ""
    skip: bool = False
    skip_reason: SkipReason = SkipReason.NONE
    notes: list[str] = []


class Translation(BaseModel):
    segment_id: str
    source_text: str
    target_text: str = ""
    target_runs: list[SegmentRun] = []
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    warnings: list[str] = []


class TranslationBatch(BaseModel):
    batch_id: str
    story_id: str
    segments: list[Segment] = []
    translations: list[Translation] = []


class EquationAlert(BaseModel):
    eps_basename: str
    terms_found: list[str]
    story_id: str = ""


class AuditReport(BaseModel):
    source_idml: str
    target_lang: str
    target_idml: str
    total_segments: int = 0
    translated_segments: int = 0
    skipped_segments: int = 0
    skip_breakdown: dict[str, int] = {}
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model: str = ""
    equation_alerts: list[EquationAlert] = []
    warnings: list[str] = []
    duration_seconds: float = 0.0
```

Serialize com `model.model_dump_json(indent=2)`.

## `idml_to_md.translation.segment_extractor`

```python
def extract_segments(
    idml_path: Path,
    style_map: StyleMap,
    *,
    xml_dump_dir: Path | None = None,
) -> list[Segment]: ...
```

Percorre as Stories em ordem de leitura (`thread_resolver.resolve_reading_order`) e emite um `Segment` por `ParagraphStyleRange`. Para cada PSR:

- `segment_id = f"{story_id}:{paragraph_idx}"`.
- `paragraph_kind` resolvido via `style_map.lookup_paragraph()`.
- Runs extraídos por `<CharacterStyleRange>/<Content>`:
  - Atributos `bold`/`italic` deduzidos de `FontStyle` + `AppliedCharacterStyle` (lower-case match para `bold`/`black`/`heavy`, `italic`/`oblique`, e por nome de CharacterStyle se contém `bold`/`italic`/`sobrescrito`/`subscrito`/`superscript`/`subscript`).
  - `superscript`/`subscript` deduzidos de `Position`.
- `plain_text` = concatenação dos textos, com `U+00AD` e `U+FEFF` removidos.
- Skip preliminar:
  - `plain_text` vazio → `SkipReason.EMPTY`.
  - `paragraph_kind == "drop"` → `SkipReason.PARAGRAPH_STYLE` + nota.

Se `xml_dump_dir` for fornecido, copia `Stories/Story_<id>.xml` byte-a-byte para `xml_dump_dir/Story_<id>.xml`.

## `idml_to_md.translation.classifier`

```python
NON_TRANSLATABLE_KINDS: frozenset[str] = {
    "code_block", "drop", "equation_display", "image", "table"
}


def classify(
    segments: Iterable[Segment],
    *,
    brand_names: Iterable[str] = (),
    extra_non_translatable_styles: Iterable[str] = (),
) -> list[Segment]: ...
```

Muta os Segments in-place e retorna a lista para encadeamento. Não toca em segmentos já marcados `skip=True`.

**Ordem das heurísticas** (parar no primeiro match):

1. `paragraph_kind in NON_TRANSLATABLE_KINDS` → `CODE_BLOCK` (se `code_block`) ou `PARAGRAPH_STYLE`.
2. `paragraph_style ∈ extra_non_translatable_styles` → `PARAGRAPH_STYLE`.
3. `plain_text` vazio (após strip) → `EMPTY`.
4. `plain_text ∈ brand_names` (match exato) → `BRAND_OR_PROPER_NAME`.
5. Numérico (regex `^(?:R\$\s*)?[\d.,/%\s\-+×÷=]+$`) → `NUMERIC_LITERAL`.
6. Pure symbols (regex `^[\s\W\d]+$`) → `PURE_SYMBOLS`.
7. Variável matemática (regex `^[A-Za-z]{1,3}(?:[₀-₉]{1,3}|\d{1,3}|_[A-Za-z\d]{1,3})?$`) → `PURE_VARIABLE`.

## `idml_to_md.translation.prompt_builder`

```python
PH_OPEN: str = "§"
PH_CLOSE: str = "§"


@dataclass(slots=True)
class PromptPair:
    system: str
    user: str
    segment_order: list[str]    # IDs na ordem em que aparecem no user


def build_segment_text_with_placeholders(seg: Segment) -> str: ...

def build_batch_prompt(
    segments: list[Segment],
    *,
    target_lang: str = "es",
) -> PromptPair: ...

def parse_batch_response(
    response_text: str,
    order: list[str],
) -> dict[str, str]: ...
```

**`build_segment_text_with_placeholders`.** Para cada run:
- Sem formatação → texto direto.
- Com `bold`/`italic`/`superscript`/`subscript` → `§<run_idx>§<texto>§/<run_idx>§`.

**`build_batch_prompt`.** Constrói:

- **System** (template em PT-BR) instruindo: domínio editorial, registro acadêmico formal (`usted` em espanhol), não traduzir variáveis matemáticas / fórmulas / nomes próprios / código, preservar `§N§...§/N§` exatos, manter pontuação inicial em espanhol (¿, ¡) quando aplicável, preservar `\n` interno. Inclui exemplos de entrada e resposta esperada.
- **User** — `[[1]] <seg1>\n\n[[2]] <seg2>\n\n...`.

Idiomas suportados pelo template (`_target_lang_pretty`): `es`, `en`, `fr`, `it`, `de`. Códigos fora dessa lista vão para o template direto.

**`parse_batch_response`.** Regex `r"\[\[(\d+)\]\]\s*(.*?)(?=\n\[\[\d+\]\]|\Z)"` (DOTALL). Retorna `{segment_id: target_text}`. Segmentos ausentes na resposta simplesmente não aparecem no dict.

## `idml_to_md.translation.openai_client`

```python
@dataclass(slots=True)
class TranslatorConfig:
    model: str = "gpt-4o-mini"
    target_lang: str = "es"
    batch_max_segments: int = 30
    batch_max_input_tokens: int = 3000
    temperature: float = 0.2
    max_completion_tokens: int = 4000


@dataclass(slots=True)
class TranslatorStats:
    total_segments: int = 0
    translated: int = 0
    failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    batches_sent: int = 0
    warnings: list[str] = []


class TranslatorClient:
    def __init__(
        self,
        config: TranslatorConfig | None = None,
        api_key: str | None = None,
        client: object | None = None,        # injeção para teste
    ) -> None: ...

    def translate_segments(self, segments: list[Segment]) -> list[Translation]: ...
```

**Inicialização.**

- Se `client` for passado, usa-o (testes mock).
- Caso contrário: `OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))`. Levanta `RuntimeError` se `OPENAI_API_KEY` não estiver disponível.
- Carrega `tiktoken.encoding_for_model(model)` com fallback `cl100k_base`. Se `tiktoken` não estiver instalado, usa estimativa heurística `len(text) // 4`.

**`translate_segments`.**

1. Filtra `[s for s in segments if not s.skip]`.
2. `_chunk_batches` agrupa respeitando `batch_max_segments`, `batch_max_input_tokens`, e preferindo manter mesma Story junta.
3. Para cada lote: `_translate_batch`.

**`_translate_batch`.**

1. Chama `build_batch_prompt`.
2. `_call_api(system, user)` com retry exponencial via `tenacity` (3 tentativas, backoff 2–10s, log antes de cada retry).
3. Em falha após retries: marca **todo o lote** como `failed`, retorna Translations com `target_text=""` e `target_runs=runs originais`, e warning `batch_failed: <exc>`.
4. Em sucesso: `parse_batch_response` + `_distribute_runs` por segmento.
5. Atualiza `stats` (`prompt_tokens`, `completion_tokens`, `estimated_cost_usd`, `translated`/`failed`).

**`_distribute_runs(seg, target_text) → (target_runs, warnings)`.**

- Captura placeholders `§N§...§/N§` na tradução; cada N vira o conteúdo do run formatado.
- Texto residual (após remover placeholders) vai no **primeiro** run de texto puro; demais ficam vazios.
- Placeholders ausentes: warning + fallback (texto inteiro no primeiro run, demais zerados).

**Tabela de preços** (constante `_MODEL_PRICING`, USD por 1M tokens):

| Modelo | Input | Output |
|---|---|---|
| `gpt-4o` | 2.50 | 10.00 |
| `gpt-4o-mini` | 0.150 | 0.600 |
| `gpt-4-turbo` | 10.00 | 30.00 |
| `gpt-3.5-turbo` | 0.50 | 1.50 |

Modelos fora desta tabela contam tokens normalmente mas `estimated_cost_usd` permanece `0.0`.

## `idml_to_md.translation.idml_writer`

```python
def write_translated_idml(
    source_idml: Path,
    target_idml: Path,
    segments: list[Segment],
    translations: list[Translation],
    *,
    xml_dump_dir: Path | None = None,
) -> dict[str, int]: ...


def copy_xml_original(source_idml: Path, dump_dir: Path) -> int: ...
```

**`write_translated_idml`.** Retorna `{"stories_modified": N, "contents_replaced": M}`.

Fluxo:
1. Indexa `translations` por `segment_id`. Agrupa `segments` por `story_id`.
2. Para cada Story com Segments:
   - Lê `Stories/Story_<id>.xml` do ZIP original.
   - Parse com `lxml` (`remove_blank_text=False, recover=False`).
   - Para cada Segment com `skip=False` e Translation correspondente:
     - Localiza o `<ParagraphStyleRange>` pelo `paragraph_idx`.
     - Para cada `<CharacterStyleRange>` no PSR: consolida o texto traduzido dos `target_runs` com mesmo `run_idx` e coloca tudo no **primeiro** `<Content>`; demais Contents são zerados.
   - Serializa com `etree.tostring(xml_declaration=True, encoding="UTF-8", standalone=True)`.
   - Normaliza para o estilo InDesign:
     - Header com aspas duplas: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`.
     - Tags vazias com espaço antes do `/>`: `<Tag attr=".." />`.
3. Recria o ZIP IDML via `_write_idml_zip`:
   - `mimetype` como **primeiro** membro, compressão `STORED`.
   - Demais membros com `DEFLATE`, preservando ordem original.
4. Se `xml_dump_dir` for fornecido, salva uma cópia byte-a-byte de cada Story XML modificado.

**Garantias.**

- IDs `Self` não são alterados.
- Atributos de PSR/CSR não são alterados.
- Estrutura do ZIP (ordem de membros + mimetype STORED) preservada — passa o validador OCF do InDesign.

**`copy_xml_original`.** Helper: copia **todos** os Stories XML do IDML para `dump_dir` (não é usado no fluxo principal porque `segment_extractor` já dump enquanto extrai).

## `idml_to_md.translation.audit_reporter`

```python
DEFAULT_PT_TERMS: tuple[str, ...] = (
    "Juros", "Montante", "Capital", "Taxa", "Tempo", "Saldo",
    "Período", "Periodo", "Valor", "Total", "Médio", "Médios",
    "Inicial", "Final",
)


def build_audit_report(
    *,
    source_idml: Path,
    target_idml: Path,
    target_lang: str,
    segments: list[Segment],
    translations: list[Translation],
    stats: TranslatorStats,
    duration_seconds: float = 0.0,
    pt_terms: tuple[str, ...] = DEFAULT_PT_TERMS,
) -> AuditReport: ...


def save_report(report: AuditReport, path: Path) -> None: ...
```

**`build_audit_report`.**

- Conta `skipped_segments` e `skip_breakdown` (counter de `skip_reason.value`).
- Junta warnings de `stats` + warnings de cada `Translation` (com prefixo `<segment_id>:`).
- Chama `_scan_equations_for_pt_terms`:
  - Varre `.eps` dentro do ZIP IDML e em `idml_path.parent / "Links/"`.
  - Para cada EPS, tenta `_extract_from_text` (reusa o extrator MathML).
  - Se MathML contém qualquer termo de `pt_terms` (match com `\b<termo>\b`), gera `EquationAlert(eps_basename, terms_found)`.
- Retorna `AuditReport` com `model=""` (preenchido pelo CLI antes de salvar).

**`save_report`.** Cria diretório pai e escreve `report.model_dump_json(indent=2)`.

## `idml_to_md.translation.pipeline`

```python
@dataclass(slots=True)
class TranslationConfig:
    target_lang: str = "es"
    model: str = "gpt-4o-mini"
    batch_max_segments: int = 30
    batch_max_input_tokens: int = 3000
    temperature: float = 0.2
    max_completion_tokens: int = 4000
    brand_names: tuple[str, ...] = ()
    non_translatable_styles: tuple[str, ...] = ()

    @classmethod
    def from_yaml(cls, path: Path) -> TranslationConfig: ...


@dataclass(slots=True)
class TranslationResult:
    target_idml: Path
    segments_path: Path
    translations_path: Path
    report_path: Path
    report: AuditReport
    output_dir: Path


def translate_idml(
    idml_path: Path,
    output_dir: Path,
    *,
    config: TranslationConfig | None = None,
    styles_overlay: Path | None = None,
    dry_run: bool = False,
    api_key: str | None = None,
    translator_client: TranslatorClient | None = None,
) -> TranslationResult: ...
```

**`from_yaml`** carrega o YAML; campos ausentes recebem o default da dataclass.

**`translate_idml`** executa o pipeline completo:

1. Cria `output_dir/<slug>/`, com `xml_original/` e `xml_traduzido/`.
2. `build_style_map(overlay_path=styles_overlay)` (do pacote principal).
3. `extract_segments(idml_path, style_map, xml_dump_dir=xml_original_dir)`.
4. `classify(segments, brand_names=cfg.brand_names, extra_non_translatable_styles=cfg.non_translatable_styles)`.
5. Salva `segments.json`.
6. Log do skip breakdown.
7. Se `dry_run`: gera report vazio (model = `"<model> (dry-run)"`) e retorna.
8. Senão: instancia `TranslatorClient` (ou usa o injetado), chama `translate_segments`.
9. Salva `translations.json`.
10. `write_translated_idml(source, target, segments, translations, xml_dump_dir=xml_traduzido_dir)`.
11. `build_audit_report(...)`, atribui `report.model = cfg.model`, `save_report(report, report_path)`.
12. Retorna `TranslationResult`.

`api_key` e `translator_client` permitem injeção (testes e uso programático).

## `idml_to_md.translation.cli`

Entrypoint Typer registrado como `idml-translate` (em `pyproject.toml`).

```python
app: typer.Typer

@app.command()
def translate(
    idml_path: Path,
    output_dir: Path = Path("out"),
    target_lang: str = "es",
    config: Path | None = None,
    styles_overlay: Path | None = None,
    model: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> None: ...
```

Funcionalidades extras vs. apenas chamar `translate_idml`:

- `_setup_logging(verbose)` — `loguru` em DEBUG/INFO para stderr.
- `_load_env_file()` — carrega `.env` do `cwd` ou da raiz do pacote (2 níveis acima de `translation/cli.py`).
- `_override(cfg, **kwargs)` — produz uma cópia do `TranslationConfig` com campos sobrescritos pelo `--target-lang` e `--model`.

Saída no stdout:
- Caminhos do IDML traduzido (ou dos segmentos em dry-run), do JSON de segmentos, do JSON de traduções, do relatório e das duas pastas de XML.
- Resumo: total / traduzidos / pulados.
- Se não for dry-run: custo estimado USD + tokens.
- Alertas: quantidade de equation_alerts e warnings diversos.

## Fim da referência

Volte ao [índice geral](../README.md).
