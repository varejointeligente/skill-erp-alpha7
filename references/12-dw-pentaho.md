# Data Warehouse sobre o Alpha 7 — modelo dimensional e queries-fonte

> Referência de **"como já se extraiu esse dado antes"**. As queries abaixo vieram das transformações
> Pentaho (`.ktr`) e de um DAG Airflow que migrou o mesmo ETL. Entidades XML foram decodificadas e os
> parâmetros do Pentaho foram substituídos por placeholders explicados.
>
> ⚠️ Este DW é uma **fonte secundária**: alguns mapeamentos aqui divergem do que foi validado ao vivo
> contra o ERP (notavelmente `entrega.status`). Onde há conflito, a divergência está marcada.

## Sumário

- [Arquitetura do ETL](#arquitetura-do-etl)
- [Convenção de parâmetros](#convenção-de-parâmetros)
- [Dimensões](#dimensões)
- [Fatos](#fatos)
- [O que o DW NÃO cobre](#o-que-o-dw-não-cobre)
- [Achados de modelagem reaproveitáveis](#achados-de-modelagem-reaproveitáveis)

---

## Arquitetura do ETL

```text
Alpha 7 (PostgreSQL, somente leitura)
        │
        ├── 1.Dimensoes/*.ktr   → dim_*   (lookup/update SCD)
        └── 2.Fatos/*.ktr       → fato_*  (lookup de SK + insert)
                │
                ▼
        DW (PostgreSQL próprio)
```

- Duas conexões: `alpha7_postgres` (fonte) e `dw_postgres` (destino).
- Execução **diária**, processando o dia anterior nos fatos com janela de data.
- **Surrogate keys (`sk`)** próprias por dimensão; a chave natural do ERP fica em **`nk`**.

**Tipos de SCD usados:**

| Dimensão | SCD |
| --- | --- |
| `dim_filial` | Tipo 2 (`date_from`, `date_to`, `version`) |
| `dim_pessoa` | Tipo 2 |
| `dim_produtos` | Tipo 2 |
| `dim_curvaabc` | Tipo 2 |
| `dim_usuario` | Tipo 1 |
| `dim_contacorrente` | Tipo 1 |
| `dim_planodecontas` | Tipo 1 |

Índices do DW: `(nk, date_to) WHERE date_to IS NULL` nas dimensões SCD-2 (registro vigente).

## Convenção de parâmetros

As transformações Pentaho usam **`?` posicional** (não `${...}`), alimentado por um passo anterior
que devolve uma linha com a janela de datas. Nas queries abaixo, os `?` foram substituídos por
`$1`, `$2`… e a origem está explicada em cada caso.

Os passos de janela mais comuns:

```sql
-- "Seleciona dt_inicio e dt_fim" (padrão dos fatos com janela)
SELECT date_trunc('day', MIN(<coluna_de_data>))                                AS inicio,
       date_trunc('day', MIN(<coluna_de_data>)) + interval '1 day -1 second'   AS fim
FROM <tabela_do_fato>;
```

(No DAG Airflow o mesmo papel é feito em código: `ontem 00:00:00` … `ontem 23:59:59`.)

---

## Dimensões

### `dim_filial` — SCD 2, a partir de `unidadenegocio`

```sql
SELECT
    un.id                                             AS nk,
    COALESCE(gun.nome, 'Sem grupo de negócio')        AS grupo_negocio,
    un.codigo,
    un.nome,
    COALESCE(un.razaosocial,  'Sem razão social')     AS razaosocial,
    COALESCE(un.nomefantasia, 'Sem nome fantasia')    AS nomefantasia,
    COALESCE(un.cidade,       'Sem cidade')           AS cidade,
    COALESCE(un.cnpj,         'Sem Cnpj')             AS cnpj,
    CASE WHEN status = 'I' THEN 'Não' ELSE 'Sim' END  AS ativo,
    CASE
        -- Verifica se há um segundo hífen
        WHEN (length(regexp_replace(un.nome, '[^-]', '', 'g')) >= 2) THEN
            substring(
                un.nome
                FROM 1 FOR position('-' IN un.nome || '')
                          + position('-' IN substring(un.nome FROM position('-' IN un.nome) + 1)) - 1
            )
        ELSE un.nome
    END                                               AS nome_reduzido
FROM unidadenegocio un
LEFT JOIN grupounidadenegocio gun ON un.grupounidadenegocioid = gun.id;
```

Colunas do DW: `sk`, `nk`, `grupo_negocio`, `codigo`, `nome`, `razaosocial`, `nomefantasia`,
`cidade`, `cnpj`, `ativo`, `nome_reduzido`, `date_from`, `date_to`, `version`.

> Descoberta reaproveitável: existe **`grupounidadenegocio`** (agrupamento de filiais), pouco citado
> em outras fontes. E o "nome reduzido" corta o nome até o **2º hífen** — alternativa ao
> `LEFT(nome,2)` usado nos relatórios operacionais.

### `dim_pessoa` — SCD 2

```sql
SELECT
    p.id AS nk,
    nome,
    CASE WHEN tipo = 'J' THEN 'Juridico' ELSE 'Fisico' END                        AS tipo,
    COALESCE(date_part('year', age(current_date, p.datanascimento)), 0)           AS idade,
    CASE WHEN sexo = 'M' THEN 'Masculino'
         WHEN sexo = 'F' THEN 'Feminino'
         ELSE 'Não incide' END                                                     AS sexo,
    CASE WHEN status = 'A' THEN 'Sim' ELSE 'Não' END                              AS ativo,
    CASE WHEN estadocivil = 'S' THEN 'Solteiro'
         WHEN estadocivil = 'C' THEN 'Casado'
         ELSE 'Não incide' END                                                     AS estadocivil,
    (EXTRACT(epoch FROM age(now(), p.datahorainclusao)) / 86400)::int             AS dias_cadastrado
FROM pessoa p;
```

⚠️ Sem filtro — varre as ~5,4 milhões de linhas de `pessoa`.

### `dim_produtos` — SCD 2, granularidade **EMBALAGEM**

⚠️ **A `nk` é `embalagem.id`, não `produto.id`.** Coerente com o ERP: nada é vendido no nível de
produto.

```sql
SELECT
    e.id                                                              AS nk,
    e.descricao,
    classificacao.caminho                                             AS classificacao_caminho,
    classificacao.nome                                                AS classificacao,
    split_part(classificacao.caminho, ' > ', 2)                       AS classficacao_pai,
    CASE WHEN e.padraofornecedores = true THEN 'Sim' ELSE 'Não' END   AS padrao,
    COALESCE(e.codigobarras, 'Sem código de barras')                  AS barras,
    (EXTRACT(epoch FROM age(now(), e.datahorainclusao)) / 86400)::int AS dias_cadastrado,
    COALESCE(gr.nome, 'Sem grupo de remarcação')                      AS grupo_remarcacao,
    CASE WHEN p.listapis = 'N' THEN 'Negativa'
         WHEN p.listapis = 'U' THEN 'Neutra'
         WHEN p.listapis = 'P' THEN 'Positiva'
         WHEN p.listapis = 'A' THEN 'Não especificado' END            AS lista,
    CASE WHEN p.status = 'I' THEN 'Não' ELSE 'Sim' END                AS ativo,
    CASE WHEN tipopreco = 'L' THEN 'Liberado' ELSE 'Monitorado' END   AS tipo_preco,
    COALESCE(p.registroms, 'Sem registro MS')                         AS registroms,
    pe.nome                                                           AS fabricante,
    COALESCE(pa.nome, 'Sem Principio Ativo')                          AS principio_ativo,
    CASE WHEN p.tipo = 'M' THEN 'Mercadoria'
         WHEN p.tipo = 'S' THEN 'Serviço'
         WHEN p.tipo = 'T' THEN 'Serviço tomado'
         ELSE 'Ajuste Fiscal' END                                     AS tipo_produto,
    CASE WHEN p.origemmercadoria = '0' THEN 'Nacional'
         WHEN p.origemmercadoria = '1' THEN 'Estrangeira - Importação direta'
         WHEN p.origemmercadoria = '2' THEN 'Estrangeira - Adquirida no mercado interno'
         WHEN p.origemmercadoria = '3' THEN 'Nacional - Conteúdo superior a 40% e inferior ou igual a 70%'
         WHEN p.origemmercadoria = '4' THEN 'Nacional - Processo Produtivo básico'
         WHEN p.origemmercadoria = '5' THEN 'Nacional - Conteúdo inferior a 40%'
         WHEN p.origemmercadoria = '6' THEN 'Estrageiro - Imp. direta com similar nacional'
         WHEN p.origemmercadoria = '7' THEN 'Estrageiro - Mercado interno sem similar nacional'
         WHEN p.origemmercadoria = '8' THEN 'Nacional - Conteúdo superior a 70%' END AS origem,
    ncm.codigo    AS ncm_codigo,
    ncm.nome      AS ncm_nome,
    pis.piscst    AS pis_cst,
    pis.descricao AS pis_descricao,
    p2.icmscst    AS icms_cst,
    p2.descricao  AS icms_descricao
FROM embalagem e
JOIN produto p                ON e.produtoid = p.id
JOIN classificacaoproduto c   ON p.id = c.produtoid
JOIN classificacao            ON classificacao.id = c.classificacaoid
                             AND classificacao.principal
JOIN fabricante f             ON p.fabricanteid = f.id
LEFT JOIN pessoa pe           ON f.pessoaid = pe.id
LEFT JOIN gruporemarcacao gr  ON e.gruporemarcacaoid = gr.id
LEFT JOIN ncm                 ON p.ncmid = ncm.id
LEFT JOIN principioativo pa   ON p.principioativoid = pa.id
LEFT JOIN perfilpis pis       ON p.perfilpisid = pis.id
LEFT JOIN icmsproduto icms    ON p.id = icms.produtoid AND icms.estadoid = 83
LEFT JOIN perfilicms p2       ON icms.perfilicmsid = p2.id;
```

⚠️ Notas críticas sobre esta query:

- Usa `classificacao.principal` como filtro — mas foi **validado ao vivo que `principal` é `true` em
  ~100 nós** (macro, sub e folha), então isso **não** garante uma linha por produto. Com mais de um
  nó `principal` casando, o produto **duplica** na dimensão. Nos relatórios operacionais a convenção
  correta é `caminho ILIKE 'PRINCIPAL > %'` + `MIN(split_part(caminho,' > ',2))` agrupado por produto.
- `JOIN fabricante` é **INNER** — produto sem fabricante cai fora da dimensão.
- `icms.estadoid = 83` é um valor fixo de UF — conferir antes de reusar em outro estado.

### `dim_usuario` — SCD 1

```sql
SELECT
    u.id                                                              AS nk,
    login,
    initcap(apelido)                                                  AS apelido,
    initcap(p.nome)                                                   AS nome,
    initcap(split_part(p.nome, ' ', 1))                               AS primeiro_nome,
    COALESCE(date_part('year', age(current_date, p.datanascimento)),0) AS idade,
    CASE WHEN sexo = 'M' THEN 'Masculino' ELSE 'Feminino' END         AS sexo,
    (EXTRACT(epoch FROM age(now(), p.datahorainclusao)) / 86400)::int AS dias_cadastrado,
    COALESCE(initcap(un.nome), 'Sem filial associada')                AS filial
FROM usuario u
LEFT JOIN unidadenegocio un ON u.unidadenegocioid = un.id
LEFT JOIN pessoa p          ON u.pessoaid = p.id;
```

> Confirma o padrão `pessoa`: **nome e sexo do colaborador vêm de `pessoa`**, não de `usuario`.
> `login` está exposto como atributo próprio (é o "número do ERP" que as pessoas citam).

⚠️ O `CASE` de sexo aqui não trata `'N'` (não informado) — cai em "Feminino". A versão de
`dim_pessoa` trata corretamente.

### `dim_curvaabc` — SCD 2, granularidade **produto × loja × embalagem**

```sql
SELECT
    c.produtoid,
    c.unidadenegocioid,
    e.id                AS embalagemid,
    curvaabc.nome       AS curvaabcquantidade,
    c2.nome             AS curvaabcvalor
FROM curvaabcprodutounidadenegocio c
JOIN curvaabc     ON c.curvaabcquantidadeid = curvaabc.id
JOIN curvaabc c2  ON c.curvaabcvalorid      = c2.id
JOIN produto p    ON c.produtoid            = p.id
JOIN embalagem e  ON p.id                   = e.produtoid
ORDER BY c.unidadenegocioid, e.id;
```

> Mostra a "descida" de granularidade: a curva é por **produto+loja** no ERP, mas o DW a explode por
> **embalagem** para poder ligar aos fatos, que são todos por embalagem.
>
> ⚠️ Esta query **não filtra estoque > 0** — sujeita à armadilha da "Curva D fantasma"
> (ver [03-produto-embalagem.md](03-produto-embalagem.md)).

### `dim_contacorrente` — SCD 1

```sql
SELECT id,
       CASE status WHEN 'A' THEN 'Ativo' ELSE 'Inativo' END      AS status,
       nome,
       CASE tipo   WHEN 'B' THEN 'Bancária' ELSE 'Caixa' END     AS tipo,
       unidadenegocioid
FROM contacorrente;
```

### `dim_planodecontas` — SCD 1

```sql
SELECT id                                   AS nk,
       nome,
       caminho,
       split_part(caminho, ' > ', 3) AS nivel1,
       split_part(caminho, ' > ', 4) AS nivel2,
       split_part(caminho, ' > ', 5) AS nivel3,
       split_part(caminho, ' > ', 6) AS nivel4
FROM planocontas;
```

⚠️ **Índices diferentes dos usados nos relatórios operacionais** (que usam 2/3/4 depois do prefixo
`Resultado > `). Esta versão assume um caminho com **um segmento a mais** — provável raiz adicional.
**Sempre inspecionar o `caminho` cru antes de reusar qualquer índice de `split_part`.**

### `dim_cadernooferta`

```sql
SELECT
    id AS nk,
    CASE WHEN status = 'A' THEN 'Sim' ELSE 'Não' END AS ativo,
    c.nome,
    c.datahorainicial,
    c.datahorafinal,
    CASE
        WHEN current_date BETWEEN c.datahorainicial AND c.datahorafinal THEN 'Sim'
        WHEN c.datahorainicial IS NULL AND c.datahorafinal IS NULL      THEN 'Sim'
        ELSE 'Não'
    END AS vigente
FROM cadernooferta c;
```

> Trata explicitamente o caso **vigência NULL = sem limite = vigente** — regra que vale em qualquer
> consulta a `cadernooferta`.

---

## Fatos

### `fato_venda` — granularidade **item de venda**

**Janela:** `date_trunc('day', MIN(datahorafechamento))` … `+ interval '1 day -1 second'` (no
Airflow: o dia anterior). Os 4 `?` originais são `data_inicio` (2×) e `data_fim` (2×), aplicados
tanto em `itemvenda.datahora` quanto em `venda.datahorafechamento`.

```sql
SELECT v.id                                                            AS vendaid,
       vi.id                                                           AS nk,
       CASE WHEN vi.status = 'F' THEN 'Fechado'
            WHEN vi.status = 'G' THEN 'Estornado'
            WHEN vi.status = 'C' THEN 'Cancelado'
            WHEN vi.status = 'D' THEN 'Devolvido' END                  AS status,
       COALESCE(pbm.nome, 'Venda sem Pbm')                             AS pbm,
       COALESCE(v.unidadenegocioid, 0)                                 AS unidadenegocioid,
       COALESCE(itemorcamento.usuarioid, 0)                            AS usuarioid,
       v.coo,
       v.datahorafechamento,
       to_char(v.datahorafechamento, 'DDMMYYYY')                       AS date_string,
       to_char(v.datahorafechamento, 'HH24MI')                         AS hora,
       vi.embalagemid,
       COALESCE(vi.cadernoofertaid, 0)                                 AS cadernoofertaid,
       COALESCE(v.pessoaid, 0)                                         AS pessoaid,
       CASE WHEN vi.origemdesconto = 'S' THEN 'Sem Desconto'
            WHEN vi.origemdesconto = 'D' THEN 'Caderno de Oferta Desconto'
            WHEN vi.origemdesconto = 'P' THEN 'Caderno de Oferta Preço'
            WHEN vi.origemdesconto = 'Q' THEN 'Caderno de Oferta Desconto por Qtd.'
            WHEN vi.origemdesconto = 'M' THEN 'Manual'
            WHEN vi.origemdesconto = 'B' THEN 'PBM'
            WHEN vi.origemdesconto = 'E' THEN 'Caderno de Oferta Markup sobre Custo Médio'
            WHEN vi.origemdesconto = 'R' THEN 'Caderno de Oferta Markup sobre Preço Referencial'
            WHEN vi.origemdesconto = 'C' THEN 'Caderno de Oferta Markup sobre Custo'
            WHEN vi.origemdesconto = 'L' THEN 'Caderno de Oferta Leve Pague'
            ELSE 'Origem desconhecida' END                             AS origem_desconto,
       vi.quantidade,
       CASE WHEN (vi.desconto = 0 AND vi.valordesconto > 0)
            THEN (vi.quantidade * (vi.valorunitario - vi.valordesconto))
            ELSE vi.valortotal END                                     AS valor,
       vi.valorunitario * vi.quantidade                                AS valor_bruto,
       vi.valordesconto  * vi.quantidade                               AS desconto_total,
       vi.quantidade * COALESCE(movimentacaoestoque.custo, 0)          AS custo_total,
       vi.quantidade * COALESCE(movimentacaoestoque.customedio, 0)     AS customedio_total,
       CASE WHEN e.status IS NULL THEN 'Não' ELSE 'Sim' END            AS entrega,
       CASE WHEN e.status = 'C' THEN 'Faturada'
            WHEN e.status = 'D' THEN 'Enviada'
            WHEN e.status = 'E' THEN 'Cancelada'
            WHEN e.status = 'F' THEN 'Finalizada'
            WHEN e.status = 'G' THEN 'Retornada'
            ELSE 'Não é entrega' END                                   AS status_entrega
FROM itemvenda vi
JOIN venda v                ON v.id = vi.vendaid
                           AND vi.datahora           >= $1 AND vi.datahora           <= $3
                           AND v.datahorafechamento  >= $2 AND v.datahorafechamento  <= $4
JOIN unidadenegocio         ON unidadenegocio.id = vi.unidadenegocioid
JOIN usuario                ON usuario.id = v.usuarioid
JOIN caixa                  ON caixa.id = v.caixaid
LEFT JOIN orcamento         ON orcamento.id = v.orcamentoid
LEFT JOIN entrega e         ON orcamento.id = e.orcamentoid
LEFT JOIN receitamedica     ON receitamedica.orcamentoid = orcamento.id
LEFT JOIN prescritor        ON prescritor.id = receitamedica.prescritorid
LEFT JOIN orcamentopbm      ON orcamentopbm.orcamentoid = orcamento.id
LEFT JOIN pbm               ON pbm.id = orcamentopbm.pbmid
LEFT JOIN itemorcamento     ON itemorcamento.id = vi.itemorcamentoid
JOIN movimentacaoestoque    ON movimentacaoestoque.id = vi.movimentacaoestoqueid
LEFT JOIN itemdevolucaovenda itemDevolucao ON itemDevolucao.itemvendaid = vi.id
WHERE vi.status IN ('F', 'D', 'G')
ORDER BY 1;
```

**Achados desta query que valem para qualquer análise de venda:**

1. ✅ **`usuarioid` = `itemorcamento.usuarioid`** — o DW já usava a atribuição correta de vendedor
   (ver [02-vendas.md](02-vendas.md)). ⚠️ Mas **sem fallback**: quando o item não tem orçamento, grava
   `0` (o DW resolve com uma linha "sem usuário"; num relatório isso faria o vendedor sumir).
2. ✅ **Custo vem de `movimentacaoestoque`** (`custo` e `customedio` **do momento da venda**), via
   `itemvenda.movimentacaoestoqueid` — **JOIN direto pelo id, sem varrer por data.** É a forma barata
   de obter custo histórico, ao contrário de varrer `movimentacaoestoque` por período.
3. ⚠️ **`valor` tem um ajuste condicional:** quando `desconto = 0` mas `valordesconto > 0`, o valor é
   recalculado como `quantidade × (valorunitario − valordesconto)` em vez de usar `valortotal`. Sinal
   de que há casos em que `valortotal` não reflete o desconto.
4. ✅ **Entrega ligada via `orcamento`**, confirmando que `entrega` não tem vínculo direto com `venda`.
5. ⚠️ **O mapeamento de `entrega.status` aqui CONFLITA** com o validado operacionalmente
   (`C`=Faturada/`E`=Cancelada aqui × `C`=Cancelada/`E`=Entregue lá). **Tratar como incerto.**
6. ⚠️ Inclui `status IN ('F','D','G')` — não só `'F'`. A fórmula canônica de receita usa só `'F'`.
7. ⚠️ Os `JOIN` com `unidadenegocio`, `usuario` e `caixa` são **INNER** sem usar nenhuma coluna
   deles — funcionam como filtro implícito de integridade e podem descartar linhas silenciosamente.
8. ⚠️ `receitamedica`/`prescritor`/`itemdevolucaovenda` estão no `FROM` mas **não aparecem no
   SELECT** — resíduo; podem causar fan-out se a cardinalidade não for 1:1.

**Colunas do `fato_venda` no DW:** `sk_filial`, `sk_tempo`, `sk_hora`, `sk_produto`, `sk_pessoa`,
`sk_usuario`, `sk_curvaabc`, `origem_desconto`, `vendaid`, `status`, `pbm`, `coo`, `quantidade`,
`valor`, `valor_bruto`, `desconto_total`, `custo_total`, `customedio_total`, `entrega`,
`status_entrega`.

### `fato_compras` — granularidade **item de nota fiscal**

**Janela:** `MIN(datahoraentrada)` do dia (os 2 `?` são início/fim).

```sql
SELECT inf.embalagemid,
       nf.fornecedorid,
       inf.cfop,
       nf.datahoraemissao,
       to_char(nf.datahoraemissao, 'DDMMYYYY')  AS dataemissao_string,
       to_char(nf.datahoraentrada, 'DDMMYYYY')  AS dataentrada_string,
       to_char(nf.datahoraentrada, 'HHMM')      AS hora,
       nf.unidadenegocioid,
       nf.numero                                AS nota_fiscal,
       nf.chaveacesso,
       inf.quantidade,
       inf.valorunitario                        AS valor_unitario_bruto,
       inf.desconto                             AS desconto_total,
       round(inf.desconto / inf.quantidade, 2)  AS desconto_unitario,
       inf.valorproduto                         AS total_bruto,
       inf.valortotal                           AS total_liquido,
       inf.valortotal + inf.icmsstvalor + inf.icmsstfcpvalor
         + inf.ipivalor + inf.icmsstrecolhidovalor + inf.fcpstrecolhidovalor
         - inf.rateiodesconto - inf.icmsdesoneradovalor
         + inf.rateiofrete + inf.rateioseguro + inf.rateiodespesa
         + inf.rateiotvf                        AS total_impostos,
       round((inf.valortotal / inf.quantidade) - inf.icmsstretidovalor, 2)
                                                AS valor_sem_imposto_unitario,
       round((inf.valortotal / inf.quantidade) - inf.icmsstretidovalor, 2) * inf.quantidade
                                                AS valor_sem_impoto_total
FROM itemnotafiscal inf
JOIN notafiscal nf ON inf.notafiscalid = nf.id
WHERE nf.datahoraentrada BETWEEN $1 AND $2
  AND nf.status = 'C';
```

- ✅ Confirma que o **custo real de entrada** é `itemnotafiscal.valorunitario`, e dá a fórmula
  completa de "custo com impostos".
- ⚠️ Filtra `nf.status = 'C'` (Conferida) — **exclui `'R'` (Recebida)**, que tem a mesma semântica.
  A prática operacional é filtrar por `datahoraentrada IS NOT NULL`, que cobre as duas.
- ⚠️ **Não classifica por CFOP** — o `cfop` vem como coluna, então transferência entra junto com
  compra e a separação fica para a camada de análise.

### `fato_estoque` — snapshot diário de estoque

Ver a query completa em [04-estoque.md](04-estoque.md) ("Reconstruir estoque numa data passada").
Resumo da técnica: `RANK() OVER (PARTITION BY loja, embalagem ORDER BY datahora DESC, <prioridade de
tipo> DESC, id DESC)` sobre `movimentacaoestoque` com `datahora < $1` e
`NOT naoatualizarestoque`, pegando `pos = 1`.

A janela vem de:

```sql
SELECT to_char(MIN(datahora), 'YYYY-MM-DD 23:59:59') AS inicio
FROM movimentacaoestoque
JOIN tipomovimentacaoestoque t ON t.id = tipomovimentacaoestoqueid
WHERE t.codigo IN ('RF','RTR','ETR','DVV','EVND','EEV');
```

> ✅ **`tipomovimentacaoestoque.codigo` é uma coluna mnemônica** — mais estável que o `id` numérico
> para escrever regra de negócio.
>
> **Prioridade de desempate** (quando há várias movimentações no mesmo timestamp):
> 1. entradas (`RF`, `RTR`, `ETR`, `DVV`, `EVND`, `EEV`)
> 2. `CES` (correção de estoque saída)
> 3. `CEE` (correção de estoque entrada)
> 4. saídas (`ERF`, `TRF`, `VND`, `BAIXA`, `DVC`)

### `fato_perdas` — granularidade **item de baixa de estoque**

**Janela:** `MIN(datahorainicial)` de `baixaestoque`.

```sql
SELECT unidadenegocioid,
       i.baixaestoqueid,
       i.embalagemid,
       i.quantidade,
       i.valorunitario,
       i.valortotal,
       m.descricao,
       datahora,
       to_char(datahora, 'DDMMYYYY') AS date_string,
       b.usuarioid
FROM itembaixaestoque i
JOIN baixaestoque b ON i.baixaestoqueid = b.id
JOIN motivo m       ON b.motivoid = m.id
WHERE b.status = 'F'
  AND datahora BETWEEN $1 AND $2;
```

> ✅ Traz `motivo.descricao` cru (não um id) — coerente com o achado de que **múltiplos `motivo.id`
> têm a mesma descrição**.

`fato_perda` no DW: `sk_filial`, `sk_tempo`, `sk_produto`, `sk_usuario`, `sk_curvaabc`, `quantidade`,
`valorunitario`, `valortotal`, `motivo`.

### `fato_devolucoes` — devolução de COMPRA, agregada por loja e dia

```sql
SELECT unidadeneg1_.id                                     AS codigounidadenegocio,
       to_char(devolucaoc0_.datahorafinal, 'DDMMYYYY')     AS datahora_string,
       SUM(itens3_.quantidade)                             AS quantidade,
       SUM(itens3_.valortotal)                             AS valor_tot,
       AVG(itens3_.valorunitario)                          AS valor_medio
FROM devolucaocompra devolucaoc0_
JOIN unidadenegocio unidadeneg1_    ON devolucaoc0_.unidadenegocioid = unidadeneg1_.id
JOIN usuario usuario2_              ON devolucaoc0_.usuarioid = usuario2_.id
JOIN devolucaocompraitem itens3_    ON devolucaoc0_.id = itens3_.devolucaocompraid
                                   AND itens3_.status = 'F'
JOIN embalagem embalagem4_          ON itens3_.embalagemid = embalagem4_.id
JOIN produto produto5_              ON embalagem4_.produtoid = produto5_.id
JOIN fabricante fabricante6_        ON produto5_.fabricanteid = fabricante6_.id
JOIN pessoa pessoa7_                ON fabricante6_.pessoaid = pessoa7_.id
JOIN classificacaoproduto classifica8_ ON produto5_.id = classifica8_.produtoid
JOIN classificacao classifica9_     ON classifica8_.classificacaoid = classifica9_.id
                                   AND classifica9_.principal = true
JOIN fornecedor fornecedor10_       ON devolucaoc0_.fornecedorid = fornecedor10_.id
JOIN pessoa pessoa11_               ON fornecedor10_.pessoaid = pessoa11_.id
WHERE devolucaoc0_.status = 'F'
GROUP BY unidadeneg1_.id, devolucaoc0_.datahorafinal
ORDER BY unidadeneg1_.id, devolucaoc0_.datahorafinal;
```

> Query com cara de gerada por ORM (aliases `devolucaoc0_`, `itens3_`…) — provavelmente copiada do
> log do próprio Alpha 7, o que a torna útil como **referência do join oficial do ERP**.
>
> ✅ Confirma: `devolucaocompra` **não tem valor próprio** — o valor é `SUM(devolucaocompraitem.valortotal)`
> com `status='F'`.
>
> ⚠️ Todos os joins são **INNER** — devolução de produto sem fabricante/classificação some.
> ⚠️ `classificacao.principal = true` de novo (ver a ressalva em `dim_produtos`) — pode **duplicar** a
> linha e inflar o `SUM`.

### `fato_transferencia` — granularidade **item recebido**

```sql
SELECT itemTransferencia.id,
       transferencia.unidadenegocioorigemid,
       transferencia.unidadenegociodestinoid,
       to_char(transferencia.datahorafinal, 'DDMMYYYY') AS datefinal_string,
       transferencia.datahorafinal,
       to_char(transferencia.datahora,      'DDMMYYYY') AS datehora_string,
       transferencia.datahora,
       itemTransferencia.embalagemid,
       itemTransferencia.quantidade,
       itemTransferencia.valorunitario,
       itemTransferencia.valortotal,
       itemTransferencia.status
FROM recebimentotransferencia
JOIN transferencia
  ON transferencia.id = recebimentotransferencia.transferenciaid
JOIN itemrecebimentotransferencia
  ON itemrecebimentotransferencia.recebimentotransferenciaid = recebimentotransferencia.id
LEFT JOIN itemtransferencia
  ON itemtransferencia.transferenciaid = transferencia.id
 AND itemtransferencia.embalagemid     = itemrecebimentotransferencia.embalagemid
JOIN (
    SELECT DISTINCT itemtransferencia.id AS iditemtransferencia
    FROM transferencia
    LEFT JOIN recebimentotransferencia
           ON transferencia.id = recebimentotransferencia.transferenciaid
          AND recebimentotransferencia.status = 'F'
    LEFT JOIN itemtransferencia
           ON itemtransferencia.transferenciaid = transferencia.id
    LEFT JOIN estornoitemtransferencia
           ON estornoitemtransferencia.itemtransferenciaid = itemtransferencia.id
    WHERE itemtransferencia.status IN ('E', 'R', 'S')
      AND transferencia.status IN ('R')
) AS filtros ON filtros.iditemtransferencia = itemtransferencia.id
JOIN (
    SELECT DISTINCT embalagem.id AS idembalagem
    FROM embalagem
    JOIN produto              ON embalagem.produtoid = produto.id
    JOIN fabricante           ON fabricante.id = produto.fabricanteid
    JOIN classificacaoproduto ON classificacaoproduto.produtoid = produto.id
    JOIN classificacao        ON classificacao.id = classificacaoproduto.classificacaoid
) AS embalagemFiltros ON embalagemFiltros.idembalagem = itemrecebimentotransferencia.embalagemid
JOIN unidadenegocio unidadeNegocioOrigem
  ON unidadeNegocioOrigem.id = transferencia.unidadenegocioorigemid
JOIN unidadenegocio unidadeNegocioDestino
  ON unidadeNegocioDestino.id = transferencia.unidadenegociodestinoid
JOIN usuario           ON usuario.id = recebimentotransferencia.usuarioid
JOIN embalagem         ON embalagem.id = itemrecebimentotransferencia.embalagemid
JOIN produto           ON produto.id = embalagem.produtoid
JOIN fabricante        ON fabricante.id = produto.fabricanteid
JOIN pessoa fabricantePessoa ON fabricantePessoa.id = fabricante.pessoaid
JOIN classificacaoproduto    ON classificacaoproduto.produtoid = produto.id
JOIN classificacao           ON classificacao.id = classificacaoproduto.classificacaoid
JOIN movimentacaoestoque
  ON movimentacaoestoque.id = itemrecebimentotransferencia.movimentacaoestoqueid
WHERE classificacao.principal = true
  AND itemrecebimentotransferencia.status = 'F';
```

> Também tem cara de query nativa do ERP. Achados úteis:
>
> - ✅ Confirma que **`itemrecebimentotransferencia.movimentacaoestoqueid`** existe — o item recebido
>   aponta para a movimentação de estoque correspondente.
> - ✅ `itemtransferencia.status IN ('E','R','S')` e `transferencia.status = 'R'` são os filtros que o
>   próprio ERP usa para "transferência recebida" (⚠️ estes valores **não estão decodificados** em
>   nenhuma outra fonte — usar com cautela).
> - ✅ Existe `estornoitemtransferencia` (estorno por item de transferência).
> - ⚠️ O join `itemtransferencia` é por `(transferenciaid, embalagemid)` — não há FK direta do item
>   recebido para o item enviado.

### `fato_recebimento_crediario`

**Janela:** `MIN(datahora)` de `recebimentocrediario`.

```sql
SELECT r.unidadenegocioid,
       r.usuarioid,
       cr.pessoaid,
       to_char(r.datahora,        'DDMMYYYY') AS data_recebimento_string,
       to_char(r.datahora,        'HHMM')     AS hora_recebimento,
       to_char(cr.datavencimento, 'DDMMYYYY') AS data_vencimento_string,
       irc.valorrecebimento                   AS valor_recebimento,
       irc.valorjuros                         AS valor_juros,
       irc.valormulta                         AS valor_multa,
       irc.valortaxaconvenio                  AS valor_taxa_convenio
FROM itemrecebimentocrediario irc
JOIN recebimentocrediario r ON irc.recebimentocrediarioid = r.id
JOIN crediarioreceber cr    ON irc.crediarioreceberid = cr.id
LEFT JOIN fatura f          ON cr.faturaorigemid = f.id
WHERE irc.status = 'A'
  AND r.datahora >= $1
  AND r.datahora <= $2;
```

> ✅ Detalha a decomposição do recebimento: **principal + juros + multa + taxa de convênio**.
> ⚠️ `irc.status = 'A'` aqui parece significar "ativo/válido" (o item do recebimento), não "aberto".

### `fato_recebimento_cartao`

```sql
SELECT recebimentoCartao.datahora                        AS datarecebimento,
       to_char(recebimentoCartao.datahora, 'DDMMYYYY')   AS data_string,
       unidadeNegocio.id                                 AS codigounidadenegocio,
       itemRecebimentoCartao.valorrecebimento            AS valorrecebimento
FROM itemrecebimentocartao itemRecebimentoCartao
JOIN recebimentocartao recebimentoCartao
  ON recebimentoCartao.id = itemRecebimentoCartao.recebimentocartaoid
LEFT JOIN cartaoreceber
  ON cartaoreceber.id = itemRecebimentoCartao.cartaoreceberid
LEFT JOIN pessoa pessoaDevedora   ON pessoaDevedora.id = cartaoreceber.pessoaid
LEFT JOIN modalidadecartao        ON modalidadecartao.id = cartaoreceber.modalidadecartaoid
LEFT JOIN unidadenegocio unidadeNegocio
  ON unidadeNegocio.id = cartaoreceber.unidadenegocioid
JOIN usuario ON usuario.id = recebimentoCartao.usuarioid
LEFT JOIN conciliacaocartaoitem itemConciliacaoCartao
  ON itemConciliacaoCartao.id = itemRecebimentoCartao.conciliacaocartaoitemorigemid
LEFT JOIN conciliacaocartao
  ON conciliacaocartao.id = itemConciliacaoCartao.conciliacaocartaoid
LEFT JOIN conciliacaocartaoconfiguracao
  ON conciliacaocartaoconfiguracao.codigoestabelecimento = itemConciliacaoCartao.codigoestabelecimento
LEFT JOIN unidadenegocio unidadeNegocioConciliacao
  ON (unidadeNegocioConciliacao.id   = conciliacaocartaoconfiguracao.unidadenegocioid
   OR unidadeNegocioConciliacao.cnpj = itemConciliacaoCartao.codigoestabelecimento)
WHERE itemRecebimentoCartao.status = 'A';
```

> ✅ Mapa completo da cadeia de conciliação de cartão, incluindo o detalhe de que a loja pode ser
> resolvida por **duas vias** (`conciliacaocartaoconfiguracao.unidadenegocioid` **ou**
> `unidadenegocio.cnpj = codigoestabelecimento`).
> ⚠️ Muitos joins não contribuem com colunas do SELECT — resíduo de uma versão mais rica.

### `fato_rupturas`

Fórmula de ruptura **do DW** — ⚠️ **diferente da métrica canônica validada com o gestor**
(ver [04-estoque.md](04-estoque.md)). Útil como comparação.

```sql
WITH vendas_temporaria AS (
  SELECT hv.unidadenegocioid,
         hv.embalagemid,
         SUM(hv.quantidade)        AS quantidade,
         SUM(hv.quantidade) / 90.0 AS demanda,
         MAX(hv.data)              AS ultima_venda
  FROM historicovenda hv
  WHERE hv.data > (CURRENT_DATE - INTERVAL '90 days')
  GROUP BY hv.unidadenegocioid, hv.embalagemid
)
SELECT e.unidadenegocioid,
       to_char(current_date, 'DDMMYYYY') AS data_string,
       current_date                      AS data,
       p.id,
       e.embalagemid,
       p.descricao,
       emb.codigobarras,
       p.status,
       e.estoque,
       v.quantidade,
       v.demanda,
       m.ultima_mov_ts                   AS ultima_venda,
       FLOOR(EXTRACT(EPOCH FROM (CURRENT_DATE::timestamp - (m.ultima_mov_ts::date)::timestamp)) / 86400)::int
         AS dias_sem_estoque,
       CEIL((EXTRACT(EPOCH FROM (CURRENT_DATE::timestamp - (m.ultima_mov_ts::date)::timestamp)) / 86400.0) * v.demanda)
         AS vendas_perdidas,
       emb.precoreferencial
         * CEIL((EXTRACT(EPOCH FROM (CURRENT_DATE::timestamp - m.ultima_mov_ts)) / 86400.0) * v.demanda)
         AS valor_perdido
FROM estoque e
JOIN vendas_temporaria v
  ON v.unidadenegocioid = e.unidadenegocioid
 AND v.embalagemid      = e.embalagemid
JOIN embalagem emb ON emb.id = e.embalagemid
JOIN produto   p   ON p.id   = emb.produtoid
-- pega a última movimentação por índice, sem agregação cara
JOIN LATERAL (
  SELECT me.datahora AS ultima_mov_ts
  FROM movimentacaoestoque me
  WHERE me.unidadenegocioid = e.unidadenegocioid
    AND me.embalagemid      = e.embalagemid
  ORDER BY me.datahora DESC
  LIMIT 1
) m ON TRUE
WHERE e.estoque = 0
  AND v.demanda > 0
  AND p.status  = 'A'
  AND NOT EXISTS (
    SELECT 1 FROM suspendecompraprodutounidadenegocio s
    WHERE s.unidadenegocioid = e.unidadenegocioid
      AND emb.produtoid      = s.produtoid
  );
```

**Descobertas importantes desta query:**

- ✅✅ **Existe uma tabela `historicovenda`** (`unidadenegocioid`, `embalagemid`, `quantidade`,
  `data`) — **agregado de venda pré-computado pelo próprio ERP**. Não é citada em nenhuma outra
  fonte, mas é potencialmente **muito mais barata** que varrer `venda + itemvenda` para demanda
  histórica. ⚠️ **Vale investigar cobertura e granularidade antes de confiar.**
- ✅ O `JOIN LATERAL ... ORDER BY datahora DESC LIMIT 1` usa o índice
  `(embalagemid, unidadenegocioid)` de `movimentacaoestoque` — é o jeito barato de pegar a última
  movimentação de um par específico (diferente de varrer por data, que não tem índice).
- ✅ Já aplica a exclusão por `suspendecompraprodutounidadenegocio` (qualquer origem).

**Diferenças em relação à métrica canônica:**

| Aspecto | DW | Canônico |
| --- | --- | --- |
| Janela de demanda | **90 dias** | **60 dias** |
| Granularidade | **embalagem** | **produto** (`SUM(estoque)` agregado) |
| Condição de estoque | `estoque = 0` | `SUM(estoque) <= 0` (inclui negativo) |
| Fonte de demanda | `historicovenda` | `venda` + `itemvenda` |
| Filtro de tipo | só `p.status='A'` | também `p.tipo='M'` |
| Preço da venda perdida | `precoreferencial` | preço médio unitário praticado |

### `fato_dre`

```sql
SELECT id,
       data,
       to_char(data, 'DDMMYYYY') AS date_string,
       unidadenegocioid,
       categoria,
       nivel1,
       nivel2,
       nivel3,
       valor
FROM dre
WHERE valor <> 0;
```

> Cópia direta da tabela pré-computada, só descartando linhas zeradas.

### `lancamento_financeiro`

```sql
SELECT CASE tipo WHEN 'S' THEN 'Saida'
                 WHEN 'E' THEN 'Entrada'
                 ELSE 'Outros' END                       AS tipo,
       to_char(l.datahora,        'DDMMYYYY')            AS datahora_string,
       l.datahora,
       to_char(l.datahorainclusao,'DDMMYYYY')            AS datahora_inclusao_string,
       l.datahorainclusao,
       l.unidadenegocioid,
       l.valor,
       l.planocontasid,
       l.descricao,
       l.contacorrenteid
FROM lancamentofinanceiro l;
```

> ⚠️ Sem filtro de período — carga full.

---

## O que o DW NÃO cobre

Áreas do Alpha 7 sem fato/dimensão neste DW (e que, portanto, não têm query-fonte de referência
aqui):

- **Contas a pagar / a receber** (`contapagar`, `crediarioreceber` em aberto, `cartaoreceber`) — só
  os *recebimentos* de cartão e crediário viraram fato, não a carteira.
- **Pedido de compra** (`pedidocompra`) e o vínculo formal com recebimento físico.
- **Pedido de transferência** (`pedidotransferencia`) — só a execução (`transferencia`) virou fato.
- **Entrega / remessa** — `entrega` aparece só como atributo do `fato_venda`.
- **Receita médica / prescritor** — presente no `FROM` do `fato_venda`, mas não no SELECT.
- **Ofertas** — existe `dim_cadernooferta`, mas nenhum fato de "item em oferta"
  (`itemcadernooferta`) nem de alteração de preço (`alteracaopreco`).
- **Tesouraria** (`quebracaixa`, `sessaocaixa`, `depositosangria`, `extratobancario`).
- **Baixa/estorno de recebimento físico** (`recebimentofisico`, `estornoitemrecebimentofisico`).
- **Devolução de VENDA** (`devolucaovenda`) — só a devolução de compra virou fato.

## Achados de modelagem reaproveitáveis

Independentemente de usar o DW, estas decisões valem para qualquer extração do Alpha 7:

1. **A granularidade natural de tudo é `embalagem`** — a dimensão de produto do DW usa
   `embalagem.id` como chave natural, não `produto.id`.
2. **Custo histórico sai barato via `itemvenda.movimentacaoestoqueid`** — JOIN direto pelo id, sem
   varrer `movimentacaoestoque` por data (que é Seq Scan de 32 mi de linhas).
3. **`tipomovimentacaoestoque.codigo`** (`RF`, `VND`, `DVV`…) é mais estável e legível que o `id`
   numérico para escrever regra de negócio.
4. **`historicovenda`** existe e pode substituir varreduras de `venda + itemvenda` para demanda
   histórica — ⚠️ **investigar cobertura antes de confiar**.
5. **Vigência NULL de caderno de oferta = vigente** (sem limite) — tratar explicitamente.
6. **Reconstrução de estoque numa data passada** exige desempate por prioridade de tipo de
   movimentação, não só por `datahora` + `id`.
7. **A loja de uma conciliação de cartão pode vir por duas vias** (configuração ou CNPJ).
8. ⚠️ **`classificacao.principal = true` NÃO garante uma linha por produto** — as queries do DW que o
   usam como único filtro podem duplicar linha e inflar somas.
9. ⚠️ **Joins INNER "decorativos"** (tabelas no `FROM` que não contribuem com nenhuma coluna do
   SELECT) aparecem em várias queries herdadas do ERP — são filtros implícitos de integridade que
   podem descartar linhas em silêncio. Ao reaproveitar uma dessas queries, revisar cada join.
