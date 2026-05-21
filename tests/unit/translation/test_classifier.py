"""Testes do classifier."""

from __future__ import annotations

import pytest

from idml_to_md.translation.classifier import (
    _is_numeric_literal,
    _is_pure_symbols,
    _is_pure_variable,
    classify,
)
from idml_to_md.translation.models import Segment, SegmentRun, SkipReason


def _make_segment(text: str, *, kind: str = "paragraph", style: str = "Texto principal") -> Segment:
    return Segment(
        segment_id=f"u:{abs(hash(text)) % 1000}",
        story_id="u",
        paragraph_idx=0,
        paragraph_style=style,
        paragraph_kind=kind,
        runs=[SegmentRun(run_idx=0, content_idx=0, text=text)],
        plain_text=text,
    )


class TestPureSymbolsRegex:
    @pytest.mark.parametrize("text", ["123", "1+2=3", "   ", "===", "-+×"])
    def test_pure_symbols(self, text: str) -> None:
        assert _is_pure_symbols(text)

    @pytest.mark.parametrize("text", ["abc", "A1B2", "café", "R$ 500,00"])
    def test_has_letters(self, text: str) -> None:
        assert not _is_pure_symbols(text)


class TestNumericLiteralRegex:
    @pytest.mark.parametrize("text", ["1.234,56", "100%", "3.14", "R$ 1.500,00", "1/2"])
    def test_numeric(self, text: str) -> None:
        assert _is_numeric_literal(text)

    @pytest.mark.parametrize("text", ["abc", "100 reais"])
    def test_not_numeric(self, text: str) -> None:
        assert not _is_numeric_literal(text)


class TestPureVariableRegex:
    @pytest.mark.parametrize("text", ["M", "V", "VP", "C0", "i_n"])
    def test_variable(self, text: str) -> None:
        assert _is_pure_variable(text)

    @pytest.mark.parametrize("text", ["palavra", "ABCDE", "Juros"])
    def test_not_variable(self, text: str) -> None:
        assert not _is_pure_variable(text)


class TestClassify:
    def test_paragraph_kind_drop(self) -> None:
        seg = _make_segment("ignorar", kind="drop")
        seg.skip = False
        seg.skip_reason = SkipReason.NONE
        out = classify([seg])
        # 'drop' está em NON_TRANSLATABLE_KINDS — marca skip com reason apropriado
        assert out[0].skip
        assert out[0].skip_reason == SkipReason.PARAGRAPH_STYLE

    def test_code_block_skipped(self) -> None:
        seg = _make_segment("print('hello')", kind="code_block")
        out = classify([seg])
        assert out[0].skip
        assert out[0].skip_reason == SkipReason.CODE_BLOCK

    def test_brand_skipped(self) -> None:
        seg = _make_segment("InDesign")
        out = classify([seg], brand_names=["InDesign"])
        assert out[0].skip
        assert out[0].skip_reason == SkipReason.BRAND_OR_PROPER_NAME

    def test_numeric_skipped(self) -> None:
        seg = _make_segment("1.234,56")
        out = classify([seg])
        assert out[0].skip
        assert out[0].skip_reason == SkipReason.NUMERIC_LITERAL

    def test_pure_symbols_skipped(self) -> None:
        seg = _make_segment("M = C(1 + i)^n")
        out = classify([seg])
        # tem letras (M, C, i, n) então NÃO é pure_symbols
        # mas a string como um todo deve ser analisada — letras presentes => não simbólico
        assert not out[0].skip or out[0].skip_reason != SkipReason.PURE_SYMBOLS

    def test_variable_skipped(self) -> None:
        seg = _make_segment("V0")
        out = classify([seg])
        assert out[0].skip
        assert out[0].skip_reason == SkipReason.PURE_VARIABLE

    def test_normal_text_not_skipped(self) -> None:
        seg = _make_segment("Os juros simples são calculados sobre o capital.")
        out = classify([seg])
        assert not out[0].skip

    def test_extra_styles(self) -> None:
        seg = _make_segment("Crédito da imagem", style="Credito imagem")
        out = classify([seg], extra_non_translatable_styles=["Credito imagem"])
        assert out[0].skip
        assert out[0].skip_reason == SkipReason.PARAGRAPH_STYLE

    def test_table_caption_kind_translatable(self) -> None:
        # Cabeçalho de tabela (kind=caption) com texto real → traduzível
        seg = _make_segment("Parte inteira", kind="caption", style="Titulo - tabela")
        out = classify([seg])
        assert not out[0].skip

    def test_table_kind_no_longer_auto_skipped(self) -> None:
        # "table" saiu de NON_TRANSLATABLE_KINDS; texto real é traduzível
        seg = _make_segment("Total de vendas", kind="table")
        out = classify([seg])
        assert not out[0].skip

    def test_already_skipped_not_reclassified(self) -> None:
        seg = _make_segment("normal")
        seg.skip = True
        seg.skip_reason = SkipReason.EMPTY
        out = classify([seg])
        assert out[0].skip_reason == SkipReason.EMPTY
