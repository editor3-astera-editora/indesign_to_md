# Referência de CLI

Dois entrypoints expostos pelo `pyproject.toml`:

- `idml2md` → `idml_to_md.cli:app` — conversão IDML → Markdown.
- `idml-translate` → `idml_to_md.translation.cli:app` — tradução IDML → IDML.

Ambos usam [Typer](https://typer.tiangolo.com/); use `--help` em qualquer subcomando para ver a ajuda contextual.

---

## `idml2md`

### `idml2md convert`

Converte um arquivo `.idml` em um único Markdown, copiando os assets vinculados.

```
idml2md convert <idml_path> [OPÇÕES]
```

**Argumentos posicionais**

| Argumento   | Tipo | Obrigatório | Descrição                                               |
|-------------|------|-------------|---------------------------------------------------------|
| `idml_path` | Path | sim         | Caminho do `.idml`. Deve existir, ser arquivo, legível. |

**Opções**

| Flag              | Tipo | Default           | Descrição                                                       |
|-------------------|------|-------------------|-----------------------------------------------------------------|
| `-o`, `--output`  | Path | `out`             | Pasta-pai do output. Será criado `<output>/<slug>/`.            |
| `-c`, `--config`  | Path | _(nenhum)_        | YAML overlay sobre `config/styles.default.yaml`.                |
| `-t`, `--title`   | str  | stem do arquivo   | Título do livro (vai para o `# H1` no topo do MD).              |
| `--links`         | Path | `<idml>/../Links` | Pasta com os assets vinculados (EPS, JPG, AI, PNG).             |
| `--inkscape`      | Path | _(auto)_          | Caminho explícito para `inkscape.exe` (override de PATH e env). |
| `-v`, `--verbose` | flag | desativado        | Log em nível DEBUG.                                             |

**Saída**

```
<output>/<slug>/
  <slug>.md                  ← arquivo único do livro
  _report.json               ← métricas e auditoria
  assets/
    img/                     ← raster copiado (JPG/PNG/etc.)
    vector/                  ← SVG/PNG convertidos de .ai/.eps não-mat
```

`<slug>` é gerado a partir do título via `idml_to_md.utils.slugify.slugify` (lowercase ASCII, hífens). Avisos importantes (estilos não mapeados, assets faltando) são impressos no stderr e detalhados em `_report.json`.

### `idml2md inspect`

Lista todos os `ParagraphStyle` encontrados no IDML com contagem de uso. Útil **antes** de criar um overlay YAML — você só configura o que de fato aparece.

```
idml2md inspect <idml_path> [--top N]
```

| Flag    | Tipo | Default     | Descrição                        |
|---------|------|-------------|----------------------------------|
| `--top` | int  | `0` (todos) | Mostrar apenas os N mais usados. |

Imprime uma tabela Rich com colunas `Estilo` e `Uso`.

### `idml2md version`

Imprime a versão instalada (`idml_to_md.__version__`).

### Subcomandos previstos (ainda não implementados)

Estes existem no plano original (`fuzzy-moseying-lampson.md`) mas **não estão no `cli.py`** atual:

- `idml2md batch` — conversão paralela de um diretório de livros via `ProcessPoolExecutor`.
- `idml2md validate` — sanity check do MD vs. um PDF de referência (contagens de palavras / headings / imagens).

Se aparecerem, esta documentação será atualizada.

---

## `idml-translate`

### `idml-translate translate`

Traduz um IDML completo via OpenAI e gera `<slug>_<lang>.idml` para reabrir no InDesign.

```
idml-translate translate <idml_path> [OPÇÕES]
```

**Argumentos posicionais**

| Argumento   | Tipo | Obrigatório | Descrição                      |
|-------------|------|-------------|--------------------------------|
| `idml_path` | Path | sim         | Caminho do `.idml` fonte (PT). |

**Opções**

| Flag                  | Tipo | Default                   | Descrição                                                                       |
|-----------------------|------|---------------------------|---------------------------------------------------------------------------------|
| `-o`, `--output`      | Path | `out`                     | Pasta-pai do output.                                                            |
| `-l`, `--target-lang` | str  | `es`                      | Código do idioma destino: `es`, `en`, `fr`, `it`, `de`.                         |
| `-c`, `--config`      | Path | _(nenhum)_                | YAML de configuração da tradução (modelo, batch limits, marcas).                |
| `--styles`            | Path | _(nenhum)_                | Overlay para `style_mapper` (afeta classificação de `paragraph_kind`).          |
| `-m`, `--model`       | str  | do config / `gpt-4o-mini` | Override do modelo OpenAI.                                                      |
| `--dry-run`           | flag | desativado                | Só extrai segmentos e gera relatório vazio; NÃO chama OpenAI nem grava `.idml`. |
| `-v`, `--verbose`     | flag | desativado                | Log em nível DEBUG.                                                             |

**Pré-requisito**

`OPENAI_API_KEY` deve estar disponível como variável de ambiente ou no `.env` da raiz do projeto / cwd.

**Saída**

```
<output>/<slug>/
  <slug>_<lang>.idml             ← IDML traduzido (abre no InDesign)
  segments.json                  ← segmentos extraídos (com flags de skip)
  translations.json              ← traduções produzidas pela OpenAI
  _translation_report.json       ← contadores, tokens, custo, alertas
  xml_original/Story_*.xml       ← cópias dos XMLs originais
  xml_traduzido/Story_*.xml      ← XMLs com texto traduzido
```

O CLI imprime no stdout: total de segmentos, traduzidos, pulados, custo estimado em USD, contagem de tokens, número de alertas de equações com termos PT remanescentes.

**Modo `--dry-run`**

Roda extractor + classifier, salva `segments.json`, gera um `_translation_report.json` vazio (com sufixo `(dry-run)` no campo `model`), e termina. Não toca em OpenAI nem grava IDML. Use para conferir o que será enviado e em qual lote antes de gastar tokens.

---

## Códigos de saída

| Código | Significado                                                                       |
|--------|-----------------------------------------------------------------------------------|
| 0      | Sucesso.                                                                          |
| ≠0     | Erro do Typer (argumento inválido, arquivo ausente, etc.) ou exceção do pipeline. |

O pipeline registra avisos via `loguru` (warnings) sem alterar o código de saída — falhas de assets, equações que caíram no fallback e estilos não mapeados aparecem em `_report.json`/`_translation_report.json`.

## Próximo

[configuration.md](configuration.md) — como customizar mapeamentos de estilos e parâmetros de tradução.
