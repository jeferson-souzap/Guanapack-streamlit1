"""Anotações livres nos pedidos (ficam no banco, com usuário e PC)."""
import pandas as pd

from core import db
from core.contexto import pc, usuario


def listar(num_pedido: int | None = None, so_abertas: bool = False) -> pd.DataFrame:
    sql, params = "SELECT * FROM anotacoes WHERE 1 = 1", []
    if num_pedido is not None:
        sql += " AND num_pedido = ?"
        params.append(int(num_pedido))
    if so_abertas:
        sql += " AND resolvida = 0"
    df = db.consultar_df(sql + " ORDER BY criado_em DESC", tuple(params))
    df["resolvida"] = df["resolvida"].astype(bool)
    return df


def incluir(num_pedido: int, prog: int | None, texto: str):
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Escreva a anotação.")
    db.executar("INSERT INTO anotacoes (num_pedido, prog, texto, usuario, pc, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
                (int(num_pedido), None if prog is None else int(prog), texto, usuario(), pc(), db.agora()))


def marcar(id_anotacao: int, resolvida: bool):
    db.executar("UPDATE anotacoes SET resolvida = ? WHERE id = ?", (int(resolvida), int(id_anotacao)))


def excluir(id_anotacao: int):
    db.executar("DELETE FROM anotacoes WHERE id = ?", (int(id_anotacao),))
