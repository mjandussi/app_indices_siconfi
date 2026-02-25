import streamlit as st
import pandas as pd
import requests
import time
import numpy as np
from io import BytesIO

# =========================================================
# CONFIG STREAMLIT
# =========================================================
st.set_page_config(
    page_title="Análise de Índices Municipais",
    layout="wide",
    initial_sidebar_state="expanded"
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
    "A1_PIB per Capita": "PIB per capita (IBGE/SIDRA)",
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
# IBGE (AGREGADOS / SIDRA) - ROBUSTO
# =========================================================
IBGE_AGREGADOS_BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"

# ✅ Confirmados nos metadados do IBGE:
AGREG_PIB_MUN = 5938
PIB_TOTAL_VAR = "37"     # "Produto Interno Bruto a preços correntes" (Mil Reais)  :contentReference[oaicite:2]{index=2}

AGREG_POP     = 6579
POP_VAR       = "9324"   # "População residente estimada"                          :contentReference[oaicite:3]{index=3}


def _http_get_json(url: str, timeout: int = 25):
    r = requests.get(url, timeout=timeout)
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
def _get_json(url: str, timeout: int = 15) -> dict:
    r = requests.get(url, verify=False, timeout=timeout)
    r.raise_for_status()
    return r.json()

def safe_division(numerator, denominator):
    try:
        numerator = float(numerator)
        denominator = float(denominator)
    except Exception:
        return 0.0
    return numerator / denominator if denominator != 0 else 0.0


# =========================================================
# FUNÇÃO PRINCIPAL (SEU CÁLCULO) - AGORA USANDO df_pib/df_pop da API
# =========================================================
@st.cache_data(show_spinner="Buscando dados no SICONFI e calculando índices…", ttl=60*30, max_entries=128)
def calculate_municipal_indices(ano: int, selected_entes_ids: list[int], df_pib: pd.DataFrame, df_pop: pd.DataFrame):
    resultados = []

    for ente in selected_entes_ids:
        try:
            link_rreo_1 = (
                f"https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?"
                f"an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2001&id_ente={ente}"
            )
            df_rreo_1 = pd.DataFrame(_get_json(link_rreo_1, timeout=20).get("items", []))
            time.sleep(0.05)

            link_rreo_2 = (
                f"https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?"
                f"an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2002&id_ente={ente}"
            )
            df_rreo_2 = pd.DataFrame(_get_json(link_rreo_2, timeout=20).get("items", []))
            time.sleep(0.05)

            link_rreo_3 = (
                f"https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?"
                f"an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2003&id_ente={ente}"
            )
            df_rreo_3 = pd.DataFrame(_get_json(link_rreo_3, timeout=20).get("items", []))
            time.sleep(0.05)

            link_dca_ab = (
                f"https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca?"
                f"an_exercicio={ano}&no_anexo=DCA-Anexo%20I-AB&id_ente={ente}"
            )
            df_dca_ab = pd.DataFrame(_get_json(link_dca_ab, timeout=20).get("items", []))
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
        ente_str = str(ente)
        pop_row = df_pop[(df_pop["cod_ibge"] == ente_str) & (df_pop["ano"] == int(ano))]
        pib_row = df_pib[(df_pib["cod_ibge"] == ente_str) & (df_pib["ano"] == int(ano))]

        nro_habitantes = float(pop_row["pop"].sum()) if not pop_row.empty else 0.0
        pib_pc = float(pib_row["pib_pc"].sum()) if not pib_row.empty else 0.0

        #### FALL BACK (se não tiver dados de PIB ou População na API)

        # ✅ fallback POP: último ano disponível do município
        if nro_habitantes == 0.0:
            sub_pop = df_pop[df_pop["cod_ibge"] == ente_str].sort_values("ano")
            if not sub_pop.empty:
                nro_habitantes = float(sub_pop.iloc[-1]["pop"])
                pop_ano_usado = int(sub_pop.iloc[-1]["ano"])
            else:
                pop_ano_usado = int(ano)
        else:
            pop_ano_usado = int(ano)

        # ✅ fallback PIB: último ano disponível do município
        if pib_pc == 0.0:
            sub_pib = df_pib[df_pib["cod_ibge"] == ente_str].sort_values("ano")
            if not sub_pib.empty:
                pib_pc = float(sub_pib.iloc[-1]["pib_pc"])
                pib_ano_usado = int(sub_pib.iloc[-1]["ano"])
            else:
                pib_ano_usado = int(ano)
        else:
            pib_ano_usado = int(ano)

        # # Aviso (uma vez por município/ano)
        # if pib_ano_usado != int(ano):
        #     st.info(
        #         f"PIB per capita do IBGE não disponível para {ano} em {ibge_to_nome.get(ente, ente)}. "
        #         f"Usei o último ano disponível: {pib_ano_usado}."
        #     )

        # ✅ Se quiser padronizar (PIB e POP no mesmo ano do PIB):
        if pib_ano_usado != int(ano):
            pop_row_pib = df_pop[(df_pop["cod_ibge"] == ente_str) & (df_pop["ano"] == pib_ano_usado)]
            if not pop_row_pib.empty:
                nro_habitantes = float(pop_row_pib["pop"].sum())
                pop_ano_usado = pib_ano_usado

        # if nro_habitantes == 0.0:
        #     st.warning(f"Sem população IBGE para {ibge_to_nome.get(ente, ente)} (ano {ano}). Per capita pode zerar.")

        # # se pop não vier para o ano selecionado, tenta fallback: último ano disponível para aquele município
        # if nro_habitantes == 0.0:
        #     subm = df_pop[df_pop["cod_ibge"] == ente_str].sort_values("ano")
        #     if not subm.empty:
        #         nro_habitantes = float(subm.iloc[-1]["pop"])

        # if pib_pc == 0.0:
        #     subm = df_pib[df_pib["cod_ibge"] == ente_str].sort_values("ano")
        #     if not subm.empty:
        #         pib_pc = float(subm.iloc[-1]["pib_pc"])

        # if nro_habitantes == 0.0:
        #     st.warning(f"Sem população IBGE para {ibge_to_nome.get(ente, ente)} (ano {ano}). Indicadores per capita podem zerar.")

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
        return pd.DataFrame()

    df_resultados = pd.DataFrame(resultados)
    df_resultados["Município"] = df_resultados["Município"].replace(ibge_to_nome)

    df_long = df_resultados.melt(id_vars=["Município"], var_name="Índice", value_name="Valor")
    tabela_final = df_long.pivot_table(index="Índice", columns="Município", values="Valor", aggfunc="first")

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

    return tabela_final


# =========================================================
# UI
# =========================================================
st.title("📊 Análise dos Indicadores Fiscais, Orçamentários e Contábeis")
st.markdown(
    "Esta ferramenta analisa indicadores fiscais, orçamentários e contábeis dos municípios, "
    "com dados oficiais do **SICONFI (Tesouro Nacional)** e bases socioeconômicas do **IBGE/SIDRA via API**."
)
st.markdown("---")

# 1) IBGE
st.subheader("1) Carregar bases via API do IBGE (PIB per capita e População)")

col_a, col_b = st.columns([1, 2])
with col_a:
    carregar_ibge = st.button("📥 Carregar dados do IBGE", use_container_width=True)
with col_b:
    st.caption("Carrega automaticamente PIB per capita e população via API do IBGE (Agregados/SIDRA).")

if carregar_ibge:
    municipios = list(ibge_to_nome.keys())
    anos = available_years[:]
    try:
        pib_df, pop_df = carregar_bases_ibge_via_api(anos=anos, municipios=municipios)
        st.session_state.pib_df = pib_df
        st.session_state.pop_df = pop_df
        st.session_state.ibge_loaded = True
        st.success("✅ Bases do IBGE carregadas com sucesso!")
        st.write("Anos PIB disponíveis:", sorted(st.session_state.pib_df["ano"].unique().tolist()))
    except Exception as e:
        st.session_state.ibge_loaded = False
        st.error(f"❌ Falha ao carregar bases do IBGE: {e}")


if not st.session_state.ibge_loaded:
    st.warning("⚠️ Para continuar, clique em **Carregar dados do IBGE** acima.")
    # debug opcional quando falha:
    with st.expander("🔧 Diagnóstico (metadados IBGE)"):
        st.write("Se falhar, o motivo costuma ser o metadado/variável não bater com o texto esperado.")
        st.write("Dica: ajuste AGREG_PIB_MUN / AGREG_POP e/ou confirme a variável no metadado.")
    st.stop()

with st.expander("🔎 Ver metadados/variáveis detectadas (IBGE)"):
    st.json(st.session_state.ibge_debug)

st.markdown("---")

# 2) PARÂMETROS
st.subheader("2) Selecionar parâmetros")

c1, c2 = st.columns([1, 3])
with c1:
    selected_year = st.selectbox("Ano de análise", options=available_years, index=len(available_years) - 1)

with c2:
    selected_municipios_names = st.multiselect("Municípios", options=all_municipios_names, default=all_municipios_names)

selected_entes_ids = [nome_to_ibge[name] for name in selected_municipios_names]

st.markdown("---")

# 3) GERAR
st.subheader("3) Gerar análise (SICONFI + IBGE)")

gerar = st.button("⚙️ Gerar Análise", type="primary", use_container_width=True)

if gerar:
    if not selected_entes_ids:
        st.warning("Selecione pelo menos um município para análise.")
    else:
        final_table = calculate_municipal_indices(
            int(selected_year),
            selected_entes_ids,
            st.session_state.pib_df,
            st.session_state.pop_df
        )
        st.session_state.final_table = final_table
        st.session_state.siconfi_loaded = True

# RESULTADOS
if st.session_state.siconfi_loaded and not st.session_state.final_table.empty:
    st.markdown("---")
    st.success("✅ Análise de índices gerada com sucesso!")
    st.subheader(f"Resultados dos Índices para o Ano {selected_year}")

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

    st.markdown("---")
    st.subheader("Glossário e Classificação")
    st.markdown(r"""
**Variação (%):** Diferença percentual do índice do município em relação à média dos municípios selecionados.  
**Classificação:**
* **1:** Variação absoluta $\le 10\%$ da média.
* **2:** Variação absoluta entre $10\%$ e $30\%$ da média.
* **3:** Variação absoluta $> 30\%$ da média.
""")
else:
    st.info("ℹ️ Selecione ano e municípios e clique em **Gerar Análise**.")