"""
Versão do app, tirada do git: commit, data e mensagem do último commit, e se há alterações locais
ainda não enviadas. Lida uma vez quando o app sobe (um deploy novo reinicia o app e lê de novo).
"""
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
