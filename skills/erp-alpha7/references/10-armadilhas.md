# Catálogo de armadilhas e bugs reais do Alpha 7

> Cada entrada segue o formato **sintoma → causa → correção → como evitar**. Todos os casos abaixo
> aconteceram de verdade e foram medidos contra bancos reais.

## Sumário

- [Modelagem e joins](#modelagem-e-joins)
- [Status e códigos mal interpretados](#status-e-códigos-mal-interpretados)
- [Atribuição de pessoa (vendedor, colaborador, cliente)](#atribuição-de-pessoa-vendedor-colaborador-cliente)
- [Performance](#performance)
- [SQL / semântica do Postgres](#sql--semântica-do-postgres)
- [Datas e fuso horário](#datas-e-fuso-horário)
- [Qualidade do dado (texto livre, duplicatas)](#qualidade-do-dado-texto-livre-duplicatas)
- [Métricas e reconciliação](#métricas-e-reconciliação)
- [Ofertas e precificação](#ofertas-e-precificação)
- [Infraestrutura](#infraestrutura)

---

## Modelagem e joins

### A1. JOIN direto de venda com produto

- **Sintoma:** join não resolve / linhas somem / erro de tipo.
- **Causa:** `itemvenda.embalagemid` aponta para `embalagem.id`, **não** para `produto.id`. Produtos
  não são vendidos diretamente.
- **Correção:** `itemvenda → embalagem → produto`.
- **Como evitar:** memorizar as poucas exceções que ligam direto em `produtoid`
  (`itempedidotransferencia`, `custoproduto`, mínimo/máximo, `curvaabcprodutounidadenegocio`,
  `suspendecompraprodutounidadenegocio`, `classificacaoproduto`, `icmsproduto`). Tudo o mais passa por
  `embalagem`.

### A2. Comparar estoque com estoque mínimo sem agregar

- **Sintoma:** produto parece abaixo do mínimo quando não está (ou o contrário).
- **Causa:** `estoque` é por **embalagem+loja**; `estoqueminimo` é por **produto+loja**.
- **Correção:** agregar `SUM(est.estoque)` por `(loja, embalagem.produtoid)` antes de comparar.
- **Como evitar:** ao juntar duas tabelas de estoque/preço/custo, sempre conferir a granularidade das
  duas.

### A3. Fan-out silencioso ao usar `itemvenda` só para filtrar

- **Sintoma:** avisos de "chave duplicada" na UI; somas infladas.
- **Causa:** um `itemorcamento` vendido em várias unidades escaneadas separadamente gera **vários
  `itemvenda`** (quantidade negociada 15 → 15 linhas de quantidade 1). Medido: **355 de 3.758 itens
  em 30 dias (~9,4%)**, um caso com 15.
- **Correção:** trocar `JOIN itemvenda` por **`EXISTS`** quando nenhuma coluna do SELECT vem dela.
  Conjunto de itens idêntico, sem duplicata.
- **Como evitar:** se a tabela juntada não contribui com nenhuma coluna, ela não deveria estar no
  `FROM`.

### A4. Fan-out por classificação múltipla

- **Sintoma:** receita/quantidade inflada ao filtrar por categoria.
- **Causa:** `classificacaoproduto` é N:N — um produto pode ter mais de um caminho.
- **Correção:** `EXISTS` sobre uma CTE `DISTINCT (produtoid, chave)` para filtrar; `MIN(...)` +
  `GROUP BY produtoid` só para exibir.
- **Como evitar:** separar "CTE de filtro" de "CTE de exibição".
- ⚠️ **Variante que engana:** `JOIN classificacao ... AND classificacao.principal` **parece** resolver
  o N:N (soa como "pega só a classificação principal"), mas `principal` é `true` em **~100 nós**
  (macro, sub e folha). Produto pendurado em mais de um nó `principal` continua duplicando — e o
  `SUM` continua inflado. Esse padrão aparece em queries herdadas e nas geradas pelo próprio ERP;
  ao reaproveitar uma delas, **trocar por `caminho ILIKE 'PRINCIPAL > %'` + `MIN(split_part(...))`
  agrupado por produto**. Ver [03-produto-embalagem.md](03-produto-embalagem.md).

### A5. `venda.cadernoofertaid` usado como "venda em oferta"

- **Sintoma:** "% de venda em promoção" absurdamente alto ou baixo, sem relação com o encarte.
- **Causa:** `venda.cadernoofertaid` só captura cadernos de **venda inteira** — ~1,3% da receita, e
  **~99% disso é convênio** (clube de desconto, convênio de funcionários/empresas), não promoção.
- **Correção:** usar **`itemvenda.cadernoofertaid`** e recortar por nome do caderno
  (`co.nome ILIKE 'PANFLETO%'`).
- **Como evitar:** neste ERP `cadernooferta` é uma tabela-guarda-chuva (promoção + convênio + canal +
  preço controlado) — sempre olhar o `nome` antes de tratar como campanha.

### A6. `transferencia.notafiscalid` sempre vazio

- **Sintoma:** join com nota fiscal não devolve nada em transferência.
- **Causa:** `transferencia.notafiscalid` tem **0% de cobertura** para transferência.
- **Correção:** a nota fica em **`recebimentotransferencia.notafiscalid`** (~80% de cobertura).
- **Como evitar:** medir cobertura de uma FK antes de construir métrica em cima dela.

### A7. `itemnotafiscal.numeropedidocompra` usado como vínculo

- **Sintoma:** "% de entradas com pedido" absurdo.
- **Causa:** o campo é texto livre de outro sistema — só **~7%** batem com um `pedidocompra` real
  (nem por `codigo` nem por `id`).
- **Correção:** usar a cadeia
  `notafiscal → recebimentofisiconotafiscal → recebimentofisico → recebimentofisicopedidocompra → pedidocompra`.
- **Como evitar:** ⚠️ e saber que **mesmo o caminho formal cobre só ~6%** dos recebimentos — não usar
  como proxy de "o item chegou".

### A8. `liberacaousuarionegociacaonegativaid` tratado como `usuario.id`

- **Sintoma:** join resolve 0% dos casos.
- **Causa:** apesar do nome, a coluna referencia **`liberacaousuario.id`**, uma tabela de eventos de
  liberação.
- **Correção:** `orcamento.liberacaousuarionegociacaonegativaid → liberacaousuario.usuarioid → usuario → pessoa.nome`.
- **Como evitar:** desconfiar de nome de coluna terminado em `id` que não bate — checar a cardinalidade
  do join antes de confiar.

### A9. ⚠️⚠️ A MESMA tabela juntada duas vezes no `FROM` — fan-out puro

- **Sintoma:** quantidade, valor e custo inflados numa proporção que não bate com nada; o resultado
  parece só "um pouco alto demais".
- **Causa real encontrada:** uma query de item de venda tinha `entrega` **duas vezes** no `FROM` —
  uma com alias (`LEFT JOIN entrega e ON e.orcamentoid = orcamento.id`, usada no SELECT) e outra sem
  alias (`LEFT JOIN entrega ON entrega.orcamentoid = v.orcamentoid`), **que não era usada em lugar
  nenhum**. Como `orcamento → entrega` é **1:N**, o segundo join multiplica a linha do item por cada
  entrega do orçamento — sem nenhuma contrapartida no resultado.
- **Correção:** apagar o join que não contribui com coluna nenhuma. Se a tabela repetida for
  necessária de fato, colapsar para 1 linha antes (`DISTINCT ON`, `EXISTS` ou CTE agregada).
- **Como evitar:** ⚠️ **antes de somar, contar.** Rodar a query com `COUNT(*)` e comparar com o
  `COUNT(*)` da tabela-base do período — se não bater, há fan-out. Vale para qualquer 1:N pendurado
  numa query de agregação: `entrega`, `itemdevolucaovenda` (um `itemvenda` pode ter mais de uma
  devolução parcial), `classificacaoproduto`, `contato`.

### A10. ⚠️ `INNER JOIN` "decorativo" que filtra em silêncio

- **Sintoma:** o total não fecha com o relatório nativo do ERP, e não há linha visivelmente errada —
  há linhas **faltando**.
- **Causa:** queries herdadas do Alpha 7 costumam trazer tabelas no `FROM` que **não contribuem com
  nenhuma coluna do SELECT** (`unidadenegocio`, `usuario`, `caixa`, `fabricante`,
  `classificacaoproduto`, `receitamedica`, `prescritor`). Sendo `INNER JOIN`, elas funcionam como
  **filtro implícito de integridade**: produto sem fabricante cadastrado, item sem classificação ou
  venda sem caixa vinculado somem do resultado sem aviso. Num schema quase sem FK declarada, órfão é
  comum.
- **Correção:** ao reaproveitar uma query dessas, revisar **cada** join: se não fornece coluna e não
  é filtro intencional, apagar; se é filtro intencional, escrever como `WHERE ... IS NOT NULL`
  explícito para ficar visível.
- **Como evitar:** medir o custo do join antes de mantê-lo — `COUNT(*)` com e sem ele. É o mesmo
  princípio de A3: **tabela que não contribui com coluna não deveria estar no `FROM`.**

## Status e códigos mal interpretados

### B1. ⚠️⚠️ `notafiscal.status = 'A'` tratado como "Aberta"

- **Sintoma:** backlog de notas pendentes inflado; notas "pendentes" que já foram estornadas há anos.
- **Causa:** `'A'` é **Cancelada**, não "Aberta". A dedução original veio só de correlação com
  `datahoraentrada` (`'A'` costuma estar sem entrada) e nunca checou `cancelamentonotafiscal`, com
  quem correlaciona ~100% (motivos reais: "estornada", "cancelar", "erro", "ANTIGA", "2020").
- **Correção:** backlog = **`nf.status = 'I'`** apenas.
- **Impacto real:** numa tela o backlog caiu de **7.723 → 3.348** notas; noutra, de **1.443 → 474**
  (as 969 removidas eram 100% cancelamento real).
- **Como evitar:** este bug foi encontrado em **4 relatórios diferentes**. Sempre procurar uma
  **tabela de auditoria/cancelamento** que explique um status, em vez de deduzir por
  presença/ausência de outra coluna.

### B2. `quebracaixa.status = 'C'` tratado como "Cancelada"

- **Sintoma:** quebra de caixa some quase inteira do relatório.
- **Causa:** `'C'` é o **estado NORMAL/processado** (~97% das linhas, observação "FECHAMENTO DE
  CAIXA…").
- **Correção:** **não filtrar por status** em `quebracaixa`.
- **Como evitar:** conferir a distribuição de valores de um `char(1)` antes de assumir significado —
  se um valor é 97% das linhas, dificilmente é "cancelado".

### B3. `quebracaixa.tipo` usado para distinguir falta de sobra

- **Sintoma:** falta e sobra somadas juntas.
- **Causa:** o `tipo` **não** distingue — `tipo='A'` tem valores positivos e negativos.
- **Correção:** **o SINAL do `valor`**: `< 0` = FALTA, `> 0` = SOBRA. E excluir correções de cartão
  (`origemcorrecaocartaoreceberid IS NOT NULL`).

### B4. `recebimentofisico.datahorafinal` usado como data do estorno

- **Sintoma:** estornos aparecem no período errado.
- **Causa:** `datahorafinal` é a data do recebimento **ORIGINAL** — em 100% dos casos `E`/`P` é
  anterior ao estorno, que às vezes acontece semanas depois.
- **Correção:** a data e o usuário do estorno ficam em **`estornoitemrecebimentofisico`**
  (`usuarioid`, `datahora`, `motivo`), por item revertido.

### B5. Filtrar aba "recebidas" por `datahoraemissao`

- **Sintoma:** notas conferidas há pouco tempo simplesmente não aparecem.
- **Causa:** o filtro de período usava `datahoraemissao`, não `datahoraentrada`. Casos reais com
  **600+ dias** entre emissão e entrada (emissão 21/10/2024, entrada 13/07/2026).
- **Impacto:** só **~38%** das notas com entrada nos últimos 7 dias apareciam (1.901 de 5.002).
- **Correção:** filtrar por `nf.datahoraentrada` e ordenar por ela.
- **Como evitar:** a coluna de filtro tem que representar **o que a tela diz que é**.

### B6. `pedidocompra.status` — inventar significado

- **Sintoma:** contagens de pedido inconsistentes.
- **Causa:** a coluna tem **8 valores** (`E,C,H,G,A,J,D,I`) e **só `'D'` (Cancelado) foi decodificado
  com confiança** (96% tem registro em `cancelamentopedidocompra`). Os outros 7 não têm lookup nem
  correlação clara.
- **Correção:** usar `status <> 'D'` e **não inventar significado** para os demais.

### B7. `entrega.status` com dois mapeamentos divergentes

- **Sintoma:** contagens diferentes entre duas fontes de documentação.
- **Causa:** o mapeamento operacional validado (`F`/`E` concluídas, `C` cancelada, `A`/`B`/`D`/`H`
  pendentes) diverge de um mapeamento alternativo observado numa extração e nunca validado ao vivo
  (`C`=Faturada, `D`=Enviada, `E`=Cancelada, `F`=Finalizada, `G`=Retornada). Os dois se contradizem
  exatamente em `C` e `E` — os valores que mais aparecem em filtro de cancelamento.
- **Correção:** ⚠️ **incerto** — usar o mapeamento operacional (validado com dados de pendência) e
  confirmar contra a tela do ERP antes de qualquer decisão que dependa disso.

### B8. `formapagamento.id` hardcodado

- **Sintoma:** relatório funciona num banco e devolve vazio/errado noutro.
- **Causa:** os ids são **dinâmicos por banco** — PIX é `4557373` numa base e `50140839229`/`50140839226`
  noutra.
- **Correção:** sempre `JOIN formapagamento` e casar por `nome`.

## Atribuição de pessoa (vendedor, colaborador, cliente)

### C1. ⚠️⚠️ `venda.usuarioid` tratado como vendedor

- **Sintoma:** vendedor cadastrado em metas aparece com zero venda; comissão errada.
- **Causa:** `venda.usuarioid` é quem **fechou o caixa**; o vendedor é `orcamento.usuarioid`
  (ou `itemorcamento.usuarioid`). Medido: **~29% das vendas** têm usuário diferente entre venda e
  orçamento — é estrutural.
- **Correção:** cascata `itemorcamento.usuarioid → orcamento.usuarioid → venda.usuarioid`,
  pré-computada por CTE + `LEFT JOIN` (`orcamento.vendaid` não tem índice).
- **Impacto real:** um nome com 0 cupons via `venda.usuarioid` tinha **227 cupons / R$ 21 mil** via
  orçamento.
- **Como evitar:** revisar qualquer relatório que atribua venda a colaborador individual. Métricas
  que são legitimamente sobre o operador do PDV (quebra de caixa, produtividade de retaguarda)
  continuam usando `usuarioid` direto.

### C2. ⚠️⚠️ Atribuição PURA por item faz o vendedor desaparecer

- **Sintoma:** "Fulana não aparece em Comissão" — não com número errado, **a linha inteira some**.
- **Causa:** `INNER JOIN itemorcamento io ON io.id = iv.itemorcamentoid AND io.usuarioid IS NOT NULL`
  descarta todo item cujo `itemvenda.itemorcamentoid` seja NULL (venda direta) ou cujo orçamento
  tenha `usuarioid` nulo. Se TODA a venda de alguém cair nesse caso, ele não gera nenhuma linha.
- **Causa secundária:** a decisão "pura" foi tomada de propósito para bater exato com o relatório
  nativo do ERP num caso validado — trocou "R$ 80 de diferença explicada" por "vendedor invisível".
- **Correção:** restaurar a cascata com fallback (`COALESCE`), nas duas telas irmãs.
- **Como evitar:** ao "casar exato" com um relatório nativo, medir também **o que fica de fora**.

### C3. Coluna de usuário dominada por conta de sistema

- **Sintoma:** "produtividade por colaborador" cheia de linhas sem nome.
- **Causa:** `notafiscal.usuarioinclusaoid` foi escolhido por "cobrir 100% das notas", mas **~97% das
  notas (60 dias) estavam lançadas por um único `usuario.id = 4` sem nome** — conta de
  sistema/integração (import de XML). Comparado com `recebimentofisico.usuarioid`, os dois só batem
  em ~3% dos casos.
- **Correção:** usar `recebimentofisico.usuarioid` via `recebimentofisiconotafiscal` (cobre ~53% das
  notas, mas com colaboradores reais).
- **Como evitar:** **"cobertura de 100%" não é garantia de qualidade.** Sempre checar QUEM está por
  trás da coluna, especialmente quando um único id concentra a maioria absoluta.

### C4. "Número do usuário" tratado como `usuario.id`

- **Sintoma:** join não acha ninguém, ou acha a pessoa errada.
- **Causa:** os códigos curtos que as pessoas usam (442, 395, 1626, 1) são **`usuario.login`**. Não
  existe coluna `codigo` em `usuario`; o `id` é um bigint grande.
- **Correção:** resolver por `usuario.login` (ou `apelido`).
- **Como evitar:** ⚠️ há **homônimos inativos** — sempre conferir pelo login.

### C5. Restringir busca de cliente por `EXISTS cliente`

- **Sintoma:** clientes com milhares de cupons não aparecem.
- **Causa:** **muitos compradores identificados não têm registro em `cliente`** — a entidade é
  `pessoa` (`venda.pessoaid`).
- **Correção:** buscar em `pessoa`; `cliente` é opcional.

### C6. Homônimos fundidos por `GROUP BY nome`

- **Sintoma:** um "cliente" com valor somado de duas pessoas; link abre a ficha de quem não é.
- **Causa:** `GROUP BY pe.nome` sem o id.
- **Correção:** `GROUP BY v.pessoaid, pe.nome`.

### C7. Agrupar prescritor pela chave do conselho

- **Sintoma:** dois médicos diferentes viram um só.
- **Causa:** há 5 chaves `(tipoconselho, numero, uf)` repetidas no cadastro — e pelo menos uma junta
  **médicos com nomes completamente diferentes** sob o mesmo CRM/UF.
- **Correção:** agrupar por **`prescritor.id`**. O custo é o inverso (o mesmo médico digitado 2× conta
  separado), mas fundir pessoas distintas é pior.

### C8. Pessoa jurídica dominando ranking de cliente

- **Sintoma:** o "top 10 clientes" é plano funerário, operadora de saúde, prefeitura, órgão público
  estadual e o marketplace de delivery — nenhum consumidor de verdade.
- **Causa:** 632 PJ respondem por só **1,12% da receita** mas dominam qualquer Top N por valor.
- **Correção:** `COALESCE(pe.tipo,'F') <> 'J'` em relatório de CRM/consumidor.
- **Limitação sem solução por query:** convênio cadastrado como **pessoa física com CPF** continua
  entrando — o maior "cliente" da rede (R$ 339 mil/ano, 5.667 cupons) é um deles. **Nenhum campo do
  ERP o distingue de um consumidor.** É erro de cadastro.

## Performance

### D1. ⚠️⚠️ `EXISTS` correlacionado sobre `orcamento` — 14 MINUTOS

- **Sintoma:** query "essa venda tem entrega?" nunca termina.
- **Causa:** **`orcamento.vendaid` NÃO TEM ÍNDICE** (~3,9 mi de linhas). O Postgres faz varredura
  sequencial de `orcamento` inteiro **por cada linha de `venda` avaliada**.
- **Correção:** pré-computar o conjunto de `venda_id` com entrega **uma vez** numa CTE
  (`entrega JOIN orcamento JOIN venda`, filtrado pelo período) e fazer `LEFT JOIN` contra ela.
- **Como evitar:** rodar `EXPLAIN` sempre que uma query com lógica "essa venda tem X?" parecer lenta
  sem explicação.

### D2. Busca por nome em `pessoa` — 15 s a 40 s

- **Sintoma:** autocomplete de cliente trava.
- **Causas e correções:** ver a tabela completa em [05-pessoas-clientes.md](05-pessoas-clientes.md).
  Resumo: `ILIKE 'prefixo%'` → seqscan 15 s; `normalize_str()` inline dentro do `LIKE` → 40 s;
  adicionar `ORDER BY nome` → 40 s. **Certo:** prefixo já normalizado como parâmetro,
  **sem `ORDER BY`**, `LIMIT 30`, ordenar no cliente.

### D3. ⚠️⚠️ `LIKE ANY(array)` — 1.700× mais lento que `OR` de `LIKE`

- **Sintoma:** casar 4 prefixos contra `pessoa` custa **70.868 ms**.
- **Causa:** com `LIKE ANY(array)` o planner **não extrai o prefixo constante** e varre 5,4 mi de
  linhas. Com `A LIKE $1 OR A LIKE $2 …` o plano vira `BitmapOr` de
  `Bitmap Index Scan on cidx_pessoa_nome`.
- **Correção:** gerar N placeholders e unir por `OR`: **42 ms**.

### D4. `EXISTS` correlacionado em receita médica — 50,6 s

- **Causa:** `WHERE EXISTS (SELECT 1 FROM receitamedicaitem rmi WHERE rmi.receitamedicaid = ... AND rmi.embalagemid = iv.embalagemid)`.
- **Correção:** `JOIN receitamedicaitem` + `JOIN itemvenda ON (vendaid, embalagemid)` com
  **`DISTINCT (receita, itemvenda)`** → **9,7 s**. O `DISTINCT` é obrigatório: sem ele, receita que
  repete a mesma embalagem conta o item de venda duas vezes.

### D5. `LEFT JOIN LATERAL` por linha em tabela grande

- **Sintoma:** query de transferência em ~18–20 s.
- **Causa:** 2 LATERAIS correlacionados por linha de `transferencia` (~8,7 mil linhas no período).
- **Correção:** CTEs pré-agregadas independentes (`GROUP BY transferenciaid`,
  `DISTINCT ON (transferenciaid)`) + `LEFT JOIN` normal → **~7–8 s**, mesmo agregando a tabela
  relacionada inteira sem filtro de período.
- **Nota:** `LATERAL` por linha é **barato** quando a população é pequena (backlog de ~750 pedidos).

### D6. Duas queries pesadas em paralelo compartilhando a MESMA CTE

- **Sintoma:** ~18–20 s cada, disputando as mesmas tabelas grandes.
- **Causa:** resumo e lista rodando em paralelo, cada uma repetindo a CTE inteira
  (`estoque`, `venda`/`itemvenda` 90d, `suspendecompra…` de 379 mil linhas,
  `curvaabcprodutounidadenegocio` de 1,2 mi).
- **Correção:** **uma execução só** da CTE devolvendo todos os candidatos, com agregação e corte
  feitos na aplicação → melhor caso ~7 s.
- **Regra complementar:** quando as CTEs são **diferentes** (venda/estoque × NF/baixa), o inverso é
  verdade — juntar tudo numa query custou **~22 s** contra **~12 s** separadas em paralelo.

### D7. `movimentacaoestoque` — Seq Scan irredutível

- **Sintoma:** CMV real custa ~54 s, sempre.
- **Causa:** 32,2 mi de linhas **sem índice em `datahora`**; filtrar um mês não ajuda.
- **Correção:** aceitar e usar **snapshot diário**; nunca calcular a cada request. As 3 alternativas
  foram medidas antes de escolher: `movimentacaoestoque` direto **54 s** (escolhida) ·
  `itemvenda + custoproduto` **80 s** · `itemvenda → movimentacaoestoque` pelo id
  (`itemvenda.movimentacaoestoqueid`, tentando usar o índice `id+custo+customedio`)
  **118 s — a PIOR**.
- ⚠️ **O JOIN por `itemvenda.movimentacaoestoqueid` parece "barato" e não é.** Ele *parece* a opção
  óbvia — é join por id, e existe um índice `id + custo + customedio` que cobre exatamente as
  colunas buscadas — e é por isso que aparece com tanta frequência em query herdada de extração de
  CMV. Mas o join por id contra 32 mi de linhas **não compensa**: 118 s contra 54 s e 80 s das
  alternativas. Medição manda, não intuição.
- **O que continua válido desse caminho é a fonte, não a performance:**
  `movimentacaoestoque.custo`/`.customedio` é o custo **do momento da venda** (≠ `custoproduto`, que
  é o custo de hoje aplicado retroativamente).

### D8. Filtrar `itemvenda` direto por `cadernoofertaid`

- **Sintoma:** 13,3 s para um caderno.
- **Causa:** **`itemvenda.cadernoofertaid` não tem índice**.
- **Correção:** começar a CTE pela `itemcadernooferta` (poucas linhas por caderno) e casar por
  `embalagemid` (que tem índice composto) → ~8,5 s.

### D9. Mover `EXISTS` de oferta para dentro do `FILTER`

- **Sintoma:** query de precificação passou de ~11 s para **não terminar em 60 s**.
- **Causa:** tentativa de "economizar o segundo scan" colocando o `EXISTS` de oferta dentro de um
  `SUM(...) FILTER (WHERE EXISTS (...))` na CTE de agregação por produto+loja.
- **Correção:** manter como **CTE separada** (~5 s extra num mês inteiro).

### D10. `LIMIT` escondendo lojas pequenas num drill-down

- **Sintoma:** resumo mostra 11 itens para uma loja, o detalhe mostra 0.
- **Causa:** `ORDER BY datahora ASC` (mais antigo primeiro) com `LIMIT 500` — o CD sozinho (400+
  linhas, muito mais antigas) consumia o limite inteiro.
- **Correção:** subir o teto para cobrir o backlog com folga, ou filtrar o detalhe pela mesma seleção
  de loja do resumo.

## SQL / semântica do Postgres

### E1. ⚠️⚠️ `NOT ILIKE` sobre coluna nullable derruba 96% das linhas em silêncio

- **Sintoma:** o total de "a pagar" despencou de ~R$ 35 mi para ~R$ 2,8 mi, **sem nenhum erro**.
- **Causa:** `contapagar.descricao` é NULL em ~96% dos títulos (70.586 de ~73 mil) e, em SQL,
  `NULL NOT ILIKE '...'` devolve **NULL, não TRUE**.
- **Correção:** `COALESCE(cp.descricao, '') NOT ILIKE '%PREVIS%'`.
- **Como evitar:** **regra geral — todo filtro `NOT ILIKE`/`NOT LIKE` sobre coluna nullable precisa
  de `COALESCE(col, '')`.**

### E2. `NULL = ANY(...)` some com registro órfão

- **Sintoma:** títulos sem `pessoaid` desaparecem de uma listagem que só deveria excluir uma lista.
- **Causa:** `NOT (NULL = ANY(...))` é NULL, não TRUE.
- **Correção:** `pessoaid IS NULL OR NOT (pessoaid = ANY($1))`. Array vazio é seguro
  (`NOT (x = ANY('{}'))` = TRUE).

### E3. ⚠️ `ORDER BY <alias>` onde o alias é `expr::text`

- **Sintoma:** ordenação errada — `"10"` vem antes de `"2900"`; `"40"` antes de `"3043"`.
- **Causa:** o alias é texto, então a ordenação é **lexicográfica**.
- **Correção:**

```sql
-- ERRADO
SELECT (v.qtd/90.0*30*...)::text AS venda_perdida ... ORDER BY venda_perdida DESC
-- CERTO
... ORDER BY (v.qtd/90.0*30*...) DESC
```

- **Como evitar:** este bug reapareceu pelo menos 3 vezes em relatórios diferentes. Ao fazer `::text`
  para evitar BigInt, **conferir todo `ORDER BY` da query**.

### E4. `%MÓVEIS%` é substring de `%IMÓVEIS%`

- **Sintoma:** "MANUTENÇÃO DE IMÓVEIS" cai em dois indicadores.
- **Correção:** guard explícito (`nivel3 NOT ILIKE '%MANUTENÇÃO%'`) na regra que captura MÓVEIS.

### E5. Termo curto vira ímã de conta/cliente homônimo

- **Sintomas e casos reais:**
  - `ALUGUEL` arrastou **"ALUGUEL DE CARRO"** (R$ 44 mil) para o grupo errado
  - `FRETE` arrastou **"FRETE ADMINISTRATIVO"**
  - `CARTORIO` arrastou **"CUSTAS DE CARTÓRIO"** (R$ 9,1 mil)
  - um fragmento de 4 letras tirado do nome de uma **empresa irmã** pegou junto um **cliente comum
    sem relação nenhuma** (R$ 10 mil a receber) que só tinha aquelas letras no meio do nome
  - um fragmento genérico do ramo (tipo `%FORMULA%`) pegou um fornecedor homônimo (R$ 3,3 mil)
  - `"ST"` (imposto) pegaria qualquer palavra com "st"
- **Correção:** usar o nome **MAIS ESPECÍFICO** que ainda casa; casar por **fronteira de palavra**,
  não substring solta; usar prefixo específico e ancorado (`<NOME DA REDE> FUNCIONARIO%`) em vez de
  `%TERMO%`.

### E6. Ordem das regras de classificação decide o resultado

- **Sintoma:** "13º SALÁRIO"/"INSS 13º"/"FGTS MULTA RESCISÓRIA" caem em "Pessoal" em vez de "Pessoal
  Extraordinário".
- **Causa:** a regra genérica (SALÁRIO/INSS/FGTS) vem antes da específica.
- **Correção:** ordenar da mais específica para a mais genérica. Casos reais: Extraordinário antes de
  Pessoal; "Imposto sobre o Resultado" antes de "IMPOSTOS"; "Taxa de transação" antes de "Despesas
  Financeiras"; "Marketing" antes de "Assessorias"; "Sócios" antes de "Pessoal e Benefícios".

### E7. Crase em comentário SQL dentro de template literal

- **Sintoma:** build quebra com "Expected a semicolon".
- **Causa:** um comentário `-- ` dentro de um `$queryRaw` levou crase estilo markdown
  (`` `descricao` ``) — a crase **fecha a string JS**.
- **Correção:** **nunca usar crase em comentário `--` dentro de template literal SQL**, nem para nome
  de tabela/CTE.
- **Como evitar:** este erro aconteceu **pelo menos duas vezes** mesmo já estando documentado.

### E8. `\s` em regex dentro de template literal SQL

- **Sintoma:** escape inválido, build quebra.
- **Correção:** usar `[[:space:]]` no lugar de `\s`:
  `regexp_replace(caminho, '[[:space:]]+', ' ')`.

### E9. `split_part` no índice errado

- **Sintoma:** filtro por plano de contas fica com só 2–3 baldes grossos.
- **Causa:** `split_part(caminho, ' > ', 2)` escolhido sem inspecionar o `caminho` cru
  (`"Resultado > 02.1 - Custo Operacional > 02.1 - FORNECEDORES > 7.01 - MEDICAMENTO"`) — o segmento
  útil era o **3º**.
- **Correção:** inspecionar o dado cru antes de escolher o índice; proteger com `NULLIF(..., '')`.

### E10. Interpolar SQL cru num tagged template

- **Sintoma:** erro de sintaxe SQL ao tentar reaproveitar uma CTE compartilhada.
- **Causa:** o wrapper transforma **todo** `${...}` em parâmetro posicional — a CTE vira um parâmetro
  de valor, não texto de query.
- **Correção:** escrever a CTE por extenso nas duas queries, ou usar a variante que aceita
  string + params posicionais.

## Datas e fuso horário

### F1. ⚠️⚠️ `CURRENT_DATE` do banco não é "hoje"

- **Sintoma:** "Data de referência: 10/07" às 23h do dia 09/07; "dias desde a última compra" inflado
  em 1 dia para a base inteira.
- **Causa:** a sessão do Postgres roda em `America/Sao_Paulo` (UTC-3); a operação está em
  `America/Cuiaba` (UTC-4).
- **Correção:** `(NOW() AT TIME ZONE 'America/Cuiaba')::date`.

### F2. `new Date()` no servidor também não é "hoje"

- **Sintoma:** projeção por run-rate cada vez mais errada conforme o dia avança.
- **Causa:** o container de aplicação não define `TZ` → `new Date()` reflete UTC; a partir de ~20h em
  UTC-4 o "hoje" do servidor já virou o dia seguinte, inflando "dias decorridos".
- **Correção:** função explícita de "hoje no fuso da operação" (`Intl.DateTimeFormat` com
  `timeZone`). Componentes de navegador não precisam do fix — `new Date()` ali já reflete o fuso de
  quem acessa.

### F3. `toISOString().slice(0,10)` para pegar "a data de hoje"

- **Sintoma:** chave de cache/gate diário não bate à noite; a tela parece quebrada.
- **Causa:** `toISOString()` normaliza para UTC **antes** de cortar — em UTC-4, depois das 20h o dia
  já virou.
- **Correção:** usar `getFullYear/getMonth/getDate` (local) ou um formatter com fuso explícito.

### F4. Data gravada à meia-noite volta um dia

- **Sintoma:** `new Date("1975-03-08T00:00:00")` em fuso negativo vira dia 7.
- **Correção:** gravar com **`T12:00:00`**, nunca meia-noite. Para montar data local a partir de
  ano/mês/dia, usar `new Date(a, m-1, d)`, nunca `new Date("2026-08-11")` (lida como UTC).

## Qualidade do dado (texto livre, duplicatas)

### G1. ⚠️ `cidade.nome` corrompido — perde ~60% das entregas

- **Sintoma:** filtro por cidade devolve muito menos do que deveria.
- **Causa:** a MESMA cidade aparece em várias grafias (cidades genericizadas, defeitos reais):
  `CIDADE_A`, `CIIDADE_AA` (letra duplicada), `CIDADE  A` (2 espaços), `CIDADE_AA`;
  `CIDADE_ÇAS` vira `CIDADE_ÇASS` e `CIDADE_ÇAS <UF>` (sigla da UF colada);
  `cidade_b mt` em minúsculas.
- **Correção:** casar por um **TRECHO ESTÁVEL** — o prefixo sem acento que sobrevive a todas as
  variantes — e devolver o nome canônico.

### G2. `unidadenegocio.cidade` duplicando linhas no agrupamento

- **Sintoma:** a mesma cidade vira 2 linhas — R$ 901,83 na grafia mista ("Cidade_a") separado de
  R$ 53.171,34 na grafia maiúscula ("CIDADE_A").
- **Correção:** `UPPER(TRIM(cidade))` no `GROUP BY` **e** no `SELECT`.
- **Como evitar:** ⚠️ **regra geral** — sempre que agrupar por campo de texto livre do ERP (não um
  código/enum), rodar uma checagem de duplicata por caixa/espaço **antes** de confiar no
  agrupamento. Este foi o primeiro caso pego **depois** de já estar em produção.

### G3. Telefone repetido 5–6× na mesma pessoa

- **Sintoma:** um diálogo de contato lista 10–20 telefones quase idênticos e fica inútil.
- **Causa:** o mesmo número gravado com máscaras diferentes (número fictício, variações reais:
  `65900010002`, `6590010002`, `659001-0002`, `6590001 0002`…).
- **Correção:** dedup por **DDD + os 8 últimos dígitos** (funde variação de máscara e a
  presença/ausência do 9º dígito). Validado em 2 amostras de 40 mil contatos: **0 fusões indevidas**.
- ⚠️ Não filtrar por `principal` — **53% das pessoas têm mais de 1 contato** e algumas não têm nenhum
  marcado como principal.
- ⚠️ Nunca "consertar" número: só aplicar máscara com exatamente 10 ou 11 dígitos.

### G4. Fabricante com nome literalmente duplicado

- **Sintoma:** produtos do "mesmo" fabricante ficam de fora de um filtro.
- **Causa:** dois cadastros "KENDALL" com ids diferentes; "BARUEL"/"BARUEL " (espaço); "ALCON
  BRASIL" ×2; "HENKEL LTDA" ×2; etc.
- **Correção:** ao casar por nome normalizado, vincular **todos** os ids do grupo. No match "contém",
  manter a regra estrita (só aceitar match único) — ali candidatos múltiplos costumam ser marcas de
  fato diferentes ("EUROFARMA" bate em "EUROFARMA OTC"/"GENÉRICO"/"RX").

### G5. Normalizar nome de pessoa filtrando palavras curtas

- **Sintoma:** um cadastro que existe não casa.
- **Causa:** filtro `palavra.length > 1` (pensado para descartar iniciais) descartava o **"E"** —
  `"2-COMPRE E RETIRE"` virava `"COMPRE RETIRE"`.
- **Correção:** descartar **só bloco puramente numérico**. **Nunca filtrar por comprimento de
  palavra** ao normalizar nome de pessoa — partículas de 1 letra são parte do nome.

### G6. Cadastro de prescritor sujo

- **Sintoma:** nomes com espaço à esquerda, minúsculas, cidade nula, `"PRIMVEERA DO LESTE"`.
- **Correção:** `NULLIF(TRIM(...), '')` na exibição.

## Métricas e reconciliação

### H1. ⚠️ Denominador de ruptura podia passar de 100%

- **Causa:** a fórmula antiga (`itens em ruptura ÷ itens com estoque`) comparava dois conjuntos
  **disjuntos**.
- **Correção:** `itens em ruptura ÷ (itens com estoque + itens em ruptura)`.

### H2. ⚠️⚠️ Curva D "fantasma" — classificação sobrevive ao estoque zerar

- **Sintoma:** produtos zerados entram na contagem de Curva D.
- **Causa:** `curvaabcvalorid = 343` marca produto+loja **independente do estoque atual**.
- **Correção:** exigir `estoque_total > 0` no join. Impacto real: EMS GENERICOS caiu de **204 → 125**
  produtos.
- ⚠️ **Exceções deliberadas:** flag de auditoria num item recém-recebido e a análise "Curva D com
  saída em outra loja" (onde estoque baixo é justamente o sinal certo).

### H3. `venda.status='D'` descontada duas vezes

- **Sintoma:** receita líquida subestimada.
- **Causa:** venda `'D'` = devolvida por inteiro; a receita bruta só soma `'F'`, então ela **já está
  fora** — descontar a devolução dela conta o estorno duas vezes. Validado: das 16.469 devoluções,
  **4.183 apontam para venda `'D'`** (R$ 519 mil).
- **Correção:** ao calcular devolução do período, filtrar `v.status = 'F'`.

### H4. `pagamentovenda.valor` não fecha com a receita

- **Sintoma:** Σ pagamentos R$ 14,34 mi × receita R$ 13,83 mi.
- **Causa:** `pagamentovenda.valor` **inclui o troco** (só no Dinheiro).
  `Σ pagamentovenda = venda.valortotal + venda.valortroco`.
- **Correção:** subtrair `SUM(venda.valortroco)` da forma Dinheiro.

### H5. Venda digital duplicada por múltiplas formas de pagamento

- **Sintoma:** soma dos 5 canais R$ 36.648,62 × total real R$ 34.434,41 (**6,4% de inflação**).
- **Causa:** uma venda pode ter 2+ formas digitais (existem itens com
  `canais = [E-COMMERCE PRÓPRIO, MARKETPLACE_A, PLATAFORMA_2]` na mesma venda); somar produto sobre "uma linha por
  venda+canal" conta o item 2×.
- **Correção:** CTE que agrupa **por venda** e devolve `array_agg(canal)`; manter o `unnest` dos
  canais **isolado numa CTE de rótulo**, nunca junto do `SUM`.

### H6. Contagem do cabeçalho = número da página

- **Sintoma:** "100 médicos pararam de prescrever" tanto na rede (2.301) quanto numa filial (718).
- **Correção:** `COUNT(*) OVER ()` + `SUM(...) OVER ()` **antes** do `LIMIT`.
- **Como evitar:** vale para qualquer lista truncada cujo cabeçalho anuncia contagem.

### H7. Drill-down não reconcilia com a célula

- **Sintoma:** o diálogo mostra R$ 840/mês a mais que a célula.
- **Causa:** `3.2.9 - ENDOMARKETING` mora sob "PESSOAL E BENEFÍCIO" mas é classificado como
  Marketing; o drill de "Pessoal e Benefícios" o trazia de volta.
- **Correção:** quando uma conta é classificada **por nome** para uma linha diferente da do seu grupo
  pai, o drill da linha do grupo pai precisa **excluí-la**.
- **Como evitar:** reconciliar **célula × drill linha a linha**. O total da tela nunca denunciaria.

### H8. ⚠️⚠️ `AJUSTE DE SALDO` de R$ 95 mi escondido em "Despesas Financeiras"

- **Sintoma:** Resultado Final da empresa em ~−R$ 95 mi.
- **Causa:** `4.2.19 - AJUSTE DE SALDO (DESPESA)` (−R$ 95,2 mi), `TRANSFERÊNCIA ENTRE CONTAS`
  (−R$ 4,4 mi) e `ESTORNO` (−R$ 45 mil) — **movimentação interna de caixa, não despesa**. As contas
  de custo real do dinheiro somam só ~R$ 2,75 mi.
- **Correção:** listar conta a conta e deixar visível numa linha "Outros", em vez de escondido.
- **Como evitar:** **só apareceu ao reconciliar conta a conta** — o total da linha nunca denunciaria.

### H9. Comparação ano contra ano por código de conta

- **Sintoma:** a coluna "mesmo mês do ano anterior" veio 100% "—".
- **Causa:** **o plano de contas muda de ano para ano** (`7.02 - NÃO MEDICAMENTO` em 2026 tem outro
  código em 2025).
- **Correção:** comparar por **nome** (tirando código e acento).

### H10. Média de percentuais / média de médias

- **Sintoma:** ticket médio, margem e elasticidade "quase certos" mas nunca reconciliando.
- **Correção:** **somar os componentes brutos ANTES de dividir**, sempre. KPI de rede é ponderado.

### H11. Zero exibido onde não há dado

- **Sintoma:** cliente sem venda aparece com margem 0%; NPS sem resposta aparece como 0.
- **Causa:** zero é um valor **ruim de verdade** (margem zero, NPS zero) — confundir com "sem dado" é
  o erro clássico do indicador.
- **Correção:** devolver `null` e mostrar **"—"**.

### H12. Faixas de threshold comparando só o teto

- **Sintoma:** um valor fracionário (49,5) fica sem nenhuma faixa.
- **Causa:** faixas definidas com `max: 49`.
- **Correção:** comparar **só pelo piso** (`min`), sem teto.

## Ofertas e precificação

### I1. `precooferta IS NOT NULL` zera a categoria Leve+Pague

- **Sintoma:** a categoria "Leve + Pague" fica sempre vazia.
- **Causa:** `itemcadernooferta.precooferta` é **sempre NULL** para `tipooferta='L'` — o desconto é
  implícito na razão leve/pague.
- **Correção:** tornar o filtro condicional (só exigir fora de leve/pague).

### I2. Caderno "CONVENIO FUNCIONARIOS" usado para identificar funcionários

- **Sintoma:** exclusão tiraria R$ 1.309.748,48 (64,8%) e 220 de 356 clientes.
- **Causa:** **733 pessoas distintas** compram por ele em 12 meses, incluindo prefeitura, hospital,
  empresas de dedetização, fazendas e escritórios de advocacia — é um caderno de **convênio em
  geral**. E a conta agregadora de funcionários tem **ZERO** vendas por esse caderno.
- **Correção:** excluir pelas contas nomeadas (prefixo específico), não pelo caderno.

### I3. `estoquemaximoprodutounidadenegocio` como fonte de "estoque máximo"

- **Sintoma:** análise de excesso não devolve nada.
- **Causa:** a tabela tem **3 linhas** cadastradas nesta rede.
- **Correção:** usar **cobertura de estoque** (`estoque ÷ (qtd_90d ÷ 90)`).

### I4. `embalagem.markup` como base para preço sugerido

- **Sintoma:** preço sugerido absurdo.
- **Causa:** o markup cadastrado diverge muito do real (ex.: cadastrado 34%, real hoje 1.975%) —
  calculado contra o custo em outro momento e nunca resincronizado.
- **Correção:** calcular a partir do custo (`custo / (1 - margemObjetivo)`); exibir o markup só como
  coluna informativa.

### I5. `subcategoria = NULL` como sentinela de "toda a categoria"

- **Sintoma:** a constraint `UNIQUE(categoria, subcategoria)` não impede duplicatas.
- **Causa:** tanto SQLite quanto PostgreSQL tratam `NULL` como distinto de si mesmo em `UNIQUE`.
- **Correção:** usar `''` (string vazia) como sentinela.

### I6. Filtro de categoria aplicado depois do `LIMIT`

- **Sintoma:** escolher uma categoria mostra poucos itens mesmo ela tendo muito mais candidatos; e
  categorias de baixa receita nunca aparecem como **opção** do filtro.
- **Correção:** filtro **dentro da CTE de candidatos**, antes do corte; e opções do filtro vindas de
  **query própria contra `classificacao`**.

### I7. Priorizar "mais críticos" só na ordenação visual

- **Sintoma:** itens com margem profundamente negativa mas baixo giro nunca aparecem.
- **Causa:** o `ORDER BY` do `LIMIT 200` continuava por receita.
- **Correção:** mudar o **corte server-side** para `ORDER BY margem ASC`. Resultado: a 1ª linha
  passou a mostrar margem de **−54.550%** (produto com preço de R$ 0,01, bug de cadastro real).

### I8. Drill-down de desconto trazendo a cesta inteira

- **Sintoma:** aparecem todos os itens da venda, não só o que teve desconto.
- **Causa:** `liberacaousuarionegociacaonegativaid` é do **ORÇAMENTO** — a negociação pode ter mexido
  em 1 item só.
- **Correção:** filtro por item: `(io.precovenda * io.quantidade) - io.valortotal > 0.01`.
- **Complemento:** para restringir à negociação **manual**, alcançar `itemvenda.origemdesconto='M'`
  via `EXISTS` (nunca `JOIN` — ver A3).

### I9. Não existe auditoria de remoção de item de caderno

- **Sintoma:** impossível saber "o que saiu da oferta".
- **Causa:** **nenhuma tabela de auditoria de remoção de `itemcadernooferta`** existe (confirmado
  varrendo `information_schema.tables`).
- **Correção:** manter **snapshot próprio** e fazer diff entre dias. Nos primeiros dias não há
  histórico — informar isso explicitamente, nunca mostrar "zero" como se fosse resultado real.

## Infraestrutura

### J1. `no pg_hba.conf entry for host …` confundido com "VPN desligada"

- **Sintoma:** todas as telas que leem o ERP devolvem erro, mesmo com VPN ativa.
- **Causa:** o Postgres **rejeita na autenticação**, depois do handshake TCP. `Test-NetConnection`
  retorna sucesso — o TCP chega normalmente.
- **Descartes feitos:** reproduzido com um cliente `pg` cru, fora de qualquer framework (erro
  idêntico char a char) e em rotas antigas sem relação com a feature nova.
- **Correção:** **só o administrador do Postgres do Alpha 7 resolve** — liberar o host em
  `pg_hba.conf` (e possivelmente `hostssl` em vez de `host`, pelo aviso `no encryption`).
- ⚠️ **Trocar o nome do banco não contorna** — a regra é por host+usuário, não por banco.
- ⚠️ **O túnel SSH também não contorna** se o gateway não tiver rota para o host novo do ERP
  (sintoma diferente: `timeout expired` em vez do erro de `pg_hba`).

### J2. Falha de rede escondida como "sem dado"

- **Sintoma:** filtro de filial vem vazio, sem nenhuma explicação — indistinguível de "não tem filial
  cadastrada".
- **Causa:** o cliente engolia o erro (`.then(r => r.ok ? r.json() : []).catch(() => {})`).
- **Correção:** guardar o erro em estado e mostrar mensagem + botão "tentar de novo".
- **Como evitar:** **nunca engolir falha de rede em silêncio** — o custo é uma investigação inteira
  atrás de um bug que não existe.

### J3. Snapshot servindo valor calculado com a fórmula antiga

- **Sintoma:** o número não muda mesmo depois de corrigir a fórmula.
- **Causa:** snapshot diário cacheado por chave.
- **Correção:** ao mudar a fórmula, **bumpar a chave do snapshot** (ou limpar os registros
  manualmente) — senão o valor antigo é servido até a virada do dia.

### J4. Pool com configuração antiga após editar variável de ambiente

- **Causa:** o pool é criado uma vez por processo e sobrevive a hot reload.
- **Correção:** reiniciar o processo.
