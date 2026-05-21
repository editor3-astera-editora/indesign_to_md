# Testes — idml-to-md

## Como rodar

```bash
# unit (rápido, <10s; subprocess externos mockados)
pytest

# unit + integração (executa Saxon, Inkscape, Ghostscript reais)
pytest -m "integration or not integration"

# cobertura local (HTML em htmlcov/index.html)
pytest --cov --cov-report=term-missing --cov-report=html

# gate do CI (falha se cobertura < 80%)
pytest --cov --cov-fail-under=80
```

## Estrutura

- `unit/` — testes unitários, sem rede, sem subprocess externo real.
- `integration/` — fim-a-fim com o IDML real `Indesign_exemplos/81_Matemática Financeira.idml`. Marcador `@pytest.mark.integration`.
- `fixtures/` — IDMLs sintéticos pequenos por padrão a cobrir + EPS reais + golden Markdown.

## Snapshot (golden) tests

Em F1+ usaremos `pytest-snapshot`. Para atualizar:

```bash
pytest --snapshot-update tests/unit/test_md_writer.py
```

Sempre revise o diff no PR antes de confirmar a atualização.
