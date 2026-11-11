"""
Relatórios do ERP lidos direto da pasta (sem passar pelo banco).

Cada relatório é conferido antes de ser usado (existe? abre? tem as colunas esperadas? é de
hoje?). A leitura fica em cache pela "assinatura" do arquivo (caminho + data de gravação +
tamanho): enquanto o .xls não muda, o app não lê de novo; quando alguém salva um relatório novo,
a próxima consulta já usa o novo.
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from core import contexto


@dataclass(frozen=True)
class Arquivo:
    chave: str
    caminho: str
    mtime: float
    tamanho: int

    @property
    def assinatura(self) -> tuple:
        return (self.caminho, self.mtime, self.tamanho)


def caminho(chave: str, pasta: Path | None = None) -> Path:
    pasta = pasta or contexto.pasta_relatorios()[0]
    return Path(pasta) / contexto.arquivos_relatorios()[chave]


def arquivo(chave: str, pasta: Path | None = None) -> Arquivo | None:
    p = caminho(chave, pasta)
    try:
        s = p.stat()
    except OSError:
        return None
    return Arquivo(chave, str(p), s.st_mtime, s.st_size)


@st.cache_data(show_spinner=False, max_entries=50)
def _colunas(caminho_arquivo: str, mtime: float, tamanho: int) -> list[str] | None:
    try:
        return [str(c).strip() for c in pd.read_excel(caminho_arquivo, nrows=0).columns]
    except Exception:
        return None


@st.cache_resource(show_spinner=False, max_entries=12)
def ler(caminho_arquivo: str, mtime: float, tamanho: int) -> pd.DataFrame:
    """Lê o relatório (cache pela assinatura). Não altere o dataframe devolvido: faça .copy()."""
    return pd.read_excel(caminho_arquivo)


def ler_relatorio(arq: Arquivo) -> pd.DataFrame:
    return ler(*arq.assinatura)


def _quando(salvo: datetime) -> tuple[str, int]:
    dias = (datetime.now().date() - salvo.date()).days
    texto = "hoje" if dias == 0 else "ontem" if dias == 1 else f"há {dias} dias"
    return texto, dias


def conferir(chave: str, pasta: Path | None = None, tolerancia_dias: int = 0) -> dict:
    """Situação do relatório: OK, AVISO (antigo) ou ERRO (falta, não abre ou não é o relatório)."""
    rel = config.RELATORIOS[chave]
    p = caminho(chave, pasta)
    base = {"chave": chave, "titulo": rel.titulo, "arquivo": p.name, "caminho": str(p), "salvo_em": None}
    arq = arquivo(chave, pasta)
    if arq is None:
        return {**base, "situacao": "ERRO", "mensagem": "arquivo não encontrado na pasta"}
    salvo = datetime.fromtimestamp(arq.mtime)
    quando, dias = _quando(salvo)
    base.update(salvo_em=salvo, quando=quando, dias=dias)
    colunas = _colunas(*arq.assinatura)
    if colunas is None:
        return {**base, "situacao": "ERRO", "mensagem": "não foi possível abrir (corrompido, aberto no Excel ou não é Excel)"}
    faltando = [c for c in rel.colunas if c not in colunas]
    if faltando:
        msg = f"não é o relatório esperado; faltam: {', '.join(faltando[:5])}" + (
            f" e mais {len(faltando) - 5}" if len(faltando) > 5 else "")
        parece = [r.arquivo for r in config.RELATORIOS.values() if r.chave != chave and set(r.colunas) <= set(colunas)]
        if parece:
            msg += f" (o conteúdo parece ser do {parece[0]})"
        return {**base, "situacao": "ERRO", "mensagem": msg}
    if dias > tolerancia_dias:
        return {**base, "situacao": "AVISO", "mensagem": f"salvo {quando} ({salvo:%d/%m/%Y %H:%M}); confira se é a versão atual"}
    return {**base, "situacao": "OK", "mensagem": f"salvo {quando} às {salvo:%H:%M}"}


def conferir_todos(pasta: Path | None = None, tolerancia_dias: int = 0) -> dict[str, dict]:
    return {chave: conferir(chave, pasta, tolerancia_dias) for chave in config.RELATORIOS}
