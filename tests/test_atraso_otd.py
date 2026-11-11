"""Testes do Atraso OTD (core/regras/AtrasoOtd.py) com os exemplos do cabeçalho do módulo."""
import pandas as pd

from core.regras.AtrasoOtd import ATRASADO, OK, VAI_ATRASAR, calcular_atraso_otd, mapa_data_otd

HOJE = "2026-11-10"


def ctlr(num, embarque, peso_prod=0, prev_prod=None, status="EM CARTEIRA", uf="SP", cfop=6101):
    return {"num_ped": num, "num_prog": 1, "embarque": pd.Timestamp(embarque), "peso_prod": peso_prod,
            "prev_prod": pd.Timestamp(prev_prod) if prev_prod else pd.NaT, "status_pedido": status,
            "uf": uf, "cfop": cfop}


def of(pedido, final_prev, dt_otd=None, final_real=None):
    return {"pedido": pedido, "seq_prog": 1, "dt_otd": pd.Timestamp(dt_otd) if dt_otd else pd.NaT,
            "final_prev": pd.Timestamp(final_prev), "final_real": pd.Timestamp(final_real) if final_real else pd.NaT}


def situacao(linhas, ofs):
    df = calcular_atraso_otd(pd.DataFrame(linhas), pd.DataFrame(ofs), hoje=HOJE)
    return dict(zip(df["num_ped"], df["atraso_otd"])), df


def test_exemplos_do_cabecalho():
    s, _ = situacao(
        [ctlr(1, "2026-11-10"), ctlr(2, "2026-11-09", peso_prod=1000, prev_prod="2026-11-08"),
         ctlr(3, "2026-11-12"), ctlr(4, "2026-11-12")],
        [of(1, "2026-11-24"), of(3, "2026-11-11 08:00"), of(4, "2026-11-10 20:00")],
    )
    assert s == {1: ATRASADO, 2: ATRASADO, 3: VAI_ATRASAR, 4: OK}


def test_sem_of_no_planejamento_fica_ok():
    # Pedido atendido por estoque ou ainda sem programação: o BI também não mostra
    s, _ = situacao([ctlr(1, "2026-11-01")], [])
    assert s == {1: OK}


def test_produzido_atrasado_so_conta_no_mes_do_embarque():
    s, _ = situacao([ctlr(1, "2026-10-20", peso_prod=500, prev_prod="2026-10-25")], [])
    assert s == {1: OK}


def test_cancelado_fica_ok():
    s, _ = situacao([ctlr(1, "2026-11-05", status="CANCELADO")], [of(1, "2026-11-30")])
    assert s == {1: OK}


def test_exportacao_usa_a_data_otd_do_planejamento():
    # Embarque 30/11 (embarque - 2 = 28/11), mas o planejamento diz OTD 05/11: já atrasou
    s, df = situacao([ctlr(1, "2026-11-30", uf="EX", cfop=7127), ctlr(2, "2026-11-30")],
                     [of(1, "2026-11-24", dt_otd="2026-11-05"), of(2, "2026-11-24", dt_otd="2026-11-05")])
    assert s == {1: ATRASADO, 2: OK}           # o nacional continua com embarque - 2
    assert df.loc[df.num_ped == 1, "data_otd"].iloc[0] == pd.Timestamp("2026-11-05")
    assert df.loc[df.num_ped == 2, "data_otd"].iloc[0] == pd.Timestamp("2026-11-28")


def test_mapa_para_o_encaixe():
    _, df = situacao([ctlr(221009, "2026-11-10")], [])
    assert mapa_data_otd(df) == {"221009|1": pd.Timestamp("2026-11-08")}
