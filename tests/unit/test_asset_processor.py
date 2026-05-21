"""Testes do ``asset_processor``."""

from __future__ import annotations

from pathlib import Path

import pytest

from idml_to_md.asset_processor import (
    process_raster_assets,
    process_vector_assets,
)


@pytest.fixture
def links_dir(tmp_path: Path) -> Path:
    d = tmp_path / "Links"
    d.mkdir()
    (d / "foo.jpg").write_bytes(b"FAKE_JPG_DATA")
    (d / "bar.png").write_bytes(b"FAKE_PNG_DATA")
    (d / "duplicate.jpg").write_bytes(b"FAKE_JPG_DATA")  # mesmo conteúdo de foo.jpg
    (d / "vector.eps").write_bytes(b"FAKE_EPS_DATA")
    return d


@pytest.fixture
def out_assets(tmp_path: Path) -> Path:
    return tmp_path / "out" / "assets" / "img"


class TestCopy:
    def test_copies_jpg(self, links_dir: Path, out_assets: Path) -> None:
        m = process_raster_assets(["foo.jpg"], links_dir, out_assets)
        assert m.output_relative == {"foo.jpg": "assets/img/foo.jpg"}
        assert (out_assets / "foo.jpg").exists()

    def test_skips_non_raster(self, links_dir: Path, out_assets: Path) -> None:
        m = process_raster_assets(["vector.eps"], links_dir, out_assets)
        assert m.output_relative == {}
        assert m.skipped_non_raster == ["vector.eps"]

    def test_missing_recorded(self, links_dir: Path, out_assets: Path) -> None:
        m = process_raster_assets(["missing.jpg"], links_dir, out_assets)
        assert m.missing == ["missing.jpg"]

    def test_dedup_by_hash(self, links_dir: Path, out_assets: Path) -> None:
        m = process_raster_assets(["foo.jpg", "duplicate.jpg"], links_dir, out_assets)
        # Ambos apontam para a mesma cópia (foo.jpg foi copiado primeiro)
        assert m.output_relative["foo.jpg"] == "assets/img/foo.jpg"
        assert m.output_relative["duplicate.jpg"] == "assets/img/foo.jpg"
        # duplicate.jpg NÃO foi escrito no destino
        assert not (out_assets / "duplicate.jpg").exists()

    def test_dedup_within_same_request(self, links_dir: Path, out_assets: Path) -> None:
        m = process_raster_assets(["foo.jpg", "foo.jpg", "bar.png"], links_dir, out_assets)
        assert len(m.output_relative) == 2

    def test_name_collision_disambiguates(self, links_dir: Path, out_assets: Path) -> None:
        out_assets.mkdir(parents=True)
        # Cria um foo.jpg pré-existente com conteúdo DIFERENTE
        (out_assets / "foo.jpg").write_bytes(b"OTHER_DATA")
        m = process_raster_assets(["foo.jpg"], links_dir, out_assets)
        assert m.output_relative == {"foo.jpg": "assets/img/foo_1.jpg"}
        assert (out_assets / "foo_1.jpg").exists()
        assert (out_assets / "foo.jpg").read_bytes() == b"OTHER_DATA"

    def test_empty_request_creates_dir_only(self, links_dir: Path, out_assets: Path) -> None:
        m = process_raster_assets([], links_dir, out_assets)
        assert m.output_relative == {}
        assert out_assets.exists()


class TestProcessVector:
    """F3: conversão de .ai/.eps via Inkscape (mockado)."""

    @pytest.fixture
    def links_with_vectors(self, tmp_path: Path) -> Path:
        d = tmp_path / "Links"
        d.mkdir()
        (d / "illustration.ai").write_bytes(b"FAKE_AI")
        (d / "vector.eps").write_bytes(b"FAKE_EPS")
        return d

    @pytest.fixture
    def vector_out(self, tmp_path: Path) -> Path:
        return tmp_path / "out" / "assets" / "vector"

    def test_inkscape_success_produces_svg(
        self, links_with_vectors: Path, vector_out: Path, mocker
    ) -> None:
        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            # Simula Inkscape: cria o SVG no destino
            for arg in cmd:
                if arg.startswith("--export-filename="):
                    Path(arg.split("=", 1)[1]).write_text("<svg/>", encoding="utf-8")
            from idml_to_md.utils.subprocess_safe import CommandResult

            return CommandResult(returncode=0, stdout="", stderr="")

        mocker.patch(
            "idml_to_md.asset_processor.resolve_inkscape_path",
            return_value=Path("/usr/bin/inkscape"),
        )
        mocker.patch("idml_to_md.asset_processor.run", side_effect=fake_run)

        m = process_vector_assets(["illustration.ai"], links_with_vectors, vector_out)
        assert "illustration.ai" in m.output_relative
        assert m.output_relative["illustration.ai"].endswith("illustration.svg")
        assert "illustration.ai" in m.vector_converted

    def test_inkscape_failure_falls_back_to_ghostscript(
        self, links_with_vectors: Path, vector_out: Path, mocker
    ) -> None:
        from idml_to_md.utils.subprocess_safe import CommandResult

        call_count = {"n": 0}

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            call_count["n"] += 1
            if cmd[0] == "inkscape":
                return CommandResult(returncode=1, stdout="", stderr="boom")
            if cmd[0] == "gs":
                # Cria PNG e retorna 0
                for arg in cmd:
                    if arg.startswith("-sOutputFile="):
                        Path(arg.split("=", 1)[1]).write_bytes(b"PNG_FAKE")
                return CommandResult(returncode=0, stdout="", stderr="")
            return CommandResult(returncode=127, stdout="", stderr="")

        mocker.patch(
            "idml_to_md.asset_processor.resolve_inkscape_path",
            return_value=Path("/usr/bin/inkscape"),
        )
        mocker.patch("idml_to_md.asset_processor.run", side_effect=fake_run)

        m = process_vector_assets(["vector.eps"], links_with_vectors, vector_out)
        assert "vector.eps" in m.output_relative
        assert m.output_relative["vector.eps"].endswith("vector.png")
        assert "vector.eps" in m.vector_converted

    def test_no_inkscape_falls_back(
        self, links_with_vectors: Path, vector_out: Path, mocker
    ) -> None:
        from idml_to_md.utils.subprocess_safe import CommandResult

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            if cmd[0] == "gs":
                for arg in cmd:
                    if arg.startswith("-sOutputFile="):
                        Path(arg.split("=", 1)[1]).write_bytes(b"PNG")
                return CommandResult(returncode=0, stdout="", stderr="")
            return CommandResult(returncode=127, stdout="", stderr="")

        # resolve retorna None → Inkscape ausente
        mocker.patch("idml_to_md.asset_processor.resolve_inkscape_path", return_value=None)
        mocker.patch("idml_to_md.asset_processor.run", side_effect=fake_run)
        m = process_vector_assets(["illustration.ai"], links_with_vectors, vector_out)
        assert "illustration.ai" in m.output_relative

    def test_both_fail_records_in_failed(
        self, links_with_vectors: Path, vector_out: Path, mocker
    ) -> None:
        from idml_to_md.utils.subprocess_safe import CommandResult

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            return CommandResult(returncode=1, stdout="", stderr="")

        mocker.patch(
            "idml_to_md.asset_processor.resolve_inkscape_path",
            return_value=Path("/usr/bin/inkscape"),
        )
        mocker.patch("idml_to_md.asset_processor.run", side_effect=fake_run)
        m = process_vector_assets(["illustration.ai"], links_with_vectors, vector_out)
        assert "illustration.ai" in m.vector_failed
        assert "illustration.ai" not in m.output_relative

    def test_missing_file_recorded(self, links_with_vectors: Path, vector_out: Path) -> None:
        m = process_vector_assets(["nonexistent.ai"], links_with_vectors, vector_out)
        assert "nonexistent.ai" in m.missing

    def test_non_vector_extension_skipped(self, tmp_path: Path) -> None:
        links = tmp_path / "Links"
        links.mkdir()
        (links / "x.jpg").write_bytes(b"x")
        out = tmp_path / "out"
        m = process_vector_assets(["x.jpg"], links, out)
        # JPG não é vetorial → nem em output_relative nem em failed
        assert m.output_relative == {}
        assert m.vector_failed == []


class TestResolveInkscapePath:
    """Resolução do caminho do Inkscape com várias estratégias."""

    def test_explicit_path_wins(self, tmp_path: Path, mocker) -> None:
        from idml_to_md.asset_processor import resolve_inkscape_path

        existing = tmp_path / "inkscape.exe"
        existing.write_text("fake")
        # which retorna outro caminho mas explícito vence
        mocker.patch("idml_to_md.asset_processor.which", return_value=Path("/usr/bin/inkscape"))
        result = resolve_inkscape_path(explicit=existing)
        assert result == existing

    def test_explicit_nonexistent_returns_none(self, tmp_path: Path, mocker) -> None:
        from idml_to_md.asset_processor import resolve_inkscape_path

        # Mesmo com PATH disponível, explícito inválido → None
        mocker.patch("idml_to_md.asset_processor.which", return_value=Path("/usr/bin/inkscape"))
        result = resolve_inkscape_path(explicit=tmp_path / "missing.exe")
        assert result is None

    def test_env_var_used(self, tmp_path: Path, monkeypatch, mocker) -> None:
        from idml_to_md.asset_processor import resolve_inkscape_path

        existing = tmp_path / "inkscape.exe"
        existing.write_text("fake")
        monkeypatch.setenv("IDML2MD_INKSCAPE_PATH", str(existing))
        mocker.patch("idml_to_md.asset_processor.which", return_value=None)
        result = resolve_inkscape_path()
        assert result == existing

    def test_path_fallback(self, monkeypatch, mocker) -> None:
        from idml_to_md.asset_processor import resolve_inkscape_path

        monkeypatch.delenv("IDML2MD_INKSCAPE_PATH", raising=False)
        from_path = Path("/usr/bin/inkscape")
        mocker.patch("idml_to_md.asset_processor.which", return_value=from_path)
        result = resolve_inkscape_path()
        assert result == from_path

    def test_returns_none_when_nothing_works(self, monkeypatch, mocker) -> None:
        from idml_to_md.asset_processor import resolve_inkscape_path

        monkeypatch.delenv("IDML2MD_INKSCAPE_PATH", raising=False)
        mocker.patch("idml_to_md.asset_processor.which", return_value=None)
        mocker.patch(
            "idml_to_md.asset_processor._candidate_inkscape_paths",
            return_value=iter([]),
        )
        assert resolve_inkscape_path() is None
