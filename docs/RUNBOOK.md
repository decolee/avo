# RUNBOOK — o que colar numa sessão do Claude Code

Cada sessão abaixo é autocontida e tem um critério de parada explícito. Rode em
ordem: a sessão N assume que a N−1 terminou verde.

O modo padrão é **modo sessão**: o harness entrega o prompt de variação para a
conversa corrente do Claude Code, sem spawnar agente e sem chamar API. Custo
marginal zero. O modo não supervisionado (`avo run`) existe e gasta quota — é
opt-in de propósito.

---

## Sessão 0 — setup e verificação (≈5 min)

> Rode `make setup`. Confirme três coisas, nesta ordem: os testes do upstream
> passam, `make test` passa, e `avo-lab verify` reporta todos os alvos válidos.
> Se qualquer uma falhar, **PARE e reporte o erro** — não tente consertar o
> `eval.py` de nenhum alvo para fazer a verificação passar. Se as três passarem,
> escreva `experiments/STATUS.md` com a saída das três e o commit fixado em
> `vendor/avo.lock`.

**Critério de parada:** `avo-lab verify` sai 0 com todos os alvos válidos.

---

## Sessão 1 — primeiro run autônomo (15 passos)

> Leia `CLAUDE.md` e `docs/TARGET_DESIGN.md`. Rode
> `make run TARGET=etl_agg STEPS=15`.
>
> Atue como operador de variação por até 15 passos. Em cada passo: leia o
> prompt, faça **UMA** mudança substancial, valide com `./avo-eval` de dentro do
> run dir, e submeta **da raiz** com
> `python3 -m avo submit --run runs/<id> -m "<resumo com o número medido>"`.
>
> Registre becos sem saída no `NOTES.md` do run — é a memória entre passos, e um
> beco não registrado será re-explorado.
>
> **NÃO edite `eval.py` em nenhuma circunstância.** O hook vai bloquear; se você
> se pegar querendo contornar o hook, pare e escreva por que no `NOTES.md`.
>
> Ao terminar escreva `RESULTS.md` com: a tabela de lineage, o score por versão
> e por regime, quais passos foram rejeitados e o **motivo exato do framework**,
> e a sua leitura de onde a curva estagnou e por quê.

**Critério de parada:** 15 passos ou platô declarado. `RESULTS.md` escrito.

**O que observar:** a razão de aceitação. O paper reporta ~8% (500+ direções,
40 commits). Uma razão muito maior sugere que o alvo é fácil demais; muito
menor, que está difícil demais ou que o gate está reprovando por engano.

---

## Sessão 2 — teste de trapaça (o mais importante, e o mais pulado)

> Você acabou de rodar uma busca que otimiza um número. Agora tente ganhar esse
> número **sem resolver o problema**. Escreva e rode candidatos que:
> cacheiam o resultado entre chamadas; memorizam a saída; detectam qual arquivo
> está sendo lido e devolvem constante; assumem ordem fixa de campos; reduzem
> precisão para ganhar velocidade.
>
> Para cada um, registre se passou no gate e que score tirou. Escreva
> `experiments/REWARD_HACKING.md` com o resultado.
>
> Se algum trapaceiro pontuar, **o alvo está quebrado** e a ablação não pode
> rodar em cima dele. Conserte o gate (adicionando mutante e caso adversarial,
> nunca afrouxando), rode `--selftest`, e repita.

**Critério de parada:** nenhum candidato trapaceiro pontua.

**Por que aqui e não depois:** foi exatamente assim que a Falha 1 apareceu. O
gate parecia sólido até alguém tentar quebrá-lo de propósito.

---

## Sessão 3 — a ablação (o entregável científico)

> Leia `docs/ABLATION_PROTOCOL.md` **inteiro** antes de rodar qualquer coisa. Ele
> é um pré-registro: a métrica primária, o n, e o método de análise já estão
> fixados, e mudá-los depois de ver os dados invalida o experimento.
>
> Rode os braços descritos em §3 com o orçamento de tokens igualado (§4),
> intercalados e com ordem aleatorizada. Registre por execução: braço, seed,
> commits aceitos, score final por regime, passos até o primeiro platô, tokens
> gastos.
>
> Escreva `ABLATION.md` comparando os braços contra o pré-registro. Diga
> **explicitamente** se a diferença é distinguível do ruído com o n usado. Não
> conclua mais do que as amostras suportam: "não distinguível" não é "não
> existe", e as duas frases precisam aparecer separadas no texto.

**Critério de parada:** `ABLATION.md` escrito, com intervalos de confiança e a
declaração de efeito mínimo detectável.

---

## Sessão 4 — generalidade (a tese C14)

> A afirmação central do paper é que "o agente subjacente permanece o mesmo;
> apenas as ferramentas específicas do ambiente e a avaliação mudam". Teste-a
> dentro da bancada: rode o mesmo harness, sem mudar nada nele, contra
> `sql_agg` (SQL) e `dedupe_match` (métrica de qualidade, não de velocidade).
>
> Compare o comportamento do loop entre os três domínios: razão de aceitação,
> forma da curva, onde estagnou. Escreva `experiments/GENERALIDADE.md`.

**Por que importa:** se o mesmo harness funciona trocando só evaluator e
ferramentas, você validou a afirmação central da NVIDIA de forma independente.
Isso é mais interessante que qualquer número de ARC — o public set do ARC-AGI-3
já foi saturado por três sistemas.

---

## Sessão 5 — alvo novo (só depois de 1–4 funcionarem)

> Crie `targets/<nome>/` seguindo `targets/etl_agg/` como molde. Leia
> `docs/TARGET_DESIGN.md` inteiro antes: as quatro propriedades de um alvo
> válido, e principalmente o requisito de **headroom graduado** (§3), que é o
> mais fácil de errar e o que invalida a ablação quando errado.
>
> Obrigatório antes de considerar o alvo pronto: `--selftest` verde com ≥ 5
> mutantes, `--budget` verde, headroom medido com pelo menos 4 movimentos
> distintos, e a checklist do fim do `TARGET_DESIGN.md` inteira. `avo-lab verify`
> tem que passar.

---

## Sessão 6 — Tier 1 real: Postgres

> Só depois de `sql_agg` (SQLite) dar sinal. O caminho é o mesmo alvo com outro
> backend: snapshot congelado como tabela materializada, `pg_stat_statements`
> para medida, cache limpo ou primeira execução descartada entre candidatos, e
> gate por hash do result set ordenado.
>
> O experimento que reduz mais incerteza está em `ABLATION_PROTOCOL.md` §9:
> pegue uma query que **você já otimizou à mão** e veja se o AVO bate a sua
> versão. Os três desfechos possíveis são todos informativos.
