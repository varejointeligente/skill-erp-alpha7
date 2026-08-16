# ERP Alpha 7 — Visão geral e conceitos fundamentais

> Base de conhecimento destilada de documentação de projeto real (rede de farmácias) e de um Data
> Warehouse construído sobre o mesmo ERP. Tudo aqui foi observado/validado contra bancos reais do
> Alpha 7; o que for incerto está marcado como tal.

## Sumário

- [O que é o Alpha 7](#o-que-é-o-alpha-7)
- [Banco de dados e padrão de nome das bases](#banco-de-dados-e-padrão-de-nome-das-bases)
- [Conceito-chave 1 — o padrão `pessoa`](#conceito-chave-1--o-padrão-pessoa)
- [Conceito-chave 2 — a camada `embalagem`](#conceito-chave-2--a-camada-embalagem)
- [Convenções gerais do schema](#convenções-gerais-do-schema)
- [Mapa de relacionamentos principais](#mapa-de-relacionamentos-principais)
- [Somente leitura (e a exceção)](#somente-leitura-e-a-exceção)
- [Índice dos demais arquivos](#índice-dos-demais-arquivos)

---

## O que é o Alpha 7

O **Alpha 7** é um ERP de varejo farmacêutico (rede de drogarias). Cobre PDV/venda, estoque,
compras, transferências entre lojas, entregas a domicílio, crediário/convênio, contas a
pagar/receber, tesouraria/conciliação, precificação/cadernos de oferta, receita médica e prescritor,
e um DRE pré-computado.

Características que moldam qualquer consulta:

- É um schema **grande e antigo**, com nomes de tabela/coluna **tudo em minúsculo e sem separador**
  (`unidadenegocio`, `movimentacaoestoque`, `estoqueminimoprodutounidadenegocio`).
- Volumes reais medidos numa rede de ~14–20 lojas: `pessoa` ~5,4 milhões de linhas,
  `movimentacaoestoque` ~32,2 milhões, `itemvenda` ~26,2 milhões, `venda` ~9,4 milhões,
  `orcamento` ~3,9 milhões, `itempedidocompra` ~3,3 milhões.
- **Praticamente não há FK nem CHECK constraint declarados** no banco (validado ao inspecionar
  `alteracaopreco` e `embalagem`): o Alpha 7 confia na aplicação cliente para manter consistência.
  Quem escreve nele precisa replicar as invariantes à mão.
- Muitos campos são `char(1)` com significado dependente da tabela (ver
  [11-glossario.md](11-glossario.md)).

## Banco de dados e padrão de nome das bases

- **PostgreSQL.** Todo o SQL deste conjunto de referências é Postgres (`ILIKE`, `::tipo`,
  `split_part`, `FILTER`, CTEs, `generate_series`, `DISTINCT ON`).
- **Nome da base segue o padrão `<cliente>_esc_<data>`** — exemplos reais observados:
  - `ultrapopularprimaveradoleste_esc_20250715`
  - `primaveradoleste_loja01_20250819` (variante `<cliente>_loja<NN>_<data>`)

  ⚠️ **O banco corrente é ROTACIONADO periodicamente** pelo próprio Alpha 7 — a data no nome muda.
  Toda string de conexão precisa ser atualizada quando isso acontece. Trocar o nome do banco **não**
  altera permissões nem regras de rede (ver [09-consultas-e-performance.md](09-consultas-e-performance.md)).

- **Fuso da sessão do Postgres = `America/Sao_Paulo` (UTC-3)**, mesmo quando a operação real está em
  `America/Cuiaba` (UTC-4). Isso quebra `CURRENT_DATE`/`NOW()::date` — ver a armadilha em
  [10-armadilhas.md](10-armadilhas.md).

- Existe uma função no banco: **`normalize_str(texto)`** (remove acento + normaliza caixa), com
  índices dedicados construídos sobre ela (`cidx_pessoa_nome`, `cidx_embalagem_descricao`). É a
  base de toda busca textual performática.

## Conceito-chave 1 — o padrão `pessoa`

O Alpha 7 usa uma **tabela central `pessoa`** que armazena todos os dados pessoais/de entidade
(nome, CPF, CNPJ, sexo, data de nascimento, estado civil, endereço). As tabelas de **papel** têm FK
`pessoaid` apontando para ela:

```text
pessoa (entidade central)
  ├── cliente     (papel: cliente)
  ├── fornecedor  (papel: fornecedor)
  ├── fabricante  (papel: fabricante)
  ├── usuario     (papel: usuário do sistema / colaborador)
  ├── prescritor  (papel: médico prescritor)
  └── farmaceutico(papel: farmacêutico responsável)
```

```sql
-- Nome de um cliente
SELECT p.nome FROM cliente c JOIN pessoa p ON p.id = c.pessoaid WHERE c.id = $1;

-- Nome de um fabricante
SELECT p.nome FROM fabricante f JOIN pessoa p ON p.id = f.pessoaid WHERE f.id = $1;

-- Nome de um usuário/colaborador
SELECT p.nome FROM usuario u JOIN pessoa p ON p.id = u.pessoaid WHERE u.id = $1;
```

Consequências práticas:

1. **`venda.pessoaid` aponta para `pessoa`, não para `cliente`.** A entidade de cliente para
   relatórios é `pessoa` — muitos compradores identificados (com milhares de cupons) **não têm
   registro em `cliente`**. Nunca restringir busca de cliente por `EXISTS cliente`.
2. **Um mesmo `pessoa.id` pode acumular papéis.** É assim que se descobre, por exemplo, que o
   fabricante selecionado também é o fornecedor direto de uma nota:
   `fornecedor.pessoaid = fabricante.pessoaid`.
3. Telefone/e-mail **não** ficam em `pessoa` — ficam em `contato` (`pessoaid`, `ddd`, `contato`,
   `principal`, `tipo`: `T`=telefone, `C`=celular, `E`=e-mail).
4. `pessoa.tipo`: `F` = física (~5,4 mi), `J` = jurídica (~6,3 mil — convênios/empresas).

## Conceito-chave 2 — a camada `embalagem`

**Produtos não são vendidos diretamente.** Existe uma tabela intermediária **`embalagem`**
(apresentação/SKU) entre `produto` e quase tudo — venda, estoque, movimentação, transferência,
oferta, nota fiscal, pedido de compra. Um produto pode ter várias apresentações (CX 10, CX 30,
unitário) com códigos de barras e preços diferentes.

```text
produto (1) → (N) embalagem → itemvenda
                            → estoque
                            → movimentacaoestoque
                            → itemtransferencia
                            → itemnotafiscal
                            → itempedidocompra
                            → itemcadernooferta
                            → precoembalagemunidadenegocio
                            → itemdevolucaovenda / devolucaocompraitem
                            → receitamedicaitem
```

**Nunca fazer JOIN direto de `itemvenda` com `produto`** — sempre passar por `embalagem`:

```sql
SELECT p.descricao, e.apresentacao, iv.quantidade, iv.valortotal
FROM itemvenda iv
JOIN embalagem e ON e.id = iv.embalagemid
JOIN produto  p ON p.id = e.produtoid;
```

**Exceções conhecidas (ligam direto em `produto`, sem passar por `embalagem`):**

| Tabela | Coluna |
| --- | --- |
| `itempedidotransferencia` | `produtoid` (direto) |
| `custoproduto` | `produtoid` + `unidadenegocioid` |
| `estoqueminimoprodutounidadenegocio` | `produtoid` + `unidadenegocioid` |
| `estoquemaximoprodutounidadenegocio` | `produtoid` + `unidadenegocioid` |
| `curvaabcprodutounidadenegocio` | `produtoid` + `unidadenegocioid` |
| `suspendecompraprodutounidadenegocio` | `produtoid` + `unidadenegocioid` |
| `classificacaoproduto` | `produtoid` |
| `icmsproduto` | `produtoid` |

⚠️ **Assimetria central:** `estoque` é por **embalagem+loja**, mas mínimo/máximo, custo e curva ABC
são por **produto+loja**. Para comparar, agregue o estoque por produto
(`SUM(e.estoque) GROUP BY loja, embalagem.produtoid`).

## Convenções gerais do schema

- **Todos os PKs/FKs são `bigint`** — e não são sequenciais pequenos. `unidadenegocio.id` chega a
  `1050000376428`; `formapagamento.id` de PIX/IFOOD passa de 10 dígitos. Nunca assumir inteiro
  pequeno; serializar BigInt na camada de aplicação, ou fazer `::text` no SELECT.
- **Status `char(1)`** — o significado depende da tabela. Padrão mais comum: `'A'` = Ativo/Aberto,
  `'F'` = Finalizado, `'C'` = Cancelado/Conferido (varia!), `'I'` = Inativo/Inicial,
  `'B'` = Baixado. Ver a tabela completa em [11-glossario.md](11-glossario.md).
- **`'?'` como default** — muitos campos `char(1)` usam `'?'` para "não definido".
- **Campos de texto livre são sujos** — `unidadenegocio.cidade`, `cidade.nome`, `cadernooferta.nome`,
  `classificacao.caminho`, `prescritor.nome`, `contato.contato`. Sempre normalizar
  (`UPPER(TRIM(...))`, `normalize_str`) antes de agrupar por eles.
- **Nome de loja em relatório:** usar **`LEFT(un.nome, 2)`** — os 2 primeiros caracteres de `nome`
  são o apelido interno (`"CV - FILIAL - CAMPO VERDE"` → `"CV"`). Não existe coluna `apelido` em
  `unidadenegocio`. Nunca usar o `id` bigint como rótulo.

## Mapa de relacionamentos principais

```text
pessoa
  ├── cliente / fornecedor / fabricante / usuario / prescritor / farmaceutico
  └── contato (telefone, e-mail)

produto
  ├── embalagem (1:N — apresentações/SKUs)
  │     ├── estoque (por loja)
  │     ├── movimentacaoestoque (histórico)
  │     ├── itemvenda
  │     ├── itemtransferencia
  │     ├── itemnotafiscal
  │     ├── itemcadernooferta
  │     └── precoembalagemunidadenegocio
  ├── classificacaoproduto → classificacao (N:N, hierárquica)
  ├── curvaabcprodutounidadenegocio
  ├── custoproduto
  ├── estoqueminimoprodutounidadenegocio / estoquemaximoprodutounidadenegocio
  ├── suspendecompraprodutounidadenegocio
  ├── fabricante → pessoa
  ├── principioativo
  └── ncm

venda
  ├── itemvenda (1:N)
  ├── pagamentovenda → formapagamento (1:N)
  ├── devolucaovenda → itemdevolucaovenda
  ├── unidadenegocio (loja)
  ├── usuario (operador de CAIXA — não é o vendedor!)
  └── pessoa (cliente, opcional)

orcamento (carrinho/cotação, antecede a venda)
  ├── itemorcamento (usuarioid = VENDEDOR de verdade)
  ├── vendaid → venda
  ├── entrega
  ├── receitamedica → prescritor + receitamedicaitem
  └── liberacaousuarionegociacaonegativaid → liberacaousuario

transferencia / pedidotransferencia / recebimentotransferencia (N:N via transferenciapedido)
notafiscal → itemnotafiscal (CFOP classifica compra × transferência × serviço)
          → recebimentofisiconotafiscal → recebimentofisico → recebimentofisicopedidocompra → pedidocompra
          → notafiscalcontapagar → contapagar → planocontas
```

## Somente leitura (e a exceção)

O acesso ao Alpha 7 num projeto de BI/relatórios é normalmente **`GRANT SELECT` puro**. Nada de
escrita: "conferido", "aprovado", "dispensado" etc. têm de ser gravados num banco próprio da
aplicação, indexados pelo id do ERP guardado **como texto** (bigint não cabe em `Int` de muitos ORMs).

**Exceção documentada — escrita real de alteração de preço.** Um caso específico exigiu credencial
separada (`GRANT SELECT, UPDATE ON embalagem, INSERT ON alteracaopreco` — nada de
DELETE/DROP/TRUNCATE). Regras descobertas ao inspecionar o schema **antes** de escrever:

- Nem `alteracaopreco` nem `embalagem` têm FK/CHECK — toda invariante é responsabilidade de quem grava.
- Alteração de preço **BASE** (não override por loja) grava `alteracaopreco.unidadenegocioprecoid = NULL`
  **e** `unidadenegocioid = 1` (ESC/Escritório) — confirmado em 4.387 de 4.388 casos recentes.
- `precoreferencial` (PMC/máximo) **não muda** — grava-se o valor atual como anterior e posterior.
- `alteracaopreco.usuarioid` sempre resolve para um `usuario.id` real (mesmo sem FK formal).
- `embalagem.ultimaalteracaoprecoid` precisa apontar para o novo registro: fazer
  `INSERT alteracaopreco ... RETURNING id` **antes** do `UPDATE embalagem`, tudo na mesma transação
  (`BEGIN` / `SELECT ... FOR UPDATE` / `COMMIT` / `ROLLBACK`).

Detalhes em [07-compras-precificacao.md](07-compras-precificacao.md).

## Índice dos demais arquivos

| Arquivo | Conteúdo |
| --- | --- |
| [02-vendas.md](02-vendas.md) | `venda`, `itemvenda`, `pagamentovenda`, `formapagamento`, devoluções de venda, canais digitais/televendas, vendedor, fórmulas de faturamento/margem/ticket |
| [03-produto-embalagem.md](03-produto-embalagem.md) | `produto`, `embalagem`, `classificacao`, `precoembalagemunidadenegocio`, `custoproduto`, `curvaabc`, apresentações e cadastro fiscal |
| [04-estoque.md](04-estoque.md) | `estoque`, `movimentacaoestoque`, mín/máx, ruptura, transferências, perdas/baixas, inventário, suspensão de compra |
| [05-pessoas-clientes.md](05-pessoas-clientes.md) | `pessoa`, `cliente`, `contato`, `prescritor`, `receitamedica`, `farmaceutico`, `usuario`, busca por nome/CPF e performance, pessoa jurídica |
| [06-financeiro.md](06-financeiro.md) | contas a pagar/receber, `cancelamentocontapagar`, crediário, cartão, conta corrente, `planocontas`, `dre`, tesouraria/conciliação, `lancamentofinanceiro` |
| [07-compras-precificacao.md](07-compras-precificacao.md) | `pedidocompra`, `notafiscal`, `recebimentofisico`, `cadernooferta`, `orcamento`/`itemorcamento`/`liberacaousuario`, margem objetiva, alteração de preço, elasticidade |
| [08-logistica-entregas.md](08-logistica-entregas.md) | `entrega`, `remessa`, `entregaremessa`, endereço/geocodificação, `unidadenegocio` |
| [09-consultas-e-performance.md](09-consultas-e-performance.md) | joins canônicos, padrões de query, cuidados de performance, conexão/túnel SSH, particularidades do Postgres nessa base |
| [10-armadilhas.md](10-armadilhas.md) | catálogo sintoma → causa → correção → como evitar |
| [11-glossario.md](11-glossario.md) | vocabulário do negócio ↔ tabela/coluna/valor |
| [12-dw-pentaho.md](12-dw-pentaho.md) | modelo dimensional do DW construído sobre o Alpha 7, com as queries-fonte reais |
