"""Servidor MCP: expõe os dados da CVM como tools para um cliente LLM
(Claude Desktop, etc.) via stdio.

A visão padrão é trimestral: as tools partem do último trimestre publicado
pela empresa e devolvem os 12 meses anteriores, trimestre a trimestre, com
as contas contábeis como a CVM publica — sem indicadores calculados.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import quarters
from .config import TRIMESTRES_PADRAO
from .cvm_client import (
    STATEMENTS,
    CompanyNotFoundError,
    StatementNotAvailableError,
    company_statement_with_fallback,
    resolve_company,
    scale_to_millions,
    search_companies,
)
from .models import Company

mcp = FastMCP("cvm-mcp")


def _company_dict(company: Company) -> dict:
    return {
        "cnpj": company.cnpj,
        "cd_cvm": company.cd_cvm,
        "denominacao_social": company.denom_social,
        "setor_atividade": company.setor_ativ,
        "situacao_registro": company.situacao_registro,
        "situacao_emissor": company.situacao_emissor,
    }


def _serie_trimestral(
    company: Company, demonstrativo: str, n: int, consolidado: bool
) -> tuple[list[dict], list[str]]:
    """Monta a série de trimestres de um demonstrativo, agregando os avisos
    sem repetir o mesmo texto em cada período."""
    trimestres = quarters.ultimos_trimestres(company, n=n, consolidado=consolidado)
    periodos: list[dict] = []
    avisos: list[str] = []

    for trimestre in trimestres:
        contas, usou_consolidado, avisos_periodo = quarters.contas_do_trimestre(
            company, trimestre, demonstrativo, consolidado
        )
        for aviso in avisos_periodo:
            if aviso not in avisos:
                avisos.append(aviso)
        periodos.append(
            {
                "trimestre": trimestre.rotulo,
                "inicio": trimestre.dt_ini,
                "fim": trimestre.dt_fim,
                "consolidado": usou_consolidado,
                "derivado": trimestre.derivado,
                "contas": contas,
            }
        )

    return periodos, avisos


@mcp.tool()
def buscar_empresa(consulta: str, limite: int = 10) -> dict:
    """Busca companhias abertas no cadastro da CVM por nome, CNPJ ou código CVM.

    Use esta tool antes de qualquer outra para confirmar a empresa certa:
    existem nomes parecidos e empresas com registro cancelado/suspenso que
    podem não ter demonstrativos recentes.
    """
    empresas = search_companies(consulta, limit=limite)
    if not empresas:
        return {"encontrado": False, "empresas": [], "aviso": f"Nenhuma empresa encontrada para '{consulta}'."}
    return {"encontrado": True, "empresas": [_company_dict(c) for c in empresas]}


@mcp.tool()
def analisar_empresa(nome_ou_cnpj: str, consolidado: bool = True) -> dict:
    """Visão trimestral padrão de uma empresa: a DRE dos últimos 12 meses,
    trimestre a trimestre, terminando no último trimestre que a companhia
    publicou na CVM.

    Use quando o usuário pedir algo genérico como "analise a empresa X". Os
    valores são contas contábeis publicadas, em R$ milhões, sem indicadores
    calculados — cada trimestre vem isolado (não acumulado), então dá para
    comparar períodos diretamente.

    Atenção ao campo `derivado`: o 4º trimestre não é publicado no ITR e é
    obtido por diferença contra o exercício completo do DFP. Para o balanço
    (BPA/BPP) ou outros demonstrativos, use obter_demonstrativo_trimestral.
    """
    try:
        empresa = resolve_company(nome_ou_cnpj)
    except CompanyNotFoundError as exc:
        return {"encontrado": False, "aviso": str(exc)}

    periodos, avisos = _serie_trimestral(empresa, "DRE", TRIMESTRES_PADRAO, consolidado)
    if not periodos:
        return {
            "encontrado": False,
            "empresa": _company_dict(empresa),
            "aviso": "Nenhum trimestre publicado encontrado para esta empresa na CVM.",
        }

    return {
        "encontrado": True,
        "empresa": _company_dict(empresa),
        "demonstrativo": "DRE",
        "moeda": "BRL",
        "escala": "milhoes",
        "periodicidade": "trimestral",
        "periodos": periodos,
        "avisos": avisos,
    }


@mcp.tool()
def obter_demonstrativo_trimestral(
    nome_ou_cnpj: str,
    demonstrativo: str,
    trimestres: int = TRIMESTRES_PADRAO,
    consolidado: bool = True,
) -> dict:
    """Contas de um demonstrativo específico ao longo dos últimos trimestres
    publicados, terminando no mais recente disponível na CVM.

    demonstrativo: um de BPA, BPP, DRE, DFC_MD, DFC_MI, DVA, DMPL, DRA.
    trimestres: quantos períodos retroceder (4 = últimos 12 meses).

    BPA e BPP são saldos na data de fechamento de cada trimestre; os demais
    são o movimento do trimestre isolado. Use para o balanço patrimonial, o
    fluxo de caixa, ou para ir além dos 12 meses padrão.
    """
    try:
        empresa = resolve_company(nome_ou_cnpj)
    except CompanyNotFoundError as exc:
        return {"encontrado": False, "aviso": str(exc)}

    demonstrativo = demonstrativo.upper()
    if demonstrativo not in STATEMENTS:
        return {"encontrado": False, "aviso": f"Demonstrativo desconhecido: {demonstrativo}. Use um de {list(STATEMENTS)}."}
    if trimestres < 1:
        return {"encontrado": False, "aviso": "trimestres deve ser no mínimo 1."}

    periodos, avisos = _serie_trimestral(empresa, demonstrativo, trimestres, consolidado)
    if not periodos:
        return {
            "encontrado": False,
            "empresa": _company_dict(empresa),
            "aviso": f"Nenhum trimestre com {demonstrativo} encontrado para esta empresa.",
        }

    return {
        "encontrado": True,
        "empresa": _company_dict(empresa),
        "demonstrativo": demonstrativo,
        "moeda": "BRL",
        "escala": "milhoes",
        "periodicidade": "trimestral",
        "tipo_conta": "estoque" if demonstrativo in quarters.ESTOQUE else "fluxo",
        "periodos": periodos,
        "avisos": avisos,
    }


@mcp.tool()
def obter_demonstrativo_anual(
    nome_ou_cnpj: str, ano: int, demonstrativo: str, consolidado: bool = True
) -> dict:
    """Contas de um demonstrativo do exercício ANUAL fechado (DFP), sem
    recorte trimestral.

    Use só quando o usuário pedir explicitamente o ano fechado — a visão
    padrão deste servidor é trimestral (analisar_empresa,
    obter_demonstrativo_trimestral).
    """
    try:
        empresa = resolve_company(nome_ou_cnpj)
    except CompanyNotFoundError as exc:
        return {"encontrado": False, "aviso": str(exc)}

    try:
        df, usou_consolidado = company_statement_with_fallback(
            empresa, ano, demonstrativo.upper(), consolidado, tipo="DFP"
        )
    except (StatementNotAvailableError, ValueError) as exc:
        return {"encontrado": False, "aviso": str(exc)}

    if df.empty:
        return {"encontrado": False, "aviso": f"Sem dados de {demonstrativo} para {empresa.denom_social} em {ano}."}

    df = scale_to_millions(df)
    contas = df[["CD_CONTA", "DS_CONTA", "VL_CONTA"]].sort_values("CD_CONTA").to_dict(orient="records")
    return {
        "encontrado": True,
        "empresa": _company_dict(empresa),
        "ano": ano,
        "demonstrativo": demonstrativo.upper(),
        "consolidado": usou_consolidado,
        "moeda": "BRL",
        "escala": "milhoes",
        "periodicidade": "anual",
        "contas": contas,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
