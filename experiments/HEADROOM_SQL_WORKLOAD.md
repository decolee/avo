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

---

## 6. §3f — o piloto de potência, e o que ele desmentiu

Rodado depois de tudo acima, com o alvo congelado. Cinco sessões de `greedy` de
900 s e um `full` de 8 passos, US$ 33,64 no total.

### O braço barato

| semente | ganho | |
|---|---:|---|
| s0 | 5,08× | |
| s3 | 5,44× | |
| s2 | 5,46× | |
| s4 | 5,75× | |
| s1 | 6,36× | |
| **média** | **5,620×** | desvio 0,478, **cv 8,5%**, US$ 2,21 por sessão |

**As cinco passam do headroom que eu havia declarado (4,73×).** Uma sessão única
de quinze minutos supera a escada de dez degraus escrita à mão — o mesmo padrão
que §3e já tinha registrado em três dos cinco alvos anteriores, aqui pela quarta
vez e com a maior margem.

### O braço caro

| passo | ganho | acumulado | veredicto |
|---|---:|---:|---|
| 1 | 5,63× | US$ 3,30 | aceito |
| 2 | 5,88× | US$ 4,94 | aceito |
| 3 | 6,10× | US$ 6,62 | aceito |
| 4 | 6,61× | US$ 7,95 | aceito |
| 5 | 7,21× | US$ 11,07 | aceito |
| 6 | 7,21× | US$ 15,70 | **rejeitado** |
| 7 | 7,21× | US$ 19,93 | **rejeitado** |
| 8 | **7,42×** | US$ 22,61 | aceito, **supervisor disparou** |

Duas observações que valem mais que o número final:

1. **Os passos rejeitados são os mais caros** (US$ 4,63 e US$ 4,22, contra
   US$ 1,32–3,30 dos aceitos). O agente trabalha mais quando não acha ganho, e
   isso é custo real de um platô.
2. **O supervisor quebrou o platô.** Ele disparou uma vez em oito passos,
   exatamente depois das duas rejeições, e o passo seguinte foi aceito. É o
   mecanismo que o paper atribui ao supervisor, observado num run só — n=1, mas
   é a primeira vez que esta bancada o vê acontecer.

### A re-medição pareada, e o que ela corrigiu

Os números acima são do braço medindo o estado final contra uma base tirada até
quinze minutos antes. Re-medidos em pares alternados seed/candidato:

| candidato | não pareado | **pareado** | inflação |
|---|---:|---:|---:|
| `full` s0 (v6) | 7,42× | **6,773× ± 3,7%** | +9,6% |
| `greedy` s1 | 6,36× | **5,648× ± 6,9%** | +12,6% |
| `greedy` s4 | 5,75× | **5,262× ± 1,1%** | +9,3% |

A deriva da máquina inflava tudo entre 9% e 13%. É o defeito 9 da Fase 2A pela
segunda vez, agora antecipado em vez de descoberto depois.

**O headroom declarado passa para 6,77×**, que é o melhor demonstrado por
qualquer meio — 43% acima da escada à mão.

### O dimensionamento

| efeito | delta | n por braço | US$ (os dois braços) |
|---|---:|---:|---:|
| 5% | 0,28× | 45 | 2 054 |
| 10% | 0,56× | 11 | 514 |
| 15% | 0,84× | 5 | 228 |
| 20% | 1,12× | 3 | 128 |

O efeito observado é de **+32% não pareado** e de **+20% a +29% pareado**. Um
efeito nessa faixa pede **n = 3 a 5 por braço**, isto é, **US$ 128 a US$ 228 por
comparação**. Pagável.

O `avo-lab verify` emite aviso aqui, e o aviso está tecnicamente certo e
praticamente errado: ele pergunta quantas sementes detectam **5%**, e 45 é caro
demais. A pergunta de §3f, no texto do próprio documento, é outra — "a diferença
entre os braços que vão rodar é grande comparada ao desvio entre sementes" — e a
diferença que vai rodar é de 20% a 32%, não de 5%. **A limitação é do check, que
fixa 5% em vez de usar o efeito medido.** Deixei o aviso como está de propósito:
mudar o árbitro logo depois de ele reprovar o meu próprio alvo é o padrão que a
regra do laboratório existe para impedir, mesmo quando a mudança tem mérito. A
correção — aceitar um `lab.piloto_efeito_observado` declarado e dimensionar por
ele — fica como recomendação para quem revisar.

## 7. O que o piloto desmentiu no projeto do alvo

O mecanismo 1 de §3g — "Amdahl de propósito", oito artefatos de custo comparável
— **não produziu a fricção que eu projetei**. O passo 1 do `full` reescreveu
**as oito consultas de uma vez** e saltou de 1,00× para 5,63×. A regra "uma
mudança substancial por passo" é uma instrução ao agente, não uma restrição do
alvo, e ele não a seguiu no primeiro passo.

O que produziu os sete passos seguintes foi o mecanismo 2 — os movimentos que se
destravam. As mudanças aceitas depois do v1 são exatamente do tipo previsto:

- **v2** tirou o `WHERE` parcial do índice e acrescentou `status` como coluna, o
  que **permitiu** reescrever q8 como duas leituras index-only. Índice e consulta
  mudando juntos, com o ganho aparecendo só na combinação.
- **v3 e v5** eliminaram materializações intermediárias em q1, q3 e q8.
- **v4** passou a agregar por `sku` antes de juntar `products`, trocando ~42 mil
  buscas por algumas centenas.
- **v6** consolidou três transformações e, entre elas, **desfez** `ROW_NUMBER` em
  q7, `UNION` em q5 e a anti-junção de q4 — três das minhas próprias escolhas de
  referência. A escada já tinha medido a de q5 como negativa (0,968×); o agente
  chegou às três de forma independente.

Vale registrar que o v6 diz, no resumo do commit, "vence 6 de 6 pares alternados
de `./avo-eval`". O agente adotou a medição pareada por conta própria, seguindo
`kb/20-medicao.md`. A KB funcionou.

**A conclusão de projeto, corrigida:** largura em artefatos não cria fricção
sozinha — um agente com contexto suficiente atravessa todos de uma vez.
Profundidade em *interações* cria. O `sql_workload` acabou sendo um alvo bom pela
segunda razão, não pela primeira, e §3g foi reescrito para dizer isso.
