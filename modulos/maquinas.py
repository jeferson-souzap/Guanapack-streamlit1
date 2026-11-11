"""Planejamento das máquinas: cada OF com a situação da reserva do mesmo pedido."""
import pandas as pd
import streamlit as st

from core import ui

c = ui.ctx()
ui.cabecalho("Planejamento das máquinas", "OFs do planejamento cruzadas com a reserva da carteira.",
             ("planejamento",))

plan = ui.calcular(c.maquinas_reserva)
if plan is None:
    st.stop()
stretch = c.planejamento()[1]

k = st.columns(4)
k[0].metric("OFs no planejamento", ui.num(len(plan)))
k[1].metric("OFs de extrusão stretch", ui.num(len(stretch)))
k[2].metric("Saldo a produzir", ui.kg(pd.to_numeric(stretch.get("saldo_kg"), errors="coerce").sum()))
k[3].metric("Máquinas", ui.num(stretch["maquina"].nunique()))

f1, f2 = st.columns(2)
df = ui.filtro_multi(plan, "maquina", "Máquina", "maq", f1)
df = ui.filtro_multi(df, "tipo_of", "Tipo de OF", "maq", f2)
COLS = ["maquina", "tipo_of", "id_of", "firmado", "pedido", "seq_prog", "cliente", "id_pa", "produto", "formulacao",
        "qtde_of", "qtde_prod", "saldo_kg", "inicio_prev", "final_prev", "dt_otd", "situacao_of", "tem_estoque",
        "atendimento", "alternativo_usado", "peso_reservado"]
ui.tabela(df[[x for x in COLS if x in df]], "planejamento", "maq")

with st.expander("Saldo por máquina"):
    s = stretch.assign(kg=pd.to_numeric(stretch["saldo_kg"], errors="coerce"))
    st.bar_chart(s.groupby("maquina")["kg"].sum(), y_label="kg", horizontal=True)
