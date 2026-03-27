"""
CSV Parser — Lê exports de exchanges e normaliza para formato interno.

Exchanges suportadas:
- Binance Brasil
- Mercado Bitcoin

Produz uma lista de Transacao com formato unificado independente da origem.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class FormatoDesconhecidoError(Exception):
    """Levantado quando o arquivo CSV não corresponde a nenhum formato suportado."""
    pass


class CSVVazioError(Exception):
    """Levantado quando o arquivo não contém nenhuma transação válida."""
    pass


@dataclass
class Transacao:
    """Formato interno unificado — independente da exchange de origem."""
    data: datetime
    tipo: str               # BUY, SELL, TRADE, STAKING, TRANSFER_IN, TRANSFER_OUT, FEE
    asset_out: str          # ativo que saiu (ex: "BTC" em venda, "BRL" em compra)
    amount_out: float
    asset_in: str           # ativo que entrou
    amount_in: float
    price_brl: float        # preço unitário do crypto em BRL
    fee_brl: float          # taxa em BRL
    exchange: str           # nome da exchange
    exchange_type: str      # "nacional" ou "estrangeira"
    raw_line: str           # linha original para auditoria


# ─────────────────────────────────────────────
# Detecção de formato
# ─────────────────────────────────────────────

CABECALHO_BINANCE_BR = {"Date(UTC)", "Pair", "Side", "Price", "Executed", "Amount", "Fee"}
CABECALHO_MB = {"Data/Hora", "Operação", "Moeda", "Quantidade", "Preço Unitário", "Total BRL", "Taxa"}

def detectar_formato(caminho_csv: str | Path) -> str:
    """
    Lê o cabeçalho do CSV e identifica o formato.

    Retorna: "binance_br" ou "mercado_bitcoin"
    Levanta: FormatoDesconhecidoError se não reconhecer
    """
    caminho = Path(caminho_csv)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_csv}")

    with open(caminho, "r", encoding="utf-8-sig") as f:
        leitor = csv.reader(f)
        cabecalho_linha = next(leitor, None)

    if cabecalho_linha is None:
        raise FormatoDesconhecidoError("Arquivo CSV está vazio ou sem cabeçalho.")

    colunas = {col.strip() for col in cabecalho_linha}

    if CABECALHO_BINANCE_BR.issubset(colunas):
        return "binance_br"
    if CABECALHO_MB.issubset(colunas):
        return "mercado_bitcoin"

    raise FormatoDesconhecidoError(
        f"Formato não suportado. Colunas encontradas: {sorted(colunas)}. "
        "Use CSV exportado da Binance Brasil ou do Mercado Bitcoin."
    )


# ─────────────────────────────────────────────
# Utilitários
# ─────────────────────────────────────────────

def _float_br(valor: str) -> float:
    """
    Converte número para float.
    Suporta formato brasileiro com vírgula ('1.234,56') e formato padrão ('1234.56').
    """
    valor = valor.strip()
    if "," in valor and "." in valor:
        # Formato BR: 1.234,56 → remove ponto de milhar, troca vírgula por ponto
        valor = valor.replace(".", "").replace(",", ".")
    elif "," in valor:
        # Só vírgula: 1234,56 → troca por ponto
        valor = valor.replace(",", ".")
    # Se só tem ponto ou sem separador → float() direto
    return float(valor)


def _extrair_quantidade_e_ativo(texto: str) -> tuple[float, str]:
    """
    Extrai quantidade e símbolo de strings como '0.01000000 BTC' ou '3500.00 BRL'.
    Retorna (quantidade, símbolo).
    """
    partes = texto.strip().split()
    if len(partes) != 2:
        raise ValueError(f"Formato inesperado: '{texto}'")
    return float(partes[0]), partes[1].upper()


MAPA_TIPOS_MB = {
    "Compra": "BUY",
    "Venda": "SELL",
    "Depósito": "TRANSFER_IN",
    "Saque": "TRANSFER_OUT",
    "Bônus": "STAKING",
    "Bonus": "STAKING",
    "Staking": "STAKING",
}


# ─────────────────────────────────────────────
# Parser Binance Brasil
# ─────────────────────────────────────────────

def _parsear_linha_binance(linha: dict, n: int, erros: list) -> Transacao | None:
    """Processa uma linha do CSV da Binance Brasil."""
    try:
        data = datetime.strptime(linha["Date(UTC)"].strip(), "%Y-%m-%d %H:%M:%S")
        side = linha["Side"].strip().upper()
        pair = linha["Pair"].strip().upper()
        price = float(linha["Price"].strip())

        quantidade_exec, asset_exec = _extrair_quantidade_e_ativo(linha["Executed"])
        quantidade_amount, asset_amount = _extrair_quantidade_e_ativo(linha["Amount"])
        fee_qtd, fee_ativo = _extrair_quantidade_e_ativo(linha["Fee"])

        # Taxa em BRL
        if fee_ativo == "BRL":
            fee_brl = fee_qtd
        else:
            # Taxa em crypto — estimar em BRL pelo preço da operação
            fee_brl = fee_qtd * price

        if side == "BUY":
            # Compra: gastou BRL, recebeu crypto
            return Transacao(
                data=data, tipo="BUY",
                asset_out=asset_amount,  # BRL saiu
                amount_out=quantidade_amount,
                asset_in=asset_exec,     # crypto entrou
                amount_in=quantidade_exec,
                price_brl=price,
                fee_brl=fee_brl,
                exchange="Binance Brasil",
                exchange_type="nacional",
                raw_line=str(linha),
            )
        elif side == "SELL":
            # Venda: saiu crypto, entrou BRL
            return Transacao(
                data=data, tipo="SELL",
                asset_out=asset_exec,    # crypto saiu
                amount_out=quantidade_exec,
                asset_in=asset_amount,   # BRL entrou
                amount_in=quantidade_amount,
                price_brl=price,
                fee_brl=fee_brl,
                exchange="Binance Brasil",
                exchange_type="nacional",
                raw_line=str(linha),
            )
        else:
            erros.append(f"Linha {n}: tipo '{side}' não reconhecido — ignorado.")
            return None

    except (ValueError, KeyError) as e:
        erros.append(f"Linha {n}: erro ao processar ({e}) — ignorada.")
        return None


def parsear_binance_br(caminho_csv: str | Path) -> tuple[list[Transacao], list[str]]:
    """
    Lê CSV da Binance Brasil e retorna (transações, lista de erros).
    Erros não abortam o processo — linhas problemáticas são ignoradas.
    """
    transacoes: list[Transacao] = []
    erros: list[str] = []
    caminho = Path(caminho_csv)

    with open(caminho, "r", encoding="utf-8-sig") as f:
        leitor = csv.DictReader(f)
        for n, linha in enumerate(leitor, start=2):  # linha 1 = cabeçalho
            tx = _parsear_linha_binance(linha, n, erros)
            if tx:
                transacoes.append(tx)

    return sorted(transacoes, key=lambda t: t.data), erros


# ─────────────────────────────────────────────
# Parser Mercado Bitcoin
# ─────────────────────────────────────────────

def _parsear_linha_mb(linha: dict, n: int, erros: list) -> Transacao | None:
    """Processa uma linha do CSV do Mercado Bitcoin."""
    try:
        data = datetime.strptime(linha["Data/Hora"].strip(), "%Y-%m-%d %H:%M:%S")
        operacao = linha["Operação"].strip()
        moeda = linha["Moeda"].strip().upper()
        quantidade = _float_br(linha["Quantidade"])
        preco_unitario = _float_br(linha["Preço Unitário"])
        total_brl = _float_br(linha["Total BRL"])
        taxa = _float_br(linha["Taxa"])

        tipo = MAPA_TIPOS_MB.get(operacao)
        if tipo is None:
            erros.append(f"Linha {n}: operação '{operacao}' não reconhecida — ignorada.")
            return None

        if tipo == "BUY":
            return Transacao(
                data=data, tipo="BUY",
                asset_out="BRL", amount_out=total_brl,
                asset_in=moeda, amount_in=quantidade,
                price_brl=preco_unitario,
                fee_brl=taxa,
                exchange="Mercado Bitcoin",
                exchange_type="nacional",
                raw_line=str(linha),
            )
        elif tipo == "SELL":
            return Transacao(
                data=data, tipo="SELL",
                asset_out=moeda, amount_out=quantidade,
                asset_in="BRL", amount_in=total_brl,
                price_brl=preco_unitario,
                fee_brl=taxa,
                exchange="Mercado Bitcoin",
                exchange_type="nacional",
                raw_line=str(linha),
            )
        elif tipo in ("TRANSFER_IN", "TRANSFER_OUT", "STAKING"):
            return Transacao(
                data=data, tipo=tipo,
                asset_out=moeda if tipo == "TRANSFER_OUT" else "BRL",
                amount_out=quantidade if tipo == "TRANSFER_OUT" else 0,
                asset_in=moeda if tipo in ("TRANSFER_IN", "STAKING") else "BRL",
                amount_in=quantidade if tipo in ("TRANSFER_IN", "STAKING") else 0,
                price_brl=preco_unitario,
                fee_brl=taxa,
                exchange="Mercado Bitcoin",
                exchange_type="nacional",
                raw_line=str(linha),
            )
        return None

    except (ValueError, KeyError) as e:
        erros.append(f"Linha {n}: erro ao processar ({e}) — ignorada.")
        return None


def parsear_mercado_bitcoin(caminho_csv: str | Path) -> tuple[list[Transacao], list[str]]:
    """
    Lê CSV do Mercado Bitcoin e retorna (transações, lista de erros).
    """
    transacoes: list[Transacao] = []
    erros: list[str] = []
    caminho = Path(caminho_csv)

    with open(caminho, "r", encoding="utf-8-sig") as f:
        leitor = csv.DictReader(f)
        for n, linha in enumerate(leitor, start=2):
            tx = _parsear_linha_mb(linha, n, erros)
            if tx:
                transacoes.append(tx)

    return sorted(transacoes, key=lambda t: t.data), erros


# ─────────────────────────────────────────────
# Função principal — autodetecta o formato
# ─────────────────────────────────────────────

def parsear_csv(caminho_csv: str | Path) -> tuple[list[Transacao], list[str]]:
    """
    Detecta o formato automaticamente e parseia o arquivo.
    Retorna (transações, lista de avisos/erros).
    """
    formato = detectar_formato(caminho_csv)
    if formato == "binance_br":
        return parsear_binance_br(caminho_csv)
    elif formato == "mercado_bitcoin":
        return parsear_mercado_bitcoin(caminho_csv)
    raise FormatoDesconhecidoError(f"Formato '{formato}' sem parser implementado.")
