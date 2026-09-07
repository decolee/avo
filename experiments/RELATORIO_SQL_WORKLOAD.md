# `sql_workload` — o alvo difícil, e o que ele mediu

**Data:** 2026-09-04 · **Custo total:** US$ 34,17 (piloto US$ 33,64 + sonda ~US$ 0,53)
· **Veredicto:** o alvo serve, e é o primeiro da bancada em que o `full` se separa
do `greedy` por uma margem que o orçamento resolve.

---

## 1. O que é

Oito relatórios SQL independentes sobre um esquema físico compartilhado — o
fechamento noturno de uma loja. O candidato evolui **nove artefatos**: as oito
consultas e o `setup.sql` (índices, views, `ANALYZE`).

Cada relatório tem um defeito de plano **diferente** no seed: predicado
não-sargável, agregação antes do filtro, ranking por auto-junção, anti-junção
correlacionada, `OR` entre colunas, `CAST` na coluna de junção, `MIN`
correlacionado, varredura por dia.

Três regimes, que são três **seletividades** e não três repetições:

| regime | o que roda | quanto da tabela casa |
|---|---|---|
| `frio` | `setup.sql` + lote trimestral, banco virgem | ~12% |
| `quente` | lote trimestral, banco preparado | ~12% |
| `estreito` | lote quinzenal, canal e país raros | < 1% |

O score é a média geométrica dos três. `frio` cobra a construção do índice;
`estreito` a recompensa. As duas pressões se opõem de propósito.

### Por que este alvo existe

`RELATORIO_FINAL.md` fechou a Fase 2A com um resultado nulo e uma recomendação:
o gargalo da bancada era §3e — nos cinco alvos existentes, uma sessão única
captura de 46% a 254% do headroom, e um espaço que uma sessão esgota não
distingue arquiteturas de busca. Este alvo foi projetado de trás para frente a
partir dessa falha.

---

## 2. As nove propriedades, com número

| # | propriedade | resultado |
|---|---|---|
| 1 | gate com mordida | **27 mutantes rejeitados** — o maior número do repositório (sql_agg: 21) |
| 2 | custo dimensionado | seed 8,0 s · execução mais rápida 35 ms — dentro dos limites |
| 3 | headroom graduado | **6,77×** · 8 movimentos na escada à mão · maior movimento 29% |
| 3b | medição não trapaceável | 10 ataques rodados pelo avaliador inteiro; nenhum pontuou acima do seed |
| 3c | propriedades acidentais | 4 enumeradas, viradas em contrato declarado, com asserção nos dois bancos |
| 3d | total e distribuição | total 6,77× e maior fatia 29% — os dois ao mesmo tempo |
| 3e | sonda de 100 s | 0% do headroom (mas ver §5: a sonda é curta demais aqui) |
| 3f | poder medido | **cv 8,5%; efeito de 20–32%; n = 3 a 5 por braço** |
| 4 | score diagnóstico | 3 seletividades com pressões opostas |

`make verify`: **verde, 6 alvos**. `avo-lab verify`: tudo `ok` menos um aviso em
§3f, tratado em §6.

---

## 3. A escada medida à mão

Uma versão por movimento, cumulativa, medida com o próprio avaliador:

| versão | vs seed | passo |
|---|---:|---:|
| v0 seed | 1,000× | — |
| v1 q6 junção direta pela PK | 1,382× | **1,382×** |
| v2 q2 filtro antes da agregação | 1,681× | **1,217×** |
| v3 q3 função de janela | 1,860× | 1,107× |
| v4 q1 predicados sargáveis | 2,053× | 1,104× |
| v5 q8 passe único | 2,090× | 1,018× |
| v6 q7 `ROW_NUMBER` | 2,096× | 1,003× |
| v7 q4 anti-junção | 2,160× | 1,030× |
| v8 q5 `UNION` | 2,090× | **0,968×** |
| v9 `ANALYZE` | 2,928× | **1,401×** |
| v10 + índice | **4,537×** | **1,550×** |
| v11 + parciais de canal e país | 4,267× | **0,941×** |

Oito movimentos com ganho, o maior valendo 29% do ganho em log. Dois medem
**negativo** — a reescrita de q5 e os índices parciais — e são becos sem saída de
verdade, não erros de execução.

### A propriedade que o alvo foi construído para ter

O **mesmo** `setup.sql`, aplicado a dois candidatos diferentes:

| | consultas do seed | consultas reescritas |
|---|---:|---:|
| índice + `ANALYZE` | **1,14×** | **2,10×** |
| `ANALYZE` sozinho | **0,985×** (perda) | **1,375×** |

Índice sobre coluna que a consulta embrulha em função não é usado por ninguém: o
custo de construir aparece no `frio` e o benefício não aparece. Quem cria índice
antes de reescrever mede ruído e tem todo motivo para descartar a ideia.

---

## 4. O piloto: `greedy` × `full`

### Braço barato — 5 sessões de 900 s, US$ 2,21 cada

5,08× · 5,44× · 5,46× · 5,75× · 6,36× → **média 5,620×, desvio 0,478, cv 8,5%**

**As cinco superam o headroom de 4,73× que eu havia declarado.** Uma sessão de
quinze minutos bate uma escada de dez degraus escrita à mão. É a quarta vez que
isso acontece nesta bancada, e a de maior margem.

### Braço caro — 8 passos, US$ 22,61, 76 min

| passo | ganho | veredicto |
|---|---:|---|
| 1 | 5,63× | aceito |
| 2 | 5,88× | aceito |
| 3 | 6,10× | aceito |
| 4 | 6,61× | aceito |
| 5 | 7,21× | aceito |
| 6 | 7,21× | **rejeitado** |
| 7 | 7,21× | **rejeitado** |
| 8 | **7,42×** | aceito, **supervisor disparou** |

Duas rejeições seguidas, o supervisor entra, e o passo seguinte quebra o platô.
É o mecanismo que o paper atribui ao supervisor (§4.2), observado pela primeira
vez nesta bancada. **n=1: não prova nada, mas é a primeira ocorrência.**

Os passos rejeitados foram os **mais caros** (US$ 4,63 e US$ 4,22 contra
US$ 1,32–3,30 dos aceitos). Um platô não é ausência de gasto.

### A re-medição pareada

| candidato | não pareado | **pareado** | inflação |
|---|---:|---:|---:|
| `full` s0 | 7,42× | **6,773× ± 3,7%** | +9,6% |
| `greedy` s1 | 6,36× | **5,648× ± 6,9%** | +12,6% |
| `greedy` s4 | 5,75× | **5,262× ± 1,1%** | +9,3% |

A deriva da máquina inflava tudo entre 9% e 13%. É o defeito 9 da Fase 2A pela
segunda vez — desta vez antecipado.

### O efeito

**+32% não pareado, +20% a +29% pareado.** Contra os 5% que a Fase 2A tentou
detectar no `sql_agg` e não conseguiu.

| efeito | n por braço | US$ por comparação |
|---|---:|---:|
| 20% | 3 | 128 |
| 15% | 5 | 228 |
| 10% | 11 | 514 |

---

## 5. O que o alvo desmentiu do próprio projeto

A tese era que **largura** — oito artefatos de custo comparável — criaria a
fricção que uma sessão não vence. **Está errada.** O passo 1 do `full` reescreveu
as oito consultas de uma vez e saltou para 5,63×. "Uma mudança substancial por
passo" é uma instrução ao agente, não uma restrição do alvo.

O que sustentou os sete passos seguintes foi a **profundidade em interações**:

- **v2** tirou o `WHERE` parcial do índice e acrescentou `status` como coluna, o
  que **permitiu** reescrever q8 como leitura index-only. Índice e consulta
  mudando juntos, com o ganho só na combinação.
- **v4** passou a agregar por `sku` antes de juntar `products` — 42 mil buscas
  viraram algumas centenas.
- **v6 desfez** `ROW_NUMBER` em q7, `UNION` em q5 e a anti-junção de q4 — três
  escolhas da minha própria referência. A escada já tinha medido a de q5 como
  negativa; o agente chegou às três de forma independente.

E o v6 registra "vence 6 de 6 pares alternados de `./avo-eval`": **o agente
adotou a medição pareada por conta própria**, seguindo `kb/20-medicao.md`. A KB
funcionou como K deveria funcionar — ensinou o método, não a resposta.

A sonda de 100 s mediu 0,98× — zero. Isso **não** é evidência de dificuldade: uma
avaliação custa 14 s aqui, e cem segundos não cobrem nem a leitura da KB. **A
sonda de §3e não é livre de escala**, e isso agora está escrito no documento.

---

## 6. O aviso do `avo-lab verify`, e por que ele fica

O check de §3f pergunta quantas sementes detectam **5%** — 45, "caro demais". O
efeito medido é de 20–32%, que pede n=3–5. A limitação é do check, que fixa 5% em
vez de usar o efeito observado; o texto de §3f diz que a pergunta certa é "a
diferença entre os braços **que vão rodar**".

**Não mexi no árbitro.** Mudar o check logo depois de ele reprovar o meu próprio
alvo é o padrão que a regra do laboratório existe para impedir, mesmo quando a
mudança tem mérito. A correção — aceitar um `lab.piloto_efeito_observado` e
dimensionar por ele — fica como recomendação para quem revisar.

> **Atualização 2026-09-07.** A correção foi feita, depois de a ablação fechar e
> ser publicada — não com o experimento em curso. O campo chama-se
> `lab.piloto_efeito_alvo` e o n sai por `n(d) = n(5%)·(0,05/d)²`; sem a
> declaração, o comportamento é o de antes, e os outros cinco alvos não mudaram
> de veredito. O `sql_workload` declara 30% e passa com n=2. O aviso desta seção
> não existe mais, e a ordem em que isso aconteceu é o ponto.

---

## 7. Defeitos do instrumento encontrados nesta sessão

Somam-se aos doze do `RELATORIO_FINAL.md` — que **não está no repositório**, de modo que a numeração 1–12 não é auditável. O registro consolidado, com o
defeito 17 (o detector de sessão cega), está em `DEFEITOS.md`.

**13. O prompt do braço barato nomeava só o `entrypoint`.** Dizia "Otimize
`work/setup.sql`" — o menos importante dos nove arquivos. O braço `full` recebe o
prompt do harness, que não nomeia arquivo, então o viés seria **assimétrico**,
entre os dois braços que o piloto compara. Corrigido antes de gastar: a fonte da
verdade passou a ser o conteúdo do `seed/`. Afetava também o `sql_agg`, cujo
prompt nomeava `query.sql` e omitia `setup.sql` da linha de abertura.

**14. O container é recuperado após ~20 min de sessão ociosa.** Matou o piloto
duas vezes. Check-in a cada 45 minutos garantia que ele morresse entre um e
outro. A solução foi manter a sessão aquecida com monitores curtos; o piloto já
retomava do `piloto.jsonl` sozinho, e foi só por isso que nada se perdeu.

**15. Disco a 97%, 1,5 GB livres.** 138 diretórios temporários órfãos — cópias do
banco de 38 MB deixadas por processos de medição mortos antes de limpar. Limpeza
liberou 28 GB. Um `tempfile.TemporaryDirectory` não sobrevive a um `SIGKILL`, e
uma bancada que mata processos precisa limpar o rastro.

**16. `pgrep -f "piloto.py"` casa com a própria linha de comando do grep.**
Reportei o piloto vivo quando ele estava morto havia meia hora. Use
`ps | grep "[p]iloto.py"`.

---

## 8. Recomendação

**Rodar a ablação neste alvo, com n=5 por braço.**

O raciocínio, em três linhas:

1. O efeito medido (20–32%) é **quatro a seis vezes maior** que o que a Fase 2A
   tentou detectar no `sql_agg` (5%) e não conseguiu.
2. Com cv de 8,5%, n=5 detecta 15% a 5% de significância e 80% de poder. Isso é
   **US$ 228 por comparação de dois braços** — contra os US$ 3.000 que o
   `csv_normalize` pediria.
3. O piloto já mostrou o supervisor quebrando um platô. Se a ablação for de
   componentes (com/sem supervisor, com/sem lineage), há um mecanismo concreto
   para medir, e não só uma diferença agregada.

**O que NÃO recomendo:** tratar os 6,77× como teto. O `full` estava ainda subindo
quando os oito passos acabaram — o passo 8 ganhou 2,9% e foi aceito. O teto real
deste alvo não é conhecido, e a declaração de `lab.headroom_medido` deve ser
revista de novo depois de qualquer run mais longo.

**Ressalva honesta:** tudo em §4 do braço caro é **n=1**. A trajetória, o platô, o
supervisor e o custo por passo são de um único run. O que tem n=5 é o braço
barato. O piloto foi dimensionado para medir variância, não para testar hipótese
— e nada aqui é resultado de ablação.
