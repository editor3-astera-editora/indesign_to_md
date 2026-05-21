"""Leitura low-level do pacote IDML (ZIP de XMLs).

Expõe ``IDMLDocument`` com:
- ordered spreads (na ordem do designmap → ordem de página)
- acesso a Stories por id
- nomes de ParagraphStyle/CharacterStyle definidos

Usa ``zipfile`` + ``lxml`` diretamente para ter controle fino do parsing.
``simpleidml`` está na lista de dependências para uso futuro (helpers de
componentes mais ricos), mas a F1 não depende dele.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from urllib.parse import unquote

from lxml import etree

_SPREAD_SRC_RE = re.compile(r'src="(Spreads/Spread_[^"]+\.xml)"')


@dataclass(slots=True)
class TextFrameInfo:
    """Metadados de um TextFrame relevantes para reconstruir a ordem de leitura."""

    self_id: str
    parent_story: str
    previous_text_frame: str  # "n" ou "" quando raiz
    next_text_frame: str
    spread_index: int
    order_in_spread: int


class IDMLDocument:
    """Wrapper de um pacote .idml. Usar como context manager."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._zip = zipfile.ZipFile(self.path, "r")
        self._designmap: etree._Element | None = None
        self._styles_root: etree._Element | None = None

    # ---------------------------------------------------------------- lifecycle
    def __enter__(self) -> IDMLDocument:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._zip.close()

    # -------------------------------------------------------------------- core
    def _parse(self, member: str) -> etree._Element:
        with self._zip.open(member) as fh:
            return etree.parse(fh).getroot()

    def designmap(self) -> etree._Element:
        if self._designmap is None:
            self._designmap = self._parse("designmap.xml")
        return self._designmap

    def styles_root(self) -> etree._Element:
        if self._styles_root is None:
            self._styles_root = self._parse("Resources/Styles.xml")
        return self._styles_root

    # ------------------------------------------------------------- enumeration
    def spread_paths(self) -> list[str]:
        """Caminhos internos das Spreads na ordem do designmap (= ordem de página)."""
        # NB: usamos regex em vez de XPath porque preservar a ordem exata é
        # mais simples; lxml também preserva ordem, mas evita riscos com namespace.
        with self._zip.open("designmap.xml") as fh:
            text = fh.read().decode("utf-8")
        return _SPREAD_SRC_RE.findall(text)

    def story_paths(self) -> list[str]:
        """Caminhos internos das Stories, na ordem em que aparecem no designmap.

        Esta ordem NÃO é a ordem de leitura — é apenas a ordem em que o IDML
        registrou as Stories. A ordem de leitura é resolvida pelo ``thread_resolver``.
        """
        return [
            name
            for name in self._zip.namelist()
            if name.startswith("Stories/Story_") and name.endswith(".xml")
        ]

    def iter_spreads(self) -> Iterator[tuple[int, str, etree._Element]]:
        """Itera (index, path, root) das Spreads na ordem do designmap."""
        for idx, path in enumerate(self.spread_paths()):
            yield idx, path, self._parse(path)

    def get_story_root(self, story_id: str) -> etree._Element | None:
        """Obtém o root XML de uma Story pelo id (``u1f81d``).

        Retorna ``None`` se não existir (algumas refs em designmap podem
        apontar para Stories que foram removidas).
        """
        member = f"Stories/Story_{story_id}.xml"
        if member not in self._zip.namelist():
            return None
        return self._parse(member)

    # ------------------------------------------------------------------ styles
    def paragraph_style_names(self) -> list[str]:
        """Nomes (já decoded) dos ParagraphStyles definidos no IDML."""
        return self._extract_style_names("ParagraphStyle")

    def character_style_names(self) -> list[str]:
        """Nomes (já decoded) dos CharacterStyles definidos no IDML."""
        return self._extract_style_names("CharacterStyle")

    def _extract_style_names(self, tag: str) -> list[str]:
        root = self.styles_root()
        names: list[str] = []
        for el in root.iter(tag):
            self_id = el.get("Self") or ""
            # Self é tipo "ParagraphStyle/Títulos%3aT1" → tudo após primeiro "/"
            _, _, raw = self_id.partition("/")
            names.append(unquote(raw))
        return names

    # ------------------------------------------------------------- text frames
    def iter_text_frames(self) -> Iterator[TextFrameInfo]:
        """Itera TODOS os TextFrames de TODAS as Spreads, em ordem de página.

        Inclui ``spread_index`` (página) e ``order_in_spread`` para uso em
        heurísticas geométricas de fallback no ``thread_resolver``.
        """
        for idx, _path, root in self.iter_spreads():
            for order, tf in enumerate(root.iter("TextFrame")):
                yield TextFrameInfo(
                    self_id=tf.get("Self") or "",
                    parent_story=tf.get("ParentStory") or "",
                    previous_text_frame=tf.get("PreviousTextFrame") or "n",
                    next_text_frame=tf.get("NextTextFrame") or "n",
                    spread_index=idx,
                    order_in_spread=order,
                )
