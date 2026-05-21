"""Converte MathML → LaTeX em Python puro, com cache.

Cobertura de elementos (suficiente para o corpus MathType deste pipeline):

- ``mi``, ``mn``, ``mo``, ``mtext``, ``mspace``
- ``mrow``, ``mfenced`` (parênteses padrão e custom ``open``/``close``)
- ``mfrac``, ``msqrt``, ``mroot``
- ``msup``, ``msub``, ``msubsup``
- ``munder``, ``mover``, ``munderover``
- ``mtable``, ``mtr``, ``mtd`` (rudimentar — usa ``\\begin{matrix}``)

Decisões de tradução:

- Operadores Unicode comuns (``⋅``, ``×``, ``±``, ``≤``, ``≥``, ``≠``, ``≈``,
  ``∑``, ``∏``, ``∫``, ``→``, ``∞``, ``√``, …) são mapeados para macros LaTeX.
- ``mfenced`` usa ``\\left(`` / ``\\right)`` (ou ``open``/``close``) para crescer
  automaticamente com o conteúdo.
- Caracteres ASCII de operador (``+``, ``-``, ``=``, ``*``, ``/``) saem como
  estão.

API:

    converter = EquationConverter()
    latex = converter.convert(mathml_str)

A instância mantém um cache em memória por SHA-1 do MathML. Cache em disco é
opcional via ``cache_dir`` no construtor.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# Tabelas de tradução
# ---------------------------------------------------------------------------

# Operadores Unicode → macro LaTeX. Cobre o set comum em livros didáticos.
_OPERATOR_MAP: dict[str, str] = {
    "±": r"\pm",
    "·": r"\cdot",
    "×": r"\times",
    "÷": r"\div",
    "∂": r"\partial",
    "−": "-",  # MINUS SIGN
    "∓": r"\mp",
    "∘": r"\circ",
    "∙": r"\bullet",
    "√": r"\sqrt{}",  # raramente como mo; msqrt cobre
    "∝": r"\propto",
    "∞": r"\infty",
    "∧": r"\land",
    "∨": r"\lor",
    "∩": r"\cap",
    "∪": r"\cup",
    "∫": r"\int",
    "∴": r"\therefore",
    "∵": r"\because",
    "≈": r"\approx",
    "≠": r"\neq",
    "≡": r"\equiv",
    "≤": r"\leq",
    "≥": r"\geq",
    "⊂": r"\subset",
    "⊃": r"\supset",
    "⊆": r"\subseteq",
    "⊇": r"\supseteq",
    "∈": r"\in",
    "∉": r"\notin",
    "∋": r"\ni",
    "∅": r"\emptyset",
    "∑": r"\sum",
    "∏": r"\prod",
    "→": r"\to",
    "←": r"\leftarrow",
    "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow",
    "⇔": r"\Leftrightarrow",
    "⋅": r"\cdot",  # DOT OPERATOR (mais comum em MathType)
    " ": " ",  # NBSP → espaço normal
    "\u200b": "",  # ZERO WIDTH SPACE
}

# Letras gregas (mi). Cobre as comuns; demais caem em fallback texto.
_GREEK_MAP: dict[str, str] = {
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "φ": r"\varphi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
}

# Caracteres LaTeX-especiais que precisam escape quando saem como texto.
_LATEX_ESCAPE_RE = re.compile(r"([&%$#_{}~^\\])")


def _escape_text(text: str) -> str:
    """Escapa o conteúdo de ``mtext`` para uso em modo matemático."""
    return _LATEX_ESCAPE_RE.sub(r"\\\1", text)


# Lista das macros LaTeX que ESTE conversor pode emitir. Usada para
# detectar "macro + letra colada" sem cair em backtracking ambíguo
# (``\cdot`` greedy encurtaria para ``\cdo`` se a regex aceitasse qualquer
# sequência de letras como nome de macro).
_KNOWN_MACROS: frozenset[str] = frozenset(
    {v.removeprefix("\\") for v in _OPERATOR_MAP.values() if v.startswith("\\")}
    | {v.removeprefix("\\") for v in _GREEK_MAP.values()}
)

_MACRO_LETTER_RE = re.compile(
    r"\\(" + "|".join(sorted(_KNOWN_MACROS, key=len, reverse=True)) + r")(?=[a-zA-Z])"
)


def _post_process(latex: str) -> str:
    """Pós-fixes finais sobre o LaTeX gerado.

    Insere espaço entre macros conhecidas (``\\cdot``, ``\\div``, ``\\alpha``…)
    e letras subsequentes para evitar interpretação como macro composta
    inexistente (``\\cdota`` → ``\\cdot a``).
    """
    return _MACRO_LETTER_RE.sub(r"\\\1 ", latex)


# ---------------------------------------------------------------------------
# Conversor
# ---------------------------------------------------------------------------


class MathMLConversionError(Exception):
    """MathML não pôde ser convertido (parsing failed ou elemento não suportado)."""


@dataclass(slots=True)
class _Stats:
    cache_hits: int = 0
    cache_misses: int = 0
    failures: int = 0


@dataclass(slots=True)
class EquationConverter:
    """Converter MathML → LaTeX com cache.

    Use ``convert(mathml_str)`` para obter o LaTeX. ``stats`` expõe métricas.
    """

    cache_dir: Path | None = None
    _memory_cache: dict[str, str] = field(default_factory=dict)
    stats: _Stats = field(default_factory=_Stats)

    def convert(self, mathml: str) -> str:
        """Converte MathML completo (``<math>...</math>``) para LaTeX.

        Resultado é o conteúdo "puro" (sem ``$...$`` em volta). Quem chama
        adiciona delimitadores conforme inline ou display.
        """
        key = hashlib.sha1(mathml.encode("utf-8"), usedforsecurity=False).hexdigest()

        cached = self._memory_cache.get(key)
        if cached is not None:
            self.stats.cache_hits += 1
            return cached

        disk_hit = self._read_disk(key)
        if disk_hit is not None:
            self.stats.cache_hits += 1
            self._memory_cache[key] = disk_hit
            return disk_hit

        try:
            latex = self._render(mathml).strip()
        except Exception as exc:
            self.stats.failures += 1
            raise MathMLConversionError(str(exc)) from exc

        self.stats.cache_misses += 1
        self._memory_cache[key] = latex
        self._write_disk(key, latex)
        return latex

    # -------------------------------------------------------------- internals
    def _render(self, mathml: str) -> str:
        try:
            root = etree.fromstring(mathml.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            raise MathMLConversionError(f"XML inválido: {exc}") from exc
        return _post_process(_render_element(root))

    def _disk_path(self, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{key}.tex"

    def _read_disk(self, key: str) -> str | None:
        path = self._disk_path(key)
        if path is None or not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _write_disk(self, key: str, latex: str) -> None:
        path = self._disk_path(key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(latex, encoding="utf-8")


# ---------------------------------------------------------------------------
# Render dispatch
# ---------------------------------------------------------------------------


def _local(tag: object) -> str:
    """Tag local sem namespace (``{ns}foo`` → ``foo``)."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


# Palavras curtas (2 letras) de português que NÃO devem ser tratadas como
# variáveis matemáticas. Para 3+ letras consecutivas usamos a heurística da
# vogal, mas 2 letras precisam estar nessa lista para evitar falso-positivo
# em expressões como ``ab`` (variáveis ``a`` e ``b``).
_TWO_LETTER_WORDS: frozenset[str] = frozenset(
    {"ou", "de", "da", "do", "na", "no", "em", "se", "ao", "às", "há"}
)

# Vogais (com acentos comuns) — heurística para detectar "palavra plausível".
_VOWELS: frozenset[str] = frozenset("aeiouáéíóúâêôãõàèìòù")


def _is_word_letter_mi(child: etree._Element) -> bool:
    """``<mi>X</mi>`` com X = letra latina single-char (não grega)."""
    if _local(child.tag) != "mi":
        return False
    text = (child.text or "").strip()
    if len(text) != 1:
        return False
    if text in _GREEK_MAP:
        return False
    return text.isalpha()


def _is_whitespace_element(child: etree._Element) -> bool:
    """``<mi> </mi>``, ``<mo>&#xa0;</mo>`` ou similares — separadores de palavras."""
    name = _local(child.tag)
    if name not in ("mi", "mo", "mtext"):
        return False
    text = child.text or ""
    if not text:
        return False
    # NBSP ( ), espaço, e outros whitespace
    return all(ch.isspace() or ch == " " for ch in text)


def _looks_like_word(letters: str) -> bool:
    """Heurística para decidir se uma sequência de letras é palavra natural.

    - 2 letras: precisa estar em ``_TWO_LETTER_WORDS``.
    - 3+ letras: precisa ter pelo menos uma vogal e não ser tudo a mesma letra.
    """
    clean = letters.replace(" ", "")
    if len(clean) < 2:
        return False
    if len(clean) == 2:
        return clean.lower() in _TWO_LETTER_WORDS
    if len(set(clean.lower())) == 1:
        return False
    return any(ch.lower() in _VOWELS for ch in clean)


def _process_letter_run(  # noqa: PLR0912
    children: list[etree._Element], start: int
) -> tuple[str, int] | None:
    """Coleta uma sequência de ``<mi>`` single-letter (com whitespaces internos)
    e a renderiza separando em **tokens** por whitespace.

    Cada token é classificado independentemente:

    - Token que ``_looks_like_word`` → ``\\text{token}``.
    - Token de 2+ letras NÃO-palavra (ex.: ``FV``, ``PV``) → ``\\mathrm{token}``.
    - Token de 1 letra → renderiza a letra como variável (itálico padrão).

    Isso evita absorver variáveis legítimas em runs de palavras adjacentes
    (``M=C+J ou FV=...`` mantém ``J``, ``FV`` como variáveis).

    Retorna ``(rendered_string, end_index)`` ou ``None`` se ``start`` não for
    um ``<mi>`` letter.
    """
    if start >= len(children) or not _is_word_letter_mi(children[start]):
        return None

    tokens: list[str] = []
    buf: list[str] = []
    i = start
    n = len(children)
    while i < n:
        child = children[i]
        if _is_word_letter_mi(child):
            buf.append((child.text or "").strip())
            i += 1
            continue
        if _is_whitespace_element(child):
            # Pula todos os whitespaces consecutivos
            j = i
            while j < n and _is_whitespace_element(children[j]):
                j += 1
            # Só considera "separador interno" se houver outra letra após
            if j < n and _is_word_letter_mi(children[j]):
                if buf:
                    tokens.append("".join(buf))
                    buf = []
                tokens.append(" ")
                i = j
                continue
            break
        break

    if buf:
        tokens.append("".join(buf))
    if not tokens:
        return None

    # Renderiza tokens
    out: list[str] = []
    pending_space = False
    for tok in tokens:
        if tok == " ":
            pending_space = True
            continue
        is_word = _looks_like_word(tok)
        if pending_space and out:
            out.append("\\,")
        if is_word:
            out.append(rf"\text{{{tok}}}")
        elif len(tok) >= 2:
            out.append(rf"\mathrm{{{tok}}}")
        else:
            out.append(tok)
        pending_space = False
    return "".join(out), i


def _render_children(el: etree._Element, sep: str = "") -> str:
    parts: list[str] = []
    if el.text:
        parts.append(_translate_chars(el.text))
    children = list(el)
    i = 0
    n = len(children)
    while i < n:
        # Tenta processar um run de letras-single (mi + whitespace)
        run = _process_letter_run(children, i)
        if run is not None:
            rendered, end_idx = run
            parts.append(rendered)
            tail = children[end_idx - 1].tail
            if tail:
                parts.append(_translate_chars(tail))
            i = end_idx
            continue

        child = children[i]
        # whitespace isolado (não dentro de run) → vira espaço LaTeX
        if _is_whitespace_element(child):
            parts.append("\\,")
            if child.tail:
                parts.append(_translate_chars(child.tail))
            i += 1
            continue

        parts.append(_render_element(child))
        if child.tail:
            parts.append(_translate_chars(child.tail))
        i += 1
    return sep.join(p for p in parts if p)


def _render_element(el: etree._Element) -> str:  # noqa: PLR0911, PLR0912
    name = _local(el.tag)
    if name == "math":
        return _render_children(el)
    if name in ("mrow", "mstyle", "mphantom", "merror"):
        return _render_children(el)
    if name == "mi":
        return _render_mi(el)
    if name == "mn":
        return (el.text or "").strip()
    if name == "mo":
        return _render_mo(el)
    if name in ("mtext", "ms"):
        text = (el.text or "").strip()
        return rf"\text{{{_escape_text(_translate_chars(text))}}}" if text else ""
    if name == "mspace":
        return r"\,"
    if name == "mfrac":
        return _render_mfrac(el)
    if name == "msqrt":
        return rf"\sqrt{{{_render_children(el)}}}"
    if name == "mroot":
        return _render_mroot(el)
    if name in ("msup", "msub", "msubsup"):
        return _render_scripts(el)
    if name in ("munder", "mover", "munderover"):
        return _render_under_over(el)
    if name == "mfenced":
        return _render_mfenced(el)
    if name == "mtable":
        return _render_mtable(el)
    if name in ("mtr", "mtd"):  # caem para _render_mtable normalmente
        return _render_children(el)
    if name == "mlabeledtr":
        return _render_children(el)
    # Fallback: ignora tag desconhecida mas processa filhos
    return _render_children(el)


# ---------------------------------------------------------------------------
# Element renderers
# ---------------------------------------------------------------------------


def _render_mi(el: etree._Element) -> str:
    raw = (el.text or "").strip()
    if not raw:
        return ""
    translated = _translate_chars(raw)
    # mi com 1 char é variável; multi-char vira \mathrm{}
    if len(raw) == 1:
        return translated
    return rf"\mathrm{{{translated}}}"


def _render_mo(el: etree._Element) -> str:
    raw = (el.text or "").strip()
    if not raw:
        return ""
    translated = _translate_chars(raw)
    return translated


def _render_mfrac(el: etree._Element) -> str:
    children = list(el)
    num = _render_element(children[0]) if len(children) > 0 else ""
    den = _render_element(children[1]) if len(children) > 1 else ""
    return rf"\frac{{{num}}}{{{den}}}"


def _render_mroot(el: etree._Element) -> str:
    children = list(el)
    base = _render_element(children[0]) if len(children) > 0 else ""
    idx = _render_element(children[1]) if len(children) > 1 else ""
    return rf"\sqrt[{idx}]{{{base}}}"


def _render_scripts(el: etree._Element) -> str:
    name = _local(el.tag)
    children = list(el)
    if not children:
        return ""
    base = _render_element(children[0])
    if name == "msup":
        sup = _render_element(children[1]) if len(children) > 1 else ""
        return f"{base}^{{{sup}}}"
    if name == "msub":
        sub = _render_element(children[1]) if len(children) > 1 else ""
        return f"{base}_{{{sub}}}"
    # msubsup
    sub = _render_element(children[1]) if len(children) > 1 else ""
    sup = _render_element(children[2]) if len(children) > 2 else ""
    return f"{base}_{{{sub}}}^{{{sup}}}"


def _render_under_over(el: etree._Element) -> str:
    name = _local(el.tag)
    children = list(el)
    if not children:
        return ""
    base = _render_element(children[0])
    if name == "munder":
        under = _render_element(children[1]) if len(children) > 1 else ""
        return rf"\underset{{{under}}}{{{base}}}"
    if name == "mover":
        over = _render_element(children[1]) if len(children) > 1 else ""
        return rf"\overset{{{over}}}{{{base}}}"
    # munderover
    under = _render_element(children[1]) if len(children) > 1 else ""
    over = _render_element(children[2]) if len(children) > 2 else ""
    return rf"\overset{{{over}}}{{\underset{{{under}}}{{{base}}}}}"


def _render_mfenced(el: etree._Element) -> str:
    open_ = el.get("open", "(")
    close = el.get("close", ")")
    sep = el.get("separators", ",")
    children = list(el)
    parts = [_render_element(c) for c in children]
    separated = _interleave(parts, list(sep) if sep else [","])
    inner = "".join(separated)
    return rf"\left{_fence_char(open_)}{inner}\right{_fence_char(close)}"


def _render_mtable(el: etree._Element) -> str:
    rows: list[str] = []
    for tr in el:
        if _local(tr.tag) not in ("mtr", "mlabeledtr"):
            continue
        cells = [_render_children(td) for td in tr if _local(td.tag) == "mtd"]
        rows.append(" & ".join(cells))
    body = " \\\\ ".join(rows)
    return rf"\begin{{matrix}} {body} \end{{matrix}}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fence_char(ch: str) -> str:
    """Converte fence-char para o que o LaTeX espera após ``\\left``/``\\right``."""
    if not ch:
        return "."
    if ch in {"{", "}"}:
        return "\\" + ch
    return ch


def _interleave(parts: list[str], seps: list[str]) -> list[str]:
    """``[a,b,c]`` + ``[,]`` → ``[a, ',', b, ',', c]``."""
    if not parts:
        return []
    out: list[str] = [parts[0]]
    for i, part in enumerate(parts[1:], start=1):
        sep = seps[i - 1] if i - 1 < len(seps) else seps[-1]
        out.append(sep)
        out.append(part)
    return out


def _translate_chars(text: str) -> str:
    """Traduz caracteres Unicode → macro LaTeX (operadores, letras gregas)."""
    out: list[str] = []
    for ch in text:
        if ch in _OPERATOR_MAP:
            out.append(_OPERATOR_MAP[ch])
        elif ch in _GREEK_MAP:
            out.append(_GREEK_MAP[ch])
        else:
            out.append(ch)
    return "".join(out)
