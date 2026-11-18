"""Banco SQLite: migração de bancos criados por versões antigas do app."""
import sqlite3

import config
from core import db


def _tabelas() -> set[str]:
    return {l["name"] for l in db.consultar("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_banco_antigo_perde_as_tabelas_dos_modulos_removidos(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE", tmp_path / "antigo.sqlite3")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    with sqlite3.connect(config.DATABASE) as c:           # como era até o esquema 2
        c.execute("CREATE TABLE historico_indicadores (id INTEGER PRIMARY KEY, data_hora TEXT, atrasados INTEGER)")
        c.execute("INSERT INTO historico_indicadores (data_hora, atrasados) VALUES ('2026-11-01 08:00:00', 5)")
        c.execute("CREATE TABLE execucoes (id INTEGER PRIMARY KEY, acao TEXT)")
    db.inicializar()
    assert not _tabelas() & set(db.TABELAS_REMOVIDAS)
    assert {"maquinas", "cenarios_simulacao", "auditoria"} <= _tabelas()
    backups = list(config.BACKUP_DIR.glob("guanapack_*.sqlite3"))
    assert len(backups) == 1                               # cópia com as tabelas antigas, antes de apagar
    with sqlite3.connect(backups[0]) as c:
        assert c.execute("SELECT atrasados FROM historico_indicadores").fetchall() == [(5,)]
    db.inicializar()                                       # rodar de novo não dá erro nem faz outro backup
    assert len(list(config.BACKUP_DIR.glob("guanapack_*.sqlite3"))) == 1


def test_banco_novo_nao_cria_as_tabelas_removidas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE", tmp_path / "novo.sqlite3")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    db.inicializar()
    assert not _tabelas() & set(db.TABELAS_REMOVIDAS)
    assert not config.BACKUP_DIR.exists() or not any(config.BACKUP_DIR.iterdir())


def test_anotacoes_incluir_resolver_e_excluir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE", tmp_path / "anot.sqlite3")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    db.inicializar()
    from core import anotacoes
    anotacoes.incluir(123, None, "cliente aceitou adiar")
    notas = anotacoes.listar(123)
    assert list(notas["texto"]) == ["cliente aceitou adiar"] and not notas["resolvida"].iloc[0]
    anotacoes.marcar(int(notas["id"].iloc[0]), True)
    assert anotacoes.listar(so_abertas=True).empty
    anotacoes.excluir(int(notas["id"].iloc[0]))
    assert anotacoes.listar(123).empty
