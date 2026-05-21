# Pipeline de tradução IDML → IDML

Detalha o fluxo end-to-end orquestrado por `idml_to_md.translation.pipeline.translate_idml`.

O objetivo é **traduzir** o livro mantendo o layout do InDesign intacto, para o editor reabrir o `.idml` traduzido no InDesign Desktop e exportar PDF sem retrabalho de diagramação.

## Visão de alto nível

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ translate_idml(idml_path, output_dir, config=..., dry_run=False)            │
│                                                                             │
│  1. build_style_map(styles_overlay)                ─► style_mapper          │
│  2. extract_segments(idml, style_map, xml_dump_dir) ─► segment_extractor    │
│       (Stories → list[Segment], dump xml_original/Story_*.xml)              │
│  3. classify(segments, brand_names, ...)            ─► classifier           │
│       (marca skip: vazio, código, marca, símbolo, variável, numérico)       │
│  4. Salva segments.json                                                     │
│  5. (se dry_run) → relatório vazio + return                                 │
│  6. TranslatorClient(config, api_key)               ─► openai_client        │
│       └─► translate_segments(segments) → list[Translation]                  │
│             ├─► _chunk_batches() (tiktoken + story affinity)                │
│             ├─► build_batch_prompt() (placeholders §N§)                     │
│             ├─► chat.completions.create (retry exponencial)                 │
│             └─► _distribute_runs() (heurística runs traduzidos)             │
│  7. Salva translations.json                                                 │
│  8. write_translated_idml(idml, target, segments, translations)             │
│       ─► idml_writer (substitui <Content>, regrava ZIP)                     │
│  9. build_audit_report(...) + save_report                                   │
│                                                                             │
│  → TranslationResult(target_idml, segments_path, translations_path,         │
│                      report_path, report, output_dir)                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Etapa por etapa

### 1. Extração de segmentos

`segment_extractor.extract_segments(idml_path, style_map, xml_dump_dir) → list[Segment]`

Reusa `IDMLDocument` + `resolve_reading_order` do pipeline de conversão. Para cada Story:

1. Copia o XML original para `xml_original/Story_<id>.xml`.
2. Itera `<ParagraphStyleRange>` em ordem; cada um vira um `Segment` com:
   - `segment_id = "<story_id>:<paragraph_idx>"` (chave estável).
   - `paragraph_kind` resolvido via `style_map.lookup_paragraph()`.
   - Lista de `SegmentRun` extraída do conteúdo:
     - 1 run por `<CharacterStyleRange>/<Content>`.
     - Atributos `bold`/`italic`/`superscript`/`subscript` deduzidos de `FontStyle`, `Position` e do nome do `CharacterStyle`.
3. `plain_text` = concatenação dos textos, limpando `U+00AD` e `U+FEFF`.
4. Marca skip preliminar: vazio (`SkipReason.EMPTY`) ou `paragraph_kind == "drop"`.

### 2. Classificação

`classifier.classify(segments, brand_names, extra_non_translatable_styles) → list[Segment]`

Aplica heurísticas em ordem, mutando os Segments in-place:

| Teste | `skip_reason` |
|---|---|
| `paragraph_kind in {code_block, drop, equation_display, image, table}` | `CODE_BLOCK` ou `PARAGRAPH_STYLE` |
| `paragraph_style` ∈ `non_translatable_styles` | `PARAGRAPH_STYLE` |
| `plain_text` vazio | `EMPTY` |
| `plain_text` ∈ `brand_names` (match exato) | `BRAND_OR_PROPER_NAME` |
| `plain_text` é numérico (regex `^(?:R\$\s*)?[\d.,/%\s\-+×÷=]+$`) | `NUMERIC_LITERAL` |
| `plain_text` é só símbolos (regex `^[\s\W\d]+$`) | `PURE_SYMBOLS` |
| `plain_text` é variável matemática (1-3 letras + índice opcional, regex `^[A-Za-z]{1,3}(?:[₀-₉]{1,3}\|\d{1,3}\|_[A-Za-z\d]{1,3})?$`) | `PURE_VARIABLE` |

`brand_names` e `non_translatable_styles` vêm do `config/translation.yaml`.

### 3. Persistência dos segmentos

`segments.json` é salvo logo após a classificação, com `model_dump()` de cada `Segment`. Útil para inspeção (`--dry-run`) e para reaproveitamento por `scripts/rebuild_idml_from_translations.py`.

### 4. Lote → OpenAI

`openai_client.TranslatorClient.translate_segments(segments)`:

**`_chunk_batches`** agrupa os segmentos traduzíveis (`skip=False`) em lotes respeitando 3 limites:
- `batch_max_segments` (default 30).
- `batch_max_input_tokens` (default 3000, estimado via `tiktoken.encoding_for_model(model)` com fallback `cl100k_base`).
- **Story affinity**: prefere não cruzar fronteira de Story para preservar contexto narrativo.

**`build_batch_prompt`** (em `prompt_builder.py`) gera:
- **System prompt** em PT-BR orientando: domínio editorial técnico (matemática/finanças/admin), preservar marcadores `§N§...§/N§`, não traduzir variáveis matemáticas, manter pontuação espanhola (¿, ¡) quando aplicável.
- **User prompt** com cada segmento numerado:
  ```
  [[1]] Os §0§juros simples§/0§ são calculados...
  [[2]] ...
  ```
  Apenas runs com formatação inline (`bold`/`italic`/`sup`/`sub`) ganham placeholder `§N§...§/N§`; runs de texto puro vão diretos.

**`_call_api`** chama `client.chat.completions.create(model, temperature, max_tokens, messages)` com retry exponencial via `tenacity`:
- 3 tentativas, backoff 2–10s.
- Loga warning antes de cada retry.
- Reraises após o terceiro fracasso (lote inteiro vai como `failed`).

**`parse_batch_response`** (regex `r"\[\[(\d+)\]\]\s*(.*?)(?=\n\[\[\d+\]\]|\Z)"`) divide a resposta em `{segment_id: target_text}`.

**`_distribute_runs`** reidrata os runs traduzidos:
- Para cada run formatado, lê o conteúdo de `§N§...§/N§` na tradução.
- Texto residual (entre/fora dos placeholders) vai no **primeiro run de texto puro**; demais ficam vazios.
- Placeholder ausente → fallback: texto inteiro no primeiro run, demais zerados (limitação conhecida da v1).

Custo é estimado por lote via `_estimate_cost(model, in_tokens, out_tokens)` usando `_MODEL_PRICING`.

### 5. Persistência das traduções

`translations.json` é salvo após o último lote. Cada entrada tem `segment_id`, `source_text`, `target_text`, `target_runs[]`, `model`, `prompt_tokens`, `completion_tokens`, `warnings[]`.

### 6. Reescrita do IDML

`idml_writer.write_translated_idml(source_idml, target_idml, segments, translations, xml_dump_dir)`:

1. Agrupa Segments por `story_id`.
2. Para cada Story que tem ao menos uma `Translation`:
   - Parseia `Stories/Story_<id>.xml` com `lxml` (sem remover whitespace).
   - Localiza `<ParagraphStyleRange>` pelo `paragraph_idx` (ordinal 0-based).
   - Para cada `<CharacterStyleRange>` filho, lê os `target_runs` correspondentes (mesmo `run_idx`), consolida o texto e substitui no **primeiro `<Content>`** do CSR; os demais Content são esvaziados.
3. Serializa com `etree.tostring` + normalização ao estilo InDesign:
   - Header `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` (aspas duplas).
   - Tags vazias com espaço antes do `/>`: `<Tag attr=".." />` (não `<Tag attr=".."/>`).
4. Reescreve o ZIP IDML preservando ordem dos membros e mantendo `mimetype` como **primeiro** membro com compressão `STORED`.

XMLs traduzidos são opcionalmente espelhados em `xml_traduzido/Story_<id>.xml`.

Garantias:
- IDs (`Self="..."`) **nunca** alterados — InDesign valida.
- Atributos **nunca** alterados — só `text` dos `<Content>`.
- Estrutura ZIP preservada (passa o validador OCF do InDesign).

### 7. Relatório

`audit_reporter.build_audit_report(...)`:
- Conta `total_segments`, `translated_segments`, `skipped_segments`, `skip_breakdown` por motivo.
- Acumula `total_prompt_tokens`, `total_completion_tokens`, `estimated_cost_usd`.
- Junta warnings do `TranslatorStats` + warnings de cada `Translation`.
- **Varre os EPS** em `Links/` (ao lado do `.idml`) por termos PT comuns em matemática financeira (`DEFAULT_PT_TERMS`: Juros, Montante, Capital, Taxa, Tempo, Saldo, Período, Valor, etc.) que tenham permanecido dentro do MathML embutido. EPS são binários gerados pelo MathType — o pipeline **não os modifica**, mas sinaliza para o editor revisar manualmente no MathType.

`save_report(report, path)` serializa em `_translation_report.json`.

## Modo `--dry-run`

Quando `dry_run=True`:
1. Roda extractor + classifier.
2. Salva `segments.json`.
3. Gera `_translation_report.json` com `TranslatorStats` vazio e `model="<model> (dry-run)"`.
4. Pula completamente OpenAI e geração de IDML.

Use para conferir quantos segmentos vão à API e quantos pulam, antes de gastar tokens.

## Limitações conhecidas

- **Tabelas não são segmentadas por célula** na v1; o `paragraph_kind=table` vira skip.
- **Distribuição de runs** é heurística simples: o texto traduzido vai todo no primeiro run de texto puro entre placeholders. Pode causar espaçamento estranho ao redor de negritos se a ordem de palavras mudar muito.
- **EPS MathType com termos PT** não são traduzidos automaticamente — a auditoria só aponta.
- **Glossário não é implementado**: o system prompt cita o domínio mas não fornece lista de termos.

## Próximo

[output-format.md](output-format.md) — schemas dos JSONs gerados.
