"""
Sugestão de reserva de estoque para a carteira de pedidos (PCP_OF_CARTEIRA_PEDIDO).

Regra:
- Pedidos atendidos em ordem de embarque; cada pallet reservado sai do saldo.
- Só entra estoque DISPONIVEL; os pallets são reservados inteiros.
- Exato: mesma formulação, micra, família, largura, peso e peso do tubete.
- Alternativo: micra até ±2 OU formulação 1 degrau acima no rank (cadastro de formulações),
  mantendo família, largura, peso e peso do tubete. PCR só com PCR.
  Micra e formulação diferentes ao mesmo tempo contam como 2 alternativos e não são aceitas.
- O pedido é atendido por UM único produto (o exato ou um alternativo), sem misturar.
- O total reservado precisa ficar dentro da tolerância de ±5% do pedido. Os pallets mais
  parados (slow move) têm preferência, mas outra combinação é usada se eles não fecharem.
- Atendido -> tem_estoque "SIM" (e qual alternativo, se for o caso); senão "NÃO" (com o motivo).
  Os pallets escolhidos vão em pallets_reservados (OF/rua/sequência), com a quantidade e o peso.
- Estoque já solicitado (regra da planilha Excel, rev010): de cada produto sai antes o que já foi
  pedido em solicitação de reserva, o MAIOR entre a reserva_solicitada da carteira (soma das linhas
  de um pedido/prog) e a soma do relatório SOLICITACOES_RESERVA. Um pedido só usa o saldo livre do
  produto, em kg líquido.
- Kanban de cliente prioritário (cadastro de clientes prioritários, rev018): o pallet kanban cujo
  cliente_kanban está na lista só atende, na 1ª passada, os pedidos desse cliente. Depois os pedidos
  que ficaram sem estoque são refeitos com o que sobrou desses pallets liberado para todos.
  Ex.: kanban "BRASKEM - TRIUNFO" vai primeiro para "Braskem - Triunfo (1203)" e outras unidades.
"""
import pandas as pd

from core.regras.Prioridade import ListaPrioritarios
from core.regras.LimpezaCtlrPedidos import normalizar_desc_tecnica
from core.regras.LimpezaDataframe import extrair_familia, parse_dimensoes


TEM_ESTOQUE = "SIM"
SEM_ESTOQUE = "NÃO"

# Colunas da carteira que identificam o pedido na planilha de saída
COLUNAS_PEDIDO = ['num_pedido', 'prog', 'cliente', 'dt_embarque', 'id_pa', 'produto', 'formulacao',
                  'qtde_kg', 'tipo_venda']

TIPO_ESTOQUE_USADO = "DISPONIVEL"
TOLERANCIA_QTD = 0.05            # ±5% sobre o qtde_kg do pedido
TOLERANCIA_MICRA = 2.0           # micra até 2 acima ou abaixo
MAX_DEGRAUS_FORMULACAO = 1       # sobe no máximo 1 degrau no rank
CHAVES_IGUAIS = ["familia", "largura", "peso", "peso_tubete"]
LIMITE_COMBINACOES = 50_000      # combinações testadas por produto antes de desistir
SEM_LIMITE = float('inf')        # produto sem solicitação: o saldo não limita

# O rank das formulações vem do cadastro (tabela formulacoes_rank do banco):
# número maior = formulação superior; PCR tem o mesmo rank da versão normal.

_EPS = 1e-6


def _normalizar_formulacao(valor) -> str | None:
    if pd.isna(valor):
        return None
    return " ".join(str(valor).upper().split())


def _eh_pcr(formulacao) -> bool:
    return isinstance(formulacao, str) and "PCR" in formulacao.split()


def preparar_pedidos(df_carteira: pd.DataFrame, prioritarios: ListaPrioritarios | None = None) -> pd.DataFrame:
    """Extrai da carteira as características usadas na comparação com o estoque."""
    # O relatório repete o pedido uma vez para cada solicitação de reserva do produto
    # (só mudam reserva_solicitada e estoque_liquido); fica uma linha por pedido/prog/produto.
    ped = df_carteira.drop_duplicates(['num_pedido', 'prog', 'id_pa']).copy()
    ped['desc_tecnica'] = ped['produto'].map(normalizar_desc_tecnica)
    ped['familia'] = ped['desc_tecnica'].map(extrair_familia)
    ped[['largura', 'micra', 'peso', 'peso_tubete']] = ped['desc_tecnica'].apply(parse_dimensoes)
    ped['peso_tubete'] = ped['peso_tubete'].fillna(0)
    ped['formulacao_norm'] = ped['formulacao'].map(_normalizar_formulacao)
    ped['dt_embarque'] = pd.to_datetime(ped['dt_embarque'], errors='coerce', format='mixed', dayfirst=True)
    # Venda bruta é comparada com o peso bruto do pallet; a líquida, com o líquido
    ped['coluna_peso'] = ped['tipo_venda'].astype(str).str.upper().str.startswith('BRUTO').map(
        {True: 'peso_bruto', False: 'peso_liquido'}
    )
    # Linhas da lista de clientes prioritários em que o cliente do pedido aparece (só pelo nome)
    lista = prioritarios or ListaPrioritarios([])
    ped['linhas_cliente'] = ped['cliente'].map(lista.linhas_do_cliente)
    return ped.sort_values(['dt_embarque', 'num_pedido', 'prog'], kind='mergesort').reset_index(drop=True)


def preparar_pallets(df_estoque: pd.DataFrame, prioritarios: ListaPrioritarios | None = None) -> pd.DataFrame:
    """Filtra o estoque disponível e quebra cada linha em pallets individuais."""
    est = df_estoque[df_estoque['tipo_estoque'] == TIPO_ESTOQUE_USADO].copy()
    est['familia'] = est['tipo_familia_teste']
    est['formulacao_norm'] = est['grupo_formulacao'].map(_normalizar_formulacao)
    est['qtd_pallets'] = pd.to_numeric(est['qtd_pallets'], errors='coerce').fillna(1).clip(lower=1).astype(int)

    est['linha_estoque'] = est.index
    pallets = est.loc[est.index.repeat(est['qtd_pallets'])].copy()
    pallets['seq_pallet'] = pallets.groupby('linha_estoque').cumcount() + 1
    pallets['peso_liquido'] = pallets['peso_liquido'] / pallets['qtd_pallets']
    pallets['peso_bruto'] = pallets['peso_bruto'] / pallets['qtd_pallets']
    pallets['id_pallet'] = (pallets['id_of'].astype(str) + '/' + pallets['rua'].astype(str)
                            + '/' + pallets['seq_pallet'].astype(str) + 'de' + pallets['qtd_pallets'].astype(str))
    pallets['dias_parado'] = pallets['dias_parado'].fillna(0)
    pallets['disponivel'] = True
    # Kanban de cliente prioritário: linhas da lista donas do pallet (vazio = livre para todos)
    lista = prioritarios or ListaPrioritarios([])
    if 'kanban' in pallets:
        eh_kanban = pallets['kanban'].astype(str).str.strip().str.upper() == 'SIM'
    else:
        eh_kanban = pd.Series(False, index=pallets.index)
    cliente_kanban = pallets['cliente_kanban'] if 'cliente_kanban' in pallets else pd.Series(None, index=pallets.index)
    pallets['donos_kanban'] = [lista.linhas_do_cliente(c) if k else frozenset()
                               for k, c in zip(eh_kanban, cliente_kanban)]
    return pallets.reset_index(drop=True)


def _id_produto(valor) -> int | None:
    """id_pa como inteiro, igual nos três relatórios (35135, "35135" e "35135 - A - FILME...")."""
    numero = pd.to_numeric(str(valor).split(' - ')[0].strip(), errors='coerce')
    return None if pd.isna(numero) else int(numero)


def estoque_solicitado(df_carteira: pd.DataFrame, df_solicitacoes: pd.DataFrame | None) -> dict[int, float]:
    """Kg já solicitados de cada produto: o maior entre a carteira e o relatório de solicitações.

    Cada fonte deixa algo de fora: a carteira junta solicitações de mesmo peso; o relatório de
    solicitações não traz todas. Na carteira, o pedido se repete uma vez por solicitação do
    produto, então a soma das linhas de um pedido/prog é o total do produto.
    """
    if 'reserva_solicitada' in df_carteira:
        solicitada = pd.to_numeric(df_carteira['reserva_solicitada'], errors='coerce').fillna(0)
    else:
        solicitada = pd.Series(0.0, index=df_carteira.index)
    cart = df_carteira.assign(id_pa_num=df_carteira['id_pa'].map(_id_produto), solicitada=solicitada)
    por_cart = cart.groupby(['num_pedido', 'prog', 'id_pa_num'])['solicitada'].sum().groupby('id_pa_num').max()
    por_rel = pd.Series(dtype=float)
    if df_solicitacoes is not None and not df_solicitacoes.empty:
        sol = df_solicitacoes.assign(id_pa_num=df_solicitacoes['produto'].map(_id_produto),
                                     kg=pd.to_numeric(df_solicitacoes['qtde_kg'], errors='coerce'))
        por_rel = sol.dropna(subset=['id_pa_num', 'kg']).groupby('id_pa_num')['kg'].sum()
    junto = pd.concat([por_cart, por_rel], axis=1).fillna(0).max(axis=1)
    return {int(k): float(v) for k, v in junto.items() if v > 0}


def _validar_pedido(pedido, rank_formulacao: dict[str, int]) -> list[str]:
    motivos = []
    if pd.isna(pedido['qtde_kg']) or pedido['qtde_kg'] <= 0:
        motivos.append("quantidade ausente ou zero")
    if pd.isna(pedido['micra']):
        motivos.append("micra não identificada na descrição")
    ausentes = [c for c in CHAVES_IGUAIS if pd.isna(pedido[c])]
    if ausentes:
        motivos.append("características não identificadas: " + ", ".join(ausentes))
    if pedido['formulacao_norm'] is None:
        motivos.append("formulação ausente")
    elif pedido['formulacao_norm'] not in rank_formulacao:
        motivos.append(f"formulação não cadastrada no rank: {pedido['formulacao_norm']}")
    return motivos


def _candidatos(pedido, pallets: pd.DataFrame, rank_formulacao: dict[str, int],
                kanban_liberado: bool = True) -> tuple[pd.DataFrame, bool]:
    """Pallets disponíveis que podem atender o pedido (exato ou alternativo).

    Retorna (candidatos, se havia pallets descartados por micra e formulação diferentes).
    kanban_liberado=False (1ª passada): o kanban de cliente prioritário só serve aos pedidos dele.
    """
    mascara = pallets['disponivel'].copy()
    if not kanban_liberado:
        linhas = pedido['linhas_cliente']
        mascara &= pallets['donos_kanban'].map(lambda donos: not donos or bool(donos & linhas))
    for col in CHAVES_IGUAIS:
        if col == 'familia':
            mascara &= pallets[col] == pedido[col]
        else:
            mascara &= (pallets[col] - pedido[col]).abs() < _EPS

    dif_micra = pallets['micra'] - pedido['micra']
    mascara &= dif_micra.abs() <= TOLERANCIA_MICRA + _EPS

    form_ped = pedido['formulacao_norm']
    rank_ped = rank_formulacao[form_ped]
    rank_pallet = pallets['formulacao_norm'].map(rank_formulacao)
    dif_rank = rank_pallet - rank_ped
    mesma_form = pallets['formulacao_norm'] == form_ped
    acima = (dif_rank >= 1) & (dif_rank <= MAX_DEGRAUS_FORMULACAO)
    mascara &= mesma_form | acima.fillna(False)

    # PCR só com PCR (nos dois sentidos)
    mascara &= pallets['formulacao_norm'].map(_eh_pcr) == _eh_pcr(form_ped)

    cand = pallets[mascara].copy()
    cand['dif_micra'] = dif_micra[mascara]
    cand['dif_rank'] = dif_rank[mascara].fillna(0)
    cand['outra_form'] = (~mesma_form[mascara]).astype(int)

    # Micra e formulação diferentes ao mesmo tempo contam como 2 alternativos: não vale
    duplo = (cand['dif_micra'].abs() >= _EPS) & (cand['outra_form'] == 1)
    return cand[~duplo], bool(duplo.any())


def _escolher_pallets(grupo: pd.DataFrame, coluna_peso: str, minimo: float, maximo: float,
                      limite_liq: float = SEM_LIMITE):
    """Escolhe pallets (slow move primeiro) cuja soma fique entre mínimo e máximo.

    Testa as combinações começando pelos pallets mais parados, então a primeira que fecha
    é a que usa os mais antigos. Ex.: pedido de 1.000 kg com pallets de 800, 500 e 500 ->
    o 800 não fecha com nenhum outro, então usa 500 + 500 (pegar só os mais antigos recusaria).
    limite_liq: saldo livre do produto em kg líquido (estoque já solicitado descontado).
    Retorna (índices, total) ou (None, total mais próximo que coube no máximo).
    """
    ordenado = grupo.sort_values(['dias_parado', 'id_pallet'], ascending=[False, True])
    ordenado = ordenado[ordenado[coluna_peso].notna() & (ordenado[coluna_peso] > 0)]
    indices = ordenado.index.tolist()
    pesos = ordenado[coluna_peso].astype(float).tolist()
    liqs = (ordenado['peso_liquido'].fillna(0).astype(float).tolist() if 'peso_liquido' in ordenado
            else [0.0] * len(pesos))
    com_limite = limite_liq != SEM_LIMITE

    # restante[i] = soma dos pallets de i em diante (se não alcança o mínimo, nem tenta)
    restante = [0.0] * (len(pesos) + 1)
    for i in range(len(pesos) - 1, -1, -1):
        restante[i] = restante[i + 1] + pesos[i]

    melhor = 0.0
    # Cada item: (próximo pallet, total, pesos já pulados, pallets escolhidos, total líquido)
    pilha = [(0, 0.0, frozenset(), (), 0.0)]
    for _ in range(LIMITE_COMBINACOES):
        if not pilha:
            break
        i, acumulado, pulados, escolhidos, acum_liq = pilha.pop()
        melhor = max(melhor, acumulado)
        if acumulado >= minimo - _EPS:
            return [indices[j] for j in escolhidos], acumulado
        if i == len(pesos) or acumulado + restante[i] < minimo - _EPS:
            continue

        peso = pesos[i]
        # Com limite de saldo, pallets de mesmo peso só são iguais se o líquido também for
        chave = (round(peso, 3), round(liqs[i], 3)) if com_limite else round(peso, 3)
        pilha.append((i + 1, acumulado, pulados | {chave}, escolhidos, acum_liq))  # sem o pallet i
        # Com o pallet i (testado primeiro). Se um pallet mais antigo de mesmo peso já foi
        # pulado, trocar um pelo outro dá a mesma soma: não precisa testar de novo.
        if chave not in pulados and acumulado + peso <= maximo + _EPS \
                and acum_liq + liqs[i] <= limite_liq + _EPS:
            pilha.append((i + 1, acumulado + peso, pulados, escolhidos + (i,), acum_liq + liqs[i]))
    return None, melhor


def _descrever_alternativo(linha, pedido) -> str:
    motivos = []
    if abs(linha['dif_micra']) >= _EPS:
        motivos.append(f"MICRA {pedido['micra']:g}->{linha['micra']:g}")
    if linha['outra_form']:
        motivos.append(f"FORMULAÇÃO {pedido['formulacao_norm']}->{linha['formulacao_norm']}")
    return (f"{linha['id_pa']} - {linha['desc_tecnica']} ({linha['formulacao_norm']}) "
            f"[{' + '.join(motivos)}]")


def _processar_pedido(pedido, pallets: pd.DataFrame, rank_formulacao: dict[str, int],
                      saldo: dict | None = None, solicitado: dict | None = None,
                      kanban_liberado: bool = True):
    """Tenta atender o pedido com um único produto. Retorna (resumo, índices dos pallets).

    saldo: kg líquido livre por produto (só dos produtos com solicitação); é atualizado aqui.
    """
    saldo = {} if saldo is None else saldo
    solicitado = solicitado or {}
    resumo = {'tem_estoque': SEM_ESTOQUE, 'atendimento': None, 'alternativo_usado': None,
              'motivo_sem_estoque': None}

    motivos = _validar_pedido(pedido, rank_formulacao)
    if motivos:
        resumo['motivo_sem_estoque'] = "; ".join(motivos)
        return resumo, []

    cand, tinha_duplo = _candidatos(pedido, pallets, rank_formulacao, kanban_liberado)
    if cand.empty:
        if tinha_duplo:
            resumo['motivo_sem_estoque'] = ("só há estoque com micra e formulação diferentes "
                                            "(2 alternativos ao mesmo tempo)")
        else:
            resumo['motivo_sem_estoque'] = "sem estoque elegível (exato ou alternativo)"
        return resumo, []

    qtd = float(pedido['qtde_kg'])
    coluna_peso = pedido['coluna_peso']
    minimo, maximo = qtd * (1 - TOLERANCIA_QTD), qtd * (1 + TOLERANCIA_QTD)

    # Um grupo por produto (id_pa), do mais parecido com o pedido para o menos parecido
    cand['abs_micra'] = cand['dif_micra'].abs()
    cand['lado'] = (cand['dif_micra'] < 0).astype(int)  # em empate, micra acima primeiro
    ordem_grupos = (cand.groupby('id_pa')
                    .agg(dif_rank=('dif_rank', 'first'), outra_form=('outra_form', 'first'),
                         abs_micra=('abs_micra', 'first'), lado=('lado', 'first'),
                         dias_parado=('dias_parado', 'max'))
                    .sort_values(['dif_rank', 'outra_form', 'abs_micra', 'lado', 'dias_parado'],
                                 ascending=[True, True, True, True, False], kind='mergesort'))

    melhor_parcial = 0.0
    todos_solicitados = all(saldo.get(_id_produto(i), SEM_LIMITE) <= _EPS for i in ordem_grupos.index)
    for id_pa in ordem_grupos.index:
        grupo = cand[cand['id_pa'] == id_pa]
        livre = saldo.get(_id_produto(id_pa), SEM_LIMITE)
        if livre <= _EPS:
            continue                                   # estoque do produto já está todo solicitado
        escolhidos, acumulado = _escolher_pallets(grupo, coluna_peso, minimo, maximo, livre)
        if escolhidos is None:
            melhor_parcial = max(melhor_parcial, acumulado)
            continue

        primeira = grupo.loc[escolhidos[0]]
        exato = primeira['abs_micra'] < _EPS and primeira['outra_form'] == 0
        resumo.update({
            'tem_estoque': TEM_ESTOQUE,
            'atendimento': 'EXATO' if exato else 'ALTERNATIVO',
            'alternativo_usado': None if exato else _descrever_alternativo(primeira, pedido),
        })
        if livre != SEM_LIMITE:
            saldo[_id_produto(id_pa)] = livre - pallets.loc[escolhidos, 'peso_liquido'].fillna(0).sum()
        return resumo, escolhidos

    # Não fechou: explica se falta estoque ou se os pallets não encaixam na tolerância.
    # O total de cada produto já sai sem o que está solicitado (proporcional, na venda bruta).
    if todos_solicitados:
        primeiro = _id_produto(ordem_grupos.index[0])
        resumo['motivo_sem_estoque'] = (f"estoque elegível já está todo solicitado para outros pedidos "
                                        f"({solicitado.get(primeiro, 0):,.0f} kg solicitados do {primeiro})")
        return resumo, []
    totais = {}
    for id_pa, g in cand.groupby('id_pa', sort=False):
        total = g[coluna_peso].sum()
        total_liq = g['peso_liquido'].sum()
        livre = saldo.get(_id_produto(id_pa), SEM_LIMITE)
        if livre != SEM_LIMITE and total_liq > 0 and livre < total_liq:
            total = total * max(livre, 0) / total_liq
        totais[id_pa] = total
    melhor = max(totais, key=lambda k: totais[k])      # o 1º com o maior total
    total_elegivel = totais[melhor]
    if total_elegivel < minimo:
        resumo['motivo_sem_estoque'] = (f"estoque insuficiente: melhor produto tem {total_elegivel:,.0f} kg "
                                        f"de {qtd:,.0f} kg ({total_elegivel / qtd:.0%})")
        if solicitado.get(_id_produto(melhor), 0) > 0:
            resumo['motivo_sem_estoque'] += (f"; já descontados {solicitado[_id_produto(melhor)]:,.0f} kg "
                                             f"solicitados do {melhor}")
    else:
        resumo['motivo_sem_estoque'] = (f"pallets não fecham na tolerância de ±{TOLERANCIA_QTD:.0%} "
                                        f"({minimo:,.0f} a {maximo:,.0f} kg); mais próximo: {melhor_parcial:,.0f} kg")
    return resumo, []


def sugerir_reservas(df_carteira: pd.DataFrame, df_estoque: pd.DataFrame,
                     rank_formulacao: dict[str, int], df_solicitacoes: pd.DataFrame | None = None,
                     prioritarios: ListaPrioritarios | None = None,
                     descontar_solicitado: bool = True) -> pd.DataFrame:
    """Aplica a regra de reserva em toda a carteira, em ordem de embarque.

    Devolve uma linha por pedido dizendo se tem estoque e, se for alternativo, qual produto usar.
    df_solicitacoes: relatório SOLICITACOES_RESERVA (desconta o estoque já solicitado).
    prioritarios: lista de clientes prioritários (kanban deles vai primeiro para eles).
    """
    pedidos = preparar_pedidos(df_carteira, prioritarios)
    pallets = preparar_pallets(df_estoque, prioritarios)

    solicitado = estoque_solicitado(df_carteira, df_solicitacoes) if descontar_solicitado else {}
    total_por_produto = pallets.groupby(pallets['id_pa'].map(_id_produto))['peso_liquido'].sum()
    saldo = {k: total_por_produto[k] - v for k, v in solicitado.items() if k in total_por_produto.index}

    def processar(indice, liberado):
        pedido = pedidos.loc[indice]
        resumo, escolhidos = _processar_pedido(pedido, pallets, rank_formulacao, saldo, solicitado, liberado)
        # O que vai ser reservado: pallets identificados por OF/rua/sequência
        reservados = pallets.loc[escolhidos]
        resumo['qtd_pallets_reservados'] = len(reservados)
        resumo['peso_reservado'] = reservados[pedido['coluna_peso']].sum() if escolhidos else None
        resumo['pallets_reservados'] = ", ".join(reservados['id_pallet']) or None
        # O estoque usado sai do saldo para os próximos pedidos
        pallets.loc[escolhidos, 'disponivel'] = False
        return resumo

    # 1ª passada: kanban de cliente prioritário só para os pedidos dele
    resumos = {i: processar(i, False) for i in pedidos.index}
    # 2ª passada: o que sobrou desse kanban vale para os pedidos que ficaram sem estoque
    sobrou_kanban = (pallets['disponivel'] & pallets['donos_kanban'].map(bool)).any()
    if sobrou_kanban:
        for i in pedidos.index:
            if resumos[i]['tem_estoque'] == SEM_ESTOQUE:
                resumos[i] = processar(i, True)

    saida = pd.DataFrame([resumos[i] for i in pedidos.index], index=pedidos.index)
    return pd.concat([pedidos[COLUNAS_PEDIDO], saida], axis=1)
