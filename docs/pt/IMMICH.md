# Integração com o Immich

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · [Deutsch](../de/IMMICH.md) · [Italiano](../it/IMMICH.md) · [Español](../es/IMMICH.md) · **Português** · [简体中文](../zh/IMMICH.md)

O [Immich](https://immich.app/) armazena, faz backup e entrega as suas fotos. O Facet as pontua, classifica e faz a triagem. Esta página conecta os dois:

- As avaliações e os favoritos do Facet aparecem no Immich.
- Um upload para o Immich avisa o Facet de que há trabalho novo esperando.

As duas direções usam apenas a API REST do Immich. Nenhuma das ferramentas toca no banco de dados da outra.

**O Facet exige o Immich ≥ 3.0.** O Facet limpa uma avaliação com `null` e marca uma rejeição com `-1`. Um servidor 2.x recusa a limpeza, então avaliações desatualizadas ficam nos seus ativos.

---

## Sumário

- [Como os dois veem o mesmo arquivo](#como-os-dois-veem-o-mesmo-arquivo)
- [Passo 1 — compartilhar a biblioteca com o Immich](#passo-1--compartilhar-a-biblioteca-com-o-immich)
- [Passo 2 — criar uma chave de API](#passo-2--criar-uma-chave-de-api)
- [Passo 3 — mapear os caminhos](#passo-3--mapear-os-caminhos)
- [Passo 4 — testar, depois enviar](#passo-4--testar-depois-enviar)
- [Enviando rejeições](#enviando-rejeições)
- [Importar e enviar pilhas manuais](#importar-e-enviar-pilhas-manuais)
- [O webhook de entrada](#o-webhook-de-entrada)
- [Diagnóstico no visualizador](#diagnóstico-no-visualizador)
- [Referência de configuração](#referência-de-configuração)
- [Solução de Problemas](#solução-de-problemas)

---

## Como os dois veem o mesmo arquivo

O Facet e o Immich veem o mesmo arquivo no disco sob caminhos diferentes:

- O **Facet** usa o caminho absoluto na máquina que executa o escaneamento, por exemplo `/mnt/photos/2026/07/IMG_1234.jpg`.
- O **Immich** usa o seu `originalPath`: o caminho como visto *de dentro do container do Immich*. Geralmente é `/usr/src/app/upload/…` para uploads, ou o ponto de montagem de uma biblioteca externa.

Você informa ao Facet a reescrita de prefixo uma única vez, em `immich.path_map`. Toda consulta passa por ela. Se estiver errada, tudo informa "unmatched" — veja [Solução de Problemas](#solução-de-problemas).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

O mapeamento funciona nos dois sentidos. `--immich-sync` o usa para encontrar o ativo do Immich a partir de um caminho do Facet. O webhook o usa para encontrar a foto do Facet a partir de um `originalPath` do Immich.

## Passo 1 — compartilhar a biblioteca com o Immich

O arranjo mais simples é uma **biblioteca externa** do Immich: o Immich lê as fotos onde elas já estão, e o Facet escaneia o mesmo diretório.

1. No Immich, vá em **Administration → External Libraries → Create Library**, escolha o dono e adicione um caminho de importação para o diretório como o container do Immich o vê.
2. Monte esse diretório como bind mount, somente leitura, dentro do container do Immich. Em `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Escaneie a biblioteca no Immich (**Scan All Libraries**), e escaneie o mesmo diretório com o Facet:

   ```bash
   python facet.py /mnt/photos
   ```

Nenhum arquivo é duplicado em disco.

Você também pode fazer upload para o Immich normalmente (backup automático do celular, envio pela web) e apontar o Facet para o diretório de upload do Immich. Só os prefixos mudam. Reexecute o escaneamento do Facet depois dos uploads, ou use `--watch`.

## Passo 2 — criar uma chave de API

No Immich: **clique no seu avatar → Account Settings → API Keys → New API Key**.

O Immich ≥ 3.0 permite restringir uma chave a alguns escopos. A sincronização de avaliações e favoritos usa estes (as pilhas manuais exigem mais, veja adiante):

| Escopo | O que o Facet faz com ele |
|-------|-------------------------|
| `server.about` | Verificação de conectividade/autenticação do `--immich-test` |
| `asset.read` | Resolve ativos por `originalPath` |
| `asset.update` | Grava `rating` e `isFavorite` |
| `album.read` | Encontra o álbum de melhores escolhas pelo nome e lê a sua pertença |
| `album.create` | Cria o álbum de melhores escolhas na primeira vez |
| `albumAsset.create` | Adiciona fotos ao álbum de melhores escolhas |
| `albumAsset.delete` | Remove fotos que caíram abaixo do limiar de melhores escolhas |

Você pode dispensar os quatro escopos de álbum se `push.top_picks_album` estiver vazio. O Facet só toca em álbuns quando esse nome está definido. Sem `albumAsset.delete`, a sincronização continua: remoções recusadas são ignoradas e contadas no resumo, e a simulação as previsualiza.

O Facet envia a chave em um cabeçalho `x-api-key`. Coloque-a em `scoring_config.json`:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Observação:** o Facet grava avaliações com `PUT /api/assets`. O Immich o marca como obsoleto, mas o substituto ainda não foi publicado, então o Facet continua usando-o.

## Passo 3 — mapear os caminhos

Adicione um par para cada raiz compartilhada. Regras:

- Vence a primeira correspondência de prefixo. É uma comparação literal de string, não de diretório.
- Termine os prefixos de diretório com `/`.
- Coloque os mapeamentos mais específicos antes dos mais amplos.

```json
"immich": {
  "path_map": [
    { "facet_prefix": "/mnt/photos/", "immich_prefix": "/usr/src/app/external/" }
  ]
}
```

Duas raízes, dois pares:

```json
"path_map": [
  { "facet_prefix": "/mnt/photos/",  "immich_prefix": "/usr/src/app/external/" },
  { "facet_prefix": "/mnt/archive/", "immich_prefix": "/usr/src/app/archive/" }
]
```

O placeholder padrão (`{"facet_prefix": "", "immich_prefix": ""}`) passa os caminhos sem alteração. Isso só funciona se o Facet e o Immich veem caminhos absolutos idênticos, o que é raro, a menos que o Facet rode dentro do container do Immich.

Para descobrir o valor real, abra uma foto no Immich e pressione `i` para abrir o painel de informações. Compare o caminho de arquivo mostrado ali com o caminho que o Facet mostra para a mesma foto.

## Passo 4 — testar, depois enviar

```bash
# Connectivity + authentication only. No writes.
python facet.py --immich-test

# Resolve every asset and report what WOULD change. Still no writes.
python facet.py --immich-sync --dry-run

# For real.
python facet.py --immich-sync
```

A sincronização informa `matched` / `unmatched` / `updated` / `skipped (unrated)` / `identity_conflicts` / álbuns criados. Em uma simulação, `updated` conta os ativos que mudariam, e nada é gravado. Uma contagem alta de `unmatched` na primeira execução quase sempre significa que o mapeamento de caminhos está errado — veja [Solução de Problemas](#solução-de-problemas).

O que é enviado:

- **Avaliações por estrelas de 1 a 5** → o `rating` do Immich. Uma foto sem avaliação não envia nada.
- **Favoritos** → o `isFavorite` do Immich.
- **Limpezas.** Se você avaliou uma foto, sincronizou e depois voltou a deixá-la sem avaliação, a próxima sincronização envia `rating: null` para que o Immich também a limpe. O Facet lembra o que enviou da última vez (em `stats_cache`) para isso. Ele envia `null`, nunca `0`: o Immich v3 rejeita `0`, e um lote rejeitado aborta toda a sincronização.
- **Um álbum de melhores escolhas** (opcional), quando `push.top_picks_album` está definido: fotos avaliadas com pelo menos `push.top_picks_min_rating` são membros, e um membro que caiu abaixo do limiar é removido numa sincronização global enquanto o Facet o consegue atribuir (uma foto eliminada ou o asset de outra aplicação fica como está); um membro existente nunca é readicionado.

No modo multiusuário, `--immich-sync --user alice` envia as avaliações próprias da Alice (`user_preferences`) em vez das globais, e rastreia o estado de sincronização dela separadamente.

## Enviando rejeições

Desativado por padrão. Quando ativado, uma foto que você rejeita na visão de triagem do Facet recebe o marcador de rejeitada do Immich:

```json
"immich": {
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": true
  }
}
```

Com `push.rejected` ativado:

- Uma foto rejeitada envia `rating: -1`, o valor que o Immich v3 usa para "rejeitada".
- **A rejeição tem prioridade sobre as estrelas.** Uma foto rejeitada com 5 estrelas envia `-1`, não `5`.
- **Desfazer a rejeição limpa a marcação.** A foto passa então a enviar sua avaliação por estrelas atual, ou `rating: null` se não tiver nenhuma.
- Uma foto rejeitada nunca entra no álbum de melhores escolhas.
- `push.ratings: false` também desativa isso, já que `-1` é uma avaliação.

Deixe desativado se outras pessoas (ou o seu telefone) olham para a biblioteca do Immich: elas verão o `-1`.

## Importar e enviar pilhas manuais

As pilhas manuais têm o seu próprio fluxo de **plano/aplicação pela CLI local**, com as opções usuais `--config`, `--db` e `--user`. A sincronização de avaliações e favoritos não é afetada.

Requisitos:

- Immich **≥ 3.0** (o Facet também verifica o suporte a pilhas em tempo de execução).
- Permissões da chave: `user.read` e `stack.read` além de `asset.read`; o envio também precisa de `stack.create` e `asset.update`. `stack.update` e `stack.delete` não são necessários.
- Instalações multiusuário devem informar um usuário existente.
- A chave do Immich nunca é usada por operações de pilhas do visualizador web, dos assistentes (MCP) ou do webhook de upload.

Fluxo:

1. Prévia. É somente leitura nos dois lados e não migra o banco de dados.
2. Revise o plano e o seu resumo SHA-256.
3. Aplique explicitamente.

Opções e limites:

- `--stack-id UUID` (repetível) limita a execução às pilhas de origem indicadas.
- `--stack-plan-out` grava um novo arquivo JSON privado (modo POSIX `0600`) e recusa sobrescrever.
- Um plano tem no máximo **1000 grupos, 1000 membros por grupo, 20000 membros no total e 16 MiB**. Use `--stack-id` para restringi-lo.
- No Windows, escolha uma pasta de saída cuja ACL restrinja o acesso à sua conta; os bits de modo POSIX não protegem o arquivo ali.

Regras de correspondência:

- Cada membro deve corresponder a exatamente uma foto indexada, visível e disponível, pertencente à conta remota. Um membro ausente ou ambíguo ignora o grupo inteiro.
- O envio só cria uma pilha a partir de ativos remotos que ainda não estão empilhados.
- Uma correspondência exata de membros e capa vincula as duas pilhas ao aplicar.
- Sobreposições parciais, capas diferentes, membros alterados e casos desempilhados em apenas um lado são ignorados como conflitos. Pilhas existentes nunca são atualizadas.
- Só a capa é transferida nos dois sentidos; a ordem dos outros membros não.
- Não há sincronização bidirecional automática, consultas periódicas nem propagação de desempilhamento.

Planos, vínculos e recibos são limitados ao servidor, à conta remota, ao proprietário local e ao mapa de caminhos. Mude qualquer um deles e o plano antigo deixa de valer. Os recibos salvam resultados e IDs de ativos remotos, nunca credenciais.

Aplicar revalida cada grupo antes de gravar e o relê depois. Se uma resposta de criação for perdida, o Facet a reconcilia antes de qualquer nova tentativa em vez de enviá-la de novo. Cancelar para entre grupos; uma aplicação posterior retoma a partir dos recibos.

> **Aviso:** o Immich não consegue criar uma pilha de forma condicional. Outro cliente pode alterar os ativos entre a última verificação do Facet e a gravação, e o Facet não consegue reverter isso.

## O webhook de entrada

O webhook funciona no sentido contrário: o Immich avisa o Facet de que um ativo mudou, e o Facet responde com o que sabe.

**Ele fica desativado por padrão e nunca inicia um escaneamento.** Em vez disso:

- **Foto conhecida e pontuada** → o Facet envia a avaliação e o favorito de volta ao Immich imediatamente. Pontue uma foto, faça upload dela, e a avaliação chega ao Immich sem esperar por `--immich-sync`.
- **Foto desconhecida ou ainda não pontuada** → o Facet adiciona o caminho a uma lista de pendências limitada, e a próxima `--immich-sync` o registra no log.

### Habilitando o webhook

O token é um segredo, então ele vive em uma variável de ambiente, não em `scoring_config.json` (esse arquivo é legível por qualquer usuário na maioria das instalações). A configuração nomeia a variável; a variável salva o valor.

1. Gerencia um token e exporte-o onde quer que o visualizador seja iniciado — sua unidade systemd, `docker-compose.yml` ou o perfil do shell:

   ```bash
   export FACET_IMMICH_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
   ```

2. Nomeie essa variável em `scoring_config.json`:

   ```json
   "immich": {
     "webhook": {
       "token_env": "FACET_IMMICH_WEBHOOK_TOKEN",
       "header": "x-facet-token",
       "max_pending": 500
     }
   }
   ```

3. Reinicie o visualizador (`python viewer.py`).

Se `token_env` estiver vazio, ou a variável não estiver definida ou estiver vazia, o endpoint fica desativado e retorna **404** (como `frame.tokens` e `upload.username`).

### Apontando o Immich para ele

No Immich ≥ 3.0: **Administration → Workflows → Create Workflow**.

1. **Trigger** — `Asset uploaded`. Adicione `Asset updated` se edições também devem disparar.
2. **Action** — **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, em um endereço que o container do Immich consiga alcançar. Se os dois rodam em Docker no mesmo host, use o nome do serviço (`http://facet:5000/…`), não `localhost`.
4. **Header** — nome `x-facet-token`, valor o seu token. O nome precisa corresponder a `webhook.header`. `Authorization: Bearer <token>` também funciona, para proxies que só oferecem isso.
5. Salve e faça upload de uma foto para confirmar.

### O que o endpoint responde

| Status | Significado |
|--------|-----------|
| `202` | Aceito. O JSON conta os ativos desta entrega: `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | JSON válido, mas nenhum ativo que o Facet reconheça. Registrado em log, não é um erro. |
| `400` | O corpo não era JSON. |
| `401` | Nenhum token na requisição. |
| `403` | Token incorreto. |
| `404` | O recurso está desativado (nenhum token configurado). |

O Facet lê `originalPath` do payload, onde quer que esteja: um ativo solto, `{"asset": {…}}`, uma lista, ou qualquer um desses dentro de `data` / `items` / `assets`. Se o payload traz o `id` do ativo, o Facet busca esse ativo no Immich e confere o caminho e o proprietário/a biblioteca antes de atualizar. Uma divergência conta como `failed`.

A próxima sincronização registra os caminhos pendentes:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Escaneie essas fotos (`python facet.py /mnt/photos`) e elas somem da lista na sincronização seguinte. A lista salva no máximo `max_pending` entradas e descarta as mais antigas primeiro.

### Notas de segurança

- O token é comparado em tempo constante; um token incorreto recebe um `403` puro e simples, sem nenhum sinal de tempo.
- Sirva o visualizador por HTTPS, a menos que o Immich o alcance por uma rede privada: o token viaja em um cabeçalho a cada entrega.
- Para rotacionar o token, altere a variável de ambiente e o cabeçalho do workflow do Immich juntos, depois reinicie o visualizador.
- O webhook envia a avaliação global, não a de nenhum usuário específico. Para avaliações por usuário no Immich, deixe o webhook desativado e use `--immich-sync --user <nome>` em uma agenda.

## Diagnóstico no visualizador

Abra **Diagnóstico do Immich** no submenu **Tarefas e diagnóstico** do menu do usuário. É necessário acesso de superadministrador no modo multiusuário, e acesso de edição (ou edição local confiável) no modo individual.

- Nada é lido do Immich até você clicar em **Testar ligação**. O teste lê a versão do servidor e o acesso à conta e não grava nada.
- A cobertura de caminhos verifica no máximo 200 fotos indexadas. Ela não confirma que cada uma corresponde a um ativo do Immich.
- O horário da última sincronização pode ser anterior a uma mudança no servidor configurado.
- A verificação de versão não confirma as permissões de pilhas.
- Credenciais e caminhos do servidor nunca são mostrados.

## Referência de configuração

O bloco `immich` completo, com os padrões de fábrica:

```json
"immich": {
  "url": "",
  "api_key": "",
  "owner_id": "",
  "library_id": "",
  "path_map": [
    { "facet_prefix": "", "immich_prefix": "" }
  ],
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": false,
    "top_picks_album": "",
    "top_picks_min_rating": 4
  },
  "webhook": {
    "token_env": "",
    "header": "x-facet-token",
    "max_pending": 500
  },
  "timeout_seconds": 30
}
```

| Chave | Padrão | Significado |
|-----|---------|---------|
| `url` | `""` | URL base do Immich, `http` ou `https`. Uma barra final é removida. |
| `api_key` | `""` | Chave de API, enviada como `x-api-key`. Vazio interrompe qualquer sincronização com um erro claro. |
| `owner_id` | `""` | Só corresponde a ativos com exatamente este `ownerId` do Immich. |
| `library_id` | `""` | Só corresponde a ativos exatamente nesta `libraryId` do Immich. Vazio significa qualquer biblioteca. |
| `path_map` | um par vazio | Reescritas de prefixo entre os caminhos do Facet e o `originalPath` do Immich. O primeiro que corresponder vence; usado nas duas direções. |
| `push.ratings` | `true` | Envia as avaliações por estrelas de 1 a 5 (e suas limpezas). |
| `push.favorites` | `true` | Envia `isFavorite` (e suas limpezas). |
| `push.rejected` | `false` | Envia `rating: -1` para fotos rejeitadas no Facet. Requer `push.ratings`. |
| `push.top_picks_album` | `""` | Nome do álbum a manter preenchido: membros abaixo de `push.top_picks_min_rating` são removidos numa sincronização global enquanto o Facet os consegue atribuir. Vazio significa que o Facet nunca toca em álbuns. |
| `push.top_picks_min_rating` | `4` | Avaliação mínima por estrelas para esse álbum. |
| `webhook.token_env` | `""` | Variável de ambiente que salva o segredo do webhook. Vazio desativa o endpoint. |
| `webhook.header` | `"x-facet-token"` | Cabeçalho em que o Immich envia o token. |
| `webhook.max_pending` | `500` | Tamanho máximo da lista de caminhos pendentes (não pontuados). |
| `timeout_seconds` | `30` | Timeout HTTP por requisição. |

## Solução de Problemas

### Tudo volta como `unmatched`

O mapeamento de caminhos está errado. Esta é, disparadamente, a falha mais comum.

1. Abra uma foto no Immich e pressione `i`. Anote o caminho no painel de informações.
2. Encontre o caminho da mesma foto no Facet (o painel de detalhes da galeria, ou `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. Os dois caminhos terminam igual. As partes que diferem são o seu `facet_prefix` e o seu `immich_prefix`.

Armadilhas comuns:

- **Uma barra final ausente.** `"/mnt/photos"` → `"/usr/src/app/external"` também reescreve `/mnt/photosXYZ/a.jpg`. Termine os dois prefixos com `/`.
- **Caminho do host vs. caminho do container.** O caminho do Immich é o que o *container* vê. Confira com `docker compose exec immich-server ls /usr/src/app/external`.
- **Symlinks e bind mounts.** O Immich armazena o caminho que ele percorreu. Um symlink em um dos lados faz as strings diferirem.
- **Maiúsculas/minúsculas e Unicode.** A comparação é exata. Em um compartilhamento sem distinção entre maiúsculas e minúsculas, `/Photos/` e `/photos/` não correspondem entre si.
- **O Immich ainda não indexou o arquivo.** Execute **Scan All Libraries** e verifique se o ativo existe no Immich.

`--immich-sync --dry-run` registra no log os primeiros 20 caminhos não correspondidos, o que geralmente mostra o prefixo errado.

### `--immich-test` falha

- `Unsupported Immich URL scheme` — `url` precisa de `http://` ou `https://`.
- `HTTP 401` — a chave de API está errada ou foi revogada.
- `HTTP 403` — a chave não tem `server.about`. Recrie-a com os sete escopos acima.
- Conexão recusada / timeout — a porta está errada, ou o Facet não consegue alcançar o container. Teste com `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` a partir da máquina do Facet.

### O webhook retorna 404

O recurso está desativado: `webhook.token_env` está vazio, ou a variável que ele nomeia não está definida ou está vazia *no ambiente do visualizador*. Exportá-la no seu shell não alcança um visualizador executado por systemd ou Docker. Defina-a na unit ou no arquivo compose e reinicie.

### O webhook retorna 401 ou 403

`401`: nenhum token chegou, então o nome do cabeçalho que o Immich envia não corresponde a `webhook.header`. `403`: o token está errado. Compare o valor do cabeçalho do workflow com a variável de ambiente.

### `ModuleNotFoundError: No module named 'sync'`

O servidor parece saudável, mas o webhook falha quando o Immich o chama e `--immich-sync` falha de imediato. Confirme com:

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

Se você receber `ModuleNotFoundError: No module named 'sync'`, a sua imagem Docker é antiga demais. Baixe a imagem atual ou reconstrua a partir de um checkout atual.

### As avaliações são enviadas, mas as limpezas não

O Facet só limpa uma avaliação que ele enviou antes, e lembra delas em `stats_cache`, no banco de dados do Facet. Restaurar um banco de dados mais antigo, ou usar um novo, perde essa memória: uma avaliação limpa durante a lacuna permanece no Immich. Reavalie e limpe a foto novamente, ou corrija diretamente no Immich.

### As avaliações aparecem nas fotos erradas

O Facet ignora correspondências ambíguas e as informa como `identity_conflicts`:

- um caminho do Facet que corresponde a vários ativos do Immich
- vários caminhos do Facet que mapeiam para o mesmo caminho do Immich

Nada é gravado para esses caminhos; as outras fotos continuam sincronizando.

Um lote de webhook é mais rigoroso: se vários caminhos do Facet reivindicam o mesmo destino ou ID de ativo, toda entrada elegível do lote é recusada e contada como `failed`. Corrija as raízes sobrepostas em `path_map`, ou defina `owner_id` e `library_id`, e tente novamente. Não adivinhe o proprietário pelo nome de uma pessoa ou pelo caminho.

As respostas do Immich devem incluir `id` e `originalPath`, e devem corresponder a qualquer proprietário e biblioteca configurados. Uma atualização bem-sucedida significa que o Immich a aceitou; o seu próprio trabalho de metadados em segundo plano ainda pode estar em andamento.

### `rating: 0 is not valid`

O servidor Immich é mais antigo que 3.0. Atualize-o: o Facet precisa de `null` para limpar e de `-1` para `push.rejected`, e nada contorna isso no 2.x.

---

**Ver também:** [Comandos — Sincronização com o Immich](COMMANDS.md#sincronização-com-o-immich) · [Configuração](CONFIGURATION.md) · [Receitas de Interoperabilidade com Editores](INTEROP.md) para o round-trip de XMP com Lightroom, darktable e digiKam.
