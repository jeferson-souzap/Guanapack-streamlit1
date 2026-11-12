"""Histórico: evolução dos indicadores (um retrato a cada "Atualizar tudo"), execuções e auditoria."""
import streamlit as st

from core import db, indicadores, ui

st.title("Histórico")
dias = st.segmented_control("Período", [7, 30, 90, 365], default=30, format_func=lambda d: f"{d} dias")

hist = indicadores.historico(dias or 30)
aba1, aba2, aba3 = st.tabs(["Indicadores", "Execuções", "Auditoria dos cadastros"])
with aba1:
    if hist.empty:
        st.info("Ainda não há retratos no período. Cada **Atualizar tudo** na Início grava um.")
    else:
        # um ponto por dia: o último retrato do dia
        diario = hist.assign(dia=hist["data_hora"].dt.date).groupby("dia").last()
        g1, g2 = st.columns(2)
        g1.markdown("**Pedidos atrasados, que vão atrasar e lead time de estoque**")
        g1.line_chart(diario[[c for c in ("atrasados", "vao_atrasar", "lead_time_estoque") if c in diario]])
        g2.markdown("**Pedidos sem estoque e novos encaixes**")
        g2.line_chart(diario[["sem_estoque", "encaixe_novos", "encaixe_atendem"]])
        g3, g4 = st.columns(2)
        g3.markdown("**Estoque disponível e slow move (kg)**")
        g3.line_chart(diario[["estoque_kg", "slow_move_kg"]])
        g4.markdown("**Tubetes com encaixe**")
        g4.line_chart(diario[["tubetes_sem_encaixe", "tubetes_com_encaixe"]])
        with st.expander("Todos os retratos"):
            ui.tabela(hist, "historico_indicadores", "hist", busca=False)
with aba2:
    ui.tabela(db.consultar_df("SELECT * FROM execucoes ORDER BY id DESC LIMIT 500"), "execucoes", "exe")
with aba3:
    ui.tabela(db.consultar_df("SELECT data_hora, usuario, pc, tabela, acao, chave, antes, depois FROM auditoria "
                              "ORDER BY id DESC LIMIT 2000"), "auditoria", "aud")
