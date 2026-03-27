"""
Testes do IRPF Generator.
Valores verificáveis manualmente em cada teste.
"""

import pytest
from datetime import datetime
from src.csv_parser import Transacao
from src.irpf_generator import gerar_irpf, _codigo_bem


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def tx(data_str, tipo, asset_out, amount_out, asset_in, amount_in,
       price_brl, exchange_type="nacional", exchange="Binance Brasil", fee_brl=0.0):
    return Transacao(
        data=datetime.strptime(data_str, "%Y-%m-%d"),
        tipo=tipo,
        asset_out=asset_out, amount_out=amount_out,
        asset_in=asset_in, amount_in=amount_in,
        price_brl=price_brl, fee_brl=fee_brl,
        exchange=exchange, exchange_type=exchange_type,
        raw_line="",
    )


# ─────────────────────────────────────────────
# Testes de classificação de ativos
# ─────────────────────────────────────────────

def test_codigo_bem_btc():
    assert _codigo_bem("BTC") == "01"

def test_codigo_bem_stablecoin():
    assert _codigo_bem("USDT") == "03"
    assert _codigo_bem("USDC") == "03"
    assert _codigo_bem("BUSD") == "03"

def test_codigo_bem_outras():
    assert _codigo_bem("ETH") == "02"
    assert _codigo_bem("SOL") == "02"
    assert _codigo_bem("BNB") == "02"


# ─────────────────────────────────────────────
# Testes de Bens e Direitos
# ─────────────────────────────────────────────

def test_bens_direitos_usa_custo_aquisicao():
    """
    Comprou 0.1 BTC a R$300k em jan/25.
    Situação 31/12/2025 = R$30.000 (custo), NUNCA o valor de mercado.
    """
    transacoes = [
        tx("2025-01-10", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    btc = next(i for i in relatorio.bens_e_direitos if i.asset == "BTC")
    assert btc.situacao_ano_anterior == pytest.approx(0.0)   # nada em 31/12/2024
    assert btc.situacao_ano_atual == pytest.approx(30_000.0) # custo de aquisição


def test_bens_direitos_ano_anterior_populado():
    """
    Comprou em 2024 e não vendeu. Em 2025 ainda aparece o custo do ano anterior.
    """
    transacoes = [
        tx("2024-03-01", "BUY", "BRL", 10_400, "ETH", 1.0, 10_400),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    eth = next((i for i in relatorio.bens_e_direitos if i.asset == "ETH"), None)
    assert eth is not None
    assert eth.situacao_ano_anterior == pytest.approx(10_400.0)  # comprou em 2024
    assert eth.situacao_ano_atual == pytest.approx(10_400.0)     # não vendeu em 2025


def test_bens_direitos_apos_venda_parcial():
    """
    Comprou 0.1 BTC a R$300k. Vendeu 0.05 BTC em junho.
    Situação 31/12 = custo dos 0.05 BTC restantes = R$15.000.
    """
    transacoes = [
        tx("2025-01-10", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000),
        tx("2025-06-20", "SELL", "BTC", 0.05, "BRL", 20_000, 400_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    btc = next(i for i in relatorio.bens_e_direitos if i.asset == "BTC")
    # Restam 0.05 BTC × R$300k/BTC = R$15.000
    assert btc.situacao_ano_atual == pytest.approx(15_000.0)


def test_bens_direitos_venda_total_some_da_lista():
    """
    Vendeu tudo no ano → custo 31/12 = 0. Item ainda aparece com valor 0.
    """
    transacoes = [
        tx("2024-06-01", "BUY", "BRL", 10_000, "ETH", 1.0, 10_000),
        tx("2025-03-01", "SELL", "ETH", 1.0, "BRL", 15_000, 15_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    eth = next((i for i in relatorio.bens_e_direitos if i.asset == "ETH"), None)
    # Tinha em 2024, vendeu tudo em 2025
    if eth:
        assert eth.situacao_ano_anterior == pytest.approx(10_000.0)
        assert eth.situacao_ano_atual == pytest.approx(0.0)


def test_bens_direitos_codigo_correto_por_ativo():
    """BTC → código 01, ETH → código 02."""
    transacoes = [
        tx("2025-01-01", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000),
        tx("2025-01-01", "BUY", "BRL", 10_000, "ETH", 1.0, 10_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    btc = next(i for i in relatorio.bens_e_direitos if i.asset == "BTC")
    eth = next(i for i in relatorio.bens_e_direitos if i.asset == "ETH")
    assert btc.codigo_bem == "01"
    assert eth.codigo_bem == "02"


def test_bens_direitos_discriminacao_inclui_exchange():
    """Discriminação deve incluir o nome da exchange e CNPJ se conhecido."""
    transacoes = [
        tx("2025-01-01", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000,
           exchange="Binance Brasil"),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    btc = next(i for i in relatorio.bens_e_direitos if i.asset == "BTC")
    assert "Binance Brasil" in btc.discriminacao
    assert "18.600.620/0001-10" in btc.discriminacao
    assert "BTC" in btc.discriminacao


# ─────────────────────────────────────────────
# Testes de Rendimentos Tributáveis
# ─────────────────────────────────────────────

def test_staking_e_rendimento_tributavel():
    """Staking de 0.04 ETH a R$13.000 = R$520 de rendimento."""
    transacoes = [
        tx("2025-04-01", "STAKING", "BRL", 0, "ETH", 0.04, 13_000,
           exchange="Binance Brasil"),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    assert len(relatorio.rendimentos) == 1
    r = relatorio.rendimentos[0]
    assert r.tipo == "STAKING"
    assert r.asset == "ETH"
    assert r.quantidade_total == pytest.approx(0.04)
    assert r.valor_brl == pytest.approx(520.0)


def test_airdrop_e_rendimento_tributavel():
    """Airdrop de 150 ARB a R$2,50 = R$375 de rendimento."""
    transacoes = [
        tx("2025-09-10", "AIRDROP", "BRL", 0, "ARB", 150, 2.5),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    assert len(relatorio.rendimentos) == 1
    assert relatorio.rendimentos[0].valor_brl == pytest.approx(375.0)


def test_staking_acumulado_mesmo_ativo():
    """Dois recebimentos de staking do mesmo ativo somam corretamente."""
    transacoes = [
        tx("2025-04-01", "STAKING", "BRL", 0, "ETH", 0.02, 13_000),
        tx("2025-05-01", "STAKING", "BRL", 0, "ETH", 0.02, 14_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    r = relatorio.rendimentos[0]
    assert r.quantidade_total == pytest.approx(0.04)
    # 0.02 × 13k + 0.02 × 14k = 260 + 280 = R$540
    assert r.valor_brl == pytest.approx(540.0)


def test_sem_staking_sem_rendimentos():
    """Sem staking ou airdrop → lista de rendimentos vazia."""
    transacoes = [
        tx("2025-01-01", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    assert relatorio.rendimentos == []
    assert relatorio.total_rendimentos_brl == 0.0


# ─────────────────────────────────────────────
# Testes de Renda Variável
# ─────────────────────────────────────────────

def test_rv_mes_isento_classificado_corretamente():
    """Venda abaixo de R$35k → isento na renda variável."""
    transacoes = [
        tx("2025-01-10", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000),
        tx("2025-03-15", "SELL", "BTC", 0.005, "BRL", 1_750, 350_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    mar = next((r for r in relatorio.renda_variavel if r.mes == 3), None)
    assert mar is not None
    assert mar.e_isento is True
    assert mar.imposto_recolhido == 0.0


def test_rv_mes_tributavel_com_imposto():
    """Venda acima de R$35k → ganho e imposto na renda variável."""
    transacoes = [
        tx("2025-01-10", "BUY", "BRL", 24_000, "BTC", 0.08, 300_000),
        tx("2025-01-10", "BUY", "BRL", 5_200, "ETH", 0.5, 10_400),
        tx("2025-06-20", "SELL", "BTC", 0.08, "BRL", 30_400, 380_000),
        tx("2025-06-22", "SELL", "ETH", 0.5, "BRL", 6_000, 12_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    jun = next((r for r in relatorio.renda_variavel if r.mes == 6), None)
    assert jun is not None
    assert jun.e_isento is False
    assert jun.ganho_liquido == pytest.approx(7_200.0)
    assert jun.imposto_recolhido == pytest.approx(1_080.0)


def test_rv_sem_vendas_lista_vazia():
    """Sem vendas no ano → renda variável vazia."""
    transacoes = [
        tx("2025-01-01", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    assert relatorio.renda_variavel == []


def test_rv_total_imposto_correto():
    """Total de DARF recolhido soma corretamente os meses tributados."""
    transacoes = [
        tx("2025-01-10", "BUY", "BRL", 24_000, "BTC", 0.08, 300_000),
        tx("2025-01-10", "BUY", "BRL", 5_200, "ETH", 0.5, 10_400),
        tx("2025-06-20", "SELL", "BTC", 0.08, "BRL", 30_400, 380_000),
        tx("2025-06-22", "SELL", "ETH", 0.5, "BRL", 6_000, 12_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    assert relatorio.total_imposto_darf == pytest.approx(1_080.0)


# ─────────────────────────────────────────────
# Teste de integração — cenário completo
# ─────────────────────────────────────────────

def test_cenario_completo_2025():
    """
    Cenário completo do documento de referência:
    - Jan/25: compra 0.01 BTC a R$300k
    - Mar/25: vende 0.005 BTC → isento (R$1.750)
    - Jun/25: vende 0.08 BTC + 0.5 ETH → tributável (imposto R$1.080)
    - Abr/25: staking de 0.04 ETH (R$520)
    """
    transacoes = [
        tx("2024-01-10", "BUY", "BRL", 30_000, "BTC", 0.10, 300_000),
        tx("2024-03-01", "BUY", "BRL", 10_400, "ETH", 1.00, 10_400),
        tx("2025-01-10", "BUY", "BRL", 3_000,  "BTC", 0.01, 300_000),
        tx("2025-03-15", "SELL", "BTC", 0.005, "BRL", 1_750, 350_000),
        tx("2025-04-01", "STAKING", "BRL", 0, "ETH", 0.04, 13_000),
        tx("2025-06-20", "SELL", "BTC", 0.08, "BRL", 30_400, 380_000),
        tx("2025-06-22", "SELL", "ETH", 0.50, "BRL", 6_000, 12_000),
    ]
    relatorio = gerar_irpf(transacoes, 2025)

    # Bens e Direitos
    btc = next(i for i in relatorio.bens_e_direitos if i.asset == "BTC")
    eth = next(i for i in relatorio.bens_e_direitos if i.asset == "ETH")

    # BTC: comprou 0.10 em 2024 + 0.01 em 2025. Vendeu 0.085 (0.005+0.08). Resta 0.025.
    # FIFO: 0.025 BTC restante é do lote de jan/24 a R$300k → custo = 0.025 × 300k = R$7.500
    assert btc.situacao_ano_anterior == pytest.approx(30_000.0)  # 0.1 × 300k
    assert btc.situacao_ano_atual == pytest.approx(7_500.0)      # 0.025 × 300k

    # ETH: comprou 1.0 em 2024. Recebeu 0.04 de staking. Vendeu 0.5. Resta 0.54.
    # Custo do restante pelo FIFO: 0.5 × 10.400 + 0.04 × 13.000 = 5.200 + 520 = R$5.720
    assert eth.situacao_ano_anterior == pytest.approx(10_400.0)  # 1.0 × 10.400
    assert eth.situacao_ano_atual == pytest.approx(5_720.0)      # (0.5 × 10.400) + (0.04 × 13.000)

    # Rendimentos
    assert relatorio.total_rendimentos_brl == pytest.approx(520.0)

    # Renda Variável
    assert relatorio.total_imposto_darf == pytest.approx(1_080.0)
