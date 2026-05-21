# Troubleshooting

Problemas comuns, diagnóstico e mitigação.

## Conversão (`idml2md convert`)

### `BinaryNotFoundError: inkscape`

**Causa.** O pipeline precisa converter `.ai` ou `.eps` não-matemáticos em SVG, mas o Inkscape não foi localizado.

**Solução.**

1. Passe o caminho explícito: `idml2md convert ... --inkscape "C:/Path/To/inkscape.exe"`.
2. Ou exporte: `set IDML2MD_INKSCAPE_PATH=C:/Path/To/inkscape.exe` (PowerShell: `$env:IDML2MD_INKSCAPE_PATH=...`).
3. Ou adicione o Inkscape ao `PATH`.

**Sem Inkscape disponível.** O pipeline cai automaticamente em Ghostscript (PNG @300dpi). Se Ghostscript também falhar, o vetorial fica em `vector_failed[]` no `_report.json` e a referência some do MD — investigar arquivos listados.

### `EquationExtractionError: EPS sem marcador MathType`

**Causa.** O `.eps` referenciado **não** é uma equação MathType — é uma ilustração vetorial.

**O que o pipeline faz.** Captura a exceção silenciosamente e trata o EPS como ilustração vetorial (entra em `vector_basenames` e é convertido por `process_vector_assets`).

**Quando se preocupar.** Se uma equação real está caindo aqui, o EPS foi criado por outra ferramenta (não MathType) ou perdeu os comentários PostScript. Solução: regerar pela MathType.

### `unmapped_paragraph_styles` ≠ `{}` no relatório

**Causa.** ParagraphStyles que apareceram no IDML não existem em `config/styles.default.yaml`.

**Solução.**

1. Rode `idml2md inspect <livro.idml>` para listar todos os estilos com contagem.
2. Crie `config/styles.<colecao>.yaml` mapeando os que aparecem em `unmapped_paragraph_styles`:
   ```yaml
   paragraph_styles:
     "Novo Estilo": { kind: paragraph }
     "Outro Estilo Drop": { kind: drop, reason: "marca d'água" }
   ```
3. Rode novamente com `-c config/styles.<colecao>.yaml`.

A política `unknown_paragraph_style: passthrough` (default) garante que o conteúdo **não é perdido** — vira parágrafo genérico até você mapear.

### Tabela com merged cells aparece como HTML "feio"

**Causa.** GFM (`| col1 | col2 |`) não suporta `rowspan`/`colspan`. O pipeline detecta merged cells e cai automaticamente em `<table>` HTML.

**Comportamento esperado.** Visualizadores Markdown que suportam HTML inline (VS Code, GitHub, Obsidian) renderizam corretamente. Não há fix — é limitação do GFM.

### Equação não renderiza no visualizador

**Diagnóstico.**

1. Verifique se o visualizador tem suporte a math (extensão Markdown+Math em VS Code, plugin Math no Obsidian).
2. Veja `equations_failed[]` no `_report.json` — se o EPS está lá, a conversão falhou e o `$$...$$` ficou vazio.
3. Para EPS específico, rode `python scripts/extract_mathml_smoke.py <pasta_com_o_eps>` para isolar a falha.

### `missing_assets` ≠ `[]`

**Causa.** O IDML referencia um arquivo em `Links/` que não existe na pasta.

**Solução.**

1. Confirme que a pasta `Links/` está completa.
2. Use `--links <PATH>` para apontar outro lugar.
3. Em projetos com assets distribuídos, considere copiar tudo para uma pasta `Links/` local antes da conversão.

## Tradução (`idml-translate translate`)

### `OPENAI_API_KEY não configurada` (RuntimeError)

**Causa.** A chave não está no ambiente nem no `.env`.

**Solução.** Copie `.env.example` para `.env` e preencha:

```
OPENAI_API_KEY=sk-proj-...
```

Ou exporte explicitamente: `set OPENAI_API_KEY=sk-...` (PowerShell: `$env:OPENAI_API_KEY=...`).

### `Pacote openai não instalado`

**Causa.** `openai>=1.30` não está instalado.

**Solução.**

```bash
pip install "openai>=1.30"
# ou refazer pip install -e ".[dev]" que já inclui
```

### Custo estimado muito alto / quero limitar

**Soluções.**

1. Use `--dry-run` para ver quantos segmentos vão à API antes de gastar tokens.
2. Reduza `batch_max_input_tokens` no `config/translation.yaml` para forçar lotes menores (mais chamadas, mas menor risco de truncamento da resposta).
3. Use modelo mais barato: `--model gpt-4o-mini` (default) já é o mais barato com qualidade aceitável; `gpt-3.5-turbo` é ainda mais barato.
4. Marque mais estilos como `non_translatable_styles` no YAML para pular legendas, créditos, etc.

### Resposta da OpenAI ignora placeholders `§N§`

**Sintoma.** Em `_translation_report.json`, vários `warnings` contêm `placeholders ausentes na tradução: [N]`.

**Causa.** O modelo "esqueceu" do marcador. `_distribute_runs` faz fallback colocando texto inteiro no primeiro run e zerando os demais — a formatação inline (negrito/itálico) é perdida nesse parágrafo.

**Mitigação.**

1. Aumente `temperature: 0.0` no `config/translation.yaml` (default `0.2`).
2. Reduza `batch_max_segments` para diminuir confusão do modelo entre vários `[[N]]` simultâneos.
3. Use modelo maior (`gpt-4o`) — mais caro mas mais fiel a placeholders.

### `equation_alerts` no relatório de tradução

**Sintoma.** EPS listados com termos PT remanescentes (`Juros`, `Montante`, etc.).

**Causa.** O pipeline **não traduz EPS** — eles são binários gerados pela MathType. O alerta é informativo.

**Solução manual.**

1. Abra o EPS no MathType.
2. Edite as labels em português.
3. Salve. O EPS atualizado é referenciado pelo IDML automaticamente.

### IDML traduzido não abre no InDesign

**Diagnóstico.**

1. Confirme que o `mimetype` ficou como **primeiro** membro do ZIP e com compressão STORED — o `idml_writer._write_idml_zip` faz isso automaticamente. Use `unzip -l <slug>_<lang>.idml | head -5` para verificar.
2. Diff um `Story_<id>.xml` em `xml_original/` vs. `xml_traduzido/` — só `<Content>` deveria ter mudado.
3. Se o InDesign reclamar de XML inválido, abra o arquivo problemático e procure `<` ou `>` literal sem escape no texto traduzido.

### `paragraph_idx fora do range`

**Sintoma.** Warning no log: `paragraph_idx N fora do range para Story (psrs=M)`.

**Causa.** `segments.json` foi gerado para uma versão do IDML diferente da que está sendo regravada — a estrutura mudou entre extração e write.

**Solução.** Use o **mesmo** `.idml` original em todas as etapas. Se o IDML foi editado entre `segment_extractor` e `idml_writer`, re-rode o `translate` completo.

## Testes

### `pytest --cov` reprovou (cobertura abaixo de 80%)

**Não bypasse.** A política do projeto é não-negociável.

**Diagnóstico.** `pytest --cov --cov-report=term-missing` mostra as linhas não cobertas. Para HTML interativo: `pytest --cov --cov-report=html` e abra `htmlcov/index.html`.

### Teste `tests/integration/test_pipeline_real.py` falha localmente

**Causa.** Precisa do `Indesign_exemplos/81_Matemática Financeira.idml` (1.4 MB) presente, e Inkscape + Ghostscript no PATH.

**Solução.** Rode só os unit tests no loop local: `pytest` (default — pula `integration`).

### `filterwarnings = error` falha um teste com DeprecationWarning

**Causa.** Algum import emitiu DeprecationWarning não-filtrada.

**Solução.** Adicione o filtro específico no `pyproject.toml`:

```toml
filterwarnings = [
    "error",
    "ignore::DeprecationWarning:simple_idml.*",
    "ignore::DeprecationWarning:meu_modulo_problema",
]
```

Prefira filtros específicos a `ignore::DeprecationWarning` global — assim novos avisos continuam pegando.

## Diagnóstico geral

### Habilitar logs DEBUG

Tanto `idml2md` quanto `idml-translate` aceitam `-v` / `--verbose` para nível DEBUG (vai para stderr via `loguru`).

### Inspeção sem rodar nada

```bash
# Quais estilos de parágrafo o livro usa?
idml2md inspect "livro.idml" --top 50

# Quais EPS convertem MathML?
python scripts/extract_mathml_smoke.py "<links_dir>" --verbose
```

### Reaproveitar trabalho parcial

Tradução interrompida no meio?

- `segments.json` é salvo **antes** da OpenAI (sobrevive).
- `translations.json` é salvo **depois** de todos os lotes (não sobrevive se travou no meio).

Para retomar do zero sem re-extrair: use `scripts/rebuild_idml_from_translations.py` com os JSONs parciais (vai usar `target_text` vazio para os ausentes — equivalente a não traduzir aquele parágrafo).
