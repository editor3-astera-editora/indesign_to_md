"""Helpers de namespaces IDML para uso com ``lxml``.

Os prefixos abaixo são os declarados pelo InDesign nos arquivos IDML; expor
um mapping pronto evita repetir a string em cada XPath.
"""

from __future__ import annotations

from collections.abc import Iterator

from lxml import etree

IDML_NAMESPACES: dict[str, str] = {
    "idPkg": "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging",
    "aid": "http://ns.adobe.com/AdobeInDesign/4.0/",
    "aid5": "http://ns.adobe.com/AdobeInDesign/5.0/",
}

# Wrappers inline cujo ``<Content>`` faz parte do fluxo do parágrafo: âncoras de
# hyperlink / referência cruzada / entradas de sumário (TOC). Nesses casos o
# ``<Content>`` fica ANINHADO dentro do wrapper, não como filho direto do
# ``<CharacterStyleRange>``. Descer um nível neles é o que torna o texto visível.
INLINE_TEXT_WRAPPERS: frozenset[str] = frozenset(
    {"HyperlinkTextSource", "HyperlinkTextDestination"}
)


def iter_psr_csr_units(psr: etree._Element) -> Iterator[etree._Element]:
    """Itera as unidades "tipo ``CharacterStyleRange``" de um ``ParagraphStyleRange``.

    A InDesign grava texto de hyperlink / entrada de sumário em DUAS estruturas:

    1. **Normal:** o ``<CharacterStyleRange>`` é filho direto do PSR (e pode conter
       ``<HyperlinkTextSource>`` dentro). ``iter_csr_text_nodes`` desce no wrapper.
    2. **Invertida:** o ``<HyperlinkTextSource>``/``<HyperlinkTextDestination>`` é
       filho DIRETO do PSR e ENVOLVE os ``<CharacterStyleRange>`` (caso de algumas
       entradas de sumário). Os CSRs ficam dentro do wrapper.

    Esta função emite, em ordem de documento, o CSR a processar nos dois casos:
    para (2) desce no wrapper e emite cada CSR interno; se o wrapper segura
    ``<Content>`` direto (sem CSR interno), emite o próprio wrapper (aí o
    ``iter_csr_text_nodes`` lê o ``<Content>`` dele). Usar a MESMA travessia na
    leitura (``segment_extractor``) e na escrita (``idml_writer``) mantém o
    ``(run_idx, content_idx)`` alinhado no round-trip.

    Para parágrafos sem a estrutura invertida, o resultado é idêntico a
    ``psr.findall("CharacterStyleRange")`` (mesma ordem) — comportamento intacto.
    """
    for child in psr:
        tag = child.tag
        if not isinstance(tag, str):  # comentários/PIs do lxml
            continue
        if tag == "CharacterStyleRange":
            yield child
        elif tag in INLINE_TEXT_WRAPPERS:
            inner_csrs = [
                sub
                for sub in child
                if isinstance(sub.tag, str) and sub.tag == "CharacterStyleRange"
            ]
            if inner_csrs:
                yield from inner_csrs
            else:
                # Wrapper filho-direto segurando <Content> sem CSR interno.
                yield child


def iter_csr_text_nodes(csr: etree._Element) -> Iterator[tuple[str, etree._Element]]:
    """Itera os nós de texto de um ``<CharacterStyleRange>`` em ordem de documento.

    Emite ``("content", <Content>)`` e ``("br", <Br>)`` descendo UM nível nos
    wrappers inline (:data:`INLINE_TEXT_WRAPPERS`). Usar a mesma travessia no
    ``segment_extractor`` (leitura) e no ``idml_writer`` (escrita) garante que o
    ordinal ``content_idx`` do run case com o ``<Content>`` correto na volta —
    inclusive para texto dentro de ``HyperlinkTextSource`` (sumário/hyperlinks).
    """
    for child in csr:
        tag = child.tag
        if not isinstance(tag, str):  # comentários/PIs do lxml
            continue
        if tag == "Content":
            yield "content", child
        elif tag == "Br":
            yield "br", child
        elif tag in INLINE_TEXT_WRAPPERS:
            for sub in child:
                sub_tag = sub.tag
                if not isinstance(sub_tag, str):
                    continue
                if sub_tag == "Content":
                    yield "content", sub
                elif sub_tag == "Br":
                    yield "br", sub
