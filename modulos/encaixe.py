"""Encaixe em máquinas: onde produzir os pedidos sem estoque, sem empurrar quem já está no prazo."""
import pandas as pd
import streamlit as st

from core import ui

c = ui.ctx()
ui.cabecalho("Encaixe em máquinas",
             f"As {c.params['ordens_fixas']} primeiras OFs de cada máquina ficam fixas. "
             "O pedido novo não quebra a sequência de formulação da máquina (só entra entre OFs cujo rank "
             "comporta o dele; no fim da fila sempre pode), mesmo que fique atrasado. "
             "Regras das máquinas e rank das formulações em Cadastros.", ("carteira", "estoque", "solicitacoes", "planejamento"))

enc = ui.calcular(c.encaixe)
if enc is None:
    st.stop()
pedidos, filas, resumo = enc
st.info(resumo)

novos = pedidos["sugestao"] == "NOVO NA MÁQUINA"
k = st.columns(4)
k[0].metric("Novos na máquina", ui.num(novos.sum()),
            help=f"{ui.num((novos & (pedidos['atende_embarque'] == 'SIM')).sum())} atendem o embarque")
k[1].metric("Por OF de estoque", ui.num((pedidos["sugestao"] == "OF DE ESTOQUE").sum()))
k[2].metric("Sem máquina", ui.num((pedidos["sugestao"] == "SEM MÁQUINA").sum()))
k[3].metric("OFs que passam a atrasar", ui.num((filas["atraso"] == "PASSA A ATRASAR").sum()))

aba1, aba2, aba3 = st.tabs(["Pedidos sem estoque", "Fila sugerida por máquina", "Gráfico"])
with aba1:
    f1, f2 = st.columns(2)
    df = ui.filtro_multi(pedidos, "sugestao", "Sugestão", "enc", f1)
    df = ui.filtro_multi(df, "maquina", "Máquina", "enc", f2)
    ui.tabela(df, "encaixe_pedidos", "enc_ped")
with aba2:
    maquinas = sorted(filas["maquina"].dropna().unique())
    maq = st.selectbox("Máquina", maquinas) if maquinas else None
    if maq:
        fila = filas[filas["maquina"] == maq]
        st.caption(f"{len(fila)} OFs · {(fila['situacao'] == 'NOVO').sum()} novas · "
                   f"{(fila['atraso'] == 'PASSA A ATRASAR').sum()} passam a atrasar")
        ui.tabela(fila, f"fila_{maq[:20]}", "enc_fila", busca=False)
    with st.expander("Todas as filas"):
        ui.tabela(filas, "encaixe_filas", "enc_filas")
with aba3:
    g = filas.copy()
    g["inicio"] = pd.to_datetime(g["inicio_sugerido"], errors="coerce")
    g["fim"] = pd.to_datetime(g["fim_sugerido"], errors="coerce")
    g = g.dropna(subset=["inicio", "fim"])
    if g.empty:
        st.caption("Sem datas para desenhar.")
    else:
        import plotly.express as px
        g["rotulo"] = g.apply(lambda r: f"{r['pedido']}/{r['prog']}" if r["situacao"] == "NOVO" else f"OF {r['id_of']}",
                              axis=1)
        fig = px.timeline(g, x_start="inicio", x_end="fim", y="maquina", color="situacao", hover_name="rotulo",
                          hover_data=["cliente", "produto", "qtde_kg", "atraso"])
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_layout(height=120 + 45 * g["maquina"].nunique(), margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")
