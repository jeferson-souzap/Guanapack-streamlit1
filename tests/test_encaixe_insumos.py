"""Testes do encaixe em máquina e do consumo de tubetes e pallets com filas pequenas montadas à mão."""
import pandas as pd

from core.regras.Prioridade import ListaPrioritarios
from core.regras.ConsumoInsumos import calcular_consumo, catalogo_de_tubetes, medida_do_tubete
from core.regras.EncaixeMaquinas import NOVO, OF_ESTOQUE, SEM_MAQUINA, gerar_encaixe, grupo_formulacao

MAQUINA = "GNP - Extrusora ST 03 (Power)"
REGRAS = [{"maquina": MAQUINA, "apelido": "Power", "grupos": ["FM", "MN", "MO", "QUANTUM"],
           "palavras_nao_roda": ["CORELESS"], "micra_min": 8, "micra_max": 40, "peso_min": 2.38, "peso_max": 50,
           "tubete_min": 0.38, "tubete_max": 2, "largura_min": 450, "largura_max": 1000}]
PRODUTO = "A - FILME STRETCH AUTOMATICO 500 X 20 X 3 X 18 X 0,9"
INICIO = pd.Timestamp("2026-11-10")


def of(id_of, n_hora, horas=10, pedido=None, id_pa=10, qtde=1000, cliente="CLIENTE"):
    """OF que começa n_hora horas depois de INICIO e dura `horas` (1.000 kg em 10 h = 100 kg/h)."""
    ini = INICIO + pd.Timedelta(hours=n_hora)
    return {"maquina": MAQUINA, "id_of": id_of, "firmado": "Sim", "pedido": pedido, "seq_prog": 1 if pedido else None,
            "cliente": cliente, "cliente_razao_social": "", "id_pa": id_pa, "produto": PRODUTO,
            "formulacao": "MN 250%", "qtde_of": qtde, "qtde_prod": 0, "inicio_prev": ini,
            "final_prev": ini + pd.Timedelta(hours=horas), "dt_otd": pd.NaT}


def ped(num, embarque, kg=1000, id_pa=20, cliente="OUTRO", produto=PRODUTO, formulacao="MN 250%"):
    return {"num_pedido": num, "prog": 1, "cliente": cliente, "dt_embarque": pd.Timestamp(embarque), "id_pa": id_pa,
            "produto": produto, "formulacao": formulacao, "qtde_kg": kg, "tem_estoque": "NÃO"}


def encaixar(ofs, pedidos, prioritarios=None):
    return gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame(pedidos), REGRAS, prioritarios, {}, agora=INICIO)


def test_grupo_formulacao():
    assert [grupo_formulacao(f) for f in ["QUANTUM 400%", "FM 150% PCR", "MO 300% UV", "MN 250%"]] == \
        ["QUANTUM", "PCR", "UV", "MN"]


def test_novo_entra_depois_das_3_fixas_e_atende_o_prazo():
    ofs = [of(i, 10 * i) for i in range(4)]
    pedidos, filas, _ = encaixar(ofs, [ped(1, "2026-11-20")])
    p = pedidos.iloc[0]
    assert p.sugestao == NOVO and p.atende_embarque == "SIM"
    assert p.depois_de == "OF 3"                    # depois das 3 fixas, no fim (não empurra ninguém)
    assert list(filas.situacao[:3]) == ["FIXA"] * 3


def test_prazo_e_a_data_otd():
    # Embarque 13/11 -> data OTD 11/11: o pedido de 10 h depois das 4 OFs termina 11/11 às 02h (atende)
    pedidos, _, _ = encaixar([of(i, 10 * i) for i in range(4)], [ped(1, "2026-11-13")])
    assert pedidos.iloc[0].data_otd == pd.Timestamp("2026-11-11")
    assert pedidos.iloc[0].atende_embarque == "SIM"
    # Embarque 12/11 -> data OTD 10/11: termina 11/11, não atende
    pedidos, _, _ = encaixar([of(i, 10 * i) for i in range(4)], [ped(1, "2026-11-12")])
    assert pedidos.iloc[0].atende_embarque == "NÃO"


def test_of_de_estoque_do_mesmo_produto_atende_sem_of_nova():
    ofs = [of(1, 0), of(2, 10, id_pa=20, qtde=5000)]          # OF 2 sem pedido, mesmo produto do pedido
    pedidos, _, _ = encaixar(ofs, [ped(1, "2026-11-20", kg=1000)])
    assert pedidos.iloc[0].sugestao == OF_ESTOQUE
    assert pedidos.iloc[0].depois_de == "OF 2 (estoque)"


def test_maquina_que_nao_roda_o_produto():
    pedidos, _, _ = encaixar([of(1, 0)], [ped(1, "2026-11-20", produto="A - FILME STRETCH CORELESS 500 X 25 X 10")])
    assert pedidos.iloc[0].sugestao == SEM_MAQUINA
    assert "não roda CORELESS" in pedidos.iloc[0].maquinas_que_nao_rodam


def test_prioritario_e_encaixado_primeiro():
    lista = ListaPrioritarios([{"cliente": "Braskem"}])
    pedidos, _, _ = encaixar([of(i, 10 * i) for i in range(3)],
                             [ped(1, "2026-11-12"), ped(2, "2026-11-30", cliente="Braskem - Triunfo")], lista)
    assert list(pedidos.num_pedido) == ["2", "1"]             # o prioritário vem antes, mesmo embarcando depois
    assert pedidos.iloc[0].cliente_prioritario == "SIM"


def test_peso_do_tubete_digitado_errado_vem_do_tubete_de_mesma_medida():
    catalogo = catalogo_de_tubetes(["Tubete - 514 X 78 X 14,5 X 1,5"])
    assert medida_do_tubete("Tubete - 514 X 78 X 14,5 X 150", None, catalogo)[:2] == (514, 1.5)
    assert medida_do_tubete("Tubete - 514 X 78 X 14,5 X0.", None, catalogo)[:2] == (514, 1.5)
    assert medida_do_tubete("Tubete - 514 X 78 X 9x 0,9", None, catalogo) == (514, 0.9, "")


def test_consumo_conta_so_o_que_falta_e_soma_o_encaixe():
    base = {"maquina": MAQUINA, "pedido": None, "seq_prog": None, "qtde_of": 1000, "tubete": "Tubete - 514 X 78 X 9 X 0,9",
            "peso_tubete": 0.9, "pallet": "Palete PBR 1000 X 1200", "num_pallet": 3}
    plan = pd.DataFrame([{**base, "id_of": 1, "qtde_prod": 500, "final_real": pd.NaT, "num_tubete": 101},
                         {**base, "id_of": 2, "qtde_prod": 1000, "final_real": pd.Timestamp("2026-11-09"), "num_tubete": 100}])
    encaixe = pd.DataFrame([{"num_pedido": 7, "prog": 1, "sugestao": "NOVO NA MÁQUINA", "maquina": "Power"}])
    carteira = pd.DataFrame([{"num_pedido": 7, "prog": 1, "tubete": "Tubete - 514 X 78 X 9x 0,9", "qtde_tubete": 40,
                              "pallet": "Palete PBR 1000 X 1200", "qtde_pallet": 2, "produto": PRODUTO}])
    tubetes, pallets, _, _ = calcular_consumo(plan, encaixe, carteira)
    t = tubetes.iloc[0]
    # OF 1 pela metade: 101 tubetes x 50% = 50,5 -> 51; OF 2 terminada não conta; encaixe soma 40
    assert (t.largura_mm, t.peso_kg, t.programado_maquinas, t.encaixe, t.com_encaixe) == (514, 0.9, 51, 40, 91)
    assert pallets.iloc[0].com_encaixe == 2 + 2               # 3 x 50% = 1,5 -> 2, mais 2 do encaixe


# ----- regra 6: sequência de formulação (11/11/2026) -----
RANK = {"FM 150%": 1, "MN 250%": 2, "MO 300%": 3, "QUANTUM 400%": 5}


def of_form(id_of, n_hora, formulacao, pedido=None):
    linha = of(id_of, n_hora, pedido=pedido)
    linha["formulacao"] = formulacao
    return linha


def encaixar_seq(ofs, pedidos):
    return gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame(pedidos), REGRAS, None, {}, agora=INICIO, rank=RANK)


def test_nivel_formulacao_le_carteira_e_planejamento():
    from core.regras.EncaixeMaquinas import nivel_formulacao
    rank = {**RANK, "STIFF": 6, "FM 150% PCR": 1}
    assert nivel_formulacao("MO 300%", rank) == 3
    assert nivel_formulacao("Blue Pe FM 150% Nacional | Rev180/2026-05/05/26", rank) == 1
    assert nivel_formulacao("Quantum 400% - Nacional e Exportação | Rev104", rank) == 5
    assert nivel_formulacao("QUANTUM 350%", rank) == 5                 # não cadastrada: pela 1ª palavra
    assert nivel_formulacao("Stiff(unilever/nacional) | Rev43", rank) == 6
    assert nivel_formulacao(None, rank) is None and nivel_formulacao("XYZ", rank) is None


def test_nao_entra_no_meio_de_uma_sequencia_de_mn_mesmo_atrasando():
    # 3 fixas + 4 MN; o pedido MO com prazo curto só pode ir para o fim (depois da sequência de MN)
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(7)]
    pedidos, _, _ = encaixar_seq(ofs, [ped(1, "2026-11-12", formulacao="MO 300%")])
    p = pedidos.iloc[0]
    assert p.depois_de == "OF 6" and p.atende_embarque == "NÃO"
    # sem o rank (regra antiga) ele entrava logo depois das 3 fixas
    antigo, _, _ = encaixar([dict(o) for o in ofs], [ped(1, "2026-11-12", formulacao="MO 300%")])
    assert antigo.iloc[0].depois_de == "OF 2"


def test_mesma_formulacao_pode_entrar_no_meio_da_sequencia():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(7)]
    pedidos, _, _ = encaixar_seq(ofs, [ped(1, "2026-11-12", formulacao="MN 250%")])
    assert pedidos.iloc[0].depois_de == "OF 2"


def test_entra_na_troca_de_formulacao_que_respeita_a_subida():
    # FM FM FM (fixas) | MN MN | MO MO: o MN pode entrar entre FM e MN ou entre MN e MO; o MO só entre MN e MO ou no fim;
    # o FM só logo depois das fixas (entre FM e MN) ou no fim
    forms = ["FM 150%"] * 3 + ["MN 250%"] * 2 + ["MO 300%"] * 2
    ofs = [of_form(i, 10 * i, f) for i, f in enumerate(forms)]
    pedidos, _, _ = encaixar_seq(ofs, [ped(1, "2026-11-12", formulacao="MO 300%")])
    assert pedidos.iloc[0].depois_de == "OF 4"                 # 1ª posição permitida: entre MN (OF 4) e MO (OF 5)
    pedidos, _, _ = encaixar_seq(ofs, [ped(1, "2026-11-12", formulacao="QUANTUM 400%")])
    assert pedidos.iloc[0].depois_de == "OF 6"                 # QUANTUM só depois do último MO


def test_of_sem_formulacao_conta_como_a_anterior():
    forms = ["MN 250%"] * 4 + [None, None, "MO 300%"]
    ofs = [of_form(i, 10 * i, f) for i, f in enumerate(forms)]
    pedidos, _, _ = encaixar_seq(ofs, [ped(1, "2026-11-12", formulacao="MO 300%")])
    assert pedidos.iloc[0].depois_de == "OF 5"                 # as OFs 4 e 5 (sem formulação) são do bloco MN


# ----- rev030: grupo_form, opção PODE QUEBRAR (regra 7) e grupo nas filas -----
def encaixar_opcao(ofs, pedidos, opcao):
    return gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame(pedidos), REGRAS, None, {}, agora=INICIO, rank=RANK, opcao=opcao)


def test_nivel_vem_do_grupo_form_antes_da_formulacao():
    # formulação do relatório errada/vazia, grupo_form certo: vale o grupo
    forms = ["MN 250%"] * 4 + [None, "FM 150% Nacional (pcp Firmar)", "MO 300%"]
    ofs = [of_form(i, 10 * i, f) for i, f in enumerate(forms)]
    for o, g in zip(ofs, ["MN 250%"] * 4 + ["MO 300%", "MO 300%", "MO 300%"]):
        o["grupo_form"] = g
    pedidos, filas, _ = encaixar_seq(ofs, [ped(1, "2026-11-12", formulacao="MO 300%")])
    assert pedidos.iloc[0].depois_de == "OF 3"                 # entre o último MN (OF 3) e o 1º MO (OF 4)
    assert list(filas.grupo_formulacao[:3]) == ["MN 250%"] * 3 and filas.nivel_formulacao.iloc[0] == 2


def test_pode_quebrar_so_quando_precisa_para_o_prazo():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(7)]
    pedidos, filas, resumo = encaixar_opcao(ofs, [ped(1, "2026-11-14", formulacao="MO 300%")], "PODE QUEBRAR")
    p = pedidos.iloc[0]
    # quebra na posição que cumpre o prazo e empurra menos OFs (antes da última)
    assert p.depois_de == "OF 5" and p.atende_embarque == "SIM" and p.quebra_sequencia == "SIM"
    assert p.comparar_opcao == "NÃO QUEBRAR" and p.comparar_atende_embarque == "NÃO"
    assert "QUEBRA" in filas[filas.situacao == "NOVO"].observacao.iloc[0]
    assert "1 quebra a sequência" in resumo and "1 pedidos mudam" in resumo
    # com prazo folgado não quebra: vai para o fim, como no NÃO QUEBRAR
    pedidos, _, _ = encaixar_opcao(ofs, [ped(1, "2026-12-30", formulacao="MO 300%")], "PODE QUEBRAR")
    assert pedidos.iloc[0].depois_de == "OF 6" and pd.isna(pedidos.iloc[0].quebra_sequencia)


def test_nao_quebrar_e_o_padrao_e_compara_com_a_outra():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(7)]
    pedidos, _, resumo = encaixar_seq(ofs, [ped(1, "2026-11-14", formulacao="MO 300%")])
    p = pedidos.iloc[0]
    assert p.depois_de == "OF 6" and p.comparar_opcao == "PODE QUEBRAR"
    assert p.comparar_atende_embarque == "SIM" and "quebra a sequência" in p.comparar_sugestao
    assert resumo.startswith("1 pedidos sem estoque | NÃO QUEBRAR")
