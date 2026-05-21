"""Orquestrador do pipeline de tradução PT→ES.

Junta extractor → classifier → OpenAI → writer → audit.

Saídas em ``output_dir/<slug>/``:
- ``<slug>_<lang>.idml`` — IDML traduzido (input para abrir no InDesign)
- ``segments.json`` — segmentos extraídos (com flags de skip)
- ``translations.json`` — traduções produzidas
- ``_translation_report.json`` — relatório de auditoria
- ``xml_original/Story_*.xml`` — XMLs originais (cópia)
- ``xml_traduzido/Story_*.xml`` — XMLs com texto traduzido
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger

from idml_to_md.style_mapper import build_style_map
from idml_to_md.translation.audit_reporter import build_audit_report, save_report
from idml_to_md.translation.classifier import classify
from idml_to_md.translation.idml_writer import write_translated_idml
from idml_to_md.translation.models import AuditReport, Segment, Translation
from idml_to_md.translation.openai_client import (
    TranslatorClient,
    TranslatorConfig,
    TranslatorStats,
)
from idml_to_md.translation.segment_extractor import extract_segments
from idml_to_md.utils.slugify import slugify

# Estilos que o ``styles.default.yaml`` marca como ``kind: drop`` (corretamente,
# para o pipeline Markdown que regenera o TOC e descarta a capa) mas que DEVEM
# ser traduzidos na saída IDML — título da capa e entradas do sumário manual.
# São convenções consistentes da coleção; sobrescrevíveis via
# ``config/translation.yaml`` (chave ``translate_dropped_styles``).
_DEFAULT_TRANSLATE_DROPPED_STYLES: tuple[str, ...] = (
    "Sumario:Folha de rosto",
    "Sumario:SUMARIO",
    "Sumario:SUMARIO UNIDADE",
    "Sumario:Item 1",
    "Sumario:Item 1.1",
)

# Estilos de capa que PODEM ser extraídos de Stories que só existem em
# MasterSpreads — caso do título "UNIDADE" da capa de unidade, que nas Unidades
# 2/3/4 foi sobreposto na página mas na Unidade 1 ficou só no master.
_DEFAULT_MASTER_COVER_STYLES: tuple[str, ...] = (
    "Título capa",
    "ESTILOS PRINCIPAIS:Título capa",
)

# Glossário determinístico da capa: ``plain_text`` exato → tradução fixa,
# aplicado antes da LLM (custo zero, sempre consistente). O número da unidade é
# preservado pelo classifier (NUMERIC_LITERAL).
_DEFAULT_COVER_GLOSSARY: dict[str, str] = {
    "UNIDADE": "UNIDAD",
    "Unidade": "Unidad",
}


@dataclass(slots=True)
class TranslationConfig:
    """Configuração agregada para o pipeline.

    Carregada de ``config/translation.yaml`` quando fornecida; demais valores
    seguem defaults seguros.
    """

    target_lang: str = "es"
    model: str = "gpt-4o-mini"
    batch_max_segments: int = 30
    batch_max_input_tokens: int = 3000
    temperature: float = 0.2
    max_completion_tokens: int = 4000
    brand_names: tuple[str, ...] = ()
    non_translatable_styles: tuple[str, ...] = ()
    translate_dropped_styles: tuple[str, ...] = _DEFAULT_TRANSLATE_DROPPED_STYLES
    # Capa de unidade que vive só no MasterSpread (ver módulo acima).
    include_master_spreads: bool = True
    master_cover_styles: tuple[str, ...] = _DEFAULT_MASTER_COVER_STYLES
    cover_glossary: dict[str, str] = field(
        default_factory=lambda: dict(_DEFAULT_COVER_GLOSSARY)
    )

    @classmethod
    def from_yaml(cls, path: Path) -> TranslationConfig:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(
            target_lang=data.get("target_lang", "es"),
            model=data.get("model", "gpt-4o-mini"),
            batch_max_segments=data.get("batch_max_segments", 30),
            batch_max_input_tokens=data.get("batch_max_input_tokens", 3000),
            temperature=data.get("temperature", 0.2),
            max_completion_tokens=data.get("max_completion_tokens", 4000),
            brand_names=tuple(data.get("brand_names") or ()),
            non_translatable_styles=tuple(data.get("non_translatable_styles") or ()),
            # Chave ausente → usa o default da coleção; chave presente (mesmo
            # ``[]``) → respeita o valor do YAML (permite desligar o override).
            translate_dropped_styles=(
                tuple(data["translate_dropped_styles"])
                if "translate_dropped_styles" in data
                else _DEFAULT_TRANSLATE_DROPPED_STYLES
            ),
            include_master_spreads=data.get("include_master_spreads", True),
            master_cover_styles=(
                tuple(data["master_cover_styles"])
                if "master_cover_styles" in data
                else _DEFAULT_MASTER_COVER_STYLES
            ),
            cover_glossary=(
                dict(data["cover_glossary"])
                if "cover_glossary" in data
                else dict(_DEFAULT_COVER_GLOSSARY)
            ),
        )


@dataclass(slots=True)
class TranslationResult:
    """Caminhos e métricas finais."""

    target_idml: Path
    segments_path: Path
    translations_path: Path
    report_path: Path
    report: AuditReport
    output_dir: Path


def translate_idml(
    idml_path: Path,
    output_dir: Path,
    *,
    config: TranslationConfig | None = None,
    styles_overlay: Path | None = None,
    dry_run: bool = False,
    api_key: str | None = None,
    translator_client: TranslatorClient | None = None,
) -> TranslationResult:
    """Pipeline completo de tradução.

    Args:
        idml_path: caminho do .idml fonte (PT).
        output_dir: pasta-pai do output (será criado ``<output_dir>/<slug>/``).
        config: configuração de tradução; default = ``TranslationConfig()``.
        styles_overlay: YAML overlay para ``style_mapper``.
        dry_run: se True, NÃO chama a OpenAI nem gera o .idml; só extrai
            os segmentos e salva ``segments.json``. Útil para revisar o que
            será enviado antes de gastar tokens.
        api_key: chave OpenAI; default = env ``OPENAI_API_KEY``.
        translator_client: instância pré-construída (útil para testes/mocks).

    Returns:
        Caminhos e relatório.
    """
    idml_path = Path(idml_path).resolve()
    output_dir = Path(output_dir).resolve()
    cfg = config or TranslationConfig()

    slug = slugify(idml_path.stem.replace("_", " "))
    book_out = output_dir / slug
    book_out.mkdir(parents=True, exist_ok=True)

    xml_original_dir = book_out / "xml_original"
    xml_traduzido_dir = book_out / "xml_traduzido"
    target_idml = book_out / f"{slug}_{cfg.target_lang}.idml"
    segments_path = book_out / "segments.json"
    translations_path = book_out / "translations.json"
    report_path = book_out / "_translation_report.json"

    style_map = build_style_map(overlay_path=styles_overlay)

    started = time.perf_counter()

    logger.info("Extraindo segmentos de {}", idml_path.name)
    segments = extract_segments(
        idml_path,
        style_map,
        xml_dump_dir=xml_original_dir,
        force_translate_styles=frozenset(cfg.translate_dropped_styles),
        include_master_spreads=cfg.include_master_spreads,
        master_cover_styles=frozenset(cfg.master_cover_styles),
    )

    classify(
        segments,
        brand_names=cfg.brand_names,
        extra_non_translatable_styles=cfg.non_translatable_styles,
    )

    _save_segments(segments, segments_path)
    translatable_count = sum(1 for s in segments if not s.skip)
    logger.info(
        "Segments: {} totais, {} traduzíveis, {} pulados",
        len(segments),
        translatable_count,
        len(segments) - translatable_count,
    )

    # Detalhamento das razões de skip (ajuda a diagnosticar regras agressivas)
    skip_counts: dict[str, int] = {}
    for s in segments:
        if s.skip:
            skip_counts[s.skip_reason.value] = skip_counts.get(s.skip_reason.value, 0) + 1
    if skip_counts:
        logger.info(
            "  Skip breakdown: {}",
            ", ".join(f"{k}={v}" for k, v in sorted(skip_counts.items())),
        )

    if dry_run:
        logger.info("dry-run: pulando OpenAI e geração de IDML")
        empty_stats = TranslatorStats(total_segments=translatable_count)
        report = build_audit_report(
            source_idml=idml_path,
            target_idml=target_idml,
            target_lang=cfg.target_lang,
            segments=segments,
            translations=[],
            stats=empty_stats,
            duration_seconds=time.perf_counter() - started,
        )
        report.model = cfg.model + " (dry-run)"
        save_report(report, report_path)
        return TranslationResult(
            target_idml=target_idml,
            segments_path=segments_path,
            translations_path=translations_path,
            report_path=report_path,
            report=report,
            output_dir=book_out,
        )

    if translator_client is None:
        translator_config = TranslatorConfig(
            model=cfg.model,
            target_lang=cfg.target_lang,
            batch_max_segments=cfg.batch_max_segments,
            batch_max_input_tokens=cfg.batch_max_input_tokens,
            temperature=cfg.temperature,
            max_completion_tokens=cfg.max_completion_tokens,
            glossary=dict(cfg.cover_glossary),
        )
        translator_client = TranslatorClient(translator_config, api_key=api_key)

    logger.info(
        "Traduzindo {} segmentos via {} (target={})",
        translatable_count,
        cfg.model,
        cfg.target_lang,
    )
    translations = translator_client.translate_segments(segments)
    _save_translations(translations, translations_path)
    logger.info(
        "Tradução concluída: {} OK, {} falhas, ~US$ {:.4f} ({} tokens in / {} out)",
        translator_client.stats.translated,
        translator_client.stats.failed,
        translator_client.stats.estimated_cost_usd,
        translator_client.stats.prompt_tokens,
        translator_client.stats.completion_tokens,
    )

    logger.info("Gerando IDML traduzido em {}", target_idml.name)
    write_translated_idml(
        source_idml=idml_path,
        target_idml=target_idml,
        segments=segments,
        translations=translations,
        xml_dump_dir=xml_traduzido_dir,
    )

    report = build_audit_report(
        source_idml=idml_path,
        target_idml=target_idml,
        target_lang=cfg.target_lang,
        segments=segments,
        translations=translations,
        stats=translator_client.stats,
        duration_seconds=time.perf_counter() - started,
    )
    report.model = cfg.model
    save_report(report, report_path)

    return TranslationResult(
        target_idml=target_idml,
        segments_path=segments_path,
        translations_path=translations_path,
        report_path=report_path,
        report=report,
        output_dir=book_out,
    )


def _save_segments(segments: list[Segment], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [s.model_dump() for s in segments]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_translations(translations: list[Translation], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [t.model_dump() for t in translations]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
