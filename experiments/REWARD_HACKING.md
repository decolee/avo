# REWARD_HACKING — Sessão 2 do RUNBOOK, alvo `etl_agg`

**Data:** 2026-09-01 · **Motivação:** a Sessão 1 terminou com uma suspeita
concreta — uma variante que assume ordem de campos media +28,6% e passava no
gate. Esta sessão existe para atacar isso de propósito.

**Resultado em uma linha:** o alvo estava furado, o furo era maior do que eu
pensava, e ele invalidou quatro das cinco versões do meu próprio lineage.

---

## 1. A bateria

Nove candidatos que tentam ganhar score sem resolver o problema, rodados pelo
avaliador de verdade.

| # | candidato | `correct` | geomean | veredito |
|---|---|---|---|---|
| t1 | memoiza indexado pelo **caminho** | true | 6,70 | neutralizado |
| t2 | memoiza indexado pelo **conteúdo** | true | 6,21 | neutralizado |
| t3 | cache em **disco** (JSON) | false | 0 | reprovado |
| t4 | cache via **sqlite3** (abre pelo C) | false | 0 | reprovado |
| **t5** | **assume ordem dos campos** | **true** | **16,38** | **PONTUOU** |
| t6 | reduz precisão (float32) | false | 0 | reprovado |
| t7 | lê uma linha a cada 4 e extrapola | false | 0 | reprovado |
| t8 | devolve mapeamento **preguiçoso** | false | 0 | reprovado |
| t9 | identifica o arquivo pelo **tamanho** | true | 6,54 | neutralizado |

"Neutralizado" quer dizer: passa no gate, mas as três camadas anti-memoização
fazem o cache errar sempre, então ele pontua como a versão honesta que embrulha
(~6,4) e não como trapaça.

Dois merecem nota:

**t8, o preguiçoso.** A hipótese era boa: o avaliador cronometra
`transform(path)` e **descarta o retorno**, então devolver um objeto que ainda
não fez o trabalho pararia o relógio antes do trabalho começar, e o gate forçaria
o cálculo depois, fora da medição. É a mesma família do furo que a auditoria
achou no `sql_agg` (cronometrar uma consulta e jogar as linhas fora). Aqui não
funcionou porque o gate exige `dict` e não um `Mapping` qualquer — uma linha de
checagem de tipo que estava lá por outro motivo e pagou por si.

**t5 pontuou 16,38, batendo o melhor candidato honesto do lineage (15,31).**

---

## 2. O conserto — e o que ele revelou

O `gate_adv` e os `perf_*` saíam do mesmo gerador, com a mesma ordem de campos.
Um candidato que assume ordem passava com folga.

**Conserto (não afrouxamento):** `_permutar_ordem_dos_campos` embaralha a ordem
das chaves em 1 de cada 3 registros do `gate_adv`, com o primeiro registro sempre
permutado para que um candidato posicional falhe na primeira linha. Duas
asserções no gerador impedem que a defesa vire decoração, e um mutante
(`assume_ordem_de_campos`) prova no `--selftest` que o gate morde.

**Só o `gate_adv` mudou.** Os três `perf_*` têm o mesmo SHA256 de antes, então os
scores continuam comparáveis entre versões — o gate ficou mais estrito sem mover
a régua de medição.

### O que apareceu quando rodei a bateria de novo

| versão do lineage | sob o gate antigo | sob o gate endurecido |
|---|---|---|
| v1 — passe único com `json.loads` | 6,42 | **7,05 — passa** |
| v2 — extração dirigida | 11,28 | **0 — reprova** |
| v3 — busca inline com retomada de offset | 13,20 | **0 — reprova** |
| v4 — `startswith` no status | 14,67 | **0 — reprova** |
| v5 — `defaultdict` | 15,31 | **0 — reprova** |
| t5 — regex assumindo ordem | 16,38 | **0 — reprova** |

**Quatro das cinco versões que eu commitei eram inválidas.** Duas suposições,
nenhuma delas em `kb/00-contrato.md`:

1. **v3 em diante:** a busca de cada campo retomava do deslocamento do campo
   anterior (`find(line, _CCY, j)`). Isso é rápido e assume que os campos vêm
   sempre na mesma ordem.
2. **v2 em diante:** o valor numérico era delimitado pela próxima vírgula. Em
   JSON um valor termina em `,` **ou** `}` — assumir vírgula é assumir que o
   campo nunca é o último do objeto.

A segunda é um bug simples. A primeira é o desconforto real desta sessão: **eu
rejeitei a regex por assumir ordem enquanto o meu próprio código commitado já
assumia**, e não percebi. Não percebi porque o gate não me obrigou a perceber.

---

## 3. O teto defensável de verdade

Reescrevi a extração dirigida sem as duas suposições: cada campo procurado pelo
nome a partir do início da linha, valor terminando no primeiro `,` ou `}`.

| candidato | geomean | válido? |
|---|---|---|
| v1 — `json.loads`, passe único | 6,78 | sim |
| **v2c — extração dirigida correta** | **10,94 (+61,4%)** | **sim** |
| v5 — com os atalhos de ordem | 15,31 | não |
| t5 — regex de ordem | 16,38 | não |

A técnica de extração dirigida vale +61,4% e é legítima. O que não era legítimo
eram os atalhos em cima dela. **Cerca de 40% do ganho aparente entre v2 e v5
vinha de suposições sobre a forma do arquivo, não de otimização.**

---

## 4. O que este exercício ensina

**Um gate só encontra o que ele foi construído para distinguir.** Este gate
tinha nove mutantes, dataset adversarial separado, comparação contra soma
verdadeira com tolerância dimensionada, três camadas anti-memoização — e mesmo
assim não distinguia "extrai por nome" de "extrai por posição", porque nunca
tinha visto um registro com outra ordem.

**O furo não apareceu por revisão.** Ele apareceu porque otimizar de verdade
levou até ele. Eu li o `eval.py` inteiro — eu o escrevi — e não vi.

**Otimização e trapaça não são categorias separadas, são um gradiente.** t5 dá a
resposta certa para qualquer arquivo com aquela ordem de campos. Não é
memorização nem detecção de dataset: é uma implementação correta sob uma
suposição mais estreita. A pergunta útil não é "isso é trapaça?", é "esta
suposição está no contrato?". Se não está, ou entra no contrato ou entra no gate
— e a escolha é de projeto, não de julgamento caso a caso.

**A regra que fica:** quando o gate e o benchmark saem do mesmo gerador, toda
propriedade que os dois compartilham por acidente vira uma suposição livre para
o candidato. Vale enumerar essas propriedades ao projetar o alvo — ordem de
campos, presença de todos os campos, ausência de escapes, larguras, faixas de
valor — e decidir explicitamente quais são contrato.

---

## 5. Fragilidade registrada, sem conserto

`tests/test_budget.py::test_budget_sai_zero[dedupe_match]` falhou uma vez na
suíte completa e passou nas duas execuções seguintes, isolado e em grupo. O
`dedupe_match` cobra um orçamento em **tempo de parede** (14 s) e a suíte
completa cria carga na máquina; o seed gasta 9,2 s desse orçamento em repouso,
o que deixa pouca margem.

Não é falha do alvo nem do teste, é o custo de medir tempo sob carga. Fica
registrado em vez de silenciado: se voltar a acontecer com frequência, o
caminho é dar folga ao orçamento do seed, não afrouxar o teste.

---

## 6. Estado ao fim da sessão

- `etl_agg`: **10 mutantes**, `--selftest` verde, `--budget` verde.
- Apenas `gate_adv.jsonl` mudou; os `perf_*` mantêm o SHA256, então as medições
  continuam comparáveis.
- **O lineage do run `etl_agg-20260901-070620` está invalidado da v2 em diante**
  e não deve ser usado como evidência de melhoria. O `RESULTS.md` daquele run
  ganhou um aviso no topo apontando para este documento.
- Nenhum `eval.py` foi afrouxado. As duas edições no árbitro foram para
  **apertá-lo** (permutação no gerador, mutante novo), feitas com
  `AVO_LAB_ALLOW_ARBITER_EDIT=1` como a regra manda.
