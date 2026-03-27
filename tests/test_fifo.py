"""
Testes do FIFO Calculator.
Cobre todos os casos fiscais relevantes com valores verificáveis manualmente.
"""

import pytest
from datetime import date
from src.fifo_calculator import FIFOCalculator, SaldoInsuficienteError


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def fifo_com_btc_jan_jun() -> FIFOCalculator:
    """
    FIFO com dois lotes de BTC — cenário base do documento.
    Preço unitário = R$/BTC (não total pago).
    """
    fifo = FIFOCalculator()
    fifo.registrar_compra("BTC", 0.1, 200_000, date(2024, 1, 10), "Binance")   # 0.1 BTC a R$200k/BTC → custo R$20k
    fifo.registrar_compra("BTC", 0.1, 350_000, date(2024, 6, 20), "Binance")   # 0.1 BTC a R$350k/BTC → custo R$35k
    return fifo


# ─────────────────────────────────────────────
# Testes de venda simples (1 lote)
# ─────────────────────────────────────────────

def test_venda_simples_lote_inteiro():
    """Vende exatamente o primeiro lote — ganho calculado corretamente."""
    fifo = FIFOCalculator()
    fifo.registrar_compra("BTC", 0.1, 2_000_000, date(2024, 1, 10), "Binance")

    resultado = fifo.calcular_venda("BTC", 0.1, 3_500_000, date(2025, 3, 1))

    assert resultado.receita_total == pytest.approx(350_000.00)
    assert resultado.custo_total == pytest.approx(200_000.00)
    assert resultado.ganho_capital == pytest.approx(150_000.00)
    assert not resultado.e_prejuizo
    assert len(resultado.lotes_consumidos) == 1
    assert resultado.lotes_consumidos[0].quantidade_usada == pytest.approx(0.1)


def test_venda_simples_parcial():
    """Vende metade do lote — saldo restante correto."""
    fifo = FIFOCalculator()
    fifo.registrar_compra("BTC", 0.1, 2_000_000, date(2024, 1, 10), "Binance")

    resultado = fifo.calcular_venda("BTC", 0.04, 3_500_000, date(2025, 3, 1))

    # Custo: 0.04 × 2.000.000 = R$80.000
    # Receita: 0.04 × 3.500.000 = R$140.000
    assert resultado.custo_total == pytest.approx(80_000.00)
    assert resultado.receita_total == pytest.approx(140_000.00)
    assert resultado.ganho_capital == pytest.approx(60_000.00)

    # Saldo restante: 0.06 BTC
    assert fifo.saldo_atual("BTC") == pytest.approx(0.06)


# ─────────────────────────────────────────────
# Testes com múltiplos lotes (cenário do documento)
# ─────────────────────────────────────────────

def test_fifo_consome_multiplos_lotes():
    """
    Cenário exato do documento:
    - Comprou 0.1 BTC em jan/24 a R$200k/BTC  → custo R$20.000
    - Comprou 0.1 BTC em jun/24 a R$350k/BTC  → custo R$35.000
    - Vendeu  0.15 BTC em mar/25 a R$400k/BTC → receita R$60.000

    FIFO:
      0.10 BTC do lote jan → custo R$20.000
      0.05 BTC do lote jun → custo R$17.500
      Custo total: R$37.500
      Ganho: R$22.500
    """
    fifo = fifo_com_btc_jan_jun()
    resultado = fifo.calcular_venda("BTC", 0.15, 400_000, date(2025, 3, 15))  # R$400k/BTC → receita 0.15 × 400k = R$60k

    assert resultado.custo_total == pytest.approx(37_500.00)
    assert resultado.receita_total == pytest.approx(60_000.00)
    assert resultado.ganho_capital == pytest.approx(22_500.00)
    assert len(resultado.lotes_consumidos) == 2

    # Lote 1: 0.10 BTC a R$2.000.000/BTC
    assert resultado.lotes_consumidos[0].data_compra == date(2024, 1, 10)
    assert resultado.lotes_consumidos[0].quantidade_usada == pytest.approx(0.1)
    assert resultado.lotes_consumidos[0].custo == pytest.approx(20_000.00)  # 0.1 × 200k

    # Lote 2: 0.05 BTC a R$3.500.000/BTC
    assert resultado.lotes_consumidos[1].data_compra == date(2024, 6, 20)
    assert resultado.lotes_consumidos[1].quantidade_usada == pytest.approx(0.05)
    assert resultado.lotes_consumidos[1].custo == pytest.approx(17_500.00)  # 0.05 × 350k


def test_saldo_apos_multiplos_lotes():
    """Após vender 0.15 BTC de dois lotes, saldo é 0.05."""
    fifo = fifo_com_btc_jan_jun()
    fifo.calcular_venda("BTC", 0.15, 4_000_000, date(2025, 3, 15))

    assert fifo.saldo_atual("BTC") == pytest.approx(0.05)


def test_fifo_ordem_cronologica():
    """Lotes são consumidos em ordem cronológica, não de inserção."""
    fifo = FIFOCalculator()
    # Inserindo fora de ordem
    fifo.registrar_compra("ETH", 1.0, 10_000, date(2024, 6, 1), "Binance")   # mais recente
    fifo.registrar_compra("ETH", 1.0, 5_000, date(2024, 1, 1), "Binance")    # mais antigo

    resultado = fifo.calcular_venda("ETH", 1.0, 15_000, date(2025, 1, 1))

    # Deve consumir o lote de janeiro (R$5.000), não o de junho (R$10.000)
    assert resultado.custo_total == pytest.approx(5_000.00)
    assert resultado.lotes_consumidos[0].data_compra == date(2024, 1, 1)


# ─────────────────────────────────────────────
# Testes de prejuízo
# ─────────────────────────────────────────────

def test_venda_com_prejuizo():
    """Vende abaixo do custo — ganho é negativo."""
    fifo = FIFOCalculator()
    fifo.registrar_compra("BTC", 0.1, 4_000_000, date(2024, 11, 1), "Binance")  # comprou a R$400k

    resultado = fifo.calcular_venda("BTC", 0.1, 3_000_000, date(2025, 2, 1))  # vendeu a R$300k

    assert resultado.ganho_capital == pytest.approx(-100_000.00)
    assert resultado.e_prejuizo is True


# ─────────────────────────────────────────────
# Testes de saldo zerado
# ─────────────────────────────────────────────

def test_venda_total_zera_saldo():
    """Vender tudo deixa saldo zero."""
    fifo = fifo_com_btc_jan_jun()
    fifo.calcular_venda("BTC", 0.2, 4_000_000, date(2025, 1, 1))

    assert fifo.saldo_atual("BTC") == pytest.approx(0.0)


def test_saldo_insuficiente_levanta_erro():
    """Tentar vender mais do que o saldo disponível levanta SaldoInsuficienteError."""
    fifo = FIFOCalculator()
    fifo.registrar_compra("BTC", 0.1, 2_000_000, date(2024, 1, 1), "Binance")

    with pytest.raises(SaldoInsuficienteError) as exc:
        fifo.calcular_venda("BTC", 0.5, 4_000_000, date(2025, 1, 1))

    assert "saldo disponível" in str(exc.value)


def test_saldo_ativo_inexistente():
    """Saldo de ativo nunca comprado é zero."""
    fifo = FIFOCalculator()
    assert fifo.saldo_atual("SOL") == 0.0


# ─────────────────────────────────────────────
# Testes de custo médio e posição (IRPF)
# ─────────────────────────────────────────────

def test_custo_medio_ponderado():
    """Custo médio ponderado calculado corretamente com dois lotes."""
    fifo = fifo_com_btc_jan_jun()

    # Ambos os lotes intactos: (0.1 × 200k + 0.1 × 350k) / 0.2 = 55k / 0.2 = R$275.000/BTC
    custo_medio = fifo.custo_medio_ponderado("BTC")
    assert custo_medio == pytest.approx(275_000.00)


def test_custo_total_posicao():
    """Custo total da posição atual = soma dos lotes restantes × preço unitário."""
    fifo = fifo_com_btc_jan_jun()

    # 0.1 × 200k + 0.1 × 350k = R$55.000
    custo_total = fifo.custo_total_posicao("BTC")
    assert custo_total == pytest.approx(55_000.00)


def test_custo_total_apos_venda_parcial():
    """Custo total da posição diminui após venda parcial."""
    fifo = fifo_com_btc_jan_jun()
    fifo.calcular_venda("BTC", 0.1, 400_000, date(2025, 1, 1))  # consome lote de jan inteiro

    # Resta apenas o lote de junho: 0.1 × 350k = R$35.000
    custo_total = fifo.custo_total_posicao("BTC")
    assert custo_total == pytest.approx(35_000.00)


def test_ativos_com_saldo():
    """Lista apenas ativos com saldo positivo."""
    fifo = FIFOCalculator()
    fifo.registrar_compra("BTC", 0.1, 300_000, date(2024, 1, 1), "Binance")
    fifo.registrar_compra("ETH", 1.0, 10_000, date(2024, 1, 1), "Binance")

    # Vende todo BTC
    fifo.calcular_venda("BTC", 0.1, 350_000, date(2025, 1, 1))

    ativos = fifo.ativos_com_saldo()
    assert "ETH" in ativos
    assert "BTC" not in ativos


# ─────────────────────────────────────────────
# Testes de case-insensitive
# ─────────────────────────────────────────────

def test_asset_case_insensitive():
    """'btc' e 'BTC' são o mesmo ativo."""
    fifo = FIFOCalculator()
    fifo.registrar_compra("btc", 0.1, 300_000, date(2024, 1, 1), "Binance")

    saldo = fifo.saldo_atual("BTC")
    assert saldo == pytest.approx(0.1)
