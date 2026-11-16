"""Início: situação dos relatórios e atalhos para a simulação da programação e o encaixe."""
from datetime import datetime

import streamlit as st

from core import contexto, ui

c = ui.ctx()
hora = datetime.now().hour
saudacao = "Bom dia" if hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
st.title(f"{saudacao}, {contexto.usuario().split('.')[0].title()}")
st.caption(f"Guanapack PCP · programação das máquinas · {datetime.now():%d/%m/%Y} · relatórios em `{c.pasta}`")

# ------------------------------------------------------------------ relatórios
colunas = st.columns(len(c.situacao))
for col, s in zip(colunas, c.situacao.values()):
    with col.container(border=True):
        st.markdown(f"{ui.ICONE_SITUACAO[s['situacao']]} **{s['titulo']}**")
        st.caption(s["mensagem"])

erros_rel = [s for s in c.situacao.values() if s["situacao"] == "ERRO"]
if erros_rel:
    st.warning(f"{len(erros_rel)} relatório(s) com problema. A simulação e o encaixe precisam de todos eles. "
               "Salve os relatórios na pasta ou ajuste o local em **Configuração**.")

# ------------------------------------------------------------------ atalhos
st.subheader("Montar a programação")
a, b = st.columns(2)
with a.container(border=True):
    st.page_link("modulos/simulacao.py", label="**Simulação da programação**", icon=":material/tune:")
    st.caption("Escolha as regras, gere a sugestão de fila, mexa à mão (posição e máquina), trave OFs e "
               "compare cenários salvos.")
with b.container(border=True):
    st.page_link("modulos/encaixe.py", label="**Encaixe em máquinas**", icon=":material/view_timeline:")
    st.caption("Onde produzir os pedidos sem estoque, a fila sugerida de cada máquina e o gráfico de Gantt.")
st.caption("Regras das máquinas e rank das formulações em **Cadastros**; pasta e parâmetros em **Configuração**.")
