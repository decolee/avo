"""Canonicalização e comparação — a parte do gate que decide `correct`.

Duas regras que valem para todo target do laboratório:

1. **Compare antes de arredondar.** O hash final é sobre a *apresentação*
   (2 casas). Se o gate só olhar para o hash, um candidato que arredonda a cada
   acumulação passa despercebido enquanto o erro couber dentro do arredondamento
   — foi exatamente a Falha 1. Por isso `compare_mappings` compara os valores
   crus com tolerância explícita **e** o hash.

2. **Ordem de inserção não importa; valores importam.** A canonicalização ordena
   as chaves antes de alimentar o SHA256, então um candidato é livre para
   escolher a ordem de saída.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any


class CanonError(ValueError):
    """A saída do candidato não tem a forma exigida pelo contrato."""


def _fmt(value: Any, places: int) -> str:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise CanonError(f"valor não finito na saída: {value!r}")
        # normaliza -0.0 -> 0.0 para o hash não depender do sinal do zero
        value = value + 0.0
        return f"{value:.{places}f}"
    return str(value)


def canon_hash(
    mapping: Mapping[str, Mapping[str, Any]],
    fields: Sequence[str],
    places: Mapping[str, int] | None = None,
) -> str:
    """SHA256 sobre os itens ordenados, com casas decimais fixas por campo.

    `places` diz quantas casas cada campo float usa na apresentação; campos
    ausentes de `places` são serializados com `str()`.
    """
    places = places or {}
    digest = hashlib.sha256()
    for key in sorted(mapping):
        row = mapping[key]
        try:
            parts = [_fmt(row[f], places.get(f, 0)) for f in fields]
        except KeyError as exc:
            raise CanonError(f"chave {key!r}: campo {exc.args[0]!r} ausente") from None
        except TypeError as exc:
            raise CanonError(f"chave {key!r}: {exc}") from None
        digest.update((str(key) + "|" + "|".join(parts) + "\n").encode("utf-8"))
    return digest.hexdigest()


def canon_hash_rows(rows: Iterable[Sequence[Any]], places: int = 6) -> str:
    """SHA256 sobre linhas já ordenadas (result set de SQL, por exemplo).

    A ordem das linhas **importa** aqui: um result set com ORDER BY declarado é
    parte do contrato. Use para targets cuja saída é tabular.
    """
    digest = hashlib.sha256()
    for row in rows:
        digest.update(("|".join(_fmt(c, places) for c in row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def compare_mappings(
    expected: Mapping[str, Mapping[str, Any]],
    got: Any,
    exact_fields: Sequence[str] = (),
    float_fields: Sequence[str] = (),
    tol: float | Callable[[str, str, Mapping[str, Any]], float] = 1e-9,
    max_report: int = 1,
) -> tuple[bool, str]:
    """Compara a saída do candidato contra a referência, com erro diagnóstico.

    Devolve `(ok, detalhe)`. O detalhe é o que o agente lê numa rejeição, então
    ele nomeia a chave, o campo, o esperado e o obtido — nunca só "divergiu".

    `tol` pode ser um número ou uma função `(chave, campo, linha_esperada) ->
    float`. A forma de função existe porque tolerância constante é errada quando
    as magnitudes variam: um grupo somando ~1e10 acumula erro de ponto flutuante
    ordens de grandeza maior que um somando ~1e3, e uma tolerância que sirva
    para o primeiro deixa passar erro real no segundo. O target calcula a folga
    a partir da magnitude do grupo — assim o gate julga a lógica do candidato,
    não a ordem em que ele somou.
    """
    if not isinstance(got, dict):
        return False, f"esperado dict, obtido {type(got).__name__}"

    if set(got) != set(expected):
        missing = sorted(set(expected) - set(got))
        extra = sorted(set(got) - set(expected))
        detail = f"chaves divergentes (faltam {len(missing)}, sobram {len(extra)})"
        if missing:
            detail += f"; primeira faltando: {missing[0]!r}"
        if extra:
            detail += f"; primeira sobrando: {extra[0]!r}"
        return False, detail

    problems: list[str] = []
    for key in sorted(expected):
        exp_row, got_row = expected[key], got[key]
        if not isinstance(got_row, dict):
            problems.append(f"{key}: esperado dict, obtido {type(got_row).__name__}")
            continue
        for field in exact_fields:
            if field not in got_row:
                problems.append(f"{key}.{field}: ausente")
            elif got_row[field] != exp_row[field]:
                problems.append(
                    f"{key}.{field}: esperado {exp_row[field]!r}, obtido {got_row[field]!r}"
                )
        for field in float_fields:
            if field not in got_row:
                problems.append(f"{key}.{field}: ausente")
                continue
            try:
                delta = abs(float(got_row[field]) - float(exp_row[field]))
            except (TypeError, ValueError):
                problems.append(f"{key}.{field}: não numérico ({got_row[field]!r})")
                continue
            limit = tol(key, field, exp_row) if callable(tol) else tol
            if not math.isfinite(delta) or delta > limit:
                problems.append(
                    f"{key}.{field}: esperado {exp_row[field]!r}, obtido {got_row[field]!r} "
                    f"(erro {delta:.3g} > tol {limit:.3g})"
                )
        if len(problems) >= max_report:
            break

    if problems:
        return False, "; ".join(problems[:max_report])
    return True, "ok"


def compare_hash(expected_hash: str, got_hash: str, label: str = "hash") -> tuple[bool, str]:
    if expected_hash != got_hash:
        return False, f"{label} divergente ({got_hash[:12]} != {expected_hash[:12]})"
    return True, "ok"


def stdlib_only(module_path: str, allowed_extra: Iterable[str] = ()) -> tuple[bool, str]:
    """Checa estaticamente que um candidato importa só a stdlib.

    O contrato "somente stdlib" estava escrito na prosa do goal e não era
    verificado por nada. Isto o torna executável: qualquer import de terceiro
    fora de `allowed_extra` é uma violação relatada com o nome do módulo.

    A mensagem devolvida é uma frase **completa**, pronta para ir ao agente sem
    prefixo. Dois motivos distintos reprovam aqui — o arquivo não compila, ou
    ele importa algo de fora da stdlib — e apresentar o primeiro embrulhado numa
    frase sobre stdlib manda o agente investigar a coisa errada.
    """
    import ast
    import sys

    allowed = set(allowed_extra)
    name = os.path.basename(module_path)
    try:
        with open(module_path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=module_path)
    except SyntaxError as exc:
        return False, f"{name} não compila: SyntaxError: {exc}"

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])

    std = set(sys.stdlib_module_names)
    offenders = sorted(n for n in names if n not in std and n not in allowed)
    if offenders:
        return False, "somente a stdlib é permitida; import de fora dela: " + ", ".join(offenders)
    return True, "ok"


def as_callable(module: Any, symbol: str) -> Callable[..., Any]:
    fn = getattr(module, symbol, None)
    if fn is None:
        raise AttributeError(f"{symbol}(...) não definido")
    if not callable(fn):
        raise AttributeError(f"{symbol} não é chamável")
    return fn
