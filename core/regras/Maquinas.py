"""
Regras das máquinas de stretch usadas no encaixe (vieram do Regras-Maquinas.xlsx).

Parte "pura" do ConfigMaquinas do Guanapack-Flask: o cadastro fica no SQLite (core/db.py).

formulacoes: grupos aceitos, separados por vírgula (QUANTUM, STIFF, PCR, PRE-ESTIRADO, UV ou as
             2 primeiras letras: FM, MN, MO).
nao_roda:    palavras na família, formulação ou descrição que barram o produto (ex.: CORELESS).
Faixas de micra, peso da bobina (kg), peso do tubete (kg) e largura (mm) lidas da descrição
(largura X micra X ... X peso X tubete).
"""
import re

CAMPOS_FAIXA = ['micra_min', 'micra_max', 'peso_min', 'peso_max', 'tubete_min', 'tubete_max',
                'largura_min', 'largura_max']


def _lista(texto) -> list[str]:
    return [p.strip().upper() for p in re.split(r"[,;]", texto or "") if p.strip()]


def apelido(maquina: str) -> str:
    """"GNP - Extrusora ST 01 (Davis)" -> "Davis"."""
    achado = re.search(r"\(([^()]*)\)\s*$", maquina or "")
    return achado.group(1) if achado else (maquina or "")


def montar_regras(linhas) -> list[dict]:
    """Regras prontas para o encaixe (listas em maiúsculas e faixas numéricas).

    linhas: cadastro das máquinas (dicionários com as colunas da tabela maquinas).
    """
    regras = []
    for linha in linhas:
        r = dict(linha)
        r['grupos'] = _lista(r.get('formulacoes'))
        r['palavras_nao_roda'] = _lista(r.get('nao_roda'))
        r['apelido'] = apelido(r['maquina'])
        regras.append(r)
    return regras
