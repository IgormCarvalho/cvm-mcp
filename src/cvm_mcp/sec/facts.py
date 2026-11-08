"""Leitura dos "company facts" XBRL da SEC.

O endpoint `companyfacts` devolve, para um CIK, todos os valores que a
empresa já reportou em XBRL, organizados por taxonomia → tag → unidade.
Cada valor ("fact") traz o período (`start`/`end` para fluxo, só `end`
para saldo), o formulário de origem, o número de acesso (`accn`) e a data
de entrega (`filed`).

O mesmo período aparece várias vezes — o 10-K de 2026 repete o ano de 2025
como comparativo, e uma emenda pode corrigir um número. Aqui fica a versão
mais recente de cada (tag, unidade, período), e o fato é marcado como
`reapresentado` quando valores diferentes foram reportados para ele.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

import pandas as pd

from .config import COMPANYFACTS_URL_TEMPLATE, FORMS_ACEITOS, MAX_AGE_COMPANYFACTS_SECONDS
from .http import fetch_json

_MOEDA = re.compile(r"^[A-Z]{3}$")

COLUNAS = ["taxonomia", "tag", "unidade", "inicio", "fim", "valor", "accn", "fy", "fp", "form", "filed"]


class SecFactsNotAvailableError(Exception):
    pass


def baixar_companyfacts(cik: int) -> tuple[dict, bool]:
    """Retorna (json, stale). stale=True quando a SEC estava inacessível e
    foi usada a cópia em cache."""
    resposta = fetch_json(
        COMPANYFACTS_URL_TEMPLATE.format(cik=cik), f"companyfacts_CIK{cik:010d}.json", MAX_AGE_COMPANYFACTS_SECONDS
    )
    return resposta.dados, resposta.stale


def facts_para_dataframe(dados: dict) -> pd.DataFrame:
    """Achata o JSON do companyfacts numa tabela (uma linha por fato
    reportado), já filtrando para os formulários de demonstrações."""
    linhas = []
    for taxonomia, tags in (dados.get("facts") or {}).items():
        for tag, conteudo in tags.items():
            for unidade, fatos in (conteudo.get("units") or {}).items():
                for fato in fatos:
                    if fato.get("form") not in FORMS_ACEITOS:
                        continue
                    linhas.append(
                        (
                            taxonomia,
                            tag,
                            unidade,
                            fato.get("start"),
                            fato["end"],
                            float(fato["val"]),
                            fato.get("accn"),
                            fato.get("fy"),
                            fato.get("fp"),
                            fato.get("form"),
                            fato.get("filed"),
                        )
                    )
    return pd.DataFrame(linhas, columns=COLUNAS)


def consolidar(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (taxonomia, tag, unidade, início, fim): fica a entrega
    mais recente; `reapresentado` indica que houve valores diferentes;
    `fy_original` é o ano fiscal que a empresa deu ao período na PRIMEIRA
    entrega (é o nome que ela mesma usa para o exercício)."""
    if df.empty:
        return df.assign(reapresentado=pd.Series(dtype=bool), fy_original=pd.Series(dtype=float))

    chave = ["taxonomia", "tag", "unidade", "inicio", "fim"]
    df = df.assign(inicio=df["inicio"].fillna(""))
    ordenado = df.sort_values("filed")

    grupos = ordenado.assign(_v=ordenado["valor"].round(2)).groupby(chave, sort=False)
    distintos = grupos["_v"].transform("nunique") > 1
    primeiro_fy = grupos["fy"].transform("first")
    ordenado = ordenado.assign(reapresentado=distintos, fy_original=primeiro_fy)

    ultimo = ordenado.drop_duplicates(subset=chave, keep="last")
    return ultimo.reset_index(drop=True)


def moeda_principal(df: pd.DataFrame) -> str:
    """Moeda em que a empresa reporta (USD para americanas; emissores
    estrangeiros podem usar outra). Decide pela unidade monetária mais
    frequente entre os fatos."""
    contagem = Counter(u for u in df["unidade"] if _MOEDA.match(str(u)))
    return contagem.most_common(1)[0][0] if contagem else "USD"


@lru_cache(maxsize=32)
def _carregar(cik: int) -> tuple[pd.DataFrame, str, str, bool]:
    dados, stale = baixar_companyfacts(cik)
    df = consolidar(facts_para_dataframe(dados))
    if df.empty:
        raise SecFactsNotAvailableError(
            "A empresa não tem demonstrações estruturadas (XBRL) nos formulários 10-K/10-Q/20-F/40-F."
        )
    return df, moeda_principal(df), dados.get("entityName", ""), stale


def carregar_facts(cik: int) -> tuple[pd.DataFrame, str, str, bool]:
    """(fatos consolidados, moeda, nome da entidade, stale). Cacheado em
    memória durante a sessão do servidor; o arquivo em disco tem seu
    próprio controle de validade (ver http.py)."""
    return _carregar(cik)


def limpar_cache_memoria() -> None:
    _carregar.cache_clear()
