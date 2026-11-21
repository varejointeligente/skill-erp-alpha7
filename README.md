# erp-alpha7

Skill do Claude com a base de conhecimento do **ERP Alpha 7** — ERP de varejo farmacêutico, banco
**PostgreSQL**, bases no padrão `<cliente>_esc_<data>`.

Serve para atendimento de suporte e consultoria: quando alguém pede um relatório, questiona um
número ou pergunta "de onde sai esse campo", o Claude passa a responder a partir do que já foi
medido contra bancos reais, em vez de deduzir pelo nome das colunas.

## Instalar

Este repositório é um plugin do Claude e também o seu próprio marketplace — um comando adiciona,
outro instala.

**Claude Code:**

```
/plugin marketplace add varejointeligente/skill-erp-alpha7
/plugin install erp-alpha7@varejointeligente-alpha7
```

**Cowork (app desktop):** Customize → Plugins → Add marketplace → cole
`varejointeligente/skill-erp-alpha7` → Browse plugins → Install.

A skill passa a ser acionada sozinha quando a conversa envolve o Alpha 7; não é preciso invocá-la
pelo nome. Atualizações chegam por `/plugin marketplace update` (ou automaticamente, se o
auto-update estiver ligado).

## Conteúdo

```
.claude-plugin/
  plugin.json                     metadados do plugin
  marketplace.json                torna o próprio repositório instalável
skills/erp-alpha7/
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
    12-operar-pelo-cli.md         gravar no ERP pelas facades: grupo de consumidores, caderno de oferta
  scripts/
    consultar_alpha7.py           consulta somente leitura no PostgreSQL
    alpha7_credenciais.py         janela de login (servidores do A7Pharma, usuário, senha); grava um perfil local
    alpha7_cli.py                 executa o CLI das facades do servidor de aplicação
    alpha7-cli.jar                o CLI (Java 17) — vem pronto na instalação
```

## Consultar o banco

```bash
pip install psycopg2-binary
export A7_HOST=... A7_PORT=5432 A7_USER=usuario_leitura A7_PASSWORD=...
python skills/erp-alpha7/scripts/consultar_alpha7.py --bases                    # achar a base `_esc_` corrente
export A7_DATABASE=cliente_esc_20260101
python skills/erp-alpha7/scripts/consultar_alpha7.py "SELECT * FROM unidadenegocio ORDER BY 1"
python skills/erp-alpha7/scripts/consultar_alpha7.py --tabelas itemvenda
```

O script abre a sessão em modo *read-only*, fixa o fuso em `America/Sao_Paulo` e recusa qualquer
comando que não seja leitura. Isso importa mais aqui do que no normal: o Alpha 7 praticamente não
tem foreign key nem check constraint declarados, então uma escrita acidental não bate em nenhuma
rede de proteção.

> O nome da base **rotaciona** — o Alpha 7 troca a data periodicamente. Se uma conexão que
> funcionava parou, confira `--bases` antes de investigar a query.

## Operar o ERP (gravar)

Para gravar, a skill não usa SQL: usa o **CLI das facades** do servidor de aplicação do Alpha 7 —
as mesmas operações da tela do A7Pharma, com validação, permissão e log do ERP. Hoje cobre grupo
de consumidores (criar grupo, vincular e remover pessoas), transferência entre lojas (incluir
produto na sugestão e gerar o pedido), cadastro de cliente, caderno de oferta e a chamada
genérica de qualquer facade.

```
python skills/erp-alpha7/scripts/alpha7_credenciais.py      # janela de login: servidor (lista do A7Pharma), usuário e senha
python skills/erp-alpha7/scripts/alpha7_cli.py --preparar   # confere libs, Java e o CLI
python skills/erp-alpha7/scripts/alpha7_cli.py cadastrar-grupo-consumidores --stdin-file grupo.json --confirmar-escrita
```

(`python3` no Linux/macOS.) No uso normal ninguém digita esses comandos: o Claude abre a janela de
acesso e roda o CLI; a pessoa só preenche a janela e confirma as gravações. O que precisa na máquina:

- **A7Pharma instalado** (as libs do cliente e o JRE 17 saem dele). Sem a instalação, o script
  baixa as libs do servidor da rede e precisa de um Java 17+.
- **Nada para compilar ou instalar à parte**: o `alpha7-cli.jar` vem junto na instalação do plugin.
- **Rede até o servidor de aplicação** do Alpha 7 (porta 8443 por padrão).

O perfil de credenciais fica em `%APPDATA%\erp-alpha7\` (Windows) ou `~/.config/erp-alpha7/`, fora
do repositório. Todo comando que grava exige `--confirmar-escrita`. Detalhes, regras e roteiros em
[`references/12-operar-pelo-cli.md`](skills/erp-alpha7/references/12-operar-pelo-cli.md).

Os comandos de grupo de consumidores foram validados contra um ERP de produção: criar, vincular,
pular repetido, listar, remover pessoa, inativar e excluir. Só a entrada por CPF ainda não.
A transferência entre lojas também: incluir, alterar e excluir sugestão, gerar e excluir o pedido.

## Manter viva

Quando aparecer uma armadilha nova, registre em `references/10-armadilhas.md` no mesmo formato,
com o caso concreto e o número medido. Vários pontos estão marcados como incertos — trate a marca
como pedido de conferência contra a tela do ERP, e atualize a referência quando confirmar.

Lacunas conhecidas:

- **Status não decodificados:** `pedidocompra.status` (7 de 8 valores), `pedidocompra.origem`,
  `itemtransferencia.status`, `liberacaousuario.tipo`, `devolucaocompra.status`.
- **`venda.status = 'G'`** — só o volume foi medido (~23 mil); o significado **não** está
  confirmado (o rótulo "Estornada" vem do `G` de `itemvenda`, outra tabela).
- **`itemvenda.origemdesconto = 'F'`** — existe na base e não aparece em nenhum dos mapeamentos
  observados de `origemdesconto`.
- **`tipomovimentacaoestoque`: id ↔ `codigo` nunca foi verificado.** Os ids (com descrição) e os
  códigos (`RF`, `VND`, `EVND`…) vêm de fontes diferentes e **nenhuma faz o join**. Um
  `SELECT id, codigo, descricao FROM tipomovimentacaoestoque` fecha essa lacuna.
- **`alteracaopreco`:** sabe-se que `precoreferencial` é gravado com o mesmo valor como anterior e
  posterior, mas os **nomes dessas duas colunas** não estão registrados — conferir no
  `information_schema` antes de qualquer `INSERT`.
- `entrega.status` tem **dois mapeamentos conflitantes** — o validado operacionalmente e outro
  observado numa extração — ainda não reconciliados. Eles se contradizem justamente em `C` e `E`.
- A tabela `historicovenda` (agregado de venda por loja+embalagem+data, pré-computado pelo ERP) foi
  descoberta numa extração mas **nunca teve cobertura medida** — não usar como fonte de demanda
  antes de comparar um mês dela contra `venda + itemvenda`.
- **Profundidade do `planocontas.caminho`:** há registro de extrações lendo os níveis em índices de
  `split_part` diferentes (2/3/4 × 3/4/5/6), o que sugere uma raiz a mais em alguma base. Qual é a
  forma corrente não foi confirmado.

## Origem e privacidade

Destilado de documentação de projeto real de uma rede de farmácias e de extrações SQL rodadas contra
o banco do próprio ERP. **A skill é deliberadamente neutra quanto a cliente** — serve para qualquer
rede que rode o Alpha 7.

O que **fica**: estrutura de tabela, significado de coluna, semântica de `char(1)`, fórmula,
armadilha estrutural, comportamento do PostgreSQL nessa base, e os **casos concretos com número
medido** (volume, tempo de query, percentual) — é isso que ensina.

O que **saiu**: nome da rede, nomes reais de banco de produção, cidades e nomes de loja, clientes
nominados (PJ e PF), telefones, a carteira de convênios/canais de uma rede específica, ids de
unidade de negócio e códigos de loja de um cliente, e a **infraestrutura analítica de um cliente
específico** (ferramenta, orquestração, modelagem própria) — que não faz parte do Alpha 7 e não
existe na maioria das redes; o que essas extrações ensinaram **sobre o ERP** foi preservado nos
arquivos de área. Onde o exemplo era necessário para a lição, ele
foi substituído por placeholder (`redefarmacias_esc_<data>`, `CIDADE_A`, `MARKETPLACE_A`,
`<LOJA_FORA>`, telefone fictício) **preservando o formato e os números medidos**. Nomes de pessoas
foram substituídos por "o gestor"; não há credenciais, hosts nem IPs nos arquivos.

⚠️ Ao usar a skill num cliente novo, tudo que estiver marcado como cadastro do cliente (códigos de
unidade, categorias de `classificacao`, formas de pagamento, cadernos de oferta, convenção de preço
quebrado) **precisa ser levantado por query naquela base** — não é conhecimento do ERP.

## Licença

MIT — ver [LICENSE](LICENSE).
