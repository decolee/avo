# GENERALIDADE — Sessão 4 do RUNBOOK

**A pergunta.** O paper afirma (C14) que *"o agente subjacente permanece o mesmo;
apenas as ferramentas específicas do ambiente e a avaliação mudam"*. Esta sessão
testa isso dentro da bancada: o **mesmo harness, sem uma linha alterada**, contra
três domínios que não têm nada em comum a não ser a forma de `f`.

**Data:** 2026-09-01 · **Harness:** `f6dad9e6` (fixado, idêntico nos três)

---

## 1. Os três domínios

| | `etl_agg` | `sql_agg` | `dedupe_match` |
|---|---|---|---|
| o que evolui | módulo Python | `query.sql` + `setup.sql` | módulo Python |
| `f` maximiza | throughput | throughput | **F1** |
| restrição vinculante | correção exata | correção exata do result set | **orçamento de tempo** |
| regimes | 3 formas de dado | frio / quente / larga | 3 bancos rotulados |
| o que o gate julga | valor e apresentação | result set linha a linha | forma, determinismo, pureza |

O terceiro é o teste de verdade: a métrica tem **forma diferente** (qualidade,
não velocidade) e o gate julga coisas que nos outros dois nem existem — que a
função é determinística, que independe da ordem da entrada, e que não leu o
gabarito.

---

## 2. O que aconteceu

| | `etl_agg` | `sql_agg` | `dedupe_match` |
|---|---|---|---|
| seed | 4,225 | 1,563 | 0,249 |
| melhor | 15,305 † | 4,208 | 0,757 |
| ganho | +262% † | **+169%** | **+204%** |
| baseline superada? | sim, na v2 | não (−22%) | sim, na v1 |
| versões aceitas | 5 | 2 | 2 |
| direções exploradas | 16 | 4 | 5 |
| razão de aceitação | 31% | 50% | 40% |
| maior salto isolado | +76% (v2) | **+143% (v2)** | **+192% (v1)** |
| onde estagnou | ruído da máquina | tensão frio/quente | conflito entre bancos |

† O lineage do `etl_agg` foi invalidado depois pela Sessão 2. O teto defensável
real é **+61,4%**. Os números estão aqui como foram medidos, não como evidência.

**O harness rodou os três sem nenhuma modificação.** `avo start`, `./avo-eval`,
`avo submit`, `avo revert`, o lineage em git, a política *iguala-ou-melhora*, o
arquivamento de diffs rejeitados — tudo funcionou igual. A afirmação C14 se
sustenta neste teste.

---

## 3. As curvas têm formas diferentes — e a diferença é do domínio

**`etl_agg` — degraus decrescentes.** +52%, +76%, +17%, +11%, +4%. Cada passo
remove uma categoria de custo, e o custo por linha vai encolhendo até a
micro-otimização sumir no ruído de ±3% da máquina. **Estagnou por resolução de
medida:** as ideias existiam e foram medidas; o que acabou foi a capacidade de
distinguir o ganho do ruído.

**`sql_agg` — um degrau que domina.** +11% e depois **+143%**. O salto inteiro é
um índice. Antes dele, reescrever a consulta rendeu pouco porque o gargalo não
era o plano, era a varredura. **Estagnou numa tensão de projeto:** o passo
seguinte (mais dois índices) deixou as consultas 20% mais rápidas e o score 14%
pior, porque o regime `frio` cronometra a construção junto. Não é falta de
ideia, é o score cobrando o preço — que é o que um score de banco deve fazer.

**`dedupe_match` — um salto e um muro.** +192% e depois +4%. O salto é bloqueio
mais evidência composta. O muro é diferente dos outros dois: **os três bancos
querem regras opostas.** Rebaixar telefone e email de identificadores fortes
melhora empresas (F1 0,654 → 0,702) e derruba pessoas (0,861 → 0,754) e ruidoso
(0,771 → 0,636). A média geométrica rejeita, e está certa: uma regra que só serve
para um tipo de entidade não é melhoria do deduplicador.

**A leitura.** As três curvas são diferentes porque os três *problemas* são
diferentes, não porque o harness se comportou de forma diferente. O harness não
sabe o que é um índice, um regime de dado ou um F1 — ele só sabe pedir uma
variação, medir, e commitar se não regrediu. Essa indiferença é a tese C14, e ela
se sustentou.

---

## 4. O que só apareceu porque os domínios eram diferentes

**A razão de aceitação não é comparável entre domínios.** 31% / 50% / 40% parecem
próximos, e não medem a mesma coisa: no `etl_agg` a maior parte da exploração
foi A/B fora do run dir (o `./avo-eval` é livre dentro do passo), enquanto no
`sql_agg` cada tentativa custa ~10 s e a exploração é naturalmente mais econômica.
**O custo da avaliação molda o estilo de busca**, e isso não aparece em nenhuma
métrica que o framework registra.

Consequência direta para a ablação (`docs/ABLATION_PROTOCOL.md`): comparar braços
por commits aceitos só faz sentido dentro do mesmo alvo. Entre alvos, o número
mede o custo de avaliar, não a qualidade da busca.

**Cada domínio quebra por um motivo próprio.** Ruído de medida no primeiro,
tensão de projeto no segundo, conflito entre regimes no terceiro. Um único alvo
teria mostrado só um desses modos de platô — e o platô é o que a ablação precisa
medir. **Rodar a ablação em um alvo só mediria um modo de falha.**

**O terceiro domínio testou coisas que os outros não testam.** O gate do
`dedupe_match` precisa provar determinismo, independência da ordem da entrada e
que o candidato não leu o gabarito. Nada disso existe nos alvos de throughput, e
foi construindo essas provas que a técnica de interceptar as portas de arquivo
por gancho de auditoria apareceu — que depois virou a terceira camada
anti-memoização do `labkit`, usada pelos outros alvos. **A generalidade pagou de
volta.**

---

## 5. Ressalvas

- **n = 1 por alvo.** Uma execução por domínio não distingue propriedade do alvo
  de acaso do operador. As formas de curva descritas aqui são observações, não
  resultados.
- **O operador sou eu, e eu escrevi os alvos.** Sei onde estão os ganhos, o que
  infla o desempenho e desinfla a razão de aceitação em relação a um agente que
  chega sem esse conhecimento. Isto **não** é uma medição da capacidade do AVO.
- **Nenhum braço de ablação foi rodado.** Esta sessão testa que o harness
  atravessa domínios, não que algum componente dele contribui.
- **A comparação com o paper é de forma, não de escala.** 40 versões em 7 dias
  contra 2–5 versões em minutos.

---

## 6. Veredito

**A tese C14 se sustenta neste teste.** O mesmo harness, sem modificação,
conduziu buscas produtivas em agregação Python, SQL sobre banco congelado, e
record linkage com métrica de qualidade sob orçamento. O que mudou por domínio
foi o alvo — seed, KB, `eval.py` — que é exatamente o que o paper diz que deve
mudar.

O achado que não estava previsto: **a diversidade de domínios melhorou a
bancada**, não só a validou. O gate mais exigente dos três produziu uma técnica
de defesa que os outros dois adotaram.
