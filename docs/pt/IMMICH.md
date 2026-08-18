# Integração com o Immich

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · [Deutsch](../de/IMMICH.md) · [Italiano](../it/IMMICH.md) · [Español](../es/IMMICH.md) · **Português**

Facet e [Immich](https://immich.app/) fazem trabalhos diferentes sobre as mesmas fotos. O Immich é a biblioteca: ele importa as fotos, faz backup delas e as entrega para o seu telefone. O Facet é o julgamento: ele pontua, classifica e faz a triagem delas. Esta página conecta os dois de forma que os veredictos a que o Facet chega apareçam como avaliações e favoritos no Immich, e que um upload para o Immich avise o Facet de que há trabalho novo esperando.

A ligação é somente REST nas duas direções. O Facet nunca toca no banco de dados do Immich, e o Immich nunca toca no do Facet.

**O Facet exige o Immich ≥ 3.0.** Servidores mais antigos rejeitam a semântica de avaliação da qual o Facet depende: `null` para limpar uma avaliação e `-1` para marcar uma como rejeitada. Em um servidor 2.x, a limpeza é recusada e avaliações desatualizadas ficam presas para sempre nos seus ativos.

---

## Sumário

- [Como os dois veem o mesmo arquivo](#como-os-dois-veem-o-mesmo-arquivo)
- [Passo 1 — compartilhar a biblioteca com o Immich](#passo-1--compartilhar-a-biblioteca-com-o-immich)
- [Passo 2 — criar uma chave de API](#passo-2--criar-uma-chave-de-api)
- [Passo 3 — mapear os caminhos](#passo-3--mapear-os-caminhos)
- [Passo 4 — testar, depois enviar](#passo-4--testar-depois-enviar)
- [Enviando rejeições](#enviando-rejeições)
- [O webhook de entrada](#o-webhook-de-entrada)
- [Referência de configuração](#referência-de-configuração)
- [Solução de Problemas](#solução-de-problemas)

---

## Como os dois veem o mesmo arquivo

Tudo aqui se apoia em uma única ideia: **a mesma foto no disco, vista a partir de dois containers**.

O Facet conhece uma foto pelo seu caminho absoluto na máquina que executa o escaneamento — `/mnt/photos/2026/07/IMG_1234.jpg`. O Immich conhece o mesmo arquivo pelo seu próprio `originalPath`, que é como esse arquivo aparece *de dentro do container do Immich* — geralmente `/usr/src/app/upload/…` para ativos enviados por upload, ou o ponto de montagem que você deu a uma biblioteca externa.

Nenhum dos dois lados consegue adivinhar a visão do outro, então você informa ao Facet a reescrita de prefixo uma única vez (`immich.path_map`), e toda consulta nas duas direções passa por ela. Acerte isso e o resto é mecânico; erre e tudo passa a informar silenciosamente "unmatched" — veja [Solução de Problemas](#solução-de-problemas).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

O mapeamento é usado nas duas direções: de saída (`--immich-sync` traduz um caminho do Facet para encontrar o ativo) e de entrada (o webhook traduz o `originalPath` do Immich de volta para encontrar a foto).

## Passo 1 — compartilhar a biblioteca com o Immich

O arranjo mais limpo é uma **biblioteca externa**: o Immich lê as fotos onde elas já estão, em vez de possuir uma segunda cópia. O Facet escaneia o mesmo diretório a partir do seu próprio lado.

1. No Immich, vá em **Administration → External Libraries → Create Library**, escolha o dono e adicione um caminho de importação apontando para o diretório como o container do Immich o vê.
2. Garanta que esse diretório esteja montado como bind mount, somente leitura, dentro do container do Immich. Em `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Escaneie a biblioteca pela interface do Immich (**Scan All Libraries**), e escaneie o mesmo diretório com o Facet:

   ```bash
   python facet.py /mnt/photos
   ```

Agora as duas ferramentas têm uma linha por arquivo. Nada é duplicado em disco.

Se, em vez disso, você fizer upload para o Immich normalmente (backup automático do celular, o envio pela web) e apontar o Facet para o próprio diretório de upload do Immich, a integração funciona exatamente da mesma forma — só os prefixos mudam. Nesse caso o Immich é quem define a organização dos arquivos, então reexecute o escaneamento do Facet depois dos uploads (ou use `--watch`).

## Passo 2 — criar uma chave de API

No Immich: **clique no seu avatar → Account Settings → API Keys → New API Key**.

O Immich ≥ 3.0 permite restringir o escopo de uma chave em vez de conceder tudo a ela. O Facet precisa de exatamente seis escopos:

| Escopo | O que o Facet faz com ele |
|-------|-------------------------|
| `server.about` | Verificação de conectividade/autenticação do `--immich-test` |
| `asset.read` | Resolve ativos por `originalPath` |
| `asset.update` | Grava `rating` e `isFavorite` |
| `album.read` | Encontra um álbum de melhores escolhas existente pelo nome |
| `album.create` | Cria o álbum de melhores escolhas na primeira vez |
| `albumAsset.create` | Adiciona fotos ao álbum de melhores escolhas |

Descarte os últimos três se você deixar `push.top_picks_album` vazio — o Facet só toca em álbuns quando esse nome está definido.

A chave é enviada como um cabeçalho `x-api-key` em cada requisição. Coloque-a em `scoring_config.json`:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Uma observação sobre `PUT /api/assets`.** O Facet grava avaliações com `PUT /api/assets`, que o documento OpenAPI do Immich marca como *deprecated*. Os aliases `PATCH` que o substituiriam foram anunciados, mas estão **ausentes da especificação publicada**, então ainda não há para onde migrar — `PUT` continua sendo o único endpoint que de fato existe, e o Facet continua usando-o. Todo caminho do Immich que o Facet toca vive em `ImmichClient` (`sync/immich.py`), então no dia em que as rotas `PATCH` forem lançadas, a mudança se resume a uma única classe.

## Passo 3 — mapear os caminhos

Adicione um par para cada raiz que você compartilha. O primeiro par cujo `facet_prefix` corresponder a uma foto vence:

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

Deixe o placeholder padrão (`{"facet_prefix": "", "immich_prefix": ""}`) como está e os caminhos passam sem alteração — correto apenas quando o Facet e o Immich realmente veem caminhos absolutos idênticos, o que acontece se você rodar o Facet dentro do namespace do container do Immich, e quase nunca no caso contrário.

Para descobrir o valor real, abra qualquer foto no Immich, pressione `i` para abrir o painel de informações e compare o caminho de arquivo mostrado ali com o caminho que o Facet relata para a mesma foto.

## Passo 4 — testar, depois enviar

```bash
# Apenas conectividade + autenticação. Nenhuma gravação.
python facet.py --immich-test

# Resolve cada ativo e informa o que MUDARIA. Ainda sem gravações.
python facet.py --immich-sync --dry-run

# Para valer.
python facet.py --immich-sync
```

A sincronização informa `matched` / `unmatched` / `updated` / `skipped (unrated)` / álbuns criados. Uma primeira execução com uma contagem alta de `unmatched` quase sempre significa que o mapeamento de caminhos está errado — veja [Solução de Problemas](#solução-de-problemas).

O que é enviado:

- **Avaliações por estrelas de 1 a 5** → o `rating` do Immich. Uma foto que você nunca avaliou não envia nada.
- **Favoritos** → o `isFavorite` do Immich.
- **Limpezas.** Se você avaliou uma foto com 5 estrelas, sincronizou e depois voltou a deixá-la sem avaliação, a próxima sincronização envia `rating: null` para que o Immich também a esqueça. O Facet lembra o que enviou da última vez (na tabela auxiliar `stats_cache`) exatamente para que essa transição não se perca. É `null`, nunca `0` — o Immich v3 rejeita `0` de forma direta, e um lote rejeitado aborta toda a sincronização.
- **Um álbum opcional de melhores escolhas**, preenchido a partir de `push.top_picks_min_rating`, quando `push.top_picks_album` define um nome.

No modo multiusuário, `--immich-sync --user alice` envia as avaliações de `user_preferences` da Alice em vez das colunas globais, e rastreia seu estado sob o escopo dela.

## Enviando rejeições

Desativado por padrão. Ative e uma foto que você rejeitou na câmara escura de triagem do Facet recebe o próprio marcador de rejeitada do Immich:

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
- **A rejeição tem prioridade sobre as estrelas.** Uma foto rejeitada com 5 estrelas envia `-1`, não `5` — você a descartou, e esse é o fato que vale a pena espelhar.
- **Desfazer a rejeição limpa a marcação.** Uma foto que enviou `-1` e depois tem a rejeição desfeita passa a enviar sua avaliação por estrelas atual, ou `rating: null` se não tiver nenhuma. O mesmo mecanismo de estado rastreado de qualquer outra limpeza.
- Uma foto rejeitada nunca entra no álbum de melhores escolhas.
- `push.ratings: false` suprime isso. `-1` é uma gravação de avaliação, então uma configuração que desativou o envio de avaliações não tem uma reintroduzida às escondidas.

Deixe desativado se outras pessoas (ou o seu telefone) olham para a biblioteca do Immich: um `-1` fica visível lá, e "rejeitada no Facet" é um julgamento de trabalho que você talvez não queira divulgar.

## O webhook de entrada

Tudo o que veio antes é Facet → Immich. O webhook é a outra direção: o Immich avisa o Facet de que um ativo acabou de mudar, e o Facet responde imediatamente com o que sabe sobre ele.

**Ele fica desativado por padrão e nunca inicia um escaneamento.** Um webhook é uma chamada sem autenticação por sessão vinda de outro daemon; deixar que um deles disparasse trabalho de GPU daria a qualquer portador do token uma forma de derrubar sua máquina. O que ele faz em vez disso:

- **Foto conhecida e pontuada** → sua avaliação/favorito é enviada de volta direto para o Immich, ali mesmo, como uma atualização de um único ativo. É isso que fecha o ciclo depois de um escaneamento: pontue uma foto, faça upload dela, e a avaliação chega ao Immich sem esperar pela próxima `--immich-sync`.
- **Foto desconhecida ou ainda não pontuada** → o caminho é lembrado em uma lista de pendências limitada e sem duplicatas, e a próxima `--immich-sync` a registra no log. Nada é escaneado.

### Habilitando o webhook

O token é um segredo compartilhado, então ele vive no ambiente, nunca em `scoring_config.json` (esse arquivo é reescrito no lugar por vários endpoints e é legível por qualquer usuário na maioria das instalações). A configuração nomeia a *variável*; a variável guarda o *valor*.

1. Gere um token e exporte-o onde quer que o visualizador seja iniciado — sua unidade systemd, `docker-compose.yml`, ou o perfil do shell:

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

Um `token_env` vazio, ou uma variável que não está definida ou está vazia, desativa o endpoint por completo — ele retorna **404**, exatamente como `frame.tokens` e `upload.username`. Não existe um estado meio aberto.

### Apontando o Immich para ele

No Immich ≥ 3.0: **Administration → Workflows → Create Workflow**.

1. **Trigger** — escolha o evento de ativo que você quer espelhar. `Asset uploaded` é o útil; adicione `Asset updated` se você também quiser que edições disparem de novo.
2. **Action** — escolha **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, usando um endereço que o container do Immich consiga realmente alcançar. Se os dois rodam em Docker no mesmo host, isso é o nome do serviço (`http://facet:5000/…`), não `localhost`.
4. **Header** — nome `x-facet-token`, valor o token que você gerou. O nome precisa corresponder a `webhook.header`; renomeie os dois juntos se a sua configuração precisar de um nome diferente. `Authorization: Bearer <token>` também é aceito, para proxies que só oferecem isso.
5. Salve e faça upload de uma foto para confirmar.

### O que o endpoint responde

| Status | Significado |
|--------|-----------|
| `202` | Corpo entendido. A contagem em JSON informa `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | JSON válido, mas nenhum ativo que o Facet reconheça. Registrado em log, não é um erro — o formato do payload é do Immich, que pode alterá-lo quando quiser. |
| `400` | O corpo não era JSON de forma alguma. |
| `401` | Nenhum token na requisição. |
| `403` | Token incorreto. |
| `404` | O recurso está desativado (nenhum token configurado). |

O Facet lê `originalPath` de dentro do payload e é deliberadamente flexível quanto a onde ele está — um objeto de ativo isolado, `{"asset": {…}}`, uma lista, ou qualquer um desses aninhado sob `data` / `items` / `assets` funciona. Se o payload trouxer o `id` do ativo, o Facet o utiliza e pula uma consulta extra de busca.

Os caminhos pendentes são informados pela próxima sincronização:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Escaneie essas fotos (`python facet.py /mnt/photos`) e elas somem da lista na sincronização seguinte. A lista tem um teto de `max_pending` entradas, com as mais antigas descartadas primeiro, para que um Immich tagarela nunca consiga fazê-la crescer sem limite.

### Notas de segurança

- O token é comparado em tempo constante. Um token incorreto sempre resulta em um `403` puro e simples, sem nenhum sinal de tempo.
- Sirva o visualizador por HTTPS se o Immich o alcança através de algo menos confiável do que uma rede bridge privada — o token viaja em um cabeçalho a cada envio.
- Para rotacionar, altere a variável de ambiente e o cabeçalho do workflow do Immich juntos, depois reinicie o visualizador.
- O webhook lê as colunas de avaliação globais, então, no modo multiusuário, ele espelha a avaliação compartilhada/global, não a camada de nenhum usuário específico. Se o que você quer no Immich são avaliações por usuário, deixe o webhook desativado e use `--immich-sync --user <nome>` em uma agenda.

## Referência de configuração

O bloco `immich` completo, com os padrões de fábrica:

```json
"immich": {
  "url": "",
  "api_key": "",
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
| `path_map` | um par vazio | Reescritas de prefixo entre os caminhos do Facet e os valores de `originalPath` do Immich. O primeiro que corresponder vence; usado nas duas direções. |
| `push.ratings` | `true` | Envia as avaliações por estrelas de 1 a 5 (e suas limpezas). |
| `push.favorites` | `true` | Envia `isFavorite` (e suas limpezas). |
| `push.rejected` | `false` | Envia `rating: -1` para fotos rejeitadas no Facet. Requer `push.ratings`. |
| `push.top_picks_album` | `""` | Nome do álbum a preencher. Vazio significa que o Facet nunca toca em álbuns. |
| `push.top_picks_min_rating` | `4` | Avaliação mínima por estrelas para esse álbum. |
| `webhook.token_env` | `""` | Nome da variável de ambiente que guarda o segredo do webhook. Vazio ⇒ o endpoint retorna 404. |
| `webhook.header` | `"x-facet-token"` | Cabeçalho em que o Immich envia o token. |
| `webhook.max_pending` | `500` | Teto para a lista de caminhos lembrados mas ainda não pontuados. |
| `timeout_seconds` | `30` | Timeout HTTP por requisição. |

## Solução de Problemas

### Tudo volta como `unmatched`

O mapeamento de caminhos está errado — essa é, disparadamente, a falha mais comum.

1. Abra uma foto no Immich e pressione `i`. Anote o caminho no painel de informações.
2. Encontre o caminho da mesma foto no Facet (o painel de detalhes da galeria, ou `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. Os dois compartilham um *sufixo*. O que difere é o prefixo, e esses dois prefixos são exatamente `facet_prefix` e `immich_prefix`.

Armadilhas comuns:

- **Uma barra final ausente.** `"/mnt/photos"` → `"/usr/src/app/external"` também reescreve `/mnt/photosXYZ/a.jpg`. Sempre termine os dois prefixos com `/`.
- **Caminho do host vs. caminho do container.** O caminho do Immich é o que o *container* vê. `docker compose exec immich-server ls /usr/src/app/external` resolve a dúvida.
- **Symlinks e bind mounts.** O Immich armazena o caminho que ele percorreu. Se a sua biblioteca é alcançada por um symlink em um dos lados, as strings diferem mesmo sendo o mesmo arquivo.
- **Maiúsculas/minúsculas e Unicode.** A comparação é exata. Uma biblioteca em um compartilhamento sem distinção entre maiúsculas e minúsculas pode conter tanto `/Photos/` quanto `/photos/`; só a grafia armazenada dá match.
- **O Immich ainda não indexou o arquivo.** Execute **Scan All Libraries** e verifique se o ativo realmente existe no Immich antes de culpar o mapeamento.

`--immich-sync --dry-run` lista os primeiros 20 caminhos não correspondidos no log; essa lista geralmente identifica o prefixo errado à primeira vista.

### `--immich-test` falha

- `Unsupported Immich URL scheme` — `url` precisa de `http://` ou `https://`.
- `HTTP 401` — a chave de API está errada ou foi revogada.
- `HTTP 403` — a chave é válida, mas não tem `server.about`. Recrie-a com os seis escopos acima.
- Conexão recusada / timeout — a porta está errada, ou o Facet não consegue alcançar o container. Teste com `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` a partir da máquina que roda o Facet.

### O webhook retorna 404

O recurso está desativado. Ou `webhook.token_env` está vazio, ou a variável que ele nomeia não está definida ou está vazia *no próprio ambiente do visualizador*. Exportá-la no seu shell interativo não faz efeito nenhum para um visualizador gerenciado por systemd ou Docker — defina-a no arquivo de unit ou no arquivo compose e reinicie.

### O webhook retorna 401 ou 403

`401` significa que nenhum token chegou: o nome do cabeçalho que o Immich envia não corresponde a `webhook.header`. `403` significa que um token chegou e estava errado — compare o valor do cabeçalho do workflow com a variável de ambiente, caractere por caractere.

### `ModuleNotFoundError: No module named 'sync'`

O servidor inicia e parece saudável, mas o webhook falha apenas quando o Immich realmente o chama, e `--immich-sync` falha de imediato. Confirme com:

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

Um `ModuleNotFoundError: No module named 'sync'` significa que sua imagem é anterior à correção — `sync/` estava ausente do build do Docker. Baixe a imagem atual, ou reconstrua a partir de um checkout que inclua a correção.

### As avaliações são enviadas, mas as limpezas não

O Facet só envia uma limpeza para uma foto que ele realmente enviou antes; essa memória vive em `stats_cache`, no banco de dados do Facet. Restaurar um banco de dados mais antigo (ou rodar contra um banco novo) faz com que ela se perca, e uma avaliação limpa durante essa lacuna não será desfeita no Immich. Reavalie e limpe a foto novamente, ou corrija diretamente no Immich.

### As avaliações aparecem nas fotos erradas

Dois arquivos com o mesmo `originalPath` não podem acontecer dentro do Immich, mas duas raízes *Facet* mapeando para o mesmo prefixo do Immich podem colidir. Verifique se os seus pares de `path_map` não se sobrepõem: o primeiro par que corresponder vence, então um par amplo listado antes de um mais específico o engole.

### `rating: 0 is not valid`

O servidor Immich é mais antigo que 3.0. Atualize-o — a semântica de limpeza do Facet precisa de `null`, e `push.rejected` precisa de `-1`; não há fallback que funcione no 2.x.

---

**Ver também:** [Comandos — Sincronização com o Immich](COMMANDS.md#sincronização-com-o-immich) · [Configuração](CONFIGURATION.md) · [Receitas de Interoperabilidade com Editores](INTEROP.md) para o round-trip de XMP com Lightroom, darktable e digiKam.
