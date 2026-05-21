"""Fixtures locais para os testes do subpacote ``translation``.

Inclui um construtor de IDML mínimo na memória: gera um ZIP no formato IDML
com poucas Stories e estilos suficientes para validar extração, classificação
e escrita.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

# IDML é um pacote OCF: mimetype + designmap + Resources/Styles.xml + Spreads/* + Stories/*
# Para testes, geramos a estrutura mínima necessária para o pipeline funcionar.

MIMETYPE = b"application/vnd.adobe.indesign-idml-package"

DESIGNMAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<?aid style="50" type="document" readerVersion="6.0" featureSet="257" product="18.0(58)" ?>
<Document xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
  <idPkg:Spread src="Spreads/Spread_us1.xml"/>
</Document>
"""

STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Styles xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="18.0">
  <RootParagraphStyleGroup Self="u1ps">
    <ParagraphStyle Self="ParagraphStyle/Texto principal" Name="Texto principal"/>
    <ParagraphStyle Self="ParagraphStyle/T%c3%adtulos%3aT1" Name="Títulos:T1"/>
  </RootParagraphStyleGroup>
  <RootCharacterStyleGroup Self="u1cs">
    <CharacterStyle Self="CharacterStyle/Bold" Name="Bold"/>
  </RootCharacterStyleGroup>
</idPkg:Styles>
"""

SPREAD_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Spread xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="18.0">
  <Spread Self="us1" PageCount="1">
    <Page Self="up1" Name="1"/>
    <TextFrame Self="utf1" ParentStory="ust1" PreviousTextFrame="n" NextTextFrame="n"/>
    <TextFrame Self="utf2" ParentStory="ust2" PreviousTextFrame="n" NextTextFrame="n"/>
  </Spread>
</idPkg:Spread>
"""

STORY1_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="18.0">
  <Story Self="ust1">
    <ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/T%c3%adtulos%3aT1">
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content>Matemática Financeira</Content>
      </CharacterStyleRange>
    </ParagraphStyleRange>
    <ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content>Os </Content>
      </CharacterStyleRange>
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/Bold" FontStyle="Bold">
        <Content>juros simples</Content>
      </CharacterStyleRange>
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content> são calculados sobre o capital inicial.</Content>
      </CharacterStyleRange>
    </ParagraphStyleRange>
  </Story>
</idPkg:Story>
"""

STORY2_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="18.0">
  <Story Self="ust2">
    <ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content>M = C(1 + i)^n</Content>
      </CharacterStyleRange>
    </ParagraphStyleRange>
    <ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content>1.234,56</Content>
      </CharacterStyleRange>
    </ParagraphStyleRange>
  </Story>
</idPkg:Story>
"""


SINGLE_STORY_SPREAD = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Spread xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="18.0">
  <Spread Self="us1" PageCount="1">
    <Page Self="up1" Name="1"/>
    <TextFrame Self="utf1" ParentStory="ust1" PreviousTextFrame="n" NextTextFrame="n"/>
  </Spread>
</idPkg:Spread>
"""


def build_idml_single_story(
    out_path: Path, story_inner: str, story_id: str = "ust1"
) -> Path:
    """Cria um IDML mínimo com UMA Story cujo corpo é ``story_inner``.

    ``story_inner`` é o conteúdo dentro de ``<Story Self="ust1">…</Story>``
    (um ou mais ``<ParagraphStyleRange>``). Útil para testar estruturas
    específicas (quebras, âncoras) ponta-a-ponta.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    story_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"'
        ' DOMVersion="18.0">'
        f'<Story Self="{story_id}">{story_inner}</Story></idPkg:Story>'
    )
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, MIMETYPE)
        zf.writestr("designmap.xml", DESIGNMAP_TEMPLATE)
        zf.writestr("Resources/Styles.xml", STYLES_XML)
        zf.writestr("Spreads/Spread_us1.xml", SINGLE_STORY_SPREAD)
        zf.writestr(f"Stories/Story_{story_id}.xml", story_xml)
    return out_path


def build_minimal_idml(out_path: Path) -> Path:
    """Cria um IDML mínimo válido o suficiente para o pipeline.

    Estrutura:
    - 2 Stories (capítulo + parágrafo, e fórmula + número solto)
    - 1 Spread referenciando ambas
    - Estilos: Titulos:T1, Texto principal, Bold
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # mimetype STORED primeiro
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, MIMETYPE)
        zf.writestr("designmap.xml", DESIGNMAP_TEMPLATE)
        zf.writestr("Resources/Styles.xml", STYLES_XML)
        zf.writestr("Spreads/Spread_us1.xml", SPREAD_TEMPLATE)
        zf.writestr("Stories/Story_ust1.xml", STORY1_XML)
        zf.writestr("Stories/Story_ust2.xml", STORY2_XML)
    return out_path


@pytest.fixture
def minimal_idml(tmp_path: Path) -> Path:
    """Cria e retorna o caminho de um IDML mínimo em tmp_path."""
    return build_minimal_idml(tmp_path / "mini.idml")


# PSR de topo contendo uma tabela 1 linha × 2 colunas:
# célula c0 = texto traduzível ("Parte inteira"); célula c1 = número ("42").
TABLE_INNER = (
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">'
    '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">'
    '<Table Self="utbl1" ColumnCount="2" BodyRowCount="1">'
    '<Row Self="utbl1Row0"/><Column Self="utbl1Col0"/><Column Self="utbl1Col1"/>'
    '<Cell Self="utbl1c0" Name="0:0">'
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">'
    "<CharacterStyleRange><Content>Parte inteira</Content></CharacterStyleRange>"
    "</ParagraphStyleRange></Cell>"
    '<Cell Self="utbl1c1" Name="1:0">'
    '<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Texto principal">'
    "<CharacterStyleRange><Content>42</Content></CharacterStyleRange>"
    "</ParagraphStyleRange></Cell>"
    "</Table></CharacterStyleRange></ParagraphStyleRange>"
)


@pytest.fixture
def table_idml(tmp_path: Path) -> Path:
    """IDML com uma Story contendo uma tabela (célula de texto + célula numérica)."""
    return build_idml_single_story(tmp_path / "table.idml", TABLE_INNER)
