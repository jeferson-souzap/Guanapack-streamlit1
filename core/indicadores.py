"""
Números do painel, calculados a partir das saídas do pipeline (em memória).

Cada "Atualizar tudo" grava um retrato desses números em historico_indicadores, para ver a
evolução (módulo Histórico).
"""
import pandas as pd

from core import contexto, db
from core.pipeline import Contexto
from core.regras.LimpezaCtlrPedidos import STATUS_EM_ABERTO


def _tentar(func):
    try:
        return func()
    except Exception:
        return None


def calcular(ctx: Contexto) -> dict:
    """Indicadores disponíveis (os que dependem de relatório faltando ficam None)."""
    p = dict.fromkeys(["atrasados", "vao_atrasar", "lead_time_estoque", "pedidos_reserva", "sem_estoque", "encaixe_pedidos",
                       "encaixe_novos", "encaixe_atendem", "ofs_passam_atrasar", "troca_pedir",
                       "tubetes_sem_encaixe", "tubetes_com_encaixe", "pallets_sem_encaixe", "pallets_com_encaixe",
                       "estoque_kg", "slow_move_kg", "em_aberto", "em_aberto_kg"])

    ctlr = _tentar(ctx.ctlr)
    if ctlr is not None:
        p["atrasados"] = int((ctlr["atraso_otd"] == "ATRASADO").sum())
        p["vao_atrasar"] = int((ctlr["atraso_otd"] == "VAI ATRASAR").sum())
        p["lead_time_estoque"] = int(ctlr["lead_time_estoque"].notna().sum())
        aberto = ctlr["status_pedido"].isin(STATUS_EM_ABERTO)
        p["em_aberto"] = int(aberto.sum())
        p["em_aberto_kg"] = float(pd.to_numeric(ctlr.loc[aberto, "peso"], errors="coerce").sum())

    est = _tentar(ctx.estoque)
    if est is not None:
        disp = est[est["tipo_estoque"] == "DISPONIVEL"]
        peso = pd.to_numeric(disp["peso_liquido"], errors="coerce")
        p["estoque_kg"] = float(peso.sum())
        dias = pd.to_numeric(disp["dias_parado"], errors="coerce")
        p["slow_move_kg"] = float(peso[dias > ctx.params["dias_slow_move"]].sum())

    res = _tentar(ctx.reserva)
    if res is not None:
        p["pedidos_reserva"] = int(len(res))
        p["sem_estoque"] = int((res["tem_estoque"] != "SIM").sum())

    enc = _tentar(ctx.encaixe)
    if enc is not None:
        ped, filas, _ = enc
        novos = ped["sugestao"] == "NOVO NA MÁQUINA"
        p["encaixe_pedidos"] = int(len(ped))
        p["encaixe_novos"] = int(novos.sum())
        p["encaixe_atendem"] = int((novos & (ped["atende_embarque"] == "SIM")).sum())
        p["ofs_passam_atrasar"] = int((filas["atraso"] == "PASSA A ATRASAR").sum()) if "atraso" in filas else 0

    ins = _tentar(ctx.insumos)
    if ins is not None:
        tub, pal, _, _ = ins
        p["tubetes_sem_encaixe"] = float(tub["sem_encaixe"].sum())
        p["tubetes_com_encaixe"] = float(tub["com_encaixe"].sum())
        p["pallets_sem_encaixe"] = float(pal["sem_encaixe"].sum())
        p["pallets_com_encaixe"] = float(pal["com_encaixe"].sum())

    tr = _tentar(ctx.troca)
    if tr is not None:
        p["troca_pedir"] = int((tr[0]["situacao"] == "PEDIR TROCA").sum()) if len(tr[0]) else 0
    return p


COLUNAS_HISTORICO = ["atrasados", "vao_atrasar", "lead_time_estoque", "pedidos_reserva", "sem_estoque", "encaixe_pedidos", "encaixe_novos",
                     "encaixe_atendem", "ofs_passam_atrasar", "troca_pedir", "tubetes_sem_encaixe",
                     "tubetes_com_encaixe", "pallets_sem_encaixe", "pallets_com_encaixe", "estoque_kg", "slow_move_kg"]


def gravar(ind: dict, duracao_s: float, erros: dict):
    valores = [ind.get(c) for c in COLUNAS_HISTORICO]
    resultado = "ok" if not erros else "; ".join(f"{k}: {v}" for k, v in erros.items())[:500]
    db.executar(f"INSERT INTO historico_indicadores (data_hora, usuario, pc, {', '.join(COLUNAS_HISTORICO)}, "
                f"duracao_s, resultado) VALUES (?, ?, ?, {', '.join('?' * len(COLUNAS_HISTORICO))}, ?, ?)",
                (db.agora(), contexto.usuario(), contexto.pc(), *valores, round(duracao_s, 1), resultado))


def historico(dias: int = 90) -> pd.DataFrame:
    df = db.consultar_df("SELECT * FROM historico_indicadores WHERE data_hora >= datetime('now', 'localtime', ?) "
                         "ORDER BY data_hora", (f"-{int(dias)} days",))
    if not df.empty:
        df["data_hora"] = pd.to_datetime(df["data_hora"])
    return df
