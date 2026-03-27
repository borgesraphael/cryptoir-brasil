"""
FIFO Calculator — Custo de aquisição pelo método First In, First Out.

A Receita Federal exige FIFO para calcular o ganho de capital em crypto.
A compra mais antiga é sempre a primeira a ser "consumida" em uma venda.
"""

from dataclasses import dataclass, field
from datetime import date
from collections import defaultdict


class SaldoInsuficienteError(Exception):
    """Levantado quando se tenta vender mais do que o saldo disponível."""
    pass


@dataclass
class Lote:
    """Representa um lote de compra de um ativo."""
    data_compra: date
    quantidade_original: float
    preco_unitario_brl: float
    exchange: str
    quantidade_restante: float = field(init=False)

    def __post_init__(self):
        self.quantidade_restante = self.quantidade_original

    @property
    def custo_total_original(self) -> float:
        return self.quantidade_original * self.preco_unitario_brl

    @property
    def custo_restante(self) -> float:
        return self.quantidade_restante * self.preco_unitario_brl


@dataclass
class LoteConsumido:
    """Registro de quanto de um lote foi usado em uma venda."""
    data_compra: date
    quantidade_usada: float
    preco_unitario_brl: float
    exchange: str

    @property
    def custo(self) -> float:
        return self.quantidade_usada * self.preco_unitario_brl


@dataclass
class ResultadoFIFO:
    """Resultado completo do cálculo FIFO para uma venda."""
    asset: str
    quantidade_vendida: float
    preco_venda_brl: float
    receita_total: float
    custo_total: float
    ganho_capital: float           # pode ser negativo (prejuízo)
    lotes_consumidos: list[LoteConsumido]
    e_prejuizo: bool

    @property
    def aliquota_estimada(self) -> float:
        """Alíquota estimada (apenas para referência — DARF calcula a definitiva)."""
        if self.ganho_capital <= 0:
            return 0.0
        if self.ganho_capital <= 5_000_000:
            return 0.15
        elif self.ganho_capital <= 10_000_000:
            return 0.175
        elif self.ganho_capital <= 30_000_000:
            return 0.20
        return 0.225


class FIFOCalculator:
    """
    Mantém o estado dos lotes de compra por ativo e calcula o custo
    de cada venda usando o método FIFO.

    Uso:
        fifo = FIFOCalculator()
        fifo.registrar_compra("BTC", 0.1, 300000, date(2024, 1, 10), "Mercado Bitcoin")
        resultado = fifo.calcular_venda("BTC", 0.05, 380000, date(2025, 3, 15))
    """

    def __init__(self):
        # chave: símbolo do ativo (ex: "BTC")
        # valor: lista de Lotes em ordem cronológica (FIFO)
        self._lotes: dict[str, list[Lote]] = defaultdict(list)

    def registrar_compra(
        self,
        asset: str,
        quantidade: float,
        preco_unitario_brl: float,
        data_compra: date,
        exchange: str,
    ) -> None:
        """
        Registra uma compra criando um novo lote na fila FIFO.
        Também usado para staking, airdrop e yield (custo = valor de mercado no dia).
        """
        asset = asset.upper()
        lote = Lote(
            data_compra=data_compra,
            quantidade_original=quantidade,
            preco_unitario_brl=preco_unitario_brl,
            exchange=exchange,
        )
        self._lotes[asset].append(lote)
        # Garante ordem cronológica (caso inserções fora de ordem)
        self._lotes[asset].sort(key=lambda l: l.data_compra)

    def calcular_venda(
        self,
        asset: str,
        quantidade_vendida: float,
        preco_venda_brl: float,
        data_venda: date,
    ) -> ResultadoFIFO:
        """
        Processa uma venda usando FIFO e retorna o resultado com memória de cálculo.

        Consome os lotes mais antigos primeiro, atualizando quantidade_restante.
        Levanta SaldoInsuficienteError se não houver saldo suficiente.
        """
        asset = asset.upper()
        saldo = self.saldo_atual(asset)

        if quantidade_vendida > saldo + 1e-8:  # tolerância para float
            raise SaldoInsuficienteError(
                f"Tentativa de vender {quantidade_vendida:.8f} {asset}, "
                f"mas saldo disponível é {saldo:.8f}. "
                f"Verifique se todas as compras foram importadas."
            )

        lotes_consumidos: list[LoteConsumido] = []
        custo_total = 0.0
        quantidade_restante_venda = quantidade_vendida

        for lote in self._lotes[asset]:
            if lote.quantidade_restante <= 1e-10:
                continue  # lote já esgotado
            if quantidade_restante_venda <= 1e-10:
                break    # venda satisfeita

            # Quanto consumir deste lote
            consumir = min(lote.quantidade_restante, quantidade_restante_venda)

            lotes_consumidos.append(LoteConsumido(
                data_compra=lote.data_compra,
                quantidade_usada=consumir,
                preco_unitario_brl=lote.preco_unitario_brl,
                exchange=lote.exchange,
            ))

            custo_total += consumir * lote.preco_unitario_brl
            lote.quantidade_restante -= consumir
            quantidade_restante_venda -= consumir

        receita_total = quantidade_vendida * preco_venda_brl
        ganho_capital = receita_total - custo_total

        return ResultadoFIFO(
            asset=asset,
            quantidade_vendida=quantidade_vendida,
            preco_venda_brl=preco_venda_brl,
            receita_total=receita_total,
            custo_total=custo_total,
            ganho_capital=ganho_capital,
            lotes_consumidos=lotes_consumidos,
            e_prejuizo=ganho_capital < 0,
        )

    def saldo_atual(self, asset: str) -> float:
        """Retorna a quantidade disponível do ativo (soma dos lotes com saldo > 0)."""
        asset = asset.upper()
        return sum(l.quantidade_restante for l in self._lotes.get(asset, []))

    def custo_medio_ponderado(self, asset: str) -> float:
        """
        Custo médio ponderado do saldo restante.
        Usado para calcular o valor a declarar na ficha Bens e Direitos do IRPF.
        """
        asset = asset.upper()
        lotes = [l for l in self._lotes.get(asset, []) if l.quantidade_restante > 1e-10]
        if not lotes:
            return 0.0
        total_quantidade = sum(l.quantidade_restante for l in lotes)
        total_custo = sum(l.quantidade_restante * l.preco_unitario_brl for l in lotes)
        return total_custo / total_quantidade

    def custo_total_posicao(self, asset: str) -> float:
        """Custo total de aquisição do saldo atual (para Bens e Direitos IRPF)."""
        asset = asset.upper()
        return sum(
            l.quantidade_restante * l.preco_unitario_brl
            for l in self._lotes.get(asset, [])
            if l.quantidade_restante > 1e-10
        )

    def ativos_com_saldo(self) -> list[str]:
        """Retorna lista de ativos com saldo positivo."""
        return [a for a, lotes in self._lotes.items()
                if sum(l.quantidade_restante for l in lotes) > 1e-10]
