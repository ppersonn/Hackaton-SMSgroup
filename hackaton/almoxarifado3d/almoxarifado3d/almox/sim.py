"""Motor de simulação do almoxarifado (eventos + operadores + estoque físico x sistema).

O que acontece em cada dia de operação:
  - chegam pedidos de retirada e caminhões com lotes de reposição;
  - os operadores (agentes) caminham pelo layout, separam, recebem e contam;
  - o ESTOQUE FÍSICO muda conforme a realidade; o ESTOQUE DO SISTEMA muda
    conforme o que foi registrado (e pode divergir: retirada sem baixa,
    erro de recebimento, item no endereço errado);
  - ao fim do dia a política de reposição decide pedidos usando o estoque do
    SISTEMA (é aí que a divergência vira ruptura ou excesso).

As tecnologias entram só por `Params` (ver params.py) e por dois flags:
RFID (contagem sem caminhar) e visão computacional (câmeras na estante).
"""
from __future__ import annotations

import heapq
import itertools
from collections import deque
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .layout import Layout
from .params import DIA, Params

N_U_LINHA = 6   # u: erro, sem_baixa, det_estante, det_expedicao, auto, alerta
N_U_LOTE = 6    # u: erro_receb, endereco, (livre), hora, auto, alerta


@dataclass
class Linha:
    item: int
    qty: int
    u: np.ndarray


@dataclass
class Pedido:
    id: int
    dia: int
    t_rel: float
    linhas: list


@dataclass
class Lote:
    item: int
    qty: int
    t_rel: float
    u: np.ndarray


class Mundo:
    """Tudo o que é aleatório e NÃO depende do cenário (mesma semente em todos)."""

    def __init__(self, cat: pd.DataFrame, demanda: np.ndarray, lead_times: np.ndarray,
                 layout: Layout, loc_item: np.ndarray, P: Params, semente: int = 42):
        self.cat, self.demanda, self.lead_times = cat, demanda, lead_times
        self.layout, self.loc_item = layout, loc_item
        self.n, self.T = demanda.shape
        rng = np.random.default_rng(semente + 100)

        self.pedidos: list[list[Pedido]] = []
        pid = 0
        for d in range(self.T):
            linhas = []
            for i in range(self.n):
                q = int(demanda[i, d])
                while q > 0:
                    c = min(q, int(rng.integers(1, 3)))
                    linhas.append((i, c))
                    q -= c
            rng.shuffle(linhas)
            pedidos, k = [], 0
            while k < len(linhas):
                m = int(rng.integers(1, 5))
                grupo, k = linhas[k:k + m], k + m
                fundido: dict[int, int] = {}
                for i, c in grupo:
                    fundido[i] = fundido.get(i, 0) + c
                ls = [Linha(i, c, rng.random(N_U_LINHA)) for i, c in fundido.items()]
                pedidos.append(Pedido(pid, d, float(rng.uniform(0, P.janela_pedidos_h * 3600)), ls))
                pid += 1
            pedidos.sort(key=lambda o: o.t_rel)
            self.pedidos.append(pedidos)
        self.u_lote = rng.random((self.n, self.T, N_U_LOTE))
        self.ordem_contagem = rng.permutation(self.n)


class Operador:
    __slots__ = ("id", "pos", "livre")

    def __init__(self, id, pos):
        self.id, self.pos, self.livre = id, tuple(pos), True


class Sim:
    def __init__(self, mundo: Mundo, P: Params, politica, rfid: bool, visao: bool,
                 dia_viz: int | None = None):
        self.m, self.P, self.pol = mundo, P, politica
        self.pol.iniciar(mundo.cat)
        self.rfid, self.visao = rfid, visao
        self.L: Layout = mundo.layout
        self.loc = mundo.loc_item
        self.n, self.T = mundo.n, mundo.T
        self.custo = mundo.cat["custo_unit"].to_numpy().astype(float)
        self.turno_s = P.turno_h * 3600
        self.dia_viz = dia_viz

        self.phys = mundo.cat["estoque_inicial"].to_numpy().astype(int).copy()
        self.sys = self.phys.copy()
        self.mis = np.zeros(self.n, dtype=bool)
        self.transito = np.zeros(self.n, dtype=int)
        ex = self.L.expedicao
        self.ops = [Operador(k, (ex[0] - 0.8 * k, ex[1])) for k in range(P.n_operadores)]

        self.q_lote, self.q_ped, self.q_cont = deque(), deque(), deque()
        self.lotes_dia: list[list[Lote]] = [[] for _ in range(self.T + 1)]

        # acumuladores de KPI
        self.sep_s, self.ciclo_h, self.dist_ped, self.rec_s = [], [], [], []
        self.busy = {"ped": 0.0, "lote": 0.0, "cont": 0.0, "alerta": 0.0}
        self.busca_s = 0.0
        self.n_ped = self.n_ped_erro = self.n_ped_retrab = self.n_otif = 0
        self.entregue = np.zeros(self.n, dtype=np.int64)
        self.demandado = np.zeros(self.n, dtype=np.int64)
        self.falta_un = np.zeros(self.n, dtype=np.int64)
        self.perda_un = np.zeros(self.n, dtype=np.int64)
        self.rup = np.zeros((self.n, self.T), dtype=bool)
        self.n_alertas = 0
        self.mov_total = self.mov_auto = 0
        self.latencias: list[float] = []
        self.n_pedidos_compra = self.n_urgentes = 0
        self.cont_s = 0.0
        self.s_diverg, self.s_acur, self.s_fant = [], [], []
        self.s_est_valor, self.s_est_un, self.s_ocup, self.s_fill = [], [], [], []
        self.dist_acc = 0.0
        self.dia = 0
        self.gravando = False
        self.rec = None

    # ------------------------------------------------------------ gravação
    def _seg(self, op, t0, t1, p0, p1, tipo, item=-1):
        if self.gravando:
            b = self.rec["segs"][op.id]
            b.append([round(t0 - self.t_dia, 1), round(t1 - self.t_dia, 1),
                      round(p0[0], 2), round(p0[1], 2), round(p1[0], 2), round(p1[1], 2), tipo, int(item)])

    def _evt(self, t, tipo, **kw):
        if self.gravando:
            e = {"t": round(t - self.t_dia, 1), "tipo": tipo}
            e.update({k: (int(v) if isinstance(v, (np.integer,)) else v) for k, v in kw.items()})
            self.rec["evts"].append(e)

    def _delta(self, t, i, dp, ds):
        if self.gravando and (dp or ds):
            self.rec["delta"].append([round(t - self.t_dia, 1), int(i), int(dp), int(ds)])

    # --------------------------------------------------------- movimentação
    def _andar(self, op, t, destino, tipo="andar"):
        path = self.L.rota(op.pos, destino)
        for a, b in zip(path[:-1], path[1:]):
            d = abs(b[0] - a[0]) + abs(b[1] - a[1])
            dt = d / self.P.vel_caminhada
            self._seg(op, t, t + dt, a, b, tipo)
            t += dt
            self.dist_acc += d
        op.pos = (float(destino[0]), float(destino[1]))
        return t

    def _parado(self, op, t, dur, tipo, item=-1):
        self._seg(op, t, t + dur, op.pos, op.pos, tipo, item)
        return t + dur

    def _util_elapsed(self, t_a, t_f):
        """Tempo decorrido contando só horas de turno (descarta as noites)."""
        noites = int(t_f // DIA) - int(t_a // DIA)
        return (t_f - t_a) - noites * (DIA - self.turno_s)

    # ----------------------------------------------------------- tarefas
    def _ordenar(self, linhas):
        L = self.L
        por_x: dict[float, list] = {}
        for ln in linhas:
            a = L.posicoes[self.loc[ln.item]]["acesso"]
            por_x.setdefault(a[0], []).append((a[1], ln))
        ordem = []
        for k, x in enumerate(sorted(por_x)):
            g = sorted(por_x[x], key=lambda p: p[0], reverse=(k % 2 == 1))
            ordem += [ln for _, ln in g]
        return ordem

    def _registra_mov(self, t, u_auto, recorded):
        self.mov_total += 1
        if u_auto < self.P.auto_pick:
            self.mov_auto += 1
            lat = self.P.latencia_auto_s
        else:
            lat = max(60.0, self.fim - t)
        if recorded:
            self.latencias.append(lat / 60.0)

    def _tarefa_pedido(self, op, t, o: Pedido):
        P, L = self.P, self.L
        t_ini = t
        self.dist_acc = 0.0
        t = self._andar(op, t, L.expedicao)
        erros_pend, tem_erro, falta_total, entregue = [], False, 0, 0
        for ln in self._ordenar(o.linhas):
            i, q, u = ln.item, ln.qty, ln.u
            self.demandado[i] += q
            loc = L.posicoes[self.loc[i]]
            t = self._andar(op, t, loc["acesso"])
            t = self._parado(op, t, P.t_ler_endereco, "ler", i)
            if self.mis[i] and self.phys[i] > 0:
                t = self._parado(op, t, P.t_busca, "busca", i)
                self.busca_s += P.t_busca
                self.mis[i] = False
                self._evt(t, "localizado", item=i)
            t = self._parado(op, t, P.t_pega_linha + 4 * (q - 1), "pega", i)
            take = min(q, int(self.phys[i]))
            falta = q - take
            if falta > 0:
                falta_total += falta
                self.falta_un[i] += falta
                self.rup[i, self.dia] = True
                self._evt(t, "ruptura", item=i, falta=falta)
            if take > 0:
                entregue += take
                self.entregue[i] += take
                self.phys[i] -= take
                gravou = u[1] >= P.p_sem_baixa
                if gravou:
                    ds = min(take, int(self.sys[i]))
                    self.sys[i] -= ds
                else:
                    ds = 0
                    self._evt(t, "sem_baixa", item=i)
                self._delta(t, i, -take, -ds)
                self._registra_mov(t, u[4], gravou)
                if self.visao:
                    self._evt(t, "camera", item=i)
                if u[0] < P.p_erro_sep:
                    tem_erro = True
                    self._evt(t, "erro", item=i)
                    if u[2] < P.p_det_estante:
                        t = self._parado(op, t, P.t_corrige, "corrige", i)
                        self._evt(t, "camera_corrige", item=i)
                    else:
                        erros_pend.append((i, u[3]))
                if u[5] < P.falsos_por_mov:
                    t = self._parado(op, t, P.t_alerta, "alerta", i)
                    self.n_alertas += 1
                    self.busy["alerta"] += P.t_alerta
                    self._evt(t, "alerta_falso", item=i)
        t = self._andar(op, t, L.expedicao)
        t = self._parado(op, t, P.t_conf_expedicao, "conf")
        if self.rfid:
            self._evt(t, "rfid_expedicao")
        retrab, cliente_erro = False, False
        for i, ud in erros_pend:
            if ud < P.p_det_expedicao:
                retrab = True
                t = self._andar(op, t, L.posicoes[self.loc[i]]["acesso"])
                t = self._parado(op, t, P.t_retrabalho, "corrige", i)
                t = self._andar(op, t, L.expedicao)
            else:
                cliente_erro = True
        t_arr = self.dia * DIA + self.ini_rel + o.t_rel
        ciclo = self._util_elapsed(t_arr, t) / 3600.0
        completo = falta_total == 0
        self.n_ped += 1
        self.n_ped_erro += int(tem_erro)
        self.n_ped_retrab += int(retrab)
        self.n_otif += int(completo and not cliente_erro and ciclo <= P.sla_h)
        self.sep_s.append(t - t_ini)
        self.ciclo_h.append(ciclo)
        self.dist_ped.append(self.dist_acc)
        self.busy["ped"] += t - t_ini
        self._evt(t, "pedido_ok" if completo and not cliente_erro else "pedido_falha", id=o.id)
        return t

    def _tarefa_lote(self, op, t, lote: Lote):
        P, L = self.P, self.L
        t_ini = t
        self.dist_acc = 0.0
        i, qty, u = lote.item, lote.qty, lote.u
        t = self._andar(op, t, L.recebimento)
        t = self._parado(op, t, P.t_receb_conf, "receb", i)
        if self.rfid:
            self._evt(t, "rfid_recebimento", item=i)
        self._evt(t, "caminhao_sai", item=i)
        recebido = qty
        if u[0] < P.p_erro_receb:
            falta = max(1, int(round(P.perc_perda_receb * qty)))
            recebido = max(0, qty - falta)
            self.perda_un[i] += qty - recebido
            self._evt(t, "erro_recebimento", item=i)
        t = self._andar(op, t, L.posicoes[self.loc[i]]["acesso"])
        t = self._parado(op, t, P.t_putaway, "pega", i)
        if u[1] < P.p_endereco_errado:
            self.mis[i] = True
            self._evt(t, "endereco_errado", item=i)
        self.phys[i] += recebido
        self.sys[i] += qty
        self.transito[i] -= qty
        self._delta(t, i, recebido, qty)
        self.mov_total += 1
        if u[4] < P.auto_receb:
            self.mov_auto += 1
            self.latencias.append(P.latencia_auto_s / 60.0)
        else:
            self.latencias.append(max(60.0, self.fim - t) / 60.0)
        if u[5] < P.falsos_por_mov:
            t = self._parado(op, t, P.t_alerta, "alerta", i)
            self.n_alertas += 1
            self.busy["alerta"] += P.t_alerta
            self._evt(t, "alerta_falso", item=i)
        self.rec_s.append(t - t_ini)
        self.busy["lote"] += t - t_ini
        return t

    def _tarefa_contagem(self, op, t, i):
        P, L = self.P, self.L
        t_ini = t
        if not self.rfid:
            t = self._andar(op, t, L.posicoes[self.loc[i]]["acesso"])
            if self.mis[i] and self.phys[i] > 0:
                t = self._parado(op, t, P.t_busca, "busca", i)
                self.busca_s += P.t_busca
        else:
            self._evt(t, "rfid_contagem", item=i)
        t = self._parado(op, t, P.t_contagem_item, "contagem", i)
        dif = int(self.phys[i]) - int(self.sys[i])
        if dif != 0:
            self._delta(t, i, 0, dif)
            self._evt(t, "ajuste", item=i, dif=dif)
        self.sys[i] = self.phys[i]
        if self.mis[i]:
            self._evt(t, "localizado", item=i)
        self.mis[i] = False
        self.cont_s += t - t_ini
        self.busy["cont"] += t - t_ini
        return t

    # -------------------------------------------------------------- laço
    def _despachar(self, t, heap, cont):
        if t >= self.fim:
            return
        while True:
            op = next((o for o in self.ops if o.livre), None)
            if op is None:
                return
            if self.q_lote:
                lote = self.q_lote.popleft()
                t_fim = self._tarefa_lote(op, t, lote)
            elif self.q_ped:
                o = self.q_ped.popleft()
                t_fim = self._tarefa_pedido(op, t, o)
            elif self.q_cont:
                t_fim = self._tarefa_contagem(op, t, self.q_cont.popleft())
            else:
                return
            op.livre = False
            heapq.heappush(heap, (t_fim, next(cont), "livre", op))

    def _dia(self, d):
        P, m = self.P, self.m
        self.dia = d
        self.t_dia = d * DIA
        self.ini_rel = P.turno_ini_h * 3600
        self.ini = self.t_dia + self.ini_rel
        self.fim = self.ini + self.turno_s
        self.gravando = (d == self.dia_viz)
        if self.gravando:
            self.rec = {"segs": [[] for _ in self.ops], "evts": [], "delta": [],
                        "phys0": self.phys.tolist(), "sys0": self.sys.tolist(),
                        "mis0": self.mis.astype(int).tolist(),
                        "pos0": [list(o.pos) for o in self.ops]}
        for o in self.ops:
            o.livre = True
        cont = itertools.count()
        heap = [(self.ini, next(cont), "inicio", None)]
        for o in m.pedidos[d]:
            heapq.heappush(heap, (self.ini + o.t_rel, next(cont), "ped", o))
        for lote in self.lotes_dia[d]:
            heapq.heappush(heap, (self.ini + lote.t_rel, next(cont), "lote", lote))
        n_cont = P.contagens_por_dia
        for k in range(n_cont):
            item = int(m.ordem_contagem[(d * n_cont + k) % self.n])
            heapq.heappush(heap, (self.ini + 1800 + 60 * k, next(cont), "cont", item))
        while heap:
            t, _, tipo, dado = heapq.heappop(heap)
            if tipo == "ped":
                self.q_ped.append(dado)
                self._evt(t, "pedido_chega", id=dado.id, linhas=len(dado.linhas))
            elif tipo == "lote":
                self.q_lote.append(dado)
                self._evt(t, "caminhao", item=dado.item, qty=dado.qty)
            elif tipo == "cont":
                self.q_cont.append(dado)
            elif tipo == "livre":
                dado.livre = True
            self._despachar(t, heap, cont)

        # ---- fim do dia: fotografia do estoque e reposição
        c = self.custo
        self.s_diverg.append(float((self.sys != self.phys).mean()))
        self.s_acur.append(float(1.0 - self.mis.mean()))
        self.s_fant.append(float((np.maximum(self.sys - self.phys, 0) * c).sum()))
        self.s_est_valor.append(float((self.phys * c).sum()))
        self.s_est_un.append(float(self.phys.sum()))
        self.s_ocup.append(float((self.phys > 0).sum() / len(self.L.posicoes)))
        dem_dia = int(m.demanda[:, d].sum())
        self.s_fill.append(None)  # preenchido no final se necessário

        self.pol.observar(d, m.demanda[:, d])
        pos = self.sys + self.transito
        qtd = self.pol.decidir(d, pos)
        lim = self.pol.limite()
        urg = (qtd > 0) & (pos <= 0.5 * lim)
        for i in np.nonzero(qtd)[0]:
            q = int(qtd[i])
            self.transito[i] += q
            self.n_pedidos_compra += 1
            self.n_urgentes += int(urg[i])
            self._evt(self.fim + 300, "pedido_compra", item=int(i), qty=q, urgente=bool(urg[i]))
            chega = d + int(max(1, m.lead_times[i, d]))
            if chega < self.T:
                u = m.u_lote[i, d]
                self.lotes_dia[chega].append(Lote(int(i), q, float(u[3]) * 5 * 3600, u))
        if self.gravando:
            self.rec["phys1"] = self.phys.tolist()
            self.rec["sys1"] = self.sys.tolist()

    def rodar(self):
        for d in range(self.T):
            self._dia(d)
        return self

    # ------------------------------------------------------------- resultados
    def kpis(self) -> dict:
        P, T = self.P, self.T
        ano = 365.0 / T
        c = self.custo
        n_ped = max(self.n_ped, 1)
        horas_ped = max(self.busy["ped"] / 3600.0, 1e-9)
        est_medio = float(np.mean(self.s_est_valor))
        dem_total = float(self.demandado.sum())
        vendas_custo = float((self.entregue * c).sum())
        ult = min(90, T)
        parados = float((self.m.demanda[:, -ult:].sum(axis=1) == 0).mean())
        # os alertas já estão dentro do tempo das tarefas; não somar duas vezes
        busy_total = self.busy["ped"] + self.busy["lote"] + self.busy["cont"]
        disp = P.n_operadores * T * self.turno_s
        mao_obra = busy_total / 3600.0 * P.custo_hora * ano
        posse = est_medio * P.taxa_posse_anual
        pedidos = self.n_pedidos_compra * P.custo_pedido * ano
        ruptura = float((self.falta_un * c).sum()) * P.mult_ruptura * ano
        perdas = float((self.perda_un * c).sum()) * ano
        k = {
            "sep_tempo": float(np.mean(self.sep_s)) / 60.0,
            "prod": self.n_ped / horas_ped,
            "ciclo": float(np.mean(self.ciclo_h)),
            "dist": float(np.mean(self.dist_ped)),
            "busca": self.busca_s / 60.0 / (T * P.n_operadores),
            "receb": (float(np.mean(self.rec_s)) / 60.0) if self.rec_s else 0.0,
            "contagem": self.cont_s / 3600.0 / (T / 30.0),
            "erro_sep": self.n_ped_erro / n_ped,
            "retrab": self.n_ped_retrab / n_ped,
            "util": busy_total / disp,
            "fill": float(self.entregue.sum()) / max(dem_total, 1.0),
            "otif": self.n_otif / n_ped,
            "rup_dias": float(self.rup.sum()) * ano,
            "rup_itens": float(self.rup.any(axis=1).mean()),
            "diverg": float(np.mean(self.s_diverg)),
            "acur_loc": float(np.mean(self.s_acur)),
            "fantasma": float(np.mean(self.s_fant)),
            "perdas": perdas,
            "est_medio": est_medio,
            "giro": vendas_custo / max(est_medio, 1e-9) * ano,
            "cobertura": float(np.mean(self.s_est_un)) / max(dem_total / T, 1e-9),
            "ped_compra": self.n_pedidos_compra * ano,
            "emergencia": self.n_urgentes * ano,
            "parados": parados,
            "ocupacao": float(np.mean(self.s_ocup)),
            "latencia": float(np.mean(self.latencias)) if self.latencias else 0.0,
            "rastreio": self.mov_auto / max(self.mov_total, 1),
            "falsos": self.n_alertas / (T / 7.0),
            "custo_op": mao_obra + posse + pedidos + ruptura + perdas,
        }
        k["_componentes"] = {"mao_de_obra": mao_obra, "posse": posse, "pedidos": pedidos,
                             "ruptura": ruptura, "perdas": perdas}
        return k

    def series(self) -> dict:
        return {"estoque_valor": [round(v, 0) for v in self.s_est_valor],
                "divergencia": [round(v, 4) for v in self.s_diverg]}

    def dia_gravado(self) -> dict | None:
        if self.rec is None:
            return None
        r = self.rec
        r["evts"].sort(key=lambda e: e["t"])
        r["delta"].sort(key=lambda e: e[0])
        return r
