"""Políticas de reposição.

Cada política é chamada pelo motor uma vez por dia, ao fim do dia, com o
estado de todos os itens (vetores numpy) e devolve a quantidade a pedir de
cada item (0 = não pedir).

Contrato:
    politica.iniciar(catalogo)              -> prepara estado interno
    politica.observar(dia, demanda_do_dia)  -> aprende com a demanda real
    politica.decidir(dia, posicao)          -> vetor de quantidades a pedir
onde `posicao` = estoque físico + o que já está em trânsito.
"""
from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd


def _arredonda_para_lote(qtd: np.ndarray, lote: np.ndarray) -> np.ndarray:
    """Pedidos só saem em múltiplos do lote de compra (caixa/embalagem)."""
    qtd = np.maximum(qtd, 0)
    return (np.ceil(qtd / lote) * lote).astype(int)


class MinMax:
    """Política atual do ERP: min e max fixos, calibrados uma vez."""

    nome = "Min/Max (ERP)"

    def iniciar(self, cat: pd.DataFrame) -> None:
        self.minimo = cat["min_erp"].to_numpy()
        self.maximo = cat["max_erp"].to_numpy()
        self.lote = cat["lote_compra"].to_numpy()

    def observar(self, dia: int, demanda_dia: np.ndarray) -> None:
        pass  # política estática: não aprende nada

    def limite(self) -> np.ndarray:
        """Ponto de pedido atual (usado para classificar pedidos urgentes)."""
        return self.minimo

    def decidir(self, dia: int, posicao: np.ndarray) -> np.ndarray:
        precisa = posicao <= self.minimo
        qtd = _arredonda_para_lote(self.maximo - posicao, self.lote)
        return np.where(precisa, qtd, 0)


class SmartStock:
    """Reposição adaptativa.

    - Estima demanda média e variabilidade por média móvel exponencial,
      então acompanha mudanças de regime.
    - Calcula estoque de segurança para um nível de serviço alvo, levando em
      conta a variabilidade da demanda E a do prazo do fornecedor.
    - Ponto de pedido s = demanda_media * LT + segurança.
    - Pede até S = s + cobertura (dias de demanda), em múltiplos do lote.
    """

    nome = "SmartStock"

    def __init__(
        self,
        nivel_servico: float = 0.97,
        alfa: float = 0.04,
        cobertura_dias: int = 14,
    ):
        self.nivel_servico = nivel_servico
        self.alfa = alfa
        self.cobertura_dias = cobertura_dias
        self.z = NormalDist().inv_cdf(nivel_servico)

    def iniciar(self, cat: pd.DataFrame) -> None:
        self.lt = cat["lt_medio"].to_numpy().astype(float)
        self.lt_desvio = cat["lt_desvio"].to_numpy().astype(float)
        self.lote = cat["lote_compra"].to_numpy()
        # parte da mesma informação que o min/max teve na calibração
        self.mu = cat["demanda_media"].to_numpy().astype(float)
        self.var = self.mu.copy()  # ponto de partida ~Poisson (var = média)

    def observar(self, dia: int, demanda_dia: np.ndarray) -> None:
        a = self.alfa
        erro = demanda_dia - self.mu
        self.mu = self.mu + a * erro
        self.var = (1 - a) * (self.var + a * erro**2)

    def _parametros(self):
        seguranca = self.z * np.sqrt(
            self.lt * self.var + (self.mu * self.lt_desvio) ** 2
        )
        ponto_pedido = self.mu * self.lt + seguranca
        nivel_max = ponto_pedido + np.maximum(self.lote, self.mu * self.cobertura_dias)
        return ponto_pedido, nivel_max

    def limite(self) -> np.ndarray:
        return self._parametros()[0]

    def decidir(self, dia: int, posicao: np.ndarray) -> np.ndarray:
        ponto_pedido, nivel_max = self._parametros()
        precisa = posicao <= ponto_pedido
        qtd = _arredonda_para_lote(nivel_max - posicao, self.lote)
        return np.where(precisa, qtd, 0)
