"""
CSV Parser — Lê exports de exchanges e normaliza para formato interno.

Exchanges suportadas:
- Binance Brasil (Trade History — colunas em inglês)
- Binance Transaction History (colunas em português — formato mais comum)
- Mercado Bitcoin

Produz uma lista de Transacao com formato unificado independente da origem.
"""

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
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
CABECALHO_BINANCE_HISTORICO = {"ID do Usuário", "Tempo", "Conta", "Operação", "Moeda", "Alterar"}

def detectar_formato(caminho_csv: str | Path) -> str:
    """
    Lê o cabeçalho do CSV e identifica o formato.

    Retorna: "binance_br", "binance_historico" ou "mercado_bitcoin"
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
    if CABECALHO_BINANCE_HISTORICO.issubset(colunas):
        return "binance_historico"

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
# Parser Binance Transaction History (português)
# ─────────────────────────────────────────────

def _parse_data_binance_historico(s: str) -> datetime:
    """
    Parse de data no formato 'YY-MM-DD HH:MM:SS' (2 dígitos de ano).
    Python interpreta 00-68 como 2000-2068, então '25' → 2025.
    Também aceita 'YYYY-MM-DD HH:MM:SS' como fallback.
    """
    s = s.strip()
    try:
        return datetime.strptime(s, "%y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def parsear_binance_historico(caminho_csv: str | Path) -> tuple[list[Transacao], list[str]]:
    """
    Lê CSV do Binance Transaction History (colunas em português).

    Reconstrói transações a partir de linhas pareadas:
    - 'Binance Convert': par com timestamps a até 5 segundos (ex: BRL→ETH)
    - 'Buy Crypto With Fiat': par com Deposit BRL negativo anterior (até 30s)
    - 'Deposit' positivo em crypto: TRANSFER_IN
    - 'Withdrawal': TRANSFER_OUT

    Retorna (transações, lista de erros/avisos).
    """
    transacoes: list[Transacao] = []
    erros: list[str] = []
    caminho = Path(caminho_csv)

    # ── Leitura e normalização de todas as linhas ──
    linhas: list[dict] = []
    with open(caminho, "r", encoding="utf-8-sig") as f:
        leitor = csv.DictReader(f)
        for n, linha in enumerate(leitor, start=2):
            tempo_str = linha.get("Tempo", "").strip()
            operacao = linha.get("Operação", "").strip()
            moeda = linha.get("Moeda", "").strip().upper()
            alterar_str = linha.get("Alterar", "").strip()

            if not tempo_str or not operacao or not moeda or not alterar_str:
                continue

            try:
                data = _parse_data_binance_historico(tempo_str)
                alterar = float(alterar_str)
            except ValueError:
                erros.append(f"Linha {n}: erro ao converter data ou valor — ignorada.")
                continue

            linhas.append({
                "n": n,
                "data": data,
                "operacao": operacao,
                "moeda": moeda,
                "alterar": alterar,
                "raw": str(dict(linha)),
                "usado": False,
            })

    # Ordena por timestamp para facilitar o pareamento
    linhas.sort(key=lambda x: x["data"])

    _JANELA_CONVERT = timedelta(seconds=5)
    _JANELA_FIAT = timedelta(seconds=60)

    # ── Passagem principal: reconstrói transações ──
    for i, row in enumerate(linhas):
        if row["usado"]:
            continue

        operacao = row["operacao"]

        # Negative BRL Deposit: aguarda ser reclamado por Buy Crypto With Fiat
        if operacao == "Deposit" and row["moeda"] == "BRL" and row["alterar"] < 0:
            continue

        # ── Binance Convert: par positivo + negativo dentro de 5 segundos ──
        if operacao == "Binance Convert":
            row["usado"] = True
            par_idx = None
            for j in range(i + 1, min(i + 20, len(linhas))):
                other = linhas[j]
                if (not other["usado"]
                        and other["operacao"] == "Binance Convert"
                        and abs((other["data"] - row["data"]).total_seconds()) <= _JANELA_CONVERT.seconds):
                    par_idx = j
                    break

            if par_idx is None:
                erros.append(f"Linha {row['n']}: 'Binance Convert' sem par — ignorada.")
                continue

            other = linhas[par_idx]
            other["usado"] = True

            # positivo = ativo recebido, negativo = ativo gasto
            if row["alterar"] > 0:
                recv, spend = row, other
            else:
                recv, spend = other, row

            recv_asset = recv["moeda"]
            recv_amount = abs(recv["alterar"])
            spend_asset = spend["moeda"]
            spend_amount = abs(spend["alterar"])

            if spend_asset == "BRL":
                # BRL → crypto: compra
                tipo = "BUY"
                price_brl = spend_amount / recv_amount if recv_amount else 0.0
            elif recv_asset == "BRL":
                # crypto → BRL: venda
                tipo = "SELL"
                price_brl = recv_amount / spend_amount if spend_amount else 0.0
            else:
                # crypto → crypto (ex: USDT → BTC): evento tributável
                tipo = "TRADE"
                price_brl = 0.0  # custo em BRL calculado via PTAX no DARFCalculator

            transacoes.append(Transacao(
                data=recv["data"],
                tipo=tipo,
                asset_out=spend_asset,
                amount_out=spend_amount,
                asset_in=recv_asset,
                amount_in=recv_amount,
                price_brl=price_brl,
                fee_brl=0.0,
                exchange="Binance",
                exchange_type="estrangeira",
                raw_line=recv["raw"],
            ))

        # ── Buy Crypto With Fiat: emparelha com Deposit BRL negativo anterior ──
        elif operacao == "Buy Crypto With Fiat":
            row["usado"] = True
            crypto_asset = row["moeda"]
            crypto_amount = abs(row["alterar"])

            brl_row = None
            for j in range(i - 1, max(i - 30, -1), -1):
                other = linhas[j]
                if (not other["usado"]
                        and other["operacao"] == "Deposit"
                        and other["moeda"] == "BRL"
                        and other["alterar"] < 0
                        and abs((row["data"] - other["data"]).total_seconds()) <= _JANELA_FIAT.seconds):
                    brl_row = other
                    other["usado"] = True
                    break

            if brl_row is None or crypto_amount == 0:
                erros.append(
                    f"Linha {row['n']}: 'Buy Crypto With Fiat' sem Deposit BRL correspondente — ignorada."
                )
                continue

            brl_amount = abs(brl_row["alterar"])
            price_brl = brl_amount / crypto_amount

            transacoes.append(Transacao(
                data=row["data"],
                tipo="BUY",
                asset_out="BRL",
                amount_out=brl_amount,
                asset_in=crypto_asset,
                amount_in=crypto_amount,
                price_brl=price_brl,
                fee_brl=0.0,
                exchange="Binance",
                exchange_type="estrangeira",
                raw_line=row["raw"],
            ))

        # ── Deposit positivo em crypto: transferência recebida ──
        elif operacao == "Deposit":
            row["usado"] = True
            if row["alterar"] > 0 and row["moeda"] != "BRL":
                transacoes.append(Transacao(
                    data=row["data"],
                    tipo="TRANSFER_IN",
                    asset_out=row["moeda"],
                    amount_out=0.0,
                    asset_in=row["moeda"],
                    amount_in=row["alterar"],
                    price_brl=0.0,
                    fee_brl=0.0,
                    exchange="Binance",
                    exchange_type="estrangeira",
                    raw_line=row["raw"],
                ))
            # Deposit BRL positivo = depósito fiat → não é evento tributável, ignorar

        # ── Withdrawal: saque/transferência para fora ──
        elif operacao == "Withdrawal":
            row["usado"] = True
            if row["alterar"] < 0 and row["moeda"] != "BRL":
                transacoes.append(Transacao(
                    data=row["data"],
                    tipo="TRANSFER_OUT",
                    asset_out=row["moeda"],
                    amount_out=abs(row["alterar"]),
                    asset_in=row["moeda"],
                    amount_in=0.0,
                    price_brl=0.0,
                    fee_brl=0.0,
                    exchange="Binance",
                    exchange_type="estrangeira",
                    raw_line=row["raw"],
                ))

        # ── Staking / Cashback / Distribution ──
        elif operacao in ("Staking Rewards", "Simple Earn Flexible Interest",
                          "Simple Earn Locked Rewards", "Referral Kickback",
                          "Distribution", "Airdrop Assets"):
            row["usado"] = True
            if row["alterar"] > 0:
                transacoes.append(Transacao(
                    data=row["data"],
                    tipo="STAKING",
                    asset_out=row["moeda"],
                    amount_out=0.0,
                    asset_in=row["moeda"],
                    amount_in=row["alterar"],
                    price_brl=0.0,
                    fee_brl=0.0,
                    exchange="Binance",
                    exchange_type="estrangeira",
                    raw_line=row["raw"],
                ))

        else:
            row["usado"] = True
            erros.append(f"Linha {row['n']}: operação '{operacao}' não reconhecida — ignorada.")

    # Negative BRL Deposits não reclamados: ignorar silenciosamente
    for row in linhas:
        if not row["usado"]:
            row["usado"] = True
            # Apenas loga se não for o caso esperado de BRL negativo não pareado
            if not (row["operacao"] == "Deposit" and row["moeda"] == "BRL" and row["alterar"] < 0):
                erros.append(f"Linha {row['n']}: linha não processada ({row['operacao']}) — ignorada.")

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
    elif formato == "binance_historico":
        return parsear_binance_historico(caminho_csv)
    raise FormatoDesconhecidoError(f"Formato '{formato}' sem parser implementado.")
