# idml-to-md

Pipeline **IDML-first** para converter livros didáticos do Adobe InDesign em Markdown estruturado, com **alta fidelidade** ao conteúdo editorial original — sem OCR.

Substitui o pipeline anterior baseado em PyMuPDF + DocLayout-YOLO operando sobre o PDF final.

## Por que IDML?

O arquivo `.idml` é a representação XML aberta do projeto InDesign. Ele preserva a semântica editorial (ParagraphStyles, hierarquia, tabelas, objetos ancorados) que se perde ao rasterizar para PDF. Combinado com os assets vinculados (`Links/*.eps`, `*.ai`, `*.jpg`), permite reconstruir o livro com fidelidade máxima:

- **Hierarquia** derivada dos nomes de ParagraphStyle (`Títulos:T1`–`T4` → `#`–`####`).
- **Equações** extraídas do **MathML embutido** nos comentários PostScript dos EPS gerados pela MathType — sem OCR.
- **Imagens** copiadas (raster) ou convertidas (vetorial `.ai`/`.eps` → SVG via Inkscape).
- **Tabelas** mapeadas para GFM (fallback HTML para células mescladas).
- **Caixas de destaque** viram admonitions GFM (`> [!NOTE]`).

## Saída

Para cada livro convertido:

```
out/<book_slug>/
  <book_slug>.md     ← arquivo único do livro, com TOC no topo
  assets/
    img/             ← JPG/PNG
    vector/          ← SVG (oriundos de .ai/.eps não-matemáticos)
    eqs/             ← fallback raster de equações quando MathML falha
  _report.json       ← auditoria (estilos não mapeados, fórmulas falhas, etc.)
```

## Instalação

Requer Python ≥ 3.11.

```bash
pip install -e ".[dev]"
```

Binários externos necessários no PATH (validados no startup do CLI):

- **Saxon-HE 12+** + Java 17+ — MathML→LaTeX via [`mml2tex`](https://github.com/transpect/mml2tex)
- **Inkscape ≥ 1.2** — `.ai`/`.eps` → SVG
- **Ghostscript ≥ 10** — fallback raster

## Uso

```bash
# Listar estilos encontrados num livro (antes de criar overlay YAML)
idml2md inspect "Indesign_exemplos/81_Matemática Financeira.idml"

# Converter um livro
idml2md convert "Indesign_exemplos/81_Matemática Financeira.idml" -o out/

# Converter um diretório de livros em paralelo
idml2md batch ./books/ -o ./out/ --workers 8 --report agregado.json
```

> Os subcomandos acima entram nas Fases F1–F4. Veja `tests/README.md` e o plano em `~/.claude/plans/fuzzy-moseying-lampson.md`.

## Desenvolvimento

```bash
pytest                              # unit (rápido)
pytest --cov --cov-fail-under=80    # gate do CI
ruff check . && ruff format .
mypy idml_to_md
```

Cobertura de testes mínima **80%** — política do projeto, gate no CI.

## Configuração

`config/styles.default.yaml` define o mapeamento padrão de ParagraphStyle/CharacterStyle. Para coleções específicas, criar `config/styles.<colecao>.yaml` (deep-merge sobre o default).

## Licença

MIT.


python -m idml_to_md.cli convert "Indesign_exemplos/81_Matemática Financeira.idml" -o out --inkscape "C:/Users/Luiz.barros/Inkscape/PFiles64/Inkscape/bin/inkscape.exe"

python -m idml_to_md.cli convert "Indesign_exemplos/81_Matemática Financeira.idml" -o out