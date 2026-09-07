# Defeitos de instrumento — registro consolidado

Um defeito de instrumento é um erro na **bancada**, não no resultado: algo que
faz o experimento medir outra coisa diferente da que ele diz medir. Eles são o
subproduto mais reutilizável deste laboratório — os números nulos não viajam
para outro projeto, estes viajam.

Este arquivo existe porque a numeração estava espalhada. Antes dele, os defeitos
13–16 viviam em `RELATORIO_SQL_WORKLOAD.md` §7 sob a linha *"somam-se aos doze
do `RELATORIO_FINAL.md`"* — e **`RELATORIO_FINAL.md` não está no repositório**.
Não foi apagado (não há registro de remoção no git); nunca foi commitado. Então
a numeração 1–12 não é auditável e não vou reconstruí-la de memória.

## O que é verificável hoje

| nº | defeito | onde está descrito |
|---|---|---|
| 9 | Comparar um número de agora com outro de meia hora atrás: a deriva da máquina inflava tudo entre 9% e 13%. Corrigido por medição **pareada**. | `HEADROOM_SQL_WORKLOAD.md` §6, `RELATORIO_SQL_WORKLOAD.md` |
| 13 | O prompt do braço barato nomeava só o `entrypoint` — viés **assimétrico** entre os dois braços comparados. Corrigido antes de gastar. | `RELATORIO_SQL_WORKLOAD.md` §7 |
| 14 | O container é recuperado após ~20 min de sessão ociosa. Matou o piloto duas vezes. | `RELATORIO_SQL_WORKLOAD.md` §7 |
| 15 | Disco a 97%: 138 diretórios temporários órfãos de processos de medição mortos por `SIGKILL`. `TemporaryDirectory` não sobrevive a sinal. | `RELATORIO_SQL_WORKLOAD.md` §7 |
| 16 | `pgrep -f "piloto.py"` casa com a própria linha de comando do grep. Use `ps \| grep "[p]iloto.py"`. | `RELATORIO_SQL_WORKLOAD.md` §7 |
| 17 | **O detector de sessão cega errava nos dois sentidos.** Ver abaixo. | este arquivo; `ABLACAO_SQL_WORKLOAD.md` ADENDO |

Sem número verificável, mas documentados: o **defeito de permissão** que fez
agentes escreverem código sem conseguir medir (`CONTROLE.md` §1, `ABLATION.md`
§8) — o mesmo que, com o detector já corrigido, ainda marca 13 de 100 sessões da
Fase 2A como genuinamente cegas.

## 17. O detector de sessão cega errava nos dois sentidos

`destilar_logs.exige_visao` é o portão que roda antes de qualquer estatística.
Ele decidia duas coisas por substring:

```
TENTOU medir  <- o comando contém "avo-eval" ou "eval.py"
MEDIU         <- o resultado contém "avo_result" ou "medianas:"
```

Medido sobre 300 transcrições da ablação do `sql_workload`:

- **Falso positivo na tentativa.** 1293 comandos casavam, dos quais 254 eram
  `cat`, 227 `sed`, 126 `grep` e 70 `ls`. **Ler o fonte do avaliador contava como
  tentar medir.**
- **Falso negativo na medição.** `AVO_RESULT:` e `medianas:` são o stdout
  *padrão*. Um agente que canaliza para um parser
  (`./avo-eval | python3 -c "import json..."`) ou importa `medir()` para montar
  comparação pareada não emite nenhuma das duas. 757 comandos tinham saída com
  forma de medição e não eram reconhecidos.

O efeito líquido: **o detector marcava como cega exatamente a sessão que mede
melhor** — a que desconfia do ruído e faz medição pareada, que é o que
`kb/20-medicao.md` manda fazer.

### O conserto

Não foi alargar as strings. Foi separar as duas perguntas e responder cada uma
pelo sinal certo:

1. **o comando executa ou só lê?** — posição de comando, com o corpo dos
   heredocs removido antes (escrever sobre medir, no `NOTES.md`, não é medir);
2. **o que voltou tem forma de medição?** — `primary=`, `correct: ok`,
   `frio=2.4`, `'quente': 8.7`, além do formato padrão.

**Nenhum dos dois sozinho serve.** A forma-do-resultado sozinha dá **16,9%** de
falso positivo, porque `cat NOTES.md` e `cat kb/20-medicao.md` estão cheios de
`primary = 1.16` e `quente=8.4` em prosa. É a conjunção que fecha.

### Validação

| conjunto | antes | depois | esperado |
|---|---|---|---|
| ablação `sql_workload` (160 sessões-passo) | 7 cegas | **1 cega** | 6 tinham medido; a 7ª fez 0 tentativas |
| piloto `sql_agg` CEGO (controle negativo) | 6/6 cegas | **6/6 cegas** | tem que continuar reprovando |
| Fase 2A `sql_agg` (100 sessões) | 19 cegas | **13 cegas** | o defeito de permissão é real, não podia sumir |

O controle negativo é a parte que importa: um detector que só ficasse mais
permissivo aprovaria as sessões do `piloto_sql_agg_CEGO`, e essas são cegas de
verdade. Ele continua reprovando as seis.

Regressão fixada em `tests/test_detector_de_cegueira.py`, 8 casos, cobrindo as
duas direções — inclusive o heredoc e a prosa com número.

### O que o conserto NÃO mudou

A conclusão da ablação. Com o portão corrigido saem 19 das 20 sementes (contra
14 com o portão quebrado), e os três contrastes seguem nulos com p Holm 1,000.
Está em `ABLACAO_RESULTADO.md`.

### Por que só agora

O ADENDO do pré-registro, escrito com 12 dos 20 runs prontos, declarou que o
conserto **não** seria feito durante o experimento: alterar um detector logo
depois de ele reprovar dois runs do próprio braço de referência é o movimento
que a disciplina daqui existe para impedir, mesmo estando certo. O experimento
fechou, o resultado foi publicado, e só então o instrumento foi mexido — com a
verificação explícita de que a conclusão publicada não mudava.
