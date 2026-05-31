# teste_ibge_api.py
# ---------------------------------------------------------
# Script simples para testar/validar dados IBGE (Agregados/SIDRA):
# - Lista variáveis disponíveis (metadados)
# - Tenta detectar PIB per capita e População por keywords
# - Baixa série por municípios e anos
# - Valida (faltantes, duplicados, tipos)
# - Opcional: salva CSV
# ---------------------------------------------------------

from __future__ import annotations

import sys
import json
import math
import pandas as pd
import requests
import numpy as np

IBGE_AGREGADOS_BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"

# ---- Ajuste aqui se necessário ----
AGREG_PIB_MUN = 5938  # PIB dos Municípios (típico)
AGREG_POP = 6579      # População (pode variar)
# ----------------------------------

KEYWORDS_PIB_PC = ["per capita", "pib per capita", "produto interno bruto per capita"]
KEYWORDS_POP = ["população", "populacao", "população residente", "população estimada"]

# Municípios (RJ 5 maiores do seu app)
MUNICIPIOS = [3304557, 3304904, 3301702, 3303500, 3301009]
ANOS = [2020, 2021, 2022, 2023, 2024]


def http_get_json(url: str, timeout: int = 30) -> dict | list:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def extract_variables_from_metadados(meta: dict | list) -> list[dict]:
    candidates = []

    if isinstance(meta, dict):
        for k in ["variaveis", "variáveis", "variavel", "variável", "variables"]:
            if k in meta and isinstance(meta[k], list):
                candidates = meta[k]
                break

        if not candidates:
            for k, v in meta.items():
                if isinstance(v, dict):
                    for kk in ["variaveis", "variáveis"]:
                        if kk in v and isinstance(v[kk], list):
                            candidates = v[kk]
                            break
                if candidates:
                    break

    if not candidates and isinstance(meta, list):
        for item in meta:
            if isinstance(item, dict) and "variaveis" in item and isinstance(item["variaveis"], list):
                candidates = item["variaveis"]
                break

    out = []
    for v in candidates or []:
        if not isinstance(v, dict):
            continue
        vid = v.get("id") or v.get("ID") or v.get("codigo") or v.get("código")
        nome = v.get("nome") or v.get("variavel") or v.get("variável") or v.get("descricao") or v.get("descrição")
        out.append({"id": str(vid) if vid is not None else None, "nome": str(nome) if nome is not None else ""})
    return out


def pick_variable_id(vars_list: list[dict], keywords: list[str]) -> tuple[str | None, str]:
    for v in vars_list:
        nome_low = (v.get("nome") or "").lower()
        if any(k in nome_low for k in keywords):
            return v["id"], f"match por nome: {v.get('nome')}"
    for v in vars_list:
        if v.get("id"):
            return v["id"], "fallback: primeira variável disponível"
    return None, "nenhuma variável encontrada"


def fetch_series_agregado(agregado: int, variavel: str, anos: list[int], cod_municipios: list[int]) -> pd.DataFrame:
    anos_str = ",".join(map(str, sorted(set(anos))))
    locs = ",".join(map(str, cod_municipios))
    url = f"{IBGE_AGREGADOS_BASE}/{agregado}/periodos/{anos_str}/variaveis/{variavel}?localidades=N6[{locs}]"
    js = http_get_json(url)

    rows = []
    if isinstance(js, list) and js:
        obj = js[0]
        resultados = obj.get("resultados", [])
        for res in resultados:
            for serie in res.get("series", []):
                loc_id = serie.get("localidade", {}).get("id")
                serie_map = serie.get("serie", {})
                for ano, val in (serie_map or {}).items():
                    # tenta converter valor
                    vnum = np.nan
                    try:
                        # alguns retornos vêm como string
                        vnum = float(str(val).replace(".", "").replace(",", "."))
                    except Exception:
                        try:
                            vnum = float(val)
                        except Exception:
                            vnum = np.nan
                    rows.append({"cod_ibge": str(loc_id), "ano": int(ano), "valor": vnum})

    df = pd.DataFrame(rows)
    df["agregado"] = agregado
    df["variavel"] = variavel
    return df


def validate_df(df: pd.DataFrame, value_col: str) -> None:
    print("\n--- Validações ---")
    if df.empty:
        print("DataFrame vazio.")
        return

    # tipos
    print(df.dtypes)

    # duplicados por cod+ano
    dup = df.duplicated(subset=["cod_ibge", "ano"]).sum()
    print(f"Duplicados (cod_ibge, ano): {dup}")

    # faltantes
    missing = df[value_col].isna().sum()
    print(f"Valores NaN em {value_col}: {missing}")

    # anos faltantes por município
    anos = sorted(df["ano"].unique().tolist())
    print(f"Anos presentes: {anos}")

    for cod in sorted(df["cod_ibge"].unique().tolist()):
        sub = df[df["cod_ibge"] == cod]
        falt = sorted(set(ANOS) - set(sub["ano"].tolist()))
        if falt:
            print(f"Município {cod} faltando anos: {falt}")

    # estatísticas rápidas
    desc = df[value_col].describe()
    print("\nResumo numérico:")
    print(desc)


def main() -> int:
    print("=== TESTE IBGE (Agregados/SIDRA) ===")
    print(f"Municípios: {MUNICIPIOS}")
    print(f"Anos: {ANOS}")

    # 1) Metadados PIB
    pib_meta_url = f"{IBGE_AGREGADOS_BASE}/{AGREG_PIB_MUN}/metadados"
    pop_meta_url = f"{IBGE_AGREGADOS_BASE}/{AGREG_POP}/metadados"

    try:
        pib_meta = http_get_json(pib_meta_url)
        pop_meta = http_get_json(pop_meta_url)
    except Exception as e:
        print(f"Erro ao baixar metadados: {e}")
        return 1

    pib_vars = extract_variables_from_metadados(pib_meta)
    pop_vars = extract_variables_from_metadados(pop_meta)

    pib_var_id, pib_reason = pick_variable_id(pib_vars, KEYWORDS_PIB_PC)
    pop_var_id, pop_reason = pick_variable_id(pop_vars, KEYWORDS_POP)

    print("\n--- Metadados / Variáveis (PIB) ---")
    print(f"URL: {pib_meta_url}")
    print(f"Variável escolhida: {pib_var_id} ({pib_reason})")
    print("Primeiras variáveis detectadas:")
    for v in pib_vars[:20]:
        print(f"  - {v['id']}: {v['nome']}")

    print("\n--- Metadados / Variáveis (POP) ---")
    print(f"URL: {pop_meta_url}")
    print(f"Variável escolhida: {pop_var_id} ({pop_reason})")
    print("Primeiras variáveis detectadas:")
    for v in pop_vars[:20]:
        print(f"  - {v['id']}: {v['nome']}")

    if not pib_var_id or not pop_var_id:
        print("\n❌ Não foi possível identificar variáveis. Ajuste AGREG_PIB_MUN / AGREG_POP.")
        return 2

    # 2) Baixar séries
    try:
        df_pib = fetch_series_agregado(AGREG_PIB_MUN, pib_var_id, ANOS, MUNICIPIOS).rename(columns={"valor": "pib_pc"})
        df_pop = fetch_series_agregado(AGREG_POP, pop_var_id, ANOS, MUNICIPIOS).rename(columns={"valor": "pop"})
    except Exception as e:
        print(f"\nErro ao baixar séries: {e}")
        return 3

    print("\n=== PIB per capita (amostra) ===")
    print(df_pib.head(10))
    validate_df(df_pib, "pib_pc")

    print("\n=== População (amostra) ===")
    print(df_pop.head(10))
    validate_df(df_pop, "pop")

    # 3) Merge para checar cobertura conjunta
    df_merge = pd.merge(
        df_pop[["cod_ibge", "ano", "pop"]],
        df_pib[["cod_ibge", "ano", "pib_pc"]],
        on=["cod_ibge", "ano"],
        how="outer",
        indicator=True
    )
    print("\n=== Cobertura conjunta (pop x pib_pc) ===")
    print(df_merge["_merge"].value_counts(dropna=False))

    # 4) Salvar CSV (opcional)
    df_pib.to_csv("ibge_pib_pc.csv", index=False, encoding="utf-8")
    df_pop.to_csv("ibge_pop.csv", index=False, encoding="utf-8")
    df_merge.to_csv("ibge_pop_pib_merge.csv", index=False, encoding="utf-8")
    print("\n✅ CSVs gerados:")
    print(" - ibge_pib_pc.csv")
    print(" - ibge_pop.csv")
    print(" - ibge_pop_pib_merge.csv")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# python teste_ibge_api.py