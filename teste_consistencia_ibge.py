# teste_consistencia_ibge.py
# ------------------------------------------------------------
# Compara PIB/Pop de planilhas (Excel) vs API IBGE (Agregados/SIDRA)
# Foco: consistência e rastreabilidade (não exige cobertura total)
# ------------------------------------------------------------

import pandas as pd
import requests
import numpy as np
from pathlib import Path

# =========================
# CONFIG
# =========================
ANO_PIB = 2021                 # ano do PIB a comparar (planilha e API)
ANO_POP_PLANILHA = 2022        # seu arquivo POP_2022... (pode ajustar)
ANOS_API_PIB = [ANO_PIB]       # anos a puxar do PIB via API
ANOS_API_POP = [ANO_PIB]       # pop via API (use 2021 pra casar com PIB)
# Se quiser testar vários anos:
# ANOS_API_PIB = [2020, 2021, 2022, 2023]
# ANOS_API_POP = [2020, 2021, 2022, 2023, 2024]

MUNICIPIOS = [3304557, 3304904, 3301702, 3303500, 3301009]  # RJ, SG, DC, NI, Campos

# Seus arquivos locais
PIB_XLSX = Path("data") / "PIB dos Municípios - base de dados 2010-2021.xlsx"
POP_XLSX = Path("data") / "POP_2022_Municipios.xlsx"

# Agregados IBGE (os mesmos que você validou)
AGREGADO_PIB = 5938
VAR_PIB_TOTAL = 37      # "Produto Interno Bruto a preços correntes" (em R$ 1.000)
AGREGADO_POP = 6579
VAR_POP = 9324          # "População residente estimada"

TIMEOUT = 30


# =========================
# HELPERS
# =========================
def norm_col(c: str) -> str:
    """Normaliza nome de coluna pra evitar 'Ano' vs 'ano', espaços etc."""
    return (
        str(c)
        .strip()
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("  ", " ")
    )

def to_str_ibge(x) -> str:
    """Cod IBGE como string sem .0"""
    if pd.isna(x):
        return ""
    try:
        return str(int(float(x)))
    except Exception:
        return str(x).strip()

def safe_float(x):
    """Converte para float (aceita '1.234,56' e strings), senão NaN."""
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.number)):
        return float(x)
    s = str(x).strip()
    if s == "":
        return np.nan
    # tenta BR -> EN
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return np.nan

def ibge_agregados_fetch(agregado: int, variavel: int, anos: list[int], municipios: list[int]) -> pd.DataFrame:
    """
    Busca série no endpoint v3/agregados e retorna dataframe tidy:
    cod_ibge, ano, valor
    """
    anos_str = "|".join(str(a) for a in anos)
    mun_str = ",".join(str(m) for m in municipios)

    url = (
        f"https://servicodados.ibge.gov.br/api/v3/agregados/{agregado}"
        f"/periodos/{anos_str}/variaveis/{variavel}"
        f"?localidades=N6[{mun_str}]"
    )

    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()

    rows = []
    # Estrutura típica:
    # data[0]["resultados"][0]["series"] -> cada serie tem "localidade" e "serie" (dict ano->valor)
    for bloco in data:
        resultados = bloco.get("resultados", [])
        for res in resultados:
            series = res.get("series", [])
            for s in series:
                loc = s.get("localidade", {})
                cod = loc.get("id")
                serie = s.get("serie", {})
                for ano, val in serie.items():
                    rows.append({
                        "cod_ibge": str(cod),
                        "ano": int(ano),
                        "valor": safe_float(val),
                    })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.dropna(subset=["cod_ibge", "ano"])
    return df


# =========================
# LEITURA PLANILHAS
# =========================
def load_pib_excel(path: Path, ano: int, municipios: list[int]) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [norm_col(c) for c in df.columns]

    # tenta achar colunas esperadas (pelo seu layout original)
    # "Ano", "Código do Município", "Produto Interno Bruto, a preços correntes (R$ 1.000)", "Produto Interno Bruto per capita (R$ 1,00)"
    # Como os nomes têm quebras de linha, vamos localizar por contém.
    col_ano = next((c for c in df.columns if c.lower() == "ano"), None)
    if col_ano is None:
        # fallback por contém
        col_ano = next((c for c in df.columns if "ano" in c.lower()), None)

    col_cod = next((c for c in df.columns if "Código do Município" in c), None)
    if col_cod is None:
        col_cod = next((c for c in df.columns if "código do município" in c.lower()), None)

    col_pib_total = next((c for c in df.columns if "Produto Interno Bruto" in c and "R$ 1.000" in c), None)
    col_pib_pc = next((c for c in df.columns if "per capita" in c.lower() and "Produto Interno Bruto" in c), None)

    if not col_ano or not col_cod or not col_pib_total:
        raise ValueError(
            f"Não consegui identificar colunas do PIB na planilha.\n"
            f"Detectado: col_ano={col_ano}, col_cod={col_cod}, col_pib_total={col_pib_total}, col_pib_pc={col_pib_pc}\n"
            f"Colunas disponíveis: {list(df.columns)}"
        )

    df2 = df[[col_ano, col_cod, col_pib_total] + ([col_pib_pc] if col_pib_pc else [])].copy()
    df2 = df2.rename(columns={
        col_ano: "ano",
        col_cod: "cod_ibge",
        col_pib_total: "pib_total_mil_plan",
        **({col_pib_pc: "pib_pc_plan"} if col_pib_pc else {})
    })

    df2["cod_ibge"] = df2["cod_ibge"].apply(to_str_ibge)
    df2["ano"] = pd.to_numeric(df2["ano"], errors="coerce").astype("Int64")
    df2["pib_total_mil_plan"] = df2["pib_total_mil_plan"].apply(safe_float)
    if "pib_pc_plan" in df2.columns:
        df2["pib_pc_plan"] = df2["pib_pc_plan"].apply(safe_float)

    df2 = df2.dropna(subset=["cod_ibge", "ano"])
    df2 = df2[df2["ano"].astype(int) == int(ano)]
    df2 = df2[df2["cod_ibge"].isin([str(m) for m in municipios])]

    # PIB total na planilha vem em R$ 1.000, então o total em R$:
    df2["pib_total_rs_plan"] = df2["pib_total_mil_plan"] * 1000.0
    return df2.reset_index(drop=True)


def load_pop_excel(path: Path, ano_pop_planilha: int, municipios: list[int]) -> pd.DataFrame:
    # seu arquivo POP_2022 costuma ter header=1 e rodapé
    df = pd.read_excel(path, header=1, dtype=object)
    df.columns = [norm_col(c) for c in df.columns]

    # remove rodapé (você já fazia tail(35))
    if len(df) > 40:
        df = df.iloc[:-35].copy()

    # tenta detectar colunas
    col_uf = next((c for c in df.columns if c.strip().upper() in ["COD. UF", "COD.UF", "COD UF"]), None)
    col_mun = next((c for c in df.columns if c.strip().upper() in ["COD. MUNIC", "COD.MUNIC", "COD MUNIC"]), None)
    col_pop = next((c for c in df.columns if "POPULA" in c.upper()), None)

    if not col_uf or not col_mun or not col_pop:
        raise ValueError(
            f"Não consegui identificar colunas da POP na planilha.\n"
            f"Detectado: col_uf={col_uf}, col_mun={col_mun}, col_pop={col_pop}\n"
            f"Colunas disponíveis: {list(df.columns)}"
        )

    df2 = df[[col_uf, col_mun, col_pop]].copy()
    df2 = df2.rename(columns={col_uf: "cod_uf", col_mun: "cod_mun", col_pop: "pop_plan"})
    df2["cod_uf"] = df2["cod_uf"].apply(to_str_ibge).str.zfill(2)
    df2["cod_mun"] = df2["cod_mun"].apply(to_str_ibge).str.zfill(5)
    df2["cod_ibge"] = df2["cod_uf"] + df2["cod_mun"]

    df2["pop_plan"] = pd.to_numeric(df2["pop_plan"], errors="coerce")
    df2["ano"] = int(ano_pop_planilha)

    df2 = df2[df2["cod_ibge"].isin([str(m) for m in municipios])]
    return df2[["cod_ibge", "ano", "pop_plan"]].reset_index(drop=True)


# =========================
# MAIN
# =========================
def main():
    print("=== TESTE CONSISTÊNCIA IBGE: Planilha × API ===")
    print(f"Ano PIB: {ANO_PIB}")
    print(f"Ano Pop (planilha): {ANO_POP_PLANILHA}")
    print(f"Municípios: {MUNICIPIOS}")

    # --- lê planilhas
    df_pib_plan = load_pib_excel(PIB_XLSX, ANO_PIB, MUNICIPIOS)
    df_pop_plan = load_pop_excel(POP_XLSX, ANO_POP_PLANILHA, MUNICIPIOS)

    print("\n--- Planilha PIB (amostra) ---")
    print(df_pib_plan.head(10).to_string(index=False))

    print("\n--- Planilha POP (amostra) ---")
    print(df_pop_plan.head(10).to_string(index=False))

    # --- busca API
    df_pib_api = ibge_agregados_fetch(AGREGADO_PIB, VAR_PIB_TOTAL, ANOS_API_PIB, MUNICIPIOS)
    df_pop_api = ibge_agregados_fetch(AGREGADO_POP, VAR_POP, ANOS_API_POP, MUNICIPIOS)

    df_pib_api = df_pib_api.rename(columns={"valor": "pib_total_mil_api"})
    df_pop_api = df_pop_api.rename(columns={"valor": "pop_api"})

    # PIB api vem em R$ 1.000 também (para var=37 no agregado 5938), então:
    df_pib_api["pib_total_rs_api"] = df_pib_api["pib_total_mil_api"] * 1000.0

    # merge api pib+pop (mesmo ano)
    df_api = df_pib_api.merge(df_pop_api, on=["cod_ibge", "ano"], how="left")

    # calcula pib per capita baseado na API
    df_api["pib_pc_api_calc"] = df_api["pib_total_rs_api"] / df_api["pop_api"]

    print("\n--- API (amostra) ---")
    print(df_api.head(10).to_string(index=False))

    # =========================
    # CONSISTÊNCIA / COMPARAÇÃO
    # =========================
    # 1) comparação PIB do ano 2021 (planilha) vs PIB do ano 2021 (API)
    df_cmp = df_pib_plan.merge(
        df_api[["cod_ibge", "ano", "pib_total_mil_api", "pib_total_rs_api", "pib_pc_api_calc", "pop_api"]],
        on=["cod_ibge", "ano"],
        how="left"
    )

    # 2) opcional: trazer população da planilha (que pode ser 2022) só pra você enxergar a diferença
    # (merge só por cod_ibge, porque o ano é diferente)
    df_cmp = df_cmp.merge(
        df_pop_plan[["cod_ibge", "ano", "pop_plan"]],
        on=["cod_ibge"],
        how="left",
        suffixes=("", "_popplan")
    ).rename(columns={"ano_popplan": "ano_pop_plan"})

    # diffs PIB
    df_cmp["diff_pib_mil_plan_api"] = df_cmp["pib_total_mil_plan"] - df_cmp["pib_total_mil_api"]
    df_cmp["diff_pib_mil_pct"] = np.where(
        (df_cmp["pib_total_mil_api"].notna()) & (df_cmp["pib_total_mil_api"] != 0),
        (df_cmp["diff_pib_mil_plan_api"] / df_cmp["pib_total_mil_api"]) * 100.0,
        np.nan
    )

    # se planilha tiver PIB per capita, compara também
    if "pib_pc_plan" in df_cmp.columns:
        df_cmp["diff_pib_pc_plan_vs_api_calc"] = df_cmp["pib_pc_plan"] - df_cmp["pib_pc_api_calc"]
        df_cmp["diff_pib_pc_pct"] = np.where(
            (df_cmp["pib_pc_api_calc"].notna()) & (df_cmp["pib_pc_api_calc"] != 0),
            (df_cmp["diff_pib_pc_plan_vs_api_calc"] / df_cmp["pib_pc_api_calc"]) * 100.0,
            np.nan
        )

    # sanity checks
    print("\n--- Validações ---")
    print("Planilha PIB linhas:", len(df_pib_plan))
    print("API PIB linhas:", len(df_pib_api))
    print("API POP linhas:", len(df_pop_api))
    print("Comparação linhas:", len(df_cmp))
    print("NaNs pib_total_mil_api:", int(df_cmp["pib_total_mil_api"].isna().sum()))
    print("NaNs pop_api:", int(df_cmp["pop_api"].isna().sum()))

    print("\n--- Resumo Diferenças PIB (mil R$) ---")
    if df_cmp["diff_pib_mil_pct"].notna().any():
        print(df_cmp["diff_pib_mil_pct"].describe().to_string())
    else:
        print("Sem dados suficientes para percentuais (API vazia ou zeros).")

    # salva CSV para inspecionar
    out = Path("comparacao_ibge_planilha_vs_api.csv")
    df_cmp.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n✅ CSV gerado: {out.resolve()}")

    # imprime visão rápida
    cols_show = [
        "cod_ibge", "ano",
        "pib_total_mil_plan", "pib_total_mil_api", "diff_pib_mil_plan_api", "diff_pib_mil_pct"
    ]
    if "pib_pc_plan" in df_cmp.columns:
        cols_show += ["pib_pc_plan", "pib_pc_api_calc", "diff_pib_pc_plan_vs_api_calc", "diff_pib_pc_pct"]
    cols_show += ["pop_api", "pop_plan", "ano_pop_plan"]

    print("\n--- Amostra final (comparação) ---")
    print(df_cmp[cols_show].to_string(index=False))


if __name__ == "__main__":
    main()