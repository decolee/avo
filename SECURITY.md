# Seguranca

## O risco de verdade desta bancada

Nao e vazamento de dado nem dependencia vulneravel. E mais direto que isso:

> **O avaliador importa e executa codigo de candidato, no mesmo processo e com
> os mesmos privilegios de quem rodou o comando.**

Isso e inerente ao que a bancada faz. Nao da para pontuar um programa sem
executa-lo, e o programa e escrito por um modelo de linguagem que esta sendo
recompensado por fazer o numero subir. Nao ha suposicao de ma fe aqui — ha um
otimizador explorando um espaco de busca, e "escrever no disco", "abrir um
socket" e "ler uma variavel de ambiente" sao movimentos validos desse espaco a
menos que alguem os impeca.

Some a isso o modo nao supervisionado (`avo run`), que **spawna um agente com
`--permission-mode bypassPermissions`** por design: ele precisa editar arquivos e
rodar comandos sem confirmacao para que o loop feche sozinho.

Conclusao pratica, sem rodeios: **trate rodar este laboratorio como executar
codigo arbitrario de terceiro.** Porque e exatamente isso.

## Como rodar com seguranca

1. **Sandbox de verdade.** Container descartavel, VM, ou no minimo um usuario
   dedicado sem acesso ao resto da maquina. O loop autonomo nao deve rodar no seu
   ambiente de trabalho.
2. **Sem credencial de producao no ambiente.** Nada aqui precisa de segredo — e a
   bancada nao deve estar perto de nenhum. Nem `AWS_*`, nem `~/.aws`, nem
   `~/.ssh`, nem token de banco, nem `.env` de outro projeto herdado pelo shell.
   Um agente otimizando throughput nao vai *querer* usar sua credencial; ele so
   vai encontra-la se ela estiver la.
3. **Dado sintetico, sempre.** Todos os datasets sao gerados localmente pelos
   `make_data.py`, sao deterministicos e nao contem nada real. Nao aponte um alvo
   para um extrato, um dump de producao ou uma base com PII. Se precisar medir
   sobre dado real, gere um sintetico com a mesma forma.
4. **Rede restrita, se der.** O loop precisa de rede so para falar com a API do
   modelo. Nada nos alvos precisa de rede — sao stdlib e arquivo local.
5. **Sem segredo no CI.** Os workflows deste repositorio declaram
   `permissions: contents: read` e nao usam nenhum segredo. Se um PR adicionar
   `secrets.` a um workflow, isso e um alerta, nao um detalhe.

## O que as protecoes do `labkit` **nao** sao

O `labkit` tem defesas anti-trapaca — proibicao de escrita em disco durante a
medicao, modulo novo a cada execucao, caminho de arquivo novo a cada regime,
deteccao de velocidade implausivel. Elas existem para proteger a **validade da
medicao**: impedem que um candidato memorize a resposta e chame isso de
otimizacao.

**Elas nao sao isolamento de seguranca.** Nao interceptam syscall, nao restringem
rede, nao impedem leitura de arquivo, nao contem processo filho. Um candidato
malicioso passa por elas sem esforco. Quem isola e o container, nao o `labkit` —
e confundir uma coisa com a outra e como tratar um `try/except` como firewall.

## Superficie de ataque, ponto a ponto

| onde | o que roda | contencao |
|---|---|---|
| `targets/*/eval.py` | importa e chama codigo do candidato | nenhuma; e o ponto do exercicio |
| `avo run` | spawna agente que escreve e roda codigo | `--permission-mode bypassPermissions` por design |
| `runs/*/work/` | arvore git que o agente edita livremente | so o diretorio; nada impede caminho absoluto |
| `.claude/hooks/` | shell disparado a cada Edit/Write | roda com seus privilegios |
| `bootstrap.sh` | `git clone` + `pip install -e` | commit fixado em `vendor/avo.lock` |
| CI | lint, testes, gate | sem segredo, `contents: read` |

O `pip install -e vendor/avo` do bootstrap executa o `setup.py`/backend do
upstream — mais uma razao para o commit ser fixado e auditado, e nao um `main`
que se move sozinho.

## Segredo neste repositorio

Nao ha nenhum, e nao deve haver. Tres camadas, em ordem de importancia
decrescente:

1. **Nao coloque segredo aqui.** Esta e a unica que funciona sozinha.
2. `.gitignore` cobre `.env`, `.env.*`, `*.pem`, `*.key`, `credentials.json`.
3. `.claude/settings.json` nega leitura desses caminhos, mais `~/.aws`, `~/.ssh`
   e `.netrc`, pelo agente.

As duas ultimas sao rede de protecao contra descuido, nao controle de acesso.

## Reportar uma vulnerabilidade

Isto e uma bancada de pesquisa, mantida em regime de melhor esforco — nao ha SLA.
Ainda assim, se voce encontrar algo:

- **Nao abra issue publica com exploit funcional.** Use o *Report a vulnerability*
  (Security Advisory privado) do repositorio no GitHub.
- Inclua o que da para reproduzir: comando, alvo, saida.
- Se for uma fuga do gate — um candidato que pontua sem resolver o problema —
  isso tambem interessa, e **pode ser issue publica**: e uma falha de projeto do
  alvo, nao um risco para terceiro. Mande junto o candidato que passou; ele
  provavelmente vira um mutante novo no `--selftest`.

## Versoes suportadas

So o `main`. Nao ha release nem backport: o repositorio e o experimento.
