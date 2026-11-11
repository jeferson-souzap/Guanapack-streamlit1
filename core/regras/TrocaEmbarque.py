"""
Troca da data de embarque (mesma regra da aba troca_embarque da planilha Excel, rev027).

Regra do usuário (10/11/2026): a data de embarque só pode ser trocada até 24 horas depois da emissão
do pedido. Depois disso ela fica como está, e o pedido ainda pode ficar com status de atraso no OTD
(o atraso_otd do CTLR não muda). A emissão vem do ERP sem hora, então o prazo vai até o fim do dia
seguinte à emissão. Ex.: emitido em 09/11 -> pode pedir a troca até 10/11 (inclusive).

Lista os pedidos em aberto dentro do prazo de troca:
- "PEDIR TROCA": o atraso_otd diz ATRASADO ou VAI ATRASAR (a OF do planejamento termina depois da data
  OTD), ou o encaixe diz que o pedido sem estoque não atende o prazo (ou não tem máquina);
- "CONFERIR": sem OF no planejamento e fora da reserva da carteira (não dá para saber o prazo);
- "OK": atendido pelo estoque, ou a OF/o encaixe terminam até a data OTD.
embarque_sugerido = dia do fim previsto + 2 dias (a data OTD = embarque - 2 cai no dia em que termina).
"""
import pandas as pd

DIAS_PARA_TROCAR = 1      # 24 h depois da emissão (emissão sem hora: até o fim do dia seguinte)
DIAS_OTD = 2
PEDIR_TROCA = "PEDIR TROCA"
CONFERIR = "CONFERIR"
OK = "OK"
STATUS_EM_ABERTO = ["AGUARDANDO APROVAÇÃO", "EM CARTEIRA", "SOLICITAÇÃO DE RESERVA", "RESERVADO"]
ORDEM = {PEDIR_TROCA: 0, CONFERIR: 1, OK: 2}
COLUNAS = ["situacao", "num_pedido", "prog", "cliente", "dt_emissao", "prazo_troca", "status_pedido", "embarque",
           "data_otd", "fim_previsto", "embarque_sugerido", "atraso_otd", "motivo"]


def _chave(pedido, prog) -> str:
    p, g = pd.to_numeric(pedido, errors="coerce"), pd.to_numeric(prog, errors="coerce")
    return f"{'' if pd.isna(p) else int(p)}|{'' if pd.isna(g) else int(g)}"


def _dia(v):
    d = pd.to_datetime(v, errors="coerce")
    return d.normalize() if pd.notna(d) else pd.NaT


def calcular_troca(ctlr: pd.DataFrame, plan: pd.DataFrame | None, encaixe: pd.DataFrame | None,
                   reserva: pd.DataFrame | None, hoje=None) -> tuple[pd.DataFrame, str]:
    hoje = pd.Timestamp(hoje if hoje is not None else pd.Timestamp.now()).normalize()
    fim_plan = {}
    if plan is not None and not plan.empty:
        p = plan[pd.to_numeric(plan["pedido"], errors="coerce").notna() & plan["final_prev"].notna()]
        for _, r in p.iterrows():
            k = _chave(r["pedido"], r["seq_prog"])
            fim_plan[k] = max(fim_plan.get(k, r["final_prev"]), r["final_prev"])
    enc = {}
    if encaixe is not None and not encaixe.empty:
        enc = {_chave(r["num_pedido"], r["prog"]): r for _, r in encaixe.iterrows()}
    com_estoque = {}
    if reserva is not None and not reserva.empty:
        com_estoque = {_chave(r["num_pedido"], r["prog"]): r["atendimento"]
                       for _, r in reserva[reserva["tem_estoque"] == "SIM"].iterrows()}

    linhas, vistos = [], set()
    for _, r in ctlr.iterrows():
        emissao = _dia(r["dt_emissao"])
        status = r["status_pedido"]
        if pd.isna(emissao) or status not in STATUS_EM_ABERTO:
            continue
        prazo = emissao + pd.Timedelta(days=DIAS_PARA_TROCAR)
        k = _chave(r["num_ped"], r["num_prog"])
        if hoje > prazo or k in vistos:
            continue
        vistos.add(k)
        embarque = _dia(r["embarque"])
        otd = _dia(r.get("data_otd"))
        if pd.isna(otd) and pd.notna(embarque):
            otd = embarque - pd.Timedelta(days=DIAS_OTD)
        atraso = r.get("atraso_otd") or OK
        situacao, motivo, fim = OK, "", None
        if atraso in ("ATRASADO", "VAI ATRASAR"):
            situacao, motivo = PEDIR_TROCA, f"Atraso OTD: {atraso} (OF do planejamento termina depois da data OTD)"
            fim = fim_plan.get(k)
        elif k in enc:
            e = enc[k]
            if e["sugestao"] == "SEM MÁQUINA":
                situacao, motivo = PEDIR_TROCA, "sem estoque e sem máquina que rode o produto"
            elif e["atende_embarque"] == "NÃO":
                maquina = f", {e['maquina']}" if pd.notna(e.get("maquina")) else ""
                situacao, motivo = PEDIR_TROCA, f"encaixe ({str(e['sugestao']).lower()}{maquina}) termina depois da data OTD"
                fim = e["fim_previsto"]
            else:
                motivo = f"encaixe atende o prazo ({str(e['sugestao']).lower()})"
        elif status in ("RESERVADO", "SOLICITAÇÃO DE RESERVA"):
            motivo = f"atendido pelo estoque ({status.lower()})"
        elif k in com_estoque:
            motivo = f"reserva da carteira: tem estoque ({str(com_estoque[k]).lower()})"
        elif k in fim_plan:
            motivo = "OF do planejamento termina até a data OTD"
        else:
            situacao, motivo = CONFERIR, f"sem OF no planejamento e fora da reserva da carteira ({status.lower()})"
        fim = pd.to_datetime(fim, errors="coerce") if fim is not None else pd.NaT
        sugerido = fim.normalize() + pd.Timedelta(days=DIAS_OTD) if situacao == PEDIR_TROCA and pd.notna(fim) else pd.NaT
        linhas.append({"situacao": situacao, "num_pedido": r["num_ped"], "prog": r["num_prog"], "cliente": r["nome_cli"],
                       "dt_emissao": emissao, "prazo_troca": prazo, "status_pedido": status, "embarque": embarque,
                       "data_otd": otd, "fim_previsto": fim, "embarque_sugerido": sugerido, "atraso_otd": atraso,
                       "motivo": motivo})
    df = pd.DataFrame(linhas, columns=COLUNAS)
    if not df.empty:
        df = df.assign(_o=df["situacao"].map(ORDEM)).sort_values(["_o", "embarque"], kind="mergesort").drop(columns="_o")
        df = df.reset_index(drop=True)
    n_troca = int((df["situacao"] == PEDIR_TROCA).sum()) if not df.empty else 0
    return df, f"{len(df)} pedidos dentro do prazo de troca (emitidos ontem ou hoje) | {n_troca} para pedir troca"
