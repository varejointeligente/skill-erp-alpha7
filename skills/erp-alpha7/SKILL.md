---
name: erp-alpha7
description: Base de conhecimento do ERP Alpha 7, o ERP de farmácia cujo banco é PostgreSQL em bases nomeadas no padrão cliente_esc_data. Use SEMPRE que aparecer "Alpha 7", "Alpha7", "base _esc_", ou tabelas/colunas desse ERP — `pessoa`, `embalagem`, `venda`, `itemvenda`, `unidadenegocio`, `movimentacaoestoque`, `precoembalagemunidadenegocio`, `estoqueminimoprodutounidadenegocio`, `cadernooferta`, `contapagar`, `pedidocompra`, `orcamento`, `liberacaousuario`, `dre`. Use também, mesmo sem o ERP ser nomeado, quando a tarefa for escrever ou revisar SQL/relatório de farmácia sobre faturamento, margem, CMV, ruptura, cobertura, giro, curva ABC, elasticidade, mínimo/máximo por loja, transferência entre lojas, entregas, crediário, contas a pagar/receber, DRE, caderno de ofertas, alteração de preço ou comissão de vendedor — e o banco for PostgreSQL. Use ainda quando o pedido for OPERAR o Alpha 7 (gravar, não só consultar): criar grupo de consumidores/grupo de clientes e pôr clientes nele, incluir produto em sugestão de transferência entre lojas e gerar o pedido de transferência, cadastrar cliente, criar ou alterar caderno de oferta — isso é feito pelo CLI das facades do servidor, não por SQL. Consulte antes de escrever a query — nesse ERP quase tudo passa por `pessoa` e por `embalagem`, e ignorar essas duas camadas produz número errado sem erro aparente.
---

# ERP Alpha 7 — base de conhecimento

Este skill carrega o que já foi aprendido, medindo contra bancos reais, sobre o schema do Alpha 7.
Ele existe porque duas decisões de modelagem desse ERP — a tabela `pessoa` e a camada `embalagem` —
atravessam praticamente toda consulta, e quem não as conhece escreve SQL que roda, retorna, e
mente.

## Como usar

**Leia a referência da área antes de escrever SQL.** O schema é grande, antigo, quase sem foreign
keys declaradas, e o significado de cada `char(1)` depende da tabela — nada disso é adivinhável.

| Você precisa de… | Leia |
| --- | --- |
| Os dois conceitos-chave, convenções, mapa de relacionamentos | `references/01-visao-geral.md` |
| Venda, item, pagamento, devolução, canal, vendedor, ticket, margem | `references/02-vendas.md` |
| Produto, apresentação/SKU, classificação, preço por loja, custo, curva ABC | `references/03-produto-embalagem.md` |
| Estoque, movimentação, mínimo/máximo, ruptura, perdas, transferência | `references/04-estoque.md` |
| Cliente, prescritor, receita, farmacêutico, usuário, busca por nome/CPF | `references/05-pessoas-clientes.md` |
| Contas a pagar/receber, crediário, cartão, plano de contas, DRE, tesouraria | `references/06-financeiro.md` |
| Pedido de compra, nota fiscal, caderno de oferta, negociação, alteração de preço | `references/07-compras-precificacao.md` |
| Entrega, remessa, endereço, unidades de negócio | `references/08-logistica-entregas.md` |
| Performance, joins canônicos, conexão, particularidades do Postgres | `references/09-consultas-e-performance.md` |
| "Por que esse número está errado?" | `references/10-armadilhas.md` |
| O gestor usou um termo que você não reconhece | `references/11-glossario.md` |
| **Gravar** no ERP: grupo de consumidores, transferência entre lojas, cadastro de cliente, caderno de oferta, qualquer facade | `references/12-operar-pelo-cli.md` |

Quando a tarefa cruza áreas, leia as duas — a interseção é onde moram os erros.

## As cinco regras que valem para qualquer query

1. **Tudo que é gente passa por `pessoa`.** `cliente`, `fornecedor`, `fabricante`, `prescritor` e
   afins são papéis com `pessoaid` apontando para a tabela central. Nome, CPF e CNPJ moram lá,
   não na tabela de papel. Há exceções que ligam direto em `produtoid` — estão listadas na visão
   geral.

2. **Tudo que é produto passa por `embalagem`.** O que se vende é a apresentação (SKU), não o
   produto. Mas nem tudo segue a mesma granularidade: estoque é por embalagem+loja, enquanto
   mínimo, custo e curva ABC são por produto+loja. Misturar os dois níveis num mesmo `GROUP BY`
   é a fonte mais comum de número inflado.

3. **`venda.usuarioid` não é o vendedor.** Quem vendeu vem de `orcamento`/`itemorcamento`, com uma
   cascata de fallback. Atribuir comissão pelo `usuarioid` faz vendedor sumir do relatório inteiro,
   não apenas ficar com número errado.

4. **O nome da base muda sozinho.** As bases seguem `<cliente>_esc_<data>` e são rotacionadas
   periodicamente pelo próprio Alpha 7. String de conexão fixa quebra sem aviso — confirme a base
   corrente antes de culpar a query.

5. **O fuso da sessão é `America/Sao_Paulo`, mesmo quando a loja não está nele.** `CURRENT_DATE` e
   `NOW()::date` mentem para operações em UTC-4. Sempre explicite o fuso ao cortar período.

## Conhecimento do ERP × cadastro do cliente

Estas referências valem para **qualquer rede que rode o Alpha 7**. Estrutura de tabela, significado
de coluna, semântica de `char(1)`, fórmula e armadilha estrutural são do ERP e podem ser aplicadas
direto. Já **códigos e ids de unidade de negócio, formas de pagamento, nomes de caderno de oferta,
categorias de `classificacao` e convenções comerciais** (terminação de preço, margem objetiva,
quais lojas excluir) são **cadastro de cada cliente** — os exemplos aqui usam placeholders e o valor
real precisa ser levantado por query na base em uso. Nunca copiar um id ou um código de loja de um
cliente para outro.

## Antes de dar um número como certo

Existem métricas já validadas com gestores de rede — receita bruta e líquida, CMV, margem, cupons,
ticket, ruptura, cobertura, giro, elasticidade — com fórmula exata e o *porquê* de cada escolha de
denominador. Use essas fórmulas em vez de improvisar uma: elas são o que faz o seu número bater
com o que o cliente já aceitou como verdade. Estão em `references/02-vendas.md` e
`references/04-estoque.md`.

Parte do que está registrado veio de **extrações SQL já rodadas contra o banco**, não de validação
ao vivo com o gestor — esses pontos estão marcados como "observado numa extração, não validado ao
vivo". Trate-os como ponto de partida a conferir, não como fato: onde uma extração diverge do que
foi validado operacionalmente (o caso mais grave é `entrega.status`), a divergência está anotada no
próprio ponto.

## Ao validar contra o cliente

Quando o cliente disser que um número está errado, vá ao dado cru: isole **uma** linha que ele
apontou e compare campo a campo. As divergências já catalogadas tiveram causa estrutural — join no
nível errado de granularidade, `COALESCE` faltando, pessoa jurídica poluindo ranking, fuso,
`status` mal decodificado. Nenhuma era arredondamento.

Ao encontrar causa nova, registre em `references/10-armadilhas.md` no formato
sintoma → causa → correção → como evitar, com o caso concreto e o número medido. O caso concreto é
o que ensina.

Alguns campos de `status` ainda estão parcialmente decodificados e vários pontos estão marcados
como incertos nas referências. Trate marca de incerteza como pedido de conferência contra a tela do
ERP, não como detalhe — e atualize a referência quando confirmar.

## Consultando o banco

`scripts/consultar_alpha7.py` abre conexão **somente leitura** no PostgreSQL e imprime o resultado
em tabela ou JSON. Antes de rodar consulta pesada, leia
`references/09-consultas-e-performance.md`: nessa base há queries que passam de 14 minutos por uma
escolha de operador, e alternativas ~1.700× mais rápidas para o mesmo resultado.

Consulta de leitura para conferir dado é livre. **Escrita direto no banco é possível e já foi
feita** (alteração de preço), mas o banco quase não tem constraint declarada: quem escreve precisa
replicar as invariantes à mão, e isso exige confirmação explícita do cliente antes — as invariantes
estão em `references/07-compras-precificacao.md`. Quando existe facade para a operação, grave por
ela (seção seguinte), não por SQL.

## Operando o ERP (gravar)

`scripts/alpha7_cli.py` chama as facades do servidor de aplicação do Alpha 7 — as mesmas operações
da tela do A7Pharma, com a validação, a permissão e o log do ERP. É o caminho para gravar: criar
grupo de consumidores e vincular pessoas, solicitar transferência entre lojas, cadastrar cliente,
criar e alterar caderno de oferta, ou
chamar qualquer outra facade. **Leia `references/12-operar-pelo-cli.md` antes da primeira chamada**
— o nome do campo no JSON tem regra própria e campo errado é descartado sem erro.

O padrão é **SQL acha, CLI grava, SQL confere**: levante os ids por consulta, grave pelo CLI e
confira o resultado por consulta.

Três regras que não se negociam:

- **Credencial é digitada pela pessoa, numa janela que você abre.** Se o perfil não existir,
  avise o usuário e execute `scripts/alpha7_credenciais.py`: abre uma janela como a do login do
  A7Pharma (lista de servidores, usuário e senha), e a senha vai direto para o perfil local. Não peça senha na conversa, não leia
  o arquivo do perfil, e não mande o usuário rodar comando — ele não é técnico.
- **Toda gravação exige `--confirmar-escrita`, e a flag só entra depois do "pode" do usuário**, com
  o que será gravado e o servidor de destino à vista. É o ERP de produção; não há ambiente de teste.
- **Escrita não se repete às cegas.** Falhou ou estourou o tempo: confira o que ficou gravado antes
  de tentar de novo.

A maioria das redes roda Windows: chame com `python` (não `python3`) e passe o payload por
`--stdin-file`, nunca JSON entre aspas na linha de comando.
