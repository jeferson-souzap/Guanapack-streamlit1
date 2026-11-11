"""Troca de embarque: pedidos emitidos ontem/hoje cuja produção termina depois da data OTD."""
import streamlit as st

from core import ui

c = ui.ctx()
ui.cabecalho("Troca de embarque", "Pedidos ainda no prazo de troca (emitidos ontem ou hoje).",
             ("ctlr", "solicitacoes", "planejamento"))

tr = ui.calcular(c.troca)
if tr is None:
    st.stop()
tabela, resumo = tr
st.info(resumo)
if tabela.empty:
    st.stop()

pedir = tabela[tabela["situacao"] == "PEDIR TROCA"]
k = st.columns(3)
k[0].metric("No prazo de troca", ui.num(len(tabela)))
k[1].metric("Pedir troca", ui.num(len(pedir)))
k[2].metric("Conferir", ui.num((tabela["situacao"] == "CONFERIR").sum()))

if len(pedir):
    st.subheader("Pedir troca")
    ui.tabela(pedir, "pedir_troca", "pedir", busca=False)
    texto = "\n".join(f"Pedido {r.num_pedido}/{r.prog} ({r.cliente}): embarque {r.embarque} → sugerido "
                      f"{r.embarque_sugerido}. {r.motivo}" for r in pedir.itertuples())
    with st.expander("Texto para enviar ao comercial"):
        st.code(texto, language=None)

st.subheader("Todos no prazo de troca")
df = ui.filtro_multi(tabela, "situacao", "Situação", "troca")
ui.tabela(df, "troca_embarque", "troca")
