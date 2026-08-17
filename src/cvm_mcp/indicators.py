"""Cálculo dos indicadores financeiros a partir dos demonstrativos da CVM.

Tudo aqui parte de contas contábeis públicas (DRE, BPA, BPP, DFC) — não há
nenhuma fonte de cotação/mercado envolvida. Sempre que um indicador depende
de uma aproximação (EBITDA, dívida) isso é registrado em `avisos` para ser
exibido ao usuário junto com o número.
"""

from __future__ import annotations

from . import accounts
from .cvm_client import StatementNotAvailableError, company_statement_with_fallback, scale_to_millions
from .models import Company, YearFinancials

AVISO_SETOR_FINANCEIRO = (
    "Empresa do setor financeiro/segurador: o plano de contas de DRE é diferente do padrão "
    "(não existe uma linha de 'resultado antes do financeiro'), então EBIT/EBITDA estimado "
    "aqui não é comparável ao de empresas não financeiras."
)
AVISO_EBITDA_ESTIMADO = (
    "EBITDA é uma estimativa (EBIT + Depreciação/Amortização extraída do fluxo de caixa), "
    "não o número 'ajustado' que a empresa pode divulgar em release de resultados."
)
AVISO_DA_NAO_ENCONTRADA = (
    "Depreciação/Amortização não localizada no fluxo de caixa; EBITDA estimado não calculado."
)
AVISO_DIVIDA_NAO_ENCONTRADA = (
    "Linha de Empréstimos e Financiamentos não encontrada nos códigos contábeis padrão; "
    "dívida líquida e dívida líquida/EBITDA omitidos."
)
AVISO_VERSAO_INDIVIDUAL = (
    "Demonstrativo consolidado não disponível para este ano; usando dados individuais da empresa."
)


def compute_year_financials(company: Company, ano: int, consolidado: bool = True) -> YearFinancials:
    avisos: list[str] = []
    if company.setor_financeiro:
        avisos.append(AVISO_SETOR_FINANCEIRO)

    try:
        dre, dre_consolidado = company_statement_with_fallback(company, ano, "DRE", consolidado)
        bpa, _ = company_statement_with_fallback(company, ano, "BPA", consolidado)
        bpp, _ = company_statement_with_fallback(company, ano, "BPP", consolidado)
        dfc, _ = company_statement_with_fallback(company, ano, "DFC_MI", consolidado)
    except StatementNotAvailableError:
        return YearFinancials(ano=ano, avisos=[f"Nenhum demonstrativo DFP publicado para {ano}."])

    if dre.empty:
        return YearFinancials(ano=ano, avisos=[f"Empresa não publicou DFP para o exercício de {ano}."])

    if consolidado and not dre_consolidado:
        avisos.append(AVISO_VERSAO_INDIVIDUAL)

    dre, bpa, bpp, dfc = (scale_to_millions(df) for df in (dre, bpa, bpp, dfc))

    receita = accounts.find_by_code(dre, accounts.DRE_RECEITA_LIQUIDA)
    ebit = accounts.find_by_code(dre, accounts.DRE_EBIT)
    lucro_liquido = accounts.lucro_liquido(dre)

    depreciacao_amortizacao = accounts.sum_rows_containing(
        dfc, *accounts.DEPRECIACAO_PALAVRAS, code_prefix="6.01"
    )
    ebitda = None
    if ebit is not None and depreciacao_amortizacao is not None:
        ebitda = ebit + depreciacao_amortizacao
    elif ebit is not None:
        avisos.append(AVISO_DA_NAO_ENCONTRADA)
    if ebitda is not None:
        avisos.append(AVISO_EBITDA_ESTIMADO)

    ativo_circulante = accounts.find_by_code(bpa, accounts.BPA_ATIVO_CIRCULANTE)
    caixa = accounts.find_by_code(bpa, accounts.BPA_CAIXA_E_EQUIVALENTES)
    passivo_circulante = accounts.find_by_code(bpp, accounts.BPP_PASSIVO_CIRCULANTE)
    patrimonio_liquido = accounts.find_by_code(bpp, accounts.BPP_PATRIMONIO_LIQUIDO)
    divida_bruta = accounts.divida_bruta(bpp)
    if divida_bruta is None:
        avisos.append(AVISO_DIVIDA_NAO_ENCONTRADA)

    margem_liquida = _pct(lucro_liquido, receita)
    margem_ebitda = _pct(ebitda, receita)
    roe = _pct(lucro_liquido, patrimonio_liquido)
    liquidez_corrente = _ratio(ativo_circulante, passivo_circulante)

    divida_liquida = None
    divida_liquida_sobre_ebitda = None
    if divida_bruta is not None and caixa is not None:
        divida_liquida = divida_bruta - caixa
        divida_liquida_sobre_ebitda = _ratio(divida_liquida, ebitda)

    return YearFinancials(
        ano=ano,
        receita_liquida_milhoes=receita,
        ebit_milhoes=ebit,
        ebitda_estimado_milhoes=ebitda,
        lucro_liquido_milhoes=lucro_liquido,
        margem_liquida_pct=margem_liquida,
        margem_ebitda_pct=margem_ebitda,
        roe_pct=roe,
        liquidez_corrente=liquidez_corrente,
        divida_bruta_milhoes=divida_bruta,
        caixa_milhoes=caixa,
        divida_liquida_milhoes=divida_liquida,
        divida_liquida_sobre_ebitda=divida_liquida_sobre_ebitda,
        avisos=avisos,
    )


def compute_history(company: Company, anos: list[int], consolidado: bool = True) -> list[YearFinancials]:
    return [compute_year_financials(company, ano, consolidado=consolidado) for ano in sorted(anos)]


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 2)
