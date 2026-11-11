"""Enviar relatórios: sobe os .xls do ERP pelo navegador (para quando o app roda fora da rede, ex.: na nuvem)."""
import streamlit as st

import config
from core import contexto, pipeline, relatorios, ui

st.title("Enviar relatórios")
st.caption("Arraste os relatórios do ERP aqui. O app reconhece cada um pelo nome do arquivo ou, se o nome for "
           "diferente, pelas colunas. Enviar de novo troca o anterior.")

pasta, origem = contexto.pasta_relatorios()
if contexto.usando_enviados():
    st.info(f"O app está lendo os **relatórios enviados por aqui** ({origem}).")
else:
    st.warning(f"Neste computador o app lê os relatórios da pasta `{pasta}` ({origem}). "
               f"Os arquivos enviados aqui ficam guardados, mas só são usados quando essa pasta não existe "
               f"(ex.: no app na nuvem).")

if "_envio_n" not in st.session_state:
    st.session_state["_envio_n"] = 0

enviados = st.file_uploader("Relatórios (.xls / .xlsx)", type=["xls", "xlsx"], accept_multiple_files=True,
                            key=f"envio_{st.session_state['_envio_n']}")

if enviados:
    lidos = []
    for f in enviados:
        conteudo = f.getvalue()
        chave = relatorios.identificar(f.name, conteudo)
        lidos.append((f.name, chave, conteudo))
    for nome, chave, _ in lidos:
        if chave:
            st.markdown(f":green-badge[OK] `{nome}` → **{config.RELATORIOS[chave].titulo}**")
        else:
            st.markdown(f":red-badge[Erro] `{nome}`: não reconheci este relatório (nome e colunas não batem "
                        f"com nenhum dos esperados). Ele não será salvo.")
    repetidos = {c for _, c, _ in lidos if c and sum(1 for _, x, _ in lidos if x == c) > 1}
    if repetidos:
        st.warning("Mais de um arquivo para: " + ", ".join(config.RELATORIOS[c].titulo for c in repetidos)
                   + ". Fica o último da lista.")
    validos = [(c, b) for _, c, b in lidos if c]
    if validos and st.button(f"Salvar {len({c for c, _ in validos})} relatório(s)", type="primary"):
        for chave, conteudo in validos:
            relatorios.salvar_enviado(chave, conteudo)
        pipeline.limpar_cache()
        st.session_state["_envio_n"] += 1  # limpa a caixa de envio
        st.success("Relatórios salvos.")
        st.rerun()

st.subheader("Relatórios enviados")
tol = int(contexto.parametros()["dias_tolerancia_relatorio"])
situacao = relatorios.conferir_todos(pasta=config.PASTA_ENVIADOS, tolerancia_dias=tol)
for chave, s in situacao.items():
    c1, c2 = st.columns([6, 1])
    c1.markdown(f"{ui.ICONE_SITUACAO[s['situacao']]} **{s['titulo']}** (`{s['arquivo']}`)  \n"
                f"<small>{s['mensagem']}</small>", unsafe_allow_html=True)
    if s.get("salvo_em") and c2.button("Apagar", key=f"apagar_{chave}"):
        relatorios.apagar_enviado(chave)
        pipeline.limpar_cache()
        st.rerun()
st.caption("No app na nuvem os arquivos enviados podem sumir quando o app reinicia; aí é só enviar de novo.")
