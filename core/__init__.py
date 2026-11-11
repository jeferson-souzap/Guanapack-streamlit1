"""Núcleo do app: banco, contexto (usuário/PC/pasta), relatórios, cálculo e regras."""
import pandas as pd

# O Streamlit instala o pyarrow, e com ele o pandas 3 guarda texto em colunas Arrow. As regras foram
# conferidas (0 diferenças com a planilha) com o texto em Python puro, como no Guanapack-Flask:
# coluna de texto toda vazia, por exemplo, não aceita conta no modo Arrow.
try:
    pd.set_option("mode.string_storage", "python")
except Exception:  # pandas antigo sem a opção
    pass
