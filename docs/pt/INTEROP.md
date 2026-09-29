# Receitas de Interoperabilidade com Editores

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · **Português** · [简体中文](../zh/INTEROP.md)

Receitas práticas, passo a passo, para fazer as classificações, os rótulos e as tags do Facet irem e voltarem entre os editores externos e as ferramentas de gerenciamento de fotos (DAM) que os fotógrafos realmente usam. Esta página assume que você já sabe *que* o Facet grava XMP — veja [Comandos — Preview & Export](COMMANDS.md#preview--export) para a referência completa das opções `--export-sidecars` / `--import-sidecars` e o mapeamento de campos (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## A armadilha do nome dos sidecars RAW

O Facet nomeia um sidecar como `<imagem><ext>.xmp` — por exemplo, `IMG_1234.CR2.xmp` ao lado de `IMG_1234.CR2` — a mesma convenção usada pelo darktable e pelo digiKam. **O Lightroom Classic e o Capture One esperam o oposto: `IMG_1234.xmp`, sem a extensão RAW.** Nenhum dos dois vai descobrir um sidecar gravado pelo Facet para um arquivo RAW proprietário (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — tudo exceto DNG), e o `--import-sidecars` do Facet tampouco vai encontrar um sidecar que um aplicativo do ecossistema Adobe gravou para o mesmo RAW. É uma incompatibilidade de convenções de nome entre ecossistemas, não um defeito de nenhum dos lados.

Isso **não** afeta:
- **JPEG, HEIC, TIFF, PNG, DNG** — passe `--embed-originals` e o Facet grava os metadados *dentro do próprio arquivo* (via exiftool), então não há nome de sidecar para o Lightroom/Capture One deixarem de encontrar.
- **digiKam** — verifica as duas convenções de nome e encontra o sidecar do Facet de qualquer forma (veja [digiKam](#digikam) abaixo).
- **darktable** — usa a mesma convenção `<imagem><ext>.xmp` do Facet (veja [darktable](#darktable) abaixo).

**GIF, WebP, BMP e AVIF são a exceção — são os mais atingidos pela divergência.** Ficam fora do conjunto incorporável do Facet, então `--embed-originals` não faz nada por eles e seu único veículo de ida e volta é um sidecar XMP com o nome que o Facet usa (`photo.webp.xmp`). A divergência acima vale portanto para esses quatro exatamente como para o RAW proprietário: digiKam e darktable encontram o sidecar, Lightroom Classic e Capture One não.

Portanto, para um fluxo com Lightroom ou Capture One: use `--embed-originals` para tudo que estiver no conjunto incorporável (JPEG, HEIC, TIFF, PNG, DNG), e espere que a ida e volta por sidecar fique em silêncio (nenhum erro, apenas nada é lido) para os RAW proprietários — e para GIF, WebP, BMP e AVIF. Se você fotografa em RAW+JPEG, o JPEG companheiro é o veículo prático de interoperabilidade — o RAW permanece no disco, intocado, enquanto o banco de dados do Facet mantém a classificação que faz autoridade.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (adicione um caminho para limitar o escopo, por exemplo `--export-sidecars /fotos/casamento-2026`). Adicione `--embed-originals` para também gravar diretamente em arquivos JPEG/HEIC/TIFF/PNG/DNG.
2. No módulo Biblioteca do Lightroom Classic, selecione as fotos (Ctrl/Cmd+A para todas) e escolha **Metadados → Ler metadados do arquivo**. O Lightroom sobrescreve a classificação, o rótulo de cor e as palavras-chave do seu catálogo a partir do sidecar (ou dos metadados incorporados, para os formatos acima).

O marcador de rejeição do Facet (`xmp:Rating = -1`) é relido como o sinalizador de Rejeição do Lightroom. Um favorito do Facet grava `xmp:Label = Yellow`, que o Lightroom exibe como o **rótulo de cor Amarelo** — não como o sinalizador de Seleção (Pick). Se o seu fluxo no Lightroom depende dos sinalizadores Pick em vez dos rótulos de cor, adicione uma etapa de conversão rótulo-de-cor → pick, ou filtre pelo rótulo Amarelo.

Um feed `python facet.py --export-manifest` (caminho, categoria, todas as pontuações, tags e as mesmas colunas de classificação do `--export-sidecars` — incluindo avaliações por usuário via `--export-manifest --user alice` em uma instalação multiusuário) agora existe para ferramentas que querem os dados do Facet sem analisar o XMP — veja [Comandos — Preview & Export](COMMANDS.md#preview--export). É justamente esse feed que o plug-in do Facet descrito abaixo consome.

**Manifesto versão 2.** O manifesto agora também traz `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` e uma contagem de nível superior `pending_corrections` (correções manuais de bracket/panorama ainda não aplicadas por uma execução de detecção — execute novamente `--detect-panoramas`). O plug-in usa os campos por foto nas opções de seleção/rejeição de sequências e de fallback de estrelas descritas abaixo, e exibe `pending_corrections` como uma linha de aviso em sua Pré-visualização, para que você saiba que outra execução da detecção ainda pode mudar quais quadros são líderes. Não há caminho de leitura retrocompatível: um plug-in construído para a versão 2 recusa de imediato um manifesto em versão 1, com uma caixa de diálogo pedindo para reexportar, e um plug-in mais antigo também não consegue ler um manifesto em versão 2. Se você vir essa caixa de diálogo, basta executar `--export-manifest` novamente.

No viewer, a caixa de diálogo **Export to editor** da galeria oferece o mesmo manifesto através de um botão **Download Lightroom manifest**, limitado à mesma seleção/filtro da exportação de sidecars ao lado — veja [Editor Export](VIEWER.md#exportação-para-editor). Ele grava exatamente a mesma forma de `facet_manifest.json` que `--export-manifest`, então a caixa de diálogo do plug-in abaixo funciona da mesma forma independentemente de qual lado gerou o arquivo.

### O plug-in do Facet (classificações por estrelas, sinalizadores Pick, campos de metadados e palavras-chave)

`facet.lrplugin/`, no repositório do Facet, é um plug-in do Lightroom Classic que grava a classificação por estrelas e o estado favorito/rejeitado do Facet **diretamente no catálogo**. Ele existe porque duas das situações acima não têm solução pelo lado do XMP: o Lightroom nunca encontra um sidecar do Facet para um arquivo RAW proprietário, e o XMP não tem nenhum canal para o sinalizador de Seleção (Pick) do Lightroom. O plug-in lê um arquivo de manifesto: nunca fala com o servidor do Facet, não pede senha e funciona com o Facet desligado — e como ele casa as fotos por caminho em vez de por sidecar, **uma biblioteca inteiramente RAW funciona exatamente como uma de JPEG**.

O plug-in registra dois itens em **Biblioteca → Extras de plug-in** (**Library → Plug-in Extras**): **Facet: Apply ratings and flags...** (o sentido manifesto → catálogo, descrito nesta seção) e **Facet: Export Lightroom State to Facet...** (o sentido inverso — veja [Lightroom → Facet](#lightroom--facet) abaixo).

**Instalação** (uma única vez):

1. Copie a pasta `facet.lrplugin` para a máquina que executa o Lightroom. No macOS, compacte-a antes em zip — o Finder trata uma pasta `.lrplugin` como um pacote.
2. No Lightroom Classic: **Arquivo → Gerenciador de plug-ins → Adicionar**, selecione a pasta `facet.lrplugin` e clique em **Concluído**.

**Uso** (sempre que quiser o veredito do Facet no catálogo):

1. `python facet.py --export-manifest /fotos/casamento-2026` (o caminho limita o escopo; o arquivo é sempre gravado como `facet_manifest.json` no diretório atual). Copie-o para a máquina do Lightroom se o Facet rodar em outro lugar.
2. No módulo Biblioteca, selecione as fotos e escolha **Biblioteca → Extras de plug-in → Facet: Apply ratings and flags...** (a interface do plug-in está em inglês).
3. Aponte o diálogo para o arquivo `facet_manifest.json`. O caminho fica memorizado para a próxima vez.
4. **Se o Facet analisou as fotos a partir de outra máquina, preencha os dois prefixos de caminho.** O manifesto guarda os caminhos da máquina que fez a varredura (`/volume1/photos/...` num NAS), enquanto o Lightroom conhece os da estação de trabalho (`Z:\photos\...`). Informe o prefixo do Lightroom e o do Facet que designam a mesma pasta; deixe ambos vazios quando coincidirem. É o único erro de primeira execução que realmente importa — ele simplesmente não casa foto nenhuma.
5. Escolha o escopo: as fotos selecionadas (padrão) ou todas as fotos da pasta atual.
6. Clique em **Preview...** (Visualizar). **Nada é gravado ainda.** O plug-in informa quantas fotos encontrou no manifesto, quantas não encontrou, e quantas classificações e sinalizadores gravaria. Se o número de correspondências for 0, ele mostra um caminho de exemplo do Lightroom ao lado de um do manifesto, para que você veja como os prefixos devem ficar.
7. Clique em **Apply** (Aplicar). O progresso é exibido e pode ser cancelado; um diálogo de resumo informa o que foi gravado, ignorado e não encontrado.

**O que ele grava** — nada além disso, e nunca nos seus arquivos de imagem:

| Estado no Facet | Campo do Lightroom |
|---|---|
| `star_rating` 1-5 | classificação por estrelas |
| favorito | sinalizador de Seleção (Pick) |
| rejeitado | sinalizador de Rejeição (Reject) |

Uma classificação do Facet igual a 0 significa "sem opinião" (veja `xmp_export.score_to_rating`) e nunca é gravada.

**Semântica de sobrescrita** — por padrão o plug-in nunca contraria você: ele só define uma classificação quando a foto está *sem classificação* no Lightroom, e um sinalizador só quando a foto está *sem sinalizador*. Tudo o que você classificou ou sinalizou à mão fica intacto e é contado como "kept as they are" (mantidas como estão) na pré-visualização. Marque **Overwrite ratings and flags that are already set in Lightroom** para substituí-las mesmo assim. Isso espelha o `only_when_unrated` de `xmp_export.score_to_rating`, de modo que o plug-in e o caminho dos sidecars tratam suas edições manuais da mesma forma.

**Novas opções da caixa de diálogo** (todas opcionais, cada uma lembrada para a próxima vez):

- **Fill in star ratings from Facet scores for photos you have not rated** — quando uma foto não tem `star_rating` no manifesto (ou é 0), mas a pontuação `aggregate` do Facet corresponde a uma contagem de estrelas, essa classificação derivada preenche a lacuna. Como é um recurso de reserva para uma foto *sem classificação*, e não uma classificação real do manifesto, ela **nunca sobrescreve uma classificação que o Lightroom já tenha — mesmo com Overwrite marcada.** Uma `star_rating` real do manifesto continua seguindo a regra normal de sobrescrita acima, sem alteração.
- **Pick the recommended frame of each burst** — para cada grupo de sequência com pelo menos 2 membros no manifesto, cada membro que o manifesto marca como `is_burst_lead` (uma sequência pode manter mais de um quadro) é definido como Selecionado (Pick). Um quadro isolado que o manifesto nunca agrupou com outros nunca é tocado por essa opção, e um grupo de sequência sem nenhum membro `is_burst_lead` em todo o manifesto é ignorado por completo (não há nada de onde derivar). Um sinalizador Pick/Reject definido manualmente — ou um favorito/rejeição do Facet no manifesto — sempre prevalece sobre essa seleção derivada.
- **Reject the other frames** (aninhada sob a opção anterior, ativável somente junto com ela) — define como Rejeitado cada membro da sequência que *não* é o quadro líder, com duas exceções: um membro de um bracket, panorama ou panorama HDR nunca é rejeitado por essa regra, mesmo que seu `burst_group_id` também o agrupe com outros — esses conjuntos são mantidos inteiros; e um grupo sem nenhum quadro líder em todo o manifesto (veja acima) também não recebe rejeições.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — para cada grupo com pelo menos 2 fotos correspondentes no escopo atual, cria ou reaproveita uma coleção chamada `<yyyy-mm-dd HH:MM:SS> – <filename>` (o horário de captura e o nome de arquivo do membro mais antigo; `~ (no date) – <filename>` quando esse membro não tem horário de captura), aninhada sob `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` ou `Facet › HDR panoramas`, conforme o caso. Um grupo de sequência simples cujos membros pertencem *todos* já integralmente a um conjunto bracket/panorama/panorama HDR não recebe uma coleção Bursts separada, pois duplicaria a coleção já existente sob Brackets/Panoramas/HDR panoramas. **Executar novamente apenas adiciona** — fotos são adicionadas a uma coleção reencontrada, nunca removidas, então uma coleção pode ficar desatualizada em relação a um conjunto reagrupado ou redetectado depois (uma foto retirada de um bracket em uma varredura posterior não é removida da coleção). Os nomes de coleção também colidem quando os membros mais antigos de dois grupos diferentes partilham a mesma hora de captura ao segundo e o mesmo nome de ficheiro — duas câmaras que gravaram ambas `IMG_0001` no mesmo instante acabam por partilhar uma única coleção em vez de ter uma cada. É uma limitação conhecida, não um bug a ser reportado.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (aninhada sob a opção anterior) — em vez de apenas adicionar, limpa e reabastece uma coleção, mas só quando a coleção E todo o seu grupo cabem inteiramente no escopo desta execução; uma coleção apenas parcialmente coberta (algum membro fora da seleção) ou que aponta para uma coleção inteligente/não resolvida é deixada intacta e contada como ignorada, e o resumo informa quantas foram reconstruídas, excluídas, ignoradas e com falha. Também alcança uma coleção Facet cujo grupo se DISSOLVEU nesta execução (deixou de ter pelo menos 2 membros no escopo, portanto sem entrada no plano) — essa coleção também é esvaziada e excluída, mas só quando toda foto que ela contém foi encontrada por esta execução; uma coleção com alguma foto fora desta execução é deixada intacta. Rebuild só é oferecida — e só é executada — enquanto **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** estiver ativada; desmarcar essa opção também desativa Rebuild. A varredura de coleções dissolvidas só toca uma coleção cujo nome corresponde exatamente à forma que o próprio Facet gera (uma data-hora ISO, ou o prefixo sem data `~ (no date)`, seguido de ` – <filename>`), então uma coleção que você mesmo nomeou sob um conjunto Facet nunca é esvaziada nem excluída. Quando a varredura tem algo a excluir, o Preview adiciona uma linha `Facet collections to delete: N`, e a varredura é executada mesmo quando é a única mudança pendente, em vez de ser informada como nada a mudar.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — grava a pontuação `aggregate` (por exemplo, `8.4`), uma faixa inteira (`0`-`10`), a categoria e o tipo de conjunto nos próprios campos de metadados do plug-in do Facet, visíveis no painel de Metadados e utilizáveis como critérios de texto (`sdktext:`) no Filtro de biblioteca ou em coleções inteligentes — por exemplo, uma coleção inteligente que faça corresponder a faixa a "qualquer um entre 8, 9, 10". Um campo que já não se aplica a uma foto (por exemplo, ela saiu de um bracket, então o tipo de conjunto desapareceu) é apagado em vez de deixado obsoleto — do contrário, uma coleção inteligente ou critério do Filtro de biblioteca baseado nesse campo continuaria correspondendo a uma foto que já não se qualifica. O SDK da Adobe só admite os campos próprios de um plug-in no vocabulário de busca como texto ou enumeração, nunca como intervalo numérico, então ainda não existe uma coleção inteligente "aggregate > 8" — a faixa é o substituto de texto mais próximo. Duas propriedades adicionais de controle interno (a classificação/o pick que esta execução derivou) são gravadas ao mesmo tempo, mas ficam fora do Filtro de biblioteca e dos critérios de coleção inteligente — veja a nota sobre a exportação inversa em [Lightroom → Facet](#lightroom--facet). **NÃO VERIFICADO em um catálogo real:** se um campo de metadados sem título é realmente invisível no painel de Metadados e no Filtro de biblioteca não está confirmado apenas pela documentação do SDK do Lightroom; as duas propriedades de controle interno são, portanto, marcadas como `searchable = false, browsable = false`, o recurso mais seguro e confirmado em vez de confiar num comportamento de omissão de título não confirmado — elas podem continuar visíveis em algumas versões do Lightroom Classic.
- **Create "Facet" keywords from Facet tags (never included on export)** — cria uma palavra-chave raiz `Facet` com um filho para cada tag do Facet que suas fotos carreguem, e mantém as palavras-chave filhas `Facet ›` de cada foto exatamente correspondentes às suas tags do manifesto (adiciona e remove conforme as tags mudam entre execuções). Toda palavra-chave que essa opção cria ou toca tem `Include on Export` desativado, então as tags automáticas do Facet nunca vazam para uma exportação JPEG/TIFF ou uma galeria de cliente. Suas próprias palavras-chave fora da raiz `Facet` são lidas (para detectar uma palavra-chave `Facet` de nível superior pré-existente, que é adotada como raiz), mas nunca são adicionadas, removidas ou gravadas por essa opção; qualquer palavra-chave filha que você mesmo colocar sob essa raiz `Facet` adotada é tratada como obsoleta e removida.

**Por que coleções, e não pilhas.** O SDK do Lightroom não tem nenhuma chamada para criar ou gerenciar uma pilha (Stack) — `stackInFolder`/`stackPositionInFolder` são somente leitura em `LrPhoto`. Uma coleção é o substituto gravável mais próximo, e `canReturnPrior` faz com que executar o plug-in novamente reencontre a mesma coleção em vez de duplicá-la. Se você quiser uma pilha real do Lightroom, selecione as fotos de uma coleção e use você mesmo **Foto → Empilhamento → Agrupar em pilha** (Ctrl/Cmd+G) — o plug-in não pode fazer essa etapa por você.

**Limitações**, com honestidade:

- **Sinalizadores Pick existem apenas no catálogo.** Isso é do projeto do Lightroom, não do plug-in: o Lightroom nunca grava o sinalizador Pick no XMP, então ele não chega a nenhum outro aplicativo e se perde se você reconstruir o catálogo a partir dos arquivos. As classificações por estrelas, essas sobrevivem, via **Metadados → Salvar metadados no arquivo**.
- **O caminho da coleção inteligente por campo de metadados continua só em texto.** O SDK da Adobe só admite os campos próprios de um plug-in no vocabulário de busca como texto ou enumeração (`sdktext:`); os operadores numéricos (`>`, `<`, "está no intervalo") ficam reservados aos critérios nativos do Lightroom. O campo de faixa acima é o substituto de texto mais próximo de "aggregate > 8"; fazer a pontuação bruta passar pela **classificação por estrelas** (a opção de fallback acima) continua sendo o único canal que o próprio Lightroom filtra e ordena numericamente.
- **Desfazer** funciona um lote por vez: o plug-in grava em blocos de 200 fotos, então Ctrl/Cmd+Z desfaz 200 fotos de uma vez.
- Marque **Write facet-apply.log next to the manifest** antes de uma execução se precisar ver, linha a linha, quais caminhos casaram e o que foi gravado.

### Lightroom → Facet

**Classificações, picks e rejeições — o Lightroom vence (via o plug-in).** **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** abre um painel para salvar (sem nome de arquivo ou local padrão) e gravar um arquivo de estado do Lightroom (um registro por foto: `path`, e `rating`/`pick` só quando ainda precisam viajar — veja abaixo). Reimporte-o com `python facet.py --import-lightroom facet_lightroom_state.json` (adicione `--user alice` numa instalação multiusuário; ali obrigatório) ou, no viewer, o botão **Import Lightroom state…** da caixa de diálogo **Export to editor** da galeria, que envia o conteúdo do arquivo diretamente ao servidor. O valor do Lightroom vence incondicionalmente para cada chave presente em um registro — a CLI e o viewer compartilham o mesmo importador `processing/lightroom_sync.py`, que reporta as contagens `matched`/`unmatched`/`changed`:

| Estado no Lightroom | Resultado no Facet |
|---|---|
| Sinalizador Pick = Selecionado (`pick = 1`) | favorito = ativado, rejeitado = desativado |
| Sinalizador Pick = Rejeitado (`pick = -1`) | favorito = desativado, rejeitado = ativado |
| Sinalizador Pick = nenhum (`pick = 0`) | favorito = desativado, rejeitado = desativado |
| classificação por estrelas (`rating`, 0-5) | `star_rating` (`0` a limpa) |

Um registro que omite `rating` ou `pick` deixa intacto o valor correspondente do Facet — a exportação só inclui uma chave quando o valor atual do Lightroom difere do que o sentido Apply derivou por último para aquela foto (duas propriedades ocultas e não pesquisáveis do plug-in registram essa referência), então reexportar uma foto não tocada grava um registro vazio e não muda nada. Como o Lightroom vence incondicionalmente, exportar também limpa uma classificação/favorito/rejeição do Facet em qualquer foto exportada que o sentido Apply nunca tenha tocado — uma foto sem classificação e sem sinalizador no Lightroom (`pick = 0`, sem `rating`) sobrescreve uma classificação por estrelas ou favorito/rejeição existente do Facet com "nenhum". Uma importação que muda algo também reconstrói os pares de treinamento derivados das classificações e aciona o mesmo retreinamento automático disparado por inatividade que qualquer outra gravação de classificação. As cópias virtuais são deduplicadas para o seu original por caminho antes da exportação, preferindo o original quando ambos existem para o mesmo arquivo.

**Classificações, rótulos e palavras-chave via XMP.** Separadamente, e ainda de mão única nesta direção:

1. No Lightroom, selecione as fotos e escolha **Metadados → Salvar metadados no arquivo** (Ctrl/Cmd+S). Isso descarrega a classificação, o rótulo e as palavras-chave do catálogo no sidecar XMP (RAW) ou as incorpora diretamente no arquivo (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars` (opcionalmente limitado a um caminho) as relê para o banco de dados do Facet.

### Regras de conflito

- **Classificações e rótulos seguem a regra "o mais recente vence"**, comparando o `xmp:MetadataDate` do sidecar com o `scanned_at` da foto (a última vez que o Facet a pontuou) — não um carimbo de tempo por classificação. Um sidecar mais recente que a última varredura pode sobrescrever uma classificação que você alterou no Facet *depois* daquela varredura. Mantenha a ida e volta simples: exportar → Lightroom lê → editar no Lightroom → Lightroom salva → importar, sem reclassificar no Facet no meio.
- **Tags e palavras-chave são sempre mescladas** (união, sem duplicatas) nas duas direções — as palavras-chave do Lightroom nunca apagam as tags automáticas do Facet, e vice-versa.
- **Multiusuário** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): as classificações são roteadas para a linha `user_preferences` de Alice em vez das colunas globais. As palavras-chave permanecem globais seja qual for o `--user` — elas são compartilhadas entre usuários.
- Execute `python database.py --migrate-tags` depois de `--import-sidecars` se você usa a tabela de consulta `photo_tags`, para que os filtros de tags vejam imediatamente as palavras-chave mescladas.

## Capture One

O Capture One nunca grava no arquivo original nem em um sidecar XMP sincronizado continuamente como faz o salvamento automático do Lightroom — ele mantém seus próprios ajustes em arquivos `.cos` (Sessões) ou no banco de dados do catálogo, e a sua preferência **Sync Metadata** tem um modo bidirecional "Full Sync" que pode sobrescrever silenciosamente o lado que gravou por último. Rodar um ciclo bidirecional por essa configuração arrisca perder as alterações do Facet ou as do Capture One. O padrão seguro é **mão única, Facet → Capture One**:

1. `python facet.py --export-sidecars /caminho/da/sessão --embed-originals`.
2. No Capture One, deixe **Preferences → General → Sync Metadata** no valor padrão (não "Full Sync").
3. Selecione as imagens importadas, clique com o botão direito e escolha **Load Metadata** para trazer uma única vez a classificação, o rótulo e as palavras-chave do sidecar (ou dos metadados incorporados) para os campos de catálogo do Capture One.

Trate o Facet como a fonte de verdade a montante para as classificações e tags derivadas de IA daquela sessão: faça a importação pontual via `Load Metadata` e depois tome as demais decisões no Capture One, sem religar a sincronização de metadados dele de volta ao sidecar do Facet. Se quiser trazer as escolhas do Capture One de volta ao Facet, exporte-as explicitamente do Capture One para XMP e execute `--import-sidecars` naquela pasta como uma etapa separada e deliberada, em vez de uma sincronização automática — e lembre-se da [armadilha do nome dos sidecars RAW](#a-armadilha-do-nome-dos-sidecars-raw) acima: isso só funciona para JPEG/HEIC/TIFF/PNG/DNG, já que o Capture One também nomeia sidecars RAW como `<imagem>.xmp` em vez do `<imagem><ext>.xmp` do Facet.

## digiKam

Desde o digiKam 9.1.0 (lançado em 2026-06-07), o digiKam lê sidecars XMP nativamente — nenhum exiftool é necessário do lado do digiKam — e ele procura pelas duas convenções de nome (`<imagem><ext>.xmp` primeiro, com `<imagem>.xmp` como reserva), então encontra os sidecars do Facet para arquivos RAW sem a armadilha acima. Depois de `python facet.py --export-sidecars`, abra (ou atualize) a pasta no digiKam: ele captura automaticamente a classificação, o rótulo de cor, as palavras-chave e as regiões de rosto nomeadas, desde que **Settings → Configure digiKam → Metadata → Read from sidecar files** esteja habilitado (o padrão).

### Gancho no Batch Queue Manager

Você pode encaixar uma reimportação do Facet em um fluxo do Batch Queue Manager (BQM) do digiKam com a ferramenta **Custom Script**, para que as fotos que você classifica ou rotula no digiKam voltem para o banco de dados do Facet sem sair do digiKam. Habilite **Settings → Configure digiKam → Metadata → Write to sidecar files** para que o digiKam persista suas edições imediatamente em `<imagem>.xmp`, e então adicione uma fila cuja única ferramenta seja o Custom Script:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` são os marcadores por arquivo do digiKam (o BQM executa o script via `/bin/bash` no Linux/macOS e espera um arquivo de saída, daí o repasse com `cp`). Como `--import-sidecars` varre a pasta inteira, executá-lo uma vez por foto em um lote grande é redundante, embora inofensivo (é idempotente — fotos sem alteração são puladas). Para lotes grandes, dispense o gancho do BQM e simplesmente execute `python facet.py --import-sidecars /caminho/da/pasta` uma vez, manualmente, depois que a fila terminar.

## darktable

O darktable já recebe tratamento de primeira classe em [Configuração — Viewer](CONFIGURATION.md#viewer) (perfis/estilos de exportação `viewer.raw_processor.darktable`) e [Visualizador — Download](VIEWER.md#endpoints-da-api) (conversões `type=darktable`). No lado do XMP: o darktable grava o seu próprio `<imagem><ext>.xmp` para armazenar o histórico de edições, e o gravador de sidecar do Facet, apoiado no exiftool, mescla nesse mesmo arquivo no lugar — os nós `darktable:history`/máscaras são preservados, nunca sobrescritos. Nenhuma receita separada é necessária aqui: o comportamento bidirecional de sidecar descrito acima para o Lightroom (exportar/importar, o mais recente vence, união de tags) se aplica da mesma forma, sem a armadilha de nome RAW, já que darktable e Facet concordam em `<imagem><ext>.xmp`.

**Ressalva: o próprio recarregamento de XMP do darktable não é confiável.** Independentemente do caminho de gravação do Facet, reimportar uma imagem que o darktable já editou pode fazer com que o darktable sobrescreva o histórico de edições do sidecar com um em branco em vez de recarregá-lo — um bug upstream aberto ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), relatado em 2026-03-15) contra o qual a preferência "check for new/updated xmp files on start" não protege. O Facet não é a causa (a mesclagem via exiftool acima já preserva `darktable:history`), mas o risco está justamente na etapa de releitura da qual depende a ida e volta desta página. Solução prática, seguindo a mesma disciplina de "uma vez só" da receita do Capture One acima: depois do `--export-sidecars`, não reimporte em bloco uma pasta já editada — recarregue os sidecars apenas das imagens que o Facet acabou de tocar, e confirme que o histórico de edições ainda está lá antes de confiar no restante do lote.

## Como o Facet mescla

| Campo | O Facet grava | O Facet relê | Regra de conflito |
|---|---|---|---|
| Classificação (estrelas/rejeição) | `xmp:Rating` (`-1` = rejeitada) | `xmp:Rating` | O mais recente vence, vs. `scanned_at` |
| Rótulo de cor | `xmp:Label` (`Red` = rejeitada, `Yellow` = favorita) | `xmp:Label` | O mais recente vence, vs. `scanned_at` |
| Tags / palavras-chave | `dc:subject` (plano, inclui os nomes das pessoas das regiões de rosto nomeadas) | `dc:subject` | Sempre mesclado (união, sem duplicatas) |
| Tags hierárquicas | `lr:hierarchicalSubject` (`Category\|<cat>`, `People\|<nome>`) | Não reimportado | Somente exportação |
| Legenda | `dc:description` (+ `IPTC:Caption-Abstract` via exiftool) | Não reimportado | Somente exportação |
| Regiões de rosto nomeadas | `mwg-rs:RegionList` MWG (centralizada-normalizada, `Type=Face`) | Não reimportado | Somente exportação; lida nativamente pelo digiKam, **não** lida pelo Lightroom (uma limitação conhecida da Adobe — o Lightroom só consome regiões MWG que ele mesmo gravou) |

Veja [Comandos — Preview & Export](COMMANDS.md#preview--export) para a referência completa da CLI (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).
