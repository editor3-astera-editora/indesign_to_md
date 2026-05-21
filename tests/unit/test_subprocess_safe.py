"""Testes do ``subprocess_safe``."""

from __future__ import annotations

from pathlib import Path

import pytest

from idml_to_md.utils.subprocess_safe import (
    BinaryNotFoundError,
    CommandResult,
    run,
    which,
)


class TestWhich:
    def test_returns_path_for_python(self) -> None:
        # python sempre está no PATH se este teste roda
        located = which("python")
        # Pode falhar em ambientes onde python só é "python3"
        if located is None:
            located = which("python3")
        assert located is not None
        assert isinstance(located, Path)

    def test_returns_none_for_nonexistent(self) -> None:
        assert which("definitely_not_a_binary_12345") is None


class TestRun:
    def test_runs_python_command(self) -> None:
        result = run(["python", "-c", "print('hi')"], timeout=10.0)
        assert isinstance(result, CommandResult)
        assert result.returncode == 0
        assert "hi" in result.stdout

    def test_captures_stderr(self) -> None:
        result = run(["python", "-c", "import sys; sys.stderr.write('warn')"], timeout=10.0)
        assert result.returncode == 0
        assert "warn" in result.stderr

    def test_non_zero_exit_returns_code(self) -> None:
        result = run(["python", "-c", "import sys; sys.exit(2)"], timeout=10.0)
        assert result.returncode == 2

    def test_missing_binary_raises(self) -> None:
        with pytest.raises(BinaryNotFoundError):
            run(["definitely_not_a_binary_12345"], timeout=5.0)
