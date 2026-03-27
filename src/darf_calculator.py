"""
Motor DARF — Cálculo do imposto de ganho de capital em criptomoedas.

Aplica as regras da Receita Federal brasileira:
- Isenção de R$35.000/mês para exchanges nacionais
- Alíquotas progressivas sobre o lucro
- Compensação de prejuízos de meses anteriores
- Tratamento diferenciado para exchanges estrangeiras
- Staking e airdrop como renda (não ganho de capital)
"""

from dataclasses import dataclass, field
from datetime import date
from dateutil.relativedelta import relativedelta
from dateutil. easter import easter
import calendar

from .csv_parser import Transacao
from .fifo_calculator import FIFOCalculator, ResultadoFIFO


# ─────────────────────────────────────────────
# Constantes fiscais
# ─────────────────────────────────────────────

LIMITE_ISENCAO_MENSAL = 35_000.00   # R$35.000 (exchanges nacionais)
CODIGO_DARF = "4600"

ALIQUOTAS = [
    (5_000_000,   0.15),
    (10_000_000,  0.175),
    (30_000_000,  0.20),
    (float("inf"), 0.225),
]

TIPOS_VENDA_TRIBUTAVEL = {"SELL", "TRADE"}
TIPOS_RENDA = {"STAKING", "YIELD", "AIRDROP"}
TIPOS_TRANSFERENCIA = {"TRANSFER_IN", "TRANSFER_OUT"}
TIPOS_COMPRA = {"BUY"}

STABLECOINS = {"USDT", "USDC", "BUSD", "DAI", "BRLA", "BRZ", "TUSD", "USDP", "GUSD"}


# ─────────────────────────────────────────────
# Dataclasses de resultado
# ─────────────────────────────────────────────

@dataclass
class DetalheVenda:
    """Detalhe de uma venda individual com seu cálculo FIFO."""
    data: date
    asset: str
    quantidade: float
    preco_venda_brl: float
    receita_brl: float
    custo_brl: float
    ganho_brl: float
    e_trade_crypto: bool        # True = troca crypto→crypto
    e_conversao_stablecoin: bool


@dataclass
class RendimentoTributavel:
    """Staking, airdrop ou yield recebido — vai para IRPF, não DARF."""
    data: date
    tipo: str           # STAKING, AIRDROP, YIELD
    asset: str
    quantidade: float
    valor_brl: float    # valor de mercado no dia do recebimento
    exchange: str


@dataclass
class ResultadoDARF:
    """Resultado completo do cálculo DARF para um mês/ano."""
    mes: int
    ano: int
    exchange_type: str                  # "nacional" ou "estrangeira"

    # Vendas
    total_vendas: float
    detalhes_vendas: list[DetalheVenda]

    # Isenção
    e_isento: bool
    limite_isencao: float

    # Ganho de capital
    ganho_bruto: float
    prejuizo_compensado: float
    ganho_liquido: float

    # Imposto
    aliquota: float
    imposto_devido: float

    # Rendimentos (staking/airdrop — para IRPF, não DARF)
    rendimentos: list[RendimentoTributavel] = field(default_factory=list)

    # Metadados
    vencimento: date = field(default=None)
    codigo_darf: str = CODIGO_DARF
    observacoes: list[str] = field(default_factory=list)

    @property
    def periodo(self) -> str:
        return f"{self.mes:02d}/{self.ano}"

    @property
    def total_rendimentos_brl(self) -> float:
        return sum(r.valor_brl for r in self.rendimentos)


# ─────────────────────────────────────────────
# Utilitários de datas
# ─────────────────────────────────────────────

def _feriados_nacionais(ano: int) -> set[date]:
    """Retorna feriados nacionais fixos e móveis do ano."""
    pascoa = easter(ano)
    feriados = {
        date(ano, 1, 1),                            # Ano Novo
        date(ano, 4, 21),                           # Tiradentes
        date(ano, 5, 1),                            # Dia do Trabalho
        date(ano, 9, 7),                            # Independência
        date(ano, 10, 12),                          # Nossa Senhora Aparecida
        date(ano, 11, 2),                           # Finados
        date(ano, 11, 15),                          # Proclamação da República
        date(ano, 12, 25),                          # Natal
        pascoa - relativedelta(days=2),             # Sexta-feira Santa
        pascoa,                                     # Páscoa
        pascoa - relativedelta(days=47),            # Carnaval (terça)
        pascoa - relativedelta(days=48),            # Carnaval (segunda)
        pascoa + relativedelta(days=60),            # Corpus Christi
    }
    return feriados


def _e_dia_util(d: date) -> bool:
    return d.weekday() < 5 and d not in _feriados_nacionais(d.year)


def calcular_vencimento_darf(mes: int, ano: int) -> date:
    """
    Retorna o vencimento do DARF: último dia útil do mês SEGUINTE.
    """
    # Avança para o mês seguinte
    if mes == 12:
        mes_venc, ano_venc = 1, ano + 1
    else:
        mes_venc, ano_venc = mes + 1, ano

    # Último dia do mês seguinte
    ultimo_dia = calendar.monthrange(ano_venc, mes_venc)[1]
    d = date(ano_venc, mes_venc, ultimo_dia)

    # Volta até encontrar dia útil
    while not _e_dia_util(d):
        d = d - relativedelta(days=1)

    return d


# ─────────────────────────────────────────────
# Classificação de eventos
# ─────────────────────────────────────────────

def _e_venda_tributavel(tx: Transacao) -> bool:
    """
    Retorna True se a transação é um evento de venda tributável.
    Inclui: venda por BRL, troca crypto→crypto, conversão para stablecoin.
    """
    if tx.tipo not in TIPOS_VENDA_TRIBUTAVEL:
        return False

    # Venda por BRL — sempre tributável
    if tx.asset_in == "BRL":
        return True

    # Conversão para stablecoin — também tributável
    if tx.asset_in.upper() in STABLECOINS:
        return True

    # Troca crypto→crypto — tributável
    if tx.asset_in not in ("BRL",) and tx.asset_out not in ("BRL",):
        return True

    return False


def _calcular_aliquota(ganho: float) -> float:
    """Retorna a alíquota aplicável ao ganho de capital."""
    for limite, aliquota in ALIQUOTAS:
        if ganho <= limite:
            return aliquota
    return 0.225


# ─────────────────────────────────────────────
# Motor Principal
# ─────────────────────────────────────────────

class DARFCalculator:
    """
    Calcula o DARF mensal a partir de uma lista de transações.

    Mantém o histórico de prejuízos para compensação futura.
    """

    def __init__(self):
        self.fifo = FIFOCalculator()
        self._prejuizos_acumulados_nacional: float = 0.0
        self._prejuizos_acumulados_estrangeira: float = 0.0

    def processar_transacoes(self, transacoes: list[Transacao]) -> None:
        """
        Pré-processa todas as transações de compra para popular o FIFO.
        Deve ser chamado com o histórico COMPLETO antes de calcular qualquer mês.
        """
        compras = [t for t in transacoes if t.tipo in TIPOS_COMPRA or
                   (t.tipo == "TRADE" and t.asset_in not in ("BRL",))]

        for tx in sorted(compras, key=lambda t: t.data):
            if tx.tipo == "BUY":
                self.fifo.registrar_compra(
                    asset=tx.asset_in,
                    quantidade=tx.amount_in,
                    preco_unitario_brl=tx.price_brl,
                    data_compra=tx.data.date(),
                    exchange=tx.exchange,
                )
            elif tx.tipo == "TRADE":
                # Lado "compra" do trade: registra o ativo recebido
                preco_unit_in = (tx.amount_out * tx.price_brl) / tx.amount_in if tx.amount_in > 0 else 0
                self.fifo.registrar_compra(
                    asset=tx.asset_in,
                    quantidade=tx.amount_in,
                    preco_unitario_brl=preco_unit_in,
                    data_compra=tx.data.date(),
                    exchange=tx.exchange,
                )

        # Staking e airdrop também criam lotes (custo = valor de mercado no dia)
        for tx in sorted(transacoes, key=lambda t: t.data):
            if tx.tipo in TIPOS_RENDA and tx.asset_in not in ("BRL",):
                self.fifo.registrar_compra(
                    asset=tx.asset_in,
                    quantidade=tx.amount_in,
                    preco_unitario_brl=tx.price_brl,
                    data_compra=tx.data.date(),
                    exchange=tx.exchange,
                )

    def calcular_mes(
        self,
        transacoes: list[Transacao],
        mes: int,
        ano: int,
    ) -> ResultadoDARF:
        """
        Calcula o DARF para um mês específico.

        Assume que processar_transacoes() já foi chamado com o histórico completo.
        """
        # Filtra transações do mês
        txs_mes = [
            t for t in transacoes
            if t.data.month == mes and t.data.year == ano
        ]

        # Separa nacionais e estrangeiras
        txs_nacionais = [t for t in txs_mes if t.exchange_type == "nacional"]
        txs_estrangeiras = [t for t in txs_mes if t.exchange_type == "estrangeira"]

        # Processa nacionais (tem isenção mensal)
        resultado_nacional = self._calcular_nacional(txs_nacionais, mes, ano)

        # Rendimentos do mês (staking, airdrop)
        rendimentos = self._extrair_rendimentos(txs_mes)
        resultado_nacional.rendimentos = rendimentos

        return resultado_nacional

    def _calcular_nacional(
        self,
        transacoes: list[Transacao],
        mes: int,
        ano: int,
    ) -> ResultadoDARF:
        """Calcula DARF para exchanges nacionais com regra de isenção R$35k."""
        detalhes_vendas: list[DetalheVenda] = []
        total_vendas = 0.0
        ganho_bruto = 0.0
        observacoes: list[str] = []

        for tx in sorted(transacoes, key=lambda t: t.data):
            if not _e_venda_tributavel(tx):
                continue

            receita = tx.amount_out * tx.price_brl
            total_vendas += receita

            # Calcula custo FIFO
            try:
                resultado_fifo: ResultadoFIFO = self.fifo.calcular_venda(
                    asset=tx.asset_out,
                    quantidade_vendida=tx.amount_out,
                    preco_venda_brl=tx.price_brl,
                    data_venda=tx.data.date(),
                )
                custo = resultado_fifo.custo_total
                ganho = resultado_fifo.ganho_capital
            except Exception as e:
                observacoes.append(f"⚠ Aviso: {e}")
                custo = 0.0
                ganho = receita  # conservador: assume custo zero

            ganho_bruto += ganho

            e_trade = tx.tipo == "TRADE"
            e_stablecoin = tx.asset_in.upper() in STABLECOINS

            if e_trade:
                observacoes.append(
                    f"ℹ Troca {tx.asset_out}→{tx.asset_in} em {tx.data.date()} "
                    f"é evento tributável (receita R${receita:,.2f})."
                )
            if e_stablecoin:
                observacoes.append(
                    f"ℹ Conversão {tx.asset_out}→{tx.asset_in} (stablecoin) "
                    f"é evento tributável."
                )

            detalhes_vendas.append(DetalheVenda(
                data=tx.data.date(),
                asset=tx.asset_out,
                quantidade=tx.amount_out,
                preco_venda_brl=tx.price_brl,
                receita_brl=receita,
                custo_brl=custo,
                ganho_brl=ganho,
                e_trade_crypto=e_trade,
                e_conversao_stablecoin=e_stablecoin,
            ))

        # Aplica isenção
        e_isento = total_vendas <= LIMITE_ISENCAO_MENSAL

        if e_isento:
            imposto = 0.0
            aliquota = 0.0
            prejuizo_compensado = 0.0
            ganho_liquido = ganho_bruto
        else:
            # Compensa prejuízo acumulado
            if ganho_bruto > 0 and self._prejuizos_acumulados_nacional > 0:
                prejuizo_compensado = min(ganho_bruto, self._prejuizos_acumulados_nacional)
                self._prejuizos_acumulados_nacional -= prejuizo_compensado
                if prejuizo_compensado > 0:
                    observacoes.append(
                        f"ℹ Prejuízo compensado: R${prejuizo_compensado:,.2f}"
                    )
            else:
                prejuizo_compensado = 0.0

            ganho_liquido = ganho_bruto - prejuizo_compensado

            if ganho_liquido > 0:
                aliquota = _calcular_aliquota(ganho_liquido)
                imposto = ganho_liquido * aliquota
            else:
                aliquota = 0.0
                imposto = 0.0

        # Acumula prejuízo para meses futuros
        if ganho_bruto < 0:
            self._prejuizos_acumulados_nacional += abs(ganho_bruto)
            observacoes.append(
                f"ℹ Prejuízo de R${abs(ganho_bruto):,.2f} registrado para compensação futura."
            )

        vencimento = calcular_vencimento_darf(mes, ano)

        return ResultadoDARF(
            mes=mes,
            ano=ano,
            exchange_type="nacional",
            total_vendas=total_vendas,
            detalhes_vendas=detalhes_vendas,
            e_isento=e_isento,
            limite_isencao=LIMITE_ISENCAO_MENSAL,
            ganho_bruto=ganho_bruto,
            prejuizo_compensado=prejuizo_compensado,
            ganho_liquido=ganho_liquido,
            aliquota=aliquota,
            imposto_devido=imposto,
            vencimento=vencimento,
            observacoes=observacoes,
        )

    def _extrair_rendimentos(self, transacoes: list[Transacao]) -> list[RendimentoTributavel]:
        """Extrai staking, airdrop e yield como rendimentos tributáveis."""
        rendimentos = []
        for tx in transacoes:
            if tx.tipo in TIPOS_RENDA:
                valor_brl = tx.amount_in * tx.price_brl
                rendimentos.append(RendimentoTributavel(
                    data=tx.data.date(),
                    tipo=tx.tipo,
                    asset=tx.asset_in,
                    quantidade=tx.amount_in,
                    valor_brl=valor_brl,
                    exchange=tx.exchange,
                ))
        return rendimentos

    def calcular_ano_estrangeira(
        self,
        transacoes: list[Transacao],
        ano: int,
    ) -> ResultadoDARF:
        """
        Calcula imposto anual para exchanges estrangeiras.
        Sem isenção, alíquota flat de 15%, apuração anual.
        """
        txs_ano = [
            t for t in transacoes
            if t.data.year == ano and t.exchange_type == "estrangeira"
        ]

        detalhes_vendas: list[DetalheVenda] = []
        total_vendas = 0.0
        ganho_bruto = 0.0
        observacoes: list[str] = []

        observacoes.append(
            "ℹ Exchange estrangeira: sem isenção mensal. "
            "Imposto recolhido na Declaração de Ajuste Anual (DAA), não em DARF mensal."
        )

        for tx in sorted(txs_ano, key=lambda t: t.data):
            if not _e_venda_tributavel(tx):
                continue

            receita = tx.amount_out * tx.price_brl
            total_vendas += receita

            try:
                resultado_fifo = self.fifo.calcular_venda(
                    asset=tx.asset_out,
                    quantidade_vendida=tx.amount_out,
                    preco_venda_brl=tx.price_brl,
                    data_venda=tx.data.date(),
                )
                custo = resultado_fifo.custo_total
                ganho = resultado_fifo.ganho_capital
            except Exception as e:
                observacoes.append(f"⚠ Aviso: {e}")
                custo = 0.0
                ganho = receita

            ganho_bruto += ganho
            detalhes_vendas.append(DetalheVenda(
                data=tx.data.date(),
                asset=tx.asset_out,
                quantidade=tx.amount_out,
                preco_venda_brl=tx.price_brl,
                receita_brl=receita,
                custo_brl=custo,
                ganho_brl=ganho,
                e_trade_crypto=tx.tipo == "TRADE",
                e_conversao_stablecoin=tx.asset_in.upper() in STABLECOINS,
            ))

        ganho_liquido = ganho_bruto  # sem compensação entre anos para estrangeira
        aliquota = 0.15 if ganho_liquido > 0 else 0.0
        imposto = ganho_liquido * aliquota if ganho_liquido > 0 else 0.0

        return ResultadoDARF(
            mes=12,   # apuração anual
            ano=ano,
            exchange_type="estrangeira",
            total_vendas=total_vendas,
            detalhes_vendas=detalhes_vendas,
            e_isento=False,
            limite_isencao=0.0,
            ganho_bruto=ganho_bruto,
            prejuizo_compensado=0.0,
            ganho_liquido=ganho_liquido,
            aliquota=aliquota,
            imposto_devido=imposto,
            vencimento=date(ano + 1, 4, 30),  # DAA, aproximado
            observacoes=observacoes,
            rendimentos=self._extrair_rendimentos(txs_ano),
        )
