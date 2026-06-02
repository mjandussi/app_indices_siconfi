"""
teste_ibge_api.py
Teste e validação de dados do IBGE/SIDRA (API v3 agregados)
- PIB municipal (agregado 5938, variável 37 = PIB total a preços correntes)
- População estimada (agregado 6579, variável 9324)
- Calcula PIB per capita = PIB / População
"""

from __future__ import annotations

import sys
import time
from typing import Dict, List, Tuple

import pandas as pd
import requests


# =========================
# CONFIG
# =========================
MUNICIPIOS: List[int] = [3304557, 3304904, 3301702, 3303500, 3301009]
ANOS: List[int] = [2020, 2021, 2022, 2023, 2024]  # ajuste aqui

AG_PIB = 5938
VAR_PIB_TOTAL = 37     # "Produto Interno Bruto a preços correntes" (PIB total)
AG_POP = 6579
VAR_POP = 9324         # "População residente estimada"

BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"


# =========================
# HTTP helpers
# =========================
def _get_json(url: str, timeout: int = 30, retries: int = 3, sleep_s: float = 0.8) -> dict | list:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(sleep_s * (i + 1))
    raise RuntimeError(f"Falha GET após {retries} tentativas: {url}\nErro: {last_err}")


def get_metadados(agregado: int) -> dict:
    url = f"{BASE}/{agregado}/metadados"
    return _get_json(url)


def build_url(agregado: int, variavel: int, anos: List[int], municipios: List[int]) -> str:
    # Formato da API v3 (agregados):
    # /agregados/{id}/periodos/{a1|a2|...}/variaveis/{var}?localidades=N6[mun1,mun2,...]
    anos_s = "|".join(map(str, anos))
    mun_s = ",".join(map(str, municipios))
    return f"{BASE}/{agregado}/periodos/{anos_s}/variaveis/{variavel}?localidades=N6[{mun_s}]"


# =========================
# Parse helpers
# =========================
def parse_sidra_agregado(data: list, value_col_name: str) -> pd.DataFrame:
    """
    Resposta típica:
    [
      {
        "id": "...",
        "variavel": "...",
        "unidade": "...",
        "resultados": [
          {
            "classificacoes": [...],
            "series": [
              {
                "localidade": {"id": "3304557", "nome": "...", ...},
                "serie": {"2020":"123", "2021":"456", ...}
              }, ...
            ]
          }
        ]
      }
    ]
    """
    if not isinstance(data, list) or len(data) == 0:
        return pd.DataFrame(columns=["cod_ibge", "ano", value_col_name])

    root = data[0]
    agregado_id = int(root.get("agregado", root.get("id", 0)) or 0)
    variavel_id = str(root.get("variavel", ""))

    resultados = root.get("resultados", [])
    if not resultados:
        return pd.DataFrame(columns=["cod_ibge", "ano", value_col_name, "agregado", "variavel"])

    series = resultados[0].get("series", [])
    rows = []
    for s in series:
        loc = s.get("localidade", {}) or {}
        cod_ibge = str(loc.get("id", "")).strip()
        serie = s.get("serie", {}) or {}

        for ano_str, val_str in serie.items():
            # Normaliza valor (vem como string)
            try:
                val = float(str(val_str).replace(".", "").replace(",", "."))
            except Exception:
                # muitos retornam "..." ou "-" quando não existe dado
                val = None

            rows.append(
                {
                    "cod_ibge": cod_ibge,
                    "ano": int(ano_str),
                    value_col_name: val,
                    "agregado": agregado_id,
                    "variavel": variavel_id,
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df[value_col_name] = pd.to_numeric(df[value_col_name], errors="coerce")
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").astype("Int64")
    df["cod_ibge"] = df["cod_ibge"].astype(str)
    return df.dropna(subset=["ano"]).astype({"ano": "int"})


# =========================
# Validations
# =========================
def validar_cobertura(df: pd.DataFrame, value_col: str, anos: List[int], municipios: List[int]) -> None:
    print("\n--- Validações ---")
    print(df.dtypes)
    dup = df.duplicated(subset=["cod_ibge", "ano"]).sum()
    print(f"Duplicados (cod_ibge, ano): {dup}")
    print(f"Valores NaN em {value_col}: {df[value_col].isna().sum()}")

    anos_presentes = sorted(df["ano"].unique().tolist())
    print(f"Anos presentes: {anos_presentes}")

    for m in municipios:
        m_str = str(m)
        anos_m = sorted(df.loc[df["cod_ibge"] == m_str, "ano"].unique().tolist())
        faltando = sorted(set(anos) - set(anos_m))
        if faltando:
            print(f"Município {m_str} faltando anos: {faltando}")


# =========================
# Main
# =========================
def main() -> int:
    print("=== TESTE IBGE (Agregados/SIDRA) ===")
    print(f"Municípios: {MUNICIPIOS}")
    print(f"Anos: {ANOS}")

    # Metadados PIB
    meta_pib = get_metadados(AG_PIB)
    print("\n--- Metadados (PIB) ---")
    print(f"Agregado: {meta_pib.get('id')} — {meta_pib.get('nome')}")
    print(f"Periodicidade: {meta_pib.get('periodicidade')}")
    print("Primeiras variáveis detectadas:")
    for v in (meta_pib.get("variaveis") or [])[:10]:
        print(f"  - {v.get('id')}: {v.get('nome')}")

    # Metadados POP
    meta_pop = get_metadados(AG_POP)
    print("\n--- Metadados (POP) ---")
    print(f"Agregado: {meta_pop.get('id')} — {meta_pop.get('nome')}")
    print(f"Periodicidade: {meta_pop.get('periodicidade')}")
    print("Variáveis:")
    for v in (meta_pop.get("variaveis") or [])[:10]:
        print(f"  - {v.get('id')}: {v.get('nome')}")

    # URLs
    url_pib = build_url(AG_PIB, VAR_PIB_TOTAL, ANOS, MUNICIPIOS)
    url_pop = build_url(AG_POP, VAR_POP, ANOS, MUNICIPIOS)

    print("\n--- URLs ---")
    print("PIB:", url_pib)
    print("POP:", url_pop)

    # Fetch
    data_pib = _get_json(url_pib)
    data_pop = _get_json(url_pop)

    # Parse
    df_pib = parse_sidra_agregado(data_pib, value_col_name="pib_total")
    df_pop = parse_sidra_agregado(data_pop, value_col_name="pop")

    print("\n=== PIB total (amostra) ===")
    print(df_pib.head(10))

    validar_cobertura(df_pib, "pib_total", ANOS, MUNICIPIOS)

    print("\n=== População (amostra) ===")
    print(df_pop.head(10))

    validar_cobertura(df_pop, "pop", ANOS, MUNICIPIOS)

    # Merge & PIB per capita
    df_merge = df_pop.merge(df_pib, on=["cod_ibge", "ano"], how="outer", indicator=True)
    df_merge["pib_per_capita_calc"] = df_merge["pib_total"] / df_merge["pop"]

    print("\n=== Cobertura conjunta (pop x pib_total) ===")
    print(df_merge["_merge"].value_counts())

    # Export CSVs
    df_pib.to_csv("ibge_pib_total.csv", index=False, encoding="utf-8")
    df_pop.to_csv("ibge_pop.csv", index=False, encoding="utf-8")
    df_merge.to_csv("ibge_pop_pib_merge.csv", index=False, encoding="utf-8")

    print("\n✅ CSVs gerados:")
    print(" - ibge_pib_total.csv")
    print(" - ibge_pop.csv")
    print(" - ibge_pop_pib_merge.csv")
    print("\nObs: pib_per_capita_calc é calculado (PIB total / População).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# python teste_ibge_api.py