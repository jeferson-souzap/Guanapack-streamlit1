"""Banco SQLite: migração de bancos criados por versões antigas do app."""
import sqlite3

import config
from core import db, indicadores


def test_banco_antigo_ganha_a_coluna_de_lead_time(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE", tmp_path / "antigo.sqlite3")
    with sqlite3.connect(config.DATABASE) as c:           # histórico como era no esquema 1
        c.execute("CREATE TABLE historico_indicadores (id INTEGER PRIMARY KEY AUTOINCREMENT, data_hora TEXT NOT NULL, "
                  "usuario TEXT, pc TEXT, atrasados INTEGER, vao_atrasar INTEGER)")
        c.execute("INSERT INTO historico_indicadores (data_hora, atrasados) VALUES ('2026-11-01 08:00:00', 5)")
    db.inicializar()
    colunas = {l["name"] for l in db.consultar("PRAGMA table_info(historico_indicadores)")}
    assert "lead_time_estoque" in colunas
    assert db.consultar("SELECT atrasados, lead_time_estoque FROM historico_indicadores") == \
        [{"atrasados": 5, "lead_time_estoque": None}]       # o retrato antigo fica, sem o número novo
    db.inicializar()                                        # rodar de novo não dá erro


def test_banco_novo_grava_todas_as_colunas_do_historico(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE", tmp_path / "novo.sqlite3")
    db.inicializar()
    indicadores.gravar({"lead_time_estoque": 7}, 1.0, {})
    assert db.consultar("SELECT lead_time_estoque FROM historico_indicadores") == [{"lead_time_estoque": 7}]
