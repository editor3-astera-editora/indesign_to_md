# Formato de saída

Anatomia da pasta `out/<slug>/` e schemas dos JSONs gerados.

## Anatomia geral

Após uma conversão **e** uma tradução, a pasta de um livro contém:

```
out/<book_slug>/
├── <book_slug>.md                  ← conversão (idml2md convert)
├── _report.json                    ← auditoria da conversão
├── assets/
│   ├── img/                        ← raster copiado (JPG/PNG/GIF/TIF/WebP)
│   ├── vector/                     ← SVG ou PNG (de .ai e .eps não-mat)
│   └── eqs/                        ← (reservado) fallback raster de equações
├── <book_slug>_<lang>.idml         ← tradução (idml-translate translate)
├── segments.json                   ← segmentos extraídos
├── translations.json               ← traduções produzidas
├── _translation_report.json        ← auditoria da tradução
├── xml_original/                   ← cópia dos Stories XML originais
│   └── Story_<id>.xml
└── xml_traduzido/                  ← Stories XML com texto traduzido
    └── Story_<id>.xml
```

O cache de equações compartilhado (entre execuções) fica fora desta pasta, em `<output_dir>/../.idml2md_cache/equations/<sha1>.tex`.

## `<slug>.md` (Markdown)

Layout fixo:

```markdown
# <Título do livro>

<front matter — title em **bold**, authors/imprint em *italic*>

## Sumário

- [Capítulo 1](#capitulo-1)
  - [Seção 1.1](#secao-1-1)
- [Capítulo 2](#capitulo-2)

<corpo: headings, parágrafos, listas, imagens, admonitions, code, tabelas, eqs>

## Referências

<reference entries>
```

Convenções:
- Headings em `#`..`####` (nível derivado do `level` no `paragraph_styles`).
- Inline: `**bold**`, `*italic*`, `***bold_italic***`, `<sup>`, `<sub>`.
- Equação inline: `$latex$`. Equação display: `$$\nlatex\n$$`.
- Imagens: `![alt](caminho-relativo)`; legenda em `*texto*` na linha seguinte.
- Admonition: GFM (`> [!NOTE]`, `> [!TIP]`, etc.).
- Listas: `-`, `1.`, `I.`, `A.` conforme `marker`. Sublistas indentadas com 2 espaços.

## `_report.json` (ConversionReport)

Schema completo (campos do dataclass em `idml_to_md.report.ConversionReport`):

```jsonc
{
  "tool_version": "0.1.0",
  "book_slug": "81-matematica-financeira",
  "book_title": "81 Matemática Financeira",

  "seen_paragraph_styles":     { "Texto principal": 412, "Títulos:T1": 18, ... },
  "unmapped_paragraph_styles": { "Estilo Novo Que Apareceu": 3 },
  "seen_character_styles":     { "Bold": 87, "Italic": 24 },
  "unmapped_character_styles": { },

  "block_counts": {
    "heading": 65, "paragraph": 412, "list": 19,
    "admonition": 8, "image": 23, "equation_display": 51, "table": 5, ...
  },

  "missing_assets": ["INOVA_F009.jpg"],
  "copied_assets": 71,

  "front_matter_blocks": 4,
  "body_blocks": 612,
  "reference_entries": 22,

  "equations_total": 84,
  "equations_failed": ["81_MF_Eqn073.eps"],
  "equation_cache_hits": 12,
  "equation_cache_misses": 72,

  "vector_converted": ["INOVA_F012.ai"],
  "vector_failed": []
}
```

Indicadores que merecem revisão imediata:
- `unmapped_paragraph_styles` ≠ `{}` → criar overlay YAML para a coleção.
- `missing_assets` ≠ `[]` → checar se a pasta `Links/` está completa.
- `equations_failed` longo → conferir se os EPS são realmente MathType (podem ser ilustrações).
- `vector_failed` ≠ `[]` → verificar Inkscape; fallback Ghostscript também falhou.

## `_translation_report.json` (AuditReport)

Schema completo (campos do Pydantic `idml_to_md.translation.models.AuditReport`):

```jsonc
{
  "source_idml": "<caminho absoluto>",
  "target_lang": "es",
  "target_idml": "<caminho absoluto>",

  "total_segments": 612,
  "translated_segments": 387,
  "skipped_segments": 225,
  "skip_breakdown": {
    "empty": 14, "paragraph_style": 102, "pure_variable": 51,
    "numeric_literal": 38, "pure_symbols": 12, "brand_or_proper_name": 8
  },

  "total_prompt_tokens": 24180,
  "total_completion_tokens": 19002,
  "estimated_cost_usd": 0.014,
  "model": "gpt-4o-mini",

  "equation_alerts": [
    { "eps_basename": "81_MF_Eqn027.eps", "terms_found": ["Juros", "Montante"], "story_id": "" }
  ],
  "warnings": [
    "uxx:3: placeholders ausentes na tradução: [1]",
    "batch failed: APIError ..."
  ],
  "duration_seconds": 73.2
}
```

`equation_alerts` apontam EPS que **não foram tocados** pelo pipeline mas que ainda têm termos PT dentro do MathML — o editor precisa abrir manualmente no MathType para traduzir.

## `segments.json`

Lista plana de `Segment` (Pydantic) serializados:

```jsonc
[
  {
    "segment_id": "u1f81d:0",
    "story_id": "u1f81d",
    "paragraph_idx": 0,
    "paragraph_style": "Títulos:T1",
    "paragraph_kind": "heading",
    "runs": [
      {
        "run_idx": 0, "content_idx": 0,
        "text": "Matemática Financeira",
        "bold": false, "italic": false,
        "superscript": false, "subscript": false,
        "character_style": ""
      }
    ],
    "plain_text": "Matemática Financeira",
    "skip": false,
    "skip_reason": "none",
    "notes": []
  },
  ...
]
```

| Campo | Tipo | Descrição |
|---|---|---|
| `segment_id` | str | `<story_id>:<paragraph_idx>`. Chave estável para o writer. |
| `story_id` | str | ID interno do IDML (`u1f81d`). |
| `paragraph_idx` | int | Posição ordinal 0-based do `ParagraphStyleRange` na Story. |
| `paragraph_style` | str | Nome normalizado do estilo (sem prefixo `ParagraphStyle/`). |
| `paragraph_kind` | str | `kind` resolvido pelo `style_mapper` (`heading`/`paragraph`/`drop`/…). |
| `runs` | list[SegmentRun] | Runs com formatação inline. |
| `plain_text` | str | Concatenação dos `runs[].text`, com `U+00AD` e `U+FEFF` removidos. |
| `skip` | bool | `true` se o classifier marcou como não-traduzível. |
| `skip_reason` | SkipReason | `none`/`empty`/`paragraph_style`/`code_block`/`pure_symbols`/`pure_variable`/`brand_or_proper_name`/`numeric_literal`/`already_translated`. |
| `notes` | list[str] | Anotações livres do classifier. |

## `translations.json`

Lista de `Translation` na mesma ordem dos segmentos traduzíveis:

```jsonc
[
  {
    "segment_id": "u1f81d:3",
    "source_text": "Os juros simples são calculados...",
    "target_text": "Los intereses simples se calculan...",
    "target_runs": [
      { "run_idx": 0, "content_idx": 0, "text": "Los intereses simples...", ... }
    ],
    "model": "gpt-4o-mini",
    "prompt_tokens": 38,
    "completion_tokens": 27,
    "warnings": []
  },
  ...
]
```

`prompt_tokens` e `completion_tokens` por segmento são uma **divisão proporcional** do custo do lote (`tokens_do_lote // len(batch)`); o total exato fica em `_translation_report.json`.

## XML dumps

`xml_original/Story_<id>.xml` e `xml_traduzido/Story_<id>.xml` são cópias byte-a-byte (originais) ou serializações do `lxml` (traduzidos). Servem para:
- Diff visual entre antes/depois.
- Debug do `idml_writer` sem reabrir o IDML.
- Reprocessamento via `scripts/rebuild_idml_from_translations.py` sem reler o `.idml`.

## Próximo

[scripts.md](scripts.md) — scripts auxiliares para validação e regravação.
