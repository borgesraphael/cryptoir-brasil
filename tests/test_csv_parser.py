"""
Testes do CSV Parser.
"""

import pytest
import tempfile
import os
from pathlib import Path
from datetime import datetime
from src.csv_parser import (
    parsear_csv,
    parsear_binance_br,
    parsear_mercado_bitcoin,
    detectar_formato,
    FormatoDesconhecidoError,
)

SAMPLES = Path(__file__).parent.parent / "data" / "samples"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def csv_temp(conteudo: str) -> str:
    """Cria um arquivo CSV temporário com o conteúdo dado."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(conteudo)
    f.close()
    return f.name


# ─────────────────────────────────────────────
# Detecção de formato
# ─────────────────────────────────────────────

def test_detecta_binance_br():
    assert detectar_formato(SAMPLES / "binance_sample.csv") == "binance_br"


def test_detecta_mercado_bitcoin():
    assert detectar_formato(SAMPLES / "mercadobitcoin_sample.csv") == "mercado_bitcoin"


def test_formato_desconhecido():
    caminho = csv_temp("coluna1,coluna2,coluna3\n1,2,3\n")
    try:
        with pytest.raises(FormatoDesconhecidoError):
            detectar_formato(caminho)
    finally:
        os.unlink(caminho)


def test_arquivo_nao_encontrado():
    with pytest.raises(FileNotFoundError):
        detectar_formato("/caminho/que/nao/existe.csv")


def test_csv_vazio_levanta_erro():
    caminho = csv_temp("")
    try:
        with pytest.raises(FormatoDesconhecidoError):
            detectar_formato(caminho)
    finally:
        os.unlink(caminho)


# ─────────────────────────────────────────────
# Parser Binance Brasil
# ─────────────────────────────────────────────

def test_binance_quantidade_correta():
    txs, erros = parsear_binance_br(SAMPLES / "binance_sample.csv")
    assert len(txs) == 6  # 3 compras + 3 vendas no sample completo
    assert not erros


def test_binance_compra_normalizada():
    txs, _ = parsear_binance_br(SAMPLES / "binance_sample.csv")
    compra = txs[0]  # primeira linha = compra de 0.1 BTC em jan/24

    assert compra.tipo == "BUY"
    assert compra.asset_in == "BTC"
    assert compra.amount_in == pytest.approx(0.1)
    assert compra.asset_out == "BRL"
    assert compra.price_brl == pytest.approx(300_000.0)
    assert compra.fee_brl == pytest.approx(75.0)
    assert compra.exchange == "Binance Brasil"
    assert compra.exchange_type == "nacional"


def test_binance_venda_normalizada():
    txs, _ = parsear_binance_br(SAMPLES / "binance_sample.csv")
    # Primeira venda = índice 3 (após 3 compras)
    venda = next(t for t in txs if t.tipo == "SELL")

    assert venda.tipo == "SELL"
    assert venda.asset_out == "BTC"
    assert venda.amount_out == pytest.approx(0.005)
    assert venda.asset_in == "BRL"
    assert venda.amount_in == pytest.approx(1750.0)
    assert venda.price_brl == pytest.approx(350_000.0)


def test_binance_ordenado_por_data():
    txs, _ = parsear_binance_br(SAMPLES / "binance_sample.csv")
    datas = [t.data for t in txs]
    assert datas == sorted(datas)


def test_binance_linha_invalida_ignorada():
    conteudo = (
        "Date(UTC),Pair,Side,Price,Executed,Amount,Fee\n"
        "DATA_INVALIDA,BTCBRL,BUY,300000.00,0.01 BTC,3000.00 BRL,7.50 BRL\n"
        "2025-06-20 09:00:00,BTCBRL,SELL,380000.00,0.08 BTC,30400.00 BRL,76.00 BRL\n"
    )
    caminho = csv_temp(conteudo)
    try:
        txs, erros = parsear_binance_br(caminho)
        assert len(txs) == 1   # só a linha válida
        assert len(erros) == 1  # um erro registrado
    finally:
        os.unlink(caminho)


def test_binance_somente_cabecalho_retorna_lista_vazia():
    conteudo = "Date(UTC),Pair,Side,Price,Executed,Amount,Fee\n"
    caminho = csv_temp(conteudo)
    try:
        txs, erros = parsear_binance_br(caminho)
        assert txs == []
        assert erros == []
    finally:
        os.unlink(caminho)


# ─────────────────────────────────────────────
# Parser Mercado Bitcoin
# ─────────────────────────────────────────────

def test_mb_quantidade_correta():
    txs, erros = parsear_mercado_bitcoin(SAMPLES / "mercadobitcoin_sample.csv")
    assert len(txs) == 4
    assert not erros


def test_mb_compra_normalizada():
    txs, _ = parsear_mercado_bitcoin(SAMPLES / "mercadobitcoin_sample.csv")
    compra = txs[0]

    assert compra.tipo == "BUY"
    assert compra.asset_in == "ETH"
    assert compra.amount_in == pytest.approx(1.0)
    assert compra.price_brl == pytest.approx(10_400.0)
    assert compra.exchange == "Mercado Bitcoin"
    assert compra.exchange_type == "nacional"


def test_mb_venda_normalizada():
    txs, _ = parsear_mercado_bitcoin(SAMPLES / "mercadobitcoin_sample.csv")
    venda = next(t for t in txs if t.tipo == "SELL")

    assert venda.asset_out == "ETH"
    assert venda.amount_out == pytest.approx(0.5)
    assert venda.asset_in == "BRL"
    assert venda.amount_in == pytest.approx(7_000.0)


def test_mb_staking_normalizado():
    txs, _ = parsear_mercado_bitcoin(SAMPLES / "mercadobitcoin_sample.csv")
    staking = next(t for t in txs if t.tipo == "STAKING")

    assert staking.asset_in == "ETH"
    assert staking.amount_in == pytest.approx(0.04)


def test_mb_operacao_desconhecida_ignorada():
    conteudo = (
        "Data/Hora,Operação,Moeda,Quantidade,Preço Unitário,Total BRL,Taxa\n"
        "2025-06-01 10:00:00,OperacaoEstranha,BTC,0.01,300000.00,3000.00,7.50\n"
        "2025-06-02 10:00:00,Compra,BTC,0.01,300000.00,3000.00,7.50\n"
    )
    caminho = csv_temp(conteudo)
    try:
        txs, erros = parsear_mercado_bitcoin(caminho)
        assert len(txs) == 1
        assert len(erros) == 1
    finally:
        os.unlink(caminho)


# ─────────────────────────────────────────────
# Função autodetect (parsear_csv)
# ─────────────────────────────────────────────

def test_autodetect_binance():
    txs, _ = parsear_csv(SAMPLES / "binance_sample.csv")
    assert len(txs) == 6
    assert all(t.exchange == "Binance Brasil" for t in txs)


def test_autodetect_mercado_bitcoin():
    txs, _ = parsear_csv(SAMPLES / "mercadobitcoin_sample.csv")
    assert len(txs) == 4
    assert all(t.exchange == "Mercado Bitcoin" for t in txs)
