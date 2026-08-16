# Financeiro: contas a pagar/receber, DRE, plano de contas e tesouraria

## Sumário

- [`contapagar` — contas a pagar](#contapagar--contas-a-pagar)
- [`cancelamentocontapagar`](#cancelamentocontapagar)
- [Contas a receber — as 4 correntes](#contas-a-receber--as-4-correntes)
- [Crediário e convênio](#crediário-e-convênio)
- [Cartão e conciliação de cartão](#cartão-e-conciliação-de-cartão)
- [`planocontas`](#planocontas)
- [`lancamentofinanceiro` e `contacorrente`](#lancamentofinanceiro-e-contacorrente)
- [`dre` — DRE pré-computado](#dre--dre-pré-computado)
- [Tesouraria, caixa e conciliação bancária](#tesouraria-caixa-e-conciliação-bancária)
- [Indicadores de balanço derivados](#indicadores-de-balanço-derivados)

---

## `contapagar` — contas a pagar

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `pessoaid` | bigint FK | → `pessoa.nome` (fornecedor/credor) |
| `unidadenegocioid` | bigint FK | → `unidadenegocio`. Inclui o **ESCRITÓRIO** (`codigo='ESC'`, id `1`), que concentra a maior parte das contas (pagamentos centralizados) |
| `planocontasid` | bigint FK | → `planocontas` (nullable — usar `COALESCE(pc.caminho,'')`) |
| `descricao` | varchar | ⚠️ **NULL em ~96% dos títulos** |
| `numerodocumento` | varchar | |
| `dataemissao` | timestamp | |
| `datavencimento` | timestamp | Vencimento nominal |
| `datavencimentoutil` | timestamp | **Vencimento já rolado para o próximo dia útil pelo ERP** (considera fim de semana + feriados locais). Para `status='A'` é SEMPRE dia útil (DOW 1–5, zero nulos) |
| `valor` | numeric | **Valor líquido a pagar** (com desconto/acréscimo/multa aplicados) — usar este para cash planning |
| `valordocumento` | numeric | Valor de face do documento (difere de `valor` em ~0,6% dos casos) |
| `status` | char(1) | `'A'` **Aberto** (~68 mil) · `'B'` **Baixado/pago** (~587 mil) · `'C'` **Cancelado** (~453 mil) |

**Regras:**

- "Em aberto" = `status = 'A'`. **Não precisa** de `NOT EXISTS cancelamentocontapagar` — canceladas
  já são `'C'`.
- ⚠️ **`contapagar` não tem data de pagamento própria.** A data de baixa fica em
  **`pgtocontapagar.datahora`**. Para regime de caixa:

```sql
FROM contapagar cp
JOIN pgtocontapagar pg ON pg.contapagarid = cp.id
WHERE cp.status = 'B'
  AND pg.datahora >= $1 AND pg.datahora < $2
```

- "Por dia útil" → usar `datavencimentoutil`, **não recriar roll-forward de feriado na aplicação**.
  Extrair o dia da semana no SQL: `EXTRACT(DOW FROM cp.datavencimentoutil)` (imune a fuso;
  0=Dom..6=Sáb).
- **Grupos por plano de contas** (classificação validada):
  - **Fornecedor** = `planocontas.caminho ILIKE '%Custo Operacional%'` (compra de mercadoria)
  - **Pessoas** = `ILIKE '%PESSOAL%'`
  - **Outros** = o resto (sempre com `COALESCE(pc.caminho,'')` para tratar título sem plano)

### ⚠️⚠️ Títulos com "PREVISÃO" na descrição não são obrigação real

Título com "previsão" na `descricao` é estimativa digitada à mão para planejamento de caixa.
Medido: **R$ 3,0 mi**, sendo **R$ 2,49 mi só de "PREVISÃO DE MERCADORIA EM TRÂNSITO"**, mais 13º/INSS
13º (R$ 243 mil), entregadores (R$ 360 mil) e previsões de fornecedor; uma delas diz literalmente
**"PREVISÃO - CONFIRMAR VALOR"**.

```sql
AND COALESCE(cp.descricao, '') NOT ILIKE '%PREVIS%'
```

- O padrão `'%PREVIS%'` é proposital: a base tem `PREVISÃO`, `PREVISAO`, `previsão`/`previsao`
  minúsculo, `CREDITAS (PREVISÃO)` no meio do texto e até o erro de digitação **`PREVISAÕ VEPAKUM`**.
- ⚠️⚠️ **O `COALESCE` NÃO é cosmético.** `descricao` é NULL em ~96% dos títulos, e em SQL
  `NULL NOT ILIKE '...'` devolve **NULL, não TRUE** — sem o `COALESCE`, o filtro excluiria **70.586
  títulos em silêncio** e o "a pagar" despencaria de ~R$ 35 mi para ~R$ 2,8 mi, sem nenhum erro.
  **Regra geral: todo filtro `NOT ILIKE`/`NOT LIKE` sobre coluna nullable precisa de `COALESCE(col,'')`.**
- ⚠️ Um plano de contas cujo **nome** contém `**PREVISÃO**` (ex.: um convênio de vale-alimentação)
  **não** deve ser excluído: aqueles títulos têm fornecedor real, número de documento e vencimento
  certo. Os dois marcadores não se sobrepõem (zero títulos com os dois).

### ⚠️ `contapagar` não tem produto/comprador/fabricante

A única ponte é pela nota fiscal:

```text
contapagar → notafiscalcontapagar → notafiscal → itemnotafiscal → embalagem → produto
```

Cobertura parcial (zero para notas ainda não processadas financeiramente). Ao ratear "compras" por
dia de vencimento, quando **uma NF gera várias parcelas**, dividir na proporção do valor de cada
parcela sobre o **total de TODAS as parcelas da nota** — nunca só as em aberto, senão uma parcela já
paga infla artificialmente a fração das demais.

## `cancelamentocontapagar`

Cancelamentos de contas a pagar. **Precisa de JOIN com `contapagar`** para obter valor, fornecedor,
filial e documento.

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `contapagarid` | bigint FK | → `contapagar.id` |
| `usuarioid` | bigint FK | → `usuario.id` (quem cancelou) |
| `datahora` | timestamp | **Data/hora do cancelamento** — usar como filtro |
| `motivo` | varchar | Ex.: "BAIXADO NO BIG" |

> A tabela `businessconnectcontapagarexcluida` existe mas está **vazia** — não usar.

```sql
SELECT cc.datahora::text          AS datahora,
       cc.motivo,
       p.nome                     AS fornecedor,
       cp.valordocumento::text    AS valor,
       un.nomefantasia            AS filial,
       cp.numerodocumento,
       cp.datavencimento::text    AS datavencimento,
       pu.nome                    AS usuario
FROM cancelamentocontapagar cc
JOIN contapagar cp        ON cp.id = cc.contapagarid
LEFT JOIN pessoa p        ON p.id  = cp.pessoaid
LEFT JOIN unidadenegocio un ON un.id = cp.unidadenegocioid
LEFT JOIN usuario u       ON u.id  = cc.usuarioid
LEFT JOIN pessoa pu       ON pu.id = u.pessoaid
WHERE cc.datahora::date = $1::date
ORDER BY cc.datahora DESC;
```

Família de tabelas de cancelamento equivalentes: `cancelamentopedidocompra`,
`pedidotransferenciacancelamento`, `entregacancelamento`, `cancelamentonotafiscal`,
`cancelamentocreditofornecedor`.

## Contas a receber — as 4 correntes

⚠️ **Não existe tabela única de contas a receber.** Existem 4 correntes independentes, cada uma com
`status` / `datavencimento` / `valor` / `unidadenegocioid`, e `'A'` = a receber:

| Tabela | Estado real (medido) |
| --- | --- |
| **`crediarioreceber`** | ✅ **A única com baixa confiável** — `status='B'` com 100% de `recebimentocrediarioid` preenchido, carteira viva |
| `cartaoreceber` | ❌ **Nunca dá baixa** — 100% sem `recebimentocartaoid`, mesmo com 99,8% `conferido` |
| `pbmreceber` | ❌ `datavencimento` **100% nulo** |
| `chequereceber` | ❌ 50 títulos residuais, todos de 2024 para trás |

### ⚠️⚠️ Os títulos "em aberto" do ERP são LIXO para balanço

- `cartaoreceber` com `status='A'`: **6,2 MILHÕES de títulos / R$ 425 mi**, com vencimento até o ano
  **0248**; **R$ 338 mi vencidos há mais de 1 ano**. O ERP nunca dá baixa.
- `contapagar` com `status='A'` também acumula (R$ 102 mi numa janela curta, contra ~R$ 4–5 mi/mês
  que a rede paga de verdade).

**Consequências práticas:**

1. Qualquer indicador de capital de giro precisa de uma **janela** (ex.: 90 dias) e de um **aviso
   explícito** de que o número não serve para banco/sócio enquanto a baixa não for corrigida no ERP.
2. O **CCC** (ciclo de conversão de caixa) dá valores absurdos (−253 dias, PMP de 311 dias) — o único
   componente confiável é o **PME** (estoque ÷ CMV), que não depende de baixa de título.
3. **Para qualquer métrica de recebível/inadimplência, partir do crediário** e justificar caso a caso
   a inclusão das demais.

**Previsão de recebimento por dia de vencimento** = `UNION` das 4 correntes com `status='A'`,
excluindo CDs.

## Crediário e convênio

⚠️ **"Convênio" NÃO existe como campo no ERP** — `crediarioreceber.taxaconvenio` e
`crediarioreceber.faturaid` estão ~vazios. Na prática, **convênio = crediário**.

### `crediarioreceber`

| Coluna | Descrição |
| --- | --- |
| `pessoaid` | → `pessoa.nome` (o titular do título — pode ser a conta agregadora do convênio) |
| `clienteid` | → `cliente` → `pessoa` — **quem de fato comprou** (ver [05-pessoas-clientes.md](05-pessoas-clientes.md)) |
| `dependenteclienteid` | ⚠️ **100% nulo** nesta base |
| `unidadenegocioid` | Loja do crediário |
| `datavencimento` | |
| `valor` | |
| `status` | `'A'` em aberto · `'B'` baixado (com `recebimentocrediarioid` preenchido) |
| `faturaorigemid` | → `fatura` |

**Definições:** em aberto = `status='A'`; **vencido/atraso** = `datavencimento < hoje`;
**a vencer** = `>= hoje`. Aging típico: Vencido / 0-7 / 8-15 / 16-30 / 31-60 / 60+.
Dias em atraso = `CURRENT_DATE - MIN(datavencimento)` por cliente.

⚠️ `crediarioreceber` é **transacional** — medições do "em aberto" feitas com minutos de diferença
variam alguns reais. Não é divergência de fórmula.

### Recebimento de crediário

```text
recebimentocrediario (unidadenegocioid, usuarioid, datahora)
  └── itemrecebimentocrediario (crediarioreceberid, valorrecebimento, valorjuros,
                                valormulta, valortaxaconvenio, status='A')
        └── crediarioreceber → pessoa
              └── fatura (faturaorigemid)
```

## Cartão e conciliação de cartão

| Tabela | Conteúdo |
| --- | --- |
| `cartaoreceber` | Recebível de cartão: `pessoaid`, `modalidadecartaoid`, `unidadenegocioid`, `datavencimento`, `valor`, `status`, `conferido` |
| `modalidadecartao` | Modalidade (crédito/débito/bandeira) |
| `recebimentocartao` | Cabeçalho de recebimento: `datahora`, `usuarioid` |
| `itemrecebimentocartao` | `recebimentocartaoid`, `cartaoreceberid`, `valorrecebimento`, `conciliacaocartaoitemorigemid`, `status='A'` |
| `conciliacaocartao` | Cabeçalho do arquivo da operadora (`status` `A`/`B`/`C`) |
| `conciliacaocartaoitem` | Transações: `unidadenegocioid`, `datahoratransacao`, `valor`, `taxa`, `baixadata`, **`cartaoreceberid`**, `codigoestabelecimento` |
| `conciliacaocartaoconfiguracao` | `codigoestabelecimento` ↔ `unidadenegocioid` |

**Conciliado (cartão) = `conciliacaocartaoitem.cartaoreceberid IS NOT NULL`** (transação casada com
o recebível), medido por `datahoratransacao`.

⚠️ **`baixadata` (quando o dinheiro caiu) é preenchido em poucos itens — NÃO usar como "conciliado".**

⚠️ O casamento da loja pode vir por **duas vias**: `conciliacaocartaoconfiguracao.unidadenegocioid`
**ou** `unidadenegocio.cnpj = conciliacaocartaoitem.codigoestabelecimento`.

## `planocontas`

Hierarquia com **`caminho`** completo, separador `" > "`:

```text
Resultado > 03.1 - Despesas Operacionais > 3.02 - DESPESAS OPERACIONAIS FIXAS > 3.02.003 - Beneficios Funcionarios
Resultado > 02.1 - Custo Operacional > 02.1 - FORNECEDORES > 7.01 - MEDICAMENTO
```

| Coluna | Descrição |
| --- | --- |
| `id` | |
| `nome` | |
| `caminho` | Caminho completo |
| `folha` | `true` = conta lançável |
| `tiporesultado` | Tipo contábil (`A`=receita, `C`=custo, `D`=despesa, etc.) |

**Extração de níveis** (o prefixo `Resultado > ` é o 1º segmento):

| Nível | Extração | Exemplo |
| --- | --- | --- |
| 1 | `split_part(caminho,' > ',2)` | `02.1 - Custo Operacional` |
| 2 | `split_part(caminho,' > ',3)` | `02.1 - FORNECEDORES` |
| 3 | `split_part(caminho,' > ',4)` | `7.01 - MEDICAMENTO` |

⚠️ **Bug real:** um filtro usou `split_part(caminho,' > ',2)` sem checar valores reais e ficou com
só 2–3 baldes grossos ("Custo Operacional"/"Despesas Operacionais"). O segmento útil para filtro
operacional era o **3º**. Sempre inspecionar `caminho` cru antes de escolher o índice, e proteger com
`NULLIF(..., '')`.

⚠️ Ao casar plano de contas por texto num `$queryRaw`, normalizar espaços com
**`regexp_replace(caminho,'[[:space:]]+',' ')`** — `\s` num template literal vira escape inválido e
quebra o build.

### ⚠️⚠️ O plano de contas MUDA de ano para ano

O mesmo indicador tem códigos diferentes: Manutenção de imóveis = `4.09` (2025) / `3.6.11`,`3.7.6`
(2026); Investimento = `11.0x` (2025) / `3.7.2`,`3.7.4`,`3.92.x` (2026).

→ **Classificar sempre pelo NOME da conta, nunca pelo código.** Amarrar em código zera o indicador na
virada do ano. Para comparar ano contra ano, tirar o código e o acento antes de comparar
("chave por nome").

### ⚠️ Termo genérico rouba conta de outro grupo — 3 bugs reais

Ao classificar contas por nome, um termo curto vira ímã de conta homônima em outro grupo:

| Termo | O que arrastou errado | Correção |
| --- | --- | --- |
| `ALUGUEL` | **"ALUGUEL DE CARRO"** (R$ 44 mil, logística) para Funcionamento | exceção explícita `ALUGUEL DE CARRO`/`ALUGUEL DE VEICULO` |
| `FRETE` (substring) | **"FRETE ADMINISTRATIVO"** para Frete de Mercadoria | estreitar para `FRETE DE MERCADORIA` / `FRETE DE COMPRA` |
| `CARTORIO` | **"CUSTAS DE CARTÓRIO"** (R$ 9,1 mil, despesa bancária) para Administrativas | usar o nome cheio da conta |

**Regra prática:** usar o nome MAIS ESPECÍFICO que ainda casa com a conta; casar por **fronteira de
palavra**, não substring solta ("ST" pegaria qualquer palavra com "st").

**A ORDEM das regras decide.** Exemplos reais: "Pessoal Extraordinário" precisa vir ANTES de "Pessoal
e Benefícios" (senão "13º SALÁRIO"/"INSS 13º"/"FGTS MULTA RESCISÓRIA" são capturados pelos termos
SALÁRIO/INSS/FGTS); "Imposto sobre o Resultado" antes de "IMPOSTOS"; "Taxa de transação" antes de
"Despesas Financeiras" (COMISSÃO ADM DE CARTÕES e MENSALIDADE POS moram sob `4.2 - DESPESAS
FINANCEIRAS` mas são taxa de transação); "Marketing" antes de "Assessorias" (`6.17 - ASSESSORIA MKT
(SISTEMAS)` é Marketing); "Sócios" antes de "Pessoal e Benefícios" (por causa de `VALE ALIMENTAÇÃO`).

⚠️ **Quando uma conta é classificada por NOME para uma linha diferente da do seu grupo pai, o
drill-down da linha do grupo pai precisa EXCLUÍ-LA** — senão diverge em silêncio. Bug real:
`3.2.9 - ENDOMARKETING` mora sob "PESSOAL E BENEFÍCIO" mas é classificado como Marketing; o drill de
"Pessoal e Benefícios" o trazia de volta e ficava R$ 840/mês acima da célula. Só apareceu ao
reconciliar **célula × drill linha a linha**.

⚠️ **Sempre ter uma linha "Outros / sem classificação"** para que nada suma em silêncio — e rodar a
reconciliação `soma das linhas cruas − soma das contas classificadas = R$ 0,00` a cada mudança de
regra.

## `lancamentofinanceiro` e `contacorrente`

### `lancamentofinanceiro`

| Coluna | Descrição |
| --- | --- |
| `tipo` | `'E'` = Entrada, `'S'` = Saída |
| `datahora` | Data do lançamento |
| `datahorainclusao` | Data de inclusão |
| `unidadenegocioid` | |
| `valor` | |
| `planocontasid` | → `planocontas` |
| `descricao` | |
| `contacorrenteid` | → `contacorrente` |

É o razão de caixa/banco (movimento individual), ligado ao plano de contas.

### `contacorrente`

`id`, `nome`, `status` (`'A'` Ativo, senão Inativo), `tipo` (`'B'` Bancária, senão Caixa),
`unidadenegocioid`.

Relacionadas: `movimentacaocontacorrente`, `extratobancario`, `extratobancarioconciliacao`.

### ⚠️⚠️ As três fontes de "pago" NÃO se reconciliam

Medido em jul/2026: `dre` C.M.P. **−R$ 5,54 mi** · contas a pagar **pagas** **−R$ 4,13 mi** ·
`lancamentofinanceiro` (caixa) **−R$ 1,35 mi**.

Causas investigadas:

1. O DRE captura débitos que o banco faz direto, **sem gerar conta a pagar** (IOF, tarifas) — invisíveis
   para quem só olha `contapagar`.
2. O DRE conta **juros de empréstimo pela EMISSÃO**, não pelo pagamento: em jul o ERP emitiu **63
   parcelas de juros de uma vez (R$ 1,27 mi)**, das quais só 7 foram pagas (R$ 111 mil).

→ **O DRE C.M.P. NÃO é caixa puro** — mistura emissão com pagamento.

## `dre` — DRE pré-computado

Tabela **mensal, por loja**, calculada pelo próprio Alpha 7.

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `data` | timestamp | **Primeiro dia do mês de referência** |
| `unidadenegocioid` | bigint FK | → `unidadenegocio` — ⚠️ os ids podem ser de uma faixa diferente da usada em `venda` |
| `categoria` | varchar | `'1 - DRE'` (competência) · `'2 - C.M.P.'` (Custo da Mercadoria **Paga**, regime de caixa) · `'3 - I. Geral'` · `'4 - I. Econ.'` |
| `nivel1` | varchar | Linha principal (ex.: `'01.1 - Receita Operacional Bruta'`) |
| `nivel2` | varchar | Sub-grupo (ex.: `'3.02 - DESPESAS OPERACIONAIS FIXAS'`) — **vazio `''` para linhas de resultado** |
| `nivel3` | varchar | Conta detalhe (ex.: `'3.02.003 - Beneficios Funcionarios'`) — vazio para subtotais |
| `valor` | numeric | **Negativo para custos/despesas**, positivo para receitas e resultados |
| `planocontasid` | bigint FK | → `planocontas` — ⚠️ **nullable, e no C.M.P. é 0 de 15.211 preenchidos** |

### Hierarquia de exibição

| Condição | Significado |
| --- | --- |
| `nivel2 = ''` | Linha de resultado pré-computada (ROB, ROL, Lucro Bruto, Resultado Operacional/Líquido) — negrito |
| `nivel2 <> '' AND nivel3 = ''` | Sub-grupo — indentado nível 1 |
| `nivel3 <> ''` | Conta detalhe — indentado nível 2 |

Ordenar por `nivel1, nivel2, nivel3` (os códigos "01.1", "01.3", "02.2"… dão a ordem correta).

Verificado: **nenhum (nivel1, nivel2) tem subtotal (`nivel3=''`) e detalhe (`nivel3<>''`) juntos** —
somar os subgrupos não duplica.

⚠️ Ao somar detalhe, filtrar `nivel2 <> ''`, senão os resultados pré-computados contam em dobro.

### ⚠️ Armadilhas do `dre`

- **O ESCRITÓRIO (`ESC`) carrega itens corporativos/financeiros** — tem resultado alto com receita
  zero (ex.: um mês com R$ 7,2 mi de Resultado Líquido e ROB 0).
- **IDs de sistema a excluir:** `-125` (CLOUD), `1` (ESC), `4473914` (SINC); e `un.codigo ILIKE 'BKP%'`.
- **`'2 - C.M.P.' NÃO tem contas de RECEITA.** As contas de recebimento que aparecem na tela do ERP
  (Receita de Boletos, Cartões Recebidos, Cheques, PBM, Vendas à Vista, SODEXO…) **não existem** na
  tabela `dre` — só em `lancamentofinanceiro` (tipo `E`) e nas tabelas de recebível.
- **O DRE de competência foi considerado não confiável** pelo gestor: competência ~R$ 18–21 M/mês
  contra venda real de ~R$ 12–14 M/mês. A prática adotada foi usar **venda real**
  (`SUM(venda.valortotal)` finalizada) como Receita Operacional.
- ⚠️⚠️ **`4.2.19 - AJUSTE DE SALDO (DESPESA)` = −R$ 95,2 mi** (!), mais `TRANSFERÊNCIA ENTRE CONTAS`
  (−R$ 4,4 mi) e `ESTORNO` (−R$ 45 mil) — **movimentação interna de caixa, não despesa**. Ficam
  escondidos dentro de "Despesas Financeiras" e derrubam o resultado. As contas de custo real do
  dinheiro (tarifas, juros, IOF, seguro) somam só ~R$ 2,75 mi. Só apareceu ao reconciliar conta a
  conta — o total da linha nunca denunciaria.
- **Efeito de trocar a fonte:** ao abandonar a tabela `dre` e somar `contapagar` `status='B'` pela
  data de pagamento (`pgtocontapagar.datahora`), o Resultado Final de um ano foi de
  **−R$ 95,1 mi para +R$ 7,68 mi**.
- ⚠️ Ao trocar a fonte, "Perda Operacional" vira **R$ 0,00** — perda de estoque e quebra de
  inventário **não são conta a pagar** (são baixa de estoque). Não é bug; se precisar do valor,
  vem de `baixaestoque`.
- **Consórcio e aplicação financeira ficam FORA do DRE** (são aplicação, não despesa): excluir
  `nivel3 ILIKE '%INVESTIMENTO%CONSORCIO%'`. ⚠️ Não afeta "CONSORCIO CRA" (conta a receber). Sobra
  um resíduo conhecido (`03.93 - NAO USR > CONSORCIO`) que escapa dessa exclusão.
- ⚠️ **`%MÓVEIS%` é substring de `%IMÓVEIS%`** — ao classificar Investimento por `%INVESTIMENTO%`,
  colocar um guard `nivel3 NOT ILIKE '%MANUTENÇÃO%'`, senão "MANUTENÇÃO DE IMÓVEIS" cai em dois
  baldes.
- **Despesa é NEGATIVA no ERP.** Consequências: (a) numa cascata de resultado, **somar** a despesa
  negativa já reduz o resultado — nunca subtrair; (b) a regra de cor colapsa numa comparação só —
  **`realizado >= meta` é sempre o lado bom** (gastar −9,8 mi contra meta de −10,4 mi é "maior";
  faturar abaixo da meta é "menor"); (c) meta de despesa precisa ser cadastrada negativa.

### Reconstruindo o DRE a partir de `contapagar` (regime de caixa real)

```sql
-- soma o que foi PAGO no mês, convertendo planocontas.caminho nos MESMOS 3 níveis do dre
SELECT split_part(caminho_sem_prefixo, ' > ', 1) AS nivel1,
       split_part(caminho_sem_prefixo, ' > ', 2) AS nivel2,
       split_part(caminho_sem_prefixo, ' > ', 3) AS nivel3,
       SUM(cp.valor) AS valor
FROM contapagar cp
JOIN pgtocontapagar pg ON pg.contapagarid = cp.id
JOIN planocontas pc    ON pc.id = cp.planocontasid
CROSS JOIN LATERAL (
  SELECT regexp_replace(pc.caminho, '^Resultado > ', '') AS caminho_sem_prefixo
) x
WHERE cp.status = 'B'
  AND pg.datahora >= $1 AND pg.datahora < $2
GROUP BY 1,2,3;
```

Bônus: o drill-down (que lê `contapagar`) passa a **reconciliar** com a célula.

### Fórmulas de reconciliação úteis

Ao trocar a fonte do CMV (de "pago a fornecedor" para "custo do vendido"), a ponte algébrica que
preserva a reconciliação é:

```text
R      = receita bruta
Dr     = receita devolvida
CMVliq = custo do vendido (líquido de devolução)
Cp     = pago a fornecedor
O      = demais linhas

DRE Pago       = R − Cp + O
Comportamento  = (R − Dr) − CMVliq + ajuste + O
⇒ ajuste = Dr + CMVliq − Cp
```

(variação de estoque `CMVliq − Cp` + a devolução que o regime de caixa não desconta). Resíduo
algébrico validado: **R$ 0,00 em todos os meses**.

## Tesouraria, caixa e conciliação bancária

Todas essas tabelas têm `unidadenegocioid` **exceto `extratobancario`**.

| Tabela | Notas |
| --- | --- |
| **`extratobancario`** | Linhas do extrato, por **conta bancária** (`contabancariaid`), **sem `unidadenegocioid`**. `datahora`, `valor`, `influenciasaldo` |
| **`extratobancarioconciliacao`** | `extratobancarioid`, `movimentacaocontacorrenteid` — **conciliado = existe linha aqui** |
| **`sessaocaixa`** | `caixaid`, `unidadenegocioid`, `datahorainicial`, **`datahorafinal`**, `usuarioid`, `pdvid`. **Aberto = `datahorafinal IS NULL`** |
| **`fechamentocaixa`** | Liga `sessaocaixaid` e `quebracaixaid` |
| **`quebracaixa`** | `unidadenegocioid`, `datahora`, **`valor`**, `tipo`, `status`, `sessaocaixaid`, `origemcorrecaocartaoreceberid`, `observacao` |
| **`depositosangria`** | `sangriaid`, `unidadenegocioid`, `datahora`, `valor`, `contacorrenteid` — dinheiro sangrado do caixa e depositado (o **"malote"**) |
| `sangria` | Retirada do caixa (`tipo`) |
| `movimentacaocaixa`, `apuracaoquebracaixa`, `quebracaixacorrecao` | Relacionadas |

> ⚠️ **Não existe tabela `malote`.** "Valor depositado do malote" = `SUM(depositosangria.valor)`.

### ⚠️ Armadilhas de `quebracaixa`

- **O `tipo` NÃO distingue falta de sobra** — `tipo='A'` tem valores positivos e negativos.
  **O SINAL do `valor` é que distingue: `valor < 0` = FALTA, `valor > 0` = SOBRA.**
- **`status='C'` é o estado NORMAL/processado** (~97% das linhas, observação "FECHAMENTO DE
  CAIXA…"), **NÃO** é cancelada — **não filtrar por status**.
- Excluir **correções de cartão** (`origemcorrecaocartaoreceberid IS NOT NULL`, observação
  "Valor Original/Corrigido") — são ajuste de recebível, não quebra de caixa.
- Falta do dia = `ABS(SUM(valor) FILTER (WHERE valor < 0))`.

### Métricas de tesouraria validadas

| Métrica | Fórmula |
| --- | --- |
| **% conciliação de extrato** | linhas de `extratobancario` com vínculo em `extratobancarioconciliacao` ÷ total. ⚠️ **Sem filial** (extrato é por conta bancária). ⚠️ Dias recentes ficam baixos: o extrato é importado com atraso — é normal |
| **% conciliação de cartão** | `conciliacaocartaoitem` com `cartaoreceberid IS NOT NULL` ÷ total, por `datahoratransacao` |
| **% caixa fechado** | `sessaocaixa` com `datahorafinal IS NOT NULL` ÷ total, por `datahorainicial` |
| **% entregas pendentes de baixa** | `entrega` com `status IN ('A','B','D','H')` ÷ não canceladas (`status<>'C'`), por `datahorainicial` (filial via `orcamento`) |
| **% quebra de caixa (falta)** | `ABS(SUM(quebracaixa.valor) FILTER (valor<0))` ÷ **faturamento do dia** |
| **Valor depositado do malote** | `SUM(depositosangria.valor)` |

Faixas de semáforo usadas (meta / alerta): conciliações e caixa fechado **0,85 / 0,70**; entregas
pendentes **0,05 / 0,15**; quebra **0,003 / 0,008**; tolerância do malote **R$ 0,01**.

## Indicadores de balanço derivados

Fórmulas validadas (com a ressalva dos títulos em aberto, acima):

| Indicador | Fórmula |
| --- | --- |
| **Capital de giro** | (a receber + estoque a custo médio) − a pagar |
| **Capacidade de geração de caixa** | Lucro Operacional do DRE (não recalcular — usar a cascata, uma fonte só), em R$ e % do faturamento |
| **Endividamento** | juros de empréstimo PAGOS ÷ faturamento do mês |
| **CCC** | PME + PMR − PMP |
| **PME** | estoque ÷ CMV × 30 |
| **PMR** | a receber ÷ faturamento × 30 |
| **PMP** | a pagar ÷ CMV × 30 |
| **PMV (Prazo Médio de Vencimento)** | média de `contapagar.datavencimento − contapagar.dataemissao` do fornecedor, filtrado a `Custo Operacional` e `status <> 'C'` |
| **Margem de contribuição** | Receita − custos/despesas VARIÁVEIS |
| **Índice de MC** | MC ÷ receita |
| **Ponto de equilíbrio** | custos fixos ÷ índice de MC |

⚠️ **PMV por fabricante só existe quando o fabricante é o fornecedor DIRETO da nota** — join pela
`pessoa` compartilhada (`fornecedor.pessoaid = fabricante.pessoaid`). Fabricante que só vende via
distribuidor mostra **"—"**, nunca zero. Validado: 197 fabricantes têm `contapagar` vinculado por
esse caminho.
