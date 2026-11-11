from datetime import datetime
import re
import numpy as np
import pandas as pd

from core.regras.LimpezaDataframe import extrair_familia, parse_dimensoes, remover_peso_tubete


# Prefixo de classificação do produto (ex.: "A - FILME STRETCH ...")
_PADRAO_PREFIXO = re.compile(r"^\s*[A-Z]\s*-\s*")

# Famílias mantidas na análise (as demais são descartadas)
FAMILIAS_VALIDAS = ["FILME STRETCH", "FILME STRETCH BLUE"]

# Status considerados em aberto (usados no lead time de estoque)
STATUS_EM_ABERTO = ["AGUARDANDO APROVAÇÃO", "EM CARTEIRA", "SOLICITAÇÃO DE RESERVA", "RESERVADO"]


def normalizar_desc_tecnica(desc: str) -> str:
    """Remove o prefixo ("A - ") e os espaços repetidos, deixando no mesmo formato do estoque."""
    if not isinstance(desc, str):
        return ""
    texto = re.sub(r"\s+", " ", desc).strip()
    return _PADRAO_PREFIXO.sub("", texto)


def eh_familia_valida(df: pd.DataFrame) -> pd.Series:
    """Linhas das famílias mantidas na análise (usado na limpeza e na conferência)."""
    return df['familia'].astype(str).str.strip().str.upper().isin(FAMILIAS_VALIDAS)


def calcular_status_pedido(df: pd.DataFrame, chaves_solicitacao: set) -> pd.Series:
    """Define o status do pedido pela etapa mais avançada (a primeira condição verdadeira vence).

    CANCELADO só com cancelado = SIM. anulado = SIM é a NF anulada depois do faturamento (o pedido não
    foi cancelado): com entrega ao cliente fica ENTREGUE; sem entrega, NF ANULADA (decisão do usuário
    em 10/11/2026; antes o anulado contava como cancelado).
    """
    chave = list(zip(df['num_ped'], df['num_prog']))
    tem_solicitacao = pd.Series([k in chaves_solicitacao for k in chave], index=df.index)
    sim = lambda col: df[col].astype(str).str.strip().str.upper() == 'SIM'

    condicoes = [
        sim('cancelado'),
        df['dt_entrega_cli'].notna(),
        sim('anulado'),
        df['dt_faturamento'].notna(),
        df['dt_romaneio'].notna(),
        df['dt_reserva'].notna(),
        tem_solicitacao,
        df['dt_aprovado'].notna(),
    ]
    status = ['CANCELADO', 'ENTREGUE', 'NF ANULADA', 'FATURADO', 'EM ROMANEIO', 'RESERVADO',
              'SOLICITAÇÃO DE RESERVA', 'EM CARTEIRA']
    return pd.Series(np.select(condicoes, status, default='AGUARDANDO APROVAÇÃO'), index=df.index)


def processar_dataframe_ctlr(df: pd.DataFrame, df_solicitacoes: pd.DataFrame) -> pd.DataFrame:
    """Aplica as mesmas transformações do estoque no DataFrame de controle de pedidos."""
    # 0. Mantém somente as famílias de stretch
    df_proc = df[eh_familia_valida(df)].copy()

    # 1. Descrição técnica no padrão do estoque
    df_proc['desc_tecnica'] = df_proc['desc_tec'].map(normalizar_desc_tecnica)

    # 2. Extração da família
    df_proc['tipo_familia_teste'] = df_proc['desc_tecnica'].map(extrair_familia)

    # 3. Parsing das dimensões e descrição alternativa
    dimensoes = df_proc['desc_tecnica'].apply(parse_dimensoes)
    df_proc[['largura', 'micra', 'peso_desc', 'peso_tubete']] = dimensoes
    df_proc['desc_alternativa'] = df_proc['desc_tecnica'].apply(remover_peso_tubete)

    # 4. Tratamento de nulos e tipos de dados
    df_proc['peso_tubete'] = df_proc['peso_tubete'].fillna(0)

    agora = datetime.now().astimezone()
    dt_hoje = agora.strftime("%Y-%m-%d")
    df_proc['import_data'] = dt_hoje
    df_proc['import_data_hora'] = agora.isoformat(timespec="seconds")

    colunas_numericas = ['largura', 'micra', 'peso_desc', 'peso_tubete']
    for col in colunas_numericas:
        if col in df_proc.columns:
            df_proc[col] = pd.to_numeric(df_proc[col], errors='coerce')

    # Datas vazias vêm do ERP como "  -   -" e viram nulo
    colunas_datas = ['dt_emissao', 'dt_aprovado', 'dt_cancelado', 'ipi_validade', 'embarque_orig',
                     'embarque', 'entrega_orig', 'entrega', 'prev_prod', 'dt_reserva', 'dt_romaneio',
                     'dt_tms', 'dt_faturamento', 'dt_entrega_cli', 'dt_cancelamento', 'dt_anulacao',
                     'dt_agendamento', 'import_data']
    for col in colunas_datas:
        if col in df_proc.columns:
            df_proc[col] = pd.to_datetime(df_proc[col], errors='coerce', format='mixed', dayfirst=True)

    # 5. Status do pedido (solicitação de reserva vem do relatório SOLICITACOES_RESERVA,
    #    cruzando pedido + programação: seq da solicitação = num_prog do CTLR)
    chaves_solicitacao = set(zip(df_solicitacoes['num_pedido'], df_solicitacoes['seq']))
    df_proc['status_pedido'] = calcular_status_pedido(df_proc, chaves_solicitacao)
    cancelado = df_proc['status_pedido'] == 'CANCELADO'

    # 6. Atraso OTD: faturamento (ou hoje, se não faturado) contra a data de embarque atual
    hoje = pd.Timestamp.now().normalize()
    data_realizada = df_proc['dt_faturamento'].dt.normalize().fillna(hoje)
    dias_atraso = (data_realizada - df_proc['embarque']).dt.days
    df_proc['otd_dias_atraso'] = dias_atraso.clip(lower=0).where(~cancelado)
    df_proc['otd_status'] = np.where(dias_atraso > 0, 'ATRASADO', 'NO PRAZO')
    df_proc.loc[cancelado | dias_atraso.isna(), 'otd_status'] = None

    # 7. Lead time de estoque: pedido em aberto com embarque para o dia da emissão ou o seguinte.
    #    Usa o embarque atual para o pedido sair da lista quando o comercial trocar a data.
    dias_emissao_embarque = (df_proc['embarque'] - df_proc['dt_emissao'].dt.normalize()).dt.days
    em_aberto = df_proc['status_pedido'].isin(STATUS_EM_ABERTO)
    df_proc['lead_time_estoque'] = np.where(em_aberto & (dias_emissao_embarque <= 1), 'LEAD TIME ESTOQUE', None)

    return df_proc


def obter_ctlr_pedidos_limpo(fonte_dados, fonte_solicitacoes) -> pd.DataFrame:
    df_raw = pd.read_excel(fonte_dados)
    df_solicitacoes = pd.read_excel(fonte_solicitacoes)
    df_limpo = processar_dataframe_ctlr(df_raw, df_solicitacoes)
    return df_limpo
