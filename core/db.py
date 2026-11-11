"""
Banco SQLite do app (dados/guanapack.sqlite3).

Fica no banco só o que é do usuário e precisa durar entre uma consulta e outra:
- cadastros: rank de formulações, clientes prioritários (especiais) e regras das máquinas;
- locais da pasta de relatórios por usuário e PC, e o nome do arquivo de cada relatório;
- parâmetros das regras, módulos ativos e preferências de cada usuário;
- histórico de indicadores (um retrato do painel a cada "Atualizar tudo"), log de execuções,
  anotações nos pedidos e auditoria de toda alteração nos cadastros.

Os relatórios do ERP não são gravados aqui: o app lê os .xls direto da pasta.

Cada função abre e fecha a própria conexão (o Streamlit roda cada sessão numa thread).
"""
import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import pandas as pd

import config

VERSAO_ESQUEMA = 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
CREATE TABLE IF NOT EXISTS formulacoes (
    formulacao TEXT PRIMARY KEY,
    rank INTEGER NOT NULL,
    observacao TEXT,
    atualizado_em TEXT,
    atualizado_por TEXT
);
CREATE TABLE IF NOT EXISTS clientes_prioritarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente TEXT NOT NULL,
    material TEXT,
    formulacao TEXT,
    observacao TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    atualizado_em TEXT,
    atualizado_por TEXT
);
CREATE TABLE IF NOT EXISTS maquinas (
    maquina TEXT PRIMARY KEY,
    ativa INTEGER NOT NULL DEFAULT 1,
    formulacoes TEXT NOT NULL,
    nao_roda TEXT,
    micra_min REAL, micra_max REAL,
    peso_min REAL, peso_max REAL,
    tubete_min REAL, tubete_max REAL,
    largura_min REAL, largura_max REAL,
    observacao TEXT,
    atualizado_em TEXT,
    atualizado_por TEXT
);
CREATE TABLE IF NOT EXISTS locais_relatorios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT NOT NULL DEFAULT '*',
    pc TEXT NOT NULL DEFAULT '*',
    pasta TEXT NOT NULL,
    observacao TEXT,
    atualizado_em TEXT,
    UNIQUE (usuario, pc)
);
CREATE TABLE IF NOT EXISTS arquivos_relatorios (
    chave TEXT PRIMARY KEY,
    arquivo TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parametros (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    atualizado_em TEXT,
    atualizado_por TEXT
);
CREATE TABLE IF NOT EXISTS modulos (
    id TEXT PRIMARY KEY,
    ativo INTEGER NOT NULL DEFAULT 1,
    ordem INTEGER
);
CREATE TABLE IF NOT EXISTS preferencias (
    usuario TEXT NOT NULL,
    chave TEXT NOT NULL,
    valor TEXT,
    PRIMARY KEY (usuario, chave)
);
CREATE TABLE IF NOT EXISTS historico_indicadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL,
    usuario TEXT, pc TEXT,
    atrasados INTEGER, vao_atrasar INTEGER,
    pedidos_reserva INTEGER, sem_estoque INTEGER,
    encaixe_pedidos INTEGER, encaixe_novos INTEGER, encaixe_atendem INTEGER,
    ofs_passam_atrasar INTEGER,
    troca_pedir INTEGER,
    tubetes_sem_encaixe REAL, tubetes_com_encaixe REAL,
    pallets_sem_encaixe REAL, pallets_com_encaixe REAL,
    estoque_kg REAL, slow_move_kg REAL,
    duracao_s REAL,
    resultado TEXT
);
CREATE TABLE IF NOT EXISTS execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL,
    usuario TEXT, pc TEXT,
    acao TEXT NOT NULL,
    duracao_s REAL,
    resultado TEXT
);
CREATE TABLE IF NOT EXISTS anotacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    num_pedido INTEGER NOT NULL,
    prog INTEGER,
    texto TEXT NOT NULL,
    resolvida INTEGER NOT NULL DEFAULT 0,
    usuario TEXT, pc TEXT,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_anotacoes_pedido ON anotacoes (num_pedido, prog);
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL,
    usuario TEXT, pc TEXT,
    tabela TEXT NOT NULL,
    acao TEXT NOT NULL,
    chave TEXT,
    antes TEXT,
    depois TEXT
);
"""


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def conectar():
    """Conexão com commit no fim (rollback se der erro)."""
    config.DADOS_DIR.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(config.DATABASE, timeout=15)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    try:
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


def consultar(sql: str, parametros: tuple = ()) -> list[dict]:
    with conectar() as c:
        return [dict(l) for l in c.execute(sql, parametros).fetchall()]


def consultar_df(sql: str, parametros: tuple = ()) -> pd.DataFrame:
    with conectar() as c:
        return pd.read_sql_query(sql, c, params=parametros)


def executar(sql: str, parametros: tuple = ()) -> int:
    with conectar() as c:
        return c.execute(sql, parametros).lastrowid


# ===================================================================== inicialização

def inicializar():
    """Cria as tabelas e faz a carga inicial dos cadastros (só com a tabela vazia)."""
    with conectar() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(ESQUEMA)
        c.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES ('versao_esquema', ?)", (str(VERSAO_ESQUEMA),))

        if _vazia(c, "formulacoes") and config.ARQ_FORMULACOES_RANK.exists():
            df = _ler_csv(config.ARQ_FORMULACOES_RANK)
            c.executemany("INSERT OR IGNORE INTO formulacoes (formulacao, rank, atualizado_em, atualizado_por) "
                          "VALUES (?, ?, ?, 'carga inicial')",
                          [(" ".join(f.upper().split()), int(r), agora()) for f, r in zip(df['formulacao'], df['rank'])])

        if _vazia(c, "clientes_prioritarios") and config.ARQ_CLIENTES_PRIORITARIOS.exists():
            df = _ler_csv(config.ARQ_CLIENTES_PRIORITARIOS)
            c.executemany("INSERT INTO clientes_prioritarios (cliente, material, formulacao, observacao, "
                          "atualizado_em, atualizado_por) VALUES (?, ?, ?, ?, ?, 'carga inicial')",
                          [(r['cliente'], r.get('material') or None, r.get('formulacao') or None,
                            r.get('observacao') or None, agora()) for r in df.to_dict('records')])

        if _vazia(c, "maquinas") and config.ARQ_MAQUINAS.exists():
            df = _ler_csv(config.ARQ_MAQUINAS)
            for r in df.to_dict('records'):
                valores = {k: (_numero(v) if k.endswith(('_min', '_max')) else (v or None)) for k, v in r.items()}
                valores.update(ativa=1, atualizado_em=agora(), atualizado_por='carga inicial')
                c.execute(f"INSERT INTO maquinas ({', '.join(valores)}) VALUES ({', '.join('?' * len(valores))})",
                          tuple(valores.values()))

        if _vazia(c, "locais_relatorios"):
            c.executemany("INSERT INTO locais_relatorios (usuario, pc, pasta, observacao, atualizado_em) "
                          "VALUES (?, ?, ?, 'carga inicial', ?)",
                          [(u, p, pasta, agora()) for (u, p), pasta in config.LOCAIS_INICIAIS.items()])

        for chave, rel in config.RELATORIOS.items():
            c.execute("INSERT OR IGNORE INTO arquivos_relatorios (chave, arquivo) VALUES (?, ?)", (chave, rel.arquivo))


def _vazia(c, tabela: str) -> bool:
    return c.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0] == 0


def _ler_csv(arquivo) -> pd.DataFrame:
    df = pd.read_csv(arquivo, sep=';', encoding='utf-8-sig', dtype=str, keep_default_na=False)
    df.columns = [col.strip().lower() for col in df.columns]
    return df


def _numero(v):
    """"9,5" -> 9.5; vazio -> None."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    texto = str(v).strip().replace(',', '.')
    return float(texto) if texto else None


# ===================================================================== auditoria

def auditar(c, tabela: str, acao: str, chave, antes: dict | None, depois: dict | None, usuario: str, pc: str):
    def js(d):
        return None if d is None else json.dumps(d, ensure_ascii=False, default=str)
    c.execute("INSERT INTO auditoria (data_hora, usuario, pc, tabela, acao, chave, antes, depois) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (agora(), usuario, pc, tabela, acao, str(chave), js(antes), js(depois)))


def registrar_execucao(acao: str, usuario: str, pc: str, duracao_s: float | None = None, resultado: str = "ok"):
    executar("INSERT INTO execucoes (data_hora, usuario, pc, acao, duracao_s, resultado) VALUES (?, ?, ?, ?, ?, ?)",
             (agora(), usuario, pc, acao, None if duracao_s is None else round(duracao_s, 1), (resultado or "ok")[:500]))


# ===================================================================== cópia de segurança

def fazer_backup() -> str:
    """Copia o banco para dados/backup/guanapack_AAAAMMDD_HHMMSS.sqlite3 e devolve o caminho."""
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destino = config.BACKUP_DIR / f"guanapack_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
    with conectar() as c:
        c.execute("PRAGMA wal_checkpoint(FULL)")
    shutil.copy2(config.DATABASE, destino)
    return str(destino)


def backup_diario():
    """Um backup por dia, na primeira abertura do app (guarda os 30 mais novos)."""
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    hoje = datetime.now().strftime("%Y%m%d")
    if not config.DATABASE.exists() or any(config.BACKUP_DIR.glob(f"guanapack_{hoje}_*.sqlite3")):
        return
    fazer_backup()
    antigos = sorted(config.BACKUP_DIR.glob("guanapack_*.sqlite3"))[:-30]
    for arquivo in antigos:
        arquivo.unlink(missing_ok=True)
