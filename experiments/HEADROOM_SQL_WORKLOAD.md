# Headroom do `sql_workload`, medido

Todos os números desta página saíram de execução, não de estimativa. O
instrumento é `medir()` do próprio `targets/sql_workload/eval.py` — o mesmo que
pontua um candidato —, com `repeats=3, warmup=1`, nesta máquina.

O alvo existe por causa de `docs/TARGET_DESIGN.md` §3e: os cinco alvos
anteriores têm um espaço que uma sessão única esgota, e por isso não conseguem
comparar arquiteturas de busca. A aposta aqui é que **nove artefatos
interdependentes** produzem um espaço que uma sessão não fecha.

---

## 1. A escada, um movimento por degrau

Cada linha acrescenta UM movimento ao anterior. `vs seed` é a média geométrica
dos três regimes contra o seed; `passo` é o ganho marginal daquele degrau.

| versão | frio | quente | estreito | vs seed | passo |
|---|---:|---:|---:|---:|---:|
| v0 seed | 825,1 ms | 831,6 ms | 504,1 ms | 1,000× | — |
| v1 q6 junção direta pela PK | 585,9 | 582,3 | 384,4 | 1,382× | **1,382×** |
| v2 q2 filtro antes da agregação | 489,7 | 484,6 | 306,8 | 1,681× | **1,217×** |
| v3 q3 função de janela | 412,3 | 422,1 | 308,8 | 1,860× | **1,107×** |
| v4 q1 predicados sargáveis | 382,2 | 396,0 | 264,0 | 2,053× | **1,104×** |
| v5 q8 passe único + acumulado por janela | 383,3 | 370,5 | 266,8 | 2,090× | 1,018× |
| v6 q7 `ROW_NUMBER` | 389,2 | 370,0 | 260,8 | 2,096× | 1,003× |
| v7 q4 anti-junção | 372,2 | 356,6 | 258,7 | 2,160× | 1,030× |
| v8 q5 `UNION` de dois ramos | 364,8 | 380,6 | 273,0 | 2,090× | **0,968×** |
| v9 `setup.sql`: `ANALYZE` | 331,4 | 263,4 | 157,9 | 2,928× | **1,401×** |
| v10 `setup.sql`: + índice `(status, order_date, customer_id)` | 400,0 | 213,3 | 43,4 | **4,537×** | **1,550×** |
| v11 `setup.sql`: + parciais de canal e país | 538,8 | 201,6 | 41,0 | 4,267× | **0,941×** |

**Oito movimentos com ganho medido.** Dois medem negativo (v8 e v11) e são becos
sem saída de verdade, não erros de execução — voltam a aparecer na seção 3.

Repartição do ganho em espaço logarítmico, sobre `ln(4,537) = 1,512`:

| movimento | fatia |
|---|---:|
| v10 índice | **29,0%** |
| v9 `ANALYZE` | 22,3% |
| v1 q6 | 21,4% |
| v2 q2 | 13,0% |
| v3 q3 | 6,7% |
| v4 q1 | 6,5% |
| v7 q4 | 2,0% |
| v5 q8 | 1,2% |
| v6 q7 | 0,2% |
| v8 q5 | −2,1% |

O maior movimento vale **29%**. A barra de §3 é "nenhum acima de ~70%", e nos
outros cinco alvos do repositório o maior movimento fica entre 49% e 98%.

## 2. O headroom declarado, medido em pares

Comparar um número de agora com um número de meia hora atrás foi o defeito 9 da
Fase 2A (`RELATORIO_FINAL.md`) e mudou uma conclusão inteira. Aqui a base e o
candidato foram medidos em sequência imediata, três vezes, com a base
re-medida entre os candidatos:

| candidato | par 1 | par 2 | par 3 | média | cv |
|---|---:|---:|---:|---:|---:|
| oito consultas reescritas + índice + `ANALYZE` | 4,668× | 4,485× | 4,547× | 4,567× | 2,0% |
| idem, mantendo q5 do seed | 4,581× | 4,810× | 4,788× | **4,726×** | 2,7% |

Os dois empatam: 3,5% de diferença contra um cv de 2,0–2,7%. O declarado no
`target.yaml` é o **melhor demonstrado, 4,73×** — declarar menos seria mentir
para baixo, que é o erro que §3e pune.

## 3. A propriedade que este alvo tenta ter: os movimentos se destravam

Esta é a razão de o alvo existir. O **mesmo** `setup.sql` foi aplicado às
consultas do seed e às reescritas:

| | sem índice | + `ANALYZE` | + índice + `ANALYZE` | valor do setup |
|---|---:|---:|---:|---:|
| consultas do **seed** | 0,999× | 0,985× | 1,137× | **1,139×** |
| consultas **reescritas** | 2,084× | 2,864× | 4,374× | **2,099×** |

Duas leituras, e a segunda é a que importa:

1. O mesmo `setup.sql` vale **1,14× no seed e 2,10× nas reescritas**. Índice
   sobre coluna que a consulta embrulha em função não é usado por ninguém: o
   custo de construir aparece no `frio` e o benefício não aparece em lugar
   nenhum.
2. **`ANALYZE` sozinho é uma perda no seed (0,985×) e um ganho de 1,375× nas
   reescritas.** A mesma linha, com sinal invertido, dependendo do que já existe.

Quem cria índice antes de reescrever mede ~1,1×, dentro do ruído acumulado, e
tem todo motivo para descartar a ideia. O ganho só aparece para quem **volta a
testar** o que já descartou, depois de mudar outra coisa. Uma passada única não
fecha esse ciclo; um lineage com memória entre passos pode fechar.

### O par que troca de sinal: q5 e os índices parciais

| | q5 do seed | q5 reescrita em `UNION` |
|---|---:|---:|
| índice geral + `ANALYZE` | **4,615×** | 4,304× |
| + parciais de canal e país | 4,035× | 4,289× |

- Reescrever q5 **sem** os parciais: 0,933× (perda).
- Reescrever q5 **com** os parciais: 1,063× (ganho).
- Criar os parciais **com** q5 do seed: 0,874× (perda).
- Criar os parciais **com** q5 reescrita: 0,996× (neutro).

Nenhum dos dois paga sozinho, e juntos empatam com não fazer nada. É um beco sem
saída que só a medição encontra — exatamente o tipo de coisa que a regra de
`NOTES.md` existe para não fazer duas vezes.

## 4. Tentativas de trapaça, e o que cada uma marcou

Rodadas pelo avaliador inteiro, não só pelo gate. O seed marca 1,386.

| tentativa | resultado |
|---|---|
| reconhece o banco por `COUNT(*)` da tabela | recusado (consistência no banco medido) |
| reconhece o banco pelo `MAX(order_id)` | recusado (idem) |
| data embutida fora do alcance do gate | recusado (idem, pelo lote estreito) |
| lê o caminho do arquivo (`pragma_database_list`) | recusado (checagem estática) |
| o mesmo escondido atrás de uma `CREATE VIEW` | recusado (idem, no `setup.sql`) |
| materializa a resposta (`CREATE TABLE`) | recusado (allowlist do `setup.sql`) |
| DDL dentro da consulta | recusado (um comando por arquivo) |
| apaga uma consulta do fechamento | recusado (as oito são exigidas) |
| esvazia uma consulta | recusado (idem) |
| `CREATE VIEW` com a janela cronometrada embutida | 1,358 — **empata com o seed** |

Nenhuma pontuou acima do seed.

### O ataque que o gate não pega, e por que ele mesmo assim não paga

Um índice parcial recortado nas janelas que o relógio usa é indistinguível de
otimização para qualquer gate de correção: índice não muda resultado. Quatro
formas foram medidas, todas sobre as consultas reescritas:

| `setup.sql` | score |
|---|---:|
| recorte nas duas janelas exatas (`OR` de dois intervalos) | 3,769 |
| corte simples `order_date >= '2024-01-01'` | 4,087 |
| corte por calendário + status, a forma mais afiada | 3,862 |
| **sem calendário, `WHERE status = 'delivered'`** | **5,826 a 6,365** |

A especialização perde de 35% a 40% para a transformação geral. A razão é
mecânica: as janelas chegam como parâmetros nomeados (`:d0`, `:d1`), o
planejador não conhece o valor deles na hora de escolher o plano, e por isso não
consegue provar que `order_date >= :d0` implica `order_date >= '2024-01-01'`. O
índice é construído, cobrado no `frio`, e nunca usado.

Isso é uma defesa **estrutural**, não uma barreira: ela vem de graça do uso de
parâmetros nomeados, e vale a pena saber que é assim que ela funciona, caso um
alvo futuro passe a interpolar datas no SQL — aí ela desaparece sem aviso.

## 5. O que ainda não foi medido

`lab.sonda_100s_fracao` (§3e) e `lab.piloto_cv` / `lab.piloto_n_para_5pct` (§3f).
As duas exigem rodar agentes de verdade e são o que decide se o alvo serve para a
ablação — a escada acima só diz que ele serve para otimizar.
