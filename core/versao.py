"""
Versão do app, tirada do git: commit, data e mensagem do último commit, e se há alterações locais
ainda não enviadas. Lida uma vez quando o app sobe (um deploy novo reinicia o app e lê de novo).
"""
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import streamlit as st

import config

BRASILIA = timezone(timedelta(hours=-3))  # o servidor na nuvem roda em UTC


def _agora() -> datetime:
    return datetime.now(BRASILIA).replace(tzinfo=None)


@dataclass(frozen=True)
class Versao:
    commit: str = ""
    data: datetime | None = None
    mensagem: str = ""
    alteracoes_locais: bool = False
    iniciado_em: datetime | None = None

    @property
    def texto(self) -> str:
        if not self.commit:
            return "versão desconhecida (sem git)"
        data = f" de {self.data:%d/%m/%Y %H:%M}" if self.data else ""
        return f"versão {self.commit}{data}" + (" + alterações locais" if self.alteracoes_locais else "")


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=config.BASE_DIR, capture_output=True, text=True, encoding="utf-8",
                       timeout=5)
    if r.returncode != 0:
        raise OSError(r.stderr.strip())
    return r.stdout.strip()


def ler() -> Versao:
    agora = _agora()
    try:
        commit, data, mensagem = _git("log", "-1", "--format=%h%x1f%cI%x1f%s").split("\x1f", 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return Versao(iniciado_em=agora)
    try:
        alteracoes = bool(_git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        alteracoes = False
    try:
        quando = datetime.fromisoformat(data).astimezone(BRASILIA).replace(tzinfo=None)
    except ValueError:
        quando = None
    return Versao(commit, quando, mensagem, alteracoes, agora)


# ===================================================================== código desatualizado na memória

def _marca(arquivo: str) -> tuple | None:
    try:
        s = os.stat(arquivo)
    except OSError:
        return None
    return (s.st_mtime_ns, s.st_size)


@st.cache_resource(show_spinner=False)
def _marcas_dos_modulos() -> dict:
    """(nome, id do módulo) -> marca do arquivo quando o módulo foi visto pela primeira vez. Fica no cache do
    processo: sobrevive às recargas da página e ao recarregamento deste próprio arquivo."""
    return {}


def modulos_desatualizados() -> list[str]:
    """Módulos do app cujo arquivo mudou no disco depois de carregados (ex.: um deploy que não recarregou o
    config.py). O módulo recarregado é outro objeto (outro id) e começa com a marca nova, então só sobra
    aqui o que continua rodando com o código antigo. Rodar a cada recarga da página, logo no início."""
    marcas = _marcas_dos_modulos()
    raiz = os.path.normcase(str(config.BASE_DIR)) + os.sep
    antigos = []
    for nome, modulo in list(sys.modules.items()):
        arquivo = getattr(modulo, "__file__", None)
        caminho = os.path.normcase(os.path.abspath(arquivo)) if arquivo else ""
        if not caminho.startswith(raiz) or f"{os.sep}.venv{os.sep}" in caminho:
            continue
        atual = _marca(arquivo)
        vista = marcas.setdefault((nome, id(modulo)), atual)
        if vista != atual:
            antigos.append(nome)
    return sorted(antigos)
