"""Layout do almoxarifado como dados + rotas de caminhada.

Convenções (metros): x = horizontal, z = profundidade (0 = parede das docas),
y = altura. A circulação é um corredor transversal (z = z_cruz) perto das docas
e corredores verticais (ao longo de z) entre os racks.

O mesmo layout alimenta o motor (distâncias e tempos) e o 3D (desenho).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import math

import numpy as np
import pandas as pd


@dataclass
class ConfigLayout:
    n_racks: int | None = None      # None = calcula pela ocupação alvo
    baias: int = 10                 # baias por face de rack
    niveis: int = 3                 # níveis de altura
    largura_baia: float = 1.4       # m por baia (ao longo de z)
    prof_rack: float = 2.0          # profundidade total do rack (2 faces)
    largura_corredor: float = 2.2   # m
    margem_lateral: float = 9.0     # espaço das docas nas laterais
    z_cruz: float = 3.0             # corredor transversal
    z_racks: float = 6.0            # início dos racks
    altura_nivel: float = 1.1       # m por nível
    ocupacao_alvo: float = 0.6      # fração de posições ocupadas


class Layout:
    def __init__(self, cfg: ConfigLayout, n_itens: int):
        self.cfg = cfg
        por_rack = 2 * cfg.baias * cfg.niveis
        if cfg.n_racks is None:
            cfg.n_racks = max(2, math.ceil(n_itens / (por_rack * cfg.ocupacao_alvo)))
        self.n_racks = cfg.n_racks
        A, P = cfg.largura_corredor, cfg.prof_rack

        # corredores (centro em x) e racks (centro em x)
        self.x_corredor = [cfg.margem_lateral + A / 2 + k * (A + P) for k in range(self.n_racks + 1)]
        self.x_rack = [cfg.margem_lateral + A + P / 2 + r * (A + P) for r in range(self.n_racks)]
        self.largura = cfg.margem_lateral * 2 + (self.n_racks + 1) * A + self.n_racks * P
        self.comprimento_rack = cfg.baias * cfg.largura_baia
        self.profundidade = cfg.z_racks + self.comprimento_rack + 3.0

        self.recebimento = (3.5, cfg.z_cruz)
        self.expedicao = (self.largura - 3.5, cfg.z_cruz)

        # posições de armazenagem
        pos = []
        for r in range(self.n_racks):
            for face in (0, 1):                      # 0 = oeste, 1 = leste
                x_acc = self.x_corredor[r + (1 if face else 0)]
                dx = (-1 if face == 0 else 1) * P / 4
                for b in range(cfg.baias):
                    z = cfg.z_racks + (b + 0.5) * cfg.largura_baia
                    for n in range(cfg.niveis):
                        pos.append({
                            "id": len(pos), "rack": r, "face": face, "baia": b, "nivel": n,
                            "pos": [round(self.x_rack[r] + dx, 3), round((n + 0.5) * cfg.altura_nivel, 3), round(z, 3)],
                            "acesso": [round(x_acc, 3), round(z, 3)],
                        })
        self.posicoes = pos

    # ------------------------------------------------------------------ rotas
    def rota(self, a, b):
        """Polilinha [(x,z)...] de a até b pelos corredores (Manhattan com corredores)."""
        zc = self.cfg.z_cruz
        eps = 1e-6
        em_corredor = lambda p: p[1] > zc + 0.5          # dentro de um corredor vertical?
        pts = [tuple(a)]
        if em_corredor(a) and em_corredor(b) and abs(a[0] - b[0]) < eps:
            pts.append(tuple(b))
        else:
            if em_corredor(a):
                pts.append((a[0], zc))
            if em_corredor(b):
                pts.append((b[0], zc))
            pts.append(tuple(b))
        # remove pontos repetidos
        limpo = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - limpo[-1][0]) > eps or abs(p[1] - limpo[-1][1]) > eps:
                limpo.append(p)
        return limpo

    @staticmethod
    def distancia(path):
        return sum(abs(path[i + 1][0] - path[i][0]) + abs(path[i + 1][1] - path[i][1])
                   for i in range(len(path) - 1))

    def dist(self, a, b):
        return self.distancia(self.rota(a, b))

    # --------------------------------------------------------------- slotting
    def alocar_itens(self, cat: pd.DataFrame) -> np.ndarray:
        """Itens de maior giro nas posições mais próximas da expedição e dos níveis baixos."""
        chave = []
        for p in self.posicoes:
            d = self.dist(self.expedicao, p["acesso"])
            chave.append(d + 2.5 * p["nivel"])
        ordem_pos = np.argsort(chave)
        ordem_itens = np.argsort(-cat["demanda_media"].to_numpy())
        loc = np.zeros(len(cat), dtype=int)
        for k, it in enumerate(ordem_itens):
            loc[it] = ordem_pos[k]
        return loc

    def para_json(self, loc_item: np.ndarray, cat: pd.DataFrame) -> dict:
        c = self.cfg
        return {
            "largura": round(self.largura, 2),
            "profundidade": round(self.profundidade, 2),
            "altura_nivel": c.altura_nivel,
            "niveis": c.niveis,
            "z_cruz": c.z_cruz,
            "largura_corredor": c.largura_corredor,
            "prof_rack": c.prof_rack,
            "comprimento_rack": round(self.comprimento_rack, 2),
            "z_racks": c.z_racks,
            "x_racks": [round(x, 3) for x in self.x_rack],
            "x_corredores": [round(x, 3) for x in self.x_corredor],
            "recebimento": list(self.recebimento),
            "expedicao": [round(self.expedicao[0], 3), self.expedicao[1]],
            "posicoes": self.posicoes,
            "itens": [{"idx": i, "item_id": cat["item_id"].iloc[i], "posicao": int(loc_item[i]),
                       "custo": float(cat["custo_unit"].iloc[i]),
                       "max": int(cat["max_erp"].iloc[i])} for i in range(len(cat))],
        }
