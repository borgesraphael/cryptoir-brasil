"""
Testes do PTAX Service.

Alguns testes fazem chamadas reais à API do BCB.
Marcar com @pytest.mark.api para poder pular em CI sem internet.
"""

import json
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.ptax_service import buscar_ptax, buscar_ptax_venda, PTAXIndisponivelError, _chave_cache


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _mock_api(retorno: dict | None):
    """Retorna um mock da função _buscar_na_api."""
    return patch("src.ptax_service._buscar_na_api", return_value=retorno)

def _mock_cache_vazio():
    return patch("src.ptax_service._carregar_cache", return_value={})

def _mock_salvar():
    return patch("src.ptax_service._salvar_cache")

COTACAO_EXEMPLO = {"compra": 5.7432, "venda": 5.7438, "fonte": "bcb_api"}


# ─────────────────────────────────────────────
# Testes de busca normal
# ─────────────────────────────────────────────

def test_retorna_cotacao_dia_normal():
    """Dia útil normal retorna cotação corretamente."""
    with _mock_cache_vazio(), _mock_api(COTACAO_EXEMPLO), _mock_salvar():
        resultado = buscar_ptax(date(2025, 6, 20))

    assert resultado["compra"] == 5.7432
    assert resultado["venda"] == 5.7438
    assert resultado["data_efetiva"] == date(2025, 6, 20)
    assert "aviso" not in resultado


def test_retorna_cotacao_moeda_eur():
    """Busca cotação de EUR funciona."""
    cotacao_eur = {"compra": 6.20, "venda": 6.21, "fonte": "bcb_api"}
    with _mock_cache_vazio(), _mock_api(cotacao_eur), _mock_salvar():
        resultado = buscar_ptax(date(2025, 6, 20), moeda="EUR")

    assert resultado["venda"] == 6.21


def test_atalho_buscar_ptax_venda():
    """buscar_ptax_venda retorna apenas o float da cotação de venda."""
    with _mock_cache_vazio(), _mock_api(COTACAO_EXEMPLO), _mock_salvar():
        venda = buscar_ptax_venda(date(2025, 6, 20))

    assert venda == 5.7438


# ─────────────────────────────────────────────
# Testes de fallback (fim de semana / feriado)
# ─────────────────────────────────────────────

def test_sabado_usa_sexta():
    """Sábado não tem cotação → usa a sexta-feira anterior."""
    # Sábado 21/06/2025: API retorna None
    # Sexta 20/06/2025: API retorna cotação
    respostas = {
        date(2025, 6, 21): None,
        date(2025, 6, 20): COTACAO_EXEMPLO,
    }

    def api_side_effect(data, moeda):
        return respostas.get(data)

    with _mock_cache_vazio(), _mock_salvar():
        with patch("src.ptax_service._buscar_na_api", side_effect=api_side_effect):
            resultado = buscar_ptax(date(2025, 6, 21))

    assert resultado["data_efetiva"] == date(2025, 6, 20)
    assert "aviso" in resultado
    assert "último dia útil anterior" in resultado["aviso"]


def test_domingo_usa_sexta():
    """Domingo não tem cotação → usa sexta (2 dias atrás)."""
    respostas = {
        date(2025, 6, 22): None,
        date(2025, 6, 21): None,
        date(2025, 6, 20): COTACAO_EXEMPLO,
    }

    def api_side_effect(data, moeda):
        return respostas.get(data)

    with _mock_cache_vazio(), _mock_salvar():
        with patch("src.ptax_service._buscar_na_api", side_effect=api_side_effect):
            resultado = buscar_ptax(date(2025, 6, 22))

    assert resultado["data_efetiva"] == date(2025, 6, 20)


def test_feriado_ano_novo_usa_dia_anterior():
    """1º de janeiro não tem cotação → usa 31/12 do ano anterior."""
    respostas = {
        date(2025, 1, 1): None,
        date(2024, 12, 31): COTACAO_EXEMPLO,
    }

    def api_side_effect(data, moeda):
        return respostas.get(data)

    with _mock_cache_vazio(), _mock_salvar():
        with patch("src.ptax_service._buscar_na_api", side_effect=api_side_effect):
            resultado = buscar_ptax(date(2025, 1, 1))

    assert resultado["data_efetiva"] == date(2024, 12, 31)


def test_levanta_erro_quando_nenhum_dia_tem_cotacao():
    """Se 7 dias consecutivos não tiverem cotação, levanta PTAXIndisponivelError."""
    with _mock_cache_vazio(), _mock_salvar():
        with patch("src.ptax_service._buscar_na_api", return_value=None):
            with pytest.raises(PTAXIndisponivelError) as exc:
                buscar_ptax(date(2025, 6, 20))

    assert "Não foi possível obter cotação" in str(exc.value)


# ─────────────────────────────────────────────
# Testes de cache
# ─────────────────────────────────────────────

def test_cache_hit_nao_chama_api():
    """Se a cotação está em cache, a API não é chamada."""
    cache_populado = {
        _chave_cache(date(2025, 6, 20), "USD"): COTACAO_EXEMPLO
    }

    with patch("src.ptax_service._carregar_cache", return_value=cache_populado):
        with patch("src.ptax_service._buscar_na_api") as mock_api:
            resultado = buscar_ptax(date(2025, 6, 20))

    mock_api.assert_not_called()
    assert resultado["compra"] == 5.7432


def test_cache_salvo_apos_busca_api():
    """Após busca na API, o resultado é salvo no cache."""
    with _mock_cache_vazio():
        with patch("src.ptax_service._buscar_na_api", return_value=COTACAO_EXEMPLO):
            with patch("src.ptax_service._salvar_cache") as mock_salvar:
                buscar_ptax(date(2025, 6, 20))

    mock_salvar.assert_called_once()
    cache_salvo = mock_salvar.call_args[0][0]
    chave = _chave_cache(date(2025, 6, 20), "USD")
    assert chave in cache_salvo
