"""f(x) do alvo sessionize — o arbitro. Nunca afrouxe isto para um candidato passar.

Separacao entre gate e benchmark, como em todo alvo do laboratorio: `gate_adv`
decide `correct` e so ele; os `perf_*` so medem tempo.

O que este alvo cobra e que os outros nao cobram: ORDEM. A sessao de um usuario
existe em relacao ao evento anterior dele, entao nao ha resposta correta sem
ordenar. Isso cria duas classes de erro que os outros alvos nao tem como
produzir, e o `gate_adv` foi construido em cima delas:

  A FRONTEIRA. O contrato diz que um intervalo de exatamente 1800 s MANTEM a
  sessao aberta. Trocar `>` por `>=` erra apenas nos pares que estao a
  exatamente 1800 s de distancia — e se o dataset nao tiver nenhum, o gate e
  cego para o off-by-one mais provavel do alvo. O gerador se recusa a escrever
  um dataset sem esse par.

  A MAGNITUDE DO TIMESTAMP. Ordenar `ts` como texto funciona enquanto todos
  tiverem o mesmo numero de digitos, e e um erro que passa despercebido em
  qualquer dataset limpo. O `gate_adv` tem um usuario com timestamps de
  magnitudes diferentes — o tipo de sujeira que aparece quando um campo vem de
  origem errada — e la a ordem lexicografica diverge da numerica.

Uma coisa que o contrato NAO fixa, de proposito: a ordem entre eventos do mesmo
usuario com o MESMO `ts`. Ela e inobservavel — `n` conta eventos e `inicio`/`fim`
sao valores de `ts`, entao empates com delta zero dao o mesmo resultado em
qualquer ordem. Declarar um desempate no contrato sugeriria que ele importa, e
um mutante que "quebrasse" o desempate passaria no gate por estar certo.

As tres camadas anti-memoizacao do laboratorio estao ligadas: caminho novo e
modulo novo a cada execucao medida, e proibicao de escrever em disco. Ver
`docs/TARGET_DESIGN.md` secao 3b.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import contracts, datakit, evalkit  # noqa: E402

ENTRYPOINT = "sessionize.py"
SYMBOL = "sessionize"

GAP = 1800
GATE_FILE = "gate_adv.jsonl"
REGIME_FILES = (
    ("curto", "perf_curto.jsonl", "muitos usuarios, sessoes curtas"),
    ("longo", "perf_longo.jsonl", "poucos usuarios, muitos eventos"),
    ("denso", "perf_denso.jsonl", "sessoes longas e sobrepostas"),
)


def data(nome: str) -> Path:
    return datakit.data_dir(HERE) / nome


# ----------------------------------------------------------------- referencia


def reference(path):
    """A implementacao correta. Ordena por ts e fecha a sessao em `> GAP`."""
    por_usuario: dict[str, list[tuple]] = {}
    with open(path, encoding="utf-8") as fh:
        for linha in fh:
            r = json.loads(linha)
            por_usuario.setdefault(r["user_id"], []).append((r["ts"], r["page"], r["duration_ms"]))

    saida = {}
    for uid, eventos in por_usuario.items():
        eventos.sort(key=lambda e: e[0])
        indice = 0
        inicio = anterior = eventos[0][0]
        n = 0
        paginas: set[str] = set()
        duracao = 0
        for ts, pagina, dur in eventos:
            if ts - anterior > GAP:
                saida[f"{uid}|{indice}"] = {
                    "n": n,
                    "inicio": inicio,
                    "fim": anterior,
                    "paginas": len(paginas),
                    "duracao_ms": duracao,
                }
                indice += 1
                inicio = ts
                n = 0
                paginas = set()
                duracao = 0
            anterior = ts
            n += 1
            paginas.add(pagina)
            duracao += dur
        saida[f"{uid}|{indice}"] = {
            "n": n,
            "inicio": inicio,
            "fim": anterior,
            "paginas": len(paginas),
            "duracao_ms": duracao,
        }
    return saida


# ----------------------------------------------------------------------- gate


def judge(fn) -> tuple[bool, str]:
    got = fn(str(data(GATE_FILE)))
    esperado = reference(str(data(GATE_FILE)))
    if not isinstance(got, dict):
        return False, f"{SYMBOL}() deve devolver dict, devolveu {type(got).__name__}"
    return contracts.compare_mappings(
        esperado, got, exact_fields=("n", "inicio", "fim", "paginas", "duracao_ms"), max_report=1
    )


GATE = evalkit.Gate(judge=judge, description="dataset adversarial: fronteira, empates, bordas")


def fingerprint(resultado) -> str:
    return contracts.canon_hash(resultado, fields=("n", "inicio", "fim", "paginas", "duracao_ms"))[
        :16
    ]


# ------------------------------------------------------------------- mutantes


def _eventos_por_usuario(path):
    por_usuario: dict[str, list[tuple]] = {}
    with open(path, encoding="utf-8") as fh:
        for linha in fh:
            r = json.loads(linha)
            por_usuario.setdefault(r["user_id"], []).append((r["ts"], r["page"], r["duration_ms"]))
    return por_usuario


def _sessionizar(
    por_usuario, gap=GAP, estrito=False, esquece_ultima=False, indice_global=False, ordena=True
):
    saida = {}
    contador = 0
    for uid, eventos in por_usuario.items():
        if ordena:
            eventos.sort(key=lambda e: e[0])
        indice = contador if indice_global else 0
        inicio = anterior = eventos[0][0]
        n = 0
        paginas: set = set()
        duracao = 0
        for ts, pagina, dur in eventos:
            delta = ts - anterior
            fecha = delta >= gap if estrito else delta > gap
            if fecha:
                saida[f"{uid}|{indice}"] = {
                    "n": n,
                    "inicio": inicio,
                    "fim": anterior,
                    "paginas": len(paginas),
                    "duracao_ms": duracao,
                }
                indice += 1
                inicio = ts
                n = 0
                paginas = set()
                duracao = 0
            anterior = ts
            n += 1
            paginas.add(pagina)
            duracao += dur
        if not esquece_ultima:
            saida[f"{uid}|{indice}"] = {
                "n": n,
                "inicio": inicio,
                "fim": anterior,
                "paginas": len(paginas),
                "duracao_ms": duracao,
            }
        contador = indice + 1
    return saida


def _mut_fronteira_estrita(path):
    """Usa `>=` no lugar de `>`. Erra so nos pares a exatamente GAP de distancia."""
    return _sessionizar(_eventos_por_usuario(path), estrito=True)


def _mut_esquece_ultima_sessao(path):
    """Nao emite a sessao aberta no fim do laco. O classico do laco de janela."""
    return _sessionizar(_eventos_por_usuario(path), esquece_ultima=True)


def _mut_indice_global(path):
    """Numera as sessoes globalmente em vez de por usuario."""
    return _sessionizar(_eventos_por_usuario(path), indice_global=True)


def _mut_gap_em_minutos(path):
    """Confunde a unidade: 30 em vez de 1800."""
    return _sessionizar(_eventos_por_usuario(path), gap=30)


def _mut_fim_exclusivo(path):
    """`fim` recebe o ts do proximo evento em vez do ultimo da sessao."""
    saida = reference(path)
    for v in saida.values():
        v["fim"] = v["fim"] + 1
    return saida


def _mut_n_conta_sessoes(path):
    """`n` vira 1 por sessao em vez da contagem de eventos."""
    saida = reference(path)
    for v in saida.values():
        v["n"] = 1
    return saida


def _mut_ordena_como_texto(path):
    """Ordena o timestamp como string.

    Funciona perfeitamente enquanto todos os `ts` tiverem o mesmo numero de
    digitos — ou seja, em qualquer dataset limpo. So o usuario de magnitudes
    mistas do `gate_adv` separa isto de uma implementacao correta.
    """
    por_usuario: dict[str, list] = {}
    with open(path, encoding="utf-8") as fh:
        for linha in fh:
            r = json.loads(linha)
            por_usuario.setdefault(r["user_id"], []).append(
                (str(r["ts"]), r["page"], r["duration_ms"])
            )
    convertido = {
        u: [(int(t), pg, d) for t, pg, d in sorted(v, key=lambda e: e[0])]
        for u, v in por_usuario.items()
    }
    # `ordena=False`: a ordem textual E a mutacao. Reordenar aqui desfaria o
    # mutante — foi o que aconteceu na primeira versao deste arquivo, e o
    # `--selftest` acusou, o que e exatamente o trabalho dele.
    return _sessionizar(convertido, ordena=False)


def _mut_perde_usuario_de_um_evento(path):
    """Descarta usuarios com um unico evento, tratando-os como ruido."""
    saida = reference(path)
    for chave in [k for k, v in saida.items() if v["n"] == 1]:
        saida.pop(chave)
        break
    return saida


def _mut_paginas_conta_repetidas(path):
    """`paginas` conta visitas em vez de paginas DISTINTAS."""
    saida = reference(path)
    for v in saida.values():
        v["paginas"] = v["n"]
    return saida


def _mut_duracao_nao_reseta(path):
    """A duracao acumula entre sessoes do mesmo usuario: o contador nao zera.

    E o erro classico de laco de janela — a variavel de acumulacao fica fora do
    escopo certo e vaza de uma sessao para a proxima.
    """
    por_usuario = _eventos_por_usuario(path)
    saida = {}
    for uid, eventos in por_usuario.items():
        eventos.sort(key=lambda e: e[0])
        indice = 0
        inicio = anterior = eventos[0][0]
        n = 0
        paginas: set = set()
        duracao = 0
        for ts, pagina, dur in eventos:
            if ts - anterior > GAP:
                saida[f"{uid}|{indice}"] = {
                    "n": n,
                    "inicio": inicio,
                    "fim": anterior,
                    "paginas": len(paginas),
                    "duracao_ms": duracao,
                }
                indice += 1
                inicio = ts
                n = 0
                paginas = set()
            anterior = ts
            n += 1
            paginas.add(pagina)
            duracao += dur
        saida[f"{uid}|{indice}"] = {
            "n": n,
            "inicio": inicio,
            "fim": anterior,
            "paginas": len(paginas),
            "duracao_ms": duracao,
        }
    return saida


MUTANTS = evalkit.MutantSuite(
    reference=reference,
    mutants=[
        ("fronteira_maior_ou_igual", _mut_fronteira_estrita),
        ("esquece_ultima_sessao", _mut_esquece_ultima_sessao),
        ("indice_global", _mut_indice_global),
        ("gap_em_minutos", _mut_gap_em_minutos),
        ("fim_deslocado", _mut_fim_exclusivo),
        ("n_conta_sessoes", _mut_n_conta_sessoes),
        ("ordena_ts_como_texto", _mut_ordena_como_texto),
        ("perde_usuario_de_um_evento", _mut_perde_usuario_de_um_evento),
        ("paginas_conta_repetidas", _mut_paginas_conta_repetidas),
        ("duracao_vaza_entre_sessoes", _mut_duracao_nao_reseta),
    ],
)


# ------------------------------------------------------------------- regimes


def regimes(alias_dir: str | None = None) -> list[evalkit.Regime]:
    saida = []
    for nome, arquivo, descricao in REGIME_FILES:
        caminho = str(data(arquivo))
        if alias_dir is None:
            saida.append(evalkit.Regime(nome, (caminho,), descricao))
        else:
            saida.append(
                evalkit.Regime(
                    nome,
                    (caminho,),
                    descricao,
                    args_factory=lambda c=caminho: (evalkit.unique_alias(c, alias_dir),),
                )
            )
    return saida


def pisos() -> dict[str, float]:
    return {nome: evalkit.read_floor([data(arq)]) for nome, arq, _ in REGIME_FILES}


# ----------------------------------------------------------------------- main


def main() -> int:
    args = evalkit.standard_parser(__doc__.splitlines()[0]).parse_args()

    ok_dados, detalhe = datakit.verify_lock(HERE)
    if not ok_dados:
        if args.selftest:
            print(f"dataset: {detalhe}", file=sys.stderr)
            return 1
        evalkit.emit_failure(f"dataset invalido: {detalhe}")
        return 0

    if args.selftest:
        return 0 if MUTANTS.selftest(GATE) else 1

    if args.budget:
        seed_fn = contracts.as_callable(
            evalkit.load_module(HERE / "seed" / ENTRYPOINT, "seedmod"), SYMBOL
        )
        corrida_seed = evalkit.measure(seed_fn, regimes(), repeats=3, warmup=1)
        corrida_ref = evalkit.measure(reference, regimes(), repeats=3, warmup=1)
        saudavel, mensagem = evalkit.budget_report(
            corrida_seed.wall_s, min(corrida_ref.per_regime.values())
        )
        print(mensagem)
        print(f"  seed:       {corrida_seed.notes()}")
        print(f"  referencia: {corrida_ref.notes()}")
        return 0 if saudavel else 1

    if args.baselines:
        medicao = evalkit.measure(reference, regimes(), repeats=3, warmup=1)
        evalkit.emit_baselines({"referencia_uma_passada": medicao.throughput()})
        return 0

    candidato = evalkit.candidate_path(args.workdir, ENTRYPOINT)
    if not candidato.exists():
        evalkit.emit_failure(f"{ENTRYPOINT} ausente em {args.workdir}")
        return 0

    ok_imports, detalhe = contracts.stdlib_only(str(candidato))
    if not ok_imports:
        evalkit.emit_failure(detalhe)
        return 0

    try:
        modulo = evalkit.load_module(candidato)
        fn = contracts.as_callable(modulo, SYMBOL)
    except Exception as exc:  # noqa: BLE001
        evalkit.emit_failure(f"{type(exc).__name__}: {exc}")
        return 0

    ok_gate, detalhe = GATE.check(fn)
    if not ok_gate:
        evalkit.emit_failure(f"gate: {detalhe}")
        return 0

    violacoes: list[str] = []

    def fresh():
        chamada = contracts.as_callable(evalkit.load_module(candidato, "cand_timed"), SYMBOL)

        def guardada(*a):
            with evalkit.no_disk_writes(violacoes):
                return chamada(*a)

        return guardada

    with tempfile.TemporaryDirectory(prefix="sessionize-alias-") as alias_dir:
        try:
            medicao = evalkit.measure(fn, regimes(alias_dir), repeats=5, warmup=1, fn_factory=fresh)
        except Exception as exc:  # noqa: BLE001
            evalkit.emit_failure(f"falhou durante a medicao: {type(exc).__name__}: {exc}")
            return 0

    if violacoes:
        evalkit.emit_failure(f"o candidato escreveu em disco durante a medicao: {violacoes[0]}")
        return 0

    suspeito, detalhe_fisica = evalkit.implausible_speed(medicao.per_regime, pisos())
    if suspeito:
        evalkit.emit_failure(f"velocidade implausivel: {detalhe_fisica}")
        return 0

    digest = fingerprint(fn(str(data(GATE_FILE))))
    evalkit.emit_success(
        medicao.throughput(), notes=f"gate=ok fingerprint={digest} {medicao.notes()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
