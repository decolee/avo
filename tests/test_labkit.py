"""Unidade do `labkit` — a lógica que os alvos delegam e não reimplementam.

O critério para um teste entrar aqui é ter lógica que possa estar errada sem
ninguém perceber. Um `dataclass` que só guarda campos não entra; a
canonicalização, a comparação com tolerância, o relatório de orçamento, a suíte
de mutantes e o lock de dataset entram, porque cada um deles decide sozinho se
um candidato é aceito ou se um experimento é comparável.

Vários destes testes são regressões nomeadas de falhas que já aconteceram e
estão registradas em `docs/PLANO_AVO_DATA_ENGINEERING.md` §3. Onde for o caso, o
docstring diz qual.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from labkit import contracts, datakit, evalkit  # noqa: E402

# ===================================================================== canon


def test_canon_hash_ignora_ordem_de_insercao():
    """A ordem em que o candidato monta o dict não é parte do contrato.

    Exigir ordem de inserção reprovaria código correto — e reprovar candidato
    bom envenena a busca tanto quanto aprovar candidato ruim, porque o agente
    aprende que a mudança certa foi rejeitada.
    """
    a = {"x": {"n": 1, "v": 2.5}, "y": {"n": 3, "v": 4.5}}
    b = {"y": {"n": 3, "v": 4.5}, "x": {"n": 1, "v": 2.5}}

    campos = ("n", "v")
    casas = {"v": 2}
    assert contracts.canon_hash(a, campos, casas) == contracts.canon_hash(b, campos, casas)


def test_canon_hash_e_sensivel_a_valor():
    a = {"x": {"n": 1, "v": 2.50}}
    b = {"x": {"n": 1, "v": 2.51}}
    campos, casas = ("n", "v"), {"v": 2}
    assert contracts.canon_hash(a, campos, casas) != contracts.canon_hash(b, campos, casas)


def test_canon_hash_e_sensivel_a_chave():
    """Renomear um grupo muda a saída, mesmo com os mesmos valores."""
    a = {"x": {"n": 1}}
    b = {"y": {"n": 1}}
    assert contracts.canon_hash(a, ("n",)) != contracts.canon_hash(b, ("n",))


def test_canon_hash_normaliza_zero_negativo():
    """`-0.0` e `0.0` são o mesmo dinheiro.

    Uma soma que passa por um valor negativo e volta pode terminar em `-0.0`.
    Se o hash enxergasse o sinal do zero, dois candidatos igualmente corretos
    teriam impressões digitais diferentes por acidente de ordem de soma.
    """
    positivo = {"x": {"v": 0.0}}
    negativo = {"x": {"v": -0.0}}
    casas = {"v": 2}
    assert contracts.canon_hash(positivo, ("v",), casas) == contracts.canon_hash(
        negativo, ("v",), casas
    )


def test_canon_hash_campo_ausente_vira_canon_error():
    """Campo faltando é violação de contrato, não hash diferente.

    Devolver um hash divergente diria ao agente "seu valor está errado" quando o
    problema é que a chave nem existe. `CanonError` nomeia a chave e o campo.
    """
    with pytest.raises(contracts.CanonError) as exc:
        contracts.canon_hash({"x": {"n": 1}}, ("n", "v"))
    assert "'x'" in str(exc.value)
    assert "'v'" in str(exc.value)


def test_canon_hash_recusa_valor_nao_finito():
    """`nan` e `inf` não têm apresentação de duas casas; são erro de contrato."""
    for ruim in (float("nan"), float("inf")):
        with pytest.raises(contracts.CanonError):
            contracts.canon_hash({"x": {"v": ruim}}, ("v",), {"v": 2})


def test_canon_hash_rows_a_ordem_das_linhas_importa():
    """Para result set com ORDER BY declarado, a ordem É o contrato.

    É a diferença entre `canon_hash` (mapa: ordem livre) e `canon_hash_rows`
    (tabela: ordem fixa). Trocar um pelo outro num alvo de SQL deixaria passar
    uma consulta sem ORDER BY.
    """
    linhas = [("a", 1.0), ("b", 2.0)]
    invertidas = list(reversed(linhas))
    assert contracts.canon_hash_rows(linhas) != contracts.canon_hash_rows(invertidas)
    assert contracts.canon_hash_rows(linhas) == contracts.canon_hash_rows(list(linhas))


def test_canon_hash_rows_respeita_as_casas_declaradas():
    """`places` define até onde a diferença conta como diferença."""
    grosso = contracts.canon_hash_rows([(1.0000001,)], places=2)
    igual = contracts.canon_hash_rows([(1.0,)], places=2)
    fino = contracts.canon_hash_rows([(1.0000001,)], places=9)
    diferente = contracts.canon_hash_rows([(1.0,)], places=9)
    assert grosso == igual
    assert fino != diferente


# ========================================================== compare_mappings


REF = {"a": {"n": 1, "v": 10.0}, "b": {"n": 2, "v": 20.0}}


def _compara(got, **kw):
    return contracts.compare_mappings(
        REF, got, exact_fields=("n",), float_fields=("v",), **{"tol": 1e-9, **kw}
    )


def test_compare_mappings_aceita_igual():
    ok, detalhe = _compara({"a": {"n": 1, "v": 10.0}, "b": {"n": 2, "v": 20.0}})
    assert ok, detalhe


def test_compare_mappings_chave_faltando():
    ok, detalhe = _compara({"a": {"n": 1, "v": 10.0}})
    assert not ok
    assert "faltam 1" in detalhe
    assert "'b'" in detalhe


def test_compare_mappings_chave_sobrando():
    ok, detalhe = _compara(
        {"a": {"n": 1, "v": 10.0}, "b": {"n": 2, "v": 20.0}, "c": {"n": 3, "v": 30.0}}
    )
    assert not ok
    assert "sobram 1" in detalhe
    assert "'c'" in detalhe


def test_compare_mappings_campo_exato_errado():
    ok, detalhe = _compara({"a": {"n": 99, "v": 10.0}, "b": {"n": 2, "v": 20.0}})
    assert not ok
    assert "a.n" in detalhe
    assert "99" in detalhe


def test_compare_mappings_campo_ausente_na_linha():
    ok, detalhe = _compara({"a": {"n": 1}, "b": {"n": 2, "v": 20.0}})
    assert not ok
    assert "a.v" in detalhe and "ausente" in detalhe


def test_compare_mappings_float_dentro_e_fora_da_tolerancia():
    """O eixo inteiro da Falha 1: erro pequeno passa, erro de centavo não.

    Ordem de soma erra na décima casa e tem que passar; arredondamento
    incremental erra no centavo e tem que ser pego. Uma tolerância só, explícita,
    separa os dois.
    """
    dentro, _ = _compara({"a": {"n": 1, "v": 10.0 + 1e-12}, "b": {"n": 2, "v": 20.0}}, tol=1e-9)
    assert dentro

    fora, detalhe = _compara({"a": {"n": 1, "v": 10.01}, "b": {"n": 2, "v": 20.0}}, tol=1e-9)
    assert not fora
    assert "a.v" in detalhe
    assert "tol" in detalhe and "erro" in detalhe


def test_compare_mappings_tol_callable_da_folga_por_chave():
    """Tolerância constante é errada quando as magnitudes variam.

    Um grupo somando 1e10 acumula erro de ponto flutuante ordens de grandeza
    maior que um somando 1e3. Uma tolerância que sirva para o primeiro perdoa
    erro real no segundo — então a folga é calculada a partir da magnitude do
    grupo, e é isso que a forma de função permite.
    """
    esperado = {"grande": {"v": 1e10}, "pequeno": {"v": 1e3}}
    obtido = {"grande": {"v": 1e10 + 0.5}, "pequeno": {"v": 1e3 + 0.5}}

    def tol(_chave, _campo, linha):
        return abs(linha["v"]) * 1e-9  # 10.0 para o grande, 1e-6 para o pequeno

    ok, detalhe = contracts.compare_mappings(
        esperado, obtido, float_fields=("v",), tol=tol, max_report=5
    )
    assert not ok
    assert "pequeno.v" in detalhe, "o grupo pequeno tem que reprovar com o mesmo erro absoluto"
    assert "grande.v" not in detalhe, "o grupo grande tem folga proporcional e passa"


def test_compare_mappings_recusa_tipo_errado():
    ok, detalhe = contracts.compare_mappings(REF, ["não", "é", "dict"])
    assert not ok
    assert "list" in detalhe

    ok, detalhe = _compara({"a": ["não é dict"], "b": {"n": 2, "v": 20.0}})
    assert not ok
    assert "a:" in detalhe and "list" in detalhe


def test_compare_mappings_max_report_limita_o_ruido():
    """Uma rejeição com 4 mil linhas de diff não é diagnóstico, é despejo."""
    esperado = {str(i): {"n": i} for i in range(50)}
    obtido = {str(i): {"n": -1} for i in range(50)}
    ok, detalhe = contracts.compare_mappings(esperado, obtido, exact_fields=("n",), max_report=3)
    assert not ok
    assert detalhe.count(";") <= 2


# =============================================================== stdlib_only


def _modulo(tmp_path: Path, corpo: str, nome: str = "cand.py") -> str:
    caminho = tmp_path / nome
    caminho.write_text(corpo, encoding="utf-8")
    return str(caminho)


def test_stdlib_only_aceita_a_stdlib(tmp_path):
    caminho = _modulo(
        tmp_path,
        "import json\nimport os.path\nfrom collections import defaultdict\n\nX = 1\n",
    )
    ok, detalhe = contracts.stdlib_only(caminho)
    assert ok, detalhe


def test_stdlib_only_recusa_terceiro(tmp_path):
    caminho = _modulo(tmp_path, "import json\nimport pandas as pd\nfrom numpy import array\n")
    ok, detalhe = contracts.stdlib_only(caminho)
    assert not ok
    assert "pandas" in detalhe and "numpy" in detalhe
    assert "stdlib" in detalhe


def test_stdlib_only_respeita_allowed_extra(tmp_path):
    """Um alvo pode permitir uma dependência específica — e só ela."""
    caminho = _modulo(tmp_path, "import numpy\nimport pandas\n")
    ok, _ = contracts.stdlib_only(caminho, allowed_extra=("numpy",))
    assert not ok, "pandas continua proibido"
    ok, detalhe = contracts.stdlib_only(caminho, allowed_extra=("numpy", "pandas"))
    assert ok, detalhe


def test_stdlib_only_syntax_error_e_um_motivo_diferente(tmp_path):
    """Arquivo que não compila reprova, mas não por causa de import.

    Embrulhar `SyntaxError` numa frase sobre stdlib manda o agente investigar a
    coisa errada — ele passaria o passo seguinte procurando um import que não
    existe.
    """
    caminho = _modulo(tmp_path, "def transform(:\n    pass\n")
    ok, detalhe = contracts.stdlib_only(caminho)
    assert not ok
    assert "SyntaxError" in detalhe
    assert "não compila" in detalhe
    assert "stdlib" not in detalhe


def test_stdlib_only_nao_confunde_import_relativo(tmp_path):
    """`from . import x` não é dependência externa; é o próprio pacote do candidato."""
    caminho = _modulo(tmp_path, "from . import helper\nfrom .util import parse\nimport json\n")
    ok, detalhe = contracts.stdlib_only(caminho)
    assert ok, detalhe


def test_stdlib_only_pega_import_dentro_de_funcao(tmp_path):
    """Esconder o import dentro da função não escapa: a checagem é sobre a AST inteira."""
    caminho = _modulo(tmp_path, "def transform(p):\n    import scipy\n    return scipy\n")
    ok, detalhe = contracts.stdlib_only(caminho)
    assert not ok
    assert "scipy" in detalhe


# ================================================================ Measurement


def _medicao() -> evalkit.Measurement:
    return evalkit.Measurement(
        per_regime={"rapido": 0.25, "lento": 0.5},
        raw={"rapido": [0.24, 0.25, 0.26], "lento": [0.5, 0.5, 0.5]},
        wall_s=3.2,
    )


def test_throughput_inverte_a_mediana():
    assert _medicao().throughput() == {"rapido": 4.0, "lento": 2.0}


def test_throughput_ignora_regime_de_tempo_zero():
    """Divisão por zero viraria `inf` e contaminaria a média geométrica."""
    m = evalkit.Measurement(per_regime={"ok": 0.5, "instantaneo": 0.0})
    assert m.throughput() == {"ok": 2.0}


def test_spread_mede_ruido_e_nao_inventa_quando_nao_da():
    espalhamento = _medicao().spread()
    assert espalhamento["lento"] == 0.0, "três medidas idênticas: ruído zero"
    assert espalhamento["rapido"] > 0.0

    unica = evalkit.Measurement(per_regime={"r": 0.1}, raw={"r": [0.1]})
    assert unica.spread() == {}, "com uma execução só não há variância a reportar"


def test_notes_carrega_medianas_ordenadas_e_custo():
    notas = _medicao().notes()
    assert "medianas:" in notas
    assert notas.index("lento") < notas.index("rapido"), "ordenado por nome, para diff estável"
    assert "250.0ms" in notas and "500.0ms" in notas
    assert "3.2s" in notas


# ============================================================== budget_report


def test_budget_report_saudavel():
    ok, msg = evalkit.budget_report(6.0, fastest_run_s=0.12)
    assert ok
    assert "saudável" in msg


def test_budget_report_estoura_o_teto():
    """Falha 2: o seed levava 140 s por avaliação e o primeiro passo custou 2,3 min."""
    ok, msg = evalkit.budget_report(evalkit.BUDGET_CEILING_S + 1)
    assert not ok
    assert "Reduza o dataset" in msg
    assert "SEED" in msg, "a mensagem tem que dizer por qual versão dimensionar"


def test_budget_report_abaixo_do_piso():
    """O piso protege o SINAL, não o tempo do agente — é a outra ponta da régua."""
    ok, msg = evalkit.budget_report(5.0, fastest_run_s=evalkit.RUN_FLOOR_S / 2)
    assert not ok
    assert "ruído" in msg
    assert "Aumente o dataset" in msg


def test_budget_report_reporta_os_dois_problemas_juntos():
    ok, msg = evalkit.budget_report(evalkit.BUDGET_CEILING_S + 1, fastest_run_s=0.001)
    assert not ok
    assert "|" in msg, "os dois problemas são independentes e aparecem os dois"


def test_budget_report_sem_estimativa_do_mais_rapido():
    """Nem todo alvo sabe estimar seu candidato mais rápido; isso não é falha."""
    ok, msg = evalkit.budget_report(4.0)
    assert ok
    assert "execução mais rápida" not in msg


# ================================================================ MutantSuite


def _suite(mutantes: int = 5, sobrevivente: bool = False, minimo: int = 5):
    """Uma suíte sintética: a referência devolve `"certo"`, os mutantes não.

    O `sobrevivente` é o caso que este laboratório existe para não deixar
    acontecer: um mutante que o gate aprova.
    """

    def referencia():
        return "certo"

    lista = [(f"m{i}", (lambda: "errado")) for i in range(mutantes)]
    if sobrevivente and lista:
        lista[0] = ("finge_ser_correto", lambda: "certo")
    return evalkit.MutantSuite(reference=referencia, mutants=lista, minimum=minimo)


GATE_SINTETICO = evalkit.Gate(
    judge=lambda fn: (fn() == "certo", "ok" if fn() == "certo" else "saída divergente"),
    description="gate de brinquedo para exercitar a MutantSuite",
)


def test_mutant_suite_passa_quando_todos_os_mutantes_falham():
    passou, linhas = _suite().run(GATE_SINTETICO)
    assert passou
    assert linhas[0][1] is True, "a referência tem que passar"
    assert all(not ok for _, ok, _ in linhas[1:]), "nenhum mutante pode passar"


def test_mutant_suite_falha_quando_um_mutante_sobrevive():
    """O único bug que esta bancada não pode ter.

    Um gate que aprova mutante aceita candidato errado como melhoria — é o teto
    de verificador imperfeito de *Inference Scaling fLaws*: mais compute não
    conserta, só produz mais rápido a coisa errada.
    """
    passou, linhas = _suite(sobrevivente=True).run(GATE_SINTETICO)
    assert not passou
    sobreviventes = [nome for nome, ok, _ in linhas[1:] if ok]
    assert sobreviventes == ["mutante finge_ser_correto (deve falhar)"]

    saida = io.StringIO()
    assert _suite(sobrevivente=True).selftest(GATE_SINTETICO, stream=saida) is False
    assert "GATE FURADO" in saida.getvalue()


def test_mutant_suite_falha_com_menos_que_o_minimo():
    """Quatro mutantes bem escolhidos ainda são poucos: o mínimo é do laboratório.

    A regra existe porque a tentação, ao criar um alvo, é escrever dois mutantes
    óbvios e declarar o gate testado.
    """
    passou, _ = _suite(mutantes=3).run(GATE_SINTETICO)
    assert not passou, "todos falharam, mas são poucos: continua reprovado"

    saida = io.StringIO()
    _suite(mutantes=3).selftest(GATE_SINTETICO, stream=saida)
    texto = saida.getvalue()
    assert "Só 3 mutantes" in texto
    assert "mínimo do laboratório é 5" in texto


def test_mutant_suite_falha_quando_a_referencia_reprova():
    """Gate quebrado ao contrário: reprova o código correto."""
    gate_paranoico = evalkit.Gate(judge=lambda _fn: (False, "reprova tudo"))
    passou, linhas = _suite().run(gate_paranoico)
    assert not passou
    assert linhas[0][1] is False


def test_selftest_imprime_a_marca_que_o_ci_procura():
    saida = io.StringIO()
    assert _suite().selftest(GATE_SINTETICO, stream=saida) is True
    texto = saida.getvalue()
    assert "GATE SELFTEST: OK" in texto
    assert texto.count("FAIL") == 5
    assert texto.count("PASS") == 1


def test_gate_transforma_excecao_do_candidato_em_reprovacao():
    """Candidato que explode é candidato reprovado, não avaliador quebrado."""

    def explode(_fn):
        raise RuntimeError("boom")

    ok, detalhe = evalkit.Gate(judge=explode).check(lambda: None)
    assert not ok
    assert "RuntimeError: boom" in detalhe


# ==================================================================== datakit


def _spec(nome: str = "d.txt", conteudo: str = "linha\n" * 10) -> datakit.DatasetSpec:
    def build(caminho: Path) -> None:
        caminho.write_text(conteudo, encoding="utf-8")

    return datakit.DatasetSpec(nome, build, purpose="fixture de teste", rows=10)


def test_generate_e_idempotente(tmp_path):
    """`make setup` roda a cada sessão; regerar 20 MB toda vez é desperdício."""
    specs = [_spec()]
    primeiro = datakit.generate(tmp_path, specs)
    assert primeiro.written == ["d.txt"]
    assert primeiro.lock_written

    segundo = datakit.generate(tmp_path, specs)
    assert segundo.written == []
    assert segundo.skipped == ["d.txt"]
    assert not segundo.lock_written, "lock idêntico não é reescrito"
    assert "já existiam" in segundo.render()


def test_generate_force_reconstroi(tmp_path):
    specs = [_spec()]
    datakit.generate(tmp_path, specs)
    forcado = datakit.generate(tmp_path, specs, force=True)
    assert forcado.written == ["d.txt"]


def test_lock_e_estavel_entre_execucoes(tmp_path):
    """O lock é commitado: instabilidade no conteúdo vira ruído em todo diff."""
    specs = [_spec()]
    datakit.generate(tmp_path, specs)
    texto = datakit.dataset_lock_path(tmp_path).read_text(encoding="utf-8")
    datakit.generate(tmp_path, specs, force=True)
    assert datakit.dataset_lock_path(tmp_path).read_text(encoding="utf-8") == texto

    lock = json.loads(texto)
    assert lock["files"]["d.txt"]["sha256"] == datakit.sha256_file(tmp_path / "data" / "d.txt")
    assert lock["files"]["d.txt"]["rows"] == 10


def test_verify_lock_aprova_o_que_foi_gerado(tmp_path):
    datakit.generate(tmp_path, [_spec()])
    ok, detalhe = datakit.verify_lock(tmp_path)
    assert ok, detalhe
    assert "1 arquivo" in detalhe


def test_verify_lock_distingue_alterado_de_ausente(tmp_path):
    """Os dois erros pedem consertos opostos, então as mensagens têm que diferir.

    Arquivo ausente numa máquina limpa se resolve com `make data`. Arquivo
    alterado significa que o gerador mudou — e um gerador que muda move o score
    de todas as versões do lineage de uma vez, invalidando a comparação que é o
    ponto do experimento.
    """
    specs = [_spec()]
    datakit.generate(tmp_path, specs)
    arquivo = tmp_path / "data" / "d.txt"

    arquivo.write_text("conteúdo diferente\n", encoding="utf-8")
    ok, alterado = datakit.verify_lock(tmp_path)
    assert not ok
    assert "checksum divergente" in alterado
    assert "gerador" in alterado

    arquivo.unlink()
    ok, ausente = datakit.verify_lock(tmp_path)
    assert not ok
    assert "ausente" in ausente
    assert "make data" in ausente

    assert alterado != ausente
    assert "checksum divergente" not in ausente


def test_verify_lock_sem_lock(tmp_path):
    ok, detalhe = datakit.verify_lock(tmp_path)
    assert not ok
    assert datakit.LOCK_NAME in detalhe


def test_verify_lock_com_lock_ilegivel(tmp_path):
    """JSON truncado não pode virar `KeyError` no meio de uma avaliação."""
    datakit.generate(tmp_path, [_spec()])
    datakit.dataset_lock_path(tmp_path).write_text("{ isto não é json", encoding="utf-8")
    ok, detalhe = datakit.verify_lock(tmp_path)
    assert not ok
    assert "ilegível" in detalhe


def test_require_diz_como_gerar(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        datakit.require(tmp_path, "nao_existe.jsonl")
    assert "make data" in str(exc.value)
    assert "nao_existe.jsonl" in str(exc.value)


# ================================================================== load_module


def test_load_module_nao_deixa_lixo_no_sys_modules_quando_falha(tmp_path):
    """Um candidato que explode no import não pode envenenar o import seguinte.

    Sem a limpeza, o módulo meio-inicializado ficaria em `sys.modules` sob o
    mesmo nome e a próxima avaliação importaria o cadáver do anterior.
    """
    ruim = tmp_path / "ruim.py"
    ruim.write_text("raise RuntimeError('falhei no import')\n", encoding="utf-8")

    with pytest.raises(RuntimeError):
        evalkit.load_module(ruim, "candidato_de_teste")
    assert "candidato_de_teste" not in sys.modules


def test_as_callable_diagnostica_simbolo_ausente(tmp_path):
    modulo = evalkit.load_module(
        _modulo(tmp_path, "transform = 42\n", nome="sem_funcao.py"), "sem_funcao"
    )
    with pytest.raises(AttributeError, match="não é chamável"):
        contracts.as_callable(modulo, "transform")
    with pytest.raises(AttributeError, match="não definido"):
        contracts.as_callable(modulo, "inexistente")
