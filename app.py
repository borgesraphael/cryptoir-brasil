"""
CryptoIR Brasil — Interface Web (Streamlit)
Validação com usuários reais.
"""

import streamlit as st
import tempfile
import os
from datetime import date
from pathlib import Path

from src.csv_parser import parsear_csv, FormatoDesconhecidoError
from src.darf_calculator import DARFCalculator
from src.fifo_calculator import SaldoInsuficienteError
from src.irpf_generator import gerar_irpf, formatar_relatorio_irpf
from main import formatar_relatorio

# ─────────────────────────────────────────────
# Configuração da página
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="CryptoIR Brasil",
    page_icon="📊",
    layout="centered",
)

# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────

st.title("📊 CryptoIR Brasil")
st.markdown("**Calcule seu DARF e prepare sua declaração de IRPF de criptomoedas.**")
st.markdown("Faça o upload do CSV exportado da sua exchange. Seus dados não são salvos.")

st.divider()

# ─────────────────────────────────────────────
# Upload do CSV
# ─────────────────────────────────────────────

st.subheader("1. Envie o histórico da sua exchange")

with st.expander("ℹ Como exportar o CSV", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
**Binance Brasil**
1. Acesse **Carteira → Spot**
2. Clique em **Histórico de Transações**
3. Selecione o período desejado
4. Clique em **Exportar → CSV**
        """)
    with col2:
        st.markdown("""
**Mercado Bitcoin**
1. Acesse **Extrato**
2. Selecione o período desejado
3. Clique em **Exportar CSV**
        """)

arquivo = st.file_uploader(
    "Selecione o arquivo CSV",
    type=["csv"],
    help="Suporta Binance Brasil e Mercado Bitcoin",
)

# ─────────────────────────────────────────────
# Processamento do CSV
# ─────────────────────────────────────────────

transacoes = None
exchange_detectada = None

if arquivo:
    # Salva temporariamente para usar os parsers existentes
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
        tmp.write(arquivo.read())
        tmp_path = tmp.name

    try:
        transacoes, erros = parsear_csv(tmp_path)
        exchange_detectada = transacoes[0].exchange if transacoes else None

        col1, col2 = st.columns(2)
        with col1:
            st.success(f"✅ **{len(transacoes)} transações** carregadas")
        with col2:
            st.info(f"🏦 Exchange: **{exchange_detectada}**")

        if erros:
            with st.expander(f"⚠ {len(erros)} linha(s) ignorada(s)", expanded=False):
                for e in erros:
                    st.caption(e)

    except FileNotFoundError:
        st.error("Arquivo não encontrado.")
        transacoes = None
    except FormatoDesconhecidoError:
        # Mostra o cabeçalho real para diagnóstico
        import csv as _csv
        with open(tmp_path, "r", encoding="utf-8-sig") as _f:
            cabecalho_real = next(_csv.reader(_f), [])
        st.error("❌ Formato não suportado. Use o CSV exportado da **Binance Brasil** ou **Mercado Bitcoin**.")
        st.warning(f"**Colunas encontradas no arquivo:** `{', '.join(cabecalho_real)}`")
        st.info("📸 Tire um print desta mensagem e compartilhe — vamos adicionar suporte a este formato.")
        transacoes = None
    finally:
        os.unlink(tmp_path)

# ─────────────────────────────────────────────
# Seleção do modo
# ─────────────────────────────────────────────

if transacoes:
    st.divider()
    st.subheader("2. O que você precisa calcular?")

    modo = st.radio(
        "Selecione:",
        options=["📅 DARF mensal", "📋 Declaração de IRPF anual"],
        horizontal=True,
    )

    st.divider()

    # ── DARF ──
    if modo == "📅 DARF mensal":
        st.subheader("3. Selecione o período")

        anos_disponiveis = sorted({t.data.year for t in transacoes}, reverse=True)
        col1, col2 = st.columns(2)

        with col1:
            ano = st.selectbox("Ano", options=anos_disponiveis)
        with col2:
            MESES = {
                1:"Janeiro", 2:"Fevereiro", 3:"Março", 4:"Abril",
                5:"Maio", 6:"Junho", 7:"Julho", 8:"Agosto",
                9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro"
            }
            meses_com_txs = sorted({
                t.data.month for t in transacoes if t.data.year == ano
            })
            opcoes_mes = {MESES[m]: m for m in meses_com_txs}
            mes_nome = st.selectbox("Mês", options=list(opcoes_mes.keys()))
            mes = opcoes_mes[mes_nome]

        if st.button("🧮 Calcular DARF", type="primary", use_container_width=True):
            with st.spinner("Calculando..."):
                try:
                    motor = DARFCalculator()
                    motor.processar_transacoes(transacoes)
                    resultado = motor.calcular_mes(transacoes, mes, ano)

                    # Métricas principais
                    st.divider()
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.metric(
                            "Total vendido",
                            f"R$ {resultado.total_vendas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                        )
                    with col2:
                        status = "✅ Isento" if resultado.e_isento else "⚠️ Tributável"
                        st.metric("Status", status)
                    with col3:
                        st.metric(
                            "Imposto devido",
                            f"R$ {resultado.imposto_devido:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                        )

                    if not resultado.e_isento and resultado.imposto_devido > 0:
                        st.error(
                            f"**DARF a pagar:** R$ {resultado.imposto_devido:,.2f}  |  "
                            f"Código 4600  |  "
                            f"Vencimento: {resultado.vencimento.strftime('%d/%m/%Y')}"
                            .replace(",", "X").replace(".", ",").replace("X", ".")
                        )
                    elif resultado.e_isento:
                        margem = resultado.limite_isencao - resultado.total_vendas
                        st.success(
                            f"**Isento!** Você ainda pode vender até "
                            f"R$ {margem:,.2f} este mês sem pagar imposto."
                            .replace(",", "X").replace(".", ",").replace("X", ".")
                        )

                    # Relatório completo
                    relatorio_txt = formatar_relatorio(resultado, arquivo.name)
                    with st.expander("📄 Ver relatório completo com memória de cálculo", expanded=False):
                        st.code(relatorio_txt, language=None)

                    st.download_button(
                        label="⬇️ Baixar relatório (.txt)",
                        data=relatorio_txt.encode("utf-8-sig"),
                        file_name=f"darf_{mes:02d}_{ano}.txt",
                        mime="text/plain; charset=utf-8",
                        use_container_width=True,
                    )

                except SaldoInsuficienteError as e:
                    st.error(f"❌ {e}\n\nDica: importe o histórico completo incluindo todas as compras anteriores.")

    # ── IRPF ──
    else:
        st.subheader("3. Selecione o ano-base")

        anos_disponiveis = sorted({t.data.year for t in transacoes}, reverse=True)
        ano_irpf = st.selectbox(
            "Ano-base (ex: 2025 para a declaração entregue em 2026)",
            options=anos_disponiveis,
        )

        st.info(
            "O relatório IRPF gera os valores exatos para preencher no **PGD IRPF** oficial:\n"
            "- **Ficha Bens e Direitos** (grupo 08) — custo de aquisição em 31/12\n"
            "- **Renda Variável** — ganhos mensais e DARF recolhido\n"
            "- **Rendimentos Tributáveis** — staking, airdrop e yield"
        )

        if st.button("📋 Gerar dados para IRPF", type="primary", use_container_width=True):
            with st.spinner("Calculando posição de todos os ativos..."):
                relatorio = gerar_irpf(transacoes, ano_irpf)

                st.divider()

                # Bens e Direitos
                if relatorio.bens_e_direitos:
                    st.markdown("#### 📁 Bens e Direitos — Grupo 08")
                    st.caption("⚠️ Informe o **custo de aquisição**, nunca o valor de mercado atual.")

                    for item in relatorio.bens_e_direitos:
                        with st.container(border=True):
                            col1, col2 = st.columns([2, 1])
                            with col1:
                                st.markdown(f"**Código {item.codigo_grupo}{item.codigo_bem} — {item.asset}**")
                                st.caption(f"Discriminação: {item.discriminacao}")
                            with col2:
                                v_ant = f"R$ {item.situacao_ano_anterior:,.2f}".replace(",","X").replace(".",",").replace("X",".")
                                v_atu = f"R$ {item.situacao_ano_atual:,.2f}".replace(",","X").replace(".",",").replace("X",".")
                                st.metric(f"31/12/{ano_irpf - 1}", v_ant)
                                st.metric(f"31/12/{ano_irpf}", v_atu)

                # Rendimentos
                if relatorio.rendimentos:
                    st.markdown("#### 💰 Rendimentos Tributáveis — Código 26")
                    st.caption("Informe na ficha: Rendimentos Tributáveis Recebidos de PJ")
                    for r in relatorio.rendimentos:
                        v = f"R$ {r.valor_brl:,.2f}".replace(",","X").replace(".",",").replace("X",".")
                        st.markdown(f"- **{r.tipo}** de {r.asset}: **{v}** ({r.exchange})")
                    total = f"R$ {relatorio.total_rendimentos_brl:,.2f}".replace(",","X").replace(".",",").replace("X",".")
                    st.markdown(f"**Total: {total}**")

                # Renda Variável
                if relatorio.renda_variavel:
                    st.markdown("#### 📈 Renda Variável — Operações em Criptoativos")
                    for rv in relatorio.renda_variavel:
                        if rv.e_isento:
                            st.markdown(f"- {rv.periodo}: ✅ Isento")
                        elif rv.ganho_liquido > 0:
                            g = f"R$ {rv.ganho_liquido:,.2f}".replace(",","X").replace(".",",").replace("X",".")
                            d = f"R$ {rv.imposto_recolhido:,.2f}".replace(",","X").replace(".",",").replace("X",".")
                            st.markdown(f"- {rv.periodo}: Ganho **{g}** → DARF recolhido: **{d}**")
                        else:
                            p = f"R$ {abs(rv.ganho_liquido):,.2f}".replace(",","X").replace(".",",").replace("X",".")
                            st.markdown(f"- {rv.periodo}: Prejuízo **{p}**")

                # Download
                relatorio_txt = formatar_relatorio_irpf(relatorio)
                st.download_button(
                    label="⬇️ Baixar relatório IRPF (.txt)",
                    data=relatorio_txt.encode("utf-8-sig"),  # BOM garante UTF-8 no Windows
                    file_name=f"irpf_{ano_irpf}.txt",
                    mime="text/plain; charset=utf-8",
                    use_container_width=True,
                )

                if relatorio.observacoes:
                    for obs in relatorio.observacoes:
                        st.warning(obs)

# ─────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────

st.divider()
st.caption(
    "⚠️ Estimativa baseada nas normas da Receita Federal (IN RFB 2.291/2025). "
    "Não substitui orientação de contador ou advogado tributarista. "
    "**Seus dados não são armazenados.**"
)
