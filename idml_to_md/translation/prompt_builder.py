"""Constrói os prompts para a OpenAI API.

Estratégia:

- **System prompt em PT-BR** orientando: domínio editorial (livro didático),
  registro técnico, NÃO traduzir variáveis matemáticas isoladas, NÃO traduzir
  marcadores especiais (placeholders ``§N§...§/N§``).
- **User prompt** envia múltiplos segmentos numerados; modelo deve responder
  com formato deterministicamente parseável: ``[[N]] <tradução>``.
- **Placeholders inline** para preservar negrito/itálico: para cada run não-texto-puro,
  o texto vai envolvido em ``§N§...§/N§`` (N = índice ordinal do run).
  O modelo é instruído a manter os marcadores exatamente como recebidos.

A v1 NÃO usa glossário (decisão do usuário). O system prompt cita o domínio
para orientar terminologia, mas sem lista de termos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from idml_to_md.translation.models import Segment, SegmentRun

# Caracteres usados como sentinelas para placeholders inline.
# Escolhidos para não aparecer em texto normal e para sobreviver a tokenização.
PH_OPEN = "§"
PH_CLOSE = "§"
# Prefixos/marcadores do esquema posicional:
#   §tN§…§/tN§  → run de texto N (N = índice do run em ``seg.runs``)
#   §br§        → quebra de linha (<Br/>)
#   §aN§        → objeto ancorado inline (fórmula EPS) de ordinal N
PH_TEXT_PREFIX = "t"
PH_ANCHOR_PREFIX = "a"
PH_BR = f"{PH_OPEN}br{PH_CLOSE}"


@dataclass(slots=True)
class PromptPair:
    """Par (system, user) pronto para enviar à API."""

    system: str
    user: str
    segment_order: list[str]  # IDs dos segmentos, na ordem em que aparecem no user


def text_run_marker_open(idx: int) -> str:
    """Marcador de abertura ``§tN§`` para o run de texto de índice ``idx``."""
    return f"{PH_OPEN}{PH_TEXT_PREFIX}{idx}{PH_OPEN}"


def text_run_marker_close(idx: int) -> str:
    """Marcador de fechamento ``§/tN§``."""
    return f"{PH_CLOSE}/{PH_TEXT_PREFIX}{idx}{PH_CLOSE}"


def anchor_marker(anchor_ord: int) -> str:
    """Marcador auto-fechável ``§aN§`` para um objeto ancorado inline."""
    return f"{PH_OPEN}{PH_ANCHOR_PREFIX}{anchor_ord}{PH_CLOSE}"


def build_segment_text_with_placeholders(seg: Segment) -> str:
    """Renderiza o segmento como texto com marcadores posicionais.

    Caminho rápido: se o parágrafo é um único run de texto sem fronteiras
    significativas (caso comum), o texto vai cru, sem marcadores.

    Caso estruturado (vários runs, negrito no meio, quebras entre textos, ou
    fórmula entre textos): cada run de texto vira ``§tN§…§/tN§`` (N = índice do
    run em ``seg.runs``), cada ``<Br/>`` vira ``§br§`` e cada objeto ancorado
    vira ``§aN§``, tudo em ordem de documento. Assim a remontagem
    (``_distribute_runs``) reposiciona o texto traduzido por POSIÇÃO, não
    "tudo no primeiro run".
    """
    runs = seg.runs
    boundaries = seg.boundaries

    if not _is_structured(runs, boundaries):
        return "".join(r.text for r in runs)

    parts: list[str] = []

    def emit_boundaries(after: int) -> None:
        for b in boundaries:
            if b.after_text_ord != after:
                continue
            parts.append(PH_BR if b.kind == "br" else anchor_marker(b.anchor_ord))

    emit_boundaries(-1)
    for i, run in enumerate(runs):
        if run.text:
            parts.append(
                f"{text_run_marker_open(i)}{run.text}{text_run_marker_close(i)}"
            )
        emit_boundaries(i)
    return "".join(parts)


def _is_structured(
    runs: list[SegmentRun], boundaries: list  # list[SegmentBoundary]
) -> bool:
    """True quando o parágrafo precisa de marcadores posicionais.

    Estruturado se há 2+ runs de texto com conteúdo, OU se existe um run de
    texto APÓS alguma fronteira (texto depois de uma quebra/fórmula). Um único
    run seguido só de fronteiras finais (ex.: parágrafo comum terminado em
    ``<Br/>``) NÃO é estruturado — vai cru.
    """
    nonempty = [i for i, r in enumerate(runs) if r.text.strip()]
    if len(nonempty) >= 2:
        return True
    if not nonempty:
        return False
    return any(any(i > b.after_text_ord for i in nonempty) for b in boundaries)


SYSTEM_PROMPT_TEMPLATE = """Você é um tradutor especializado em livros didáticos universitários.
Sua tarefa é traduzir do português (Brasil) para o {target_lang_pretty}.

DOMÍNIO: livros técnicos da área de matemática, finanças, administração e ciências exatas.

REGRAS ESTRITAS:

1. Preserve o REGISTRO ACADÊMICO formal. Use "usted" como pronome de tratamento
   (não "tú") em espanhol; mantenha clareza didática.

2. NÃO traduza:
   - Variáveis matemáticas (M, V, P, C, i, n, etc.)
   - Fórmulas, números, símbolos matemáticos
   - Nomes próprios, marcas, siglas (ISO, ABNT, etc.)
   - Código de programação ou strings técnicas

3. PRESERVE EXATAMENTE todos os marcadores delimitados por § (cifrão de seção):
   - §tN§...§/tN§ envolvem um trecho de texto (N é um número). Traduza SOMENTE
     o texto DENTRO do par e mantenha o MESMO N nos dois marcadores.
   - §br§ marca uma quebra de linha; §aN§ marca uma fórmula/objeto inline.
     NÃO os traduza, NÃO os remova e mantenha-os na MESMA POSIÇÃO relativa ao
     texto ao redor.
   - Nunca funda dois pares §tN§ em um só, não crie pares novos e não mude a
     ordem dos marcadores.
   Exemplos:
   - Entrada:  "§t0§tem apenas §/t0§§t1§um terço§/t1§§t2§ do oxigênio.§/t2§"
   - Saída ES: "§t0§tiene solo §/t0§§t1§un tercio§/t1§§t2§ del oxígeno.§/t2§"
   - Entrada:  "§t0§A fração §/t0§§a0§§t1§ é menor que 1.§/t1§"
   - Saída ES: "§t0§La fracción §/t0§§a0§§t1§ es menor que 1.§/t1§"

4. Mantenha pontuação inicial em espanhol quando aplicável (¿, ¡).

5. Quando NÃO houver marcadores §, traduza o texto normalmente, sem inventá-los.

FORMATO DE RESPOSTA:
Receberá segmentos numerados como [[1]], [[2]], etc.
Responda com os mesmos números [[N]], na mesma ordem, com a tradução em seguida.
Não inclua nenhuma explicação fora dos marcadores.

Exemplo de resposta:
[[1]] Los intereses simples se calculan...
[[2]] El §t1§monto§/t1§ final es...
"""


def build_batch_prompt(
    segments: list[Segment],
    *,
    target_lang: str = "es",
) -> PromptPair:
    """Constrói o prompt para um lote de segmentos.

    Args:
        segments: segmentos NÃO marcados como skip (apenas os traduzíveis).
        target_lang: código do idioma alvo (ex: ``"es"``).
    """
    target_pretty = _target_lang_pretty(target_lang)
    system = SYSTEM_PROMPT_TEMPLATE.format(target_lang_pretty=target_pretty)

    lines: list[str] = []
    order: list[str] = []
    for idx, seg in enumerate(segments, start=1):
        rendered = build_segment_text_with_placeholders(seg)
        lines.append(f"[[{idx}]] {rendered}")
        order.append(seg.segment_id)

    user = "\n\n".join(lines)
    return PromptPair(system=system, user=user, segment_order=order)


def _target_lang_pretty(code: str) -> str:
    mapping = {
        "es": "espanhol (Espanha/América Latina neutra)",
        "en": "inglês (variante neutra)",
        "fr": "francês",
        "it": "italiano",
        "de": "alemão",
    }
    return mapping.get(code.lower(), code)


# ---------------------------------------------------------------------------
# Parser de resposta
# ---------------------------------------------------------------------------


def parse_batch_response(
    response_text: str,
    order: list[str],
) -> dict[str, str]:
    """Parseia a resposta da OpenAI em um dicionário ``segment_id → texto``.

    Tolera respostas com whitespace/quebras antes ou depois dos marcadores.
    Se algum [[N]] estiver ausente, o respectivo segment_id NÃO aparecerá
    no dicionário (o caller deve registrar como warning).
    """
    pattern = re.compile(r"\[\[(\d+)\]\]\s*(.*?)(?=\n\[\[\d+\]\]|\Z)", re.DOTALL)
    result: dict[str, str] = {}
    for match in pattern.finditer(response_text):
        idx_1based = int(match.group(1))
        if idx_1based < 1 or idx_1based > len(order):
            continue
        seg_id = order[idx_1based - 1]
        result[seg_id] = match.group(2).strip()
    return result
