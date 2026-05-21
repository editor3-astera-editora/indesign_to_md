"""Verifica se TUDO do IDML original está presente no IDML traduzido.

Auditoria puramente estrutural (independe da qualidade da tradução), pensada
como gate de QA antes de abrir o ``.idml`` traduzido no InDesign. Responde à
pergunta "tudo que está no XML original está no traduzido?" comparando:

1. Inventário do pacote ZIP (nº de entradas, ``Stories/*``, ``Spreads/*``).
2. Boa-formação de todo ``*.xml`` do traduzido.
3. IDs ``Self`` em correspondência 1:1 (nada perdido, duplicado ou extra).
4. Contagens estruturais por story (PSR/CSR/Content/Br + objetos ancorados).
5. Texto por parágrafo, alinhado 1:1: falha se um parágrafo tinha texto no
   original e ficou vazio no traduzido (detector primário de perda de conteúdo).
6. Volume total de texto (informativo; expansão PT→ES costuma ser > 1,0).

O ``idml_writer`` só altera o ``.text`` dos ``<Content>``; logo, qualquer
divergência nas checagens 1-4 indica corrupção, e a 5 pega perda real de texto.
Páginas em branco no PDF com este relatório ``ok=True`` apontam para
overset/layout no InDesign, não para perda de conteúdo.

Os elementos internos da Story (``ParagraphStyleRange``, ``Content``, ``Br`` …)
não têm namespace; por isso usamos ``Element.iter(tag)`` como o resto do pacote.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree

from idml_to_md.translation.models import CompletenessReport

# Tags contadas por story para detectar perda estrutural. Namespace-agnóstico
# (comparado via ``local-name()``). Inclui runs de texto, quebras e os objetos
# que podem aparecer ancorados/inline dentro de uma Story.
_COUNTED_TAGS: tuple[str, ...] = (
    "ParagraphStyleRange",
    "CharacterStyleRange",
    "Content",
    "Br",
    "Rectangle",
    "TextFrame",
    "Polygon",
    "GraphicLine",
    "Group",
    "Image",
    "Table",
    "Cell",
)

_SELF_RE = re.compile(rb'\sSelf="([^"]+)"')


def check_completeness(source_idml: Path, translated_idml: Path) -> CompletenessReport:
    """Compara original vs traduzido e devolve um ``CompletenessReport``.

    Não levanta exceção por divergência de conteúdo — registra tudo no relatório
    e marca ``ok=False``. Levanta apenas se um dos arquivos não for um ZIP/IDML
    válido (erro de uso, não de conteúdo).
    """
    with zipfile.ZipFile(source_idml, "r") as zsrc, zipfile.ZipFile(
        translated_idml, "r"
    ) as ztrad:
        src_names = zsrc.namelist()
        trad_names = ztrad.namelist()

        report = CompletenessReport(
            source_idml=str(source_idml),
            translated_idml=str(translated_idml),
            source_entries=len(src_names),
            translated_entries=len(trad_names),
            source_stories=_count_prefix(src_names, "Stories/"),
            translated_stories=_count_prefix(trad_names, "Stories/"),
            source_spreads=_count_prefix(src_names, "Spreads/"),
            translated_spreads=_count_prefix(trad_names, "Spreads/"),
        )
        report.package_match = (
            report.source_entries == report.translated_entries
            and report.source_stories == report.translated_stories
            and report.source_spreads == report.translated_spreads
        )

        report.malformed_xml = _find_malformed(ztrad, trad_names)
        _check_self_ids(zsrc, src_names, ztrad, trad_names, report)
        _check_stories(zsrc, src_names, ztrad, trad_names, report)

    report.text_ratio = (
        round(report.translated_text_len / report.source_text_len, 4)
        if report.source_text_len
        else 0.0
    )
    report.ok = (
        report.package_match
        and not report.malformed_xml
        and not report.self_ids_missing
        and not report.self_ids_extra
        and not report.self_ids_new_duplicates
        and not report.story_count_diffs
        and not report.lost_paragraphs
    )
    report.summary = _summarize(report)
    return report


def _count_prefix(names: list[str], prefix: str) -> int:
    return sum(1 for n in names if n.startswith(prefix))


def _find_malformed(zf: zipfile.ZipFile, names: list[str]) -> list[str]:
    """Lista os membros ``*.xml`` que o lxml não consegue parsear."""
    bad: list[str] = []
    for n in names:
        if not n.endswith(".xml"):
            continue
        try:
            etree.fromstring(zf.read(n))
        except etree.XMLSyntaxError:
            bad.append(n)
    return bad


def _self_counts(zf: zipfile.ZipFile, names: list[str]) -> Counter[str]:
    """Conta cada valor de ``Self="..."`` em todos os ``*.xml`` (via regex)."""
    counts: Counter[str] = Counter()
    for n in names:
        if not n.endswith(".xml"):
            continue
        for m in _SELF_RE.finditer(zf.read(n)):
            counts[m.group(1).decode("utf-8")] += 1
    return counts


def _check_self_ids(
    zsrc: zipfile.ZipFile,
    src_names: list[str],
    ztrad: zipfile.ZipFile,
    trad_names: list[str],
    report: CompletenessReport,
) -> None:
    src = _self_counts(zsrc, src_names)
    trad = _self_counts(ztrad, trad_names)
    report.self_ids_missing = sorted(k for k in src if k not in trad)
    report.self_ids_extra = sorted(k for k in trad if k not in src)
    src_dups = {k for k, v in src.items() if v > 1}
    report.self_ids_new_duplicates = sorted(
        k for k, v in trad.items() if v > 1 and k not in src_dups
    )


def _story_members(names: list[str]) -> list[str]:
    return [n for n in names if n.startswith("Stories/") and n.endswith(".xml")]


def _tag_counts(root: etree._Element) -> dict[str, int]:
    return {tag: sum(1 for _ in root.iter(tag)) for tag in _COUNTED_TAGS}


def _psr_texts(root: etree._Element) -> list[str]:
    """Texto concatenado de cada ``ParagraphStyleRange`` em ordem de documento.

    PSRs aninhados (células de tabela) entram como entradas próprias; o texto de
    um PSR inclui o de seus descendentes. A comparação 1:1 por índice continua
    válida porque a estrutura é idêntica quando ``story_count_diffs`` está vazio.
    """
    return [
        "".join(c.text or "" for c in psr.iter("Content"))
        for psr in root.iter("ParagraphStyleRange")
    ]


def _story_text_len(root: etree._Element) -> int:
    return sum(len(c.text or "") for c in root.iter("Content"))


def _check_stories(
    zsrc: zipfile.ZipFile,
    src_names: list[str],
    ztrad: zipfile.ZipFile,
    trad_names: list[str],
    report: CompletenessReport,
) -> None:
    trad_member_set = set(_story_members(trad_names))

    for member in _story_members(src_names):
        src_root = etree.fromstring(zsrc.read(member))
        report.source_text_len += _story_text_len(src_root)

        if member not in trad_member_set:
            report.story_count_diffs.append(f"{member}: ausente no traduzido")
            continue

        try:
            trad_root = etree.fromstring(ztrad.read(member))
        except etree.XMLSyntaxError:
            # Já registrado em malformed_xml; não dá para comparar estrutura.
            report.story_count_diffs.append(f"{member}: XML malformado")
            continue
        report.translated_text_len += _story_text_len(trad_root)

        sc = _tag_counts(src_root)
        tc = _tag_counts(trad_root)
        if sc != tc:
            diffs = ", ".join(
                f"{tag} {sc[tag]}→{tc[tag]}" for tag in _COUNTED_TAGS if sc[tag] != tc[tag]
            )
            report.story_count_diffs.append(f"{member}: {diffs}")
            # Contagens divergem → alinhamento por índice não é confiável; pula.
            continue

        src_psrs = _psr_texts(src_root)
        trad_psrs = _psr_texts(trad_root)
        for idx, (a, b) in enumerate(zip(src_psrs, trad_psrs, strict=False)):
            if a.strip() and not b.strip():
                report.lost_paragraphs.append(f"{member}#{idx}: {len(a)} chars → vazio")


def _summarize(report: CompletenessReport) -> str:
    if report.ok:
        return (
            f"OK — nada faltando. {report.translated_stories} stories, "
            f"texto {report.text_ratio:.3f}x do original "
            f"({report.translated_text_len}/{report.source_text_len} chars)."
        )
    problems: list[str] = []
    if not report.package_match:
        problems.append(
            f"inventário difere (entries {report.source_entries}→{report.translated_entries}, "
            f"stories {report.source_stories}→{report.translated_stories}, "
            f"spreads {report.source_spreads}→{report.translated_spreads})"
        )
    if report.malformed_xml:
        problems.append(f"{len(report.malformed_xml)} XML malformado(s)")
    if report.self_ids_missing:
        problems.append(f"{len(report.self_ids_missing)} Self ausente(s)")
    if report.self_ids_extra:
        problems.append(f"{len(report.self_ids_extra)} Self extra(s)")
    if report.self_ids_new_duplicates:
        problems.append(f"{len(report.self_ids_new_duplicates)} Self duplicado(s)")
    if report.story_count_diffs:
        problems.append(f"{len(report.story_count_diffs)} story(ies) com estrutura divergente")
    if report.lost_paragraphs:
        problems.append(f"{len(report.lost_paragraphs)} parágrafo(s) com texto PERDIDO")
    return "FALHA — " + "; ".join(problems)
