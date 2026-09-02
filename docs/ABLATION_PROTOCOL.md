# Protocolo de ablação — o entregável científico

**Estado: pré-registro.** Este documento descreve o experimento *antes* de rodá-lo,
de propósito. As decisões de análise ficam fixadas aqui para que a leitura dos
resultados não seja escolhida depois de vê-los. Resultados vão para
`experiments/`, nunca neste arquivo.

---

## 1. A pergunta

A NVIDIA publicou uma arquitetura com cinco componentes identificáveis, destacou
dois como "particularmente importantes" (memória persistente e supervisão), e
**declarou por escrito que não isolou a contribuição individual de nenhum**:

> "este experimento não isola a contribuição individual [da memória]" — blog
> NVIDIA, registrado como C16 em `AVO_REPLICATION_REPORT.md`

O paper confirma a ausência: a Tabela 1 ablaciona *otimizações descobertas*
(v19→v20 etc.), nunca componentes do AVO. Ninguém — nem NVIDIA, nem a reprodução
aberta, nem VISTA ou Tycho — publicou essa ablação.

**A pergunta desta bancada:** quanto do desempenho do AVO vem da arquitetura, e
quanto vem simplesmente de um bom modelo com um número objetivo para perseguir?

É a única contribuição científica disponível aqui, e ela é barata: alvo
sintético, sem GPU, modo sessão sem custo de API.

## 2. Por que esta bancada consegue responder

Três condições que raramente coexistem:

- **`f` é objetivo e contínuo.** Não é pass@1 binário: é melhoria de score por
  iteração, que é muito mais sensível e precisa de menos amostras.
- **Correção é decidida por um gate adversarial**, não por julgamento. Um braço
  não pode ganhar afrouxando o critério.
- **Os alvos têm headroom graduado** (ver `TARGET_DESIGN.md` §3). Sem isso todo
  braço encontra o mesmo ganho óbvio no passo 1 e estagna junto — o experimento
  mediria a facilidade do primeiro passo, não a arquitetura.

## 3. Os braços

| braço | o que muda | como se implementa |
|---|---|---|
| `full` | nada — AVO completo | padrão |
| `no_supervisor` | sem detecção de estagnação nem redirecionamento | `--no-supervisor` |
| `no_memory` | `NOTES.md` é zerado entre passos | hook no runner do experimento |
| `no_kb` | o alvo roda sem knowledge base | `kb/` vazia numa cópia do alvo |
| `no_lineage` | o prompt não mostra o histórico de versões | variante do prompt de variação |

`full`, `no_supervisor` e `no_kb` são controláveis direto pelo harness.
`no_memory` e `no_lineage` exigem um invólucro; ele fica em `experiments/` e é
parte do entregável, não do harness.

**Braço de controle honesto.** Um sexto braço, `greedy`, roda o mesmo modelo com
o mesmo `f` mas sem nenhuma estrutura AVO: sem lineage, sem gate persistente, sem
supervisor — só "melhore este código, aqui está o número". Se `greedy` empatar
com `full`, a resposta à pergunta de §1 é "quase tudo vem do modelo", e esse é um
resultado publicável tanto quanto o contrário.

## 4. Controles não negociáveis

- **Orçamento de tokens igualado entre braços**, incluindo os tokens do
  supervisor. Sem isso o braço `full` ganha por gastar mais, e nós
  reproduziríamos exatamente o erro metodológico que a NVIDIA evitou declarar.
  Igualar por *passos* não basta: um passo com supervisor custa mais.
- **Mesmo alvo, mesmo dataset congelado, mesmo commit do harness**
  (`vendor/avo.lock`).
- **Máquina ociosa.** O score é tempo de parede; ruído de vizinho contamina.
  Registre carga e temperatura se possível, e rode os braços **intercalados**
  (A,B,C,A,B,C…), nunca em bloco, para que deriva térmica não vire efeito.
- **Ordem dos braços aleatorizada** dentro de cada rodada.
- **Cegamento na análise.** Os resultados são rotulados por identificador opaco
  até a análise estar escrita.
- **O agente consegue medir — verificado na transcrição, nunca presumido.**
  Este controle existe porque foi violado em dois experimentos seguidos, US$ 343,
  sem que nada acusasse. O harness usa `bypassPermissions`, que é recusado quando
  o processo roda como root; ao trocar por `acceptEdits` o Bash passou a exigir
  aprovação, e num run não supervisionado a aprovação não vem. Os agentes
  escreveram código no escuro e o experimento reportou números como se eles
  tivessem medido.

  A verificação é `python3 experiments/ablacao/destilar_logs.py --logs <dir>`,
  que correlaciona `tool_use` com `tool_result` por id e **sai com código 1 se
  qualquer sessão terminar sem uma medição bem-sucedida**. Correlacionar por id é
  a parte que importa: contar a *intenção* de chamar a ferramenta fazia as
  sessões cegas parecerem ter medido dezenas de vezes cada.

  Rode-a **antes de analisar**, não depois. Uma sessão cega não é ruído a mais na
  amostra; é uma sessão que não testa o que o desenho diz testar.

## 5. Métricas

Primária, fixada antes de rodar:

> **Melhoria relativa de score sob orçamento fixo de tokens**, ou seja
> `primary_final / primary_seed`, com o orçamento igualado entre braços.

Secundárias, reportadas sempre, nunca promovidas a primária depois:

- commits aceitos (a razão 500:40 do paper dá ~8% de aceitação como referência)
- passos até o primeiro platô (3 passos consecutivos sem melhoria acima do ruído)
- taxa de re-exploração: quantas vezes um braço tentou algo já registrado como
  beco sem saída no `NOTES.md` (é a métrica que ataca o Gap 1 — a arquitetura de
  memória — de forma direta)
- score por regime, não só o agregado: um braço pode ganhar no geomean e estar
  regredindo num regime

## 5b. A catraca de ruído — um confundidor descoberto antes de rodar

Ao testar o modo não supervisionado, um passo falhou por um motivo de ambiente
(`--dangerously-skip-permissions` não roda como root). O agente morreu em 1,1 s
sem tocar em nada. **O passo foi ACEITO como v1, com +3,59%.**

O `git diff v0 v1` não toca no `transform.py`. O código era idêntico ao seed. A
avaliação apenas mediu um pouco mais rápido, e a política *iguala ou melhora*
commitou.

Isso é um confundidor direto do experimento, e da pior espécie — ele **favorece
os braços que falham mais**:

- Um braço com mais falhas de agente acumula mais passos "aceitos" sem código
  novo. `commits aceitos` deixa de medir busca produtiva.
- Cada aceite por ruído vira o novo incumbente. Como só se commita o que iguala
  ou melhora, a régua sobe e nunca desce: o score final acumula o **máximo** do
  ruído em vez da mediana. Com 6 passos e ±3% de ruído, isso infla o resultado
  de qualquer braço, e infla mais quem tem mais passos vazios.

Não é um defeito do harness — *matches-or-improves* é o critério do paper (§3.2)
e existe para permitir refactor neutro. É um defeito de **medição** quando o
ruído é comparável ao efeito, que é exatamente o regime desta bancada.

**Mitigações adotadas, todas registradas no `results.jsonl`:**

1. **Coluna `codigo_mudou`.** Por passo, o runner compara o arquivo do candidato
   entre as duas versões commitadas. Um aceite sem mudança de código é uma
   catraca de ruído e é contado à parte.
2. **`agente_ok` por passo.** Falha de agente é reportada, não escondida numa
   média.
3. **Métrica primária inalterada, mas lida com cuidado.** A melhoria relativa
   continua sendo `primary_final / primary_seed`; a análise reporta em paralelo
   a melhoria contando **só os passos em que o código mudou**.
4. **Se um braço tiver taxa de falha de agente muito diferente dos outros**, a
   comparação daquele braço é reportada como não interpretável — a diferença
   estaria medindo o ambiente, não a arquitetura.

Vale registrar o método: isto apareceu porque um passo falhou por acaso e eu fui
olhar *por que* ele tinha sido aceito. Um experimento que só olhasse a curva de
score teria absorvido o efeito inteiro sem notar.

## 6. Amostragem e análise

- **n = 5 execuções por braço** por alvo, alvos `etl_agg` e `sql_agg` no mínimo.
- **Bootstrap** (10.000 reamostragens) para intervalo de confiança da diferença
  entre cada braço e `full`. Não use teste t: com n=5 a normalidade não é
  verificável.
- **Holm-Bonferroni** sobre as cinco comparações contra `full`.
- **Reporte o tamanho do efeito e o intervalo, sempre.** Um p-valor sozinho com
  n=5 não informa nada.

**O que n=5 consegue detectar.** Com o ruído de medição observado nesta bancada
(coeficiente de variação de 2–4% por avaliação, variação entre execuções do loop
muito maior), n=5 por braço detecta com confiança apenas **efeitos grandes** — da
ordem de 30% ou mais de diferença na métrica primária. Isso precisa estar escrito
na conclusão:

> Se a diferença entre braços for pequena, este experimento **não vai
> distingui-la do ruído**, e "não distinguível" não é "não existe".

Declarar isso antes de rodar é o que separa um resultado de uma narrativa.

## 7. Ameaças à validade

| ameaça | mitigação |
|---|---|
| Alvo fácil demais: todo braço satura | `TARGET_DESIGN.md` §3; verificar headroom graduado antes |
| Alvo difícil demais: nenhum braço sai do lugar | rodar `full` primeiro como sonda; se não melhorar, o alvo não serve |
| Ruído de máquina vira efeito | braços intercalados, ordem aleatorizada, máquina ociosa |
| Variância do modelo domina a arquitetura | é uma **conclusão possível**, não um defeito; reporte-a |
| Overfitting ao alvo | dois alvos de domínios distintos (agregação Python e SQL) |
| Análise escolhida depois dos dados | este pré-registro; métrica primária fixada em §5 |

## 8. O que este experimento **não** responde

- Nada sobre kernels em B200. A escala é outra e o regime de otimização é outro.
- Nada sobre ARC-AGI-3. O public set já foi saturado por três sistemas
  independentes; 100% ali não é mais um resultado.
- Nada sobre o agente interno da NVIDIA, que o paper confirma ser não-público
  (§4.1). Estamos ablacionando a *arquitetura* descrita, com um agente diferente.
- Nada sobre produção. Um ganho num alvo sintético não é um ganho num pipeline
  real, e a única forma de saber é o experimento de §9.

## 9. O experimento que reduz a maior incerteza

Independente da ablação, e provavelmente mais valioso para uso interno:

> Pegue uma query do `bw_normalization` que **você já otimizou à mão** e veja se
> o AVO bate a sua versão.

- Se bater: o sistema tem valor de produção, e isso vale mais que qualquer
  número de benchmark.
- Se empatar: o valor está na ablação, não na aplicação.
- Se perder: você aprendeu isso por algumas horas de CPU em vez de por um
  trimestre de projeto.

Os três desfechos são informativos. É o que caracteriza um bom experimento.

## 10. Entregáveis

```
experiments/<data>-<alvo>/
  PROTOCOL.md      cópia deste arquivo no estado em que foi rodado
  arms/<braço>/<seed>/   runs completos (lineage, trajectory, NOTES)
  results.jsonl    uma linha por execução: braço, seed, métricas, tokens
  ABLATION.md      a análise, escrita contra o pré-registro
```

`ABLATION.md` precisa dizer explicitamente se a diferença é distinguível do
ruído com o n usado. **Não conclua mais do que as amostras suportam** — é a
regra que a própria NVIDIA seguiu no corpo do post e que a imprensa ignorou no
subtítulo.
