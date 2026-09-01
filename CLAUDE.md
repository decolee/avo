# AVO Data Lab — regras operacionais

Busca evolutiva com um coding agent como operador de variação (AVO, arXiv:2603.24517),
aplicada a engenharia de dados. O harness fica em `vendor/avo` (upstream:
`gatordevin/avo`, commit fixado em `vendor/avo.lock`). **Nosso trabalho fica em
`targets/` e `labkit/`.**

## Comandos

| o quê | comando |
|---|---|
| setup completo | `make setup` |
| verificar tudo | `make verify` |
| rodar um alvo | `make run TARGET=etl_agg` |
| avaliar (dentro do run dir) | `./avo-eval` |
| submeter (**da raiz**) | `python3 -m avo submit --run runs/<id> -m "<resumo>"` |
| estado | `python3 -m avo status --run runs/<id>` · `lineage` · `plot` |

`avo submit` **falha se rodado de dentro do run dir** — precisa ser da raiz, com
`--run`. Não é bug seu; está registrado como Falha 3.

## Regras invioláveis

- **Nunca edite `targets/*/eval.py` para fazer um candidato passar.** O evaluator
  é o árbitro. Mexer nele para vencer é reward hacking, não otimização. Isto não é
  só uma regra escrita: o hook `.claude/hooks/protect_arbiter.sh` bloqueia a
  edição. Quando a mudança no árbitro for legítima — adicionar um mutante,
  corrigir um bug do gate — libere com `AVO_LAB_ALLOW_ARBITER_EDIT=1` e diga no
  commit por que era legítima.
- **Toda mudança em qualquer `eval.py` exige `--selftest` verde antes de qualquer
  run.** Todos os mutantes rejeitados, sem exceção.
- **Não rode `git commit`, `git reset` ou `git checkout` dentro de `runs/*/work/`.**
  O framework é dono do lineage.
- **Uma mudança substancial por passo.** Várias juntas impedem a atribuição do ganho,
  que é a única coisa que o lineage sabe medir.
- **Meça antes de submeter.** Mudança não medida é chute, e o chute entra no
  lineage junto com o resto.
- **Registre becos sem saída no `NOTES.md` do run.** É a memória entre passos — no
  paper, é literalmente o histórico de conversa do agente (§4.1). Um beco não
  registrado será re-explorado.

## O que torna uma mudança commitável

A política do framework é **iguala ou melhora** (paper §3.2): empate commita.
Isso é deliberado — um refactor neutro que abre caminho para o próximo ganho vale
a pena. Mas descreva-o como o que é. "Refactor neutro, prepara X" é honesto;
"otimização" para um empate não é.

Antes de submeter, saiba responder:
1. Qual foi a mudança, em uma frase?
2. Quanto ela mediu, em cada regime?
3. O ganho está acima do ruído? (o avaliador reporta o coeficiente de variação —
   veja `kb/20-medicao.md` do alvo; tipicamente **abaixo de 3% é empate**)
4. É uma transformação geral ou explora a forma deste dataset?

A pergunta 4 é a que separa otimização de trapaça. Um candidato que detecta qual
arquivo está lendo, memoriza a saída, ou assume ordem fixa de campos vai passar
no gate e não vale nada. O gate roda num dataset **diferente** do benchmark
justamente para achar esse tipo de suposição — mas ele não pega tudo, e a
diferença é sua responsabilidade.

## Anatomia de um alvo

Quatro peças. Detalhes e o raciocínio de projeto em `docs/TARGET_DESIGN.md`.

```
targets/<nome>/
  target.yaml      seed, kb, entrypoint, comando de avaliação, direção do score
  eval.py          f — emite AVO_RESULT no stdout; --selftest com >= 5 mutantes
  seed/            x_0: correto e obviamente subótimo
  kb/              K: o domínio, nunca a solução
  make_data.py     datasets determinísticos + dataset.lock.json (SHA256)
```

Um alvo só é **sadio** quando `python3 eval.py --selftest` fica verde e
`--budget` confirma o dimensionamento. Sem as duas coisas ele não entra —
`make verify` e o CI recusam.

Ser sadio não basta para o alvo servir ao experimento. Ele também precisa
declarar `lab.headroom_medido` e `lab.movimentos` no `target.yaml` e alcançar a
barra de **3× em 4 movimentos** (`docs/TARGET_DESIGN.md` §3). Abaixo dela o
`verify` emite **aviso**, não erro: o alvo funciona, mas não distingue braços
numa ablação. Dois dos cinco alvos estão nessa situação — inclusive o `etl_agg`,
que era a referência até o gate ser endurecido.

## Contexto de projeto

- `docs/TARGET_DESIGN.md` — **leia antes de criar um alvo novo.** Tem as três
  falhas já encontradas, transformadas em regras verificáveis, e o requisito de
  headroom graduado, que é o mais fácil de errar.
- `docs/ABLATION_PROTOCOL.md` — o experimento científico da bancada, com o
  desenho pré-registrado. É o entregável real; os alvos existem para servi-lo.
- `docs/AVO_REPLICATION_REPORT.md` — separa o que é **confirmado da NVIDIA** do
  que é escolha da reprodução aberta. Não atribua à NVIDIA design que é do
  upstream; o relatório marca cada linha.
- `docs/PLANO_AVO_DATA_ENGINEERING.md` — os tiers (Python → SQLite → Postgres →
  Snowflake) e o histórico do que já quebrou.

## O que não fazer

- Não aponte a busca para greenfield, decisões de arquitetura, ou qualquer coisa
  cuja melhoria só se avalie lendo. **Sem `f` objetivo — candidato incumbente
  mais um número para maximizar — o loop não fecha.**
- Não confie num gate que você não tentou quebrar de propósito.
- Não vá para um tier novo antes do anterior dar sinal.
