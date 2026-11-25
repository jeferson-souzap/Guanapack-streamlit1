"""
Simulação da programação das extrusoras (11/11/2026, pedido do usuário).

Em vez de "programar a OF", o usuário monta cenários: escolhe as regras, gera uma sugestão de fila
(o mesmo encaixe da planilha) e depois mexe na fila à mão — muda a posição, troca de máquina — vendo
na hora as datas, quem atrasa e quantas trocas de formulação ficam. Cada cenário pode ser salvo e
comparado com outros. A ferramenta não grava nada no ERP: o cenário escolhido é a fila para replicar.

Regras do cenário (RegrasCenario):
- sequencia: NÃO QUEBRAR / PODE QUEBRAR (as do encaixe, regras 6 e 7) ou IGNORAR (não confere);
- prioridade: PRAZO (encaixe pelo prazo OTD) ou FORMULACAO (ignora as datas: depois do encaixe,
  as OFs que não são fixas de cada máquina são agrupadas pela sequência de formulação — sobe a
  partir do grupo da última OF fixa e depois desce —, mantendo a ordem atual dentro de cada grupo);
- ordens_fixas: quantas OFs do começo de cada máquina não mudam (no encaixe);
- prioritarios: clientes prioritários primeiro (sim/não);
- setup_min: minutos a mais em cada troca de grupo de formulação (0 = como o encaixe);
- maquinas: quais máquinas entram (vazio = todas);
- fator_kgh: ajuste do kg/h dos pedidos novos (1.0 = mediana do relatório);
- salto_micra: maior diferença de micra entre duas OFs seguidas (regra 9 do encaixe). Acima disso a
  linha é marcada como salto, com as micras das OFs de estoque a gerar entre as duas;
- encaixar_alternativos: encaixa também os pedidos atendidos só por estoque alternativo (regra 10);
- modo: NÃO ATRASAR A FILA / ATENDER O PEDIDO (regra 11 do encaixe).

Avaliação (25/11/2026): avaliar_programacao diz se a programação está BOA / ATENÇÃO / RUIM e monta um
plano de mudanças que tira OFs do atraso sem atrasar quem está no prazo (ver o fim do arquivo).

Subida e descida de micra (17/11/2026): vale na fila inteira, também na troca de grupo de formulação.
Agrupar por formulação ordena também a micra dentro de cada grupo, continuando da micra da OF
anterior: se ela está mais perto da menor micra do grupo, o grupo sobe; senão, desce.

Datas da fila (recalcular): cada máquina começa no início da 1ª OF do planejamento; cada OF dura o
que dura no planejamento (pedido novo: qtde / kg/h da máquina na micra) e mantém o intervalo que
tinha antes dela no planejamento (pedido novo: sem intervalo). Sem mexer em nada, as datas são as do
planejamento e as do encaixe. OF levada para outra máquina passa a durar qtde / kg/h dessa máquina.
"""
from dataclasses import asdict, dataclass, field

import pandas as pd

from core.regras import EncaixeMaquinas
from core.regras.EncaixeMaquinas import (ATENDER_PEDIDO, NAO_QUEBRAR, PODE_QUEBRAR, SITUACAO_NAO_PROG, Encaixe, Pedido, e_salto,
                                         micra_do_produto, nivel_formulacao, texto_salto)
from core.regras.LimpezaDataframe import extrair_familia, parse_dimensoes
from core.regras.Prioridade import ListaPrioritarios

ENTRAM = ("NOVO", SITUACAO_NAO_PROG)       # entram na fila pelo encaixe (pedido novo ou OF não programada)

IGNORAR = "IGNORAR"
SEQUENCIAS = (NAO_QUEBRAR, PODE_QUEBRAR, IGNORAR)
PRAZO = "PRAZO"
FORMULACAO = "FORMULACAO"

# Situação de cada linha da fila
NAO_ATENDE = "NÃO ATENDE"
JA_ATRASADA = "JÁ ATRASADA"
PASSA_A_ATRASAR = "PASSA A ATRASAR"
OK = "OK"

COLUNAS = ["chave", "maquina", "ordem", "situacao", "id_of", "pedido", "prog", "cliente", "id_pa", "produto",
           "formulacao", "grupo_formulacao", "nivel_formulacao", "qtde_kg", "dur_h", "intervalo_h",
           "inicio_atual", "fim_atual", "inicio", "fim", "empurrado_h", "data_otd", "atraso", "troca_grupo",
           "quebra_sequencia", "micra", "salto_micra", "prioritario", "maquina_original", "roda_em", "alerta"]


@dataclass
class RegrasCenario:
    sequencia: str = NAO_QUEBRAR
    prioridade: str = PRAZO
    ordens_fixas: int = 3
    prioritarios: bool = True
    setup_min: float = 0.0
    maquinas: list = field(default_factory=list)
    fator_kgh: float = 1.0
    salto_micra: float = field(default_factory=lambda: EncaixeMaquinas.SALTO_MICRA)
    encaixar_alternativos: bool = field(default_factory=lambda: EncaixeMaquinas.ENCAIXAR_ALTERNATIVOS)
    modo: str = field(default_factory=lambda: EncaixeMaquinas.MODO_ENCAIXE)

    def texto(self) -> str:
        partes = [self.modo.lower(), f"sequência {self.sequencia}", "pelo prazo" if self.prioridade == PRAZO else "agrupado por formulação",
                  f"{self.ordens_fixas} fixas", "prioritários primeiro" if self.prioritarios else "sem prioritários"]
        if self.setup_min:
            partes.append(f"setup {self.setup_min:g} min/troca")
        if self.fator_kgh != 1:
            partes.append(f"kg/h {self.fator_kgh:.0%}")
        partes.append(f"salto de micra > {self.salto_micra:g} µ")
        if self.encaixar_alternativos:
            partes.append("encaixa os alternativos")
        if self.maquinas:
            partes.append("máquinas: " + ", ".join(self.maquinas))
        return " · ".join(partes)

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Cenario:
    """Uma fila por máquina (itens) e o que é preciso para recalcular as datas."""
    regras: RegrasCenario
    itens: pd.DataFrame
    inicio: dict            # máquina -> início da fila
    taxas: dict             # máquina -> {micra: kg/h}
    rank: dict


# ===================================================================== gerar a sugestão

def _pedido_do_item(it) -> Pedido:
    """Pedido "de mentira" com as medidas de uma OF, para conferir em que máquinas ela roda."""
    dims = parse_dimensoes(it.produto)
    tubete = dims["peso_tubete"]
    return Pedido(num_pedido=it.pedido, prog=it.prog, cliente=it.cliente, embarque=pd.NaT, id_pa=it.id_pa,
                  produto=it.produto, formulacao=it.grupo_form or it.formulacao, qtde=it.qtde,
                  familia=extrair_familia(it.produto) or "", largura=dims["largura"], micra=dims["micra"],
                  peso=dims["peso"], tubete=0.0 if pd.isna(tubete) else float(tubete), prioritario=it.prioritario)


def gerar_cenario(plan, reserva, regras_maq, prioritarios=None, mapa_otd=None, rank=None,
                  regras: RegrasCenario | None = None, agora=None, travadas: pd.DataFrame | None = None,
                  avisos: list | None = None) -> Cenario:
    """Roda o encaixe com as regras do cenário e devolve a fila sugerida, pronta para mexer.

    travadas (chave, maquina, ordem): OFs travadas no cenário anterior. Elas voltam para a mesma
    máquina e posição e continuam travadas; as outras se arrumam em volta (antes de agrupar por
    formulação, que também respeita a trava). Os avisos vão para a lista avisos."""
    regras = regras or RegrasCenario()
    rank = dict(rank or {})
    if regras.maquinas:
        regras_maq = [r for r in regras_maq if r["apelido"] in regras.maquinas]
    enc = Encaixe(plan, reserva, regras_maq, prioritarios if regras.prioritarios else ListaPrioritarios([]),
                  mapa_otd, agora, rank=None if regras.sequencia == IGNORAR else rank,
                  pode_quebrar=(regras.sequencia == PODE_QUEBRAR), ordens_fixas=regras.ordens_fixas,
                  fator_kgh=regras.fator_kgh, salto_micra=regras.salto_micra,
                  encaixar_alternativos=regras.encaixar_alternativos, modo=regras.modo).executar()

    apelidos = [r["apelido"] for r in regras_maq]
    linhas, inicio = [], {}
    for m, fila in enumerate(enc.filas):
        maq = apelidos[m]
        originais = [it for it in fila if not it.novo]
        inicio[maq] = originais[0].ini0 if originais else (fila[0].ini if fila else enc.agora)
        anterior_fim = None
        for it in originais:                           # intervalo antes de cada OF no planejamento
            it._intervalo = 0.0 if anterior_fim is None else max(0.0, (it.ini0 - anterior_fim).total_seconds() / 3600)
            anterior_fim = it.fim0
        for j, it in enumerate(fila, start=1):
            p = _pedido_do_item(it)
            roda = [apelidos[k] for k in range(len(apelidos)) if not enc.bloqueios(k, p)]
            dur = (it.fim - it.ini) if it.novo else (it.fim0 - it.ini0)
            linhas.append({
                "chave": Encaixe.nome(it), "maquina": maq, "ordem": j, "travada": False,
                "situacao": SITUACAO_NAO_PROG if it.nao_prog else "NOVO" if it.novo else ("FIXA" if it.fixa else ""),
                "id_of": None if it.novo and not it.nao_prog else it.id_of, "pedido": it.pedido or None, "prog": it.prog or None,
                "cliente": it.cliente or None, "id_pa": it.id_pa, "produto": it.produto, "formulacao": it.formulacao,
                "grupo_formulacao": (it.grupo_form or it.formulacao) or None, "qtde_kg": it.qtde,
                "dur_h": dur.total_seconds() / 3600, "intervalo_h": 0.0 if it.novo else it._intervalo,
                "inicio_atual": None if it.novo else it.ini0, "fim_atual": None if it.novo else it.fim0,
                "prazo": it.prazo, "prioritario": bool(it.prioritario), "maquina_original": maq,
                "roda_em": ", ".join(roda), "micra": micra_do_produto(it.produto),
            })
    itens = pd.DataFrame(linhas)
    taxas = {apelidos[m]: dict(t) for m, t in enumerate(enc.taxas)}
    cen = Cenario(regras=regras, itens=itens, inicio=inicio, taxas=taxas, rank=rank)
    avs = manter_travadas(cen, travadas) if travadas is not None and not itens.empty else []
    if avisos is not None:
        avisos.extend(avs)
    if regras.prioridade == FORMULACAO and not itens.empty:
        for maq in itens["maquina"].unique():
            agrupar_por_formulacao(cen, maq)
    return recalcular(cen)


def manter_travadas(cen: Cenario, travadas: pd.DataFrame) -> list[str]:
    """Põe as OFs travadas de um cenário anterior na mesma máquina e posição, travadas."""
    if travadas is None or travadas.empty:
        return []
    avisos = []
    presentes = set(cen.itens["chave"])
    maquinas = set(cen.itens["maquina"]) | set(cen.inicio)
    linhas = []
    for r in travadas.itertuples():
        if r.chave not in presentes:
            avisos.append(f"{r.chave} estava travada, mas não entrou nesta sugestão (máquina fora do cenário "
                          "ou já não está no planejamento).")
            continue
        maq = r.maquina
        if maq not in maquinas:
            maq = cen.itens.loc[cen.itens["chave"] == r.chave, "maquina"].iloc[0]
            avisos.append(f"{r.chave} estava travada na {r.maquina}, que não entra neste cenário; ficou travada na {maq}.")
        linhas.append({"chave": r.chave, "maquina": maq, "ordem": int(r.ordem), "travada": True})
    if linhas:
        avisos += [a.replace("era FIXA e foi mexida", "travada saiu do lugar de FIXA da sugestão")
                   for a in aplicar_mudancas(cen, pd.DataFrame(linhas))]
    return avisos


# ===================================================================== mexer na fila

def _taxa(taxas: dict, micra) -> float:
    if not taxas or micra is None or pd.isna(micra):
        return 0.0
    if float(micra) in taxas:
        return taxas[float(micra)]
    perto = min(taxas, key=lambda k: (abs(k - micra), k))
    return taxas[perto]


def _com_travadas(fila: pd.DataFrame, presas: pd.Series) -> pd.DataFrame:
    """Numera a fila de uma máquina: as linhas presas (travadas) ficam na posição pos_alvo; as outras
    ocupam os lugares que sobram, na ordem de ordem_alvo. Duas presas no mesmo lugar: a 2ª vai para o
    próximo livre."""
    n = len(fila)
    lugares: dict[int, str] = {}
    for r in fila[presas].sort_values("pos_alvo", kind="stable").itertuples():
        p = int(min(max(round(float(r.pos_alvo)), 1), n))
        livres = [q for q in range(p, n + 1) if q not in lugares] or [q for q in range(n, 0, -1) if q not in lugares]
        lugares[livres[0]] = r.chave
    soltas = iter(fila[~presas].sort_values("ordem_alvo", kind="stable")["chave"])
    ordem = {}
    for p in range(1, n + 1):
        ordem[lugares[p] if p in lugares else next(soltas)] = p
    return fila.assign(ordem=fila["chave"].map(ordem))


def aplicar_mudancas(cen: Cenario, editado: pd.DataFrame) -> list[str]:
    """Aplica as colunas ordem, maquina e travada editadas na tela. Linha mudada vai para a posição
    pedida (ordem 3 = passa a ser a 3ª da máquina). Linha travada não sai do lugar quando as outras
    mudam (se for ela a mudada, vai para o lugar novo e continua travada). Devolve avisos."""
    itens = cen.itens.set_index("chave")
    if "travada" not in itens:
        itens["travada"] = False
    avisos = []
    novo = itens.copy()
    novo["ordem_alvo"] = novo["ordem"].astype(float)
    novo["pos_alvo"] = novo["ordem"].astype(float)
    for r in editado.itertuples():
        if r.chave not in itens.index:
            continue
        antes = itens.loc[r.chave]
        trava = getattr(r, "travada", None)
        if trava is not None and not pd.isna(trava):
            novo.loc[r.chave, "travada"] = bool(trava)
        maq = r.maquina if isinstance(r.maquina, str) and r.maquina else antes["maquina"]
        ordem = pd.to_numeric(r.ordem, errors="coerce")
        if pd.isna(ordem):
            ordem = antes["ordem"]
        if maq == antes["maquina"] and float(ordem) == float(antes["ordem"]):
            continue
        if antes["situacao"] == "FIXA":
            avisos.append(f"{r.chave} era FIXA e foi mexida.")
        if maq != antes["maquina"]:
            if maq not in str(antes["roda_em"]).split(", "):
                avisos.append(f"{r.chave}: pelas regras do cadastro, {maq} não roda este produto.")
            kgh = _taxa(cen.taxas.get(maq, {}), antes["micra"])
            if kgh > 0:
                novo.loc[r.chave, "dur_h"] = antes["qtde_kg"] / kgh
            else:
                avisos.append(f"{r.chave}: {maq} sem kg/h no relatório; ficou a duração de antes.")
        novo.loc[r.chave, "maquina"] = maq
        novo.loc[r.chave, "ordem_alvo"] = float(ordem) - 0.5      # entra antes de quem já está nessa posição
        novo.loc[r.chave, "pos_alvo"] = float(ordem)
    novo = novo.reset_index()
    partes = [_com_travadas(fila, fila["travada"].fillna(False).astype(bool)) for _, fila in novo.groupby("maquina", sort=False)]
    cen.itens = pd.concat(partes).drop(columns=["ordem_alvo", "pos_alvo"]).sort_values(["maquina", "ordem"]).reset_index(drop=True)
    recalcular(cen)
    return avisos


def agrupar_por_formulacao(cen: Cenario, maquina: str):
    """Agrupa as OFs que não são fixas pela sequência de formulação: a partir do nível da última OF
    fixa sobe (níveis maiores ou iguais, em ordem crescente) e depois desce (os menores, em ordem
    decrescente). Sem nível: no fim. Dentro de cada grupo a micra sobe ou desce continuando da micra
    da OF anterior (a que está mais perto: da menor, sobe; da maior, desce); OF sem micra fica no fim
    do grupo, na ordem atual. OFs fixas e travadas não saem do lugar."""
    it = cen.itens
    if "travada" not in it:
        it["travada"] = False
    fila = it[it["maquina"] == maquina].sort_values("ordem")
    if fila.empty:
        return
    niveis = pd.Series([_nivel(g, f, cen.rank) for g, f in zip(fila["grupo_formulacao"], fila["formulacao"])],
                       index=fila.index, dtype=object)
    fixas = fila["situacao"] == "FIXA"
    presas = fixas | fila["travada"].fillna(False).astype(bool)
    base = niveis[fixas].dropna()
    ref = base.iloc[-1] if not base.empty else (niveis.dropna().min() if niveis.notna().any() else 0)

    def chave(n):
        if n is None or pd.isna(n):
            return (2, 0)
        return (0, n) if n >= ref else (1, -n)

    k = niveis.map(chave)
    micras = [_micra_linha(r) for r in fila.itertuples()]
    ordem_nova = sorted(range(len(fila)), key=lambda j: k.iloc[j])          # estável: mantém a ordem no grupo
    base_micra = [micras[j] for j in range(len(fila)) if fixas.iloc[j] and micras[j] is not None]
    ordem_nova = ordenar_micra_nos_grupos(ordem_nova, [k.iloc[j] for j in range(len(fila))], micras,
                                          base_micra[-1] if base_micra else None)
    fila = fila.assign(pos_alvo=fila["ordem"].astype(float), ordem_alvo=0.0)
    fila.iloc[ordem_nova, fila.columns.get_loc("ordem_alvo")] = list(range(len(fila)))
    fila = _com_travadas(fila, presas).drop(columns=["pos_alvo", "ordem_alvo"])
    it.loc[fila.index, "ordem"] = fila["ordem"]
    cen.itens = it.sort_values(["maquina", "ordem"]).reset_index(drop=True)
    recalcular(cen)


def _micra_linha(r) -> float | None:
    m = getattr(r, "micra", None)
    if m is None or pd.isna(m):
        return micra_do_produto(r.produto)
    return float(m)


def ordenar_micra_nos_grupos(ordem: list, grupos: list, micras: list, ultima) -> list:
    """Dentro de cada grupo seguido de ordem (mesmo valor em grupos), põe a micra em ordem: sobe se a
    micra anterior (ultima) está mais perto da menor micra do grupo, desce se está mais perto da maior.
    Sem micra anterior, sobe. OFs sem micra ficam no fim do grupo, na ordem em que estavam."""
    saida, j = [], 0
    while j < len(ordem):
        fim = j
        while fim < len(ordem) and grupos[ordem[fim]] == grupos[ordem[j]]:
            fim += 1
        bloco = ordem[j:fim]
        com = [x for x in bloco if micras[x] is not None]
        sem = [x for x in bloco if micras[x] is None]
        if com:
            menor = min(micras[x] for x in com)
            maior = max(micras[x] for x in com)
            desce = ultima is not None and abs(ultima - maior) < abs(ultima - menor)
            com = sorted(com, key=lambda x: -micras[x] if desce else micras[x])   # estável no empate
            ultima = micras[com[-1]]
        saida += com + sem
        j = fim
    return saida


# ===================================================================== datas e indicadores

def recalcular(cen: Cenario) -> Cenario:
    """Datas de cada OF (ver cabeçalho), situação de atraso, trocas e quebras de sequência."""
    it = cen.itens
    if it.empty:
        return cen
    setup = pd.Timedelta(minutes=float(cen.regras.setup_min or 0))
    it = it.sort_values(["maquina", "ordem"], kind="stable").reset_index(drop=True)
    it["travada"] = it["travada"].fillna(False).astype(bool) if "travada" in it else False   # cenário salvo antes da trava
    it["nivel_formulacao"] = pd.Series([_nivel(g, f, cen.rank) for g, f in zip(it["grupo_formulacao"], it["formulacao"])],
                                       index=it.index, dtype=object)
    if "micra" not in it:
        it["micra"] = None
    it["micra"] = [_micra_linha(r) for r in it.itertuples()]
    limite = float(cen.regras.salto_micra or 0)
    inicios, fins, trocas, quebras, saltos = [], [], [], [], []
    for maq, fila in it.groupby("maquina", sort=False):
        t = pd.Timestamp(cen.inicio.get(maq, fila["inicio_atual"].dropna().min()))
        niveis = _herdar(list(fila["nivel_formulacao"]))
        micras = list(fila["micra"])
        conhecidas = sorted(cen.taxas.get(maq, {}))
        saltos += [texto_salto(micras[j - 1], micras[j], limite, conhecidas)
                   if j > 0 and e_salto(micras[j - 1], micras[j], limite) else None for j in range(len(micras))]
        for j, r in enumerate(fila.itertuples()):
            troca = j > 0 and niveis[j] is not None and niveis[j - 1] is not None and niveis[j] != niveis[j - 1]
            if j > 0:
                t += pd.Timedelta(hours=float(r.intervalo_h or 0))
                if troca:
                    t += setup
            inicio = t
            t = inicio + pd.Timedelta(hours=float(r.dur_h or 0))
            inicios.append(inicio)
            fins.append(t)
            trocas.append(bool(troca))
            antes = niveis[j - 1] if j > 0 else None
            depois = niveis[j + 1] if j + 1 < len(niveis) else None
            quebras.append(r.situacao in ENTRAM and None not in (antes, depois, niveis[j])
                           and not (min(antes, depois) <= niveis[j] <= max(antes, depois)))
    it["inicio"], it["fim"], it["troca_grupo"], it["quebra_sequencia"] = inicios, fins, trocas, quebras
    it["salto_micra"] = saltos
    it["empurrado_h"] = [None if pd.isna(a) else round((i - a).total_seconds() / 3600, 1)
                         for i, a in zip(it["inicio"], it["inicio_atual"])]
    it["data_otd"] = [None if p is None or pd.isna(p) else p - pd.Timedelta(days=1) for p in it["prazo"]]
    it["atraso"] = [_atraso(r) for r in it.itertuples()]
    it["alerta"] = [_alerta(r) for r in it.itertuples()]
    cen.itens = it
    return cen


def _nivel(grupo, formulacao, rank) -> int | None:
    """Nível pelo grupo de formulação; sem ele, pela formulação (mesma regra do encaixe)."""
    n = nivel_formulacao(grupo, rank)
    return n if n is not None else nivel_formulacao(formulacao, rank)


def _herdar(niveis: list) -> list:
    """Nível vazio fica com o da OF anterior (as do começo, com o da 1ª que tem)."""
    saida = [None if n is None or pd.isna(n) else int(n) for n in niveis]
    ultimo = None
    for j, n in enumerate(saida):
        saida[j] = ultimo if n is None else n
        ultimo = saida[j]
    proximo = None
    for j in range(len(saida) - 1, -1, -1):
        saida[j] = proximo if saida[j] is None else saida[j]
        proximo = saida[j]
    return saida


def _atraso(r) -> str | None:
    if r.prazo is None or pd.isna(r.prazo):
        return None
    if r.fim < r.prazo:
        return OK
    if r.situacao in ENTRAM:
        return NAO_ATENDE
    return JA_ATRASADA if pd.notna(r.fim_atual) and r.fim_atual >= r.prazo else PASSA_A_ATRASAR


def _alerta(r) -> str:
    partes = []
    if r.atraso in (NAO_ATENDE, PASSA_A_ATRASAR, JA_ATRASADA):
        partes.append(("⚠️ " if r.prioritario else "") + r.atraso.lower())
    if r.quebra_sequencia:
        partes.append("quebra a sequência")
    if isinstance(r.salto_micra, str):
        partes.append(r.salto_micra)
    if r.maquina != r.maquina_original:
        partes.append(f"veio da {r.maquina_original}")
    if r.roda_em is not None and r.maquina not in str(r.roda_em).split(", "):
        partes.append("máquina não roda pelo cadastro")
    return " · ".join(partes)


def indicadores(cen: Cenario) -> dict:
    it = cen.itens
    if it.empty:
        return {}
    novos = it[it["situacao"].isin(ENTRAM)]
    fim = it.groupby("maquina")["fim"].max()
    return {
        "novos": len(novos),
        "novos_no_prazo": int((novos["atraso"] == OK).sum()),
        "passam_a_atrasar": int((it["atraso"] == PASSA_A_ATRASAR).sum()),
        "ja_atrasadas": int((it["atraso"] == JA_ATRASADA).sum()),
        "fora_do_prazo": int(it["atraso"].isin([NAO_ATENDE, PASSA_A_ATRASAR, JA_ATRASADA]).sum()),
        "prioritarios_fora": int((it["prioritario"] & it["atraso"].isin([NAO_ATENDE, PASSA_A_ATRASAR, JA_ATRASADA])).sum()),
        "trocas_grupo": int(it["troca_grupo"].sum()),
        "quebras": int(it["quebra_sequencia"].sum()),
        "saltos_micra": int(it["salto_micra"].notna().sum()),
        "horas_empurradas": round(float(pd.to_numeric(it["empurrado_h"], errors="coerce").clip(lower=0).sum()), 1),
        "fim_das_filas": {m: f for m, f in fim.items()},
    }


# ===================================================================== salvar e abrir

def para_json(cen: Cenario) -> dict:
    itens = cen.itens.copy()
    for c in itens.columns:
        if pd.api.types.is_datetime64_any_dtype(itens[c]) or itens[c].map(lambda v: isinstance(v, pd.Timestamp)).any():
            itens[c] = itens[c].map(lambda v: None if v is None or pd.isna(v) else pd.Timestamp(v).isoformat())
    return {"regras": cen.regras.dict(), "itens": itens.astype(object).where(itens.notna(), None).to_dict("records"),
            "inicio": {m: pd.Timestamp(v).isoformat() for m, v in cen.inicio.items()},
            "taxas": {m: {str(k): v for k, v in t.items()} for m, t in cen.taxas.items()},
            "rank": cen.rank}


def de_json(d: dict) -> Cenario:
    itens = pd.DataFrame(d["itens"])
    for c in ("inicio_atual", "fim_atual", "inicio", "fim", "prazo", "data_otd"):
        if c in itens:
            itens[c] = pd.to_datetime(itens[c], errors="coerce")
    cen = Cenario(regras=RegrasCenario(**d["regras"]), itens=itens,
                  inicio={m: pd.Timestamp(v) for m, v in d["inicio"].items()},
                  taxas={m: {float(k): v for k, v in t.items()} for m, t in d["taxas"].items()}, rank=d.get("rank", {}))
    return recalcular(cen)


# ===================================================================== avaliação da programação
# (25/11/2026, pedido do usuário: "uma simulação que seja capaz de dizer se a programação está boa ou
# não e o que pode melhorar para não atrasar o que já está atrasado")
#
# avaliar_programacao(cen) olha o cenário como está e devolve:
# - situacao BOA / ATENÇÃO / RUIM e uma nota de 0 a 100:
#   RUIM    = algum cliente prioritário fora do prazo ou alguma OF que estava no prazo passa a atrasar;
#   ATENÇÃO = há pedido novo que não atende, OF já atrasada que dá para recuperar, pedido no meio de
#             sequência de formulação ou salto de micra;
#   BOA     = nada disso (pode haver OF já atrasada que nenhuma mudança recupera; ela fica listada);
#   nota    = 100 - 25 por prioritário fora - 10 por OF que passa a atrasar - 5 por pedido novo que não
#             atende - 3 por OF já atrasada - 3 por pedido no meio de sequência - 1 por salto de micra;
# - o plano de melhoria: mudanças de posição/máquina, uma depois da outra, que tiram OFs do atraso (ou
#   diminuem as horas de atraso) SEM fazer nenhuma OF que está no prazo passar a atrasar, sem aumentar os
#   prioritários fora do prazo e respeitando a sequência de formulação (se o cenário confere) e as
#   máquinas que rodam o produto (cadastro). OFs fixas e travadas não saem do lugar e nada entra antes
#   delas. A cada passo escolhe a mudança que tira uma OF do atraso (prioritário primeiro) e mais diminui
#   as horas de atraso das máquinas envolvidas;
# - as OFs que continuam atrasadas, com o motivo (nem como a 1ª depois das fixas, em nenhuma máquina
#   que roda, ela termina no prazo -> só negociando a data / hora extra; ou toda posição que recupera
#   faz outra OF atrasar).
# aplicar_plano(cen, plano) aplica os passos no cenário (dá para desfazer na tela).

BOA, ATENCAO, RUIM = "BOA", "ATENÇÃO", "RUIM"
MAX_PASSOS = 40
GANHO_MIN_H = 0.5          # mudança que diminui menos que isso o atraso total não entra no plano


@dataclass
class Avaliacao:
    situacao: str
    nota: int
    motivos: list
    sugestoes: list
    plano: pd.DataFrame
    continuam: pd.DataFrame
    antes: dict
    depois: dict


@dataclass
class _Of:
    chave: str
    dur: float             # horas
    intervalo: float
    prazo: float | None    # horas desde a referência (1º instante atrasado)
    nivel: int | None
    presa: bool
    prioritario: bool
    qtde: float
    micra: float | None
    roda_em: str
    situacao: str
    fim_atual: float | None


def _h(ts, ref) -> float | None:
    if ts is None or pd.isna(ts):
        return None
    return (pd.Timestamp(ts) - ref).total_seconds() / 3600


class _Modelo:
    """As filas do cenário em horas, para testar muitas mudanças rápido (mesma conta de recalcular)."""

    def __init__(self, cen: Cenario):
        it = cen.itens.sort_values(["maquina", "ordem"], kind="stable")
        self.ref = pd.Timestamp(min(pd.Timestamp(v) for v in cen.inicio.values())) if cen.inicio else it["inicio"].min()
        self.setup = float(cen.regras.setup_min or 0) / 60
        self.confere_seq = cen.regras.sequencia != IGNORAR
        self.taxas = cen.taxas
        self.inicio, self.filas = {}, {}
        for maq, fila in it.groupby("maquina", sort=False):
            self.inicio[maq] = _h(cen.inicio.get(maq, fila["inicio_atual"].dropna().min()), self.ref) or 0.0
            self.filas[maq] = [
                _Of(chave=r.chave, dur=float(r.dur_h or 0), intervalo=float(r.intervalo_h or 0), prazo=_h(r.prazo, self.ref),
                    nivel=None if r.nivel_formulacao is None or pd.isna(r.nivel_formulacao) else int(r.nivel_formulacao),
                    presa=r.situacao == "FIXA" or bool(getattr(r, "travada", False)), prioritario=bool(r.prioritario),
                    qtde=float(r.qtde_kg or 0), micra=_micra_linha(r), roda_em=str(r.roda_em or ""),
                    situacao=str(r.situacao or ""), fim_atual=_h(r.fim_atual, self.ref))
                for r in fila.itertuples()]

    def fins(self, maq: str, fila: list) -> list:
        niveis = _herdar([o.nivel for o in fila])
        t, saida = self.inicio.get(maq, 0.0), []
        for j, o in enumerate(fila):
            if j > 0:
                t += o.intervalo
                if self.setup and None not in (niveis[j], niveis[j - 1]) and niveis[j] != niveis[j - 1]:
                    t += self.setup
            t += o.dur
            saida.append(t)
        return saida

    @staticmethod
    def atraso(o: _Of, fim: float) -> float | None:
        """Horas de atraso (None = no prazo ou sem prazo). Terminar no 1º instante atrasado já é atraso."""
        if o.prazo is None or fim < o.prazo - 1e-9:
            return None
        return fim - o.prazo

    def estado(self, maq: str, fila: list) -> dict:
        """chave -> horas de atraso das OFs atrasadas da fila."""
        return {o.chave: a for o, f in zip(fila, self.fins(maq, fila)) if (a := self.atraso(o, f)) is not None}

    def todas_atrasadas(self) -> dict:
        saida = {}
        for maq, fila in self.filas.items():
            for k, a in self.estado(maq, fila).items():
                saida[k] = (maq, a)
        return saida

    def primeira_livre(self, fila: list) -> int:
        return max((j + 1 for j, o in enumerate(fila) if o.presa), default=0)

    def quebra(self, niveis: list, pos: int, nivel) -> bool:
        """Entrando no índice pos (0 = começo) da fila com estes níveis herdados, quebra a sequência?"""
        if not self.confere_seq or nivel is None or pos <= 0 or pos >= len(niveis):
            return False
        antes, depois = niveis[pos - 1], niveis[pos]
        return None not in (antes, depois) and not (min(antes, depois) <= nivel <= max(antes, depois))

    def copia_para(self, o: _Of, maq: str, origem: str) -> _Of | None:
        """A OF levada para outra máquina: duração pelo kg/h dessa máquina (None = não roda / sem kg/h)."""
        if maq == origem:
            return o
        if maq not in o.roda_em.split(", "):
            return None
        kgh = _taxa(self.taxas.get(maq, {}), o.micra)
        if kgh <= 0:
            return None
        return _Of(**{**o.__dict__, "dur": o.qtde / kgh, "intervalo": 0.0})


def _insercao(mod: _Modelo, maq: str, base: list, pos: int, novo: _Of, antes: dict, prefixo: list,
              fins: list, niveis: list):
    """Insere novo no índice pos de base e devolve {chave: horas de atraso} da fila, ou None se alguma OF que
    não estava atrasada (fora de antes) passa a atrasar. prefixo[pos] = atrasos das OFs antes de pos."""
    depois = dict(prefixo[pos])
    t = mod.inicio.get(maq, 0.0) if pos == 0 else fins[pos - 1]
    nivel_ant = niveis[pos - 1] if pos > 0 else None
    seguintes = [novo] + base[pos:]
    for j, o in enumerate(seguintes):
        nivel = (novo.nivel if novo.nivel is not None else nivel_ant) if j == 0 else niveis[pos + j - 1]
        if pos > 0 or j > 0:
            t += o.intervalo
            if mod.setup and None not in (nivel, nivel_ant) and nivel != nivel_ant:
                t += mod.setup
        t += o.dur
        nivel_ant = nivel
        a = mod.atraso(o, t)
        if a is not None:
            if o.chave not in antes:
                return None
            depois[o.chave] = a
    return depois


def _base(mod: _Modelo, maq: str, base: list):
    """Fins, níveis herdados e os atrasos acumulados de cada prefixo da fila."""
    fins = mod.fins(maq, base)
    niveis = _herdar([o.nivel for o in base])
    prefixo, atual = [{}], {}
    for o, f in zip(base, fins):
        a = mod.atraso(o, f)
        if a is not None:
            atual = {**atual, o.chave: a}
        prefixo.append(atual)
    return fins, niveis, prefixo


def _melhor_mudanca(mod: _Modelo, alvos: list, atrasadas: dict, prioritarias: set):
    """A melhor mudança para uma das OFs atrasadas (ou None)."""
    melhor, chave_melhor = None, None
    estados = {maq: mod.estado(maq, fila) for maq, fila in mod.filas.items()}
    bases = {maq: _base(mod, maq, fila) for maq, fila in mod.filas.items()}
    for k in alvos:
        maq_o, atraso_o = atrasadas[k]
        fila_o = mod.filas[maq_o]
        j = next(i for i, o in enumerate(fila_o) if o.chave == k)
        o = fila_o[j]
        if o.presa:
            continue
        sem = fila_o[:j] + fila_o[j + 1:]
        est_sem = mod.estado(maq_o, sem)
        base_sem = _base(mod, maq_o, sem)
        for maq, fila in mod.filas.items():
            novo = mod.copia_para(o, maq, maq_o)
            if novo is None:
                continue
            mesma = maq == maq_o
            base = sem if mesma else fila
            fins, niveis, prefixo = base_sem if mesma else bases[maq]
            antes = dict(estados[maq_o])
            if not mesma:
                antes.update(estados[maq])
                if any(c not in antes for c in est_sem):
                    continue
            ini = mod.primeira_livre(base)
            fim_pos = j if mesma else len(base) + 1           # na mesma máquina só adianta
            for pos in range(ini, min(fim_pos, len(base) + 1)):
                t0 = mod.inicio.get(maq, 0.0) if pos == 0 else fins[pos - 1]
                if mod.atraso(novo, t0 + novo.dur) is not None and \
                        mod.atraso(novo, t0 + novo.dur) >= atraso_o - GANHO_MIN_H:
                    break                                      # daqui para frente ela não melhora
                if mod.quebra(niveis, pos, novo.nivel):
                    continue
                depois = _insercao(mod, maq, base, pos, novo, antes, prefixo, fins, niveis)
                if depois is None:
                    continue                                   # alguma OF no prazo passaria a atrasar
                if not mesma:
                    depois.update(est_sem)
                if sum(1 for c in depois if c in prioritarias) > sum(1 for c in antes if c in prioritarias):
                    continue
                ganho = sum(antes.values()) - sum(depois.values())
                sai = k not in depois
                if ganho < GANHO_MIN_H and not sai:
                    continue
                nota = (sai, o.prioritario, round(ganho, 3), -(not mesma), -abs(pos - j))
                if chave_melhor is None or nota > chave_melhor:
                    chave_melhor = nota
                    melhor = {"chave": k, "de_maquina": maq_o, "de_ordem": j + 1, "para_maquina": maq,
                              "para_ordem": pos + 1, "atraso_antes_h": round(atraso_o, 1),
                              "atraso_depois_h": round(depois.get(k, 0.0), 1), "sai_do_atraso": sai,
                              "ganho_total_h": round(ganho, 1), "prioritario": o.prioritario,
                              "_teste": base[:pos] + [novo] + base[pos:], "_sem": sem}
    return melhor


def _prioritaria(mod: _Modelo, chave: str) -> bool:
    for fila in mod.filas.values():
        for o in fila:
            if o.chave == chave:
                return o.prioritario
    return False


def _por_que_continua(mod: _Modelo, chave: str, maq_o: str) -> str:
    fila_o = mod.filas[maq_o]
    j = next(i for i, o in enumerate(fila_o) if o.chave == chave)
    o = fila_o[j]
    if o.presa:
        return "OF fixa/travada: não sai do lugar"
    sem = fila_o[:j] + fila_o[j + 1:]
    da_tempo = False
    for maq, fila in mod.filas.items():
        novo = mod.copia_para(o, maq, maq_o)
        if novo is None:
            continue
        base = sem if maq == maq_o else fila
        pos = mod.primeira_livre(base)
        teste = base[:pos] + [novo] + base[pos:]
        if mod.atraso(novo, mod.fins(maq, teste)[pos]) is None:
            da_tempo = True
    if not da_tempo:
        return ("nem como a 1ª depois das fixas, em nenhuma máquina que roda, termina no prazo: negociar a data "
                "com o comercial ou ganhar tempo (hora extra, kg/h maior)")
    return ("dá tempo adiantando, mas toda posição que recupera faz outra OF no prazo atrasar ou quebra a "
            "sequência de formulação: decidir qual pedido segura")


def avaliar_programacao(cen: Cenario, max_passos: int = MAX_PASSOS) -> Avaliacao:
    ind = indicadores(cen)
    it = cen.itens
    vazio = pd.DataFrame()
    if it.empty:
        return Avaliacao(BOA, 100, ["Nenhuma OF nas máquinas do cenário."], [], vazio, vazio, ind, ind)
    nao_atende = int((it["atraso"] == NAO_ATENDE).sum())
    nota = (100 - 25 * ind["prioritarios_fora"] - 10 * ind["passam_a_atrasar"] - 5 * nao_atende
            - 3 * ind["ja_atrasadas"] - 3 * ind["quebras"] - ind["saltos_micra"])
    nota = int(max(0, min(100, nota)))

    # plano de melhoria
    mod = _Modelo(cen)
    prioritarias = {o.chave for fila in mod.filas.values() for o in fila if o.prioritario}
    passos = []
    for _ in range(max_passos):
        atrasadas = mod.todas_atrasadas()
        if not atrasadas:
            break
        alvos = sorted(atrasadas, key=lambda c: (c not in prioritarias, -atrasadas[c][1]))
        m = _melhor_mudanca(mod, alvos, atrasadas, prioritarias)
        if m is None:
            break
        mod.filas[m["para_maquina"]] = m.pop("_teste")
        sem = m.pop("_sem")
        if m["para_maquina"] != m["de_maquina"]:
            mod.filas[m["de_maquina"]] = sem
        m["passo"] = len(passos) + 1
        passos.append(m)
    plano = pd.DataFrame(passos, columns=["passo", "chave", "de_maquina", "de_ordem", "para_maquina", "para_ordem",
                                          "atraso_antes_h", "atraso_depois_h", "sai_do_atraso", "ganho_total_h",
                                          "prioritario"])
    restantes = mod.todas_atrasadas()
    continuam = pd.DataFrame([{"chave": k, "maquina": maq, "atraso_h": round(a, 1),
                               "prioritario": _prioritaria(mod, k), "motivo": _por_que_continua(mod, k, maq)}
                              for k, (maq, a) in sorted(restantes.items(), key=lambda x: -x[1][1])],
                             columns=["chave", "maquina", "atraso_h", "prioritario", "motivo"])
    recuperaveis = int(plano["sai_do_atraso"].sum()) if not plano.empty else 0
    horas_antes = sum(a for _, a in _Modelo(cen).todas_atrasadas().values())
    horas_depois = sum(a for _, a in restantes.values())

    motivos = []
    if ind["prioritarios_fora"]:
        motivos.append(f"{ind['prioritarios_fora']} OF(s) de cliente prioritário fora do prazo.")
    if ind["passam_a_atrasar"]:
        motivos.append(f"{ind['passam_a_atrasar']} OF(s) que estavam no prazo passam a atrasar nesta fila.")
    if nao_atende:
        motivos.append(f"{nao_atende} pedido(s) novo(s) / não programada(s) não atendem a data OTD.")
    if ind["ja_atrasadas"]:
        motivos.append(f"{ind['ja_atrasadas']} OF(s) já estavam atrasadas no planejamento "
                       f"({horas_antes:.0f} h de atraso somando todas as OFs fora do prazo).")
    if ind["quebras"]:
        motivos.append(f"{ind['quebras']} pedido(s) no meio de uma sequência de formulação.")
    if ind["saltos_micra"]:
        motivos.append(f"{ind['saltos_micra']} salto(s) de micra (gerar OF de estoque intermediária).")
    if not motivos:
        motivos.append("Nenhuma OF fora do prazo, sem quebra de sequência e sem salto de micra.")

    if ind["prioritarios_fora"] or ind["passam_a_atrasar"]:
        situacao = RUIM
    elif nao_atende or recuperaveis or ind["quebras"] or ind["saltos_micra"]:
        situacao = ATENCAO
    else:
        situacao = BOA
    if situacao != RUIM and nota < 50:
        situacao = RUIM

    sugestoes = []
    if not plano.empty:
        sugestoes.append(f"Aplicar o plano de melhoria: {len(plano)} mudança(s) tiram {recuperaveis} OF(s) do atraso e "
                         f"reduzem o atraso total de {horas_antes:.0f} h para {horas_depois:.0f} h, sem atrasar quem "
                         "está no prazo.")
    if ind["passam_a_atrasar"] and cen.regras.modo == ATENDER_PEDIDO:
        sugestoes.append("Gerar a sugestão de novo com o modo NÃO ATRASAR A FILA: nenhum pedido novo entra na frente "
                         "de OF que está no prazo.")
    if ind["quebras"]:
        sugestoes.append("Os pedidos no meio de sequência (coluna alerta) podem ir para a troca de formulação mais "
                         "próxima: gerar com a sequência NÃO QUEBRAR.")
    if ind["saltos_micra"]:
        sugestoes.append("Nos saltos de micra, gerar a OF de estoque de micra intermediária indicada na coluna salto de "
                         "micra (ou agrupar a máquina por formulação, que ordena a micra dentro do grupo).")
    if not continuam.empty:
        sem_tempo = continuam["motivo"].str.startswith("nem como").sum()
        sugestoes.append(f"{len(continuam)} OF(s) continuam atrasadas"
                         + (f" ({sem_tempo} sem tempo nem como a primeira: negociar a data)" if sem_tempo else "")
                         + " — veja a lista abaixo.")
    return Avaliacao(situacao, nota, motivos, sugestoes, plano, continuam, ind,
                     {"horas_atraso_antes": round(horas_antes, 1), "horas_atraso_depois": round(horas_depois, 1),
                      "recuperadas": recuperaveis})


def aplicar_plano(cen: Cenario, plano: pd.DataFrame, ate: int | None = None) -> list[str]:
    """Aplica os passos do plano (até o passo `ate`) no cenário, um por vez. Devolve os avisos."""
    avisos = []
    for r in plano.itertuples():
        if ate is not None and r.passo > ate:
            break
        avisos += aplicar_mudancas(cen, pd.DataFrame([{"chave": r.chave, "maquina": r.para_maquina,
                                                       "ordem": r.para_ordem}]))
    return avisos
