"""O detector de sessão cega não pode reprovar quem mediu — regressão do
falso negativo achado na ablação do `sql_workload`.

`destilar_logs.exige_visao` é o portão que roda ANTES de qualquer estatística:
uma sessão que escreveu código sem nunca medir não testa o que o desenho diz
testar, e a média dela contamina o braço inteiro. Foi assim que dois
experimentos e US$ 343 produziram números que pareciam resultado.

Mas o portão errava dos dois lados, e o erro só apareceu quando ele reprovou 7
de 160 sessões-passo das quais **6 tinham medido**:

* do lado da TENTATIVA, ele casava `avo-eval`/`eval.py` em qualquer lugar do
  comando — `cat eval.py`, `sed -n ... eval.py` e `grep ... eval.py` contavam
  como tentativa de medir (254 `cat`, 227 `sed`, 126 `grep` em 300 transcrições);
* do lado da MEDIÇÃO, ele exigia `AVO_RESULT:` ou `medianas:` no resultado, que
  é o stdout *padrão*. Quem canaliza para um parser ou importa `medir()` para
  fazer comparação pareada não emite nenhuma das duas.

O detector marcava como cega exatamente a sessão que mede melhor. Estes testes
fixam as duas direções: o que conta como medição, e o que continua NÃO contando.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments" / "ablacao"))

import destilar_logs as dl  # noqa: E402


# --------------------------------------------------------- executa x lê
def test_ler_o_fonte_do_avaliador_nao_e_medir():
    """A regressão direta: ler `eval.py` não é rodar `eval.py`."""
    for cmd in (
        "cat targets/sql_workload/eval.py",
        "sed -n '820,865p' eval.py",
        "grep -n '_rodar_lote' -A25 eval.py | head -40",
        "ls -la && cat avo-eval",
        "wc -l eval.py",
    ):
        assert not dl.executa_avaliador(cmd), cmd
        assert dl.so_le_arquivo(cmd), cmd


def test_rodar_o_avaliador_e_medir():
    for cmd in (
        "./avo-eval",
        "./avo-eval && ./avo-eval",
        "cd /run/dir && ./avo-eval",
        "python3 targets/sql_workload/eval.py --selftest",
        "PYTHONPATH=x python3 -m avo.cli eval --run runs/abc",
    ):
        assert dl.executa_avaliador(cmd), cmd


def test_heredoc_nao_e_comando():
    """Escrever SOBRE medir, no NOTES.md, não é medir.

    O agente documenta o passo citando `./avo-eval` em português. Sem tirar o
    corpo do heredoc, o detector credita uma medição a quem só escreveu uma nota.
    """
    cmd = (
        "cat >> NOTES.md <<'EOF'\n"
        "## Passo 8\n"
        "Medido com `./avo-eval`, 11 rodadas alternadas: primary=9.37\n"
        "EOF"
    )
    assert not dl.executa_avaliador(cmd)
    assert not dl.mediu(cmd, "ok")


# --------------------------------------------------------- o que conta
def test_saida_parseada_conta_como_medicao():
    """O falso negativo que motivou o conserto."""
    cmd = './avo-eval | python3 -c "import json,sys; d=json.load(sys.stdin); print(d)"'
    saida = "correct= True primary= 10.0007 {'estreito': 40.166, 'frio': 2.543}"
    assert dl.mediu(cmd, saida)


def test_harness_proprio_sobre_medir_conta():
    """Importar `medir()` para comparação pareada é medir — e medir melhor."""
    cmd = "SP=/tmp/perf.py; python3 $SP"
    saida = "base 9.8685 True {'estreito': 40.38, 'frio': 2.51}\nnovo 10.0411 True {...}"
    assert dl.mediu(cmd, saida)


def test_prosa_com_numero_nao_conta():
    """`cat NOTES.md` devolve "primary = 1.16" em prosa e não mediu nada.

    Este é o motivo de a forma-do-resultado não bastar sozinha: ela sozinha dá
    16,9% de falso positivo sobre comandos que são só leitura.
    """
    cmd = "ls && echo '---NOTES---' && cat NOTES.md"
    saida = "o seed marca primary = 1.16 e o v3 chegou a quente=8.4"
    assert not dl.mediu(cmd, saida)


def test_sem_tentativa_nenhuma_continua_cega():
    """Quem não chamou o avaliador nenhuma vez segue cego.

    É o caso do `no_kb-s4/step-0008` da ablação: 0 tentativas, e o conserto
    NÃO pode absolvê-lo.
    """
    cmd = "git -C work status --porcelain"
    assert not dl.tentou_medir(cmd)
    assert not dl.mediu(cmd, "M q2.sql")


def test_recusa_de_permissao_nao_e_medicao():
    cmd = "./avo-eval"
    assert dl.mediu(cmd, "primary=8.4")  # a chamada em si mediria...
    # ...mas `destila` conta recusa antes de creditar medição; ver o corpo dele.
    assert any(x in "claude requires approval to use bash" for x in dl._RECUSA)
