"""Wrapper sobre a OpenAI Python SDK com batching e retry.

Responsabilidades:
- Quebrar a lista de segmentos em lotes pelo limite de tokens (estimativa
  via ``tiktoken``) e pelo tamanho máximo de lote.
- Chamar ``client.chat.completions.create`` com retry exponencial.
- Reidratar as traduções no schema ``Translation`` com runs traduzidos.
- Estimar custo (USD) com base em tabela de preços por modelo.

Uso típico:

>>> from idml_to_md.translation.openai_client import TranslatorClient
>>> client = TranslatorClient(model="gpt-4o-mini", api_key="sk-...")
>>> translations = client.translate_segments(segments, target_lang="es")
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger
from tenacity import (
    RetryCallState,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from idml_to_md.translation.models import Segment, SegmentRun, Translation
from idml_to_md.translation.prompt_builder import (
    PH_ANCHOR_PREFIX,
    PH_CLOSE,
    PH_OPEN,
    PH_TEXT_PREFIX,
    build_batch_prompt,
    group_logical_runs,
    parse_batch_response,
)

if TYPE_CHECKING:
    pass


def _log_before_sleep(state: RetryCallState) -> None:
    """Loga via loguru antes de tentar novamente (tenacity callback)."""
    attempt = state.attempt_number
    if state.next_action is not None:
        seconds = state.next_action.sleep
        logger.warning(
            "Retentativa {} em {:.1f}s — última falha: {}",
            attempt,
            seconds,
            state.outcome.exception() if state.outcome else "?",
        )

try:  # pragma: no cover - import guard
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment,misc]

try:  # pragma: no cover - import guard
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None  # type: ignore[assignment]


# Tabela aproximada de preços (USD por 1M tokens) — atualizar quando mudar.
# Fonte: openai.com/api/pricing/ (snapshot 2026-05).
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model: (input $/Mtok, output $/Mtok)
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.150, 0.600),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
}


@dataclass(slots=True)
class TranslatorStats:
    """Métricas acumuladas após processar todos os segmentos."""

    total_segments: int = 0
    translated: int = 0
    failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    batches_sent: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TranslatorConfig:
    """Configuração do cliente."""

    model: str = "gpt-4o-mini"
    target_lang: str = "es"
    batch_max_segments: int = 30
    batch_max_input_tokens: int = 3000
    temperature: float = 0.2
    max_completion_tokens: int = 4000
    # Glossário determinístico: ``plain_text`` exato (sem espaços nas pontas) →
    # tradução fixa. Aplicado ANTES da LLM (custo zero, resultado garantido).
    # Ex.: título da capa "UNIDADE" → "UNIDAD" em todas as unidades.
    glossary: dict[str, str] = field(default_factory=dict)


class TranslatorClient:
    """Cliente high-level que orquestra batching, chamadas e parsing."""

    def __init__(
        self,
        config: TranslatorConfig | None = None,
        api_key: str | None = None,
        client: object | None = None,
    ) -> None:
        """Inicializa.

        Args:
            config: configuração; default = TranslatorConfig().
            api_key: chave OpenAI; default = env ``OPENAI_API_KEY``.
            client: instância OpenAI pré-construída (usado em testes para mock).
        """
        self.config = config or TranslatorConfig()
        self.stats = TranslatorStats()

        if client is not None:
            self._client = client
        else:
            if OpenAI is None:
                raise RuntimeError(
                    "Pacote `openai` não instalado. `pip install openai>=1.30`."
                )
            key = api_key or os.getenv("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("OPENAI_API_KEY não configurada.")
            self._client = OpenAI(api_key=key)

        self._encoder = _load_encoder(self.config.model)

    # ------------------------------------------------------------------ API pública

    def translate_segments(
        self,
        segments: list[Segment],
    ) -> list[Translation]:
        """Traduz a lista de segmentos. Segments com ``skip=True`` NÃO são tocados.

        Retorna uma lista de ``Translation`` na mesma ordem dos segmentos
        traduzíveis (skip mantém ordem mas não aparece em translations).
        """
        translatable = [s for s in segments if not s.skip]
        self.stats.total_segments = len(translatable)
        translations: list[Translation] = []

        # Glossário determinístico ANTES da LLM: segmentos cujo texto bate exato
        # com uma chave saem traduzidos sem chamada à API (custo zero).
        glossary = self.config.glossary
        to_llm: list[Segment] = []
        for seg in translatable:
            target = glossary.get(seg.plain_text.strip()) if glossary else None
            if target is not None:
                translations.append(self._glossary_translation(seg, target))
                self.stats.translated += 1
            else:
                to_llm.append(seg)

        if translations:
            logger.info("Glossário determinístico aplicado a {} segmento(s)", len(translations))

        batches = self._chunk_batches(to_llm)
        total_batches = len(batches)
        logger.info(
            "Preparando {} lote(s) para {} segmentos traduzíveis "
            "(modelo={}, batch_max={} segs / {} tokens)",
            total_batches,
            len(to_llm),
            self.config.model,
            self.config.batch_max_segments,
            self.config.batch_max_input_tokens,
        )

        for idx, batch in enumerate(batches, start=1):
            story = batch[0].story_id if batch else "?"
            est_tokens = sum(self._count_tokens(s.plain_text) for s in batch)
            logger.info(
                "→ Lote {}/{} | story={} | segs={} | ~{} tokens (in)",
                idx,
                total_batches,
                story,
                len(batch),
                est_tokens,
            )
            t0 = time.perf_counter()
            batch_translations = self._translate_batch(batch)
            elapsed = time.perf_counter() - t0
            translations.extend(batch_translations)
            logger.info(
                "✓ Lote {}/{} OK em {:.1f}s | acumulado: {} traduzidos, "
                "{} falhas, {} tokens (in+out), ~US$ {:.4f}",
                idx,
                total_batches,
                elapsed,
                self.stats.translated,
                self.stats.failed,
                self.stats.prompt_tokens + self.stats.completion_tokens,
                self.stats.estimated_cost_usd,
            )

        return translations

    # ------------------------------------------------------------------ glossário

    def _glossary_translation(self, seg: Segment, target: str) -> Translation:
        """Monta uma ``Translation`` determinística a partir do glossário.

        O texto-alvo vai para o primeiro run com conteúdo (demais esvaziados),
        reaproveitando :func:`_flat_fallback` — exatamente o que se quer para o
        título de capa, que é um único run.
        """
        nonempty_idx = [i for i, r in enumerate(seg.runs) if r.text.strip()]
        target_runs, _ = _flat_fallback(seg, target, nonempty_idx, [])
        return Translation(
            segment_id=seg.segment_id,
            source_text=seg.plain_text,
            target_text=target,
            target_runs=target_runs,
            model="glossary",
            warnings=["glossary"],
        )

    # ------------------------------------------------------------------ batching

    def _chunk_batches(self, segments: list[Segment]) -> list[list[Segment]]:
        """Agrupa segmentos em lotes respeitando limites de tokens e quantidade.

        Mantém segmentos da mesma Story juntos quando possível (não quebra o
        lote no meio de uma Story se há espaço).
        """
        batches: list[list[Segment]] = []
        current: list[Segment] = []
        current_tokens = 0
        current_story = ""

        for seg in segments:
            seg_tokens = self._count_tokens(seg.plain_text)
            would_overflow_count = len(current) >= self.config.batch_max_segments
            would_overflow_tokens = (
                current_tokens + seg_tokens > self.config.batch_max_input_tokens
            )
            story_changed = current_story and seg.story_id != current_story

            if current and (would_overflow_count or would_overflow_tokens or story_changed):
                batches.append(current)
                current = []
                current_tokens = 0

            current.append(seg)
            current_tokens += seg_tokens
            current_story = seg.story_id

        if current:
            batches.append(current)
        return batches

    # ------------------------------------------------------------------ chamada API

    def _translate_batch(self, batch: list[Segment]) -> list[Translation]:
        """Envia um lote, parseia a resposta e cria Translations."""
        prompt = build_batch_prompt(batch, target_lang=self.config.target_lang)
        self.stats.batches_sent += 1

        try:
            response_text, usage = self._call_api(prompt.system, prompt.user)
        except Exception as exc:
            logger.error("Falha ao chamar OpenAI no lote (n={}): {}", len(batch), exc)
            self.stats.failed += len(batch)
            self.stats.warnings.append(f"batch failed: {exc}")
            return [
                Translation(
                    segment_id=seg.segment_id,
                    source_text=seg.plain_text,
                    target_text="",
                    target_runs=list(seg.runs),
                    model=self.config.model,
                    warnings=[f"batch_failed: {exc}"],
                )
                for seg in batch
            ]

        self.stats.prompt_tokens += usage[0]
        self.stats.completion_tokens += usage[1]
        self.stats.estimated_cost_usd += _estimate_cost(self.config.model, usage[0], usage[1])

        parsed = parse_batch_response(response_text, prompt.segment_order)

        translations: list[Translation] = []
        for seg in batch:
            target = parsed.get(seg.segment_id, "")
            warnings: list[str] = []
            if not target:
                warnings.append("missing in response — kept original")
                target_runs = list(seg.runs)
                target = seg.plain_text
                self.stats.failed += 1
            else:
                target_runs, parse_warnings = _distribute_runs(seg, target)
                warnings.extend(parse_warnings)
                self.stats.translated += 1

            translations.append(
                Translation(
                    segment_id=seg.segment_id,
                    source_text=seg.plain_text,
                    target_text=target,
                    target_runs=target_runs,
                    model=self.config.model,
                    prompt_tokens=usage[0] // max(len(batch), 1),
                    completion_tokens=usage[1] // max(len(batch), 1),
                    warnings=warnings,
                )
            )
        return translations

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=_log_before_sleep,
        reraise=True,
    )
    def _call_api(self, system: str, user: str) -> tuple[str, tuple[int, int]]:
        """Chama a API com retry. Retorna (texto, (prompt_tokens, completion_tokens))."""
        completion = self._client.chat.completions.create(  # type: ignore[attr-defined]
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_completion_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = completion.choices[0].message.content or ""
        usage_obj = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage_obj, "prompt_tokens", 0) if usage_obj else 0
        completion_tokens = getattr(usage_obj, "completion_tokens", 0) if usage_obj else 0
        return content, (prompt_tokens, completion_tokens)

    # ------------------------------------------------------------------ tokens

    def _count_tokens(self, text: str) -> int:
        """Estima tokens via tiktoken; fallback heurístico se tiktoken falhar."""
        if self._encoder is None:
            return max(1, len(text) // 4)
        return len(self._encoder.encode(text))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_encoder(model: str) -> object | None:
    if tiktoken is None:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except (KeyError, ValueError):
        try:
            return tiktoken.get_encoding("cl100k_base")
        except (KeyError, ValueError):  # pragma: no cover
            return None


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _MODEL_PRICING.get(model)
    if pricing is None:
        return 0.0
    input_price, output_price = pricing
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


# Casa, EM ORDEM, os tokens do esquema posicional na resposta da LLM:
#   §tN§…§/tN§  (run de texto, grupos ``tk``/``txt``)
#   §br§        (quebra)
#   §aN§        (âncora, grupo ``ak``)
_TOKEN_RE = re.compile(
    rf"{re.escape(PH_OPEN)}{PH_TEXT_PREFIX}(?P<tk>\d+){re.escape(PH_OPEN)}"
    rf"(?P<txt>.*?){re.escape(PH_CLOSE)}/{PH_TEXT_PREFIX}(?P=tk){re.escape(PH_CLOSE)}"
    rf"|{re.escape(PH_OPEN)}br{re.escape(PH_CLOSE)}"
    rf"|{re.escape(PH_OPEN)}{PH_ANCHOR_PREFIX}(?P<ak>\d+){re.escape(PH_CLOSE)}",
    re.DOTALL,
)

# Remove marcadores avulsos (usado só no fallback, quando nenhum par §tN§ casou).
_MARKER_CLEAN_RE = re.compile(
    rf"{re.escape(PH_OPEN)}/?{PH_TEXT_PREFIX}\d+{re.escape(PH_CLOSE)}"
    rf"|{re.escape(PH_OPEN)}br{re.escape(PH_CLOSE)}"
    rf"|{re.escape(PH_OPEN)}{PH_ANCHOR_PREFIX}\d+{re.escape(PH_CLOSE)}"
)


def _parse_marker_response(target_text: str) -> tuple[dict[int, str], list[str]]:
    """Separa a resposta da LLM em marcadores ``§tN§`` e texto solto (sem marcador).

    Retorna ``(found, bare_chunks)``: ``found`` mapeia índice do grupo → texto do
    par ``§tN§…§/tN§``; ``bare_chunks`` é o texto traduzido FORA de qualquer
    marcador, em ordem de documento (``§br§``/``§aN§`` são tratados como
    marcadores e não entram no texto solto).
    """
    found: dict[int, str] = {}
    bare_chunks: list[str] = []
    cursor = 0
    for match in _TOKEN_RE.finditer(target_text):
        between = target_text[cursor : match.start()]
        if between.strip():
            bare_chunks.append(between)
        txt = match.group("txt")
        if txt is not None:  # é um par §tN§…§/tN§ (não §br§/§aN§)
            found[int(match.group("tk"))] = txt
        cursor = match.end()
    tail = target_text[cursor:]
    if tail.strip():
        bare_chunks.append(tail)
    return found, bare_chunks


def _distribute_runs(
    seg: Segment,
    target_text: str,
) -> tuple[list[SegmentRun], list[str]]:
    """Reconstrói a lista de runs traduzidos a partir da resposta com marcadores.

    Mapeamento POSICIONAL por run LÓGICO (ver
    :func:`prompt_builder.group_logical_runs`): cada par ``§tN§…§/tN§`` (N =
    índice do grupo lógico) reidrata o grupo N — a tradução vai no PRIMEIRO run
    físico do grupo e os demais runs do grupo são esvaziados (uma palavra partida
    em vários ``<Content>`` é traduzida como uma só). Grupos sem marcador
    correspondente mantêm o texto original consolidado no 1º run (com aviso, se
    eram traduzíveis), nunca deixando fragmentos PT soltos. Marcadores
    ``§br§``/``§aN§`` são ignorados aqui (a estrutura física já está no XML).

    Marcador ausente mas com tradução solta: se a LLM traduziu o trecho mas
    "esqueceu" o ``§tN§`` à volta, o texto solto (não marcado) é recuperado por
    ORDEM e usado — preserva a tradução em vez de cair para o PT.

    Fallback final (grupo sem marcador E sem texto solto): consolida o ORIGINAL
    (PT) no 1º run e esvazia os demais — nunca deixa fragmentos PT soltos (ex.:
    ``"circulatorioório"``). Sem nenhum marcador reconhecido: ``_flat_fallback``.

    Retorna ``(runs_traduzidos, warnings)``.
    """
    warnings: list[str] = []

    found, bare_chunks = _parse_marker_response(target_text)

    if not seg.runs:
        return [], warnings

    nonempty_idx = [i for i, r in enumerate(seg.runs) if r.text.strip()]

    if not found:
        return _flat_fallback(seg, target_text, nonempty_idx, warnings)

    groups = group_logical_runs(seg.runs, seg.boundaries)

    # Recupera grupos sem marcador a partir do texto solto (LLM traduziu mas
    # perdeu o §tN§): casa os grupos faltantes com os trechos soltos POR ORDEM.
    missing = [gi for gi in range(len(groups)) if gi not in found]
    recovered = [gi for gi, _ in zip(missing, bare_chunks, strict=False)]
    for gi, bare in zip(missing, bare_chunks, strict=False):
        found[gi] = bare.strip()
    if recovered:
        warnings.append(
            "marcador(es) ausente(s) recuperado(s) de texto traduzido solto: "
            + ", ".join(f"§t{gi}§" for gi in recovered)
        )

    new_runs: list[SegmentRun] = [r.model_copy() for r in seg.runs]
    for gi, group in enumerate(groups):
        first = group[0]
        if gi in found:
            new_runs[first] = new_runs[first].model_copy(update={"text": found[gi]})
            for k in group[1:]:
                new_runs[k] = new_runs[k].model_copy(update={"text": ""})
        else:
            # Grupo sem marcador E sem tradução solta: consolida o ORIGINAL no 1º
            # run e esvazia os demais — evita fragmentos PT soltos.
            if any(seg.runs[k].text.strip() for k in group):
                warnings.append(
                    f"marcador §t{gi}§ ausente na tradução — mantido original"
                )
            consolidated = "".join(seg.runs[k].text for k in group)
            new_runs[first] = new_runs[first].model_copy(update={"text": consolidated})
            for k in group[1:]:
                new_runs[k] = new_runs[k].model_copy(update={"text": ""})
    return new_runs, warnings


def _flat_fallback(
    seg: Segment,
    target_text: str,
    nonempty_idx: list[int],
    warnings: list[str],
) -> tuple[list[SegmentRun], list[str]]:
    """Coloca a tradução inteira no primeiro run com conteúdo; esvazia os outros."""
    clean = _MARKER_CLEAN_RE.sub("", target_text).strip()
    target_slot = nonempty_idx[0] if nonempty_idx else 0

    new_runs: list[SegmentRun] = []
    for i, run in enumerate(seg.runs):
        if i == target_slot:
            new_runs.append(run.model_copy(update={"text": clean}))
        elif run.text.strip():
            new_runs.append(run.model_copy(update={"text": ""}))
        else:
            new_runs.append(run.model_copy(update={"text": run.text}))

    if len(nonempty_idx) > 1:
        warnings.append(
            "marcadores ausentes na tradução — fallback achatado no 1º run"
        )
    return new_runs, warnings
