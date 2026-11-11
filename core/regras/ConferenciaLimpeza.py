"""
Conferência do dataframe limpo (lido de volta do banco) contra o relatório original.

A limpeza só pode acrescentar colunas: as linhas, os totais e os valores das colunas
originais precisam continuar iguais. Datas e números são comparados pelo valor, não
pelo formato (ex.: 1 e 1.0 são iguais).
"""
import numpy as np
import pandas as pd


def _valores_diferentes(original: pd.Series, limpo: pd.Series) -> pd.Series:
    """Marca as linhas em que o valor mudou."""
    # Data vazia vem do ERP como "  -   -" (ou "  -   -  : :" com hora) e a limpeza a deixa
    # em branco: conta como igual
    # (no pandas 3 o texto vem com o tipo "str" em vez de object)
    if pd.api.types.is_object_dtype(original) or pd.api.types.is_string_dtype(original):
        original = original.mask(original.astype(str).str.fullmatch(r'[\s:-]*') & original.notna())
    ambos_vazios = original.isna() & limpo.isna()

    if pd.api.types.is_datetime64_any_dtype(limpo):
        original = pd.to_datetime(original, errors='coerce', format='mixed', dayfirst=True)
        return ~((original == limpo) | ambos_vazios)

    if pd.api.types.is_numeric_dtype(original) and pd.api.types.is_numeric_dtype(limpo):
        return ~(np.isclose(original, limpo) | ambos_vazios)

    texto_original = original.where(original.isna(), original.astype(str).str.strip())
    texto_limpo = limpo.where(limpo.isna(), limpo.astype(str).str.strip())
    return ~((texto_original == texto_limpo) | ambos_vazios)


def conferir_limpeza(original: pd.DataFrame, limpo: pd.DataFrame, colunas_total: list[str],
                     filtro_original=None, descricao_filtro: str = "") -> dict:
    """Compara o limpo com o original.

    filtro_original: função que recebe o original e devolve as linhas que a limpeza mantém
    (para relatórios em que a limpeza descarta linhas de propósito).
    Retorna {"ok": bool, "linhas": texto, "totais": [...], "problemas": [...]}.
    """
    problemas = []

    if filtro_original is None:
        linhas = f"original {len(original)} | limpo {len(limpo)}"
    else:
        total_original = len(original)
        original = original[filtro_original(original)]
        linhas = f"original {total_original} ({descricao_filtro}: {len(original)}) | limpo {len(limpo)}"

    # O limpo segue a ordem do original; o índice do original dá a linha no Excel
    limpo = limpo.copy()
    limpo.index = original.index if len(original) == len(limpo) else limpo.index
    if len(original) != len(limpo):
        problemas.append("quantidade de linhas diferente")

    totais = []
    for col in colunas_total:
        soma_original = pd.to_numeric(original[col], errors='coerce').sum()
        soma_limpo = pd.to_numeric(limpo[col], errors='coerce').sum()
        totais.append({"coluna": col, "original": soma_original, "limpo": soma_limpo})
        if not np.isclose(soma_original, soma_limpo):
            problemas.append(f"total de {col} diferente")

    faltando = [c for c in original.columns if c not in limpo.columns]
    if faltando:
        problemas.append("colunas do original ausentes no limpo: " + ", ".join(faltando))

    # Valor a valor só faz sentido se as linhas estiverem na mesma ordem e quantidade
    if len(original) == len(limpo):
        for col in original.columns:
            if col in faltando:
                continue
            diferentes = _valores_diferentes(original[col], limpo[col])
            if diferentes.any():
                linha = diferentes.idxmax()
                problemas.append(f"coluna {col}: {diferentes.sum()} valores alterados "
                                 f"(ex.: linha {linha + 2}: '{original.at[linha, col]}' -> '{limpo.at[linha, col]}')")

    return {"ok": not problemas, "linhas": linhas, "totais": totais, "problemas": problemas}
