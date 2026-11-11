"""
Atraso OTD dos pedidos do CTLR: mesma conta do relatório "Atraso OTD" do BI, mais um aviso antecipado.

Data OTD de cada pedido (fonte única, usada aqui e no encaixe em máquina):
- Nacional: embarque do CTLR - 2 dias (igual ao BI).
- Exportação (CFOP 7xxx ou UF "EX"): a dt_otd da OF no planejamento (a menor, se o pedido tiver
  mais de uma OF); sem OF no planejamento, embarque - 2. Decisão do usuário em 10/11/2026.
  Ex.: exportação 221589/1, embarque 30/11, dt_otd do planejamento 05/11 -> data OTD 05/11.

Situação (coluna atraso_otd):
- "ATRASADO":    a data OTD já passou (é antes de hoje) e a OF do pedido não terminou até ela;
                 ou o pedido já foi produzido depois da data OTD e o embarque é deste mês
                 (o BI mostra só o mês corrente; meses anteriores ficam "OK").
- "VAI ATRASAR": a data OTD ainda não chegou, mas o final previsto da OF passa dela.
- "OK":          nos demais casos, inclusive pedido sem OF no planejamento (atendido por estoque
                 ou ainda sem programação) e cancelado. O BI também não mostra esses.
Pedido produzido (peso_prod > 0): o fim da produção é a prev_prod do CTLR.
Pedido em aberto: precisa ter OF na planejamento (pedido + seq_prog); vale o maior final_prev.

Exemplos (hoje = 10/11/2026):
    embarque 10/11 (OTD 08/11), OF prevista 24/11, sem produção -> "ATRASADO"
    embarque 09/11 (OTD 07/11), produzido em 08/11              -> "ATRASADO"
    embarque 12/11 (OTD 10/11), OF prevista 11/11               -> "VAI ATRASAR"
    embarque 12/11 (OTD 10/11), OF prevista 10/11               -> "OK"
"""
import pandas as pd

DIAS_OTD = 2

ATRASADO = "ATRASADO"
VAI_ATRASAR = "VAI ATRASAR"
OK = "OK"


def _dia(serie: pd.Series) -> pd.Series:
    """Data sem hora (aceita texto dd/mm/aaaa ou data)."""
    if not pd.api.types.is_datetime64_any_dtype(serie):
        serie = pd.to_datetime(serie, errors="coerce", format="mixed", dayfirst=True)
    return serie.dt.normalize()


def _chave(pedido, prog) -> pd.Series:
    """pedido|prog como texto inteiro ("221009|2"), igual no CTLR e no planejamento."""
    ped = pd.to_numeric(pedido, errors="coerce").astype("Int64").astype(str)
    prg = pd.to_numeric(prog, errors="coerce").astype("Int64").astype(str)
    return ped + "|" + prg


def eh_exportacao(ctlr: pd.DataFrame) -> pd.Series:
    cfop = ctlr["cfop"].astype(str).str.strip() if "cfop" in ctlr else pd.Series("", index=ctlr.index)
    uf = ctlr["uf"].astype(str).str.strip().str.upper() if "uf" in ctlr else pd.Series("", index=ctlr.index)
    return cfop.str.startswith("7") | (uf == "EX")


def ofs_do_planejamento(plan: pd.DataFrame) -> pd.DataFrame:
    """Por pedido|prog: menor dt_otd, maior final_prev, se todas terminaram e o maior final_real."""
    if plan is None or plan.empty:
        return pd.DataFrame(columns=["dt_otd", "final_prev", "todas_terminadas", "final_real"])
    p = plan[pd.to_numeric(plan["pedido"], errors="coerce").notna()].copy()
    p["chave"] = _chave(p["pedido"], p["seq_prog"])
    p["dt_otd_d"] = _dia(p["dt_otd"])
    p["final_prev_d"] = _dia(p["final_prev"])
    p["final_real_d"] = _dia(p["final_real"])
    g = p.groupby("chave")
    return pd.DataFrame({
        "dt_otd": g["dt_otd_d"].min(),
        "final_prev": g["final_prev_d"].max(),
        "todas_terminadas": g["final_real_d"].apply(lambda s: s.notna().all()),
        "final_real": g["final_real_d"].max(),
    })


def data_otd(ctlr: pd.DataFrame, ofs: pd.DataFrame) -> pd.Series:
    """Data OTD de cada linha do CTLR (ver o cabeçalho)."""
    embarque = _dia(ctlr["embarque"])
    padrao = embarque - pd.Timedelta(days=DIAS_OTD)
    chave = _chave(ctlr["num_ped"], ctlr["num_prog"])
    do_plano = chave.map(ofs["dt_otd"]) if len(ofs) else pd.Series(pd.NaT, index=ctlr.index)
    usar_plano = eh_exportacao(ctlr) & pd.notna(do_plano) & embarque.notna()
    return padrao.where(~usar_plano, do_plano)


def mapa_data_otd(ctlr: pd.DataFrame) -> dict:
    """pedido|prog -> data OTD, do CTLR já com a coluna data_otd (usado pelo encaixe)."""
    if ctlr is None or ctlr.empty or "data_otd" not in ctlr:
        return {}
    datas = pd.to_datetime(ctlr["data_otd"], errors="coerce")
    chaves = _chave(ctlr["num_ped"], ctlr["num_prog"])
    return {k: d for k, d in zip(chaves, datas) if pd.notna(d) and "<NA>" not in k}


def calcular_atraso_otd(ctlr: pd.DataFrame, plan: pd.DataFrame, hoje=None) -> pd.DataFrame:
    """Devolve o CTLR com as colunas data_otd e atraso_otd."""
    hoje = pd.Timestamp(hoje if hoje is not None else pd.Timestamp.now()).normalize()
    df = ctlr.copy()
    ofs = ofs_do_planejamento(plan)
    df["data_otd"] = data_otd(df, ofs)

    embarque = _dia(df["embarque"])
    otd = df["data_otd"]
    mes_atual = (embarque.dt.year == hoje.year) & (embarque.dt.month == hoje.month)
    produzido = pd.to_numeric(df.get("peso_prod"), errors="coerce").fillna(0) > 0
    prev_prod = _dia(df["prev_prod"])

    chave = _chave(df["num_ped"], df["num_prog"])
    tem_of = chave.isin(ofs.index)
    of = ofs.reindex(chave.values)
    of.index = df.index
    terminou = of["todas_terminadas"].fillna(False).astype(bool) & of["final_real"].notna()

    situacao = pd.Series(OK, index=df.index)
    valido = embarque.notna() & ~df["status_pedido"].isin(["CANCELADO", "NF ANULADA"])

    # Já produzido: compara o fim real (prev_prod) com a data OTD, só no mês corrente
    prod_atrasado = valido & produzido & prev_prod.notna() & mes_atual & (prev_prod > otd)
    situacao[prod_atrasado] = ATRASADO

    aberto = valido & ~produzido & tem_of
    # OF terminou, mas o CTLR ainda não tem o peso produzido
    term_atrasado = aberto & terminou & (of["final_real"] > otd) & mes_atual
    situacao[term_atrasado] = ATRASADO
    pendente = aberto & ~terminou
    situacao[pendente & (hoje > otd)] = ATRASADO
    situacao[pendente & ~(hoje > otd) & (of["final_prev"] > otd)] = VAI_ATRASAR

    df["atraso_otd"] = situacao
    return df
