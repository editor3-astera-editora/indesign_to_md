"""Testes do ``mathml_to_latex``."""

from __future__ import annotations

from pathlib import Path

import pytest

from idml_to_md.mathml_to_latex import (
    EquationConverter,
    MathMLConversionError,
    _translate_chars,
)


def mml(inner: str) -> str:
    return f'<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow>{inner}</mrow></math>'


@pytest.fixture
def conv() -> EquationConverter:
    return EquationConverter()


class TestSimpleElements:
    def test_mi_single_char(self, conv: EquationConverter) -> None:
        assert conv.convert(mml("<mi>x</mi>")) == "x"

    def test_mi_multi_char_wraps_mathrm(self, conv: EquationConverter) -> None:
        assert conv.convert(mml("<mi>sin</mi>")) == r"\mathrm{sin}"

    def test_mn_number(self, conv: EquationConverter) -> None:
        assert conv.convert(mml("<mn>42</mn>")) == "42"

    def test_mo_plus(self, conv: EquationConverter) -> None:
        assert conv.convert(mml("<mo>+</mo>")) == "+"

    def test_mtext_wraps_text(self, conv: EquationConverter) -> None:
        assert conv.convert(mml("<mtext>hello</mtext>")) == r"\text{hello}"

    def test_mtext_escapes_special(self, conv: EquationConverter) -> None:
        assert conv.convert(mml("<mtext>a%b</mtext>")) == r"\text{a\%b}"

    def test_mspace(self, conv: EquationConverter) -> None:
        assert conv.convert(mml("<mspace />")) == r"\,"


class TestFractions:
    def test_mfrac(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<mfrac><mn>1</mn><mn>2</mn></mfrac>"))
        assert out == r"\frac{1}{2}"

    def test_msqrt(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<msqrt><mn>2</mn></msqrt>"))
        assert out == r"\sqrt{2}"

    def test_mroot(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<mroot><mn>8</mn><mn>3</mn></mroot>"))
        assert out == r"\sqrt[3]{8}"


class TestScripts:
    def test_msup(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<msup><mi>x</mi><mn>2</mn></msup>"))
        assert out == "x^{2}"

    def test_msub(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<msub><mi>a</mi><mn>1</mn></msub>"))
        assert out == "a_{1}"

    def test_msubsup(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<msubsup><mi>x</mi><mn>1</mn><mn>2</mn></msubsup>"))
        assert out == "x_{1}^{2}"


class TestUnderOver:
    def test_munder(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<munder><mi>x</mi><mo>_</mo></munder>"))
        # _ é caractere especial — escapado em mo? mo retorna cru.
        assert out.startswith(r"\underset{")

    def test_mover(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<mover><mi>x</mi><mo>~</mo></mover>"))
        assert out.startswith(r"\overset{")

    def test_munderover(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<munderover><mi>x</mi><mn>0</mn><mn>1</mn></munderover>"))
        assert r"\overset{" in out and r"\underset{" in out


class TestFenced:
    def test_default_parens(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<mfenced><mi>x</mi></mfenced>"))
        assert out == r"\left(x\right)"

    def test_custom_brackets(self, conv: EquationConverter) -> None:
        out = conv.convert(mml('<mfenced open="[" close="]"><mi>x</mi></mfenced>'))
        assert out == r"\left[x\right]"

    def test_multiple_args_with_default_comma(self, conv: EquationConverter) -> None:
        out = conv.convert(mml("<mfenced><mi>x</mi><mi>y</mi></mfenced>"))
        assert out == r"\left(x,y\right)"


class TestTranslateChars:
    def test_operators_to_latex(self) -> None:
        assert _translate_chars("⋅") == r"\cdot"
        assert _translate_chars("×") == r"\times"
        assert _translate_chars("≥") == r"\geq"

    def test_greek_letters(self) -> None:
        assert _translate_chars("α") == r"\alpha"
        assert _translate_chars("Δ") == r"\Delta"

    def test_ascii_passthrough(self) -> None:
        assert _translate_chars("abc 123") == "abc 123"


class TestCache:
    def test_cache_hit_in_memory(self, conv: EquationConverter) -> None:
        s = mml("<mn>1</mn>")
        conv.convert(s)
        conv.convert(s)
        assert conv.stats.cache_hits == 1
        assert conv.stats.cache_misses == 1

    def test_cache_persists_to_disk(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        s = mml("<mn>2</mn>")
        c1 = EquationConverter(cache_dir=cache_dir)
        c1.convert(s)
        # Novo converter: deve achar no disco
        c2 = EquationConverter(cache_dir=cache_dir)
        c2.convert(s)
        assert c2.stats.cache_hits == 1
        assert c2.stats.cache_misses == 0


class TestErrors:
    def test_invalid_xml_raises(self, conv: EquationConverter) -> None:
        with pytest.raises(MathMLConversionError):
            conv.convert("<math><not-closed>")

    def test_stats_failures_increments(self, conv: EquationConverter) -> None:
        with pytest.raises(MathMLConversionError):
            conv.convert("<broken")
        assert conv.stats.failures == 1


# ---------------------------------------------------------------------------
# Word grouping (fix de F2.5)
# ---------------------------------------------------------------------------


class TestWordGrouping:
    def test_three_letter_word_groups_as_text(self, conv: EquationConverter) -> None:
        # "com" como <mi>c</mi><mi>o</mi><mi>m</mi> → \text{com}
        out = conv.convert(mml("<mi>c</mi><mi>o</mi><mi>m</mi>"))
        assert r"\text{com}" in out

    def test_two_letter_word_in_pt_list(self, conv: EquationConverter) -> None:
        # "ou" entre operadores → \text{ou}
        out = conv.convert(mml("<mi>o</mi><mi>u</mi>"))
        assert r"\text{ou}" in out

    def test_two_letters_not_word_kept_as_mathrm(self, conv: EquationConverter) -> None:
        # "FV" não está em palavras-pt → \mathrm{FV}
        out = conv.convert(mml("<mi>F</mi><mi>V</mi>"))
        assert r"\mathrm{FV}" in out

    def test_single_letter_stays_variable(self, conv: EquationConverter) -> None:
        # "J" isolado → variável (italic default)
        out = conv.convert(mml("<mi>J</mi>"))
        assert out == "J"

    def test_word_with_nbsp_separator_splits_tokens(self, conv: EquationConverter) -> None:
        # "J ou FV" via NBSP em mo. Cada token avaliado:
        # J → var; ou → \text{ou}; FV → \mathrm{FV}
        nbsp = "<mo> </mo>"
        inner = f"<mi>J</mi>{nbsp}<mi>o</mi><mi>u</mi>{nbsp}<mi>F</mi><mi>V</mi>"
        out = conv.convert(mml(inner))
        assert r"\text{ou}" in out
        assert r"\mathrm{FV}" in out
        # "J" preservado como variável
        assert "J" in out
        # Nenhum dos tokens absorvidos em palavra única
        assert "JouFV" not in out

    def test_accented_letters_in_word(self, conv: EquationConverter) -> None:
        # "número" tem 'ú' (acentuado) entre letras ASCII
        out = conv.convert(mml("<mi>n</mi><mi>ú</mi><mi>m</mi><mi>e</mi><mi>r</mi><mi>o</mi>"))
        assert r"\text{número}" in out

    def test_greek_letter_not_grouped(self, conv: EquationConverter) -> None:
        # \alpha não deve virar parte de palavra
        out = conv.convert(mml("<mi>α</mi><mi>β</mi>"))
        # Greek é variável; conversão deve ter \alpha e \beta separados
        assert r"\alpha" in out
        assert r"\beta" in out
        # nenhum \text{} criado
        assert r"\text{" not in out

    def test_repeated_same_letter_not_grouped(self, conv: EquationConverter) -> None:
        # "aaa" (3 letras iguais) → NÃO é palavra (heurística)
        out = conv.convert(mml("<mi>a</mi><mi>a</mi><mi>a</mi>"))
        assert r"\text{" not in out

    def test_consonants_only_not_grouped(self, conv: EquationConverter) -> None:
        # "xyz" sem vogal → NÃO é palavra
        out = conv.convert(mml("<mi>x</mi><mi>y</mi><mi>z</mi>"))
        assert r"\text{" not in out
