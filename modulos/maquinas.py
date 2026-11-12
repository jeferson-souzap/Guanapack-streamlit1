"""Planejamento das máquinas: cada OF com a situação da reserva do mesmo pedido."""
import pandas as pd
import streamlit as st

from core import ui

c = ui.ctx()
ui.cabecalho("Planejamento das máquinas",
             "OFs de extrusão de stretch (Davis, SML 1 e Power, mais as não programadas de stretch) cruzadas com a "
             "reserva da carteira.", ("planejamento",))

plan = ui.calcular(c.maquinas_reserva)
if plan is None:
    st.stop()
nao_prog = plan["situacao_of"] == "NÃO PROGRAMADA"

k = st.columns(4)
k[0].metric("OFs de stretch", ui.num(len(plan)))
k[1].metric("Nas máquinas", ui.num((~nao_prog).sum()))
k[2].metric("Não programadas", ui.num(nao_prog.sum()))
k[3].metric("Saldo a produzir", ui.kg(pd.to_numeric(plan.get("saldo_kg"), errors="coerce").sum()))

f1, f2 = st.columns(2)
df = ui.filtro_multi(plan, "maquina", "Máquina", "maq", f1)
df = ui.filtro_multi(df, "situacao_of", "Situação da OF", "maq", f2)
COLS = ["maquina", "tipo_of", "id_of", "firmado", "pedido", "seq_prog", "cliente", "id_pa", "produto", "formulacao",
        "qtde_of", "qtde_prod", "saldo_kg", "inicio_prev", "final_prev", "dt_otd", "situacao_of", "tem_estoque",
        "atendimento", "alternativo_usado", "peso_reservado"]
ui.tabela(df[[x for x in COLS if x in df]], "planejamento", "maq")

with st.expander("Saldo por máquina"):
    s = plan.assign(kg=pd.to_numeric(plan["saldo_kg"], errors="coerce"))
    st.bar_chart(s.groupby("maquina")["kg"].sum(), y_label="kg", horizontal=True)
