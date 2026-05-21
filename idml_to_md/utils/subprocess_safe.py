"""Wrapper seguro para chamadas a binários externos (Saxon, Inkscape, Ghostscript).

Usa ``subprocess.run`` com ``check=False`` e timeout configurável. Captura
stdout/stderr, retorna ``CommandResult``. Levanta ``BinaryNotFoundError``
se o binário não está no PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class CommandResult:
    """Resultado de uma execução de subprocess externo."""

    returncode: int
    stdout: str
    stderr: str


class BinaryNotFoundError(FileNotFoundError):
    """Binário externo não disponível no PATH."""


def which(binary: str) -> Path | None:
    """Localiza o binário no PATH. ``None`` se não encontrado."""
    located = shutil.which(binary)
    return Path(located) if located else None


def run(
    cmd: list[str],
    *,
    timeout: float = 60.0,
    cwd: Path | None = None,
) -> CommandResult:
    """Executa ``cmd`` (lista de args). Lança ``BinaryNotFoundError`` se o
    primeiro elemento não existe no PATH.

    Não levanta em erro de processo — devolve ``CommandResult`` para o
    chamador decidir o que fazer.
    """
    binary = cmd[0]
    if which(binary) is None:
        msg = f"binário ausente no PATH: {binary}"
        raise BinaryNotFoundError(msg)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )
    return CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
