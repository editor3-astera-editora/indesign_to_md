# Scripts auxiliares

Scripts em `scripts/` que complementam os CLIs principais.

## `scripts/extract_mathml_smoke.py`

**Propósito.** Smoke test do pipeline de equações (F2): extrai MathML de todos os `.eps` de uma pasta, converte para LaTeX, e reporta a taxa de sucesso. Útil para validar uma coleção nova antes de rodar a conversão completa.

**Uso.**

```bash
python scripts/extract_mathml_smoke.py <pasta_com_eps> [OPÇÕES]
```

| Argumento | Tipo | Default | Descrição |
|---|---|---|---|
| `links_dir` | Path | — | Pasta com os `.eps` (obrigatório). |
| `--verbose` | flag | desativado | Imprime cada equação processada (LaTeX truncado em 80 chars). |
| `--threshold` | float | `0.95` | Taxa mínima de sucesso para considerar OK. |

**Saída (stdout).**

```
Total EPS:           125
  OK (MathML→LaTeX): 119
  SKIP (sem MathType): 4
  FAIL:              2
Taxa sobre MathType: 98.3%
Cache hits/misses:   0/119

Falhas:
  81_MF_Eqn073.eps: XML inválido: ...
```

**Exit codes.**

| Código | Significado |
|---|---|
| 0 | Taxa ≥ threshold. |
| 1 | Pasta inexistente, sem `.eps`, ou taxa abaixo do threshold. |

**Notas.**
- Conta **3 categorias**: OK (MathML extraído e convertido), SKIP (EPS sem marcador `%MathType` — é ilustração vetorial, não falha), FAIL (extração ou conversão falhou).
- A taxa é calculada sobre `OK + FAIL` (excluindo SKIPs), porque SKIPs são esperados e legítimos.
- Usa o mesmo `EquationConverter` do pipeline, sem cache em disco — o `cache_hits` reflete apenas hits em memória durante esta execução.

## `scripts/rebuild_idml_from_translations.py`

**Propósito.** Regenera o `.idml` traduzido a partir de `segments.json` + `translations.json` já existentes, **sem chamar OpenAI**. Útil para:

- Reaplicar um fix no `idml_writer` (ex.: ajuste de serialização XML) sem pagar tokens de novo.
- Corrigir manualmente uma tradução em `translations.json` e regravar o IDML.
- Diff vs. o IDML anterior depois de mudanças no writer.

**Uso.**

```bash
python scripts/rebuild_idml_from_translations.py \
    --source <idml_original> \
    --out-dir <pasta_com_segments_e_translations_json> \
    [--lang es]
```

| Flag | Tipo | Obrigatório | Default | Descrição |
|---|---|---|---|---|
| `--source` | Path | sim | — | Caminho do `.idml` original. |
| `--out-dir` | Path | sim | — | Pasta contendo `segments.json` e `translations.json`. |
| `--lang` | str | não | `es` | Sufixo do `.idml` de saída. |

**Comportamento.**

1. Carrega `segments.json` → `list[Segment]` via Pydantic.
2. Carrega `translations.json` → `list[Translation]`.
3. Determina `slug` a partir do nome da `--out-dir`.
4. Chama `write_translated_idml(source, out_dir/<slug>_<lang>.idml, segments, translations, xml_dump_dir=out_dir/"xml_traduzido")`.
5. Loga estatísticas (stories modificadas, contents substituídos).

**Exit codes.**

| Código | Significado |
|---|---|
| 0 | OK. |
| 1 | `segments.json` ou `translations.json` ausente em `--out-dir`. |

## `scripts/verify_translation_completeness.py`

**Propósito.** Gate de QA **estrutural**: verifica se *tudo que está no IDML original está no IDML traduzido*, antes de abrir o arquivo no InDesign. Não avalia a qualidade da tradução — só completude/integridade. Detecta perda de conteúdo, corrupção de IDs e XML malformado que o writer poderia ter introduzido.

**Uso.**

```bash
python scripts/verify_translation_completeness.py \
    --source <idml_original> \
    --translated <idml_traduzido> \
    [--json out/_completeness.json]
```

| Flag | Tipo | Obrigatório | Default | Descrição |
|---|---|---|---|---|
| `--source` | Path | sim | — | `.idml` original (PT). |
| `--translated` | Path | sim | — | `.idml` traduzido a auditar. |
| `--json` | Path | não | — | Se fornecido, grava o `CompletenessReport` completo em JSON. |

**Checagens** (todas via `zipfile` + `lxml`, função `check_completeness` em `idml_to_md/translation/completeness_checker.py`):

1. Inventário do pacote: nº de entradas, `Stories/*` e `Spreads/*` batem.
2. Boa-formação de todo `*.xml` do traduzido.
3. IDs `Self` em correspondência 1:1 (nada ausente, extra ou duplicado).
4. Contagens estruturais por story: PSR/CSR/Content/Br + objetos ancorados (Rectangle/TextFrame/Polygon/GraphicLine/Group/Image/Table/Cell).
5. Texto por parágrafo, alinhado 1:1 — **falha** se um parágrafo tinha texto no original e ficou vazio no traduzido (detector primário de perda de conteúdo).
6. Volume total de texto (informativo: `text_ratio`; PT→ES costuma ficar > 1,0).

**Exit codes.**

| Código | Significado |
|---|---|
| 0 | PASS — nada faltando. |
| 1 | FAIL — alguma checagem 1–5 divergiu (detalhes no log/JSON). |
| 2 | `--source` ou `--translated` inexistente. |

**Nota.** Um `PASS` com páginas em branco no PDF indica problema de **layout/overset no InDesign** (texto que não cabe e trava o fluxo), não perda de conteúdo — ver [troubleshooting.md](troubleshooting.md).

## Próximo

[testing.md](testing.md) — como rodar os testes.
