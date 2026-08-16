# erp-alpha7

Skill do Claude com a base de conhecimento do **ERP Alpha 7** — ERP de varejo farmacêutico, banco
**PostgreSQL**, bases no padrão `<cliente>_esc_<data>`.

Serve para atendimento de suporte e consultoria: quando alguém pede um relatório, questiona um
número ou pergunta "de onde sai esse campo", o Claude passa a responder a partir do que já foi
medido contra bancos reais, em vez de deduzir pelo nome das colunas.

## Conteúdo

```
SKILL.md                        instruções e índice das referências
references/
  01-visao-geral.md             pessoa, embalagem, convenções, mapa de relacionamentos
  02-vendas.md                  venda, itemvenda, pagamento, devolução, canal, vendedor, métricas
  03-produto-embalagem.md       produto, apresentação/SKU, classificação, preço, custo, curva ABC
  04-estoque.md                 estoque, movimentação, mín/máx, ruptura, perdas, transferência
  05-pessoas-clientes.md        pessoa, cliente, prescritor, receita, farmacêutico, busca
  06-financeiro.md              contas a pagar/receber, crediário, cartão, plano de contas, DRE
  07-compras-precificacao.md    pedido de compra, NF, caderno de oferta, alteração de preço
  08-logistica-entregas.md      entrega, remessa, endereço, unidades de negócio
  09-consultas-e-performance.md joins canônicos, performance, conexão, Postgres nessa base
  10-armadilhas.md              60+ casos reais: sintoma → causa → correção → prevenção
  11-glossario.md               vocabulário do negócio ↔ tabela/coluna/valor
  12-dw-pentaho.md              modelo dimensional e queries de um DW já construído sobre o ERP
scripts/
  consultar_alpha7.py           consulta somente leitura no PostgreSQL
```

## Instalar

```bash
zip -r erp-alpha7.skill . -x '.git/*'
```

## Consultar o banco

```bash
pip install psycopg2-binary
export A7_HOST=... A7_PORT=5432 A7_USER=usuario_leitura A7_PASSWORD=...
python scripts/consultar_alpha7.py --bases                    # achar a base `_esc_` corrente
export A7_DATABASE=cliente_esc_20260101
python scripts/consultar_alpha7.py "SELECT * FROM unidadenegocio ORDER BY 1"
python scripts/consultar_alpha7.py --tabelas itemvenda
```

O script abre a sessão em modo *read-only*, fixa o fuso em `America/Sao_Paulo` e recusa qualquer
comando que não seja leitura. Isso importa mais aqui do que no normal: o Alpha 7 praticamente não
tem foreign key nem check constraint declarados, então uma escrita acidental não bate em nenhuma
rede de proteção.

> O nome da base **rotaciona** — o Alpha 7 troca a data periodicamente. Se uma conexão que
> funcionava parou, confira `--bases` antes de investigar a query.

## Manter viva

Quando aparecer uma armadilha nova, registre em `references/10-armadilhas.md` no mesmo formato,
com o caso concreto e o número medido. Vários pontos estão marcados como incertos — trate a marca
como pedido de conferência contra a tela do ERP, e atualize a referência quando confirmar.

Lacunas conhecidas: `pedidocompra.status` (7 de 8 valores), `itemtransferencia.status`,
`liberacaousuario.tipo`, `devolucaocompra.status`; `entrega.status` tem **dois mapeamentos
conflitantes** (operacional × DW) ainda não reconciliados; a tabela `historicovenda` foi
descoberta mas nunca teve cobertura medida.

## Origem e privacidade

Destilado de documentação de projeto real de uma rede de farmácias e das transformações Pentaho de
um data warehouse construído sobre o mesmo ERP. Nomes de pessoas foram substituídos por "o gestor";
não há credenciais, hosts nem IPs nos arquivos.
