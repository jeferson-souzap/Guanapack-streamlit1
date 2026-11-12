"""Pedidos e OTD: atraso pela data OTD (embarque − N dias; exportação usa a data do planejamento)."""
import pandas as pd
import streamlit as st

from core import ui
from core.regras.LimpezaCtlrPedidos import STATUS_EM_ABERTO

c = ui.ctx()
ui.cabecalho("Pedidos e OTD", f"Data OTD = embarque − {c.params['dias_otd']} dias. "
             "Exportação usa a data OTD do planejamento.", ("ctlr", "solicitacoes", "planejamento"))

ctlr = ui.calcular(c.ctlr)
if ctlr is None:
    st.stop()

aberto = ctlr[ctlr["status_pedido"].isin(STATUS_EM_ABERTO)]
lead = ctlr[ctlr["lead_time_estoque"].notna()]
k = st.columns(5)
k[0].metric("Em aberto", ui.num(len(aberto)), help=ui.kg(pd.to_numeric(aberto["peso"], errors="coerce").sum()))
k[1].metric("Atrasados (OTD)", ui.num((ctlr["atraso_otd"] == "ATRASADO").sum()))
k[2].metric("Vão atrasar", ui.num((ctlr["atraso_otd"] == "VAI ATRASAR").sum()))
entregues = ctlr[ctlr["status_pedido"].isin(["FATURADO", "ENTREGUE"]) & ctlr["otd_status"].notna()]
if len(entregues):
    k[3].metric("OTD dos faturados", f"{(entregues['otd_status'] == 'NO PRAZO').mean():.0%}",
                help=f"{len(entregues)} pedidos faturados/entregues")
k[4].metric("Lead time estoque", ui.num(len(lead)), help="em aberto com embarque no dia da emissão ou no seguinte · "
            + ui.kg(pd.to_numeric(lead["peso"], errors="coerce").sum()))

COLS = ["num_ped", "num_prog", "nome_cli", "familia", "desc_tec", "peso", "embarque", "data_otd", "prev_prod",
        "status_pedido", "atraso_otd"]

aba1, aba2, aba_lead, aba3 = st.tabs(["Atrasados", "Vão atrasar", "Lead time estoque", "Todos"])
with aba1:
    ui.tabela(ctlr[ctlr["atraso_otd"] == "ATRASADO"][COLS].sort_values(["embarque", "num_ped"]), "atrasados", "atr")
with aba2:
    ui.tabela(ctlr[ctlr["atraso_otd"] == "VAI ATRASAR"][COLS].sort_values(["embarque", "num_ped"]), "vao_atrasar", "vai")
with aba_lead:
    cols_lead = COLS[:6] + ["dt_emissao"] + COLS[6:]          # emissão ao lado do embarque
    ui.tabela(lead[[col for col in cols_lead if col in lead]].sort_values(["embarque", "num_ped"]),
              "lead_time_estoque", "lead")
with aba3:
    f1, f2 = st.columns(2)
    df = ui.filtro_multi(ctlr, "status_pedido", "Status", "ped", f1)
    df = ui.filtro_multi(df, "familia", "Família", "ped", f2)
    ui.tabela(df[[col for col in COLS if col in df] + ["otd_status", "lead_time_estoque"]], "pedidos", "todos")

with st.expander("Pedidos em aberto por mês de embarque"):
    a = aberto.assign(mes=pd.to_datetime(aberto["embarque"], errors="coerce").dt.strftime("%Y-%m"),
                      kg=pd.to_numeric(aberto["peso"], errors="coerce"))
    st.bar_chart(a.groupby("mes")["kg"].sum(), y_label="kg")

ui.conferencia_limpeza(c.planejamento()[2] if c.ok("planejamento") else None)
