"""Consulta de pedido: CTLR, reserva, encaixe, planejamento e troca de um pedido, mais anotações."""
import pandas as pd
import streamlit as st

from core import anotacoes, ui
from core.pipeline import FaltaRelatorio

c = ui.ctx()
ui.cabecalho("Consulta de pedido", "Digite o número do pedido para ver tudo o que o app sabe sobre ele.")

col1, col2 = st.columns([1, 3])
numero = col1.number_input("Pedido", min_value=0, step=1, value=st.session_state.get("consulta_pedido", 0))
st.session_state["consulta_pedido"] = numero
if not numero:
    abertas = anotacoes.listar(so_abertas=True)
    st.subheader("Anotações em aberto")
    if len(abertas):
        ui.tabela(abertas, "anotacoes", "anot_abertas", busca=False)
    else:
        st.caption("Nenhuma.")
    st.stop()


def _do_pedido(df: pd.DataFrame, coluna: str) -> pd.DataFrame:
    return df[pd.to_numeric(df[coluna], errors="coerce") == numero]


def _bloco(titulo: str, func, coluna: str, cols: list | None = None):
    try:
        df = func()
    except FaltaRelatorio as e:
        st.caption(f"{titulo}: sem dados ({e}).")
        return
    if isinstance(df, tuple):
        df = df[0]
    achados = _do_pedido(df, coluna)
    st.markdown(f"**{titulo}** · {len(achados)} linha(s)")
    if len(achados):
        st.dataframe(ui.arrow(achados[[x for x in cols if x in achados]] if cols else achados), hide_index=True,
                     width="stretch")


_bloco("Pedido no CTLR", c.ctlr, "num_ped",
       ["num_ped", "num_prog", "nome_cli", "desc_tec", "peso", "dt_emissao", "embarque", "data_otd", "prev_prod",
        "status_pedido", "atraso_otd", "otd_status"])
_bloco("Reserva da carteira", c.reserva, "num_pedido")
_bloco("Encaixe em máquinas", c.encaixe, "num_pedido")
_bloco("Planejamento das máquinas", lambda: c.planejamento()[0], "pedido",
       ["maquina", "id_of", "seq_prog", "produto", "qtde_of", "qtde_prod", "inicio_prev", "final_prev", "dt_otd",
        "situacao_of"])
_bloco("Troca de embarque", c.troca, "num_pedido")

st.divider()
st.subheader("Anotações")
with st.form("nova_anotacao", clear_on_submit=True):
    a1, a2 = st.columns([1, 5])
    prog = a1.number_input("Programação (opcional)", min_value=0, step=1, value=0)
    texto = a2.text_input("Anotação", placeholder="ex.: cliente aceitou adiar para sexta")
    if st.form_submit_button("Salvar anotação"):
        try:
            anotacoes.incluir(numero, prog or None, texto)
            st.toast("Anotação salva.")
        except ValueError as e:
            st.error(str(e))

notas = anotacoes.listar(numero)
for n in notas.itertuples():
    with st.container(border=True):
        t1, t2, t3 = st.columns([6, 1, 1])
        prog_txt = f" / prog {int(n.prog)}" if pd.notna(n.prog) else ""
        t1.markdown(f"{'~~' if n.resolvida else ''}{n.texto}{'~~' if n.resolvida else ''}  \n"
                    f"<small>{n.usuario}@{n.pc} · {n.criado_em}{prog_txt}</small>", unsafe_allow_html=True)
        if t2.button("Reabrir" if n.resolvida else "Resolver", key=f"r{n.id}"):
            anotacoes.marcar(n.id, not n.resolvida)
            st.rerun()
        if t3.button("Excluir", key=f"x{n.id}"):
            anotacoes.excluir(n.id)
            st.rerun()
