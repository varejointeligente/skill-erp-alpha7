# Glossário — vocabulário do negócio ↔ tabela/coluna/valor

## Sumário

- [Termos de negócio → onde estão no banco](#termos-de-negócio--onde-estão-no-banco)
- [Dicionário de status `char(1)` por tabela](#dicionário-de-status-char1-por-tabela)
- [Códigos e ids fixos observados](#códigos-e-ids-fixos-observados)
- [Convenções de nomenclatura do schema](#convenções-de-nomenclatura-do-schema)
- [Siglas e jargão da rede](#siglas-e-jargão-da-rede)

---

## Termos de negócio → onde estão no banco

| Termo do negócio | Onde está |
| --- | --- |
| **Cupom fiscal / venda** | `venda` (1 cupom = 1 linha; `venda.coo` = nº do cupom) |
| **Item do cupom** | `itemvenda` |
| **Cliente** | `pessoa` (via `venda.pessoaid`) — `cliente` é só um papel opcional |
| **Cliente identificado** | `venda.pessoaid IS NOT NULL` |
| **Vendedor / quem atendeu** | `itemorcamento.usuarioid` → `orcamento.usuarioid` (⚠️ **nunca** `venda.usuarioid`) |
| **Operador de caixa / PDV** | `venda.usuarioid` |
| **Loja / filial / unidade** | `unidadenegocio` (rótulo = `LEFT(nome,2)`) |
| **Apelido da loja** | `LEFT(un.nome, 2)` — não existe coluna `apelido` |
| **Escritório** | `unidadenegocio` com `codigo='ESC'` (id 1) |
| **CD (centro de distribuição)** | `unidadenegocio` com `codigo='CD'` (e `CD2`/`CD3`/`CD4` secundários) |
| **Produto** | `produto` |
| **Apresentação / SKU / embalagem** | `embalagem` |
| **Código de barras / EAN** | `embalagem.codigobarras` |
| **Etiqueta** | `embalagem.etiqueta` |
| **Categoria (macro)** | `split_part(classificacao.caminho, ' > ', 2)` |
| **Subcategoria (nível 3)** | `split_part(classificacao.caminho, ' > ', 3)` |
| **Fabricante / laboratório** | `fabricante` → `pessoa.nome` |
| **Princípio ativo** | `principioativo.nome` (via `produto.principioativoid`) |
| **Registro MS / ANVISA** | `produto.registroms` |
| **Grupo de remarcação** | `embalagem.gruporemarcacaoid` → `gruporemarcacao.nome` |
| **Preço de venda (base)** | `embalagem.precovenda` |
| **Preço por loja (override)** | `precoembalagemunidadenegocio.precovenda` (~3% das embalagens) |
| **PMC / preço máximo / referencial** | `embalagem.precoreferencial` |
| **Custo médio** | `custoproduto.customedio` (hoje) ou `movimentacaoestoque.customedio` (histórico) |
| **Custo da última compra** | `custoproduto.custo` |
| **Curva ABC** | `curvaabcprodutounidadenegocio` → `curvaabc.nome` |
| **Curva D** | `curvaabcvalorid = 343` **+ estoque > 0** |
| **Estoque atual** | `estoque.estoque` (por embalagem+loja) |
| **Estoque mínimo / mix da loja** | `estoqueminimoprodutounidadenegocio.estoqueminimo > 0` |
| **Suspensão de compra** | `suspendecompraprodutounidadenegocio` |
| **Ruptura** | vendeu 60d **e** `SUM(estoque) <= 0` **e** sem suspensão |
| **Cobertura de estoque** | `estoque ÷ (qtd_vendida_90d ÷ 90)` |
| **Giro** | `365 ÷ cobertura` |
| **Devolução de venda** | `movimentacaoestoque` tipo 27 · `devolucaovenda` (ligada ao cliente) |
| **Devolução de compra** | `devolucaocompra` + `devolucaocompraitem` |
| **Crédito de fornecedor** | `creditofornecedor` (status `'A'` = pendente) |
| **Perda / baixa de estoque** | `baixaestoque` + `itembaixaestoque` + `motivo` |
| **Vencido** | `baixaestoque` com `motivo.descricao ILIKE '%vencid%'/'%venceu%'` |
| **Transferência (execução)** | `transferencia` + `itemtransferencia` |
| **Lista / pedido de transferência** | `pedidotransferencia` + `itempedidotransferencia` |
| **Recebimento de transferência** | `recebimentotransferencia` |
| **Nota fiscal de entrada** | `notafiscal` + `itemnotafiscal` |
| **Recebimento físico / conferência** | `recebimentofisico` + `itemrecebimentofisico` |
| **NF estornada** | `recebimentofisico.status IN ('E','P')` |
| **Pedido de compra** | `pedidocompra` + `itempedidocompra` |
| **Fornecedor** | `fornecedor` → `pessoa.nome` |
| **Orçamento / carrinho / cotação** | `orcamento` + `itemorcamento` |
| **Liberação de desconto (autorização)** | `orcamento.liberacaousuarionegociacaonegativaid` → `liberacaousuario` |
| **Desconto manual** | `itemvenda.origemdesconto = 'M'` |
| **Caderno de oferta / campanha** | `cadernooferta` (⚠️ mistura promoção, convênio, canal e preço controlado) |
| **Item em oferta** | `itemcadernooferta` |
| **Panfleto / encarte** | `cadernooferta.nome ILIKE 'PANFLETO%'` |
| **Oferta do dia** | `cadernooferta.nome` = `PADRÃO_<DIA DA SEMANA>` |
| **72 horas** | `cadernooferta.nome` contendo `72 HORA` |
| **Leve X Pague Y** | `itemcadernooferta.tipooferta = 'L'` (+ `leve`/`pague`) |
| **Desconto por quantidade** | `itemcadernooferta.tipooferta = 'Q'` + `itemcadernoofertaquantidade` |
| **Combo / compre e ganhe** | `combooferta` + `vendacombooferta` |
| **Histórico de alteração de preço** | `alteracaopreco` |
| **Convênio** | ⚠️ **Não existe como campo** — na prática é `crediarioreceber` (crediário) |
| **Crediário** | `crediarioreceber` + `recebimentocrediario` + `itemrecebimentocrediario` |
| **PBM (benefício farmacêutico)** | `pbm`, `orcamentopbm`, `pagamentovendapbm`, `pbmreceber`, `itemvenda.pbmid` |
| **Forma de pagamento** | `pagamentovenda` → `formapagamento` (⚠️ ids dinâmicos) |
| **Conta a pagar** | `contapagar` (+ `pgtocontapagar` para a data de pagamento) |
| **Título em aberto** | `status = 'A'` (na respectiva tabela de recebível/pagar) |
| **Plano de contas** | `planocontas.caminho` (hierárquico, separador `" > "`) |
| **Lançamento financeiro (razão)** | `lancamentofinanceiro` (`tipo` `'E'`/`'S'`) |
| **Conta corrente / caixa** | `contacorrente` (`tipo` `'B'` bancária / caixa) |
| **Extrato bancário** | `extratobancario` (⚠️ **sem `unidadenegocioid`**) |
| **Conciliação bancária** | existe linha em `extratobancarioconciliacao` |
| **Conciliação de cartão** | `conciliacaocartaoitem.cartaoreceberid IS NOT NULL` |
| **Sessão de caixa / PDV** | `sessaocaixa` (aberto = `datahorafinal IS NULL`) |
| **Quebra de caixa (falta)** | `quebracaixa` com `valor < 0` |
| **Sobra de caixa** | `quebracaixa` com `valor > 0` |
| **Malote / depósito** | `SUM(depositosangria.valor)` — ⚠️ **não existe tabela `malote`** |
| **Sangria** | `sangria` |
| **DRE** | `dre` (mensal, por loja; categorias `'1 - DRE'`, `'2 - C.M.P.'`, …) |
| **C.M.P.** | Custo da Mercadoria **Paga** — o DRE em regime de caixa (`dre.categoria = '2 - C.M.P.'`) |
| **ROB** | Receita Operacional Bruta (`dre.nivel1 = '01.1 - Receita Operacional Bruta'`) |
| **Entrega a domicílio** | `entrega` (loja via `orcamento.unidadenegocioid`) |
| **Remessa** | `remessa.codigo` (nº que sai na etiqueta) + `entregaremessa` (N:N) |
| **Entregador / motoboy** | `entregador`, `entregadorunidadenegocio` |
| **Região de entrega** | `regiaoentrega`, `regiaoentregabairro`, `regiaoentregafaixacep` |
| **Televendas** | venda com `entrega` não cancelada, agregada por **cidade** |
| **Canal digital** | identificado pela forma de pagamento (iFood, E-Delivery, Iqnus, Tray, Farmácias App) |
| **Receita médica** | `receitamedica` (via `orcamento`, não via venda) |
| **Prescritor / médico** | `prescritor` |
| **Farmacêutico** | `farmaceutico` (⚠️ `usuario.plugpharmacargo` **não** distingue) |
| **Setor do colaborador** | `grupousuario.nome` via `usuarioparticipantegrupousuario` |
| **Número do usuário (o que as pessoas citam)** | `usuario.login` (⚠️ **não** `usuario.id`) |
| **Campo personalizado (ex.: data de admissão)** | `campopersonalizadoconfiguracao` + `campopersonalizado` (EAV) |

## Dicionário de status `char(1)` por tabela

⚠️ **O mesmo caractere significa coisas diferentes em tabelas diferentes.** Nunca extrapolar.

| Tabela | Valor | Significado | Confiança |
| --- | --- | --- | --- |
| `venda` | `F` | Finalizada (~9,15 mi) | ✅ |
| `venda` | `C` | Cancelada (~221 mil) | ✅ |
| `venda` | `D` | **Devolvida por inteiro** (~10 mil) | ✅ |
| `venda` | `G` | Estornada (~23 mil) | ✅ |
| `itemvenda` | `F` / `C` / `D` / `G` | Fechado / Cancelado / Devolvido / Estornado | ✅ |
| `produto` | `A` / `I` | Ativo / Inativo | ✅ |
| `produto.tipo` | `M` / `S` / `T` | Mercadoria / Serviço / Serviço tomado (outro = ajuste fiscal) | ✅ |
| `unidadenegocio` | `A` / `I` | Ativa / Inativa | ✅ |
| `pessoa.tipo` | `F` / `J` | Física / Jurídica | ✅ |
| `pessoa.sexo` | `F` / `M` / `N` | Feminino / Masculino / Não informado | ✅ |
| `pessoa.estadocivil` | `S` / `C` | Solteiro / Casado (outro = não incide) | ✅ |
| `contato.tipo` | `T` / `C` / `E` | Telefone / Celular / E-mail | ✅ |
| `farmaceutico` | `A` / `I` | Ativo / Inativo | ✅ |
| `prescritor` | `A` / `I` | Ativo / Inativo | ✅ |
| `prescritor.tipoconselho` | `M` / `O` / `V` / `R` / `C`,`F` / `N` | CRM / CRO / CRMV / CRN / CRF / COREN | ✅ |
| **`notafiscal`** | `I` | **Inicial — o único backlog real** | ✅ |
| **`notafiscal`** | `A` | **CANCELADA** (⚠️ não é "Aberta") | ✅ |
| **`notafiscal`** | `C` | Conferida (343 mil notas) | ✅ (rótulo pode estar trocado com `R`) |
| **`notafiscal`** | `R` | Recebida (127 notas) | ⚠️ rótulo |
| `recebimentofisico` | `R` / `C` / `P` / `E` / `A` | Recebido / Cancelado / Estornado Parcialmente / Estornado / Aberto | ✅ |
| `pedidocompra` | `D` | Cancelado | ✅ |
| `pedidocompra` | `E`,`C`,`H`,`G`,`A`,`J`,`I` | **NÃO DECODIFICADOS** | ❌ |
| `pedidocompra.origem` | `F`,`A`,`L`,`B`,`G`,`K` | **NÃO DECODIFICADOS** | ❌ |
| `pedidotransferencia` | `A` / `C` / `D` / `B` | Aberto/pendente / Concluído / Cancelado / Concluído por outra via | ✅ |
| `pedidotransferencia.origem` | `A` / `C` / `D` / `B` | Sugestão Transferência (~99%) / Sugestão Compra / Transferência Automatizada / Encomenda | ✅ |
| `itemtransferencia` | `E`, `R`, `S` | valores observados, não decodificados em detalhe | ⚠️ |
| `devolucaocompra` | `F` / `C` / `A` / `E` | Finalizada / Cancelada / Aberta (rara) / raro | ⚠️ `A` inferido por analogia |
| `creditofornecedor` | `A` / `B` / `D` / `C` | Aberto/pendente / Baixado / Cancelado / ruído (1 registro) | ✅ |
| `baixaestoque` / `itembaixaestoque` | `F` / `C` | Finalizada / Cancelada | ✅ |
| `contapagar` | `A` / `B` / `C` | Aberto / Baixado (pago) / Cancelado | ✅ |
| `crediarioreceber` / `cartaoreceber` / `chequereceber` / `pbmreceber` | `A` / `B` | A receber / Baixado | ✅ (só crediário baixa de verdade) |
| `remessa` | `A` / `B` / `C` | Aberta / Baixada / Cancelada | ✅ |
| **`entrega`** | `F`, `E` | Finalizada / Entregue (têm `datahorafinal`) | ✅ operacional |
| **`entrega`** | `C` | Cancelada | ✅ |
| **`entrega`** | `A`, `B`, `D`, `H` | **Em aberto / pendentes de baixa** | ✅ operacional |
| **`entrega`** (mapeamento alternativo do DW) | `C`,`D`,`E`,`F`,`G` | Faturada / Enviada / Cancelada / Finalizada / Retornada | ❌ **conflita com o acima** |
| `cadernooferta` | `A` / `I` | Ativo / Inativo | ✅ |
| `cadernooferta.origem` | `A` / `C` / `F` | Automático-integração / Cadastro manual / Fidelidade-Scanntech | ✅ |
| `itemcadernooferta.tipooferta` | `P`/`D`/`L`/`Q`/`B` | Preço / Desconto% / Leve-Pague / Desconto por qtd / sem preço (ignorar) | ✅ |
| `itemcadernooferta.tipoitem` | `B` / `E` / `C` / `D` | Grupo de remarcação / Combo / Fabricante / Classificação | ✅ |
| `itemcadernooferta.descontoporqtdtipo` | `C` / `B` / `A` / `G` | Preço total do conjunto / Preço unitário / % por unidade / % no conjunto | ✅ |
| `itemvenda.origemdesconto` | `S`/`D`/`P`/`Q`/`M`/`B`/`E`/`R`/`C`/`L` | ver [02-vendas.md](02-vendas.md) | ✅ |
| `itemvendadesconto.origemdesconto` | `P` / `D` | Promoção via caderno / outro | ✅ |
| `quebracaixa` | `C` | **Estado NORMAL/processado** (~97%) — ⚠️ **não** é cancelada | ✅ |
| `combooferta` | `I` | Inativo | ✅ |
| `contacorrente.tipo` | `B` | Bancária (outro = Caixa) | ✅ |
| `lancamentofinanceiro.tipo` | `E` / `S` | Entrada / Saída | ✅ |
| `dre.categoria` | `'1 - DRE'` / `'2 - C.M.P.'` / `'3 - I. Geral'` / `'4 - I. Econ.'` | Competência / Pago (caixa) / Indicadores gerais / Indicadores econômicos | ✅ |
| `suspendecompra….origem` | `C` / `A` | Manual / Automática | ✅ |
| `produto.listapis` | `N`/`U`/`P`/`A` | Negativa / Neutra / Positiva / Não especificado | ✅ |
| `produto.tipopreco` | `L` | Liberado (outro = Monitorado) | ✅ |
| `liberacaousuario.tipo` | `I`, `D`, `B` | valores observados, **não mapeados** | ❌ |
| **Qualquer tabela** | `?` | "não definido/desconhecido" (default comum em `char(1)`) | ✅ |

## Códigos e ids fixos observados

⚠️ **Só os `tipomovimentacaoestoque` e os `curvaabc` se mostraram estáveis entre bancos.**
Tudo o mais (unidade, forma de pagamento) **varia** — derivar por query.

| Domínio | Id | Valor |
| --- | --- | --- |
| `curvaabc` | 340 / 341 / 342 / **343** | A / B / C / **D** |
| `tipomovimentacaoestoque` | 17 / 18 | Recebimento Físico / Estorno de Recebimento |
| | 19 / 20 | Inventário Entrada / Saída |
| | 21 / 22 / 23 | Transferência saída / Estorno / Recebimento de transferência |
| | 26 / 27 / 30 | **Venda** / **Devolução de venda** / Estorno de venda |
| | 31 / 32 | Baixa de estoque / Devolução de compra |
| `tipomovimentacaoestoque.codigo` | — | `RF`, `ERF`, `RTR`, `TRF`, `ETR`, `VND`, `DVV`, `EVND`, `EEV`, `BAIXA`, `DVC`, `CES`, `CEE` |
| `unidadenegocio` (DRE) | −125 / 1 / 4473914 | CLOUD / ESC (Escritório) / SINC — **excluir** |
| CFOP transferência | — | `1151,1152,2151,2152,5151,5152,6151,6152,5409,6409,5411,6411` |
| CFOP serviço | — | `5931,5932,5933,1933,2933,6933` |
| CFOP compra | — | o resto (`5102`, `5403`, `6102`, `5405`…) |
| `icmsproduto.estadoid` | 83 | UF usada no join de ICMS numa base específica (⚠️ conferir) |

## Convenções de nomenclatura do schema

| Padrão | Significado | Exemplos |
| --- | --- | --- |
| `item<entidade>` | Linha de detalhe do documento | `itemvenda`, `itemnotafiscal`, `itemtransferencia`, `itempedidocompra`, `itembaixaestoque`, `itemorcamento`, `itemcadernooferta` |
| `<entidade>item` | Variante do mesmo conceito | `devolucaocompraitem`, `receitamedicaitem` |
| `pedido<entidade>` | O pedido que antecede a execução | `pedidocompra`, `pedidotransferencia` |
| `recebimento<entidade>` | A confirmação de chegada | `recebimentofisico`, `recebimentotransferencia`, `recebimentocartao`, `recebimentocrediario` |
| `cancelamento<entidade>` / `<entidade>cancelamento` | Auditoria de cancelamento | `cancelamentocontapagar`, `cancelamentopedidocompra`, `cancelamentonotafiscal`, `cancelamentocreditofornecedor`, `entregacancelamento`, `pedidotransferenciacancelamento` |
| `estorno<entidade>` | Auditoria de estorno | `estornoitemrecebimentofisico`, `estornoitemtransferencia` |
| `<entidade>produtounidadenegocio` | Atributo por **produto + loja** | `custoproduto` (variante), `estoqueminimoprodutounidadenegocio`, `estoquemaximoprodutounidadenegocio`, `curvaabcprodutounidadenegocio`, `suspendecompraprodutounidadenegocio` |
| `<entidade>unidadenegocio` | Atributo por **entidade + loja** | `precoembalagemunidadenegocio`, `entregadorunidadenegocio` |
| `<a><b>` sem separador | Tabela de junção N:N | `classificacaoproduto`, `entregaremessa`, `transferenciapedido`, `usuarioparticipantegrupousuario`, `recebimentofisiconotafiscal`, `recebimentofisicopedidocompra`, `notafiscalcontapagar`, `extratobancarioconciliacao` |
| `pagamentovenda<modalidade>` | Detalhe do pagamento por modalidade | `pagamentovendacartao`, `pagamentovendacheque`, `pagamentovendacrediario`, `pagamentovendapbm`, `pagamentovendavalecompra`, `pagamentovendafidelidade` |
| `<entidade>id` | FK | `embalagemid`, `unidadenegocioid`, `pessoaid` |
| `datahora<evento>` | Timestamp do evento | `datahorafechamento`, `datahoraentrada`, `datahoraemissao`, `datahorainicial`, `datahorafinal`, `datahorainclusao` |
| `valor<coisa>` | Numeric monetário | `valortotal`, `valorunitario`, `valordesconto`, `valordocumento` |

## Siglas e jargão da rede

| Sigla / termo | Significado |
| --- | --- |
| **C.M.P.** | Custo da Mercadoria **Paga** — o DRE em regime de caixa (`dre.categoria = '2 - C.M.P.'`) |
| **CMV** | Custo da Mercadoria Vendida (custo ÷ receita líquida) |
| **ROB / ROL** | Receita Operacional Bruta / Líquida |
| **PMC** | Preço Máximo ao Consumidor (`embalagem.precoreferencial`) |
| **PMV** | **Prazo Médio de Vencimento** (`datavencimento − dataemissao` de `contapagar`) — ⚠️ **não** é "preço médio de venda" |
| **PME / PMR / PMP** | Prazo Médio de Estoque / Recebimento / Pagamento |
| **CCC** | Ciclo de Conversão de Caixa (PME + PMR − PMP) |
| **MC** | Margem de Contribuição |
| **Sell-in** | Compras (o que a rede comprou do fabricante) |
| **Sell-out** | Venda ao consumidor final |
| **PBM** | Programa de Benefício em Medicamentos |
| **RFM / RFV** | Recência, Frequência, Valor — segmentação de cliente |
| **Curva ABC/D** | Classificação de giro; **D** = praticamente não vende |
| **Ruptura** | Produto com demanda recente e estoque ≤ 0 |
| **Cobertura** | Dias que o estoque atual dura no ritmo de venda |
| **Excesso estrutural** | Cobertura > 90 dias (ou zero venda em 90d) em ≥ metade das lojas |
| **Demanda reprimida** | Fabricante sem pedido de compra há 60+ dias, com queda de venda medida antes/depois do último pedido |
| **Leadtime de entrada** | Emissão → entrada física da NF (fornecedor) · envio → recebimento (transferência) |
| **Tempo de execução** | Solicitação do pedido de transferência → primeira transferência finalizada |
| **Tempo de separação** | Solicitação do pedido → emissão da nota de transferência |
| **Malote** | Dinheiro sangrado do caixa e depositado (`depositosangria`) |
| **Quebra de caixa** | Diferença no fechamento (`valor < 0` = falta, `> 0` = sobra) |
| **Caderno de oferta** | Campanha/tabela de preço (⚠️ mistura promoção, convênio, canal, preço controlado) |
| **Panfleto / encarte** | A promoção de marketing de verdade (`nome ILIKE 'PANFLETO%'`) |
| **Grupo de remarcação** | Conjunto de SKUs que sobem/descem de preço juntos |
| **Preço quebrado** | Preço cujos centavos não são `,90` nem `,99` (~89% do catálogo termina num dos dois) |
| **Margem objetiva** | Margem-alvo por categoria/subcategoria (cadastro externo ao ERP) |
| **Elasticidade** | `%Δquantidade ÷ %Δpreço` |
| **Crediário / convênio** | `crediarioreceber` — "convênio" não existe como campo |
| **Bonificação** | `itemnotafiscal.bonificacao` (⚠️ checar também `valorunitario > 0,01`) |
