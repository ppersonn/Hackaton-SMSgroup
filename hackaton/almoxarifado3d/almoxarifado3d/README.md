# Simulador 3D de almoxarifado (SmartStock, RFID, visão computacional)

Simula um almoxarifado com operadores, pedidos, recebimentos e contagens, com três
tecnologias que se ligam e desligam (RFID, visão computacional, SmartStock), compara os
8 cenários possíveis com a mesma aleatoriedade e mostra tudo em 3D.

## Como rodar

```bash
pip install numpy pandas openpyxl
python -m almox.cenarios --xlsx planilha/plano_simulador_3d_almoxarifado.xlsx   # roda os 8 cenários
python viewer/montar.py                                                         # monta a página 3D
```

Resultados em `saida/`:

| Arquivo | O que é |
|---|---|
| `simulador3d.html` | Página 3D autocontida (abre com duplo clique, sem internet) |
| `planilha_preenchida.xlsx` | Aba Comparação preenchida com os indicadores dos 8 cenários |
| `dados.json` | Todos os resultados e o dia gravado que alimenta o 3D |

Opções: `--itens 60 --dias 365 --semente 42`. Para refazer a página 3D é preciso do Three.js:
`cd viewer && npm install three@0.128.0`.

Testes: `python tests/test_motor.py` (13 verificações de consistência).

## Como funciona

```
layout.py    almoxarifado como dados (racks, posições, docas) e rotas pelos corredores
params.py    parâmetros e efeito de cada tecnologia (sem x com); lê a aba Premissas
sim.py       motor de eventos: operadores, estoque FÍSICO x estoque do SISTEMA, indicadores
politicas.py min/max fixo (ERP) e SmartStock (adaptativo)
cenarios.py  roda os 8 cenários, exporta JSON e preenche a planilha
viewer/      página 3D (Three.js) que reproduz o dia gravado, duas vistas lado a lado
```

Cada dia: chegam pedidos e caminhões; operadores caminham, separam, recebem e contam;
o estoque físico muda conforme a realidade e o do sistema conforme o que foi registrado
(retirada sem baixa, erro de recebimento e item fora do endereço geram divergência);
no fim do dia a política de reposição decide os pedidos de compra com base no estoque do SISTEMA.
Por isso a divergência vira ruptura ou excesso, e é aí que RFID e visão computacional agem.

O que cada tecnologia altera (valores em `params.py`, aba Premissas da planilha):

- **RFID**: recebimento e contagem muito mais rápidos, item localizado sem busca, menos erros de
  endereço e de recebimento, leitura automática dos movimentos, alguns alertas falsos.
- **Visão computacional**: menos erro de separação, detecta o erro na estante, menos retiradas sem
  baixa, confere a expedição mais rápido, alguns alertas falsos.
- **SmartStock**: troca o min/max fixo pela reposição adaptativa (consumo e variabilidade
  recentes, prazo do fornecedor, nível de serviço alvo).

Com duas tecnologias ligadas: tempos e probabilidades de erro usam o melhor valor, leituras
automáticas se combinam (1 - (1-a)(1-b)) e alertas falsos somam.

## Como mudar o que quiser

- **Layout**: `ConfigLayout` em `layout.py` (racks, baias, níveis, corredores, ocupação).
- **Operação**: `Params` em `params.py` (operadores, velocidade, tempos, probabilidades, custos).
- **Efeito das tecnologias**: dicionário `EFEITOS` em `params.py`, ou a aba Premissas da planilha.
- **Nova política de reposição**: classe com `iniciar`, `observar`, `decidir` e `limite` em `politicas.py`.
- **Novo indicador**: some no `kpis()` de `sim.py`, na lista `CHAVES` e `ROTULO` de `cenarios.py`
  e na lista `IND` de `viewer/src/main.js`.

## Limites (leia antes de usar os números)

1. **Os efeitos das tecnologias e os custos são premissas, não medições.** Os valores atuais são
   exemplos plausíveis. Troque por dados de fornecedores, artigos ou de um piloto.
2. **Um cenário base não calibrado.** Antes de usar os ganhos como argumento, compare o cenário
   "nada" com o almoxarifado real (ruptura, tempo de separação, divergência).
3. **Uma semente por rodada.** Os resultados variam entre sementes (veja `--semente`); em 5
   sementes testadas, o SmartStock economizou em todas, o RFID ficou perto do empate e a visão
   computacional sozinha não se pagou com os custos de exemplo.
4. **O 3D mostra um único dia** (o dia com mais recebimentos); os indicadores usam o ano inteiro.
5. **Simplificações**: operadores não bloqueiam uns aos outros, itens têm endereço único, sem
   backorder (venda perdida), sem restrição de espaço nem de orçamento, lead time com distribuição normal.
