# Pipeline de conversão IDML → Markdown

Detalha o fluxo end-to-end orquestrado por `idml_to_md.pipeline.convert_idml`.

## Visão de alto nível

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ convert_idml(idml_path, output_dir, overlay_path, ...)                      │
│                                                                             │
│  1. IDMLDocument(idml_path).open()                ─► idml_reader            │
│  2. resolve_reading_order(doc)                    ─► thread_resolver        │
│  3. build_style_map(overlay_path)                 ─► style_mapper           │
│  4. EquationConverter(cache_dir=...)              ─► mathml_to_latex        │
│  5. Para cada Story:                                                        │
│       walk_story(root, style_map, converter, links_dir)                     │
│         ├─► classify_anchored(...)                ─► anchored_resolver      │
│         ├─► parse_table(...)                      ─► table_renderer         │
│         ├─► extract_mathml(eps)                   ─► equation_extractor     │
│         └─► converter.convert(mathml)             ─► mathml_to_latex        │
│  6. process_raster_assets(...)                    ─► asset_processor        │
│  7. process_vector_assets(...)                    ─► asset_processor        │
│  8. _rewrite_image_paths(document, ...)                                     │
│  9. build_toc(document) + render_document(document) ─► toc_builder + writer │
│ 10. build_report(...)                             ─► report                 │
│                                                                             │
│  → ConversionResult(markdown_path, report_path, report, output_dir)         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Etapa por etapa

### 1. Abertura do IDML

`idml_to_md.idml_reader.IDMLDocument` é um context manager que abre o ZIP IDML via `zipfile.ZipFile`. Não usa `simpleidml` no parsing principal — operamos diretamente sobre `lxml` para ter controle fino dos namespaces.

Expõe:
- `designmap()` — root XML do `designmap.xml`.
- `spread_paths()` — caminhos internos das Spreads na ordem do designmap (= ordem de página).
- `story_paths()` — caminhos `Stories/Story_*.xml`.
- `get_story_root(story_id)` — root XML de uma Story específica.
- `iter_text_frames()` — itera TODOS os TextFrames de TODAS as Spreads em ordem de página.
- `paragraph_style_names()` / `character_style_names()` — nomes definidos (decodificados).

### 2. Ordem de leitura

`idml_to_md.thread_resolver.resolve_reading_order(doc) → list[StoryOrderEntry]`

A unidade lógica é a **Story** (o conteúdo, não o frame). O algoritmo:

1. Itera todos os `TextFrame` de todas as Spreads em ordem de página.
2. Para cada Story, encontra o primeiro frame que a referencia.
3. Sobe pela cadeia `PreviousTextFrame` até a raiz da thread.
4. Ordena Stories pela `(spread_index, order_in_spread)` da raiz.

Edge cases tratados: referências quebradas (master spread, página removida) → para no nó atual; ciclos teoricamente infinitos → safety break em 10.000 iterações.

### 3. Mapa de estilos

`idml_to_md.style_mapper.build_style_map(overlay_path)` carrega `config/styles.default.yaml` e aplica overlay opcional via deep-merge. Retorna um `StyleMap` com:

- `paragraph_rules[nome] → ParagraphRule(kind, raw)`
- `character_rules[nome] → CharacterRule(wrap, html)`
- Counters de auditoria: `seen_paragraph_styles`, `unmapped_paragraph_styles`, idem para character.

Nomes vêm do IDML em formato `ParagraphStyle/Títulos%3aT1`; `normalize_style_name` remove prefixo e faz URL-decode → `Títulos:T1`.

### 4. Walker por Story

`idml_to_md.story_walker.walk_story(root, style_map, *, converter, links_dir) → WalkResult`

Para cada `<ParagraphStyleRange>` (PSR) na Story:

1. Resolve a rule via `style_map.lookup_paragraph()` (que também conta no auditor).
2. Coleta inlines + anchored objects + tabelas via `_walk_paragraph`:
   - `<CharacterStyleRange>` (CSR) → `_detect_inline_kind()` examina `FontStyle` e `Position`.
   - `<Content>` → `TextRun(text, kind=inline_kind)`.
   - `<Br/>` → `LineBreak`.
   - `<Rectangle>` ou `<Group>` → `classify_anchored()` decide raster / vetor / equação.
   - `<Table>` → `parse_table()` com callback recursivo.
3. **Decide inline vs. display** para equações:
   - Parágrafo tem texto não-vazio _além_ das equações → todas viram **inline** (`$latex$`).
   - Parágrafo só tem equação → vira **block display** (`$$latex$$`).
4. Despacha para o tipo correto:
   - `heading` → `Heading(level=rule.get("level", 1))`.
   - `paragraph` → `Paragraph(inlines)`.
   - `list` → item adicionado ao `_BlockStream` que agrupa adjacentes do mesmo tipo; suporta `nested` (alternativas A/B/C/D sob pergunta numerada).
   - `admonition` / `admonition_title` → agrupa em `AdmonitionBlock`; `admonition_title` no parágrafo anterior decora a próxima admonition.
   - `blockquote`, `code_block`, `caption` → blocos diretos.
   - `front_matter` → `result.front_matter.append(...)`.
   - `reference_entry` → `result.references.append(...)`.
   - `drop` → ignora.

Caracteres especiais InDesign são normalizados em `_clean_content`:

| Codepoint | Tratamento |
|---|---|
| `U+2028` (LINE SEPARATOR) | `\n` |
| `U+2029` (PARAGRAPH SEPARATOR) | `\n\n` |
| `U+00AD` (SOFT HYPHEN) | removido |
| `U+FEFF` (BOM) | removido |

### 5. Equações MathType

Quando o `_handle_anchored` encontra um `<Link>` apontando para `.eps`:

1. `extract_mathml(eps_path)` — lê em latin-1, localiza `%MathType!MathML!`, concatena linhas `%...`, recorta `<math>...</math>`, normaliza bugs do MathType (atributos colados como `<mathxmlns`, `<mostretchy`).
2. `EquationConverter.convert(mathml)` — XML parse → render recursivo (suporta `mi`, `mn`, `mo`, `mfrac`, `msqrt`, `mroot`, `msup`/`msub`/`msubsup`, `munder`/`mover`/`munderover`, `mfenced`, `mtable`).
3. Cache: memória + disco opcional em `output_dir.parent/.idml2md_cache/equations/<sha1>.tex`.
4. Operadores e letras gregas Unicode → macros LaTeX via `_OPERATOR_MAP` e `_GREEK_MAP`.

Falhas tratadas:
- EPS sem marcador `%MathType` → `EquationExtractionError` → tratado como ilustração vetorial.
- MathML inválido → `MathMLConversionError` → registrado em `failed_equations[]` do relatório.

### 6. Tabelas

`idml_to_md.table_renderer.parse_table(table_el, walk_paragraph)`:

1. Lê `HeaderRowCount`, `BodyRowCount`, `ColumnCount`.
2. Para cada `<Cell Name="row:col" RowSpan="..." ColumnSpan="...">`, chama o `walk_paragraph` callback para extrair blocos do conteúdo.
3. Retorna `TableBlock(rows, header_row_count)`.

`render_table(block)` decide GFM ou fallback HTML:

- **HTML** quando: célula com `column_span > 1` ou `row_span > 1`, ou conteúdo complexo (mais de 1 bloco, ou bloco que é `ImageBlock`/`EquationBlock`/`TableBlock`).
- **GFM** caso contrário, com header obrigatório (gera linha vazia se o IDML não tinha cabeçalho).

### 7. Processamento de assets

`asset_processor.process_raster_assets`:
- Copia `.jpg`/`.jpeg`/`.png`/`.gif`/`.tif`/`.tiff`/`.webp` de `links_dir/` para `assets/img/`.
- Dedup por SHA-1 do conteúdo; conflitos de nome com hash diferente recebem sufixo `_1.jpg`, `_2.jpg`.
- Retorna `AssetMap` com `output_relative[basename] = "assets/img/<final>"` e `missing[]`.

`asset_processor.process_vector_assets`:
- Para `.ai` e `.eps` (já filtrados como não-mat pelo walker): tenta Inkscape headless (`inkscape --export-type=svg`).
- Fallback: Ghostscript PNG @300dpi (`gs -sDEVICE=png16m -r300 -dEPSCrop`).
- Falhas silenciam (`logger.debug`) e ficam em `vector_failed[]`.

### 8. Reescrita de paths

`_rewrite_image_paths(document, combined_paths)` substitui `block.src` (que era só o basename) pelo caminho relativo final (`assets/img/foo.jpg`, `assets/vector/bar.svg`) em todos os `ImageBlock`.

### 9. TOC e renderização final

`build_toc(document, max_level=2)` coleta todos os `Heading` nível ≤ 2 em ordem, gera slugs únicos via `utils.slugify`, retorna `list[TocEntry]`.

`render_document(document)` serializa em ordem:

1. `# <Title>`
2. Front matter (renderiza títulos como `**...**`, autores como `*...*`, etc.)
3. `## Sumário` + lista de links âncora
4. Body blocks (Heading, Paragraph, ListBlock, AdmonitionBlock, Blockquote, CodeBlock, ImageBlock, EquationBlock, TableBlock, Caption)
5. `## Referências` + entries

Inline formatação:

| InlineKind | Markdown |
|---|---|
| `TEXT` | (sem wrapping) |
| `BOLD` | `**texto**` |
| `ITALIC` | `*texto*` |
| `BOLD_ITALIC` | `***texto***` |
| `SUPERSCRIPT` | `<sup>texto</sup>` |
| `SUBSCRIPT` | `<sub>texto</sub>` |
| `EQUATION_INLINE` | `$latex$` (com espaço de separação automático se necessário) |
| `LINE_BREAK` | `␣␣\n` |

Texto plain é minimamente escapado: `\` → `\\`, `<` → `&lt;`, `>` → `&gt;`. LaTeX inline NÃO é escapado.

### 10. Relatório

`build_report(...)` agrega:
- Contagens de estilos vistos vs. não mapeados (paragraph e character).
- `block_counts` (quantos de cada `BlockKind`).
- `missing_assets[]` + `copied_assets` (total).
- `equations_total`, `equations_failed[]`, `equation_cache_hits`, `equation_cache_misses`.
- `vector_converted[]`, `vector_failed[]`.

Serializa para `_report.json` ao lado do `.md`.

## Decisões-chave de design

- **1 arquivo MD por livro**, não por capítulo. Hierarquia preservada via níveis de heading. TOC vai no topo.
- **Inline vs. block** para equações depende do conteúdo do parágrafo, não de metadata do IDML.
- **Front matter, body, references** ficam em listas separadas no `Document` para o writer poder ordená-los independentemente da ordem de leitura no IDML.
- **Subprocess externos sempre opcionais**: falhas degradam graciosamente para PNG ou _skip_, nunca interrompem a conversão.
- **Cache de equações persistente** em `.idml2md_cache/equations/` (compartilhado entre execuções do mesmo workspace).
- **Inkscape é descoberto preguiçosamente** — se nenhum vetor for solicitado, nem se tenta resolver o binário.

## Próximo

[pipeline-translation.md](pipeline-translation.md) — pipeline paralelo de tradução.
