"""Testes de consistência do simulador. Rodar: python -m pytest -q tests  (ou python tests/test_motor.py)"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from almox.cenarios import CENARIOS, montar_mundo, rodar_cenario
from almox.layout import ConfigLayout, Layout
from almox.params import Params, efetivos

DIAS, ITENS = 90, 40
MUNDO, BASE = montar_mundo(ITENS, DIAS, 7)
DIA_VIZ = 30


def rodar(nome_idx, dia_viz=None):
    _, rf, vi, sm = CENARIOS[nome_idx]
    return rodar_cenario(MUNDO, BASE, rf, vi, sm, dia_viz)


def test_demanda_igual_em_todos_os_cenarios():
    totais = {int(rodar(i).demandado.sum()) for i in range(len(CENARIOS))}
    assert len(totais) == 1, "a demanda precisa ser a mesma em todos os cenários"
    assert totais.pop() == int(MUNDO.demanda.sum())


def test_conservacao_entregue_mais_falta():
    for i in range(len(CENARIOS)):
        s = rodar(i)
        assert (s.entregue + s.falta_un == s.demandado).all()


def test_estoque_fisico_nunca_negativo():
    for i in range(len(CENARIOS)):
        s = rodar(i)
        assert (s.phys >= 0).all()


def test_reprodutivel_com_mesma_semente():
    a, b = rodar(7).kpis(), rodar(7).kpis()
    assert a["custo_op"] == b["custo_op"] and a["sep_tempo"] == b["sep_tempo"]


def test_sem_tecnologia_nao_ha_rastreio_nem_alerta_falso():
    k = rodar(0).kpis()
    assert k["rastreio"] == 0 and k["falsos"] == 0


def test_rfid_reduz_divergencia_e_tempo_de_recebimento():
    base, rfid = rodar(0).kpis(), rodar(1).kpis()
    assert rfid["diverg"] < base["diverg"]
    assert rfid["receb"] < base["receb"]


def test_visao_reduz_erro_de_separacao():
    assert rodar(2).kpis()["erro_sep"] < rodar(0).kpis()["erro_sep"]


def test_smartstock_melhora_nivel_de_servico():
    assert rodar(3).kpis()["fill"] > rodar(0).kpis()["fill"]


def test_dia_gravado_fecha_as_contas():
    """phys0 + soma dos deltas do dia == phys1 (e o mesmo para o sistema)."""
    for i in (0, 7):
        r = rodar(i, DIA_VIZ)
        d = r.dia_gravado()
        phys, sys_ = np.array(d["phys0"]), np.array(d["sys0"])
        for _, item, dp, ds in d["delta"]:
            phys[item] += dp
            sys_[item] += ds
        assert (phys == np.array(d["phys1"])).all()
        assert (sys_ == np.array(d["sys1"])).all()


def test_operadores_so_andam_pelos_corredores():
    """Cada segmento de caminhada é horizontal ou vertical (nunca atravessa racks na diagonal)."""
    d = rodar(0, DIA_VIZ).dia_gravado()
    for segs in d["segs"]:
        for t0, t1, x0, z0, x1, z1, tipo, _ in segs:
            assert t1 >= t0
            if tipo == "andar":
                assert abs(x1 - x0) < 1e-6 or abs(z1 - z0) < 1e-6


def test_tempo_dos_segmentos_nao_se_sobrepoe():
    d = rodar(7, DIA_VIZ).dia_gravado()
    for segs in d["segs"]:
        for a, b in zip(segs[:-1], segs[1:]):
            assert b[0] >= a[1] - 0.2


def test_layout_posicoes_unicas_e_rota_simetrica():
    L = Layout(ConfigLayout(), ITENS)
    loc = L.alocar_itens(MUNDO.cat)
    assert len(set(loc.tolist())) == len(loc)
    a, b = L.posicoes[loc[0]]["acesso"], L.posicoes[loc[-1]]["acesso"]
    assert abs(L.dist(a, b) - L.dist(b, a)) < 1e-9


def test_efeitos_combinados_respeitam_a_regra():
    p = efetivos(Params(), True, True)
    assert p.t_receb_conf == 900.0 and p.p_erro_sep == 0.005          # melhor valor
    assert abs(p.auto_pick - (1 - (1 - 0.95) * (1 - 0.90))) < 1e-12    # leituras se combinam
    assert abs(p.falsos_por_mov - 0.012) < 1e-12                       # alertas somam


if __name__ == "__main__":
    ok = 0
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn(); ok += 1; print("ok ", nome)
    print(ok, "testes passaram")
