"""
Clientes prioritários: clientes que não podem atrasar (cadastro no módulo Cadastros).

Parte "pura" do ConfigPrioridade do Guanapack-Flask (sem banco): o cadastro fica no SQLite
(core/db.py) e chega aqui como uma lista de dicionários.

Cada linha: cliente (parte do nome), material e formulação (parte do texto; vazio = qualquer).
Maiúsculas, acentos e espaços repetidos não importam.
Ex.: cliente "Braskem" e formulação "QUANTUM" -> todo pedido Quantum de qualquer unidade da Braskem
("Braskem - Triunfo (1203)", "Braskem - Duque de Caxias (9355)"...). O material é procurado na
descrição do produto e na formulação (ex.: "JUMBO", "QUANTUM").

Onde a lista é usada:
- Reserva da carteira: o pallet kanban de um cliente da lista (cliente_kanban) vai primeiro para os
  pedidos desse cliente (aqui só o nome do cliente conta); o que sobrar vai para os outros pedidos.
- Encaixe em máquina: o pedido que casa com a linha inteira (cliente, material e formulação) é
  encaixado antes dos outros, e nenhum outro encaixe pode fazê-lo atrasar.
"""
import unicodedata
from dataclasses import dataclass


def texto_comparavel(valor) -> str:
    """Maiúsculas, sem acento e com um espaço só: "  Cervejaria  Petrópolis " -> "CERVEJARIA PETROPOLIS"."""
    if valor is None or (isinstance(valor, float) and valor != valor):
        return ""
    texto = unicodedata.normalize("NFD", str(valor).upper())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(texto.split())


@dataclass(frozen=True)
class Prioritario:
    cliente: str
    material: str
    formulacao: str


class ListaPrioritarios:
    """Regras de prioridade já normalizadas para comparar."""

    def __init__(self, linhas):
        self.linhas = [Prioritario(texto_comparavel(l["cliente"]), texto_comparavel(l.get("material")),
                                   texto_comparavel(l.get("formulacao")))
                       for l in linhas if texto_comparavel(l["cliente"])]

    def linhas_do_cliente(self, cliente) -> frozenset:
        """Índices das linhas em que o cliente aparece, só pelo nome (vazio = nenhuma)."""
        c = texto_comparavel(cliente)
        if not c:
            return frozenset()
        return frozenset(i for i, p in enumerate(self.linhas) if p.cliente in c)

    def pedido_prioritario(self, cliente, produto, formulacao) -> bool:
        """O pedido casa com alguma linha inteira (cliente, material e formulação)?"""
        c, p, f = texto_comparavel(cliente), texto_comparavel(produto), texto_comparavel(formulacao)
        if not c:
            return False
        for regra in self.linhas:
            if regra.cliente in c \
                    and (not regra.material or regra.material in p or regra.material in f) \
                    and (not regra.formulacao or regra.formulacao in f):
                return True
        return False
