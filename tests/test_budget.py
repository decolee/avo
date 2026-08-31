"""Falha 2: o custo de avaliação é parte do design do alvo, não uma consequência.

O seed do alvo antigo levava 140 s por avaliação. O paper explorou 500+ direções;
a 140 s cada, isso são 19 horas só de medição — e o primeiro passo custou 2,3
minutos parado antes de qualquer coisa acontecer. O erro por trás disso foi
dimensionar o dataset pelo candidato OTIMIZADO (2,9 s) em vez de pelo seed.

`eval.py --budget` mede o seed e compara com a faixa saudável do laboratório
(teto de 25 s para a avaliação inteira, piso de 20 ms para a execução medida mais
rápida). Ele sai diferente de zero quando o alvo sai da faixa; aqui só se cobra
que ele saia zero — a régua vive no `labkit`, e duplicá-la nesta suíte criaria
dois números para manter em sincronia.

O piso e o teto medem coisas opostas e vale repetir por quê: o teto protege o
TEMPO DO AGENTE, o piso protege o SINAL. Um alvo rápido demais faz a busca
perseguir ruído de relógio, o que é pior que um alvo lento — lento você percebe.

Marcado `slow` porque é honesto: mede tempo de verdade, algumas dezenas de
segundos no total.
"""

from __future__ import annotations

import pytest
from conftest import parametrize_targets, require_dataset, run_eval

pytestmark = [parametrize_targets, pytest.mark.slow]


def test_budget_sai_zero(target):
    """O alvo está dimensionado pelo seed e dentro da faixa saudável."""
    require_dataset(target)
    run = run_eval(target, "--budget")

    assert run.exit_code == 0, (
        f"{target.name}: --budget reprovou o dimensionamento. Dimensione pelo SEED, "
        f"nunca pelo candidato otimizado.{run.dump()}"
    )
    assert run.stdout.strip(), (
        f"{target.name}: --budget saiu zero sem imprimir nada. O relatório é o produto: "
        f"quem for ajustar o dataset precisa dos números.{run.dump()}"
    )


def test_budget_reporta_o_custo_do_seed(target):
    """O relatório nomeia o seed. Medir a referência e chamar de orçamento é o erro original.

    Checagem textual de propósito: o número em si é do `labkit`, mas *qual versão
    foi medida* é decisão do alvo, e é exatamente a decisão que a Falha 2 errou.
    """
    require_dataset(target)
    run = run_eval(target, "--budget")
    assert "seed" in run.stdout.lower(), (
        f"{target.name}: --budget não menciona o seed em lugar nenhum do relatório."
        f"{run.dump()}"
    )
