"""
Peças de tela usadas por todos os módulos: contexto da execução, cabeçalho, avisos de relatório,
tabela com filtro e download em Excel.
"""
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from core import pipeline
from core.pipeline import FaltaRelatorio

ICONE_SITUACAO = {"OK": ":green-badge[OK]", "AVISO": ":orange-badge[Aviso]", "ERRO": ":red-badge[Erro]"}


def ctx() -> pipeline.Contexto:
    """Contexto da execução atual (montado uma vez por recarga da página, em app.py)."""
    if "_ctx" not in st.session_state or st.session_state.get("_ctx_run") != st.session_state.get("_run"):
        st.session_state["_ctx"] = pipeline.montar_contexto()
        st.session_state["_ctx_run"] = st.session_state.get("_run")
    return st.session_state["_ctx"]


def cabecalho(titulo: str, descricao: str = "", relatorios: tuple = ()):
    st.title(titulo)
    if descricao:
        st.caption(descricao)
    c = ctx()
    for chave in relatorios:
        s = c.situacao[chave]
        if s["situacao"] == "ERRO":
            st.error(f"**{s['titulo']}** ({s['arquivo']}): {s['mensagem']}.  \nPasta: `{c.pasta}`")
        elif s["situacao"] == "AVISO":
            st.warning(f"**{s['titulo']}**: {s['mensagem']}.")


def calcular(func, *args):
    """Roda uma etapa do cálculo mostrando o motivo na tela quando falta algo. Devolve None se falhar."""
    try:
        return func(*args)
    except FaltaRelatorio as e:
        st.info(f"Não dá para calcular agora: {e}. Confira a pasta em **Configuração**.")
    except Exception as e:  # erro de regra: mostra sem derrubar o app
        st.error(f"Erro no cálculo: {e}")
        with st.expander("Detalhes técnicos"):
            st.exception(e)
    return None


def kg(valor) -> str:
    try:
        return f"{float(valor):,.0f} kg".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def num(valor) -> str:
    try:
        return f"{float(valor):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def excel(df: pd.DataFrame, aba: str = "dados") -> bytes:
    saida = io.BytesIO()
    copia = df.copy()
    for col in copia.columns:  # o Excel não aceita data com fuso
        if isinstance(copia[col].dtype, pd.DatetimeTZDtype):
            copia[col] = copia[col].dt.tz_localize(None)
    with pd.ExcelWriter(saida, engine="openpyxl") as w:
        copia.to_excel(w, sheet_name=aba[:31], index=False)
    return saida.getvalue()


def arrow(df: pd.DataFrame) -> pd.DataFrame:
    """Coluna com tipos misturados (número e texto) vira texto, para a tabela da tela não reclamar."""
    misturadas = [c for c in df.columns if df[c].dtype == object
                  and df[c].dropna().map(type).nunique() > 1]
    if not misturadas:
        return df
    return df.assign(**{c: df[c].map(lambda v: v if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
                        for c in misturadas})


def tabela(df: pd.DataFrame, nome: str, chave: str, busca: bool = True, altura: int | None = None,
           colunas: dict | None = None):
    """Tabela com busca por texto (qualquer coluna) e botão para baixar em Excel."""
    if df is None or df.empty:
        st.caption("Nada para mostrar.")
        return df
    mostrado = df
    if busca:
        texto = st.text_input("Buscar", key=f"busca_{chave}", placeholder="pedido, cliente, produto…",
                              label_visibility="collapsed")
        if texto.strip():
            termo = texto.strip().lower()
            mascara = mostrado.astype(str).apply(lambda s: s.str.lower().str.contains(termo, regex=False)).any(axis=1)
            mostrado = mostrado[mascara]
    st.dataframe(arrow(mostrado), width="stretch", hide_index=True, height=altura or "auto", column_config=colunas)
    c1, c2 = st.columns([1, 4])
    c1.download_button("Excel", lambda: excel(mostrado, nome), file_name=f"{nome}_{datetime.now():%Y%m%d_%H%M}.xlsx",
                       key=f"xls_{chave}", width="stretch")
    c2.caption(f"{len(mostrado)} de {len(df)} linhas")
    return mostrado


def filtro_multi(df: pd.DataFrame, coluna: str, rotulo: str, chave: str, container=st) -> pd.DataFrame:
    if coluna not in df:
        return df
    opcoes = sorted(df[coluna].dropna().astype(str).unique())
    escolhidos = container.multiselect(rotulo, opcoes, key=f"f_{chave}_{coluna}")
    return df[df[coluna].astype(str).isin(escolhidos)] if escolhidos else df


def conferencia_limpeza(conf: dict):
    """Mostra a conferência original x limpo (linhas e totais) de um relatório."""
    if not conf:
        return
    icone = ":green-badge[OK]" if conf.get("ok") else ":orange-badge[Conferir]"
    with st.expander(f"{icone} Conferência da limpeza: {conf.get('linhas', '')}"):
        st.dataframe(pd.DataFrame(conf.get("totais", [])), hide_index=True, width="stretch")
        for p in conf.get("problemas", []):
            st.warning(p)
