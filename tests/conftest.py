"""Fixtures pytest compartilhadas pela suíte."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Raiz do projeto (útil para localizar config/, exemplos)."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Pasta-base das fixtures de teste."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def real_idml_path() -> Path:
    """Caminho do livro real de referência. Só usado em testes de integração."""
    return PROJECT_ROOT / "Indesign_exemplos" / "81_Matemática Financeira.idml"
