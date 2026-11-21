# Operar o ERP pelo CLI (facades do servidor de aplicação)

## Sumário

- [Quando usar o CLI e quando usar SQL](#quando-usar-o-cli-e-quando-usar-sql)
- [Preparação: credenciais e runtime](#preparação-credenciais-e-runtime)
- [Como chamar](#como-chamar)
- [Regras que valem para toda chamada](#regras-que-valem-para-toda-chamada)
- [Grupo de consumidores (grupo de clientes)](#grupo-de-consumidores-grupo-de-clientes)
- [Transferência entre lojas (sugestão e pedido)](#transferência-entre-lojas-sugestão-e-pedido)
- [Caderno de oferta](#caderno-de-oferta)
- [Chamar uma facade que não está aqui](#chamar-uma-facade-que-não-está-aqui)
- [Erros comuns](#erros-comuns)

---

## Quando usar o CLI e quando usar SQL

O Alpha 7 tem duas portas: o **PostgreSQL** (onde `consultar_alpha7.py` lê) e o **servidor de
aplicação**, que expõe as mesmas operações que a tela do A7Pharma usa (facades EJB).
`scripts/alpha7_cli.py` fala com a segunda.

| Tarefa | Caminho |
| --- | --- |
| Ler, medir, conferir, montar relatório | **SQL**, somente leitura. É mais rápido e não depende de permissão de tela. |
| Gravar (cadastrar, vincular, editar, excluir) | **CLI**. O ERP aplica validação, permissão do usuário, geração de id e log de auditoria — tudo o que um `INSERT` direto teria de replicar à mão num banco sem FK nem CHECK. |
| Descobrir os ids que a gravação precisa (pessoa, embalagem, loja) | **SQL**, e depois o CLI com os ids em mãos. |

A combinação é o padrão: **SQL acha, CLI grava, SQL confere**.

Tudo o que o CLI grava vai para o ERP de produção da rede, no nome do usuário do perfil. Não há
ambiente de ensaio.

---

## Preparação: credenciais e runtime

**Credenciais: você abre a janela, a pessoa preenche.** Quem usa a skill não sabe (nem precisa)
rodar script. Execute você mesmo:

```
python scripts/alpha7_credenciais.py            (python3 no Linux/macOS)
python scripts/alpha7_credenciais.py --perfil redeX     um perfil por rede/servidor
```

Isso abre uma **janela igual ao login do A7Pharma**: uma lista com os servidores cadastrados no
A7Pharma daquela máquina (os mesmos nomes que a pessoa vê ao entrar no sistema), usuário e senha.
Ninguém digita endereço ou porta. Antes de executar, avise: "vou abrir uma janela para você entrar
no Alpha 7 — escolha o servidor e use o mesmo usuário e senha do A7Pharma". Só quando não há
A7Pharma instalado (ou nenhum servidor cadastrado nele) a janela pede endereço e porta. O comando fica parado até a pessoa salvar ou fechar (a janela se
fecha sozinha em 10 minutos): rode com tempo limite de 10 minutos. A saída diz `gravado: …` ou
`cancelado: …` — nunca a senha.

- **Não peça a senha na conversa, não abra o arquivo do perfil, não passe credencial por
  argumento** (`alpha7_cli.py` recusa `--user`/`--pass`). A janela existe para a senha não passar
  pelo chat.
- `--mostrar` lista o que está gravado, com os segredos ocultos — use para saber se o perfil
  existe e para qual servidor aponta. `alpha7_cli.py --servidores` lista os servidores cadastrados
  no A7Pharma, sem chamar o ERP.
- Rede com mais de um servidor (matriz e lojas): confirme com o usuário **em qual** a gravação
  deve acontecer antes de abrir a janela, e use um `--perfil` por servidor.
- O perfil fica em `%APPDATA%\erp-alpha7\<perfil>.env` (Windows) ou `~/.config/erp-alpha7/`.
- Sem tela gráfica (sessão remota por SSH, servidor), a janela não abre e o script explica a
  alternativa: a pessoa roda `alpha7_credenciais.py --terminal` no terminal dela.
- Login recusado depois: abra a janela de novo — ela vem preenchida, basta redigitar a senha.

O servidor precisa ser alcançável da máquina onde o script roda — na prática, se o A7Pharma
daquela máquina abre naquele servidor, o CLI também alcança.

Com o A7Pharma instalado na máquina não há mais nada a instalar além do Python.

**Runtime: o script acha sozinho.** `python scripts/alpha7_cli.py --preparar` mostra o que foi
encontrado, sem chamar o ERP:

| Precisa de | De onde vem |
| --- | --- |
| Libs do cliente (~94 jars) | Da instalação do A7Pharma na máquina (`C:\Alpha7\A7Pharma`, `/opt/Alpha7/A7Pharma`, `~/Alpha7/A7Pharma` ou `A7PHARMA_HOME`). Sem instalação, são baixadas do próprio servidor da rede — aí o perfil precisa das credenciais do WS de atualização (`alpha7_credenciais.py --terminal --tecnicas`, tarefa de quem dá suporte, não do usuário final). |
| Java 17+ para executar | O JRE que vem dentro do A7Pharma (`jre/jre_17*`), ou um `java` 17+ da máquina. |
| O CLI | `scripts/alpha7-cli.jar`, que já vem com a skill. |

As libs têm de ser da **mesma versão do servidor**: o protocolo trafega objetos Java serializados,
e versão diferente falha de forma difícil de diagnosticar. A7Pharma instalado e atualizado contra
aquele servidor resolve; se a máquina tem um A7Pharma de outra rede, use `--baixar-libs`.

> O download das libs pelo script (sem A7Pharma instalado) foi escrito espelhando o auto-update
> do cliente, mas **ainda não foi exercitado contra um servidor**. O caminho testado é o da
> instalação local.

---

## Como chamar

```
python scripts/alpha7_cli.py <comando> [argumentos] --stdin-file payload.json [--confirmar-escrita] [--perfil X]
```

Escreva o payload num arquivo e passe com `--stdin-file`: funciona igual em Windows, Linux e macOS.
`--stdin '<json>'` existe, mas as aspas do JSON brigam com o cmd e o PowerShell.

A saída é JSON: `{"result": ...}` com exit 0, ou `{"error": "Classe: mensagem"}` com exit 1.

| Comando | Payload | O que faz |
| --- | --- | --- |
| `invoke <Dominio> <metodo>` | `{"args":[...]}` | Chama qualquer método de facade |
| `entity-get <Tipo> <id>` | — | DTO por id |
| `entity-create <Tipo>` | `{campos}` | Cria entidade (campos escalares) |
| `entity-update <Tipo> <id>` | `{campos que mudam}` | Edita |
| `entity-delete <Tipo> <id>` | — | Remove |
| `cadastrar-grupo-consumidores` | `{nome, status, pessoas:[ids], cpfs:[...]}` | Cria grupo de consumidores e vincula pessoas |
| `grupo-consumidores-add <idGrupo>` | `{pessoas:[ids], cpfs:[...]}` | Vincula pessoas a um grupo existente |
| `grupo-consumidores-pessoas <idGrupo>` | — | Lista as pessoas do grupo (id, nome, CPF) |
| `grupo-consumidores-remove <idGrupo>` | `{pessoas:[ids], cpfs:[...]}` | Tira pessoas do grupo |
| `unidades-negocio` | — | Lojas ativas (id, código, nome) |
| `transferencia-sugestoes` | — | Sugestões de transferência do usuário do perfil |
| `transferencia-sugestao-add` | `{origemCodigo, destinosCodigos:[...], itens:[{produtoId\|codigoBarras, quantidade}]}` | Inclui produtos na sugestão de transferência |
| `transferencia-gerar-pedidos` | `{origemCodigo, destinosCodigos:[...], itensEsperados}` | Gera o pedido de transferência a partir das sugestões |
| `cadastrar-cliente` | `{nome, cpf, sexo, dataNascimento, ...}` | Cadastro rápido de pessoa/cliente |
| `cadastrar-caderno` | `{nome, dataHoraInicial, dataHoraFinal, unidadesNegocio:[ids], itens:[...]}` | Cria caderno de oferta + lojas + itens |
| `caderno-item-add <idCaderno>` | `{itens:[{embalagemId\|codigoBarras, tipoOferta, precoOferta\|descontoOferta, leve, pague}]}` | Acrescenta ofertas a um caderno |

`<Dominio>`/`<Tipo>` é o nome da entidade sem sufixo: `GrupoConsumidores`, `Pessoa`,
`CadernoOferta`, `Embalagem`.

**Todo comando que grava exige `--confirmar-escrita`.** O script trata como leitura só
`entity-get` e `invoke` cujo método começa por `find`, `get`, `busca`, `checa` e afins; o resto é
recusado sem a flag. Antes de usá-la, mostre ao usuário **o que** será gravado e **em qual
servidor** (`--preparar` mostra o host do perfil) e espere o "pode".

---

## Regras que valem para toda chamada

1. **Nome de campo no JSON: sigla inicial em minúsculas.** O campo começa em minúscula, e uma
   sigla no começo do nome vai inteira em minúsculas: `id`, `cpf`, `nome`, `dataHoraInicial`.
   **Campo com nome errado não dá erro: é descartado em silêncio.** Medido: `{"ID": 5}` chega como
   id 0 e `{"CPF": "..."}` chega como CPF vazio; `{"id": 5}` e `{"cpf": "..."}` funcionam. O mesmo
   vale na resposta — o id volta em `id`.

2. **Escrita não se repete às cegas.** Se a chamada falhar no meio, estourar o tempo ou a conexão
   cair, a gravação pode ter acontecido. Confira (por SQL ou por uma leitura no CLI) antes de
   tentar de novo: repetir `cadastrar-caderno` cria caderno duplicado, repetir `caderno-item-add`
   duplica a oferta.

3. **Leitura: prefira o método que devolve DTO** (`find…DTO…`, `findDTOByID`, `…FinderDTOs`).
   Método que devolve a entidade crua (`findEntityByID`, `findAllEntities`, `getPessoaPorCPF`)
   costuma estourar `LazyInitializationException` ao virar JSON — e o erro chega como
   `{"error": ...}`. Para ler, o SQL quase sempre é o caminho melhor.

4. **`entity-update` aplica o JSON por cima do registro do ERP.** Mande **só os campos que
   mudam**. Campo enviado vazio não é "deixa como está", é apagar.

5. **Relacionamento não se monta do JSON.** Uma entidade que aponta para outra (item → caderno,
   vínculo → grupo e pessoa) precisa das pontas carregadas do ERP. É por isso que existem os
   comandos dedicados (`caderno-item-add`, `grupo-consumidores-add`): eles buscam cada ponta por id
   antes de gravar. Via `entity-create` com `{"grupoConsumidores": {"id": 5}}` o resultado **não foi
   validado** — use o comando dedicado.

6. **`invoke` escolhe a sobrecarga pela quantidade de argumentos.** Um argumento a mais ou a menos
   é outro método, ou nenhum (`NoSuchMethodException`). O token de sessão não entra em `args`: o CLI
   injeta.

7. **`char` é texto de um caractere; `Date` é ISO-8601** (`"2026-09-04"` ou
   `"2026-09-04T08:00:00"`) ou epoch em milissegundos. Nunca o formato brasileiro. O significado de
   cada código de uma letra é do ERP e depende da entidade.

8. **A permissão é a do usuário do perfil.** `PermissionException: User has insufficient
   privileges` significa que o usuário do ERP não tem aquela permissão de tela — é ajuste no
   cadastro de usuário do Alpha 7, não no script.
   que um usuário.

9. **Chamada sem filtro em tabela grande não volta.** `findAllDTOs`/`findAllEntities` em entidade
   volumosa (pessoa, vínculos) trava até o tempo limite. Use os métodos com filtro ou SQL.

---

## Grupo de consumidores (grupo de clientes)

O que a tela chama de **Grupo de Consumidores** é o agrupamento de pessoas usado para direcionar
caderno de oferta e regras de fidelidade. No ERP:

| Entidade (CLI) | Tabela | Campos |
| --- | --- | --- |
| `GrupoConsumidores` | `grupoconsumidores` | `id`, `nome` (**único**), `status` (`A` ativo, `I` inativo), `datahorainclusao`, `usuarioinclusao` (→ `usuario.id`) |
| `PessoaGrupoConsumidores` | `pessoagrupoconsumidores` | `id`, `grupoconsumidorid` (→ grupo), `pessoaconsumidorid` (→ **`pessoa.id`**) |
| `CadernoOfertaGrupoConsumidores` | `cadernoofertagrupoconsumidores` | vínculo grupo ↔ caderno de oferta |

Os nomes de tabela e coluna acima **ainda não foram conferidos numa base** — confirme no
`information_schema` antes de escrever a primeira query (em especial `usuarioinclusao`, que pode
aparecer com sufixo `id`).

**Quem participa do grupo é a pessoa, não o cliente.** O vínculo guarda `pessoa.id`. Partindo de
clientes, converta antes: `SELECT pessoaid FROM cliente WHERE id IN (...)`. Passar id de cliente
onde se espera id de pessoa não dá erro quando o número coincide com outra pessoa — vincula a
pessoa errada.

### Roteiro

**1. Levantar as pessoas (SQL).** Monte a lista de `pessoa.id` com `consultar_alpha7.py` e mostre
ao usuário quantas são e uma amostra com nome.

**2. Ver se o grupo já existe.** O nome é único; criar de novo devolve erro de validação.

```
alpha7_cli.py invoke GrupoConsumidores findGrupoConsumidoresFinderDTOs --stdin-file p.json
p.json: {"args": ["VIP", 20, true]}
```

Os argumentos são: início do nome, limite, e incluir inativos. Com `false` no terceiro, grupo
inativo não aparece — e parece que não existe. Por SQL:
`SELECT id, nome, status FROM grupoconsumidores WHERE nome ILIKE 'VIP%'`.

**3. Criar o grupo.**

```
alpha7_cli.py cadastrar-grupo-consumidores --stdin-file p.json --confirmar-escrita
p.json: {"nome": "CLIENTES VIP", "pessoas": [1001, 1002, 1003]}
→ {"result": {"idGrupo": 555, "adicionadas": [1001, 1002, 1003], "jaNoGrupo": [], "falhas": []}}
```

`status` é opcional (padrão `A`). `pessoas` é opcional — dá para criar vazio e vincular depois. O
ERP preenche data e usuário de inclusão com o usuário do perfil.

Se o grupo for criado mas o vínculo falhar por inteiro, a resposta traz `idGrupo` **e**
`erroAoVincular`: o grupo existe. Não repita o comando (o nome já está em uso) — siga com
`grupo-consumidores-add` no id devolvido.

**4. Acrescentar pessoas a um grupo existente.**

```
alpha7_cli.py grupo-consumidores-add 555 --stdin-file p.json --confirmar-escrita
p.json: {"pessoas": [1004, 1005], "cpfs": ["111.444.777-35"]}
→ {"result": {"idGrupo": 555, "adicionadas": [1004, 1005, 2040], "jaNoGrupo": [], "falhas": []}}
```

- `pessoas` são ids de `pessoa`; `cpfs` são resolvidos pelo ERP (com ou sem pontuação). Havendo
  mais de uma pessoa com o mesmo CPF, o ERP devolve uma só — prefira o id.
- **Quem já está no grupo é pulado** e volta em `jaNoGrupo`. O ERP não impede vínculo repetido (é
  a tela que evita), então o comando confere antes de gravar. Rodar de novo a mesma lista é seguro.
- **Cada pessoa é uma gravação separada.** Falha em uma não desfaz as outras: leia `falhas`
  (`[{"pessoa": "...", "erro": "..."}]`) e trate só o que faltou.
- São umas quatro chamadas ao servidor por pessoa. Para listas grandes, mande em lotes de algumas
  centenas e aumente `--timeout`; se um lote estourar o tempo, confira por SQL o que entrou e
  reenvie a lista — o que já está no grupo é pulado.

**5. Conferir.** Pelo CLI, sem depender de acesso ao banco:

```
alpha7_cli.py grupo-consumidores-pessoas 555
→ {"result": {"idGrupo": 555, "total": 3, "pessoas": [{"idVinculo": …, "idPessoa": 1001, "nome": "…", "cpf": "…"}, …]}}
```

Ou por SQL:

```sql
SELECT g.id, g.nome, g.status, COUNT(pg.id) AS pessoas
FROM grupoconsumidores g
LEFT JOIN pessoagrupoconsumidores pg ON pg.grupoconsumidorid = g.id
WHERE g.id = 555
GROUP BY 1, 2, 3;
```

`entity-get GrupoConsumidores 555` devolve o cabeçalho com `numeroConsumidores`.

**6. Tirar pessoas.**

```
alpha7_cli.py grupo-consumidores-remove 555 --stdin-file p.json --confirmar-escrita
p.json: {"pessoas": [1002]}
→ {"result": {"idGrupo": 555, "removidas": [1002], "naoEstavam": [], "falhas": []}}
```

Quem não estava no grupo volta em `naoEstavam`, sem erro. `cpfs` aqui é comparado com o CPF das
pessoas que estão no grupo.

### Outras operações

| Quero | Como |
| --- | --- |
| Renomear, ativar ou inativar | `entity-update GrupoConsumidores <id>` com `{"nome": "..."}` ou `{"status": "I"}` |
| Excluir o grupo | `entity-delete GrupoConsumidores <id>` — leva os vínculos junto (validado com pessoas dentro); o ERP recusa se houver referência que impeça, como caderno de oferta ligado ao grupo |
| Grupos de uma pessoa | `invoke GrupoConsumidores buscarIdsGrupoConsumidoresPeloIdPessoa` com `{"args": [idPessoa]}` (só grupos ativos; `null` quando não há) |

**Permissões do usuário do perfil:** `Cadastro.GrupoConsumidores` (visualizar, incluir, editar,
excluir conforme a operação) e `Cadastro.PessoaGrupoConsumidores` (incluir, excluir).

**Validado contra um ERP de produção (libs 3.112):** buscar grupos; criar grupo vazio e já com
pessoas; vincular por id; repetir uma pessoa (pulada, volta em `jaNoGrupo`); id inexistente (volta
em `falhas` sem derrubar as demais); listar as pessoas; remover pessoa (e pedir uma que não
estava, que volta em `naoEstavam`); `entity-get`; inativar por `entity-update` (os vínculos
permanecem); excluir o grupo com pessoas dentro (não sobra vínculo). Cada chamada levou de 20 a
30 segundos, quase tudo abertura de conexão. **Ainda não exercitado:** `cpfs`, no vínculo e na
remoção — as pessoas do teste não tinham CPF.

---

## Transferência entre lojas (sugestão e pedido)

É o fluxo da tela **Sugestão de Transferência**: a "Inclusão Manual" (produto, quantidade, unidade
de origem, unidades de destino) grava uma **sugestão** na lista do usuário logado; "Gerar pedido de
transferência" transforma as sugestões em **pedido de transferência**, um por par origem → destino.
Tabelas e status do pedido estão em [04-estoque.md](04-estoque.md).

Três comportamentos do ERP que a tela esconde e que mudam o resultado:

- **A lista de sugestões é do usuário.** O CLI enxerga e mexe na lista do usuário do perfil — a
  mesma que essa pessoa vê na tela. Sugestão de outro usuário não aparece nem entra no pedido.
- **Incluir de novo o mesmo produto no mesmo par origem → destino SOMA a quantidade** na sugestão
  que já existe. Não cria outra linha e não substitui. Repetir um `transferencia-sugestao-add`
  dobra a quantidade.
- **Gerar o pedido leva TODAS as sugestões do usuário naquele par**, inclusive as que já estavam
  lá de antes. Não dá para gerar "só o item que acabei de incluir".

A unidade é o **produto**, não a embalagem (`produtoId` = `produto.id`), e a quantidade é na
unidade de estoque do produto. O valor unitário é o custo do produto na loja de origem, preenchido
pelo ERP.

### Roteiro

**1. Lojas.** `alpha7_cli.py unidades-negocio` lista as ativas com id e código. Os comandos de
transferência aceitam a loja pelo **código** que o usuário conhece (`origemCodigo`,
`destinosCodigos`, com ou sem zero à esquerda) ou pelo id (`origemId`, `destinosIds`).

**2. O que já está na lista.**

```
alpha7_cli.py transferencia-sugestoes
→ {"result": [{"idSugestao": …, "idProduto": …, "produto": "…", "quantidade": 1.0,
               "origem": "01", "destino": "03", "valorUnitario": …, "valorTotal": …}, …]}
```

Faça isso **sempre antes de incluir**: se o usuário já tem sugestões no mesmo par, elas irão junto
no pedido. Mostre a ele e pergunte se entram, ou se devem ser excluídas antes
(`invoke SugestaoTransferencia excluirSugestoesTransferencia` com `{"args": [[idSugestao, …]]}`).

**3. Incluir os produtos.**

```
alpha7_cli.py transferencia-sugestao-add --stdin-file p.json --confirmar-escrita
p.json: {"origemCodigo": "01", "destinosCodigos": ["03"],
         "itens": [{"codigoBarras": "7891058001155", "quantidade": 2}, {"produtoId": 2035034, "quantidade": 1}]}
→ {"result": {"origem": "01", "incluidos": [...], "falhas": [], "sugestoes": [ … como ficou cada linha … ]}}
```

`sugestoes` mostra a linha como ficou — com a quantidade **já somada**, se o produto estava na
lista. Cada item é uma gravação: falha em um não desfaz os outros (`falhas`). Mais de um destino
cria uma sugestão por destino, com a mesma quantidade.

**Corrigir antes de gerar.** Trocar a quantidade de uma linha (substitui, não soma) ou tirá-la da
lista:

```
alpha7_cli.py invoke SugestaoTransferencia setQuantidade --stdin-file p.json --confirmar-escrita
p.json: {"args": [[idSugestao], 5]}

alpha7_cli.py invoke SugestaoTransferencia excluirSugestoesTransferencia --stdin-file p.json --confirmar-escrita
p.json: {"args": [[idSugestao]]}
```

As duas devolvem `{"result": null}` quando dão certo — confira com `transferencia-sugestoes`.

**4. Conferir e gerar o pedido.** Rode `transferencia-sugestoes` de novo, mostre ao usuário as
linhas daquele par (produto, quantidade, valor) e, com o "pode":

```
alpha7_cli.py transferencia-gerar-pedidos --stdin-file p.json --confirmar-escrita
p.json: {"origemCodigo": "01", "destinosCodigos": ["03"], "itensEsperados": 2}
→ {"result": {"origem": "01", "pedidos": [{"idPedido": …, "codigo": …}], "itens": [ … ], "sugestoesExcluidas": true}}
```

- **`itensEsperados` é obrigatório**: é quantas sugestões (linhas) devem virar item de pedido. Se
  a lista do usuário naquele par tiver outra quantidade de linhas, o comando recusa e **não gera
  nada** — é a trava contra levar item que ninguém conferiu.
- `dataProgramada` (ISO-8601) é opcional; o padrão é agora. O ERP exige a data e recusa dia
  anterior a hoje.
- `excluirSugestoes` (padrão `true`) tira da lista o que virou pedido, como a tela faz.
- Um pedido comporta até 300 itens; acima disso o ERP divide em mais de um.

**5. Depois.** O pedido nasce com status `A` (confirmado) e origem "sugestão de transferência", e
segue o fluxo normal da loja de origem (`B` enviado, `C` recebido). Para desfazer, **só enquanto
está em `A`**:

- `entity-delete PedidoTransferencia <idPedido>` apaga o pedido e os itens, sem rastro. Excluir
  **não devolve** as sugestões para a lista.
- `invoke PedidoTransferencia cancelar` com `{"args": [idPedido, "motivo"]}` mantém o pedido,
  com status `D` (cancelado) e o motivo registrado.

**Permissões do usuário do perfil:** sugestão de transferência (visualizar, incluir, excluir) e
pedido de transferência (incluir; excluir/cancelar para desfazer).

**Validado contra um ERP de produção (libs 3.112):** listar lojas e sugestões (batem com a tela);
incluir item por código de barras com a loja pelo código sem zero à esquerda; alterar a quantidade
(o total é recalculado); excluir sugestão; a trava de `itensEsperados` (recusa sem gerar); gerar o
pedido mantendo e tirando as sugestões da lista; e excluir o pedido. **Ainda não exercitados:**
`cancelar`, mais de um destino na mesma chamada e `dataProgramada` futura.

Dois detalhes vistos no teste:

- A tela do A7Pharma **não se atualiza sozinha**: o usuário precisa clicar em "Atualizar" (em cada
  aba) para ver o que o CLI gravou.
- **O código do pedido é reaproveitado.** Excluído um pedido, o próximo gerado saiu com o mesmo
  `codigo`; o que identifica o pedido sem ambiguidade é o `idPedido`.

---

## Caderno de oferta

O ciclo abaixo **foi validado contra um ERP de produção** (criar, desativar, três tipos de oferta,
excluir). A estrutura das tabelas está em [07-compras-precificacao.md](07-compras-precificacao.md).

| Quero | Chamada |
| --- | --- |
| Procurar embalagem | `invoke Embalagem findEmbalagemFinderDTOs` — `{"args": ["termo", 50, false]}` |
| Procurar caderno (inclusive inativo) | `invoke CadernoOferta findDTOsByParams` — `{"args": [{"filterParamNomeCadernoOferta": {"text": "termo"}, "status": {"possibleValuesAsCharArray": ["A", "I"]}}]}` |
| Criar caderno | `cadastrar-caderno` — nasce ativo, manual, todo dia, todas as formas de pagamento |
| Acrescentar ofertas | `caderno-item-add <idCaderno>` — `tipoOferta` `P` (preço), `D` (desconto %), `L` (leve/pague) |
| Mudar preço ou desconto de um item | `entity-update ItemCadernoOferta <idItem>` |
| Ativar ou desativar | `entity-update CadernoOferta <id>` com `{"status": "A"}` ou `{"status": "I"}` |
| Remover itens | `invoke ItemCadernoOferta excluir` — `{"args": [[idItem, ...]]}` |
| Excluir caderno | `entity-delete CadernoOferta <id>` — leva as ofertas junto |

O que só aparece depois de errar:

- **`findCadernoOfertaFinderDTOs` esconde caderno inativo**, mesmo buscando pelo nome exato. Use
  `findDTOsByParams`, que aceita o filtro de status e devolve o `status`. Oferta em caderno inativo
  não vale no caixa, e o ERP aceita a gravação do mesmo jeito.
- **O ERP propaga a oferta para as embalagens irmãs**: pedir 3 embalagens pode resultar em 6
  participantes — são os outros códigos de barras do mesmo produto. Não é item fantasma.
- **A oferta é por loja.** O caderno só vale nas unidades participantes; para listar as ofertas de
  um caderno com o id de cada item, o SQL em `itemcadernooferta` é o caminho mais direto.
- **`caderno-item-add` não é idempotente** — repetir duplica a oferta.
- **Embalagem é o SKU.** Caixa e unidade são embalagens diferentes do mesmo produto; ofertar a
  errada é ofertar o que não gira.

---

## Chamar uma facade que não está aqui

`invoke <Dominio> <metodo>` alcança qualquer operação que o servidor expõe, não só as documentadas
aqui. O domínio é o nome da entidade (`Pessoa`, `Embalagem`, `CadernoOferta`,
`PedidoTransferencia`…), e os métodos comuns a quase todos são `findDTOByID`, `findDTOsByIDs` e
`findAllDTOs`. Nome de método ou quantidade de argumentos que não existe volta como
`NoSuchMethodException`, sem gravar nada.

Trate qualquer método novo como não validado: leia com ele antes de gravar com ele, teste a
gravação num registro descartável e registre o resultado nesta referência — o que funcionou, com o
payload exato, é o que serve para a próxima vez.

---

## Erros comuns

| Erro | Causa provável |
| --- | --- |
| `RequestSendFailedException … No more destinations are available` | Servidor inalcançável: host/porta errados, fora da rede/VPN, ou servidor fora do ar |
| Erro já no login (antes de qualquer facade) | Usuário ou senha do perfil — abra a janela de novo com `alpha7_credenciais.py` |
| `PermissionException: User has insufficient privileges` | O usuário do perfil não tem a permissão daquela operação |
| `ValidationException` / mensagem com `….nome.existente` | Regra de negócio do ERP — por exemplo, nome de grupo já usado |
| `NoSuchMethodException … com N argumento(s)` | Quantidade de argumentos não bate com nenhuma sobrecarga |
| `ClassNotFoundException …RemoteFacade` | Nome de domínio errado (é o nome da entidade, sem sufixo) |
| `LazyInitializationException` | O método devolve entidade crua — use o equivalente DTO ou SQL |
| `InvalidClassException` / `serialVersionUID` | Libs de versão diferente da do servidor — `--baixar-libs` |
| `TransientPropertyValueException` | Relacionamento montado do JSON — use o comando dedicado |
| Gravou sem erro, mas o campo ficou vazio | Nome de campo errado no JSON (regra 1) |
