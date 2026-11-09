"""Calendário fiscal e montagem dos valores por período (fonte SEC).

Como na CVM, a visão é trimestral e o 4º trimestre não é publicado: o 10-K
traz o ano fechado, e o 4T sai de `ano − acumulado até o 3T`. Na SEC há uma
segunda situação de derivação: o fluxo de caixa do 10-Q costuma vir só
ACUMULADO no ano (3, 6 e 9 meses), então o 2T e o 3T isolados também são
obtidos por diferença entre acumulados. Todo valor derivado vem marcado.

O exercício fiscal é o da própria empresa (a Apple fecha no fim de setembro,
varejistas no fim de janeiro). O rótulo do trimestre usa o ano fiscal que a
empresa declarou no 10-K original (`fy`), e sempre vem acompanhado das datas
de início e fim, que são o identificador inequívoco.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass

import pandas as pd

from .config import FORMS_ANUAIS
from .mapping import DEMONSTRATIVOS, ESTOQUE, Conta

TOLERANCIA_DIAS = 7  # calendários de 52/53 semanas deslocam datas em alguns dias
DURACAO_TRIMESTRE = (80, 100)
DURACAO_ANO = (350, 380)

AVISO_4T_DERIVADO = (
    "O 4º trimestre não é publicado isoladamente: foi derivado como (exercício anual do 10-K/20-F − "
    "acumulado até o 3º trimestre), conta a conta e na mesma tag XBRL."
)
AVISO_ACUMULADO = (
    "Algumas contas de fluxo só são reportadas acumuladas no ano (comum no fluxo de caixa do 10-Q); "
    "o trimestre isolado foi obtido pela diferença entre acumulados. Essas contas vêm com derivado=true."
)
AVISO_SINAL = (
    "Valores como reportados no XBRL da SEC: custos e despesas vêm POSITIVOS (diferente da CVM, que "
    "publica despesas negativas). Saídas de caixa (capex, dividendos, recompra) também vêm positivas."
)
AVISO_POR_ACAO_4T = (
    "LPA e número médio de ações não são derivados por subtração (não é aritmeticamente válido); "
    "no trimestre derivado esses campos ficam ausentes."
)
AVISO_REAPRESENTADO = (
    "Há contas com reapresentado=true: a empresa reportou valores diferentes para o mesmo período em "
    "entregas distintas. O valor mostrado é o da entrega mais recente."
)


def _d(valor: str) -> dt.date:
    return dt.date.fromisoformat(valor)


def _dias(inicio: str, fim: str) -> int:
    return (_d(fim) - _d(inicio)).days


def _perto(a: str, b: str, tol: int = TOLERANCIA_DIAS) -> bool:
    return abs((_d(a) - _d(b)).days) <= tol


@dataclass(frozen=True)
class Exercicio:
    fy: int
    inicio: str
    fim: str
    fechado: bool


@dataclass(frozen=True)
class SecQuarter:
    fy: int
    numero: int
    inicio: str
    fim: str
    exercicio_inicio: str
    derivado: bool  # 4T obtido por diferença contra o anual

    @property
    def rotulo(self) -> str:
        return f"{self.numero}T{self.fy % 100:02d}"


class IndiceFatos:
    """Índice em memória dos fatos consolidados, por (taxonomia, tag, unidade)."""

    def __init__(self, df: pd.DataFrame, moeda: str):
        self.moeda = moeda
        self.duracao: dict[tuple, dict[tuple[str, str], dict]] = defaultdict(dict)
        self.instante: dict[tuple, dict[str, dict]] = defaultdict(dict)
        self.fins_por_duracao: dict[tuple, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
        for linha in df.to_dict(orient="records"):
            chave = (linha["taxonomia"], linha["tag"], linha["unidade"])
            if linha["inicio"]:
                self.duracao[chave][(linha["inicio"], linha["fim"])] = linha
                self.fins_por_duracao[chave][linha["fim"]].append((linha["inicio"], linha["fim"]))
            else:
                self.instante[chave][linha["fim"]] = linha

    def unidade(self, conta: Conta) -> str:
        if conta.unidade == "por_acao":
            return f"{self.moeda}/shares"
        if conta.unidade == "acoes":
            return "shares"
        return self.moeda

    def duracao_terminando(self, chave: tuple, fim: str) -> list[dict]:
        return [self.duracao[chave][p] for p in self.fins_por_duracao[chave].get(fim, [])]


# ---------------------------------------------------------------------------
# Calendário fiscal
# ---------------------------------------------------------------------------

def _tags_de_fluxo() -> list[tuple[str, str]]:
    tags = []
    for nome in ("DRE", "DFC"):
        for conta in DEMONSTRATIVOS[nome]:
            if conta.unidade == "moeda":
                tags.extend(conta.candidatos)
    return tags


def exercicios(indice: IndiceFatos) -> list[Exercicio]:
    """Exercícios fiscais da empresa, a partir dos períodos anuais (~1 ano)
    reportados em 10-K/20-F/40-F, mais o exercício em aberto quando já há
    trimestres publicados depois do último anual."""
    por_fim: dict[str, list[tuple[str, int | None]]] = defaultdict(list)
    fins_trimestrais: list[str] = []

    for taxonomia, tag in _tags_de_fluxo():
        chave = (taxonomia, tag, indice.moeda)
        for (inicio, fim), linha in indice.duracao.get(chave, {}).items():
            dias = _dias(inicio, fim)
            if DURACAO_ANO[0] <= dias <= DURACAO_ANO[1] and linha["form"] in FORMS_ANUAIS:
                fy = linha.get("fy_original")
                por_fim[fim].append((inicio, int(fy) if pd.notna(fy) else None))
            elif dias < DURACAO_ANO[0]:
                fins_trimestrais.append(fim)

    lista: list[Exercicio] = []
    for fim in sorted(por_fim):
        inicios = Counter(i for i, _ in por_fim[fim])
        anos = Counter(a for _, a in por_fim[fim] if a)
        inicio = inicios.most_common(1)[0][0]
        fy = anos.most_common(1)[0][0] if anos else _d(fim).year
        if lista and _perto(lista[-1].fim, fim, 20):
            continue  # mesmo exercício com datas levemente diferentes entre tags
        lista.append(Exercicio(fy=fy, inicio=inicio, fim=fim, fechado=True))

    if lista and fins_trimestrais and max(fins_trimestrais) > lista[-1].fim:
        ultimo = lista[-1]
        inicio = (_d(ultimo.fim) + dt.timedelta(days=1)).isoformat()
        fim_previsto = (_d(ultimo.fim) + dt.timedelta(days=365)).isoformat()
        lista.append(Exercicio(fy=ultimo.fy + 1, inicio=inicio, fim=fim_previsto, fechado=False))

    # Anos fiscais repetidos (empresa mudou o fim do exercício): rótulo pela data.
    vistos = Counter(e.fy for e in lista)
    return [
        e if vistos[e.fy] == 1 else Exercicio(_d(e.fim).year, e.inicio, e.fim, e.fechado) for e in lista
    ]


def _numero_trimestre(exercicio_inicio: str, fim: str) -> int:
    meses = (_d(fim) - _d(exercicio_inicio)).days / 30.44
    return max(1, min(4, round(meses / 3)))


def trimestres(indice: IndiceFatos) -> list[SecQuarter]:
    """Todos os trimestres identificáveis, em ordem cronológica. Um trimestre
    existe quando há algum fato trimestral ou acumulado no ano terminando
    nele (ou, no 4T, quando o exercício fechou)."""
    resultado: list[SecQuarter] = []
    exs = exercicios(indice)

    for ex in exs:
        fins: dict[int, str] = {}
        inicios_diretos: dict[int, str] = {}
        for taxonomia, tag in _tags_de_fluxo():
            chave = (taxonomia, tag, indice.moeda)
            for (inicio, fim), _ in indice.duracao.get(chave, {}).items():
                dentro = (ex.inicio < fim <= ex.fim) if ex.fechado else (fim > ex.inicio)
                if not dentro:
                    continue
                dias = _dias(inicio, fim)
                trimestral = DURACAO_TRIMESTRE[0] <= dias <= DURACAO_TRIMESTRE[1]
                n = _numero_trimestre(ex.inicio, fim)
                # Acumulado só vale se tiver ~3, 6 ou 9 meses: períodos curtos
                # avulsos (ex: pós-aquisição) não podem virar "trimestre".
                acumulado = (
                    _perto(inicio, ex.inicio) and dias < DURACAO_ANO[0] and abs(dias - n * 91.3) <= 15
                )
                if not (trimestral or acumulado):
                    continue
                if n == 4 and ex.fechado:
                    continue  # o 4T de exercício fechado é tratado abaixo
                fins[n] = max(fins.get(n, fim), fim)
                if trimestral:
                    inicios_diretos[n] = inicio

        if ex.fechado:
            fins[4] = ex.fim

        for n in sorted(fins):
            if n == 1:
                inicio = ex.inicio
            elif n - 1 in fins:
                inicio = (_d(fins[n - 1]) + dt.timedelta(days=1)).isoformat()
            elif n in inicios_diretos:
                inicio = inicios_diretos[n]
            else:
                continue
            derivado = n == 4 and ex.fechado
            resultado.append(SecQuarter(ex.fy, n, inicio, fins[n], ex.inicio, derivado))

    return sorted(resultado, key=lambda q: q.fim)


# ---------------------------------------------------------------------------
# Valores
# ---------------------------------------------------------------------------

@dataclass
class Valor:
    valor: float
    tag: str
    taxonomia: str
    formulario: str
    acessao: str | None
    arquivado_em: str | None
    derivado: bool
    reapresentado: bool


def _valor_de(linha: dict, derivado: bool = False, valor: float | None = None, formulario: str | None = None) -> Valor:
    return Valor(
        valor=linha["valor"] if valor is None else valor,
        tag=linha["tag"],
        taxonomia=linha["taxonomia"],
        formulario=formulario or linha["form"],
        acessao=linha.get("accn"),
        arquivado_em=linha.get("filed"),
        derivado=derivado,
        reapresentado=bool(linha.get("reapresentado")),
    )


def _trimestral_direto(indice: IndiceFatos, chave: tuple, inicio: str, fim: str) -> dict | None:
    for linha in indice.duracao_terminando(chave, fim):
        dias = _dias(linha["inicio"], fim)
        if DURACAO_TRIMESTRE[0] <= dias <= DURACAO_TRIMESTRE[1] and _perto(linha["inicio"], inicio):
            return linha
    return None


def _acumulado(indice: IndiceFatos, chave: tuple, exercicio_inicio: str, fim: str) -> dict | None:
    for linha in indice.duracao_terminando(chave, fim):
        if _perto(linha["inicio"], exercicio_inicio):
            return linha
    return None


def _fluxo_trimestre(
    indice: IndiceFatos, chave: tuple, q: SecQuarter, anteriores: list[SecQuarter], permite_derivar: bool
) -> Valor | None:
    direto = _trimestral_direto(indice, chave, q.inicio, q.fim)
    if direto is not None:
        return _valor_de(direto)
    if not permite_derivar:
        return None

    acum = _acumulado(indice, chave, q.exercicio_inicio, q.fim)
    if acum is None:
        return None
    if q.numero == 1 or not anteriores:
        return _valor_de(acum) if q.numero == 1 else None

    # Mesmo exercício, trimestre imediatamente anterior.
    anterior = anteriores[-1]
    acum_ant = _acumulado(indice, chave, q.exercicio_inicio, anterior.fim)
    if acum_ant is not None:
        return _valor_de(
            acum, derivado=True, valor=acum["valor"] - acum_ant["valor"], formulario=f"{acum['form']} − {acum_ant['form']}"
        )

    # Sem acumulado anterior: soma dos trimestres anteriores (todos precisam existir).
    soma = 0.0
    for i, qa in enumerate(anteriores):
        v = _fluxo_trimestre(indice, chave, qa, anteriores[:i], permite_derivar)
        if v is None:
            return None
        soma += v.valor
    return _valor_de(acum, derivado=True, valor=acum["valor"] - soma, formulario=f"{acum['form']} − soma trimestres")


def valor_trimestre(indice: IndiceFatos, conta: Conta, q: SecQuarter, demonstrativo: str, mesmos_exercicio: list[SecQuarter]) -> Valor | None:
    unidade = indice.unidade(conta)
    for taxonomia, tag in conta.candidatos:
        chave = (taxonomia, tag, unidade)
        if demonstrativo in ESTOQUE:
            linha = indice.instante.get(chave, {}).get(q.fim)
            if linha is not None:
                return _valor_de(linha)
            continue
        valor = _fluxo_trimestre(indice, chave, q, mesmos_exercicio, permite_derivar=conta.unidade == "moeda")
        if valor is not None:
            return valor
    return None


def valor_anual(indice: IndiceFatos, conta: Conta, ex: Exercicio, demonstrativo: str) -> Valor | None:
    unidade = indice.unidade(conta)
    for taxonomia, tag in conta.candidatos:
        chave = (taxonomia, tag, unidade)
        if demonstrativo in ESTOQUE:
            linha = indice.instante.get(chave, {}).get(ex.fim)
            if linha is not None:
                return _valor_de(linha)
            continue
        for linha in indice.duracao_terminando(chave, ex.fim):
            if _perto(linha["inicio"], ex.inicio) and _dias(linha["inicio"], ex.fim) >= DURACAO_ANO[0]:
                return _valor_de(linha)
    return None


def escalar(conta: Conta, valor: float) -> float:
    if conta.unidade == "por_acao":
        return round(valor, 4)
    return round(valor / 1_000_000, 3)


def conta_para_dict(conta: Conta, v: Valor) -> dict:
    saida = {
        "codigo": conta.codigo,
        "descricao": conta.descricao,
        "valor": escalar(conta, v.valor),
        "tag_xbrl": f"{v.taxonomia}:{v.tag}",
        "formulario": v.formulario,
        "acessao": v.acessao,
        "arquivado_em": v.arquivado_em,
        "derivado": v.derivado,
    }
    if v.reapresentado:
        saida["reapresentado"] = True
    if conta.unidade == "por_acao":
        saida["unidade"] = "por ação"
    elif conta.unidade == "acoes":
        saida["unidade"] = "milhões de ações"
    return saida


def checar_balanco(contas: list[dict]) -> str | None:
    """Ativo total deve bater com passivo + PL. Diferença acima de 0,5% vira aviso."""
    por_codigo = {c["codigo"]: c["valor"] for c in contas}
    ativo, passivo_pl = por_codigo.get("1"), por_codigo.get("2")
    if ativo and passivo_pl and abs(ativo - passivo_pl) / abs(ativo) > 0.005:
        return f"Ativo total ({ativo:,.1f}) não bate com passivo + PL ({passivo_pl:,.1f}); confira as tags usadas."
    return None
