"""Servidor MCP: expõe os dados/indicadores da CVM como tools para um
cliente LLM (Claude Desktop, etc.) via stdio."""

from __future__ import annotations

import datetime
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from . import indicators
from .cvm_client import (
    CompanyNotFoundError,
    StatementNotAvailableError,
    company_statement_with_fallback,
    resolve_company,
    scale_to_millions,
    search_companies,
)
from .models import Company

mcp = FastMCP("cvm-mcp")

ANOS_ANALISE_PADRAO = 5


def _company_dict(company: Company) -> dict:
    return {
        "cnpj": company.cnpj,
        "cd_cvm": company.cd_cvm,
        "denominacao_social": company.denom_social,
        "setor_atividade": company.setor_ativ,
        "situacao_registro": company.situacao_registro,
        "situacao_emissor": company.situacao_emissor,
    }


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
def analisar_empresa(nome_ou_cnpj: str) -> dict:
    """Análise financeira padrão dos últimos 5 anos de uma empresa.

    Use quando o usuário pedir algo genérico como "analise a empresa X" sem
    especificar período ou indicadores. Retorna, em R$ milhões e por ano:
    Receita Líquida, EBIT, EBITDA estimado, Lucro Líquido, Margem Líquida,
    Margem EBITDA, ROE, Liquidez Corrente, Dívida Bruta, Caixa, Dívida
    Líquida e Dívida Líquida/EBITDA — sempre com avisos quando algum item
    não pôde ser calculado a partir dos demonstrativos públicos da CVM (ex:
    EBITDA é sempre uma estimativa, não o número "ajustado" da empresa; não
    há dado de cotação/valor de mercado nesta fonte). Para pedidos
    customizados (outro período, dado bruto, individual vs consolidado),
    use obter_indicadores ou obter_demonstrativo_bruto.
    """
    try:
        empresa = resolve_company(nome_ou_cnpj)
    except CompanyNotFoundError as exc:
        return {"encontrado": False, "aviso": str(exc)}

    ano_atual = datetime.date.today().year
    anos = list(range(ano_atual - ANOS_ANALISE_PADRAO, ano_atual))
    historico = indicators.compute_history(empresa, anos, consolidado=True)

    return {
        "encontrado": True,
        "empresa": _company_dict(empresa),
        "moeda": "BRL",
        "escala": "milhoes",
        "consolidado_preferido": True,
        "historico": [asdict(ano) for ano in historico],
    }


@mcp.tool()
def obter_indicadores(nome_ou_cnpj: str, ano_inicio: int, ano_fim: int, consolidado: bool = True) -> dict:
    """Indicadores financeiros calculados para um intervalo de anos escolhido
    pelo usuário (mesmos indicadores de analisar_empresa, mas com período e
    versão consolidado/individual livres). Use para pedidos customizados que
    fogem do padrão de 5 anos."""
    try:
        empresa = resolve_company(nome_ou_cnpj)
    except CompanyNotFoundError as exc:
        return {"encontrado": False, "aviso": str(exc)}

    if ano_fim < ano_inicio:
        return {"encontrado": False, "aviso": "ano_fim deve ser maior ou igual a ano_inicio."}

    anos = list(range(ano_inicio, ano_fim + 1))
    historico = indicators.compute_history(empresa, anos, consolidado=consolidado)
    return {
        "encontrado": True,
        "empresa": _company_dict(empresa),
        "moeda": "BRL",
        "escala": "milhoes",
        "consolidado_preferido": consolidado,
        "historico": [asdict(ano) for ano in historico],
    }


@mcp.tool()
def obter_demonstrativo_bruto(nome_ou_cnpj: str, ano: int, demonstrativo: str, consolidado: bool = True) -> dict:
    """Devolve as contas contábeis brutas (código, descrição, valor em R$
    milhões) de um demonstrativo publicado pela CVM, sem nenhum cálculo.

    demonstrativo: um de BPA, BPP, DRE, DFC_MD, DFC_MI, DVA, DMPL, DRA.
    Use quando o usuário pedir algo que os indicadores prontos não cobrem,
    como uma conta contábil específica ou maior nível de detalhe.
    """
    try:
        empresa = resolve_company(nome_ou_cnpj)
    except CompanyNotFoundError as exc:
        return {"encontrado": False, "aviso": str(exc)}

    try:
        df, usou_consolidado = company_statement_with_fallback(empresa, ano, demonstrativo.upper(), consolidado)
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
        "contas": contas,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
