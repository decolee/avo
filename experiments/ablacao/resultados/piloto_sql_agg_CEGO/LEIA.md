# Dados inválidos — mantidos como prova, não como resultado

As cinco sessões deste diretório rodaram com `--permission-mode acceptEdits` e
**sem `--allowed-tools`**. Nesse modo o agente edita arquivos mas precisa de
aprovação para Bash, e a aprovação nunca vem num run não supervisionado. As
cinco tentaram chamar `./avo-eval` entre 10 e 18 vezes cada e foram recusadas
todas as vezes:

```
        sessao  tentou  MEDIU  recusas  edicoes
 pil_greedy-s0      13      0       12        4
 pil_greedy-s1      10      0        9        3
 pil_greedy-s2      18      0       17        4
 pil_greedy-s3      18      1       17        3
 pil_greedy-s4      16      0       15        3
```

Elas escreveram SQL no escuro. Os ganhos que mediram — 4,31× / 4,60× / 1,99× /
1,94× / 4,49× — não são "o agente com o avaliador na mão"; são "o agente
escrevendo de cabeça, e o avaliador conferindo depois, uma vez só, no fim".

Os números ficam aqui porque provam o defeito e porque a bimodalidade que eles
mostram (dois grupos, ~4,5× e ~1,95×, com o **mesmo** índice em todas as cinco)
é informação real sobre o alvo. Mas nenhum deles entra em análise nenhuma.

O conserto está em `runner.FERRAMENTAS` e `greedy.FERRAMENTAS`, e o
`destilar_logs.py` agora sai com código 1 quando qualquer sessão termina cega.
