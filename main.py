#!/usr/bin/env python3
"""
CryptoIR Brasil — CLI
Calcula DARF mensal e gera dados para o IRPF anual a partir do CSV da exchange.

Uso:
  python main.py --csv binance.csv --mes 2025-06
  python main.py --csv mercadobitcoin.csv --ano 2025
  python main.py --csv trades.csv --irpf 2025
  python main.py --csv trades.csv --mes 2025-06 --output relatorio.txt
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from src.csv_parser import parsear_csv, FormatoDesconhecidoError
from src.darf_calculator import DARFCalculator, ResultadoDARF
from src.fifo_calculator import SaldoInsuficienteError
from src.ptax_service import PTAXIndisponivelError
from src.irpf_generator import gerar_irpf, formatar_relatorio_irpf


AVISO_LEGAL = (
    "⚠ Estimativa baseada nas normas da Receita Federal (IN RFB 2.291/2025 e legislação correlata).\n"
    "  Este cálculo não substitui orientação de contador ou advogado tributarista.\n"
    "  Verifique sempre no PGD IRPF oficial antes de enviar sua declaração."
)

SEPARADOR = "═" * 56
LINHA = "─" * 56


# ─────────────────────────────────────────────
# Formatação do relatório
# ─────────────────────────────────────────────

def _brl(valor: float) -> str:
    """Formata valor em BRL com separadores brasileiros."""
    return f"R$ {valor:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(valor: float) -> str:
    return f"{valor * 100:.1f}%"


def formatar_relatorio(resultado: ResultadoDARF, arquivo_csv: str) -> str:
    linhas = []

    linhas.append(SEPARADOR)
    linhas.append(f"  CryptoIR Brasil — DARF {resultado.periodo}")
    linhas.append(SEPARADOR)
    linhas.append(f"  Exchange:  {resultado.exchange_type.capitalize()}")
    linhas.append(f"  Arquivo:   {Path(arquivo_csv).name}")
    linhas.append("")

    # ── Vendas do mês ──
    if resultado.detalhes_vendas:
        linhas.append("VENDAS DO MÊS")
        linhas.append(LINHA)
        for venda in resultado.detalhes_vendas:
            flag = ""
            if venda.e_trade_crypto:
                flag = " [trade crypto→crypto]"
            elif venda.e_conversao_stablecoin:
                flag = " [conversão stablecoin]"
            linhas.append(
                f"  {venda.data.strftime('%d/%m')}  "
                f"{venda.quantidade:.6f} {venda.asset:<6}  →  "
                f"{_brl(venda.receita_brl)}{flag}"
            )
        linhas.append(LINHA)
        linhas.append(f"  Total vendido:       {_brl(resultado.total_vendas)}")
        linhas.append(f"  Limite de isenção:   {_brl(resultado.limite_isencao)}")
        linhas.append("")

        if resultado.e_isento:
            margem = resultado.limite_isencao - resultado.total_vendas
            linhas.append(f"✓ ISENTO — vendas abaixo de {_brl(resultado.limite_isencao)}")
            linhas.append(f"  Você ainda poderia vender mais {_brl(margem)} sem pagar imposto.")
            linhas.append("")
            linhas.append("  Lembre-se: mesmo isento, estas transações devem ser")
            linhas.append("  declaradas no IRPF anual (ficha Bens e Direitos).")
        else:
            excesso = resultado.total_vendas - resultado.limite_isencao
            linhas.append(f"⚠ Limite ultrapassado em {_brl(excesso)}")
    else:
        linhas.append("  Nenhuma venda registrada neste mês.")
        linhas.append("")
        linhas.append(f"✓ ISENTO — nenhuma venda no período.")

    # ── Cálculo do ganho (só se tributável) ──
    if not resultado.e_isento and resultado.detalhes_vendas:
        linhas.append("")
        linhas.append("CÁLCULO DO GANHO DE CAPITAL (FIFO)")
        linhas.append(LINHA)
        for venda in resultado.detalhes_vendas:
            linhas.append(
                f"  {venda.quantidade:.6f} {venda.asset:<6}  "
                f"custo {_brl(venda.custo_brl)}  "
                f"ganho {_brl(venda.ganho_brl)}"
            )
        linhas.append(LINHA)
        linhas.append(f"  Receita total:        {_brl(resultado.total_vendas)}")
        linhas.append(f"  Custo de aquisição:   {_brl(sum(v.custo_brl for v in resultado.detalhes_vendas))}")
        linhas.append(f"  Ganho bruto:          {_brl(resultado.ganho_bruto)}")
        if resultado.prejuizo_compensado > 0:
            linhas.append(f"  Prejuízo compensado:  {_brl(-resultado.prejuizo_compensado)}")
        linhas.append(f"  Ganho líquido:        {_brl(resultado.ganho_liquido)}")

        # ── Resultado ──
        linhas.append("")
        linhas.append("RESULTADO")
        linhas.append(LINHA)
        if resultado.ganho_liquido <= 0:
            linhas.append(f"  Prejuízo apurado.  Nenhum imposto devido.")
            linhas.append(f"  Prejuízo de {_brl(abs(resultado.ganho_liquido))} registrado para compensação futura.")
        else:
            linhas.append(f"  Alíquota:  {_pct(resultado.aliquota)}")
            linhas.append(f"  ► IMPOSTO DEVIDO: {_brl(resultado.imposto_devido)}")
            linhas.append("")
            linhas.append("DARF A PAGAR")
            linhas.append(LINHA)
            linhas.append(f"  Código:              {resultado.codigo_darf}")
            linhas.append(f"  Período apuração:    {resultado.periodo}")
            linhas.append(f"  Vencimento:          {resultado.vencimento.strftime('%d/%m/%Y')}")
            linhas.append(f"  Valor:               {_brl(resultado.imposto_devido)}")

    # ── Rendimentos (staking/airdrop) ──
    if resultado.rendimentos:
        linhas.append("")
        linhas.append("RENDIMENTOS TRIBUTÁVEIS (declarar no IRPF anual)")
        linhas.append(LINHA)
        for r in resultado.rendimentos:
            linhas.append(
                f"  {r.data.strftime('%d/%m')}  {r.tipo:<10}  "
                f"{r.quantidade:.6f} {r.asset:<6}  →  {_brl(r.valor_brl)}"
            )
        linhas.append(LINHA)
        linhas.append(f"  Total rendimentos:   {_brl(resultado.total_rendimentos_brl)}")
        linhas.append("  ℹ Declarar na ficha Rendimentos Tributáveis, código 26.")

    # ── Observações ──
    if resultado.observacoes:
        linhas.append("")
        linhas.append("OBSERVAÇÕES")
        linhas.append(LINHA)
        for obs in resultado.observacoes:
            linhas.append(f"  {obs}")

    linhas.append("")
    linhas.append(LINHA)
    linhas.append(AVISO_LEGAL)
    linhas.append(SEPARADOR)

    return "\n".join(linhas)


# ─────────────────────────────────────────────
# Lógica principal
# ─────────────────────────────────────────────

def executar(args) -> str:
    """Executa o cálculo e retorna o relatório como string."""

    # 1. Parseia CSV
    try:
        transacoes, erros_csv = parsear_csv(args.csv)
    except FileNotFoundError:
        return f"❌ Arquivo não encontrado: {args.csv}"
    except FormatoDesconhecidoError as e:
        return f"❌ {e}"

    if not transacoes:
        return "❌ Nenhuma transação encontrada no arquivo."

    if erros_csv:
        print(f"⚠ {len(erros_csv)} linha(s) ignorada(s) por erro de formato:")
        for erro in erros_csv:
            print(f"   {erro}")
        print()

    # 2. Modo IRPF
    if args.irpf:
        ano = int(args.irpf)
        relatorio = gerar_irpf(transacoes, ano)
        return formatar_relatorio_irpf(relatorio)

    # 3. Modo DARF — prepara o motor fiscal
    motor = DARFCalculator()
    try:
        motor.processar_transacoes(transacoes)
    except SaldoInsuficienteError as e:
        return f"❌ Erro no FIFO: {e}"
    except PTAXIndisponivelError as e:
        return f"❌ {e}"

    relatorios = []

    if args.mes:
        ano, mes = map(int, args.mes.split("-"))
        try:
            resultado = motor.calcular_mes(transacoes, mes, ano)
            relatorios.append(formatar_relatorio(resultado, args.csv))
        except SaldoInsuficienteError as e:
            return f"❌ Erro no FIFO: {e}"

    elif args.ano:
        ano = int(args.ano)
        for mes in range(1, 13):
            txs_mes = [t for t in transacoes if t.data.month == mes and t.data.year == ano]
            if not txs_mes:
                continue
            resultado = motor.calcular_mes(transacoes, mes, ano)
            if resultado.total_vendas > 0 or resultado.rendimentos:
                relatorios.append(formatar_relatorio(resultado, args.csv))

        if not relatorios:
            relatorios.append(f"Nenhuma transação com vendas encontrada em {ano}.")

    return "\n\n".join(relatorios)


def main():
    parser = argparse.ArgumentParser(
        description="CryptoIR Brasil — Calculadora de DARF para criptomoedas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py --csv binance.csv --mes 2025-06
  python main.py --csv mercadobitcoin.csv --ano 2025
  python main.py --csv trades.csv --irpf 2025
  python main.py --csv trades.csv --irpf 2025 --output irpf_2025.txt
        """
    )
    parser.add_argument("--csv", required=True, help="Caminho para o arquivo CSV da exchange")
    parser.add_argument("--mes", help="DARF: mês de apuração no formato YYYY-MM (ex: 2025-06)")
    parser.add_argument("--ano", help="DARF: ano completo — processa todos os meses (ex: 2025)")
    parser.add_argument("--irpf", help="IRPF: ano-base da declaração (ex: 2025 para declarar em 2026)")
    parser.add_argument("--output", help="Salvar relatório em arquivo .txt")

    args = parser.parse_args()

    # Valida argumentos mutuamente exclusivos
    modos = [x for x in [args.mes, args.ano, args.irpf] if x]
    if not modos:
        parser.error("Informe um modo: --mes 2025-06, --ano 2025 ou --irpf 2025.")
    if len(modos) > 1:
        parser.error("Use apenas um modo por vez: --mes, --ano ou --irpf.")

    # Valida formato do IRPF
    if args.irpf:
        try:
            assert 2010 <= int(args.irpf) <= 2100
        except (ValueError, AssertionError):
            parser.error(f"Ano inválido: '{args.irpf}'. Use apenas o ano (ex: 2025).")

    # Valida formato do mês
    if args.mes:
        try:
            ano, mes = args.mes.split("-")
            assert 1 <= int(mes) <= 12 and int(ano) >= 2010
        except (ValueError, AssertionError):
            parser.error(f"Formato de mês inválido: '{args.mes}'. Use YYYY-MM (ex: 2025-06).")

    relatorio = executar(args)
    print(relatorio)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(relatorio)
        print(f"\n  Relatório salvo em: {args.output}")


if __name__ == "__main__":
    main()
