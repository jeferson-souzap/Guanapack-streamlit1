"""
Configuração fixa do app (o que pode mudar sem mexer no código fica no banco SQLite).

- Pastas dos relatórios: salvas no banco por usuário e PC (módulo Configuração). Os valores
  abaixo só servem de carga inicial e de último recurso.
- Nomes dos arquivos, parâmetros das regras e módulos ativos: também no banco, com os padrões daqui.
"""
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Banco SQLite: cadastros, locais, parâmetros, histórico, anotações e auditoria.
# Os relatórios do ERP NÃO vão para o banco: são lidos direto da pasta a cada consulta.
DADOS_DIR = BASE_DIR / "dados"
DATABASE = DADOS_DIR / "guanapack.sqlite3"
BACKUP_DIR = DADOS_DIR / "backup"

# Carga inicial dos cadastros (só na primeira execução, com a tabela vazia)
CADASTROS_DIR = BASE_DIR / "cadastros"
ARQ_FORMULACOES_RANK = CADASTROS_DIR / "FORMULACOES_RANK.csv"
ARQ_CLIENTES_PRIORITARIOS = CADASTROS_DIR / "CLIENTES_PRIORITARIOS.csv"
ARQ_MAQUINAS = CADASTROS_DIR / "MAQUINAS.csv"

# Pasta usada quando não há nada salvo para o usuário/PC
PASTA_PADRAO = r"G:\PCP\10. Programação\00. Diário\Jeferson\report"

# Locais gravados no banco na primeira execução: (usuário, PC) -> pasta. "*" = qualquer.
LOCAIS_INICIAIS = {
    ("*", "DESKTOP-MLEU7OA"): r"G:\Meu Drive\Guanapack\reports",
    ("*", "*"): PASTA_PADRAO,
}

# Variável de ambiente que passa por cima de tudo (útil para testar com outra pasta)
VAR_PASTA = "PCP_REPORTS_DIR"


@dataclass(frozen=True)
class Relatorio:
    chave: str
    titulo: str
    arquivo: str                      # nome padrão do arquivo na pasta
    colunas: tuple = field(default=())  # colunas que identificam o relatório (as que o app lê)


RELATORIOS = {
    r.chave: r for r in [
        Relatorio("estoque", "Estoque de pallets", "ESTOQUE_PALLETS.xls", (
            'tipo_estoque', 'site', 'rua', 'id_of', 'final_of', 'id_pa', 'desc_tecnica',
            'grupo_formulacao', 'peso_liquido', 'peso_bruto', 'qtd_pallets', 'pedido')),
        Relatorio("ctlr", "Controle de pedidos (CTLR)", "CTLR_PEDIDOS.xls", (
            'num_ped', 'num_prog', 'familia', 'desc_tec', 'dt_emissao', 'dt_aprovado', 'embarque',
            'dt_reserva', 'dt_romaneio', 'dt_faturamento', 'dt_entrega_cli', 'cancelado', 'anulado')),
        Relatorio("carteira", "Carteira de pedidos (PCP OF)", "PCP_OF_CARTEIRA_PEDIDO.xls", (
            'num_pedido', 'prog', 'cliente', 'dt_embarque', 'qtde_kg', 'tipo_venda', 'id_pa', 'produto',
            'formulacao')),
        Relatorio("solicitacoes", "Solicitações de reserva", "SOLICITACOES_RESERVA.xls", (
            'dt_solicitacao', 'num_pedido', 'seq')),
        Relatorio("planejamento", "Planejamento das máquinas", "PCP_PLANEJAMENTO_GERAL.xls", (
            'tipo_of', 'maquina', 'id_of', 'pedido', 'seq_prog', 'id_pa', 'produto', 'formulacao',
            'qtde_of', 'inicio_prev', 'final_prev', 'qtde_prod')),
    ]
}


@dataclass(frozen=True)
class Parametro:
    chave: str
    padrao: float
    tipo: str            # "int" ou "float"
    descricao: str
    grupo: str


# Parâmetros das regras. Os padrões são as regras combinadas com o usuário (planilha rev027):
# mudar aqui ou na tela muda o resultado da reserva/encaixe/OTD.
PARAMETROS = {
    p.chave: p for p in [
        Parametro("dias_otd", 2, "int", "Data OTD = embarque − N dias (OTD, encaixe e troca de embarque)", "Pedidos e OTD"),
        Parametro("tolerancia_qtd", 0.05, "float", "Tolerância da reserva sobre o qtde_kg do pedido (0,05 = ±5%)", "Reserva"),
        Parametro("tolerancia_micra", 2.0, "float", "Micra aceita no alternativo (± micra)", "Reserva"),
        Parametro("max_degraus_formulacao", 1, "int", "Degraus que o alternativo pode subir no rank de formulação", "Reserva"),
        Parametro("ordens_fixas", 3, "int", "Primeiras OFs de cada máquina que não mudam de lugar no encaixe", "Encaixe"),
        Parametro("dias_slow_move", 90, "int", "Pallet parado há mais de N dias conta como slow move (indicador)", "Estoque"),
        Parametro("dias_tolerancia_relatorio", 0, "int", "Relatório salvo há mais de N dias recebe aviso (0 = só hoje passa)", "Relatórios"),
    ]
}
