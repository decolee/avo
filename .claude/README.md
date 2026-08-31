# `.claude/` — as regras do laboratorio, em forma executavel

`settings.json` e JSON estrito e nao aceita comentario. O porque de cada decisao
mora aqui.

## Os dois hooks

| quando | hook | o que faz |
|---|---|---|
| **PreToolUse** `Write\|Edit\|MultiEdit` | `hooks/protect_arbiter.sh` | bloqueia edicao de `targets/*/eval.py` e de `labkit/` |
| **PostToolUse** `Write\|Edit\|MultiEdit` | `hooks/gate_guard.sh` | roda o `--selftest` **do alvo tocado** e bloqueia se o gate furou |

`MultiEdit` esta no matcher junto com `Edit` porque e a mesma operacao em lote:
sem ele, dez edicoes de uma vez passariam por fora do guarda.

### `protect_arbiter.sh` — a regra inviolavel, mecanica

O `CLAUDE.md` diz "nunca edite o `eval.py` para um candidato passar". Isso era
so prosa, e prosa vale ate o momento em que o candidato falha no gate e afrouxar
uma tolerancia parece um detalhe de uma linha. O hook transforma a regra em
`exit 2`.

Valvula de escape, explicita e documentada:

```bash
AVO_LAB_ALLOW_ARBITER_EDIT=1
```

Mudanca legitima no arbitro existe e e comum — adicionar um mutante, corrigir um
bug do gate, apertar uma tolerancia frouxa. O objetivo do hook nao e impedir a
edicao: e impedir a edicao **distraida**, e obrigar quem edita a declarar que
sabe o que esta fazendo. Com a variavel setada ele libera e deixa um registro no
stderr.

### `gate_guard.sh` — dois furos da versao antiga

1. **Vigiava a copia, nao o original.** A versao antiga olhava
   `vendor/avo/targets/*/`, o diretorio que o bootstrap antigo populava com uma
   copia. Editar `targets/etl_agg/eval.py` — o arquivo de verdade — nao disparava
   nada. Nao ha mais copia (o harness resolve `Path.cwd()/targets` primeiro), e o
   hook olha `targets/` na raiz.

2. **Rodava o selftest de todos os alvos a cada edicao.** Com quatro alvos sao
   dezenas de segundos por `Edit`, inclusive ao editar um README — e um hook caro
   e um hook que alguem desliga. O payload traz `tool_input.file_path`: da para
   saber qual alvo foi tocado e rodar so o dele. Arquivo fora de `targets/` sai
   com `exit 0` em silencio; `.md` dentro de um alvo tambem, porque o `eval.py`
   nao le `kb/`.

### Robustez que os dois compartilham

Foram testados alimentando JSON no stdin, e cada item abaixo corrigiu um
comportamento real observado nesses testes:

- **sem `jq`**: cai para `python3`, e depois para `sed`.
- **sem `CLAUDE_PROJECT_DIR`**: deriva a raiz do proprio caminho do script, por
  expansao do bash — a versao com `dirname` devolvia `/` em silencio num `PATH`
  minimo, e um hook que calcula a raiz errada libera tudo.
- **JSON malformado**: o `gate_guard` sai 0 (ele roda depois da edicao; bloquear
  ali so puniria o agente por um defeito do harness). O `protect_arbiter` faz o
  oposto: varre o payload cru e bloqueia se ele menciona um arbitro — errar
  bloqueando custa uma variavel de ambiente, errar liberando custa o run.
- **caminho com espaco**: tudo entre aspas, extracao via `jq`/`python3`.
- **alvo fora da raiz detectada**: os padroes casam ancorados e nao ancorados.

## Permissoes

`allow` sao os comandos do dia a dia do laboratorio — `make`, `avo`, `pytest`,
`ruff`, leitura de arquivo — para nao pedir confirmacao a cada passo de um loop
que pode ter dezenas.

`deny` cobre leitura de segredo: `.env`, chaves privadas, `~/.aws`, `~/.ssh`,
`.netrc`. Nao ha segredo nenhum neste repositorio e **nao deve haver** — veja
`SECURITY.md`, que trata do risco de verdade desta bancada: o avaliador importa
e executa codigo de candidato. `deny` e a ultima linha, nao a primeira; a
primeira e nao rodar isto perto de credencial de producao.

`git push --force` esta negado por ser a unica operacao git aqui que destroi
historico alheio. `git push` normal nao esta: o fluxo de PR depende dele.
