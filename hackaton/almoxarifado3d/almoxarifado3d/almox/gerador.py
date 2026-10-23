"""Gerador de base sintética para o SmartStock.

Cria um catálogo de itens industriais (caixas plásticas) e as séries de
demanda diária e de prazo de entrega (lead time) de cada um.

As séries são geradas UMA vez por semente e reutilizadas por todas as
políticas, para que a comparação min/max vs SmartStock seja justa
(mesma demanda, mesmos atrasos de fornecedor).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

PADROES = ("estavel", "intermitente", "sazonal")


@dataclass
class ConfigGerador:
    n_itens: int = 60
    dias: int = 365
    semente: int = 42
    # mudança de regime: a partir deste dia (fração do horizonte) a demanda
    # de uma parte dos itens muda de nível. É isso que faz o min/max estático
    # envelhecer e o SmartStock (adaptativo) se destacar.
    dia_mudanca_frac: float = 0.5
    frac_itens_mudam: float = 0.35
    fator_mudanca_min: float = 0.5
    fator_mudanca_max: float = 2.0


def gerar_catalogo(cfg: ConfigGerador) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.semente)
    n = cfg.n_itens

    padrao = rng.choice(PADROES, size=n, p=[0.5, 0.3, 0.2])
    demanda_media = rng.lognormal(mean=1.2, sigma=0.8, size=n)  # un/dia
    demanda_media = np.clip(demanda_media, 0.3, 40.0)
    # intermitentes: pouca frequência, lote maior quando ocorre
    prob_demanda = np.where(padrao == "intermitente", rng.uniform(0.1, 0.35, n), 1.0)

    custo_unit = rng.lognormal(mean=3.0, sigma=0.9, size=n).round(2)  # R$
    lt_medio = rng.integers(3, 21, size=n)  # dias
    lt_desvio = np.round(lt_medio * rng.uniform(0.1, 0.4, size=n), 1)
    lote_compra = np.maximum(1, (demanda_media * rng.integers(5, 15, n)).round()).astype(int)

    # min/max "do ERP": calibrado uma única vez, com uma folga fixa sobre a
    # demanda do início, e nunca mais revisado.
    min_erp = np.ceil(demanda_media * lt_medio * 1.2).astype(int)
    max_erp = (min_erp + lote_compra).astype(int)

    mudam = rng.random(n) < cfg.frac_itens_mudam
    fator = np.where(
        mudam, rng.uniform(cfg.fator_mudanca_min, cfg.fator_mudanca_max, n), 1.0
    )

    return pd.DataFrame(
        {
            "item_id": [f"ITM-{i + 1:03d}" for i in range(n)],
            "padrao": padrao,
            "demanda_media": demanda_media.round(2),
            "prob_demanda": prob_demanda.round(2),
            "custo_unit": custo_unit,
            "lt_medio": lt_medio,
            "lt_desvio": lt_desvio,
            "lote_compra": lote_compra,
            "min_erp": min_erp,
            "max_erp": max_erp,
            "estoque_inicial": max_erp,
            "fator_mudanca": fator.round(2),
        }
    )


def gerar_demanda(cat: pd.DataFrame, cfg: ConfigGerador) -> np.ndarray:
    """Matriz (itens x dias) de demanda diária em unidades."""
    rng = np.random.default_rng(cfg.semente + 1)
    n, T = len(cat), cfg.dias
    dia = np.arange(T)
    dia_mud = int(cfg.dia_mudanca_frac * T)

    demanda = np.zeros((n, T), dtype=int)
    for i, it in enumerate(cat.itertuples()):
        nivel = np.full(T, it.demanda_media, dtype=float)
        nivel[dia_mud:] *= it.fator_mudanca
        if it.padrao == "sazonal":
            nivel *= 1 + 0.5 * np.sin(2 * np.pi * dia / 90 + rng.uniform(0, 2 * np.pi))
        if it.padrao == "intermitente":
            ocorre = rng.random(T) < it.prob_demanda
            tamanho = rng.poisson(np.maximum(nivel / it.prob_demanda, 0.1))
            demanda[i] = np.where(ocorre, tamanho, 0)
        else:
            demanda[i] = rng.poisson(np.maximum(nivel, 0.05))
    return demanda


def gerar_lead_times(cat: pd.DataFrame, cfg: ConfigGerador) -> np.ndarray:
    """Matriz (itens x dias): prazo de entrega de um pedido feito naquele dia."""
    rng = np.random.default_rng(cfg.semente + 2)
    n, T = len(cat), cfg.dias
    media = cat["lt_medio"].to_numpy()[:, None]
    desvio = cat["lt_desvio"].to_numpy()[:, None]
    lt = rng.normal(media, desvio, size=(n, T))
    return np.maximum(1, np.round(lt)).astype(int)


def gerar_base(cfg: ConfigGerador):
    cat = gerar_catalogo(cfg)
    return cat, gerar_demanda(cat, cfg), gerar_lead_times(cat, cfg)
