import streamlit as st
import pandas as pd
import requests
import time
import os

# --- Configurações da Página Streamlit ---
st.set_page_config(
    page_title="Análise de Índices Municipais",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Inicialização do estado da sessão para controlar o fluxo do app ---
if 'pib_pop_loaded' not in st.session_state:
    st.session_state.pib_pop_loaded = False
if 'siconfi_loaded' not in st.session_state:
    st.session_state.siconfi_loaded = False
if 'final_table' not in st.session_state:
    st.session_state.final_table = pd.DataFrame()
if 'pib_data' not in st.session_state:
    st.session_state.pib_data = pd.DataFrame()
if 'pop_data' not in st.session_state:
    st.session_state.pop_data = pd.DataFrame()

# --- Funções para Carregamento de Dados (com cache) ---
@st.cache_data
def load_pib_data(file_path):
    """Carrega e pré-processa os dados de PIB."""
    try:
        df_pib = pd.read_excel(file_path)
        colunas_desejadas = [
            'Ano', 'Sigla da Unidade da Federação', 'Código do Município', 'Nome do Município',
            'Produto Interno Bruto, \na preços correntes\n(R$ 1.000)',
            'Produto Interno Bruto per capita, \na preços correntes\n(R$ 1,00)'
        ]
        return df_pib[colunas_desejadas]
    except FileNotFoundError:
        st.error(f"Erro: Arquivo '{file_path}' não encontrado. Por favor, verifique o caminho.")
        return pd.DataFrame()

@st.cache_data
def load_pop_data(file_path):
    """Carrega e pré-processa os dados de População."""
    try:
        populacao = pd.read_excel(file_path, header=1, dtype=object)
        populacao.drop(populacao.tail(35).index, inplace=True)
        populacao['POPULAÇÃO'] = pd.to_numeric(populacao['POPULAÇÃO'], errors='coerce')
        populacao['COD. UF'] = populacao['COD. UF'].astype(str)
        populacao['COD. MUNIC'] = populacao['COD. MUNIC'].astype(str)
        populacao['cod_ibge'] = populacao['COD. UF'] + populacao['COD. MUNIC']
        return populacao
    except FileNotFoundError:
        st.error(f"Erro: Arquivo '{file_path}' não encontrado. Por favor, verifique o caminho.")
        return pd.DataFrame()

# --- Mapeamentos e Dicionários para Análise ---
ibge_to_nome = {
    3304557: "1_Rio de Janeiro", 3304904: "2_São Gonçalo", 3301702: "3_Duque de Caxias",
    3303500: "4_Nova Iguaçu", 3301009: "5_Campos dos Goytacazes"
}
nome_to_ibge = {v: k for k, v in ibge_to_nome.items()}
all_municipios_names = list(ibge_to_nome.values())
available_years = list(range(2010, 2022))

interpretacoes = {
    "A1_PIB per Capita": "Renda média por habitante", "A2_Receita Total per Capita": "Arrecadação por habitante",
    "A3_IPTU per Capita": "Arrecadação de IPTU por habitante", "A4_ISS per Capita": "Arrecadação de ISS por habitante",
    "A5_Dívida Ativa per Capita": "Valor em Dívida Ativa por habitante", "B1_Despesas Orçamentárias per Capita": "Quanto representa a Despesa por habitantes?",
    "B2_Investimentos per Capita": "Quanto representa o investimento por habitantes?", "B3_Gastos com Saúde per Capita": "Quanto representa o gasto com Saúde por pessoa?",
    "B4_Gastos com Educação per Capita": "Quanto representa o gasto com Educação por pessoa?", "B5_Transferências para o Legislativo per Capita": "Quanto representa o gasto com Legislativo por habitante?",
    "C1_Receita Tributária per Capita": "Quanto representa a Receita Tributária por habitante?", "C2_Receita de Transferências per Capita": "Quanto representa a Receita de Transferências por habitante?",
    "D1_Liquidez Instantânea ou Imediata": "Hoje consegue pagar suas dívidas de um ano?", "D3_Liquidez com recursos de terceiros": "Hoje consegue pagar os recursos de terceiros? ",
    "D4_Liquidez Corrente": "Durante um ano consegue pagar suas dívidas?", "E2_Liquidez Seca": "Sem Estoque consegue pagar suas dívidas de um ano?",
    "E3_Liquidez Geral": "No futuro conseguirá pagar suas dívidas?", "E6_Solvência Geral": "No geral conseguirá pagar suas Dívidas?",
    "F1_Endividamento Geral": "Quanto do Ativo está Endividado?", "F2_Composição das Exigibilidades": "Quanto representa o PC do total da Dívida?",
    "F3_Imobilização do Patrimônio Líquido ou Capital Próprio": "Quanto os Ativos Investimento e Imobilizado usaram do Patrimônio Líquido?",
    "F4_Grau de Comprometimento da Categoria Econômica Corrente": "Quanto a Despesa Corrente utilizou da Receita Corrente?",
    "F5_Grau de Comprometimento da Categoria Econômica de Capital": "Quanto a Despesa de Capital utilizou da Receita de Capital?",
    "G1_Grau de Gasto com Pessoal em relação a Despesa Orçamentária": "Quanto representou o Gasto com Pessoal em relação a Despesa Orçamentária?",
    "G2_Grau de Investimento em relação a Despesa Orçamentária": "Quanto representou o Investimento em relação a Despesa Orçamentária?",
    "G3_Grau de Gasto com Pessoal em relação a Receita corrente Líquida": "Quanto representou o Gasto com Pessoal em relação Receita corrente Líquida?",
    "G4_Grau de Receitas Correntes Próprias ": "Qual o Grau de independência das Receitas Correntes? ",
    "H1_Grau de Execução Orçamentária da Receita": "Quanto da Receita foi Executada?", "H2_Grau de Execução Orçamentária da Despesa": "Quanto da Despesa foi Executada?",
    "H3_Grau do Resultado da Execução Orçamentária": "Qual o grau do resultado da execução orçamentária?",
    "H4_Grau de Autonomia Orçamentária": "Quanto representa a receita própria em relação a despesa executada",
    "H5_Grau de Amortização e refinanciamento de dívida": "Quanto representam as operações de crédito em relação a despesa executada",
    "H6_Grau de Encargos da dívida na despesa corrente": "Quanto representa a despesa financeira da despesa orçamentária",
}

formulas = {
    "A1_PIB per Capita": "PIB Total/ Nr Habitantes", "A2_Receita Total per Capita": "Receita Arrecadada / Nr Habitantes",
    "A3_IPTU per Capita": "IPTU / Nr Habitantes", "A4_ISS per Capita": "ISS / Nr Habitantes",
    "A5_Dívida Ativa per Capita": "Dívida Ativa / Nr Habitante", "B1_Despesas Orçamentárias per Capita": "Despesa Executada / Nr Habitantes",
    "B2_Investimentos per Capita": "Investimentos / Nr Habitantes", "B3_Gastos com Saúde per Capita": "Despesas com Saúde / Nr Habitantes",
    "B4_Gastos com Educação per Capita": "Despesas com Educação / Nr Habitantes", "B5_Transferências para o Legislativo per Capita": "Transferência para o Legislativo / Nr de Habitantes",
    "C1_Receita Tributária per Capita": "Receita Tributária / Nr de Habitantes", "C2_Receita de Transferências per Capita": "Receita de Transferências / Nr de Habitantes",
    "D1_Liquidez Instantânea ou Imediata": "Ativo Circulante Disponível / Passivo Circulante", "D3_Liquidez com recursos de terceiros": "Ativo Circulante Disponibilidade / Depósitos de Diversas Origens",
    "D4_Liquidez Corrente": "Ativo Circulante / Passivo Circulante", "E2_Liquidez Seca": "(Ativo circulante – Estoques) / Passivo Circulante",
    "E3_Liquidez Geral": "(Ativo Circulante + Ativo Não Circulante Direitos) / (Passivo Circulante + Passivo Não Circulante)",
    "E6_Solvência Geral": "Ativo Total / Passivo Exigível", "F1_Endividamento Geral": "(Passivo Exigível / Ativo Total) x 100",
    "F2_Composição das Exigibilidades": "(Passivo Circulante / Passivo Exigível) x 100", "F3_Imobilização do Patrimônio Líquido ou Capital Próprio": "((Ativos Investimento + Imobilizado) / Patrimônio Líquido) x 100",
    "F4_Grau de Comprometimento da Categoria Econômica Corrente": "(Despesas Correntes / Receitas Correntes) x 100",
    "F5_Grau de Comprometimento da Categoria Econômica de Capital": "(Despesas de Capital / Receitas de Capital) x 100",
    "G1_Grau de Gasto com Pessoal em relação a Despesa Orçamentária": "(Pessoal Ativo e Encargos / Despesas Orçamentárias) x 100",
    "G2_Grau de Investimento em relação a Despesa Orçamentária": "(Investimentos / Despesas Orçamentária) x 100",
    "G3_Grau de Gasto com Pessoal em relação a Receita corrente Líquida": "(Pessoal Ativo e Encargos / Receita corrente Líquida) x 100",
    "G4_Grau de Receitas Correntes Próprias ": "((Receitas Correntes – Transferências) / Receitas Correntes) x 100",
    "H1_Grau de Execução Orçamentária da Receita": "(Receita Executada / Receita Prevista) x 100", "H2_Grau de Execução Orçamentária da Despesa": "(Despesa Executada / Despesa Fixada) x 100",
    "H3_Grau do Resultado da Execução Orçamentária": "(Despesa Executada / Receita Executada) x 100", "H4_Grau de Autonomia Orçamentária": "((Receitas Correntes – Transferências) / despesas totais) x 100",
    "H5_Grau de Amortização e refinanciamento de dívida": "(Operações de Crédito / despesas totais) x 100",
    "H6_Grau de Encargos da dívida na despesa corrente": "(Juros e encargos da dívida / Despesas Executadas) x 100",
}


# --- Função Principal para Calcular Índices (com cache) ---
@st.cache_data(show_spinner="Buscando dados no SICONFI e calculando índices...")
def calculate_municipal_indices(ano, selected_entes_ids, df_ibge_data, populacao_data):
    """
    Realiza a busca de dados na API do SICONFI, calcula os índices
    e retorna o DataFrame final.
    """
    resultados = []
    
    for ente in selected_entes_ids:
        try:
            # --- Importando os Anexos do RREO (6o Bimestre) ---
            link_rreo_1 = f'https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2001&id_ente={ente}'
            df_rreo_1 = pd.DataFrame(requests.get(link_rreo_1, verify=False, timeout=10).json()["items"])
            time.sleep(0.1)
            link_rreo_2 = f'https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2002&id_ente={ente}'
            df_rreo_2 = pd.DataFrame(requests.get(link_rreo_2, verify=False, timeout=10).json()["items"])
            time.sleep(0.1)
            link_rreo_3 = f'https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?an_exercicio={ano}&nr_periodo=6&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2003&id_ente={ente}'
            df_rreo_3 = pd.DataFrame(requests.get(link_rreo_3, verify=False, timeout=10).json()["items"])
            time.sleep(0.1)
            # --- Importando os Anexos da DCA ---
            link_dca_ab = f'https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca?an_exercicio={ano}&no_anexo=DCA-Anexo%20I-AB&id_ente={ente}'
            df_dca_ab = pd.DataFrame(requests.get(link_dca_ab, verify=False, timeout=10).json()["items"])
            time.sleep(0.1)
        except (requests.exceptions.RequestException, KeyError) as e:
            st.warning(f"Não foi possível obter dados para o município {ibge_to_nome.get(ente, ente)} no ano {ano}. Pulando este município. Erro: {e}")
            continue

        def get_value_or_zero(df, query, column='valor'):
            if df.empty: return 0
            filtered_df = df.query(query)
            return filtered_df[column].sum() if not filtered_df.empty else 0

        def get_value_str_or_zero(df, string_contains, query, column='valor'):
            if df.empty: return 0
            filtered_df = df[df["conta"].str.contains(string_contains, na=False)].query(query)
            return filtered_df[column].sum() if not filtered_df.empty else 0

        # --- Filtrar dados do PIB e População para o ente e ano atuais ---
        pib_munic = df_ibge_data.query(f'`Código do Município` == {ente} and Ano == {ano}')
        nro_habitantes_df = populacao_data.query(f'cod_ibge == "{ente}"')

        # --- Extrair valores, tratando casos onde o DataFrame pode estar vazio ---
        def get_value(df, column):
            return df[column].sum() if not df.empty else 0

        nro_habitantes = get_value(nro_habitantes_df, 'POPULAÇÃO')
        pib_munic_valor = get_value(pib_munic, 'Produto Interno Bruto per capita, \na preços correntes\n(R$ 1,00)')
        
        if nro_habitantes == 0 and pib_munic_valor == 0:
            st.warning(f"Não foi possível obter dados de população ou PIB para o município {ibge_to_nome.get(ente, ente)} no ano {ano}. Pulando este município.")
            continue

        # Extração de valores (com base na sua lógica original)
        rec_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "TotalReceitas"')
        iptu_rreo_3 = get_value_str_or_zero(df_rreo_3, "IPTU", 'coluna == "TOTAL (ÚLTIMOS 12 MESES)"')
        iss_rreo_3 = get_value_str_or_zero(df_rreo_3, "ISS", 'coluna == "TOTAL (ÚLTIMOS 12 MESES)"')
        div_ativa_trib_dca_ab = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.2.5.0.00.00" or cod_conta == "P1.2.1.1.1.04.00"')
        despesa_total = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "TotalDespesas"')
        despesa_investimentos = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "Investimentos"')
        despesa_saude = get_value_or_zero(df_rreo_2, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)" & conta == "Saúde" & cod_conta == "RREO2TotalDespesas"')
        despesa_educacao = get_value_or_zero(df_rreo_2, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)" & conta == "Educação" & cod_conta == "RREO2TotalDespesas"')
        legislativo_rreo_2 = get_value_or_zero(df_rreo_2, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)" & conta == "Legislativa" & cod_conta == "RREO2TotalDespesas"')
        rec_trib_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "ReceitaTributaria"')
        tranf_corr_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "TransferenciasCorrentes"')
        at_circ = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.0.0.0.00.00"')
        at_circ_disp = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.1.0.0.00.00"')
        at_nao_circ = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.2.0.0.0.00.00"')
        pass_circ = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.1.0.0.0.00.00"')
        pass_nao_circ = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.2.0.0.0.00.00"')
        vlr_restit = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.1.8.8.0.00.00"')
        estoques = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.5.0.0.00.00"')
        ativo = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.0.0.0.0.00.00"')
        passivo = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.1.0.0.0.00.00" | cod_conta == "P2.2.0.0.0.00.00"')
        imobilizado = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.2.3.0.0.00.00"')
        investimentos_ativo = get_value_or_zero(df_dca_ab, 'cod_conta == "P1.1.4.0.0.00.00"')
        pl = get_value_or_zero(df_dca_ab, 'cod_conta == "P2.3.0.0.0.00.00"')
        dps_corr_liq_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "DespesasCorrentes"')
        rec_corre_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "ReceitasCorrentes"')
        dps_capital_liq_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "DespesasDeCapital"')
        rec_capital_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "ReceitasDeCapital"')
        dps_pess_e_encarg_liq_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "PessoalEEncargosSociais"')
        dps_invest_liq_rreo_1 = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "Investimentos"')
        rcl = get_value_or_zero(df_rreo_3, 'cod_conta == "RREO3ReceitaCorrenteLiquida" and coluna == "TOTAL (ÚLTIMOS 12 MESES)"')
        rec_prevista = get_value_or_zero(df_rreo_1, 'coluna == "PREVISÃO ATUALIZADA (a)" & cod_conta == "TotalReceitas"')
        desp_fixada = get_value_or_zero(df_rreo_1, 'coluna == "DOTAÇÃO INICIAL (d)" & cod_conta == "TotalDespesas"')
        oper_cred = get_value_or_zero(df_rreo_1, 'coluna == "Até o Bimestre (c)" & cod_conta == "ReceitasDeOperacoesDeCredito"')
        juros_e_encargos_div = get_value_or_zero(df_rreo_1, 'coluna == "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)" & cod_conta == "JurosEEncargosDaDivida"')
        
        def safe_division(numerator, denominator):
            return numerator / denominator if denominator != 0 else 0

        pib_per_capita = pib_munic_valor
        receita_total_per_capita = safe_division(rec_rreo_1, nro_habitantes)
        iptu_per_capita = safe_division(iptu_rreo_3, nro_habitantes)
        iss_per_capita = safe_division(iss_rreo_3, nro_habitantes)
        div_ativa_per_capita = safe_division(div_ativa_trib_dca_ab, nro_habitantes)
        despesa_orcam_per_capita = safe_division(despesa_total, nro_habitantes)
        investimentos_per_capita = safe_division(despesa_investimentos, nro_habitantes)
        saude_per_capita = safe_division(despesa_saude, nro_habitantes)
        educacao_per_capita = safe_division(despesa_educacao, nro_habitantes)
        transf_legislativo_per_capita = safe_division(legislativo_rreo_2, nro_habitantes)
        rec_trib_per_capita = safe_division(rec_trib_rreo_1, nro_habitantes)
        rec_transf_per_capita = safe_division(tranf_corr_rreo_1, nro_habitantes)
        liquidez_imediata = safe_division(at_circ_disp, pass_circ)
        liquidez_recurso_terceiros = safe_division(at_circ_disp, vlr_restit)
        liquidez_corrente = safe_division(at_circ, pass_circ)
        liquidez_seca = safe_division((at_circ - estoques), pass_circ)
        liquidez_geral = safe_division((at_circ + at_nao_circ), (pass_circ + pass_nao_circ))
        solvencia_geral = safe_division(ativo, (pass_circ + pass_nao_circ))
        endivid_geral = safe_division(passivo, ativo) * 100
        composicao_exigibilidades = safe_division(pass_circ, passivo) * 100
        imobilizacao_pl = safe_division((imobilizado + investimentos_ativo), pl) * 100
        comprometimento_corrente = safe_division(dps_corr_liq_rreo_1, rec_corre_rreo_1) * 100
        comprometimento_capital = safe_division(dps_capital_liq_rreo_1, rec_capital_rreo_1) * 100
        gasto_pessoal_dps_orcam = safe_division(dps_pess_e_encarg_liq_rreo_1, dps_corr_liq_rreo_1) * 100
        gasto_invest_dps_orcam = safe_division(dps_invest_liq_rreo_1, dps_corr_liq_rreo_1) * 100
        gasto_pessoal_rcl = safe_division(dps_pess_e_encarg_liq_rreo_1, rcl) * 100
        rec_corr_proprias = safe_division((rec_corre_rreo_1 - tranf_corr_rreo_1), rec_corre_rreo_1) * 100
        exec_orcam_rec = safe_division(rec_rreo_1, rec_prevista) * 100
        exec_orcam_desp = safe_division(despesa_total, desp_fixada) * 100
        resultado_exec_orcam = safe_division(despesa_total, rec_rreo_1) * 100
        autonomia_orcam = safe_division((rec_corre_rreo_1 - tranf_corr_rreo_1), despesa_total) * 100
        amortizacao_e_refinanc_div = safe_division(oper_cred, despesa_total) * 100
        encargos_div_dps_corr = safe_division(juros_e_encargos_div, despesa_total) * 100
        
        resultados.append({
            "Município": ente, "A1_PIB per Capita": pib_per_capita, "A2_Receita Total per Capita": receita_total_per_capita,
            "A3_IPTU per Capita": iptu_per_capita, "A4_ISS per Capita": iss_per_capita,
            "A5_Dívida Ativa per Capita": div_ativa_per_capita, "B1_Despesas Orçamentárias per Capita": despesa_orcam_per_capita,
            "B2_Investimentos per Capita": investimentos_per_capita, "B3_Gastos com Saúde per Capita": saude_per_capita,
            "B4_Gastos com Educação per Capita": educacao_per_capita, "B5_Transferências para o Legislativo per Capita": transf_legislativo_per_capita,
            "C1_Receita Tributária per Capita": rec_trib_per_capita, "C2_Receita de Transferências per Capita": rec_transf_per_capita,
            "D1_Liquidez Instantânea ou Imediata": liquidez_imediata, "D3_Liquidez com recursos de terceiros": liquidez_recurso_terceiros,
            "D4_Liquidez Corrente": liquidez_corrente, "E2_Liquidez Seca": liquidez_seca,
            "E3_Liquidez Geral": liquidez_geral, "E6_Solvência Geral": solvencia_geral,
            "F1_Endividamento Geral": endivid_geral, "F2_Composição das Exigibilidades": composicao_exigibilidades,
            "F3_Imobilização do Patrimônio Líquido ou Capital Próprio": imobilizacao_pl,
            "F4_Grau de Comprometimento da Categoria Econômica Corrente": comprometimento_corrente,
            "F5_Grau de Comprometimento da Categoria Econômica de Capital": comprometimento_capital,
            "G1_Grau de Gasto com Pessoal em relação a Despesa Orçamentária": gasto_pessoal_dps_orcam,
            "G2_Grau de Investimento em relação a Despesa Orçamentária": gasto_invest_dps_orcam,
            "G3_Grau de Gasto com Pessoal em relação a Receita corrente Líquida": gasto_pessoal_rcl,
            "G4_Grau de Receitas Correntes Próprias ": rec_corr_proprias,
            "H1_Grau de Execução Orçamentária da Receita": exec_orcam_rec, "H2_Grau de Execução Orçamentária da Despesa": exec_orcam_desp,
            "H3_Grau do Resultado da Execução Orçamentária": resultado_exec_orcam, "H4_Grau de Autonomia Orçamentária": autonomia_orcam,
            "H5_Grau de Amortização e refinanciamento de dívida": amortizacao_e_refinanc_div,
            "H6_Grau de Encargos da dívida na despesa corrente": encargos_div_dps_corr,
        })

    if not resultados:
        return pd.DataFrame()

    df_resultados = pd.DataFrame(resultados)
    df_resultados['Município'] = df_resultados['Município'].replace(ibge_to_nome)
    df_pivot = df_resultados.melt(id_vars=["Município"], var_name="Índice", value_name="Valor")
    tabela_final = df_pivot.pivot_table(index="Índice", columns="Município", values="Valor")
    tabela_final['Média'] = tabela_final.mean(axis=1)

    for municipio_col in [col for col in tabela_final.columns if col in ibge_to_nome.values()]:
        tabela_final[f'{municipio_col}_Variação (%)'] = ((tabela_final[municipio_col] - tabela_final["Média"]) / tabela_final["Média"]) * 100
        tabela_final[f'{municipio_col}_Variação (%)'] = tabela_final[f'{municipio_col}_Variação (%)'].fillna(0).replace([float('inf'), -float('inf')], 0)

        def classificar_variacao(variacao):
            variacao_absoluta = abs(variacao)
            if variacao_absoluta <= 10: return 1
            elif 10 < variacao_absoluta <= 30: return 2
            else: return 3
        
        tabela_final[f'{municipio_col}_Classificação'] = tabela_final[f'{municipio_col}_Variação (%)'].apply(classificar_variacao)
    
    tabela_final["Interpretações"] = tabela_final.index.map(interpretacoes)
    tabela_final["Fórmulas"] = tabela_final.index.map(formulas)
    tabela_final["Ano"] = ano
    
    return tabela_final


# --- Layout do Aplicativo Streamlit ---

st.title("📊 Análise dos Indicadores Fiscais, Orçamentários e Contábeis")
st.markdown("""
Esta ferramenta tem o objetivo de analisar a gestão fiscal dos cinco maiores municípios fluminenses, com base na população estimada em 2021, avaliando seus principais indicadores fiscais, orçamentários e contábeis.
A análise é feita por meio de indicadores como PIB per capita, despesa orçamentária, arrecadação tributária e liquidez, de modo a identificar padrões de eficiência e desafios estruturais recorrentes na gestão pública municipal.
""")

st.sidebar.header("Passo a Passo da Análise")

# --------------------------
# Passo 1: Carregar Dados Locais
# --------------------------
st.sidebar.markdown("### 1. Carregar Dados Iniciais")
if st.sidebar.button("Carregar Dados de PIB e População"):
    # Caminhos CORRIGIDOS para a estrutura de pastas 'data/'
    pib_file_path = 'data/PIB dos Municípios - base de dados 2010-2021.xlsx'
    pop_file_path = 'data/POP_2022_Municipios.xlsx'

    st.session_state.pib_data = load_pib_data(pib_file_path)
    st.session_state.pop_data = load_pop_data(pop_file_path)

    if not st.session_state.pib_data.empty and not st.session_state.pop_data.empty:
        st.session_state.pib_pop_loaded = True
        st.sidebar.success("Dados de PIB e População carregados!")
    else:
        st.session_state.pib_pop_loaded = False
        st.sidebar.error("Falha ao carregar arquivos. Verifique os caminhos.")

if not st.session_state.pib_pop_loaded:
    st.warning("⚠️ **Passo 1:** Carregue os dados de PIB e População clicando no botão ao lado.")
else:
    st.success("✅ **Passo 1:** Dados de PIB e População carregados com sucesso!")
    
    # --------------------------
    # Passo 2: Seleção de Parâmetros
    # --------------------------
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 2. Selecionar Parâmetros")
    selected_year = st.sidebar.selectbox(
        "Selecione o Ano de Análise",
        options=available_years,
        index=len(available_years) - 1
    )
    selected_municipios_names = st.sidebar.multiselect(
        "Selecione os Municípios para Análise",
        options=all_municipios_names,
        default=all_municipios_names
    )
    selected_entes_ids = [nome_to_ibge[name] for name in selected_municipios_names]

    # --------------------------
    # Passo 3: Gerar Análise
    # --------------------------
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 3. Gerar Análise")
    if st.sidebar.button("Gerar Análise dos Índices SICONFI"):
        if not selected_entes_ids:
            st.warning("Por favor, selecione pelo menos um município para análise.")
        else:
            final_table = calculate_municipal_indices(
                selected_year, selected_entes_ids, st.session_state.pib_data, st.session_state.pop_data
            )
            st.session_state.final_table = final_table
            st.session_state.siconfi_loaded = True
    
    # --------------------------
    # Exibição dos Resultados Finais
    # --------------------------
    if st.session_state.siconfi_loaded and not st.session_state.final_table.empty:
        st.markdown("---")
        st.success("✅ **Passo 3:** Análise de índices gerada com sucesso!")
        st.subheader(f"Resultados dos Índices para o Ano {selected_year}")
        st.dataframe(
            st.session_state.final_table.style.format(
                {col: "{:.2f}" for col in st.session_state.final_table.select_dtypes(include='number').columns 
                 if 'Variação' not in col and 'Classificação' not in col}
            ),
            use_container_width=True
        )

        st.markdown("---")
        st.subheader("Glossário e Classificação")
        st.markdown("""
        **Variação (%):** Diferença percentual do índice do município em relação à média dos municípios selecionados.
        **Classificação:**
        * **1:** Variação absoluta $\\le 10\\%$ da média.
        * **2:** Variação absoluta entre $10\\%$ e $30\\%$ da média.
        * **3:** Variação absoluta $> 30\\%$ da média.
        """)
        
    elif st.session_state.pib_pop_loaded:
         st.info("ℹ️ **Passo 2 e 3:** Selecione o ano e os municípios na barra lateral e clique em 'Gerar Análise'.")

st.markdown("---")
st.info("""
**Observação:**
* Os arquivos `PIB dos Municípios - base de dados 2010-2021.xlsx` e `POP_2022_Municipios.xlsx` devem estar no mesmo diretório do script.
* A aplicação usa cache para acelerar o carregamento dos dados após a primeira execução.
* Divisão por zero em cálculos é tratada para evitar erros.
""")