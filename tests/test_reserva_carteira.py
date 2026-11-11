"""Testes das regras de reserva (core/regras/ReservaCarteira.py) com tabelas pequenas montadas à mão."""
import pandas as pd
import pytest

from core.regras.Prioridade import ListaPrioritarios
from core.regras.LimpezaDataframe import processar_dataframe_estoque
from core.regras.ReservaCarteira import (SEM_ESTOQUE, TEM_ESTOQUE, _escolher_pallets, estoque_solicitado,
                                          sugerir_reservas)

RANK = {'FM 150%': 1, 'FM 150% PCR': 1, 'MN 250%': 2, 'MN 250% PCR': 2, 'MO 300%': 3}


def produto(micra=25, peso=18, tubete=0.9):
    return f"FILME STRETCH AUTOMATICO 500 X {micra:g} X 3 X {peso:g} X {tubete:g}".replace('.', ',')


def pallet(id_pa, kg, formulacao='MN 250%', micra=25, dias_parado=10, tipo='DISPONIVEL', qtd_pallets=1):
    return {'tipo_estoque': tipo, 'rua': 'R1', 'id_of': f'OF{id_pa}', 'id_pa': id_pa,
            'desc_tecnica': produto(micra), 'grupo_formulacao': formulacao,
            'peso_liquido': kg, 'peso_bruto': kg + 20 * qtd_pallets, 'qtd_pallets': qtd_pallets,
            'final_of': pd.Timestamp.now().normalize() - pd.Timedelta(days=dias_parado)}


def pedido(num, kg, formulacao='MN 250%', micra=25, embarque='2026-11-10', tipo_venda='Líquido'):
    return {'num_pedido': num, 'prog': 1, 'cliente': 'CLIENTE TESTE', 'dt_embarque': embarque,
            'id_pa': 1, 'produto': 'A - ' + produto(micra), 'formulacao': formulacao,
            'qtde_kg': kg, 'tipo_venda': tipo_venda}


def reservar(pedidos, pallets):
    estoque = processar_dataframe_estoque(pd.DataFrame(pallets))
    return sugerir_reservas(pd.DataFrame(pedidos), estoque, RANK).set_index('num_pedido')


def test_exato():
    r = reservar([pedido(1, 1000)], [pallet(1, 1000)])
    assert r.at[1, 'tem_estoque'] == TEM_ESTOQUE
    assert r.at[1, 'atendimento'] == 'EXATO'
    assert pd.isna(r.at[1, 'alternativo_usado'])


def test_combinacao_que_nao_comeca_pelo_mais_antigo():
    # O 800 (mais antigo) não fecha com nenhum outro; 500 + 500 fecha os 1.000 kg
    r = reservar([pedido(1, 1000)],
                 [pallet(1, 800, dias_parado=90), pallet(1, 500, dias_parado=30), pallet(1, 500, dias_parado=20)])
    assert r.at[1, 'tem_estoque'] == TEM_ESTOQUE


def _grupo(pesos_e_dias):
    return pd.DataFrame([{'peso_liquido': kg, 'dias_parado': dias, 'id_pallet': f'P{i}'}
                         for i, (kg, dias) in enumerate(pesos_e_dias)])


def test_mais_antigos_tem_preferencia():
    grupo = _grupo([(500, 5), (500, 60), (500, 50)])
    escolhidos, total = _escolher_pallets(grupo, 'peso_liquido', 950, 1050)
    assert sorted(escolhidos) == [1, 2]
    assert total == 1000


def test_combinacao_mais_antiga_entre_varias():
    # 900 (mais antigo) + 100 fecha; 600 + 400 também, mas usa pallets mais novos
    grupo = _grupo([(600, 30), (900, 90), (400, 20), (100, 10)])
    escolhidos, _ = _escolher_pallets(grupo, 'peso_liquido', 950, 1050)
    assert sorted(escolhidos) == [1, 3]


def test_sem_combinacao_informa_o_mais_proximo():
    escolhidos, total = _escolher_pallets(_grupo([(800, 9), (600, 5)]), 'peso_liquido', 950, 1050)
    assert escolhidos is None
    assert total == 800


@pytest.mark.parametrize('kg_pallet, atende', [(950, True), (1050, True), (949, False), (1051, False)])
def test_tolerancia_5_porcento(kg_pallet, atende):
    r = reservar([pedido(1, 1000)], [pallet(1, kg_pallet)])
    assert (r.at[1, 'tem_estoque'] == TEM_ESTOQUE) is atende


def test_venda_bruta_usa_peso_bruto():
    # Líquido 1000 kg, bruto 1020 kg: pedido bruto de 1100 kg (mín. 1045) não fecha
    r = reservar([pedido(1, 1100, tipo_venda='Bruto')], [pallet(1, 1000)])
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE
    r = reservar([pedido(1, 1020, tipo_venda='Bruto')], [pallet(1, 1000)])
    assert r.at[1, 'tem_estoque'] == TEM_ESTOQUE


@pytest.mark.parametrize('micra, atende', [(23, True), (27, True), (22, False), (28, False)])
def test_alternativo_micra_ate_2(micra, atende):
    r = reservar([pedido(1, 1000)], [pallet(2, 1000, micra=micra)])
    assert (r.at[1, 'tem_estoque'] == TEM_ESTOQUE) is atende
    if atende:
        assert r.at[1, 'atendimento'] == 'ALTERNATIVO'
        assert f'MICRA 25->{micra}' in r.at[1, 'alternativo_usado']


@pytest.mark.parametrize('formulacao, atende', [('MO 300%', True), ('FM 150%', False)])
def test_formulacao_so_um_degrau_acima(formulacao, atende):
    r = reservar([pedido(1, 1000, formulacao='MN 250%')], [pallet(2, 1000, formulacao=formulacao)])
    assert (r.at[1, 'tem_estoque'] == TEM_ESTOQUE) is atende


def test_formulacao_dois_degraus_acima_nao_vale():
    r = reservar([pedido(1, 1000, formulacao='FM 150%')], [pallet(2, 1000, formulacao='MO 300%')])
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE


def test_micra_e_formulacao_diferentes_ao_mesmo_tempo_nao_vale():
    r = reservar([pedido(1, 1000)], [pallet(2, 1000, formulacao='MO 300%', micra=26)])
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE
    assert '2 alternativos' in r.at[1, 'motivo_sem_estoque']


@pytest.mark.parametrize('form_pedido, form_pallet', [('MN 250% PCR', 'MN 250%'), ('MN 250%', 'MN 250% PCR')])
def test_pcr_so_com_pcr(form_pedido, form_pallet):
    r = reservar([pedido(1, 1000, formulacao=form_pedido)], [pallet(2, 1000, formulacao=form_pallet)])
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE


def test_exato_tem_preferencia_sobre_alternativo():
    r = reservar([pedido(1, 1000)], [pallet(2, 1000, micra=24, dias_parado=200), pallet(1, 1000)])
    assert r.at[1, 'atendimento'] == 'EXATO'


def test_nao_mistura_produtos():
    # 500 do exato + 500 do alternativo somariam 1000, mas o pedido usa um produto só
    r = reservar([pedido(1, 1000)], [pallet(1, 500), pallet(2, 500, micra=24)])
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE


def test_so_estoque_disponivel():
    r = reservar([pedido(1, 1000)], [pallet(1, 1000, tipo='RESERVADO')])
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE


def test_estoque_usado_sai_do_saldo_em_ordem_de_embarque():
    r = reservar([pedido(1, 1000, embarque='2026-11-20'), pedido(2, 1000, embarque='2026-11-10')],
                 [pallet(1, 1000)])
    assert r.at[2, 'tem_estoque'] == TEM_ESTOQUE   # embarca antes, leva o pallet
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE


def test_linha_com_varios_pallets_e_dividida():
    # Uma linha do estoque com 2 pallets (1000 kg no total) atende um pedido de 500 kg e sobra 500
    r = reservar([pedido(1, 500, embarque='2026-11-10'), pedido(2, 500, embarque='2026-11-11')],
                 [pallet(1, 1000, qtd_pallets=2)])
    assert (r['tem_estoque'] == TEM_ESTOQUE).all()


def test_formulacao_fora_do_cadastro():
    r = reservar([pedido(1, 1000, formulacao='NOVA 999%')], [pallet(1, 1000)])
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE
    assert 'não cadastrada' in r.at[1, 'motivo_sem_estoque']


def test_informa_os_pallets_reservados():
    r = reservar([pedido(1, 1000), pedido(2, 5000)], [pallet(1, 1000, qtd_pallets=2)])
    assert r.at[1, 'qtd_pallets_reservados'] == 2
    assert r.at[1, 'peso_reservado'] == 1000
    assert r.at[1, 'pallets_reservados'] == 'OF1/R1/1de2, OF1/R1/2de2'
    assert r.at[2, 'qtd_pallets_reservados'] == 0
    assert pd.isna(r.at[2, 'pallets_reservados'])


# ===== Estoque já solicitado e kanban de cliente prioritário (regras da planilha Excel) =====

def test_desconta_o_estoque_ja_solicitado():
    # 1.000 kg em estoque, 600 já pedidos em solicitação de reserva: sobram 400, não fecha 1.000
    solicitacoes = pd.DataFrame([{'produto': '1 - A - FILME STRETCH', 'qtde_kg': 600}])
    estoque = processar_dataframe_estoque(pd.DataFrame([pallet(1, 1000)]))
    r = sugerir_reservas(pd.DataFrame([pedido(1, 1000)]), estoque, RANK, solicitacoes).set_index('num_pedido')
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE
    assert 'solicitados' in r.at[1, 'motivo_sem_estoque']


def test_solicitado_usa_o_maior_entre_carteira_e_relatorio():
    carteira = pd.DataFrame([{**pedido(1, 900), 'reserva_solicitada': 300},
                             {**pedido(1, 900), 'reserva_solicitada': 400}])   # mesmo pedido, 2 solicitações
    relatorio = pd.DataFrame([{'produto': '1 - A - FILME', 'qtde_kg': 500}])
    assert estoque_solicitado(carteira, relatorio) == {1: 700}


def _pallet_kanban(kg, cliente_kanban):
    return {**pallet(1, kg), 'kanban': 'SIM', 'cliente_kanban': cliente_kanban}


def test_kanban_de_prioritario_vai_primeiro_para_o_cliente():
    lista = ListaPrioritarios([{'cliente': 'Braskem'}])
    estoque = processar_dataframe_estoque(pd.DataFrame([_pallet_kanban(1000, 'BRASKEM - TRIUNFO')]))
    pedidos = pd.DataFrame([pedido(1, 1000, embarque='2026-11-10'),                  # outro cliente, embarca antes
                            {**pedido(2, 1000, embarque='2026-11-20'), 'cliente': 'Braskem - Triunfo (1203)'}])
    r = sugerir_reservas(pedidos, estoque, RANK, prioritarios=lista).set_index('num_pedido')
    assert r.at[2, 'tem_estoque'] == TEM_ESTOQUE
    assert r.at[1, 'tem_estoque'] == SEM_ESTOQUE


def test_sobra_do_kanban_prioritario_volta_para_os_outros():
    lista = ListaPrioritarios([{'cliente': 'Braskem'}])
    estoque = processar_dataframe_estoque(pd.DataFrame([_pallet_kanban(1000, 'BRASKEM - TRIUNFO')]))
    r = sugerir_reservas(pd.DataFrame([pedido(1, 1000)]), estoque, RANK, prioritarios=lista).set_index('num_pedido')
    assert r.at[1, 'tem_estoque'] == TEM_ESTOQUE          # 2ª passada: ninguém da Braskem pediu
