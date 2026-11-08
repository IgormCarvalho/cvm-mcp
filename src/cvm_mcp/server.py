"""Servidor MCP: expõe os dados da CVM (Brasil) e da SEC/EDGAR (EUA) como
tools para um cliente LLM (Claude Desktop, etc.) via stdio. As tools da SEC
têm o prefixo `sec_` e devolvem o mesmo formato de resposta das da CVM.

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
from .sec import companies as sec_companies
from .sec import config as sec_config
from .sec import facts as sec_facts
from .sec import http as sec_http
from .sec import mapping as sec_mapping
from .sec import service as sec_service

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


# ---------------------------------------------------------------------------
# SEC / EDGAR (empresas listadas nos EUA)
# ---------------------------------------------------------------------------

_SEC_ERROS = (
    sec_config.UserAgentNotConfiguredError,
    sec_http.SecHttpError,
    sec_companies.SecCompanyNotFoundError,
    sec_facts.SecFactsNotAvailableError,
)


def _sec_empresa(ticker_ou_cik: str) -> sec_companies.SecCompany:
    return sec_companies.resolve_company(ticker_ou_cik)


@mcp.tool()
def sec_buscar_empresa(consulta: str, limite: int = 10) -> dict:
    """Busca empresas registradas na SEC (EUA) por ticker (ex: AAPL), CIK ou
    nome. Use antes das demais tools sec_* para confirmar a empresa certa.

    Cobre emissores americanos (10-K/10-Q) e estrangeiros listados nos EUA
    (20-F/40-F, ex: NU, ITUB). BDRs negociados só na B3 não estão aqui —
    procure pelo ticker da empresa nos EUA.
    """
    try:
        empresas = sec_companies.search_companies(consulta, limite=limite)
    except _SEC_ERROS as exc:
        return {"encontrado": False, "aviso": str(exc)}
    if not empresas:
        return {"encontrado": False, "empresas": [], "aviso": f"Nenhuma empresa encontrada na SEC para '{consulta}'."}
    return {
        "encontrado": True,
        "empresas": [{"cik": e.cik_str, "ticker": e.ticker, "tickers": e.tickers, "nome": e.nome} for e in empresas],
    }


@mcp.tool()
def sec_analisar_empresa(ticker_ou_cik: str) -> dict:
    """Visão trimestral padrão de uma empresa americana: a DRE padronizada
    dos últimos 12 meses, trimestre a trimestre, a partir do XBRL da SEC.

    Valores em milhões da moeda de reporte (normalmente USD); LPA por ação.
    Cada conta informa a tag XBRL usada, o formulário e o número de acesso
    na SEC. O 4T é derivado (10-K − acumulado do 10-Q) e vem marcado com
    derivado=true. Custos e despesas vêm positivos, como no XBRL.
    """
    return sec_obter_demonstrativo_trimestral(ticker_ou_cik, "DRE", TRIMESTRES_PADRAO)


@mcp.tool()
def sec_obter_demonstrativo_trimestral(
    ticker_ou_cik: str, demonstrativo: str, trimestres: int = TRIMESTRES_PADRAO
) -> dict:
    """Demonstrativo padronizado de uma empresa americana ao longo dos
    últimos trimestres publicados na SEC.

    demonstrativo: DRE (resultado), BPA (ativo), BPP (passivo e PL) ou
    DFC (fluxo de caixa). trimestres: quantos períodos (4 = 12 meses).

    BPA/BPP são saldos na data de fechamento. No DFC, o 10-Q costuma trazer
    só o acumulado do ano: o trimestre isolado sai da diferença entre
    acumulados e vem com derivado=true. Contas fora do mapa padrão podem
    ser buscadas com sec_obter_conta_xbrl.
    """
    demonstrativo = demonstrativo.upper()
    if demonstrativo not in sec_mapping.DEMONSTRATIVOS:
        return {"encontrado": False, "aviso": f"Demonstrativo desconhecido: {demonstrativo}. Use um de {list(sec_mapping.DEMONSTRATIVOS)}."}
    if trimestres < 1:
        return {"encontrado": False, "aviso": "trimestres deve ser no mínimo 1."}
    try:
        empresa = _sec_empresa(ticker_ou_cik)
        serie = sec_service.serie_trimestral(empresa, demonstrativo, trimestres)
    except _SEC_ERROS as exc:
        return {"encontrado": False, "aviso": str(exc)}

    if not serie["periodos"]:
        return {
            "encontrado": False,
            "empresa": sec_service.empresa_dict(empresa),
            "aviso": f"Nenhum trimestre com {demonstrativo} estruturado (XBRL) encontrado para esta empresa.",
            "avisos": serie["avisos"],
        }
    return {
        "encontrado": True,
        "fonte": "SEC EDGAR (XBRL companyfacts)",
        "empresa": sec_service.empresa_dict(empresa),
        "demonstrativo": demonstrativo,
        "moeda": serie["moeda"],
        "escala": "milhoes",
        "periodicidade": "trimestral",
        "tipo_conta": "estoque" if demonstrativo in sec_mapping.ESTOQUE else "fluxo",
        "periodos": serie["periodos"],
        "contas_sem_dado": serie["contas_sem_dado"],
        "avisos": serie["avisos"],
    }


@mcp.tool()
def sec_obter_demonstrativo_anual(ticker_ou_cik: str, ano_fiscal: int, demonstrativo: str) -> dict:
    """Demonstrativo padronizado do exercício fiscal ANUAL fechado (10-K,
    20-F ou 40-F) de uma empresa listada nos EUA.

    ano_fiscal é o ano que a própria empresa dá ao exercício (a Apple chama
    de 2025 o ano que fecha em set/2025). demonstrativo: DRE, BPA, BPP ou DFC.
    Única forma de obter dados estruturados de emissores estrangeiros como a
    Nu Holdings, que não publicam trimestres em XBRL.
    """
    demonstrativo = demonstrativo.upper()
    if demonstrativo not in sec_mapping.DEMONSTRATIVOS:
        return {"encontrado": False, "aviso": f"Demonstrativo desconhecido: {demonstrativo}. Use um de {list(sec_mapping.DEMONSTRATIVOS)}."}
    try:
        empresa = _sec_empresa(ticker_ou_cik)
        resultado = sec_service.demonstrativo_anual(empresa, ano_fiscal, demonstrativo)
    except _SEC_ERROS as exc:
        return {"encontrado": False, "aviso": str(exc)}
    return {
        "fonte": "SEC EDGAR (XBRL companyfacts)",
        "empresa": sec_service.empresa_dict(empresa),
        "demonstrativo": demonstrativo,
        "escala": "milhoes",
        "periodicidade": "anual",
        **resultado,
    }


@mcp.tool()
def sec_obter_conta_xbrl(ticker_ou_cik: str, tag: str, taxonomia: str = "us-gaap", limite: int = 20) -> dict:
    """Série bruta de uma tag XBRL qualquer reportada pela empresa (ex:
    tag="LongTermDebt", taxonomia="us-gaap"; ou taxonomia="ifrs-full" para
    emissores IFRS). Use quando a conta não está no demonstrativo
    padronizado. Devolve os períodos mais recentes, com formulário, número de
    acesso e data de entrega; monetários em milhões.
    """
    try:
        empresa = _sec_empresa(ticker_ou_cik)
        resultado = sec_service.conta_xbrl(empresa, tag, taxonomia, max(1, limite))
    except _SEC_ERROS as exc:
        return {"encontrado": False, "aviso": str(exc)}
    return {"empresa": sec_service.empresa_dict(empresa), **resultado}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
