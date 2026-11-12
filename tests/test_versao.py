"""Aviso de código desatualizado: módulo cujo arquivo mudou depois de carregado."""
import importlib
import sys

import streamlit as st

import config
from core import versao


def test_modulo_que_mudou_no_disco_e_nao_foi_recarregado(tmp_path, monkeypatch):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    arq = tmp_path / "modulo_teste_versao.py"
    arq.write_text("VALOR = 1\n", encoding="utf-8")
    importlib.invalidate_caches()
    import modulo_teste_versao  # noqa: F401
    try:
        assert versao.modulos_desatualizados() == []             # primeira vez: guarda a marca

        arq.write_text("VALOR = 2  # deploy novo\n", encoding="utf-8")
        assert versao.modulos_desatualizados() == ["modulo_teste_versao"]   # continua o objeto antigo

        del sys.modules["modulo_teste_versao"]                   # o que o Streamlit faz ao recarregar
        importlib.import_module("modulo_teste_versao")
        assert versao.modulos_desatualizados() == []
    finally:
        sys.modules.pop("modulo_teste_versao", None)
        st.cache_resource.clear()
