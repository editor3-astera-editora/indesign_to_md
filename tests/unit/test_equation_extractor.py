"""Testes do ``equation_extractor``."""

from __future__ import annotations

from pathlib import Path

import pytest

from idml_to_md.equation_extractor import (
    EquationExtractionError,
    _extract_from_text,
    extract_mathml,
)

# Conteúdo sintético cobrindo todos os bugs conhecidos do MathType.
EPS_OK_BUGGY = (
    "%!PS-Adobe-3.0 EPSF-3.0\n"
    "%%Creator: MathType\n"
    "%MathType!MathML!1!1!+-\n"
    '%<?xmlversion="1.0"?>\n'
    "%<!--MathType@Translator@5@5@MathML2.tdl@-->\n"
    "%<mathxmlns='http://www.w3.org/1998/Math/MathML'>\n"
    "%<mrow><mfrac><mi>a</mi><mi>b</mi></mfrac></mrow></math>\n"
    "%<!--MathType@End@5@5@-->!\n"
)

EPS_DISPLAY_GLUED = (
    "%!PS\n"
    "%MathType!MathML!1!1!+-\n"
    "%<mathdisplay='block'xmlns='http://www.w3.org/1998/Math/MathML'>\n"
    "%<mrow><mn>1</mn></mrow></math>\n"
)

EPS_MFENCED_BUG = (
    "%!PS\n"
    "%MathType!MathML!1!1!+-\n"
    "%<mathxmlns='http://www.w3.org/1998/Math/MathML'>\n"
    "%<mrow><mfencedclose=']'open='['><mn>1</mn></mfenced></mrow></math>\n"
)

EPS_NO_MATHTYPE = "%!PS-Adobe-3.0 EPSF-3.0\n%%Creator: Adobe Illustrator\nq\n"

EPS_MTEF_ONLY = "%!PS\n%%Creator: MathType\n%MathType!MTEF!1!1!+-\n%feaahyart...\n"


@pytest.fixture
def eps_path(tmp_path: Path) -> Path:
    p = tmp_path / "eq.eps"
    p.write_text(EPS_OK_BUGGY, encoding="latin-1")
    return p


class TestExtractMathML:
    def test_extracts_clean_mathml(self, eps_path: Path) -> None:
        result = extract_mathml(eps_path)
        assert "<math" in result.mathml
        assert "</math>" in result.mathml
        # Bugs corrigidos
        assert "<?xmlversion" not in result.mathml
        assert "<mathxmlns" not in result.mathml
        # Xmlns normalizado
        assert 'xmlns="http://www.w3.org/1998/Math/MathML"' in result.mathml

    def test_extract_preserves_content(self, eps_path: Path) -> None:
        result = extract_mathml(eps_path)
        assert "<mfrac>" in result.mathml
        assert "<mi>a</mi>" in result.mathml


class TestNormalizations:
    def test_display_attr_glued(self, tmp_path: Path) -> None:
        p = tmp_path / "x.eps"
        p.write_text(EPS_DISPLAY_GLUED, encoding="latin-1")
        result = extract_mathml(p)
        # <mathdisplay='block'xmlns="..."> deve ter virado <math display="block" xmlns="...">
        assert "<math display" in result.mathml
        assert " xmlns=" in result.mathml

    def test_mfenced_attrs_glued(self, tmp_path: Path) -> None:
        p = tmp_path / "x.eps"
        p.write_text(EPS_MFENCED_BUG, encoding="latin-1")
        result = extract_mathml(p)
        assert "<mfenced " in result.mathml
        assert "open=" in result.mathml
        assert "close=" in result.mathml
        # Os atributos não estão mais colados
        assert "mfencedclose" not in result.mathml


class TestErrors:
    def test_no_mathtype_marker_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "x.eps"
        p.write_text(EPS_NO_MATHTYPE, encoding="latin-1")
        with pytest.raises(EquationExtractionError, match="sem marcador MathType"):
            extract_mathml(p)

    def test_mtef_without_mathml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "x.eps"
        p.write_text(EPS_MTEF_ONLY, encoding="latin-1")
        with pytest.raises(EquationExtractionError, match="MTEF"):
            extract_mathml(p)

    def test_block_without_math_element_raises(self, tmp_path: Path) -> None:
        # Tem cabeçalho mas o bloco não contém <math>
        bad = "%MathType!MathML!1!1!+-\n%no math here\n%just comments\n"
        with pytest.raises(EquationExtractionError):
            _extract_from_text(bad, source=tmp_path / "x.eps")


class TestRealFile:
    """Garante que o extractor funciona em pelo menos um EPS real, se disponível."""

    def test_real_eqn001_if_present(self, real_idml_path: Path) -> None:
        links = real_idml_path.parent / "Links"
        target = links / "81_MF_Eqn001.eps"
        if not target.exists():
            pytest.skip("EPS real ausente")
        result = extract_mathml(target)
        assert "<mfrac>" in result.mathml
