---
description: Cria um alvo novo seguindo a disciplina do laboratorio
---

Crie o alvo `$ARGUMENTS` seguindo a ordem abaixo. Nao pule etapa: cada uma
existe porque a falta dela ja custou um alvo inteiro.

**Antes de escrever qualquer linha**, leia:
- `docs/TARGET_DESIGN.md` — as cinco propriedades de um alvo valido
- `CONTRIBUTING.md` — o procedimento e a checklist do PR
- `targets/etl_agg/` inteiro — e o molde: `target.yaml`, `eval.py`,
  `make_data.py`, `seed/`, `kb/`

Depois, nesta ordem:

1. **Datasets primeiro.** Um decide correcao (adversarial, pequeno), outro mede
   tempo (grande, >= 2 formas de dado diferentes). Nao os misture — foi isso que
   produziu a Falha 1. O gerador deve se recusar a escrever um gate sem mordida.
2. **Seed**: correto e obviamente subotimo. Ele tem que passar no proprio gate.
3. **`eval.py`** com >= 5 mutantes — os atalhos plausiveis que um otimizador
   tentaria, nao bugs absurdos.
4. **Meca o headroom**: 3 ou 4 versoes progressivamente melhores num script
   descartavel. Meta: 3x-8x em >= 4 movimentos, nenhum valendo > 70%. Reporte
   os numeros reais.
5. **Tente trapacear** no seu proprio alvo: memorizar a saida, cachear em disco,
   detectar o dataset. Se algum pontuar, o alvo esta quebrado.
6. `python3 targets/<nome>/eval.py --selftest` e `--budget` verdes, e
   `make verify` verde por inteiro.

Nao declare o alvo pronto sem colar a saida real dos comandos acima.
