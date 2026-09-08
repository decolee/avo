# O andaime não paga — os artefatos

## As quatro peças

| arquivo | o que é | páginas | para quem |
|---|---|---|---|
| `completo.html` | **o relatório completo** — 23 seções, 13 figuras, 11 tabelas | — | quem vai auditar o trabalho |
| `AVO-o-andaime-nao-paga-COMPLETO.pdf` | o mesmo, com capa, sumário e numeração | **26** | apresentação, anexo, impressão |
| `index.html` + `AVO-o-andaime-nao-paga.pdf` | a versão curta, 11 seções, 4 figuras | 9 | leitura rápida |
| `promo.html` | resumo executivo de uma página | — | quem decide onde investir esforço |

Os quatro arquivos são autossuficientes: abra o `.html` no navegador ou o `.pdf`
direto. Não há dependência externa — as figuras são SVG inline e as fontes têm
fallback declarado.

## As treze figuras, e de onde cada uma sai

| # | figura | fonte |
|---|---|---|
| 1 | O loop e as quatro peças ablacionadas | `ablacao_sql_workload/results.jsonl` |
| 2 | A bateria anti-trapaça (log) | `REWARD_HACKING.md`, `tests/test_anticheat.py` |
| 3 | Inventário dos seis alvos | `targets/*/target.yaml`, bloco `lab` |
| 4 | **Retornos decrescentes por passo** | 160 passos da Ablação 2 |
| 5 | Distribuição dos 51 runs | as três `results.jsonl` |
| 6 | A escada de headroom | `HEADROOM_SQL_WORKLOAD.md` §1 |
| 7 | A propriedade de destravamento | `HEADROOM_SQL_WORKLOAD.md` §3 |
| 8 | Gráfico de floresta dos nove contrastes | todas as `results.jsonl` + `greedy.jsonl` |
| 9 | O eixo do modelo pareado por dólar | `remedido_modelo.jsonl` |
| 10 | Trajetórias de busca | `dolar_sonnet_36p/piloto.jsonl` |
| 11 | A deriva do denominador (defeito 18) | `remedido_modelo.jsonl` |
| 12 | O preço de cada pergunta | derivada: `n ≈ 2·(2,8·s/Δ)²` |
| 13 | Eficiência por dólar | `ablacao_sql_workload/results.jsonl` |

## O que só existe na versão completa

- **§05 A bateria anti-trapaça** — os nove candidatos, e o que quase escapou (t5, 16,38)
- **§07 Generalidade** — o mesmo harness em três domínios, incluindo um onde `f` é F1 e não velocidade
- **§08 A dinâmica da busca** — o passo 1 entrega 439,6 % e o passo 8 entrega 3,9 %; é a explicação
  mecânica mais provável para os nulos, e não aparecia em nenhum relatório anterior
- **§10–11 A escada de headroom e o destravamento** — como o `sql_workload` foi construído de trás
  para frente a partir da §3g
- **§16 Eficiência por dólar** — o braço completo não é o mais eficiente
- **§19 A matriz de decisão** — doze linhas de «o que fazer quando», cada uma com o número e a seção
  que a sustentam

## Como o PDF é gerado

```
python3 /tmp/print_full.py     # monta print-completo.html a partir de completo.html
python3 /tmp/topdf.py          # Chromium via Playwright, A4, rodapé numerado
```

As figuras são SVG inline, então entram vetoriais no PDF.

## O enquadramento

O resultado principal é **negativo** e o relatório abre com isso. Três experimentos e US$ 976 não
distinguiram nenhum componente do AVO do ruído; o quarto, de US$ 82, achou +28,7 % no eixo do modelo.
A §21 (Limitações) é a mais longa do documento por decisão, e a §20 calcula o preço da resposta que
não foi comprada.

Um relatório que afirmasse mais do que os dados sustentam seria desmentido pelo primeiro leitor que
abrisse um `jsonl` — e os `jsonl` estão no mesmo repositório.
