"""Mapeia ParagraphStyle/CharacterStyle do IDML → kinds semânticos Markdown.

O mapeamento vive em ``config/styles.default.yaml`` (default) e pode ser
sobreposto por um overlay YAML específico de coleção via deep-merge.

Os nomes vindos do IDML em atributos como
``AppliedParagraphStyle="ParagraphStyle/Títulos%3aT1"`` chegam aqui já normalizados:
o prefixo ``ParagraphStyle/`` é removido e ``%3a`` → ``:`` (URL-decoded).

Este módulo não tem dependência de simpleidml/lxml; recebe strings.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

import yaml

from idml_to_md.config import load_default_styles


def normalize_style_name(raw: str) -> str:
    """Remove o prefixo ``ParagraphStyle/`` ou ``CharacterStyle/`` e URL-decode.

    >>> normalize_style_name("ParagraphStyle/Títulos%3aT1")
    'Títulos:T1'
    >>> normalize_style_name("CharacterStyle/$ID/[No character style]")
    '$ID/[No character style]'
    """
    if "/" in raw:
        _, _, name = raw.partition("/")
        # Tags como "ParagraphStyle/$ID/NormalParagraphStyle" — o resto pode ter "/" interno
        # então a partição acima já basta: tudo após o primeiro "/" é nome.
    else:
        name = raw
    return unquote(name)


UnknownPolicy = Literal["passthrough", "warn", "drop"]


@dataclass(slots=True, frozen=True)
class ParagraphRule:
    """Regra de mapeamento para um ParagraphStyle."""

    kind: str
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)


@dataclass(slots=True, frozen=True)
class CharacterRule:
    """Regra de mapeamento para um CharacterStyle (negrito, sup, etc.)."""

    wrap: str | None = None
    html: str | None = None


@dataclass(slots=True)
class StyleMap:
    """Lookup tables + auditoria de estilos encontrados durante a conversão."""

    paragraph_rules: dict[str, ParagraphRule]
    character_rules: dict[str, CharacterRule]
    unknown_paragraph_policy: UnknownPolicy
    unknown_character_policy: UnknownPolicy
    admonitions_config: dict[str, Any]
    tables_config: dict[str, Any]
    equations_config: dict[str, Any]
    images_config: dict[str, Any]
    seen_paragraph_styles: Counter[str] = field(default_factory=Counter)
    seen_character_styles: Counter[str] = field(default_factory=Counter)
    unmapped_paragraph_styles: Counter[str] = field(default_factory=Counter)
    unmapped_character_styles: Counter[str] = field(default_factory=Counter)

    # ------------------------------------------------------------------ lookups
    def lookup_paragraph(self, raw_name: str) -> ParagraphRule | None:
        """Resolve ParagraphStyle. Retorna ``None`` se a policy for ``drop``.

        Para policy ``passthrough`` retorna uma regra ``paragraph`` genérica;
        para ``warn`` faz o mesmo mas registra no auditor.
        """
        name = normalize_style_name(raw_name)
        self.seen_paragraph_styles[name] += 1
        rule = self.paragraph_rules.get(name)
        if rule is not None:
            return rule

        self.unmapped_paragraph_styles[name] += 1
        if self.unknown_paragraph_policy == "drop":
            return None
        # passthrough e warn caem para parágrafo genérico
        return ParagraphRule(kind="paragraph", raw={"kind": "paragraph"})

    def lookup_character(self, raw_name: str) -> CharacterRule | None:
        """Resolve CharacterStyle (formatação inline). ``None`` = sem wrapper."""
        name = normalize_style_name(raw_name)
        self.seen_character_styles[name] += 1
        rule = self.character_rules.get(name)
        if rule is not None:
            return rule

        if name.startswith("$ID/"):
            # "$ID/[No character style]" e similares são silenciosamente OK
            return None

        self.unmapped_character_styles[name] += 1
        return None


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge não-destrutivo: ``overlay`` sobrescreve ``base`` recursivamente."""
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def build_style_map(
    overlay_path: Path | None = None,
    overlay_data: dict[str, Any] | None = None,
) -> StyleMap:
    """Carrega o YAML default e (opcionalmente) aplica overlay.

    ``overlay_data`` tem precedência sobre ``overlay_path`` (útil para testes).
    """
    data = load_default_styles()
    if overlay_data is not None:
        data = _deep_merge(data, overlay_data)
    elif overlay_path is not None:
        with overlay_path.open(encoding="utf-8") as fh:
            overlay = yaml.safe_load(fh) or {}
        data = _deep_merge(data, overlay)

    paragraph_rules: dict[str, ParagraphRule] = {}
    for name, spec in (data.get("paragraph_styles") or {}).items():
        if not isinstance(spec, dict):
            msg = f"paragraph_styles[{name!r}] deve ser mapping, recebido {type(spec).__name__}"
            raise TypeError(msg)
        kind = spec.get("kind", "paragraph")
        paragraph_rules[name] = ParagraphRule(kind=kind, raw=dict(spec))

    character_rules: dict[str, CharacterRule] = {}
    for name, spec in (data.get("character_styles") or {}).items():
        if not isinstance(spec, dict):
            msg = f"character_styles[{name!r}] deve ser mapping"
            raise TypeError(msg)
        character_rules[name] = CharacterRule(wrap=spec.get("wrap"), html=spec.get("html"))

    defaults = data.get("defaults") or {}
    return StyleMap(
        paragraph_rules=paragraph_rules,
        character_rules=character_rules,
        unknown_paragraph_policy=defaults.get("unknown_paragraph_style", "passthrough"),
        unknown_character_policy=defaults.get("unknown_character_style", "passthrough"),
        admonitions_config=dict(data.get("admonitions") or {}),
        tables_config=dict(data.get("tables") or {}),
        equations_config=dict(data.get("equations") or {}),
        images_config=dict(data.get("images") or {}),
    )
