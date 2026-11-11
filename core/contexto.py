"""
Quem está usando (usuário do Windows e PC), onde estão os relatórios e o que está configurado.

Pasta dos relatórios, na ordem:
1. variável de ambiente PCP_REPORTS_DIR (para testes);
2. local salvo para este usuário neste PC;
3. local salvo para qualquer usuário neste PC  (usuario = "*");
4. local salvo para este usuário em qualquer PC (pc = "*");
5. local geral (usuario = "*", pc = "*");
6. config.PASTA_PADRAO.

Se a pasta escolhida (itens 2 a 6) não existe neste computador (ex.: app na nuvem, sem o drive G:),
usa config.PASTA_ENVIADOS, onde ficam os relatórios enviados pelo navegador.
"""
import getpass
import os
import socket
from pathlib import Path

import config
from core import db


def usuario() -> str:
    try:
        return (os.environ.get("USERNAME") or getpass.getuser() or "desconhecido").lower()
    except Exception:
        return "desconhecido"


def pc() -> str:
    return (socket.gethostname() or "desconhecido").upper()


# ===================================================================== pasta dos relatórios

def pasta_relatorios() -> tuple[Path, str]:
    """(pasta, de onde veio) para o usuário e o PC atuais."""
    if os.environ.get(config.VAR_PASTA):
        return Path(os.environ[config.VAR_PASTA]), f"variável de ambiente {config.VAR_PASTA}"
    pasta, origem = _pasta_configurada()
    try:
        existe = pasta.is_dir()
    except OSError:
        existe = False
    if not existe:
        return config.PASTA_ENVIADOS, f"relatórios enviados pelo navegador; a pasta {pasta} não existe aqui"
    return pasta, origem


def usando_enviados() -> bool:
    """True quando o app está lendo os relatórios enviados pelo navegador."""
    try:
        return pasta_relatorios()[0].resolve() == config.PASTA_ENVIADOS.resolve()
    except OSError:
        return False


def _pasta_configurada() -> tuple[Path, str]:
    u, p = usuario(), pc()
    tentativas = [((u, p), "salva para você neste PC"), (("*", p), "salva para este PC"),
                  ((u, "*"), "salva para você (qualquer PC)"), (("*", "*"), "local geral")]
    locais = {(l["usuario"].lower() if l["usuario"] != "*" else "*", l["pc"].upper() if l["pc"] != "*" else "*"): l["pasta"]
              for l in db.consultar("SELECT usuario, pc, pasta FROM locais_relatorios")}
    for chave, origem in tentativas:
        if chave in locais:
            return Path(locais[chave]), origem
    return Path(config.PASTA_PADRAO), "padrão do sistema"


def listar_locais():
    return db.consultar_df("SELECT id, usuario, pc, pasta, observacao, atualizado_em FROM locais_relatorios "
                           "ORDER BY pc = '*', pc, usuario = '*', usuario")


def salvar_local(pasta: str, para_usuario: str, para_pc: str, observacao: str = ""):
    pasta = (pasta or "").strip().strip('"')
    if not pasta:
        raise ValueError("Informe a pasta.")
    para_usuario = (para_usuario or "*").strip().lower() or "*"
    para_pc = (para_pc or "*").strip().upper() or "*"
    with db.conectar() as c:
        antes = c.execute("SELECT pasta FROM locais_relatorios WHERE usuario = ? AND pc = ?",
                          (para_usuario, para_pc)).fetchone()
        c.execute("INSERT INTO locais_relatorios (usuario, pc, pasta, observacao, atualizado_em) VALUES (?, ?, ?, ?, ?) "
                  "ON CONFLICT (usuario, pc) DO UPDATE SET pasta = excluded.pasta, observacao = excluded.observacao, "
                  "atualizado_em = excluded.atualizado_em",
                  (para_usuario, para_pc, pasta, observacao or None, db.agora()))
        db.auditar(c, "locais_relatorios", "alterou" if antes else "incluiu", f"{para_usuario}@{para_pc}",
                   {"pasta": antes["pasta"]} if antes else None, {"pasta": pasta}, usuario(), pc())


def excluir_local(id_local: int):
    with db.conectar() as c:
        antes = c.execute("SELECT * FROM locais_relatorios WHERE id = ?", (int(id_local),)).fetchone()
        if antes is None:
            return
        c.execute("DELETE FROM locais_relatorios WHERE id = ?", (int(id_local),))
        db.auditar(c, "locais_relatorios", "excluiu", f"{antes['usuario']}@{antes['pc']}", dict(antes), None,
                   usuario(), pc())


# ===================================================================== arquivos

def arquivos_relatorios() -> dict[str, str]:
    """Nome do arquivo de cada relatório (chave -> arquivo)."""
    salvos = {l["chave"]: l["arquivo"] for l in db.consultar("SELECT chave, arquivo FROM arquivos_relatorios")}
    return {chave: salvos.get(chave, rel.arquivo) for chave, rel in config.RELATORIOS.items()}


def salvar_arquivo_relatorio(chave: str, arquivo: str):
    arquivo = (arquivo or "").strip() or config.RELATORIOS[chave].arquivo
    with db.conectar() as c:
        antes = c.execute("SELECT arquivo FROM arquivos_relatorios WHERE chave = ?", (chave,)).fetchone()
        if antes and antes["arquivo"] == arquivo:
            return
        c.execute("INSERT OR REPLACE INTO arquivos_relatorios (chave, arquivo) VALUES (?, ?)", (chave, arquivo))
        db.auditar(c, "arquivos_relatorios", "alterou", chave, {"arquivo": antes["arquivo"]} if antes else None,
                   {"arquivo": arquivo}, usuario(), pc())


# ===================================================================== parâmetros

def parametros() -> dict[str, float]:
    """Valor de cada parâmetro (o padrão de config.PARAMETROS quando não foi alterado)."""
    salvos = {l["chave"]: l["valor"] for l in db.consultar("SELECT chave, valor FROM parametros")}
    valores = {}
    for chave, p in config.PARAMETROS.items():
        bruto = salvos.get(chave)
        try:
            valor = float(bruto) if bruto is not None else p.padrao
        except ValueError:
            valor = p.padrao
        valores[chave] = int(valor) if p.tipo == "int" else valor
    return valores


def salvar_parametro(chave: str, valor):
    p = config.PARAMETROS[chave]
    valor = int(valor) if p.tipo == "int" else float(valor)
    anterior = parametros()[chave]
    if anterior == valor:
        return
    with db.conectar() as c:
        if valor == p.padrao:
            c.execute("DELETE FROM parametros WHERE chave = ?", (chave,))
        else:
            c.execute("INSERT OR REPLACE INTO parametros (chave, valor, atualizado_em, atualizado_por) VALUES (?, ?, ?, ?)",
                      (chave, str(valor), db.agora(), f"{usuario()}@{pc()}"))
        db.auditar(c, "parametros", "alterou", chave, {"valor": anterior}, {"valor": valor}, usuario(), pc())


# ===================================================================== módulos e preferências

def modulos_estado() -> dict[str, dict]:
    return {l["id"]: l for l in db.consultar("SELECT id, ativo, ordem FROM modulos")}


def salvar_modulo(id_modulo: str, ativo: bool, ordem: int):
    with db.conectar() as c:
        c.execute("INSERT OR REPLACE INTO modulos (id, ativo, ordem) VALUES (?, ?, ?)", (id_modulo, int(ativo), int(ordem)))


def preferencia(chave: str, padrao=None):
    linha = db.consultar("SELECT valor FROM preferencias WHERE usuario = ? AND chave = ?", (usuario(), chave))
    return linha[0]["valor"] if linha else padrao


def salvar_preferencia(chave: str, valor):
    db.executar("INSERT OR REPLACE INTO preferencias (usuario, chave, valor) VALUES (?, ?, ?)",
                (usuario(), chave, None if valor is None else str(valor)))
