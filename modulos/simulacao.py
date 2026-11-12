"""Simulação da programação: o usuário escolhe as regras, mexe na fila à mão e compara cenários."""
import copy
from datetime import datetime

import pandas as pd
import streamlit as st

from core import cenarios, ui
from core.regras import SimulacaoProgramacao as S

c = ui.ctx()
ui.cabecalho("Simulação da programação",
             "Monte cenários de fila para as extrusoras: escolha as regras, gere a sugestão e mexa na fila à mão "
             "(posição e máquina). As datas, os atrasos e as trocas de formulação se recalculam na hora. "
             "Nada vai para o ERP: o cenário escolhido é a fila para replicar na máquina.",
             ("carteira", "estoque", "solicitacoes", "planejamento"))

ent = ui.calcular(c.entradas_encaixe)
if ent is None:
    st.stop()
MAQUINAS = [r["apelido"] for r in ent["regras"]]
ROTULO_SEQ = {S.NAO_QUEBRAR: "Não quebrar", S.PODE_QUEBRAR: "Pode quebrar (só se precisar)", S.IGNORAR: "Ignorar"}
ROTULO_PRI = {S.PRAZO: "Respeitar as datas (prazo OTD)", S.FORMULACAO: "Agrupar por formulação (ignora as datas)"}

# ------------------------------------------------------------------ regras do cenário
with st.form("sim_regras"):
    st.markdown("**Regras do cenário**")
    a, b, d = st.columns(3)
    seq = a.radio("Sequência de formulação", list(ROTULO_SEQ), format_func=ROTULO_SEQ.get)
    pri = b.radio("O que manda na fila", list(ROTULO_PRI), format_func=ROTULO_PRI.get)
    maqs = d.multiselect("Máquinas", MAQUINAS, default=MAQUINAS)
    e, f, g, h = st.columns(4)
    fixas = e.number_input("OFs fixas no começo de cada máquina", 0, 20, int(c.params.get("ordens_fixas", 3)))
    setup = f.number_input("Setup por troca de grupo (min)", 0, 600, 0, step=15)
    fator = g.number_input("kg/h dos pedidos novos (% da mediana)", 50, 150, 100, step=5)
    prior = h.toggle("Clientes prioritários primeiro", value=True)
    manter = h.toggle("Manter as OFs travadas", value=True,
                      help="As OFs travadas (🔒) do cenário atual ficam na mesma máquina e posição na sugestão nova")
    gerar = st.form_submit_button("Gerar sugestão", type="primary")

regras = S.RegrasCenario(sequencia=seq, prioridade=pri, ordens_fixas=int(fixas), prioritarios=prior,
                         setup_min=float(setup), maquinas=maqs if len(maqs) < len(MAQUINAS) else [],
                         fator_kgh=fator / 100)


def _novo_cenario():
    travadas, avisos = None, []
    anterior = st.session_state.get("sim_cen")
    if manter and anterior is not None and "travada" in anterior.itens:
        it = anterior.itens
        travadas = it.loc[it["travada"].fillna(False).astype(bool), ["chave", "maquina", "ordem"]]
    cen = S.gerar_cenario(ent["plan"], ent["reserva"], ent["regras"], ent["prioritarios"], ent["mapa"], ent["rank"],
                          regras, travadas=travadas, avisos=avisos)
    if travadas is not None and not travadas.empty:
        avisos.insert(0, f"{len(travadas)} OF(s) travada(s) mantida(s) no lugar.")
    st.session_state.update(sim_cen=cen, sim_hist=[], sim_avisos=avisos,
                            sim_versao=st.session_state.get("sim_versao", 0) + 1, sim_nome=None)


if gerar or "sim_cen" not in st.session_state:
    with st.spinner("Gerando a sugestão…"):
        _novo_cenario()
cen: S.Cenario = st.session_state["sim_cen"]

titulo = st.session_state.get("sim_nome") or "cenário em edição (não salvo)"
st.caption(f"**{titulo}** · {cen.regras.texto()}"
           + (f" · {len(st.session_state['sim_hist'])} mexida(s) à mão" if st.session_state.get("sim_hist") else ""))

# ------------------------------------------------------------------ indicadores
ind = S.indicadores(cen)
k = st.columns(6)
k[0].metric("Novos no prazo", f"{ind.get('novos_no_prazo', 0)} de {ind.get('novos', 0)}")
k[1].metric("OFs que passam a atrasar", ind.get("passam_a_atrasar", 0))
k[2].metric("Fora do prazo (total)", ind.get("fora_do_prazo", 0),
            help=f"inclui {ind.get('ja_atrasadas', 0)} OFs que já estavam atrasadas no planejamento")
k[3].metric("Prioritários fora do prazo", ind.get("prioritarios_fora", 0))
k[4].metric("Trocas de grupo", ind.get("trocas_grupo", 0))
k[5].metric("Pedidos no meio de sequência", ind.get("quebras", 0))
for aviso in st.session_state.get("sim_avisos", []):
    st.warning(aviso)



def _tabela_tela(df: pd.DataFrame) -> pd.DataFrame:
    t = df.copy()
    t["travar"] = t["travada"].fillna(False).astype(bool) if "travada" in t else False
    t["marca"] = [("🟥" if r.atraso in (S.PASSA_A_ATRASAR, S.NAO_ATENDE) else "⬛" if r.atraso == S.JA_ATRASADA
                   else "🟧" if r.situacao == "NOVO" else "🟨" if r.situacao == "NÃO PROGRAMADA" else "") + ("🟪" if r.prioritario else "") + ("🔀" if r.troca_grupo else "") + ("🔒" if r.travada else "")
                  for r in t.itertuples()]
    return t[["travar", "ordem", "maquina", "marca", "situacao", "chave", "cliente", "produto", "grupo_formulacao",
              "nivel_formulacao", "qtde_kg", "inicio", "fim", "data_otd", "atraso", "empurrado_h", "alerta", "roda_em"]]


aba_fila, aba_graf, aba_cen = st.tabs(["Ajustar a fila", "Gráfico", "Cenários salvos"])

# ------------------------------------------------------------------ ajustar a fila
with aba_fila:
    presentes = [m for m in MAQUINAS if m in set(cen.itens["maquina"])]
    if not presentes:
        st.info("Nenhuma OF nas máquinas escolhidas.")
    else:
        maq = st.radio("Máquina", presentes, horizontal=True, key="sim_maq")
        fila = cen.itens[cen.itens["maquina"] == maq].sort_values("ordem")
        st.caption("Para mexer: mude a **ordem** (3 = passa a ser a 3ª da fila) ou a **máquina** da linha e clique em "
                   "Aplicar. Marque **travar** para a OF não sair do lugar quando você mexer nas outras ou agrupar "
                   "(mudar a ordem da própria OF travada leva ela para o lugar novo, ainda travada). "
                   "Gerar sugestão de novo mantém as travadas já aplicadas no mesmo lugar. 🟧 pedido novo · 🟨 OF que estava em não programadas · 🟥 atrasa por causa da fila · ⬛ já atrasada no planejamento · "
                   "🟪 cliente prioritário · 🔀 troca de grupo de formulação (setup) · 🔒 travada.")
        editado = st.data_editor(
            _tabela_tela(fila), key=f"sim_ed_{maq}_{st.session_state.get('sim_versao', 0)}", hide_index=True,
            width="stretch", height=min(38 * (len(fila) + 1), 640),
            disabled=[x for x in _tabela_tela(fila.head(0)).columns if x not in ("travar", "ordem", "maquina")],
            column_config={
                "travar": st.column_config.CheckboxColumn("travar", width="small",
                                                          help="A OF fica no lugar quando as outras mudam"),
                "ordem": st.column_config.NumberColumn("ordem", min_value=1, step=1, width="small"),
                "maquina": st.column_config.SelectboxColumn("máquina", options=MAQUINAS, required=True, width="small"),
                "marca": st.column_config.TextColumn("", width="small"),
                "qtde_kg": st.column_config.NumberColumn("kg", format="%d"),
                "inicio": st.column_config.DatetimeColumn("início", format="DD/MM HH:mm"),
                "fim": st.column_config.DatetimeColumn("fim", format="DD/MM HH:mm"),
                "data_otd": st.column_config.DateColumn("data OTD", format="DD/MM/YYYY"),
                "nivel_formulacao": st.column_config.NumberColumn("nível", width="small"),
                "empurrado_h": st.column_config.NumberColumn("empurrado (h)", format="%.1f"),
            })
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Aplicar mudanças", type="primary", width="stretch"):
            hist = st.session_state["sim_hist"]
            hist.append(copy.deepcopy(cen))
            st.session_state["sim_avisos"] = S.aplicar_mudancas(cen, editado[["chave", "maquina", "ordem", "travar"]].rename(columns={"travar": "travada"}))
            st.session_state["sim_versao"] += 1
            st.rerun()
        if b2.button("Agrupar esta máquina por formulação", width="stretch",
                     help="Sobe a partir do grupo da última OF fixa e depois desce; dentro do grupo fica a ordem atual"):
            st.session_state["sim_hist"].append(copy.deepcopy(cen))
            S.agrupar_por_formulacao(cen, maq)
            st.session_state.update(sim_avisos=[], sim_versao=st.session_state["sim_versao"] + 1)
            st.rerun()
        if b3.button("Desfazer", width="stretch", disabled=not st.session_state.get("sim_hist")):
            st.session_state["sim_cen"] = st.session_state["sim_hist"].pop()
            st.session_state.update(sim_avisos=[], sim_versao=st.session_state["sim_versao"] + 1)
            st.rerun()
        b4.download_button("Excel (todas as máquinas)", lambda: ui.excel(_tabela_tela(cen.itens).drop(columns="marca"), "simulacao"),
                           file_name=f"simulacao_{datetime.now():%Y%m%d_%H%M}.xlsx", width="stretch")
        fim = ind.get("fim_das_filas", {})
        if fim:
            st.caption("Fim de cada fila: " + " · ".join(f"{m} {pd.Timestamp(v):%d/%m %H:%M}" for m, v in fim.items()))

# ------------------------------------------------------------------ gráfico
with aba_graf:
    g = cen.itens.dropna(subset=["inicio", "fim"])
    if g.empty:
        st.caption("Sem datas para desenhar.")
    else:
        import plotly.express as px
        fig = px.timeline(g, x_start="inicio", x_end="fim", y="maquina", color="grupo_formulacao", hover_name="chave",
                          hover_data=["situacao", "cliente", "produto", "qtde_kg", "atraso"])
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_layout(height=160 + 50 * g["maquina"].nunique(), margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------------ cenários salvos
with aba_cen:
    s1, s2 = st.columns([3, 1])
    nome = s1.text_input("Nome do cenário", placeholder="ex.: quebra só na Power, setup 30 min",
                         label_visibility="collapsed")
    if s2.button("Salvar cenário atual", type="primary", width="stretch"):
        novo_id = cenarios.salvar(nome, cen)
        st.session_state["sim_nome"] = f"#{novo_id} {nome.strip() or 'sem nome'}"
        st.success(f"Cenário #{novo_id} salvo.")
    salvos = cenarios.listar()
    if not salvos:
        st.caption("Nenhum cenário salvo ainda.")
    else:
        ROT = {"novos_no_prazo": "novos no prazo", "novos": "novos", "passam_a_atrasar": "passam a atrasar",
               "fora_do_prazo": "fora do prazo", "prioritarios_fora": "prioritários fora", "trocas_grupo": "trocas de grupo",
               "quebras": "no meio de sequência", "horas_empurradas": "horas empurradas"}
        linhas = [{"atual (em edição)": None, **{ROT[k]: ind.get(k) for k in ROT}, "regras": cen.regras.texto(),
                   "id": None, "escolhido": ""}]
        for s in salvos:
            linhas.append({"atual (em edição)": f"#{s['id']} {s['nome']}", **{ROT[k]: s["indicadores"].get(k) for k in ROT},
                           "regras": s["regras"], "id": s["id"], "escolhido": "✅" if s["escolhido"] else "",
                           "salvo em": s["criado_em"], "por": s["usuario"]})
        tab = pd.DataFrame(linhas).rename(columns={"atual (em edição)": "cenário"})
        tab.loc[0, "cenário"] = "▶ atual (em edição)"
        st.dataframe(tab.drop(columns="id"), hide_index=True, width="stretch")
        opcoes = {f"#{s['id']} {s['nome']}": s["id"] for s in salvos}
        escolha = st.selectbox("Cenário salvo", list(opcoes))
        x1, x2, x3 = st.columns(3)
        if x1.button("Abrir para mexer", width="stretch"):
            st.session_state.update(sim_cen=cenarios.abrir(opcoes[escolha]), sim_hist=[], sim_avisos=[],
                                    sim_versao=st.session_state.get("sim_versao", 0) + 1, sim_nome=escolha)
            st.rerun()
        if x2.button("Marcar como escolhido", width="stretch",
                     help="O cenário escolhido é a fila para replicar nas máquinas (só um fica marcado)"):
            cenarios.escolher(opcoes[escolha])
            st.rerun()
        if x3.button("Apagar", width="stretch"):
            cenarios.apagar(opcoes[escolha])
            st.rerun()
        st.caption("Os cenários salvos guardam a fila do momento em que foram gerados. Se os relatórios mudarem, "
                   "gere de novo para pegar o planejamento atual.")
