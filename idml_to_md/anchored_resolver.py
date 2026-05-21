"""Classifica AnchoredObjects (Group/Rectangle dentro de uma CharacterStyleRange).

Tipos possíveis em F2:

- ``image_raster``: ``Rectangle > Image > Link`` apontando para um arquivo raster
  (jpg/png/gif/tif). Já tratado em F1.
- ``equation_eps``: ``Rectangle > Image > Link`` apontando para um ``.eps``
  gerado pela MathType. Novo em F2.
- ``other``: tudo o mais (Polygon decorativo de boxes, ilustrações vetoriais
  sem texto, etc.). Pulamos silenciosamente em F2; F3 cobrirá.

A classificação NÃO faz I/O: opera só sobre o XML. A leitura do EPS para
extrair MathML acontece em ``equation_extractor``; o pipeline é responsável
por chamar ambos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import unquote

if TYPE_CHECKING:
    from lxml import etree


class AnchoredKind(StrEnum):
    IMAGE_RASTER = "image_raster"
    IMAGE_VECTOR = "image_vector"  # .ai/.eps ilustrativos (F3)
    EQUATION_EPS = "equation_eps"
    OTHER = "other"


_RASTER_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".webp"})
_VECTOR_EXTS = frozenset({".ai"})  # .eps é decidido pelo extractor (MathType vs ilustração)


@dataclass(slots=True, frozen=True)
class AnchoredInfo:
    """Resultado da classificação."""

    kind: AnchoredKind
    basename: str = ""  # apenas para image_raster e equation_eps


def classify_anchored(el: etree._Element) -> AnchoredInfo:
    """Inspeciona um elemento ``Group``/``Rectangle`` (ou seus descendentes).

    Procura pelo primeiro ``<Link LinkResourceURI=...>`` e decide com base na
    extensão do arquivo apontado. Ignora referências sem ``Links/`` no path
    (tipicamente assets embutidos).
    """
    for link in el.iter("Link"):
        uri = link.get("LinkResourceURI") or ""
        if not uri:
            continue
        basename = _basename_from_uri(uri)
        if not basename or basename.startswith("file:"):
            continue
        ext = os.path.splitext(basename)[1].lower()
        if ext in _RASTER_EXTS:
            return AnchoredInfo(kind=AnchoredKind.IMAGE_RASTER, basename=basename)
        if ext in _VECTOR_EXTS:
            return AnchoredInfo(kind=AnchoredKind.IMAGE_VECTOR, basename=basename)
        if ext == ".eps":
            return AnchoredInfo(kind=AnchoredKind.EQUATION_EPS, basename=basename)
    return AnchoredInfo(kind=AnchoredKind.OTHER)


def _basename_from_uri(uri: str) -> str:
    """``file:.../Links/INOVA_F009.jpg`` → ``INOVA_F009.jpg`` (URL-decoded)."""
    cleaned = uri.split("Links/", 1)[-1] if "Links/" in uri else uri.rsplit("/", 1)[-1]
    return unquote(cleaned).split("/")[-1]
