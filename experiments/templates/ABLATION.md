# ABLATION — `<alvo>`

**Pré-registro:** `docs/ABLATION_PROTOCOL.md`, copiado em `PROTOCOL.md` no estado
em que foi rodado. **Métrica primária fixada antes de rodar:** melhoria relativa
de score sob orçamento de tokens igualado.

**Data:** <AAAA-MM-DD> · **n por braço:** <n> · **Orçamento por execução:** <tokens>

## Resultado primário

| braço | média | IC 95% (bootstrap) | Δ vs `full` | Holm-Bonferroni |
|---|---|---|---|---|
| `full` | | | — | — |
| `no_supervisor` | | | | |
| `no_memory` | | | | |
| `no_kb` | | | | |
| `no_lineage` | | | | |
| `greedy` | | | | |

## Secundárias

| braço | commits aceitos | passos até o 1º platô | re-exploração de becos | tokens |
|---|---|---|---|---|

## É distinguível do ruído?

<Responda diretamente, por braço. Com n pequeno esta seção é a mais importante
do documento.>

**Efeito mínimo detectável com este n:** <valor>. Diferenças abaixo disso este
experimento não consegue separar do ruído.

> "Não distinguível do ruído" **não** é "não existe". As duas frases precisam
> aparecer separadas, e nenhuma conclusão pode trocar uma pela outra.

## Desvios do pré-registro

<Qualquer coisa feita diferente do protocolo, com a justificativa. Se não houve,
escreva "nenhum". Um desvio declarado é ciência; um desvio silencioso não é.>

## Conclusão

<No máximo três frases. Não conclua mais do que as amostras suportam.>
