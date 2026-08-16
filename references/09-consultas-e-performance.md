# Consultas, joins canônicos e performance

## Sumário

- [Conexão ao banco](#conexão-ao-banco)
- [Particularidades do PostgreSQL nessa base](#particularidades-do-postgresql-nessa-base)
- [Joins canônicos](#joins-canônicos)
- [Filtros canônicos](#filtros-canônicos)
- [Índices existentes e ausentes](#índices-existentes-e-ausentes)
- [Regras de performance](#regras-de-performance)
- [Regras de cálculo](#regras-de-cálculo)
- [Serialização de BigInt e cast `::text`](#serialização-de-bigint-e-cast-text)
- [PostgreSQL vs MariaDB](#postgresql-vs-mariadb)

---

## Conexão ao banco

### Padrão observado

- Pool de conexões `pg` com **5 conexões** — é o gargalo real de qualquer `Promise.all` de queries
  pesadas.
- **Pool cacheado por processo** e mantido vivo entre hot reloads → mudar variável de ambiente exige
  **reiniciar o processo**; o pool antigo continua com a config antiga em memória.
- Query parametrizada por template literal (`$1`, `$2`…) é o padrão; interpolação de texto SQL cru
  (para reaproveitar uma CTE, ORDER BY dinâmico, ou gerar N placeholders) exige a variante "unsafe"
  — **os valores continuam parametrizados**, então não há risco de injection desde que nada de
  entrada de usuário seja concatenado.

⚠️ **Um wrapper de tagged template transforma TODO `${...}` em parâmetro posicional** — não dá para
interpolar um trecho de SQL cru (ex.: uma CTE compartilhada) como se fosse string: ele vira um
parâmetro de valor, não texto de query, e o SQL quebra. CTE compartilhada entre duas queries
precisa ou ser escrita por extenso nas duas, ou usar a variante que aceita string + params.

⚠️ Quando a CTE compartilhada é reaproveitada em queries com número **diferente** de parâmetros
antes dela, transformar a CTE numa **função que recebe os índices de parâmetro**
(`produtoCompradorCTE(idxCat, idxSub, ...)`) em vez de uma string fixa — evita reescrever a CTE
inteira só para mudar `$5` → `$1`.

### Túnel SSH (ambiente de desenvolvimento)

O padrão observado é um **túnel SSH** de uma porta local para o Postgres do ERP, através de um
gateway:

```text
localhost:<PORTA_LOCAL>  →  ssh <USUARIO>@<GATEWAY>  →  <HOST_PG_ERP>:5432
```

> Todos os hosts/IPs/usuários/portas reais foram substituídos por placeholders.

Opções de `ssh` que valem a pena replicar:

| Opção | Por quê |
| --- | --- |
| `ServerAliveInterval=30 ServerAliveCountMax=3` | detecta conexão derrubada e encerra |
| `ExitOnForwardFailure=yes` | se o forward não subir, falha rápido em vez de ficar "meio vivo" |
| `StrictHostKeyChecking=accept-new` | aceita o fingerprint **só** no primeiro acesso (recusa se mudar depois — protege contra MITM) |
| `BatchMode=yes` | desabilita TODOS os prompts; **essencial** para rodar em background sem TTY |

Em produção, normalmente não há túnel: a string de conexão aponta direto para o host do ERP.

### Troubleshooting da conexão

| Sintoma | Causa-raiz | O que fazer |
| --- | --- | --- |
| `ECONNREFUSED localhost:<porta>` | Túnel não está rodando | subir o túnel manualmente e ler o erro |
| `Connection terminated due to connection timeout` (~10 s) | Forward chega no SSH server mas o **alvo** está down / IP mudou / firewall bloqueia | testar a partir do gateway: `ping` + `(echo > /dev/tcp/<HOST>/<PORTA>)` |
| `timeout expired` **mesmo com o túnel ativo** | O gateway **não tem rota** para o host do ERP (host novo, rota antiga) | não é resolvível por config da aplicação — precisa de ajuste de rede |
| ssh fica `S (sleeping)`, porta nunca abre | Prompt de fingerprint travando em background (sem TTY) | `StrictHostKeyChecking=accept-new` + `BatchMode=yes` |
| Pool continua com config velha | Pool cacheado no processo | reiniciar o processo |
| `no pg_hba.conf entry for host "<IP>", user "<USUARIO>", database "<BANCO>", no encryption` | O Postgres **rejeita na autenticação**, depois do handshake TCP | **só o administrador do Alpha 7 resolve**: liberar o host em `pg_hba.conf` (e possivelmente exigir `hostssl`) |

⚠️ **`no pg_hba.conf entry` NÃO é "VPN desligada".** O teste de TCP (`Test-NetConnection <HOST> -Port 5432`)
retorna sucesso — a rejeição acontece **depois** do handshake, na camada de autenticação do Postgres.
Confirmado reproduzindo o erro idêntico com um cliente `pg` cru, fora de qualquer framework.

⚠️ **Trocar o nome do banco não contorna isso** — a regra de `pg_hba.conf` é por **host + usuário**,
não por banco. Trocar o nome é necessário quando o Alpha 7 rotaciona o banco corrente, mas nunca foi
a causa da rejeição.

### Diagnóstico passo a passo

Quando uma query trava em ~10 s, **não chutar** que é cache ou query lenta. Nesta ordem:

1. **Porta local aberta?** `ss -tln | grep :<PORTA>` (ou `(echo > /dev/tcp/localhost/<PORTA>)`)
2. **Processo ssh vivo?** `pgrep -af "ssh.*-L <PORTA>"`
3. **Destino alcançável do lado do gateway?**
   `ssh <USUARIO>@<GATEWAY> 'ping -c 2 <HOST_PG>; (echo > /dev/tcp/<HOST_PG>/5432) && echo OK || echo FAIL'`
4. **PG aceita auth?** conectar com um cliente `pg` cru usando as credenciais reais.
5. **Só DEPOIS** investigar query/pool/framework.

## Particularidades do PostgreSQL nessa base

- **Função `normalize_str(texto)`** existe no banco (remove acento + normaliza caixa), com índices
  funcionais construídos sobre ela. É a base de toda busca textual rápida.
- ⚠️⚠️ **A sessão do Postgres roda em `America/Sao_Paulo` (UTC-3)**, uma hora à frente do fuso real da
  operação (`America/Cuiaba`, UTC-4). Entre 23h e 00h local, `CURRENT_DATE` do banco **já virou o
  dia**, e um cálculo de "dias desde a última compra" sai inflado em 1 dia para a base inteira.

  ```sql
  -- ERRADO
  CURRENT_DATE
  -- CERTO
  (NOW() AT TIME ZONE 'America/Cuiaba')::date
  ```

  O mesmo vale na camada de aplicação: `new Date()` num servidor sem `TZ` definido é UTC, e a partir
  de ~20h em UTC-4 o "hoje" do servidor já virou o dia seguinte — inflando "dias decorridos" em
  projeções de run-rate. Usar sempre uma função explícita de "hoje no fuso da operação".

- **`ILIKE`** para busca case-insensitive (o `LIKE` do Postgres é case-sensitive, ao contrário do
  MariaDB).
- **`FILTER (WHERE ...)`** em agregados é largamente usado para múltiplos totais numa passada só.
- **`COUNT(*) OVER ()` / `SUM(...) OVER ()` ANTES do `LIMIT`** para saber o universo real quando a
  lista é truncada — sem isso, um cabeçalho que anuncia contagem mostra o número da página, não o do
  universo. Bug real: "100 médicos pararam de prescrever" tanto na rede (2.301) quanto numa filial
  (718).
- **`json_build_object` + subselects sobre as mesmas CTEs** para devolver vários blocos numa linha só
  — evita repetir a varredura de `venda` N vezes e brigar pelo pool de 5 conexões.
- **`unnest($1::text[], $2::text[], $3::numeric[])`** para injetar uma tabela virtual (vinda de um
  cadastro externo) dentro de uma query do ERP, mantendo o filtro rodando no Postgres.
- **`cardinality($1::text[]) = 0 OR col = ANY($1::text[])`** — padrão para filtro opcional
  (sem seleção = não filtra), retrocompatível.
- **`$1::bigint[] IS NULL OR col = ANY($1::bigint[])`** — mesma ideia para filtros nullable.
- ⚠️ **`NULL = ANY(...)` é NULL, não FALSE** — uma exclusão por lista some com todo registro órfão em
  silêncio. Escrever `col IS NULL OR NOT (col = ANY($1))`.
- ⚠️ **`NULL NOT ILIKE '...'` é NULL, não TRUE** — todo filtro `NOT ILIKE`/`NOT LIKE` sobre coluna
  nullable precisa de `COALESCE(col, '')`.

## Joins canônicos

```sql
-- item de venda → produto (SEMPRE via embalagem)
JOIN embalagem e ON e.id = iv.embalagemid
JOIN produto   p ON p.id = e.produtoid

-- nome do cliente
JOIN pessoa pes ON pes.id = v.pessoaid

-- nome do fabricante
JOIN fabricante fab ON fab.id = p.fabricanteid
JOIN pessoa    pfab ON pfab.id = fab.pessoaid

-- nome do usuário/colaborador
JOIN usuario u  ON u.id = <coluna>.usuarioid
JOIN pessoa  pu ON pu.id = u.pessoaid

-- custo do produto na loja
LEFT JOIN custoproduto cp
       ON cp.produtoid = e.produtoid AND cp.unidadenegocioid = v.unidadenegocioid

-- estoque atual da embalagem na loja
LEFT JOIN estoque est
       ON est.embalagemid = e.id AND est.unidadenegocioid = un.id

-- preço com override por loja
LEFT JOIN precoembalagemunidadenegocio pun
       ON pun.embalagemid = e.id AND pun.unidadenegocioid = un.id
-- usar COALESCE(pun.precovenda, e.precovenda)

-- categoria macro do produto (1 linha por produto)
JOIN classificacaoproduto clp ON clp.produtoid = p.id
JOIN classificacao        cl  ON cl.id = clp.classificacaoid
WHERE cl.caminho ILIKE 'PRINCIPAL > %'
-- categoria = split_part(cl.caminho, ' > ', 2), com MIN(...) GROUP BY produtoid

-- vendedor de verdade (pré-computado, nunca correlacionado)
LEFT JOIN orcamento_usuario ou ON ou.venda_id = v.id
-- COALESCE(ou.usuario_id, v.usuarioid)

-- farmacêutico (DISTINCT obrigatório)
LEFT JOIN (SELECT DISTINCT usuarioid FROM farmaceutico WHERE status='A') f
       ON f.usuarioid = u.id
```

## Filtros canônicos

| Objetivo | Filtro |
| --- | --- |
| Venda válida | `v.status = 'F'` |
| Item de venda válido | `iv.status = 'F'` |
| Produto ativo | `p.status = 'A'` |
| Produto = mercadoria (exclui serviço/taxa) | `p.tipo = 'M'` |
| Loja ativa | `un.status = 'A'` |
| Excluir escritório | `un.codigo <> 'ESC'` (ou `un.id <> 1`) |
| Excluir CDs e não-lojas | `un.codigo NOT ILIKE 'CD%' AND un.codigo NOT IN ('ESC','SINC','CLOUD', <códigos de loja fora do grupo>)` — os códigos de sistema são convenção do ERP; a lista de lojas a excluir é cadastro do cliente (ver [08-logistica-entregas.md](08-logistica-entregas.md)) |
| NF pendente de recebimento | `nf.status = 'I'` (**nunca** `IN ('I','A')`) |
| NF recebida | `nf.datahoraentrada IS NOT NULL` |
| Conta a pagar em aberto | `cp.status = 'A'` |
| Conta a pagar paga (caixa) | `cp.status='B'` + `pgtocontapagar.datahora` no período |
| Crediário em aberto | `cr.status = 'A'` |
| Pedido de transferência pendente | `pt.status = 'A'` |
| Pedido de compra válido | `pc.status <> 'D'` |
| Cliente identificado | `v.pessoaid IS NOT NULL` |
| Excluir PJ de ranking de consumidor | `COALESCE(pe.tipo,'F') <> 'J'` |
| Contar cupons | `COUNT(*)` em `venda` (subquery separada) |

## Índices existentes e ausentes

### Existentes (confirmados)

| Índice | Tabela | Definição |
| --- | --- | --- |
| `cidx_pessoa_nome` | `pessoa` | `btree(normalize_str(nome) varchar_pattern_ops)` |
| `idx_pessoa_nome` | `pessoa` | índice ordenado por nome (⚠️ atrai o planner e degrada busca por prefixo) |
| `cidx_pessoa_cpf` | `pessoa` | por CPF |
| `cidx_embalagem_descricao` | `embalagem` | sobre `normalize_str(descricao)` |
| — | `movimentacaoestoque` | `embalagemid + unidadenegocioid`; `id`; `id + custo + customedio` |
| — | `venda` | `datahorafechamento` (usado pelas CTEs de período) |

### ⚠️ Ausências que definem a arquitetura das queries

| Ausência | Consequência |
| --- | --- |
| **`movimentacaoestoque.datahora` sem índice** (32,2 mi linhas) | Qualquer filtro de período = Seq Scan da tabela inteira (~54 s). Filtrar um mês só **não ajuda**. Exige snapshot/cache |
| **`orcamento.vendaid` sem índice** (3,9 mi linhas) | `EXISTS` correlacionado por linha de `venda` faz varredura sequencial de `orcamento` **por cada linha avaliada** — uma query real levou **~14 minutos** |
| **`itemvenda.cadernoofertaid` sem índice** | Filtrar `itemvenda` direto por caderno custa 13,3 s. Começar pela `itemcadernooferta` e casar por `embalagemid` → ~8,5 s |

Como o ERP é somente leitura, **não é possível criar índice**. Rodar `EXPLAIN` sempre que uma query
parecer lenta sem explicação óbvia.

## Regras de performance

### 1. Pré-agregar, nunca correlacionar por linha

⚠️ **Nunca `EXISTS`/subquery correlacionado contra tabela grande sem índice.** Pré-computar o
conjunto uma única vez numa CTE e fazer `LEFT JOIN`.

Ganhos medidos:

| Caso | Antes | Depois |
| --- | --- | --- |
| "essa venda tem entrega?" via `EXISTS` sobre `orcamento` | ~14 min | segundos (CTE `entrega_vendas`) |
| Valor de itens prescritos via `EXISTS` correlacionado | 50,6 s | **9,7 s** com `JOIN` + `DISTINCT` |
| "primeiro/último valor relacionado" via `LEFT JOIN LATERAL` por linha de `transferencia` | 18–20 s | **7–8 s** com CTEs pré-agregadas (`GROUP BY` / `DISTINCT ON`) e `LEFT JOIN` |

**Regra:** quando precisar do "primeiro/último valor relacionado" por linha de uma tabela grande,
pré-agregar a tabela relacionada **inteira** numa CTE (`GROUP BY` / `DISTINCT ON`) e fazer
`LEFT JOIN` — **mesmo que a CTE agregada não tenha filtro de período**. O hash join em lote vence a
subquery correlacionada.

⚠️ **Exceção:** `LATERAL` por linha é barato quando a população é pequena (ex.: backlog de ~750
pedidos de transferência). O aviso vale para tabelas grandes como `venda`/`itemvenda`.

### 2. Uma query ou várias? Depende das CTEs

| Situação | Decisão | Evidência |
| --- | --- | --- |
| Duas queries reaproveitam a **MESMA** CTE pesada | **Juntar numa só** e derivar o resto na aplicação | `Promise.all` com a CTE duplicada gerou contenção real (~18–20 s cada, disputando as mesmas tabelas grandes); uma execução só → ~7 s |
| Duas queries tocam CTEs pesadas **DIFERENTES** | **Manter separadas e paralelizar** | Juntar tudo numa query só testou **~22 s**; separadas em `Promise.all`, **~12 s** — o planner não ganha nada por juntar conjuntos de tabelas distintos |
| Várias CTEs escalares (1 linha cada) | `FROM cte1, cte2, cte3` (`CROSS JOIN` implícito) numa query só | ~4 s em regime normal, evita contenção |

### 3. Só reconstruir o coorte quando a métrica depende dele

Medido (12 meses, rede toda): "20 itens mais vendidos" **com** coorte 65 s / 23 s **vs. 11 s / 9 s**
filtrando a demografia direto no join `venda → pessoa` — resultado **idêntico linha a linha**.
Agrupar por `embalagem.produtoid` (resolvendo `produto.descricao` só nas 20 linhas do topo) vale
outros ~15 s.

### 4. Filtro DENTRO da CTE, antes do `LIMIT`

Filtro aplicado depois do corte por top-N esconde categorias/lojas de baixo volume. E as **contagens
do resumo** precisam do mesmo filtro, não só a tabela.

### 5. Opções de filtro vêm de fonte independente

Nunca derivar as opções de um `<select>` das linhas já carregadas/limitadas — categorias, lojas e
cadernos de baixo volume somem do próprio filtro sem ninguém perceber. Exceção aceitável: quando o
universo relevante **é** exatamente o que já foi buscado no período (e isso está documentado).

### 6. Cache/snapshot para o que é caro e não muda no dia

Métricas que dependem de `movimentacaoestoque` por período, ou que cruzam `itempedidocompra` com
`itemvenda`/`estoque`, precisam de **snapshot diário** por chave (ano/filiais/etc.).

⚠️ **Ao mudar a fórmula por trás de um snapshot, é obrigatório invalidar/bumpar a chave** — senão o
valor antigo continua sendo servido até a virada do dia.

### 7. Nunca escanear tabela grande sem filtro de data quando só a EXISTÊNCIA recente importa

O filtro de janela entra **dentro** da CTE, não depois.

### 8. Volumes/tempos de referência

| Consulta | Tempo típico |
| --- | --- |
| Dashboard consolidado (7 CTEs cruzadas) | ~4 s |
| Query de precificação por loja | 6–12 s (pool aquecido) · até ~27 s a frio |
| Sugestão de oferta (CTE única, ~20 mil candidatos) | ~7 s (melhor caso) · 18–25 s sob concorrência |
| RFV rede inteira (185 mil clientes) | ~7 s aquecido · ~25 s a frio |
| Elasticidade (66 cadernos, 20 mil linhas, 14 dias) | ~7,5 s |
| Demanda reprimida (cacheada) | ~29 s |
| CMV real por `movimentacaoestoque` | **~45–54 s** (irredutível) |

## Regras de cálculo

Estas regras foram violadas e corrigidas várias vezes; valem para qualquer métrica:

1. **A rota/SQL devolve COMPONENTES CRUS; a razão é calculada depois.** Nunca `AVG(percentual)`,
   nunca razão pronta no SQL.
2. **Somar os componentes ANTES de dividir.** Ticket médio = Σcaptado ÷ Σcupons, jamais média dos
   tickets individuais. Vale para margem, elasticidade, ruptura, leadtime, CMV.
3. **KPI de rede é PONDERADO**, nunca média aritmética dos percentuais das lojas.
4. **"Sem dado" ≠ zero.** Mostrar "—" quando não há base (cliente sem venda no período, fabricante
   sem contas a pagar, NPS sem resposta). Zero costuma ser um valor ruim de verdade — confundir os
   dois é o erro clássico.
5. **`COUNT(*) OVER ()` antes do `LIMIT`** sempre que o cabeçalho anuncia uma contagem.
6. **Ordenar pela expressão numérica**, nunca pelo alias `::text`.
7. **Reconciliar sempre que reagrupar.** Se duas visões partem do mesmo universo, o total tem que
   bater ao centavo — e é bom ter um alerta permanente para o caso de divergirem.
8. **Nunca mudar um número financeiro em silêncio.** Toda exclusão (previsão, contas internas,
   unidades) tem que estar escrita onde o número aparece.

## Serialização de BigInt e cast `::text`

O ERP retorna `bigint` para todos os IDs. Duas soluções complementares:

**1. Cast `::text` no SELECT** — a mais prática quando há muitas colunas numéricas:

```sql
SELECT un.id::text AS loja_id,
       COALESCE(v.receita, 0)::text AS receita
```

O cliente converte com `parseFloat`. ⚠️ **Mas então NUNCA ordenar pelo alias** — `ORDER BY receita`
ordena lexicograficamente ("10" antes de "2900"). Ordenar pela expressão numérica original.

**2. Replacer na serialização JSON:**

```js
JSON.parse(JSON.stringify(rows, (_key, v) => (typeof v === "bigint" ? v.toString() : v)))
```

⚠️ O replacer recebe `(key, value)`, **não** `(value)` — escrever `(v) => typeof v === 'bigint' ...`
está errado.

⚠️ Ao guardar um id do ERP num banco externo, guardar **como TEXTO** — bigint não cabe no `Int` de
muitos ORMs.

## PostgreSQL vs MariaDB

Tabela de tradução, útil ao portar SQL de um ERP anterior:

| Conceito | MariaDB | PostgreSQL (Alpha 7) |
| --- | --- | --- |
| String case-insensitive | `LIKE` (já é CI) | **`ILIKE`** |
| Cast de tipo | `CAST(x AS SIGNED)` | `x::bigint` ou `CAST(x AS bigint)` |
| Timestamp literal | `'2026-01-01 00:00:00'` | `'2026-01-01T00:00:00'::timestamp` |
| Concatenar | `CONCAT(a, b)` | `a \|\| b` |
| Boolean | `'S'`/`'N'` ou `1`/`0` | `true`/`false` nativo |
| LIMIT + OFFSET | `LIMIT 10, 20` | `LIMIT 20 OFFSET 10` |
| Upsert | `INSERT ... ON DUPLICATE KEY UPDATE` | `INSERT ... ON CONFLICT DO UPDATE` |

⚠️ Diferença estrutural para lembrar: **no Alpha 7 o custo fica em tabela separada
(`custoproduto`)**, não direto na linha de movimento como em ERPs mais antigos.
