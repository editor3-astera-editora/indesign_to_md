"""Teste de integração in-process do pipeline de tradução.

Usa um OpenAI mock que devolve traduções determinísticas para validar o
caminho fim-a-fim: extração → classificação → tradução → escrita do IDML →
relatório. Valida também os artefatos extras pedidos pelo usuário (XML
original + XML traduzido salvos lado a lado).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from idml_to_md.translation.openai_client import TranslatorClient, TranslatorConfig
from idml_to_md.translation.pipeline import (
    TranslationConfig,
    translate_idml,
)
from tests.unit.translation.conftest import build_idml_single_story

# ---------------------------------------------------------------------------
# Mock OpenAI: devolve a entrada em maiúsculas como "tradução"
# ---------------------------------------------------------------------------


@dataclass
class _Usage:
    prompt_tokens: int = 20
    completion_tokens: int = 10


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Completion:
    choices: list[_Choice]
    usage: _Usage


class _Completions:
    def create(self, **kwargs: Any) -> _Completion:
        # Devolve cada [[N]] segmento em maiúsculas, sem mexer em placeholders.
        user = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
        lines: list[str] = []
        import re

        for match in re.finditer(r"\[\[(\d+)\]\]\s*(.*?)(?=\n\[\[\d+\]\]|\Z)", user, re.DOTALL):
            idx, content = match.group(1), match.group(2)
            up = content.upper().strip()
            # .upper() também maiusculiza os marcadores §tN§/§br§/§aN§; restaura.
            up = re.sub(r"§(/?)T(\d+)§", r"§\1t\2§", up)
            up = up.replace("§BR§", "§br§")
            up = re.sub(r"§A(\d+)§", r"§a\1§", up)
            lines.append(f"[[{idx}]] {up}")
        text = "\n".join(lines)
        return _Completion(
            choices=[_Choice(message=_Message(content=text))],
            usage=_Usage(),
        )


class _Chat:
    completions = _Completions()


class _OpenAIMock:
    chat = _Chat()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_pipeline_end_to_end(minimal_idml: Path, tmp_path: Path) -> None:
    client = TranslatorClient(
        config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
        client=_OpenAIMock(),
    )
    cfg = TranslationConfig(model="gpt-4o-mini", target_lang="es")

    result = translate_idml(
        idml_path=minimal_idml,
        output_dir=tmp_path / "out",
        config=cfg,
        translator_client=client,
    )

    assert result.target_idml.exists()
    assert result.segments_path.exists()
    assert result.translations_path.exists()
    assert result.report_path.exists()

    # XMLs originais e traduzidos salvos lado a lado (requisito do usuário)
    xml_original = result.output_dir / "xml_original"
    xml_traduzido = result.output_dir / "xml_traduzido"
    assert xml_original.is_dir()
    assert xml_traduzido.is_dir()
    assert any(xml_original.iterdir())
    assert any(xml_traduzido.iterdir())

    # IDML traduzido contém o texto em maiúsculas (mock)
    with zipfile.ZipFile(result.target_idml, "r") as zf:
        story1 = zf.read("Stories/Story_ust1.xml").decode("utf-8")
    assert "MATEMÁTICA FINANCEIRA" in story1.upper()

    # Report consistente
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["target_lang"] == "es"
    assert report["total_segments"] >= 2


def test_pipeline_preserves_br_structure(tmp_path: Path) -> None:
    """Bug #1 ponta-a-ponta: 3 Content separados por Br não devem se fundir."""
    inner = (
        '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">'
        '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
        "<Content>Primeiro paragrafo.</Content><Br/>"
        "<Content>Segundo paragrafo.</Content><Br/>"
        "<Content>Terceiro paragrafo.</Content><Br/>"
        "</CharacterStyleRange></ParagraphStyleRange>"
    )
    idml = build_idml_single_story(tmp_path / "rich.idml", inner)

    client = TranslatorClient(
        config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
        client=_OpenAIMock(),
    )
    result = translate_idml(
        idml_path=idml,
        output_dir=tmp_path / "out",
        config=TranslationConfig(model="gpt-4o-mini", target_lang="es"),
        translator_client=client,
    )

    with zipfile.ZipFile(result.target_idml, "r") as zf:
        story = zf.read("Stories/Story_ust1.xml").decode("utf-8")

    import re

    contents = [c for c in re.findall(r"<Content>(.*?)</Content>", story) if c.strip()]
    # Os três parágrafos continuam separados (não colapsaram no primeiro)
    assert contents == [
        "PRIMEIRO PARAGRAFO.",
        "SEGUNDO PARAGRAFO.",
        "TERCEIRO PARAGRAFO.",
    ]
    # As três quebras forçadas foram preservadas
    assert story.count("<Br") == 3


def test_pipeline_translates_table_cells(table_idml: Path, tmp_path: Path) -> None:
    """Fase 2 ponta-a-ponta (bugs #4/#5): célula de texto traduz, número fica."""
    client = TranslatorClient(
        config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
        client=_OpenAIMock(),
    )
    result = translate_idml(
        idml_path=table_idml,
        output_dir=tmp_path / "out",
        config=TranslationConfig(model="gpt-4o-mini", target_lang="es"),
        translator_client=client,
    )
    with zipfile.ZipFile(result.target_idml, "r") as zf:
        story = zf.read("Stories/Story_ust1.xml").decode("utf-8")
    # célula de texto traduzida (mock = MAIÚSCULAS); célula numérica intacta
    assert "PARTE INTEIRA" in story
    assert "<Content>42</Content>" in story


def test_pipeline_dry_run(minimal_idml: Path, tmp_path: Path) -> None:
    cfg = TranslationConfig(model="gpt-4o-mini", target_lang="es")
    result = translate_idml(
        idml_path=minimal_idml,
        output_dir=tmp_path / "out",
        config=cfg,
        dry_run=True,
    )
    assert result.segments_path.exists()
    assert result.report_path.exists()
    # dry-run NÃO grava o IDML traduzido
    assert not result.target_idml.exists()
    # mas grava o XML original para auditoria
    assert (result.output_dir / "xml_original").is_dir()


# ---------------------------------------------------------------------------
# translate_dropped_styles: capa + sumário (estilos drop forçados a traduzir)
# ---------------------------------------------------------------------------

_COVER_INNER = (
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Sumario%3aFolha de rosto">'
    "<CharacterStyleRange><Content>Matemática Financeira</Content></CharacterStyleRange>"
    "</ParagraphStyleRange>"
)


def test_config_default_includes_dropped_styles() -> None:
    cfg = TranslationConfig()
    assert "Sumario:Folha de rosto" in cfg.translate_dropped_styles
    assert "Sumario:Item 1" in cfg.translate_dropped_styles


def test_config_from_yaml_default_when_key_absent(tmp_path: Path) -> None:
    yaml_path = tmp_path / "t.yaml"
    yaml_path.write_text("target_lang: es\n", encoding="utf-8")
    cfg = TranslationConfig.from_yaml(yaml_path)
    # chave ausente → mantém o default da coleção
    assert "Sumario:Folha de rosto" in cfg.translate_dropped_styles


def test_config_from_yaml_can_disable(tmp_path: Path) -> None:
    yaml_path = tmp_path / "t.yaml"
    yaml_path.write_text("translate_dropped_styles: []\n", encoding="utf-8")
    cfg = TranslationConfig.from_yaml(yaml_path)
    # chave presente como lista vazia → desliga o override
    assert cfg.translate_dropped_styles == ()


def test_pipeline_translates_cover_title_by_default(tmp_path: Path) -> None:
    """Default do TranslationConfig traduz o título da capa (estilo drop)."""
    idml = build_idml_single_story(tmp_path / "cover.idml", _COVER_INNER)
    client = TranslatorClient(
        config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
        client=_OpenAIMock(),
    )
    result = translate_idml(
        idml_path=idml,
        output_dir=tmp_path / "out",
        config=TranslationConfig(model="gpt-4o-mini", target_lang="es"),
        translator_client=client,
    )
    with zipfile.ZipFile(result.target_idml, "r") as zf:
        story = zf.read("Stories/Story_ust1.xml").decode("utf-8")
    # mock = MAIÚSCULAS → prova que o título da capa foi traduzido (não pulado)
    assert "MATEMÁTICA FINANCEIRA" in story


def test_pipeline_translates_toc_hyperlink_entries(tmp_path: Path) -> None:
    """Sumário ponta-a-ponta: estilo drop forçado + texto em HyperlinkTextSource."""
    inner = (
        '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Sumario%3aItem 1">'
        '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
        '<HyperlinkTextSource Self="h1"><Properties/>'
        "<Content>Conjuntos\t16</Content></HyperlinkTextSource><Br/>"
        '<HyperlinkTextSource Self="h2">'
        "<Content>Estatística e Pesquisa\t33</Content></HyperlinkTextSource>"
        "</CharacterStyleRange></ParagraphStyleRange>"
    )
    idml = build_idml_single_story(tmp_path / "toc.idml", inner)
    client = TranslatorClient(
        config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
        client=_OpenAIMock(),
    )
    result = translate_idml(
        idml_path=idml,
        output_dir=tmp_path / "out",
        config=TranslationConfig(model="gpt-4o-mini", target_lang="es"),
        translator_client=client,
    )
    with zipfile.ZipFile(result.target_idml, "r") as zf:
        story = zf.read("Stories/Story_ust1.xml").decode("utf-8")
    # mock = MAIÚSCULAS → prova que as entradas (dentro do hyperlink) traduziram
    assert "CONJUNTOS" in story
    assert "ESTATÍSTICA E PESQUISA" in story
    # estrutura do hyperlink preservada (Self intactos)
    assert 'HyperlinkTextSource Self="h1"' in story
    assert 'HyperlinkTextSource Self="h2"' in story


def test_pipeline_skips_cover_title_when_disabled(tmp_path: Path) -> None:
    """Com translate_dropped_styles=() o título da capa fica em PT (drop)."""
    idml = build_idml_single_story(tmp_path / "cover.idml", _COVER_INNER)
    client = TranslatorClient(
        config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
        client=_OpenAIMock(),
    )
    result = translate_idml(
        idml_path=idml,
        output_dir=tmp_path / "out",
        config=TranslationConfig(
            model="gpt-4o-mini", target_lang="es", translate_dropped_styles=()
        ),
        translator_client=client,
    )
    with zipfile.ZipFile(result.target_idml, "r") as zf:
        story = zf.read("Stories/Story_ust1.xml").decode("utf-8")
    # original preservado (drop pulado, não traduzido)
    assert "<Content>Matemática Financeira</Content>" in story


# ---------------------------------------------------------------------------
# Sincronização sumário ↔ títulos de capítulo (sync_toc_titles)
# ---------------------------------------------------------------------------


class _DivergentCompletions:
    """Mock que traduz o MESMO título de formas diferentes no corpo e no sumário.

    Corpo (sem marcadores §tN§) → sufixo ``-COR``. Sumário (multi-run, com
    marcadores) → cada título recebe ``-SUM``, preservando ``\\t<página>``.
    Simula a não-determinismo da LLM que motiva a sincronização.
    """

    def create(self, **kwargs: Any) -> _Completion:
        import re

        user = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
        out_lines: list[str] = []
        for match in re.finditer(
            r"\[\[(\d+)\]\]\s*(.*?)(?=\n\[\[\d+\]\]|\Z)", user, re.DOTALL
        ):
            idx, content = match.group(1), match.group(2).strip()
            if "§t" in content:

                def _repl(m: re.Match[str]) -> str:
                    n, inner = m.group(1), m.group(2)
                    title, sep, page = inner.partition("\t")
                    return f"§t{n}§{title}-SUM{sep}{page}§/t{n}§"

                content = re.sub(r"§t(\d+)§(.*?)§/t\1§", _repl, content, flags=re.DOTALL)
            else:
                content = f"{content}-COR"
            out_lines.append(f"[[{idx}]] {content}")
        return _Completion(
            choices=[_Choice(message=_Message(content="\n".join(out_lines)))],
            usage=_Usage(),
        )


class _DivergentChat:
    completions = _DivergentCompletions()


class _DivergentMock:
    chat = _DivergentChat()


_SYNC_INNER = (
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/T%c3%adtulos%3aT1">'
    '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
    "<Content>Conjuntos</Content></CharacterStyleRange></ParagraphStyleRange>"
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Sumario%3aItem 1">'
    '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
    '<HyperlinkTextSource Self="h1"><Properties/>'
    "<Content>Conjuntos\t16</Content></HyperlinkTextSource><Br/>"
    '<HyperlinkTextSource Self="h2">'
    "<Content>Estatística e Pesquisa\t33</Content></HyperlinkTextSource>"
    "</CharacterStyleRange></ParagraphStyleRange>"
)


def _run_sync_pipeline(tmp_path: Path, *, sync: bool) -> str:
    idml = build_idml_single_story(tmp_path / "sync.idml", _SYNC_INNER)
    client = TranslatorClient(
        config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
        client=_DivergentMock(),
    )
    result = translate_idml(
        idml_path=idml,
        output_dir=tmp_path / "out",
        config=TranslationConfig(
            model="gpt-4o-mini", target_lang="es", sync_toc_titles=sync
        ),
        translator_client=client,
    )
    with zipfile.ZipFile(result.target_idml, "r") as zf:
        return zf.read("Stories/Story_ust1.xml").decode("utf-8")


def test_pipeline_syncs_toc_entry_to_chapter_title(tmp_path: Path) -> None:
    """Sumário é reescrito para o título traduzido do corpo (sufixo de página intacto)."""
    story = _run_sync_pipeline(tmp_path, sync=True)
    # Corpo (heading) + entrada do sumário usam a MESMA tradução "-COR".
    assert story.count("Conjuntos-COR") == 2
    assert "Conjuntos-COR\t16" in story
    # A versão divergente do sumário foi descartada.
    assert "Conjuntos-SUM" not in story
    # Sem heading correspondente → mantém a tradução da LLM.
    assert "Estatística e Pesquisa-SUM\t33" in story


def test_pipeline_no_sync_leaves_divergent_toc(tmp_path: Path) -> None:
    """Com sync_toc_titles=False a entrada do sumário fica divergente do corpo."""
    story = _run_sync_pipeline(tmp_path, sync=False)
    assert story.count("Conjuntos-COR") == 1  # só o heading do corpo
    assert "Conjuntos-SUM\t16" in story


# Estrutura INVERTIDA: HyperlinkTextSource é filho DIRETO do PSR e envolve os
# CSRs, com o título partido em 2 runs ("Mundo do " + "trabalho \t59").
# Reproduz o caso real do livro 81 (Story_u1cf09 / "Mundo do trabalho").
_INVERTED_TOC_INNER = (
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/T%c3%adtulos%3aT1">'
    '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
    "<Content>Mundo do trabalho</Content></CharacterStyleRange></ParagraphStyleRange>"
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Sumario%3aItem 1">'
    '<HyperlinkTextSource Self="h3"><Properties/>'
    '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
    "<Content>Mundo do </Content></CharacterStyleRange>"
    '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
    "<Content>trabalho \t59</Content></CharacterStyleRange>"
    "</HyperlinkTextSource>"
    '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
    "<Br/></CharacterStyleRange></ParagraphStyleRange>"
)


def _run_inverted_pipeline(tmp_path: Path, *, sync: bool) -> str:
    idml = build_idml_single_story(tmp_path / "inv.idml", _INVERTED_TOC_INNER)
    client = TranslatorClient(
        config=TranslatorConfig(model="gpt-4o-mini", batch_max_segments=10),
        client=_DivergentMock(),
    )
    result = translate_idml(
        idml_path=idml,
        output_dir=tmp_path / "out",
        config=TranslationConfig(
            model="gpt-4o-mini", target_lang="es", sync_toc_titles=sync
        ),
        translator_client=client,
    )
    with zipfile.ZipFile(result.target_idml, "r") as zf:
        return zf.read("Stories/Story_ust1.xml").decode("utf-8")


def test_inverted_toc_entry_is_translated(tmp_path: Path) -> None:
    """Sem o fix, a entrada invertida ficaria em PT; agora ela é traduzida."""
    story = _run_inverted_pipeline(tmp_path, sync=False)
    # A entrada do sumário NÃO ficou no original PT.
    assert "<Content>trabalho \t59</Content>" not in story
    assert "-SUM" in story  # foi traduzida (mock divergente)


def test_inverted_toc_entry_synced_to_chapter_title(tmp_path: Path) -> None:
    """Com sync, o título partido em 2 runs casa o corpo e fica idêntico."""
    story = _run_inverted_pipeline(tmp_path, sync=True)
    # Corpo (heading) + sumário usam a MESMA tradução, com a página preservada.
    assert story.count("Mundo do trabalho-COR") == 2
    assert "Mundo do trabalho-COR\t59" in story
    # A versão divergente do sumário foi descartada.
    assert "-SUM" not in story


def test_config_default_sync_toc_titles() -> None:
    cfg = TranslationConfig()
    assert cfg.sync_toc_titles is True
    assert "Títulos:T1" in cfg.chapter_title_styles
    assert "Sumario:Item 1" in cfg.toc_entry_styles


def test_config_from_yaml_sync_defaults_when_absent(tmp_path: Path) -> None:
    yaml_path = tmp_path / "t.yaml"
    yaml_path.write_text("target_lang: es\n", encoding="utf-8")
    cfg = TranslationConfig.from_yaml(yaml_path)
    assert cfg.sync_toc_titles is True
    assert "Títulos:T1" in cfg.chapter_title_styles
    assert "Sumario:Item 1" in cfg.toc_entry_styles


def test_config_from_yaml_can_disable_sync(tmp_path: Path) -> None:
    yaml_path = tmp_path / "t.yaml"
    yaml_path.write_text(
        "sync_toc_titles: false\nchapter_title_styles: []\n", encoding="utf-8"
    )
    cfg = TranslationConfig.from_yaml(yaml_path)
    assert cfg.sync_toc_titles is False
    assert cfg.chapter_title_styles == ()
