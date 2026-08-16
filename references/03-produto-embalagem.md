# Produto, embalagem, classificação, preço e custo

## Sumário

- [`produto` — cadastro](#produto--cadastro)
- [`embalagem` — apresentações/SKUs](#embalagem--apresentaçõesskus)
- [`classificacao` — categorias hierárquicas](#classificacao--categorias-hierárquicas)
- [`custoproduto` — custo por produto/loja](#custoproduto--custo-por-produtoloja)
- [`precoembalagemunidadenegocio` — preço por apresentação/loja](#precoembalagemunidadenegocio--preço-por-apresentaçãoloja)
- [`curvaabc` / `curvaabcprodutounidadenegocio`](#curvaabc--curvaabcprodutounidadenegocio)
- [Cadastro fiscal e complementar](#cadastro-fiscal-e-complementar)
- [`gruporemarcacao`](#gruporemarcacao)
- [Busca de produto por descrição](#busca-de-produto-por-descrição)

---

## `produto` — cadastro

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | ID interno (bigint — não é sequencial pequeno) |
| `codigo` | integer (unique) | Código de negócio (o que o usuário enxerga) |
| `descricao` | varchar | Nome/descrição |
| `status` | char(1) | `'A'` = Ativo, `'I'` = Inativo |
| `tipo` | char(1) | `'M'` Mercadoria/Medicamento (padrão, ~70 mil), `'S'` Serviço (~11), `'T'` Serviço tomado (3), outro = ajuste fiscal |
| `fabricanteid` | bigint FK | → `fabricante.id` → `pessoa.nome` |
| `principioativoid` | bigint FK | → `principioativo.nome` |
| `ncmid` | bigint FK | → `ncm` (classificação fiscal) |
| `registroms` | varchar | Número de registro MS/ANVISA (ex.: MOUNJARO 10MG/ML → `1126002020081`) |
| `usocontinuo` | boolean | Medicamento de uso contínuo |
| `listapis` | char(1) | Lista PIS: `N` Negativa, `U` Neutra, `P` Positiva, `A` Não especificado |
| `tipopreco` | char(1) | `'L'` Liberado, outro = Monitorado |
| `origemmercadoria` | char(1) | Código fiscal de origem `'0'`–`'8'` (ver [tabela abaixo](#origemmercadoria)) |
| `perfilpisid` | bigint FK | → `perfilpis` (`piscst`, `descricao`) |
| `datahorainclusao` | timestamp | Data de cadastro — usada para excluir "produto novo" de análises de curva |

### ⚠️ `produto.tipo = 'M'` é filtro obrigatório em relatório de estoque/ruptura

Os produtos `tipo='S'` são **TAXA DE ENTREGA, ENTREGA EXPRESS, TAXA DE APLICAÇÃO, REENVIO DE
ENTREGA** — não têm estoque físico e **sempre aparecem como ruptura falsa**. Também poluem ranking
de "mais vendidos": sem o filtro, TAXA DE ENTREGA entrava em 7º lugar com R$ 508 mil.

Filtrar por `produto.tipo` é **mais seguro que filtrar por categoria**, porque ~97 mil produtos estão
sem classificação sob `PRINCIPAL` e um filtro de categoria os excluiria errado.

### `origemmercadoria`

| Valor | Significado |
| --- | --- |
| `0` | Nacional |
| `1` | Estrangeira — importação direta |
| `2` | Estrangeira — adquirida no mercado interno |
| `3` | Nacional — conteúdo > 40% e ≤ 70% |
| `4` | Nacional — processo produtivo básico |
| `5` | Nacional — conteúdo < 40% |
| `6` | Estrangeiro — imp. direta com similar nacional |
| `7` | Estrangeiro — mercado interno sem similar nacional |
| `8` | Nacional — conteúdo > 70% |

## `embalagem` — apresentações/SKUs

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `produtoid` | bigint FK | → `produto.id` |
| `codigobarras` | varchar | EAN/código de barras — ⚠️ **~4% das embalagens ativas de mercadoria não têm** (1.641 de 39.897) |
| `descricao` | varchar | Descrição completa (produto + apresentação) — tem índice `cidx_embalagem_descricao` sobre `normalize_str()` |
| `apresentacao` | varchar | Detalhe da apresentação (ex.: "CX 30 CP") |
| `etiqueta` | varchar (unique) | Código interno de etiqueta |
| `quantidadeporembalagem` | integer | Unidades por embalagem |
| `precovenda` | numeric | **Preço de venda BASE** do produto |
| `precoreferencial` | numeric | Preço referência (PMC/máximo) |
| `markup` | numeric | Markup % — ⚠️ **não confiável**, ver abaixo |
| `margemlucrovenda` | numeric | Margem de lucro % |
| `gruporemarcacaoid` | bigint FK | → `gruporemarcacao` — atributo **estável** da SKU |
| `padraofornecedores` | boolean | Embalagem padrão de compra |
| `ultimaalteracaoprecoid` | bigint FK | → `alteracaopreco` (última alteração de preço) |
| `datahorainclusao` | timestamp | |

Volume: ~39,7 mil embalagens ativas nesta rede.

### ⚠️ `embalagem.markup` não é confiável como base de cálculo

Comparado o markup cadastrado com `(preço / custo_atual − 1)`: diverge muito em boa parte dos casos
(ex.: markup cadastrado 34%, markup real hoje 1.975%). O campo provavelmente foi calculado contra o
custo em outro momento e nunca foi resincronizado.

→ **Não usar `markup` para calcular preço sugerido.** Exibir apenas como coluna informativa
("markup cadastrado").

### Preço base × preço por loja

- **Preço base** = `embalagem.precovenda`.
- **Override por loja** = `precoembalagemunidadenegocio.precovenda`.
- ⚠️ **O override é raro:** só **1.261 de 39.692 embalagens ativas (~3%)** têm preço próprio por
  loja. É defensável ignorá-lo e trabalhar só com o preço base numa tela de revisão de preço
  consolidada — mas em tela por loja (ex.: leitor de código de barras) usar
  `COALESCE(pun.precovenda, e.precovenda)`.

## `classificacao` — categorias hierárquicas

Tabela auto-referenciada por `classificacaopaiid`. O campo **`caminho`** guarda o caminho completo
com separador `" > "`:

```text
PRINCIPAL > CONVENIENCIA > CONV - ALIMENTOS
PRINCIPAL > FRALDAS > ADULTO
```

Ligação com produto: tabela N:N **`classificacaoproduto`** (`produtoid`, `classificacaoid`).

### ⚠️ `classificacao.principal = true` NÃO marca o topo

Validado: `principal` é `true` em ~100 nós — macro, sub e folha. **Para obter a categoria MACRO,
usar o 2º segmento do `caminho`:**

```sql
prod_cat AS (
  SELECT clp.produtoid, MIN(split_part(cl.caminho, ' > ', 2)) AS categoria
  FROM classificacaoproduto clp
  JOIN classificacao cl ON cl.id = clp.classificacaoid
  WHERE cl.caminho ILIKE 'PRINCIPAL > %'
  GROUP BY clp.produtoid
)
```

Agrupar por `cl.nome` dá ~100 subcategorias — granular demais para visão executiva.

⚠️ Quando o produto pode ter **mais de uma** classificação, usar `EXISTS`/`DISTINCT`, nunca `JOIN`
direto (fan-out). O `MIN(...)` acima serve para exibição (1 linha por produto); para **filtrar**,
usar uma CTE `DISTINCT (produtoid, chave)` + `EXISTS`.

⚠️⚠️ **Consequência direta: `JOIN classificacao ... AND classificacao.principal` como filtro ÚNICO
não garante uma linha por produto.** Como `principal` é `true` em ~100 nós, um produto pendurado em
mais de um nó `principal` **duplica** — e, se a query tiver um `SUM`, o valor infla sem nenhum sinal
de erro. Esse padrão aparece em queries herdadas (inclusive nas geradas pelo próprio ERP); ao
reaproveitar uma delas, trocar pelo par `caminho ILIKE 'PRINCIPAL > %'` +
`MIN(split_part(caminho,' > ',2))` agrupado por produto.

### As 9 categorias MACRO (nomes exatos observados em UMA base)

⚠️ **Isto é cadastro do cliente, não estrutura do ERP.** A árvore de `classificacao` é livre — outra
rede pode ter outra quantidade e outros nomes. Levantar por
`SELECT DISTINCT split_part(caminho,' > ',2) FROM classificacao WHERE caminho ILIKE 'PRINCIPAL > %'`
antes de hardcodar qualquer nome. O que é **estrutural** (e vale sempre) é o formato do `caminho` e
a necessidade da chave composta `categoria::nivel3`.

**PROPAGADO · GENERICOS · PERFUMARIA · CONVENIENCIA · SIMILAR · SUPLEMENTOS · VAREJO · SERVIÇOS ·
USO/CONSUMO**

- **`USO/CONSUMO`** = uso interno da rede → **excluir de relatórios de produto/venda**.
- **`SERVIÇOS`** também costuma ser ocultado de análise de categoria.
- Produto sem nó sob `PRINCIPAL` → rotular como **"Sem categoria"** (é uma pseudo-categoria, não
  existe linha em `classificacao`).

### Níveis

| Nível | Extração | Exemplo |
| --- | --- | --- |
| Macro (nível 2) | `split_part(caminho, ' > ', 2)` | `CONVENIENCIA` |
| Subcategoria (nível 3) | `split_part(caminho, ' > ', 3)` | `ALIMENTO E BEBIDA` |
| Chave desambiguada | `categoria || '::' || nivel3` | `CONVENIENCIA::ALIMENTO E BEBIDA` |

⚠️ **Nome de subcategoria se repete sob macros diferentes** — "ADULTO" existe sob `FRALDAS` **e** sob
`CALCADOS`. Sempre carregar a chave composta `categoria::nivel3`, nunca o nível 3 isolado.
Nesta rede há **66 combinações (categoria, nível 3)** reais.

⚠️ **Opções de filtro de categoria devem vir de uma query própria contra `classificacao`**, nunca
derivadas das linhas já carregadas/limitadas — senão categorias de baixo volume somem do próprio
filtro sem ninguém perceber.

## `custoproduto` — custo por produto/loja

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `produtoid` | bigint FK | → `produto` (unique por produto+loja) |
| `unidadenegocioid` | bigint FK | → `unidadenegocio` |
| `custo` | numeric | **Custo da última compra** |
| `customedio` | numeric | **Custo médio ponderado** |

Join canônico:

```sql
LEFT JOIN custoproduto cp
       ON cp.produtoid = e.produtoid
      AND cp.unidadenegocioid = v.unidadenegocioid
```

- ⚠️ **É o custo de HOJE**, aplicado retroativamente a qualquer período. Para custo histórico real,
  usar `movimentacaoestoque.customedio`/`.custo` (custo no momento da movimentação).
- ~13,5% dos itens não têm registro de custo para o par produto+loja → mostrar "—", nunca 0.
- Ao consolidar um produto entre lojas numa linha só, a convenção da casa é **média simples** entre
  as lojas onde o produto é vendido (todas pesam igual; não pondera por receita nem usa pior caso).

## `precoembalagemunidadenegocio` — preço por apresentação/loja

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `embalagemid` | bigint FK | → `embalagem` (unique por embalagem+loja) |
| `unidadenegocioid` | bigint FK | → `unidadenegocio` |
| `precovenda` | numeric | Preço de venda na loja |
| `precoreferencial` | numeric | Preço referência na loja |
| `markup` | numeric | Markup na loja |

## `curvaabc` / `curvaabcprodutounidadenegocio`

- **`curvaabc`** — definições. IDs observados: **A = 340, B = 341, C = 342, D = 343**.
- **`curvaabcprodutounidadenegocio`** — liga produto+loja à curva, em **duas dimensões**:
  - `curvaabcvalorid` (curva por valor)
  - `curvaabcquantidadeid` (curva por quantidade)

  Validado: nesta base as duas **sempre coincidem** (mesma contagem exata) — basta checar uma.

### ⚠️⚠️ Curva D "fantasma": a classificação sobrevive ao estoque zerar

`curvaabcvalorid = 343` marca a combinação produto+loja como Curva D **independente do estoque
atual** — o ERP mantém a classificação depois de o estoque zerar/ser consumido.

Bug real: uma tela contava "produtos em Curva D" sem checar estoque, inflando a métrica com itens
que já não têm uma unidade sequer parada. Ao corrigir, o fabricante EMS GENERICOS caiu de
**204 → 125 produtos** em Curva D.

**Correção:** sempre juntar com estoque agregado e exigir `> 0`:

```sql
curva_d AS (
  SELECT c.produtoid, c.unidadenegocioid
  FROM curvaabcprodutounidadenegocio c
  JOIN lojas_ativas la ON la.id = c.unidadenegocioid
  JOIN estoque_prod_loja epl
    ON epl.produtoid = c.produtoid
   AND epl.unidadenegocioid = c.unidadenegocioid   -- CTE com HAVING SUM(est.estoque) > 0
  WHERE c.curvaabcvalorid = 343
)
```

**Exceções deliberadas** (onde NÃO se deve exigir estoque > 0): flag de auditoria num item
recém-recebido (conciliação de compras) e a análise "Curva D com saída em outra loja", cujo objetivo
é justamente achar Curva D com pouco estoque.

⚠️ O **CD principal** sozinho tem **70.302 produtos com Curva D** — é depósito, quase todo o catálogo
"não vende" saindo dele. Sempre filtrar por `lojas_ativas` (que exclui CDs).

⚠️ Ao contar Curva D como indicador de gestão, é comum **excluir produto cadastrado há menos de 30
dias** (`produto.datahorainclusao`) — produto novo não teve tempo de ter classificação justa.
Efeito medido: ~1,7% dos produtos em Curva D têm menos de 90 dias de cadastro.

## Cadastro fiscal e complementar

| Tabela | Conteúdo |
| --- | --- |
| `fabricante` | `pessoaid` → `pessoa.nome`. ~1.219 fabricantes cadastrados nesta base |
| `principioativo` | `nome` (ex.: `TIRZEPATIDA`) |
| `ncm` | `codigo`, `nome` |
| `perfilpis` | `piscst`, `descricao` |
| `icmsproduto` | `produtoid`, `estadoid`, `perfilicmsid` — o `estadoid` filtra por UF (ex.: `83`) |
| `perfilicms` | `icmscst`, `descricao` |
| `campopersonalizadoconfiguracao` / `campopersonalizado` | **EAV** de campos customizados (ver abaixo) |

### ⚠️ Campos personalizados (EAV) — não achável por introspecção comum

O Alpha 7 tem uma estrutura de **campo customizado**, invisível numa varredura de nomes de coluna:

- **`campopersonalizadoconfiguracao`** (`id`, `titulo`, `categoria`, `tipo`, `obrigatorio`, `status`)
  define **quais** campos existem. Ex.: "Data de Admissão", categoria "Dado Trabalhista" — aparece na
  UI do Alpha 7 em `Usuário → Editar → Campos Personalizados`.
- **`campopersonalizado`** (`id`, `valor` text, `usuarioid`, `pessoaid`, `clienteid`, `fornecedorid`,
  `fabricanteid`, `produtoid`, …) guarda o **valor**, com **uma coluna de FK por tipo de entidade**
  (polimórfico por coluna, não por par tipo+id).
- ⚠️ **O valor é TEXTO no padrão brasileiro** — "Data de Admissão" vem como `"17/05/2018"`, não ISO,
  não timestamp. Fazer parse com regex `DD/MM/AAAA` e retornar `null` (nunca uma data inventada) se
  não bater.

**⚠️ Não confundir `fabricante` com marca única:** o ERP tem fabricantes com nome **literalmente
duplicado** — dois cadastros "KENDALL" com ids diferentes, "BARUEL"/"BARUEL " (espaço a mais),
"ALCON BRASIL" ×2, "HENKEL LTDA" ×2, "CIFARMA - MABRA" ×2, "CRISTALIA PRODUTOS QUIMICOS
FARMACEUTICO" ×2, "KIMBERLY - CLARK" ×2. Ao casar fabricante por nome, tratar múltiplos candidatos
sob a mesma chave normalizada como **o mesmo fabricante** e vincular **todos os ids** — senão
produtos cadastrados sob o id "gêmeo" ficam de fora do filtro.
Já no match "contém" (substring) a regra deve ser **estrita** (só aceitar match único) — ali
múltiplos candidatos costumam ser marcas de fato diferentes (ex.: "EUROFARMA" bate em
"EUROFARMA OTC"/"GENÉRICO"/"RX").

## `gruporemarcacao`

Tabela simples `{id, nome}`. O vínculo estável é **`embalagem.gruporemarcacaoid`** — atributo da
própria SKU, independente de campanha ativa.

⚠️ **Não** derivar grupo de remarcação de `itemcadernooferta` — lá o grupo aparece só dentro de uma
campanha ativa específica (`tipoitem='B'` + `gruporemarcacaoid`, com `embalagemid` NULL nessas
linhas), o que não serve como "esta embalagem pertence a este grupo".

```sql
LEFT JOIN gruporemarcacao gr ON gr.id = e.gruporemarcacaoid
```

## Busca de produto por descrição

Padrão validado (~40–50 ms), reaproveitável em qualquer autocomplete de produto:

1. **Caminho rápido — prefixo** sobre `normalize_str(embalagem.descricao)`, que tem índice próprio
   (`cidx_embalagem_descricao`). Palavras extras (2ª em diante) entram como filtro "contém" sobre o
   resultado já estreitado pelo prefixo — continuam baratas.
2. **Fallback "contém, qualquer ordem"** — se o prefixo não achar nada (usuário começou pelo meio:
   "500mg dipirona"), cada palavra vira `LIKE '%palavra%'` própria, todas obrigatórias, em qualquer
   posição. Mais lento (sem índice), mas só roda quando o caminho rápido veio vazio.
3. Filtrar `produto.status='A' AND produto.tipo='M'`.
4. ⚠️ Ordenar pela **expressão numérica**, nunca pelo alias `::text` — ver
   [10-armadilhas.md](10-armadilhas.md).

Como ~4% das embalagens não têm código de barras, toda rota de lookup deve aceitar
**`embalagem_id` como alternativa ao código**:

```sql
WHERE ($1::bigint IS NOT NULL AND e.id = $1)
   OR ($2::text  IS NOT NULL AND e.codigobarras = $2)
```

⚠️ Ao normalizar **nome de pessoa**, nunca descartar palavras por comprimento — partículas de 1
letra são parte do nome. Bug real: o filtro `palavra.length > 1` transformava
`"2-COMPRE E RETIRE"` em `"COMPRE RETIRE"` e o cadastro deixava de casar. Descartar só blocos
puramente numéricos.
