"""A disciplina de alvo, imposta a todo alvo — inclusive ao que ainda não existe.

Estes testes são parametrizados por varredura de `targets/*/target.yaml`. Isso é
deliberado: um alvo novo entra na suíte no momento em que ganha um `target.yaml`,
e passa a ter que provar as mesmas coisas que os quatro atuais provaram. A regra
que não se impõe automaticamente é a regra que se esquece na pressa de escrever
o quinto alvo.

O que cada bloco verifica, e por que ele existe:

  FORMA        o `target.yaml` carrega pelo `Target.load` do harness. O harness
               é a autoridade sobre o que é válido; reimplementar a validação
               aqui criaria uma segunda definição de "válido", que envelhece.
  MATERIAL     `seed/` e `kb/` existem e têm conteúdo. Um alvo sem KB é um alvo
               sem `K`: o agente vira adivinhação pura, e o experimento deixa de
               ser sobre a arquitetura AVO.
  DADOS        `dataset.lock.json` existe e confere. Um gerador que muda em
               silêncio move o score de todas as versões do lineage de uma vez.
  FALHA 1      `--selftest` sai 0, imprime `GATE SELFTEST: OK` e declara pelo
               menos cinco mutantes.
  SEED         o `x_0` passa no próprio gate. Um seed reprovado gasta os
               primeiros passos da busca em conserto, não em otimização — e o
               experimento vira uma medida de quão rápido o agente conserta o
               alvo de quem o escreveu.
"""

from __future__ import annotations

import pytest
from conftest import (
    copy_seed,
    dataset_status,
    parse_avo_result,
    parse_selftest_table,
    parametrize_targets,
    require_dataset,
    run_eval,
)

pytestmark = parametrize_targets


# ------------------------------------------------------------------- forma


def test_target_yaml_carrega_pelo_harness(target, avo_target_loader):
    """O harness aceita o alvo, e os campos que ele lê estão preenchidos.

    `evaluate.command` como LISTA não é preciosismo de estilo: o harness recusa
    string explicitamente, porque uma string obrigaria shell e shell num comando
    com caminho interpolado é injeção esperando acontecer.
    """
    t = avo_target_loader.load(target)

    assert t.name, f"{target.name}: `name` vazio"
    assert t.seed_dir is not None and t.seed_dir.is_dir(), f"{t.name}: seed inexistente"
    assert t.kb_dir is not None and t.kb_dir.is_dir(), f"{t.name}: knowledge_base inexistente"
    assert t.direction in ("maximize", "minimize"), f"{t.name}: direção {t.direction!r}"

    bruto = t.raw.get("evaluate") or {}
    assert isinstance(bruto.get("command"), list), (
        f"{t.name}: evaluate.command precisa ser uma lista de tokens argv, não uma string"
    )
    assert t.eval_command, f"{t.name}: evaluate.command vazio"
    assert any("{workdir}" in token for token in bruto["command"]), (
        f"{t.name}: evaluate.command não recebe {{workdir}} — o avaliador nunca veria o "
        "candidato, e mediria o seed a cada passo sem que ninguém percebesse"
    )
    assert t.goal.strip(), (
        f"{t.name}: agent.goal vazio. O goal é onde a restrição vinculante é declarada; "
        "sem ele o agente otimiza uma métrica sem saber o que não pode quebrar."
    )


def test_avaliador_sabe_dizer_sim_e_nao(target):
    """Todo avaliador tem os dois caminhos: aprovar e reprovar.

    Checagem estática e barata, mas não decorativa — um `eval.py` sem
    `emit_failure` só consegue dizer sim, e um alvo que não sabe dizer não é um
    alvo sem gate por construção, independente do que a prosa da KB prometa.
    """
    fonte = (target / "eval.py").read_text(encoding="utf-8")
    assert "emit_success" in fonte, f"{target.name}/eval.py nunca emite sucesso"
    assert "emit_failure" in fonte, (
        f"{target.name}/eval.py nunca emite reprovação — um alvo que não sabe dizer não "
        "não tem gate"
    )


# ---------------------------------------------------------------- material


def test_seed_existe_e_nao_esta_vazio(target):
    seed = target / "seed"
    assert seed.is_dir(), f"{target.name}: falta seed/"
    arquivos = [p for p in seed.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    assert arquivos, f"{target.name}: seed/ está vazio — não há x_0 para evoluir"


def test_seed_contem_o_entrypoint_declarado(target):
    """O entrypoint é o arquivo que o agente edita; ele tem que estar no seed."""
    yaml_texto = (target / "target.yaml").read_text(encoding="utf-8")
    entrypoint = next(
        (
            linha.split(":", 1)[1].strip()
            for linha in yaml_texto.splitlines()
            if linha.startswith("entrypoint:")
        ),
        "",
    )
    if not entrypoint:
        pytest.skip(f"{target.name} não declara entrypoint")
    assert (target / "seed" / entrypoint).is_file(), (
        f"{target.name}: entrypoint {entrypoint!r} declarado no target.yaml não existe em seed/"
    )


def test_kb_tem_pelo_menos_dois_documentos(target):
    """`K` é o análogo dos guias CUDA/PTX do paper, não um README.

    Dois arquivos é o mínimo estrutural: o contrato (o que não pode mudar) e o
    domínio (onde está o custo). Um alvo com um arquivo só está misturando as
    duas coisas, e o agente lê a restrição como sugestão de performance.
    """
    kb = target / "kb"
    assert kb.is_dir(), f"{target.name}: falta kb/"
    docs = sorted(kb.glob("*.md"))
    assert len(docs) >= 2, (
        f"{target.name}: kb/ tem {len(docs)} documento(s); o mínimo é 2 "
        "(contrato e domínio, separados)"
    )
    for doc in docs:
        assert doc.stat().st_size > 200, f"{target.name}: {doc.name} é pequeno demais para ser K"


# ---------------------------------------------------------------------- CLI


def test_eval_expoe_a_cli_padrao(target):
    """`--selftest`, `--baselines` e `--budget` são o contrato de todo avaliador.

    O CI e o hook do Claude Code chamam exatamente estes três. Um alvo que não os
    expõe quebra a automação em silêncio: o comando sai 2 com "unrecognized
    arguments" e o log passa despercebido no meio da saída do pytest.
    """
    avaliador = target / "eval.py"
    assert avaliador.is_file(), f"{target.name}: falta eval.py"

    run = run_eval(target, "--help")
    assert run.exit_code == 0, f"{target.name}: --help falhou{run.dump()}"
    for flag in ("--workdir", "--baselines", "--selftest", "--budget"):
        assert flag in run.stdout, f"{target.name}: --help não menciona {flag}{run.dump()}"


# -------------------------------------------------------------------- dados


def test_dataset_lock_existe_e_confere(target):
    """O lock é commitado; os dados não. Ausência pula, divergência falha."""
    estado, detalhe = dataset_status(target)
    if estado == "sem_lock":
        pytest.fail(
            f"{target.name}: {detalhe}. O lock é o que torna 'dataset congelado' verificável; "
            f"rode `python3 targets/{target.name}/make_data.py` e commite o lock."
        )
    if estado == "nao_gerado":
        pytest.skip(
            f"{target.name}: dataset não gerado ({detalhe}). "
            f"Rode `python3 targets/{target.name}/make_data.py`."
        )
    assert estado == "ok", (
        f"{target.name}: {detalhe}. Um arquivo que existe e não bate com o lock significa que o "
        "gerador mudou — isso move o score de todas as versões do lineage de uma vez e "
        "invalida qualquer comparação entre braços da ablação."
    )


# ------------------------------------------------------------------ Falha 1


@pytest.mark.slow
def test_selftest_verde_e_declara_mutantes_suficientes(target):
    """Falha 1: um gate que nunca foi atacado não é gate, é esperança.

    Três coisas na mesma passada, porque são a mesma chamada de subprocesso: sai
    zero, imprime a marca que o CI procura, e a tabela declara pelo menos cinco
    mutantes. O mínimo de cinco é do laboratório e está codificado também em
    `MutantSuite.minimum`; aqui ele é verificado de fora, contra a saída real,
    para o caso de um alvo instanciar a suíte com um mínimo próprio mais frouxo.
    """
    require_dataset(target)
    run = run_eval(target, "--selftest")

    assert run.exit_code == 0, f"{target.name}: --selftest reprovou{run.dump()}"
    assert "GATE SELFTEST: OK" in run.stdout, (
        f"{target.name}: --selftest não imprimiu a marca que o CI procura{run.dump()}"
    )

    mutantes = [linha for linha in parse_selftest_table(run.stdout) if linha.e_mutante]
    assert len(mutantes) >= 5, (
        f"{target.name}: só {len(mutantes)} mutantes na tabela; o mínimo do laboratório é 5. "
        "Dois mutantes óbvios não provam que o gate morde."
    )


# --------------------------------------------------------------------- seed


@pytest.mark.slow
def test_seed_passa_no_proprio_gate(target, tmp_path):
    """O `x_0` tem que ser correto e óbvio-suboptimo, não correto-depois-de-consertar.

    Um seed que reprova no próprio gate transforma os primeiros passos da busca
    em conserto do alvo. Pior para a ablação: o custo desse conserto é ruído que
    incide igual em todos os braços e comprime a diferença que o experimento
    quer medir.

    A cópia para um tmpdir reproduz o que o harness faz no passo 0 — o agente
    edita `work/`, nunca `seed/`.
    """
    require_dataset(target)
    workdir = copy_seed(target, tmp_path / "work")

    run = run_eval(target, "--workdir", str(workdir), cache=False)
    assert run.exit_code == 0, f"{target.name}: o avaliador saiu {run.exit_code}{run.dump()}"

    resultado = parse_avo_result(run.stdout)
    assert resultado.get("correct") is True, (
        f"{target.name}: o seed não passa no próprio gate — "
        f"{resultado.get('error')!r}.{run.dump()}"
    )
    assert resultado.get("metrics"), (
        f"{target.name}: correct=true sem métricas. `primary` seria a média geométrica de "
        f"nada, e o passo 0 não teria incumbente para comparar.{run.dump()}"
    )
    assert all(isinstance(v, (int, float)) and v > 0 for v in resultado["metrics"].values()), (
        f"{target.name}: métrica não positiva zera a média geométrica: {resultado['metrics']}"
    )
