"""Falha 1, atacada de frente: o gate rejeita os mutantes?

Este é o único bug que esta bancada não pode ter. Um gate que aprova mutante
aceita candidato errado como melhoria, e a busca commita a coisa errada — foi
literalmente o que aconteceu com o `etl_agg` antigo: uma versão que arredondava a
cada acumulação **passou como correta**, e só não foi commitada porque por acaso
ficou mais lenta. É o teto de verificador imperfeito de *Inference Scaling fLaws*
(arXiv:2411.17501): com falso negativo no verificador existe um limite de
qualidade que mais compute não ultrapassa — jogar mais busca só produz a coisa
errada mais rápido.

Por isso este módulo não é marcado como `slow`, apesar de rodar subprocessos: é o
teste que menos pode ser pulado. O custo é pago uma vez — o `--selftest` de cada
alvo é cacheado pela sessão e `test_target_contract.py` reaproveita o mesmo
resultado.

O que se verifica é a TABELA, não o código-fonte do avaliador. A tabela é o que o
revisor humano lê e o que o CI arquiva; checar o texto checa exatamente o que
eles veem.
"""

from __future__ import annotations

from conftest import parametrize_targets, parse_selftest_table, require_dataset, run_eval

pytestmark = parametrize_targets


def test_o_gate_rejeita_todos_os_mutantes(target):
    """Nenhuma linha `mutante ...` pode aparecer como PASS.

    Um sobrevivente é um jeito plausível de estar errado que este alvo aceita
    como certo. Não existe conserto genérico: ou o gate ganha a checagem que
    falta, ou o mutante não era plausível e não devia estar na lista.
    """
    require_dataset(target)
    run = run_eval(target, "--selftest")
    linhas = parse_selftest_table(run.stdout)

    mutantes = [ln for ln in linhas if ln.e_mutante]
    assert len(mutantes) >= 5, (
        f"{target.name}: a tabela declara {len(mutantes)} mutantes; o mínimo é 5.{run.dump()}"
    )

    sobreviventes = [ln.rotulo for ln in mutantes if ln.veredito == "PASS"]
    assert not sobreviventes, (
        f"{target.name}: o gate APROVOU {len(sobreviventes)} mutante(s): "
        f"{', '.join(sobreviventes)}. Isto é a Falha 1 acontecendo de novo — um candidato "
        f"errado seria commitado como melhoria.{run.dump()}"
    )


def test_a_referencia_e_o_unico_pass_da_suite_de_mutantes(target):
    """Exatamente uma aprovação entre referência e mutantes: a referência.

    Um gate que reprova a própria referência é tão inútil quanto um que aprova
    mutante — ele rejeita código correto, e a busca aprende que a mudança certa
    foi um erro.

    Linhas fora da suíte (o `csv_normalize` julga também o `SEED` pelo mesmo
    gate) são contadas à parte e têm que passar: são versões corretas por
    construção.
    """
    require_dataset(target)
    run = run_eval(target, "--selftest")
    linhas = parse_selftest_table(run.stdout)
    assert linhas, f"{target.name}: --selftest não imprimiu tabela nenhuma{run.dump()}"

    suite = [ln for ln in linhas if ln.e_mutante or ln.e_referencia]
    aprovados = [ln.rotulo for ln in suite if ln.veredito == "PASS"]
    assert len(aprovados) == 1, (
        f"{target.name}: esperava exatamente um PASS na suíte (a referência), obtive "
        f"{len(aprovados)}: {aprovados}{run.dump()}"
    )
    assert next(ln for ln in suite if ln.veredito == "PASS").e_referencia, (
        f"{target.name}: o único PASS não é a referência{run.dump()}"
    )

    extras_reprovados = [
        ln.rotulo
        for ln in linhas
        if not (ln.e_mutante or ln.e_referencia) and ln.veredito == "FAIL"
    ]
    assert not extras_reprovados, (
        f"{target.name}: implementação correta reprovada pelo gate: "
        f"{', '.join(extras_reprovados)}{run.dump()}"
    )


def test_gate_furado_nunca_sai_verde(target):
    """Saída zero e "GATE FURADO" não podem coexistir.

    O CI olha o código de saída; o humano olha a linha `GATE SELFTEST:`. A
    implicação só precisa valer num sentido, e é o sentido perigoso: um alvo com
    o gate furado não pode sair zero, porque ninguém lê a saída de um passo
    verde. O contrário é legítimo — o `csv_normalize` sai 1 com o gate OK quando
    é o SEED que reprova, e essa distinção é informação, não inconsistência.
    """
    require_dataset(target)
    run = run_eval(target, "--selftest")

    if run.exit_code == 0:
        assert "GATE FURADO" not in run.stdout, (
            f"{target.name}: saiu zero imprimindo GATE FURADO. O CI ficaria verde com o "
            f"gate aberto.{run.dump()}"
        )
        assert "GATE SELFTEST: OK" in run.stdout, (
            f"{target.name}: saiu zero sem afirmar que o gate está OK{run.dump()}"
        )
    else:
        assert "GATE SELFTEST:" in run.stdout, (
            f"{target.name}: --selftest reprovou sem dizer em que pé o gate ficou — "
            f"quem lê o log não sabe se o problema é o gate ou outra checagem{run.dump()}"
        )
