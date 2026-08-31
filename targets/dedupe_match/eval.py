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
e executavel: um gancho de auditoria (`sys.addaudithook`) fica ligado durante
todo o tempo em que codigo do candidato tem o controle — o IMPORT do modulo
inclusive — e qualquer leitura dentro do diretorio do alvo, qualquer escrita em
disco e qualquer evento que saia do processo sao registrados e reprovados. A
violacao fica anotada mesmo que o candidato engula a excecao.

A versao anterior desta defesa embrulhava `builtins.open`, `io.open` e
`os.open`, e uma auditoria adversarial derrubou-a com quatro candidatos de
poucas linhas, todos com `correct: true` e F1 = 1,0: ler o gabarito no corpo do
modulo (fora da janela guardada), `io.FileIO`, `os.popen` (quem importa
`subprocess` e o `os`, entao a negacao estatica de import nao ve) e cache em
`sqlite3`. O gancho de auditoria nao tem essa fraqueza porque quem o dispara e o
interpretador, no ponto em que o arquivo e de fato aberto.

Uma segunda defesa, estrutural, sustenta a primeira: a avaliacao acontece em
duas fases. Na fase 1 o candidato roda nos tres bancos e so a saida dele e
guardada; o gabarito nao esta em lugar nenhum do processo. Na fase 2, com o
candidato ja fora do ar, o gabarito e lido e o F1 calculado. Isso importa porque
candidato e avaliador dividem o interpretador: com o gabarito residente em
memoria, `match` marcava F1 = 1,0 chamando `gabarito("pessoas")` do proprio
modulo do avaliador, sem tocar em disco nenhum. Nao se tira o alcance do
candidato; tira-se o objeto de dentro do alcance.

RESIDUAL CONHECIDO, escrito aqui porque escondê-lo seria pior. Nada disso e uma
barreira de seguranca: o candidato roda no mesmo interpretador e, se procurar as
celulas de fecho da guarda e zera-las, le o gabarito do disco e marca 1,0. Um
ataque desses foi escrito e funciona. O que as defesas acima garantem e que
todo atalho com FORMA DE OTIMIZACAO falha alto e com mensagem clara, e que
passar disso exige sabotar o arbitro de forma explicita e visivel em qualquer
leitura do diff. Fechar o residual de verdade exige rodar o candidato em outro
processo, que nao tenha o gabarito ao alcance — mudanca de arquitetura do
labkit, nao deste arquivo.

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

#: Declaracao exigida por tests/test_anticheat.py. As defesas contra memoizacao
#: do labkit (`args_factory`, `fn_factory`, `implausible_speed`) protegem uma
#: metrica de TEMPO: elas existem porque o avaliador cronometra a mesma funcao
#: sobre os mesmos dados varias vezes, e a segunda chamada pode devolver cache.
#: Aqui a metrica e F1, e a estrutura da avaliacao e outra — cada banco e
#: pontuado com UMA chamada, entao nao ha segunda chamada para memoizar. Medido:
#: um candidato que indexa a resposta por (tamanho, primeiro id, ultimo id)
#: marca exatamente o mesmo score do honesto que ele embrulha.
#:
#: O que substitui cada camada, porque a ameaca nao some, ela muda de forma:
#:   modulo novo por execucao -> a quarta passada do gate reimporta o candidato,
#:       fechando o caso em que um cache de modulo esconde nao-determinismo
#:   caminho novo por execucao -> nao se aplica: o candidato recebe registros em
#:       memoria e nunca ve um caminho
#:   velocidade implausivel  -> nao se aplica: nao ha piso de leitura a comparar.
#:       O lugar da defesa e a proibicao de escrita em disco, que mata o cache
#:       entre avaliacoes — que era o unico jeito de comprar orcamento de graca
SEM_DEFESA_DE_MEDICAO = (
    "metrica de qualidade (F1), nao de tempo: cada banco e pontuado com uma unica "
    "chamada, entao nao ha medicao repetida para memoizar"
)

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

#: Modulos da stdlib negados estaticamente ao candidato. Depois que a guarda
#: passou a ser um gancho de auditoria, esta lista deixou de ser a defesa e
#: virou cortesia: ela reprova ANTES de rodar, com uma mensagem que nomeia o
#: modulo, em vez de deixar o candidato descobrir no meio da execucao. A defesa
#: que morde e o gancho — inclusive contra o que esta lista nao alcanca, como
#: `os.popen`, que importa `subprocess` por dentro do `os` e nunca aparece no
#: AST do candidato. Nenhum destes tem uso legitimo numa funcao pura sobre uma
#: lista de dicionarios em memoria, entao negar e barato e nao restringe
#: ninguem honesto.
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


def _aquecer_cache() -> None:
    """Le os REGISTROS antes de ligar a guarda de pureza.

    A guarda proibe leitura dentro do diretorio do alvo enquanto estiver ligada,
    e ela vale para o processo inteiro — o avaliador incluido. Ou ele carrega
    antes, ou tropeca na propria regra. Deixar os registros no cache do modulo e
    inofensivo: sao exatamente o que o candidato ja recebe como argumento.

    O gabarito NAO e aquecido, e essa ausencia e a defesa: ele so e lido na fase
    2, depois que o candidato ja devolveu tudo. Ver `coletar`.
    """
    registros_gate()
    for banco, _ in BANCOS:
        registros(banco)


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


#: Eventos de auditoria que sao porta de saida do processo ou porta de arquivo
#: em C, e que por isso nunca apareceriam num `open` do lado Python. Bloquear
#: pelo evento, e nao pelo nome do modulo, e o que fecha a familia inteira:
#: `os.popen` importa `subprocess` por dentro, `sqlite3.connect` abre o arquivo
#: no C, e nenhum dos dois passa por `builtins.open`.
EVENTOS_NEGADOS = (
    "os.system",
    "os.exec",
    "os.spawn",
    "os.posix_spawn",
    "os.fork",
    "os.forkpty",
    "os.startfile",
    "sqlite3.connect",
    "ctypes.dlopen",
    "ctypes.dlsym",
    "ctypes.call_function",
    "socket.__new__",
    "socket.connect",
    "mmap.__new__",
    "shutil.copyfile",
)

#: Violacoes anotadas durante a sessao guardada. Cada chamada marca a posicao
#: antes de comecar e olha so o que apareceu depois; o que sobra no fim sao as
#: violacoes que aconteceram FORA de uma chamada — import do modulo, ou thread
#: que o candidato deixou rodando para ler o gabarito depois de devolver.
_VIOLACOES: list[str] = []


def _montar_guarda():
    """Constroi a guarda de pureza e devolve so o gerenciador de contexto.

    A chave que liga e desliga a guarda vive numa CELULA DE FECHO, e nao numa
    global do modulo. Nao e obscuridade por esporte: o candidato roda no mesmo
    interpretador que o avaliador e alcanca `sys.modules["__main__"]`, entao uma
    global chamada `_PROFUNDIDADE` seria um interruptor com etiqueta — uma linha
    (`ev._PROFUNDIDADE = 0`) e a guarda inteira vira no-op, e foi assim que um
    ataque escrito nesta auditoria passou. Numa celula o mesmo ataque continua
    possivel por `_sem_disco.__wrapped__.__closure__`, e isso esta escrito aqui
    porque fingir o contrario seria pior: dentro de um processo so, nao existe
    barreira, existe custo. O que muda e que ler o gabarito deixa de ser um
    atalho de uma linha e vira sabotagem explicita do arbitro, do tipo que salta
    aos olhos em qualquer leitura do diff. Isolamento de verdade exigiria rodar
    o candidato em outro processo, sem o gabarito ao alcance.
    """
    chave = [0]
    instalado = [False]

    def auditor(evento: str, args) -> None:
        """Gancho de auditoria: a unica forma de ver TODA porta de arquivo.

        A versao anterior desta defesa embrulhava `builtins.open`, `io.open` e
        `os.open`. Tres candidatos triviais davam a volta nela e marcavam
        F1 = 1,0 com `correct: true`:

          `io.FileIO(caminho).readall()`  abre o arquivo sem passar por `open`
          `os.popen("cat " + caminho)`    quem importa `subprocess` e o `os`, em
                                          tempo de execucao: o AST nao ve
          `sqlite3.connect(...)`          escreve em disco pelo C

        O gancho e imune a classe inteira porque quem o dispara e o
        interpretador, no ponto em que o arquivo e de fato aberto, qualquer que
        seja o caminho de codigo que levou ate la. E ele nao pode ser
        desinstalado depois de instalado.
        """
        if chave[0] <= 0:
            return
        if evento == "open":
            arquivo, modo, flags = args
            try:
                caminho = os.path.realpath(os.fspath(arquivo))
            except TypeError:  # descritor numerico: nao ha caminho a julgar
                return
            escrita = bool(modo and any(c in str(modo) for c in "wxa+")) or bool(
                isinstance(flags, int)
                and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND)
            )
            if escrita:
                if caminho.endswith(".pyc") or f"{os.sep}__pycache__{os.sep}" in caminho:
                    return
                _VIOLACOES.append(f"escreveu em {caminho}")
                raise PermissionError(
                    "match() nao pode escrever em disco: cache em disco compra orcamento "
                    "sem melhorar a resposta"
                )
            if caminho.startswith(os.path.realpath(HERE) + os.sep):
                _VIOLACOES.append(f"leu {caminho}")
                raise PermissionError(
                    "match() nao pode ler arquivos do alvo: o gabarito mora ali e a "
                    "resposta tem que sair dos registros recebidos"
                )
            return
        if evento in EVENTOS_NEGADOS or evento.startswith("subprocess."):
            _VIOLACOES.append(f"usou {evento}, que sai do processo ou abre arquivo fora do Python")
            raise PermissionError(
                f"match() e uma funcao pura sobre os registros recebidos; {evento} nao e permitido"
            )

    @contextlib.contextmanager
    def sem_disco():
        """Liga a guarda de pureza enquanto codigo do candidato estiver rodando.

        Duas regras, com motivos diferentes:

          leitura dentro do diretorio do alvo -> o gabarito mora ali. Ler `data/`
              e ler a resposta, e nenhuma checagem de forma pegaria isso porque
              a saida ficaria perfeita.
          escrita em qualquer lugar -> um cache em disco atravessa avaliacoes e
              devolve trabalho ja pago de graca, comprando orcamento sem ter
              ficado melhor.

        Leitura FORA do diretorio do alvo continua livre de proposito: um
        `import` tardio dentro de `match` abre arquivos da stdlib, e reprovar
        por isso seria reprovar candidato honesto. `.pyc` e `__pycache__` sao a
        excecao simetrica do lado da escrita, pelo mesmo motivo.

        A guarda cobre o IMPORT do modulo do candidato, e nao so a chamada de
        `match`. Cobrir so a chamada deixava passar o ataque mais barato de
        todos: ler o gabarito no corpo do modulo, guardar num global e devolver
        a resposta pronta de dentro de uma `match` que nunca toca no disco.

        A violacao e ANOTADA antes de a excecao subir. Um candidato que embrulhe
        a leitura em `try/except` nao apaga o registro — so deixa de saber que
        falhou.
        """
        if not instalado[0]:
            sys.addaudithook(auditor)
            instalado[0] = True
        chave[0] += 1
        try:
            yield
        finally:
            chave[0] -= 1

    return sem_disco


_sem_disco = _montar_guarda()


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
    marca = len(_VIOLACOES)

    restante = orcamento.total - orcamento.usado + GRACA_DESPERTADOR_S
    inicio = time.perf_counter()
    try:
        # Despertador por fora: quando ele dispara, a guarda de pureza ja foi
        # desligada antes de o timer ser desarmado.
        with _despertador(restante), _sem_disco():
            bruto = fn(copia)
            # Materializar DENTRO da janela cronometrada. Devolver um gerador
            # preguicoso empurraria todo o trabalho para depois da medicao e o
            # orcamento nao cobraria nada.
            saida = list(bruto)
    except BaseException as exc:
        if len(_VIOLACOES) > marca:
            raise ContratoViolado(f"match() tocou o disco: {_VIOLACOES[marca]}") from exc
        raise
    finally:
        orcamento.cobrar(time.perf_counter() - inicio)

    if len(_VIOLACOES) > marca:
        raise ContratoViolado(f"match() tocou o disco: {_VIOLACOES[marca]}")
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


def coletar(fn, orcamento: Orcamento) -> dict[str, set[tuple[str, str]]]:
    """FASE 1: roda o candidato nos tres bancos e guarda so o que ele devolveu.

    Separada de `pontuar` de proposito, e a separacao e uma defesa e nao uma
    arrumacao: enquanto o codigo do candidato tem o controle, o gabarito nao
    esta em lugar nenhum do processo — nem no cache do modulo, nem numa variavel
    local de quem chamou. O candidato roda no mesmo interpretador que o
    avaliador e alcanca `sys.modules`, os frames e o coletor de lixo; a unica
    forma de nao entregar a resposta a esse alcance e a resposta ainda nao ter
    sido lida. O disco, que e por onde ela teria que vir, e o que a guarda de
    pureza cobre.
    """
    return {banco: _executar(fn, registros(banco), orcamento) for banco, _ in BANCOS}


def medir(previstos_por_banco, gabaritos) -> tuple[dict[str, float], list[str], str]:
    """FASE 2: compara com o gabarito, ja com o candidato fora do ar.

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
        previstos = previstos_por_banco[banco]
        f1, precisao, recall = _f1(previstos, gabaritos[banco])
        metricas[f"f1_{banco}"] = round(f1, 6)
        detalhes.append(
            f"{banco}: F1={f1:.3f} P={precisao:.3f} R={recall:.3f} ({len(previstos)} pares)"
        )
        assinatura.extend(sorted(previstos))
    return metricas, detalhes, contracts.canon_hash_rows(assinatura)[:16]


def pontuar(fn, orcamento: Orcamento) -> tuple[dict[str, float], list[str], str]:
    """As duas fases em sequencia. Para `--budget` e `--baselines`, que rodam
    codigo do proprio laboratorio e nao precisam da separacao."""
    previstos = coletar(fn, orcamento)
    return medir(previstos, {banco: gabarito(banco) for banco, _ in BANCOS})


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


def _mut_le_o_gabarito_por_fileio(records):
    """Le o gabarito por `io.FileIO`, que abre o arquivo sem passar por `open`.

    Este mutante existe porque a versao anterior da guarda embrulhava
    `builtins.open`, `io.open` e `os.open` — e `io.FileIO` nao e nenhum dos
    tres. Um candidato de sete linhas marcava F1 = 1,0 com `correct: true`.
    """
    ids = {reg["id"] for reg in records}
    fh = io.FileIO(str(HERE / "data" / "labels_pessoas.json"), "r")
    try:
        gab = json.loads(fh.readall().decode("utf-8"))
    finally:
        fh.close()
    return [tuple(par) for par in gab if par[0] in ids and par[1] in ids]


def _mut_le_o_gabarito_por_subprocesso(records):
    """`os.popen` le o gabarito de fora do processo.

    A negacao estatica de `subprocess` nao ve isto: quem importa `subprocess` e
    o proprio `os`, em tempo de execucao, e o AST do candidato so tem `os`.
    """
    ids = {reg["id"] for reg in records}
    with os.popen("cat " + str(HERE / "data" / "labels_pessoas.json")) as fh:
        gab = json.loads(fh.read())
    return [tuple(par) for par in gab if par[0] in ids and par[1] in ids]


def _mut_cache_em_sqlite(records):
    """Cache em disco por `sqlite3`, que escreve o arquivo pelo C.

    Mesma ameaca do `cache_em_disco` — comprar orcamento entre avaliacoes —
    por uma porta que nenhum embrulho de `open` alcanca.
    """
    import sqlite3

    caminho = Path(os.environ.get("TMPDIR", "/tmp")) / "dedupe_cache.db"
    con = sqlite3.connect(caminho)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")
        con.commit()
    finally:
        con.close()
    return referencia(records)


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
        ("le_o_gabarito_por_fileio", _mut_le_o_gabarito_por_fileio),
        ("le_o_gabarito_por_subprocesso", _mut_le_o_gabarito_por_subprocesso),
        ("cache_em_disco", _mut_cache_em_disco),
        ("cache_em_sqlite", _mut_cache_em_sqlite),
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

    # Todo o resto acontece com a guarda de pureza LIGADA — inclusive o import
    # do modulo. Ligar so em volta da chamada de `match` deixava passar o ataque
    # mais barato de todos: ler `data/labels_*.json` no corpo do modulo, guardar
    # num global e devolver a resposta pronta de dentro de uma `match` que nunca
    # toca no disco. Por isso os dados do avaliador sao carregados ANTES: com a
    # guarda ligada, o proprio avaliador nao pode mais abrir `data/`.
    _aquecer_cache()
    with _sem_disco():
        try:
            fn = contracts.as_callable(evalkit.load_module(candidato), SYMBOL)
        except Exception as exc:  # noqa: BLE001
            if _VIOLACOES:
                evalkit.emit_failure(
                    f"o modulo do candidato tocou o disco durante o import: {_VIOLACOES[0]}"
                )
            else:
                evalkit.emit_failure(f"{type(exc).__name__}: {exc}")
            return 0
        if _VIOLACOES:
            evalkit.emit_failure(
                f"o modulo do candidato tocou o disco durante o import: {_VIOLACOES[0]}"
            )
            return 0

        def recarregar():
            return contracts.as_callable(evalkit.load_module(candidato, "cand_recarregado"), SYMBOL)

        ok_gate, detalhe = _julgar(fn, recarregar=recarregar)
        if not ok_gate:
            evalkit.emit_failure(f"gate: {detalhe}")
            return 0

        orcamento = Orcamento(ORCAMENTO_S)
        try:
            previstos = coletar(fn, orcamento)
        except (Estouro, ContratoViolado) as exc:
            evalkit.emit_failure(str(exc))
            return 0
        except Exception as exc:  # noqa: BLE001
            evalkit.emit_failure(f"falhou durante a pontuacao: {type(exc).__name__}: {exc}")
            return 0

    # Violacao que sobrou fora de uma chamada: import do modulo ou thread que o
    # candidato deixou rodando para ler o gabarito depois que a chamada devolveu.
    if _VIOLACOES:
        evalkit.emit_failure(f"match() tocou o disco: {_VIOLACOES[0]}")
        return 0

    # Fase 2: so agora o gabarito entra no processo, com o candidato fora do ar.
    metricas, detalhes, digital = medir(previstos, {b: gabarito(b) for b, _ in BANCOS})

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
