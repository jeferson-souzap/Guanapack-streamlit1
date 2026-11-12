"""Regra 8 do encaixe (rev031): as OFs de Não-programadas entram na máquina antes dos pedidos sem estoque."""
import pandas as pd

from core.regras.EncaixeMaquinas import NAO_PROG_NA_MAQUINA, OF_ESTOQUE, OF_NAO_PROG, SITUACAO_NAO_PROG, gerar_encaixe
from core.regras.SimulacaoProgramacao import RegrasCenario, gerar_cenario, indicadores
from tests.test_encaixe_insumos import INICIO, REGRAS, of, ped


def nao_prog(id_of, dt_otd, qtde=1000, pedido=None, id_pa=30, produto=None):
    linha = of(id_of, 0, pedido=pedido, id_pa=id_pa, qtde=qtde)
    linha.update(maquina="Não-programadas", inicio_prev=pd.NaT, final_prev=pd.NaT,
                 dt_otd=pd.Timestamp(dt_otd) if dt_otd else pd.NaT)
    if produto:
        linha["produto"] = produto
    return linha


def encaixar(ofs, pedidos):
    return gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame(pedidos, columns=list(ped(0, "2026-11-20"))),
                         REGRAS, None, {}, agora=INICIO)


def test_nao_programada_entra_antes_dos_pedidos():
    ofs = [of(i, 10 * i) for i in range(5)] + [nao_prog(900, "2026-11-11")]   # tem que acabar até a hora 48
    pedidos, filas, resumo = encaixar(ofs, [ped(1, "2026-11-30")])
    assert list(pedidos["id_of"].fillna("")) == ["900", ""]                   # a OF vem primeiro na tabela
    assert pedidos.loc[0, "sugestao"] == NAO_PROG_NA_MAQUINA and pedidos.loc[0, "atende_embarque"] == "SIM"
    assert pedidos.loc[0, "depois_de"] == "OF 2"                               # logo depois das 3 fixas
    assert list(filas["id_of"].fillna("NOVO")) == ["0", "1", "2", "900", "3", "4", "NOVO"]
    linha = filas.set_index(filas["id_of"].fillna("NOVO")).loc["900"]
    assert linha["situacao"] == SITUACAO_NAO_PROG and linha["fim_sugerido"] == INICIO + pd.Timedelta(hours=40)
    assert resumo.startswith("não programadas: 1 (1 na máquina, 1 no prazo, 0 sem máquina)")


def test_so_entram_as_de_stretch_e_sem_prazo_vai_para_o_fim():
    ofs = [of(i, 10 * i) for i in range(4)] + [nao_prog(900, None),
                                                nao_prog(901, "2026-11-11", produto="P - FILME FRALDA 900 X 20 X 3 X 18 X 0,9")]
    pedidos, filas, _ = encaixar(ofs, [])
    assert list(pedidos["id_of"]) == ["900"]                                   # a fralda fica de fora
    assert list(filas["id_of"]) == ["0", "1", "2", "3", "900"]                 # sem prazo: não empurra ninguém
    assert pd.isna(pedidos.loc[0, "atende_embarque"])


def test_pedido_que_ja_tem_of_nao_programada_fica_com_ela():
    ofs = [of(i, 10 * i) for i in range(4)] + [nao_prog(900, "2026-11-20", pedido=1)]
    pedidos, filas, _ = encaixar(ofs, [ped(1, "2026-11-22")])
    assert len(filas) == 5                                                     # não entra outra OF para o pedido
    p = pedidos[pedidos["id_of"].isna()].iloc[0]
    assert p["sugestao"] == OF_NAO_PROG and p["depois_de"] == "OF 900 (não programada)"


def test_of_de_estoque_nao_programada_atende_pedido_do_mesmo_produto():
    ofs = [of(i, 10 * i) for i in range(4)] + [nao_prog(900, "2026-11-20", qtde=3000, id_pa=20)]
    pedidos, filas, _ = encaixar(ofs, [ped(1, "2026-11-22", kg=1000, id_pa=20)])
    p = pedidos[pedidos["id_of"].isna()].iloc[0]
    assert p["sugestao"] == OF_ESTOQUE and p["depois_de"] == "OF 900 (estoque, não programada)"
    assert len(filas) == 5


def test_simulacao_mostra_a_nao_programada():
    ofs = [of(i, 10 * i) for i in range(5)] + [nao_prog(900, "2026-11-11")]
    cen = gerar_cenario(pd.DataFrame(ofs), pd.DataFrame(columns=list(ped(0, "2026-11-20"))), REGRAS, None, {},
                        None, RegrasCenario(), agora=INICIO)
    it = cen.itens.set_index("chave")
    assert it.loc["OF 900", "situacao"] == SITUACAO_NAO_PROG and it.loc["OF 900", "ordem"] == 4
    assert it.loc["OF 900", "id_of"] == "900"
    assert indicadores(cen)["novos"] == 1 and indicadores(cen)["novos_no_prazo"] == 1
