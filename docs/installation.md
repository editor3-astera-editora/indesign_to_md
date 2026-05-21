# Instalação

Pré-requisitos, instalação do pacote, binários externos opcionais e variáveis de ambiente.

## Pré-requisitos

| Componente | Versão mínima | Obrigatório? |
|---|---|---|
| Python | 3.11 | sim |
| Java JRE | 17 | só se for usar Saxon (mml2tex) — **não exigido** pelo conversor interno |
| Inkscape | 1.2 | só para converter `.ai` / `.eps` não-matemáticos em SVG |
| Ghostscript | 10 | fallback raster quando Inkscape falha |
| OpenAI account | — | só para o pipeline de tradução |

Os binários externos são **opcionais**: a conversão de Markdown roda mesmo sem eles, com perda graceful (vetoriais ficam como `vector_failed` no `_report.json`; equações continuam funcionando porque o conversor MathML→LaTeX é Python puro).

## Instalação do pacote

Clone (ou copie) o projeto e instale em modo editável:

```bash
pip install -e ".[dev]"
```

A flag `[dev]` traz `pytest`, `pytest-cov`, `pytest-xdist`, `pytest-mock`, `pytest-snapshot`, `ruff` e `mypy`. Sem ela, apenas as dependências de runtime (`simpleidml`, `lxml`, `typer`, `pydantic`, `pyyaml`, `loguru`, `rich`, `pillow`, `tenacity`, `openai`, `tiktoken`, `python-dotenv`) são instaladas.

Após a instalação, dois entrypoints ficam disponíveis no PATH:

- `idml2md` — conversão IDML → Markdown (subcomandos `convert`, `inspect`, `version`).
- `idml-translate` — tradução IDML → IDML (subcomando `translate`).

## Variáveis de ambiente

| Variável | Para que serve | Onde é lida |
|---|---|---|
| `OPENAI_API_KEY` | Autentica na API OpenAI no pipeline de tradução. | `idml_to_md.translation.openai_client` |
| `IDML2MD_INKSCAPE_PATH` | Caminho explícito para `inkscape.exe` (override de PATH). | `idml_to_md.asset_processor` |

Crie `.env` na raiz do projeto a partir de `.env.example`:

```
OPENAI_API_KEY=sk-proj-...
```

O CLI `idml-translate` carrega `.env` automaticamente via `python-dotenv` se o arquivo existir no `cwd` ou na raiz do pacote.

## Localização do Inkscape (Windows)

`idml_to_md.asset_processor.resolve_inkscape_path` resolve o binário na seguinte ordem de prioridade:

1. Caminho explícito passado via `idml2md convert --inkscape <PATH>`.
2. Variável de ambiente `IDML2MD_INKSCAPE_PATH`.
3. Binário `inkscape` (ou `inkscape.exe`) no `PATH`.
4. Caminhos típicos no Windows:
   - `~/Inkscape/bin/inkscape.exe`
   - `~/Inkscape/PFiles64/Inkscape/bin/inkscape.exe`
   - `C:\Program Files\Inkscape\bin\inkscape.exe`
   - `C:\Program Files (x86)\Inkscape\bin\inkscape.exe`

Se nada for encontrado, o pipeline cai diretamente no fallback Ghostscript (PNG @300dpi). Falhas silenciam para `vector_failed[]` no relatório — não interrompem a conversão.

## Validação da instalação

```bash
# Versão instalada
idml2md version

# Lista os subcomandos e flags
idml2md --help
idml-translate --help

# Smoke test (extrai MathML de todos os EPS da pasta)
python scripts/extract_mathml_smoke.py <pasta_com_eps>

# Suíte de testes rápida (unit only)
pytest

# Suíte completa com gate de cobertura
pytest --cov --cov-fail-under=80
```

Se `idml2md` não for encontrado, confirme que o `pip install -e` foi feito no mesmo virtualenv em que o terminal está rodando.

## Próximo

[cli.md](cli.md) — referência de comandos.
