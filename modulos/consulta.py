"""Consulta de pedido: tudo o que o app sabe de um pedido (CTLR, estoque, reserva, encaixe, planejamento
e a simulação em edição) numa tela só."""
import pandas as pd
import streamlit as st

from core import ui
from core.pipeline import FaltaRelatorio

c = ui.ctx()
ui.cabecalho("Consulta de pedido", "Digite o número do pedido para ver tudo o que o app sabe sobre ele.")

col1, _ = st.columns([1, 3])
numero = col1.number_input("Pedido", min_value=0, step=1, value=st.session_state.get("consulta_pedido", 0))
st.session_state["consulta_pedido"] = numero
if not numero:
    st.caption("Mostra o pedido no CTLR (data OTD e situação), os pallets do estoque ligados a ele, a reserva, "
               "a sugestão do encaixe, a fila sugerida, o planejamento das máquinas e a simulação em edição.")
    st.stop()


def _do_pedido(df: pd.DataFrame, coluna: str) -> pd.DataFrame:
    return df[pd.to_numeric(df[coluna], errors="coerce") == numero]


def _bloco(titulo: str, func, coluna: str, cols: list | None = None):
    try:
        df = func()
    except FaltaRelatorio as e:
        st.caption(f"{titulo}: sem dados ({e}).")
        return
    if df is None or coluna not in df:
        st.caption(f"{titulo}: sem dados.")
        return
    achados = _do_pedido(df, coluna)
    st.markdown(f"**{titulo}** · {len(achados)} linha(s)")
    if len(achados):
        st.dataframe(ui.arrow(achados[[x for x in cols if x in achados]] if cols else achados), hide_index=True,
                     width="stretch")


_bloco("Pedido no CTLR", c.ctlr, "num_ped",
       ["num_ped", "num_prog", "nome_cli", "desc_tec", "peso", "dt_emissao", "embarque", "data_otd", "prev_prod",
        "status_pedido", "atraso_otd", "otd_status"])
_bloco("Pallets do estoque ligados ao pedido", c.estoque, "pedido")
_bloco("Reserva de estoque", c.reserva, "num_pedido")
_bloco("Encaixe em máquinas (sugestão)", lambda: c.encaixe()[0], "num_pedido")
_bloco("Fila sugerida pelo encaixe", lambda: c.encaixe()[1], "pedido")
_bloco("Planejamento das máquinas", lambda: c.planejamento()[0], "pedido",
       ["maquina", "id_of", "firmado", "seq_prog", "produto", "grupo_form", "qtde_of", "qtde_prod", "inicio_prev",
        "final_prev", "dt_otd", "situacao_of"])

cen = st.session_state.get("sim_cen")
if cen is not None and not cen.itens.empty:
    nome = st.session_state.get("sim_nome") or "cenário em edição (não salvo)"
    _bloco(f"Simulação da programação ({nome})", lambda: cen.itens, "pedido",
           ["maquina", "ordem", "situacao", "chave", "cliente", "produto", "grupo_formulacao", "micra", "qtde_kg",
            "inicio", "fim", "data_otd", "atraso", "salto_micra", "alerta"])
else:
    st.caption("Simulação da programação: nenhum cenário aberto nesta sessão.")
