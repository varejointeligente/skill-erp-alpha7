# Vendas no Alpha 7

## Sumário

- [`venda` — cabeçalho](#venda--cabeçalho)
- [`itemvenda` — itens](#itemvenda--itens)
- [Quem é o vendedor de verdade](#quem-é-o-vendedor-de-verdade)
- [`pagamentovenda` / `formapagamento`](#pagamentovenda--formapagamento)
- [Devolução de venda](#devolução-de-venda)
- [Canais digitais, televendas e entrega](#canais-digitais-televendas-e-entrega)
- [Fórmulas canônicas de faturamento, margem e ticket](#fórmulas-canônicas-de-faturamento-margem-e-ticket)
- [Thresholds de alerta](#thresholds-de-alerta)
- [Template de query de venda por loja](#template-de-query-de-venda-por-loja)

---

## `venda` — cabeçalho

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `unidadenegocioid` | bigint FK | → `unidadenegocio` (qual loja) |
| `usuarioid` | bigint FK | → `usuario` — **operador do CAIXA/PDV, não o vendedor** |
| `pessoaid` | bigint FK | → `pessoa` (cliente; pode ser NULL = não identificado) |
| `status` | char(1) | `'F'` = Finalizada, `'C'` = Cancelada, `'D'` = Devolvida por inteiro, **`'G'` = ⚠️ NÃO CONFIRMADO** (ver abaixo) |
| `datahoraabertura` | timestamp | Início da venda |
| `datahorafechamento` | timestamp | Conclusão — **é a coluna de filtro de período** |
| `valortotal` | numeric | Valor total da venda |
| `valortroco` | numeric | Troco |
| `caixaid` | bigint FK | → `caixa` |
| `sessaocaixaid` | bigint FK | → `sessaocaixa` |
| `orcamentoid` | bigint FK | → `orcamento` (carrinho que originou a venda) |
| `cadernoofertaid` | bigint FK | → `cadernooferta` — ⚠️ quase sempre convênio/clube, **não** promoção de encarte |
| `coo` | varchar | Número do cupom fiscal |

**Distribuição de status observada** numa base: `F` ~9,15 mi · `C` ~221 mil · `G` ~23 mil · `D` ~10 mil.
(A soma, ~9,4 mi, é de onde vem o volume "medido" de `venda` citado na visão geral — é **derivado**.)

⚠️ **`venda.status = 'G'` NÃO está decodificado.** Só o volume foi medido (~23 mil). O rótulo
"Estornada" que circula vem de um mapeamento de **`itemvenda.status`** — **outra tabela**, e
[11-glossario.md](11-glossario.md) avisa que o mesmo caractere significa coisas diferentes em
tabelas diferentes. 📌 **Lacuna:** confirmar na tela do ERP antes de tratar `G` como estorno.

**Regra:** venda válida = `v.status = 'F'`. Não existe coluna `apagado`/`cancelado` separada.

## `itemvenda` — itens

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `vendaid` | bigint FK | → `venda.id` |
| `embalagemid` | bigint FK | → `embalagem.id` (**nunca `produto`**) |
| `unidadenegocioid` | bigint FK | → `unidadenegocio` |
| `itemorcamentoid` | bigint FK | → `itemorcamento` (nullable) |
| `status` | char(1) | `'F'` **Fechado**, `'C'` Cancelado, `'D'` Devolvido, `'G'` Estornado (rótulos observados em extrações do ERP — note que aqui é "Fechado", não "Finalizado" como em `venda`) |
| `quantidade` | numeric | |
| `valorunitario` | numeric | ⚠️ **preço de TABELA, não o negociado** (ver abaixo) |
| `valortotal` | numeric | Total da linha, já com desconto |
| `desconto` | numeric | Desconto percentual |
| `valordesconto` | numeric | Valor efetivo do desconto (unitário) |
| `origemdesconto` | char(1) | Origem do desconto — ver tabela abaixo |
| `datahora` | timestamp | |
| `movimentacaoestoqueid` | bigint FK | → `movimentacaoestoque` (traz `custo`/`customedio` **do momento da venda**) |
| `cadernoofertaid` | bigint FK | → `cadernooferta` — **é aqui que a promoção real é atribuída** |
| `pbmid` | bigint FK | → `pbm` (benefício farmacêutico, nullable) |
| `liberacaousuariodescontopdvid` | bigint FK | ⚠️ **100% vazio em toda a base** (26,2 mi de linhas) — não usar |

### `itemvenda.origemdesconto` — decodificação (10 de 11 valores)

Decodificada por correlação e confirmada por um mapeamento observado em extrações do ERP. **Não é a
lista completa dos valores que existem na base** — ver `F` logo abaixo da tabela:

| Valor | Significado |
| --- | --- |
| `S` | Sem desconto |
| `D` | Caderno de oferta — Desconto |
| `P` | Caderno de oferta — Preço (bate com `venda.cadernoofertaid`/`itemcadernooferta`) |
| `Q` | Caderno de oferta — Desconto por quantidade (leve/pague por faixa) |
| `M` | **Manual** (sem correlação com cupom/PBM/promoção — é o desconto negociado) |
| `B` | PBM (99,97% correlacionado com `itemvenda.pbmid` preenchido) |
| `E` | Caderno de oferta — Markup sobre custo médio |
| `R` | Caderno de oferta — Markup sobre preço referencial |
| `C` | Caderno de oferta — Markup sobre custo |
| `L` | Caderno de oferta — Leve/Pague |
| **`F`** | ⚠️ **NÃO DECODIFICADO** — existe na base (volume baixo) e **não aparece em nenhum dos mapeamentos observados**, que o jogam em "Origem desconhecida". 📌 Lacuna |

⚠️ Os códigos `D`, `C`, `L` e `F` são de **natureza não 100% confirmada** (baixo volume); os
significados de `D`/`C`/`L` na tabela acima vêm desse mapeamento observado numa extração, não de
correlação medida.

Volumes reais (90 dias, **dentro de orçamentos já negociados**): `M`=17.345 · `P`=6.352 ·
`D`=4.304 · `B`=1.682 · `S`=1.205 · `Q`=282 · `L`=58 · `C`=13.

### ⚠️ `itemvenda.valorunitario` é o preço de TABELA

Confirmado com amostra real: item com `itemorcamento.precovenda = 988,23` e `valortotal = 728,45`
(desconto de R$ 259,78) tinha `itemvenda.valorunitario = 988,23` — o preço **cheio**.
O preço unitário efetivamente cobrado é `valortotal / quantidade`.

### ⚠️ `itemvenda.valortotal` nem sempre reflete o desconto

Há um caso conhecido em que `valortotal` **não** incorpora o desconto: quando
`desconto = 0` **e** `valordesconto > 0` (desconto gravado em valor, não em percentual). Uma
extração de venda tratava isso explicitamente, recalculando o valor da linha:

```sql
CASE WHEN (iv.desconto = 0 AND iv.valordesconto > 0)
     THEN iv.quantidade * (iv.valorunitario - iv.valordesconto)
     ELSE iv.valortotal END AS valor
```

⚠️ **Observado numa extração, não validado ao vivo** — antes de adotar o recálculo, medir quantas
linhas caem nessa condição na base em uso e conferir uma delas contra a tela do ERP. A fórmula
canônica de receita continua sendo `SUM(iv.valortotal)`.

### ⚠️ Um `itemorcamento` pode gerar VÁRIOS `itemvenda`

Quando a mesma linha negociada é bipada unidade a unidade no PDV, o Alpha 7 grava um `itemvenda`
por unidade (ex.: quantidade negociada 15 → 15 linhas de `itemvenda` com quantidade 1, todas
apontando para o mesmo `itemorcamentoid`). Medido: **355 de 3.758 itens em 30 dias (~9,4%)** têm
mais de um `itemvenda` batendo, um caso com 15.

→ Se `itemvenda` é usada **só para filtrar** (ex.: `origemdesconto='M'`), usar **`EXISTS`, nunca
`JOIN`** — o `JOIN` causa fan-out e duplica a linha.

## Quem é o vendedor de verdade

⚠️⚠️ **`venda.usuarioid` NÃO é o vendedor** — é quem fechou o caixa/PDV.
O vendedor que atendeu é **`orcamento.usuarioid`** (ou, mais fino, `itemorcamento.usuarioid`).

Medido: **~29% das vendas da rede (15.877 de 55.284 com orçamento vinculado) têm usuário diferente
entre venda e orçamento** — é estrutural (um atende, outro recebe).

**Cascata canônica de atribuição de vendedor** (nunca "pura", sempre com fallback):

```text
itemorcamento.usuarioid  →  orcamento.usuarioid (via venda.orcamentoid)  →  venda.usuarioid
```

⚠️ **Nunca usar atribuição pura por item.** Um `INNER JOIN itemorcamento io ON io.id = iv.itemorcamentoid
AND io.usuarioid IS NOT NULL` faz o vendedor **desaparecer inteiro** da resposta (não "zerado") quando
todas as vendas dele são diretas (sem carrinho) ou têm `usuarioid` nulo no orçamento. Bug real de
comissão que só apareceu quando um colaborador sumiu do relatório.

**Padrão de query** (⚠️ `orcamento.vendaid` **não tem índice** — nunca correlacionar por linha):

```sql
WITH orcamento_usuario AS (
  SELECT o.vendaid AS venda_id, o.usuarioid AS usuario_id
  FROM orcamento o
  WHERE o.vendaid IS NOT NULL AND o.usuarioid IS NOT NULL
)  -- 1:1 validado, sem fan-out
SELECT COALESCE(ou.usuario_id, v.usuarioid) AS vendedor_id, ...
FROM venda v
LEFT JOIN orcamento_usuario ou ON ou.venda_id = v.id
...
```

Cobertura: **~1,4% das vendas não têm orçamento vinculado** (`orcamento.vendaid IS NULL`) — é aí que
o fallback para `venda.usuarioid` entra.

**Onde `venda.usuarioid` continua correto:** métricas que são legitimamente sobre o operador de PDV
(quebra de caixa, sessão de caixa, produtividade de retaguarda, NF recebida por).

## `pagamentovenda` / `formapagamento`

```text
venda → pagamentovenda (1:N) → formapagamento
```

Sub-detalhes por modalidade: `pagamentovendacartao`, `pagamentovendacheque`,
`pagamentovendacrediario`, `pagamentovendapbm`, `pagamentovendavalecompra`,
`pagamentovendafidelidade`.

⚠️⚠️ **`formapagamento.id` é DINÂMICO por banco.** Nunca hardcodar — sempre
`JOIN formapagamento` e casar por `nome`.

IDs observados em **duas bases diferentes** (prova de que variam) — os nomes das plataformas
digitais foram substituídos por rótulos genéricos; o que importa é a **estrutura**: as formas
"clássicas" ficam numa faixa baixa de 2 dígitos e as digitais em ids enormes, diferentes em cada
base:

| Base A | Base B |
| --- | --- |
| 60 Dinheiro · 61 Cartão · 62 Cheque · 63 Crediário · 64 PBM · 65 Vale-Compra | 60 Dinheiro · 61 Cartao · 63 Crediario · 64 PBM · 65 Vale-Compra |
| 4557373 PIX | 50140839229 PIX - MÁQUINA · 50140839226 PIX - CHAVE |
| 250002639592 E-COMMERCE | 200036159276 E-COMMERCE PRÓPRIO · 50068658807 PLATAFORMA_1 |
| 250018615880 MARKETPLACE_A | 800026124703 MARKETPLACE_A · 1200008396523 PLATAFORMA_2 |
| — | 9254533 Cartão de rede · 6172141 Fidelidade · 1600005257317 APP_FARMACIA |

### ⚠️ `pagamentovenda.valor` inclui o TROCO (só no Dinheiro)

`Σ pagamentovenda.valor = venda.valortotal + venda.valortroco`.

Para a distribuição por forma de pagamento fechar com a receita, **subtrair `SUM(venda.valortroco)`
da forma Dinheiro**. Validado: jun/2026 → Σ pagamentos R$ 14,34 mi = receita R$ 13,83 mi + troco
R$ 0,52 mi.

### Descontos no nível da venda (cabeçalho)

| Tabela | Uso |
| --- | --- |
| `descontoacrescimovenda` | Desconto/acréscimo no cabeçalho: `vendaid`, `origem`, `desconto` (boolean), `valor` |
| `cupomdesconto` / `vendacupomdesconto` | Cupons aplicados na venda |
| `itemvendadesconto` | Desconto por item: `itemvendaid`, `origemdesconto` (`P`=promoção via caderno, `D`=outro), `valordesconto`, `cadernoofertaid`. **Raríssimo** (~295 itens com origem `P` em ~470 mil vendidos em 30d) — a maioria dos itens de oferta é vendida direto no preço reduzido, sem gerar registro de desconto. Não serve como proxy principal |

## Devolução de venda

Existem **duas fontes**, com propósitos diferentes:

### 1. `movimentacaoestoque` tipo 27 — fonte padrão para valor/custo

`tipomovimentacaoestoqueid = 27` = Devolução de Venda. **Não tem `pessoaid` nem `vendaid`**, mas tem
`precovenda` e `customedio` congelados no momento — é a fonte canônica para receita/custo devolvidos.

```sql
SELECT me.unidadenegocioid AS loja_id,
       SUM(ABS(me.quantidade) * COALESCE(me.precovenda,0))  AS valor_devolvido,
       SUM(ABS(me.quantidade) * COALESCE(me.customedio,0))  AS custo_devolvido
FROM movimentacaoestoque me
WHERE me.tipomovimentacaoestoqueid = 27
  AND me.datahora BETWEEN $1::timestamp AND $2::timestamp
GROUP BY me.unidadenegocioid;
```

### 2. `devolucaovenda` / `itemdevolucaovenda` — fonte ligada ao CLIENTE

| Coluna | Descrição |
| --- | --- |
| `id` | bigint PK |
| `vendaid` | FK → `venda` — **100% preenchido** (12 meses: 0 devoluções órfãs) |
| `pessoaid` | FK → `pessoa` — 100% preenchido; diverge de `venda.pessoaid` em só 0,17% dos casos (existe `liberacaousuarioalterarpessoanadevolucaoid`, ou seja, dá para trocar a pessoa na devolução). **Para receita líquida por cliente, usar sempre o `pessoaid` da VENDA** |
| `unidadenegocioid` | Loja — **sempre igual à loja da venda** (0 divergências em 12m) |
| `datahora` / `valortotal` / `motivo` | 99,2% referenciam venda do mesmo período |

`itemdevolucaovenda`: `devolucaovendaid`, `embalagemid`, `itemvendaid`, `movimentacaoestoqueid`,
`quantidade`, `valortotal`.

### ⚠️⚠️ `venda.status = 'D'` = venda DEVOLVIDA POR INTEIRO — não subtrair

A receita bruta só soma `status='F'`, então a venda `'D'` **já está fora**; descontar a devolução
dela contaria o estorno duas vezes.

Validado (12 meses): das 16.469 devoluções, **4.183 apontam para venda `'D'`** (R$ 519 mil) e 12.286
para venda `'F'` (R$ 1,02 mi) — e essas últimas são quase todas **parciais** (12.282 de 12.286).

```sql
-- devolução do período, SÓ de venda 'F'
SELECT v.pessoaid, SUM(dv.valortotal) AS devolvido
FROM devolucaovenda dv
JOIN venda v ON v.id = dv.vendaid
WHERE v.status = 'F'
  AND v.datahorafechamento BETWEEN $1::timestamp AND $2::timestamp
GROUP BY v.pessoaid;
```

Peso real: devolução = **0,66% da receita** de clientes identificados em 12 meses.

> ⚠️ Não confundir com **devolução de COMPRA** (`devolucaocompra` — mercadoria devolvida ao
> fornecedor). Ver [07-compras-precificacao.md](07-compras-precificacao.md).

## Canais digitais, televendas e entrega

- **Canal digital** é identificado pela **forma de pagamento** (`pagamentovenda → formapagamento`),
  não por um campo de canal. ⚠️ **Quais canais existem é contrato de cada rede** — levantar por
  `SELECT id::text, nome FROM formapagamento` na base em uso. Numa rede foram 5 (marketplaces de
  delivery e plataformas de e-commerce farmacêutico). Há ainda formas genéricas
  (`commerce`/`digital`/`online`) que não viram canal próprio.
- ⚠️ **Uma mesma venda pode ter 2+ formas digitais** — existem itens com
  `canais = [E-COMMERCE PRÓPRIO, MARKETPLACE_A, PLATAFORMA_2]` na mesma venda. Somar produto sobre uma CTE
  "uma linha por venda+canal" **duplica o item**. Medido: soma dos 5 canais R$ 36.648,62 ×
  total sem duplicar R$ 34.434,41 → **6,4% de inflação pura**.
  → Para o total "todos os canais", usar uma CTE que agrupa **por venda** e devolve
  `array_agg(canal)`; e manter o `unnest` dos canais **isolado numa CTE de rótulo**, nunca junto do
  `SUM`.
- **Televendas** = venda ligada a uma **`entrega` não cancelada**, agregada por **CIDADE**
  (`unidadenegocio.cidade`, com `UPPER(TRIM(...))` — o cadastro é texto livre e varia de caixa entre
  lojas da mesma cidade). Televendas atende uma cidade inteira, não uma filial.
- Ao filtrar "venda com entrega", ⚠️ **nunca** usar `EXISTS` correlacionado contra `orcamento`
  (sem índice em `vendaid`; uma query real levou ~14 minutos). Pré-computar:

```sql
WITH entrega_vendas AS (
  SELECT DISTINCT o.vendaid AS venda_id
  FROM entrega e
  JOIN orcamento o ON o.id = e.orcamentoid
  JOIN venda v ON v.id = o.vendaid
  WHERE v.datahorafechamento BETWEEN $1::timestamp AND $2::timestamp
    AND e.status <> 'C'
)
-- depois LEFT JOIN entrega_vendas ev ON ev.venda_id = v.id
```

## Fórmulas canônicas de faturamento, margem e ticket

Validadas com o gestor e usadas em todos os relatórios da rede.

| Métrica | Fórmula | Observação |
| --- | --- | --- |
| **Receita bruta** | `SUM(iv.valortotal)` com `v.status='F' AND iv.status='F'` | Já com desconto aplicado |
| **Devoluções** | `SUM(ABS(me.quantidade) * me.precovenda)` para `me.tipomovimentacaoestoqueid = 27` | Snapshot do preço no momento |
| **Receita líquida** | Receita bruta − Devoluções | Padrão para qualquer dashboard de lucro/margem |
| **Custo (médio)** | `SUM(iv.quantidade * cp.customedio)` − custo das devoluções | Via `custoproduto` por produto+loja |
| **Custo (última compra)** | `SUM(iv.quantidade * cp.custo)` − custo das devoluções | Útil para ver impacto de alta recente |
| **Lucro bruto** | Receita líquida − Custo | Calcular médio e última **separadamente** |
| **Margem %** | Lucro ÷ Receita líquida | Receita = 0 → retornar 0, nunca dividir por zero |
| **CMV %** | Custo ÷ Receita líquida | CMV% + Margem% = 100% |
| **Cupons** | `COUNT(*)` em `venda` com `v.status='F'` | Subquery separada — `COUNT(DISTINCT v.id)` sobre `itemvenda` é caro |
| **Ticket médio** | Receita líquida ÷ Cupons | Cupons = 0 → 0 |

**Regras de ouro derivadas:**

- ⚠️ **Sempre somar os componentes brutos ANTES de dividir.** Nunca média de percentuais, nunca
  média de médias, nunca razão pronta vinda do SQL. Vale para margem, ticket, elasticidade,
  ruptura, leadtime — tudo.
- **Custo em duas bases lado a lado** (médio como principal, última compra como secundário) é a
  convenção da casa em toda tela de precificação.
- ⚠️ `custoproduto.customedio` é o custo de **HOJE** aplicado retroativamente. Quando o custo
  histórico importa (ex.: CMV mês a mês), usar `movimentacaoestoque.customedio`, que é o custo **no
  momento da movimentação** — ao preço de varrer 32 mi de linhas (ver
  [04-estoque.md](04-estoque.md)).

**Outras fórmulas usadas na rede:**

| Métrica | Fórmula |
| --- | --- |
| Projeção (run-rate) | `receita ÷ dias decorridos × dias do período` |
| Meta de venda | `venda do mesmo período do ano passado × 1,10` |
| Aproveitamento | `receita ÷ meta` |
| % Atingimento (comissão) | **Venda projetada ÷ meta** (não a venda já realizada) |
| Elasticidade | `%Δquantidade ÷ %Δpreço`, só quando `%Δpreço < 0` (desconto real). `|elasticidade| ≥ 1` e `%Δqtd > 0` → "vale repetir" |
| Preço médio efetivo | `receita ÷ quantidade` (nunca preço de tabela) |

## Thresholds de alerta

Padrão para varejo farmacêutico (constante `CMV_ALERTA = 0.7`):

| CMV | Leitura |
| --- | --- |
| ≤ 60% | saudável forte |
| ≤ 70% | saudável — **limite operacional** |
| ≤ 80% | atenção |
| > 80% | alerta |

Margem (sinal invertido): ≥ 30% forte · ≥ 15% ok · ≥ 5% atenção · < 5% alerta.

## Template de query de venda por loja

Template aprovado, que evita os três gargalos conhecidos (JOIN com `produto` desnecessário,
`COUNT(DISTINCT)` sobre `itemvenda`, e `custoproduto` no nível bruto):

```sql
WITH cupons_cte AS (
  SELECT v.unidadenegocioid AS loja_id, COUNT(*)::bigint AS cupons
  FROM venda v
  WHERE v.status='F'
    AND v.datahorafechamento BETWEEN $1::timestamp AND $2::timestamp
  GROUP BY v.unidadenegocioid
),
itens_cte AS (
  SELECT v.unidadenegocioid AS loja_id, e.produtoid,
         SUM(iv.valortotal) AS receita, SUM(iv.quantidade) AS quantidade
  FROM venda v
  JOIN itemvenda iv ON iv.vendaid = v.id
  JOIN embalagem  e ON e.id = iv.embalagemid
  WHERE v.status='F' AND iv.status='F'
    AND v.datahorafechamento BETWEEN $1::timestamp AND $2::timestamp
  GROUP BY v.unidadenegocioid, e.produtoid
),
vendas AS (
  SELECT i.loja_id,
         SUM(i.receita)                                   AS receita,
         SUM(i.quantidade * COALESCE(cp.customedio,0))    AS custo_medio,
         SUM(i.quantidade * COALESCE(cp.custo,0))         AS custo_ultima
  FROM itens_cte i
  LEFT JOIN custoproduto cp
         ON cp.produtoid = i.produtoid AND cp.unidadenegocioid = i.loja_id
  GROUP BY i.loja_id
),
devolucoes AS (
  SELECT me.unidadenegocioid AS loja_id,
         SUM(ABS(me.quantidade) * COALESCE(me.precovenda,0)) AS valor_devolvido,
         SUM(ABS(me.quantidade) * COALESCE(me.customedio,0)) AS custo_medio_devolvido
  FROM movimentacaoestoque me
  WHERE me.tipomovimentacaoestoqueid = 27
    AND me.datahora BETWEEN $1::timestamp AND $2::timestamp
  GROUP BY me.unidadenegocioid
)
SELECT un.id::text AS loja_id, LEFT(un.nome,2) AS loja, ...
FROM unidadenegocio un
LEFT JOIN vendas     ON ...
LEFT JOIN cupons_cte ON ...
LEFT JOIN devolucoes ON ...
WHERE un.status='A' AND un.codigo <> 'ESC';
```
