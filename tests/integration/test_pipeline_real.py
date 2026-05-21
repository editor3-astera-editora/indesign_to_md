"""Conversão end-to-end do livro real ``81_Matemática Financeira.idml``.

Marcado ``@integration`` — não roda no loop local rápido; entra no CI numa
job dedicada (e exige que ``Indesign_exemplos/`` esteja presente).

Validações são estruturais (não comparam conteúdo palavra-a-palavra), e
servem como guarda contra regressões grosseiras quando refatoramos o
parser ou o renderer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from idml_to_md.pipeline import convert_idml

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def converted(tmp_path_factory: pytest.TempPathFactory, real_idml_path: Path):  # type: ignore[no-untyped-def]
    if not real_idml_path.exists():
        pytest.skip(f"IDML real ausente: {real_idml_path}")
    out = tmp_path_factory.mktemp("out_real")
    return convert_idml(real_idml_path, out)


class TestConvertedArtifacts:
    def test_markdown_file_exists(self, converted) -> None:  # type: ignore[no-untyped-def]
        assert converted.markdown_path.exists()
        assert converted.markdown_path.stat().st_size > 50_000  # >50KB é razoável

    def test_report_file_valid_json(self, converted) -> None:  # type: ignore[no-untyped-def]
        data = json.loads(converted.report_path.read_text(encoding="utf-8"))
        assert data["book_slug"] == "81-matematica-financeira"
        # Em F1 o título vem do filename
        assert "Matemática Financeira" in data["book_title"]

    def test_assets_copied(self, converted) -> None:  # type: ignore[no-untyped-def]
        assets = converted.output_dir / "assets" / "img"
        assert assets.is_dir()
        # Pelo menos uma JPG copiada
        jpgs = list(assets.glob("*.jpg"))
        assert len(jpgs) >= 1


class TestMarkdownStructure:
    @pytest.fixture
    def md(self, converted) -> str:  # type: ignore[no-untyped-def]
        return converted.markdown_path.read_text(encoding="utf-8")

    def test_starts_with_h1(self, md: str) -> None:
        assert md.lstrip().startswith("# 81 Matemática Financeira")

    def test_has_toc(self, md: str) -> None:
        assert "## Sumário" in md

    def test_has_chapter_headings(self, md: str) -> None:
        # Capítulos do livro detectados via inspeção prévia do IDML
        assert "# Introdução" in md or "Introdução" in md
        # Pelo menos um capítulo de matéria
        assert "# Operações Fundamentais" in md or "Operações Fundamentais" in md

    def test_has_admonition(self, md: str) -> None:
        # "VOCÊ SABIA?" é a marca-d'água dos boxes do livro
        assert "> [!NOTE]" in md or "> [!TIP]" in md
        assert "VOCÊ SABIA?" in md

    def test_has_references_section(self, md: str) -> None:
        assert "## Referências" in md


class TestReportMetrics:
    @pytest.fixture
    def report(self, converted):  # type: ignore[no-untyped-def]
        return json.loads(converted.report_path.read_text(encoding="utf-8"))

    def test_no_unmapped_paragraph_styles_in_this_book(self, report) -> None:  # type: ignore[no-untyped-def]
        # O YAML default cobre TODOS os ParagraphStyles vistos neste livro.
        # Se cair, alguém adicionou ou renomeou estilo no IDML — atualize o YAML.
        assert report["unmapped_paragraph_styles"] == {}, (
            f"Estilos não mapeados: {report['unmapped_paragraph_styles']}"
        )

    def test_has_many_paragraphs(self, report) -> None:  # type: ignore[no-untyped-def]
        assert report["block_counts"].get("paragraph", 0) > 100

    def test_has_headings(self, report) -> None:  # type: ignore[no-untyped-def]
        assert report["block_counts"].get("heading", 0) > 20

    def test_equations_extracted(self, report) -> None:  # type: ignore[no-untyped-def]
        # F2: o livro de matemática financeira tem dezenas de equações.
        assert report["equations_total"] > 50, "esperava ≥50 equações totais"
        # Falhas devem ser somente EPS ilustrativos (não-MathType), com prefixo INOVA_.
        for failed in report["equations_failed"]:
            assert failed.startswith("INOVA_"), f"falha inesperada: {failed}"


class TestTablesAndVectors:
    """F3: tabelas detectadas e ilustrações vetoriais classificadas."""

    @pytest.fixture
    def report(self, converted):  # type: ignore[no-untyped-def]
        return json.loads(converted.report_path.read_text(encoding="utf-8"))

    @pytest.fixture
    def md(self, converted) -> str:  # type: ignore[no-untyped-def]
        return converted.markdown_path.read_text(encoding="utf-8")

    def test_tables_detected(self, report) -> None:  # type: ignore[no-untyped-def]
        # Livro de matemática financeira tem dezenas de tabelas
        assert report["block_counts"].get("table", 0) >= 5

    def test_md_contains_gfm_or_html_table(self, md: str) -> None:
        # Pelo menos uma tabela renderizada
        assert "| --- |" in md or "<table>" in md

    def test_no_eps_misclassified_as_failed_equation(self, report) -> None:  # type: ignore[no-untyped-def]
        # F3: EPS sem marcador MathType viram vetoriais, NÃO equation failures
        assert report["equations_failed"] == [], (
            f"EPS sem MathType deveriam ser reclassificados: {report['equations_failed']}"
        )

    def test_vector_failures_only_for_missing_inkscape(self, report) -> None:  # type: ignore[no-untyped-def]
        # Em ambiente sem Inkscape, vector_failed lista os EPS/AI ilustrativos.
        # Em ambiente com Inkscape, esperamos vector_converted populated.
        total = len(report["vector_failed"]) + len(report["vector_converted"])
        # Há ao menos os 8 EPS sem MathType + alguns .ai = 9+
        assert total >= 8


class TestEquationsInMarkdown:
    @pytest.fixture
    def md(self, converted) -> str:  # type: ignore[no-untyped-def]
        return converted.markdown_path.read_text(encoding="utf-8")

    def test_has_display_equations(self, md: str) -> None:
        assert "$$\n" in md, "esperava ao menos uma equação display"

    def test_has_latex_macros(self, md: str) -> None:
        # Pelo menos uma fração ou raiz no corpo
        assert "\\frac" in md or "\\sqrt" in md

    def test_no_empty_display_blocks(self, md: str) -> None:
        # Pareia cada par de cercas `$$` (linhas próprias) e confere que o
        # conteúdo entre elas não é vazio.
        lines = md.splitlines()
        fence_indices = [i for i, ln in enumerate(lines) if ln.strip() == "$$"]
        assert len(fence_indices) % 2 == 0, "número ímpar de cercas $$"
        empties = []
        for open_idx, close_idx in zip(fence_indices[::2], fence_indices[1::2], strict=True):
            body = "\n".join(lines[open_idx + 1 : close_idx]).strip()
            if not body:
                empties.append(open_idx)
        assert not empties, f"blocos display vazios nas linhas: {empties[:10]}"
