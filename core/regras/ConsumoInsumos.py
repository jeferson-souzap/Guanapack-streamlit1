"""
Consumo de tubetes e pallets na produção, para pedir ressuprimento (mesmas regras da aba
consumo_insumos da planilha Excel, rev021/rev022).

Tubetes agrupados por LARGURA (1º número do nome) e PESO (último número):
    "Tubete de Papelao - 514 X 78 X 9 X 0,9" e "... 514 X 78 X 9x 0,9" -> 514 mm, 0,90 kg
    Peso com erro de digitação no ERP (0, "X0.", "X 150" = fora de 0-20 kg): usa o peso de outro
    tubete com a mesma largura x diâmetro x parede (ex.: "514 X 78 X 14,5 X 150" -> 1,50 do
    "514 X 78 X 14,5 X 1,5"); se não houver, o peso do tubete da OF ou do produto do pedido.
    A coluna observacao avisa quando o peso foi deduzido.
Pallets: por tipo, como o ERP escreve o nome.

Colunas:
    programado_maquinas  OFs abertas do planejamento que estão numa máquina
    nao_programadas      OFs abertas do planejamento em "Não-programadas"
    sem_encaixe          programado_maquinas + nao_programadas
    encaixe              pedidos "NOVO NA MÁQUINA" do encaixe (OF que ainda não existe); tubete e
                         pallet vêm do pedido na carteira (PCP_OF_CARTEIRA_PEDIDO)
    com_encaixe          sem_encaixe + encaixe
Regras:
- OF com final_real preenchido já terminou e não entra.
- OF já iniciada conta só o que falta: num_tubete x (qtde_of - qtde_prod) / qtde_of, arredondado
  para cima. Ex.: OF de 120.000 kg com 61.696 kg feitos e 12.000 tubetes -> 5.831 tubetes.
- "Filme Coreless Sem Tubete" não é tubete e fica fora.
- Pedido "OF DE ESTOQUE" do encaixe não soma: a OF dele já está no planejamento.
"""
import math
import re

import pandas as pd

from core.regras.LimpezaPlanejamento import MAQUINA_NAO_PROGRAMADA

_CADEIA = re.compile(r"\d+(?:[.,]\d+)?(?:\s*[Xx]\s*\d+(?:[.,]\d+)?)+")
PESO_MAXIMO_TUBETE = 20.0


def numeros_da_medida(texto) -> list[float]:
    """Números da 1ª cadeia "n X n X n": "Tubete - 514 X 78 X 9x 0,9" -> [514, 78, 9, 0.9]."""
    achado = _CADEIA.search(str(texto)) if isinstance(texto, str) else None
    if not achado:
        return []
    return [float(p.replace(",", ".")) for p in re.split(r"\s*[Xx]\s*", achado.group(0))]


def _peso_valido(peso) -> bool:
    return peso is not None and 0 < peso <= PESO_MAXIMO_TUBETE


def _eh_tubete(nome) -> bool:
    return isinstance(nome, str) and nome.strip() != "" and "sem tubete" not in nome.lower()


def catalogo_de_tubetes(nomes) -> dict:
    """largura|diâmetro|parede -> peso, dos nomes com peso válido (o 1º que aparece)."""
    catalogo = {}
    for nome in nomes:
        n = numeros_da_medida(nome)
        if len(n) >= 4 and _peso_valido(n[-1]):
            catalogo.setdefault((n[0], n[1], n[2]), n[-1])
    return catalogo


def medida_do_tubete(nome: str, peso_reserva, catalogo: dict) -> tuple[float, float, str]:
    """(largura, peso, observação). peso_reserva: peso_tubete da OF ou descrição do produto."""
    n = numeros_da_medida(nome)
    largura = n[0] if n else 0.0
    peso = n[-1] if len(n) >= 2 else 0.0
    if _peso_valido(peso):
        return largura, peso, ""
    if len(n) >= 3 and (n[0], n[1], n[2]) in catalogo:
        peso = catalogo[(n[0], n[1], n[2])]
        return largura, peso, f'"{nome}": peso deduzido do tubete de mesma medida ({peso:.2f})'.replace(".", ",")
    peso = 0.0
    if isinstance(peso_reserva, (int, float)) and not pd.isna(peso_reserva):
        peso = float(peso_reserva)
    elif isinstance(peso_reserva, str):
        r = numeros_da_medida(peso_reserva)
        peso = r[-1] if r else 0.0
    if _peso_valido(peso):
        return largura, peso, f'"{nome}": peso deduzido do produto/OF ({peso:.2f})'.replace(".", ",")
    return largura, 0.0, f'"{nome}": peso não identificado'


class _Somador:
    def __init__(self):
        self.tubetes = {}     # (largura, peso) -> [prog, não prog, encaixe]
        self.nomes = {}       # (largura, peso) -> nomes do ERP
        self.obs = {}         # (largura, peso) -> observações
        self.pallets = {}     # tipo -> [prog, não prog, encaixe]

    def tubete(self, nome, k, qtd, peso_reserva, catalogo):
        if not _eh_tubete(nome) or qtd <= 0:
            return None
        nome = nome.strip()
        largura, peso, obs = medida_do_tubete(nome, peso_reserva, catalogo)
        chave = (largura, round(peso, 2))
        self.tubetes.setdefault(chave, [0.0, 0.0, 0.0])[k] += qtd
        nomes = self.nomes.setdefault(chave, [])
        if nome not in nomes:
            nomes.append(nome)
        if obs:
            lista = self.obs.setdefault(chave, [])
            if obs not in lista:
                lista.append(obs)
        return chave

    def pallet(self, tipo, k, qtd):
        tipo = (tipo or "").strip() if isinstance(tipo, str) else ""
        if tipo and qtd > 0:
            self.pallets.setdefault(tipo, [0.0, 0.0, 0.0])[k] += qtd


def _num(v) -> float:
    n = pd.to_numeric(v, errors="coerce")
    return 0.0 if pd.isna(n) else float(n)


def _arredondar_cima(x: float) -> float:
    return float(math.ceil(round(x, 6)))


def calcular_consumo(plan: pd.DataFrame, encaixe: pd.DataFrame | None, carteira: pd.DataFrame | None):
    """Devolve (tubetes, pallets, detalhe, resumo)."""
    nomes = list(plan["tubete"]) if plan is not None and "tubete" in plan else []
    if carteira is not None and "tubete" in carteira:
        nomes += list(carteira["tubete"])
    catalogo = catalogo_de_tubetes(nomes)
    soma, detalhe = _Somador(), []
    n_ofs = n_nao_prog = n_enc = 0

    for _, r in (plan if plan is not None else pd.DataFrame()).iterrows():
        qtde_of = _num(r["qtde_of"])
        if pd.notna(r["final_real"]) or qtde_of <= 0:
            continue
        fracao = max(0.0, (qtde_of - _num(r["qtde_prod"])) / qtde_of)
        maquina = str(r["maquina"]).strip()
        k = 1 if maquina.upper() == MAQUINA_NAO_PROGRAMADA else 0
        n_ofs += 1
        n_nao_prog += k
        nt = _arredondar_cima(_num(r["num_tubete"]) * fracao)
        np_ = _arredondar_cima(_num(r["num_pallet"]) * fracao)
        chave = soma.tubete(r["tubete"], k, nt, r.get("peso_tubete"), catalogo)
        soma.pallet(r["pallet"], k, np_)
        detalhe.append(_linha_detalhe("planejamento (não programada)" if k else "planejamento", maquina,
                                      r["id_of"], r["pedido"], r["seq_prog"], r["tubete"], nt, chave,
                                      r["pallet"], np_, fracao))

    if encaixe is not None and not encaixe.empty:
        cart = {}
        if carteira is not None:
            for _, c in carteira.iterrows():
                cart.setdefault((_texto_int(c["num_pedido"]), _texto_int(c["prog"])), c)
        for _, e in encaixe[encaixe["sugestao"] == "NOVO NA MÁQUINA"].iterrows():
            n_enc += 1
            c = cart.get((_texto_int(e["num_pedido"]), _texto_int(e["prog"])))
            if c is None:
                detalhe.append(_linha_detalhe("encaixe (OF nova)", e["maquina"], None, e["num_pedido"], e["prog"],
                                              "pedido não achado na carteira", 0, None, None, 0, 1))
                continue
            nt, np_ = _num(c["qtde_tubete"]), _num(c["qtde_pallet"])
            chave = soma.tubete(c["tubete"], 2, nt, c["produto"], catalogo)
            soma.pallet(c["pallet"], 2, np_)
            detalhe.append(_linha_detalhe("encaixe (OF nova)", e["maquina"], None, e["num_pedido"], e["prog"],
                                          c["tubete"], nt, chave, c["pallet"], np_, 1))

    tubetes = pd.DataFrame([{
        "largura_mm": k[0], "peso_kg": k[1], "programado_maquinas": v[0], "nao_programadas": v[1],
        "sem_encaixe": v[0] + v[1], "encaixe": v[2], "com_encaixe": sum(v),
        "nomes_no_erp": "; ".join(soma.nomes[k]), "observacao": "; ".join(soma.obs.get(k, [])) or None,
    } for k, v in soma.tubetes.items()])
    if not tubetes.empty:
        tubetes = tubetes.sort_values(["largura_mm", "peso_kg"], kind="mergesort").reset_index(drop=True)
    pallets = pd.DataFrame([{
        "pallet": k, "programado_maquinas": v[0], "nao_programadas": v[1], "sem_encaixe": v[0] + v[1],
        "encaixe": v[2], "com_encaixe": sum(v),
    } for k, v in soma.pallets.items()])
    if not pallets.empty:
        pallets = pallets.sort_values("com_encaixe", ascending=False, kind="mergesort").reset_index(drop=True)

    def tot(df, coluna):
        total = float(df[coluna].sum()) if not df.empty else 0.0
        return f"{total:,.0f}".replace(",", ".")

    resumo = (f"OFs abertas no planejamento: {n_ofs} ({n_nao_prog} não programadas) | encaixes novos: {n_enc} | "
              f"tubetes sem encaixe: {tot(tubetes, 'sem_encaixe')}, com encaixe: {tot(tubetes, 'com_encaixe')} | "
              f"pallets sem encaixe: {tot(pallets, 'sem_encaixe')}, com encaixe: {tot(pallets, 'com_encaixe')}")
    return tubetes, pallets, pd.DataFrame(detalhe), resumo


def _texto_int(v) -> str:
    n = pd.to_numeric(v, errors="coerce")
    return str(v).strip() if pd.isna(n) else str(int(n))


def _linha_detalhe(origem, maquina, id_of, pedido, prog, tubete, n_tub, chave, pallet, n_pal, fracao) -> dict:
    tem_tubete = _eh_tubete(tubete) or tubete == "pedido não achado na carteira"
    return {"origem": origem, "maquina": maquina, "id_of": id_of, "pedido": pedido, "prog": prog,
            "tubete": tubete if tem_tubete else "(sem tubete)", "qtde_tubete": n_tub if _eh_tubete(tubete) else 0,
            "largura_mm": chave[0] if chave else None, "peso_tubete_kg": chave[1] if chave else None,
            "pallet": pallet, "qtde_pallet": n_pal, "saldo_of": fracao}
