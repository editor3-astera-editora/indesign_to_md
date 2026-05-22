"""Testes dos helpers de travessia XML (idml_to_md/utils/xml.py)."""

from __future__ import annotations

from lxml import etree

from idml_to_md.utils.xml import iter_csr_text_nodes, iter_psr_csr_units


def _psr(inner: str) -> etree._Element:
    return etree.fromstring(
        '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/X">'
        f"{inner}</ParagraphStyleRange>"
    )


def test_units_normal_direct_csrs() -> None:
    psr = _psr(
        "<CharacterStyleRange><Content>A</Content></CharacterStyleRange>"
        "<CharacterStyleRange><Content>B</Content></CharacterStyleRange>"
    )
    units = list(iter_psr_csr_units(psr))
    # Idêntico a findall('CharacterStyleRange') quando não há estrutura invertida.
    assert units == psr.findall("CharacterStyleRange")
    assert [u.findtext("Content") for u in units] == ["A", "B"]


def test_units_inverted_wrapper_yields_inner_csrs() -> None:
    psr = _psr(
        "<CharacterStyleRange><Content>A</Content></CharacterStyleRange>"
        '<HyperlinkTextSource Self="h1"><Properties/>'
        "<CharacterStyleRange><Content>Mundo do </Content></CharacterStyleRange>"
        "<CharacterStyleRange><Content>trabalho</Content></CharacterStyleRange>"
        "</HyperlinkTextSource>"
    )
    units = list(iter_psr_csr_units(psr))
    assert [u.findtext("Content") for u in units] == ["A", "Mundo do ", "trabalho"]


def test_units_wrapper_with_direct_content_fallback() -> None:
    # Wrapper filho-direto SEM CSR interno (segura Content direto) → emite o
    # próprio wrapper; iter_csr_text_nodes lê o Content dele.
    psr = _psr(
        '<HyperlinkTextSource Self="h1"><Content>Direto\t9</Content></HyperlinkTextSource>'
    )
    units = list(iter_psr_csr_units(psr))
    assert len(units) == 1
    nodes = list(iter_csr_text_nodes(units[0]))
    assert [(k, e.text) for k, e in nodes] == [("content", "Direto\t9")]


def test_units_ignores_non_elements() -> None:
    psr = _psr(
        "<!-- comentário --><CharacterStyleRange><Content>A</Content></CharacterStyleRange>"
    )
    units = list(iter_psr_csr_units(psr))
    assert [u.findtext("Content") for u in units] == ["A"]
