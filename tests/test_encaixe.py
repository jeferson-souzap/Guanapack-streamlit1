"""Testes do encaixe em máquina e do consumo de tubetes e pallets com filas pequenas montadas à mão."""
import pandas as pd

from core.regras.Prioridade import ListaPrioritarios
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
    assert p.comparar_opcao == "ATENDER O PEDIDO"          # regra 11: a comparação agora é entre os modos
    assert "QUEBRA" in filas[filas.situacao == "NOVO"].observacao.iloc[0]
    assert "1 quebra a sequência" in resumo
    # com prazo folgado não quebra: vai para o fim, como no NÃO QUEBRAR
    pedidos, _, _ = encaixar_opcao(ofs, [ped(1, "2026-12-30", formulacao="MO 300%")], "PODE QUEBRAR")
    assert pedidos.iloc[0].depois_de == "OF 6" and pd.isna(pedidos.iloc[0].quebra_sequencia)


def test_nao_quebrar_e_o_padrao():
    ofs = [of_form(i, 10 * i, "MN 250%") for i in range(7)]
    pedidos, _, resumo = encaixar_seq(ofs, [ped(1, "2026-11-14", formulacao="MO 300%")])
    p = pedidos.iloc[0]
    assert p.depois_de == "OF 6" and pd.isna(p.quebra_sequencia)
    assert p.comparar_opcao == "ATENDER O PEDIDO" and "quebra" not in p.comparar_sugestao
    assert resumo.startswith("1 pedidos sem estoque | NÃO ATRASAR A FILA | NÃO QUEBRAR")


# ----- regra 11: modo do encaixe (25/11/2026) -----
def fila_com_pedido_no_limite(dt_otd_of3):
    """3 fixas (0-30 h) | OF 3 do pedido 900 (30-40 h, termina 11/11 16h) | OF 4 de estoque (40-50 h)."""
    ofs = [of(i, 10 * i) for i in range(5)]
    ofs[3].update(pedido=900, seq_prog=1, dt_otd=pd.Timestamp(dt_otd_of3))
    return ofs


def test_nao_atrasar_a_fila_nao_empurra_quem_esta_no_prazo():
    # OF 3 tem data OTD 11/11 (atrasa se passar da meia-noite de 12/11). O pedido novo (OTD 11/11) só
    # atenderia entrando antes da OF 3, o que faz ela atrasar: no 1.1 ele fica depois dela (e não atende)
    ofs = fila_com_pedido_no_limite("2026-11-11")
    pedidos, filas, resumo = gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame([ped(1, "2026-11-13")]), REGRAS, None, {},
                                           agora=INICIO, modo="NÃO ATRASAR A FILA")
    p = pedidos.iloc[0]
    assert p.depois_de == "OF 3" and p.atende_embarque == "NÃO" and pd.isna(p.ofs_que_passam_a_atrasar)
    assert (filas.atraso == "PASSA A ATRASAR").sum() == 0
    # o outro modo vem nas colunas comparar_*: atende, mas a OF 3 passa a atrasar
    assert p.comparar_opcao == "ATENDER O PEDIDO" and p.comparar_atende_embarque == "SIM"
    assert p.comparar_depois_de == "OF 2" and p.comparar_ofs_que_passam_a_atrasar == "OF 3"
    assert "OFs que passam a atrasar: 0" in resumo


def test_atender_o_pedido_empurra_a_fila():
    ofs = fila_com_pedido_no_limite("2026-11-11")
    pedidos, filas, _ = gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame([ped(1, "2026-11-13")]), REGRAS, None, {},
                                      agora=INICIO, modo="ATENDER O PEDIDO")
    p = pedidos.iloc[0]
    assert p.depois_de == "OF 2" and p.atende_embarque == "SIM" and p.ofs_que_passam_a_atrasar == "OF 3"
    assert filas.set_index("id_of").loc["3", "atraso"] == "PASSA A ATRASAR"
    assert p.comparar_opcao == "NÃO ATRASAR A FILA"


def test_nao_atrasar_a_fila_nao_empurra_quem_ja_esta_atrasado():
    # OF 3 já está atrasada (OTD 10/11): no 1.1 o pedido não entra antes dela, mesmo com prazo folgado
    ofs = fila_com_pedido_no_limite("2026-11-10")
    pedidos, filas, _ = gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame([ped(1, "2026-11-30")]), REGRAS, None, {},
                                      agora=INICIO, modo="NÃO ATRASAR A FILA")
    assert pedidos.iloc[0].depois_de == "OF 4"           # depois da OF 3 e junto ao fim (empurra menos)
    assert filas.set_index("id_of").loc["3", "empurrado_h"] == 0


def test_sem_pedido_sem_estoque_as_tabelas_saem_com_as_colunas():
    # Todo pedido tem estoque: nada para encaixar, mas a tela e os indicadores leem as colunas
    com_estoque = {**ped(1, "2026-11-20"), "tem_estoque": "SIM"}
    pedidos, filas, _ = encaixar([of(1, 0)], [com_estoque])
    assert pedidos.empty
    for col in ("sugestao", "id_of", "atende_embarque", "maquina", "comparar_sugestao"):
        assert col in pedidos
    _, filas_vazias, _ = gerar_encaixe(pd.DataFrame([of(1, 0)]).iloc[0:0], pd.DataFrame([com_estoque]), REGRAS,
                                       None, {}, agora=INICIO)
    for col in ("maquina", "situacao", "atraso", "inicio_sugerido", "fim_sugerido"):
        assert col in filas_vazias


def test_alternativos_so_entram_com_a_opcao_ligada():
    # Regra 10: pedido atendido por estoque alternativo fica fora, a não ser que a opção esteja ligada
    alt = {**ped(1, "2026-11-20"), "tem_estoque": "SIM", "atendimento": "ALTERNATIVO",
           "alternativo_usado": "micra 19 no lugar de 18"}
    exato = {**ped(2, "2026-11-20"), "tem_estoque": "SIM", "atendimento": "EXATO", "alternativo_usado": None}
    sem = ped(3, "2026-11-20")
    ofs = [of(i, 10 * i) for i in range(4)]
    desligado, _, _ = encaixar(ofs, [alt, exato, sem])
    assert list(desligado.num_pedido) == ["3"] and desligado.estoque_alternativo.isna().all()
    ligado, filas, resumo = gerar_encaixe(pd.DataFrame(ofs), pd.DataFrame([alt, exato, sem]), REGRAS, None, {},
                                          agora=INICIO, encaixar_alternativos=True)
    assert sorted(ligado.num_pedido) == ["1", "3"]
    assert ligado.set_index("num_pedido").loc["1", "estoque_alternativo"] == "micra 19 no lugar de 18"
    assert filas.observacao.str.contains("tem estoque alternativo", na=False).sum() == 1
    assert "1 com estoque alternativo" in resumo
