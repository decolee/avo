# RESULTS — `etl_agg`, run `etl_agg-20260901-070620`

**Data:** 2026-09-01 · **Harness:** `f6dad9e6` (fixado) · **Modo:** sessão
**Passos:** 6 de 15 — parou por platô declarado, não por limite
**Máquina:** container Linux, 4 vCPU

## Lineage

| ver | primary | Δ | Δ% | resumo |
|---|---|---|---|---|
| 0 | 4,225 | — | — | seed `x_0` |
| 1 | 6,416 | +2,191 | **+51,9%** | passe único com acumulador em lista |
| 2 | 11,280 | +4,864 | **+75,8%** | extração dirigida dos 5 campos de 16 |
| 3 | 13,195 | +1,915 | **+17,0%** | busca inline com retomada do offset |
| 4 | 14,670 | +1,474 | +11,2% | `startswith` no lugar de fatiar o status |
| 5 | **15,305** | +0,635 | +4,3% | `defaultdict` no lugar de `get`+branch |

**Ganho total: +262,2% sobre o seed (3,62×).** A baseline
(`referencia_passe_unico`, 6,112) foi ultrapassada na v2 e ficou 150,4% atrás no
final.

## A forma da curva

Duas fases nítidas:

**v1–v3 — parar de fazer trabalho desnecessário.** +52%, +76%, +17%. Cada uma
remove uma categoria inteira de custo: materializar grupos, materializar os 16
campos do registro para usar 5, chamar função por campo.

**v4–v5 — micro-otimização.** +11% e +4%, e ambas medidas de novo com 5 rodadas
intercaladas deram +3,2% e +3,0% — no limiar de ruído que `kb/20-medicao.md`
define como empate. Submeti as duas descritas como o que são.

Isso reproduz em miniatura o que o paper relata: melhoria em saltos discretos,
retornos decrescentes, e platôs entre eles.

## Passos rejeitados pelo framework

**Nenhum.** 5 de 5 submissões aceitas.

Esse número precisa de contexto para não enganar. O `./avo-eval` é livre dentro
do passo, e eu o usei: explorei **16 direções** e submeti 5. A razão real é
**5/16 = 31%**, não 100%. O paper reporta ~8% (500+ direções, 40 commits), e a
diferença restante é esperada — este run cobre os primeiros passos, onde o
headroom óbvio ainda não acabou.

Uma razão de aceitação de 100% sobre as *submissões* é o normal quando o
operador mede antes de submeter. O número que diz alguma coisa sobre a busca é
o de direções exploradas.

## Direções medidas e rejeitadas por mim

Estão detalhadas no `NOTES.md`. As duas que importam:

**Processamento em bytes.** Primeira medição deu **+6,90%** e eu quase commitei.
O regime `wide` veio com ±18,2% de variação, medi de novo, e o A/B lado a lado
mostrou que a versão em bytes é **ligeiramente pior**. O +6,90% era ruído. Sem a
segunda medição, uma regressão teria entrado no lineage como melhoria.

**Regex única assumindo ordem de campos: +28,6%.** É o maior ganho isolado
disponível neste ponto, muito acima do ruído, e **não commitei**. Testei três
formas de obter o ganho sem a suposição de ordem (`finditer` global, cinco
regexes, alternação de nomes): +7,6%, −22,6%, −46,2%. O ganho *é* a suposição.

`kb/10-performance.md` nomeia exatamente isso como o risco do parsing dirigido,
e `kb/00-contrato.md` não coloca ordem de campo no contrato.

## O achado do run — um buraco no alvo, não no candidato

**O gate não distingue um candidato que assume ordem de campos de um que não
assume.** `gate_adv.jsonl` e os `perf_*.jsonl` saem do mesmo gerador, com a mesma
ordem. A variante de +28,6% passa no gate com folga.

O gate existe para achar suposições sobre a forma do dado, e esta ele não acha.
Não é consertável no meio do run — mexer no `gate_adv` muda `f` e invalida a
comparação entre as versões já commitadas. Fica para a Sessão 2.

Vale notar como o buraco apareceu: não por leitura do `eval.py`, mas por tentar
otimizar de verdade e esbarrar nele. É o mesmo padrão das cinco falhas do
`README` — o gate parecia sólido até alguém ter um motivo para empurrá-lo.

## Onde a curva estagnou, e por quê

Na v5. Três micro-otimizações testadas depois dela — içar globais para locais
(+0,2%), buffer de 1 MB (−2,5%), as duas juntas (+0,5%) — todas dentro do ruído.

Sobrou por linha: cinco `find`, três fatiamentos, duas conversões numéricas, uma
concatenação de chave, um acesso a dicionário, quatro atualizações de lista.
Nenhuma removível sem assumir algo sobre a forma do registro.

**O platô é de headroom defensável, não de ideias.** As ideias existiam e foram
medidas. O que acabou foi o que dá para fazer sem trocar generalidade por
velocidade.
