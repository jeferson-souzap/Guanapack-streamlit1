"""Reserva da carteira: qual pallet do estoque reservar para cada pedido (exato ou alternativo)."""
import streamlit as st

from core import ui

c = ui.ctx()
p = c.params
ui.cabecalho("Reserva da carteira",
             f"Tolerância de quantidade ±{p['tolerancia_qtd']:.0%} · micra ±{p['tolerancia_micra']:g} · "
             f"alternativo sobe até {p['max_degraus_formulacao']} degrau(s) no rank de formulação. "
             "Clientes prioritários são atendidos primeiro.", ("carteira", "estoque", "solicitacoes"))

res = ui.calcular(c.reserva)
if res is None:
    st.stop()

com = res["tem_estoque"] == "SIM"
k = st.columns(4)
k[0].metric("Pedidos na carteira", ui.num(len(res)))
k[1].metric("Com estoque", ui.num(com.sum()), help=ui.kg(res.loc[com, "peso_reservado"].sum()))
k[2].metric("Por alternativo", ui.num((res["atendimento"] == "ALTERNATIVO").sum()))
k[3].metric("Sem estoque", ui.num((~com).sum()), help="vão para o Encaixe em máquinas")

aba1, aba2, aba3 = st.tabs(["Reservar", "Sem estoque", "Todos"])
with aba1:
    ui.tabela(res[com], "reserva", "res_sim", colunas={
        "pallets_reservados": st.column_config.TextColumn("pallets reservados", width="large")})
with aba2:
    sem = res[~com]
    if "motivo_sem_estoque" in sem:
        st.bar_chart(sem["motivo_sem_estoque"].fillna("—").value_counts(), horizontal=True)
    ui.tabela(sem, "sem_estoque", "res_nao")
with aba3:
    df = ui.filtro_multi(res, "tipo_venda", "Tipo de venda", "res")
    ui.tabela(df, "carteira_reserva", "res_todos")
