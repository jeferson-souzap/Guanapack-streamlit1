"""Configuração: pasta dos relatórios por usuário/PC, nomes dos arquivos, parâmetros, módulos e backup."""
from pathlib import Path

import streamlit as st

import config
from core import contexto, db, pipeline, relatorios, ui
from modulos import MODULOS

st.title("Configuração")
eu, meu_pc = contexto.usuario(), contexto.pc()
aba1, aba2, aba3, aba4, aba5 = st.tabs(["Pasta dos relatórios", "Arquivos", "Parâmetros", "Módulos",
                                        "Banco"])

with aba1:
    pasta, origem = contexto.pasta_relatorios()
    st.markdown(f"Pasta usada agora por **{eu}** em **{meu_pc}**: `{pasta}`  \n<small>({origem})</small>",
                unsafe_allow_html=True)
    with st.form("local"):
        nova = st.text_input("Pasta", value=str(pasta), help=r"ex.: G:\PCP\10. Programação\00. Diário\Fulano\report")
        escopo = st.radio("Salvar para", ["mim neste PC", "qualquer usuário neste PC", "mim em qualquer PC",
                                          "todos (local geral)"], horizontal=True)
        obs = st.text_input("Observação (opcional)")
        if st.form_submit_button("Salvar local", type="primary"):
            u = eu if escopo in ("mim neste PC", "mim em qualquer PC") else "*"
            p = meu_pc if escopo in ("mim neste PC", "qualquer usuário neste PC") else "*"
            if not Path(nova.strip().strip('"')).is_dir():
                st.warning("A pasta não foi encontrada neste PC agora (salvei mesmo assim).")
            try:
                contexto.salvar_local(nova, u, p, obs)
                pipeline.limpar_cache()
                st.success("Local salvo.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    st.markdown("**Locais salvos** (o mais específico vence: você neste PC → este PC → você → geral)")
    locais = contexto.listar_locais()
    st.dataframe(locais, hide_index=True, width="stretch")
    if len(locais):
        excluir = st.selectbox("Excluir local", [None, *locais["id"]], format_func=lambda i: "—" if i is None else
                               " · ".join(str(v) for v in locais.loc[locais["id"] == i, ["usuario", "pc", "pasta"]].iloc[0]))
        if excluir and st.button("Excluir"):
            contexto.excluir_local(excluir)
            st.rerun()

with aba2:
    st.caption("Nome de cada relatório dentro da pasta. Deixe em branco para voltar ao padrão.")
    atuais = contexto.arquivos_relatorios()
    with st.form("arquivos"):
        novos = {ch: st.text_input(rel.titulo, value=atuais[ch], help=f"padrão: {rel.arquivo}")
                 for ch, rel in config.RELATORIOS.items()}
        if st.form_submit_button("Salvar nomes", type="primary"):
            for ch, nome in novos.items():
                contexto.salvar_arquivo_relatorio(ch, nome)
            pipeline.limpar_cache()
            st.success("Nomes salvos.")
    tol = int(contexto.parametros()["dias_tolerancia_relatorio"])
    for s in relatorios.conferir_todos(tolerancia_dias=tol).values():
        st.markdown(f"{ui.ICONE_SITUACAO[s['situacao']]} "
                    f"`{s['arquivo']}` — {s['mensagem']}")

with aba3:
    st.caption("Mudar um parâmetro recalcula só as etapas que dependem dele. Toda mudança vai para a auditoria.")
    valores = contexto.parametros()
    with st.form("parametros"):
        novos = {}
        grupos = sorted({p.grupo for p in config.PARAMETROS.values()})
        for g in grupos:
            st.markdown(f"**{g}**")
            for p in [p for p in config.PARAMETROS.values() if p.grupo == g]:
                if p.tipo == "int":
                    novos[p.chave] = st.number_input(p.descricao, value=int(valores[p.chave]), step=1, min_value=0,
                                                     help=f"padrão: {p.padrao:g}")
                else:
                    novos[p.chave] = st.number_input(p.descricao, value=float(valores[p.chave]), step=0.01,
                                                     min_value=0.0, format="%.2f", help=f"padrão: {p.padrao:g}")
        b1, b2 = st.columns(2)
        salvar = b1.form_submit_button("Salvar parâmetros", type="primary")
        padrao = b2.form_submit_button("Voltar todos ao padrão")
    if salvar or padrao:
        for chave, valor in novos.items():
            contexto.salvar_parametro(chave, config.PARAMETROS[chave].padrao if padrao else valor)
        st.success("Parâmetros salvos.")
        st.rerun()

with aba4:
    st.caption("Desligue os módulos que você não usa e mude a ordem do menu. Início, Cadastros e Configuração ficam "
               "sempre ligados. Vale para todos os usuários.")
    estado = contexto.modulos_estado()
    with st.form("modulos"):
        escolhas = {}
        for i, m in enumerate(MODULOS):
            c1, c2, c3 = st.columns([1, 4, 1])
            ativo = c1.toggle(m.titulo, label_visibility="collapsed", value=m.fixo or bool(estado.get(m.id, {}).get("ativo", 1)), disabled=m.fixo,
                              key=f"mod_{m.id}")
            c2.markdown(f"**{m.titulo}**  \n<small>{m.descricao}</small>", unsafe_allow_html=True)
            ordem = c3.number_input("ordem", value=int(estado.get(m.id, {}).get("ordem") or i), step=1,
                                    key=f"ord_{m.id}", label_visibility="collapsed")
            escolhas[m.id] = (ativo or m.fixo, ordem)
        if st.form_submit_button("Salvar módulos", type="primary"):
            for id_m, (ativo, ordem) in escolhas.items():
                contexto.salvar_modulo(id_m, ativo, ordem)
            st.rerun()

with aba5:
    st.markdown(f"Banco: `{config.DATABASE}`")
    tabelas = ["formulacoes", "clientes_prioritarios", "maquinas", "locais_relatorios", "parametros", "anotacoes",
               "historico_indicadores", "execucoes", "auditoria"]
    contagem = {t: db.consultar(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in tabelas}
    st.dataframe([{"tabela": t, "linhas": n} for t, n in contagem.items()], hide_index=True)
    b1, b2 = st.columns(2)
    if b1.button("Fazer backup agora"):
        st.success(f"Backup salvo em `{db.fazer_backup()}`")
    if config.DATABASE.exists():
        b2.download_button("Baixar o banco", config.DATABASE.read_bytes(), "guanapack.sqlite3")
    backups = sorted(config.BACKUP_DIR.glob("guanapack_*.sqlite3"), reverse=True) if config.BACKUP_DIR.exists() else []
    st.caption(f"{len(backups)} backup(s) em `{config.BACKUP_DIR}` (um por dia, automático; ficam os 30 mais novos).")
