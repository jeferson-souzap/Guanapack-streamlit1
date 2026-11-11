"""
Cadastros do banco: rank de formulações, clientes prioritários (especiais) e regras das máquinas.

Na tela cada cadastro é editado como uma planilha (st.data_editor). Ao salvar, a tabela inteira é
validada, comparada com o banco (incluídas, alteradas, excluídas) e cada diferença vai para a
auditoria com o usuário e o PC.
"""
import pandas as pd

from core import db
from core.contexto import pc, usuario
from core.regras.Maquinas import CAMPOS_FAIXA, _lista, montar_regras
from core.regras.Prioridade import ListaPrioritarios


def _vazio(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip()) or v is pd.NA


def _txt(v):
    return None if _vazio(v) else " ".join(str(v).split())


def _aplicar(tabela: str, chave: str, atuais: dict, novos: dict, colunas: list[str]) -> dict:
    """Grava as diferenças entre o banco (atuais) e a tela (novos), com auditoria. Devolve as contagens."""
    quem, onde = usuario(), pc()
    cont = {"incluídas": 0, "alteradas": 0, "excluídas": 0}
    with db.conectar() as c:
        for k, antes in atuais.items():
            if k not in novos:
                c.execute(f"DELETE FROM {tabela} WHERE {chave} = ?", (k,))
                db.auditar(c, tabela, "excluiu", k, antes, None, quem, onde)
                cont["excluídas"] += 1
        for k, depois in novos.items():
            valores = {col: depois.get(col) for col in colunas}
            antes = atuais.get(k)
            if antes is None:
                valores.update(atualizado_em=db.agora(), atualizado_por=f"{quem}@{onde}")
                if chave == "id":
                    valores.pop("id", None)
                cid = c.execute(f"INSERT INTO {tabela} ({', '.join(valores)}) VALUES ({', '.join('?' * len(valores))})",
                                tuple(valores.values())).lastrowid
                db.auditar(c, tabela, "incluiu", k if chave != "id" else cid, None, valores, quem, onde)
                cont["incluídas"] += 1
            elif any(antes.get(col) != valores.get(col) for col in colunas):
                valores.update(atualizado_em=db.agora(), atualizado_por=f"{quem}@{onde}")
                sets = ", ".join(f"{col} = ?" for col in valores)
                c.execute(f"UPDATE {tabela} SET {sets} WHERE {chave} = ?", (*valores.values(), antes[chave]))
                db.auditar(c, tabela, "alterou", k, {col: antes.get(col) for col in colunas},
                           {col: valores.get(col) for col in colunas}, quem, onde)
                cont["alteradas"] += 1
    return cont


# ===================================================================== formulações

COLUNAS_FORMULACAO = ["formulacao", "rank", "observacao"]


def formulacoes_df() -> pd.DataFrame:
    return db.consultar_df("SELECT formulacao, rank, observacao, atualizado_em, atualizado_por "
                           "FROM formulacoes ORDER BY rank, formulacao")


def carregar_rank() -> dict[str, int]:
    return {l["formulacao"]: int(l["rank"]) for l in db.consultar("SELECT formulacao, rank FROM formulacoes")}


def salvar_formulacoes(df: pd.DataFrame) -> dict:
    """Valida e grava o cadastro de formulações. Levanta ValueError com a mensagem para o usuário."""
    novos, erros = {}, []
    for i, r in enumerate(df.to_dict("records"), start=1):
        if all(_vazio(r.get(c)) for c in COLUNAS_FORMULACAO):
            continue
        f = _txt(r.get("formulacao"))
        if not f:
            erros.append(f"linha {i}: informe a formulação")
            continue
        f = f.upper()
        try:
            rank = int(float(str(r.get("rank")).replace(",", ".")))
        except (TypeError, ValueError):
            erros.append(f"{f}: o rank precisa ser um número inteiro")
            continue
        if f in novos:
            erros.append(f"{f}: formulação repetida")
        novos[f] = {"formulacao": f, "rank": rank, "observacao": _txt(r.get("observacao"))}
    if erros:
        raise ValueError("; ".join(erros))
    atuais = {l["formulacao"]: l for l in db.consultar("SELECT * FROM formulacoes")}
    return _aplicar("formulacoes", "formulacao", atuais, novos, COLUNAS_FORMULACAO)


# ===================================================================== clientes prioritários

COLUNAS_PRIORITARIO = ["cliente", "material", "formulacao", "observacao", "ativo"]


def prioritarios_df() -> pd.DataFrame:
    df = db.consultar_df("SELECT id, ativo, cliente, material, formulacao, observacao, atualizado_em, atualizado_por "
                         "FROM clientes_prioritarios ORDER BY cliente, id")
    df["ativo"] = df["ativo"].astype(bool)
    return df


def carregar_prioritarios() -> list[dict]:
    """Linhas ativas (dicionários simples, para servir de chave do cache)."""
    return db.consultar("SELECT cliente, material, formulacao FROM clientes_prioritarios WHERE ativo = 1 ORDER BY id")


def lista_prioritarios(linhas: list[dict] | None = None) -> ListaPrioritarios:
    return ListaPrioritarios(linhas if linhas is not None else carregar_prioritarios())


def salvar_prioritarios(df: pd.DataFrame) -> dict:
    novos, erros, provisorio = {}, [], -1
    for i, r in enumerate(df.to_dict("records"), start=1):
        if all(_vazio(r.get(c)) for c in ["cliente", "material", "formulacao", "observacao"]):
            continue
        cliente = _txt(r.get("cliente"))
        if not cliente:
            erros.append(f"linha {i}: informe o cliente (parte do nome)")
            continue
        id_linha = None if _vazio(r.get("id")) else int(r["id"])
        if id_linha is None:
            id_linha, provisorio = provisorio, provisorio - 1
        ativo = r.get("ativo")
        novos[id_linha] = {"id": id_linha, "cliente": cliente, "material": _txt(r.get("material")),
                           "formulacao": _txt(r.get("formulacao")), "observacao": _txt(r.get("observacao")),
                           "ativo": 0 if (ativo is False or ativo == 0) else 1}
    if erros:
        raise ValueError("; ".join(erros))
    atuais = {l["id"]: l for l in db.consultar("SELECT * FROM clientes_prioritarios")}
    return _aplicar("clientes_prioritarios", "id", atuais, novos, COLUNAS_PRIORITARIO)


# ===================================================================== máquinas

COLUNAS_MAQUINA = ["maquina", "ativa", "formulacoes", "nao_roda", *CAMPOS_FAIXA, "observacao"]


def maquinas_df() -> pd.DataFrame:
    df = db.consultar_df(f"SELECT {', '.join(COLUNAS_MAQUINA)}, atualizado_em, atualizado_por FROM maquinas ORDER BY maquina")
    df["ativa"] = df["ativa"].astype(bool)
    return df


def carregar_maquinas() -> list[dict]:
    """Máquinas ativas, com as colunas do cadastro (dicionários simples, para o cache)."""
    return db.consultar(f"SELECT {', '.join(COLUNAS_MAQUINA)} FROM maquinas WHERE ativa = 1 ORDER BY maquina")


def regras_maquinas(linhas: list[dict] | None = None) -> list[dict]:
    return montar_regras(linhas if linhas is not None else carregar_maquinas())


def salvar_maquinas(df: pd.DataFrame) -> dict:
    novos, erros = {}, []
    for i, r in enumerate(df.to_dict("records"), start=1):
        if all(_vazio(r.get(c)) for c in COLUNAS_MAQUINA if c != "ativa"):
            continue
        maquina = _txt(r.get("maquina"))
        if not maquina:
            erros.append(f"linha {i}: informe o nome da máquina como está no planejamento")
            continue
        grupos = _lista(r.get("formulacoes") if not _vazio(r.get("formulacoes")) else "")
        if not grupos:
            erros.append(f"{maquina}: informe ao menos um grupo de formulação")
        valores = {"maquina": maquina, "ativa": 0 if r.get("ativa") is False else 1, "formulacoes": ", ".join(grupos),
                   "nao_roda": ", ".join(_lista(r.get("nao_roda") if not _vazio(r.get("nao_roda")) else "")) or None,
                   "observacao": _txt(r.get("observacao"))}
        for campo in CAMPOS_FAIXA:
            try:
                valores[campo] = float(str(r.get(campo)).replace(",", "."))
                if pd.isna(valores[campo]):
                    raise ValueError
            except (TypeError, ValueError):
                erros.append(f"{maquina}: {campo.replace('_', ' ')} precisa ser um número")
        if maquina in novos:
            erros.append(f"{maquina}: máquina repetida")
        novos[maquina] = valores
    if erros:
        raise ValueError("; ".join(erros))
    atuais = {l["maquina"]: l for l in db.consultar("SELECT * FROM maquinas")}
    return _aplicar("maquinas", "maquina", atuais, novos, COLUNAS_MAQUINA)
