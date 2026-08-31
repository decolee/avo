"""A medição não pode ser trapaceável — regressão da Falha 5.

Um candidato que memoiza a saída devolve o resultado certo instantaneamente da
segunda chamada em diante. Ele **passa em qualquer gate de correção**, porque o
resultado está correto, e marca um score ordens de grandeza maior sem ter
otimizado nada. Medido no `etl_agg` antes da defesa: 4.672.896 contra 4,16 do
seed.

Estes testes provam que as duas camadas de defesa do `labkit` funcionam, e que
todo alvo do repositório as usa. Sem elas, qualquer ablação mede memoização em
vez de arquitetura.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from labkit import evalkit  # noqa: E402

TARGETS = sorted(p.parent for p in (ROOT / "targets").glob("*/target.yaml"))


# ------------------------------------------------------ as primitivas do labkit


def test_unique_alias_da_caminho_novo_para_o_mesmo_conteudo(tmp_path):
    origem = tmp_path / "dados.txt"
    origem.write_text("conteudo", encoding="utf-8")
    alias_dir = tmp_path / "alias"
    alias_dir.mkdir()

    primeiro = evalkit.unique_alias(origem, alias_dir)
    segundo = evalkit.unique_alias(origem, alias_dir)

    assert primeiro != segundo, "dois aliases seguidos precisam ter caminhos diferentes"
    assert Path(primeiro).read_text(encoding="utf-8") == "conteudo"
    assert Path(segundo).read_text(encoding="utf-8") == "conteudo"


def test_args_factory_e_chamado_a_cada_execucao():
    chamadas = []
    regime = evalkit.Regime("r", (), args_factory=lambda: (len(chamadas),))

    def fn(valor):
        chamadas.append(valor)

    evalkit.measure(fn, [regime], repeats=3, warmup=1)

    assert len(chamadas) == 4, "1 aquecimento + 3 repetições"
    assert len(set(chamadas)) == 4, "cada execução recebeu argumentos novos"


def test_fn_factory_descarta_estado_entre_execucoes():
    """A defesa geral: módulo novo por execução mata qualquer memoização."""
    criados = []

    def factory():
        cache = {}  # o "estado de módulo" de um candidato memoizador

        def fn(chave):
            if chave in cache:
                cache["reaproveitou"] = True
            cache[chave] = True
            criados.append(cache)
            return cache

        return fn

    regime = evalkit.Regime("r", ("mesma-chave",))
    evalkit.measure(lambda _: None, [regime], repeats=3, warmup=1, fn_factory=factory)

    assert len(criados) == 4
    assert not any("reaproveitou" in c for c in criados), (
        "nenhum cache pode sobreviver de uma execução para a outra"
    )


def test_memoizacao_nao_sobrevive_ao_fn_factory():
    """O ataque real, em miniatura: sem factory o cache acerta; com factory, não."""
    trabalho = []

    def faz_candidato():
        cache = {}

        def transform(path):
            if path in cache:
                return cache[path]
            trabalho.append(path)  # só conta quando o trabalho é de fato feito
            cache[path] = {"ok": True}
            return cache[path]

        return transform

    regime = evalkit.Regime("r", ("/mesmo/caminho",))

    trabalho.clear()
    evalkit.measure(faz_candidato(), [regime], repeats=4, warmup=1)
    com_cache = len(trabalho)

    trabalho.clear()
    evalkit.measure(faz_candidato(), [regime], repeats=4, warmup=1, fn_factory=faz_candidato)
    sem_cache = len(trabalho)

    assert com_cache == 1, "sem defesa, o cache acerta e o trabalho é feito uma vez só"
    assert sem_cache == 5, "com módulo novo por execução, toda execução paga o trabalho"


def test_no_disk_writes_libera_leitura(tmp_path):
    """Ler nunca pode ser bloqueado: nos alvos de throughput, ler É o trabalho."""
    entrada = tmp_path / "entrada.txt"
    entrada.write_bytes(b"dados")

    violacoes: list[str] = []
    with evalkit.no_disk_writes(violacoes):
        assert entrada.read_bytes() == b"dados"

    assert violacoes == []


def test_no_disk_writes_bloqueia_escrita(tmp_path):
    """Terceira camada: um cache em disco sobrevive às duas primeiras."""
    alvo = tmp_path / "cache.json"

    violacoes: list[str] = []
    with evalkit.no_disk_writes(violacoes), pytest.raises(PermissionError):
        alvo.write_text("resultado memoizado", encoding="utf-8")

    assert len(violacoes) == 1
    assert "cache.json" in violacoes[0]
    assert not alvo.exists(), "o arquivo não pode chegar a existir"


def test_no_disk_writes_anota_mesmo_se_o_candidato_engolir_a_excecao(tmp_path):
    """Embrulhar o `open` em try/except não apaga o registro da violação.

    Sem isso, a defesa seria contornável com quatro caracteres de código.
    """
    violacoes: list[str] = []
    with evalkit.no_disk_writes(violacoes):
        # try/except literal de proposito: e a forma que um candidato usaria para
        # esconder a tentativa. `contextlib.suppress` seria equivalente e menos
        # ilustrativo do ataque que este teste existe para descrever.
        try:  # noqa: SIM105
            (tmp_path / "escondido.json").write_text("x", encoding="utf-8")
        except PermissionError:
            pass

    assert len(violacoes) == 1, "a violação é anotada antes de a exceção subir"
    assert "escondido.json" in violacoes[0]


def test_no_disk_writes_restaura_as_portas(tmp_path):
    violacoes: list[str] = []
    with evalkit.no_disk_writes(violacoes):
        pass
    (tmp_path / "depois.txt").write_text("ok", encoding="utf-8")
    assert (tmp_path / "depois.txt").read_text(encoding="utf-8") == "ok"


def test_no_disk_writes_libera_bytecode(tmp_path):
    """`.pyc` é liberado: um import tardio grava bytecode e é candidato honesto."""
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    violacoes: list[str] = []
    with evalkit.no_disk_writes(violacoes):
        (pycache / "modulo.cpython-311.pyc").write_bytes(b"\x00")
    assert violacoes == []


def test_implausible_speed_pega_o_que_e_rapido_demais():
    suspeito, detalhe = evalkit.implausible_speed({"r": 0.0001}, {"r": 0.010})
    assert suspeito
    assert "memoizado" in detalhe or "cacheado" in detalhe

    suspeito, _ = evalkit.implausible_speed({"r": 0.050}, {"r": 0.010})
    assert not suspeito, "mais lento que o piso de leitura é plausível"


def test_implausible_speed_ignora_regime_sem_piso():
    suspeito, _ = evalkit.implausible_speed({"r": 0.000001}, {})
    assert not suspeito, "sem piso declarado não há como julgar; não invente suspeita"


# ------------------------------------------ todo alvo precisa usar as defesas


@pytest.mark.parametrize("target", TARGETS, ids=lambda p: p.name)
def test_alvo_defende_a_medicao(target: Path):
    """Todo alvo cronometrado precisa das duas camadas contra memoização.

    Um alvo cuja métrica não é tempo (qualidade sob orçamento, por exemplo) não
    é vulnerável da mesma forma e declara isso com `SEM_DEFESA_DE_MEDICAO` no
    `eval.py`, junto com o motivo.
    """
    fonte = (target / "eval.py").read_text(encoding="utf-8")
    if "SEM_DEFESA_DE_MEDICAO" in fonte:
        pytest.skip(f"{target.name} declara que não cronometra candidato")

    faltando = [
        nome for nome in ("args_factory", "fn_factory", "implausible_speed") if nome not in fonte
    ]
    assert not faltando, (
        f"{target.name}/eval.py não usa {', '.join(faltando)}. Sem isso, um candidato "
        "que memoiza a saída passa no gate e marca um score milhares de vezes maior "
        "sem ter otimizado nada. Ver docs/TARGET_DESIGN.md §3b."
    )


@pytest.mark.slow
@pytest.mark.parametrize("target", TARGETS, ids=lambda p: p.name)
def test_candidato_memoizador_nao_pontua(target: Path, tmp_path: Path):
    """Fim a fim: constrói um memoizador em cima do seed e confirma que não paga.

    É o teste que mais se aproxima do ataque real. Ele embrulha o próprio seed
    do alvo, então continua correto por construção — e é exatamente por isso que
    nenhum gate de correção o pegaria.
    """
    import json

    yaml_text = (target / "target.yaml").read_text(encoding="utf-8")
    if "SEM_DEFESA_DE_MEDICAO" in (target / "eval.py").read_text(encoding="utf-8"):
        pytest.skip(f"{target.name} não cronometra candidato")

    seed_dir = target / "seed"
    pontos_de_entrada = sorted(seed_dir.glob("*.py"))
    if not pontos_de_entrada:
        pytest.skip(f"{target.name} não tem seed em Python (entrypoint não é módulo)")
    if "entrypoint" not in yaml_text:
        pytest.skip(f"{target.name} não declara entrypoint")

    entrypoint = next(
        (
            linha.split(":", 1)[1].strip()
            for linha in yaml_text.splitlines()
            if linha.startswith("entrypoint:")
        ),
        None,
    )
    if not entrypoint or not (seed_dir / entrypoint).exists():
        pytest.skip(f"{target.name}: entrypoint {entrypoint!r} não é um módulo do seed")

    def roda(workdir: Path) -> dict:
        proc = subprocess.run(
            [sys.executable, "eval.py", "--workdir", str(workdir)],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        linha = next(
            (
                ln
                for ln in reversed(proc.stdout.splitlines())
                if ln.strip().startswith("AVO_RESULT:")
            ),
            None,
        )
        assert linha, (
            f"avaliador não emitiu AVO_RESULT:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
        return json.loads(linha.split("AVO_RESULT:", 1)[1])

    honesto = tmp_path / "honesto"
    honesto.mkdir()
    for arquivo in seed_dir.iterdir():
        if arquivo.is_file():
            (honesto / arquivo.name).write_bytes(arquivo.read_bytes())

    trapaceiro = tmp_path / "trapaceiro"
    trapaceiro.mkdir()
    for arquivo in seed_dir.iterdir():
        if arquivo.is_file() and arquivo.name != entrypoint:
            (trapaceiro / arquivo.name).write_bytes(arquivo.read_bytes())
    original = (seed_dir / entrypoint).read_text(encoding="utf-8")
    simbolo = "transform" if "def transform" in original else None
    if simbolo is None:
        pytest.skip(f"{target.name}: não achei o símbolo padrão para embrulhar")
    (trapaceiro / entrypoint).write_text(
        original.replace(f"def {simbolo}(", f"def _honesto_{simbolo}(", 1)
        + f'''

import hashlib as _hashlib
import os as _os

_CACHE = {{}}


def _chave(args, kwargs):
    """Indexa pelo CONTEUDO da entrada, nao pelo caminho.

    Caminho novo a cada execucao derrota um cache indexado por caminho, mas nao
    este: dois caminhos diferentes para os mesmos bytes dao a mesma chave. So
    modulo novo por execucao derruba esta versao.
    """
    partes = []
    for valor in args:
        if isinstance(valor, (str, bytes, _os.PathLike)) and _os.path.isfile(valor):
            with open(valor, "rb") as _fh:
                partes.append(_hashlib.blake2b(_fh.read(), digest_size=16).hexdigest())
        else:
            partes.append(repr(valor))
    return (tuple(partes), tuple(sorted(repr(kv) for kv in kwargs.items())))


def {simbolo}(*args, **kwargs):
    """Memoiza pelo conteudo da entrada. Sempre correto; nunca deveria pagar."""
    try:
        chave = _chave(args, kwargs)
    except Exception:
        return _honesto_{simbolo}(*args, **kwargs)
    if chave in _CACHE:
        return _CACHE[chave]
    _CACHE[chave] = _honesto_{simbolo}(*args, **kwargs)
    return _CACHE[chave]
''',
        encoding="utf-8",
    )

    r_honesto = roda(honesto)
    r_trapaceiro = roda(trapaceiro)

    if not r_honesto.get("correct"):
        pytest.skip(f"{target.name}: o seed não passa no próprio gate; outro teste cobre isso")

    def geomean(metrics: dict) -> float:
        import math

        valores = [v for v in (metrics or {}).values() if v > 0]
        return math.exp(sum(math.log(v) for v in valores) / len(valores)) if valores else 0.0

    base = geomean(r_honesto.get("metrics"))
    trapaca = geomean(r_trapaceiro.get("metrics")) if r_trapaceiro.get("correct") else 0.0

    assert trapaca < base * 2.0, (
        f"{target.name}: memoizar rendeu {trapaca:.4g} contra {base:.4g} do seed honesto "
        f"({trapaca / base if base else float('inf'):.1f}x). A medição é trapaceável — "
        "ver docs/TARGET_DESIGN.md §3b."
    )
