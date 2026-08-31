---
description: Executa um passo do loop AVO — uma mudanca, medida, submetida
---

Execute UM passo de variacao no run corrente.

1. Leia o prompt de variacao: `python3 -m avo prompt --run $ARGUMENTS`
   (sem argumento, ele pega o run mais recente).
2. Leia o `NOTES.md` do run antes de propor qualquer coisa. Ele e a memoria
   entre passos: um beco sem saida nao registrado sera re-explorado.
3. Faca **UMA** mudanca substancial no `work/`. Varias juntas impedem a
   atribuicao do ganho, que e a unica coisa que o lineage sabe medir.
4. Meca com `./avo-eval` de dentro do run dir. Compare com a versao anterior e
   com o coeficiente de variacao que o avaliador reporta — tipicamente **abaixo
   de 3% e empate**, nao ganho.
5. Antes de submeter, saiba responder:
   - Qual foi a mudanca, em uma frase?
   - Quanto ela mediu, em cada regime?
   - O ganho esta acima do ruido?
   - E uma transformacao geral, ou explora a forma deste dataset?
6. Submeta **da raiz**: `make submit RUN=runs/<id> M="<resumo com o numero>"`.
   De dentro do run dir, `avo submit` falha (Falha 3).
7. Registre no `NOTES.md` o que foi tentado — inclusive o que nao funcionou.

Se o gate rejeitar, a resposta e mudar o candidato. **Nunca** o `eval.py`: o
hook bloqueia, e ele esta certo.
