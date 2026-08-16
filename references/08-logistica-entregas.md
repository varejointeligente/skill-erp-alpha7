# Logística: entregas, remessas, endereço e unidades de negócio

## Sumário

- [`unidadenegocio` — lojas e filiais](#unidadenegocio--lojas-e-filiais)
- [`entrega`](#entrega)
- [`remessa` / `entregaremessa`](#remessa--entregaremessa)
- [Endereço de entrega e a ausência de coordenada](#endereço-de-entrega-e-a-ausência-de-coordenada)
- [Geocodificação](#geocodificação)
- [Roteirização por proximidade](#roteirização-por-proximidade)

---

## `unidadenegocio` — lojas e filiais

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | ⚠️ **Valores grandes e não sequenciais** (64706, 99651, 188259, 1731008, 1050000376428, 5500380…) |
| `codigo` | varchar (unique) | Código curto: `'01'`…`'19'`, `'CD'`, `'CD2'`, `'ESC'`, `'SINC'`, `'CLOUD'`, `'BKP…'` |
| `nome` | varchar | Nome completo — **os 2 primeiros caracteres são o apelido interno** |
| `nomefantasia` | varchar | |
| `razaosocial` | varchar | |
| `status` | char(1) | `'A'` Ativa, `'I'` Inativa |
| `cnpj` | varchar | |
| `cidade` | varchar | ⚠️ **Texto livre** — grafia inconsistente entre lojas da mesma cidade |
| `estado` | varchar | Sigla (ex.: `MT`), coluna separada de `cidade` |
| `grupounidadenegocioid` | bigint FK | → `grupounidadenegocio.nome` |

### ⚠️⚠️ Os IDs variam entre bancos — nunca hardcodar

O mesmo relatório rodando em bancos diferentes vê faixas de id completamente distintas
(ex.: uma base usa 99640–99659 em `venda`; outra usa 188259 para a matriz). E dentro do MESMO banco,
os ids que aparecem em `dre` podem ser de uma faixa diferente da que aparece em `venda`.

**Derivar sempre a lista dinamicamente:**

```sql
SELECT DISTINCT un.id::text, un.codigo, COALESCE(un.nomefantasia, un.nome) AS nome
FROM unidadenegocio un
WHERE un.status = 'A'
  AND un.codigo NOT IN ('ESC','SINC','CD')
  AND un.id IN (
    SELECT DISTINCT unidadenegocioid FROM venda
    WHERE datahorafechamento >= CURRENT_DATE - INTERVAL '180 days'
  )
ORDER BY un.codigo;
```

### CTE canônica `lojas_ativas`

O filtro varia por contexto; as variantes usadas na prática:

```sql
-- Padrão para relatório de venda/estoque (exclui TODOS os CDs)
WHERE un.status = 'A'
  AND un.codigo NOT ILIKE 'CD%'
  AND un.codigo NOT IN ('ESC','SINC','CLOUD','17')

-- Quando o CD PRINCIPAL deve aparecer como loja própria (retaguarda/logística)
WHERE un.status = 'A'
  AND un.codigo NOT IN ('CD2','CD3','CD4','ESC','SINC','17')

-- Quando também se excluem unidades não-varejo
  AND un.codigo NOT IN ('12','13','14','15')

-- DRE/tesouraria (consolidado da empresa: exclui só backup/cloud/teste)
WHERE un.codigo NOT ILIKE 'BKP%'
  AND un.codigo NOT IN ('CLOUD','SINC','17')
```

**Códigos especiais observados nesta rede:**

| Código | Papel |
| --- | --- |
| `ESC` (id 1) | **Escritório** — concentra pagamentos centralizados e convênios com empresas. Não é loja, mas tem lançamento próprio; num filtro de crediário chegou a **35% de todo o valor em aberto** |
| `CD` | Centro de distribuição principal — **é uma unidade operacional real**, com colaboradores, transferências e Curva D próprios |
| `CD2`, `CD3`, `CD4` | CDs secundários/duplicados/inativos |
| `SINC`, `CLOUD` (id −125), `BKP…` | Unidades de sistema/backup — sempre excluir |
| `17` | Unidade que **saiu do grupo** — excluir sempre; todo relatório novo já deve nascer com `NOT IN (..., '17')` |
| `12`, `13`, `14`, `15` | Unidades **não-varejo** (empresas irmãs: manipulação, vacinas, distribuidora, estética). São `unidadenegocio` reais, normalmente sem venda no período |

⚠️ Ao filtrar `NOT ILIKE 'CD%'`, o **CD principal também é barrado** — se ele deve aparecer, usar a
lista explícita `NOT IN ('CD2','CD3','CD4', ...)`.

### Nome da loja em relatórios

**`LEFT(un.nome, 2)`** — os 2 primeiros caracteres de `nome`:

| `un.nome` | Rótulo |
| --- | --- |
| `"MA - MATRIZ - PRIMAVERA DO LESTE"` | `MA` |
| `"CV - FILIAL - CAMPO VERDE"` | `CV` |
| `"DT - DESCONTAO"` | `DT` |

Não existe coluna `apelido`. ⚠️ Unidades sem o padrão `"XX - …"` (ex.: `AMO VACINAS`) geram um código
de 2 letras "aleatório" (`AM`) — aceitável, normalmente já são filtradas por `receita > 0`.

**Nome reduzido alternativo** (usado no DW), que corta até o 2º hífen:

```sql
CASE
  WHEN length(regexp_replace(un.nome, '[^-]', '', 'g')) >= 2 THEN
    substring(un.nome FROM 1 FOR
      position('-' IN un.nome || '')
      + position('-' IN substring(un.nome FROM position('-' IN un.nome) + 1)) - 1)
  ELSE un.nome
END AS nome_reduzido
```

### ⚠️ `unidadenegocio.cidade` é texto livre

Grafia inconsistente entre lojas diferentes para a mesma cidade: `"PRIMAVERA DO LESTE"` maiúscula
numa loja, `"Primavera do Leste"` mista noutra. **Sem normalizar, a mesma cidade vira 2 linhas no
agrupamento** — caso real: R$ 901,83 em "Primavera do Leste" separado de R$ 53.171,34 em
"PRIMAVERA DO LESTE" na mesma consulta.

```sql
GROUP BY UPPER(TRIM(un.cidade))
```

- `cidade` é `NULL` nas unidades não-varejo.
- **Lição geral:** sempre que agrupar por campo de texto livre do ERP (não um código/enum), rodar
  uma checagem rápida de duplicata por caixa/espaço **antes** de confiar no agrupamento.

## `entrega`

| Coluna | Tipo | Descrição |
| --- | --- | --- |
| `id` | bigint PK | |
| `orcamentoid` | bigint FK | → `orcamento` — ⚠️ **não tem `unidadenegocioid` direto** |
| `status` | char(1) | Ver tabela abaixo |
| `usuarioinicialid` | bigint FK | → `usuario` (quem abriu) |
| `pessoaid` | bigint FK | → `pessoa` (cliente) |
| `datahorainicial` | timestamp | Quando foi registrada — **usar como filtro de período** |
| `datahoraprogramada` | timestamp | Horário programado |
| `datahorafinal` | timestamp | Quando foi concluída |
| `taxaentrega` | numeric | Taxa cobrada (pode ser zero) |
| `regiaoentregaid` | bigint FK | → `regiaoentrega` |
| `transportadoraid` | bigint FK | → `transportador` |
| `logradouroid` | bigint FK | → `logradouro` |
| `numero` | varchar | Número do endereço (⚠️ sujo: `00`, `S/N`) |
| `troco` | numeric | Troco solicitado |

### `entrega.status`

⚠️ Existem **dois mapeamentos** documentados a partir de fontes diferentes. O primeiro é o usado
para métricas operacionais (backlog/pendência) e foi validado na prática; o segundo veio do DW.
**Tratar o segundo como incerto.**

**Mapeamento operacional (validado):**

| Valor | Significado |
| --- | --- |
| `'F'` | Finalizada (tem `datahorafinal`) |
| `'E'` | Entregue (tem `datahorafinal`) |
| `'C'` | Cancelada (sem `datahorafinal`) |
| `'A'`, `'B'`, `'D'`, `'H'` | **Em aberto / pendentes de baixa** (sem `datahorafinal`) |

→ **"Pendente de baixa" = `status IN ('A','B','D','H')` ÷ não canceladas (`status <> 'C'`)**.

**Mapeamento do DW (⚠️ incerto, diverge do acima — usar com cautela):**
`C`=Faturada · `D`=Enviada · `E`=Cancelada · `F`=Finalizada · `G`=Retornada.

### Como chegar em loja e valor

```sql
-- loja
entrega → orcamento.unidadenegocioid → unidadenegocio

-- valor do pedido
entrega → orcamento.vendaid → venda.valortotal
```

⚠️ **`orcamento.vendaid` não tem índice** — nunca correlacionar por linha de `venda`. Pré-computar
a CTE de "vendas com entrega" (ver [02-vendas.md](02-vendas.md)).

### Tabelas relacionadas descobertas

`entregacancelamento` · `entregador` · `entregadorunidadenegocio` · `entregaremessa` ·
`pagamentoentrega` · `pagamentoentregacartao` · `pagamentoentregacheque` · `pagamentoentregatroca` ·
`regiaoentrega` · `regiaoentregabairro` · `regiaoentregafaixacep` · `regiaoentregahorario` ·
`regiaoentregaunidadenegocioparticipante` · `regrataxaentrega` · `separacaoentrega`.

## `remessa` / `entregaremessa`

**O ERP já agrupa entregas em remessa — não inventar numeração própria antes de olhar aqui.**

| Tabela | Notas |
| --- | --- |
| `remessa` | `codigo` (**é o nº da remessa que sai na etiqueta**), `entregadorid`, `unidadenegocioid`, `usuarioid`, `datahorainicial`/`datahorafinal`, `caixaid`. `status`: **`A`** aberta (~6,4 mil) · **`B`** baixada/fechada (~711 mil) · **`C`** cancelada (~544) |
| `entregaremessa` | **N:N** (`entregaid`, `remessaid`) — **uma remessa cobre VÁRIAS entregas** |

**Distribuição real:** 461 mil remessas com 1 entrega, 104 mil com 2, 52 mil com 3… → **agrupar até
5 é o padrão da casa**, não um número arbitrário.

### ⚠️ Só ~42% das entregas pendentes já têm remessa

834 de 2.009 em 30 dias. O ERP gera a remessa em outro momento do fluxo.

→ Toda consulta que "puxa o nº da remessa" tem que conviver com o vazio: usar **`LEFT JOIN`** e um
código próprio como alternativa. Um `INNER JOIN` perderia 58% das entregas.

⚠️ A entrega pode ter passado por uma **remessa cancelada** antes. Trazer a remessa vigente assim:

```sql
DISTINCT ON (er.entregaid) er.entregaid, r.codigo
FROM entregaremessa er
JOIN remessa r ON r.id = er.remessaid
WHERE r.status <> 'C'
ORDER BY er.entregaid, r.id DESC
```

⚠️ **Só dá para LER a remessa, nunca criar uma** — o ERP é somente leitura. Agrupamento novo precisa
ser gravado fora.

## Endereço de entrega e a ausência de coordenada

### ⚠️⚠️ NÃO existe coluna de latitude/longitude em NENHUMA tabela do Alpha 7

Varrido o `information_schema` inteiro. **Qualquer mapa exige geocodificar (endereço → lat/lng) por
fora.**

### Cadeia de endereço

```text
entrega.logradouroid → logradouro (nome, cep, bairroid) → bairro (nome, cidadeid) → cidade (nome)
+ entrega.numero
```

Cobertura: **100% têm rua/número/bairro, 88% têm CEP.**

### ⚠️⚠️ `cidade.nome` é texto livre e está CORROMPIDO

A MESMA cidade aparece como:

- `PRIMAVERA DO LESTE`, **`PRIMAVERA DO LEESTEE`**, `PRIMAVERA  DO LESTE` (2 espaços),
  `PRIMAVERA DO LESTEE`
- `BARRA DO GARÇAS`, **`BARRA DO GARÇASS`**, `BARRA DO GARÇAS MT`
- `campo verde mt` (minúsculas)

**Comparar cidade por igualdade perde ~60% das entregas de Primavera do Leste.**

→ Casar por um **TRECHO ESTÁVEL** do nome (`PRIMAVERA`, `GARCA`, `POXOR`, `CAMPO VERDE`) e devolver o
nome canônico. O `numero` também é sujo (`00`, `S/N`, "COMPRE E RETIRE").

⚠️ Para agrupar televendas/entregas por cidade, preferir **`unidadenegocio.cidade` normalizada** (da
loja) a `cidade.nome` (do endereço), ou — melhor ainda — um cadastro central cidade↔loja mantido
fora do ERP.

## Geocodificação

Como o ERP não tem coordenada, o endereço precisa ser resolvido por um provedor externo. Lições
medidas com endereços **reais** da rede:

### ⚠️ OpenStreetMap/Nominatim não cobre cidades do interior

Amostra de 12 endereços por cidade:

| Cidade | Taxa de acerto |
| --- | --- |
| Primavera do Leste | 67% |
| Campo Verde | 67% |
| Poxoréu | 58% |
| Barra do Garças | 50% |

Metade das entregas de Barra do Garças ficaria sem pino. Parte das falhas é lixo de cadastro
("COMPRE E RETIRE", número `00`, "rua K"), mas várias são endereços legítimos.

→ **Antes de propor OSM como geocodificador em qualquer cidade do interior, MEDIR a cobertura — não
presumir.** (O OSM continua servindo bem como **tiles do mapa** visual.)

### ⚠️ Rejeitar `location_type: APPROXIMATE` do Google

Quando não acha a rua, o Google responde `OK` apontando para o **centro da cidade**. Aceitar isso
encheria o mapa de pinos plausíveis e errados — e, pior, a pré-seleção por proximidade agruparia
entregas "vizinhas" que estão espalhadas pela cidade.

Aceitos: `ROOFTOP`, `RANGE_INTERPOLATED`, `GEOMETRIC_CENTER`.
Um pino a menos (entrega entra na lista com aviso) é melhor que um pino mentiroso.

⚠️ `REQUEST_DENIED` / `OVER_QUERY_LIMIT` são falha de **configuração** (chave, billing, API não
ativada), **não** "endereço inexistente" — logar explicitamente, senão o mapa esvazia sem explicação.

### Regras de uso do Nominatim (quando for a reserva)

- **Máximo 1 consulta por segundo** e `User-Agent` identificável. **Nunca** disparar em paralelo — o
  IP é bloqueado. A fila é sequencial.
- **Cache obrigatório**, com chave = endereço normalizado **e a cidade já canônica** (assim
  "PRIMAVERA DO LEESTEE" e "PRIMAVERA DO LESTE" compartilham a mesma entrada).
- **Teto de endereços novos por requisição** (~40). Sem ele a tela travava ~4 minutos: uma loja tem
  ~200 entregas pendentes × 1 s cada. Quem fica de fora **não some da lista** — aparece sem pino, com
  aviso, e a próxima chamada continua de onde parou.
- ⚠️ **Cachear SÓ o resultado POSITIVO.** Não dá para distinguir "respondeu vazio" de "caiu";
  cachear o negativo faria uma queda momentânea apagar o pino para sempre.
- Endereço não localizado **entra no roteiro assim mesmo**, com aviso — o entregador leva o endereço
  escrito.

## Roteirização por proximidade

Agrupamento por **distância real** (haversine), não por nome de bairro. Parte da entrega que espera
há mais tempo e encadeia, a cada passo, a mais próxima da **última** escolhida, dentro de um raio
(3 km) — resolve de uma vez QUAIS agrupar e em que ORDEM visitar (a cadeia é o percurso). Puro, sem
custo de API.

- ⚠️ **Encadear pela ÚLTIMA parada, não pela semente.** Medir sempre a partir da semente montaria uma
  estrela em volta dela, e o entregador voltaria ao centro a cada entrega.
- ⚠️ O raio corta o **salto entre paradas**, não o total: 5 paradas de 2 km fazem 8 km de percurso.
  É de propósito — o que não pode existir é um salto longo.
- **Por que não basta agrupar por bairro:** validado com endereços reais — a rota por proximidade
  juntou **PIONEIRO com CASTELÂNDIA** (bairros diferentes, a 400–760 m um do outro), 5 paradas em
  4,11 km. O agrupamento por nome de bairro teria separado essas entregas em duas viagens.
- Entrega sem coordenada não some: cai no agrupamento por bairro e vem no fim, marcada.
