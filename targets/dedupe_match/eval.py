"""f(x) do target dedupe_match — o arbitro. Nunca afrouxe isto para um candidato passar.

ESTE ALVO MEDE QUALIDADE, NAO VELOCIDADE. E o unico da bancada assim, e existe
por um motivo preciso: a tese central do paper (C14) e que "o agente subjacente
permanece o mesmo; apenas as ferramentas e a avaliacao mudam". Um alvo cuja
metrica tem forma diferente — F1 sob orcamento de tempo, e nao throughput — e o
teste dessa tese dentro da propria bancada. Se a arquitetura so funciona quando
`f` mede tempo, ela nao e geral.

O QUE `correct` SIGNIFICA AQUI. Num alvo de velocidade, `correct` quer dizer "a
saida esta certa". Aqui isso seria absurdo: se o gate exigisse acerto, ele seria
a propria metrica e nao sobraria nada para maximizar. Entao `correct` julga o
CONTRATO, nunca o acerto:

  forma          a saida e um iteravel de pares de ids que existem na entrada,
                 sem id inventado, sem par repetido, sem par consigo mesmo
  orcamento      o tempo somado de todas as chamadas cabe no teto
  determinismo   duas chamadas identicas dao o mesmo conjunto, e permutar a
                 ordem dos registros tambem nao muda nada
  pureza         `match` nao le o disco nem escreve nele

Errar muito e legitimo e vale F1 baixo. Violar o contrato vale ZERO.

POR QUE A PUREZA E PARTE DO GATE, E NAO UMA REGRA ESCRITA NA KB. O gabarito
mora em `data/labels_*.json`. Um candidato que abrisse esse arquivo marcaria F1
= 1,0 sem ter resolvido nada, e nenhuma checagem de forma pegaria isso — a saida
estaria perfeita. Deixar a regra so na prosa da KB seria confiar na boa vontade
do otimizador, que e exatamente o que o paper diz para nao fazer. Entao a regra
e executavel: durante toda chamada de `match` as tres portas de arquivo do
CPython (`builtins.open`, `io.open`, `os.open`) sao interceptadas, e qualquer
leitura dentro do diretorio do alvo ou qualquer escrita em disco e registrada e
reprovada. A violacao fica anotada mesmo que o candidato engula a excecao —
`try/except` em volta do `open` nao apaga o registro.

A escrita e proibida pelo mesmo motivo, uma camada acima: um candidato que
gravasse o resultado num cache em disco pagaria o custo uma vez e depois
devolveria o mesmo trabalho de graca, ganhando orcamento entre avaliacoes sem
ter ficado melhor. Isso e a Falha 3b deste laboratorio na versao "qualidade".

O ORCAMENTO E A RESTRICAO VINCULANTE. Ele e cobrado como no game2048 do
upstream: o tempo de todas as chamadas de `match` soma num unico teto, e
estourar vale ZERO, nao "um pouco menos". E ele que cria a tensao real do
problema — comparacao exaustiva O(n^2) contra bloqueio esperto. O seed gasta
mais da metade do teto fazendo a coisa mais burra possivel; qualquer
similaridade mais cara colocada dentro daquele laco estoura o teto muito antes
de melhorar o F1. Nao da para comprar qualidade sem antes comprar tempo.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import random
import signal
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import contracts, datakit, evalkit  # noqa: E402

ENTRYPOINT = "match.py"
SYMBOL = "match"

#: Os tres bancos sao FORMAS de cadastro diferentes, nao repeticoes do mesmo
#: banco. Uma normalizacao afinada para pessoa fisica nao transfere para razao
#: social, e a media geometrica cobra essa diferenca.
BANCOS = (
    ("pessoas", "pessoas fisicas, corrupcao moderada"),
    ("empresas", "razao social: sufixo societario, '&', nome fantasia"),
    ("ruidoso", "pessoas fisicas com o dobro de erro de digitacao"),
)
GATE_FILE = "gate_bank.json"

#: Teto de tempo somado de TODAS as chamadas de match nos bancos pontuados.
#: Calibrado no seed desta maquina (~8,7 s, ou 62% do teto): folga suficiente
#: para uma maquina ~1,6x mais lenta nao reprovar o proprio seed, e apertado o
#: bastante para que qualquer comparador caro dentro do laco O(n^2) estoure.
#: A variavel de ambiente existe para hardware muito diferente; mudar o padrao
#: invalida a comparacao entre versoes do lineage.
ORCAMENTO_S = float(os.environ.get("AVO_DEDUPE_TIME_BUDGET", "14.0"))

#: Teto separado para as quatro passadas do gate no banco pequeno (147
#: registros). Nao sai do orcamento pontuado: sao coisas diferentes, e misturar
#: as duas faria o custo de julgar o contrato competir com o de resolver o
#: problema.
ORCAMENTO_GATE_S = 6.0

#: Folga entre o fim do orcamento e a interrupcao forcada do candidato. Existe
#: porque a cobranca so acontece quando `match` devolve: sem despertador, um
#: candidato O(n^3) rodaria horas antes de ser reprovado por um orcamento que
#: ele ja tinha estourado no primeiro segundo. Medido: o comparador caro dentro
#: do laco exaustivo levava 117s ate ser cobrado; com o despertador ele para em
#: ~15s com a mesma mensagem.
GRACA_DESPERTADOR_S = 1.0

#: Semente da permutacao usada para checar invariancia de ordem. Fixa: a
#: checagem tem que dar o mesmo veredito em toda avaliacao.
SEMENTE_PERMUTACAO = 20260831

#: Modulos da stdlib negados estaticamente ao candidato. Nao e paranoia
#: generica: cada um destes e uma porta de arquivo que NAO passa por
#: `builtins.open` / `io.open` / `os.open`, e portanto contorna a interceptacao
#: de IO. `subprocess.run(["cat", gabarito])` le a resposta sem tocar em nenhuma
#: das tres. Nenhum deles tem uso legitimo numa funcao pura sobre uma lista de
#: dicionarios em memoria, entao negar e barato e nao restringe ninguem honesto.
IMPORTS_NEGADOS = ("subprocess", "multiprocessing", "ctypes", "mmap", "socket")


def data(name: str) -> Path:
    return datakit.data_dir(HERE) / name


def imports_negados(caminho: str) -> tuple[bool, str]:
    """Recusa estaticamente os modulos que dao a volta na interceptacao de IO."""
    import ast

    try:
        arvore = ast.parse(Path(caminho).read_text(encoding="utf-8"), filename=caminho)
    except SyntaxError as exc:
        return False, f"{Path(caminho).name} nao compila: SyntaxError: {exc}"
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(a.name.split(".")[0] for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            nomes.add(no.module.split(".")[0])
    proibidos = sorted(nomes & set(IMPORTS_NEGADOS))
    if proibidos:
        return False, (
            "match() e uma funcao pura sobre os registros recebidos; estes modulos sao "
            "portas de arquivo que contornam essa regra e nao sao permitidos: "
            + ", ".join(proibidos)
        )
    return True, "ok"


# ------------------------------------------------------------------- dados

_CACHE: dict[str, object] = {}


def _ler(nome: str):
    if nome not in _CACHE:
        _CACHE[nome] = json.loads(data(nome).read_text(encoding="utf-8"))
    return _CACHE[nome]


def registros(banco: str) -> list[dict]:
    return _ler(f"records_{banco}.json")


def gabarito(banco: str) -> set[tuple[str, str]]:
    chave = f"gab_{banco}"
    if chave not in _CACHE:
        _CACHE[chave] = {tuple(par) for par in _ler(f"labels_{banco}.json")}
    return _CACHE[chave]


def registros_gate() -> list[dict]:
    return _ler(GATE_FILE)


# ------------------------------------------------------------ orcamento


class Estouro(RuntimeError):
    """O candidato gastou mais tempo do que o teto permite."""


class ContratoViolado(RuntimeError):
    """A saida ou o comportamento do candidato saiu do contrato."""


class Orcamento:
    """Um unico teto compartilhado por todas as chamadas, como no game2048.

    Estourar nao custa "um pouco de score": zera. E o que impede a solucao
    trivial de comprar qualidade gastando tempo sem limite, e o que torna
    bloqueio uma decisao de projeto em vez de um detalhe de implementacao.
    """

    def __init__(self, total: float, rotulo: str = "avaliacao"):
        self.total = total
        self.rotulo = rotulo
        self.usado = 0.0

    def cobrar(self, segundos: float) -> None:
        self.usado += segundos
        if self.usado > self.total:
            raise Estouro(
                f"match() estourou o orcamento de tempo ({self.rotulo}): "
                f"{self.usado:.1f}s usados de {self.total:.1f}s. Estourar vale zero, nao "
                "menos — o custo da comparacao faz parte do problema."
            )


# ----------------------------------------------------------- pureza de IO


@contextlib.contextmanager
def _despertador(segundos: float):
    """Interrompe o candidato quando o tempo restante do orcamento acaba.

    O orcamento so consegue cobrar quando `match` devolve, e `match` e uma
    chamada unica por banco — sem isto, um candidato que estourasse o teto no
    primeiro segundo continuaria rodando ate terminar, e um O(n^3) prenderia o
    avaliador por horas antes de receber o zero que ja era dele.

    Degrada para "sem interrupcao" fora da thread principal ou onde nao houver
    `setitimer`: perder a interrupcao atrasa o veredito, nunca o muda.
    """
    if not hasattr(signal, "setitimer") or threading.current_thread() is not (
        threading.main_thread()
    ):
        yield
        return

    def _acordar(signum, frame):  # noqa: ARG001
        raise Estouro("match() ultrapassou o tempo restante do orcamento")

    anterior = signal.signal(signal.SIGALRM, _acordar)
    signal.setitimer(signal.ITIMER_REAL, max(0.05, segundos))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, anterior)


@contextlib.contextmanager
def _sem_disco(violacoes: list[str]):
    """Intercepta as portas de arquivo do CPython durante a chamada do candidato.

    Duas regras, com motivos diferentes:

      leitura dentro do diretorio do alvo -> o gabarito mora ali. Ler `data/`
          e ler a resposta, e nenhuma checagem de forma pegaria isso porque a
          saida ficaria perfeita.
      escrita em qualquer lugar -> um cache em disco atravessa avaliacoes e
          devolve trabalho ja pago de graca, comprando orcamento sem ter ficado
          melhor.

    Leitura FORA do diretorio do alvo continua livre de proposito: um `import`
    tardio dentro de `match` abre arquivos da stdlib, e reprovar por isso seria
    reprovar candidato honesto. `.pyc` e `__pycache__` sao a excecao simetrica
    do lado da escrita, pelo mesmo motivo.

    A violacao e ANOTADA antes de a excecao subir. Um candidato que embrulhe o
    `open` em `try/except` nao apaga o registro — so deixa de saber que falhou.
    """
    alvo = os.path.realpath(HERE) + os.sep
    orig_builtins, orig_io, orig_os = builtins.open, io.open, os.open

    def _checar(arquivo, escrita: bool) -> None:
        try:
            caminho = os.path.realpath(os.fspath(arquivo))
        except TypeError:  # descritor numerico: nao ha caminho a julgar
            return
        if escrita:
            if caminho.endswith(".pyc") or f"{os.sep}__pycache__{os.sep}" in caminho:
                return
            violacoes.append(f"escreveu em {caminho}")
            raise PermissionError(
                "match() nao pode escrever em disco: cache em disco compra orcamento "
                "sem melhorar a resposta"
            )
        if caminho.startswith(alvo):
            violacoes.append(f"leu {caminho}")
            raise PermissionError(
                "match() nao pode ler arquivos do alvo: o gabarito mora ali e a resposta "
                "tem que sair dos registros recebidos"
            )

    def _envolver(original):
        def porta(arquivo, modo="r", *args, **kwargs):
            _checar(arquivo, any(c in str(modo) for c in "wxa+"))
            return original(arquivo, modo, *args, **kwargs)

        return porta

    def _envolver_os(original):
        escrita_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND

        def porta(caminho, flags, *args, **kwargs):
            _checar(caminho, bool(flags & escrita_flags))
            return original(caminho, flags, *args, **kwargs)

        return porta

    builtins.open = _envolver(orig_builtins)
    io.open = _envolver(orig_io)
    os.open = _envolver_os(orig_os)
    try:
        yield
    finally:
        builtins.open, io.open, os.open = orig_builtins, orig_io, orig_os


# ------------------------------------------------------- execucao e forma


def _normalizar_pares(saida, ids: set[str]) -> set[tuple[str, str]]:
    """Valida a forma da saida e devolve o conjunto canonico de pares.

    A ordem dentro do par nao importa (dedup nao tem direcao), entao o par e
    canonizado. O que importa e que cada elemento seja um id que existe, que os
    dois lados sejam diferentes, e que nenhum par apareca duas vezes — um par
    repetido inflaria o denominador da precisao sem nenhum sentido semantico.
    """
    pares: set[tuple[str, str]] = set()
    for item in saida:
        if isinstance(item, (str, bytes)) or not isinstance(item, (tuple, list)):
            raise ContratoViolado(
                f"esperava um par (id_a, id_b), veio {type(item).__name__}: {item!r:.60}"
            )
        if len(item) != 2:
            raise ContratoViolado(f"par com {len(item)} elementos: {item!r:.60}")
        a, b = item
        if not isinstance(a, str) or not isinstance(b, str):
            raise ContratoViolado(f"os dois lados do par tem que ser ids (str): {item!r:.60}")
        if a == b:
            raise ContratoViolado(f"par com o mesmo id dos dois lados: {a!r}")
        for lado in (a, b):
            if lado not in ids:
                raise ContratoViolado(
                    f"id {lado!r} nao existe entre os registros recebidos — a saida so pode "
                    "conter ids da entrada"
                )
        par = (a, b) if a <= b else (b, a)
        if par in pares:
            raise ContratoViolado(f"par repetido na saida: {par[0]!r}, {par[1]!r}")
        pares.add(par)
    return pares


def _executar(fn, entrada: list[dict], orcamento: Orcamento) -> set[tuple[str, str]]:
    """Uma chamada de match: copia a entrada, cobra o tempo, valida a forma."""
    copia = [dict(reg) for reg in entrada]
    ids = {reg["id"] for reg in copia}
    violacoes: list[str] = []

    restante = orcamento.total - orcamento.usado + GRACA_DESPERTADOR_S
    inicio = time.perf_counter()
    try:
        # Despertador por fora: quando ele dispara, a interceptacao de IO ja foi
        # desfeita antes de o timer ser desarmado.
        with _despertador(restante), _sem_disco(violacoes):
            bruto = fn(copia)
            # Materializar DENTRO da janela cronometrada. Devolver um gerador
            # preguicoso empurraria todo o trabalho para depois da medicao e o
            # orcamento nao cobraria nada.
            saida = list(bruto)
    except BaseException as exc:
        if violacoes:
            raise ContratoViolado(f"match() tocou o disco: {violacoes[0]}") from exc
        raise
    finally:
        orcamento.cobrar(time.perf_counter() - inicio)

    if violacoes:
        raise ContratoViolado(f"match() tocou o disco: {violacoes[0]}")
    return _normalizar_pares(saida, ids)


# ------------------------------------------------------------------- gate


def _permutar(entrada: list[dict]) -> list[dict]:
    return random.Random(SEMENTE_PERMUTACAO).sample(entrada, len(entrada))


def _julgar(fn, recarregar=None) -> tuple[bool, str]:
    """Decide `correct`: contrato, nao acerto.

    `recarregar`, quando presente, produz uma copia recem-importada do modulo
    do candidato para uma quarta passada. So o candidato de verdade recebe isso
    — os mutantes sao funcoes soltas, sem modulo para reimportar. A passada
    extra fecha um buraco especifico: um candidato que memoize a resposta num
    global do modulo passaria na checagem de determinismo devolvendo o cache,
    escondendo a nao-determinacao que so aparece no primeiro calculo.
    """
    entrada = registros_gate()
    orcamento = Orcamento(ORCAMENTO_GATE_S, "banco do gate")
    try:
        primeira = _executar(fn, entrada, orcamento)
        segunda = _executar(fn, entrada, orcamento)
        permutada = _executar(fn, _permutar(entrada), orcamento)
        recarregada = _executar(recarregar(), entrada, orcamento) if recarregar else None
    except (Estouro, ContratoViolado) as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — qualquer erro do candidato reprova
        return False, f"{type(exc).__name__}: {exc}"

    if primeira != segunda:
        return False, (
            f"nao deterministico: duas chamadas com a mesma entrada divergiram em "
            f"{len(primeira ^ segunda)} pares. Se usar aleatoriedade, use semente fixa."
        )
    if primeira != permutada:
        return False, (
            f"depende da ordem dos registros: permutar a entrada mudou "
            f"{len(primeira ^ permutada)} pares. Quem e duplicata de quem nao muda "
            "porque a linha trocou de lugar."
        )
    if recarregada is not None and primeira != recarregada:
        return False, (
            f"instavel entre importacoes: um modulo recem-carregado devolveu "
            f"{len(primeira ^ recarregada)} pares diferentes"
        )
    return True, (
        f"contrato ok ({len(primeira)} pares no banco do gate, "
        f"{orcamento.usado:.2f}s de {ORCAMENTO_GATE_S:.0f}s)"
    )


def judge(fn) -> tuple[bool, str]:
    return _julgar(fn)


GATE = evalkit.Gate(judge=judge, description="forma, orcamento, determinismo e pureza de IO")


# -------------------------------------------------------------- pontuacao


def _f1(previstos: set, verdade: set) -> tuple[float, float, float]:
    """F1, precisao e recall sobre PARES.

    Par e a unidade certa: contar entidades resolvidas premiaria quem junta
    tudo num aglomerado so, e contar registros premiaria quem nao junta nada.
    """
    acertos = len(previstos & verdade)
    if not acertos:
        return 0.0, 0.0, 0.0
    precisao = acertos / len(previstos)
    recall = acertos / len(verdade)
    return 2 * precisao * recall / (precisao + recall), precisao, recall


def pontuar(fn, orcamento: Orcamento) -> tuple[dict[str, float], list[str], str]:
    """Roda os tres bancos e devolve (metricas, detalhes por banco, impressao digital).

    Precisao e recall vao para `notes` de proposito: o F1 diz o quanto o
    candidato errou, mas so a separacao entre os dois diz ONDE. Recall baixo com
    precisao alta e um problema de normalizacao ou de bloqueio; o inverso e
    limiar frouxo ou falta de campo corroborante. Sao consertos opostos, e um
    agente que so ve o F1 chuta qual dos dois tentar.
    """
    metricas: dict[str, float] = {}
    detalhes: list[str] = []
    assinatura: list[tuple[str, str]] = []
    for banco, _ in BANCOS:
        previstos = _executar(fn, registros(banco), orcamento)
        f1, precisao, recall = _f1(previstos, gabarito(banco))
        metricas[f"f1_{banco}"] = round(f1, 6)
        detalhes.append(
            f"{banco}: F1={f1:.3f} P={precisao:.3f} R={recall:.3f} ({len(previstos)} pares)"
        )
        assinatura.extend(sorted(previstos))
    return metricas, detalhes, contracts.canon_hash_rows(assinatura)[:16]


# ------------------------------------------------------- referencia e mutantes


def _normalizar(texto: str) -> str:
    return " ".join(texto.lower().split())


def referencia(records):
    """Igualdade de nome normalizado — a mesma estrategia do seed.

    A referencia da suite de mutantes so precisa RESPEITAR O CONTRATO; ela nao
    precisa ser boa. Num alvo de qualidade essas duas coisas sao independentes,
    e e por isso que uma implementacao fraca serve perfeitamente de referencia.
    """
    grupos: dict[str, list[str]] = {}
    for reg in records:
        chave = _normalizar(reg["nome"])
        if chave:
            grupos.setdefault(chave, []).append(reg["id"])
    pares = []
    for ids in grupos.values():
        ordenados = sorted(ids)
        for i in range(len(ordenados)):
            for j in range(i + 1, len(ordenados)):
                pares.append((ordenados[i], ordenados[j]))
    return pares


def _mut_id_inexistente(records):
    """Inventa um id. O jeito mais barato de "achar" uma duplicata a mais."""
    return list(referencia(records)) + [(records[0]["id"], "ID-QUE-NAO-EXISTE")]


def _mut_id_dos_dois_lados(records):
    """Casa cada registro consigo mesmo: recall perfeito de graca."""
    return list(referencia(records)) + [(records[0]["id"], records[0]["id"])]


def _mut_par_repetido(records):
    """Devolve o mesmo par duas vezes, uma em cada ordem."""
    pares = list(referencia(records))
    a, b = pares[0]
    return pares + [(b, a)]


def _mut_nao_e_par(records):
    """Devolve ids soltos em vez de pares — a confusao de contrato mais comum."""
    return [reg["id"] for reg in records[:5]]


def _mut_nao_deterministico(records):
    """Sorteia sem semente. Roda duas vezes, da dois resultados.

    O sorteio de um par extra em vez de um filtro sobre os existentes e
    deliberado: com poucos pares no banco do gate, um filtro pode devolver o
    mesmo subconjunto duas vezes por acaso e o mutante sobreviveria por sorte.
    Um mutante que so as vezes e rejeitado nao prova nada sobre o gate.
    """
    rnd = random.Random()
    pares = list(referencia(records))
    existentes = {tuple(sorted(par)) for par in pares}
    ids = [reg["id"] for reg in records]
    for _ in range(50):
        a, b = rnd.sample(ids, 2)
        par = (a, b) if a <= b else (b, a)
        if par not in existentes:
            pares.append(par)
            break
    return pares


def _mut_depende_da_ordem(records):
    """So olha para vizinhos na lista. Barato, plausivel, e errado: quem e
    duplicata de quem nao depende da ordem das linhas."""
    pares = set()
    for i, a in enumerate(records):
        for b in records[i + 1 : i + 4]:
            if (
                _normalizar(a["nome"])[:3]
                and _normalizar(a["nome"])[:3] == _normalizar(b["nome"])[:3]
            ):
                x, y = a["id"], b["id"]
                pares.add((x, y) if x <= y else (y, x))
    return sorted(pares)


def _mut_estoura_orcamento(records):
    """Gasta mais tempo do que o teto permite. E o que um comparador caro
    dentro de um laco O(n^2) faz na pratica."""
    time.sleep(ORCAMENTO_GATE_S + 0.5)
    return referencia(records)


def _mut_le_o_gabarito(records):
    """Abre `data/labels_pessoas.json` e devolve a resposta pronta.

    E o ataque que nenhuma checagem de forma pega: a saida fica perfeita. So a
    interceptacao de IO pega, e por isso ela e parte do gate e nao da KB.
    """
    ids = {reg["id"] for reg in records}
    with open(HERE / "data" / "labels_pessoas.json", encoding="utf-8") as fh:
        gab = json.load(fh)
    return [tuple(par) for par in gab if par[0] in ids and par[1] in ids]


def _mut_cache_em_disco(records):
    """Grava o resultado num cache em disco para nao pagar de novo na proxima
    avaliacao. Correto, e mesmo assim compra orcamento sem ter ficado melhor."""
    caminho = Path(os.environ.get("TMPDIR", "/tmp")) / "dedupe_cache.json"
    pares = list(referencia(records))
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump([list(p) for p in pares], fh)
    return pares


MUTANTS = evalkit.MutantSuite(
    reference=referencia,
    mutants=[
        ("id_inexistente", _mut_id_inexistente),
        ("id_dos_dois_lados", _mut_id_dos_dois_lados),
        ("par_repetido", _mut_par_repetido),
        ("nao_e_par", _mut_nao_e_par),
        ("nao_deterministico", _mut_nao_deterministico),
        ("depende_da_ordem", _mut_depende_da_ordem),
        ("estoura_orcamento", _mut_estoura_orcamento),
        ("le_o_gabarito", _mut_le_o_gabarito),
        ("cache_em_disco", _mut_cache_em_disco),
    ],
)


# ------------------------------------------------------------- baselines


def _sem_acento(texto: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def baseline_nome_normalizado(records):
    """Acento fora, caixa unica, pontuacao fora, tokens ordenados. Uma passada.

    E a implementacao que qualquer pessoa escreveria depois de olhar os dados
    por cinco minutos, e por isso e ela — nao o seed — a baseline honesta. O
    enquadramento e o do paper: bater "o que qualquer um escreveria", nao bater
    o ponto de partida deliberadamente ingenuo.
    """
    grupos: dict[str, list[str]] = {}
    for reg in records:
        limpo = "".join(c if c.isalnum() else " " for c in _sem_acento(reg["nome"]).lower())
        chave = " ".join(sorted(limpo.split()))
        if chave:
            grupos.setdefault(chave, []).append(reg["id"])
    pares = []
    for ids in grupos.values():
        ordenados = sorted(ids)
        for i in range(len(ordenados)):
            for j in range(i + 1, len(ordenados)):
                pares.append((ordenados[i], ordenados[j]))
    return pares


BASELINES = {
    "nome_exato": referencia,
    "nome_normalizado": baseline_nome_normalizado,
}


# ----------------------------------------------------------------------- main


def main() -> int:
    args = evalkit.standard_parser(__doc__.splitlines()[0]).parse_args()

    ok_data, detail = datakit.verify_lock(HERE)
    if not ok_data:
        if args.selftest or args.budget:
            print(f"dataset: {detail}", file=sys.stderr)
            return 1
        evalkit.emit_failure(f"dataset invalido: {detail}")
        return 0

    if args.selftest:
        return 0 if MUTANTS.selftest(GATE) else 1

    if args.budget:
        # Mede o SEED, nao a referencia: e o seed que o agente paga no passo 1.
        # `fastest_run_s` fica de fora de proposito — o piso de ruido do labkit
        # protege uma metrica de TEMPO, e aqui a metrica e F1, que e exata: um
        # par acertado e um par acertado, sem variancia de relogio.
        seed_fn = contracts.as_callable(
            evalkit.load_module(HERE / "seed" / ENTRYPOINT, "seedmod"), SYMBOL
        )
        inicio = time.perf_counter()
        ok_gate, detalhe_gate = _julgar(seed_fn)
        orcamento = Orcamento(ORCAMENTO_S)
        metricas, detalhes, _ = pontuar(seed_fn, orcamento)
        parede = time.perf_counter() - inicio

        saudavel, mensagem = evalkit.budget_report(parede, label="avaliacao do seed")
        print(mensagem)
        print(f"  gate:      {detalhe_gate}")
        print(
            f"  orcamento: {orcamento.usado:.1f}s de {ORCAMENTO_S:.1f}s "
            f"({orcamento.usado / ORCAMENTO_S:.0%} gastos pelo seed)"
        )
        for linha in detalhes:
            print(f"  {linha}")
        folga = ORCAMENTO_S / orcamento.usado if orcamento.usado else 0.0
        if not ok_gate:
            print("  ATENCAO: o proprio seed reprovou no gate.")
        if folga < 1.3:
            print(
                f"  ATENCAO: o seed cabe no orcamento com folga de so {folga:.2f}x. "
                "Numa maquina mais lenta ele zera. Aumente ORCAMENTO_S."
            )
        return 0 if (saudavel and ok_gate and folga >= 1.3) else 1

    if args.baselines:
        saida: dict[str, dict[str, float]] = {}
        for nome, fn in BASELINES.items():
            try:
                metricas, _, _ = pontuar(fn, Orcamento(ORCAMENTO_S))
            except (Estouro, ContratoViolado):
                continue
            saida[nome] = metricas
        evalkit.emit_baselines(saida)
        return 0

    candidato = evalkit.candidate_path(args.workdir, ENTRYPOINT)
    if not candidato.exists():
        evalkit.emit_failure(f"{ENTRYPOINT} ausente em {args.workdir}")
        return 0

    for checagem in (contracts.stdlib_only, imports_negados):
        ok_imports, detail = checagem(str(candidato))
        if not ok_imports:
            evalkit.emit_failure(detail)
            return 0

    try:
        fn = contracts.as_callable(evalkit.load_module(candidato), SYMBOL)
    except Exception as exc:  # noqa: BLE001
        evalkit.emit_failure(f"{type(exc).__name__}: {exc}")
        return 0

    def recarregar():
        return contracts.as_callable(evalkit.load_module(candidato, "cand_recarregado"), SYMBOL)

    ok_gate, detalhe = _julgar(fn, recarregar=recarregar)
    if not ok_gate:
        evalkit.emit_failure(f"gate: {detalhe}")
        return 0

    orcamento = Orcamento(ORCAMENTO_S)
    try:
        metricas, detalhes, digital = pontuar(fn, orcamento)
    except (Estouro, ContratoViolado) as exc:
        evalkit.emit_failure(str(exc))
        return 0
    except Exception as exc:  # noqa: BLE001
        evalkit.emit_failure(f"falhou durante a pontuacao: {type(exc).__name__}: {exc}")
        return 0

    evalkit.emit_success(
        metricas,
        notes=(
            f"gate=ok fingerprint={digital} | "
            + " | ".join(detalhes)
            + f" | orcamento {orcamento.usado:.1f}s de {ORCAMENTO_S:.1f}s"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
