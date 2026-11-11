"""Testes da troca da data de embarque (core/regras/TrocaEmbarque.py)."""
import pandas as pd

from core.regras.TrocaEmbarque import CONFERIR, OK, PEDIR_TROCA, calcular_troca

HOJE = "2026-11-10"


def ctlr(num, emissao, embarque, status="EM CARTEIRA", atraso="OK"):
    return {"num_ped": num, "num_prog": 1, "nome_cli": "CLIENTE", "dt_emissao": pd.Timestamp(emissao),
            "embarque": pd.Timestamp(embarque), "data_otd": pd.Timestamp(embarque) - pd.Timedelta(days=2),
            "status_pedido": status, "atraso_otd": atraso}


def encaixe(num, fim, atende, sugestao="NOVO NA MÁQUINA"):
    return {"num_pedido": num, "prog": 1, "sugestao": sugestao, "fim_previsto": pd.Timestamp(fim),
            "atende_embarque": atende, "maquina": "SML 1"}


def troca(linhas, enc=(), reserva=(), plan=None):
    df, _ = calcular_troca(pd.DataFrame(linhas), plan, pd.DataFrame(list(enc)) if enc else None,
                           pd.DataFrame(list(reserva)) if reserva else None, hoje=HOJE)
    return df.set_index("num_pedido")


def test_prazo_e_ate_o_dia_seguinte_a_emissao():
    df = troca([ctlr(1, "2026-11-09", "2026-11-20"), ctlr(2, "2026-11-10", "2026-11-20"),
                ctlr(3, "2026-11-08", "2026-11-20")])          # emitido anteontem: já não dá para trocar
    assert sorted(df.index) == [1, 2]
    assert df.at[1, "prazo_troca"] == pd.Timestamp("2026-11-10")


def test_encaixe_que_nao_atende_pede_troca_com_embarque_sugerido():
    df = troca([ctlr(1, "2026-11-09", "2026-11-11")], [encaixe(1, "2026-11-11 07:40", "NÃO")])
    assert df.at[1, "situacao"] == PEDIR_TROCA
    assert df.at[1, "embarque_sugerido"] == pd.Timestamp("2026-11-13")     # fim 11/11 + 2 dias


def test_atraso_otd_pede_troca():
    df = troca([ctlr(1, "2026-11-10", "2026-11-12", atraso="VAI ATRASAR")])
    assert df.at[1, "situacao"] == PEDIR_TROCA


def test_com_estoque_ok_e_sem_nada_conferir():
    df = troca([ctlr(1, "2026-11-10", "2026-11-12"), ctlr(2, "2026-11-10", "2026-11-12", status="AGUARDANDO APROVAÇÃO")],
               reserva=[{"num_pedido": 1, "prog": 1, "tem_estoque": "SIM", "atendimento": "EXATO"}])
    assert df.at[1, "situacao"] == OK
    assert df.at[2, "situacao"] == CONFERIR
    assert list(df["situacao"]) == [CONFERIR, OK]                           # o que precisa de ação primeiro


def test_sem_pedidos_no_prazo():
    df = troca([ctlr(1, "2026-10-01", "2026-11-20")])
    assert df.empty and "situacao" in df.columns
