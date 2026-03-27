# CryptoIR Brasil — CLI

Calculadora de DARF para investidores em criptomoedas no Brasil.

Lê o histórico de transações exportado da sua exchange e calcula:
- Se você deve DARF no mês informado (e quanto)
- O ganho de capital usando o método FIFO exigido pela Receita Federal
- A isenção de R$35.000/mês para exchanges nacionais
- Rendimentos tributáveis de staking e airdrop

> **Aviso legal:** Este software é uma estimativa baseada nas normas da Receita Federal
> (IN RFB 2.291/2025 e legislação correlata). Não substitui orientação de contador
> ou advogado tributarista.

---

## Requisitos

- Python 3.11+
- Arquivo CSV exportado da Binance Brasil ou Mercado Bitcoin

---

## Instalação

```bash
git clone <repositório>
cd cryptoir-cli

# Criar ambiente virtual
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Instalar dependências
pip install -r requirements.txt
```

---

## Como exportar o CSV da sua exchange

### Binance Brasil
1. Acesse [Binance.com](https://www.binance.com) → **Carteira** → **Spot**
2. Clique em **Histórico de Transações**
3. Selecione o período desejado
4. Clique em **Exportar** → formato CSV
5. Salve o arquivo e use o caminho no comando abaixo

### Mercado Bitcoin
1. Acesse [MercadoBitcoin.com.br](https://www.mercadobitcoin.com.br) → **Extrato**
2. Selecione o período desejado
3. Clique em **Exportar CSV**

---

## Uso

### Calcular DARF de um mês específico

```bash
python main.py --csv seu_historico.csv --mes 2025-06
```

### Calcular todos os meses de um ano

```bash
python main.py --csv seu_historico.csv --ano 2025
```

### Salvar o relatório em arquivo

```bash
python main.py --csv seu_historico.csv --mes 2025-06 --output darf_junho.txt
```

---

## Exemplo de output

```
════════════════════════════════════════════════════════
  CryptoIR Brasil — DARF 06/2025
════════════════════════════════════════════════════════
  Exchange:  Nacional
  Arquivo:   binance_sample.csv

VENDAS DO MÊS
────────────────────────────────────────────────────────
  20/06  0.080000 BTC     →  R$    30.400,00
  22/06  0.500000 ETH     →  R$     6.000,00
────────────────────────────────────────────────────────
  Total vendido:       R$    36.400,00
  Limite de isenção:   R$    35.000,00

⚠ Limite ultrapassado em R$     1.400,00

CÁLCULO DO GANHO DE CAPITAL (FIFO)
────────────────────────────────────────────────────────
  0.080000 BTC     custo R$    24.000,00  ganho R$     6.400,00
  0.500000 ETH     custo R$     5.200,00  ganho R$       800,00
────────────────────────────────────────────────────────
  Receita total:        R$    36.400,00
  Custo de aquisição:   R$    29.200,00
  Ganho bruto:          R$     7.200,00
  Ganho líquido:        R$     7.200,00

RESULTADO
────────────────────────────────────────────────────────
  Alíquota:  15.0%
  ► IMPOSTO DEVIDO: R$     1.080,00

DARF A PAGAR
────────────────────────────────────────────────────────
  Código:              4600
  Período apuração:    06/2025
  Vencimento:          31/07/2025
  Valor:               R$     1.080,00
════════════════════════════════════════════════════════
```

---

## Regras fiscais aplicadas

| Situação | Regra |
|---|---|
| Vendas ≤ R$35.000/mês (exchange nacional) | Isento — sem DARF |
| Vendas > R$35.000/mês (exchange nacional) | 15% sobre o lucro |
| Troca crypto→crypto (ex: BTC→ETH) | Evento tributável — conta para o limite |
| Conversão para stablecoin (ex: BTC→USDT) | Evento tributável — conta para o limite |
| Transferência entre carteiras próprias | Não tributável |
| Staking / Airdrop recebido | Renda tributável (declarar no IRPF anual) |
| Exchange estrangeira (Bybit, KuCoin, etc.) | Sem isenção — 15% flat sobre lucro anual |
| Prejuízo em um mês | Compensa ganho de meses futuros |

**Método de custo:** FIFO (First In, First Out) — exigido pela Receita Federal.
**Cotação:** PTAX do Banco Central na data da operação.
**Código DARF:** 4600
**Vencimento:** último dia útil do mês seguinte à apuração.

---

## Testes

```bash
# Rodar todos os testes
python -m pytest tests/ -v

# Rodar com o CSV de exemplo
python main.py --csv data/samples/binance_sample.csv --mes 2025-06
python main.py --csv data/samples/mercadobitcoin_sample.csv --mes 2025-07
```

---

## Estrutura do projeto

```
cryptoir-cli/
├── src/
│   ├── ptax_service.py      # Cotação PTAX do Banco Central (com cache)
│   ├── fifo_calculator.py   # Cálculo de custo de aquisição (FIFO)
│   ├── csv_parser.py        # Leitura de CSV da Binance e Mercado Bitcoin
│   └── darf_calculator.py   # Motor fiscal — regras de DARF e isenção
├── tests/                   # 57 testes unitários
├── data/
│   ├── samples/             # CSVs de exemplo para teste
│   └── ptax_cache.json      # Cache local de cotações do BCB
├── main.py                  # CLI principal
└── requirements.txt
```

---

## Limitações desta versão (CLI)

- Suporta apenas Binance Brasil e Mercado Bitcoin via CSV
- Não gera o PDF do DARF (apenas informa os dados para preenchimento manual)
- Não conecta diretamente às exchanges via API
- Não rastreia cold wallets (Ledger, Trezor)
- Não gera o arquivo XML para o GCAP/PGD IRPF

Estas funcionalidades fazem parte da Fase 2 (produto web completo).

---

## Feedback e problemas

Se encontrar algum erro no cálculo ou comportamento inesperado, abra uma issue
com o CSV anonimizado (remova valores reais se desejar) e o output obtido vs. esperado.
