"""Cadastros no banco: rank de formulações, clientes prioritários e regras das máquinas."""
import pandas as pd
import streamlit as st

from core import cadastros, ui

st.title("Cadastros")
st.caption("Edite como planilha (inclua linhas no fim, apague selecionando a linha e pressionando Delete) "
           "e clique em **Salvar**. Toda alteração fica na auditoria com o usuário e o PC.")


def _salvar(func, df: pd.DataFrame, nome: str):
    try:
        cont = func(df)
    except ValueError as e:
        st.error(f"Nada foi salvo. Corrija: {e}")
        return
    if sum(cont.values()):
        st.success(f"{nome} salvo: " + ", ".join(f"{v} {k}" for k, v in cont.items() if v))
        st.rerun()
    else:
        st.info("Nenhuma alteração.")


SO_LEITURA = ["atualizado_em", "atualizado_por"]
aba1, aba2, aba3 = st.tabs(["Rank de formulações", "Clientes prioritários", "Máquinas"])

with aba1:
    st.caption("Rank menor = formulação mais simples. Na reserva, o alternativo pode usar formulação de rank maior "
               "(até o limite de degraus em Configuração).")
    df = cadastros.formulacoes_df()
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="ed_form", disabled=SO_LEITURA,
                        column_config={"formulacao": st.column_config.TextColumn("formulação", required=True),
                                       "rank": st.column_config.NumberColumn("rank", min_value=0, step=1, required=True)})
    if st.button("Salvar formulações", type="primary"):
        _salvar(cadastros.salvar_formulacoes, ed, "Rank de formulações")

with aba2:
    st.caption("Clientes que não podem atrasar: vão primeiro na reserva e no encaixe. O cliente é parte do nome "
               "(ex.: “Lactalis”); material e formulação são opcionais e restringem a regra.")
    df = cadastros.prioritarios_df()
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="ed_prior",
                        disabled=["id", *SO_LEITURA],
                        column_config={"id": None, "ativo": st.column_config.CheckboxColumn("ativo", default=True),
                                       "cliente": st.column_config.TextColumn("cliente (parte do nome)", required=True)})
    if st.button("Salvar clientes prioritários", type="primary"):
        _salvar(cadastros.salvar_prioritarios, ed, "Clientes prioritários")

with aba3:
    st.caption("Nome da máquina igual ao do planejamento. Formulações e “não roda” separados por vírgula. "
               "Faixas: micra (µ), peso da bobina (kg), tubete (kg) e largura (mm).")
    df = cadastros.maquinas_df()
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="ed_maq", disabled=SO_LEITURA,
                        column_config={"ativa": st.column_config.CheckboxColumn("ativa", default=True),
                                       "maquina": st.column_config.TextColumn("máquina", required=True, width="large")})
    if st.button("Salvar máquinas", type="primary"):
        _salvar(cadastros.salvar_maquinas, ed, "Máquinas")

st.divider()
c1, c2, c3 = st.columns(3)
c1.download_button("Formulações (Excel)", lambda: ui.excel(cadastros.formulacoes_df(), "formulacoes"), "formulacoes.xlsx")
c2.download_button("Prioritários (Excel)", lambda: ui.excel(cadastros.prioritarios_df(), "prioritarios"), "prioritarios.xlsx")
c3.download_button("Máquinas (Excel)", lambda: ui.excel(cadastros.maquinas_df(), "maquinas"), "maquinas.xlsx")
