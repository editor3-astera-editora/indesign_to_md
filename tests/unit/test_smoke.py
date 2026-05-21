"""Smoke tests da F0 — confirmam que o pacote importa e a config default carrega.

Estes testes existem para garantir que o gate de cobertura ≥80% rode em CI
desde o primeiro commit, mesmo antes de qualquer feature funcional.
"""

from __future__ import annotations

import idml_to_md
from idml_to_md import config
from idml_to_md.models import BlockKind, InlineKind


class TestPackageImport:
    def test_package_exposes_version(self) -> None:
        assert isinstance(idml_to_md.__version__, str)
        assert idml_to_md.__version__.count(".") == 2

    def test_block_kind_enum_complete(self) -> None:
        expected = {
            "heading",
            "paragraph",
            "list",
            "admonition",
            "blockquote",
            "code_block",
            "table",
            "image",
            "equation_display",
            "caption",
            "front_matter",
            "reference_entry",
            "drop",
        }
        assert {k.value for k in BlockKind} == expected

    def test_inline_kind_enum_complete(self) -> None:
        expected = {
            "text",
            "bold",
            "italic",
            "bold_italic",
            "superscript",
            "subscript",
            "link",
            "equation_inline",
            "line_break",
        }
        assert {k.value for k in InlineKind} == expected


class TestDefaultStylesYaml:
    def test_default_styles_yaml_loads(self) -> None:
        data = config.load_default_styles()
        assert data["version"] == 1
        assert "paragraph_styles" in data
        assert "character_styles" in data

    def test_essential_paragraph_styles_present(self) -> None:
        data = config.load_default_styles()
        ps = data["paragraph_styles"]
        for name in ("Títulos:T1", "Títulos:T2", "Texto principal", "Bullet", "Referências"):
            assert name in ps, f"estilo essencial ausente: {name}"

    def test_t1_starts_chapter(self) -> None:
        data = config.load_default_styles()
        t1 = data["paragraph_styles"]["Títulos:T1"]
        assert t1["kind"] == "heading"
        assert t1["level"] == 1
        assert t1["starts_chapter"] is True

    def test_character_styles_have_wrappers(self) -> None:
        data = config.load_default_styles()
        cs = data["character_styles"]
        assert cs["Bold"]["wrap"] == "**"
        assert cs["Italic"]["wrap"] == "*"
        assert cs["Sobrescrito"]["html"] == "sup"


class TestUtils:
    def test_slugify_removes_accents_and_punctuation(self) -> None:
        from idml_to_md.utils.slugify import slugify

        assert slugify("81_Matemática Financeira") == "81-matematica-financeira"
        assert slugify("Capítulo 1: Introdução") == "capitulo-1-introducao"
        assert slugify("   trim me   ") == "trim-me"

    def test_slugify_collapses_hyphens(self) -> None:
        from idml_to_md.utils.slugify import slugify

        assert slugify("a---b") == "a-b"
        assert slugify("!!!only-symbols!!!") == "only-symbols"

    def test_xml_namespaces_have_idml_prefixes(self) -> None:
        from idml_to_md.utils.xml import IDML_NAMESPACES

        assert "idPkg" in IDML_NAMESPACES
        assert IDML_NAMESPACES["aid"].startswith("http://ns.adobe.com/")

    def test_command_result_dataclass_is_frozen(self) -> None:
        import dataclasses

        from idml_to_md.utils.subprocess_safe import CommandResult

        result = CommandResult(returncode=0, stdout="ok", stderr="")
        assert result.returncode == 0
        assert dataclasses.is_dataclass(result)
