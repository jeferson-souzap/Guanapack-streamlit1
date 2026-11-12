"""
Limpeza do planejamento das máquinas (PCP_PLANEJAMENTO_GERAL).

O relatório traz as OFs programadas em cada máquina (extrusão, impressão, acabamento).
A limpeza só converte datas e números e acrescenta a situação e o saldo de cada OF.
"""
from datetime import datetime

import numpy as np
import pandas as pd

COLUNAS_DATAS = ['dt_otd', 'inicio_prev', 'final_prev', 'inicio_real', 'final_real']

# Máquina usada pelo ERP para as OFs ainda sem programação
MAQUINA_NAO_PROGRAMADA = "NÃO-PROGRAMADAS"

# Extrusoras de stretch (mesmo filtro da consulta pcp_planejamento do Excel). O Atraso OTD, o
# encaixe em máquina e o consumo de tubetes e pallets só olham estas OFs.
MAQUINAS_STRETCH = ["GNP - EXTRUSORA ST 01 (DAVIS)", "GNP - EXTRUSORA ST 02 (SML 1)",
                    "GNP - EXTRUSORA ST 03 (POWER)", MAQUINA_NAO_PROGRAMADA]


def filtrar_extrusao_stretch(df: pd.DataFrame) -> pd.DataFrame:
    """OFs de extrusão das máquinas de stretch e as não programadas."""
    if df is None or df.empty:
        return df
    tipo = df['tipo_of'].astype(str).str.strip().str.upper()
    maquina = df['maquina'].astype(str).str.strip().str.upper()
    return df[(tipo == 'EXTRUSÃO') & maquina.isin(MAQUINAS_STRETCH)]


def so_programacao_stretch(df: pd.DataFrame) -> pd.DataFrame:
    """O que entra na programação de máquina: OFs de extrusão da Davis, SML 1 e Power e as não
    programadas de produto stretch (as mesmas que o encaixe olha; fralda, recuperado etc. ficam fora)."""
    df = filtrar_extrusao_stretch(df)
    if df is None or df.empty:
        return df
    nao_prog = df['maquina'].astype(str).str.strip().str.upper() == MAQUINA_NAO_PROGRAMADA
    stretch = df['produto'].astype(str).str.upper().str.contains('STRETCH', regex=False)
    return df[~nao_prog | stretch]


def processar_dataframe_planejamento(df: pd.DataFrame) -> pd.DataFrame:
    df_proc = df.copy()

    for col in COLUNAS_DATAS:
        if col in df_proc.columns:
            df_proc[col] = pd.to_datetime(df_proc[col], errors='coerce', format='mixed', dayfirst=True)

    # Pedido e programação vêm como 218047.0 (coluna com vazios): inteiro para cruzar com a carteira
    for col in ['pedido', 'seq_prog']:
        df_proc[col] = pd.to_numeric(df_proc[col], errors='coerce').astype('Int64')

    nao_programada = df_proc['maquina'].astype(str).str.strip().str.upper() == MAQUINA_NAO_PROGRAMADA
    df_proc['situacao_of'] = np.select(
        [df_proc['final_real'].notna(), df_proc['inicio_real'].notna(), nao_programada],
        ['FINALIZADA', 'EM PRODUÇÃO', 'NÃO PROGRAMADA'],
        default='PROGRAMADA',
    )
    qtde_of = pd.to_numeric(df_proc['qtde_of'], errors='coerce')
    qtde_prod = pd.to_numeric(df_proc['qtde_prod'], errors='coerce').fillna(0)
    df_proc['saldo_kg'] = (qtde_of - qtde_prod).clip(lower=0)

    agora = datetime.now().astimezone()
    df_proc['import_data_hora'] = agora.isoformat(timespec="seconds")
    return df_proc
