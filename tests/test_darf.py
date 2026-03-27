"""
Testes do Motor DARF.
Cobre todos os casos fiscais críticos com valores verificáveis manualmente.
"""

import pytest
from datetime import date, datetime
from src.darf_calculator import DARFCalculator, calcular_vencimento_darf, LIMITE_ISENCAO_MENSAL
from src.csv_parser import Transacao


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def tx(data_str, tipo, asset_out, amount_out, asset_in, amount_in,
       price_brl, exchange_type="nacional", exchange="Mercado Bitcoin", fee_brl=0.0):
    """Cria uma Transacao de teste."""
    return Transacao(
        data=datetime.strptime(data_str, "%Y-%m-%d"),
        tipo=tipo,
        asset_out=asset_out, amount_out=amount_out,
        asset_in=asset_in, amount_in=amount_in,
        price_brl=price_brl, fee_brl=fee_brl,
        exchange=exchange, exchange_type=exchange_type,
        raw_line="",
    )


def motor_com_btc(preco_compra=300_000, quantidade=0.1) -> DARFCalculator:
    """Motor pré-carregado com um lote de BTC comprado."""
    motor = DARFCalculator()
    compras = [tx("2024-01-10", "BUY", "BRL", preco_compra * quantidade,
                  "BTC", quantidade, preco_compra)]
    motor.processar_transacoes(compras)
    return motor


# ─────────────────────────────────────────────
# Testes de isenção
# ─────────────────────────────────────────────

def test_venda_abaixo_limite_isento():
    """Venda de R$1.750 (muito abaixo de R$35k) → isento."""
    motor = motor_com_btc()
    vendas = [tx("2025-03-15", "SELL", "BTC", 0.005, "BRL", 1750, 350_000)]
    todas = vendas
    motor.processar_transacoes([])  # compras já foram no motor_com_btc

    resultado = motor.calcular_mes(vendas, 3, 2025)

    assert resultado.e_isento is True
    assert resultado.imposto_devido == 0.0
    assert resultado.total_vendas == pytest.approx(1_750.0)


def test_venda_exatamente_no_limite_isento():
    """R$35.000 exatos → ISENTO (limite é <=, não <)."""
    motor = DARFCalculator()
    compras = [tx("2024-01-01", "BUY", "BRL", 35_000, "BTC", 0.1, 350_000)]
    motor.processar_transacoes(compras)

    vendas = [tx("2025-06-01", "SELL", "BTC", 0.1, "BRL", 35_000, 350_000)]
    resultado = motor.calcular_mes(vendas, 6, 2025)

    assert resultado.e_isento is True
    assert resultado.total_vendas == pytest.approx(35_000.0)
    assert resultado.imposto_devido == 0.0


def test_venda_um_real_acima_do_limite_tributavel():
    """R$35.001 → tributável."""
    motor = DARFCalculator()
    # Compra a preço baixo para garantir lucro
    preco_compra = 100_000
    motor.processar_transacoes([tx("2024-01-01", "BUY", "BRL", 3_500.1, "BTC", 0.035001, preco_compra)])

    vendas = [tx("2025-06-01", "SELL", "BTC", 0.035001, "BRL", 35_001, 1_000_000)]
    resultado = motor.calcular_mes(vendas, 6, 2025)

    assert resultado.e_isento is False
    assert resultado.total_vendas == pytest.approx(35_001.0)
    assert resultado.imposto_devido > 0


# ─────────────────────────────────────────────
# Testes de alíquota e cálculo de imposto
# ─────────────────────────────────────────────

def test_aliquota_15_para_ganho_normal():
    """Ganho de R$7.200 → alíquota 15% → imposto R$1.080."""
    motor = DARFCalculator()
    # Comprou 0.08 BTC a R$300k + 0.5 ETH a R$10.400
    compras = [
        tx("2025-01-10", "BUY", "BRL", 24_000, "BTC", 0.08, 300_000),
        tx("2025-03-01", "BUY", "BRL", 5_200, "ETH", 0.5, 10_400),
    ]
    motor.processar_transacoes(compras)

    # Junho: vende R$36.400 total
    vendas = [
        tx("2025-06-20", "SELL", "BTC", 0.08, "BRL", 30_400, 380_000),
        tx("2025-06-22", "SELL", "ETH", 0.5, "BRL", 6_000, 12_000),
    ]
    resultado = motor.calcular_mes(vendas, 6, 2025)

    assert resultado.e_isento is False
    assert resultado.total_vendas == pytest.approx(36_400.0)
    # Custo: 0.08 × 300k + 0.5 × 10.4k = 24k + 5.2k = 29.2k
    # Ganho: 36.4k - 29.2k = 7.2k
    assert resultado.ganho_bruto == pytest.approx(7_200.0)
    assert resultado.aliquota == pytest.approx(0.15)
    assert resultado.imposto_devido == pytest.approx(1_080.0)


def test_imposto_zero_quando_isento():
    """Dentro da isenção → imposto deve ser R$0,00."""
    motor = motor_com_btc()
    vendas = [tx("2025-03-15", "SELL", "BTC", 0.001, "BRL", 300, 300_000)]
    resultado = motor.calcular_mes(vendas, 3, 2025)

    assert resultado.imposto_devido == 0.0


# ─────────────────────────────────────────────
# Testes de eventos tributáveis especiais
# ─────────────────────────────────────────────

def test_trade_crypto_crypto_e_tributavel():
    """Trocar BTC por ETH é evento tributável — conta para o limite."""
    motor = DARFCalculator()
    motor.processar_transacoes([
        tx("2024-01-01", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000),
    ])

    # Trade: vende 0.1 BTC a R$380k, compra ETH
    trade = [tx("2025-06-01", "TRADE", "BTC", 0.1, "ETH", 1.0, 380_000)]
    resultado = motor.calcular_mes(trade, 6, 2025)

    assert resultado.total_vendas == pytest.approx(38_000.0)  # 0.1 × 380k
    assert resultado.e_isento is False


def test_conversao_stablecoin_e_tributavel():
    """BTC → USDT conta como venda tributável."""
    motor = DARFCalculator()
    motor.processar_transacoes([
        tx("2024-01-01", "BUY", "BRL", 30_000, "BTC", 0.1, 300_000),
    ])

    conversao = [tx("2025-06-01", "SELL", "BTC", 0.1, "USDT", 38_000, 380_000)]
    resultado = motor.calcular_mes(conversao, 6, 2025)

    assert resultado.total_vendas == pytest.approx(38_000.0)
    assert resultado.e_isento is False


def test_staking_nao_conta_para_darf():
    """Staking não é venda — não conta para o limite de R$35k."""
    motor = DARFCalculator()
    staking = [tx("2025-06-01", "STAKING", "BRL", 0, "ETH", 0.04, 13_000,
                  exchange="Binance")]
    resultado = motor.calcular_mes(staking, 6, 2025)

    assert resultado.total_vendas == 0.0
    assert resultado.e_isento is True
    assert len(resultado.rendimentos) == 1
    assert resultado.rendimentos[0].valor_brl == pytest.approx(520.0)  # 0.04 × 13k


def test_transferencia_nao_e_tributavel():
    """Transferência entre carteiras próprias não é evento tributável."""
    motor = DARFCalculator()
    transferencia = [
        tx("2025-06-01", "TRANSFER_OUT", "BTC", 0.05, "BTC", 0.05, 380_000),
    ]
    resultado = motor.calcular_mes(transferencia, 6, 2025)

    assert resultado.total_vendas == 0.0
    assert resultado.e_isento is True


# ─────────────────────────────────────────────
# Testes de compensação de prejuízo
# ─────────────────────────────────────────────

def test_prejuizo_compensa_mes_seguinte():
    """Prejuízo de maio é compensado no ganho de junho."""
    motor = DARFCalculator()
    compras = [
        tx("2024-01-01", "BUY", "BRL", 40_000, "BTC", 0.1, 400_000),  # comprou caro
        tx("2024-02-01", "BUY", "BRL", 30_000, "ETH", 3.0, 10_000),
    ]
    motor.processar_transacoes(compras)

    # Maio: vende BTC com PREJUÍZO (comprou a 400k, vende a 360k) — mas acima de 35k
    # venda: 0.1 BTC × R$360k = R$36k (acima do limite, mas tem prejuízo)
    vendas_maio = [tx("2025-05-20", "SELL", "BTC", 0.1, "BRL", 36_000, 360_000)]
    resultado_maio = motor.calcular_mes(vendas_maio, 5, 2025)

    assert resultado_maio.e_isento is False
    assert resultado_maio.ganho_bruto == pytest.approx(-4_000.0)  # 36k - 40k = -4k
    assert resultado_maio.imposto_devido == 0.0  # prejuízo, sem imposto

    # Junho: vende ETH com LUCRO de R$8k, acima do limite
    # comprou 3 ETH a 10k, vende a 15k → receita R$45k, custo R$30k, ganho R$15k
    vendas_junho = [tx("2025-06-15", "SELL", "ETH", 3.0, "BRL", 45_000, 15_000)]
    resultado_junho = motor.calcular_mes(vendas_junho, 6, 2025)

    assert resultado_junho.e_isento is False
    assert resultado_junho.ganho_bruto == pytest.approx(15_000.0)
    assert resultado_junho.prejuizo_compensado == pytest.approx(4_000.0)
    assert resultado_junho.ganho_liquido == pytest.approx(11_000.0)
    assert resultado_junho.imposto_devido == pytest.approx(11_000.0 * 0.15)


def test_sem_prejuizo_sem_compensacao():
    """Sem prejuízo acumulado, compensação é zero."""
    motor = DARFCalculator()
    compras = [tx("2024-01-01", "BUY", "BRL", 30_000, "ETH", 3.0, 10_000)]
    motor.processar_transacoes(compras)

    vendas = [tx("2025-06-15", "SELL", "ETH", 3.0, "BRL", 45_000, 15_000)]
    resultado = motor.calcular_mes(vendas, 6, 2025)

    assert resultado.prejuizo_compensado == 0.0
    assert resultado.ganho_liquido == pytest.approx(15_000.0)


# ─────────────────────────────────────────────
# Testes de exchange estrangeira
# ─────────────────────────────────────────────

def test_exchange_estrangeira_sem_isencao():
    """Venda de R$5.000 em exchange estrangeira → tributável (sem isenção)."""
    motor = DARFCalculator()
    compras = [tx("2024-01-01", "BUY", "BRL", 3_000, "BTC", 0.01, 300_000,
                  exchange_type="estrangeira", exchange="Binance Internacional")]
    motor.processar_transacoes(compras)

    vendas = [tx("2025-04-01", "SELL", "BTC", 0.01, "BRL", 5_000, 500_000,
                 exchange_type="estrangeira", exchange="Binance Internacional")]
    resultado = motor.calcular_ano_estrangeira(vendas, 2025)

    assert resultado.e_isento is False
    assert resultado.aliquota == pytest.approx(0.15)
    assert resultado.ganho_bruto == pytest.approx(2_000.0)
    assert resultado.imposto_devido == pytest.approx(300.0)


# ─────────────────────────────────────────────
# Testes de vencimento do DARF
# ─────────────────────────────────────────────

def test_vencimento_mes_normal():
    """Apuração de abril → vencimento em maio."""
    venc = calcular_vencimento_darf(4, 2025)
    assert venc.month == 5
    assert venc.year == 2025
    assert venc.weekday() < 5  # dia útil


def test_vencimento_dezembro_vai_para_janeiro():
    """Apuração de dezembro → vencimento em janeiro do ano seguinte."""
    venc = calcular_vencimento_darf(12, 2025)
    assert venc.month == 1
    assert venc.year == 2026
    assert venc.weekday() < 5


def test_vencimento_sempre_dia_util():
    """Vencimento nunca cai em fim de semana."""
    for mes in range(1, 13):
        venc = calcular_vencimento_darf(mes, 2025)
        assert venc.weekday() < 5, f"Vencimento de {mes}/2025 caiu em fim de semana: {venc}"


def test_resultado_sem_transacoes_isento():
    """Mês sem nenhuma transação → isento, imposto zero."""
    motor = DARFCalculator()
    resultado = motor.calcular_mes([], 6, 2025)

    assert resultado.e_isento is True
    assert resultado.total_vendas == 0.0
    assert resultado.imposto_devido == 0.0
