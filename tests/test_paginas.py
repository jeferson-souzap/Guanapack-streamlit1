"""
Abre cada página do app (streamlit.testing.AppTest) e confere que nenhuma derruba o app.

Pega o tipo de erro que só aparecia com o app no ar: KeyError de coluna ou de parâmetro numa página.

- sem relatórios: roda sempre. Toda página tem de mostrar o aviso de "falta relatório", sem erro.
- com relatórios reais: roda quando há uma pasta com os relatórios do ERP. Ela vem da variável
  PCP_REPORTS_TESTE ou, se não estiver definida, da primeira pasta de config.LOCAIS_INICIAIS que existir
  neste computador. Os relatórios não vão para o git (dados de clientes).

O banco é um SQLite temporário: os testes não mexem em dados/guanapack.sqlite3.
"""
import os
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import config
from core import pipeline
from core.regras.EncaixeMaquinas import gerar_encaixe
from modulos import MODULOS

PAGINAS = [m.arquivo for m in MODULOS]
APP = str(config.BASE_DIR / "app.py")
TEMPO = 300          # segundos: o primeiro cálculo com os relatórios reais lê os Excel


def _pasta_reais() -> Path | None:
    candidatas = [os.environ.get("PCP_REPORTS_TESTE")] if os.environ.get("PCP_REPORTS_TESTE") else \
        list(config.LOCAIS_INICIAIS.values())
    for pasta in candidatas:
        try:
            p = Path(pasta)
            if p.is_dir() and all((p / r.arquivo).exists() for r in config.RELATORIOS.values()):
                return p
        except OSError:
            continue
    return None


def _isolar(mp: pytest.MonkeyPatch, raiz: Path, pasta_relatorios: Path):
    """Banco e pasta de enviados temporários; relatórios da pasta dada; cache limpo."""
    dados = raiz / "dados"
    mp.setattr(config, "DADOS_DIR", dados)
    mp.setattr(config, "DATABASE", dados / "guanapack.sqlite3")
    mp.setattr(config, "BACKUP_DIR", dados / "backup")
    mp.setattr(config, "PASTA_ENVIADOS", dados / "enviados")
    mp.setenv(config.VAR_PASTA, str(pasta_relatorios))
    st.cache_resource.clear()
    st.cache_data.clear()


@pytest.fixture
def sem_relatorios(tmp_path):
    vazia = tmp_path / "relatorios"
    vazia.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        _isolar(mp, tmp_path, vazia)
        yield
    st.cache_resource.clear()
    st.cache_data.clear()


@pytest.fixture(scope="module")
def com_relatorios_reais(tmp_path_factory):
    """Um ambiente só para todas as páginas: o cache dos cálculos vale de uma página para a outra."""
    pasta = _pasta_reais()
    if pasta is None:
        pytest.skip("sem a pasta dos relatórios (defina PCP_REPORTS_TESTE)")
    with pytest.MonkeyPatch.context() as mp:
        _isolar(mp, tmp_path_factory.mktemp("reais"), pasta)
        yield
    st.cache_resource.clear()
    st.cache_data.clear()


def _abrir(pagina: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TEMPO)
    at.run()
    assert not at.exception, f"app.py: {at.exception}"
    at.switch_page(pagina)
    at.run()
    return at


def _erros(at: AppTest) -> list[str]:
    """Exceções que derrubaram a página ou que ui.calcular mostrou na tela ("Erro no cálculo"). O aviso
    de relatório que falta também é um st.error, mas é esperado."""
    return [e.value for e in at.exception] + [e.value for e in at.error if str(e.value).startswith("Erro no cálculo")]


@pytest.mark.parametrize("pagina", PAGINAS)
def test_pagina_sem_relatorios(sem_relatorios, pagina):
    at = _abrir(pagina)
    assert not _erros(at), f"{pagina}: {_erros(at)}"


@pytest.mark.parametrize("pagina", PAGINAS)
def test_pagina_com_relatorios_reais(com_relatorios_reais, pagina):
    at = _abrir(pagina)
    assert not _erros(at), f"{pagina}: {_erros(at)}"


def test_encaixe_sem_pedido_sem_estoque(sem_relatorios, monkeypatch):
    """Dia em que todo pedido tem estoque: o encaixe sai vazio e a página abre assim mesmo."""
    regras = [{"maquina": "M1", "apelido": "M1", "grupos": [], "palavras_nao_roda": []}]
    vazio = gerar_encaixe(pd.DataFrame(columns=["maquina", "id_of", "inicio_prev", "final_prev"]),
                          pd.DataFrame(columns=["num_pedido", "prog", "tem_estoque"]), regras, None, {})
    monkeypatch.setattr(pipeline.Contexto, "encaixe", lambda self: vazio)
    at = _abrir("modulos/encaixe.py")
    assert not _erros(at), _erros(at)
