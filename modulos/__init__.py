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
    Modulo("inicio", "Início", None, "modulos/inicio.py", "", "Situação dos relatórios e resumo do dia", fixo=True),
    Modulo("enviar", "Enviar relatórios", None, "modulos/enviar.py", "",
           "Enviar os relatórios do ERP pelo navegador (app na nuvem)", fixo=True),
    Modulo("consulta", "Consulta de pedido", None, "modulos/consulta.py", "Operação",
           "Tudo sobre um pedido em uma tela, com anotações"),
    Modulo("pedidos", "Pedidos e OTD", None, "modulos/pedidos.py", "Operação",
           "Pedidos atrasados e que vão atrasar (data OTD)"),
    Modulo("estoque", "Estoque", None, "modulos/estoque.py", "Operação", "Pallets em estoque, dias parado e slow move"),
    Modulo("reserva", "Reserva da carteira", None, "modulos/reserva.py", "Planejamento",
           "Sugestão de reserva de estoque para a carteira"),
    Modulo("encaixe", "Encaixe em máquinas", None, "modulos/encaixe.py", "Planejamento",
           "Onde encaixar os pedidos sem estoque"),
    Modulo("maquinas", "Planejamento das máquinas", None, "modulos/maquinas.py", "Planejamento",
           "Fila de cada máquina com a reserva de cada OF"),
    Modulo("insumos", "Tubetes e pallets", None, "modulos/insumos.py", "Planejamento",
           "Consumo de tubetes e pallets, com e sem encaixe"),
    Modulo("troca", "Troca de embarque", None, "modulos/troca.py", "Planejamento",
           "Pedidos novos que precisam de troca de data de embarque"),
    Modulo("historico", "Histórico", None, "modulos/historico.py", "Gestão",
           "Evolução dos indicadores, execuções e auditoria"),
    Modulo("cadastros", "Cadastros", None, "modulos/cadastros.py", "Gestão",
           "Rank de formulações, clientes prioritários e máquinas", fixo=True),
    Modulo("configuracao", "Configuração", None, "modulos/configuracao.py", "Gestão",
           "Pasta dos relatórios por usuário/PC, parâmetros e módulos", fixo=True),
]

POR_ID = {m.id: m for m in MODULOS}
