# Pessoas, clientes, prescritores, farmacêuticos e usuários

## Sumário

- [`pessoa` — a entidade central](#pessoa--a-entidade-central)
- [`contato` — telefone e e-mail](#contato--telefone-e-e-mail)
- [`cliente` — o papel](#cliente--o-papel)
- [Busca por nome/CPF e performance](#busca-por-nomecpf-e-performance)
- [Pessoa jurídica poluindo rankings](#pessoa-jurídica-poluindo-rankings)
- [`usuario` — colaboradores e setores](#usuario--colaboradores-e-setores)
- [`farmaceutico`](#farmaceutico)
- [`prescritor` / `receitamedica` / `receitamedicaitem`](#prescritor--receitamedica--receitamedicaitem)
- [Métricas de cliente: RFM/RFV e curva ABC de clientes](#métricas-de-cliente-rfmrfv-e-curva-abc-de-clientes)

---

## `pessoa` — a entidade central

**~5,4 milhões de linhas.** É a tabela de dados pessoais/de entidade; todos os papéis apontam para
ela (ver [01-visao-geral.md](01-visao-geral.md)).

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | **É esta a chave usada em `venda.pessoaid`** |
| `nome` | varchar | |
| `tipo` | char(1) | `'F'` física (~5,4 mi) · `'J'` jurídica (~6,3 mil) |
| `cpf` | varchar | 11 dígitos, **com zeros à esquerda, sem pontuação** |
| `cnpj` | varchar | `tipo='J'` ⟺ `cnpj` preenchido (não há PF com CNPJ) |
| `sexo` | char(1) | `'F'` / `'M'` / `'N'` (não informado) |
| `datanascimento` | date | |
| `estadocivil` | char(1) | `'S'` Solteiro · `'C'` Casado · outro = não incide |
| `status` | char(1) | `'A'` = ativo |
| `datahorainclusao` | timestamp | Data de cadastro |

Endereço fica em tabelas próprias:
`endereco` → `logradouro` (`nome`, `cep`, `bairroid`) → `bairro` (`nome`, `cidadeid`) → `cidade` (`nome`).

⚠️ `cidade.nome` é **texto livre e corrompido** — ver [08-logistica-entregas.md](08-logistica-entregas.md).

## `contato` — telefone e e-mail

| Coluna | Descrição |
| --- | --- |
| `pessoaid` | → `pessoa` |
| `ddd` | |
| `contato` | O número/e-mail |
| `principal` | boolean |
| `tipo` | `'T'` telefone · `'C'` celular · `'E'` e-mail |

### ⚠️⚠️ O cadastro de contato é MUITO sujo — dedup é obrigatório

- **53% das pessoas têm mais de 1 contato** (105.107 de 200.000 medidas).
- **Algumas não têm NENHUM marcado como `principal`** — filtrar por `principal` esconde telefone de
  quem tem telefone cadastrado.
- O **mesmo número aparece 5–6× na mesma pessoa**, só mudando a digitação:
  `66996147972`, `6696147972`, `669614-7972`, `6699614 7972`, `669614 7972`, `6699614-7972`.

**Chave de dedup validada: DDD + os 8 ÚLTIMOS dígitos.** Funde variação de máscara **e** a
presença/ausência do 9º dígito do celular, sem fundir números de fato diferentes.
Validado em 2 amostras de 40 mil contatos: **0 fusões indevidas**; casos reais 10→3, 9→5, 4→3.
Um convênio com 20 telefones genuinamente distintos caiu só para 19 — a dedup não achata cadastro
legítimo.

⚠️ **Nunca "consertar" número.** Só aplicar máscara quando sobram exatamente 10 ou 11 dígitos;
qualquer outro caso (9 dígitos truncados como `669972018`, 12+ como `666696147972`) sai como o texto
cru do cadastro — inventar dígito daria um telefone que não é o que está no ERP.

## `cliente` — o papel

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `pessoaid` | bigint FK | → `pessoa` (nome, CPF, telefone estão lá) |
| `codigo` | integer | Código do cliente |
| `numerocartao` | varchar | Cartão fidelidade |
| `status` | char(1) | `'A'` = Ativo |
| `limite` | numeric | Limite de crédito |

⚠️ **`cliente` é opcional.** Muitos compradores identificados (com ~2.000 cupons) **não têm registro
em `cliente`**. Nunca restringir busca/ranking de cliente por `EXISTS cliente` — a entidade é
`pessoa`.

⚠️ **A tabela `clientes` (plural) NÃO existe neste banco** — é de outro ERP (colunas `clientes_id`,
`chapa`, `celular`, `telefone1/2`). Código legado que a referencie falha aqui.

### `cliente` como "quem de fato comprou" dentro de um convênio

Descoberta importante para crediário/convênio: o título fica na **conta agregadora**
(`crediarioreceber.pessoaid` = a empresa/convênio), mas **cada título guarda o `clienteid` de quem
de fato comprou** → `cliente.pessoaid` é o colaborador.

Medido numa conta de convênio de funcionários: **971 `clienteid` distintos / 967 pessoas** em 184 mil
títulos históricos (312 com parcela em aberto hoje).

⚠️ `crediarioreceber.dependenteclienteid` existe mas é **100% nulo** nesta base — não usar.

## Busca por nome/CPF e performance

`pessoa` tem ~5,4 milhões de linhas. Padrões medidos:

| Padrão | Custo |
| --- | --- |
| `nome ILIKE 'prefixo%'` | **seqscan ~15 s** — `ILIKE` não usa o índice, que é `LIKE` |
| `normalize_str(pe.nome) LIKE 'PREFIXO%'` com o prefixo **já normalizado** | **~50–190 ms** ✅ |
| `LIKE (normalize_str($1) || '%')` interpolado inline | **~40 s** — o planner não extrai o prefixo constante e cai para filter scan |
| Qualquer coisa acima **com `ORDER BY pe.nome`** | **~40 s** para prefixos comuns ("MARIA%") — o planner troca para o índice ordenado `idx_pessoa_nome` + filter |
| `pe.cpf = $digitos` | rápido (índice `cidx_pessoa_cpf`) |
| `LIKE ANY($1::text[])` com N prefixos | **70.868 ms** ❌ |
| `A LIKE $1 OR A LIKE $2 …` com os mesmos N prefixos | **42 ms** ✅ (**1.700×** mais rápido) |

**Índice-chave:** `cidx_pessoa_nome = btree(normalize_str(nome) varchar_pattern_ops)`.

### Receita completa de busca rápida

1. Normalizar o termo **no banco** primeiro: `SELECT normalize_str($termo)`.
2. Filtrar `normalize_str(pe.nome) LIKE ${prefixoNormalizado || '%'}` — passando o prefixo já
   normalizado como parâmetro, **nunca** com `normalize_str()` inline no `LIKE`.
3. **SEM `ORDER BY` no SQL.** Buscar `LIMIT 30` sem ordenar (o índice de padrão entrega em ordem de
   bytes) e **ordenar os ≤30 no cliente**.
4. CPF exato: `pe.cpf = $digitos` (11 dígitos, zeros à esquerda, sem pontuação).
5. id: `pe.id = $digitos::bigint` — só comparar quando o número cabe em bigint (**≤ 18 dígitos**),
   senão o `::bigint` estoura e a query erra.
6. Vários prefixos: `pe.nome LIKE $1 OR pe.nome LIKE $2 OR …`, **nunca `LIKE ANY(array)`**.
   O `EXPLAIN` mostra por quê: com `OR` de LIKEs o plano vira `BitmapOr` de
   `Bitmap Index Scan on cidx_pessoa_nome`; com `LIKE ANY(array)` o planner não extrai prefixo e
   varre as 5,4 mi de linhas.

⚠️ **Guarda de NULL em `NOT (x = ANY(...))`:** em SQL, `NULL = ANY(...)` é NULL, então uma exclusão
por lista some com todo registro órfão em silêncio. Escrever
`pessoaid IS NULL OR NOT (pessoaid = ANY($1))`. Array vazio é seguro: `NOT (x = ANY('{}'))` = TRUE.

## Pessoa jurídica poluindo rankings

⚠️ **632 "clientes" PJ respondem por só 1,12% da receita, mas dominam qualquer Top N por valor** —
PAX NACIONAL, ESTADO MATO GROSSO, UNIMED, PREFEITURA e o próprio IFOOD (o marketplace entra como
pessoa).

Em relatório de CRM/segmentação de consumidor:

```sql
AND COALESCE(pe.tipo, 'F') <> 'J'
```

**Limitação sem solução por query:** convênio cadastrado como pessoa **física com CPF** continua
entrando. O maior "cliente" da rede (R$ 339 mil/ano, 5.667 cupons) é um deles — nenhum campo do ERP
o distingue de um consumidor. É erro de cadastro; se incomodar, tratar no cadastro do ERP.

**Contas internas do grupo** (funcionários, empresas irmãs) também precisam de exclusão explícita
em relatório de carteira a cobrar. Ao casar por nome:

- ⚠️ **Casar por PREFIXO ESPECÍFICO, nunca por id fixo nem por termo curto.** Uma empresa tinha
  **dois cadastros duplicados** (ids e CNPJs diferentes) — o match por nome pega os dois sozinho.
  E termo curto vira ímã de homônimo: `%BELA%` pegaria "FAZENDA ISABELA-91" (cliente real, R$ 10
  mil); `%FORMULA%` pegaria "MED FORMULA LTDA ME" (R$ 3,3 mil).
- ⚠️ **Um caderno de oferta chamado "CONVENIO FUNCIONARIOS" NÃO identifica funcionários.** Medido:
  **733 pessoas distintas** compram por ele em 12 meses, incluindo PREFEITURA, HOSPITAL, empresas de
  dedetização, fazendas e escritórios de advocacia. E a conta agregadora de funcionários tem **ZERO**
  vendas por esse caderno — as duas coisas nem se cruzam.

## `usuario` — colaboradores e setores

| Coluna | Descrição |
| --- | --- |
| `id` | bigint PK — valores grandes (ex.: `1071590663`, `9631969`, `38012`) |
| `pessoaid` | → `pessoa.nome` |
| `login` | ⚠️ **Código numérico curto** (ex.: `442`, `395`, `1`, `1626`, `1734`) — é o "número do ERP" que os usuários citam |
| `apelido` | |
| `unidadenegocioid` | Loja de lotação |
| `plugpharmacargo` | Código Plugpharma 1–5 — ⚠️ **não distingue farmacêutico de balconista** |

### ⚠️⚠️ "Número do usuário" = `usuario.login`, NÃO `usuario.id`

Armadilha recorrente. Não existe coluna `codigo` em `usuario`. Sempre resolver códigos citados por
pessoas via `usuario.login` (ou `apelido`), nunca `id`.

Exemplos reais resolvidos ao vivo: login `442` → id `9631969`; login `395` → id `38218`;
login `1` → id `38012`; login `1626` → id `1071590663`.

⚠️ Existem **homônimos inativos** — sempre conferir pelo `login`, não pelo nome.

### Setor = `grupousuario`

"Setor" no Alpha 7 é o **grupo de usuário**:

```text
usuario → usuarioparticipantegrupousuario (usuarioid, grupousuarioid) → grupousuario.nome
```

É **N:N** — um usuário pode estar em vários grupos. Para exibição em 1 linha pega-se o 1º; para
"quem pertence ao setor X", considerar **todos** os grupos do usuário.

Grupos reais observados: `ATENDENTE - SETOR VENDAS`, `ESCRITORIO`, `DIRETORES`, `ALMOXARIFADO`,
`RH`, `COMPRADORES`, `FINANCEIRO`, `LÍDER DE LOJA`, `DPP`, `FARMACEUTICO ASSISTENTE`.

Volume: ~420 usuários ativos nesta rede.

### ⚠️ Contas de sistema poluem atribuição

Bug real: "NF recebida por colaborador" usava `notafiscal.usuarioinclusaoid` porque "cobria 100% das
notas". Investigado: **~97% das notas (60 dias) estavam lançadas por um único `usuario.id = 4` sem
nome cadastrado** — conta de sistema/integração (import automático de XML). Comparado com
`recebimentofisico.usuarioid` na mesma nota, os dois só batem em **~3%** dos casos.

→ **Lição: "cobertura de 100%" não é garantia de qualidade do dado.** Sempre checar QUEM está por
trás de uma coluna de usuário antes de usá-la como atribuição, especialmente quando um único id
concentra a maioria absoluta.

## `farmaceutico`

O código Plugpharma **não** distingue farmacêutico de balconista — quem distingue é esta tabela.
~76 registros nesta base, 13 lojas com farmacêuticos ativos.

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `pessoaid` | bigint FK | → `pessoa` |
| `crf` | integer | Registro no Conselho Regional de Farmácia |
| `regiao` | varchar | Cidade/região de atuação |
| `status` | char(1) | `'A'` Ativo, `'I'` Inativo — **filtrar `status='A'`** |
| `unidadenegocioid` | bigint FK | Loja de lotação |
| `usuarioid` | bigint FK | → `usuario` — join mais direto para cruzar com vendas |

Uso canônico (flag por vendedor):

```sql
LEFT JOIN (
  SELECT DISTINCT usuarioid FROM farmaceutico WHERE status = 'A'
) f ON f.usuarioid = u.id
```

O `DISTINCT` é obrigatório — evita duplicar linhas/cupons se o mesmo usuário tiver mais de um
registro ativo.

## `prescritor` / `receitamedica` / `receitamedicaitem`

A receita médica **não liga direto na venda** — o elo é o **orçamento**:

```text
receitamedica.orcamentoid  → orcamento.vendaid → venda   (1 receita por venda; 0 vendas com 2+ receitas)
receitamedica.prescritorid → prescritor
receitamedica.id           ← receitamedicaitem (embalagemid, quantidade, precovenda, usuarioid)
```

| Tabela | Notas |
| --- | --- |
| `prescritor` | `nome`, `numero` (nº do conselho), `tipoconselho`, `uf`, `cidade`, `status` (`A`/`I`), `pessoaid`. ~10,8 mil registros |
| `receitamedica` | `orcamentoid`, `prescritorid` (**nunca nulo**), endereço do prescritor. ⚠️ **Não tem data própria** — a data vem de `venda.datahorafechamento` ou de `orcamento.datahora` |
| `receitamedicaitem` | `receitamedicaid`, `embalagemid`, `quantidade`, `precovenda`, `usuarioid` |
| `tmp_prescritores` | tabela temporária de importação (2.507 linhas) — **ignorar** |

**`prescritor.tipoconselho`** (char): `M` = CRM (~9,3 mil) · `O` = CRO · `V` = CRMV · `R` = CRN ·
`C`/`F` = CRF · `N` = COREN.

**Volumes:** 130.920 receitas, das quais **93,6% viraram venda finalizada**. ~5.500 receitas/mês de
~1.100 prescritores. Em 12 meses: **R$ 9,50 mi de cupom inteiro** e **R$ 6,15 mi só nos itens
prescritos** — 6,08% do faturamento e 3,51% dos cupons da rede.

### Armadilhas de prescritor

- ⚠️⚠️ **NÃO agrupar prescritor por `(tipoconselho, numero, uf)`.** Parece a chave natural (o
  registro do conselho), mas há 5 chaves repetidas no cadastro — e pelo menos uma junta **médicos
  diferentes** (dois nomes distintos com o mesmo CRM/UF). **Agrupar por `prescritor.id`.** O custo é
  o inverso (o mesmo médico digitado 2× conta separado), mas fundir pessoas distintas é pior.
- Cadastro tem sujeira de digitação: nome com espaço à esquerda, minúsculas, cidade nula,
  `"PRIMVEERA DO LESTE"`. Usar `NULLIF(TRIM(...), '')` na exibição.
- ⚠️ **Valor dos itens prescritos: JOIN, nunca `EXISTS` correlacionado.**
  `SUM(iv.valortotal) ... WHERE EXISTS (SELECT 1 FROM receitamedicaitem rmi WHERE rmi.receitamedicaid = r.receita_id AND rmi.embalagemid = iv.embalagemid)`
  custou **50,6 s**; o mesmo resultado via `JOIN receitamedicaitem` + `JOIN itemvenda ON (vendaid, embalagemid)`
  com `DISTINCT (receita, itemvenda)` sai em **9,7 s**.
  O `DISTINCT` é obrigatório: sem ele, receita que repete a mesma embalagem conta o item duas vezes.
- **"Convertida"** = a venda existe **E** `venda.status='F'`. Não convertida = orçamento sem venda
  **ou** com venda cancelada. Filtrar não convertidas por `orcamento.datahora` e localizá-las por
  `orcamento.unidadenegocioid` (não há venda de onde tirar a loja).
- ⚠️ **O ERP não conhece "visitador"** nem nenhum dado de relacionamento do médico (CPF,
  especialidade, cônjuge, secretária, agenda de atendimento). `prescritor` só tem nome, tipo de
  conselho, número, UF, cidade e `pessoaid`. Qualquer CRM de visita médica é cadastro externo,
  chaveado por `prescritor.id` **como texto**.

**Métricas de prescritor validadas:**

- "Captação de receita" = valor do **CUPOM INTEIRO** das vendas com receita médica (inclui a compra
  casada — é o retorno real que a prescrição traz para a loja). Os itens prescritos ficam como
  número secundário (64,8% do captado).
- "Médicos mais prescritos" = ranking por **valor captado**, não por nº de receitas.
- Ranking de itens por médico: agrupar por **`produto`**, não por `embalagem` (o interesse é o
  medicamento, não o SKU).

## Métricas de cliente: RFM/RFV e curva ABC de clientes

Fórmulas validadas nesta rede (úteis como referência de "como já se calculou isso").

- **RFM/RFV**: recência = dias desde a última compra; frequência = nº de cupons; valor = **receita
  líquida** (venda finalizada − `devolucaovenda` daquela venda, com a ressalva da venda `status='D'`).
  **PJ fica fora** (`pessoa.tipo <> 'J'`).
- **Notas 1–5 por `percent_rank()`, não `ntile(5)` nem `cume_dist()`** — os três foram testados
  contra os dados reais:
  - `ntile` reparte empatados arbitrariamente entre baldes (**29,7% dos clientes têm exatamente 1
    cupom**: metade cairia em F=1 e metade em F=2, e clientes idênticos ficariam em segmentos
    diferentes).
  - `cume_dist` respeita o empate mas ancora o bloco no FIM da faixa, então **ninguém tira F=1** e os
    segmentos "Novos clientes" (R5,F1) e "Perdidos" (R1,F1) ficam **vazios**.
  - `percent_rank()` ancora no INÍCIO: quem tem o pior valor tira 1. Preço a pagar: os baldes não
    têm 20% cada (inevitável com empate massivo).
- **Curva ABC de clientes** = Pareto de faturamento do público no período: A = clientes que somam até
  **80%** da receita, B = 80–95%, C = 95–100%. Cada cliente é classificado **uma vez** (gasto na
  rede) e atribuído à sua **loja principal** (onde mais gastou no período).
- ⚠️ **Filtro demográfico define o PÚBLICO ANTES de calcular a curva** (server-side). Quem não tem o
  dado (`datanascimento`/`sexo`/endereço) sai quando o filtro correspondente está ativo.
- ⚠️ **Só reconstruir o coorte quando a métrica depende da curva.** Medido (12 meses, rede toda):
  "20 itens mais vendidos" **com** coorte 65 s / 23 s **vs. 11 s / 9 s** filtrando a demografia
  direto no join `venda → pessoa` — resultado **idêntico linha a linha**. Filtro de público puro sai
  muito mais barato como join em `pessoa`.
- **Cliente conta em CADA filial onde comprou** numa matriz loja × segmento (a soma das filiais dá
  ~1,8× a base) — comparar colunas, não somar linhas.
- ⚠️ **`n_filiais` (quantas filiais o cliente frequenta) é sempre da REDE, nunca do recorte
  filtrado.** Se a CTE base já viesse filtrada por loja, ao focar uma loja **todo cliente pareceria
  "exclusivo" dela**. Invariante conferida: `Σ exclusivos por filial == clientes do balde "1 filial"`.
  Achado: **52% dos clientes compram numa filial só e trazem 15,9% da receita**; os 48% que circulam
  trazem 84,1%.
- **Uma query só** com `json_build_object` + subselects sobre as mesmas CTEs, em vez de 5 queries em
  paralelo — repetir a varredura de `venda` cinco vezes brigaria pelo pool de conexões. ~7 s com pool
  aquecido (25 s a frio) para 185 mil clientes.
