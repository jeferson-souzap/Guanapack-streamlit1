from datetime import datetime
import re
import pandas as pd



# Regex compilados para reuso
_PADRAO_FAMILIA = re.compile(r"\bSTRETCH\b\s+(.*?)\s*(?=\d)", flags=re.IGNORECASE)
_PADRAO_CHAIN = re.compile(r'\d+(?:[.,]\d+)?(?:\s*X\s*\d+(?:[.,]\d+)?)+', re.IGNORECASE)


def extrair_familia(descricao: str) -> str | None:
    """Extrai a família da descrição do produto via regex."""
    if pd.isna(descricao):
        return None
    texto = re.sub(r"\s+", " ", str(descricao)).strip()
    achado = _PADRAO_FAMILIA.search(texto)
    if not achado:
        return None
    familia = achado.group(1).strip().upper()
    return familia or None


def parse_dimensoes(desc: str) -> pd.Series:
    """Extrai largura, micra, peso e peso do tubete da descrição técnica."""
    if not isinstance(desc, str):
        return pd.Series({"largura": None, "micra": None, "peso": None, "peso_tubete": None}, dtype="float64")

    m = _PADRAO_CHAIN.search(desc)
    if not m:
        return pd.Series({"largura": None, "micra": None, "peso": None, "peso_tubete": None}, dtype="float64")

    nums = [float(n.strip().replace(",", ".")) for n in re.split(r'X', m.group(0), flags=re.IGNORECASE)]

    if len(nums) == 5:
        largura, micra, _, peso, peso_tubete = nums
    elif len(nums) == 3:
        largura, micra, peso = nums
        peso_tubete = None
    else:
        largura = micra = peso = peso_tubete = None

    return pd.Series({
        "largura": largura,
        "micra": micra,
        "peso": peso,
        "peso_tubete": peso_tubete
    }, dtype="float64")


def normalizar_descricao(desc: str) -> str:
    """Padroniza espaços e números para permitir comparar descrições entre relatórios."""
    texto = re.sub(r"\s+", " ", desc).strip()
    # " X " uniforme entre medidas (ex.: "500X25" -> "500 X 25")
    texto = re.sub(r"(?<=\d)\s*X\s*(?=\d)", " X ", texto, flags=re.IGNORECASE)
    # Zeros à direita no decimal (ex.: "17,50" -> "17,5" e "18,0" -> "18")
    texto = re.sub(r"(\d+),(\d*?)0+\b", lambda m: f"{m.group(1)},{m.group(2)}" if m.group(2) else m.group(1), texto)
    return texto


def remover_peso_tubete(desc: str) -> str:
    """Gera a descrição alternativa removendo o peso do tubete."""
    if not isinstance(desc, str):
        return ""

    m = _PADRAO_CHAIN.search(desc)
    if not m:
        return normalizar_descricao(desc)

    matches = list(re.finditer(r'\d+(?:[.,]\d+)?', m.group(0)))
    if len(matches) == 5:
        start_tubete = m.start() + matches[4].start()
        end_tubete = m.start() + matches[4].end()
        prefixo = re.sub(r'\s*X\s*$', '', desc[:start_tubete], flags=re.IGNORECASE)
        return normalizar_descricao((prefixo + desc[end_tubete:]).strip(" -"))

    return normalizar_descricao(desc)


def processar_dataframe_estoque(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica todas as transformações e regras de negócio no DataFrame de estoque."""
    df_proc = df.copy()

    # 1. Extração da família
    df_proc['tipo_familia_teste'] = df_proc['desc_tecnica'].map(extrair_familia)

    # 2. Parsing das dimensões e descrição alternativa
    dimensoes = df_proc['desc_tecnica'].apply(parse_dimensoes)
    df_proc[['largura', 'micra', 'peso', 'peso_tubete']] = dimensoes
    df_proc['desc_alternativa'] = df_proc['desc_tecnica'].apply(remover_peso_tubete)

    # 3. Cálculo de dias parado (Slow Move)
    hoje = pd.Timestamp.now().normalize()
    df_proc['final_of'] = pd.to_datetime(df_proc['final_of'], errors='coerce', format='mixed', dayfirst=True)
    df_proc['dias_parado'] = (hoje - df_proc['final_of']).dt.days

    # 4. Tratamento de nulos e tipos de dados
    df_proc['peso_tubete'] = df_proc['peso_tubete'].fillna(0)

    agora = datetime.now().astimezone()
    dt_hoje = agora.strftime("%Y-%m-%d")
    df_proc['import_data'] = dt_hoje
    df_proc['import_data_hora'] = agora.isoformat(timespec="seconds")

    # num_seq_pallets fica como texto: vem como lista ("1,2,3,8") e viraria vazio se convertido
    colunas_numericas = ['largura', 'micra', 'peso', 'peso_tubete', 'peso_liquido', 'peso_bruto']
    for col in colunas_numericas:
        if col in df_proc.columns:
            df_proc[col] = pd.to_numeric(df_proc[col], errors='coerce')

    colunas_datas = ['dt_embarque', 'dt_embarque_original', 'import_data']
    for col in colunas_datas:
        if col in df_proc.columns:
            df_proc[col] = pd.to_datetime(df_proc[col], errors='coerce', format='mixed', dayfirst=True)

    return df_proc


def obter_estoque_limpo(fonte_dados) -> pd.DataFrame:    
    df_raw = pd.read_excel(fonte_dados)
    df_limpo = processar_dataframe_estoque(df_raw)
    return df_limpo
