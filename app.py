"""
Guanapack PCP — app Streamlit.

    streamlit run app.py        (ou dê dois cliques em iniciar.bat)

Os relatórios do ERP são lidos direto da pasta; o banco SQLite (dados/) guarda cadastros,
locais por usuário/PC, parâmetros, histórico, anotações e auditoria.
"""
import streamlit as st

import core  # noqa: F401  (ajusta o pandas antes de tudo)
from core import contexto, db, pipeline, ui, versao
from modulos import MODULOS

st.set_page_config(page_title="Guanapack PCP", layout="wide")


@st.cache_resource(show_spinner=False)
def _iniciar_banco():
    db.inicializar()
    try:
        db.backup_diario()
    except OSError:
        pass
    return True


@st.cache_resource(show_spinner=False)
def _versao():
    return versao.ler()


_iniciar_banco()
st.session_state["_run"] = st.session_state.get("_run", 0) + 1

# ------------------------------------------------------------------ navegação por módulos
estado = contexto.modulos_estado()


def _ativo(m) -> bool:
    return m.fixo or bool(estado.get(m.id, {}).get("ativo", 1))


def _ordem(m) -> int:
    o = estado.get(m.id, {}).get("ordem")
    return o if o is not None else MODULOS.index(m)


paginas: dict[str, list] = {}
for m in sorted([m for m in MODULOS if _ativo(m)], key=_ordem):
    paginas.setdefault(m.grupo, []).append(
        st.Page(m.arquivo, title=m.titulo, icon=m.icone, url_path=m.id, default=(m.id == "inicio")))

navegacao = st.navigation(paginas)

# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    c = ui.ctx()
    st.caption(f"{contexto.usuario()} @ {contexto.pc()}")
    with st.expander("Relatórios", expanded=any(s["situacao"] == "ERRO" for s in c.situacao.values())):
        st.caption(f"`{c.pasta}`  \n({c.origem_pasta})")
        for s in c.situacao.values():
            st.markdown(f"{ui.ICONE_SITUACAO[s['situacao']]} **{s['titulo']}**  \n"
                        f"<small>{s['mensagem']}</small>", unsafe_allow_html=True)
        if contexto.usando_enviados():
            st.page_link("modulos/enviar.py", label="Enviar relatórios", icon=":material/upload:")
    if st.button("Reler relatórios", width="stretch",
                 help="Apaga o cache e lê de novo os arquivos da pasta (use se trocou um relatório com o mesmo horário)"):
        pipeline.limpar_cache()
        st.rerun()
    v = _versao()
    st.divider()
    st.caption(f"{v.texto}  \n{v.mensagem}  \napp iniciado em {v.iniciado_em:%d/%m/%Y %H:%M} (Brasília)",
               help="Commit do git em uso. Muda a cada deploy novo; 'alterações locais' = há mudanças "
                    "neste computador ainda não commitadas.")

navegacao.run()
