"""Tubetes e pallets: consumo das OFs abertas, sem e com os novos encaixes."""
import streamlit as st

from core import ui

c = ui.ctx()
ui.cabecalho("Tubetes e pallets", "Consumo das OFs abertas no planejamento + o que os encaixes novos acrescentam.",
             ("planejamento", "carteira"))

ins = ui.calcular(c.insumos)
if ins is None:
    st.stop()
tubetes, pallets, detalhe, resumo = ins
st.info(resumo)
if c.chave_encaixe is None:
    st.caption("Sem encaixe calculado (faltam relatórios ou cadastros): a coluna “com encaixe” repete o “sem encaixe”.")

k = st.columns(4)
k[0].metric("Tubetes sem encaixe", ui.num(tubetes["sem_encaixe"].sum()))
k[1].metric("Tubetes com encaixe", ui.num(tubetes["com_encaixe"].sum()))
k[2].metric("Pallets sem encaixe", ui.num(pallets["sem_encaixe"].sum()))
k[3].metric("Pallets com encaixe", ui.num(pallets["com_encaixe"].sum()))

aba1, aba2, aba3 = st.tabs(["Tubetes", "Pallets", "Detalhe por OF"])
with aba1:
    ui.tabela(tubetes, "tubetes", "tub", busca=False)
with aba2:
    ui.tabela(pallets, "pallets", "pal", busca=False)
with aba3:
    df = ui.filtro_multi(detalhe, "origem", "Origem", "det")
    ui.tabela(df, "insumos_detalhe", "det")
