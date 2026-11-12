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
- fator_kgh: ajuste do kg/h dos pedidos novos (1.0 = mediana do relatório).

Datas da fila (recalcular): cada máquina começa no início da 1ª OF do planejamento; cada OF dura o
que dura no planejamento (pedido novo: qtde / kg/h da máquina na micra) e mantém o intervalo que
tinha antes dela no planejamento (pedido novo: sem intervalo). Sem mexer em nada, as datas são as do
planejamento e as do encaixe. OF levada para outra máquina passa a durar qtde / kg/h dessa máquina.
"""
from dataclasses import asdict, dataclass, field

import pandas as pd

from core.regras.EncaixeMaquinas import (NAO_QUEBRAR, PODE_QUEBRAR, SITUACAO_NAO_PROG, Encaixe, Pedido,
                                         nivel_formulacao)
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
           "quebra_sequencia", "prioritario", "maquina_original", "roda_em", "alerta"]


@dataclass
class RegrasCenario:
    sequencia: str = NAO_QUEBRAR
    prioridade: str = PRAZO
    ordens_fixas: int = 3
    prioritarios: bool = True
    setup_min: float = 0.0
    maquinas: list = field(default_factory=list)
    fator_kgh: float = 1.0

    def texto(self) -> str:
        partes = [f"sequência {self.sequencia}", "pelo prazo" if self.prioridade == PRAZO else "agrupado por formulação",
                  f"{self.ordens_fixas} fixas", "prioritários primeiro" if self.prioritarios else "sem prioritários"]
        if self.setup_min:
            partes.append(f"setup {self.setup_min:g} min/troca")
        if self.fator_kgh != 1:
            partes.append(f"kg/h {self.fator_kgh:.0%}")
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
                  regras: RegrasCenario | None = None, agora=None) -> Cenario:
    """Roda o encaixe com as regras do cenário e devolve a fila sugerida, pronta para mexer."""
    regras = regras or RegrasCenario()
    rank = dict(rank or {})
    if regras.maquinas:
        regras_maq = [r for r in regras_maq if r["apelido"] in regras.maquinas]
    enc = Encaixe(plan, reserva, regras_maq, prioritarios if regras.prioritarios else ListaPrioritarios([]),
                  mapa_otd, agora, rank=None if regras.sequencia == IGNORAR else rank,
                  pode_quebrar=(regras.sequencia == PODE_QUEBRAR), ordens_fixas=regras.ordens_fixas,
                  fator_kgh=regras.fator_kgh).executar()

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
                "roda_em": ", ".join(roda), "micra": parse_dimensoes(it.produto)["micra"],
            })
    itens = pd.DataFrame(linhas)
    taxas = {apelidos[m]: dict(t) for m, t in enumerate(enc.taxas)}
    cen = Cenario(regras=regras, itens=itens, inicio=inicio, taxas=taxas, rank=rank)
    if regras.prioridade == FORMULACAO and not itens.empty:
        for maq in itens["maquina"].unique():
            agrupar_por_formulacao(cen, maq)
    return recalcular(cen)


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
    decrescente). Dentro de cada grupo, fica a ordem atual. Sem nível: no fim. OFs fixas e travadas
    não saem do lugar."""
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
    ordem_nova = sorted(range(len(fila)), key=lambda j: k.iloc[j])          # estável: mantém a ordem no grupo
    fila = fila.assign(pos_alvo=fila["ordem"].astype(float), ordem_alvo=0.0)
    fila.iloc[ordem_nova, fila.columns.get_loc("ordem_alvo")] = list(range(len(fila)))
    fila = _com_travadas(fila, presas).drop(columns=["pos_alvo", "ordem_alvo"])
    it.loc[fila.index, "ordem"] = fila["ordem"]
    cen.itens = it.sort_values(["maquina", "ordem"]).reset_index(drop=True)
    recalcular(cen)


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
    inicios, fins, trocas, quebras = [], [], [], []
    for maq, fila in it.groupby("maquina", sort=False):
        t = pd.Timestamp(cen.inicio.get(maq, fila["inicio_atual"].dropna().min()))
        niveis = _herdar(list(fila["nivel_formulacao"]))
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
