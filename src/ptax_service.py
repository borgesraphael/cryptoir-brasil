"""
PTAX Service — Cotações oficiais do Banco Central do Brasil.

Busca a cotação PTAX para uma data específica, com:
- Cache local em JSON para evitar chamadas repetidas
- Fallback automático para o último dia útil anterior
- Suporte a USD, EUR e outras moedas
"""

import json
import httpx
from datetime import date, timedelta
from pathlib import Path

CACHE_PATH = Path(__file__).parent.parent / "data" / "ptax_cache.json"
MAX_TENTATIVAS_FALLBACK = 7  # busca até 7 dias atrás (cobre feriados prolongados)


class PTAXIndisponivelError(Exception):
    """Levantado quando não é possível obter cotação para nenhum dia próximo."""
    pass


def _carregar_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _chave_cache(data: date, moeda: str) -> str:
    return f"{data.isoformat()}_{moeda.upper()}"


def _buscar_na_api(data: date, moeda: str) -> dict | None:
    """
    Chama a API PTAX do BCB para uma data e moeda específicas.
    Retorna dict com 'compra' e 'venda', ou None se não houver cotação.
    """
    data_formatada = data.strftime("%m-%d-%Y")  # formato exigido pela API do BCB

    if moeda.upper() == "USD":
        url = (
            "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
            f"CotacaoDolarDia(dataCotacao=@data)"
            f"?@data='{data_formatada}'&$format=json&$top=1"
        )
    else:
        url = (
            "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
            f"CotacaoMoedaDia(moeda=@moeda,dataCotacao=@data)"
            f"?@moeda='{moeda.upper()}'&@data='{data_formatada}'&$format=json&$top=1"
        )

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
            response.raise_for_status()
            dados = response.json()

        valores = dados.get("value", [])
        if not valores:
            return None  # sem cotação para esta data (feriado/fim de semana)

        cotacao = valores[0]
        return {
            "compra": cotacao.get("cotacaoCompra"),
            "venda": cotacao.get("cotacaoVenda"),
            "fonte": "bcb_api",
        }

    except (httpx.HTTPError, KeyError, ValueError):
        return None


def buscar_ptax(data: date, moeda: str = "USD") -> dict:
    """
    Retorna a cotação PTAX para uma data e moeda, com cache e fallback.

    Se a data não tiver cotação (fim de semana, feriado), usa o último
    dia útil anterior. Máximo de 7 tentativas.

    Retorna:
        {"compra": 5.74, "venda": 5.75, "data_efetiva": date(...), "fonte": "bcb_api"}

    Levanta:
        PTAXIndisponivelError se não encontrar cotação em nenhum dia próximo.
    """
    cache = _carregar_cache()
    cache_modificado = False

    data_tentativa = data

    for tentativa in range(MAX_TENTATIVAS_FALLBACK):
        chave = _chave_cache(data_tentativa, moeda)

        # 1. Verifica cache local
        if chave in cache:
            resultado = cache[chave].copy()
            resultado["data_efetiva"] = data_tentativa
            if tentativa > 0:
                resultado["aviso"] = (
                    f"Cotação de {data.isoformat()} não disponível. "
                    f"Usando {data_tentativa.isoformat()} (último dia útil anterior)."
                )
            return resultado

        # 2. Busca na API do BCB
        cotacao = _buscar_na_api(data_tentativa, moeda)

        if cotacao:
            cache[chave] = cotacao
            cache_modificado = True
            resultado = cotacao.copy()
            resultado["data_efetiva"] = data_tentativa
            if tentativa > 0:
                resultado["aviso"] = (
                    f"Cotação de {data.isoformat()} não disponível. "
                    f"Usando {data_tentativa.isoformat()} (último dia útil anterior)."
                )
            _salvar_cache(cache)
            return resultado

        # 3. Tenta o dia anterior
        data_tentativa = data_tentativa - timedelta(days=1)

    if cache_modificado:
        _salvar_cache(cache)

    raise PTAXIndisponivelError(
        f"Não foi possível obter cotação PTAX para {data.isoformat()} ({moeda}). "
        f"Tentados os últimos {MAX_TENTATIVAS_FALLBACK} dias. Verifique sua conexão."
    )


def buscar_ptax_venda(data: date, moeda: str = "USD") -> float:
    """
    Atalho: retorna apenas a cotação de venda (mais usada para conversão fiscal).
    A Receita Federal usa a cotação de venda para converter valores recebidos do exterior.
    """
    resultado = buscar_ptax(data, moeda)
    return resultado["venda"]
