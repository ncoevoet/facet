# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · **Português** · [简体中文](../zh/AGENTS.md)

O Facet pode atuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), de modo que um assistente de IA compatível com MCP possa pesquisar e inspecionar a sua biblioteca com os filtros da galeria. Expõe catorze ferramentas de leitura que não alteram nada e quinze ferramentas `ui_*` que controlam a aba do navegador que tem aberto (página, filtros, seleção) sem escrever dados da biblioteca. Os tokens com um nível suficiente também podem [alterar a biblioteca](#alterar-a-biblioteca) (classificações, marcadores, etiquetas, álbuns, triagem e exclusão) e usar a [câmara escura](#câmara-escura-grupos-de-triagem).

## Ativá-lo

O endpoint está **ativado por padrão**. Para o desligar, defina `viewer.mcp.enabled` como `false` em `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) e reinicie o visualizador, ou recarregue a configuração. `/mcp` e todas as rotas `/api/mcp/*` respondem então 404.

**Instalações abertas.** Sem `viewer.password` a instalação é considerada aberta, mesmo que `viewer.edition_password` esteja definida. Em uma instalação aberta:

- os tokens são `readonly`, a menos que `viewer.trusted_local_editing` esteja ativo, ou que o token seja de edição completa, criado em uma sessão com a senha de edição e usado do mesmo computador (veja abaixo);
- o endpoint serve apenas uma chave anônima só de leitura, que não concede nada que a `/api` aberta não conceda já;
- os tokens só podem ser gerenciados a partir do computador onde o Facet está rodando, ou em uma sessão de edição quando `viewer.edition_password` está definido (ver [Criar um token](#criar-um-token)).

O endpoint é `POST /mcp` na porta do visualizador: Streamable HTTP, sem estado, respostas JSON simples (`GET` responde 405). Só a ponte da aba, `/api/mcp/bridge`, é um WebSocket; veja [Controlar a aba aberta](#controlar-a-aba-aberta).

## Criar um token

O mais simples é o navegador:

1. Com `viewer.mcp.enabled` ativo, abra o menu da conta e escolha **Ligar um assistente**.
2. Informe um **Nome** e escolha **O que o assistente pode fazer**: **Apenas ler e controlar**, **Agir como eu** ou **Edição completa**. Um token não pode superar a sessão que o cria.
3. Clique em **Criar token**. A caixa mostra **Cole isto no seu assistente**, um prompt já pronto que contém o token. É mostrado uma única vez: clique em **Copiar prompt**, cole-o no seu assistente e clique em **Concluir**.

**Gerenciar tokens (N)** lista os seus tokens com a última utilização e permite revogar um. Uma linha de estado indica se esta aba está conectada, para que os assistentes o possam controlar.

A caixa só oferece os níveis que o servidor concederá:

- uma instalação aberta oferece **Apenas ler e controlar**, e **Edição completa** nos casos indicados abaixo;
- **Agir como eu** só aparece em instalações multiusuário;
- **Edição completa** só aparece em uma sessão de edição; em uma instalação aberta isso significa um navegador no mesmo computador com `viewer.trusted_local_editing`, ou uma sessão conectada com `viewer.edition_password` (o token então só edita a partir do mesmo computador).

O prompt indica o nível efetivamente concedido. Em uma instalação aberta, aberta a partir de outra máquina sem sessão de edição, a caixa mostra «Numa instalação aberta, os tokens do assistente só podem ser geridos a partir do computador onde o Facet está a correr. Defina viewer.password para os gerir a partir de outra máquina.» em vez do formulário.

Alternativa por script (curl):

Um assistente se autentica com um token pessoal que começa por `fct_`. Crie um com um pedido autenticado. O token é devolvido **uma única vez**; o Facet salva apenas o seu hash SHA-256:

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

A resposta traz o texto simples em `token`.

- `GET /api/mcp/tokens` lista os seus tokens (nunca o segredo); `DELETE /api/mcp/tokens/{id}` revoga um.
- Um superadmin pode listar os tokens de todos os proprietários com `?all=1` e revogar qualquer um.
- Cada proprietário pode ter no máximo 20 tokens ativos.
- Estas rotas recusam as credenciais de um agente, por isso um assistente nunca pode criar, listar nem revogar tokens.

Em uma instalação aberta (sem `viewer.password`) estas rotas recusam também qualquer pedido que não venha do computador onde o Facet está rodando:

- um pedido que passe por um proxy inverso (qualquer cabeçalho `Forwarded`, `X-Forwarded-*` ou `X-Real-IP`);
- um pedido dirigido a um IP da rede local ou a um nome de host em vez de `localhost`, `127.0.0.1` ou `[::1]`;
- um pedido que chegue pela rede bridge do Docker.

Execute a receita acima no host do Facet (por SSH em um NAS; no Docker, `docker compose exec facet python -c "import urllib.request ..."`, porque a imagem não tem curl) ou defina `viewer.password`. Uma sessão iniciada com `viewer.edition_password` é aceita a partir de qualquer máquina. Um proxy inverso tem de enviar `X-Forwarded-For` ou `Forwarded`; caso contrário é tratado como a máquina local.

## Ligar o seu assistente

O prompt da caixa contém tudo o que um assistente precisa: o nome do servidor `facet`, o URL (`http://<host>/mcp`), o transporte (Streamable HTTP), o cabeçalho `Authorization: Bearer fct_...`, o nível concedido e uma chamada à ferramenta `status` para confirmar a conexão. Cole-o no seu assistente, ou adicione você mesmo o servidor ao seu cliente MCP. Use HTTPS quando o visualizador for acessível além da sua máquina: o token viaja em um cabeçalho em cada chamada.

## Níveis de permissão

Um token é criado com um nível concedido: `readonly`, `user` ou `edition`. Em cada chamada o nível **efetivo** é recalculado como o menor entre o nível concedido e o atual do proprietário. Cada ferramenta tem o seu próprio nível mínimo, verificado antes de ler ou escrever o que quer que seja; um token inferior recebe `forbidden_level`.

- **Instalações com senha única** não têm nível `user`. Um nível `user` é limitado a `readonly` na criação, e o nível efetivo é `edition` ou `readonly`. As ferramentas marcadas `user` em [Alterar a biblioteca](#alterar-a-biblioteca) precisam por isso de um token `edition`; um token inferior recebe `forbidden_level`, indicando que precisa de `edition`. Um token `edition` exige uma sessão de edição e só funciona enquanto a senha de edição não mudar.
- **Instalações multiusuário.** Se o proprietário for despromovido, o token `edition` desce para `user`. Uma promoção nunca eleva um token acima do nível concedido.
- **Instalações abertas** (sem `viewer.password`, mesmo que `viewer.edition_password` esteja definida). Os tokens pertencem a um proprietário compartilhado `_anonymous` e são `readonly`, a menos que `viewer.trusted_local_editing` esteja ativo ou o token venha de uma sessão de edição (os dois itens seguintes).
- **Edição local em uma instalação aberta.** Com `viewer.trusted_local_editing` ativo, a caixa Ligar pode criar **Edição completa** a partir de um navegador no mesmo computador. `viewer.mcp.enabled` e um token continuam necessários (uma chamada sem token continua sendo 401).
  - O token é `edition` apenas para pedidos `/mcp` da mesma máquina: par em loopback, URL `http://localhost:<port>` ou `127.0.0.1` e sem cabeçalhos de proxy. Servem tanto `:4200` (o proxy de desenvolvimento do `ng serve`) como `:5000`.
  - Qualquer outro pedido passa a `readonly`, mesmo que o prompt diga Edição completa: um cliente da rede local, um URL com nome de host ou `0.0.0.0`, ou uma implantação Docker.
  - Qualquer senha baixa o token para `readonly`; remover a senha o reativa.
  - As ferramentas de exclusão continuam precisando de `viewer.mcp.allow_destructive`.
  - A análise (`start_scan`, `scan_status`) funciona sem `viewer.features.show_scan_button`, como para o navegador local.
- **Senha de edição em uma instalação aberta.** Com `viewer.edition_password` definida e sem `viewer.password`, uma sessão conectada com a senha de edição pode criar **Edição completa**, de qualquer máquina; qualquer outra sessão recebe `readonly`.
  - O token só é `edition` para requisições a `/mcp` que passam pela mesma verificação de mesmo computador acima. Um cliente da LAN ou uma requisição por proxy recebe `readonly`: o token é um segredo ao portador em uma instalação que qualquer um pode ler.
  - Alterar ou apagar a senha de edição o reduz a `readonly`; crie um novo após a alteração.
  - A análise ainda exige `viewer.features.show_scan_button`, como uma sessão de edição no navegador. As ferramentas de exclusão ainda exigem `viewer.mcp.allow_destructive`.

> **Aviso:** `ng serve --host 0.0.0.0`, ou qualquer proxy no mesmo host que não acrescente cabeçalhos de proxy, deixa um cliente da rede local que envie `Host: localhost` passar por local. Resta então apenas o token a proteger `/mcp`.

Um token deixa de funcionar quando as credenciais do seu proprietário mudam: a senha do visualizador ou de edição (modo de senha única), a senha do proprietário (modo multiusuário) ou a exclusão da conta do proprietário. Passa então a responder 401.

## Ferramentas

As catorze ferramentas de dados são só de leitura:

| Ferramenta | O que faz |
|------|--------------|
| `search_photos` | Filtra e ordena a biblioteca como a galeria, aplicando as ocultações padrão do visualizador (piscadas, rajadas, duplicados, brackets, panorâmicas, rejeitadas) a menos que o filtro as defina (informa `hidden_summary`). Mostrado por padrão na sua aba aberta (veja abaixo); `fields` acrescenta qualquer coluna da foto |
| `semantic_search` | Encontra fotos pelo significado, ou por palavras das legendas com `scope: "text"` As linhas devolvidas são fixadas na aba. `filters` restringem a pesquisa como os da galeria, e cada linha traz a sua `similarity`. |
| `get_photo` | Detalhe completo de uma foto a partir do seu caminho (sem o histograma); ou `target: "selection"` (com `tab_id`) para a única foto selecionada |
| `get_photo_stack` | Ler a pilha local por caminho exato, ou null |
| `get_thumbnail` | Ver uma foto: a miniatura como parte de imagem (`size` de 160 a 640, 512 por padrão). Usa-se um tamanho menor se o JPEG excedesse `viewer.mcp.max_image_bytes`; `too_large` se nenhum couber; ou `target: "selection"` (com `tab_id`) para a única foto selecionada |
| `contact_sheet` | Ver de 1 a 16 fotos como uma grade numerada (`columns` de 2 a 4, lado mais comprido 1024). A parte de texto lista `legend` (número da célula e caminho, na ordem pedida) e `unavailable` (células em branco porque a foto falta ou não é visível); ou `target: "selection"` para as fotos selecionadas (no máximo 16) |
| `possible_faces` | Rostos parecidos com uma pessoa reconhecida: semelhança cosseno com o centroide da pessoa, os melhores primeiro, apenas o mesmo modelo de embedding. `scope` é `unassigned` (padrão), `unnamed` (rostos sem grupo ou num grupo que ninguém nomeou), `other_persons` ou `all`; `min_similarity` é 0,30 por padrão; `limit` até 100. Uma análise com mais de 192000 rostos é recusada (`too_large`): restrinja com `scope`, `path_prefix`, `date_from` ou `date_to`. As fotos são mostradas na sua aba. Cada linha inclui o campo `owner` (`ungrouped`, `unnamed_group` ou `named`). `candidates` é o número de rostos no escopo que pode ver, antes da verificação da dimensão do embedding; `faces_scanned` é o número de linhas realmente pontuadas. |
| `similar_photos` | Fotos semelhantes a uma foto, por embedding visual ou por cor; `min_similarity` (de 0 a 1) define o limite |
| `filter_options` | O vocabulário que um filtro aceita: câmeras, objetivas, etiquetas, pessoas, padrões, categorias, momentos narrativos, tipos de lixo, intervalos de métricas |
| `list_persons` | Pessoas reconhecidas, filtráveis por nome; `show: true` abre `/persons` com esta pesquisa |
| `list_albums` | Álbuns que o proprietário do token pode ver; `show: true` abre `/albums` com esta pesquisa |
| `library_stats` | Estatísticas da biblioteca: `kind` escolhe o resumo de tamanho e pontuações (padrão) ou qualquer dado da página Estatísticas (veja abaixo) |
| `status` | Quem é o token, o seu nível efetivo, as sinalizações do servidor e as abas abertas que pode controlar |
| `available_actions` | As tarefas que se aplicam agora à sua aba aberta e a este token, cada uma com as suas ferramentas; ferramentas acima do nível do token não são listadas |

Notas sobre os filtros:

- `show_rejected` é um booleano: `true` lista apenas as fotos rejeitadas; `false` ou omitido dá a listagem normal. Os agentes podem aplicá-lo com `ui_set_gallery_filters` para mostrar na aba as pesquisas só de rejeitadas. Os álbuns inteligentes também o podem salvar (false é omitido).
- Um `review_status` explícito determina a decisão de revisão em vez de `show_rejected` ou `hide_rejected`, e desativa `show_rejected` na aba.
- `show_rejected: true` com `favorites_only: true` é recusado nas alterações da aba e na criação de álbuns inteligentes (`invalid_input`). A pesquisa continua devolvendo a interseção, mas informa `shown_in_tab.reason: invalid_combination` e mantém a aba inalterado.
- `blinks_only` e `duplicates_only` também são booleanos. `true` mantém apenas as fotos marcadas como piscada, ou os membros de um grupo de duplicados (líderes incluídos). Como `show_rejected`, mostram cada uma dessas fotos independentemente dos interruptores de ocultação.

## Os resultados aparecem na sua aba

- **As pesquisas aparecem na sua aba.** `search_photos`, `semantic_search` e `similar_photos` aceitam `show` (padrão `true`). Depois de uma pesquisa bem-sucedida da primeira página, o servidor a mostra na sua aba do Facet aberto, para que veja o que o assistente encontrou sem precisar de pedir.
  - `search_photos` e `similar_photos` aplicam a mesma consulta à aba, substituindo os filtros dele.
  - `semantic_search` fixa exatamente as linhas devolvidas (ordem de similaridade, no máximo `limit`, com ou sem `filters` ou `scope`) como lista escolhida pelo assistente (`shown_in_tab.mode` é `paths`), porque a vista semântica própria da aba filtra e ordena de outra forma.
  - `show: false` serve para sondagens intermediárias e contagens; os assistentes são instruídos a nunca perguntar se devem mostrar os resultados.
- O resultado traz `shown_in_tab`: `{"applied": true, "tab_id", "keys", "total"}`, ou `{"applied": false, "reason"}`. Motivos: `error` (a própria exibição falhou), `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (a aba ainda a pode aplicar), `forbidden`, `invalid_input`, `upstream_error`, `page_not_first`, `empty_result`, `unsupported_filters` (com `keys`), `invalid_combination`, `unsaved_decisions`, `navigation_refused` (a aba recusou a navegação), `comparison_open` (o usuário está em `/compare`) e `modal_open` (há uma caixa de diálogo, uma folha inferior ou uma apresentação aberta na aba). Uma exibição que falha nunca faz a pesquisa falhar. Passe `tab_id` para escolher uma aba. Quando linhas são cortadas, `next_page` (com `suggested_per_page`) indica a página que continua logo após a última linha devolvida; quando as páginas não conseguem expressar esse ponto, `next_offset` o dá como deslocamento de linhas.
- Só a primeira página é mostrada (a aba pagina sozinho ao rolar) e um resultado vazio não é mostrado, para que mantenha a vista anterior. Uma pesquisa com filtros para os quais a barra lateral da galeria não tem campo (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`) nunca é aplicada parcialmente.
- Mostrar sai de `/photo` para a galeria. Só sai de `/culling` se o usuário não tiver aí decisões por confirmar (caso contrário, `unsaved_decisions`), e em `/compare` é recusado com `comparison_open`. Limpa uma seleção de toda a vista. Na página de um álbum, volta primeiro à galeria, de modo que os filtros salvos do álbum nunca são sobrescritos. Uma pesquisa cuja contagem alimenta o `expected_count` de uma ferramenta de escrita deve usar `show: false`.
- `list_albums`, `list_persons` e `junk_list` aceitam `show` (`false` por padrão: são sobretudo pesquisas de nomes). Com `show: true` abrem `/albums`, `/persons` ou `/junk` com exatamente essa consulta; uma consulta vazia limpa a pesquisa da página e restaura os restantes filtros. `junk_list` só mostra a primeira página (caso contrário, `page_not_first`) e nunca uma lista vazia (`empty_result`). `shown_in_tab` traz os mesmos motivos de uma pesquisa, com `mode` `route`. `list_culling_groups` não tem `show`: use `ui_show_culling_group`.
- `ui_show_photos` fixa uma lista exata de fotos, mostradas na sua ordem até uma alteração de filtros a substituir. `ui_get_context` indica se uma lista fixada é mostrada. A lista é simples: sem grupos, marcas nem etiquetas. Para revisar um plano de triagem, o assistente usa `auto_cull`, que abre o plano na [câmara escura](#câmara-escura-grupos-de-triagem) (`/culling`).
- **Modo de plano em `/culling`.** `ui_show_culling_plan` (chamado por `auto_cull` em uma simulação) carrega um plano de `auto_cull` na câmara escura. Obtém os mesmos grupos, bordas manter/rejeitar, lupa e comparação da triagem manual, com as fotos a manter do plano pré-selecionadas. Veja [Modo de plano do assistente](VIEWER.md#modo-de-plano-do-assistente).
  - O usuário vê um banner «Plano do assistente · x/y confirmados · Sair», um chip «#n · motivo · sugerido: manter N / rejeitar M» por grupo, e confirma grupo a grupo como de costume. A ordenação e o limiar ficam desativados; o controle deslizante do rigor continua utilizável.
  - Mover o controle, ou alterar o intervalo de datas da barra de ferramentas, volta a planejar (novo `plan_digest`). Os grupos que inverteu mantêm a sua escolha. Um grupo volta a formar-se como confirmado quando cai dentro de um grupo que confirmou, grupos de cena incluídos; com `group_by=all`, uma rajada confirmada cujas fotos mantidas reaparecem dentro de um grupo similar maior é oferecida de novo (as suas rejeições continuam aplicadas). Os grupos ignorados voltam. Uma confirmação cuja contagem regressiva ainda está em andamento é aplicada de imediato. Confirmar, ignorar e «confirmar tudo» ficam em pausa até chegar o novo plano.
  - Um intervalo de datas mais estreito transporta as inversões e os grupos confirmados pelo seu conjunto de fotos. Os grupos fora da janela desaparecem e um aviso indica as inversões perdidas. **Todas as datas** volta a planejar toda a biblioteca e pode atingir o limite do plano (`plan_truncated`).
  - **Sair**, ou alterar o agrupamento, o escopo álbum/cena ou a ordenação, abandona o modo de plano. Sair de `/culling` e voltar restabelece o plano. Um recarregamento completo da página o descarta mas mantém o álbum e as datas no URL (`?from=`, `?to=`), em um fluxo manual. As confirmações em modo de plano nunca acrescentam destaques.
  - **Distintivos de sugestão.** `ui_suggest_culling` marca as fotos a manter ou rejeitar, com um motivo curto (um distintivo tracejado), e acrescenta notas aos grupos (um chip no cabeçalho). Um clique em um distintivo inverte essa foto; sem clique nada muda. As marcas sobrevivem a mudanças do controle ou do intervalo de datas e a mostrar de novo o mesmo plano; outro plano, **Sair** ou sair do modo de plano as apaga. Os distintivos aparecem apenas nas miniaturas do grupo, não na vista de tela inteira nem em grupos confirmados ou ignorados.
  - A resposta do assistente lista os caminhos que não salvou: `redundant` (já é a escolha do plano), `closed` (grupo confirmado ou ignorado) e `missing` (não estão no plano). As notas de um grupo que confirmou, ignorou ou está confirmando ficam listadas em `groups_closed`. `suggestions_total` e `notes_total` indicam o que a aba retém (no máximo 300 sugestões e 100 notas).
- **Ler o seu progresso.** `ui_get_context.culling` é `null` fora do modo de plano. Em modo de plano devolve `{plan_digest, groups_total, confirmed, pending, changed, untouched, plan_truncated}`:
  - `confirmed`: os números de grupo do plano cuja confirmação já chegou.
  - `pending`: os grupos que inverteu em relação ao plano e não confirmou.
  - `untouched`: o número dos restantes grupos.
  - `changed`: cada grupo cujas fotos mantidas diferem do plano, como `{type, group_id, number, keep_paths, reject_paths}`.
  - `plan_truncated` é `true` quando o próprio plano atingiu o limite de grupos ou de fotos e lista apenas parte dos grupos.
  - Um bloco demasiado grande para uma resposta (o teto de 100 KiB da aba, ou o do servidor) tem as listas encurtadas e `truncated` como `true`. As contagens reais ficam em `groups_total`, `confirmed_count`, `pending_count` e `changed_count`.
  - `culling.scope` (`{album_id, date_from, date_to}`) é a janela para a qual o plano foi calculado.
  - `suggestions_open` (`[{path, action}]`) lista as marcas ainda à espera do seu clique, `suggestions_accepted` as marcas cuja foto colocou no estado sugerido e `suggestions_total` as marcas de fotos que a aba retém (não as notas de grupo). `suggestions_open_count` indica o comprimento real quando essa lista é cortada.

  Nunca volte a decidir um grupo confirmado. Uma rajada ou um grupo similar confirmado sai da pré-visualização seguinte. Um grupo de cena confirmado não fica registrado em lado nenhum e pode ser proposto de novo, por isso passe `changed` como `keep_paths` / `remove_paths` na simulação seguinte e na sua aplicação. `auto_cull` toma as datas apenas dos próprios argumentos: passe as datas de `culling.scope` juntamente com `culling.changed` na simulação seguinte (o novo plano substitui o mostrado). Mover o controle ou o intervalo de datas volta a planejar, por isso volte a ler `ui_get_context` antes da simulação seguinte.
- **Padrões de triagem.** `ui_get_context` devolve ainda `culling_defaults`, `{profile, strictness}`: as configurações que `auto_cull` usa quando não recebe nenhuma (veja **Configurações vindas da aba** na [Câmara escura](#câmara-escura-grupos-de-triagem)). São salvas por navegador, por isso duas abas as compartilham. `culling_defaults.strictness` é o valor vivo e salvo do controle deslizante: `null` quando só há um perfil salvo, 100 quando não há nenhum dos dois. Um plano dado com perfil e `strictness` salva ambos. Mover o controle fora do modo de plano apaga o perfil salvo (mistura personalizada); em modo de plano o mantém.
- **Datas.** As ferramentas de triagem (`auto_cull`, `list_culling_groups`, `suggest_culling_profile`) aceitam uma data ISO (`2026-06-01`), uma data e hora ISO (`2026-06-01T08:30:00` ou com espaço) ou a forma EXIF (`2026:06:01 08:30:00`). Um `date_to` sem hora cobre o dia inteiro. As ferramentas com granularidade de dia (`library_stats`, `possible_faces`, `cull_report` nas contagens e nos conjuntos da câmara escura) só aceitam uma data e recusam uma hora com `invalid_input`.
- As linhas trazem câmera, objetiva, abertura, velocidade do obturador, ISO, distância focal e `is_monochrome`. `fields` (nas três ferramentas de pesquisa) acrescenta qualquer outra coluna da foto, exceto dados de imagem e de embeddings, por exemplo `leading_lines_score`. `learned_score` só é preenchido ao ordenar por ele. Quando o limite de bytes corta linhas, o resultado acrescenta `returned` (e `next_offset` ou `suggested_per_page`).
- `library_stats` aceita `kind` (padrão `overview`: tamanho, contagens por tipo e resumo das pontuações). O `basis` da visão geral indica o que cada total conta. `total_photos` conta as fotos que pode ver dentro de `date_from`/`date_to` e da categoria (todas se nenhuma for indicada); ignora os interruptores de ocultação e inclui as fotos rejeitadas. `type_counts` aplica os interruptores de ocultação e ignora a data e a categoria. Os demais valores são só de leitura e devolvem os dados da página Estatísticas; listas longas são cortadas em 50 entradas com `truncated: true`:

| Valor de kind | Dados |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | Os painéis da página Estatísticas; aceitam `date_from`, `date_to` e `category`. `correlations` aceita também `x`, `y` (lista separada por vírgulas), `group_by` e `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Estatísticas por categoria (sem parâmetros) |
| `timeline_dates`, `timeline_months` | Número de fotos por dia ou por mês; exigem `year` (`timeline_dates` aceita também `month`) |
| `timeline_years` | Número de fotos por ano |

## Controlar a aba aberta

Ao lado das ferramentas de dados, o servidor lista sempre quinze ferramentas `ui_*` que atuam sobre a aba do Facet que tem aberto: mudam de página, alteram os filtros ou a seleção e voltam a ler o que vê. Nunca escrevem dados da biblioteca, por isso basta um token `readonly`.

| Ferramenta | O que faz |
|------------|-----------|
| `ui_navigate` | Ir para uma página (galeria, pessoas, álbuns, estatísticas, ...) |
| `ui_set_gallery_filters` | Juntar uma alteração aos filtros e à ordenação da galeria (`null` remove um filtro, `replace: true` parte do zero) |
| `ui_get_gallery_view` | Rota, filtros ativos, total de resultados, os primeiros caminhos de fotos visíveis e o número de fotos selecionadas; devolve também `album_filter_json` (os filtros como um álbum inteligente os salvaria) e `filters_scopable` (se descrevem toda a vista) |
| `ui_get_context` | A página aberta (rota), o estado da galeria (total, quantidade carregada, se uma lista fixada é mostrada), o número de fotos selecionadas e as `actions` que aqui se aplicam ao seu token; também `focused` (a foto em que o usuário está), `culling` (o plano do assistente em `/culling`: grupos confirmados, pendentes e alterados, e o `scope` para o qual foi calculado), `culling_defaults` (`{profile, strictness}`: o perfil salvo e o rigor vivo e salvo do controle deslizante, por navegador; `auto_cull` usa ambos quando não lhe é dado nenhum) e `user_activity` (o que o usuário fez), e aceita `activity_since` (ver abaixo); também `page` e `overlays` (veja abaixo) |
| `ui_open_photo` | Abrir uma foto |
| `ui_open_album` | Abrir um álbum (fixo ou inteligente) por `album_id`; um id desconhecido ou inacessível responde `not_found` |
| `ui_show_photos` | Mostra exatamente estes `paths` (até 200) por esta ordem como lista da galeria; os inalcançáveis voltam em `missing`. Qualquer alteração de filtros substitui a lista |
| `ui_select_photos` | Selecionar `paths` explícitos, ou toda a vista filtrada com `select_view: true`, em modo `replace`, `add` ou `remove` |
| `ui_clear_selection` | Limpar a seleção |
| `ui_get_selection` | O `scope` (`paths` ou `view`) e o `count`, com os `paths` ou, em uma vista, os `filters` e os `excluded_paths` |
| `ui_next_page` | Carregar a página seguinte da galeria |
| `ui_show_culling_group` | Abrir a câmara escura em um grupo, identificado por `(type, group_id)` (contas de edição) |
| `ui_show_culling_plan` | Abre a câmara escura em um plano de `auto_cull` (`plan_digest` e `request` da pré-visualização, `focus` opcional: número de grupo), com as fotos a manter do plano pré-selecionadas para as inverter e confirmar (contas de edição). `auto_cull` a chama por si em uma simulação. O mesmo digest do plano já mostrado só move o foco; um diferente substitui o plano e é recusado como `unsaved_decisions` enquanto tiver decisões por confirmar, e como `plan_changed` quando a biblioteca mudou desde a pré-visualização, e como `plan_load_failed` quando a aba não conseguiu carregar o plano por outro motivo |
| `ui_suggest_culling` | Enquanto um plano é mostrado em `/culling`, marca as fotos que manteria ou rejeitaria (`photos`: `path`, `action`, `reason`, até 100) e os grupos a comentar (`groups`: o `path` de uma foto do grupo e uma `note`, até 50); um motivo ou nota tem no máximo 200 caracteres. Vê um distintivo por foto e um chip por grupo, e nada muda até clicar em um distintivo. As chamadas se fundem por caminho, `replace: true` descarta primeiro tudo o que está retido, e `replace` com listas vazias limpa tudo. Responde `{plan_digest, applied, redundant, closed, missing, groups_applied, groups_missing, groups_closed, suggestions_total, notes_total}`; as recusas são `no_plan` (a aba não tem nenhum plano), `too_large` (a aba retém no máximo 300 sugestões e 100 notas: use `replace`) e `forbidden_level` (só contas de edição). Com várias abas abertas, passe o `tab_id` de `shown_in_tab` ou `status` |
| `ui_show_comparison` | Abrir a página de comparação por pares, opcionalmente em uma categoria, em uma estratégia e em um `tab` (`ab`, `snapshots`, `suggestions`, `weights`); apenas abre a página, os vencedores são escolhidos por si |

Como funciona:

- **Conexão.** Enquanto tiver sessão iniciada e `viewer.mcp.enabled` e `viewer.mcp.bridge` forem `true`, cada aba do Facet abre um WebSocket da mesma origem para `/api/mcp/bridge`, autenticado com a sua sessão na primeira mensagem. A ponte vem ativa por padrão. Ponha `viewer.mcp.bridge` como `false` para a desativar: as abas deixam então de se conectar e as ferramentas `ui_*` passam a responder com um erro claro.
- **De quem são as abas.** Uma ferramenta só chega às abas do dono do token. Com uma única senha todas as sessões são o mesmo usuário; em uma instalação aberta cada aba pertence ao usuário compartilhado `_anonymous`, incluindo as sessões de edição.
- **Níveis das abas.** Cada aba tem o nível da sessão que o abriu. Um token só controla abas de nível igual ou superior ao seu nível efetivo: um token `edition` nunca usa uma aba com sessão apenas de consulta, enquanto um token `readonly` pode controlar uma aba `edition`.
  - Instalação com senha única: um token também é limitado pela sessão que o criou. Um token criado em uma sessão apenas de consulta só alcança abas de consulta, nunca a aba de edição (um token anterior a esta regra é limitado ao seu próprio nível).
  - Instalação aberta: um token só alcança abas de consulta, nunca uma aba `edition`, exceto a aba de edição local abaixo. Um token de edição completa criado em uma sessão com a senha de edição alcança uma aba `edition` quando usado do mesmo computador.
  - Com `viewer.trusted_local_editing` em uma instalação aberta, uma aba que passa a verificação da mesma máquina se registra como `edition` e desce para `readonly` em um ping quando a opção é desligada. As abas da rede local ou encaminhadas continuam `readonly`. Um token usado a partir da máquina local alcança essa aba seja qual for o nível com que foi criado. Um token usado a partir da rede local nunca o alcança e recebe `no_tab`, com uma mensagem a explicar que um pedido não local não pode controlar uma aba de edição local.
  - Uma aba só pode ser substituída por outra de nível igual ou superior: uma sessão apenas de consulta que reutilize o `tab_id` de uma aba `edition` é recusada com 4409. Acima do limite de abas por usuário, sai primeiro o de nível mais baixo.
  - `status` lista apenas as abas que o token pode controlar e indica `out_of_reach_tabs`, o número de abas abertas que não consegue controlar.
- **Várias abas.** Usa-se a que teve o foco mais recentemente, e o campo `tab` do resultado indica qual. Passe `tab_id` (listado por `status`) para escolher outro.
- Uma aba recusa o que a sua conta não pode fazer (por exemplo `/culling` para uma conta sem edição) e a ferramenta devolve essa recusa.
- O que uma aba devolve não é confiável: a profundidade e o comprimento de cadeias e listas são limitados, e tudo fica contido por `max_bytes`.
- Erros: `no_tab` (nenhuma aba conectada ou aberta, ou ponte desativada: abra o Facet em um navegador e inicie sessão), `tab_timeout` (sem resposta em `call_timeout_s`) e `tab_outdated` (a aba aberta não conhece a ferramenta; recarregue a página depois de atualizar o Facet).
- A ponte aceita primeiro o WebSocket e depois o recusa com um código de fechamento em vez de um estado HTTP: 4404 se o endpoint ou a ponte estiver desativado (a aba fica desconectada até a página ser recarregada), 4403 se faltar `Origin` ou não for permitido, 4401 para uma sessão ausente ou rejeitada.
- **Proxy inverso.** Tem de encaminhar a atualização para WebSocket em `/api/mcp/bridge`; veja [Implantação](DEPLOYMENT.md). Se reescrever o cabeçalho `Host`, indique a origem pública em `viewer.mcp.allowed_origins` (por exemplo `["https://photos.example.com"]`): a origem da página tem de coincidir com o host ou constar da lista.
- **O que o usuário está fazendo.** `ui_get_context` devolve ainda:
  - `focused`, `{path}`: a foto sob o cursor do teclado na galeria, a foto aberta na página de foto ou a foto atual na câmara escura; caso contrário `null`. Passar o mouse não conta. Mantém-se ao mudar para a janela do assistente e é limpa quando a foto sai da lista.
  - `user_activity`, `{items, until, truncated}`: o que o usuário fez na aba, no máximo 50 itens de 20 caminhos cada, conservando os mais recentes. Não salva estado: passe o `until` da resposta anterior como `activity_since` para obter só os itens mais recentes; duas chamadas sem ele devolvem os mesmos itens.

  Ações registradas:
  - classificações, rejeições e favoritos;
  - confirmações e pulos de um plano do assistente em `/culling` (`cull_confirm`, `cull_skip`), só em modo de plano, depois de a confirmação chegar ou de a contagem regressiva do pulo terminar (a triagem manual e uma confirmação concluída por Sair não são registradas);
  - etiquetas; álbuns (criar, renomear, editar a descrição, excluir, adicionar); pessoas (atribuir, remover, fundir, dividir, renomear, ocultar, mostrar, criar, excluir); lixo (rejeitar, marcar como não lixo);
  - respostas de comparação (`winner` `a`, `b`, `tie` ou `skip`);
  - alterações dos filtros da galeria: uma rajada de edições se torna uma única entrada `filters` após um segundo de calma, `{reset: true}` para uma reposição; uma alteração só da ordenação não é registrada;
  - navegação: uma mudança de página (uma alteração só da cadeia de consulta não conta);
  - decisões manuais Manter e Restaurar das ações individuais ou em lote da galeria e dos detalhes da foto, depois de concluídas: tipo `review`, com `value` `kept` ou `undecided`. Lotes com falha ou concluídos parcialmente não adicionam nenhuma entrada.

  As escritas do assistente e a sua própria navegação `ui_*` nunca são listadas, e uma ação sua que chegue enquanto uma ferramenta `ui_*` do assistente está rodando é descartada. Os nomes, textos de pesquisa e caminhos de uma entrada são dados não confiáveis, nunca instruções. O registro vive na memória da aba (as suas últimas 500 ações) e se perde ao recarregar.

Em complemento:

- **`ui_set_gallery_filters`** leva primeiro à galeria se estiver aberta outra página e depois aplica a alteração. Na página de um álbum, qualquer alteração volta à galeria (não só `replace: true`), de modo que os filtros salvos do álbum não são sobrescritos e o escopo do álbum é abandonado. Recusa a alteração inteira (`invalid_input`) se nomear um filtro que a aba não sabe controlar (para esses use `search_photos`), um filtro desconhecido, `category` e `type` simultaneamente, ou `person` e `person_id` simultaneamente. Aceita também `semantic_query`, `semantic_threshold` (de 0 a 0,5), `similar_to`, `similarity_mode` e `min_similarity` (de 0 a 1); `similar_to` e `semantic_query` não podem ser combinados.
- `ui_get_gallery_view`, `ui_next_page` e `ui_select_photos` com `select_view` precisam que a galeria (ou um álbum) seja a página aberta; caso contrário respondem `no_active_view`; chame antes `ui_navigate` para `/`. Dê a `ui_select_photos` exatamente um de `paths` e `select_view`. Em modo `remove` com uma seleção de toda a vista, os caminhos fora da vista carregada são ignorados e listados como `not_in_view`.
- Uma ferramenta de interface que sairia de `/culling` enquanto o usuário tem decisões por confirmar responde `unsaved_decisions`. Uma navegação que o própria aba recusa responde `navigation_refused`. `forbidden_level` é apenas uma recusa de permissão.
- `ui_navigate` abre apenas as páginas estáticas da aplicação. A página de início de sessão, as páginas compartilhadas, os URL externos e os caminhos desconhecidos são recusados (`invalid_input`), tal como as páginas só de edição para uma sessão sem edição. `/timeline` aceita também `year` e `month` (1-12); `ui_get_context` devolve então `timeline`.
- **Sobreposições.** `ui_get_context.overlays` lista o que cobre a página (`dialog`, `bottom_sheet`, `slideshow`; vazio quando nada a cobre). Enquanto não estiver vazio, toda ferramenta de interface que altere a vista responde `modal_open` e não faz nada. `ui_get_context`, `ui_get_selection` e `ui_get_gallery_view` continuam respondendo, e uma pesquisa mostrada com `show` indica `shown_in_tab.reason` `modal_open` (a pesquisa em si tem êxito). Conta qualquer caixa de diálogo, incluindo as de atalhos e de edição, exceto a de conexão do assistente; menus, seletores, tooltips e snackbars não contam.
- **Estado da página.** `ui_get_context.page` é `{id, ...estado}` nestas páginas, e `null` em qualquer outra:
  - `/persons` (`persons`: `search`, `sort`, `sort_direction`, `show_hidden`)
  - `/albums` (`albums`: `search`, `sort`, `type`)
  - `/stats` (`stats`: `tab`, `category`, `date_from`, `date_to`)
  - `/map` (`map`: `date_from`, `date_to`)
  - `/timeline` (`timeline`: `date_from`, `date_to`, `sort`)
  - `/scenes` (`scenes`: `album_id`, `total`)
  - `/culling` (`culling`: `mode` (`cull` ou `stacks`))
  - `/compare` (`compare`: `tab` (`snapshots`, `ab`, `suggestions`, `weights`, `context` ou `panorama`), `category`, `strategy`, `pair_a`, `pair_b`, `pair_loading`). `tab` é `null` até se escolher uma categoria; o par é `null` enquanto a aba A/B não é mostrado.

  Os valores são lidos ao vivo e o texto livre é cortado aos 200 caracteres. Uma aba mais antiga omite `page` e `overlays`.
- A linha de estado da caixa **Ligar um assistente** mostra se esta aba está conectada; `status` lista as abas abertas e os respectivos id.
- Uma aba deixa de se religar quando a sua sessão é recusada (inicie sessão de novo). Espera que volte a ele se outro das suas abas tomou o seu lugar.

## Atualizações ao vivo

Quando um assistente altera fotos com uma ferramenta de escrita, as abas do Facet que tem abertos acompanham sem recarregar.

- **Galeria.** Os cartões alterados se atualizam no próprio local, a lista fixada do assistente se mantém e uma foto excluída da biblioteca (`delete_photos`) sai dela. Uma foto que `cull_apply` moveu ou enviou para o lixo mantém a sua linha na biblioteca, por isso permanece em uma lista fixada; as vistas que ocultam as fotos rejeitadas (o valor por padrão) já a ocultam. Uma escrita que não consegue nomear as suas fotos (ver abaixo) recarrega a vista, mantendo na tela as linhas atuais e a sua seleção até chegarem as novas. As vistas de pesquisa semântica e de fotos semelhantes atualizam as fotos já mostradas e nunca retiram nenhuma.
- **Página da foto.** Volta a pedir a sua foto; uma foto excluída da biblioteca o leva de volta.
- **Câmara escura** (`/culling`). Atualiza no local rejeição, favorito e classificação, mostra um indicador Rejeitada e mantém as suas próprias decisões. Diante de uma alteração que não consegue delimitar, só recarrega quando nada está em jogo; caso contrário, mostra um banner Recarregar até recarregar.
- **Um só aviso por rajada.** As alterações são agrupadas (debounce de 400 ms, no máximo 2 s) em um único aviso «O assistente alterou N fotos».
- **Uma entrada por chamada do assistente** no painel de atividade, com a etiqueta do nome da ferramenta no seu idioma (ou o nome original, se não tiver etiqueta), somando as fotos de toda a chamada. Acima de 200 fotos a entrada não nomeia nenhuma, por isso a vista recarrega e não há botão **Mostrar as fotos**. Depois de aplicar `auto_cull`, **Mostrar as fotos** fixa as fotos que rejeitou (até 200).
- **Que escritas.** Classificações, favoritos, rejeições, etiquetas, legendas, pertença a álbuns, triagens, exclusões, correções de sequência e de categoria, atribuições de rostos, limpeza de lixo e confirmações da câmara escura. Leituras, simulações, escritas recusadas, criação de álbuns, exportação de metadados e análises não atualizam. Uma escrita que expira (`outcome_unknown`) atualiza mesmo assim, porque pode ter sido aplicada; uma ainda em curso nesse momento surge na atualização ou recarga seguinte.
- **Escritas sem escopo.** Uma escrita dirigida a uma vista `filters`, uma que inclui os quadros irmãos de um conjunto, uma com mais de 200 fotos ou uma que não nomeia nenhum caminho recarrega a vista em vez de atualizar cartões nomeados.
- **A ponte tem de estar ativa.** Uma escrita feita por `/mcp` chega às suas abas pela ponte da aba, por isso `viewer.mcp.bridge` tem de ser `true`. Uma escrita feita pela própria página (`POST /api/mcp/call`) usa a sua resposta (`changed_paths`) e atualiza mesmo com a ponte desativada.
- **Só no mesmo processo.** Com `viewer.py --workers N` o aviso pode falhar uma aba (veja [Limitações conhecidas](#limitações-conhecidas)).
- **Após uma atualização, recarregue as abas abertas.** A lista de ferramentas mudou, por isso uma aba aberta responde `tab_outdated` até ser recarregado.

## WebMCP na página (agentes do navegador)

À parte do endpoint `/mcp`, uma aba com sessão iniciada oferece as mesmas ferramentas `ui_*` aos agentes que rodam dentro do navegador, através da API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Um assistente nativo do navegador vê exatamente as ferramentas listadas acima, as executa na aba que está vendo e não precisa de token.

- **Apenas em contexto seguro.** O Facet só registra as ferramentas em HTTPS ou em `localhost`. Em HTTP simples não são oferecidas; a conexão por token continua funcionando.
- Registram-se quando `viewer.mcp.enabled` é true e tem a sessão iniciada, e são removidas ao terminar a sessão.
- O objeto é `document.modelContext` (o alias obsoleto `navigator.modelContext` não é fornecido). É um polyfill, instalado apenas se o navegador não tiver um nativo, e não pode ser desinstalado: pode existir antes de iniciar sessão sem qualquer ferramenta do Facet e permanece depois de terminar a sessão com uma lista de ferramentas vazia.
- As ferramentas fazem o mesmo, limitadas pelo mesmo nível de conta, que na tabela acima. Um agente do navegador lê a mesma lista `actions` através de `ui_get_context`.
- **Ferramentas da biblioteca na página.** A aba também oferece as ferramentas próprias do servidor (pesquisa, classificações, etiquetas, álbuns, câmara escura, relatórios):
  - `GET /api/mcp/inpage_tools` as lista, com o esquema de cada ferramenta, o seu `required_level` e o `level` atual da sessão.
  - `POST /api/mcp/call` (`{tool, arguments, selection_snapshot?}`) executa uma como a sua sessão iniciada, pelo mesmo invólucro que `/mcp`, por isso níveis, pré-visualizações, valores `confirm` e limites de taxa se comportam de forma idêntica. Uma ferramenta que falha devolve um envelope `ok: false` normal (HTTP 200). Uma chamada também devolve `changed` (fotos escritas).
- **Nível.** O mais baixo entre o nível da sua sessão e o seu papel atual, lido de novo em cada chamada: uma conta despromovida perde as escritas de imediato e uma excluída é recusada (401). Abaixo do mínimo de uma ferramenta a resposta é `forbidden_level` («This session's level is readonly; set_rating needs edition: unlock edition in Facet»). Em uma instalação com senha única, escrever exige a edição desbloqueada.
- **Quem pode chamar.** Apenas uma pessoa com sessão iniciada. O token `/mcp` de um agente é recusado nestas rotas (403), tal como uma `Origin` estranha; um cookie sozinho nunca autentica. Cada chamada leva um cabeçalho `X-Facet-Agent-Session` (1 a 64 letras, dígitos, `_` ou `-`; responde 400 se faltar ou estiver malformado). Distingue as abas: um valor `confirm` emitido para uma aba é recusado em outro. É a página que o escolhe, por isso separa mas não autentica.
- **O que fica de fora.** As ferramentas de imagem (`get_thumbnail`, `contact_sheet`) e `available_actions` (use `ui_get_context`). O argumento `show` de uma ferramenta está sempre desligado, porque quem chama é a aba, e `tab_id` é recusado. `status` indica apenas as versões do servidor e do contrato da interface. `target: "selection"` usa o `selection_snapshot` enviado pela página (o que `ui_get_selection` devolveu). `create_album` com `target: "view"` precisa do `album_filter_json` e do `filters_scopable` que `ui_get_gallery_view` devolveu (sem eles, `invalid_input`). As ações destrutivas continuam seguindo `viewer.mcp.allow_destructive`.
- **Gosto.** Como qualquer escrita de um assistente, uma chamada de ferramenta feita a partir da página nunca registra comparações nem arma o retreino.
- **Interruptor.** `viewer.mcp.inpage_tools` (por padrão `true`) desliga as duas rotas (404) e limpa `features.mcp_inpage` em `/api/auth/status`. `viewer.mcp.enabled: false` também as desliga.

## Alterar a biblioteca

As ferramentas de escrita estão na mesma lista `/mcp` que as de leitura. Cada uma passa pelas rotas `/api` do visualizador, por isso as proteções da rota continuam valendo, e cada uma conta para o orçamento `write_rate_per_min`. O nível é o mais baixo nível efetivo que pode chamar a ferramenta (veja [Níveis de permissão](#níveis-de-permissão)).

| Ferramenta | Nível | O que faz | Limites |
|------------|-------|-----------|---------|
| `set_rating` | `user` | Define a classificação em estrelas (0-5) de fotos | 50 caminhos |
| `set_favorite` | `user` | Marca ou desmarca fotos como favoritas (marcar retira a rejeição) | 50 caminhos |
| `set_rejected` | `user` | Rejeita ou anula a rejeição de fotos (rejeitar retira a classificação e o favorito) | 50 caminhos |
| `batch_set_rating` | `edition` | Define a classificação de muitas fotos | 1000 caminhos, ou `filters` |
| `batch_set_favorite` | `edition` | Marca muitas fotos como favoritas | 1000 caminhos, ou `filters` |
| `batch_set_rejected` | `edition` | Rejeita muitas fotos | 1000 caminhos, ou `filters` |
| `add_tags` | `edition` | Adiciona etiquetas manuais (separadas das etiquetas de IA) | 10 etiquetas; 1000 caminhos, ou `filters` |
| `remove_tags` | `edition` | Remove etiquetas manuais | 10 etiquetas; 1000 caminhos, ou `filters` |
| `create_photo_stack` | `edition` | Criar uma pilha local explícita; devolve a entrada Desfazer | 2–1000 caminhos |
| `update_photo_stack` | `edition` | Substituir membros/ordem explícitos e capa opcional; revisão antiga é recusada | 1000 caminhos |
| `unstack_photos` | `edition` | Dissolver uma pilha; os originais ficam intactos |  |
| `undo_photo_stack` | `edition` | Desfazer apenas uma entrada de pilha disponível; alterações posteriores são recusadas |  |
| `create_album` | `edition` | Cria um álbum (não idempotente: duas vezes cria dois álbuns): vazio, ou a partir de `filters` / `target: "view"` como álbum inteligente que segue esses filtros, ou a partir de `paths` / `target: "selection"` como álbum fixo preenchido na mesma chamada (`added`, `skipped`). Um álbum inteligente usa os interruptores de ocultação do visualizador e em `list_albums` mostra 0 fotos. Uns `filters` sem nenhum filtro efetivo (`{}`, ou apenas interruptores de visualização desligados) são recusados como `invalid_input`: omita `filters` para um álbum vazio | |
| `album_add_photos` | `edition` | Adiciona fotos a um álbum (as já presentes são ignoradas) | 1000 caminhos |
| `album_remove_photos` | `edition` | Remove fotos de um álbum; as fotos não são tocadas | 1000 caminhos |
| `assign_faces` | `edition` | Move rostos para uma pessoa; os de outra pessoa ficam como estão salvo `allow_reassign`, e o resultado lista o que foi ignorado | 50 ids de rosto |
| `set_caption` | `edition` | Define a legenda de uma foto (semântica de conjunto; uma legenda inalterada volta como `already`) | 1 foto, 2000 caracteres |
| `export_metadata` | `edition` | Escreve sidecars XMP junto aos arquivos | 100 caminhos, ou `filters`, ou `target` |
| `junk_list` | `readonly` | Lista os candidatos da limpeza de rejeitadas, opcionalmente de um só `kind`; `show: true` abre `/junk` nesse `kind` | 100 por página |
| `junk_reject` | `edition` | Rejeita candidatos da limpeza (igual a `batch_set_rejected`) | 1000 caminhos, ou `target: "selection"` (só na página da galeria) |
| `junk_clear` | `edition` | Mantém candidatos: os marca como avaliados e limpos para saírem da fila | 50 caminhos |
| `cull_apply` | `edition` | Copia as fotos a manter, ou move ou envia para o lixo as rejeitadas ([pré-visualizar e confirmar](#ações-destrutivas-pré-visualizar-e-confirmar)) | 10000 caminhos, ou `filters` |
| `delete_photos` | `edition` | Envia os arquivos para o lixo e exclui as suas linhas da biblioteca ([pré-visualizar e confirmar](#ações-destrutivas-pré-visualizar-e-confirmar)) | 1000 caminhos |

### Pilhas manuais locais

- `get_photo_stack(path)` lê a pilha local do chamador, ou null. Com visibilidade parcial devolve apenas os membros permitidos, e a pilha fica só de leitura.
- `create_photo_stack(paths, cover_path)` exige 2–1000 fotos explícitas não empilhadas.
- `update_photo_stack(stack_id, paths, expected_revision, cover_path?)` substitui membros e ordem; 0 ou 1 membro dissolve o grupo.
- `unstack_photos(stack_id, expected_revision)` a dissolve.
- Estas três exigem `edition`, mais o UUID e a revisão atual para pilhas existentes. Nunca repita uma criação às cegas.
- As alterações bem-sucedidas devolvem `undo.entry_id`. `undo_photo_stack(entry_id)` (só edition) verifica que a entrada é de pilha e recusa após edições posteriores ou perda de visibilidade.
- Os caminhos têm no máximo 4096 caracteres. Nenhum arquivo, decisão de revisão ou estado remoto do Immich muda; as credenciais globais ficam apenas na CLI.
- `stack_truncated: true` em uma alteração grande bem-sucedida significa que a pilha só é devolvida como resumo UUID/revision/member_count, não como lista completa e editável de membros. `undo.entry_id` continua disponível.

`search_photos` e o contexto da galeria distinguem `total` (itens exibidos) de `photo_total` (originais correspondentes). Use `photo_total` para o `expected_count` de uma escrita por filtro. As seleções de toda a vista e `target:view` incluem os membros recolhidos correspondentes, por isso mostre a contagem real de fotos e o escopo de toda a vista antes de aplicar. Selecionar um cartão recolhido seleciona apenas a sua foto exibida. `user_activity` inclui `stack` create/update/unstack/undo. `stack_id`/`collapse_stacks` são só do servidor, não chaves de filtro da aba.

- **As ferramentas `user` precisam de um token `edition` em uma instalação com senha única**, que não tem nível intermediário (veja [Níveis de permissão](#níveis-de-permissão)).
- **Semântica de definição.** As ferramentas por foto só escrevem uma diferença em relação ao estado atual, por isso repetir uma chamada é inofensivo; cada caminho indica `changed` ou `already`. Processam um caminho de cada vez e param no primeiro `library_busy`, `outcome_unknown` ou `forbidden_level`, indicando `affected`, os `results` por caminho e `not_attempted`. As ferramentas em lote definem o mesmo estado.
- **Escolher as fotos.** As ferramentas em lote, de etiquetas e `cull_apply` aceitam OU `paths` OU `filters` (o objeto de filtros de `search_photos`), mais uma lista `exclude` opcional.
  - Um alvo `filters` precisa de `expected_count`: o número de correspondências dos filtros antes de `exclude` (o `photo_total` de `search_photos`). O Facet volta primeiro a contar e não escreve nada se os números diferirem (`invalid_input`, com `actual_count`).
  - As ocultações padrão do visualizador (incluindo as fotos rejeitadas) se aplicam a `filters` exatamente como em `search_photos`. Por isso, para `move_rejects` e `trash_rejects`, passe `show_rejected` (ou `hide_rejected: false`) tanto a `search_photos` COMO a `cull_apply`. `copy_keeps` não precisa de mais nada.
- **De quem é o estado.** As classificações, favoritos e rejeições são os do proprietário do token.
- **Arquivos ignorados.** Quando `cull_apply` ou `delete_photos` devolve uma lista `skipped` não vazia, vem com um `skipped_reason`: esses caminhos não têm nenhum arquivo legível no disco (ausente, movido ou fora das pastas analisadas) e nada foi feito com eles.
- **As fotos que o usuário selecionou.** Onde uma ferramenta aceita `paths`, `target: "selection"` usa em vez disso a seleção da aba aberta (`tab_id` escolhe a aba).
  - Uma seleção que mudou entre a pré-visualização e a confirmação responde `invalid_input` com `selection_changed`; uma seleção demasiado grande para a resposta da aba responde `too_large`. `delete_photos` relê a seleção ao confirmar.
  - `get_photo`, `get_thumbnail` (exatamente uma foto selecionada) e `contact_sheet` (no máximo 16) também aceitam `target: "selection"`, a partir de qualquer página.
  - `junk_reject` só o aceita na página da galeria (caso contrário, `invalid_input`).
- **Legendas e exportações.** `set_caption` salva apenas o texto. A legenda não é recodificada, por isso a pesquisa semântica de legendas continua encontrando o texto antigo até uma nova codificação. A exportação incremental para a base de dados do visualizador mantém uma legenda existente quando a de origem está vazia, por isso uma legenda apagada pode voltar com uma exportação ou análise posterior. `export_metadata` espera até 180 segundos, reporta `written`, `skipped` e `errors` (o primeiro texto de erro em `first_error`), e recusa escrever com exiftool 13.23 a 13.27.
- **Rostos.** `assign_faces` ignora, e lista, os rostos ausente, já nessa pessoa, de outra pessoa (salvo `allow_reassign`), de outro modelo de embedding ou de uma pessoa oculta. `assigned_count` é o que realmente se moveu.

### Ações destrutivas: pré-visualizar e confirmar

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) e `delete_photos` estão marcados com `destructiveHint` e rodam como simulação, a menos que sejam chamados com `dry_run: false`.

1. A simulação não altera nada e lista os arquivos que copiaria, moveria ou enviaria para o lixo (as listas longas são cortadas a `max_rows`, com um `<key>_count`). Para `move_rejects`, `trash_rejects` e `delete_photos` devolve também um valor `confirm`, de uso único e válido durante `confirm_expires_in_s` (5 minutos).
2. A chamada real (`dry_run: false`) tem de passar esse `confirm`. O Facet recalcula os arquivos e as opções; se algo mudou, a chamada responde `confirmation_required`: repita a simulação.
3. `copy_keeps` não precisa de `confirm`, pois só escreve cópias. Mesmo assim começa por uma simulação por padrão.

O valor `confirm` está vinculado ao token, à ação e ao conjunto exato de arquivos e opções. Vive em memória em um só processo, por isso um reinício descarta todos os valores pendentes.

**Prática recomendada:** mostre sempre ao usuário o resumo da simulação (contagens e lista de arquivos) e obtenha a sua aprovação explícita antes da chamada `dry_run: false`. Nunca confirme por iniciativa própria.

- `move_rejects` e `trash_rejects` só atuam sobre as fotos que o proprietário rejeitou; as restantes são indicadas como `excluded_by_state`. Os arquivos RAW e `.xmp` acompanhantes (`include_companions`) e os outros quadros de um bracketing ou panorama (`include_sequence_siblings`) não são tocados, a menos que o ative.
- **Pré-requisitos.** `trash_rejects` e `delete_photos` exigem `viewer.cull.allow_trash` como `true` (por padrão `false`). O `target_dir` de `copy_keeps` e `move_rejects` tem de estar em uma localização de exportação permitida: `viewer.export.allowed_target_dirs` mais os seus diretórios de análise (veja [Destinos de exportação e seleção](CONFIGURATION.md#destinos-de-exportação-e-seleção)).

> **Aviso:** `delete_photos` envia os arquivos para o lixo do sistema e **exclui as suas linhas da biblioteca**. As pontuações, etiquetas e classificações não são recuperáveis, mesmo que os arquivos o sejam.

## Correções e dados de referência

- **Correções** (`edition`). `override_sequence` (`kind`: `panorama`, `bracket`, `hdr_panorama` ou `suppress`; pelo menos 2 caminhos exceto para `suppress`) e `clear_sequence_override` registram uma correção aplicada na próxima passagem de detecção (o resultado indica `pending`). `override_category` e `clear_category_override` definem ou removem uma categoria persistente que sobrevive a novas análises e mantém o contexto de pontuação.
- **Comparar quadros** (`readonly`). `group_compare` compara os quadros de um grupo de triagem (até 12 caminhos) com `by: "faces"` (por quadro: número de rostos, piscadas, olhos abertos mais baixos, melhor sorriso, `best_path_by_eyes`) ou `by: "subjects"` (nitidez e destaque do motivo, `sharpest_path`). É um conselho, não uma decisão.
- **Relatório de triagem.** `cull_report` resume um escopo em uma chamada: total, mantidas, rejeitadas, favoritas, classificadas, por revisar, o que os interruptores de ocultação escondiam, lixo, pontuações baixas, as melhores e, com um token edition, os primeiros grupos da câmara escura. Os motivos se sobrepõem. O seu `basis` indica quais filtros cada contagem respeita (as contagens ignoram os interruptores de ocultação).
- **Gosto.** `comparison_status` (`edition`) indica quantas comparações por pares fez e quanto cobrem a biblioteca. Nenhuma ferramenta submete, edita ou apaga uma comparação: a resposta a cada par é o seu próprio clique. As escritas de um assistente (classificações, rejeições, confirmações da câmara escura, `auto_cull`) nunca registram comparações nem ativam o retreino automático; a mesma ação feita por si na galeria continua a fazê-lo. As classificações, favoritos e rejeições escritos por um assistente também ficam fora dos pares de treino do classificador pessoal, até você classificar essa foto.
- **Análises.** `start_scan` e `scan_status` (`edition`) iniciam e acompanham uma análise das diretórios configuradas. Só são listados quando `viewer.features.show_scan_button` está ativo e a instalação está bloqueada (uma chave superadmin no modo multiusuário), ou para um token local de edição completa sob `viewer.trusted_local_editing`, que não precisa de `show_scan_button`. As análises são aditivas e são recusadas enquanto outra tarefa está em andamento (`conflict`). A sincronização com o Immich continua na linha de comandos. Em uma instalação aberta com `viewer.edition_password`, um token local de edição completa criado em uma sessão de edição também as recebe, mas só com `show_scan_button` ativo.
- **Recursos.** O servidor lista ainda cinco recursos `facet://` só de leitura: `facet://categories`, `facet://tags`, `facet://persons`, `facet://filters` (cada filtro de pesquisa com o seu domínio de valores, mais os intervalos das métricas) e `facet://scoring-contexts`. Cada um mostra a biblioteca como o proprietário da chave a vê, limitado a 200 linhas e 32 KiB (`truncated` o indica). Um sexto, `facet://scoring-weights` (os pesos diferentes de zero de cada categoria), é oferecido apenas às chaves `edition`.
- **Escolher o que é listado.** `viewer.mcp.tool_profile` é `full` (padrão) ou `core`. `core` lista apenas um conjunto de 11 ferramentas para modelos pequenos (`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`); só muda a lista, nunca o que uma chave pode chamar. `viewer.mcp.allow_destructive` (padrão `false`) controla `delete_photos` (não listado se desativado), as ações `move_rejects` e `trash_rejects` de `cull_apply` e `assign_faces` com `allow_reassign`; as chamadas recusadas respondem `feature_disabled`. As ferramentas acima do nível de um token também não são listadas.
- **Mais dois códigos de erro.** `feature_disabled`: uma chave de configuração desativa a rota, e a mensagem a nomeia. `conflict`: a biblioteca está ocupada com uma tarefa que exclui esta (por exemplo, uma análise já em curso).

## Pontuações e pesos

Os assistentes podem ler os pesos de pontuação e simular uma alteração. Quatro ferramentas escrevem: `apply_weights` e `restore_weight_snapshot` alteram a configuração, `recompute_scores` reescreve as pontuações e `override_categories` fixa fotos. Cada uma exige o nível `edition` e um `confirm` em dois passos vindo de uma simulação ou de uma pré-visualização. As leituras não alteram nada.

- **Explicar uma pontuação** (`readonly`). `explain_score` (`path`, ou `target: "selection"` para exatamente uma foto selecionada; `top_n` de 1 a 12, 5 por padrão) explica a pontuação de uma foto: a sua categoria e porque nenhuma categoria de maior prioridade a ficou, o agregado salvo, as principais métricas como `{metric_key, value, weight_percent, contribution}`, o resto como contagem e soma, pontos fortes, pontos fracos e penalizações.
  - É baseada em regras e só de leitura; nunca executa o VLM.
  - `weight_percent` é o peso efetivo usado pelo cálculo. Pode diferir do `*_percent` configurado: `quality` é incorporado em `aesthetic` e as métricas que esta instalação não executa são renormalizadas.
  - Requer `viewer.features.show_critique` (ativo por padrão). Se estiver desativado, a ferramenta não é listada e `status` a indica em `hidden_tools.disabled`.
- **Ler os pesos** (`edition`). `category_weights` devolve os pesos diferentes de zero, os modificadores, os filtros e a prioridade de uma categoria, ou os pesos diferentes de zero e o bônus de cada categoria. O recurso `facet://scoring-weights` traz a mesma lista. Para uma categoria devolve também `configured_keys`: as chaves `*_percent` que a configuração da categoria realmente contém (zeros explícitos incluídos).
- **Simular uma alteração** (`edition`). `preview_weights(category, weights | deltas, sample)` recalcula até `sample` fotos da categoria (30 por padrão, no máximo 100) com os pesos atuais e com os propostos, ambos normalizados como o cálculo os normaliza. Indique `weights` (um mapa parcial sobreposto aos valores atuais) ou `deltas` (pontos percentuais com sinal).
  - Indica primeiro as mudanças de posição, depois o desvio médio, `warnings` e um `preview_digest` de utilização única (válido 5 minutos, mantido por um único processo).
  - É aproximada (`basis: "approximate"`): sem instantâneo de percentis, sem penalizações e com as pontuações limitadas a 10. Usa apenas as métricas armazenadas e não salva nada.
  - Aplica-se apenas a regra do próprio servidor (cada peso de 0 a 100), mais uma recusa quando todos os pesos somam 0 (`all_weights_zero`). Uma soma fora de 95 a 105 (que o carregador de configuração reescala) e uma chave desconhecida (salva tal como escrita, descartada por um carregamento com validação) voltam como `warnings`, não como recusas.
  - `bonus` e os modificadores não são editáveis pelo assistente.
  - Uma categoria com mais de 100 fotos é amostrada apenas entre as suas 100 melhores e 100 piores por agregado (`sample_scope`).
  - O digest não é um consentimento: mostre primeiro ao usuário a proposta, o desvio e `basis_note`.
- **Aplicar uma alteração** (`edition`). `apply_weights(category, weights | deltas, preview_digest)` grava uma alteração simulada. Repita os MESMOS `weights` ou `deltas` dados a `preview_weights` e passe o seu `preview_digest`. Sem o digest desta proposta exata sobre os pesos atuais, a chamada responde `confirmation_required` e não grava nada. O digest é de uso único, vinculado ao token que simulou, e fica anulado se os pesos mudarem.
  - A gravação passa pela mesma rota da interface web: os pesos anteriores são primeiro salvos em um snapshot (`auto:edit`) e o resultado indica esse `snapshot`. O resultado é relido (`verified`).
  - Nenhuma foto é recalculada: a resposta traz `scores_stale: true` e `next: "recompute_scores"`. As pontuações salvas, as posições e a galeria só mudam depois desse trabalho.
  - Limitação conhecida: uma página /compare já aberta salva os pesos antigos e voltaria a enviá-los na próxima edição; por isso a resposta traz `reload_compare: true` e o assistente pede ao usuário que a recarregue.
- **Snapshots** (`edition`). `list_weight_snapshots(category, limit, offset)` lista os snapshots salvos, do mais recente para o mais antigo, com os pesos diferentes de zero e um indicador `restorable`. `restore_weight_snapshot(snapshot_id)` é por padrão uma simulação: lista a alteração e devolve um `confirm` de uso único. A execução real (`dry_run: false` mais esse `confirm`) responde `confirmation_required` se os pesos mudaram nesse meio-tempo. Antes de sobrescrever, salva os pesos atuais como `auto:pre_restore` (`undo_snapshot_id`), por isso uma restauração pode ela própria ser desfeita. Um snapshot salvo pela interface web em outro formato (nomes de métricas simples em vez de chaves `*_percent`) responde `unsupported_snapshot` nas duas execuções: restaure-o a partir de /compare.
- **Recalcular** (`edition`). Uma alteração de pesos não recalcula nada até que `recompute_scores(category | all: true)` seja executado. Inicia de imediato o trabalho em segundo plano (pergunte primeiro ao usuário) e devolve `started_at`. `recompute_status(started_at)` indica depois `running`, `succeeded`, `failed`, `busy` (outro processo detém o bloqueio da biblioteca) ou `idle`; `matches_started_job` diz se o estado descreve o trabalho iniciado.
  - Roda um só trabalho de cada vez (`conflict`).
  - O recálculo de uma categoria reescreve apenas essa categoria e não atualiza os grupos de rajadas nem de sequências (`all` fá-lo). Ambas as execuções salvam o snapshot de percentis que a normalização seguinte de cada categoria lê.
  - O estado vive em um só processo: com vários workers, uma consulta pode chegar a um que desconhece o trabalho.
- **O que as comparações do usuário favorecem** (`edition`). `learned_weights(category, with_confidence)` executa o otimizador sobre as comparações A/B do próprio usuário e devolve apenas os `changes` diferentes de zero e uma `proposal` para entregar a `preview_weights`; nada é salvo. Em vez de inventar uma sugestão, responde `available: false` com um `reason` (`not_enough_comparisons`, `unavailable_if_external` quando o motor de aprendizagem é externo, `optimizer_unavailable`). Quando o otimizador não encontra melhoria, diz ao assistente para não propor nenhuma alteração.
- **Corrigir categorias** (`edition`). `misassigned_categories(category, limit, scan)` lista fotos de uma categoria que talvez pertençam a outra, entre as `scan` com melhor pontuação. É uma heurística (`confidence_basis: "heuristic"`), não uma prova; não grava nada, ignora fotos com categoria manual e desaparece com `show_critique`.
  - `stale`: a configuração atual coloca a foto em outra categoria. Corrija com `recompute_scores`, não com uma substituição.
  - `near_miss`: falhou por menos de 10 % o primeiro limite numérico não cumprido de uma categoria de maior prioridade.
- **Fixar categorias** (`edition`). `override_categories(category, paths, dry_run, confirm, expected_count)` fixa até 50 fotos.
  - A simulação lista quais mudariam (`would_change`, `already`, `missing`) e devolve um `confirm` de uso único.
  - A execução real o exige com um `expected_count` igual a `would_pin`. As fotos que já estão na categoria também são fixadas, para que a escolha sobreviva a um recálculo posterior. Para na primeira falha e indica `affected`, `remaining` e `failed_path`.
  - Cada fixação é duradoura e recalcula o agregado da foto; `clear_category_override` desfaz uma.
- `ui_show_comparison` aceita um `tab` (`ab`, `snapshots`, `suggestions`, `weights`) para que o assistente possa abrir a página onde o usuário revisa uma alteração.

## Prompts

O servidor oferece ainda cinco prompts prontos, listados por `prompts/list` e filtrados pelo nível do token. Um prompt só nomeia ferramentas que o token pode chamar, e uma ferramenta destrutiva só depois da sua simulação e da sua confirmação. Cada chamada conta no limite de leitura e é registrada pelo nome, nunca com os seus argumentos.

| Prompt | Argumentos | O que pede ao assistente |
|--------|------------|--------------------------|
| `find_photo` | `description` | Encontrar uma foto a partir de uma descrição e mostrá-la |
| `cull_shoot` | `scope_hint` | Revisar uma sessão, propor o que rejeitar e, depois de decidir, registrar as suas decisões com `confirm_culling_groups`; mover ou enviar para o lixo só acontece após uma simulação e a sua confirmação |
| `build_album` | `theme`, `album_name` | Reunir as fotos correspondentes em um novo álbum |
| `tag_people` | `person` | Encontrar rostos parecidos com uma pessoa e atribuir os que confirmar |
| `teach_taste` | `category` | Abrir a página de comparação por pares na sua aba e acompanhar quantas comparações fez; a resposta a cada par é sempre o seu próprio clique |

## Câmara escura (grupos de triagem)

As ferramentas da câmara escura espelham a página `/culling`. Todas exigem o nível `edition`, mesmo as que apenas listam.

| Ferramenta | O que faz |
|------|--------------|
| `list_culling_groups` | Lista os grupos (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) com as suas fotos e pontuações, ordenáveis e delimitáveis por álbum ou intervalo de datas |
| `culling_profiles` | Os perfis de triagem prontos e o padrão |
| `suggest_culling_profile` | Indica o perfil adequado a um álbum ou intervalo de captura |
| `keeper_hints` | Dicas por foto «existe uma foto melhor nesta rajada» para até 100 caminhos (vazias se não houver cabeça de classificação treinada) |
| `auto_cull` | Triagem automática de um escopo com um orçamento de fotos a manter: pré-visualização do plano página a página e depois aplicação com o valor `confirm` |
| `confirm_culling_groups` | Confirma até 20 grupos: mantém os seus `keep_paths` e rejeita o resto dos seus `paths` |

- **Um grupo é identificado pelo par `(type, group_id)`**, nunca só por `group_id`: os ids dos grupos semelhantes são deslocados ao serem fundidos com as rajadas.
- **O valor padrão `group_by: "all"` devolve apenas rajadas e grupos semelhantes.** Peça explicitamente `scene`, `bracket`, `panorama` ou `hdr_panorama`.
- **Uma página é reduzida para caber em `max_bytes` encurtando a lista `photos` de cada grupo, nunca removendo grupos.** `photo_count` continua sendo o tamanho real, `photos_truncated` assinala uma lista cortada e `has_more` indica se segue outra página.
- **Bracketings, panoramas e panoramas HDR são mantidos inteiros.** Em `confirm_culling_groups`, `keep_paths` tem de ser igual a `paths` para estes tipos (senão `invalid_input`), e `auto_cull` nunca os divide.
- **Um `keep_paths` vazio rejeita todos os quadros do grupo.** A primeira chamada responde então `confirmation_required` com um valor `confirm`: mostre-o ao usuário e repita a chamada com esse valor. Se um lote parar em `forbidden_level`, `library_busy` ou `rate_limited`, os grupos já concluídos são indicados.
- **`auto_cull` faz uma pré-visualização por padrão.** Devolve a repartição manter/rejeitar por grupo, mais um valor `confirm` quando resta algo por rejeitar.
  - Cada chamada planeja todo o escopo e o devolve em páginas de grupos inteiros. A rota pagina a 200 fotos, um único grupo maior recebe a sua própria página, e a ferramenta pode devolver menos grupos para caber no tamanho do resultado.
  - Repita a chamada com `cursor` igual ao `next_cursor` anterior e `plan_digest` igual ao `plan_digest` da página do cursor 0 (obrigatório se `cursor` > 0) até `next_cursor` ser `null`. Se o plano mudou desde a primeira página, a chamada responde `confirmation_required`: recomece a partir do cursor 0.
  - Cada linha traz o seu `number` em todo o plano; `kept` e `rejected` cobrem o plano completo.
  - Faça a triagem de um intervalo de datas inteiro em uma ÚNICA chamada, nunca mês a mês.
- **Um único `confirm` cobre todo o plano** (válido 300 s, de uso único, emitido apenas na página do cursor 0). A aplicação recalcula o plano e responde `confirmation_required` se mudou desde a pré-visualização. Devolve apenas contagens (`groups_processed`, `kept`, `rejected`, `highlights_added`). As rejeições feitas por um assistente nunca alimentam o classificador pessoal, ao contrário da mesma triagem feita por si na galeria.
- **Substituições.** `keep_paths` e `remove_paths` (até 1000 cada) substituem quadros isolados do plano. Passe as mesmas substituições na simulação que emite o `confirm` e na aplicação.
  - Os caminhos que não estão no plano são ignorados e comunicados como `ignored_overrides` (os 20 primeiros, com `ignored_overrides_count`).
  - São recusados como `invalid_input`, que nomeia os caminhos ou os grupos: remover um quadro que o plano MANTÉM em um bracketing, em um panorama ou em um panorama HDR; deixar um grupo sem foto mantida; indicar um caminho nas duas listas.
  - Remover um quadro que o plano já rejeita não faz nada.
  - A regra das séries só cobre grupos formados inteiramente por um só tipo de série. Um grupo que mistura quadros comuns com quadros de série não é mantido inteiro, por isso os seus quadros podem ser substituídos como os de qualquer rajada.
- **A aplicação nunca lê as inversões do usuário na aba.** Para as respeitar, leia `ui_get_context.culling.changed` e passe os `keep_paths` / `reject_paths` desses grupos como `keep_paths` / `remove_paths` na simulação seguinte e na sua aplicação (as mesmas listas em ambas). Um grupo confirmado pelo usuário na aba sai do plano: o digest do plano muda, um `confirm` pendente responde `confirmation_required`, e a nova pré-visualização já não contém esse grupo. Nunca volte a decidi-lo.
- **Se o usuário alterar algo entre a pré-visualização e a aplicação.** A aplicação é verificada contra a pré-visualização.
  - Uma foto cuja classificação, favorito ou estado de rejeição o usuário alterou desde a pré-visualização fica de fora e é comunicada como `skipped_user_changed` (os 50 primeiros caminhos, com `skipped_user_changed_count`). Um grupo que fica sem foto mantida é ignorado por inteiro e contado em `skipped_user_changed_groups`.
  - Esta exclusão por foto só se aplica quando não é dado nem `keep_paths` nem `remove_paths`. Com listas explícitas, a aplicação repete a simulação e recusa qualquer alteração do plano, incluindo uma rejeição manual.
  - Uma classificação, um favorito ou uma rejeição escrita por qualquer pessoa entre a pré-visualização e a aplicação conta como alteração, incluindo as escritas do próprio assistente. Uma alteração do plano que essas fotos não expliquem continua sendo recusada como `confirmation_required`.
  - Quando o servidor já não salva a pré-visualização (mais de 15 minutos, expulsa ou em poder de outro processo), ou o plano tem mais de 12000 fotos em todas as páginas, a resposta diz `state_guard: "unavailable"` e se aplica a recusa tudo ou nada.
  - A proteção cobre apenas pedidos do assistente; a linha de comandos `--auto-cull` não muda.
- **`scope_dependent_kinds`** indica os tipos de grupo cuja composição depende do intervalo de datas ou do conjunto de candidatos (`similar`, `scene`, mais `bracket` se `trim_brackets` estiver ativo), com uma nota para fazer a triagem de todo o intervalo em uma chamada. As rajadas e os panoramas não mudam com o intervalo, nem os bracketings enquanto `trim_brackets` estiver inativo.
- **`show`** (`true` por padrão, com `tab_id`). Em uma simulação, o plano se abre na página `/culling` do usuário através de `ui_show_culling_plan` (ver Modo de plano em `/culling` acima).
  - O resultado traz `shown_in_tab`: `{"applied": true, ...}`, ou `applied: false` com os motivos de uma exibição de pesquisa falhada e, ainda, `unsaved_decisions` (o usuário tem na página decisões por confirmar), `stack_mode_active` (a página está no modo de pilhas sugeridas), `plan_changed` (a biblioteca mudou desde a pré-visualização), `too_large` (as substituições são demasiado grandes para enviar à aba) e `plan_load_failed` (qualquer outra falha de carregamento).
  - Só a primeira página (`cursor` 0) carrega o plano; uma página com `cursor` > 0 apenas move o foco da aba para o primeiro grupo dessa página.
  - Uma exibição falhada nunca faz falhar a chamada. Uma aplicação nunca mostra.
  - A atualização ao vivo de uma aplicação (e, na página, o `show_paths` da resposta de `/api/mcp/call`) traz as fotos que rejeitou, até 200, para o **Mostrar as fotos** da entrada de atividade; o resultado da ferramenta continua limitado a contagens. Uma aplicação que nada rejeitou não oferece **Mostrar as fotos**, e uma simulação não emite atualização ao vivo.
- **Configurações vindas da aba.** Sem `strictness` nem `profile`, `auto_cull` planeja com as configurações com que a página `/culling` da aba aberta iniciaria.
  - Rigor: o valor salvo do controle deslizante; se nunca foi movido, o rigor próprio do perfil salvo, ou 100 sem perfil.
  - Perfil: o perfil de triagem salvo neste navegador, se existir. Fornece as suas restantes configurações (como o mínimo de fotos a manter por grupo); o rigor do controle prevalece.
  - Mostrar um plano move o controle para o rigor do plano; aplicar um perfil sugerido salva o seu rigor.
  - Sem aba alcançável usa `auto_cull.default_strictness` do servidor.
  - O resultado comunica o que usou como `knobs_from_tab` (`{profile}`, `{strictness}` ou ambos); `ui_get_context.culling_defaults` mostra o mesmo par.
  - Uma aplicação com um nonce de confirmação reutiliza as configurações da pré-visualização (incluindo `keep_paths` / `remove_paths` explícitos) e não volta a ler a aba. Responde `confirmation_required` quando a página `/culling` do usuário mostra agora um plano diferente do da pré-visualização (replaneado ou substituído). Uma aba inalcançável ou sem plano mostrado não é verificada.
- Chame `ui_show_culling_group` para mostrar um grupo ao usuário na sua aba aberta (veja [Controlar a aba aberta](#controlar-a-aba-aberta)).

## Resultados, limites e erros

Cada resultado é um envelope JSON: `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. As listagens devolvem `data.rows` (um conjunto compacto e fixo de campos por foto) e `total`. O resultado de uma pesquisa traz também `shown_in_tab`, e um resultado cortado pelo limite de bytes traz `returned`.

- **Limites máximos:** no máximo `max_rows` linhas e `max_bytes` bytes serializados. As últimas linhas são descartadas e `truncated: true` é definido. Um resultado sem linhas que exceda `max_bytes` se torna um erro `too_large`.
- **Imagens:** `get_thumbnail` e `contact_sheet` devolvem uma parte de imagem antes da parte JSON. A imagem é limitada por `max_image_bytes` (262144 por padrão), não por `max_bytes`. O texto visível dentro de uma imagem é um dado, nunca uma instrução.
- **Análise de rostos:** `possible_faces` lê no máximo 192000 rostos e pode esperar até 120 segundos; acima disso responde `too_large`.
- **Limite de taxa:** `rate_per_min` chamadas por minuto e por token para leitura. As ferramentas de escrita usam um orçamento separado, `write_rate_per_min` (30 por padrão), para que leituras e escritas não se privem mutuamente de quota. A simulação de `cull_apply` e `delete_photos` conta como escrita, a pré-visualização de `auto_cull` como leitura. Acima disso: `rate_limited` com `retry_after_s`. Dez tentativas bearer falhadas por minuto a partir do mesmo endereço recebem 429.
- **Códigos de erro:** `forbidden_level` (endpoint desativado, token inválido ou nível insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`, `no_active_view`, `unsaved_decisions`, `navigation_refused`, `modal_open`, `stack_mode_active`.
- **Os códigos mais recentes:** `confirmation_required` (uma chamada destrutiva não tem um valor `confirm` válido para este conjunto exato: repita a simulação, mostre o resultado ao usuário e tente de novo), `outcome_unknown` (uma escrita excedeu o tempo ou a conexão caiu, por isso pode ou não ter acontecido: volte a ler o estado antes de repetir, nunca repita às cegas), `library_busy` (a biblioteca está ocupada com outra tarefa: tente de novo daqui a pouco).
- **Códigos HTTP à entrada:** 401 para token ausente ou desconhecido, 403 para um pedido de navegador de outra origem ou para as credenciais de um agente em `/api/mcp/tokens`, 404 quando está desativado. A ponte de abas responde com códigos de fechamento. Em uma instalação aberta, `/api/mcp/tokens` responde também 403 a um pedido que não venha do computador onde o Facet está rodando.

## Notas de segurança

- Legendas, etiquetas, nomes de arquivos, caminhos e nomes de álbuns e pessoas vêm da sua biblioteca e podem conter texto escrito para manipular um assistente (injeção de prompts). Cada ferramenta está marcada com `facet/untrusted_content` e diz ao modelo para os tratar como dados. Não dê a um assistente que também lê conteúdo não fiável uma forma de agir sobre o que encontra aqui.
- Os tokens nunca expiram. Revogue os que já não usa.
- Os registros salvam o id do token, a ferramenta, o resultado e o número de linhas, nunca os argumentos nem o token.

## Limitações conhecidas

- **Instalações abertas** (sem senha). Só a gestão de tokens fica limitada ao computador local, por isso um par da rede não consegue encher o limite de 20 tokens. `/mcp`, as ferramentas da página e a ponte de aba continuam acessíveis a quem alcance o visualizador, como o usuário anônimo compartilhado. Defina uma senha antes de ativar o endpoint em uma rede.
- **Abas falsas em uma instalação aberta.** Um cliente que não seja um navegador pode enviar um `Origin` inventado e um token nulo, registrar uma aba `_anonymous` com o foco, responder às chamadas `ui_*` com os dados que quiser e expulsar abas reais através do limite de 8 abas. Com `viewer.trusted_local_editing`, um processo local também pode registrar uma aba `edition` falsa (pode falsificar `Host` e `Origin` no WebSocket), mas já podia agir como o navegador. Um cliente da rede local não pode, pois é exigido um par em loopback.
- Os limites de frequência e os contadores de autenticações falhadas vivem em memória em cada processo; com `viewer.py --workers N` cada worker conta em separado.
- O registro de abas vive em memória em um só processo. Use um único worker (`viewer.py --workers 1`, o valor por padrão) se depender das ferramentas `ui_*`; com vários workers uma chamada pode chegar a um processo que não conhece a sua aba e responder `no_tab`.
- Um usuário pode ter no máximo 8 abas conectadas; abrir um nono fecha o mais antigo.
- Nada é empurrado da aba para um assistente externo: este só conhece o progresso do plano e a atividade do usuário chamando `ui_get_context`. A aplicação de `auto_cull` não lê a aba.
- A proteção de estado de `auto_cull` salva 8 planos por usuário durante 15 minutos. A memória de pré-visualizações é separada: 300 segundos e 64 entradas para todos os usuários. Ambas vivem na memória de um único processo; com vários workers, uma aplicação pode chegar a um processo que não tenha nenhuma, e a resposta diz então `state_guard: "unavailable"`.
