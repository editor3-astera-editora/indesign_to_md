"""Testes do ``anchored_resolver``."""

from __future__ import annotations

from lxml import etree

from idml_to_md.anchored_resolver import (
    AnchoredKind,
    _basename_from_uri,
    classify_anchored,
)


def make_link_xml(uri: str) -> etree._Element:
    """Constrói ``<Group><Rectangle><Image><Link LinkResourceURI="..."/></Image></Rectangle></Group>``."""
    xml = (
        "<Group>"
        "<Rectangle>"
        "<Image>"
        f'<Link Self="lk" LinkResourceURI="{uri}" />'
        "</Image></Rectangle></Group>"
    )
    return etree.fromstring(xml.encode("utf-8"))


class TestClassify:
    def test_raster_jpg(self) -> None:
        el = make_link_xml("file:C:/x/Links/photo.jpg")
        info = classify_anchored(el)
        assert info.kind == AnchoredKind.IMAGE_RASTER
        assert info.basename == "photo.jpg"

    def test_raster_png(self) -> None:
        el = make_link_xml("file:C:/x/Links/icon.PNG")
        info = classify_anchored(el)
        assert info.kind == AnchoredKind.IMAGE_RASTER

    def test_equation_eps(self) -> None:
        el = make_link_xml("file:C:/x/Links/81_MF_Eqn001.eps")
        info = classify_anchored(el)
        assert info.kind == AnchoredKind.EQUATION_EPS
        assert info.basename == "81_MF_Eqn001.eps"

    def test_ai_is_vector(self) -> None:
        # F3: .ai vira IMAGE_VECTOR (era OTHER em F2)
        el = make_link_xml("file:C:/x/Links/illustration.ai")
        info = classify_anchored(el)
        assert info.kind == AnchoredKind.IMAGE_VECTOR
        assert info.basename == "illustration.ai"

    def test_unknown_extension_is_other(self) -> None:
        el = make_link_xml("file:C:/x/Links/data.csv")
        info = classify_anchored(el)
        assert info.kind == AnchoredKind.OTHER

    def test_no_link_returns_other(self) -> None:
        el = etree.fromstring(b"<Group><Polygon /></Group>")
        info = classify_anchored(el)
        assert info.kind == AnchoredKind.OTHER

    def test_embedded_file_prefix_skipped(self) -> None:
        # URIs sem "Links/" e que começam com "file:" são tratadas como embutidas
        el = make_link_xml("file:Image137670.PNG")
        info = classify_anchored(el)
        assert info.kind == AnchoredKind.OTHER


class TestBasenameFromUri:
    def test_strips_links_prefix(self) -> None:
        assert _basename_from_uri("file:C:/x/y/Links/foo.jpg") == "foo.jpg"

    def test_url_decode(self) -> None:
        assert _basename_from_uri("Links/Imagem%201.jpg") == "Imagem 1.jpg"

    def test_no_links_keeps_path(self) -> None:
        assert _basename_from_uri("just_a_name.eps") == "just_a_name.eps"
