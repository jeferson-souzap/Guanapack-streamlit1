"""
Registro dos módulos (páginas) do app.

Cada módulo é um arquivo em modulos/. Para criar um novo: escreva o arquivo e inclua uma linha
em MODULOS. Ativar/desativar e a ordem ficam no banco (Configuração > Módulos); os marcados
como fixos não podem ser desligados.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Modulo:
    id: str
    titulo: str
    icone: str | None
    arquivo: str
    grupo: str
    descricao: str
    fixo: bool = False


MODULOS = [
    Modulo("inicio", "Início", None, "modulos/inicio.py", "", "Situação dos relatórios e atalhos", fixo=True),
    Modulo("enviar", "Enviar relatórios", None, "modulos/enviar.py", "",
           "Enviar os relatórios do ERP pelo navegador (app na nuvem)", fixo=True),
    Modulo("consulta", "Consulta de pedido", None, "modulos/consulta.py", "Programação",
           "Tudo sobre um pedido numa tela: CTLR, estoque, reserva, encaixe, planejamento e simulação"),
    Modulo("simulacao", "Simulação da programação", None, "modulos/simulacao.py", "Programação",
           "Cenários de fila das máquinas: escolher as regras, mexer na fila à mão e comparar"),
    Modulo("reserva", "Reserva de estoque", None, "modulos/reserva.py", "Programação",
           "Qual pallet do estoque reservar para cada pedido da carteira (exato ou alternativo)"),
    Modulo("encaixe", "Encaixe em máquinas", None, "modulos/encaixe.py", "Programação",
           "Onde encaixar os pedidos sem estoque"),
    Modulo("cadastros", "Cadastros", None, "modulos/cadastros.py", "Ajustes",
           "Rank de formulações, clientes prioritários e máquinas", fixo=True),
    Modulo("configuracao", "Configuração", None, "modulos/configuracao.py", "Ajustes",
           "Pasta dos relatórios por usuário/PC, parâmetros e módulos", fixo=True),
]

POR_ID = {m.id: m for m in MODULOS}
