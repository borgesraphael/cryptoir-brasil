"""
IRPF Generator — Gera os dados para preenchimento da declaração anual.

Produz três fichas:
1. Bens e Direitos (grupo 08) — posição de cada ativo em 31/12
2. Rendimentos Tributáveis (código 26) — staking, airdrop, yield
3. Renda Variável — ganhos/perdas mensais de exchanges nacionais

REGRA CRÍTICA: Bens e Direitos usa CUSTO DE AQUISIÇÃO, nunca valor de mercado.
Se comprou 1 BTC por R$300k e hoje vale R$600k, declara R$300k.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from collections import defaultdict

from .csv_parser import Transacao
from .fifo_calculator import FIFOCalculator
from .darf_calculator import DARFCalculator, LIMITE_ISENCAO_MENSAL, TIPOS_RENDA


# ─────────────────────────────────────────────
# Mapeamento fiscal de ativos
# ─────────────────────────────────────────────

STABLECOINS = {"USDT", "USDC", "BUSD", "DAI", "BRLA", "BRZ", "TUSD", "USDP", "GUSD"}

CNPJ_EXCHANGES = {
    "Binance Brasil":     "18.600.620/0001-10",
    "Mercado Bitcoin":    "18.322.231/0001-06",
    "Foxbit":             "18.512.581/0001-19",
    "Novadax":            "30.731.633/0001-02",
    "Coinext":            "28.696.293/0001-78",
}

def _codigo_bem(asset: str) -> str:
    """Retorna o código do bem no grupo 08 conforme a Receita Federal."""
    asset = asset.upper()
    if asset == "BTC":
        return "01"
    if asset in STABLECOINS:
        return "03"
    return "02"  # demais criptomoedas


def _nome_bem(asset: str) -> str:
    nomes = {
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "SOL": "Solana",
        "BNB": "BNB",
        "USDT": "Tether (USDT)",
        "USDC": "USD Coin (USDC)",
    }
    return nomes.get(asset.upper(), asset.upper())


# ─────────────────────────────────────────────
# Dataclasses de resultado
# ─────────────────────────────────────────────

@dataclass
class ItemBensEDireitos:
    codigo_grupo: str = "08"
    codigo_bem: str = ""        # 01=BTC, 02=outras, 03=stablecoins
    asset: str = ""
    discriminacao: str = ""
    situacao_ano_anterior: float = 0.0   # custo em 31/12/(ano-1)
    situacao_ano_atual: float = 0.0      # custo em 31/12/ano
    quantidade_atual: float = 0.0
    exchange: str = ""


@dataclass
class RendimentoIRPF:
    tipo: str           # STAKING, AIRDROP, YIELD
    asset: str
    quantidade_total: float
    valor_brl: float    # valor de mercado na data do recebimento
    exchange: str


@dataclass
class ResultadoMensalRV:
    mes: int
    ano: int
    total_vendas: float
    ganho_liquido: float   # pode ser negativo
    imposto_recolhido: float
    e_isento: bool

    @property
    def periodo(self) -> str:
        meses = ["Jan","Fev","Mar","Abr","Mai","Jun",
                 "Jul","Ago","Set","Out","Nov","Dez"]
        return f"{meses[self.mes - 1]}/{self.ano}"


@dataclass
class RelatorioIRPF:
    ano: int
    bens_e_direitos: list[ItemBensEDireitos] = field(default_factory=list)
    rendimentos: list[RendimentoIRPF] = field(default_factory=list)
    renda_variavel: list[ResultadoMensalRV] = field(default_factory=list)
    observacoes: list[str] = field(default_factory=list)

    @property
    def total_rendimentos_brl(self) -> float:
        return sum(r.valor_brl for r in self.rendimentos)

    @property
    def total_ganhos_rv(self) -> float:
        return sum(r.ganho_liquido for r in self.renda_variavel if r.ganho_liquido > 0)

    @property
    def total_imposto_darf(self) -> float:
        return sum(r.imposto_recolhido for r in self.renda_variavel)


# ─────────────────────────────────────────────
# Funções auxiliares de FIFO por data
# ─────────────────────────────────────────────

def _construir_fifo_ate(transacoes: list[Transacao], data_limite: date) -> FIFOCalculator:
    """
    Constrói um FIFOCalculator processando apenas transações até data_limite.
    Usado para capturar a posição em 31/12 de um dado ano.
    """
    fifo = FIFOCalculator()
    motor = DARFCalculator.__new__(DARFCalculator)
    motor.fifo = fifo
    motor._prejuizos_acumulados_nacional = 0.0
    motor._prejuizos_acumulados_estrangeira = 0.0

    txs_ate = [t for t in transacoes if t.data.date() <= data_limite]
    motor.processar_transacoes(txs_ate)

    # Processa as vendas para consumir os lotes corretamente
    from .darf_calculator import _e_venda_tributavel
    for tx in sorted(txs_ate, key=lambda t: t.data):
        if _e_venda_tributavel(tx):
            try:
                fifo.calcular_venda(
                    asset=tx.asset_out,
                    quantidade_vendida=tx.amount_out,
                    preco_venda_brl=tx.price_brl,
                    data_venda=tx.data.date(),
                )
            except Exception:
                pass  # saldo insuficiente ignorado para snapshot

    return fifo


def _posicao_em(fifo: FIFOCalculator) -> dict[str, dict]:
    """Retorna a posição atual de todos os ativos com saldo."""
    resultado = {}
    for asset in fifo.ativos_com_saldo():
        resultado[asset] = {
            "quantidade": fifo.saldo_atual(asset),
            "custo_total": fifo.custo_total_posicao(asset),
        }
    return resultado


# ─────────────────────────────────────────────
# Gerador principal
# ─────────────────────────────────────────────

def gerar_irpf(transacoes: list[Transacao], ano: int) -> RelatorioIRPF:
    """
    Gera o relatório completo para a declaração IRPF do ano informado.

    ano = ano-base (ex: 2025 para a declaração entregue em 2026)
    """
    relatorio = RelatorioIRPF(ano=ano)

    # ── 1. Bens e Direitos ──
    relatorio.bens_e_direitos = _gerar_bens_e_direitos(transacoes, ano)

    # ── 2. Rendimentos tributáveis (staking, airdrop, yield) ──
    relatorio.rendimentos = _gerar_rendimentos(transacoes, ano)

    # ── 3. Renda Variável (exchanges nacionais, mês a mês) ──
    relatorio.renda_variavel = _gerar_renda_variavel(transacoes, ano)

    # ── 4. Observações ──
    if any(r.valor_brl > 0 for r in relatorio.rendimentos):
        relatorio.observacoes.append(
            "Rendimentos de staking/airdrop devem ser declarados na ficha "
            "Rendimentos Tributáveis Recebidos de PJ, código 26."
        )

    txs_estrangeiras = [t for t in transacoes
                        if t.data.year == ano and t.exchange_type == "estrangeira"]
    if txs_estrangeiras:
        relatorio.observacoes.append(
            "Você tem transações em exchanges estrangeiras. "
            "Declare-as na ficha Bens no Exterior."
        )

    return relatorio


def _gerar_bens_e_direitos(
    transacoes: list[Transacao],
    ano: int,
) -> list[ItemBensEDireitos]:
    """Calcula a posição de cada ativo em 31/12 do ano anterior e do ano atual."""

    data_31dec_anterior = date(ano - 1, 12, 31)
    data_31dec_atual = date(ano, 12, 31)

    fifo_anterior = _construir_fifo_ate(transacoes, data_31dec_anterior)
    fifo_atual = _construir_fifo_ate(transacoes, data_31dec_atual)

    posicao_anterior = _posicao_em(fifo_anterior)
    posicao_atual = _posicao_em(fifo_atual)

    # União de todos os ativos que apareceram em qualquer dos dois anos
    todos_ativos = set(posicao_anterior.keys()) | set(posicao_atual.keys())
    todos_ativos.discard("BRL")

    # Mapeia cada ativo para a exchange principal (última vista)
    exchange_por_ativo: dict[str, str] = {}
    for tx in sorted(transacoes, key=lambda t: t.data):
        if tx.asset_in not in ("BRL",) and tx.asset_in.upper() not in STABLECOINS or True:
            if tx.asset_in not in ("BRL",):
                exchange_por_ativo[tx.asset_in.upper()] = tx.exchange
            if tx.asset_out not in ("BRL",):
                exchange_por_ativo[tx.asset_out.upper()] = tx.exchange

    itens = []
    for asset in sorted(todos_ativos):
        asset_upper = asset.upper()
        pos_ant = posicao_anterior.get(asset_upper, {"quantidade": 0.0, "custo_total": 0.0})
        pos_atu = posicao_atual.get(asset_upper, {"quantidade": 0.0, "custo_total": 0.0})

        # Só inclui se teve saldo em algum dos dois anos
        if pos_ant["custo_total"] == 0.0 and pos_atu["custo_total"] == 0.0:
            continue

        exchange = exchange_por_ativo.get(asset_upper, "exchange não identificada")
        cnpj = CNPJ_EXCHANGES.get(exchange, "")
        cnpj_str = f" CNPJ {cnpj}" if cnpj else ""

        qtd_atual = pos_atu["quantidade"]
        discriminacao = (
            f"{qtd_atual:.8f} {asset_upper} — "
            f"custodiado em {exchange}{cnpj_str}"
        )

        itens.append(ItemBensEDireitos(
            codigo_grupo="08",
            codigo_bem=_codigo_bem(asset_upper),
            asset=asset_upper,
            discriminacao=discriminacao,
            situacao_ano_anterior=round(pos_ant["custo_total"], 2),
            situacao_ano_atual=round(pos_atu["custo_total"], 2),
            quantidade_atual=qtd_atual,
            exchange=exchange,
        ))

    # Ordena: BTC primeiro, depois alfabético
    itens.sort(key=lambda i: (i.codigo_bem, i.asset))
    return itens


def _gerar_rendimentos(
    transacoes: list[Transacao],
    ano: int,
) -> list[RendimentoIRPF]:
    """Agrega staking, airdrop e yield do ano como rendimentos tributáveis."""

    # agrupa por tipo + asset + exchange
    grupos: dict[tuple, dict] = defaultdict(lambda: {"quantidade": 0.0, "valor_brl": 0.0})

    for tx in transacoes:
        if tx.data.year != ano:
            continue
        if tx.tipo not in TIPOS_RENDA:
            continue
        if tx.asset_in in ("BRL",):
            continue

        chave = (tx.tipo, tx.asset_in.upper(), tx.exchange)
        grupos[chave]["quantidade"] += tx.amount_in
        grupos[chave]["valor_brl"] += tx.amount_in * tx.price_brl

    return [
        RendimentoIRPF(
            tipo=tipo,
            asset=asset,
            quantidade_total=round(dados["quantidade"], 8),
            valor_brl=round(dados["valor_brl"], 2),
            exchange=exchange,
        )
        for (tipo, asset, exchange), dados in sorted(grupos.items())
        if dados["valor_brl"] > 0
    ]


def _gerar_renda_variavel(
    transacoes: list[Transacao],
    ano: int,
) -> list[ResultadoMensalRV]:
    """
    Calcula ganhos/perdas mensais de exchanges nacionais para a ficha Renda Variável.
    Usa um DARFCalculator fresh para ter os prejuízos acumulados corretos.
    """
    motor = DARFCalculator()
    motor.processar_transacoes(transacoes)

    resultados = []
    for mes in range(1, 13):
        txs_mes = [t for t in transacoes
                   if t.data.year == ano and t.data.month == mes
                   and t.exchange_type == "nacional"]
        if not txs_mes:
            continue

        resultado = motor.calcular_mes(transacoes, mes, ano)

        if resultado.total_vendas == 0 and not resultado.rendimentos:
            continue

        resultados.append(ResultadoMensalRV(
            mes=mes,
            ano=ano,
            total_vendas=resultado.total_vendas,
            ganho_liquido=resultado.ganho_liquido,
            imposto_recolhido=resultado.imposto_devido,
            e_isento=resultado.e_isento,
        ))

    return resultados


# ─────────────────────────────────────────────
# Formatação do relatório
# ─────────────────────────────────────────────

SEPARADOR = "═" * 56
LINHA = "─" * 56


def _brl(valor: float) -> str:
    return f"R$ {valor:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_relatorio_irpf(relatorio: RelatorioIRPF) -> str:
    linhas = []
    ano_declaracao = relatorio.ano + 1

    linhas.append(SEPARADOR)
    linhas.append(f"  CryptoIR Brasil — IRPF {ano_declaracao} (ano-base {relatorio.ano})")
    linhas.append(SEPARADOR)
    linhas.append("")
    linhas.append("  ⚠ ATENÇÃO: Os valores abaixo são CUSTOS DE AQUISIÇÃO.")
    linhas.append("  Nunca informe o valor de mercado atual dos ativos.")
    linhas.append("")

    # ── Bens e Direitos ──
    linhas.append("FICHA BENS E DIREITOS — GRUPO 08 (Criptoativos)")
    linhas.append(LINHA)

    if not relatorio.bens_e_direitos:
        linhas.append("  Nenhum ativo identificado.")
    else:
        for item in relatorio.bens_e_direitos:
            linhas.append(f"  Código {item.codigo_bem} — {_nome_bem(item.asset)} ({item.asset})")
            linhas.append(f"  Discriminação: \"{item.discriminacao}\"")
            linhas.append(f"  Situação 31/12/{relatorio.ano - 1}:  {_brl(item.situacao_ano_anterior)}")
            linhas.append(f"  Situação 31/12/{relatorio.ano}:  {_brl(item.situacao_ano_atual)}")
            linhas.append("")

    # ── Rendimentos ──
    if relatorio.rendimentos:
        linhas.append("RENDIMENTOS TRIBUTÁVEIS — CÓDIGO 26")
        linhas.append(LINHA)
        linhas.append("  Informe na ficha: Rendimentos Tributáveis Recebidos de PJ")
        linhas.append("  Código: 26 — Outros")
        linhas.append("")
        for r in relatorio.rendimentos:
            linhas.append(
                f"  {r.tipo:<10} {r.asset:<6}  "
                f"{r.quantidade_total:.6f} unid.  →  {_brl(r.valor_brl)}"
                f"  ({r.exchange})"
            )
        linhas.append(LINHA)
        linhas.append(f"  Total rendimentos:  {_brl(relatorio.total_rendimentos_brl)}")
        linhas.append("")

    # ── Renda Variável ──
    if relatorio.renda_variavel:
        linhas.append("RENDA VARIÁVEL — GANHOS EM CRIPTOATIVOS (exchanges nacionais)")
        linhas.append(LINHA)
        linhas.append("  Informe na ficha: Renda Variável → Operações em Bolsa")
        linhas.append("")

        for rv in relatorio.renda_variavel:
            if rv.e_isento:
                linhas.append(
                    f"  {rv.periodo:<10}  "
                    f"Vendas: {_brl(rv.total_vendas)}  "
                    f"✓ Isento"
                )
            elif rv.ganho_liquido > 0:
                linhas.append(
                    f"  {rv.periodo:<10}  "
                    f"Ganho: {_brl(rv.ganho_liquido)}  "
                    f"DARF: {_brl(rv.imposto_recolhido)}"
                )
            else:
                linhas.append(
                    f"  {rv.periodo:<10}  "
                    f"Prejuízo: {_brl(rv.ganho_liquido)}"
                )

        linhas.append(LINHA)
        if relatorio.total_ganhos_rv > 0:
            linhas.append(f"  Total ganhos tributáveis:  {_brl(relatorio.total_ganhos_rv)}")
            linhas.append(f"  Total DARF recolhido:      {_brl(relatorio.total_imposto_darf)}")
        else:
            linhas.append("  Nenhum ganho tributável no ano.")
        linhas.append("")

    # ── Observações ──
    if relatorio.observacoes:
        linhas.append("ATENÇÃO")
        linhas.append(LINHA)
        for obs in relatorio.observacoes:
            linhas.append(f"  ℹ {obs}")
        linhas.append("")

    linhas.append(LINHA)
    linhas.append("⚠ Estimativa baseada nas normas da Receita Federal.")
    linhas.append("  Verifique no PGD IRPF oficial antes de enviar.")
    linhas.append(SEPARADOR)

    return "\n".join(linhas)
