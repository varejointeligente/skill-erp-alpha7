# Compras, notas fiscais, ofertas e precificação

## Sumário

- [`notafiscal` — compra, transferência e serviço na mesma tabela](#notafiscal--compra-transferência-e-serviço-na-mesma-tabela)
- [CFOP: como classificar a nota](#cfop-como-classificar-a-nota)
- [`itemnotafiscal`](#itemnotafiscal)
- [`recebimentofisico` e o vínculo com pedido de compra](#recebimentofisico-e-o-vínculo-com-pedido-de-compra)
- [`pedidocompra`](#pedidocompra)
- [`devolucaocompra` e crédito de fornecedor](#devolucaocompra-e-crédito-de-fornecedor)
- [`cadernooferta` e o ecossistema de oferta/desconto](#cadernooferta-e-o-ecossistema-de-ofertadesconto)
- [`orcamento` / `itemorcamento` / `liberacaousuario` — negociação de preço](#orcamento--itemorcamento--liberacaousuario--negociação-de-preço)
- [`alteracaopreco` — histórico de preço e escrita no ERP](#alteracaopreco--histórico-de-preço-e-escrita-no-erp)
- [Margem objetiva e arredondamento psicológico](#margem-objetiva-e-arredondamento-psicológico)
- [Elasticidade de preço](#elasticidade-de-preço)
- [Demanda reprimida e reposição](#demanda-reprimida-e-reposição)

---

## `notafiscal` — compra, transferência e serviço na mesma tabela

| Coluna | Descrição |
| --- | --- |
| `id` | |
| `numero` / `chaveacesso` | Identificação fiscal |
| `unidadenegocioid` | Loja |
| `fornecedorid` | Preenchido em **toda** nota, inclusive nas de transferência entre lojas (cada loja é um CNPJ, então "fornecedor" pode ser a própria filial de origem) |
| `datahoraemissao` | Emissão pelo fornecedor/loja de origem |
| `datahoraentrada` | **Entrada física na loja — `NULL` = ainda não recebida** |
| `valortotal` | Valor do cabeçalho |
| `usuarioinclusaoid` | ⚠️ ~97% das notas são lançadas por uma conta de sistema (`usuario.id=4`, sem nome) — **não usar como atribuição de colaborador** |
| `origem` | ⚠️ **Não usar para classificar** compra/transferência/serviço — código A/B/C/D sem correlação limpa |
| `status` | Ver abaixo |

### ⚠️⚠️ `notafiscal.status` — os 4 valores reais

Corrigido a partir de print da tela real do Alpha 7 (**dois mapeamentos anteriores estavam errados**):

| Valor | Significado | Evidência |
| --- | --- | --- |
| `'I'` | **Inicial** | 0% tem `datahoraentrada` — **é o único status realmente pendente** |
| `'A'` | **Cancelada** | ~100% correlacionado com `cancelamentonotafiscal`, motivos reais "estornada"/"cancelar"/"erro"/"ANTIGA"/"2020". ~98% sem `datahoraentrada`, ~2% cancelada depois de recebida |
| `'C'` | **Conferida** | 100% de correlação com `datahoraentrada` preenchida. Maioria esmagadora (343 mil notas) |
| `'R'` | **Recebida** | 100% de correlação com `datahoraentrada`. Rara (127 notas) |

- ⚠️⚠️ **Backlog/pendência = `status = 'I'`, NUNCA `IN ('I','A')`.** Esse bug (tratar Cancelada como
  pendente) já foi encontrado e corrigido em **4 relatórios diferentes**. Impacto real medido: o
  backlog caiu de **7.723 para 3.348** notas numa tela; noutra, de **1.443 para 474**.
- Não há coluna que distinga `C` de `R` com certeza absoluta. Como sempre foram tratadas de forma
  idêntica na lógica de negócio (`datahoraentrada IS NOT NULL`), uma eventual inversão de rótulo é
  cosmética.
- ⚠️ **Por isso mesmo, "nota entrada" NÃO é `status = 'C'`.** Filtrar só por `'C'` descarta em
  silêncio as `'R'`, que têm a mesma semântica (já vi extração de custo de entrada fazendo isso). A
  forma correta e à prova de inversão de rótulo é **`nf.datahoraentrada IS NOT NULL`**, que cobre as
  duas. Como `'R'` é raro (127 notas contra 343 mil), o erro é pequeno o bastante para nunca chamar
  atenção — e é exatamente esse o problema.
- ⚠️ **Aba "recebidas" filtra por `datahoraentrada`, NÃO por `datahoraemissao`.** Bug real: das notas
  com entrada nos últimos 7 dias, só **~38% apareciam** (1.901 de 5.002) quando o filtro era por
  emissão — havia casos com **600+ dias** entre emissão e entrada.

## CFOP: como classificar a nota

Usar o **CFOP do ITEM** (`itemnotafiscal.cfop`), nunca `notafiscal.origem`:

```sql
-- Transferência entre lojas (mesma empresa)
cfop IN ('1151','1152','2151','2152','5151','5152','6151','6152','5409','6409','5411','6411')
-- Prestação de serviço
cfop IN ('5931','5932','5933','1933','2933','6933')
-- Resto (5102, 5403, 6102, etc.) = compra de fornecedor
```

### ⚠️ Bug real: 5409/6409 faltavam e 41,6% do bucket "fornecedor" era transferência

CFOP **5409/6409** = "venda de mercadoria sujeita a ST (ICMS-ST já retido) entre estabelecimentos da
mesma empresa". Como cada filial é um CNPJ próprio, o Alpha 7 emite transferência de produto com ST
entre lojas como uma "venda" fiscal, com `fornecedorid` apontando para o cadastro interno da filial.

Validado (90 dias): CFOP 5409 apareceu em **21.099 notas, 100% de fornecedor interno**; 5411 em mais
5, também 100% interno. Sem a correção, **18.448 de 44.340 notas (41,6%)** do bucket "fornecedor"
eram transferência entre filiais.

⚠️ **NÃO adicionar 5405** — apesar de aparecer nessas mesmas filiais-fornecedor (1 ocorrência em
90d), é 99,9% fornecedor externo genuíno (1.885 externas × 1 interna).

> Se aparecer CFOP novo classificando errado, ajustar as constantes. Elas costumam estar duplicadas
> em várias rotas — trocar todas juntas.

## `itemnotafiscal`

| Coluna | Descrição |
| --- | --- |
| `notafiscalid` | → `notafiscal` |
| `embalagemid` | → `embalagem` |
| `cfop` | Classifica a operação |
| `quantidade` | |
| `valorunitario` | **Custo unitário DESSA entrada específica** (≠ "custo da última compra" do sistema) |
| `valorproduto` | Total bruto |
| `valortotal` | Total líquido |
| `desconto` | |
| `bonificacao` | boolean |
| `rateiofrete`, `rateioseguro`, `rateiodesconto`, `rateiodespesa`, `rateiotvf` | Rateios do cabeçalho |
| `icmsstvalor`, `icmsstfcpvalor`, `ipivalor`, `icmsstrecolhidovalor`, `fcpstrecolhidovalor`, `icmsstretidovalor`, `icmsdesoneradovalor` | Impostos |
| `numeropedidocompra` | ⚠️ **texto livre, NÃO confiável** — ver abaixo |

**Custo total com impostos** (fórmula observada em extrações de custo de entrada):

```sql
inf.valortotal + inf.icmsstvalor + inf.icmsstfcpvalor + inf.ipivalor
  + inf.icmsstrecolhidovalor + inf.fcpstrecolhidovalor
  - inf.rateiodesconto - inf.icmsdesoneradovalor
  + inf.rateiofrete + inf.rateioseguro + inf.rateiodespesa + inf.rateiotvf
```

**Custo sem imposto:** `round((inf.valortotal / inf.quantidade) - inf.icmsstretidovalor, 2)`.

⚠️ **Bonificação a 1 centavo:** usar **dupla defesa** — `NOT itemnotafiscal.bonificacao`
**e** `valorunitario > 0,01` (a flag nativa não cobre todo caso de bonificação disfarçada de custo
simbólico).

⚠️ **`notafiscal.valortotal` ≠ `Σ itemnotafiscal.valortotal`** em **~15% das notas pendentes e ~37%
das recebidas** — frete/seguro/desconto rateado no cabeçalho nem sempre reconcilia limpo. Não é bug
de query; é característica do dado fiscal. Sinalizar a divergência em vez de "consertar".

## `recebimentofisico` e o vínculo com pedido de compra

### ⚠️ `itemnotafiscal.numeropedidocompra` NÃO é confiável

Dos itens com esse campo preenchido, só **~7%** batem com um `pedidocompra` real (nem por `codigo`
nem por `id`) — o valor armazenado (ex.: `"000000001783602"`) não corresponde a nenhum dos formatos
do `pedidocompra` desta base. Provavelmente é referência de outro sistema.

### O caminho relacional correto

```text
notafiscal → recebimentofisiconotafiscal (notafiscalid) → recebimentofisico (recebimentofisicoid)
          → recebimentofisicopedidocompra (recebimentofisicoid) → pedidocompra (pedidocompraid)
```

```sql
tem_pedido AS (
  SELECT DISTINCT rfn.notafiscalid
  FROM recebimentofisiconotafiscal rfn
  JOIN recebimentofisicopedidocompra rfp
    ON rfp.recebimentofisicoid = rfn.recebimentofisicoid
)
```

⚠️ **Mesmo esse caminho formal cobre só ~6% dos recebimentos** dos últimos 30 dias — a maioria das
entradas desta rede não passa pelo fluxo formal de pedido de compra. Isso é o **próprio ponto** de
uma auditoria de compras, não um bug de query. E é por isso que **não se deve usá-lo para inferir
"o item chegou"** (ver ruptura em [04-estoque.md](04-estoque.md)).

### `recebimentofisico.status`

char(1), **sem tabela de lookup no banco** (o texto só existe decodificado no front-end do ERP).
Decodificado por correlação com `itemrecebimentofisico`/`estornoitemrecebimentofisico`
(confirmação cruzada exata: 100% dos `E`/`P` têm item revertido; 0% dos `R`/`C`/`A` têm):

| Valor | Significado |
| --- | --- |
| `R` | Recebido (finalizado ok, maioria) |
| `C` | Cancelado (abortado antes de finalizar, sem estorno) |
| `P` | **Estornado Parcialmente** (sobra item não revertido) |
| `E` | **Estornado** total |
| `A` | Aberto (em digitação) |

**"NF estornada" = `status IN ('E','P')`** (os dois juntos).

⚠️ **`recebimentofisico.datahorafinal` NÃO é a data do estorno** — é a data do recebimento
**ORIGINAL** (100% dos casos E/P têm `datahorafinal` anterior ao estorno, às vezes semanas antes).
A data/usuário do estorno de verdade ficam em **`estornoitemrecebimentofisico`**
(`itemrecebimentofisicoid`, `usuarioid`, `datahora`, `motivo` — texto livre), **por ITEM revertido**.

⚠️ `recebimentofisico.usuarioid` = quem **recebeu/conferiu**, não quem estornou.

⚠️ Um recebimento pode cobrir **várias NFs de uma vez** (achado: até **574 NFs num só recebimento**)
— "contar recebimentos" ≠ "contar NFs afetadas".

⚠️ **`recebimentofisico` × `cancelamentonotafiscal` medem coisas diferentes.**
`cancelamentonotafiscal` é cancelamento **fiscal** do documento (3.567 casos históricos);
`recebimentofisico.status IN ('E','P')` é reversão do **processo físico** de conferência (5.575 notas
afetadas). **Só 68 casos aparecem nas duas fontes.**

⚠️ **Transferência não passa por `recebimentofisico`** — validado: 0% das NFs de transferência têm
registro ali; 99,9% passam por `recebimentotransferencia`.

## `pedidocompra`

| Coluna | Descrição |
| --- | --- |
| `id` | |
| `fornecedorid` | → `fornecedor` |
| `unidadenegocioid` | **Existe direto** (confirmado via `information_schema`) — não precisa passar por fornecedor |
| `datahora` | Criação do pedido — filtro de período |
| `usuarioid` | Quem criou o pedido |
| `status` | char(1), **8 valores observados** (`E,C,H,G,A,J,D,I`) — ⚠️ **só `'D'` foi decodificado com confiança: Cancelado** (96% tem registro em `cancelamentopedidocompra`). Os outros 7 não têm lookup nem correlação clara — **não inventar significado** |
| `origem` | char(1), 6 valores (`F,A,L,B,G,K`), **não decodificado** |

- `itempedidocompra` → `embalagemid` → `embalagem.produtoid` (join padrão).
- `cancelamentopedidocompra` (`pedidocompraid`) = cancelamento formal.
- **"Pedidos realizados"** = `pedidocompra` com `status <> 'D'` e `datahora` no período.

⚠️ Ao verificar "existe pedido recente para esse produto", filtrar o período **DENTRO da CTE** — nunca
varrer o histórico inteiro de `itempedidocompra` (3,3 mi de linhas) quando só a **existência recente**
importa.

## `devolucaocompra` e crédito de fornecedor

Devolução **DE COMPRA** = mercadoria devolvida ao fornecedor. Não confundir com devolução de venda
(`movimentacaoestoque` tipo 27 / `devolucaovenda`).

| Tabela | Notas |
| --- | --- |
| `devolucaocompra` | `unidadenegocioid`, `fornecedorid`, `usuarioid`, `datahorainicial`, `datahorafinal`, `motivo`, `status`. ⚠️ **Não tem valor próprio no cabeçalho** |
| `devolucaocompraitem` | `devolucaocompraid`, `embalagemid`, `quantidade`, `valorunitario`, `valortotal`, `status='F'` — o valor da devolução é `SUM(...)` daqui |
| `nfe` | XML da nota eletrônica; tem **`devolucaocompraid`** (FK direta) → é o que define "com NF" / "sem NF" |
| `creditofornecedor` | `devolucaocompraorigemid`, `valor`, `valorutilizado`, `status` |
| `cancelamentocreditofornecedor` | Auditoria de cancelamento de crédito |

**`devolucaocompra.status`:** `'F'` Finalizada (maioria, ~4.345) · `'C'` Cancelada (~742) ·
`'A'` Aberta/pendente (raro, ~7) · `'E'` raro.

⚠️ **Todos os status têm `datahorafinal` preenchida** (diferente de `transferencia`/`notafiscal`) —
não dá para usar null-check para detectar pendência aqui.

**`creditofornecedor.status`** (decodificado por correlação):

| Valor | Significado |
| --- | --- |
| `'A'` | **Aberto/pendente** — não utilizado (~4.078 registros históricos desde 2021, cresce mês a mês; é o backlog real) |
| `'B'` | Baixado (100% com `valor = valorutilizado`) |
| `'D'` | Cancelado (**100% correlacionado** com `cancelamentocreditofornecedor`) |
| `'C'` | 1 registro isolado, ruído |

- "Créditos pendentes" = `status = 'A'` (cobre exatamente o saldo não usado, sem precisar de
  `valor - valorutilizado > 0`).
- "Gerou crédito" = existe `creditofornecedor.devolucaocompraorigemid` apontando para a devolução
  com `status <> 'D'`. Validado: 635 de 638 devoluções em 180 dias geraram crédito.
- "Com NF" = existe `nfe.devolucaocompraid`. Validado: 637 de 638 em 180 dias — "sem NF" existe mas
  é raro.

## `cadernooferta` e o ecossistema de oferta/desconto

> ⚠️⚠️ Nesta base, `cadernooferta` é usado para **bem mais do que promoção de encarte** — mistura
> convênio, canal de venda e tabela de preço controlado.

### `cadernooferta` (cabeçalho)

| Coluna | Descrição |
| --- | --- |
| `nome` | ⚠️ **Não existe coluna de tipo** — o tipo é identificado pelo NOME |
| `status` | `'A'` = ativo |
| `origem` | `'A'` automático/integração · `'C'` cadastro manual · `'F'` fidelidade/Scanntech |
| `datahorainicial` / `datahorafinal` | Vigência — **podem ser NULL = sem limite** |
| (outras) | Regras de dia da semana / CRM |

**Nomes reais convivendo na mesma tabela:**

| Categoria | Padrão de nome |
| --- | --- |
| Panfleto | `PANFLETO%` (ex.: `PANFLETO 2026 MAI/JUNHO`, `PANFLETO - MES DAS MAES`) |
| Oferta do Dia | `PADRÃO_SEGUNDA` … `PADRÃO_SEXTA GENERICO` (casar com `normalize_str`, tem acento). ⚠️ **Sábado e domingo não têm caderno cadastrado** — a categoria fica vazia nesses dias, não é bug |
| 72 Horas | contém `72 HORA` (com ou sem espaço) — cobre `007 - PADRÃO 72 HORAS DE OFERTA <loja>` |
| Leve + Pague | `009 - LEVE+ PAGUE-` e outros — mas o certo é filtrar por `itemcadernooferta.tipooferta='L'` |
| Convênio | nome do clube de desconto da rede + `500 - CONVENIO FUNCIONARIOS`, `501 - CONVENIO EMPRESAS` (⚠️ **a carteira de convênios é de cada cliente** — levantar por `SELECT nome FROM cadernooferta`) |
| Canal | nome do marketplace de delivery / plataforma de e-commerce (idem: varia por cliente) |
| Preço controlado | `Preço Controlado Plugpharma`, `PRC - 000 - PRODUTOS EM PROMOÇÃO`, `PRC - 999 - DESCONTO AUTOMÁTICO POR GRUPO` |
| Cupom médico | `CUPOM-MEDICO` |

⚠️ Entre os 66 cadernos com venda em 14 dias, o TOPO por volume é todo administrativo
(`PRC - 000` com 72 mil itens, `PRC - 999` com 33 mil, `CONVENIO FUNCIONARIOS`,
`Preço Controlado Plugpharma`); só o 4º da lista é uma oferta real.

### ⚠️⚠️ Atribuição de campanha é no ITEM, não na venda

- **`venda.cadernoofertaid`** só captura cadernos de **venda inteira** — ~1,3% da receita, e **~99%
  disso é convênio**, não promoção. **Não usar como proxy de "venda em oferta".**
- **`itemvenda.cadernoofertaid`** é a atribuição real por promoção.

```sql
-- venda do panfleto
SELECT SUM(iv.valortotal)
FROM itemvenda iv
JOIN cadernooferta co ON co.id = iv.cadernoofertaid
WHERE co.nome ILIKE 'PANFLETO%';

-- cupons do panfleto
COUNT(DISTINCT v.id) FILTER (WHERE co.nome ILIKE 'PANFLETO%')
```

Todos os cadernos no nível item somam ~69% da receita — inclui tabelas de preço, não serve como
"campanha de marketing". Daí o recorte por nome.

⚠️ **`itemvenda.cadernoofertaid` NÃO TEM ÍNDICE** (`pg_indexes`) — filtrar `itemvenda` direto por
essa coluna é lento (13,3 s para 1 caderno). **Começar a CTE pela `itemcadernooferta`** (poucas
linhas por caderno) **e casar por `embalagemid`**, que tem índice composto com
`unidadenegocioid`/`datahora` → caiu para ~8,5 s. Para "todos os cadernos", uma CTE
`cadernos_periodo` (distinct `cadernoofertaid` com venda no período, via o índice de
`venda.datahorafechamento`) cobre tudo numa query só (~7,5 s para 66 cadernos / 20.349 linhas).

### `itemcadernooferta`

| Coluna | Descrição |
| --- | --- |
| `cadernoofertaid` | |
| `embalagemid` | ⚠️ **NULL** quando a linha é de grupo/fabricante/classificação |
| `tipoitem` | `'B'` = grupo de remarcação (usa `gruporemarcacaoid`) · `'E'` = combo (usa `combooferta`) · `'C'`/`'D'` = fabricante/classificação (regra em massa) |
| `gruporemarcacaoid` | Quando `tipoitem='B'` |
| `tipooferta` | Ver tabela abaixo |
| `precooferta` | Preço fixo da oferta — ⚠️ **sempre NULL para `tipooferta='L'`** |
| `descontooferta` | % de desconto |
| `leve` / `pague` | Leve X Pague Y |
| `descontoporqtdtipo` | Regra de exibição do desconto por quantidade |
| `ultimaedicaodatahora` | Cobre inclusão nova **e** edição de preço — só existe uma data de "última edição" |

**~408 mil linhas ativas** — cobre quase todo o catálogo. Portanto **"produto cadastrado em algum
caderno" NÃO é sinal útil de "produto em oferta"**.

### `itemcadernooferta.tipooferta`

| Valor | Significado | Como virar preço |
| --- | --- | --- |
| `P` | Preço fixo | De/Por com `precooferta` |
| `D` | Desconto % | Por = `precovenda × (1 − descontooferta/100)` |
| `L` | Leve/Pague | `leve`/`pague`; **`precooferta` é sempre NULL** |
| `Q` | Desconto por quantidade | Faixas em `itemcadernoofertaquantidade` |
| `B` e demais sem preço | ignorados (17,6 mil itens `tipooferta='B'` sem preço de oferta) | — |

⚠️ **Armadilha real:** uma query exigia `precooferta IS NOT NULL` para todas as categorias, o que
**zerava sempre** a categoria Leve+Pague. Tornar esse filtro condicional.

### `itemcadernoofertaquantidade` (desconto por quantidade)

Colunas: `quantidade`, `preco`, `precototal`, `desconto`, `descontototal`.
Usar sempre a **maior faixa de quantidade**. O texto segue `descontoporqtdtipo`:

| Tipo | Texto |
| --- | --- |
| `C` | `LEVE N POR R$X` (preço total do conjunto) |
| `B` | `LEVE N · R$X CADA` (preço unitário) |
| `A` | `LEVE N COM X% OFF` (% por unidade) |
| `G` | `LEVE N COM X% OFF` (% no conjunto) |

### Demais tabelas de oferta

| Tabela | Uso |
| --- | --- |
| `combooferta` / `vendacombooferta` | Combos (`status='I'` = inativo, excluir) |
| `cupomdesconto` / `vendacupomdesconto` | Cupons de desconto |
| `descontoacrescimovenda` | Desconto/acréscimo no cabeçalho da venda |
| `unidadenegocioparticipantecadernooferta` | Lojas participantes do caderno |
| `planometavendacadernooferta` | Meta de venda por caderno |

### Sinal validado para "vendeu pelo preço de oferta"

Item cujo `itemvenda.valorunitario` bate (±R$ 0,01) com o `itemcadernooferta.precooferta`
cadastrado para a mesma `embalagemid`, dentro da vigência:

```sql
EXISTS (
  SELECT 1 FROM itemcadernooferta ico
  JOIN cadernooferta co ON co.id = ico.cadernoofertaid
  WHERE ico.embalagemid = iv.embalagemid
    AND co.status = 'A'
    AND ico.precooferta IS NOT NULL
    AND ABS(ico.precooferta - iv.valorunitario) < 0.01
    AND (co.datahorainicial IS NULL OR co.datahorainicial <= v.datahorafechamento)
    AND (co.datahorafinal   IS NULL OR co.datahorafinal   >= v.datahorafechamento)
)
```

Resultado: ~1,6% da receita em 30 dias — ordem de grandeza plausível para oferta de encarte.

⚠️ **Performance:** calcular esse `EXISTS` como **CTE separada** (segundo scan de `venda`+`itemvenda`
do período) custa ~5 s extra num mês inteiro — aceitável. Tentar movê-lo para dentro de um
`SUM(...) FILTER (WHERE EXISTS (...))` na mesma CTE de agregação **piorou muito** (de ~11 s para
não terminar em 60 s). **Manter como CTE separada.**

### O que NÃO existe

⚠️ **Não há NENHUMA tabela de auditoria de remoção de `itemcadernooferta`** (confirmado varrendo
`information_schema.tables` por `%exclu%caderno%`, `%cancel%caderno%` etc.). Para saber "o que saiu
da oferta" é preciso manter **snapshot próprio** e fazer diff entre dias.

## `orcamento` / `itemorcamento` / `liberacaousuario` — negociação de preço

**Existem dois mecanismos de desconto completamente separados no Alpha 7 — não confundir:**

1. **Desconto direto no PDV** — `itemvenda.origemdesconto` / `valordesconto`, aplicado pelo próprio
   operador, sem segunda pessoa. Ver [02-vendas.md](02-vendas.md).
   ⚠️ **`itemvenda.liberacaousuariodescontopdvid` está 100% vazio em TODA a base** (26,2 mi de
   linhas) — o fluxo existe no schema mas não é usado. Não usar.

2. **Negociação de preço no orçamento com liberação de um segundo usuário** — **este é o mecanismo
   real de "desconto manual com autorização"** usado pela rede.

### `orcamento`

| Coluna | Descrição |
| --- | --- |
| `id` | |
| `unidadenegocioid` | Loja — **existe e é confiável** |
| `vendaid` | → `venda`; NULL se não convertido. ⚠️ **SEM ÍNDICE** (~3,9 mi de linhas) |
| `usuarioid` | **O vendedor que atendeu** (ver [02-vendas.md](02-vendas.md)) |
| `datahora` | |
| `liberacaousuarionegociacaonegativaid` | → **`liberacaousuario.id`**, não `usuario.id` |

⚠️ **`orcamento` não tem `valortotal` próprio** — o valor fica em `venda.valortotal`.

### A cadeia de liberação

⚠️ Apesar do nome, `liberacaousuarionegociacaonegativaid` **não referencia `usuario.id`** (join
direto resolve 0%):

```text
orcamento.liberacaousuarionegociacaonegativaid → liberacaousuario.id
liberacaousuario.usuarioid → usuario.id → usuario.pessoaid → pessoa.nome   (AUTORIZADOR real)
orcamento.usuarioid → usuario → pessoa.nome                                (VENDEDOR, outra pessoa)
orcamento.vendaid → venda   (só contar orçamentos que viraram venda 'F')
```

`liberacaousuario` também tem `unidadenegocioid`, `datahora`, `tipo` (código do tipo de liberação —
negociação é um dos usos; tipos vistos: `I`, `D`, `B`, não mapeados em detalhe).

Validado: ~4.021 orçamentos em 30 dias tiveram liberação de negociação, 100% resolvendo para um nome
de pessoa real (algumas anonimizadas por LGPD como "Pessoa Anonimizada").

### `itemorcamento` e o cálculo robusto do desconto

| Coluna | Descrição |
| --- | --- |
| `orcamentoid` | |
| `embalagemid` | |
| `usuarioid` | **Vendedor no nível do item** |
| `quantidade` | |
| `precovenda` | **Preço de TABELA** |
| `valortotal` | Valor final da linha |
| `desconto` | Percentual |
| `valornegociacao` / `valornegociacaototal` | ⚠️ Ajustes que **nem sempre refletem o desconto real** (ficam parciais/zerados mesmo havendo negociação) |

**Cálculo robusto do desconto** (funciona independente do mecanismo que gerou a redução):

```sql
-- por orçamento
SUM(io.precovenda * io.quantidade) - SUM(io.valortotal)

-- por item
(io.precovenda * io.quantidade) - io.valortotal   AS valor_desconto
 io.precovenda * io.quantidade                    AS valor_tabela
 io.valortotal / NULLIF(io.quantidade, 0)         AS valor_unitario_real
```

### ⚠️ Bugs reais de drill-down de desconto

1. **A liberação é do ORÇAMENTO, não do item.** Filtrar só
   `o.liberacaousuarionegociacaonegativaid IS NOT NULL` traz **a cesta inteira** (produtos vendidos
   ao preço de tabela misturados com o item que de fato teve desconto). Corrigir com filtro por
   item: `WHERE (io.precovenda * io.quantidade) - io.valortotal > 0.01` (tolerância de 1 centavo
   contra ruído de arredondamento).

2. **Dentro de um orçamento negociado convivem descontos de outra origem** (promoção do caderno,
   PBM, leve-e-pague). `itemorcamento` **não carrega `origemdesconto`** (só existe em `itemvenda`) —
   para restringir a negociação manual de verdade, é preciso alcançar `itemvenda` e filtrar
   `origemdesconto='M'`. ⚠️ Usar **`EXISTS`, nunca `JOIN`** (fan-out — ver
   [02-vendas.md](02-vendas.md)).

3. **Outlier de desconto** (heurística inicial): flagra loja/autorizador com % de desconto acima de
   **1,5×** a média da rede, considerando só quem teve **3+** autorizações no período (evita alarme
   falso por amostra de 1).

## `alteracaopreco` — histórico de preço e escrita no ERP

Histórico nativo de alteração de preço do ERP.

| Coluna | Descrição |
| --- | --- |
| `precovendaanterior` / `precovendaposterior` | Preço de venda antes/depois — **os únicos nomes de coluna de par anterior/posterior confirmados** |
| `datahora` | Quando mudou |
| `unidadenegocioid` | ⚠️ Em alteração de preço **BASE** é sempre a unidade **ESC/Escritório** |
| `unidadenegocioprecoid` | ⚠️ **NULL** em alteração BASE; preenchido em override por loja |
| `usuarioid` | Sempre resolve para um `usuario.id` real (100% dos casos recentes), embora sem FK formal |

⚠️ **`precoreferencial` (PMC/máximo) não muda numa alteração de preço de venda — grava-se o valor
atual como anterior e posterior.** É o que a inspeção do schema registrou, em prosa. 📌 **Lacuna:**
os **nomes** das colunas que guardam esse par anterior/posterior do `precoreferencial` **não foram
registrados** — descobrir com
`SELECT column_name FROM information_schema.columns WHERE table_name = 'alteracaopreco'` antes de
escrever o `INSERT`. Não deduzir o nome por analogia com `precovenda*`.

Confirmado por amostragem: **4.387 de 4.388** alterações de base dos últimos 30 dias usam
`unidadenegocioprecoid = NULL` **e** `unidadenegocioid` = o id do **ESC/Escritório** (na base medida
esse id era `1`; ⚠️ **ids de unidade variam por base** — resolver por
`SELECT id FROM unidadenegocio WHERE codigo = 'ESC'`, nunca hardcodar).

`embalagem.ultimaalteracaoprecoid` aponta para o registro mais recente.

### Escrita real no Alpha 7 (o único caso documentado de gravação)

Credencial **separada** da de leitura, com o mínimo:
`GRANT SELECT, UPDATE ON embalagem, INSERT ON alteracaopreco` — **nunca DELETE/DROP/TRUNCATE**.

**Invariantes a replicar à mão** (o banco não tem FK/CHECK para garanti-las):

1. `INSERT alteracaopreco (...) RETURNING id` **antes** do `UPDATE embalagem`.
2. `UPDATE embalagem SET precovenda = ..., ultimaalteracaoprecoid = <novo id> WHERE id = ...`.
3. Tudo na **mesma transação** (`BEGIN` / `SELECT ... FOR UPDATE` na linha da embalagem / `COMMIT` /
   `ROLLBACK`).
4. `precoreferencial` não muda — gravar o valor atual como anterior **e** posterior (⚠️ confirmar os
   nomes dessas duas colunas no `information_schema` antes; não estão registrados aqui).
5. Alteração BASE → `unidadenegocioprecoid = NULL`, `unidadenegocioid` = id do **ESC/Escritório**
   resolvido por `codigo = 'ESC'` na base corrente.
6. Exigir que quem aprovou tenha um `usuario.id` real no ERP — falhar **antes** de abrir a conexão de
   escrita se não tiver.
7. **Nunca "fingir que aplicou"**: sem a credencial configurada, falhar com mensagem clara e gravar o
   erro no registro da fila de aprovação.

**Sinalização de oferta ativa antes de mexer no preço:** `EXISTS` em
`itemcadernooferta` + `cadernooferta` com `precooferta` batendo (±R$ 0,01) com o preço avaliado,
`status='A'` e vigência contendo **hoje** (`NOW()`, não uma data de venda). É um aviso, não um
bloqueio.

## Margem objetiva e arredondamento psicológico

### Critérios de "produto para revisão de preço"

Candidato = qualquer um dos dois:

1. **Preço quebrado** = centavos do preço fora do conjunto de terminações que a rede usa. ⚠️ **Quais
   terminações são "certas" é convenção COMERCIAL do cliente, não regra do ERP** — medir antes:
   numa rede, `{0,90 ; 0,99}` cobriam **~89% do catálogo ativo**, e foi isso que tornou o critério
   defensável. Rodar a mesma contagem na base em uso antes de adotar o conjunto.
2. **Margem abaixo do objetivo** = margem (custo médio consolidado) menor que a margem objetiva da
   categoria/subcategoria. ⚠️ A margem objetiva é **cadastro externo ao ERP**, por cliente; o
   fallback de **20%** usado quando a categoria não tem cadastro também é decisão do cliente.

Volume real: ~13,1 mil embalagens candidatas (consolidado por produto).

### Arredondamento

A convenção da casa **não** é "termina em 9 na dezena" (19,90/29,90) — é **qualquer preço terminado
em ,90**:

```text
arredondarParaBaixo(preco) = centavos >= 90 ? inteiro + 0,90 : (inteiro - 1) + 0,90
```

Ex.: R$ 20,00 e R$ 20,07 → R$ 19,90; mas R$ 20,95 → R$ 20,90 (não desce um inteiro, já passou da
marca de 90 centavos).

### Preço sugerido

```text
precoIdeal = custo / (1 - margemObjetivo)
```

- Item com **margem baixa** → arredondar **para CIMA** (arredondar para baixo anularia o ajuste de
  margem que acabou de ser calculado).
- **Sugestão simétrica** ao monitorar custo de entrada: `precoIdeal > preço atual` → "Aumentar
  preço" (para cima); `<` → "Reduzir preço" (para baixo); senão "Manter". Sem a simetria, um custo
  que caiu nunca geraria sugestão.
- ⚠️ **Não usar `embalagem.markup`** como base (ver [03-produto-embalagem.md](03-produto-embalagem.md)).

### Cadastro de margem objetiva (externo ao ERP)

Cadastro em banco próprio, com dois níveis: **categoria macro** (2º segmento do `caminho`) e
**subcategoria** (o resto do caminho depois da macro, **caminho relativo completo** — ex.
`"FRALDAS > ADULTO"`, não só `"ADULTO"`, porque nomes se repetem sob macros diferentes).

⚠️ Usar `''` (string vazia) como sentinela de "toda a categoria macro", **nunca `NULL`** — tanto
SQLite quanto PostgreSQL tratam `NULL` como distinto de si mesmo em `UNIQUE`, então várias linhas com
`subcategoria = NULL` não violariam a constraint.

**Injetar o cadastro externo na query do ERP** sem trazer 400 mil linhas para a aplicação:

```sql
WITH margem_cadastro AS (
  SELECT * FROM unnest($1::text[], $2::text[], $3::numeric[])
              AS t(categoria, subcategoria, margem)
)
-- fallback em cadeia:
-- COALESCE(match categoria+subcategoria, match só categoria, $4::numeric /* padrão */)
```

Assim o filtro `margem_medio < margem_objetivo` continua rodando **dentro do Postgres**.

### Priorização por criticidade

⚠️ Ao priorizar "itens mais críticos primeiro", **mudar o `ORDER BY` do `LIMIT`, não só a ordenação
visual.** Se só a ordenação visual mudar, um item com margem profundamente negativa mas receita baixa
(baixo giro) nunca aparece — já foi cortado pelo critério antigo (top por receita). Ao trocar para
`ORDER BY margem ASC`, a 1ª linha apareceu com margem de **−54.550%** (produto com preço quebrado a
R$ 0,01, bug de cadastro genuíno — exatamente o caso que a priorização deveria capturar).

⚠️ **Filtro de categoria tem que entrar ANTES do `LIMIT`**, dentro da CTE de candidatos — senão
filtra sobre o top-N já cortado. Validado: sem filtro, 13.181 itens para revisão; filtrando por
PERFUMARIA, 1.546 — a **contagem** também tem que respeitar o filtro, não só a tabela.

## Elasticidade de preço

**Fórmula:** elasticidade clássica `%Δquantidade ÷ %Δpreço`, calculada **no cliente** a partir dos
componentes crus, nunca no SQL.

**Janelas:** "durante" = o período escolhido pelo usuário; "antes" = **mesmo nº de dias,
imediatamente anterior**, sem sobreposição.

### ⚠️⚠️ Pivô de design: a vigência do CADERNO foi ABANDONADA como referência de janela

A ideia natural seria usar `cadernooferta.datahorainicial`/`datahorafinal` como o período "durante".
Medido no ERP: os cadernos de **maior volume de venda não são campanhas reais** — são mecanismos
estruturais recorrentes (`PADRÃO_SEGUNDA`, `72 HORAS DE OFERTA`, que reusam o mesmo ID toda
semana/mês) ou tabelas de preço/convênio com vigência de **meses a décadas**. Usar essas datas
misturaria anos de venda "normal" com a análise de oferta.

→ **"Durante" = sempre o período escolhido pelo usuário.** Isso desacopla o cálculo do cadastro
administrativo do caderno.

**Regras de cálculo:**

- `durante` = `SUM(itemvenda.quantidade)`/`SUM(itemvenda.valortotal)` no período, com atribuição
  **por ITEM** (`itemvenda.cadernoofertaid`).
- `antes` = mesma métrica do **mesmo produto+loja**, **sem filtrar por caderno** (é a venda "normal"
  de qualquer origem antes da oferta).
- **Preço = preço médio EFETIVAMENTE pago** (`receita ÷ quantidade`), não preço de tabela — mais
  robusto a exceção de preço por loja e a promoções sobrepostas.
- Só calcular quando `%Δpreço < 0` (desconto real). Sem desconto real ou sem baseline
  (`qtd_antes = 0`) → "Sem desconto real" / "Sem histórico", **nunca um número forçado**.
- Tag: `%Δpreço < 0` **e** `%Δqtd > 0` **e** `|elasticidade| >= 1` → "Vale repetir"; senão "Atenção".
- **Elasticidade agregada** = somar os componentes brutos de TODAS as linhas e só então recalcular a
  razão — **nunca média de elasticidades individuais**.

Exemplo reconciliado manualmente contra o ERP: LOSARTANA POTASSICA 50MG (TEUTO), loja BG, caderno
PANFLETO — `qtd_durante=158 / receita=472,42` × `qtd_antes=115 / receita=394,85` →
`%Δpreço = −12,92%`, `%Δqtd = +37,39%`, **elasticidade = −2,89** → "Vale repetir".

## Demanda reprimida e reposição

**Demanda reprimida por FABRICANTE** — fabricantes cuja demanda está caindo por falta de reposição:

- **Threshold: 60 dias sem nenhum pedido de compra novo.**
- **"Último pedido" é fabricante-level, independente de quem forneceu** — via
  `itempedidocompra → embalagem → produto.fabricanteid`, `JOIN pedidocompra` (`status <> 'D'`),
  `MAX(datahora)`.
  ⚠️ Deliberadamente **não** usa `pedidocompra.fornecedorid` (que exigiria o fabricante ser também o
  fornecedor direto) — o sinal que importa é "faz quanto tempo que NENHUM produto dessa marca foi
  comprado, de QUALQUER distribuidor", que é o que causa a ruptura física.
- **Metodologia da queda: antes/depois do ÚLTIMO PEDIDO** (média mensal dos 3 meses imediatamente
  ANTES do último pedido × média dos últimos 3 meses) — isola o efeito causal, diferente do padrão
  "mesmo período ano passado".
- **Dois grupos:**
  - **Com histórico** (tem data-âncora): entra na lista só se `receita_antes > 0` — sem isso não é
    "demanda reprimida", é SKU morto.
  - **Sem NENHUM pedido registrado** (134 de 671 fabricantes ativos): sem âncora, não dá para
    calcular "antes/depois". Fica em lista separada, só com contexto, para revisão manual.
- **Venda perdida mensal** = `max(0, antes − depois)`; **total** = mensal × meses parado.
- Excluir produtos da categoria macro **`USO/CONSUMO`** de toda a análise.
- Excluir fabricante com **estoque zerado** da lista principal (sem estoque remanescente não sobra
  decisão de reposição a tomar).

**Performance:** restringir o cálculo caro (tendência, estoque, ruptura) **só aos fabricantes que já
passaram no filtro de 60+ dias** — de 671 ativos, só 141 qualificam. Medido: "último pedido por
fabricante" ~1,5 s (671 linhas); venda antes/depois dos 141 ~15 s + 4,5 s; estoque ~0,3 s; ruptura
~8 s → **~29 s total, aceitável só porque é cacheado** em snapshot diário.

Resultado real: 136 fabricantes parados (60+ dias), 84 críticos (queda ≥ 50%),
**R$ 4,5 mi em venda perdida estimada acumulada**; um fabricante parado desde 08/02/2023 (1.249
dias).

**Outras análises de reposição validadas:**

| Análise | Definição |
| --- | --- |
| **Demanda Cidade × Loja** | Produto vendido na cidade (soma das lojas) no mês corrente, mas **sem venda numa loja específica** daquela cidade. Só cidades com 2+ lojas ativas |
| **Reposição Reprimida** | Produto+loja com venda nos últimos 30 dias e reposição (compra de fornecedor no mesmo período) **abaixo de 50%** do que vendeu, **só entre quem comprou algo** (`compra > 0`) — "zero compra" fica fora de propósito (já é coberto pela Demanda Reprimida) |
| **Curva D com saída em outra loja** | Produto em Curva D na loja A, sem entrada de estoque (compra ou transferência) há 30+ dias, mas vendendo na loja B nos últimos 60 dias — candidato a transferência |
| **Conciliação de entradas** | Por item de NF de compra: **Sem pedido** (~79% dos itens), **Novidade** (1ª entrada do produto em qualquer loja, em todo o histórico), **Curva D**, **Suspenso p/ compra** (~2%, o sinal mais grave — chegou mesmo estando suspenso) |

**Aprovação de pedido de compra (simulador de caixa)** — regras validadas:

- Prazo parcelado: valor total dividido **igualmente** entre os prazos informados; cada parcela vira
  um vencimento próprio.
- Vencimento = `data_faturamento + prazo_dias` (dias corridos) **rolado para o próximo dia útil** —
  replicando o que o ERP faz em `contapagar.datavencimentoutil`, mas calculado fora porque o pedido
  ainda não existe no ERP.
- "Fornecedor já lançado" = `contapagar` `status='A'` com
  `planocontas.caminho ILIKE '%Custo Operacional%'`, agregado por `datavencimentoutil::date`.
- **Capacidade agrupada em dias sem pagamento:** a folga de sábado/domingo/feriado soma-se à
  capacidade do próximo dia útil (`limite_diario × (dias não úteis imediatamente antes + 1)`) — senão
  a segunda-feira competiria sozinha com 1 dia de limite para absorver o que seria de até 3 dias.
