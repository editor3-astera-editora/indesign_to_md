"""Gera o ``_translation_report.json`` consolidando métricas e avisos.

Inputs:
- Lista de Segments (com flags de skip e motivo)
- Lista de Translations (com warnings e tokens)
- Stats do TranslatorClient (custo agregado)
- Caminho do IDML original (para varrer EPS MathType)

Output: arquivo JSON conforme schema ``AuditReport``.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path

from loguru import logger

from idml_to_md.equation_extractor import (
    EquationExtractionError,
    _extract_from_text,
)
from idml_to_md.translation.models import AuditReport, EquationAlert, Segment, Translation
from idml_to_md.translation.openai_client import TranslatorStats

# Lista mínima de termos PT comuns em matemática financeira que, se aparecerem
# DENTRO de uma equação MathType, devem ser sinalizados para revisão manual.
# Conservadora: só termos onde a probabilidade de falso positivo é baixa.
DEFAULT_PT_TERMS: tuple[str, ...] = (
    "Juros",
    "Montante",
    "Capital",
    "Taxa",
    "Tempo",
    "Saldo",
    "Período",
    "Periodo",
    "Valor",
    "Total",
    "Médio",
    "Médios",
    "Inicial",
    "Final",
)


def build_audit_report(
    *,
    source_idml: Path,
    target_idml: Path,
    target_lang: str,
    segments: list[Segment],
    translations: list[Translation],
    stats: TranslatorStats,
    duration_seconds: float = 0.0,
    pt_terms: tuple[str, ...] = DEFAULT_PT_TERMS,
) -> AuditReport:
    """Constrói um ``AuditReport`` pronto para ser serializado."""
    skip_breakdown: Counter[str] = Counter()
    for seg in segments:
        if seg.skip:
            skip_breakdown[seg.skip_reason.value] += 1

    warnings: list[str] = list(stats.warnings)
    for t in translations:
        for w in t.warnings:
            warnings.append(f"{t.segment_id}: {w}")

    equation_alerts = _scan_equations_for_pt_terms(source_idml, segments, pt_terms)

    return AuditReport(
        source_idml=str(source_idml),
        target_idml=str(target_idml),
        target_lang=target_lang,
        total_segments=len(segments),
        translated_segments=stats.translated,
        skipped_segments=sum(1 for s in segments if s.skip),
        skip_breakdown=dict(skip_breakdown),
        total_prompt_tokens=stats.prompt_tokens,
        total_completion_tokens=stats.completion_tokens,
        estimated_cost_usd=round(stats.estimated_cost_usd, 6),
        model="",  # preenchido pelo CLI antes de salvar
        equation_alerts=equation_alerts,
        warnings=warnings,
        duration_seconds=duration_seconds,
    )


def _scan_equations_for_pt_terms(
    idml_path: Path,
    segments: list[Segment],
    pt_terms: tuple[str, ...],
) -> list[EquationAlert]:
    """Varre os EPS dentro do IDML procurando termos PT no MathML.

    EPS são binários gerados pelo MathType e o pipeline NÃO os modifica.
    Esta função detecta quando palavras como ``Juros`` ou ``Montante``
    aparecem dentro do MathML do EPS, sinalizando para o editor revisar
    manualmente no MathType.
    """
    alerts: list[EquationAlert] = []
    term_patterns = [re.compile(rf"\b{re.escape(t)}\b") for t in pt_terms]

    try:
        with zipfile.ZipFile(idml_path, "r") as zf:
            members = [m for m in zf.namelist() if m.lower().endswith(".eps")]
            # EPS embutidos em IDML são raros (geralmente ficam em Links/),
            # mas tratamos por simetria. A varredura real é em Links/.
            for member in members:
                with zf.open(member) as fh:
                    text = fh.read().decode("latin-1", errors="ignore")
                alert = _scan_eps_text(text, member, term_patterns, pt_terms)
                if alert is not None:
                    alerts.append(alert)
    except zipfile.BadZipFile:
        logger.warning("IDML não é ZIP válido (auditoria de equações): {}", idml_path)

    # Os EPS mais relevantes ficam em Links/ ao lado do .idml
    links_dir = idml_path.parent / "Links"
    if links_dir.is_dir():
        for eps_path in sorted(links_dir.glob("*.eps")):
            try:
                text = eps_path.read_text(encoding="latin-1", errors="ignore")
            except OSError as exc:
                logger.debug("Falha ao ler EPS {}: {}", eps_path.name, exc)
                continue
            alert = _scan_eps_text(text, eps_path.name, term_patterns, pt_terms)
            if alert is not None:
                alerts.append(alert)

    return alerts


def _scan_eps_text(
    text: str,
    basename: str,
    patterns: list[re.Pattern[str]],
    pt_terms: tuple[str, ...],
) -> EquationAlert | None:
    """Extrai MathML do EPS e verifica termos PT.

    Retorna ``None`` quando o EPS não é uma equação MathType ou quando não
    há nenhum termo PT detectado.
    """
    try:
        extracted = _extract_from_text(text, source=Path(basename))
    except EquationExtractionError:
        return None

    mathml = extracted.mathml
    found = [pt_terms[i] for i, pat in enumerate(patterns) if pat.search(mathml)]
    if not found:
        return None
    return EquationAlert(eps_basename=basename, terms_found=found)


def save_report(report: AuditReport, path: Path) -> None:
    """Serializa o relatório para JSON com indentação."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
