# Contribuir com o AVO Data Lab

Este repositorio tem uma peculiaridade que muda tudo: **um agente autonomo roda
aqui dentro, sozinho, otimizando contra uma funcao de score.** Codigo mal escrito
ele contorna. Documentacao errada ele ignora. Mas um **gate frouxo** ele explora
ate o fim, com confianca, e todo o trabalho construido em cima vira lixo sem que
nada fique vermelho.

Por isso a maior parte do que segue e sobre o `eval.py`, e nao sobre estilo.

## Setup

```bash
./bootstrap.sh          # ou: make setup
make verify             # lint + testes + gate de todos os alvos + dimensionamento
```

`make verify` verde e a condicao de entrada de qualquer PR. E o que o CI roda.

## As tres regras que nao se negociam

**1. Nunca edite `targets/*/eval.py` para um candidato passar.** O avaliador e o
arbitro. Afrouxa-lo para vencer nao e otimizacao, e reward hacking: o numero sobe
e para de significar alguma coisa. O hook `.claude/hooks/protect_arbiter.sh`
bloqueia a edicao de qualquer `eval.py` de alvo e de `labkit/`. Quando a mudanca
for legitima — adicionar um mutante, corrigir um bug do gate, apertar uma
tolerancia frouxa — libere explicitamente:

```bash
AVO_LAB_ALLOW_ARBITER_EDIT=1
```

e diga **no commit** por que era legitima. A valvula existe para que a regra seja
cumprivel, nao para ser contornada em silencio.

**2. Um alvo sem `--selftest` verde nao entra.** Nao "entra com aviso", nao
"entra e a gente arruma depois": nao entra. Um gate que aceita um mutante nao
distingue otimizacao de atalho, e um alvo que nao faz essa distincao nao mede
nada. `make selftest` e o CI recusam, e o hook `gate_guard.sh` recusa ainda antes,
no instante da edicao.

**3. Numero medido, nao estimado.** Nenhuma afirmacao de desempenho entra em
documento, comentario ou mensagem de commit sem ter saido de uma execucao real.
"Deve ser ~3x mais rapido" e chute; chute vira folclore, e folclore vira decisao
de projeto seis meses depois.

## Adicionar um alvo novo

Os **criterios de projeto** — o que faz um alvo valido — estao em
`docs/TARGET_DESIGN.md`, com as cinco falhas historicas que os produziram. Leia
antes. O que segue e o **procedimento**.

### 1. Copie o molde

`targets/etl_agg/` e a referencia. Quatro pecas:

```
targets/<nome>/
  target.yaml      seed, kb, entrypoint, comando de avaliacao, direcao do score
  make_data.py     datasets deterministicos + dataset.lock.json (SHA256)
  seed/            x_0: correto e obviamente subotimo
  kb/              K: o dominio, nunca a solucao
  eval.py          f — emite AVO_RESULT no stdout; --selftest com >= 5 mutantes
```

### 2. Escreva os datasets antes do avaliador

Dois papeis que **nao se misturam**: um dataset decide correcao, outro mede
tempo. Foi confundir os dois que produziu a Falha 1 — um dataset de benchmark com
duas casas decimais e estruturalmente incapaz de expor arredondamento
incremental, e o gate aprovou um candidato que violava o contrato.

O dataset de gate e adversarial de proposito, e o gerador deve **se recusar a
escrever um gate sem mordida** (veja a assercao no `make_data.py` do `etl_agg`).

### 3. Escreva o `eval.py` pensando em quem vai tentar te enganar

Os mutantes nao sao bugs absurdos: sao **os atalhos plausiveis que um otimizador
de verdade tentaria**. Arredondar durante a acumulacao. Assumir ordem fixa de
campos. Cachear entre chamadas. Detectar qual arquivo esta lendo. Minimo cinco;
o `etl_agg` tem nove.

### 4. Meca o headroom antes de declarar o alvo pronto

Escreva 3 ou 4 versoes progressivamente melhores num script descartavel e rode.
A meta e **3x a 8x no total, distribuido em 4+ movimentos independentes**, nenhum
valendo mais de 70%.

Headroom concentrado e a falha mais dificil de enxergar porque o alvo parece
otimo: 132x disponiveis soam generosos ate voce ver que o primeiro passo obvio
captura 98% deles. Um alvo assim **nao consegue distinguir bracos de uma
ablacao** — todos acham o mesmo ganho no passo 1 e estagnam juntos —, e a
ablacao e o motivo de a bancada existir.

### 5. Tente trapacear no seu proprio alvo

Escreva um candidato que memoriza a saida, um que cacheia em disco, um que
detecta o dataset. Rode. Se algum pontuar, o alvo esta quebrado. No `etl_agg`
isso rendeu tres camadas de defesa que **so foram escritas depois de o alvo ja
ter sido dado como pronto, com `--selftest` verde**.

### Checklist do PR

Um alvo novo so entra com todos os itens marcados:

```
[ ] python3 targets/<nome>/eval.py --selftest        verde, >= 5 mutantes rejeitados
[ ] python3 targets/<nome>/eval.py --budget          verde (seed <= 25s, execucao >= 20ms)
[ ] python3 targets/<nome>/make_data.py              deterministico; lock commitado
[ ] make verify                                      verde por inteiro
[ ] headroom medido e reportado no PR               3x-8x em >= 4 movimentos
[ ] seed correto e obviamente subotimo               passa no proprio gate
[ ] kb/ ensina o dominio, nao a solucao              >= 2 arquivos .md
[ ] tentei trapacear e nao consegui                  descreva o que tentou
```

Os quatro primeiros itens sao verificados pelo CI. Os quatro ultimos so por
quem revisa — e sao os que mais importam.

## Estilo

- **Python 3.11, somente stdlib** nos seeds e nos avaliadores. Isso e checado
  estaticamente pelo `contracts.stdlib_only`: um import fora da stdlib reprova o
  candidato antes de rodar. `pyyaml` so no harness.
- **`ruff check` e `ruff format`**, linha de 100. `make fmt` aplica, `make lint`
  cobra.
- **Documentacao e comentario em portugues do Brasil, sem emoji.** Comentario
  explica o **porque**, nao o que: o que o codigo ja diz.
- **Um alvo por PR.** Alvo e uma unidade de projeto, nao um arquivo.

## O que nao entra

- Alvo cuja melhoria so se avalia lendo o resultado. Sem `f` objetiva — candidato
  incumbente mais um numero para maximizar — o loop simplesmente nao fecha.
- Gate que voce nao tentou quebrar de proposito.
- Dependencia externa nos alvos.
- Numero de desempenho que nao saiu de uma execucao.
- Mudanca no `labkit` que quebra a API que os alvos ja usam: ela e compartilhada
  por todos os avaliadores e por isso e tratada como congelada. Precisa mudar?
  Abra a discussao antes, e migre todos os alvos no mesmo PR.

## Rodando o loop

O modo padrao e **modo sessao**: o harness entrega o prompt de variacao para a
conversa corrente. Custo marginal zero. O modo nao supervisionado (`avo run`)
gasta quota e **executa codigo gerado** — e opt-in de proposito, e deve rodar em
sandbox. Veja `SECURITY.md`.

`avo submit` roda da **raiz** do repositorio, com `--run runs/<id>`. De dentro do
run dir ele falha (a "Falha 3" do historico). `make submit RUN=runs/<id> M="..."`
faz isso certo.
