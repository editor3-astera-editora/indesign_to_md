# Testes

Suíte pytest com gate de cobertura ≥80% no CI.

## Comandos principais

```bash
# Unit only (rápido, <10s — subprocess externos mockados)
pytest

# Unit + integração (executa Saxon/Inkscape/Ghostscript reais se disponíveis)
pytest -m "integration or not integration"

# Cobertura local + relatório HTML em htmlcov/index.html
pytest --cov --cov-report=term-missing --cov-report=html

# Gate do CI — falha se cobertura cair abaixo de 80%
pytest --cov --cov-fail-under=80

# Snapshot tests: atualizar golden files
pytest --snapshot-update tests/unit/test_md_writer.py
```

## Stack

- `pytest >= 8.2`
- `pytest-cov` (coverage.py)
- `pytest-xdist` (paralelismo)
- `pytest-mock`
- `pytest-snapshot` (golden Markdown)

Configuração em `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = ["-ra", "--strict-markers", "--strict-config"]
testpaths = ["tests"]
markers = [
    "integration: testes lentos que executam binários externos reais ...",
    "slow: testes que tomam mais de 5 segundos",
]
filterwarnings = ["error", "ignore::DeprecationWarning:simple_idml.*"]
```

`filterwarnings = ["error", ...]` significa que qualquer warning de outro lugar **falha** o teste — quem introduz um warning precisa filtrá-lo explicitamente.

## Marcadores

| Marcador | Para que serve |
|---|---|
| `@pytest.mark.integration` | Executa pipeline completo no `Indesign_exemplos/81_Matemática Financeira.idml`. Usa binários externos reais. Pulado por default no loop local. |
| `@pytest.mark.slow` | Testes que tomam >5s. Não pulam por default; use para filtrar com `-m "not slow"` em desenvolvimento. |

## Cobertura — `.coveragerc`

```ini
[run]
branch = True
source = idml_to_md
omit =
    idml_to_md/cli.py
    scripts/*
    tests/*
    */__init__.py

[report]
fail_under = 80
show_missing = True
exclude_also =
    pragma: no cover
    raise NotImplementedError
    if TYPE_CHECKING:
    if __name__ == .__main__.:
```

- O CLI principal (`cli.py`) é omitido porque a cobertura dele vem dos testes E2E do pipeline; testá-lo unitariamente é redundante.
- Scripts auxiliares ficam fora — são executados manualmente.
- Política do projeto: **cobertura ≥80% é não-negociável** (gate do CI).

## Estrutura

```
tests/
├── conftest.py                  ← fixtures globais (project_root, fixtures_dir, real_idml_path)
├── README.md
├── unit/
│   ├── test_anchored_resolver.py
│   ├── test_asset_processor.py
│   ├── test_equation_extractor.py
│   ├── test_idml_reader.py
│   ├── test_mathml_to_latex.py
│   ├── test_md_writer.py
│   ├── test_pipeline.py
│   ├── test_report.py
│   ├── test_smoke.py
│   ├── test_story_walker.py
│   ├── test_style_mapper.py
│   ├── test_subprocess_safe.py
│   ├── test_table_renderer.py
│   ├── test_thread_resolver.py
│   ├── test_toc_builder.py
│   └── translation/
│       ├── conftest.py
│       ├── test_audit_reporter.py
│       ├── test_classifier.py
│       ├── test_cli.py
│       ├── test_idml_writer.py
│       ├── test_models.py
│       ├── test_openai_client.py
│       ├── test_pipeline.py
│       ├── test_prompt_builder.py
│       └── test_segment_extractor.py
└── integration/
    └── test_pipeline_real.py    ← @pytest.mark.integration
```

## Fixtures globais

`tests/conftest.py` expõe:

| Fixture | Escopo | Retorno |
|---|---|---|
| `project_root` | session | `Path` da raiz do projeto. |
| `fixtures_dir` | session | `Path` de `tests/fixtures/`. |
| `real_idml_path` | session | `Path` do `Indesign_exemplos/81_Matemática Financeira.idml`. |

Use `tmp_path` (built-in do pytest) para output temporário em testes unitários.

## Princípios

- **Subprocess externos sempre mockados** em unit tests (Saxon, Inkscape, Ghostscript). A integração real é exercida só em `tests/integration/test_pipeline_real.py`.
- **Filesystem** isolado via `tmp_path` em testes unitários.
- **OpenAI** mockada em `tests/unit/translation/` via `pytest-mock`; `TranslatorClient(client=mock)` aceita um cliente injetado para testes.
- **Snapshot tests** comparam o Markdown gerado contra arquivos golden em `tests/fixtures/expected/`. Atualizar intencionalmente com `--snapshot-update`; sempre revise o diff no PR.
- **Warnings = erros** (via `filterwarnings = ["error"]`): isso pega DeprecationWarning silenciosa cedo.

## Próximo

[troubleshooting.md](troubleshooting.md) — diagnóstico de problemas comuns.
