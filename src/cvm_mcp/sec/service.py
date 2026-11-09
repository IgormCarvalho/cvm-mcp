"""Monta as respostas das tools SEC no mesmo formato das tools da CVM
(empresa, periodos com `derivado`, `contas`, `avisos`)."""

from __future__ import annotations

from .companies import SecCompany
from .facts import carregar_facts
from .mapping import DEMONSTRATIVOS, ESTOQUE
from .periods import (
    AVISO_4T_DERIVADO,
    AVISO_ACUMULADO,
    AVISO_POR_ACAO_4T,
    AVISO_REAPRESENTADO,
    AVISO_SINAL,
    IndiceFatos,
    checar_balanco,
    conta_para_dict,
    exercicios,
    trimestres,
    valor_anual,
    valor_trimestre,
)

AVISO_ESTRANGEIRO = (
    "Emissor estrangeiro (20-F/40-F/6-K): a SEC só exige XBRL no relatório anual. Os resultados "
    "trimestrais entregues em 6-K normalmente não são estruturados, então podem não aparecer aqui — "
    "use sec_obter_demonstrativo_anual, e o release de RI da empresa para os trimestres."
)
AVISO_STALE = "A SEC não respondeu; os dados vieram da cópia em cache local e podem estar desatualizados."


def empresa_dict(empresa: SecCompany) -> dict:
    return {
        "cik": empresa.cik_str,
        "ticker": empresa.ticker,
        "tickers": empresa.tickers,
        "nome": empresa.nome,
        "setor_sic": empresa.setor,
        "codigo_sic": empresa.sic,
        "fim_exercicio_fiscal": empresa.fim_exercicio_fiscal,
        "bolsas": empresa.bolsas,
        "categoria": empresa.categoria,
        "incorporacao": empresa.pais_incorporacao,
        "emissor_estrangeiro": empresa.emissor_estrangeiro,
    }


def _adicionar(avisos: list[str], aviso: str | None) -> None:
    if aviso and aviso not in avisos:
        avisos.append(aviso)


def _contas_do_trimestre(indice, demonstrativo, q, anteriores) -> list[dict]:
    contas = []
    for conta in DEMONSTRATIVOS[demonstrativo]:
        v = valor_trimestre(indice, conta, q, demonstrativo, anteriores)
        if v is not None:
            contas.append(conta_para_dict(conta, v))
    return contas


def serie_trimestral(empresa: SecCompany, demonstrativo: str, n: int) -> dict:
    df, moeda, _, stale = carregar_facts(empresa.cik)
    indice = IndiceFatos(df, moeda)
    todos = trimestres(indice)

    periodos: list[dict] = []
    avisos: list[str] = []
    for i, q in enumerate(todos):
        anteriores = [x for x in todos[:i] if x.exercicio_inicio == q.exercicio_inicio]
        contas = _contas_do_trimestre(indice, demonstrativo, q, anteriores)
        if not contas:
            continue
        if demonstrativo in ESTOQUE:
            outro = "BPP" if demonstrativo == "BPA" else "BPA"
            _adicionar(avisos, checar_balanco(contas + _contas_do_trimestre(indice, outro, q, anteriores)))
        periodos.append(
            {
                "trimestre": q.rotulo,
                "ano_fiscal": q.fy,
                "inicio": q.inicio,
                "fim": q.fim,
                "derivado": q.derivado and demonstrativo not in ESTOQUE,
                "contas": contas,
            }
        )

    periodos = periodos[-n:]
    usadas = {c["codigo"] for p in periodos for c in p["contas"]}

    if demonstrativo not in ESTOQUE:
        _adicionar(avisos, AVISO_SINAL)
        for p in periodos:
            derivadas = [c for c in p["contas"] if c["derivado"]]
            if p["derivado"] and derivadas:
                _adicionar(avisos, AVISO_4T_DERIVADO)
                if demonstrativo == "DRE":
                    _adicionar(avisos, AVISO_POR_ACAO_4T)
            elif derivadas:
                _adicionar(avisos, AVISO_ACUMULADO)
    if any(c.get("reapresentado") for p in periodos for c in p["contas"]):
        _adicionar(avisos, AVISO_REAPRESENTADO)
    if empresa.emissor_estrangeiro:
        _adicionar(avisos, AVISO_ESTRANGEIRO)
    if stale:
        _adicionar(avisos, AVISO_STALE)

    return {
        "moeda": moeda,
        "periodos": periodos,
        "contas_sem_dado": [c.codigo + " " + c.descricao for c in DEMONSTRATIVOS[demonstrativo] if c.codigo not in usadas],
        "avisos": avisos,
    }


def demonstrativo_anual(empresa: SecCompany, ano_fiscal: int, demonstrativo: str) -> dict:
    df, moeda, _, stale = carregar_facts(empresa.cik)
    indice = IndiceFatos(df, moeda)
    fechados = [e for e in exercicios(indice) if e.fechado]
    ex = next((e for e in fechados if e.fy == ano_fiscal), None)
    if ex is None:
        disponiveis = [e.fy for e in fechados]
        return {"encontrado": False, "aviso": f"Exercício fiscal {ano_fiscal} não encontrado. Disponíveis: {disponiveis}."}

    contas = []
    for conta in DEMONSTRATIVOS[demonstrativo]:
        v = valor_anual(indice, conta, ex, demonstrativo)
        if v is not None:
            contas.append(conta_para_dict(conta, v))

    avisos: list[str] = []
    if demonstrativo not in ESTOQUE:
        _adicionar(avisos, AVISO_SINAL)
    else:
        outro = "BPP" if demonstrativo == "BPA" else "BPA"
        extra = [conta_para_dict(c, v) for c in DEMONSTRATIVOS[outro] if (v := valor_anual(indice, c, ex, outro))]
        _adicionar(avisos, checar_balanco(contas + extra))
    if any(c.get("reapresentado") for c in contas):
        _adicionar(avisos, AVISO_REAPRESENTADO)
    if stale:
        _adicionar(avisos, AVISO_STALE)

    return {
        "encontrado": bool(contas),
        "moeda": moeda,
        "ano_fiscal": ex.fy,
        "inicio": ex.inicio,
        "fim": ex.fim,
        "contas": contas,
        "avisos": avisos,
    }


def conta_xbrl(empresa: SecCompany, tag: str, taxonomia: str, limite: int) -> dict:
    """Série bruta de uma tag XBRL qualquer — para contas fora do mapa padrão."""
    df, moeda, _, stale = carregar_facts(empresa.cik)
    serie = df[(df["tag"] == tag) & (df["taxonomia"] == taxonomia)]
    if serie.empty:
        parecidas = sorted(df.loc[df["tag"].str.contains(tag, case=False, regex=False), "tag"].unique())[:15]
        return {"encontrado": False, "aviso": f"Tag {taxonomia}:{tag} não reportada pela empresa.", "tags_parecidas": parecidas}

    serie = serie.sort_values(["fim", "inicio"]).tail(limite)
    registros = []
    for linha in serie.to_dict(orient="records"):
        monetaria = len(str(linha["unidade"])) == 3 and str(linha["unidade"]).isupper()
        registros.append(
            {
                "inicio": linha["inicio"] or None,
                "fim": linha["fim"],
                "unidade": linha["unidade"],
                "valor": round(linha["valor"] / 1_000_000, 3) if monetaria else linha["valor"],
                "escala": "milhoes" if monetaria else "unidade",
                "formulario": linha["form"],
                "acessao": linha["accn"],
                "arquivado_em": linha["filed"],
                "reapresentado": bool(linha["reapresentado"]),
            }
        )
    return {
        "encontrado": True,
        "tag_xbrl": f"{taxonomia}:{tag}",
        "moeda_principal": moeda,
        "valores": registros,
        "avisos": [AVISO_STALE] if stale else [],
    }
