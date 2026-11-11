"""Estoque de pallets: disponível, dias parado e slow move."""
import pandas as pd
import streamlit as st

from core import pipeline, ui

c = ui.ctx()
ui.cabecalho("Estoque", f"Slow move = pallet disponível parado há mais de {c.params['dias_slow_move']} dias "
             "(Configuração > Parâmetros).", ("estoque",))

est = ui.calcular(c.estoque)
if est is None:
    st.stop()

est = est.copy()
est["peso_liquido"] = pd.to_numeric(est["peso_liquido"], errors="coerce")
est["dias_parado"] = pd.to_numeric(est["dias_parado"], errors="coerce")
disp = est[est["tipo_estoque"] == "DISPONIVEL"]
slow = disp[disp["dias_parado"] > c.params["dias_slow_move"]]

k = st.columns(4)
k[0].metric("Estoque total", ui.kg(est["peso_liquido"].sum()))
k[1].metric("Disponível", ui.kg(disp["peso_liquido"].sum()), help=f"{ui.num(disp['qtd_pallets'].sum())} pallets")
k[2].metric("Slow move", ui.kg(slow["peso_liquido"].sum()), help=f"{ui.num(slow['qtd_pallets'].sum())} pallets")
k[3].metric("Média de dias parado", ui.num(disp["dias_parado"].mean()))

g1, g2 = st.columns(2)
with g1:
    st.markdown("**Disponível por dias parado**")
    faixas = pd.cut(disp["dias_parado"], [-1, 30, 60, 90, 180, float("inf")],
                    labels=["até 30", "31–60", "61–90", "91–180", "> 180"])
    st.bar_chart(disp.groupby(faixas, observed=False)["peso_liquido"].sum(), y_label="kg")
with g2:
    st.markdown("**Disponível por formulação (10 maiores)**")
    st.bar_chart(disp.groupby("grupo_formulacao")["peso_liquido"].sum().nlargest(10), y_label="kg", horizontal=True)

COLS = ["tipo_estoque", "site", "rua", "id_of", "id_pa", "desc_tecnica", "grupo_formulacao", "largura", "micra", "peso",
        "peso_liquido", "qtd_pallets", "pedido", "cliente", "dt_embarque", "dias_parado"]
aba1, aba2 = st.tabs(["Estoque", "Slow move"])
with aba1:
    f1, f2 = st.columns(2)
    df = ui.filtro_multi(est, "tipo_estoque", "Tipo de estoque", "est", f1)
    df = ui.filtro_multi(df, "grupo_formulacao", "Formulação", "est", f2)
    ui.tabela(df[[x for x in COLS if x in df]], "estoque", "est")
with aba2:
    ui.tabela(slow[[x for x in COLS if x in slow]].sort_values("dias_parado", ascending=False), "slow_move", "slow")

ui.conferencia_limpeza(pipeline.etapa_estoque(c.sig["estoque"])[1])
