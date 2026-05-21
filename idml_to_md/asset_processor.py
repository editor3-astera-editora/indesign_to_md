"""Copia/converte assets do diretório Links/ para o output.

Raster (F1):
- ``.jpg``/``.jpeg``/``.png``/``.gif``/``.tif``/``.tiff``/``.webp`` → cópia 1:1
  para ``assets/img/``, deduplicado por SHA-1.

Vetorial (F3):
- ``.ai`` (Adobe Illustrator) e ``.eps`` (NÃO-MathType) → conversão para SVG
  via Inkscape headless. Fallback Ghostscript → PNG @300dpi se Inkscape
  falhar ou não estiver disponível.

Localização do Inkscape, em ordem de prioridade:
1. Caminho explícito passado via ``inkscape_path`` no ``process_vector_assets``.
2. Variável de ambiente ``IDML2MD_INKSCAPE_PATH``.
3. Binário ``inkscape`` no PATH.
4. Caminhos típicos no Windows (Program Files + ``~/Inkscape``).
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from idml_to_md.utils.subprocess_safe import BinaryNotFoundError, run, which

RASTER_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".webp"})
VECTOR_EXTENSIONS = frozenset({".ai", ".eps"})


# Caminhos comuns onde Inkscape pode estar instalado no Windows sem ir ao PATH.
def _candidate_inkscape_paths() -> Iterator[Path]:
    home = Path.home()
    program_files = Path("C:/Program Files")
    program_files_x86 = Path("C:/Program Files (x86)")
    for base in (home, program_files, program_files_x86):
        # Padrão usado pelo instalador Inno + PortableApps
        yield base / "Inkscape" / "bin" / "inkscape.exe"
        yield base / "Inkscape" / "PFiles64" / "Inkscape" / "bin" / "inkscape.exe"
        yield base / "Inkscape" / "inkscape.exe"


def resolve_inkscape_path(explicit: Path | None = None) -> Path | None:
    """Localiza o executável do Inkscape.

    Prioridade: explícito > env var > PATH > caminhos típicos do Windows.
    Retorna ``None`` se nada encontrado.
    """
    if explicit is not None:
        return explicit if explicit.exists() else None
    env = os.environ.get("IDML2MD_INKSCAPE_PATH")
    if env:
        env_path = Path(env)
        if env_path.exists():
            return env_path
    in_path = which("inkscape")
    if in_path is not None:
        return in_path
    for candidate in _candidate_inkscape_paths():
        if candidate.exists():
            return candidate
    return None


@dataclass(slots=True)
class AssetMap:
    """Mapeia ``basename original → caminho relativo dentro do output``."""

    output_relative: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    skipped_non_raster: list[str] = field(default_factory=list)
    vector_converted: list[str] = field(default_factory=list)
    vector_failed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Raster (cópia)
# ---------------------------------------------------------------------------


def process_raster_assets(
    requested_basenames: list[str],
    links_dir: Path,
    output_assets_dir: Path,
) -> AssetMap:
    """Copia imagens raster referenciadas para ``output_assets_dir``.

    Args:
        requested_basenames: nomes-base (sem path) que o story_walker viu
            via ``LinkResourceURI``.
        links_dir: pasta ``Links/`` do projeto editorial.
        output_assets_dir: destino (geralmente ``out/<book>/assets/img/``).

    Returns:
        ``AssetMap`` indicando para cada basename solicitado o caminho
        relativo dentro do output (ou ausência em ``missing``).
    """
    output_assets_dir.mkdir(parents=True, exist_ok=True)
    asset_map = AssetMap()
    hashes_seen: dict[str, str] = {}

    unique_requests = list(dict.fromkeys(requested_basenames))

    for basename in unique_requests:
        ext = Path(basename).suffix.lower()
        if ext not in RASTER_EXTENSIONS:
            asset_map.skipped_non_raster.append(basename)
            continue

        source = links_dir / basename
        if not source.exists():
            asset_map.missing.append(basename)
            continue

        digest = _sha1(source)
        if digest in hashes_seen:
            asset_map.output_relative[basename] = hashes_seen[digest]
            continue

        dest = output_assets_dir / basename
        if dest.exists() and _sha1(dest) != digest:
            dest = _disambiguate(output_assets_dir, basename)

        shutil.copyfile(source, dest)
        rel = f"assets/img/{dest.name}"
        asset_map.output_relative[basename] = rel
        hashes_seen[digest] = rel

    return asset_map


# ---------------------------------------------------------------------------
# Vector (.ai/.eps)
# ---------------------------------------------------------------------------


def process_vector_assets(
    requested_basenames: list[str],
    links_dir: Path,
    output_vector_dir: Path,
    *,
    inkscape_path: Path | None = None,
) -> AssetMap:
    """Converte ``.ai``/``.eps`` (não-MathType) → SVG via Inkscape.

    Fallback: PNG via Ghostscript se Inkscape falhar.

    Falhas silenciam (loga DEBUG) e ficam em ``vector_failed``.

    Args:
        inkscape_path: caminho explícito para ``inkscape.exe``. Se ``None``,
            tenta env var ``IDML2MD_INKSCAPE_PATH``, PATH, e caminhos típicos.
    """
    output_vector_dir.mkdir(parents=True, exist_ok=True)
    asset_map = AssetMap()
    inkscape_bin = resolve_inkscape_path(inkscape_path)
    if inkscape_bin is not None:
        logger.info("Inkscape: {}", inkscape_bin)
    else:
        logger.debug("Inkscape não encontrado; usando fallback Ghostscript")

    unique = list(dict.fromkeys(requested_basenames))
    for basename in unique:
        ext = Path(basename).suffix.lower()
        if ext not in VECTOR_EXTENSIONS:
            continue
        source = links_dir / basename
        if not source.exists():
            asset_map.missing.append(basename)
            continue

        target_svg = output_vector_dir / f"{Path(basename).stem}.svg"
        success = False
        if inkscape_bin is not None:
            success = _convert_with_inkscape(inkscape_bin, source, target_svg)

        if not success:
            target_png = output_vector_dir / f"{Path(basename).stem}.png"
            success_png = _convert_with_ghostscript(source, target_png)
            if success_png:
                asset_map.output_relative[basename] = f"assets/vector/{target_png.name}"
                asset_map.vector_converted.append(basename)
            else:
                asset_map.vector_failed.append(basename)
            continue

        asset_map.output_relative[basename] = f"assets/vector/{target_svg.name}"
        asset_map.vector_converted.append(basename)

    return asset_map


def _convert_with_inkscape(inkscape_bin: Path, source: Path, dest_svg: Path) -> bool:
    """Tenta converter via ``inkscape --export-type=svg``. Retorna True se OK."""
    try:
        result = run(
            [
                str(inkscape_bin),
                str(source),
                "--export-type=svg",
                f"--export-filename={dest_svg}",
            ],
            timeout=60.0,
        )
    except (BinaryNotFoundError, FileNotFoundError, OSError) as exc:
        logger.debug("Inkscape falhou em {}: {}", source.name, exc)
        return False
    except Exception as exc:
        logger.debug("Inkscape erro inesperado em {}: {}", source.name, exc)
        return False
    if result.returncode != 0 or not dest_svg.exists():
        logger.debug(
            "Inkscape retornou {} em {}: {}",
            result.returncode,
            source.name,
            result.stderr[:200],
        )
        return False
    return True


def _convert_with_ghostscript(source: Path, dest_png: Path) -> bool:
    """Fallback raster via Ghostscript (PNG @300dpi)."""
    try:
        result = run(
            [
                "gs",
                "-sDEVICE=png16m",
                "-r300",
                "-dEPSCrop",
                "-dNOPAUSE",
                "-dBATCH",
                "-dQUIET",
                f"-sOutputFile={dest_png}",
                str(source),
            ],
            timeout=30.0,
        )
    except (BinaryNotFoundError, FileNotFoundError, OSError) as exc:
        logger.debug("Ghostscript falhou em {}: {}", source.name, exc)
        return False
    except Exception as exc:
        logger.debug("Ghostscript erro inesperado em {}: {}", source.name, exc)
        return False
    return result.returncode == 0 and dest_png.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha1(path: Path) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _disambiguate(target_dir: Path, basename: str) -> Path:
    """Gera ``foo.jpg`` → ``foo_1.jpg`` se houver conflito."""
    stem = Path(basename).stem
    suffix = Path(basename).suffix
    n = 1
    while True:
        candidate = target_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1
