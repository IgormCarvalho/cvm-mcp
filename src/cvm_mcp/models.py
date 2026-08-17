"""Estruturas de dados trocadas entre as camadas internas e as tools MCP.
Tudo aqui é serializável em dict/JSON via dataclasses.asdict()."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Company:
    cnpj: str
    cd_cvm: str
    denom_social: str
    setor_ativ: str | None = None
    situacao_registro: str | None = None
    situacao_emissor: str | None = None

    @property
    def setor_financeiro(self) -> bool:
        """Bancos, seguradoras e afins têm um plano de contas diferente
        (não têm 'Resultado Antes do Resultado Financeiro') — usado para
        avisar quando EBIT/EBITDA estimado não é confiável."""
        setor = (self.setor_ativ or "").lower()
        palavras = ("banco", "financ", "segur", "previd", "credit")
        return any(palavra in setor for palavra in palavras)


@dataclass(frozen=True)
class Quarter:
    """Um trimestre de uma empresa, sempre identificado pelas datas além do
    rótulo: exercícios sociais não-calendário fazem o "2T" fechar em maio ou
    agosto, então só o par (dt_ini, dt_fim) é inequívoco.

    origem indica a procedência do dado: "ITR" para trimestre publicado, e
    "DFP-ITR" para o 4T, que é derivado por diferença.
    """

    ano: int
    numero: int
    dt_ini: str
    dt_fim: str
    origem: str

    @property
    def rotulo(self) -> str:
        return f"{self.numero}T{self.ano % 100:02d}"

    @property
    def derivado(self) -> bool:
        return self.origem == "DFP-ITR"


@dataclass
class YearFinancials:
    ano: int
    receita_liquida_milhoes: float | None = None
    ebit_milhoes: float | None = None
    ebitda_estimado_milhoes: float | None = None
    lucro_liquido_milhoes: float | None = None
    margem_liquida_pct: float | None = None
    margem_ebitda_pct: float | None = None
    roe_pct: float | None = None
    liquidez_corrente: float | None = None
    divida_bruta_milhoes: float | None = None
    caixa_milhoes: float | None = None
    divida_liquida_milhoes: float | None = None
    divida_liquida_sobre_ebitda: float | None = None
    avisos: list[str] = field(default_factory=list)
