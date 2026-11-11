"""Cenários salvos da simulação da programação (tabela cenarios_simulacao do banco)."""
import json

from core import contexto, db
from core.regras.SimulacaoProgramacao import Cenario, de_json, indicadores, para_json


def _js(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


def salvar(nome: str, cen: Cenario, observacao: str = "") -> int:
    ind = {k: v for k, v in indicadores(cen).items() if k != "fim_das_filas"}
    return db.executar(
        "INSERT INTO cenarios_simulacao (nome, criado_em, usuario, pc, regras, indicadores, dados, observacao) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ((nome or "").strip() or "sem nome", db.agora(), contexto.usuario(), contexto.pc(), cen.regras.texto(),
         _js(ind), _js(para_json(cen)), observacao or None))


def listar() -> list[dict]:
    linhas = db.consultar("SELECT id, nome, criado_em, usuario, regras, indicadores, escolhido, observacao "
                          "FROM cenarios_simulacao ORDER BY id DESC")
    for l in linhas:
        l["indicadores"] = json.loads(l["indicadores"] or "{}")
    return linhas


def abrir(id_cenario: int) -> Cenario:
    linha = db.consultar("SELECT dados FROM cenarios_simulacao WHERE id = ?", (int(id_cenario),))
    if not linha:
        raise KeyError(f"cenário {id_cenario} não existe")
    return de_json(json.loads(linha[0]["dados"]))


def apagar(id_cenario: int):
    db.executar("DELETE FROM cenarios_simulacao WHERE id = ?", (int(id_cenario),))


def escolher(id_cenario: int):
    """Marca o cenário como o escolhido (a fila para replicar nas máquinas); só um fica marcado."""
    with db.conectar() as c:
        c.execute("UPDATE cenarios_simulacao SET escolhido = 0")
        c.execute("UPDATE cenarios_simulacao SET escolhido = 1 WHERE id = ?", (int(id_cenario),))
