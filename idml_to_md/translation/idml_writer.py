"""Escreve um IDML traduzido a partir do original + translations.

Estratégia:

1. Lê o IDML original como ZIP.
2. Para cada Story que tenha pelo menos 1 Translation: parseia o XML,
   localiza ``ParagraphStyleRange`` pelo índice ordinal, substitui o texto
   nos ``<Content>`` filhos dos ``<CharacterStyleRange>`` correspondentes.
3. Reescreve o ZIP IDML preservando a ordem de membros exigida pelo formato
   (``mimetype`` deve ser o PRIMEIRO membro, sem compressão).
4. Opcionalmente, salva os XMLs traduzidos em ``out/<book>/xml_traduzido/``
   para auditoria (espelho de ``xml_original/`` gerado pelo extractor).

Garantias:
- IDs ``Self`` dos elementos NÃO são alterados — InDesign valida.
- Atributos dos CSR/PSR NÃO são alterados — só o ``text`` de ``<Content>``.
- Cada ``<Content>`` recebe o texto do seu run correspondente, endereçado por
  ``(índice do CSR, índice do Content)``. ``<Br/>`` e objetos ancorados ficam
  intactos — só o ``text`` dos ``<Content>`` é alterado. Isso preserva quebras
  de linha, listas e fórmulas inline na posição original.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path

from loguru import logger
from lxml import etree

from idml_to_md.translation.models import Segment, Translation
from idml_to_md.utils.xml import iter_csr_text_nodes

# Regex para normalizar serialização do lxml ao formato que o InDesign aceita:
#   <Tag attr=".."/>  →  <Tag attr=".." />   (espaço antes de />)
# Lookbehind: casa todo "/>" que NÃO é precedido por espaço.
_SELF_CLOSING_RE = re.compile(rb"(?<!\s)/>")


def write_translated_idml(
    source_idml: Path,
    target_idml: Path,
    segments: list[Segment],
    translations: list[Translation],
    *,
    xml_dump_dir: Path | None = None,
) -> dict[str, int]:
    """Cria o IDML traduzido.

    Args:
        source_idml: caminho do .idml original.
        target_idml: caminho do .idml a gerar.
        segments: todos os segmentos extraídos (inclusive os skipped).
        translations: traduções produzidas pelo OpenAI client.
        xml_dump_dir: se fornecido, salva uma cópia dos Stories XML modificados
            (com o texto traduzido) para auditoria lado a lado com o original.

    Returns:
        Estatísticas: ``{"stories_modified": N, "contents_replaced": M}``.
    """
    by_id = {t.segment_id: t for t in translations}
    # Agrupa segmentos por story_id para minimizar parses
    by_story: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        by_story[seg.story_id].append(seg)

    if xml_dump_dir is not None:
        xml_dump_dir.mkdir(parents=True, exist_ok=True)

    stories_modified = 0
    contents_replaced = 0

    # Lê todos os membros do ZIP original
    with zipfile.ZipFile(source_idml, "r") as zin:
        members = zin.namelist()
        member_set = set(members)
        # Cria pasta temporária com nomes determinísticos
        story_xml_translated: dict[str, bytes] = {}

        for story_id, story_segments in by_story.items():
            member = f"Stories/Story_{story_id}.xml"
            if member not in member_set:
                logger.warning("Story XML não encontrada no IDML: {}", member)
                continue

            with zin.open(member) as fh:
                xml_bytes = fh.read()

            new_xml, replaced = _apply_translations_to_story(
                xml_bytes, story_segments, by_id
            )

            if replaced > 0:
                story_xml_translated[member] = new_xml
                stories_modified += 1
                contents_replaced += replaced

                if xml_dump_dir is not None:
                    (xml_dump_dir / f"Story_{story_id}.xml").write_bytes(new_xml)

    # Escreve o IDML novo (recriando o ZIP)
    _write_idml_zip(source_idml, target_idml, story_xml_translated)

    logger.info(
        "IDML traduzido gravado em {} (stories={}, contents={})",
        target_idml,
        stories_modified,
        contents_replaced,
    )
    return {"stories_modified": stories_modified, "contents_replaced": contents_replaced}


def _apply_translations_to_story(
    xml_bytes: bytes,
    segments: list[Segment],
    translations_by_id: dict[str, Translation],
) -> tuple[bytes, int]:
    """Aplica todas as traduções relevantes a uma única Story XML.

    Retorna ``(novo_xml_bytes, n_contents_replaced)``.
    """
    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    root = etree.fromstring(xml_bytes, parser=parser)
    story = root.find(".//Story")
    if story is None:
        return xml_bytes, 0

    psrs = story.findall("ParagraphStyleRange")
    replaced = 0

    for seg in segments:
        translation = translations_by_id.get(seg.segment_id)
        if translation is None or seg.skip:
            continue
        psr = _locate_psr(story, psrs, seg)
        if psr is None:
            continue
        replaced += _replace_runs_in_psr(psr, translation)

    new_xml = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )
    new_xml = _normalize_to_indesign_style(new_xml)
    return new_xml, replaced


def _normalize_to_indesign_style(xml: bytes) -> bytes:
    """Ajusta a serialização do lxml para casar com o estilo do Adobe InDesign.

    Diferenças que o InDesign rejeita silenciosamente ao abrir o IDML:

    1. lxml usa aspas simples no header XML; InDesign usa aspas duplas.
    2. lxml serializa tags vazias como ``<Tag attr=".."/>``; InDesign usa
       ``<Tag attr=".." />`` (com espaço antes do "/").

    Esta normalização é PURAMENTE sintática — não muda nenhuma estrutura.
    """
    # 1. Header XML
    if xml.startswith(b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"):
        xml = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + xml[len(b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>") :]
        )

    # 2. Self-closing tags
    xml = _SELF_CLOSING_RE.sub(rb" />", xml)
    return xml


def _locate_psr(
    story: etree._Element,
    top_psrs: list[etree._Element],
    seg: Segment,
) -> etree._Element | None:
    """Localiza o ``ParagraphStyleRange`` alvo de um segmento.

    Parágrafos de célula são endereçados pelo ``Self`` da ``<Cell>`` (único) e
    pelo índice do PSR dentro dela. Parágrafos de topo, pelo índice ordinal.
    Retorna ``None`` (com aviso) quando o alvo não existe.
    """
    if seg.cell_self:
        cell = story.find(f".//Cell[@Self='{seg.cell_self}']")
        if cell is None:
            logger.warning("Cell não encontrada no IDML: {}", seg.cell_self)
            return None
        cell_psrs = cell.findall("ParagraphStyleRange")
        if seg.paragraph_idx >= len(cell_psrs):
            logger.warning(
                "paragraph_idx {} fora do range na célula {} (psrs={})",
                seg.paragraph_idx,
                seg.cell_self,
                len(cell_psrs),
            )
            return None
        return cell_psrs[seg.paragraph_idx]

    if seg.paragraph_idx >= len(top_psrs):
        logger.warning(
            "paragraph_idx {} fora do range para Story (psrs={})",
            seg.paragraph_idx,
            len(top_psrs),
        )
        return None
    return top_psrs[seg.paragraph_idx]


def _replace_runs_in_psr(
    psr: etree._Element,
    translation: Translation,
) -> int:
    """Substitui o texto de cada ``<Content>`` pelo run correspondente.

    Endereçamento POSICIONAL por ``(run_idx=índice do CSR, content_idx=índice do
    Content)``. Usa :func:`iter_csr_text_nodes` (mesma travessia do extractor) —
    inclusive descendo em ``HyperlinkTextSource`` (texto de sumário/hyperlinks).
    Cada ``<Content>`` é escrito individualmente; ``<Br/>`` e objetos ancorados
    ficam intactos, preservando quebras, listas e fórmulas inline.
    """
    if not translation.target_runs:
        return 0

    text_by_slot: dict[tuple[int, int], str] = {
        (run.run_idx, run.content_idx): run.text for run in translation.target_runs
    }

    replaced = 0
    for csr_idx, csr in enumerate(psr.findall("CharacterStyleRange")):
        content_idx = 0
        for kind, el in iter_csr_text_nodes(csr):
            if kind != "content":
                continue
            new_text = text_by_slot.get((csr_idx, content_idx))
            if new_text is not None:
                el.text = new_text
                replaced += 1
            content_idx += 1

    return replaced


def _write_idml_zip(
    source_idml: Path,
    target_idml: Path,
    overrides: dict[str, bytes],
) -> None:
    """Recria o ZIP IDML mantendo a ordem original dos membros.

    IDML é um pacote OCF-like:
    - ``mimetype`` deve ser o PRIMEIRO membro
    - ``mimetype`` deve estar STORED (sem compressão), sem nenhum extra header
    - Demais membros podem ser DEFLATE
    """
    target_idml.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source_idml, "r") as zin, zipfile.ZipFile(
        target_idml, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        members = zin.namelist()

        # Garante que mimetype, se existir, seja o primeiro
        ordered = sorted(members, key=lambda m: (0 if m == "mimetype" else 1, members.index(m)))
        # NB: members já está na ordem original do zip; este sort estável só
        # promove "mimetype" para o início.

        for member in ordered:
            data = overrides.get(member)
            if data is None:
                data = zin.read(member)

            if member == "mimetype":
                # STORED, sem compressão
                info = zipfile.ZipInfo(member)
                info.compress_type = zipfile.ZIP_STORED
                zout.writestr(info, data)
            else:
                zout.writestr(member, data)


def copy_xml_original(
    source_idml: Path,
    dump_dir: Path,
) -> int:
    """Conveniência: copia TODOS os Stories XML do IDML para ``dump_dir``.

    Usado quando o caller quer salvar o XML original mesmo se nenhuma Story
    foi extraída (segment_extractor já dá conta no fluxo normal).
    """
    dump_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(source_idml, "r") as zf:
        for member in zf.namelist():
            if not member.startswith("Stories/Story_"):
                continue
            target = dump_dir / Path(member).name
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count
