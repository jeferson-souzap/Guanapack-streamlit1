"""Testes da simulação da programação (filas pequenas montadas à mão)."""
import pandas as pd

from core.regras.EncaixeMaquinas import gerar_encaixe
from core.regras.SimulacaoProgramacao import (FORMULACAO, IGNORAR, PASSA_A_ATRASAR, RegrasCenario, aplicar_mudancas,
                                              agrupar_por_formulacao, de_json, gerar_cenario, indicadores, para_json)
from tests.test_encaixe_insumos import INICIO, MAQUINA, PRODUTO, RANK, REGRAS, of_form, ped

SML = "GNP - Extrusora ST 02 (SML 1)"
REGRAS2 = REGRAS + [{**REGRAS[0], "maquina": SML, "apelido": "SML 1"}]


def cenario(ofs, pedidos, regras=None, maquinas=REGRAS, **kw):
    return gerar_cenario(pd.DataFrame(ofs), pd.DataFrame(pedidos), maquinas, None, {}, RANK, regras or RegrasCenario(),
                         agora=INICIO, **kw)


def test_sem_mexer_as_datas_sao_as_do_encaixe():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(5)]
    ofs[3]["inicio_prev"] += pd.Timedelta(hours=2)            # intervalo de 2 h antes da OF 3 no planejamento
    ofs[3]["final_prev"] += pd.Timedelta(hours=2)
    ofs[4]["inicio_prev"] += pd.Timedelta(hours=2)
    ofs[4]["final_prev"] += pd.Timedelta(hours=2)
    pedidos = [ped(1, "2026-11-20")]
    _, filas, _ = gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame(pedidos), REGRAS, None, {}, agora=INICIO, rank=RANK)
    it = cenario(ofs, pedidos).itens
    assert list(it["chave"]) == [("NOVO 1/1" if s == "NOVO" else f"OF {i}") for s, i in zip(filas.situacao, filas.id_of)]
    assert list(it["fim"]) == list(filas["fim_sugerido"])
    assert it.set_index("chave").loc["OF 3", "intervalo_h"] == 2       # o intervalo vai junto com a OF


def test_mexer_na_ordem_e_de_maquina():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(5)]
    cen = cenario(ofs, [], maquinas=REGRAS2)
    ed = cen.itens[["chave", "maquina", "ordem"]].copy()
    ed.loc[ed.chave == "OF 4", "ordem"] = 1                   # a última vira a primeira
    avisos = aplicar_mudancas(cen, ed)
    it = cen.itens
    assert list(it["chave"]) == ["OF 4", "OF 0", "OF 1", "OF 2", "OF 3"]
    assert it.loc[0, "inicio"] == INICIO and it.loc[1, "inicio"] == INICIO + pd.Timedelta(hours=10)
    assert avisos == []
    ed = cen.itens[["chave", "maquina", "ordem"]].copy()
    ed.loc[ed.chave == "OF 0", "maquina"] = "SML 1"           # SML 1 sem OF no relatório: sem kg/h
    avisos = aplicar_mudancas(cen, ed)
    assert any("sem kg/h" in a for a in avisos) and any("FIXA" in a for a in avisos)
    assert cen.itens.set_index("chave").loc["OF 0", "maquina"] == "SML 1"


def test_mexer_mostra_quem_passa_a_atrasar():
    ofs = [of_form(i, 10 * i, "MN 250%", pedido=100 + i) for i in range(4)]
    for o in ofs:
        o["dt_otd"] = pd.Timestamp("2026-11-10")              # todas têm que terminar até 10/11 (OF 0 e 1 cabem)
    cen = cenario(ofs, [])
    assert indicadores(cen)["passam_a_atrasar"] == 0
    ed = cen.itens[["chave", "maquina", "ordem"]].copy()
    ed.loc[ed.chave == "OF 3", "ordem"] = 1
    aplicar_mudancas(cen, ed)
    assert cen.itens.set_index("chave").loc["OF 1", "atraso"] == PASSA_A_ATRASAR


def test_setup_por_troca_de_grupo():
    forms = ["MN 250%", "MN 250%", "MO 300%", "MO 300%"]
    ofs = [of_form(i, 10 * i, f) for i, f in enumerate(forms)]
    cen = cenario(ofs, [], RegrasCenario(setup_min=60))
    it = cen.itens.set_index("chave")
    assert it.loc["OF 2", "troca_grupo"] and indicadores(cen)["trocas_grupo"] == 1
    assert it.loc["OF 3", "fim"] == INICIO + pd.Timedelta(hours=41)


def test_agrupar_por_formulacao_sobe_e_depois_desce():
    forms = ["MN 250%"] * 3 + ["FM 150%", "MO 300%", "MN 250%", "QUANTUM 400%", "FM 150%"]
    ofs = [of_form(i, 10 * i, f) for i, f in enumerate(forms)]
    cen = cenario(ofs, [], RegrasCenario(prioridade=FORMULACAO))
    assert list(cen.itens["formulacao"]) == ["MN 250%"] * 4 + ["MO 300%", "QUANTUM 400%", "FM 150%", "FM 150%"]
    assert indicadores(cen)["trocas_grupo"] == 3


def test_ignorar_sequencia_e_salvar_e_abrir():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(7)]
    cen = cenario(ofs, [ped(1, "2026-11-14", formulacao="MO 300%")], RegrasCenario(sequencia=IGNORAR))
    assert cen.itens.set_index("chave").loc["NOVO 1/1", "ordem"] == 7       # entre dois MN: no prazo, empurra 1 OF
    assert indicadores(cen)["quebras"] == 1
    copia = de_json(para_json(cen))
    assert list(copia.itens["fim"]) == list(cen.itens["fim"]) and copia.regras == cen.regras
    agrupar_por_formulacao(copia, "Power")
    assert indicadores(copia)["quebras"] == 0


def test_of_travada_nao_sai_do_lugar():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(7)]
    cen = cenario(ofs, [])
    ed = cen.itens[["chave", "maquina", "ordem", "travada"]].copy()
    ed.loc[ed.chave == "OF 5", "travada"] = True              # trava a 6ª
    ed.loc[ed.chave == "OF 6", "ordem"] = 4                   # a última sobe para a 4ª
    aplicar_mudancas(cen, ed)
    assert list(cen.itens["chave"]) == ["OF 0", "OF 1", "OF 2", "OF 6", "OF 3", "OF 5", "OF 4"]
    assert cen.itens.set_index("chave").loc["OF 5", "ordem"] == 6
    # mexer na própria travada leva ela para o lugar novo, ainda travada
    ed = cen.itens[["chave", "maquina", "ordem", "travada"]].copy()
    ed.loc[ed.chave == "OF 5", "ordem"] = 7
    aplicar_mudancas(cen, ed)
    it = cen.itens.set_index("chave")
    assert it.loc["OF 5", "ordem"] == 7 and bool(it.loc["OF 5", "travada"])


def test_agrupar_respeita_a_travada():
    forms = ["MN 250%"] * 3 + ["FM 150%", "MO 300%", "MN 250%", "QUANTUM 400%"]
    ofs = [of_form(i, 10 * i, f) for i, f in enumerate(forms)]
    cen = cenario(ofs, [])
    ed = cen.itens[["chave", "maquina", "ordem", "travada"]].copy()
    ed.loc[ed.chave == "OF 3", "travada"] = True              # FM travada na 4ª posição
    aplicar_mudancas(cen, ed)
    agrupar_por_formulacao(cen, "Power")
    assert list(cen.itens["chave"]) == ["OF 0", "OF 1", "OF 2", "OF 3", "OF 5", "OF 4", "OF 6"]


def test_gerar_de_novo_mantem_as_travadas():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(7)]
    cen = cenario(ofs, [])
    ed = cen.itens[["chave", "maquina", "ordem", "travada"]].copy()
    ed.loc[ed.chave == "OF 1", ["ordem", "travada"]] = [6, True]     # trava a 2ª na 6ª posição
    aplicar_mudancas(cen, ed)
    travadas = cen.itens.loc[cen.itens["travada"], ["chave", "maquina", "ordem"]]
    avisos = []
    novo = cenario(ofs, [], travadas=travadas, avisos=avisos)
    it = novo.itens.set_index("chave")
    assert it.loc["OF 1", "ordem"] == 6 and bool(it.loc["OF 1", "travada"])
    assert int(novo.itens["travada"].sum()) == 1
    assert any("FIXA" in a for a in avisos)                    # saiu de uma posição fixa da sugestão
    # travada que não existe mais vira aviso
    avisos = []
    cenario(ofs, [], travadas=pd.DataFrame([{"chave": "OF 99", "maquina": "Power", "ordem": 2}]), avisos=avisos)
    assert any("OF 99" in a for a in avisos)
