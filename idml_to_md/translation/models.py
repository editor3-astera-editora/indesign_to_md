"""Modelos pydantic para o pipeline de tradução.

Schemas serializáveis em JSON, para que cada fase do pipeline possa
gravar seu output em ``out/<book>/`` e ser inspecionado/retomado.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SkipReason(StrEnum):
    """Motivos para um Segmento ser pulado pela tradução."""

    NONE = "none"
    EMPTY = "empty"
    PARAGRAPH_STYLE = "paragraph_style"  # estilo configurado como não-traduzível
    CODE_BLOCK = "code_block"
    PURE_SYMBOLS = "pure_symbols"  # apenas números/operadores/pontuação
    PURE_VARIABLE = "pure_variable"  # variável matemática isolada (M, V, P, i…)
    BRAND_OR_PROPER_NAME = "brand_or_proper_name"
    NUMERIC_LITERAL = "numeric_literal"
    ALREADY_TRANSLATED = "already_translated"


class SegmentRun(BaseModel):
    """Um run de texto dentro de um parágrafo.

    Cada ``CharacterStyleRange/Content`` do IDML vira um run, com posição
    ordinal estável dentro do parágrafo. Necessário para reconstruir a
    formatação inline (negrito/itálico) após a tradução.
    """

    run_idx: int = Field(..., description="Índice 0-based do CharacterStyleRange no parágrafo")
    content_idx: int = Field(..., description="Índice 0-based do <Content> dentro do CSR")
    text: str = Field(..., description="Texto literal do run")
    bold: bool = False
    italic: bool = False
    superscript: bool = False
    subscript: bool = False
    character_style: str = Field("", description="Nome normalizado do CharacterStyle")


class SegmentBoundary(BaseModel):
    """Fronteira não-textual dentro de um parágrafo (quebra ou objeto ancorado).

    Registra a POSIÇÃO de ``<Br/>`` (quebra de linha forçada) e de objetos
    ancorados inline (fórmula EPS = CSR sem ``<Content>``) em relação aos runs de
    texto. O ``prompt_builder`` usa isso para inserir marcadores ``§br§``/``§aN§``
    para que a LLM preserve a posição e a remontagem mantenha o texto do lado
    certo da quebra/fórmula.
    """

    kind: str = Field(..., description='"br" (quebra de linha) ou "anchor" (objeto ancorado)')
    after_text_ord: int = Field(
        -1,
        description="Índice (em ``runs``) do run de texto que esta fronteira segue; -1 = antes do 1º",
    )
    csr_idx: int = Field(-1, description="Índice do CharacterStyleRange de origem (auditoria)")
    anchor_ord: int = Field(-1, description="Ordinal da âncora no parágrafo (marcador §aN§)")


class Segment(BaseModel):
    """Unidade de tradução: um parágrafo de uma Story do IDML.

    Identificadores:
    - ``story_id``: id da Story (``u1f81d``)
    - ``paragraph_idx``: posição ordinal 0-based do ``ParagraphStyleRange``
      dentro da Story
    - ``runs``: lista ordenada de runs (CSR/Content) — a posição na lista é o
      ordinal usado nos marcadores ``§tN§…§/tN§``.
    - ``boundaries``: quebras/âncoras intercaladas com os runs (ordem de documento)
    - ``cell_self``: quando o parágrafo está dentro de uma célula de tabela, é o
      ``Self`` da ``<Cell>`` (id globalmente único). Nesse caso ``paragraph_idx``
      é o índice do PSR DENTRO da célula, e o writer localiza por esse ``Self``.
    """

    segment_id: str = Field(..., description="Chave única: '<story_id>:<paragraph_idx>'")
    story_id: str
    paragraph_idx: int
    paragraph_style: str = Field("", description="AppliedParagraphStyle normalizado")
    paragraph_kind: str = Field("paragraph", description="kind resolvido (heading|paragraph|…)")
    runs: list[SegmentRun] = Field(default_factory=list)
    boundaries: list[SegmentBoundary] = Field(default_factory=list)
    table_self: str = Field("", description="Self da <Table> quando o parágrafo é de célula")
    cell_self: str = Field("", description="Self da <Cell> quando o parágrafo é de célula")
    plain_text: str = Field("", description="Texto concatenado dos runs (sem formatação)")
    skip: bool = False
    skip_reason: SkipReason = SkipReason.NONE
    notes: list[str] = Field(default_factory=list)


class Translation(BaseModel):
    """Resultado da tradução de um Segment.

    ``target_runs`` mantém o mesmo número/ordem de runs que o original,
    com o texto traduzido distribuído. Para v1, simplificamos: cada run
    recebe sua porção da tradução baseada em placeholders.
    """

    segment_id: str
    source_text: str
    target_text: str = ""
    target_runs: list[SegmentRun] = Field(default_factory=list)
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    warnings: list[str] = Field(default_factory=list)


class TranslationBatch(BaseModel):
    """Conjunto de segmentos enviados juntos para a API.

    Mantém contexto narrativo (mesma Story) e ajuda no rate limiting.
    """

    batch_id: str
    story_id: str
    segments: list[Segment] = Field(default_factory=list)
    translations: list[Translation] = Field(default_factory=list)


class EquationAlert(BaseModel):
    """Alerta de termo PT detectado dentro de EPS MathType.

    O EPS é binário gerado pelo MathType e o pipeline não regera;
    o editor precisa abrir manualmente no MathType para traduzir.
    """

    eps_basename: str
    terms_found: list[str]
    story_id: str = ""


class CompletenessReport(BaseModel):
    """Auditoria de completude: tudo do IDML original está no traduzido?

    Comparação puramente estrutural entre o ``.idml`` original e o traduzido,
    independente da qualidade da tradução. Serve de gate de QA antes de abrir o
    arquivo no InDesign (escalável para centenas de livros).

    ``ok`` é ``True`` somente quando NADA de conteúdo foi perdido: inventário
    do pacote idêntico, todo XML bem-formado, IDs ``Self`` em correspondência
    1:1, contagens estruturais por story iguais e nenhum parágrafo que tinha
    texto no original ficou vazio no traduzido. ``text_ratio`` é informativo
    (expansão PT→ES costuma ficar acima de 1,0).
    """

    source_idml: str
    translated_idml: str
    ok: bool = False
    package_match: bool = False
    # Inventário do pacote ZIP
    source_entries: int = 0
    translated_entries: int = 0
    source_stories: int = 0
    translated_stories: int = 0
    source_spreads: int = 0
    translated_spreads: int = 0
    # Integridade
    malformed_xml: list[str] = Field(default_factory=list)
    self_ids_missing: list[str] = Field(
        default_factory=list, description="Self presentes no original e ausentes no traduzido"
    )
    self_ids_extra: list[str] = Field(
        default_factory=list, description="Self presentes só no traduzido"
    )
    self_ids_new_duplicates: list[str] = Field(
        default_factory=list, description="Self duplicados no traduzido que não eram no original"
    )
    story_count_diffs: list[str] = Field(
        default_factory=list,
        description="Stories cujas contagens estruturais (PSR/CSR/Content/Br/âncoras) divergem",
    )
    lost_paragraphs: list[str] = Field(
        default_factory=list,
        description="Parágrafos com texto no original e vazios no traduzido (perda de conteúdo)",
    )
    # Volume de texto
    source_text_len: int = 0
    translated_text_len: int = 0
    text_ratio: float = 0.0
    summary: str = ""


class AuditReport(BaseModel):
    """Relatório final consolidando métricas e avisos da tradução."""

    source_idml: str
    target_lang: str
    target_idml: str
    total_segments: int = 0
    translated_segments: int = 0
    skipped_segments: int = 0
    skip_breakdown: dict[str, int] = Field(default_factory=dict)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model: str = ""
    equation_alerts: list[EquationAlert] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
