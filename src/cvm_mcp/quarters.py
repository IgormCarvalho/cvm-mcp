"""Montagem da visão trimestral a partir dos dados abertos da CVM.

O ITR publica apenas 1T, 2T e 3T — e já traz cada trimestre isolado além dos
acumulados do exercício, então recortar um trimestre é filtrar período, não
subtrair. O 4T não existe no ITR: é derivado como (exercício completo do DFP
− acumulado até o 3T), e é o único cálculo próprio desta camada.

Contas de estoque (BPA/BPP) nunca passam por subtração: o saldo na data de
fechamento já é o valor do trimestre.
"""

from __future__ import annotations

import datetime

import httpx
import pandas as pd

from .config import ITR_FIRST_YEAR
from .cvm_client import (
    StatementNotAvailableError,
    company_statement_with_fallback,
    scale_to_millions,
)
from .models import Company, Quarter

# BPA/BPP são saldos numa data; os demais demonstrativos são movimento de um
# período. A distinção decide se o recorte usa DT_FIM sozinho ou o par
# DT_INI/DT_FIM, e se o 4T pode ser derivado por diferença.
ESTOQUE = frozenset({"BPA", "BPP"})

AVISO_4T_DERIVADO = (
    "O 4º trimestre não é publicado no ITR. Os valores de fluxo aqui foram derivados como "
    "(exercício completo do DFP − acumulado até o 3º trimestre do ITR), não são um número "
    "divulgado diretamente pela empresa."
)
AVISO_VERSAO_INDIVIDUAL = (
    "Demonstrativo consolidado não disponível neste período; usando dados individuais da empresa."
)

_COLUNAS_SAIDA = ["CD_CONTA", "DS_CONTA", "VL_CONTA"]


def _dia_seguinte(data_iso: str) -> str:
    return (datetime.date.fromisoformat(data_iso) + datetime.timedelta(days=1)).isoformat()


def _dia_anterior(data_iso: str) -> str:
    return (datetime.date.fromisoformat(data_iso) - datetime.timedelta(days=1)).isoformat()


def _buscar(
    company: Company, ano: int, statement: str, consolidado: bool, tipo: str
) -> tuple[pd.DataFrame, bool]:
    """Wrapper tolerante: anos sem pacote publicado (ou fora do ar) devolvem
    vazio em vez de estourar, porque a montagem da janela de 12 meses varre
    anos vizinhos especulativamente."""
    try:
        return company_statement_with_fallback(company, ano, statement, consolidado, tipo=tipo)
    except (StatementNotAvailableError, ValueError, OSError, httpx.HTTPError):
        return pd.DataFrame(), consolidado


def _trimestres_itr(company: Company, ano: int, consolidado: bool) -> list[Quarter]:
    """Lê do ITR os trimestres isolados (1T–3T) que a empresa publicou no
    exercício. Usa a DRE como referência por ser o demonstrativo que toda
    companhia entrega."""
    dre, _ = _buscar(company, ano, "DRE", consolidado, "ITR")
    if dre.empty:
        return []

    # Vários períodos terminam na mesma data (o trimestre isolado e os
    # acumulados do exercício). O de DT_INI mais tardio é o mais curto — ou
    # seja, o trimestre isolado.
    isolados = dre.groupby("DT_FIM_EXERC")["DT_INI_EXERC"].max().sort_index()

    return [
        Quarter(ano=ano, numero=i, dt_ini=dt_ini, dt_fim=dt_fim, origem="ITR")
        for i, (dt_fim, dt_ini) in enumerate(isolados.items(), start=1)
    ]


def _anos_dfp_candidatos(ano: int) -> tuple[int, int]:
    """A CVM arquiva o DFP pelo ano da data de referência. Num exercício
    social não-calendário (ex: fecha em fevereiro), o fechamento do exercício
    que começou em `ano` cai no pacote de `ano + 1`."""
    return (ano, ano + 1)


def _trimestre_4(company: Company, ano: int, consolidado: bool, anteriores: list[Quarter]) -> Quarter | None:
    """O 4T só existe se o exercício já fechou (DFP publicado) e se os três
    primeiros trimestres estão no ITR para servir de base da subtração."""
    if len(anteriores) < 3:
        return None

    inicio_exercicio = anteriores[0].dt_ini
    terceiro = anteriores[-1]

    for ano_dfp in _anos_dfp_candidatos(ano):
        dfp, _ = _buscar(company, ano_dfp, "DRE", consolidado, "DFP")
        if dfp.empty:
            continue
        # Casa pelo início do exercício para não confundir com o exercício
        # vizinho, que convive no mesmo pacote quando as datas não são o ano civil.
        mesmo_exercicio = dfp[dfp["DT_INI_EXERC"] == inicio_exercicio]
        if mesmo_exercicio.empty:
            continue
        fim_exercicio = mesmo_exercicio["DT_FIM_EXERC"].max()
        if fim_exercicio > terceiro.dt_fim:
            return Quarter(
                ano=ano,
                numero=4,
                dt_ini=_dia_seguinte(terceiro.dt_fim),
                dt_fim=fim_exercicio,
                origem="DFP-ITR",
            )

    return None


def _dfp_do_exercicio(
    company: Company, quarter: Quarter, statement: str, consolidado: bool
) -> tuple[pd.DataFrame, bool]:
    """Localiza o pacote DFP que contém o fechamento deste trimestre, que pode
    estar no ano seguinte ao do ITR (ver _anos_dfp_candidatos)."""
    for ano_dfp in _anos_dfp_candidatos(quarter.ano):
        df, usou_consolidado = _buscar(company, ano_dfp, statement, consolidado, "DFP")
        if not df.empty and (df["DT_FIM_EXERC"] == quarter.dt_fim).any():
            return df, usou_consolidado
    return pd.DataFrame(), consolidado


def trimestres_do_exercicio(company: Company, ano: int, consolidado: bool = True) -> list[Quarter]:
    """Todos os trimestres disponíveis de um exercício, em ordem cronológica."""
    trimestres = _trimestres_itr(company, ano, consolidado)
    quarto = _trimestre_4(company, ano, consolidado, trimestres)
    return trimestres + ([quarto] if quarto else [])


def ultimos_trimestres(company: Company, n: int = 4, consolidado: bool = True) -> list[Quarter]:
    """Os `n` trimestres mais recentes que a empresa publicou, terminando no
    último divulgado à CVM.

    Anda para trás a partir do ano corrente porque o "último trimestre" é por
    empresa, não global: exercícios sociais não-calendário fecham em meses
    diferentes, e nem toda companhia entrega o ITR na mesma data.
    """
    trimestres: list[Quarter] = []
    ano = datetime.date.today().year

    while len(trimestres) < n and ano >= ITR_FIRST_YEAR:
        trimestres = trimestres_do_exercicio(company, ano, consolidado) + trimestres
        ano -= 1

    return trimestres[-n:]


def _recorte_estoque(df: pd.DataFrame, quarter: Quarter) -> pd.DataFrame:
    return df[df["DT_FIM_EXERC"] == quarter.dt_fim]


def _recorte_fluxo(df: pd.DataFrame, dt_ini: str, dt_fim: str) -> pd.DataFrame:
    return df[(df["DT_INI_EXERC"] == dt_ini) & (df["DT_FIM_EXERC"] == dt_fim)]


def _derivar_quarto_trimestre(
    company: Company, quarter: Quarter, statement: str, consolidado: bool
) -> tuple[pd.DataFrame, bool]:
    """4T de conta de fluxo = exercício completo (DFP) − acumulado até o 3T (ITR),
    casado conta a conta pelo código contábil."""
    anual, usou_consolidado = _dfp_do_exercicio(company, quarter, statement, consolidado)
    acumulado, _ = _buscar(company, quarter.ano, statement, consolidado, "ITR")
    if anual.empty or acumulado.empty:
        return pd.DataFrame(), usou_consolidado

    # Escala antes da subtração: DFP e ITR podem publicar em escalas
    # diferentes (MIL vs UNIDADE), e subtrair valores crus daria lixo.
    anual = scale_to_millions(_recorte_fluxo(anual, anual["DT_INI_EXERC"].min(), quarter.dt_fim))
    fim_terceiro = _dia_anterior(quarter.dt_ini)
    acumulado = acumulado[acumulado["DT_FIM_EXERC"] == fim_terceiro]
    if acumulado.empty or anual.empty:
        return pd.DataFrame(), usou_consolidado
    acumulado = scale_to_millions(_recorte_fluxo(acumulado, acumulado["DT_INI_EXERC"].min(), fim_terceiro))

    juntos = anual.merge(
        acumulado[["CD_CONTA", "VL_CONTA"]], on="CD_CONTA", how="left", suffixes=("", "_acum")
    )
    # Conta que só aparece no exercício completo teve movimento concentrado no
    # 4T — ausência no acumulado vale zero, não dado faltante.
    juntos["VL_CONTA"] = juntos["VL_CONTA"] - juntos["VL_CONTA_acum"].fillna(0)
    return juntos, usou_consolidado


def contas_do_trimestre(
    company: Company, quarter: Quarter, statement: str, consolidado: bool = True
) -> tuple[list[dict], bool, list[str]]:
    """Contas contábeis de um demonstrativo para um trimestre, em R$ milhões.

    Retorna (contas, usou_consolidado, avisos).
    """
    avisos: list[str] = []

    if statement in ESTOQUE:
        # Estoque no 4T vem do DFP (fechamento do exercício); nos demais, do ITR.
        # Saldo nunca é derivado: a data de fechamento já traz o valor.
        if quarter.derivado:
            df, usou_consolidado = _dfp_do_exercicio(company, quarter, statement, consolidado)
        else:
            df, usou_consolidado = _buscar(company, quarter.ano, statement, consolidado, "ITR")
        df = scale_to_millions(_recorte_estoque(df, quarter)) if not df.empty else df
    elif quarter.origem == "ITR":
        df, usou_consolidado = _buscar(company, quarter.ano, statement, consolidado, "ITR")
        df = scale_to_millions(_recorte_fluxo(df, quarter.dt_ini, quarter.dt_fim)) if not df.empty else df
    else:
        df, usou_consolidado = _derivar_quarto_trimestre(company, quarter, statement, consolidado)
        if not df.empty:
            avisos.append(AVISO_4T_DERIVADO)

    if consolidado and not usou_consolidado:
        avisos.append(AVISO_VERSAO_INDIVIDUAL)

    if df.empty:
        return [], usou_consolidado, avisos

    contas = df[_COLUNAS_SAIDA].sort_values("CD_CONTA")
    contas = contas.assign(VL_CONTA=contas["VL_CONTA"].round(3))
    return contas.to_dict(orient="records"), usou_consolidado, avisos
