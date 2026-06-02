import streamlit as st
import pandas as pd
import requests
import time
import numpy as np
from io import BytesIO
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================================================
# SESSÃO HTTP ROBUSTA (retry + User-Agent)
# =========================================================
# No Streamlit Cloud o app roda em datacenter (maior latência ao IBGE) e a API
# do IBGE é lenta/instável e às vezes rejeita clientes sem User-Agent. Por isso
# usamos uma sessão com retry automático e cabeçalhos de navegador.
def _build_http_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.5,  # espera 0s, 1.5s, 3s, 6s... entre tentativas
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; app-indicadores-contabeis/1.0)",
        "Accept": "application/json",
    })
    return s

# (connect timeout, read timeout) — connect maior por causa da latência do datacenter
HTTP_TIMEOUT = (30, 90)

HTTP = _build_http_session()

# =========================================================
# CONFIG STREAMLIT
# =========================================================
st.set_page_config(
    page_title="Análise DC — 5 Maiores Cidades do RJ (Cap. 6)",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# =========================================================
# ESTADO
# =========================================================
if "ibge_loaded" not in st.session_state:
    st.session_state.ibge_loaded = False
if "siconfi_loaded" not in st.session_state:
    st.session_state.siconfi_loaded = False
if "final_table" not in st.session_state:
    st.session_state.final_table = pd.DataFrame()

if "pib_df" not in st.session_state:
    st.session_state.pib_df = pd.DataFrame()   # colunas: cod_ibge, ano, pib_pc
if "pop_df" not in st.session_state:
    st.session_state.pop_df = pd.DataFrame()   # colunas: cod_ibge, ano, pop

if "fontes_table" not in st.session_state:
    st.session_state.fontes_table = pd.DataFrame()  # anos IBGE de referência usados

if "siconfi_table" not in st.session_state:
    st.session_state.siconfi_table = pd.DataFrame()  # extrações brutas SICONFI/IBGE

if "ibge_debug" not in st.session_state:
    st.session_state.ibge_debug = {}           # guarda metadados/variáveis detectadas


# =========================================================
# FORMATAÇÃO BR
# =========================================================
def fmt_br_num(x, casas=2):
    if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
        return ""
    try:
        x = float(x)
    except Exception:
        return str(x)
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def fmt_br_int(x):
    if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
        return ""
    try:
        return fmt_br_num(int(round(float(x))), casas=0)
    except Exception:
        return str(x)

def fmt_br_pct(x, casas=2):
    if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
        return ""
    try:
        x = float(x)
    except Exception:
        return str(x)
    return f"{fmt_br_num(x, casas=casas)}%"

def build_br_formatters(df: pd.DataFrame):
    fmt = {}
    for col in df.columns:
        if col == "Ano":
            fmt[col] = fmt_br_int
        elif "Classificação" in col:
            fmt[col] = fmt_br_int
        elif "Variação (%)" in col:
            fmt[col] = fmt_br_pct
        elif pd.api.types.is_numeric_dtype(df[col]):
            fmt[col] = fmt_br_num
    return fmt

def style_table(df: pd.DataFrame):
    styler = (
        df.style
        .set_properties(**{"text-align": "right"}, subset=df.select_dtypes(include="number").columns)
        .set_properties(**{"text-align": "left"}, subset=[c for c in df.columns if c not in df.select_dtypes(include="number").columns])
        .set_table_styles([
            {"selector": "th", "props": [("text-align", "left"), ("font-weight", "700")]},
            {"selector": "td", "props": [("vertical-align", "top")]},
        ])
        .set_table_styles(
            [
                {"selector": "thead th", "props": [("position", "sticky"), ("top", "0"), ("background", "#111827")]},
                {"selector": "tbody tr:nth-child(even)", "props": [("background", "rgba(255,255,255,0.03)")]},
            ],
            overwrite=False
        )
    )
    return styler

def gerar_excel_download(df: pd.DataFrame):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Indicadores", index=True)
    output.seek(0)
    return output


# =========================================================
# MAPAS / DICIONÁRIOS (SEU CASO: 5 MAIORES RJ)
# =========================================================
ibge_to_nome = {
    3304557: "1_Rio de Janeiro",
    3304904: "2_São Gonçalo",
    3301702: "3_Duque de Caxias",
    3303500: "4_Nova Iguaçu",
    3301009: "5_Campos dos Goytacazes"
}
nome_to_ibge = {v: k for k, v in ibge_to_nome.items()}
all_municipios_names = list(ibge_to_nome.values())

# anos SICONFI (você pode ampliar; o app vai lidar com ausência de PIB em certos anos)
available_years = list(range(2020, 2025))


interpretacoes = {
    "A1_PIB per Capita": "Renda média por habitante",
    "A2_Receita Total per Capita": "Arrecadação por habitante",
    "A3_IPTU per Capita": "Arrecadação de IPTU por habitante",
    "A4_ISS per Capita": "Arrecadação de ISS por habitante",
    "A5_Dívida Ativa per Capita": "Valor em Dívida Ativa por habitante",
    "B1_Despesas Orçamentárias per Capita": "Despesa por habitante",
    "B2_Investimentos per Capita": "Investimento por habitante",
    "B3_Gastos com Saúde per Capita": "Gasto com Saúde por habitante",
    "B4_Gastos com Educação per Capita": "Gasto com Educação por habitante",
    "B5_Transferências para o Legislativo per Capita": "Gasto com Legislativo por habitante",
    "C1_Receita Tributária per Capita": "Receita Tributária por habitante",
    "C2_Receita de Transferências per Capita": "Transferências por habitante",
    "D1_Liquidez Instantânea ou Imediata": "Caixa/PC: paga dívidas de curto prazo?",
    "D3_Liquidez com recursos de terceiros": "Caixa cobre depósitos/restituições?",
    "D4_Liquidez Corrente": "AC/PC: liquidez no ano",
    "E2_Liquidez Seca": "AC sem estoques / PC",
    "E3_Liquidez Geral": "(AC+ANC)/(PC+PNC)",
    "E6_Solvência Geral": "Ativo / Passivo exigível",
    "F1_Endividamento Geral": "Passivo exigível / Ativo",
    "F2_Composição das Exigibilidades": "PC / Passivo exigível",
    "F3_Imobilização do Patrimônio Líquido ou Capital Próprio": "Imobilizado+Investimentos / PL",
    "F4_Grau de Comprometimento da Categoria Econômica Corrente": "Desp. Corrente / Rec. Corrente",
    "F5_Grau de Comprometimento da Categoria Econômica de Capital": "Desp. Capital / Rec. Capital",
    "G1_Grau de Gasto com Pessoal em relação a Despesa Orçamentária": "Pessoal / Desp. Corrente",
    "G2_Grau de Investimento em relação a Despesa Orçamentária": "Investimentos / Desp. Corrente",
    "G3_Grau de Gasto com Pessoal em relação a Receita corrente Líquida": "Pessoal / RCL",
    "G4_Grau de Receitas Correntes Próprias ": "(Rec. Corrente - Transf.) / Rec. Corrente",
    "H1_Grau de Execução Orçamentária da Receita": "Receita executada / prevista",
    "H2_Grau de Execução Orçamentária da Despesa": "Despesa executada / fixada",
    "H3_Grau do Resultado da Execução Orçamentária": "Despesa / Receita",
    "H4_Grau de Autonomia Orçamentária": "Receita própria / despesa",
    "H5_Grau de Amortização e refinanciamento de dívida": "Op. crédito / despesa",
    "H6_Grau de Encargos da dívida na despesa corrente": "Juros / despesa",
}

formulas = {
    "A1_PIB per Capita": "PIB total / População (IBGE/SIDRA) — usa o último ano disponível quando o ano selecionado ainda não foi divulgado",
    "A2_Receita Total per Capita": "Receita Total / Habitantes",
    "A3_IPTU per Capita": "IPTU / Habitantes",
    "A4_ISS per Capita": "ISS / Habitantes",
    "A5_Dívida Ativa per Capita": "Dívida Ativa / Habitantes",
    "B1_Despesas Orçamentárias per Capita": "Despesa Total / Habitantes",
    "B2_Investimentos per Capita": "Investimentos / Habitantes",
    "B3_Gastos com Saúde per Capita": "Saúde / Habitantes",
    "B4_Gastos com Educação per Capita": "Educação / Habitantes",
    "B5_Transferências para o Legislativo per Capita": "Legislativo / Habitantes",
    "C1_Receita Tributária per Capita": "Rec. Tributária / Habitantes",
    "C2_Receita de Transferências per Capita": "Transferências / Habitantes",
    "D1_Liquidez Instantânea ou Imediata": "Disponível / PC",
    "D3_Liquidez com recursos de terceiros": "Disponível / Restituições",
    "D4_Liquidez Corrente": "AC / PC",
    "E2_Liquidez Seca": "(AC-Estoques) / PC",
    "E3_Liquidez Geral": "(AC+ANC) / (PC+PNC)",
    "E6_Solvência Geral": "Ativo Total / Passivo Exigível",
    "F1_Endividamento Geral": "(Passivo Exigível / Ativo Total) x 100",
    "F2_Composição das Exigibilidades": "(PC / Passivo Exigível) x 100",
    "F3_Imobilização do Patrimônio Líquido ou Capital Próprio": "((Investimentos+Imobilizado)/PL) x 100",
    "F4_Grau de Comprometimento da Categoria Econômica Corrente": "(Desp. Correntes / Rec. Correntes) x 100",
    "F5_Grau de Comprometimento da Categoria Econômica de Capital": "(Desp. Capital / Rec. Capital) x 100",
    "G1_Grau de Gasto com Pessoal em relação a Despesa Orçamentária": "(Pessoal / Desp. Corrente) x 100",
    "G2_Grau de Investimento em relação a Despesa Orçamentária": "(Investimentos / Desp. Corrente) x 100",
    "G3_Grau de Gasto com Pessoal em relação a Receita corrente Líquida": "(Pessoal / RCL) x 100",
    "G4_Grau de Receitas Correntes Próprias ": "((Rec. Correntes - Transf.) / Rec. Correntes) x 100",
    "H1_Grau de Execução Orçamentária da Receita": "(Receita / Prevista) x 100",
    "H2_Grau de Execução Orçamentária da Despesa": "(Despesa / Fixada) x 100",
    "H3_Grau do Resultado da Execução Orçamentária": "(Despesa / Receita) x 100",
    "H4_Grau de Autonomia Orçamentária": "((Rec. Corrente - Transf.) / Desp. Total) x 100",
    "H5_Grau de Amortização e refinanciamento de dívida": "(Op. Crédito / Desp. Total) x 100",
    "H6_Grau de Encargos da dívida na despesa corrente": "(Juros / Desp. Total) x 100",
}


# =========================================================
# DOCUMENTAÇÃO DAS EXTRAÇÕES SICONFI/IBGE
# (de qual relatório/anexo, coluna e cod_conta cada métrica é obtida)
# =========================================================
EXTRACOES_DOC = [
    # Métrica, Relatório/Anexo, Coluna (filtro), Conta / cod_conta (filtro)
    ("Receita Total", "RREO - Anexo 01", 'Até o Bimestre (c)', 'cod_conta == "TotalReceitas"'),
    ("IPTU", "RREO - Anexo 03", 'TOTAL (ÚLTIMOS 12 MESES)', 'conta contém "IPTU"'),
    ("ISS", "RREO - Anexo 03", 'TOTAL (ÚLTIMOS 12 MESES)', 'conta contém "ISS"'),
    ("Dívida Ativa", "DCA - Anexo I-AB", '—', 'cod_conta == "P1.1.2.5.0.00.00" ou "P1.2.1.1.1.04.00"'),
    ("Despesa Total", "RREO - Anexo 01", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)', 'cod_conta == "TotalDespesas"'),
    ("Investimentos (despesa)", "RREO - Anexo 01", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)', 'cod_conta == "Investimentos"'),
    ("Saúde", "RREO - Anexo 02", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)', 'conta == "Saúde" & cod_conta == "RREO2TotalDespesas"'),
    ("Educação", "RREO - Anexo 02", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)', 'conta == "Educação" & cod_conta == "RREO2TotalDespesas"'),
    ("Legislativo", "RREO - Anexo 02", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)', 'conta == "Legislativa" & cod_conta == "RREO2TotalDespesas"'),
    ("Receita Tributária", "RREO - Anexo 01", 'Até o Bimestre (c)', 'cod_conta == "ReceitaTributaria"'),
    ("Transferências Correntes", "RREO - Anexo 01", 'Até o Bimestre (c)', 'cod_conta == "TransferenciasCorrentes"'),
    ("Ativo Circulante", "DCA - Anexo I-AB", '—', 'cod_conta == "P1.1.0.0.0.00.00"'),
    ("Disponível (Caixa/Bancos)", "DCA - Anexo I-AB", '—', 'cod_conta == "P1.1.1.0.0.00.00"'),
    ("Ativo Não Circulante", "DCA - Anexo I-AB", '—', 'cod_conta == "P1.2.0.0.0.00.00"'),
    ("Passivo Circulante", "DCA - Anexo I-AB", '—', 'cod_conta == "P2.1.0.0.0.00.00"'),
    ("Passivo Não Circulante", "DCA - Anexo I-AB", '—', 'cod_conta == "P2.2.0.0.0.00.00"'),
    ("Restituições", "DCA - Anexo I-AB", '—', 'cod_conta == "P2.1.8.8.0.00.00"'),
    ("Estoques", "DCA - Anexo I-AB", '—', 'cod_conta == "P1.1.5.0.0.00.00"'),
    ("Ativo Total", "DCA - Anexo I-AB", '—', 'cod_conta == "P1.0.0.0.0.00.00"'),
    ("Passivo Exigível", "DCA - Anexo I-AB", '—', 'cod_conta == "P2.1.0.0.0.00.00" | "P2.2.0.0.0.00.00"'),
    ("Imobilizado", "DCA - Anexo I-AB", '—', 'cod_conta == "P1.2.3.0.0.00.00"'),
    ("Investimentos (ativo)", "DCA - Anexo I-AB", '—', 'cod_conta == "P1.1.4.0.0.00.00"'),
    ("Patrimônio Líquido", "DCA - Anexo I-AB", '—', 'cod_conta == "P2.3.0.0.0.00.00"'),
    ("Despesa Corrente", "RREO - Anexo 01", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)', 'cod_conta == "DespesasCorrentes"'),
    ("Receita Corrente", "RREO - Anexo 01", 'Até o Bimestre (c)', 'cod_conta == "ReceitasCorrentes"'),
    ("Despesa de Capital", "RREO - Anexo 01", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)', 'cod_conta == "DespesasDeCapital"'),
    ("Receita de Capital", "RREO - Anexo 01", 'Até o Bimestre (c)', 'cod_conta == "ReceitasDeCapital"'),
    ("Pessoal e Encargos", "RREO - Anexo 01", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)', 'cod_conta == "PessoalEEncargosSociais"'),
    ("RCL", "RREO - Anexo 03", 'TOTAL (ÚLTIMOS 12 MESES)', 'cod_conta == "RREO3ReceitaCorrenteLiquida"'),
    ("Receita Prevista", "RREO - Anexo 01", 'PREVISÃO ATUALIZADA (a)', 'cod_conta == "TotalReceitas"'),
    ("Despesa Fixada", "RREO - Anexo 01", 'DOTAÇÃO INICIAL (d)', 'cod_conta == "TotalDespesas"'),
    ("Operações de Crédito", "RREO - Anexo 01", 'Até o Bimestre (c)', 'cod_conta == "ReceitasDeOperacoesDeCredito"'),
    ("Juros e Encargos da Dívida", "RREO - Anexo 01", 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)', 'cod_conta == "JurosEEncargosDaDivida"'),
    ("Habitantes (IBGE)", "IBGE/SIDRA - Agregado 6579", 'População residente estimada (var. 9324)', 'localidade N6 (município)'),
    ("PIB per capita (IBGE)", "IBGE/SIDRA - Agregado 5938", 'PIB a preços correntes (var. 37) ÷ População', 'localidade N6 (município)'),
]


# =========================================================
# IBGE (AGREGADOS / SIDRA) - ROBUSTO
# =========================================================
IBGE_AGREGADOS_BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"

# ✅ Confirmados nos metadados do IBGE:
AGREG_PIB_MUN = 5938
PIB_TOTAL_VAR = "37"     # "Produto Interno Bruto a preços correntes" (Mil Reais)  :contentReference[oaicite:2]{index=2}

AGREG_POP     = 6579
POP_VAR       = "9324"   # "População residente estimada"                          :contentReference[oaicite:3]{index=3}


def _http_get_json(url: str, timeout=HTTP_TIMEOUT):
    r = HTTP.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _extract_variables_from_metadados(meta: dict | list) -> list[dict]:
    """
    Tenta extrair lista de variáveis de vários formatos possíveis.
    Retorna lista de dicts com pelo menos: id (ou codigo) e nome (se existir).
    """
    candidates = []

    if isinstance(meta, dict):
        # formatos comuns
        for k in ["variaveis", "variáveis", "variavel", "variável", "variables"]:
            if k in meta and isinstance(meta[k], list):
                candidates = meta[k]
                break

        # às vezes fica aninhado
        if not candidates:
            for k in meta.keys():
                if isinstance(meta[k], dict):
                    for kk in ["variaveis", "variáveis"]:
                        if kk in meta[k] and isinstance(meta[k][kk], list):
                            candidates = meta[k][kk]
                            break
                if candidates:
                    break

    # se vier como lista, tenta achar bloco com variaveis
    if not candidates and isinstance(meta, list):
        for item in meta:
            if isinstance(item, dict) and "variaveis" in item and isinstance(item["variaveis"], list):
                candidates = item["variaveis"]
                break

    # normaliza
    out = []
    for v in candidates or []:
        if not isinstance(v, dict):
            continue
        vid = v.get("id") or v.get("ID") or v.get("codigo") or v.get("código")
        nome = v.get("nome") or v.get("variavel") or v.get("variável") or v.get("descricao") or v.get("descrição")
        out.append({"id": vid, "nome": nome, "raw": v})
    return out

def _pick_variable_id(vars_list: list[dict], keywords: list[str]) -> tuple[str | None, str]:
    """
    Retorna (id, motivo). Se não achar por keywords, retorna primeiro id válido como fallback.
    """
    # 1) tenta por nome
    for v in vars_list:
        nome = (v.get("nome") or "")
        nome_low = str(nome).lower()
        if any(k in nome_low for k in keywords):
            return str(v.get("id")), f"match por nome: {nome}"

    # 2) fallback: primeiro id válido
    for v in vars_list:
        if v.get("id") is not None and str(v.get("id")).strip() != "":
            return str(v.get("id")), "fallback: primeira variável disponível"
    return None, "nenhuma variável encontrada no metadado"



def _fetch_series_agregado(agregado: int, variavel: str, anos: list[int], cod_municipios: list[int]) -> pd.DataFrame:
    anos_str = ",".join(map(str, sorted(set(anos))))
    locs = ",".join(map(str, cod_municipios))
    url = f"{IBGE_AGREGADOS_BASE}/{agregado}/periodos/{anos_str}/variaveis/{variavel}?localidades=N6[{locs}]"
    js = _http_get_json(url)

    rows = []
    if isinstance(js, list) and js:
        obj = js[0]
        for res in obj.get("resultados", []):
            for serie in res.get("series", []):
                loc_id = serie.get("localidade", {}).get("id")
                serie_map = serie.get("serie", {}) or {}
                for ano, val in serie_map.items():
                    try:
                        vnum = float(str(val).replace(".", "").replace(",", "."))
                    except Exception:
                        vnum = np.nan
                    rows.append({"cod_ibge": str(loc_id), "ano": int(ano), "valor": vnum})

    return pd.DataFrame(rows)


@st.cache_data(show_spinner="📥 Carregando PIB e População do IBGE via API…", ttl=60*60, max_entries=64)
def carregar_bases_ibge_via_api(anos: list[int], municipios: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    # PIB total (Mil Reais)
    df_pib_total = _fetch_series_agregado(AGREG_PIB_MUN, PIB_TOTAL_VAR, anos, municipios).rename(
        columns={"valor": "pib_total_mil"}
    )

    # População estimada
    df_pop = _fetch_series_agregado(AGREG_POP, POP_VAR, anos, municipios).rename(
        columns={"valor": "pop"}
    )

    # ✅ calcula PIB per capita corretamente (R$)
    df = df_pib_total.merge(df_pop, on=["cod_ibge", "ano"], how="left")
    df["pib_pc"] = np.where(df["pop"] > 0, (df["pib_total_mil"] * 1000.0) / df["pop"], np.nan)

    # retorna só o que você precisa no app
    df_pib = df[["cod_ibge", "ano", "pib_pc", "pib_total_mil"]].copy()
    return df_pib, df_pop

# =========================================================
# SICONFI HELPERS
# =========================================================
@st.cache_data(show_spinner=False, ttl=60*30, max_entries=256)
def _get_json(url: str, timeout=HTTP_TIMEOUT) -> dict:
    r = HTTP.get(url, verify=False, timeout=timeout)
    r.raise_for_status()
    return r.json()

def safe_division(numerator, denominator):
    try:
        numerator = float(numerator)
        denominator = float(denominator)
    except Exception:
        return 0.0
    return numerator / denominator if denominator != 0 else 0.0


def _valor_ano_ou_ultimo(df: pd.DataFrame, valor_col: str, cod_ibge: str, ano: int):
    """
    Retorna (valor, ano_usado) de uma série IBGE para um município.

    Usa o valor do ano pedido; se ele estiver ausente, NaN ou <= 0 (ex.: PIB
    municipal ainda não divulgado para anos recentes), cai automaticamente para
    o ÚLTIMO ano que tenha um valor válido. Se não houver nenhum dado válido,
    retorna (NaN, None).
    """
    sub = df[df["cod_ibge"] == cod_ibge].copy()
    if sub.empty:
        return np.nan, None
    sub[valor_col] = pd.to_numeric(sub[valor_col], errors="coerce")
    sub = sub[sub[valor_col].notna() & (sub[valor_col] > 0)]
    if sub.empty:
        return np.nan, None
    exato = sub[sub["ano"] == int(ano)]
    if not exato.empty:
        return float(exato.iloc[-1][valor_col]), int(ano)
    sub = sub.sort_values("ano")
    return float(sub.iloc[-1][valor_col]), int(sub.iloc[-1]["ano"])


# =========================================================
# FUNÇÃO PRINCIPAL (SEU CÁLCULO) - AGORA USANDO df_pib/df_pop da API
# =========================================================
@st.cache_data(show_spinner="Buscando dados no SICONFI e calculando índices…", ttl=60*30, max_entries=128)
def calculate_municipal_indices(ano: int, selected_entes_ids: list[int], df_pib: pd.DataFrame, df_pop: pd.DataFrame):
    resultados = []
    meta_fontes = []   # registra qual ano IBGE (PIB/pop) foi usado por município
    meta_siconfi = []  # registra as extrações brutas do SICONFI/IBGE por município

    for ente in selected_entes_ids:
        try:
            link_rreo_1 = (
                f"https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?"
                f"an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2001&id_ente={ente}"
            )
            df_rreo_1 = pd.DataFrame(_get_json(link_rreo_1).get("items", []))
            time.sleep(0.05)

            link_rreo_2 = (
                f"https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?"
                f"an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2002&id_ente={ente}"
            )
            df_rreo_2 = pd.DataFrame(_get_json(link_rreo_2).get("items", []))
            time.sleep(0.05)

            link_rreo_3 = (
                f"https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?"
                f"an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2003&id_ente={ente}"
            )
            df_rreo_3 = pd.DataFrame(_get_json(link_rreo_3).get("items", []))
            time.sleep(0.05)

            link_dca_ab = (
                f"https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca?"
                f"an_exercicio={ano}&no_anexo=DCA-Anexo%20I-AB&id_ente={ente}"
            )
            df_dca_ab = pd.DataFrame(_get_json(link_dca_ab).get("items", []))
            time.sleep(0.05)

        except Exception as e:
            st.warning(f"Falha SICONFI para {ibge_to_nome.get(ente, ente)} em {ano}: {e}")
            continue

        def get_value_or_zero(df, query, column="valor"):
            if df.empty:
                return 0.0
            sub = df.query(query)
            if sub.empty:
                return 0.0
            return float(pd.to_numeric(sub[column], errors="coerce").fillna(0).sum())

        def get_value_str_or_zero(df, string_contains, query, column="valor"):
            if df.empty or "conta" not in df.columns:
                return 0.0
            mask = df["conta"].astype(str).str.contains(string_contains, na=False)
            sub = df.loc[mask].query(query)
            if sub.empty:
                return 0.0
            return float(pd.to_numeric(sub[column], errors="coerce").fillna(0).sum())

        # --------- IBGE (API) ----------
        # PIB e População do ano selecionado; se ausente/NaN/<=0, cai automaticamente
        # para o último ano com dado válido. O PIB municipal do IBGE é divulgado com
        # ~2-3 anos de defasagem, então em anos recentes esse fallback é o caso normal
        # (é o que garante que a linha A1 não fique vazia e suma da tabela).
        ente_str = str(ente)
        pib_pc, pib_ano_usado = _valor_ano_ou_ultimo(df_pib, "pib_pc", ente_str, ano)
        nro_habitantes, pop_ano_usado = _valor_ano_ou_ultimo(df_pop, "pop", ente_str, ano)

        # Registra, de forma transparente, qual ano de referência foi efetivamente usado
        meta_fontes.append({
            "Município": ibge_to_nome.get(ente, ente),
            "Ano selecionado": int(ano),
            "Ano PIB (IBGE)": pib_ano_usado,
            "Ano População (IBGE)": pop_ano_usado,
        })

        # --------- EXTRAÇÕES SICONFI ----------
        rec_total = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "TotalReceitas"')
        iptu = get_value_str_or_zero(df_rreo_3, "IPTU", 'coluna == "TOTAL (ÚLTIMOS 12 MESES)"')
        iss = get_value_str_or_zero(df_rreo_3, "ISS", 'coluna == "TOTAL (ÚLTIMOS 12 MESES)"')
        div_ativa = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.2.5.0.00.00" or cod_conta == "P1.2.1.1.1.04.00"')

        desp_total = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "TotalDespesas"')
        invest = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "Investimentos"')
        saude = get_value_or_zero(df_rreo_2, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)" & conta == "Saúde" & cod_conta == "RREO2TotalDespesas"')
        educ = get_value_or_zero(df_rreo_2, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)" & conta == "Educação" & cod_conta == "RREO2TotalDespesas"')
        legis = get_value_or_zero(df_rreo_2, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)" & conta == "Legislativa" & cod_conta == "RREO2TotalDespesas"')

        rec_trib = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "ReceitaTributaria"')
        transf_corr = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "TransferenciasCorrentes"')

        at_circ = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.0.0.0.00.00"')
        at_disp = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.1.0.0.00.00"')
        at_nc = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.2.0.0.0.00.00"')
        pass_circ = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.1.0.0.0.00.00"')
        pass_nc = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.2.0.0.0.00.00"')
        restit = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.1.8.8.0.00.00"')
        estoques = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.5.0.0.00.00"')
        ativo = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.0.0.0.0.00.00"')
        passivo = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.1.0.0.0.00.00" | cod_conta == "P2.2.0.0.0.00.00"')
        imobil = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.2.3.0.0.00.00"')
        invest_ativo = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.4.0.0.00.00"')
        pl = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.3.0.0.0.00.00"')

        desp_corr = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "DespesasCorrentes"')
        rec_corr = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "ReceitasCorrentes"')
        desp_cap = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "DespesasDeCapital"')
        rec_cap = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "ReceitasDeCapital"')
        pess_enc = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "PessoalEEncargosSociais"')

        rcl = get_value_or_zero(df_rreo_3, 'cod_conta == "RREO3ReceitaCorrenteLiquida" and coluna == "TOTAL (ÚLTIMOS 12 MESES)"')
        rec_prev = get_value_or_zero(df_rreo_1, 'coluna == "PREVISÃO ATUALIZADA (a)" & cod_conta == "TotalReceitas"')
        desp_fix = get_value_or_zero(df_rreo_1, 'coluna == "DOTAÇÃO INICIAL (d)" & cod_conta == "TotalDespesas"')
        op_cred = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "ReceitasDeOperacoesDeCredito"')
        juros = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "JurosEEncargosDaDivida"')

        # Registra as extrações brutas (auditoria/transparência) por município
        meta_siconfi.append({
            "Município": ibge_to_nome.get(ente, ente),
            "Receita Total": rec_total,
            "IPTU": iptu,
            "ISS": iss,
            "Dívida Ativa": div_ativa,
            "Despesa Total": desp_total,
            "Investimentos (despesa)": invest,
            "Saúde": saude,
            "Educação": educ,
            "Legislativo": legis,
            "Receita Tributária": rec_trib,
            "Transferências Correntes": transf_corr,
            "Ativo Circulante": at_circ,
            "Disponível (Caixa/Bancos)": at_disp,
            "Ativo Não Circulante": at_nc,
            "Passivo Circulante": pass_circ,
            "Passivo Não Circulante": pass_nc,
            "Restituições": restit,
            "Estoques": estoques,
            "Ativo Total": ativo,
            "Passivo Exigível": passivo,
            "Imobilizado": imobil,
            "Investimentos (ativo)": invest_ativo,
            "Patrimônio Líquido": pl,
            "Despesa Corrente": desp_corr,
            "Receita Corrente": rec_corr,
            "Despesa de Capital": desp_cap,
            "Receita de Capital": rec_cap,
            "Pessoal e Encargos": pess_enc,
            "RCL": rcl,
            "Receita Prevista": rec_prev,
            "Despesa Fixada": desp_fix,
            "Operações de Crédito": op_cred,
            "Juros e Encargos da Dívida": juros,
            "Habitantes (IBGE)": nro_habitantes,
            "PIB per capita (IBGE)": pib_pc,
        })

        # --------- INDICADORES ----------
        out = {
            "A1_PIB per Capita": pib_pc,
            "A2_Receita Total per Capita": safe_division(rec_total, nro_habitantes),
            "A3_IPTU per Capita": safe_division(iptu, nro_habitantes),
            "A4_ISS per Capita": safe_division(iss, nro_habitantes),
            "A5_Dívida Ativa per Capita": safe_division(div_ativa, nro_habitantes),

            "B1_Despesas Orçamentárias per Capita": safe_division(desp_total, nro_habitantes),
            "B2_Investimentos per Capita": safe_division(invest, nro_habitantes),
            "B3_Gastos com Saúde per Capita": safe_division(saude, nro_habitantes),
            "B4_Gastos com Educação per Capita": safe_division(educ, nro_habitantes),
            "B5_Transferências para o Legislativo per Capita": safe_division(legis, nro_habitantes),

            "C1_Receita Tributária per Capita": safe_division(rec_trib, nro_habitantes),
            "C2_Receita de Transferências per Capita": safe_division(transf_corr, nro_habitantes),

            "D1_Liquidez Instantânea ou Imediata": safe_division(at_disp, pass_circ),
            "D3_Liquidez com recursos de terceiros": safe_division(at_disp, restit),
            "D4_Liquidez Corrente": safe_division(at_circ, pass_circ),
            "E2_Liquidez Seca": safe_division(at_circ - estoques, pass_circ),
            "E3_Liquidez Geral": safe_division(at_circ + at_nc, pass_circ + pass_nc),

            "E6_Solvência Geral": safe_division(ativo, pass_circ + pass_nc),
            "F1_Endividamento Geral": safe_division(passivo, ativo) * 100,
            "F2_Composição das Exigibilidades": safe_division(pass_circ, passivo) * 100,
            "F3_Imobilização do Patrimônio Líquido ou Capital Próprio": safe_division(imobil + invest_ativo, pl) * 100,

            "F4_Grau de Comprometimento da Categoria Econômica Corrente": safe_division(desp_corr, rec_corr) * 100,
            "F5_Grau de Comprometimento da Categoria Econômica de Capital": safe_division(desp_cap, rec_cap) * 100,

            "G1_Grau de Gasto com Pessoal em relação a Despesa Orçamentária": safe_division(pess_enc, desp_corr) * 100,
            "G2_Grau de Investimento em relação a Despesa Orçamentária": safe_division(invest, desp_corr) * 100,
            "G3_Grau de Gasto com Pessoal em relação a Receita corrente Líquida": safe_division(pess_enc, rcl) * 100,
            "G4_Grau de Receitas Correntes Próprias ": safe_division(rec_corr - transf_corr, rec_corr) * 100,

            "H1_Grau de Execução Orçamentária da Receita": safe_division(rec_total, rec_prev) * 100,
            "H2_Grau de Execução Orçamentária da Despesa": safe_division(desp_total, desp_fix) * 100,
            "H3_Grau do Resultado da Execução Orçamentária": safe_division(desp_total, rec_total) * 100,
            "H4_Grau de Autonomia Orçamentária": safe_division(rec_corr - transf_corr, desp_total) * 100,
            "H5_Grau de Amortização e refinanciamento de dívida": safe_division(op_cred, desp_total) * 100,
            "H6_Grau de Encargos da dívida na despesa corrente": safe_division(juros, desp_total) * 100,
        }

        resultados.append({"Município": ente, **out})

    if not resultados:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    df_resultados = pd.DataFrame(resultados)
    df_resultados["Município"] = df_resultados["Município"].replace(ibge_to_nome)

    df_long = df_resultados.melt(id_vars=["Município"], var_name="Índice", value_name="Valor")
    # dropna=False garante que linhas como A1_PIB per Capita apareçam mesmo se,
    # excepcionalmente, não houver PIB disponível para nenhum município.
    tabela_final = df_long.pivot_table(index="Índice", columns="Município", values="Valor", aggfunc="first", dropna=False)

    tabela_final["Média"] = tabela_final.mean(axis=1)

    for municipio_col in [c for c in tabela_final.columns if c in ibge_to_nome.values()]:
        tabela_final[f"{municipio_col}_Variação (%)"] = ((tabela_final[municipio_col] - tabela_final["Média"]) / tabela_final["Média"]) * 100
        tabela_final[f"{municipio_col}_Variação (%)"] = tabela_final[f"{municipio_col}_Variação (%)"].fillna(0).replace([np.inf, -np.inf], 0)

        def classificar_variacao(v):
            va = abs(v)
            if va <= 10:
                return 1
            elif va <= 30:
                return 2
            else:
                return 3

        tabela_final[f"{municipio_col}_Classificação"] = tabela_final[f"{municipio_col}_Variação (%)"].apply(classificar_variacao)

    tabela_final["Interpretações"] = tabela_final.index.map(interpretacoes)
    tabela_final["Fórmulas"] = tabela_final.index.map(formulas)
    tabela_final["Ano"] = ano

    fontes_df = pd.DataFrame(meta_fontes)
    siconfi_df = pd.DataFrame(meta_siconfi)
    return tabela_final, fontes_df, siconfi_df


# =========================================================
# SÉRIE HISTÓRICA (um município: índices nas linhas, anos nas colunas)
# =========================================================
def build_historical_table(ente_id: int, nome: str, anos, df_pib: pd.DataFrame, df_pop: pd.DataFrame) -> pd.DataFrame:
    """Calcula os índices de um município para cada ano e monta uma tabela com os
    índices nas linhas e os anos nas colunas. Reaproveita as bases IBGE já carregadas
    (PIB/População) — o cálculo SICONFI é feito ano a ano (com cache)."""
    series_por_ano = {}
    for ano in anos:
        tab, _, _ = calculate_municipal_indices(int(ano), [ente_id], df_pib, df_pop)
        if not tab.empty and nome in tab.columns:
            # coluna como string ("2020"...) evita erro de formatação e ordena corretamente
            series_por_ano[str(int(ano))] = tab[nome]

    if not series_por_ano:
        return pd.DataFrame()

    hist = pd.DataFrame(series_por_ano)
    hist = hist[sorted(hist.columns)]
    hist.insert(0, "Interpretação", hist.index.map(interpretacoes))
    hist.insert(1, "Fórmula", hist.index.map(formulas))
    hist.index.name = "Índice"
    return hist


# =========================================================
# UI
# =========================================================
st.title("📊 Análise das Demonstrações Contábeis das 5 Maiores Cidades do RJ")
st.caption(
    "Aplicativo derivado do **Capítulo 6** do livro *Governança Pública: boas práticas para o gestor público* "
    "(Grande Editora, 2025) — versão **dinâmica e interativa** da metodologia de análise fiscal municipal."
)
st.markdown(
    "Esta ferramenta analisa indicadores fiscais, orçamentários e contábeis dos cinco maiores municípios "
    "do Estado do Rio de Janeiro, com dados oficiais do **SICONFI (Tesouro Nacional)** e bases "
    "socioeconômicas (PIB e População) do **IBGE/SIDRA**, ambos obtidos **ao vivo via API**."
)

st.info(
    "👥 **Autores do Capítulo 6:** Waldir Jorge Ladeira dos Santos · Yasmim da Costa Monteiro · "
    "Bruno Campos Pereira · Marcelo Jandussi Walther de Almeida"
)

with st.expander("📖 Sobre este aplicativo — base no Capítulo 6 do livro"):
    st.markdown(
        """
Este aplicativo é o **produto digital derivado do Capítulo 6** da obra:

> **SANTOS**, Waldir Jorge Ladeira dos; **MONTEIRO**, Yasmim da Costa; **PEREIRA**, Bruno Campos;
> **ALMEIDA**, Marcelo Jandussi Walther de. *Análise das Demonstrações Contábeis das cinco maiores
> cidades do Estado do Rio de Janeiro.* In: ROSSI, Gustavo Afonso Santi; SANTOS, Waldir Jorge
> Ladeira dos (org.). **Governança Pública: boas práticas para o gestor público**. Rio de Janeiro:
> Grande Editora, 2025. **cap. 6, p. 210–240**. ISBN 978-65-6125-029-0.

**O que muda em relação ao livro — de estático para dinâmico:**

| | 📕 Capítulo 6 (livro) | 💻 Este aplicativo |
|---|---|---|
| **Período** | Fixo — exercício de **2021** | **Qualquer ano** disponível (seleção dinâmica) |
| **PIB e População** | Planilha estática (IBGE, 2021) | **API do IBGE/SIDRA** (Agregados), ao vivo |
| **Dados fiscais/contábeis** | Extração pontual do SICONFI | **API do SICONFI** (RREO e DCA), ao vivo |
| **Cálculo dos índices** | Manual / planilha | **Automático e reprodutível** a cada execução |
| **Resultado** | Tabelas impressas no capítulo | Tabela interativa + **exportação para Excel** |

Os mesmos grupos de indicadores propostos no capítulo (receita e arrecadação, despesa e
aplicação de recursos, liquidez, estrutura de capitais e execução orçamentária) são aqui
recalculados de forma dinâmica, mantendo a fidelidade metodológica à pesquisa original.
"""
    )
    st.caption(
        "Cidades analisadas (IBGE): Rio de Janeiro, São Gonçalo, Duque de Caxias, "
        "Nova Iguaçu e Campos dos Goytacazes."
    )

# Carrega as bases do IBGE automaticamente (cacheadas) — sem etapa manual.
if not st.session_state.ibge_loaded:
    try:
        with st.spinner("📥 Carregando PIB e População do IBGE (Agregados/SIDRA)…"):
            _pib_df, _pop_df = carregar_bases_ibge_via_api(
                anos=available_years, municipios=list(ibge_to_nome.keys())
            )
        st.session_state.pib_df = _pib_df
        st.session_state.pop_df = _pop_df
        st.session_state.ibge_loaded = True
    except Exception as e:
        st.session_state.ibge_loaded = False
        st.warning(
            "⚠️ Não foi possível carregar as bases do IBGE agora "
            f"(os indicadores per capita podem ficar incompletos). Detalhe: {e}"
        )

# Status e recarga das bases num expander compacto (sem sidebar, preserva a largura da tabela)
with st.expander("⚙️ Bases de dados (IBGE) — status / recarregar"):
    if st.session_state.ibge_loaded and not st.session_state.pib_df.empty:
        anos_pib = sorted(st.session_state.pib_df["ano"].dropna().unique().tolist())
        st.caption("✅ PIB e População carregados — anos de PIB disponíveis: "
                   + ", ".join(str(int(a)) for a in anos_pib))
    else:
        st.caption("⚠️ Bases do IBGE indisponíveis no momento.")
    if st.button("🔄 Recarregar bases do IBGE"):
        carregar_bases_ibge_via_api.clear()
        st.session_state.ibge_loaded = False
        st.rerun()

# CSS para deixar as TABS grandes e bem visíveis (navegação principal)
st.markdown(
    """
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        border-bottom: 2px solid rgba(255,255,255,0.08);
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 1.05rem;
        font-weight: 700;
        padding: 12px 22px;
        border-radius: 10px 10px 0 0;
        background: rgba(255,255,255,0.04);
    }
    .stTabs [aria-selected="true"] {
        background: rgba(255, 75, 75, 0.18);
        color: #ff6b6b !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.subheader("Escolha a análise 👇")
tab_comp, tab_hist = st.tabs([
    "📊  Comparação entre os 5 municípios",
    "📈  Série histórica de um município",
])

# =========================================================
# TAB 1 — COMPARAÇÃO ENTRE OS 5 MUNICÍPIOS (metodologia do Capítulo 6)
# =========================================================
with tab_comp:
    # 1) PARÂMETROS
    st.subheader("1) Selecionar parâmetros")

    c1, c2 = st.columns([1, 3])
    with c1:
        selected_year = st.selectbox("Ano de análise", options=available_years, index=len(available_years) - 1)

    with c2:
        selected_municipios_names = st.multiselect("Municípios", options=all_municipios_names, default=all_municipios_names)

    selected_entes_ids = [nome_to_ibge[name] for name in selected_municipios_names]

    st.markdown("---")

    # 2) GERAR
    st.subheader("2) Gerar análise (SICONFI + IBGE)")

    gerar = st.button("⚙️ Gerar Análise", type="primary", use_container_width=True)

    if gerar:
        if not selected_entes_ids:
            st.warning("Selecione pelo menos um município para análise.")
        else:
            final_table, fontes_df, siconfi_df = calculate_municipal_indices(
                int(selected_year),
                selected_entes_ids,
                st.session_state.pib_df,
                st.session_state.pop_df
            )
            st.session_state.final_table = final_table
            st.session_state.fontes_table = fontes_df
            st.session_state.siconfi_table = siconfi_df
            st.session_state.siconfi_loaded = True

    # RESULTADOS
    if st.session_state.siconfi_loaded and not st.session_state.final_table.empty:
        st.markdown("---")
        st.success("✅ Análise de índices gerada com sucesso!")
        st.subheader(f"Resultados dos Índices para o Ano {selected_year}")

        # --- Transparência: anos de referência do IBGE efetivamente usados ---
        # O PIB municipal do IBGE é divulgado com defasagem; deixamos explícito qual
        # ano de PIB/população foi usado em cada município para o usuário ter clareza.
        fontes_df = st.session_state.fontes_table.copy()
        if not fontes_df.empty:
            ano_sel = int(selected_year)
            houve_fallback_pib = (fontes_df["Ano PIB (IBGE)"] != ano_sel).any()

            def _observacao(row):
                obs = []
                if pd.isna(row["Ano PIB (IBGE)"]):
                    obs.append("PIB: sem dado disponível")
                elif int(row["Ano PIB (IBGE)"]) != ano_sel:
                    obs.append(f"PIB: usou {int(row['Ano PIB (IBGE)'])} (último disponível)")
                if pd.isna(row["Ano População (IBGE)"]):
                    obs.append("População: sem dado disponível")
                elif int(row["Ano População (IBGE)"]) != ano_sel:
                    obs.append(f"População: usou {int(row['Ano População (IBGE)'])} (último disponível)")
                return " | ".join(obs) if obs else "Dados do próprio ano selecionado"

            fontes_df["Observação"] = fontes_df.apply(_observacao, axis=1)

            if houve_fallback_pib:
                st.info(
                    f"ℹ️ **A1_PIB per Capita** — O PIB municipal do IBGE é divulgado com "
                    f"defasagem e ainda não há valor para **{ano_sel}**. Nesses casos o app "
                    f"utiliza automaticamente o **último ano de PIB disponível** por município "
                    f"(detalhado abaixo). Os demais indicadores per capita usam a população "
                    f"estimada do IBGE para {ano_sel} (ou a mais recente disponível)."
                )

            with st.expander("🔎 Transparência — anos de referência dos dados do IBGE usados"):
                st.caption(
                    "Para cada município, qual ano de PIB e de população do IBGE foi "
                    "efetivamente usado no cálculo. Quando o dado do ano selecionado ainda "
                    "não foi divulgado, recorre-se ao último ano disponível."
                )
                st.dataframe(
                    fontes_df[["Município", "Ano selecionado", "Ano PIB (IBGE)",
                               "Ano População (IBGE)", "Observação"]],
                    use_container_width=True, hide_index=True
                )

        df_show = st.session_state.final_table.copy()

        municipios_cols = [c for c in df_show.columns if c in ibge_to_nome.values()]
        variacoes = [c for c in df_show.columns if "Variação (%)" in c]
        classes = [c for c in df_show.columns if "Classificação" in c]
        textos = [c for c in ["Interpretações", "Fórmulas"] if c in df_show.columns]

        ordem = []
        ordem += municipios_cols
        if "Média" in df_show.columns:
            ordem += ["Média"]
        ordem += variacoes + classes + textos
        if "Ano" in df_show.columns:
            ordem += ["Ano"]

        df_show = df_show[ordem]

        num_cols = df_show.select_dtypes(include="number").columns
        df_show[num_cols] = (
            df_show[num_cols]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )

        fmt = build_br_formatters(df_show)
        styler = style_table(df_show).format(fmt)

        st.dataframe(styler, use_container_width=True, height=650)

        excel_file = gerar_excel_download(st.session_state.final_table)
        st.download_button(
            label="📥 Exportar tabela para Excel",
            data=excel_file,
            file_name=f"Indicadores_Municipais_{selected_year}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

        st.divider()

        # --- Auditoria: extrações brutas do SICONFI/IBGE (insumos dos índices) ---
        siconfi_df = st.session_state.siconfi_table.copy()
        if not siconfi_df.empty:
            with st.expander("🧾 Ver extrações brutas do SICONFI/IBGE (insumos dos índices)"):
                st.caption(
                    "Valores em R$ extraídos diretamente do SICONFI (RREO e DCA) e do IBGE "
                    "(habitantes e PIB per capita), antes do cálculo dos índices per capita e dos "
                    "quocientes. Útil para auditoria e rastreabilidade do resultado."
                )
                # Métricas nas linhas, municípios nas colunas (espelha a tabela de índices)
                siconfi_t = siconfi_df.set_index("Município").T
                siconfi_t.index.name = "Métrica (SICONFI/IBGE)"
                fmt_siconfi = {col: fmt_br_num for col in siconfi_t.columns}
                st.dataframe(
                    siconfi_t.style.format(fmt_siconfi),
                    use_container_width=True, height=650
                )
                st.download_button(
                    label="📥 Exportar extrações brutas para Excel",
                    data=gerar_excel_download(siconfi_t),
                    file_name=f"Extracoes_SICONFI_IBGE_{selected_year}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

        st.divider()

        # --- Documentação: de onde cada métrica é extraída no SICONFI/IBGE ---
        with st.expander("📐 Ver fórmulas de extração no SICONFI/IBGE (relatório, coluna e conta)"):
            st.caption(
                "Mapeamento de cada métrica para sua origem: qual relatório/anexo, qual coluna e qual "
                "conta (cod_conta) são usados no filtro de extração. Ex.: a métrica **Juros e Encargos da "
                "Dívida** vem do RREO - Anexo 01, coluna *DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)*, "
                'cod_conta *JurosEEncargosDaDivida*.'
            )
            doc_df = pd.DataFrame(
                EXTRACOES_DOC,
                columns=["Métrica", "Relatório / Anexo", "Coluna (filtro)", "Conta / cod_conta (filtro)"]
            )
            st.dataframe(doc_df, use_container_width=True, hide_index=True, height=650)
            st.download_button(
                label="📥 Exportar mapa de extrações para Excel",
                data=gerar_excel_download(doc_df.set_index("Métrica")),
                file_name="Mapa_Extracoes_SICONFI_IBGE.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        st.markdown("---")
        st.subheader("Glossário e Classificação")
        st.markdown(r"""
**Variação (%):** Diferença percentual do índice do município em relação à média dos municípios selecionados.
**Classificação:**
* **1:** Variação absoluta $\le 10\%$ da média.
* **2:** Variação absoluta entre $10\%$ e $30\%$ da média.
* **3:** Variação absoluta $> 30\%$ da média.

> 📖 A classificação acima dialoga com a **metodologia de qualificação de perfis** proposta no
> Capítulo 6 do livro, que compara cada indicador à média (padrão) da amostra das cinco maiores
> cidades do RJ, atribuindo perfis em faixas de variação percentual.
""")
    else:
        st.info("ℹ️ Selecione ano e municípios e clique em **Gerar Análise**.")

# =========================================================
# TAB 2 — SÉRIE HISTÓRICA DE UM MUNICÍPIO
# =========================================================
with tab_hist:
    st.subheader("Série histórica de um município")
    st.caption(
        "Inspirada na evolução do Capítulo 6: escolha **um** dos cinco municípios e veja como cada "
        "índice evolui ao longo dos anos (índices nas linhas, anos nas colunas)."
    )

    col_h1, col_h2 = st.columns([2, 1])
    with col_h1:
        nome_hist = st.selectbox(
            "Município (5 maiores do RJ — Cap. 6)",
            options=all_municipios_names,
            key="hist_mun",
        )
    ente_hist = nome_to_ibge[nome_hist]

    st.caption(
        f"Cada ano consulta o SICONFI (4 chamadas); a primeira geração pode levar alguns segundos "
        f"(anos {available_years[0]}–{available_years[-1]})."
    )

    if st.button("📈 Gerar série histórica", type="primary", use_container_width=True, key="hist_btn"):
        st.session_state["hist_table"] = build_historical_table(
            ente_hist, nome_hist, available_years,
            st.session_state.pib_df, st.session_state.pop_df
        )
        st.session_state["hist_nome"] = nome_hist

    hist = st.session_state.get("hist_table", pd.DataFrame())
    if not hist.empty:
        st.success(f"✅ Série histórica — {st.session_state.get('hist_nome', '')}")

        hist_show = hist.copy()
        num_cols_h = hist_show.select_dtypes(include="number").columns
        hist_show[num_cols_h] = (
            hist_show[num_cols_h]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )
        fmt_h = build_br_formatters(hist_show)
        st.dataframe(style_table(hist_show).format(fmt_h), use_container_width=True, height=650)

        st.download_button(
            label="📥 Exportar série histórica para Excel",
            data=gerar_excel_download(hist),
            file_name=f"Indices_Serie_Historica_{st.session_state.get('hist_nome', 'ente')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="hist_dl",
        )
    else:
        st.info("ℹ️ Escolha o município e clique em **Gerar série histórica**.")

# =========================================================
# RODAPÉ — Créditos e referência ao livro
# =========================================================
st.markdown("---")
st.caption(
    "📚 **Referência:** SANTOS, W. J. L.; MONTEIRO, Y. C.; PEREIRA, B. C.; ALMEIDA, M. J. W. de. "
    "*Análise das Demonstrações Contábeis das cinco maiores cidades do Estado do Rio de Janeiro.* "
    "In: ROSSI, G. A. S.; SANTOS, W. J. L. (org.). **Governança Pública: boas práticas para o gestor público**. "
    "Rio de Janeiro: Grande Editora, 2025. cap. 6, p. 210–240. ISBN 978-65-6125-029-0."
)
st.caption(
    "Fontes de dados: SICONFI/Tesouro Nacional (RREO e DCA) e IBGE/SIDRA (PIB e População) — via API. "
    "Aplicativo de uso educacional e de apoio à gestão fiscal municipal."
)