"""Extrai MathML embutido nos comentários PostScript dos EPS gerados pela MathType.

Cada EPS produzido pela MathType carrega, antes do PostScript de renderização,
um bloco de comentários como:

::

    %MathType!MTEF!1!1!+-
    %feaahyart1ev3aqatCvAUfeBSjuyZ ... (MTEF codificado)
    %MathType!MathML!1!1!+-
    %<?xmlversion="1.0"?><!--MathType@Translator@5@5@MathML2(Clipboard).tdl ...
    %<mathxmlns='http://www.w3.org/1998/Math/MathML'><mrow>...
    %<--MathType@End@5@5@-->!

O bloco MathML está em texto simples — basta:

1. Localizar `%MathType!MathML!...!+-` como marcador de início;
2. Concatenar as linhas subsequentes que começam com `%` (decapando o ``%``);
3. Recortar a substring entre ``<math`` e ``</math>``;
4. Normalizar bugs conhecidos do MathType (atributos colados sem espaço:
   ``mathxmlns``, ``mathdisplay``, ``mostretchy``, ``munderaccentunder``).

Este módulo NÃO depende de Saxon nem de qualquer subprocess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Início do bloco de comentários MathML; consome até a quebra de linha.
_BLOCK_HEADER_RE = re.compile(r"%MathType!MathML![^\n]*\n")

# Bugs conhecidos do MathType: atributos sem espaço de separação após o nome do
# elemento. Cada par (incorreto, correto). A ordem importa para evitar
# substituições parciais.
_BUGGY_ATTRS: tuple[tuple[str, str], ...] = (
    ("<?xmlversion", "<?xml version"),
    ("<mathxmlns", "<math xmlns"),
    ("<mathdisplay", "<math display"),
    ("<mostretchy", "<mo stretchy"),
    ("<munderaccentunder", "<munder accentunder"),
    ("<moverlace", "<mover lace"),
    ("<mfencedclose", "<mfenced close"),
    ("<mfencedopen", "<mfenced open"),
    ("<mfencedseparators", "<mfenced separators"),
)

# Captura "<tag attr='v'attr2=" (sem espaço) e força um espaço.
# Cobre padrões genéricos como ``display='block'xmlns="..."`` que aparecem
# quando o MathType colou dois atributos.
_GLUED_ATTRS_RE = re.compile(r'(["\'])([a-zA-Z_][\w:-]*=)')


@dataclass(slots=True, frozen=True)
class ExtractedMathML:
    """Resultado da extração."""

    mathml: str
    source_eps: Path
    has_mtef_only: bool = False  # True quando achamos MTEF mas não MathML


class EquationExtractionError(Exception):
    """Lançada quando o EPS não pôde ter MathML extraído.

    Casos cobertos:
    - EPS sem marcador ``%MathType!``
    - EPS com marcador MTEF mas sem MathML (raro)
    - Bloco MathML truncado ou malformado
    """


def extract_mathml(eps_path: Path) -> ExtractedMathML:
    """Extrai e normaliza o MathML embutido em ``eps_path``.

    Lê em ``latin-1`` (PostScript é byte-safe; o MathML é ASCII puro).
    """
    text = eps_path.read_text(encoding="latin-1", errors="ignore")
    return _extract_from_text(text, source=eps_path)


def _extract_from_text(text: str, source: Path) -> ExtractedMathML:
    """Versão pura para testes — recebe o conteúdo já lido."""
    if "MathType" not in text:
        raise EquationExtractionError(f"{source.name}: sem marcador MathType")

    block = _capture_comment_block(text)
    if block is None:
        # MTEF sem MathML? Acontece em EPS muito antigos
        if "MathType!MTEF!" in text:
            raise EquationExtractionError(f"{source.name}: contém MTEF mas não MathML embutido")
        raise EquationExtractionError(f"{source.name}: bloco MathML não encontrado")

    mathml = _isolate_math_element(block)
    if mathml is None:
        raise EquationExtractionError(f"{source.name}: <math>...</math> não localizado")

    return ExtractedMathML(mathml=_normalize(mathml), source_eps=source)


def _capture_comment_block(text: str) -> str | None:
    """Encontra o início do bloco MathML e concatena as linhas ``%...``."""
    match = _BLOCK_HEADER_RE.search(text)
    if match is None:
        return None
    start = match.end()
    out: list[str] = []
    for raw in text[start:].splitlines():
        if not raw.startswith("%"):
            break
        out.append(raw[1:])  # decapa o '%'
    if not out:
        return None
    return "".join(out)


def _isolate_math_element(decapped: str) -> str | None:
    """Recorta a substring de ``<math`` até ``</math>`` inclusivo.

    Necessário antes da normalização porque ``<mathxmlns`` (com bug) precisa
    casar com ``<math`` também — fazemos isso aplicando a correção primeiro
    no campo bruto e depois recortando.
    """
    # Normaliza só os bugs de abertura do <math/<? para o recorte funcionar.
    fixed_for_search = decapped.replace("<mathxmlns", "<math xmlns").replace(
        "<mathdisplay", "<math display"
    )
    start = fixed_for_search.find("<math")
    end = fixed_for_search.find("</math>")
    if start == -1 or end == -1:
        return None
    return fixed_for_search[start : end + len("</math>")]


def _normalize(mathml: str) -> str:
    """Aplica TODAS as correções de bugs do MathType + minúsculos ajustes XML."""
    out = mathml
    for bad, good in _BUGGY_ATTRS:
        out = out.replace(bad, good)
    # Insere espaço entre atributos colados (display='block'xmlns="...")
    out = _GLUED_ATTRS_RE.sub(r"\1 \2", out)
    # Aspas simples em xmlns viram aspas duplas (lxml tolera, mas padroniza)
    out = out.replace(
        "xmlns='http://www.w3.org/1998/Math/MathML'",
        'xmlns="http://www.w3.org/1998/Math/MathML"',
    )
    return out.strip()
