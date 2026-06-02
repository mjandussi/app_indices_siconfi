# 📊 Análise das Demonstrações Contábeis das 5 Maiores Cidades do Estado do Rio de Janeiro

> **Autores do Capítulo 6:** Waldir Jorge Ladeira dos Santos · Yasmim da Costa Monteiro ·
> Bruno Campos Pereira · Marcelo Jandussi Walther de Almeida

Aplicativo **Streamlit** que analisa, de forma **dinâmica e interativa**, os principais indicadores
fiscais, orçamentários e contábeis dos **cinco maiores municípios do Estado do Rio de Janeiro**,
combinando dados oficiais do **SICONFI (Tesouro Nacional)** com bases socioeconômicas de **PIB** e
**População** do **IBGE/SIDRA** — todos obtidos **ao vivo via API**.

---

## 📖 Origem: Capítulo 6 do livro *Governança Pública*

Este aplicativo é o **produto digital derivado do Capítulo 6** da obra:

> **SANTOS**, Waldir Jorge Ladeira dos; **MONTEIRO**, Yasmim da Costa; **PEREIRA**, Bruno Campos;
> **ALMEIDA**, Marcelo Jandussi Walther de. *Análise das Demonstrações Contábeis das cinco maiores
> cidades do Estado do Rio de Janeiro.* In: ROSSI, Gustavo Afonso Santi; SANTOS, Waldir Jorge
> Ladeira dos (org.). **Governança Pública: boas práticas para o gestor público**.
> Rio de Janeiro: Grande Editora, 2025. **cap. 6, p. 210–240**. ISBN 978-65-6125-029-0.

O capítulo apresenta a metodologia de análise da gestão fiscal municipal por meio de indicadores de
resultado (PIB per capita, despesa orçamentária, arrecadação tributária, liquidez, estrutura de
capitais e execução orçamentária), aplicada às cinco maiores cidades fluminenses, com o objetivo de
identificar padrões de eficiência, fragilidades, boas práticas e oportunidades de aperfeiçoamento na
administração pública municipal.

---

## 🔄 De estático para dinâmico — o diferencial deste aplicativo

A análise publicada no livro foi **estática**: baseou-se em uma **planilha fixa do exercício de 2021**,
com dados de PIB, População (IBGE) e demonstrativos do SICONFI coletados pontualmente. Este aplicativo
**evolui** essa pesquisa para um modelo **dinâmico**, recalculando os mesmos indicadores a cada execução.

| | 📕 Capítulo 6 (livro) | 💻 Este aplicativo |
|---|---|---|
| **Período** | Fixo — exercício de **2021** | **Qualquer ano** disponível (seleção dinâmica) |
| **PIB e População** | Planilha estática (IBGE, 2021) | **API do IBGE/SIDRA** (Agregados), ao vivo |
| **Dados fiscais/contábeis** | Extração pontual do SICONFI | **API do SICONFI** (RREO e DCA), ao vivo |
| **Cálculo dos índices** | Manual / planilha | **Automático e reprodutível** |
| **Resultado** | Tabelas impressas no capítulo | Tabela interativa + **exportação para Excel** |

> ⚠️ **Defasagem do PIB municipal:** o IBGE divulga o PIB dos municípios com alguns anos de
> defasagem. Quando não há PIB para o ano selecionado, o app utiliza automaticamente o **último ano
> disponível** por município e informa, de forma transparente, qual ano de referência foi usado.

---

## 🏙️ Municípios analisados

| Município (código IBGE) | |
|---|---|
| Rio de Janeiro (3304557) | Nova Iguaçu (3303500) |
| São Gonçalo (3304904) | Campos dos Goytacazes (3301009) |
| Duque de Caxias (3301702) | |

---

## 🧮 Indicadores calculados

Organizados nos grupos propostos no Capítulo 6:

- **A — Receita e Arrecadação:** PIB, Receita Total, IPTU, ISS e Dívida Ativa *per capita*.
- **B — Despesa e Aplicação de Recursos:** despesa orçamentária, investimentos, saúde, educação e
  transferências ao Legislativo *per capita*.
- **C — Receita Tributária e Transferências** *per capita*.
- **D / E — Liquidez e Capacidade de Pagamento:** liquidez imediata, corrente, seca, geral e solvência.
- **F — Estrutura de Capitais:** endividamento, composição das exigibilidades e imobilização do PL.
- **G / H — Execução Orçamentária:** comprometimento, gastos com pessoal, autonomia, execução de
  receita/despesa e encargos da dívida.

Para cada indicador o app calcula a **média** da amostra, a **variação (%)** de cada município em
relação à média e uma **classificação** — em diálogo com a *qualificação de perfis* descrita no capítulo.

---

## 🗂️ Fontes de dados (via API)

- **SICONFI / Tesouro Nacional** — RREO (Anexos 01, 02 e 03) e DCA (Anexo I-AB).
  `https://apidatalake.tesouro.gov.br/ords/siconfi/`
- **IBGE / SIDRA — Agregados** — PIB municipal (agregado 5938) e População estimada (agregado 6579).
  `https://servicodados.ibge.gov.br/api/v3/agregados/`

---

## ▶️ Como executar

```bash
# 1. (recomendado) criar e ativar um ambiente virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 2. instalar as dependências
pip install -r requirements.txt

# 3. rodar o aplicativo
streamlit run app.py
```

No app:

1. Clique em **📥 Carregar dados do IBGE** (PIB e População).
2. Selecione o **ano de análise** e os **municípios**.
3. Clique em **⚙️ Gerar Análise** para calcular os índices.
4. Consulte a tabela de resultados, a **transparência dos anos de referência** e exporte para **Excel**.

---

## ✍️ Autoria

Capítulo 6 e metodologia de autoria de **Waldir Jorge Ladeira dos Santos**, **Yasmim da Costa Monteiro**,
**Bruno Campos Pereira** e **Marcelo Jandussi Walther de Almeida**.

Aplicativo de uso **educacional** e de **apoio à gestão fiscal municipal**, sem vínculo oficial com os
órgãos provedores dos dados (Tesouro Nacional e IBGE).
