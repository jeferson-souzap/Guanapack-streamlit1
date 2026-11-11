"""
Encaixe em máquina dos pedidos sem estoque (mesmas regras do modEncaixe da planilha Excel, rev030).

Entradas: o planejamento das extrusoras de stretch (fila atual de cada máquina), a reserva da
carteira (pedidos com tem_estoque = "NÃO"), as regras das máquinas, a lista de clientes
prioritários e a data OTD de cada pedido (ver AtrasoOtd).

Regras (combinadas com o usuário em 09 e 10/11/2026):
1. Pedidos em ordem de embarque (clientes prioritários antes). O pedido precisa terminar até o fim
   da data OTD (nacional = embarque - 2 dias; exportação = dt_otd do planejamento).
2. Se já existe OF de estoque (sem pedido) do mesmo produto, numa máquina, que termina antes do
   prazo e ainda tem saldo (qtde_of - qtde_prod - pedidos já ligados a ela), o pedido fica com
   essa OF e não entra OF nova. Ex.: OF 256331 (100 t do 35136) atende os pedidos do 35136.
3. Senão, testa cada máquina que roda o produto (formulação, família, micra, peso, tubete,
   largura) e cada posição da fila depois das ORDENS_FIXAS primeiras OFs da máquina (essas não
   mudam; as outras podem ser empurradas, mesmo firmadas).
   Duração = qtde_kg / kg por hora. O kg/h é a mediana das OFs da mesma máquina e micra no
   relatório (ou da micra mais próxima). Sem tempo de setup.
4. Escolhe, nesta ordem: a posição que atende o prazo; a que faz menos OFs passarem a atrasar;
   a que fica junto de OF do mesmo produto; a que empurra menos OFs. Se nenhuma atende, a que
   termina mais cedo. As OFs que vêm depois são empurradas pela duração do pedido novo.
5. Clientes prioritários: os pedidos deles são encaixados antes dos outros e na posição que
   termina mais cedo. A posição que faria um pedido ou OF deles atrasar só é escolhida se não
   houver outra (vem antes de todos os critérios do passo 4).
6. Sequência de formulação (11/11/2026, regra do usuário): o pedido novo não pode "quebrar" a
   sequência de formulações da máquina, nem que fique atrasado. Cada formulação tem um nível (o
   rank do cadastro de formulações: FM 1, MN 2, MO 3, F03 4, QUANTUM 5, STIFF 6), e o pedido só
   entra entre duas OFs se o nível dele estiver entre o das duas (subida e descida de formulação):
   entre MN e MN só MN; entre MN e MO, MN ou MO; entre FM e MO, só MN. No fim da fila sempre pode.
   Entre as posições que atendem o prazo sem fazer outras OFs atrasarem, prefere a que fica ao lado
   de OF da mesma formulação (critério novo do passo 4, logo depois de "menos OFs passam a atrasar").
   (rev030) O nível da OF vem do grupo_form do planejamento (sempre preenchido); só se ele estiver
   vazio usa a formulacao e, se as duas estiverem vazias, a da OF anterior.
7. Opção do usuário (rev030): NÃO QUEBRAR (padrão, regra 6) ou PODE QUEBRAR (o pedido pode entrar no
   meio de uma sequência, mas só quando isso é preciso para atender o prazo ou para não fazer outra OF
   atrasar; havendo posição igual sem quebrar, fica com ela). gerar_encaixe roda as duas: as filas
   seguem a opção escolhida e a tabela de pedidos traz as colunas comparar_* com a outra.
"""
import re
from dataclasses import dataclass, field
from statistics import median

import pandas as pd

from core.regras.Maquinas import apelido
from core.regras.Prioridade import ListaPrioritarios
from core.regras.LimpezaDataframe import extrair_familia, parse_dimensoes

ORDENS_FIXAS = 3             # primeiras OFs de cada máquina que não mudam de lugar
MIN_HORAS_TAXA = 0.25        # OF mais curta que isso não entra na conta do kg/h
DIAS_OTD = 2                 # data OTD = embarque - 2 dias (pedido sem data no CTLR)

NOVO = "NOVO NA MÁQUINA"
OF_ESTOQUE = "OF DE ESTOQUE"
SEM_MAQUINA = "SEM MÁQUINA"

NAO_QUEBRAR = "NÃO QUEBRAR"      # regra 7: opções da sequência de formulação
PODE_QUEBRAR = "PODE QUEBRAR"
OPCOES_SEQUENCIA = (NAO_QUEBRAR, PODE_QUEBRAR)


def outra_opcao(opcao: str) -> str:
    return NAO_QUEBRAR if opcao == PODE_QUEBRAR else PODE_QUEBRAR


@dataclass
class Item:
    """Uma OF da fila de uma máquina (do relatório ou nova)."""
    maq: int
    novo: bool = False
    id_of: str = ""
    firmado: str = ""
    pedido: str = ""
    prog: str = ""
    cliente: str = ""
    id_pa: str = ""
    produto: str = ""
    formulacao: str = ""
    grupo_form: str = ""                   # grupo_form do planejamento; pedido novo: formulação da carteira
    quebra: bool = False                   # pedido novo que entrou no meio de uma sequência (PODE QUEBRAR)
    qtde: float = 0.0
    ini0: pd.Timestamp | None = None
    fim0: pd.Timestamp | None = None
    ini: pd.Timestamp | None = None
    fim: pd.Timestamp | None = None
    prazo: pd.Timestamp | None = None      # 1º instante já atrasado (dia seguinte à data OTD)
    cap_livre: float = 0.0                 # OF de estoque: kg que ainda podem atender pedidos
    atende_pedidos: list = field(default_factory=list)
    prioritario: bool = False
    fixa: bool = False
    kgh: float = 0.0
    taxa_origem: str = ""


@dataclass
class Pedido:
    num_pedido: str
    prog: str
    cliente: str
    embarque: pd.Timestamp
    id_pa: str
    produto: str
    formulacao: str
    qtde: float
    familia: str
    largura: float | None
    micra: float | None
    peso: float | None
    tubete: float
    prioritario: bool
    tipo: str = SEM_MAQUINA
    item: Item | None = None
    bloqueios: list = field(default_factory=list)
    passam_atrasar: str = ""
    quebra: bool = False


@dataclass
class Opcao:
    maq: int
    pos: int                     # 1 = antes da 1ª OF da fila; len + 1 = no fim
    ini: pd.Timestamp
    fim: pd.Timestamp
    atende: bool
    n_atrasos: int
    n_atrasos_prior: int
    atrasos: str
    junto: bool
    empurra: int
    prioritario: bool
    kgh: float = 0.0
    taxa_origem: str = ""
    mesma_formulacao: bool = False   # fica ao lado de OF da mesma formulação (não cria troca de formulação)
    quebra: bool = False             # entra no meio de uma sequência de formulação (só com PODE QUEBRAR)


def _texto(valor) -> str:
    """Texto da célula sem espaços nas pontas; número inteiro sem ",0" ("218047.0" -> "218047")."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NA:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _num(valor, padrao=0.0) -> float:
    numero = pd.to_numeric(valor, errors="coerce")
    return padrao if pd.isna(numero) else float(numero)


def _fmt(numero) -> str:
    """Número como no Excel em português: 2.38 -> "2,38", 18.0 -> "18"."""
    return f"{numero:g}".replace(".", ",")


def grupo_formulacao(formulacao: str) -> str:
    """"QUANTUM 400%" -> QUANTUM, "FM 150% PCR" -> PCR, "MO 300% UV" -> UV, "MN 250%" -> MN."""
    f = (formulacao or "").upper()
    for grupo in ("QUANTUM", "STIFF", "PCR", "PRE-ESTIRADO", "UV"):
        if grupo in f:
            return grupo
    return f.strip()[:2]


def _so_palavras(texto) -> str:
    """" Quantum 400% - Nacional | Rev104" -> " QUANTUM 400% NACIONAL REV104 " (só letras A-Z, números e %)."""
    return " " + " ".join(re.sub(r"[^A-Z0-9%]+", " ", str(texto or "").upper()).split()) + " "


def nivel_formulacao(texto, rank: dict | None) -> int | None:
    """Nível da formulação na sequência da máquina = rank do cadastro de formulações.

    Procura no texto a formulação do cadastro (a mais longa que aparecer); se nenhuma aparece
    inteira, a 1ª palavra dela (ex.: "QUANTUM 350%" -> QUANTUM). Serve tanto para a formulação da
    carteira ("MO 300%") quanto para a do planejamento ("Blue Pe FM 150% Nacional | Rev180", "Stiff(unilever)").
    None = sem formulação ou não está no cadastro.
    """
    if not rank:
        return None
    t = _so_palavras(texto)
    if not t.strip():
        return None
    achou, tamanho = None, 0
    for formulacao, nivel in rank.items():
        f = _so_palavras(formulacao)
        if f.strip() and f in t and len(f) > tamanho:
            achou, tamanho = int(nivel), len(f)
    if achou is not None:
        return achou
    for formulacao, nivel in rank.items():
        palavra = _so_palavras(formulacao).split()
        if palavra and f" {palavra[0]} " in t:
            return int(nivel)
    return None


def chave_pedido(pedido, prog) -> str:
    return f"{_texto(pedido)}|{_texto(prog)}"


class Encaixe:
    def __init__(self, plan: pd.DataFrame, reserva: pd.DataFrame, regras: list[dict],
                 prioritarios: ListaPrioritarios | None = None, mapa_otd: dict | None = None, agora=None,
                 rank: dict | None = None, pode_quebrar: bool = False,
                 ordens_fixas: int | None = None, fator_kgh: float = 1.0):
        self.regras = regras
        self.rank = dict(rank or {})       # formulação -> nível (vazio = não confere a sequência)
        self.pode_quebrar = pode_quebrar   # regra 7
        # simulação: quantas OFs ficam fixas e ajuste do kg/h (1.0 = mediana do relatório)
        self.ordens_fixas = ORDENS_FIXAS if ordens_fixas is None else int(ordens_fixas)
        self.fator_kgh = float(fator_kgh)
        self.prioritarios = prioritarios or ListaPrioritarios([])
        self.mapa_otd = mapa_otd or {}
        self.agora = pd.Timestamp(agora) if agora is not None else pd.Timestamp.now()
        self.itens: list[Item] = []
        self.filas: list[list[Item]] = [[] for _ in regras]
        self.taxas: list[dict] = [{} for _ in regras]
        self._carregar_planejamento(plan)
        self._calcular_taxas()
        self.pedidos = self._carregar_pedidos(reserva)

    # ----- leitura -----
    def _indice_maquina(self, nome) -> int | None:
        nome = _texto(nome).upper()
        for i, regra in enumerate(self.regras):
            if regra["maquina"].strip().upper() == nome:
                return i
        return None

    def _carregar_planejamento(self, plan: pd.DataFrame):
        if plan is None or plan.empty:
            return
        for _, r in plan.iterrows():
            m = self._indice_maquina(r["maquina"])
            ini, fim = r["inicio_prev"], r["final_prev"]
            if m is None or pd.isna(ini) or pd.isna(fim):
                continue
            # O relatório traz segundos quebrados (07:51:33.999); a planilha Excel lê só até o minuto
            ini, fim = pd.Timestamp(ini).floor("min"), pd.Timestamp(fim).floor("min")
            it = Item(maq=m, id_of=_texto(r["id_of"]), firmado=_texto(r.get("firmado")),
                      pedido=_texto(r["pedido"]), prog=_texto(r["seq_prog"]), cliente=_texto(r.get("cliente")),
                      id_pa=_texto(r["id_pa"]), produto=_texto(r["produto"]), formulacao=_texto(r.get("formulacao")),
                      grupo_form=_texto(r.get("grupo_form")), qtde=_num(r["qtde_of"]), ini0=pd.Timestamp(ini), fim0=pd.Timestamp(fim),
                      ini=pd.Timestamp(ini), fim=pd.Timestamp(fim))
            if it.pedido:
                chave = chave_pedido(it.pedido, it.prog)
                if chave in self.mapa_otd and pd.notna(self.mapa_otd[chave]):
                    it.prazo = pd.Timestamp(self.mapa_otd[chave]).normalize() + pd.Timedelta(days=1)
                elif pd.notna(r.get("dt_otd")):
                    it.prazo = pd.Timestamp(r["dt_otd"]).normalize() + pd.Timedelta(days=1)
                it.prioritario = self.prioritarios.pedido_prioritario(
                    f"{it.cliente} {_texto(r.get('cliente_razao_social'))}", it.produto, it.formulacao)
            else:
                it.cap_livre = it.qtde - _num(r.get("qtde_prod"))
            horas = (it.fim0 - it.ini0).total_seconds() / 3600
            if horas > 0:
                it.kgh = it.qtde / horas
            self.itens.append(it)
        # Fila de cada máquina em ordem de início (estável, como a inserção do Excel)
        for it in sorted(self.itens, key=lambda x: x.ini):
            fila = self.filas[it.maq]
            fila.append(it)
            it.fixa = len(fila) <= self.ordens_fixas

    def _calcular_taxas(self):
        """kg/h de cada máquina por micra: mediana das OFs do relatório com pelo menos MIN_HORAS_TAXA."""
        for m, fila in enumerate(self.filas):
            grupos: dict[float, list] = {}
            for it in fila:
                if (it.fim0 - it.ini0).total_seconds() / 3600 >= MIN_HORAS_TAXA:
                    micra = parse_dimensoes(it.produto)["micra"]
                    if pd.notna(micra):
                        grupos.setdefault(float(micra), []).append(it.kgh)
            self.taxas[m] = {k: median(v) * self.fator_kgh for k, v in grupos.items()}

    def _carregar_pedidos(self, reserva: pd.DataFrame) -> list[Pedido]:
        pedidos = []
        if reserva is None or reserva.empty:
            return pedidos
        sem = reserva[reserva["tem_estoque"].astype(str).str.strip().str.upper() == "NÃO"]
        for _, r in sem.iterrows():
            produto = _texto(r["produto"])
            dims = parse_dimensoes(produto)
            tubete = dims["peso_tubete"]
            p = Pedido(num_pedido=_texto(r["num_pedido"]), prog=_texto(r["prog"]), cliente=_texto(r["cliente"]),
                       embarque=pd.Timestamp(r["dt_embarque"]) if pd.notna(r["dt_embarque"]) else pd.NaT,
                       id_pa=_texto(r["id_pa"]), produto=produto, formulacao=_texto(r["formulacao"]),
                       qtde=_num(r["qtde_kg"]), familia=extrair_familia(produto) or "",
                       largura=dims["largura"], micra=dims["micra"], peso=dims["peso"],
                       tubete=0.0 if pd.isna(tubete) else float(tubete),
                       prioritario=self.prioritarios.pedido_prioritario(r["cliente"], produto, r["formulacao"]))
            pedidos.append(p)
        # Prioritários primeiro, depois embarque, pedido e programação (ordenação estável)
        return sorted(pedidos, key=lambda p: (not p.prioritario, p.embarque, _num(p.num_pedido), _num(p.prog)))

    # ----- regras -----
    def prazo_do_pedido(self, p: Pedido) -> pd.Timestamp:
        """Dia seguinte à data OTD do pedido (1º instante já atrasado)."""
        otd = self.mapa_otd.get(chave_pedido(p.num_pedido, p.prog))
        if otd is None or pd.isna(otd):
            otd = p.embarque.normalize() - pd.Timedelta(days=DIAS_OTD)
        return pd.Timestamp(otd).normalize() + pd.Timedelta(days=1)

    def bloqueios(self, m: int, p: Pedido) -> str:
        """Motivos para a máquina não rodar o pedido ("" = roda)."""
        regra = self.regras[m]
        texto = f"{p.familia} {p.formulacao} {p.produto}".upper()
        mot = [f"não roda {palavra}" for palavra in regra["palavras_nao_roda"] if palavra in texto]
        grupo = grupo_formulacao(p.formulacao)
        if grupo not in regra["grupos"]:
            mot.append(f"formulação {grupo} fora da lista")
        if p.micra is None or pd.isna(p.micra):
            return ", ".join(mot + ["descrição sem medidas"])
        faixas = [("micra", p.micra, "micra", ""), ("peso", p.peso, "peso", " kg")]
        if p.tubete > 0:                                    # 0 = sem tubete (coreless)
            faixas.append(("tubete", p.tubete, "tubete", ""))
        faixas.append(("largura", p.largura, "largura", ""))
        for campo, valor, rotulo, unidade in faixas:
            minimo, maximo = regra[f"{campo}_min"], regra[f"{campo}_max"]
            if valor < minimo or valor > maximo:
                mot.append(f"{rotulo} {_fmt(valor)}{unidade} fora de {_fmt(minimo)}-{_fmt(maximo)}")
        return ", ".join(mot)

    def taxa(self, m: int, micra: float) -> tuple[float, str]:
        """kg/h da máquina na micra; sem OF dessa micra, usa a mais próxima (no empate, a menor)."""
        taxas = self.taxas[m]
        if not taxas:
            return 0.0, ""
        if float(micra) in taxas:
            return taxas[float(micra)], f"{_fmt(micra)} µ"
        perto = min(taxas, key=lambda k: (abs(k - micra), k))
        return taxas[perto], f"{_fmt(perto)} µ (micra mais próxima)"

    @staticmethod
    def nome(it: Item) -> str:
        return f"NOVO {it.pedido}/{it.prog}" if it.novo else f"OF {it.id_of}"

    def atender_por_of_de_estoque(self, p: Pedido) -> bool:
        limite = self.prazo_do_pedido(p)
        candidatos = [it for it in self.itens if not it.novo and not it.pedido and it.id_pa == p.id_pa
                      and it.cap_livre >= p.qtde - 0.001 and it.fim < limite]
        if not candidatos:
            return False
        it = min(candidatos, key=lambda x: x.fim)          # no empate, o 1º do relatório
        it.cap_livre -= p.qtde
        it.atende_pedidos.append(f"{p.num_pedido}/{p.prog}")
        if it.prazo is None or limite < it.prazo:
            it.prazo = limite                              # agora ela tem prazo para não atrasar
        it.prioritario = it.prioritario or p.prioritario
        p.tipo, p.item = OF_ESTOQUE, it
        return True

    def avaliar_posicao(self, m: int, pos: int, dur: pd.Timedelta, limite, p: Pedido) -> Opcao:
        fila = self.filas[m]
        n = len(fila)
        if pos > 1:
            ini = fila[pos - 2].fim
        elif n > 0:
            ini = fila[0].ini
        else:
            ini = self.agora
        fim = ini + dur
        atrasados = [it for it in fila[pos - 1:]
                     if it.prazo is not None and it.fim < it.prazo and it.fim + dur >= it.prazo]
        junto = (pos > 1 and fila[pos - 2].id_pa == p.id_pa) or (pos <= n and fila[pos - 1].id_pa == p.id_pa)
        return Opcao(maq=m, pos=pos, ini=ini, fim=fim, atende=fim < limite, n_atrasos=len(atrasados),
                     n_atrasos_prior=sum(1 for it in atrasados if it.prioritario),
                     atrasos=", ".join(self.nome(it) for it in atrasados), junto=junto,
                     empurra=n - pos + 1, prioritario=p.prioritario)

    def nivel_do_item(self, it: Item) -> int | None:
        """Nível de uma OF: grupo_form (rev030); se vazio ou fora do cadastro, a formulacao."""
        nivel = nivel_formulacao(it.grupo_form, self.rank)
        return nivel if nivel is not None else nivel_formulacao(it.formulacao, self.rank)

    def niveis_da_fila(self, m: int) -> list[int | None]:
        """Nível de formulação de cada OF da fila; OF sem grupo e sem formulação fica com o da
        anterior (as do começo da fila ficam com o da 1ª que tem)."""
        niveis = [self.nivel_do_item(it) for it in self.filas[m]]
        ultimo = None
        for j, n in enumerate(niveis):
            if n is None:
                niveis[j] = ultimo
            else:
                ultimo = n
        proximo = None
        for j in range(len(niveis) - 1, -1, -1):
            if niveis[j] is None:
                niveis[j] = proximo
            else:
                proximo = niveis[j]
        return niveis

    @staticmethod
    def quebra_sequencia(niveis: list, pos: int, nivel_pedido) -> bool:
        """O pedido novo, entrando antes da OF da posição pos, quebra a sequência de formulação?
        Só pode entrar se o nível dele estiver entre o da OF de antes e o da OF de depois.
        No fim (ou no começo) da fila não quebra."""
        if nivel_pedido is None or pos <= 1 or pos > len(niveis):
            return False
        antes, depois = niveis[pos - 2], niveis[pos - 1]
        if antes is None or depois is None:
            return False
        return not (min(antes, depois) <= nivel_pedido <= max(antes, depois))

    @staticmethod
    def melhor_que(a: Opcao, b: Opcao | None) -> bool:
        """a é melhor que b? (regras 4 e 5 do cabeçalho)"""
        if b is None:
            return True
        if a.n_atrasos_prior != b.n_atrasos_prior:
            return a.n_atrasos_prior < b.n_atrasos_prior
        if a.atende != b.atende:
            return a.atende
        # regra 7 (PODE QUEBRAR): quebrar só quando é preciso para atender o prazo ou para não
        # fazer outra OF atrasar (com NÃO QUEBRAR nenhuma opção quebra)
        if a.atende and a.prioritario:                     # prioritário: o mais cedo possível
            if a.quebra != b.quebra:
                return not a.quebra
            if a.fim != b.fim:
                return a.fim < b.fim
            return a.n_atrasos < b.n_atrasos
        if a.atende:
            if a.n_atrasos != b.n_atrasos:
                return a.n_atrasos < b.n_atrasos
            if a.quebra != b.quebra:
                return not a.quebra
            if a.mesma_formulacao != b.mesma_formulacao:      # regra 6: evita troca de formulação a mais
                return a.mesma_formulacao
            if a.junto != b.junto:
                return a.junto
            if a.empurra != b.empurra:
                return a.empurra < b.empurra
            return a.fim < b.fim
        if a.quebra != b.quebra:
            return not a.quebra
        if a.fim != b.fim:
            return a.fim < b.fim
        if a.n_atrasos != b.n_atrasos:
            return a.n_atrasos < b.n_atrasos
        return a.junto and not b.junto

    def encaixar_pedido(self, p: Pedido):
        limite = self.prazo_do_pedido(p)
        nivel = nivel_formulacao(p.formulacao, self.rank)
        melhor = None
        for m, regra in enumerate(self.regras):
            motivo = self.bloqueios(m, p)
            kgh, origem = 0.0, ""
            if not motivo:
                kgh, origem = self.taxa(m, p.micra)
                if kgh <= 0:
                    motivo = "sem OF no relatório para estimar o kg/h"
            if motivo:
                p.bloqueios.append(f"{regra['apelido']}: {motivo}")
                continue
            dur = pd.Timedelta(hours=p.qtde / kgh)
            fila = self.filas[m]
            ult_fixa = max((j + 1 for j, it in enumerate(fila) if it.fixa), default=0)
            niveis = self.niveis_da_fila(m)
            for pos in range(ult_fixa + 1, len(fila) + 2):
                quebra = self.quebra_sequencia(niveis, pos, nivel)
                if quebra and not self.pode_quebrar:
                    continue                               # regra 6: não entra no meio da sequência
                op = self.avaliar_posicao(m, pos, dur, limite, p)
                op.kgh, op.taxa_origem, op.quebra = kgh, origem, quebra
                op.mesma_formulacao = nivel is not None and (
                    (pos > 1 and niveis[pos - 2] == nivel) or (pos <= len(niveis) and niveis[pos - 1] == nivel))
                if self.melhor_que(op, melhor):
                    melhor = op
        if melhor is None:
            p.tipo = SEM_MAQUINA
            return
        # Empurra as OFs que vêm depois e insere a nova
        fila = self.filas[melhor.maq]
        dur = melhor.fim - melhor.ini
        for it in fila[melhor.pos - 1:]:
            it.ini += dur
            it.fim += dur
        novo = Item(maq=melhor.maq, novo=True, pedido=p.num_pedido, prog=p.prog, cliente=p.cliente,
                    id_pa=p.id_pa, produto=p.produto, formulacao=p.formulacao, grupo_form=p.formulacao,
                    quebra=melhor.quebra, qtde=p.qtde,
                    ini=melhor.ini, fim=melhor.fim, prazo=limite, kgh=melhor.kgh,
                    taxa_origem=melhor.taxa_origem, prioritario=p.prioritario)
        self.itens.append(novo)
        fila.insert(melhor.pos - 1, novo)
        p.tipo, p.item, p.passam_atrasar, p.quebra = NOVO, novo, melhor.atrasos, melhor.quebra

    def executar(self):
        for p in self.pedidos:
            if not self.atender_por_of_de_estoque(p):
                self.encaixar_pedido(p)
        return self

    # ----- saída -----
    def tabela_pedidos(self) -> pd.DataFrame:
        linhas = []
        for p in self.pedidos:
            limite = self.prazo_do_pedido(p)
            linha = {"num_pedido": p.num_pedido, "prog": p.prog, "cliente": p.cliente, "dt_embarque": p.embarque,
                     "data_otd": limite - pd.Timedelta(days=1), "id_pa": p.id_pa, "produto": p.produto,
                     "formulacao": p.formulacao, "qtde_kg": p.qtde, "sugestao": p.tipo, "maquina": None,
                     "depois_de": None, "inicio_previsto": None, "fim_previsto": None, "atende_embarque": None,
                     "kg_h": None, "kg_h_origem": None, "ofs_que_passam_a_atrasar": p.passam_atrasar or None,
                     "maquinas_que_nao_rodam": " | ".join(p.bloqueios) or None,
                     "cliente_prioritario": "SIM" if p.prioritario else None,
                     "quebra_sequencia": "SIM" if p.tipo == NOVO and p.quebra else None}
            it = p.item
            if it is not None:
                linha.update(maquina=self.regras[it.maq]["apelido"], inicio_previsto=it.ini, fim_previsto=it.fim,
                             atende_embarque="SIM" if it.fim < limite else "NÃO")
                if p.tipo == OF_ESTOQUE:
                    linha["depois_de"] = f"OF {it.id_of} (estoque)"
                else:
                    fila = self.filas[it.maq]
                    j = next(i for i, x in enumerate(fila) if x is it)
                    linha.update(depois_de="início da fila" if j == 0 else self.nome(fila[j - 1]),
                                 kg_h=round(it.kgh), kg_h_origem=it.taxa_origem)
            linhas.append(linha)
        return pd.DataFrame(linhas)

    def tabela_filas(self) -> pd.DataFrame:
        linhas = []
        for m, fila in enumerate(self.filas):
            niveis = self.niveis_da_fila(m)
            for j, it in enumerate(fila, start=1):
                atraso = None
                if it.prazo is not None:
                    if it.fim >= it.prazo:
                        atraso = ("NÃO ATENDE" if it.novo else
                                  "JÁ ATRASADA" if it.fim0 >= it.prazo else "PASSA A ATRASAR")
                    else:
                        atraso = "OK"
                observacao = None
                if it.atende_pedidos:
                    observacao = "atende os pedidos sem estoque " + ", ".join(it.atende_pedidos)
                if it.novo:
                    observacao = f"kg/h {round(it.kgh)} ({it.taxa_origem})"
                    if it.quebra:
                        observacao += " | QUEBRA a sequência de formulação"
                linhas.append({
                    "maquina": self.regras[m]["apelido"], "seq": j,
                    "situacao": "NOVO" if it.novo else ("FIXA" if it.fixa else None),
                    "id_of": None if it.novo else it.id_of, "firmado": it.firmado or None,
                    "pedido": it.pedido or None, "prog": it.prog or None, "cliente": it.cliente or None,
                    "id_pa": it.id_pa, "produto": it.produto, "formulacao": it.formulacao,
                    "grupo_formulacao": (it.grupo_form or it.formulacao) or None,
                    "nivel_formulacao": niveis[j - 1], "qtde_kg": it.qtde,
                    "inicio_atual": None if it.novo else it.ini0, "fim_atual": None if it.novo else it.fim0,
                    "inicio_sugerido": it.ini, "fim_sugerido": it.fim,
                    "empurrado_h": None if it.novo else round((it.ini - it.ini0).total_seconds() / 3600, 1),
                    "data_otd": None if it.prazo is None else it.prazo - pd.Timedelta(days=1),
                    "atraso": atraso, "observacao": observacao,
                    "cliente_prioritario": "SIM" if it.prioritario else None,
                })
        return pd.DataFrame(linhas)

    def resumo_novos(self) -> str:
        novos = [p for p in self.pedidos if p.tipo == NOVO]
        atendem = sum(1 for p in novos if p.item.fim < self.prazo_do_pedido(p))
        quebram = sum(1 for p in novos if p.quebra)
        sem = sum(1 for p in self.pedidos if p.tipo == SEM_MAQUINA)
        extra = f", {quebram} {'quebra' if quebram == 1 else 'quebram'} a sequência" if quebram else ""
        return f"novos na máquina: {len(novos)} ({atendem} atendem o embarque{extra}) | sem máquina: {sem}"

    def resumo(self) -> str:
        novos = [p for p in self.pedidos if p.tipo == NOVO]
        atendem = sum(1 for p in novos if p.item.fim < self.prazo_do_pedido(p))
        quebram = sum(1 for p in novos if p.quebra)
        estoque = sum(1 for p in self.pedidos if p.tipo == OF_ESTOQUE)
        sem = sum(1 for p in self.pedidos if p.tipo == SEM_MAQUINA)
        opcao = PODE_QUEBRAR if self.pode_quebrar else NAO_QUEBRAR
        extra = f", {quebram} {'quebra' if quebram == 1 else 'quebram'} a sequência" if quebram else ""
        return (f"{len(self.pedidos)} pedidos sem estoque | {opcao} a sequência de formulação | "
                f"novos na máquina: {len(novos)} ({atendem} atendem o embarque{extra})"
                f" | por OF de estoque: {estoque} | sem máquina: {sem}")


def _comparar(pedidos: pd.DataFrame, outra: "Encaixe", opcao_outra: str) -> tuple[pd.DataFrame, int]:
    """Colunas comparar_* (regra 7): o resultado do mesmo pedido na outra opção."""
    tab = outra.tabela_pedidos()
    if pedidos.empty:
        return pedidos, 0
    ref = {chave_pedido(r.num_pedido, r.prog): r for r in tab.itertuples()}
    cols = {"comparar_opcao": [], "comparar_sugestao": [], "comparar_maquina": [],
            "comparar_fim_previsto": [], "comparar_atende_embarque": []}
    difere = 0
    for r in pedidos.itertuples():
        o = ref.get(chave_pedido(r.num_pedido, r.prog))
        cols["comparar_opcao"].append(opcao_outra)
        if o is None:
            for c in list(cols)[1:]:
                cols[c].append(None)
            continue
        cols["comparar_sugestao"].append(o.sugestao + (" (quebra a sequência)" if o.quebra_sequencia == "SIM" else ""))
        cols["comparar_maquina"].append(o.maquina)
        cols["comparar_fim_previsto"].append(o.fim_previsto)
        cols["comparar_atende_embarque"].append(o.atende_embarque)
        if (r.atende_embarque or "") != (o.atende_embarque or "") or (r.maquina or "") != (o.maquina or ""):
            difere += 1
    return pedidos.assign(**cols), difere


def gerar_encaixe(plan, reserva, regras, prioritarios=None, mapa_otd=None, agora=None, rank=None,
                  opcao: str = NAO_QUEBRAR):
    """Roda o encaixe e devolve (pedidos, filas, resumo). rank = {formulação: rank} do cadastro de
    formulações, para não quebrar a sequência de formulação das máquinas (regra 6).
    opcao = NÃO QUEBRAR / PODE QUEBRAR (regra 7): roda também a outra opção, que vai nas colunas
    comparar_* da tabela de pedidos e no fim do resumo."""
    opcao = PODE_QUEBRAR if str(opcao).strip().upper() == PODE_QUEBRAR else NAO_QUEBRAR
    outra = Encaixe(plan, reserva, regras, prioritarios, mapa_otd, agora, rank,
                    pode_quebrar=(outra_opcao(opcao) == PODE_QUEBRAR)).executar()
    enc = Encaixe(plan, reserva, regras, prioritarios, mapa_otd, agora, rank,
                  pode_quebrar=(opcao == PODE_QUEBRAR)).executar()
    pedidos, difere = _comparar(enc.tabela_pedidos(), outra, outra_opcao(opcao))
    resumo = (f"{enc.resumo()} || comparação, {outra_opcao(opcao)}: {outra.resumo_novos()} "
              f"({difere} pedidos mudam)")
    return pedidos, enc.tabela_filas(), resumo
