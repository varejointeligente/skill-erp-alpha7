# Estoque, movimentação, ruptura, transferências e perdas

## Sumário

- [`estoque` — estoque atual](#estoque--estoque-atual)
- [`movimentacaoestoque` — o histórico](#movimentacaoestoque--o-histórico)
- [Estoque mínimo e máximo](#estoque-mínimo-e-máximo)
- [`suspendecompraprodutounidadenegocio`](#suspendecompraprodutounidadenegocio)
- [Métrica canônica de ruptura](#métrica-canônica-de-ruptura)
- [Cobertura de estoque e excesso](#cobertura-de-estoque-e-excesso)
- [Transferências entre lojas](#transferências-entre-lojas)
- [Perdas, baixas e vencimento](#perdas-baixas-e-vencimento)
- [Inventário](#inventário)
- [Reconstruir estoque numa data passada](#reconstruir-estoque-numa-data-passada)

---

## `estoque` — estoque atual

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `embalagemid` | bigint FK | → `embalagem` (unique por embalagem+loja) |
| `unidadenegocioid` | bigint FK | → `unidadenegocio` |
| `estoque` | numeric | Quantidade atual — **pode ser NEGATIVO** (venda sem baixa) |
| `ultimamovimentacaoestoqueid` | bigint FK | → `movimentacaoestoque` |

Join canônico:

```sql
LEFT JOIN estoque est
       ON est.embalagemid = e.id
      AND est.unidadenegocioid = un.id
```

### ⚠️ Duas armadilhas estruturais

1. **`estoque` é por embalagem+loja; mínimo/máximo/custo/curva são por produto+loja.** Para
   comparar, agregar:

```sql
estoque_prod_loja AS (
  SELECT est.unidadenegocioid, e.produtoid, SUM(est.estoque) AS estoque_total
  FROM estoque est
  JOIN embalagem e ON e.id = est.embalagemid
  GROUP BY est.unidadenegocioid, e.produtoid
)
```

2. **~85% das linhas de `estoque` estão ≤ 0** — toda embalagem já cadastrada tem linha, mesmo que a
   loja nunca a tenha comprado. Por isso **"ruptura" nunca pode ancorar em `estoque <= 0` puro**;
   precisa ancorar em demanda recente ou no mix com mínimo.

## `movimentacaoestoque` — o histórico

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `embalagemid` | bigint FK | → `embalagem` |
| `unidadenegocioid` | bigint FK | → `unidadenegocio` |
| `tipomovimentacaoestoqueid` | bigint FK | → `tipomovimentacaoestoque` |
| `datahora` | timestamp | Quando ocorreu |
| `quantidade` | numeric | Quantidade movimentada |
| `estoqueanterior` | numeric | Estoque antes |
| `estoque` | numeric | Estoque depois (o **delta** aplicado) — é o valor somado ao reconstruir estoque numa data passada (ver o final deste arquivo) |
| `custo` | numeric | **Custo unitário no momento** |
| `customedio` | numeric | **Custo médio no momento** |
| `precovenda` | numeric | **Preço de venda no momento** |
| `precoreferencial` | numeric | Preço referencial no momento |
| `naoatualizarestoque` | boolean | Movimentação que não afeta saldo — filtrar fora ao reconstruir |
| `usuarioid` | bigint FK | → `usuario` |

### Tipos de movimentação (`tipomovimentacaoestoque`)

⚠️ **São duas listas independentes, e a correspondência entre elas NÃO foi verificada.** Os **ids**
com descrição vieram de inspeção do ERP; os **códigos** (`tipomovimentacaoestoque.codigo`) vieram de
extrações do ERP, que nunca trazem o `id` junto. Ninguém fez o `SELECT id, codigo, descricao FROM
tipomovimentacaoestoque` que ligaria as duas — **confirmar no banco antes de usar código e id como
sinônimos.**

**Lista 1 — ids e descrição (observados no ERP):**

| id | Descrição |
| --- | --- |
| 17 | Recebimento Físico (compra) |
| 18 | Estorno de Recebimento Físico |
| 19 | Inventário Entrada |
| 20 | Inventário Saída |
| 21 | Transferência (saída) |
| 22 | Estorno de Transferência |
| 23 | Recebimento de Transferência (entrada) |
| 26 | Venda |
| 27 | **Devolução de Venda** |
| 30 | Estorno de Venda |
| 31 | Baixa de Estoque |
| 32 | Devolução de Compra |

**Lista 2 — códigos observados em extrações do ERP (`tipomovimentacaoestoque.codigo`), sem id
associado:**

`RF`, `ERF`, `RTR`, `TRF`, `ETR`, `VND`, `DVV`, `EVND`, `EEV`, `BAIXA`, `DVC`, `CES`, `CEE`.

Nessas extrações os códigos aparecem apenas agrupados por **efeito no saldo** (ver
"Reconstruir estoque numa data passada", no fim deste arquivo):
`('RF','RTR','ETR','DVV','EVND','EEV')` de um lado,
`('ERF','TRF','VND','BAIXA','DVC')` do outro, com `CES`/`CEE` isolados. Os nomes sugerem a leitura
óbvia (`RF`=recebimento físico, `VND`=venda, `DVV`=devolução de venda, `CES`/`CEE` = correção de
estoque saída/entrada), mas isso é **inferência pelo nome, não medição** — e há mais códigos (13)
do que ids listados (12), então o mapeamento não é sequer 1:1.

📌 **Lacuna:** rodar `SELECT id, codigo, descricao FROM tipomovimentacaoestoque ORDER BY id` e
substituir estas duas listas por uma só.

### ⚠️⚠️ 32,2 MILHÕES de linhas e SEM índice em `datahora`

Índices existentes: `embalagemid + unidadenegocioid`, `id`, e `id + custo + customedio`.
Não há índice em `datahora` → qualquer filtro de período faz **Seq Scan da tabela inteira**.

Medição real de três alternativas para calcular CMV histórico:

| Abordagem | Tempo |
| --- | --- |
| `movimentacaoestoque` direto (tipos 26/30/27) | **54 s** ← escolhida |
| `itemvenda` + `custoproduto` | 80 s |
| `itemvenda → movimentacaoestoque` por `itemvenda.movimentacaoestoqueid` (tentando usar o índice `id+custo+customedio`) | **118 s — a pior** |

Filtrar um mês só **não ajuda** — o Seq Scan varre tudo de qualquer jeito.
Como o ERP é somente leitura, não dá para criar índice.

⚠️ **A terceira linha é contraintuitiva e vale destacar:** o JOIN por
`itemvenda.movimentacaoestoqueid` **parece** a opção óbvia — é join por id, contra um índice que
inclui exatamente as colunas de custo — e por isso é o caminho que aparece com mais frequência em
query herdada de extração de CMV. Mas contra 32,2 mi de linhas ele ficou **mais que o dobro** do Seq
Scan direto. Se encontrar texto (aqui ou em outro lugar) chamando esse JOIN de "a forma barata de
obter custo histórico", é a intuição falando, não a medição.

(O que **continua válido** é a *fonte*: `movimentacaoestoque.custo`/`.customedio` alcançados por
`itemvenda.movimentacaoestoqueid` são o custo **do momento da venda**, não o custo de hoje aplicado
retroativamente. O problema é só o custo de execução do caminho.)

→ **Consequência de arquitetura:** métrica que depende de `movimentacaoestoque` por período precisa
de **snapshot/cache diário**, não pode ser calculada a cada request.

### Quando usar `movimentacaoestoque` em vez de `custoproduto`

| Pergunta | Fonte |
| --- | --- |
| "Qual o custo desse produto hoje?" | `custoproduto.customedio` / `.custo` |
| "Qual era o custo no momento em que essa venda aconteceu?" | `movimentacaoestoque.customedio` |
| "CMV real do mês (custo do que foi vendido naquele mês)" | `movimentacaoestoque` tipos 26 (venda) − 30 (estorno) − 27 (devolução) |

Uma varredura só de `movimentacaoestoque` entrega venda, estorno, devolução **e** a receita
devolvida (`precovenda`) de uma vez.

Descasamento medido entre "pago a fornecedor" e "CMV do vendido": jan/2026 pagou **R$ 10,42 mi** de
mercadoria e vendeu **R$ 8,44 mi** (margem subestimada em ~R$ 2 mi só nesse mês); no ANO os dois
quase empatam (R$ 64,08 mi × R$ 63,40 mi).

## Estoque mínimo e máximo

### `estoqueminimoprodutounidadenegocio`

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `produtoid` | bigint FK | → `produto` (unique por produto+loja) |
| `unidadenegocioid` | bigint FK | → `unidadenegocio` |
| `estoqueminimo` | numeric | **Filtrar `> 0`** = produto faz parte do mix da loja |
| `origem` / `tipo` | char(1) | Origem/tipo da definição |
| `datainclusao` / `datavigencia` | timestamp | |

Volume: ~87,8 mil combos produto+loja com `estoqueminimo > 0` em 18 lojas.

### `estoquemaximoprodutounidadenegocio`

Mesma estrutura, com `estoquemaximo`.

⚠️⚠️ **Nesta rede tem apenas 3 linhas cadastradas** — é **inutilizável** como fonte de "estoque
máximo". Quem precisa de "excesso" usa **cobertura de estoque** (ver abaixo), não essa tabela.

## `suspendecompraprodutounidadenegocio`

| Coluna | Descrição |
| --- | --- |
| `produtoid` | → `produto` |
| `unidadenegocioid` | → `unidadenegocio` |
| `origem` | `'C'` = manual (decisão humana explícita), `'A'` = automática (a maioria, ~324 mil linhas) |
| `motivoid` | → motivo da suspensão |

Volume total ~379 mil linhas.

**Regra canônica (decisão do gestor, 04/07/2026): qualquer suspensão — manual OU automática —
exclui o produto da métrica de ruptura.** Se o sistema não vai comprar o item de qualquer forma, não
faz sentido contá-lo como falta.

```sql
AND NOT EXISTS (
  SELECT 1 FROM suspendecompraprodutounidadenegocio s
  WHERE s.produtoid = e.produtoid
    AND s.unidadenegocioid = v.unidadenegocioid
)
```

⚠️ **Na análise de OFERTA a regra é inversa**: ambas as origens contam **a favor** de sugerir o
produto para oferta (as duas sinalizam que a rede não vai repor, reforçando a necessidade de escoar).

## Métrica canônica de ruptura

**Definição validada com o gestor:** um produto está **em ruptura** numa loja quando teve **venda nos
últimos 60 dias** (demanda comprovada) **E** o estoque agregado por produto é **≤ 0**, excluindo
produtos com qualquer suspensão de compra. **Não usa o cadastro de estoque mínimo.**

| Métrica | Fórmula |
| --- | --- |
| **Produtos vendidos 60d** | `COUNT(DISTINCT produto)` com `v.status='F' AND iv.status='F'` e `datahorafechamento >= NOW() - INTERVAL '60 days'` (contexto, não é denominador) |
| **Itens em ruptura** (numerador) | dos vendidos 60d, os com `SUM(estoque) <= 0` por `(loja, embalagem.produtoid)` |
| **Itens com estoque** | `COUNT` de produtos `tipo='M'` com `SUM(estoque) > 0` na loja — **todo o catálogo**, independente de venda recente |
| **% ruptura da loja** | `itens em ruptura ÷ (itens com estoque + itens em ruptura)` |
| **Venda média/dia** | `qtd_vendida_60d / 60` (por produto) |
| **Venda perdida estimada/mês** | `(qtd_60d/60) * 30 * preco_medio_unitario` |

**Notas de fórmula:**

- ⚠️ O denominador **inclui a própria ruptura** desde 12/07/2026 — antes era só "itens com estoque",
  dois conjuntos disjuntos, que em tese podiam passar de 100%. Com o denominador = universo total,
  o % lê-se como "% do catálogo relevante que está em falta" e nunca excede 100%.
- ⚠️ **KPI de rede é PONDERADO** (`Σ itens ruptura ÷ Σ denominador`), nunca média aritmética dos %.
- Filtro obrigatório `produto.tipo = 'M'` (serviços dariam ruptura falsa).
- Threshold de alerta: **15%** (`RUPTURA_ALERTA = 0.15`).
- Histórico: a janela era 90 dias até 04/07/2026. Com 90 dias, ~39% dos produtos no denominador
  tinham vendido menos de 3 unidades no período inteiro (mediana 3 un./90d) — muita "ruptura" era
  ruído de venda esporádica. Rede toda passou de ~26,2 mil itens (90d) para ~15,6 mil (60d).

**Cobertura de estoque, por outro lado, manteve a janela de 90 dias e só exclui suspensão manual** —
deliberadamente. Usar CTEs separadas (`vendidos_ruptura_60d` e `vendidos_cobertura_90d`) para não
acoplar as duas janelas.

### ⚠️ `historicovenda` — agregado de venda pré-computado pelo próprio ERP

Existe uma tabela **`historicovenda`** (`unidadenegocioid`, `embalagemid`, `quantidade`, `data`) que
guarda venda já agregada por loja+embalagem+data. Se a cobertura se confirmar, ela é
**potencialmente muito mais barata** que varrer `venda + itemvenda` para calcular demanda histórica:

```sql
SELECT hv.unidadenegocioid, hv.embalagemid,
       SUM(hv.quantidade)        AS quantidade,
       SUM(hv.quantidade) / 90.0 AS demanda
FROM historicovenda hv
WHERE hv.data > (CURRENT_DATE - INTERVAL '90 days')
GROUP BY hv.unidadenegocioid, hv.embalagemid
```

⚠️ **Observada numa extração, nunca validada ao vivo.** Não se sabe desde quando ela é populada, se
cobre todas as lojas, nem se o `quantidade` já é líquido de devolução. 📌 **Lacuna:** medir cobertura
(comparar um mês de `historicovenda` contra `venda + itemvenda` do mesmo mês) **antes** de trocar a
fonte de demanda de qualquer métrica.

### Variante de ruptura observada em extração (para explicar divergência)

Se alguém trouxer um número de ruptura que não bate com o canônico acima, esta é a variante já vista
em uso — útil só para reconciliar, **não** para substituir a métrica validada:

| Aspecto | Variante observada | Canônico |
| --- | --- | --- |
| Janela de demanda | 90 dias | **60 dias** |
| Granularidade | embalagem | **produto** (`SUM(estoque)` agregado) |
| Condição de estoque | `estoque = 0` | `SUM(estoque) <= 0` (inclui negativo) |
| Fonte de demanda | `historicovenda` | `venda` + `itemvenda` |
| Filtro de tipo | só `p.status='A'` | também `p.tipo='M'` |
| Preço da venda perdida | `embalagem.precoreferencial` | preço médio unitário praticado |

A exclusão por `suspendecompraprodutounidadenegocio` aparece nas duas.

### Complemento: "pedido enviado, mas o item não chegou" (14 dias)

Sinal mais específico que "ninguém tentou repor". Para cada produto+loja:

1. Pega o **primeiro** `pedidocompra` (status ≠ `'D'`) OU `pedidotransferencia` (status ≠ `'D'`,
   destino = a loja) feito nos **últimos 14 dias**;
2. Verifica se, **depois** dessa data, existe alguma `itemnotafiscal` (via `embalagem → produtoid`)
   de uma `notafiscal` da mesma loja com `datahoraentrada` preenchida (excluindo CFOP de serviço,
   separando compra de fornecedor × transferência pelo CFOP);
3. Sem entrada desde a data do pedido = "enviado mas não chegou".

⚠️ **Não usar o vínculo formal `recebimentofisicopedidocompra`** aqui — ele cobre só ~6% dos
recebimentos reais desta rede e marcaria quase todo pedido como "sem chegada".

⚠️ **Pré-agregar as 4 CTEs e unir por `LEFT JOIN`**, nunca `EXISTS` correlacionado por linha:
`pedidos_compra_14d` / `pedidos_transferencia_14d` (com `MIN(data_pedido)`) e
`entradas_fornecedor_14d` / `entradas_transferencia_14d` (com `MAX(data_entrada)`), unidas via
`UNION ALL` + `GROUP BY`, e só então comparadas
(`data_entrada IS NULL OR data_entrada < data_pedido`).

Medição: ~54% dos itens em ruptura da rede (7.208 de 13.364) não tinham nenhum pedido/transferência
nos últimos 10 dias, na versão anterior da métrica.

## Cobertura de estoque e excesso

**Cobertura (dias)** = `estoque_total ÷ (qtd_vendida_90d ÷ 90)` — quantos dias o estoque atual dura
no ritmo de venda dos últimos 90 dias. Ponderada (soma/soma), só produtos com estoque > 0.

**Giro (vezes/ano)** = `365 ÷ Cobertura` — derivado da mesma base, para não ter duas fórmulas de giro
divergentes.

**Excesso estrutural** (candidato a oferta): produto em excesso (**cobertura > 90 dias**, OU
estoque > 0 com **zero venda em 90 dias**) em **metade ou mais das lojas ativas da rede**.

- O threshold de "metade" é calculado dinamicamente (`CEIL(total_lojas_ativas / 2)`), nunca
  hardcoded — muda sozinho se abrir/fechar loja.
- Distingue **problema estrutural de rede** (resolve com oferta) de excesso pontual de 1–2 lojas
  (resolve com transferência).
- ⚠️ `total_lojas_ativas` inclui unidades não-varejo que nunca têm estoque farmacêutico — o
  threshold fica levemente mais rígido; efeito considerado pequeno.

**Ranking de candidatos a oferta:** por **valor de estoque parado** (`estoque_total × custo_médio_rede`)
— foco no maior capital imobilizado primeiro.

Volume real: ~20 mil produtos candidatos na rede (a maioria por suspensão ou Curva D — essas duas
são bem menos seletivas que excesso estrutural, que sozinha dá ~1,7 mil produtos).

## Transferências entre lojas

Três conceitos distintos — **não confundir**:

```text
pedidotransferencia   = o PEDIDO/lista que o comprador monta
transferencia         = o documento de EXECUÇÃO/envio
recebimentotransferencia = a confirmação de recebimento no destino
```

A relação pedido ↔ transferência é **N:N**, via **`transferenciapedido`**
(`pedidotransferenciaid`, `transferenciaid`): um pedido pode virar várias transferências (envio
parcial) e uma transferência pode atender vários pedidos (envio consolidado, ~46% dos casos).

⚠️ **Nunca contar `transferencia` como proxy de "listas pendentes" nem de "tempo de execução do
pedido"** — usar `pedidotransferencia`.

### Linha do tempo canônica

```text
pedidotransferencia.datahora      → solicitação (comprador montou a lista)
transferencia.datahorafinal       → separação/envio concluído na ORIGEM (via transferenciapedido)
recebimentotransferencia.datahora → recebimento confirmado no DESTINO
```

### `pedidotransferencia`

| Coluna | Descrição |
| --- | --- |
| `datahora` | Solicitação — filtro de período |
| `unidadenegocioorigemid` | Loja que vai ATENDER — **100% preenchido**, nunca igual ao destino |
| `unidadenegociodestinoid` | Loja que SOLICITOU |
| `usuarioid` | Quem solicitou |
| `status` | `'A'` aberto/pendente (0% tem execução ou cancelamento — estado limpo, ~750 registros) · `'C'` concluído (100% tem transferência com `datahorafinal`, ~96%) · `'D'` majoritariamente cancelado (~87% tem registro em `pedidotransferenciacancelamento`) · `'B'` concluído por outra via (~0,6%) |
| `origem` | `'A'` **Sugestão Transferência** (~99%) · `'C'` **Sugestão Compra** (~1%) · `'D'` **Transferência Automatizada** (100% correlacionado com `compraautomatizadaid`) · `'B'` **Encomenda** (100% correlacionado com `encomendaorigemid`) |

`itempedidotransferencia` liga **direto em `produtoid`**, sem passar por `embalagem` — exceção rara.

### `transferencia` / `itemtransferencia`

- `transferencia`: `unidadenegocioorigemid`, `unidadenegociodestinoid`, `datahora`,
  `datahorafinal`, `usuarioid` (quem processou a separação — campo próprio da execução, sem
  correlação com nenhum usuário do pedido), `status`.
- `itemtransferencia`: `embalagemid`, `quantidade`, `valorunitario`, `valortotal`,
  `movimentacaoestoqueid`, `status` (`'E'`, `'R'`, `'S'` observados).
- `itemrecebimentotransferencia`: `recebimentotransferenciaid`, `embalagemid`, `status`, e
  **`movimentacaoestoqueid` próprio** — o item recebido aponta para a movimentação de estoque que
  ele gerou no destino (não é preciso passar pelo item enviado para chegar no custo).
- `estornoitemtransferencia` — estorno por item.

⚠️ **Não há FK do item recebido para o item enviado.** Para casar
`itemrecebimentotransferencia` com `itemtransferencia` é preciso usar o par
**`(transferenciaid, embalagemid)`** — o que significa que uma transferência com a mesma embalagem
em duas linhas não casa de forma determinística.

**Filtro de "transferência recebida" observado em extrações:** `transferencia.status = 'R'` +
`itemtransferencia.status IN ('E','R','S')` + `itemrecebimentotransferencia.status = 'F'`.
⚠️ Nenhum desses valores está decodificado em nenhuma fonte — é o filtro que se viu em uso,
**observado numa extração, não validado ao vivo**. Conferir contra a tela antes de depender dele.
- ⚠️ **`transferencia.notafiscalid` NUNCA é preenchido para transferência** (0% de cobertura). A
  nota fica em **`recebimentotransferencia.notafiscalid`** (~80% de cobertura entre as transferências
  com solicitação).

### Métricas de transferência validadas

| Métrica | Definição |
| --- | --- |
| **Tempo de execução** | `pedidotransferencia.datahora` → primeira `transferencia.datahorafinal` vinculada (`MIN()` quando há mais de uma), filtrado a `origem IN ('A','C','D')` (exclui Encomenda). ~1,5 dia em média |
| **Leadtime de entrada (transferência)** | `recebimentotransferencia.datahora − transferencia.datahorafinal`. ~3 dias — é a fase que demora |
| **Tempo de separação** | `notafiscal.datahoraemissao − pedidotransferencia.datahora`, só para transferências **com solicitação**. Média ~1,7 dia (0 casos de emissão antes da solicitação) |
| **Backlog de pendências** | `pedidotransferencia` com `status='A'` (~750–830 registros) |
| **Atraso** | **≥ 2 dias ÚTEIS** desde a solicitação, agrupado pela **ORIGEM** (quem precisa separar/enviar) |
| **Com/sem solicitação** | Toda `transferencia` classificada por ter ou não `pedidotransferencia` vinculado via `transferenciapedido`. ~50/50 na rede |

**Atraso em dias úteis** (SQL puro, sem calendário de feriados):

```sql
LEFT JOIN LATERAL (
  SELECT d::date AS data_atraso
  FROM (
    SELECT d, ROW_NUMBER() OVER (ORDER BY d) AS rn
    FROM generate_series(pt.datahora::date + 1, CURRENT_DATE, '1 day') d
    WHERE EXTRACT(ISODOW FROM d) < 6      -- só seg-sex
  ) s
  WHERE rn = 2                             -- 2º dia útil = limite de "2 dias úteis"
) atr ON TRUE
```

- Impacto medido ao trocar dias corridos por dias úteis: **493 → 130** pedidos em atraso na rede
  (mesmo snapshot). Muitos "atrasados" só ultrapassavam 2 dias por atravessar um fim de semana.
- Um `LATERAL` por linha é barato **aqui** (backlog de ~750 pedidos) — diferente de `venda`.
- **Limite diferente para o CD:** 3 dias úteis em vez de 2 (o CD opera em escala muito maior).
  Efeito: CD caiu de 198 para 8 pedidos "atrasados".
- **Papel da loja é intencionalmente misto** numa mesma linha de relatório ("visão 360°"): leadtime
  e tempo de execução por **destino**; atraso e "pendente para envio" por **origem**; NF pela própria
  loja.

## Perdas, baixas e vencimento

### `baixaestoque` / `itembaixaestoque` / `motivo`

| Tabela | Colunas relevantes |
| --- | --- |
| `baixaestoque` | `unidadenegocioid`, `datahora`, `datahorainicial`, `motivoid`, `usuarioid`, `status` (`'F'` Finalizada — filtrar por isso; `'C'` Cancelada) |
| `itembaixaestoque` | `baixaestoqueid`, `embalagemid`, `quantidade`, `valorunitario`, **`valortotal`** (não tem coluna `custo` — o valor já vem calculado), `status` |
| `motivo` | `descricao` |

**Motivos reais encontrados:** "PRODUTO VENCIDO", "PRODUTO VENCEU", "FURO DE ESTOQUE",
"PRODUTO DANIFICADO", "USO E CONSUMO - …", "FURTO/ROUBO", "BAIXA DE ESTOQUE BONIFICADO".

⚠️ **Múltiplos `motivo.id` têm a MESMA descrição** — nunca hardcodar um id. Sempre:

```sql
WHERE m.descricao ILIKE '%vencid%' OR m.descricao ILIKE '%venceu%'
```

**Definições usadas:**

- **"Vencidos"** = produtos **já baixados do estoque** por motivo de vencimento (ação que já
  aconteceu, olhando para trás num período) — **não** é "produtos vencidos ainda parados em
  estoque" (isso seria via `loteembalagem.datavalidade`, tabela que existe mas não é usada para essa
  métrica).
- **"Estragado"** = motivo `%danific%` / `%estrag%`.
- **"Baixa (perdas)"** = baixas exceto uso/consumo/bonificado.
- **% Perda por vencimento** = `valor de baixa por vencimento ÷ receita líquida do período`
  (sobre o valor de VENDA, não sobre CMV nem sobre compras).
- **Perda Operacional** (DRE) = Perda de Estoque + Quebra de Inventário.
  ⚠️ Não aparece em regime de caixa: baixa de estoque **não é conta a pagar**.

### `devolucaocompra` — devolução ao fornecedor

Ver [07-compras-precificacao.md](07-compras-precificacao.md). Nota importante: ⚠️ **todos os status
têm `datahorafinal` preenchida** (diferente de `transferencia`/`notafiscal`, onde a data nula indica
pendência) — não dá para usar null-check aqui.

## Inventário

- `movimentacaoestoque` tipo **19** = Inventário Entrada, tipo **20** = Inventário Saída.
- "Quebra de Inventário" entra na Perda Operacional do DRE junto com Perda de Estoque.
- Correções de estoque aparecem nos códigos `CES` (saída) / `CEE` (entrada) do
  `tipomovimentacaoestoque`.

## Reconstruir estoque numa data passada

Padrão usado em snapshot diário de estoque. Pega, para cada (loja, embalagem), **a última
movimentação antes do corte**, com desempate por prioridade de tipo:

```sql
SELECT me.unidadenegocioid,
       me.embalagemid,
       $1::date                                        AS dataestoque,
       SUM(me.estoque)                                 AS estoque,
       AVG(me.custo)                                   AS custo_unitario,
       SUM(me.custo      * me.estoque)                 AS estoque_custo,
       AVG(me.customedio)                              AS custo_medio_unitario,
       SUM(me.customedio * me.estoque)                 AS estoque_custo_medio,
       AVG(me.precoreferencial)                        AS preco_referencial,
       SUM(me.precoreferencial * me.estoque)           AS estoque_preco_referencial,
       AVG(me.precovenda)                              AS preco_venda_unitario,
       SUM(me.precovenda * me.estoque)                 AS estoque_preco_venda
FROM (
  SELECT m.id, m.unidadenegocioid, m.embalagemid,
         RANK() OVER (
           PARTITION BY m.unidadenegocioid, m.embalagemid
           ORDER BY m.datahora DESC,
                    CASE
                      WHEN t.codigo IN ('RF','RTR','ETR','DVV','EVND','EEV') THEN 1
                      WHEN t.codigo = 'CES'                                   THEN 2
                      WHEN t.codigo = 'CEE'                                   THEN 3
                      WHEN t.codigo IN ('ERF','TRF','VND','BAIXA','DVC')      THEN 4
                    END DESC,
                    m.id DESC
         ) AS pos
  FROM movimentacaoestoque m
  JOIN tipomovimentacaoestoque t ON t.id = m.tipomovimentacaoestoqueid
  WHERE m.datahora < $1
    AND NOT m.naoatualizarestoque
) sub
JOIN movimentacaoestoque me ON me.id = sub.id
WHERE sub.pos = 1
  AND me.estoque <> 0
GROUP BY 1,2,3
HAVING SUM(me.estoque) <> 0;
```

> Nota: `$1` é a data-base do corte. `me.estoque` aqui é o saldo resultante gravado na movimentação.
>
> **Prioridade de desempate** (quando há várias movimentações no mesmo timestamp): entradas
> (`RF`, `RTR`, `ETR`, `DVV`, `EVND`, `EEV`) → `CES` (correção de estoque saída) → `CEE` (correção
> de estoque entrada) → saídas (`ERF`, `TRF`, `VND`, `BAIXA`, `DVC`). Sem esse desempate, duas
> movimentações no mesmo segundo produzem saldo diferente a cada execução.
