"""Início: situação dos relatórios, botão de atualizar e o resumo do dia."""
from datetime import datetime

import streamlit as st

from core import contexto, db, indicadores, pipeline, ui
from modulos import MODULOS

c = ui.ctx()
hora = datetime.now().hour
saudacao = "Bom dia" if hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
st.title(f"{saudacao}, {contexto.usuario().split('.')[0].title()}")
st.caption(f"Guanapack PCP · {datetime.now():%d/%m/%Y} · relatórios em `{c.pasta}`")

# ------------------------------------------------------------------ relatórios
colunas = st.columns(len(c.situacao))
for col, s in zip(colunas, c.situacao.values()):
    with col.container(border=True):
        st.markdown(f"{ui.ICONE_SITUACAO[s['situacao']]} **{s['titulo']}**")
        st.caption(s["mensagem"])

erros_rel = [s for s in c.situacao.values() if s["situacao"] == "ERRO"]
if erros_rel:
    st.warning(f"{len(erros_rel)} relatório(s) com problema. Os módulos que dependem deles ficam sem cálculo. "
               "Salve os relatórios na pasta ou ajuste o local em **Configuração**.")

esq, dir_ = st.columns([1, 3])
if esq.button("Atualizar tudo", type="primary", width="stretch",
              help="Calcula pedidos, reserva, encaixe, insumos e troca (o que não mudou vem do cache) "
                   "e grava um retrato dos indicadores no histórico"):
    with st.spinner("Calculando…"):
        erros, duracao = pipeline.atualizar_tudo(c)
        ind = indicadores.calcular(c)
        indicadores.gravar(ind, duracao, erros)
        db.registrar_execucao("atualizar tudo", contexto.usuario(), contexto.pc(), duracao,
                              "ok" if not erros else str(erros))
    st.session_state["_indicadores"] = ind
    if erros:
        dir_.warning("Concluído com pendências: " + " · ".join(f"**{k}** {v}" for k, v in erros.items()))
    else:
        dir_.success(f"Tudo atualizado em {duracao:.0f} s.")

# ------------------------------------------------------------------ resumo
ind = st.session_state.get("_indicadores")
if ind is None:
    ultimo = db.consultar("SELECT * FROM historico_indicadores ORDER BY id DESC LIMIT 1")
    if ultimo:
        ind = ultimo[0]
        st.caption(f"Resumo da última atualização ({ind['data_hora']}, por {ind['usuario']}). "
                   "Clique em **Atualizar tudo** para recalcular com os relatórios de agora.")

if ind:
    st.subheader("Resumo")
    linha1 = st.columns(4)
    linha1[0].metric("Pedidos atrasados (OTD)", ui.num(ind.get("atrasados")))
    linha1[1].metric("Vão atrasar", ui.num(ind.get("vao_atrasar")))
    linha1[2].metric("Pedidos sem estoque", ui.num(ind.get("sem_estoque")),
                     help=f"de {ui.num(ind.get('pedidos_reserva'))} pedidos na carteira")
    linha1[3].metric("Pedir troca de embarque", ui.num(ind.get("troca_pedir")))
    linha2 = st.columns(4)
    linha2[0].metric("Novos encaixes", ui.num(ind.get("encaixe_novos")),
                     help=f"{ui.num(ind.get('encaixe_atendem'))} atendem o embarque")
    linha2[1].metric("OFs que passam a atrasar", ui.num(ind.get("ofs_passam_atrasar")))
    linha2[2].metric("Estoque disponível", ui.kg(ind.get("estoque_kg")))
    linha2[3].metric("Slow move", ui.kg(ind.get("slow_move_kg")))
else:
    st.info("Clique em **Atualizar tudo** para ver o resumo do dia.")

# ------------------------------------------------------------------ atalhos
st.subheader("Módulos")
estado = contexto.modulos_estado()
ativos = [m for m in MODULOS if m.id != "inicio" and (m.fixo or estado.get(m.id, {}).get("ativo", 1))]
grade = st.columns(4)
for i, m in enumerate(ativos):
    with grade[i % 4]:
        st.page_link(m.arquivo, label=m.titulo, icon=m.icone, help=m.descricao)
