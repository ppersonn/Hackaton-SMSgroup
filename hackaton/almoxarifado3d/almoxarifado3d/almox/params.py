"""Parâmetros do simulador e efeitos de cada tecnologia.

Todos os números de efeito (RFID, visão computacional) são PREMISSAS iniciais,
não dados medidos. Podem ser lidos da aba "Premissas" da planilha
(`carregar_premissas_xlsx`) ou editados aqui.

Regra de combinação quando duas tecnologias estão ligadas:
  - tempos e probabilidades de erro: vale o melhor (menor) valor;
  - taxas de leitura automática: 1 - (1-a)(1-b);
  - alertas falsos: somam.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace

DIA = 86400


@dataclass
class Params:
    # ---- operação
    n_operadores: int = 2
    turno_ini_h: float = 7.0
    turno_h: float = 9.0
    janela_pedidos_h: float = 6.5     # pedidos chegam nas primeiras horas do turno
    vel_caminhada: float = 1.3        # m/s
    sla_h: float = 4.0                # prazo do pedido (horas úteis)
    custo_hora: float = 32.0          # R$/h de mão de obra

    # ---- tempos base (s)
    t_ler_endereco: float = 6.0
    t_pega_linha: float = 25.0
    t_conf_expedicao: float = 20.0
    t_receb_conf: float = 2700.0      # 45 min
    t_putaway: float = 60.0
    t_contagem_item: float = 30.0
    t_busca: float = 480.0            # item fora do endereço
    t_corrige: float = 20.0           # correção na estante (visão)
    t_alerta: float = 120.0           # verificar um alerta falso
    t_retrabalho: float = 60.0

    # ---- probabilidades base
    p_erro_sep: float = 0.03
    p_det_expedicao: float = 0.70
    p_det_estante: float = 0.0        # só a visão detecta na estante
    p_sem_baixa: float = 0.05
    p_erro_receb: float = 0.02
    p_endereco_errado: float = 0.02
    contagens_por_dia: int = 5

    # ---- leitura automática e alertas
    auto_pick: float = 0.0
    auto_receb: float = 0.0
    latencia_auto_s: float = 60.0
    falsos_por_mov: float = 0.0       # alertas falsos por movimento

    # ---- reposição
    nivel_servico: float = 0.97
    alfa: float = 0.04
    cobertura_dias: int = 14

    # ---- custos
    taxa_posse_anual: float = 0.25
    custo_pedido: float = 80.0
    mult_ruptura: float = 0.5
    perc_perda_receb: float = 0.10    # fração do lote faltante quando há erro de recebimento


EFEITOS = {
    "rfid": {
        "t_receb_conf": 900.0,        # 45 -> 15 min
        "t_contagem_item": 5.0,       # 30 -> 5 s
        "t_busca": 40.0,              # localiza o item rápido
        "p_endereco_errado": 0.003,
        "p_erro_receb": 0.002,
        "p_sem_baixa": 0.02,
        "p_det_expedicao": 0.90,
        "contagens_por_dia": 15,
        "auto_pick": 0.95,
        "auto_receb": 0.98,
        "falsos_por_mov": 0.004,
    },
    "visao": {
        "p_erro_sep": 0.005,          # 3% -> 0,5%
        "p_sem_baixa": 0.01,          # 5% -> 1%
        "p_det_estante": 0.95,
        "p_det_expedicao": 0.98,
        "t_conf_expedicao": 5.0,
        "auto_pick": 0.90,
        "falsos_por_mov": 0.008,
    },
}
REGRA = {
    "t_receb_conf": "min", "t_contagem_item": "min", "t_busca": "min",
    "p_endereco_errado": "min", "p_erro_receb": "min", "p_sem_baixa": "min",
    "p_erro_sep": "min", "t_conf_expedicao": "min",
    "p_det_expedicao": "max", "p_det_estante": "max", "contagens_por_dia": "max",
    "auto_pick": "comb", "auto_receb": "comb", "falsos_por_mov": "soma",
}


def efetivos(base: Params, rfid: bool, visao: bool, efeitos: dict | None = None) -> Params:
    """Parâmetros efetivos de um cenário, aplicando os efeitos das tecnologias ligadas."""
    efeitos = efeitos or EFEITOS
    d = asdict(base)
    ativos = [n for n, on in (("rfid", rfid), ("visao", visao)) if on]
    for chave in {k for n in ativos for k in efeitos[n]}:
        vals = [efeitos[n][chave] for n in ativos if chave in efeitos[n]]
        regra = REGRA[chave]
        if regra == "min":
            d[chave] = min([d[chave]] + vals)
        elif regra == "max":
            d[chave] = max([d[chave]] + vals)
        elif regra == "soma":
            d[chave] = d[chave] + sum(vals)
        elif regra == "comb":
            p = 1.0 - d[chave]
            for v in vals:
                p *= (1.0 - v)
            d[chave] = 1.0 - p
    return Params(**d)


# --------------------------------------------------------------------------
# leitura da aba "Premissas" da planilha (valores "sem" e "com" a tecnologia)
# --------------------------------------------------------------------------
def carregar_premissas_xlsx(caminho: str, base: Params | None = None):
    """Lê a aba Premissas e devolve (Params base, efeitos atualizados).

    Mapeamento por texto da coluna B (parâmetro), colunas D (sem) e E (com).
    Parâmetros que a planilha não cobre mantêm os valores padrão.
    """
    from openpyxl import load_workbook
    import copy

    base = base or Params()
    efeitos = copy.deepcopy(EFEITOS)
    ws = load_workbook(caminho, data_only=True)["Premissas"]
    usados = []
    for r in range(5, ws.max_row + 1):
        nome = ws.cell(row=r, column=2).value
        sem, com = ws.cell(row=r, column=4).value, ws.cell(row=r, column=5).value
        if not nome or sem is None or com is None:
            continue
        n = str(nome).lower()
        if n.startswith("tempo de recebimento"):
            base = replace(base, t_receb_conf=float(sem) * 60); efeitos["rfid"]["t_receb_conf"] = float(com) * 60
        elif n.startswith("tempo de contagem"):
            base = replace(base, t_contagem_item=float(sem)); efeitos["rfid"]["t_contagem_item"] = float(com)
        elif n.startswith("erro de separação"):
            base = replace(base, p_erro_sep=float(sem)); efeitos["visao"]["p_erro_sep"] = float(com)
        elif n.startswith("retiradas sem baixa"):
            base = replace(base, p_sem_baixa=float(sem)); efeitos["visao"]["p_sem_baixa"] = float(com)
        elif n.startswith("nível de serviço"):
            base = replace(base, nivel_servico=float(com))
        else:
            continue
        usados.append(str(nome))
    return base, efeitos, usados
