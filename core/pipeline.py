"""
Cadeia de cálculo, em memória, a partir dos relatórios da pasta:

    estoque ─┐
    carteira ┼─> reserva da carteira ─────────┐
    solicit. ┤                                ├─> encaixe em máquina / simulação da programação
    CTLR ────┴─> limpeza do CTLR ─> data OTD ─┤
    planej. ───> limpeza ─> extrusão stretch ─┘

Cada etapa fica em cache pela assinatura dos arquivos que usa (caminho + data + tamanho), pelos
cadastros e pelos parâmetros que a afetam. Mudar o cadastro de máquinas, por exemplo, refaz só o
encaixe; a limpeza e a reserva continuam do cache.

As regras ficam em core/regras (as mesmas do Guanapack-Flask, conferidas com a planilha Excel).
Os dataframes devolvidos são compartilhados pelo cache: não altere, faça .copy() antes.
"""
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import streamlit as st

from core import cadastros, contexto, relatorios
from core.regras import AtrasoOtd, EncaixeMaquinas, ReservaCarteira
from core.regras.AtrasoOtd import calcular_atraso_otd, mapa_data_otd
from core.regras.ConferenciaLimpeza import conferir_limpeza
from core.regras.EncaixeMaquinas import NAO_QUEBRAR, PODE_QUEBRAR, gerar_encaixe
from core.regras.LimpezaCtlrPedidos import eh_familia_valida, processar_dataframe_ctlr
from core.regras.LimpezaDataframe import processar_dataframe_estoque
from core.regras.LimpezaPlanejamento import filtrar_extrusao_stretch, processar_dataframe_planejamento
from core.regras.Prioridade import ListaPrioritarios
from core.regras.Maquinas import montar_regras
from core.regras.ReservaCarteira import sugerir_reservas


class FaltaRelatorio(Exception):
    """Relatório necessário não está na pasta ou não é o esperado."""


# ===================================================================== parâmetros das regras

def _aplicar_parametros(p: dict):
    """Os módulos de regra leem estas constantes na hora do cálculo."""
    AtrasoOtd.DIAS_OTD = EncaixeMaquinas.DIAS_OTD = int(p["dias_otd"])
    EncaixeMaquinas.ORDENS_FIXAS = int(p["ordens_fixas"])
    EncaixeMaquinas.SALTO_MICRA = float(p["salto_micra"])
    EncaixeMaquinas.ENCAIXAR_ALTERNATIVOS = bool(int(p.get("encaixar_alternativos", 0)))
    ReservaCarteira.TOLERANCIA_QTD = float(p["tolerancia_qtd"])
    ReservaCarteira.TOLERANCIA_MICRA = float(p["tolerancia_micra"])
    ReservaCarteira.MAX_DEGRAUS_FORMULACAO = int(p["max_degraus_formulacao"])


def _df(sig: tuple | None, chave: str) -> pd.DataFrame:
    if sig is None:
        raise FaltaRelatorio(chave)
    return relatorios.ler(*sig)


# ===================================================================== etapas (cache)

@st.cache_resource(show_spinner="Limpando o estoque…", max_entries=4)
def etapa_estoque(sig_estoque):
    original = _df(sig_estoque, "estoque")
    limpo = processar_dataframe_estoque(original)
    conf = conferir_limpeza(original, limpo, ['peso_liquido', 'peso_bruto', 'qtd_pallets'])
    return limpo, conf


@st.cache_resource(show_spinner="Limpando o CTLR…", max_entries=4)
def etapa_ctlr(sig_ctlr, sig_solic):
    original = _df(sig_ctlr, "ctlr")
    limpo = processar_dataframe_ctlr(original, _df(sig_solic, "solicitacoes"))
    conf = conferir_limpeza(original, limpo, ['qtde_com', 'peso', 'val_total', 'peso_entrega'],
                            filtro_original=eh_familia_valida, descricao_filtro="famílias stretch")
    return limpo, conf


@st.cache_resource(show_spinner="Lendo o planejamento…", max_entries=4)
def etapa_planejamento(sig_plan):
    original = _df(sig_plan, "planejamento")
    limpo = processar_dataframe_planejamento(original)
    conf = conferir_limpeza(original, limpo, ['qtde_prog', 'qtde_of', 'qtde_prod'])
    stretch = filtrar_extrusao_stretch(limpo)
    return limpo, stretch, conf


@st.cache_resource(show_spinner="Calculando o atraso OTD…", max_entries=4)
def etapa_atraso(sig_ctlr, sig_solic, sig_plan, hoje, dias_otd):
    AtrasoOtd.DIAS_OTD = int(dias_otd)
    ctlr, _ = etapa_ctlr(sig_ctlr, sig_solic)
    stretch = etapa_planejamento(sig_plan)[1] if sig_plan else pd.DataFrame()
    return calcular_atraso_otd(ctlr, stretch, hoje=hoje)


@st.cache_resource(show_spinner="Gerando a reserva da carteira…", max_entries=4)
def etapa_reserva(sig_carteira, sig_estoque, sig_solic, rank: tuple, prioritarios: tuple, params: tuple):
    _aplicar_parametros(dict(params))
    estoque, _ = etapa_estoque(sig_estoque)
    pedidos = sugerir_reservas(_df(sig_carteira, "carteira"), estoque, dict(rank), _df(sig_solic, "solicitacoes"),
                               ListaPrioritarios([dict(l) for l in prioritarios]))
    return pedidos.drop(columns=[c for c in ('linhas_cliente',) if c in pedidos])


@st.cache_resource(show_spinner="Encaixando os pedidos sem estoque nas máquinas…", max_entries=4)
def etapa_encaixe(chave_reserva: tuple, chave_atraso: tuple, sig_plan, maquinas: tuple, prioritarios: tuple,
                  params: tuple):
    _aplicar_parametros(dict(params))
    reserva = etapa_reserva(*chave_reserva)
    ctlr = etapa_atraso(*chave_atraso) if chave_atraso else None
    stretch = etapa_planejamento(sig_plan)[1]
    mapa = mapa_data_otd(ctlr[['num_ped', 'num_prog', 'data_otd']]) if ctlr is not None else {}
    regras = montar_regras([dict(m) for m in maquinas])
    rank = dict(chave_reserva[3])          # cadastro de formulações: sequência de formulação da máquina
    opcao = PODE_QUEBRAR if int(dict(params).get("pode_quebrar_sequencia", 0)) else NAO_QUEBRAR   # regra 7
    return gerar_encaixe(stretch, reserva, regras, ListaPrioritarios([dict(l) for l in prioritarios]), mapa,
                         rank=rank, opcao=opcao, salto_micra=float(dict(params).get("salto_micra", 5.0)),
                         encaixar_alternativos=bool(int(dict(params).get("encaixar_alternativos", 0))))


def entradas_encaixe(chave_reserva: tuple, chave_atraso: tuple, sig_plan, maquinas: tuple, prioritarios: tuple,
                     params: tuple) -> dict:
    """O que entra no encaixe (para a simulação da programação montar os cenários)."""
    _aplicar_parametros(dict(params))
    reserva = etapa_reserva(*chave_reserva)
    ctlr = etapa_atraso(*chave_atraso) if chave_atraso else None
    return {"plan": etapa_planejamento(sig_plan)[1], "reserva": reserva,
            "regras": montar_regras([dict(m) for m in maquinas]),
            "prioritarios": ListaPrioritarios([dict(l) for l in prioritarios]),
            "mapa": mapa_data_otd(ctlr[['num_ped', 'num_prog', 'data_otd']]) if ctlr is not None else {},
            "rank": dict(chave_reserva[3])}


# ===================================================================== fachada

def _tupla(linhas: list[dict]) -> tuple:
    return tuple(tuple(sorted(l.items())) for l in linhas)


@dataclass
class Contexto:
    """Tudo o que entra no cálculo agora (pasta, assinaturas dos arquivos, cadastros, parâmetros)."""
    pasta: str
    origem_pasta: str
    hoje: str
    sig: dict
    situacao: dict
    params: dict
    rank: tuple
    prioritarios: tuple
    maquinas: tuple
    erros: dict = field(default_factory=dict)

    def ok(self, *chaves) -> bool:
        return all(self.situacao[c]["situacao"] != "ERRO" for c in chaves)

    def faltando(self, *chaves) -> list[str]:
        return [self.situacao[c]["titulo"] for c in chaves if self.situacao[c]["situacao"] == "ERRO"]

    # chaves das etapas ---------------------------------------------------------------
    @property
    def _params(self) -> tuple:
        return tuple(sorted(self.params.items()))

    @property
    def chave_atraso(self):
        if not self.ok("ctlr", "solicitacoes"):
            return None
        return (self.sig["ctlr"], self.sig["solicitacoes"], self.sig["planejamento"] if self.ok("planejamento") else None,
                self.hoje, int(self.params["dias_otd"]))

    @property
    def chave_reserva(self):
        if not self.ok("carteira", "estoque", "solicitacoes") or not self.rank:
            return None
        return (self.sig["carteira"], self.sig["estoque"], self.sig["solicitacoes"], self.rank, self.prioritarios,
                self._params)

    @property
    def chave_encaixe(self):
        if self.chave_reserva is None or not self.ok("planejamento") or not self.maquinas:
            return None
        return (self.chave_reserva, self.chave_atraso, self.sig["planejamento"], self.maquinas, self.prioritarios,
                self._params)

    # resultados ----------------------------------------------------------------------
    def estoque(self):
        if not self.ok("estoque"):
            raise FaltaRelatorio(", ".join(self.faltando("estoque")))
        return etapa_estoque(self.sig["estoque"])[0]

    def ctlr(self):
        if self.chave_atraso is None:
            raise FaltaRelatorio(", ".join(self.faltando("ctlr", "solicitacoes")))
        return etapa_atraso(*self.chave_atraso)

    def planejamento(self):
        if not self.ok("planejamento"):
            raise FaltaRelatorio(", ".join(self.faltando("planejamento")))
        return etapa_planejamento(self.sig["planejamento"])

    def reserva(self):
        if self.chave_reserva is None:
            raise FaltaRelatorio(", ".join(self.faltando("carteira", "estoque", "solicitacoes"))
                                 or "nenhuma formulação cadastrada (Cadastros > Formulações)")
        return etapa_reserva(*self.chave_reserva)

    def encaixe(self):
        """(pedidos, filas, resumo)."""
        if self.chave_encaixe is None:
            motivo = ", ".join(self.faltando("carteira", "estoque", "solicitacoes", "planejamento"))
            if not motivo:
                motivo = ("nenhuma máquina ativa (Cadastros > Máquinas)" if not self.maquinas
                          else "nenhuma formulação cadastrada (Cadastros > Formulações)")
            raise FaltaRelatorio(motivo)
        return etapa_encaixe(*self.chave_encaixe)

    def entradas_encaixe(self) -> dict:
        """Planejamento, reserva, máquinas, prioritários, data OTD e rank (simulação da programação)."""
        if self.chave_encaixe is None:
            self.encaixe()                 # levanta FaltaRelatorio com o motivo, como no encaixe
        return entradas_encaixe(*self.chave_encaixe)


def montar_contexto() -> Contexto:
    """Lê o estado atual (rápido: só stat dos arquivos e consultas pequenas no banco)."""
    conferir_versao_cache()
    pasta, origem = contexto.pasta_relatorios()
    params = contexto.parametros()
    situacao = relatorios.conferir_todos(pasta, int(params["dias_tolerancia_relatorio"]))
    sig = {}
    for chave in situacao:
        arq = relatorios.arquivo(chave, pasta)
        sig[chave] = arq.assinatura if arq else None
    return Contexto(
        pasta=str(pasta), origem_pasta=origem, hoje=pd.Timestamp.now().strftime("%Y-%m-%d"), sig=sig,
        situacao=situacao, params=params, rank=tuple(sorted(cadastros.carregar_rank().items())),
        prioritarios=_tupla(cadastros.carregar_prioritarios()), maquinas=_tupla(cadastros.carregar_maquinas()),
    )


_RAIZ = Path(__file__).resolve().parent.parent
_ARQUIVOS_CODIGO = ("config.py", "core/*.py", "core/regras/*.py")


def assinatura_codigo() -> str:
    """Hash do código que monta os resultados em cache. O st.cache_resource só se invalida quando muda o
    corpo da própria função em cache, não as regras que ela chama: depois de um deploy, a página nova
    receberia um resultado calculado pelo código antigo (ex.: KeyError numa coluna nova)."""
    h = hashlib.sha1()
    for padrao in _ARQUIVOS_CODIGO:
        for arq in sorted(_RAIZ.glob(padrao)):
            h.update(arq.relative_to(_RAIZ).as_posix().encode())
            h.update(arq.read_bytes())
    return h.hexdigest()


@st.cache_resource
def _codigo_em_cache() -> dict:
    """Assinatura do código com que o cache atual foi calculado (compartilhada por todas as sessões)."""
    return {"assinatura": None}


def conferir_versao_cache():
    """Apaga o cache das etapas se o código mudou desde o último cálculo."""
    atual, guardada = assinatura_codigo(), _codigo_em_cache()
    if guardada["assinatura"] != atual:    # None = primeira vez neste processo: limpa também, por garantia
        limpar_cache()
        guardada["assinatura"] = atual


def limpar_cache():
    for etapa in (etapa_estoque, etapa_ctlr, etapa_planejamento, etapa_atraso, etapa_reserva, etapa_encaixe,
                  relatorios.ler):
        etapa.clear()
    st.cache_data.clear()
