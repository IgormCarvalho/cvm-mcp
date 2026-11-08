"""Mapa de padronização: tags XBRL da SEC → contas padrão do servidor.

Na CVM o plano de contas é fixo (o código 3.01 é sempre a receita). Na SEC
cada empresa escolhe as tags dentro da taxonomia US-GAAP (ou IFRS, no caso
de emissores estrangeiros), e a mesma conta aparece com nomes diferentes —
a receita pode vir como `Revenues`, `RevenueFromContractWithCustomer...`,
`SalesRevenueNet` etc.

Cada conta abaixo tem uma lista ORDENADA de candidatos: para cada período
usa-se o primeiro que a empresa reportou. A resposta sempre informa qual tag
foi usada (`tag_xbrl`), para o analista auditar. Contas que não estão aqui
podem ser consultadas direto pela tool `sec_obter_conta_xbrl`.

Os códigos imitam a estrutura da CVM (1 = ativo, 2 = passivo e PL,
3 = resultado, 6 = caixa) para facilitar a leitura lado a lado, mas não são
códigos oficiais de nenhum órgão.
"""

from __future__ import annotations

from dataclasses import dataclass

US = "us-gaap"
IFRS = "ifrs-full"
DEI = "dei"


@dataclass(frozen=True)
class Conta:
    codigo: str
    descricao: str
    candidatos: tuple[tuple[str, str], ...]
    unidade: str = "moeda"  # "moeda", "por_acao" ou "acoes"


def _c(codigo: str, descricao: str, us: list[str], ifrs: list[str] | None = None, unidade: str = "moeda") -> Conta:
    candidatos = tuple((US, tag) for tag in us) + tuple((IFRS, tag) for tag in (ifrs or []))
    return Conta(codigo, descricao, candidatos, unidade)


DRE = (
    _c("3.01", "Receita total", [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "RevenuesNetOfInterestExpense",
    ], ["Revenue", "RevenueFromContractsWithCustomers"]),
    _c("3.02", "Custo dos produtos/serviços vendidos", [
        "CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices",
    ], ["CostOfSales"]),
    _c("3.03", "Lucro bruto", ["GrossProfit"], ["GrossProfit"]),
    _c("3.04", "Pesquisa e desenvolvimento", ["ResearchAndDevelopmentExpense"], ["ResearchAndDevelopmentExpense"]),
    _c("3.05", "Despesas de vendas, gerais e administrativas", ["SellingGeneralAndAdministrativeExpense"],
       ["SellingGeneralAndAdministrativeExpense"]),
    _c("3.06", "Custos e despesas operacionais totais", ["CostsAndExpenses", "OperatingExpenses"]),
    _c("3.07", "Resultado operacional", ["OperatingIncomeLoss"], ["ProfitLossFromOperatingActivities"]),
    _c("3.08", "Receita de juros (financeiras/bancos)", [
        "InterestAndDividendIncomeOperating", "InterestIncome", "InterestAndFeeIncomeLoansAndLeases",
    ], ["RevenueFromInterest", "InterestRevenueCalculatedUsingEffectiveInterestMethod"]),
    _c("3.09", "Despesa de juros", ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseOperating"],
       ["InterestExpense", "FinanceCosts"]),
    _c("3.10", "Provisão para perdas de crédito", [
        "ProvisionForLoanLeaseAndOtherLosses", "ProvisionForLoanAndLeaseLosses", "CreditLossExpense",
        "ProvisionForCreditLosses",
    ], ["ImpairmentLossImpairmentGainAndReversalOfImpairmentLossDeterminedInAccordanceWithIFRS9"]),
    _c("3.11", "Resultado antes dos impostos", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
    ], ["ProfitLossBeforeTax"]),
    _c("3.12", "Imposto de renda", ["IncomeTaxExpenseBenefit"], ["IncomeTaxExpenseContinuingOperations"]),
    _c("3.13", "Lucro líquido atribuído aos controladores", ["NetIncomeLoss", "ProfitLoss"],
       ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"]),
    _c("3.99.01", "LPA básico", ["EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"],
       ["BasicEarningsLossPerShare"], unidade="por_acao"),
    _c("3.99.02", "LPA diluído", ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
       ["DilutedEarningsLossPerShare"], unidade="por_acao"),
    _c("3.99.03", "Ações médias ponderadas diluídas", ["WeightedAverageNumberOfDilutedSharesOutstanding"],
       ["WeightedAverageNumberOfSharesOutstandingDiluted"], unidade="acoes"),
)

BPA = (
    _c("1", "Ativo total", ["Assets"], ["Assets"]),
    _c("1.01", "Ativo circulante", ["AssetsCurrent"], ["CurrentAssets"]),
    _c("1.01.01", "Caixa e equivalentes", [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndDueFromBanks",
    ], ["CashAndCashEquivalents"]),
    _c("1.01.02", "Aplicações financeiras de curto prazo", [
        "ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ], ["CurrentInvestments"]),
    _c("1.01.03", "Contas a receber", ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
       ["TradeAndOtherCurrentReceivables"]),
    _c("1.01.04", "Estoques", ["InventoryNet"], ["Inventories"]),
    _c("1.02", "Ativo não circulante", ["AssetsNoncurrent"], ["NoncurrentAssets"]),
    _c("1.02.01", "Imobilizado líquido", ["PropertyPlantAndEquipmentNet"], ["PropertyPlantAndEquipment"]),
    _c("1.02.02", "Ágio (goodwill)", ["Goodwill"], ["Goodwill"]),
    _c("1.02.03", "Intangível", ["IntangibleAssetsNetExcludingGoodwill"], ["IntangibleAssetsOtherThanGoodwill"]),
    _c("1.03", "Carteira de crédito líquida (financeiras/bancos)", [
        "LoansAndLeasesReceivableNetReportedAmount",
        "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
        "NotesReceivableNet",
    ]),
)

BPP = (
    _c("2", "Passivo total + patrimônio líquido", ["LiabilitiesAndStockholdersEquity"], ["EquityAndLiabilities"]),
    _c("2.01", "Passivo circulante", ["LiabilitiesCurrent"], ["CurrentLiabilities"]),
    _c("2.01.01", "Fornecedores", ["AccountsPayableCurrent"], ["TradeAndOtherCurrentPayables"]),
    _c("2.01.02", "Dívida de curto prazo", ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings"],
       ["CurrentPortionOfLongtermBorrowings", "ShorttermBorrowings"]),
    _c("2.02", "Passivo não circulante", ["LiabilitiesNoncurrent"], ["NoncurrentLiabilities"]),
    _c("2.02.01", "Dívida de longo prazo", ["LongTermDebtNoncurrent", "LongTermDebt"], ["LongtermBorrowings"]),
    _c("2.03", "Passivo total", ["Liabilities"], ["Liabilities"]),
    _c("2.04", "Depósitos (bancos)", ["Deposits"], ["DepositsFromCustomers"]),
    _c("2.05", "Patrimônio líquido dos controladores", ["StockholdersEquity"],
       ["EquityAttributableToOwnersOfParent"]),
    _c("2.05.01", "Participação de não controladores", ["MinorityInterest"], ["NoncontrollingInterests"]),
    _c("2.06", "Patrimônio líquido total", [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity",
    ], ["Equity"]),
)

DFC = (
    _c("6.01", "Caixa líquido das atividades operacionais", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ], ["CashFlowsFromUsedInOperatingActivities"]),
    _c("6.01.01", "Depreciação e amortização", [
        "DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet",
    ], ["DepreciationAndAmortisationExpense"]),
    _c("6.01.02", "Remuneração baseada em ações", ["ShareBasedCompensation"]),
    _c("6.02", "Caixa líquido das atividades de investimento", [
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    ], ["CashFlowsFromUsedInInvestingActivities"]),
    _c("6.02.01", "Aquisição de imobilizado (capex)", ["PaymentsToAcquirePropertyPlantAndEquipment"],
       ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"]),
    _c("6.03", "Caixa líquido das atividades de financiamento", [
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
    ], ["CashFlowsFromUsedInFinancingActivities"]),
    _c("6.03.01", "Dividendos pagos", ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
       ["DividendsPaidClassifiedAsFinancingActivities"]),
    _c("6.03.02", "Recompra de ações", ["PaymentsForRepurchaseOfCommonStock"],
       ["PaymentsToAcquireOrRedeemEntitysShares"]),
)

DEMONSTRATIVOS: dict[str, tuple[Conta, ...]] = {"DRE": DRE, "BPA": BPA, "BPP": BPP, "DFC": DFC}

# Saldos numa data (instant) x movimento de um período (duration).
ESTOQUE = frozenset({"BPA", "BPP"})
