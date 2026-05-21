"""Carga e validação de configuração YAML (default + overlay por coleção).

A implementação completa entra em F1. Por ora, expomos apenas o loader do
``styles.default.yaml`` para que o smoke test confirme que o arquivo é válido.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_STYLES_PATH = Path(__file__).resolve().parents[1] / "config" / "styles.default.yaml"


def load_default_styles(path: Path | None = None) -> dict[str, Any]:
    """Carrega o YAML de mapeamento de estilos default.

    Args:
        path: caminho opcional para override (usado em testes).

    Returns:
        Dicionário com a estrutura do YAML.
    """
    target = path or DEFAULT_STYLES_PATH
    with target.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        msg = f"styles YAML em {target} deve ser um mapping, recebido {type(data).__name__}"
        raise TypeError(msg)
    return data
