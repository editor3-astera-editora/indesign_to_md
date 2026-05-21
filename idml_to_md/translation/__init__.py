"""Tradução PT→ES de livros IDML preservando layout.

Pipeline em 5 fases:

1. ``segment_extractor`` — percorre Stories do IDML e produz Segmentos
   com IDs estáveis (story_id + paragraph_path + run_path).
2. ``classifier`` — marca segmentos que NÃO devem ser traduzidos
   (código, marcas, símbolos puros).
3. ``openai_client`` + ``prompt_builder`` — traduz em lotes por Story,
   preservando placeholders inline de negrito/itálico.
4. ``idml_writer`` — substitui ``<Content>`` no XML das Stories
   e regrava o IDML mantendo a estrutura ZIP.
5. ``audit_reporter`` — gera ``_translation_report.json`` com
   métricas, avisos e custos.

O .idml resultante é aberto manualmente no Adobe InDesign Desktop
para exportar o PDF final pixel-perfect.
"""

from idml_to_md.translation.models import (
    AuditReport,
    CompletenessReport,
    Segment,
    SegmentRun,
    SkipReason,
    Translation,
    TranslationBatch,
)

__all__ = [
    "AuditReport",
    "CompletenessReport",
    "Segment",
    "SegmentRun",
    "SkipReason",
    "Translation",
    "TranslationBatch",
]
