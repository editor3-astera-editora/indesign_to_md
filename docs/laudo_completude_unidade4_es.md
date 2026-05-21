# Laudo — "Unidade 4 ausente" na tradução ES (81 Matemática Financeira)

**Data:** 2026-05-20
**Sintoma relatado:** ao abrir o `.idml` traduzido (`out/81-matematica-financeira/81-matematica-financeira_es.idml`) no InDesign via *File > Open* e exportar o PDF, a **Unidade 4 some** e há **páginas em branco da 103 em diante**.
**Pergunta investigada:** *tudo que está no XML original está no XML traduzido?*

## Conclusão

**SIM — o XML traduzido está 100% completo. Nenhum conteúdo do original foi perdido.**
As páginas em branco **não** são causadas por perda de conteúdo na tradução; são um
problema de **layout/overset no InDesign** (texto ES mais longo que deixa de caber e trava
o fluxo de texto).

## Evidências

Comparação `Indesign_exemplos/81_Matemática Financeira.idml` (PT) vs.
`out/81-matematica-financeira/81-matematica-financeira_es.idml` (ES):

| Checagem | Resultado |
|---|---|
| Inventário do pacote | 351 entradas / **256 Stories** / 75 Spreads — idêntico |
| XML bem-formado | 0 entradas malformadas |
| IDs `Self` (todas as entradas) | mapeamento **1:1** — 0 ausente, 0 extra, 0 duplicado |
| Contagens por story (PSR/CSR/Content/Br + âncoras) | **iguais** nas 256 stories |
| Fluxo principal `u1f81d` (corpo do livro) | Content 1500=1500, Br 1240=1240, Rectangle 207, TextFrame 179, Polygon 345, GraphicLine 190, Group 160, Image 54, PSR 997, CSR 1427 — todos iguais |
| Texto por parágrafo (997 PSRs, alinhados 1:1) | **0** parágrafos com texto no original e vazios no traduzido; último parágrafo com texto no mesmo índice (996) |
| Volume de texto | ES **1,044×** o PT (190.757 vs 182.806 chars) — expansão normal PT→ES |

Reproduzível com o gate de QA:

```bash
python scripts/verify_translation_completeness.py \
  --source "Indesign_exemplos/81_Matemática Financeira.idml" \
  --translated "out/81-matematica-financeira/81-matematica-financeira_es.idml"
# → PASS — OK — nada faltando. 256 stories, texto 1.044x do original.
```

O `out/entrega_es/...idml` também passa (mesma completude).

## Por que as páginas ficam em branco (causa real)

- Todo o corpo do livro é **um único fluxo de texto** (story `u1f81d`) encadeado por
  **140 frames**, cobrindo as **páginas 6–148**. A Unidade 4 é a **cauda** desse fluxo.
- Os frames das páginas 103+ **existem** e o texto traduzido é **mais longo** — logo o
  conteúdo está presente; o que ocorre é o InDesign **parar de compor** o fluxo num ponto
  e deixar todos os frames seguintes vazios. Essa é a assinatura exata de
  *"branco da página X em diante"* — um **overset em cascata**.
- Como o `idml_writer` só troca o `.text` dos `<Content>` (nunca mexe em `Self`,
  atributos, `<Br/>`, âncoras ou estrutura — confirmado por auditoria), a única variável
  que mudou é o **comprimento do texto** (+4,4%). Candidatos concretos a travar a coluna
  após a expansão: as **14 tabelas** do fluxo (algumas 13×4, 11×2, que crescem com o texto
  ES) e **figuras ancoradas de até ~página inteira (681 pt)** deslocadas para onde não
  cabem mais.

## Como corrigir no InDesign

1. Abrir o `.idml` traduzido no InDesign.
2. **Window > Output > Preflight** → procurar o erro **Text → Overset text**;
   duplo-clique salta direto ao frame com overset.
3. Ir à **página ~103** e localizar o frame com o **"+" vermelho** na porta de saída
   (out-port). O objeto/parágrafo logo após o último conteúdo visível é o gargalo
   (provável tabela ou figura ancorada que cresceu).
4. Resolver o overset, por exemplo:
   - **Text Frame Options > Auto-Size** para o frame poder crescer; ou
   - reduzir a tabela/figura (corpo da fonte, escala da imagem); ou
   - ajustar **Keep Options** do parágrafo (evitar bloco maior que a coluna); ou
   - encurtar levemente o texto ES naquele trecho.
5. Re-exportar o PDF e conferir a Unidade 4 visível.

## Prevenção (próximos livros)

Rodar `scripts/verify_translation_completeness.py` como gate antes da entrega garante que
qualquer **perda real de conteúdo** (regressão no writer) seja detectada automaticamente.
Overset é um efeito de **diagramação**, fora do escopo do verificador — só é determinável
compondo no InDesign; fica como possível melhoria futura uma heurística de risco de overset.
