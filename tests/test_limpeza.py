"""Testes das limpezas (estoque e CTLR)."""
import datetime as dt

import pandas as pd

from core.regras.LimpezaCtlrPedidos import processar_dataframe_ctlr

DATAS_CTLR = ['dt_emissao', 'dt_aprovado', 'dt_cancelado', 'embarque', 'dt_reserva', 'dt_romaneio',
              'dt_faturamento', 'dt_entrega_cli']


def linha_ctlr(**datas):
    linha = {'num_ped': 1, 'num_prog': 1, 'familia': 'FILME STRETCH', 'cancelado': 'NÃO', 'anulado': 'NÃO',
             'desc_tec': 'A - FILME STRETCH AUTOMATICO 500 X 25 X 3 X 18 X 0,9'}
    linha.update({col: '  -   -' for col in DATAS_CTLR})
    linha.update(datas)
    return linha


def limpar(*linhas):
    return processar_dataframe_ctlr(pd.DataFrame(list(linhas)), pd.DataFrame(columns=['num_pedido', 'seq']))


def test_data_em_texto_le_o_dia_primeiro():
    # "03/11/26" é 3 de novembro (padrão brasileiro), não 11 de março
    df = limpar(linha_ctlr(dt_cancelado='03/11/26 12:01', dt_emissao='14/08/26'))
    assert df.at[0, 'dt_cancelado'] == pd.Timestamp(2026, 11, 3, 12, 1)
    assert df.at[0, 'dt_emissao'] == pd.Timestamp(2026, 8, 14)


def test_data_do_excel_e_data_vazia():
    df = limpar(linha_ctlr(dt_emissao=dt.datetime(2026, 8, 14, 10, 35), dt_cancelado='  -   -  : :'))
    assert df.at[0, 'dt_emissao'] == pd.Timestamp(2026, 8, 14, 10, 35)
    assert pd.isna(df.at[0, 'dt_cancelado'])


def test_anulado_e_nf_anulada_e_nao_cancelado():
    # anulado = SIM é a NF anulada depois do faturamento: entregue -> ENTREGUE; senão NF ANULADA
    df = limpar(linha_ctlr(num_ped=1, anulado='SIM', dt_faturamento='08/10/26', dt_entrega_cli='10/10/26'),
                linha_ctlr(num_ped=2, anulado='SIM', dt_faturamento='08/10/26'),
                linha_ctlr(num_ped=3, cancelado='SIM', dt_faturamento='08/10/26'))
    assert df['status_pedido'].tolist() == ['ENTREGUE', 'NF ANULADA', 'CANCELADO']


def test_familias_fora_do_stretch_sao_descartadas():
    df = limpar(linha_ctlr(), linha_ctlr(familia='PEBDL'), linha_ctlr(familia='FILME STRETCH BLUE'))
    assert df['familia'].tolist() == ['FILME STRETCH', 'FILME STRETCH BLUE']


def test_so_programacao_stretch():
    import pandas as pd
    from core.regras.LimpezaPlanejamento import so_programacao_stretch
    df = pd.DataFrame([
        {'tipo_of': 'EXTRUSÃO', 'maquina': 'GNP - Extrusora ST 01 (Davis)', 'produto': 'FILME STRETCH MANUAL 500 X 25'},
        {'tipo_of': 'EXTRUSÃO', 'maquina': 'GNP - Extrusora ST 03 (Power)', 'produto': 'FILME STRETCH JUMBO 500 X 20'},
        {'tipo_of': 'EXTRUSÃO', 'maquina': 'GNP - Extrusora 05 (Fralda)', 'produto': 'FILME FRALDA'},
        {'tipo_of': 'IMPRESSÃO', 'maquina': 'GNP - Extrusora ST 01 (Davis)', 'produto': 'FILME STRETCH'},
        {'tipo_of': 'EXTRUSÃO', 'maquina': 'Não-programadas', 'produto': 'FILME STRETCH MANUAL 500 X 23'},
        {'tipo_of': 'EXTRUSÃO', 'maquina': 'Não-programadas', 'produto': 'FILME RECUPERADO'},
    ])
    r = so_programacao_stretch(df)
    assert list(r.index) == [0, 1, 4]
