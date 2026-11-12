# Receitas de Interoperabilidade com Editores

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · **Português** · [简体中文](../zh/INTEROP.md)

Receitas passo a passo para levar as classificações, os rótulos e as tags do Facet para o Lightroom, o Capture One, o digiKam e o darktable, e trazê-los de volta. Para a referência completa das opções `--export-sidecars` / `--import-sidecars` e o mapeamento de campos (`xmp:Rating`, `xmp:Label`, `dc:subject`), veja [Comandos — Preview & Export](COMMANDS.md#preview--export).

Os originais nunca são modificados, a menos que você peça a incorporação: `--embed-originals` na linha de comando, ou **Gravar metadados no arquivo** no visualizador.

## O que é transferido

As localizações manuais e as decisões de revisão só são transferidas quando você exporta os metadados no visualizador ou executa `--export-sidecars`.

- **GPS** usa `exif:GPSLatitude` / `exif:GPSLongitude`. Apenas as localizações definidas manualmente são exportadas, de modo que o GPS da varredura nunca substitui o GPS do arquivo. `--embed-originals` também grava o GPS EXIF nos originais compatíveis. Apagar uma localização exporta uma limpeza explícita; um campo ausente nunca apaga uma localização na importação.
- **Data de captura.** Uma data corrigida é exportada como `exif:DateTimeOriginal` (e como EXIF `DateTimeOriginal` com `--embed-originals`). Depois de **Usar data do ficheiro**, a exportação seguinte a remove do sidecar, mas não toca em uma data escrita por outro editor.
- **Manter e rejeitar.** Manter é independente de estrelas e favoritos. Rejeitar apaga Manter, estrelas e favorito.

O namespace XMP próprio do Facet, `https://github.com/ncoevoet/facet/ns/1.0/`, acrescenta:

| Tag | Valores | Finalidade |
|---|---|---|
| `facet:ReviewDecision` | `kept`, `rejected`, `undecided` | Decisão de revisão do Facet |
| `facet:GPSState` | `set`, `cleared` | Se o Facet definiu ou apagou a localização |
| `facet:DateState` | `set` | A data de captura do sidecar veio do Facet |
| `facet:KeywordState` | JSON (`version` 1; listas `owned`, `deleted`, `ai`, `manual`) | Quais palavras-chave o Facet gravou |
| `facet:RegionOwner` | `Facet` | As regiões de rostos MWG que o Facet gravou |

`facet:KeywordState` permite que `--reconcile-keywords` remova apenas nomes que o Facet possui, e impede que um antigo rótulo de IA vire tag manual na importação. `facet:RegionOwner` permite que o ExifTool substitua apenas as regiões de rostos do Facet.

Como `--import-sidecars` aplica uma decisão do Facet:

- Aplica a decisão quando os campos de revisão padrão concordam com ela ou estão ausentes.
- Se o estado de rejeição padrão divergir, outro editor alterou os campos padrão. O Facet ignora sua decisão privada e usa a verificação de mais recente vence, pela data da varredura, nos campos padrão.
- Uma decisão exportada junto com campos de revisão padrão também usa a verificação de mais recente vence, de modo que uma exportação mais antiga não desfaz uma decisão posterior. A exceção é uma foto sem estado de revisão (sem estrelas, favorito, Manter ou rejeição): uma biblioteca reescaneada recupera suas decisões.
- As importações apenas de decisão continuam explícitas (você as pede) e são aplicadas sem a verificação da data da varredura.

Outras regras:

- O GPS manual já presente no Facet é preservado, a menos que você adicione `--overwrite-manual-gps`. Coordenadas inválidas ou incompletas são ignoradas.
- `--user alice` limita importações e exportações às pastas visíveis e às decisões privadas desse usuário. O GPS permanece compartilhado. Sem `--user`, a CLI trabalha no estado global.
- As importações globais (sem `--user`), incluindo as pré-visualizações com `--dry-run`, não precisam do segredo de autenticação do visualizador.
- Com o ExifTool, a exportação é mesclada nos sidecars existentes. Sem ele, a exportação deixa intacto o sidecar existente do editor e grava um arquivo alternativo.
- As exportações com ExifTool exigem as configurações de etiquetas incluídas no Facet. Se estiverem ausentes, a exportação para antes de alterar qualquer coisa; reinstale o Facet.

## A armadilha do nome dos sidecars RAW

O Facet exporta `IMG_1234.CR2.xmp` ao lado de `IMG_1234.CR2` (convenção de nome completo do darktable). Lightroom Classic e Capture One geralmente usam `IMG_1234.xmp` para RAW proprietário. Os nomes exportados nunca mudam.

Para JPEG/HEIC/TIFF/PNG/DNG, `--embed-originals` grava dentro do arquivo. GIF/WebP/BMP/AVIF/JPEG XL e RAW proprietário ainda precisam de um sidecar com nome compatível.

Na importação, escolha o nome com `--import-sidecars --sidecar-naming full|basename|auto`:

- `full` (padrão): lê `<image.ext>.xmp` ou `<image.ext>.facet.xmp`, o modificado mais recentemente. Em caso de empate, vence o principal.
- `basename`: lê `<image>.xmp` (apenas a última extensão é removida). Os sidecars com nome completo são ignorados.
- `auto`: aceita o tipo que existir. Se ambos existirem, a foto é ignorada por ambiguidade; escolha `full` ou `basename`.

Em `basename` e `auto`, um nome base compartilhado por várias imagens (por exemplo `same.CR3` e `same.jpg`) é recusado, mesmo que só uma esteja no escopo. Use sidecars com nome completo para esses casos. `same_v1.jpg` tem outro nome base e não há problema.

- Um arquivo de extensão dupla como `IMG.CR2.jpg` nunca lê `IMG.CR2.xmp`, que pertence a `IMG.CR2`. O mesmo vale para o arquivo alternativo `.facet.xmp` de outra imagem.
- Nomes incompatíveis, ambiguidades e sidecars ilegíveis são informados. O Facet não tenta outro nome depois de uma falha de análise.
- O resumo conta todas as fotos afetadas, inclusive os sidecars ignorados por causa do nome escolhido. Os avisos mostram um exemplo de cada tipo.
- Nenhum arquivo é renomeado.

Importar não exige ExifTool. Mesclar na exportação, incorporar e gravar retângulos de rostos MWG exigem ExifTool. Sem ele, o Facet deixa intacto o sidecar existente do editor e grava `<image.ext>.facet.xmp` sem retângulos de rostos. Os outros editores não procuram esse nome, então entregue-o deliberadamente.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (adicione um caminho para limitar o escopo, por exemplo `--export-sidecars /photos/2026-wedding`). Adicione `--embed-originals` para também gravar diretamente em arquivos JPEG/HEIC/TIFF/PNG/DNG.
2. No módulo Biblioteca do Lightroom Classic, selecione as fotos (Ctrl/Cmd+A para todas) e escolha **Metadados → Ler metadados do arquivo**. O Lightroom substitui a classificação, o rótulo de cor e as palavras-chave pelos do sidecar (ou dos metadados incorporados).

O marcador de rejeição do Facet (`xmp:Rating = -1`) é relido como o sinalizador de Rejeição do Lightroom. Um favorito do Facet grava `xmp:Label = Yellow`, que o Lightroom exibe como o **rótulo de cor Amarelo**, não como Pick. Para obter Picks, use o plug-in abaixo ou filtre pelo rótulo Amarelo.

`python facet.py --export-manifest` grava os dados do Facet sem XMP: caminho, categoria, todas as pontuações, tags e as mesmas colunas de classificação do `--export-sidecars`. Use `--export-manifest --user alice` para as classificações por usuário. Veja [Comandos — Preview & Export](COMMANDS.md#preview--export). O plug-in do Facet abaixo o lê.

**Manifesto versão 2** acrescenta `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` e uma contagem `pending_corrections` de nível superior. Essa contagem é o número de correções manuais de bracket/panorama ainda não aplicadas; execute novamente `--detect-panoramas` para aplicá-las. O plug-in a exibe como aviso em sua Pré-visualização. Um plug-in de versão 2 recusa um manifesto de versão 1 (e vice-versa); execute `--export-manifest` novamente se vir essa caixa de diálogo.

No visualizador, a caixa de diálogo **Exportar para o editor** da galeria tem um botão **Baixar manifesto do Lightroom** para a mesma seleção ou filtro — veja [Editor Export](VIEWER.md#exportação-para-editor). Ele gera o mesmo `facet_manifest.json` que `--export-manifest`.

### O plug-in do Facet (classificações por estrelas, sinalizadores Pick, campos de metadados e palavras-chave)

`facet.lrplugin/`, no repositório do Facet, é um plug-in do Lightroom Classic. Ele grava a classificação por estrelas e o estado favorito/rejeitado do Facet **diretamente no catálogo**. Isso resolve duas coisas que o XMP não resolve: o Lightroom nunca encontra um sidecar do Facet para RAW proprietário, e o XMP não tem como carregar o sinalizador Pick do Lightroom.

O plug-in lê um arquivo de manifesto. Nunca fala com o servidor do Facet, não pede senha e funciona com o Facet desligado. Ele casa as fotos por caminho, então **uma biblioteca inteiramente RAW funciona como uma de JPEG**.

Ele adiciona dois itens em **Biblioteca → Extras de plug-in** (**Library → Plug-in Extras**):

- **Facet: Apply ratings and flags...** — manifesto → catálogo (esta seção).
- **Facet: Export Lightroom State to Facet...** — catálogo → Facet, veja [Lightroom → Facet](#lightroom--facet).

**Instalação** (uma única vez):

1. Copie a pasta `facet.lrplugin` para a máquina que executa o Lightroom. No macOS, compacte-a antes em zip: o Finder trata uma pasta `.lrplugin` como um pacote.
2. No Lightroom Classic: **Arquivo → Gerenciador de plug-ins → Adicionar**, selecione a pasta `facet.lrplugin` e clique em **Concluído**.

**Uso:**

1. `python facet.py --export-manifest /photos/2026-wedding` (o caminho limita a exportação; o arquivo é sempre `facet_manifest.json` no diretório atual). Copie-o para a máquina do Lightroom, se necessário.
2. No módulo Biblioteca, selecione as fotos e escolha **Biblioteca → Extras de plug-in → Facet: Apply ratings and flags...**
3. Aponte o diálogo para `facet_manifest.json`. O caminho fica memorizado.
4. **Se o Facet analisou as fotos em outra máquina, preencha os dois prefixos de caminho.** O manifesto salva os caminhos da máquina que fez a varredura (por exemplo `/volume1/photos/...` em um NAS); o Lightroom salva os da estação de trabalho (por exemplo `Z:\photos\...`). Informe o prefixo do Lightroom e o do Facet para a mesma pasta. Deixe ambos vazios se os caminhos coincidirem. Se estiverem errados, nada casa.
5. Escolha o escopo: as fotos selecionadas (padrão) ou toda a pasta atual.
6. Clique em **Preview...** (Visualizar). **Nada é gravado ainda.** Ele mostra quantas fotos casaram, quantas não, e o que definiria. Se nada casou, mostra um caminho de exemplo do Lightroom ao lado de um caminho de exemplo do manifesto, para que você corrija os prefixos.
7. Clique em **Apply** (Aplicar). Você pode cancelar durante o progresso. Um resumo mostra o que foi definido, ignorado e não encontrado.

**O que ele grava** (nunca nos seus arquivos de imagem):

| Estado no Facet | Campo do Lightroom |
|---|---|
| `star_rating` 1-5 | classificação por estrelas |
| favorito | sinalizador Pick |
| rejeitado | sinalizador Reject |

Uma classificação do Facet igual a 0 significa "sem opinião" e nunca é gravada.

**Regra de sobrescrita.** Por padrão, o plug-in só define uma classificação em uma foto *sem classificação* no Lightroom, e um sinalizador em uma foto *sem sinalizador*. Suas próprias classificações e sinalizadores são mantidos e contados como "kept as they are" (mantidas como estão). Marque **Overwrite ratings and flags that are already set in Lightroom** para substituí-los. A exportação de sidecars segue a mesma regra (`xmp_export.score_to_rating.only_when_unrated`, padrão `true`).

**Opções da caixa de diálogo** (todas desativadas por padrão, memorizadas entre as execuções):

- **Fill in star ratings from Facet scores for photos you have not rated** — se o manifesto não tem `star_rating` (ou é 0), a pontuação `aggregate` é convertida em estrelas. Esse recurso de reserva **nunca sobrescreve uma classificação existente no Lightroom, mesmo com Overwrite marcada.**
- **Pick the recommended frame of each burst** — em cada grupo de sequência com pelo menos 2 membros, todo membro marcado como `is_burst_lead` é definido como Pick (uma sequência pode manter mais de um). Quadros isolados e grupos sem líder são ignorados. Seus próprios sinalizadores Pick/Reject e os favoritos/rejeições do Facet sempre prevalecem.
- **Reject the other frames** (somente com a opção de pick) — rejeita todo membro da sequência que não é líder. Os membros de um bracket, panorama ou panorama HDR nunca são rejeitados, e grupos sem líder não recebem rejeições.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — para cada grupo com pelo menos 2 fotos correspondentes no escopo, cria ou reaproveita uma coleção sob `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` ou `Facet › HDR panoramas`.
  - Nome: `<yyyy-mm-dd HH:MM:SS> – <filename>` do membro mais antigo, ou `~ (no date) – <filename>` se ele não tem horário de captura.
  - Uma sequência cujos membros pertencem todos a um mesmo conjunto bracket ou panorama não recebe uma coleção Bursts separada.
  - **Executar novamente apenas adiciona fotos.** Uma foto que depois sai de um conjunto permanece na sua coleção.
  - Limitação conhecida: dois grupos cujos membros mais antigos têm o mesmo segundo de captura e o mesmo nome de arquivo (por exemplo, duas câmeras que gravam `IMG_0001`) compartilham uma coleção.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (somente com a opção acima) — esvazia e reabastece uma coleção, mas só quando a coleção e todo o seu grupo estão no escopo atual. Coleções parcialmente cobertas e coleções inteligentes são ignoradas.
    - Também esvazia e exclui a coleção de um grupo que se dissolveu nesta execução, mas só se todas as fotos dela foram encontradas por esta execução.
    - Só toca coleções cujo nome tem o formato próprio do Facet (data-hora ou `~ (no date)`, seguido de ` – <filename>`). Coleções que você mesmo nomeou nunca são tocadas.
    - O Preview mostra uma linha `Facet collections to delete: N` quando há algo a excluir. O resumo informa as coleções reconstruídas, excluídas, ignoradas e com falha.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — grava a pontuação `aggregate` (por exemplo `8.4`), uma faixa inteira (`0`-`10`), a categoria e o tipo de conjunto nos campos de metadados próprios do Facet. Eles aparecem no painel de Metadados e funcionam como critérios de texto (`sdktext:`) no Filtro de biblioteca e em coleções inteligentes, por exemplo faixa "qualquer um entre 8, 9, 10". Um campo que já não se aplica é apagado. Duas propriedades de controle interno (a classificação e o pick que esta execução derivou) também são gravadas; ficam fora da busca, mas ainda podem aparecer em algumas versões do Lightroom Classic (não verificado).
- **Create "Facet" keywords from Facet tags (never included on export)** — cria uma palavra-chave raiz `Facet` com um filho para cada tag (de IA e [tags manuais](#tags-manuais-e-palavras-chave-xmp)). Os filhos `Facet ›` de cada foto são ajustados para corresponder às suas tags, então uma tag removida no Facet some no próximo Apply. `Include on Export` fica desativado em todos eles, de modo que nunca vazam para exportações nem galerias de cliente. Suas palavras-chave fora da raiz `Facet` nunca são alteradas. Uma palavra-chave `Facet` de nível superior já existente é adotada como raiz, e qualquer filho que você mesmo tenha colocado sob ela é removido.

**Por que coleções, e não pilhas.** O SDK do Lightroom não consegue criar pilhas. Para empilhar as fotos de uma coleção, selecione-as e use **Foto → Empilhamento → Agrupar em pilha** (Ctrl/Cmd+G).

**Limitações:**

- **Sinalizadores Pick ficam no catálogo.** O Lightroom nunca os grava no XMP, então nenhum outro aplicativo os vê, e reconstruir o catálogo a partir dos arquivos os perde. As classificações por estrelas sobrevivem via **Metadados → Salvar metadados no arquivo**.
- **Sem coleções inteligentes numéricas nos campos do Facet.** Os campos de plug-in são só de texto (`sdktext:`); os operadores numéricos (`>`, `<`, "está no intervalo") funcionam apenas nos campos nativos do Lightroom. Use o campo de faixa, ou a opção de preenchimento de estrelas, que o Lightroom ordena e filtra numericamente.
- **Desfazer** reverte um lote de 200 fotos por Ctrl/Cmd+Z.
- Marque **Write facet-apply.log next to the manifest** para registrar quais caminhos casaram e o que foi gravado.

### Lightroom → Facet

**Classificações, picks e rejeições — o Lightroom vence (via o plug-in).**

1. **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** abre um painel para salvar. O arquivo contém um registro por foto: `path`, mais `rating`/`pick` quando precisam viajar.
2. Importe-o com `python facet.py --import-lightroom facet_lightroom_state.json` (`--user alice` é obrigatório em uma instalação multiusuário) ou com **Importar estado do Lightroom…** na caixa de diálogo **Exportar para o editor** da galeria.

O valor do Lightroom vence para todos os campos de um registro. A importação informa as contagens `matched`/`unmatched`/`changed`.

| Estado no Lightroom | Resultado no Facet |
|---|---|
| Sinalizador Pick = Selecionado (`pick = 1`) | favorito = ativado, rejeitado = desativado |
| Sinalizador Pick = Rejeitado (`pick = -1`) | favorito = desativado, rejeitado = ativado |
| Sinalizador Pick = nenhum (`pick = 0`) | favorito = desativado, rejeitado = desativado |
| classificação por estrelas (`rating`, 0-5) | `star_rating` (`0` a limpa) |

- Um registro sem `rating` ou `pick` deixa intacto o valor correspondente do Facet. A exportação só inclui um campo quando o valor do Lightroom difere do que o último Apply definiu, então uma foto não tocada não muda nada.
- As cópias virtuais são mescladas ao seu original antes da exportação.
- Uma importação bem-sucedida que muda algo atualiza os pares de treinamento e arma o retreinamento automático, como qualquer mudança de classificação.

> **Aviso:** Como o Lightroom vence, uma foto que o Apply nunca tocou e que está sem classificação e sem sinalizador no Lightroom (`pick = 0`, sem `rating`) apaga na importação a classificação por estrelas, o favorito e a rejeição do Facet.

**Classificações, rótulos e palavras-chave via XMP** (mão única):

1. No Lightroom, selecione as fotos e escolha **Metadados → Salvar metadados no arquivo** (Ctrl/Cmd+S). Isso grava classificação, rótulo e palavras-chave no sidecar XMP (RAW) ou dentro do arquivo (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars /path --sidecar-naming basename` lê os sidecars RAW. Nomes base RAW/JPEG compartilhados são recusados. O comando não lê metadados incorporados. As palavras-chave importadas viram tags manuais.

### Regras de conflito

- **Tags e palavras-chave são mescladas por padrão.** As exportações adicionam palavras-chave do Facet; `--reconcile-keywords` também remove nomes obsoletos pertencentes ao Facet. As importações adicionam tags manuais e nunca substituem as de IA. Veja [Tags manuais e palavras-chave XMP](#tags-manuais-e-palavras-chave-xmp).
- **Multiusuário** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): as classificações vão para as classificações próprias da Alice (`user_preferences`) em vez das globais. As palavras-chave são sempre globais: as tags manuais são compartilhadas.
- As palavras-chave importadas são armazenadas em `photo_manual_tags`, que os filtros de tags leem diretamente. Depois de `--import-sidecars` não é preciso rodar `python database.py --migrate-tags`.

## Capture One

O Capture One mantém seus ajustes em arquivos `.cos` (Sessões) ou no catálogo. O modo "Full Sync" de **Sync Metadata** pode sobrescrever o lado que gravou por último, então um ciclo bidirecional pode perder edições. Use **mão única, Facet → Capture One**:

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`.
2. No Capture One, deixe **Preferences → General → Sync Metadata** no valor padrão (não "Full Sync").
3. Selecione as imagens, clique com o botão direito e escolha **Load Metadata** para trazer uma única vez a classificação, o rótulo e as palavras-chave.

Depois, continue trabalhando no Capture One sem sincronização automática. Para trazer de volta ao Facet o XMP salvo, execute `--import-sidecars /path/to/shoot --sidecar-naming basename` para sidecars RAW sem a extensão da imagem, ou `full` para nomes completos. Nomes base RAW/JPEG compartilhados são recusados. O comando lê sidecars, não metadados incorporados.

## digiKam

As [configurações de sidecars do digiKam](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings) usam um único nome: `filename.ext.xmp` por padrão, ou `filename.xmp` com **Sidecar file names are compatible with commercial programs** ativado. Ele não tenta ambos.

- **Facet → digiKam:** use a configuração de nome completo, ative **Read from sidecar files**, releia os metadados dos arquivos e verifique os campos.
- **digiKam → Facet:** passe `--sidecar-naming full` ou `basename` conforme a sua configuração do digiKam.

Estrelas, rótulos de cor e sinalizadores de seleção significam coisas ligeiramente diferentes em cada aplicativo, então verifique o resultado.

### Gancho no Batch Queue Manager

Você pode executar uma importação do Facet a partir da ferramenta **Custom Script** do Batch Queue Manager (BQM) do digiKam. Antes, ative a gravação de sidecars, salve a configuração de nome e aplique as mudanças de metadados pendentes (o digiKam pode adiar as gravações). Este exemplo supõe sidecars com nome completo; use `basename` apenas para uma coleção sem nomes base compartilhados:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` são os marcadores por arquivo do digiKam. O BQM espera um arquivo de saída, daí o `cp`. Como `--import-sidecars` varre a pasta inteira, executá-lo por foto é redundante, mas inofensivo. Para lotes grandes, execute `python facet.py --import-sidecars /path/to/folder` uma vez depois que a fila terminar.

## darktable

Veja [Configuração — Viewer](CONFIGURATION.md#viewer) (perfis e estilos de exportação `viewer.raw_processor.darktable`) e [Visualizador — Download](VIEWER.md#endpoints-da-api) (conversões `type=darktable`).

O darktable salva seu histórico de edições em seu próprio `<image><ext>.xmp`. O gravador do Facet com ExifTool mescla nesse arquivo e preserva os nós `darktable:history` e de máscaras. O comportamento de sidecar do Lightroom descrito acima (exportar/importar, o mais recente vence, união de tags) se aplica sem mudanças, e não há divergência de nome RAW: ambos usam `<image><ext>.xmp`.

**Versão do ExifTool:**

- Recomenda-se a **13.28 ou superior**.
- As alterações de rostos exigem a **12.65 ou superior**. Versões anteriores ou desconhecidas ignoram as alterações de rostos com um aviso e exportam o restante.
- As versões **13.23 a 13.27** corrompem sidecars que contêm o histórico do darktable, por isso o Facet se recusa a escrever com elas e pede a atualização. A imagem Docker traz uma versão segura fixada. Os pacotes de distribuição podem não trazer (o `libimage-exiftool-perl` do Debian trixie é a 13.25).

> **Aviso:** o próprio darktable pode apagar o histórico de edições ao reimportar uma imagem já editada: ele pode sobrescrever o histórico do sidecar com um em branco. É um bug upstream aberto ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), relatado em 2026-03-15), e a preferência "check for new/updated xmp files on start" não o evita. Depois de `--export-sidecars`, não reimporte em bloco uma pasta editada. Recarregue apenas as imagens que o Facet tocou e confira o histórico delas antes.

## Tags manuais e palavras-chave XMP

O Facet salva os tags que você digita (veja [Visualizador — Tags manuais](VIEWER.md#tags-manuais)) em `photo_manual_tags`, separados dos tags de IA de `photos.tags`. Um reescaneamento ou uma nova etiquetagem nunca os toca.

- **Exportação.** Cada escritor de palavras-chave emite primeiro os tags de IA, depois os tags manuais, depois os nomes de pessoas, sem duplicatas e sem diferenciar maiúsculas de minúsculas. Isso cobre `--export-sidecars`, as ações de exportação XMP e «Gravar metadados no arquivo» da galeria, e o manifesto do Lightroom (`--export-manifest`, `/api/lightroom/manifest`).
- **Importação.** `--import-sidecars` lê palavras-chave planas de `dc:subject` e caminhos hierárquicos separadamente de `lr:hierarchicalSubject`. As palavras-chave planas são normalizadas como tags digitados: sem espaços nas pontas, em minúsculas, no máximo 64 caracteres, 50 tags manuais por foto. Cada uma vira um tag manual com origem `xmp`, a menos que:
  - já seja um dos tags de IA ou nomes de pessoas da foto,
  - duplique um caminho presente explicitamente em `lr:hierarchicalSubject`,
  - contenha vírgula ou caractere de controle, ou
  - ultrapasse o limite.
- **A remoção de palavras-chave é explícita.** Por padrão, as exportações apenas adicionam. `--export-sidecars /path --reconcile-keywords` (exige ExifTool) também remove nomes que o Facet gravou antes e que já não estão no Facet. Palavras-chave que o Facet nunca gravou nunca são removidas, mesmo que o nome coincida, e sidecars antigos sem marcador não dão propriedade ao Facet. Se você readicionar em outro editor uma palavra-chave removida, o Facet pode importá-la de novo e a trata depois como externa. As palavras-chave são compartilhadas mesmo com `--user`.
- **As palavras-chave do Facet vencem na exportação.** Uma palavra-chave ainda presente no Facet é gravada de volta mesmo que outro editor a tenha removido do arquivo. Para removê-la de vez, remova o tag no Facet. A reconciliação nunca apaga tags do Facet.
- Nomes como `2024`, `1.50`, `1e3`, `true`, `false` e `null` preservam a grafia.
- Se o Facet não consegue ler os metadados de um arquivo existente, a exportação para antes de gravar.
- **O manifesto do Lightroom, em compensação, propaga as remoções.** A opção de palavras-chave do plug-in reescreve os filhos `Facet ›` de cada foto a cada Apply.
- **A origem IA sobrevive à retagagem.** Os sidecars registram quais palavras-chave eram de IA e quais manuais, então uma nova etiquetagem não transforma uma antiga palavra-chave de IA em tag manual. Sidecars de versões anteriores do Facet mantêm o comportamento aditivo antigo.
- **Hierarquias.** Os caminhos importados são adicionados à hierarquia compartilhada; nomes planos com `|` ou `/` não criam uma hierarquia por si só. Caminhos marcados como gerados pelo Facet não são importados como atribuições manuais, a menos que também estejam marcados como manuais. Um sidecar do Facet 1.28 ou anterior traz `facet:KeywordState`, mas não `facet:HierarchyState`; seus caminhos `Category|` e `People|` são tratados como gerados e ignorados, incluindo os que um usuário digitou ali, e cada caminho ignorado aparece na prévia da importação como `legacy_generated_path`. As exportações incluem atribuições explícitas e caminhos gerados de categorias/pessoas. A exportação é aditiva por padrão; `--reconcile-keywords` remove apenas caminhos obsoletos pertencentes ao Facet e preserva os externos.
- **Limites de propriedade:** 10.000 nomes por lista e 1.024 caracteres por nome. Uma exportação que os excedesse para antes de gravar. Arquive e limpe esse sidecar manualmente antes de recomeçar.
- **As palavras-chave importadas por uma versão anterior ficam onde estão.** As versões anteriores mesclavam as palavras-chave em `photos.tags`, onde parecem tags de IA, e nada as migra. Para converter uma em tag manual, esvazie ou reetiquete `photos.tags` e rode `--import-sidecars` de novo — ou adicione o tag manualmente.
- **Arquivos movidos ou renomeados.** As tags manuais estão ligadas ao caminho do catálogo. Depois de mover os arquivos, use o [processo de revinculação](RELINK.md) com revisão prévia para atualizar esse caminho e preservar as tags; apenas varrer o novo local não as transfere.
- **`--export-csv` e `--export-json` continuam somente de IA.** O valor `tags` deles não inclui tags manuais.

## Como o Facet mescla

| Campo | O Facet grava | O Facet relê | Regra de conflito |
|---|---|---|---|
| Classificação (estrelas/rejeição) | `xmp:Rating` (`-1` = rejeitada) | `xmp:Rating` | Relógios de revisão; regra histórica da varredura |
| Rótulo de cor | `xmp:Label` (`Red` = rejeitada, `Yellow` = favorita) | `xmp:Label` | Relógios de revisão; regra histórica da varredura |
| Tags / palavras-chave | `dc:subject` (plano, tags de IA + tags manuais, inclui os nomes das pessoas reconhecidas) | `dc:subject` (armazenado como tags manuais) | Aditivo por padrão; `--reconcile-keywords` remove apenas nomes obsoletos do Facet; os imports permanecem aditivos ([Tags manuais e palavras-chave XMP](#tags-manuais-e-palavras-chave-xmp)) |
| Tags hierárquicas | `lr:hierarchicalSubject` (atribuições explícitas e caminhos gerados de categorias/pessoas) | `lr:hierarchicalSubject` (atribuições à hierarquia compartilhada) | Importação aditiva; a reconciliação na exportação remove apenas caminhos obsoletos do Facet |
| Legenda | `dc:description` idioma padrão (+ `IPTC:Caption-Abstract` via exiftool) | Não reimportado | Somente exportação |
| Regiões de rosto nomeadas | `mwg-rs:RegionList` + `facet:RegionOwner=Facet` MWG (centralizada-normalizada, `Type=Face`) | Não reimportado | Somente exportação; lida nativamente pelo digiKam, **não** lida pelo Lightroom (uma limitação conhecida da Adobe — o Lightroom só consome regiões MWG que ele mesmo gravou) |

Veja [Comandos — Preview & Export](COMMANDS.md#preview--export) para a referência completa da CLI (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).

**Limpezas de GPS.** Se um sidecar tem campos GPS padrão e também um antigo `facet:GPSState=cleared`, prevalece um par completo e válido de latitude/longitude. Um par parcial ou inválido é ignorado e nunca apaga a localização. Apenas um par ausente ou vazio, junto com o marcador de limpeza, apaga o GPS. O GPS manual permanece protegido, salvo pedido de sobrescrita.

**Legendas.** Com o ExifTool, a exportação atualiza apenas o idioma padrão (`x-default`) de `dc:description` e preserva os outros idiomas. Uma legenda vazia no Facet deixa intactas as existentes. Sem o ExifTool, o Facet grava uma legenda no idioma padrão e, quando existe um sidecar de editor, grava em `<image>.facet.xmp`.

**Regiões de rostos.** Com o ExifTool, a exportação substitui apenas os retângulos MWG marcados com `facet:RegionOwner=Facet`.

- Regiões sem marca, inclusive as de versões anteriores do Facet, são preservadas. Depois de atualizar, um rosto antigo sem marca e sua nova cópia marcada podem aparecer juntos, e limpar rostos mantém o antigo.
- Exportações repetidas substituem as cópias marcadas; elas não se acumulam.
- Se as dimensões da imagem diferem das usadas para desenhar as regiões existentes (ou são desconhecidas), as alterações de rostos são ignoradas com um aviso. Classificação, rótulo, palavras-chave e GPS continuam sendo exportados.
- Metadados de rostos ilegíveis ou inválidos interrompem a exportação ou incorporação de uma única foto antes de gravar.
- O gravador alternativo (sem ExifTool) não exporta retângulos de rostos.
- Uma região marcada que você edita em outro lugar continua sendo do Facet. Remova o marcador de propriedade para mantê-la como sua.

> **Aviso:** As gravações em arquivos separados não são atômicas. Uma falha de E/S ou uma alteração externa durante a exportação pode deixar alguns arquivos atualizados e outros não.

Se a verificação da versão do ExifTool falhar, o Facet a repete na próxima vez. Enquanto a versão for desconhecida, as regiões de rostos são ignoradas e o restante é exportado. As versões defeituosas conhecidas são sempre recusadas.

## Prévia de importação de sidecars e conflitos de revisão

Execute `--import-sidecars /path --dry-run` para ver o plano em JSON antes de gravar: o sidecar escolhido, os campos antes/depois, as palavras-chave a adicionar, a data da fonte e os motivos de recusa/conflito. A prévia abre o banco de dados somente para leitura e nunca o altera. Aplicar relê tudo, então a prévia não é um token que se reaplica.

Se o banco de dados estiver ausente, ilegível ou inválido, a prévia termina com código 1 e não o cria nem o repara. `--dry-run-count` limita apenas as amostras da varredura, não as prévias de importação.

`--sidecar-fields review,gps,keywords` seleciona quais grupos importar; deixe um grupo de fora para ignorá-lo.

- **review** importa estrelas, favorito, rejeição e Manter juntos, de modo que um conflito nunca aplica metade de uma decisão.
- **gps** preserva as localizações manuais, a menos que `--overwrite-manual-gps` seja dado.
- **keywords** são aditivas e compartilhadas, mesmo com `--user`.

**Relógios de edição.** O Facet registra quando cada campo de revisão foi alterado pela última vez, por foto e conta, inclusive as redefinições. Um sidecar mais antigo que essa alteração é um conflito `newer_local_edit`, e esse grupo de revisão fica inalterado. `--overwrite-sidecar-review` anula isso e a verificação da data da varredura. Uma fonte `local` significa um escritor desconhecido, não necessariamente uma pessoa. Legendas, rostos e GPS externo sem marcador nunca são importados.

- Os campos alterados antes de o Facet começar a registrar edições não têm data de edição conhecida. Vale a regra da data da varredura, informada como `untracked_legacy_edit`.
- A prévia também abre bancos mais antigos sem atualizá-los; um campo Manter ausente é lido como indeciso.
- A data do sidecar é `xmp:MetadataDate`, ou a data de modificação do arquivo se ela estiver ausente ou inválida.
- Os detalhes listam as primeiras 1.000 fotos no escopo e 100 notas por foto, com as contagens do que foi omitido.

Os relógios de edição ficam em seu próprio banco de dados. Uma nova exportação para o visualizador não copia relógios de edição do scanner nem caminhos de sidecar. Uma exportação incremental preserva os relógios do próprio visualizador, de modo que as redefinições feitas nele (inclusive as classificações por usuário excluídas) sobrevivem. Os valores do scanner que o visualizador nunca editou continuam sendo atualizados.

> **Aviso:** Um banco do visualizador criado por uma compilação não lançada anterior à 1.24.0 pode conter relógios copiados do scanner. Eles agora contam como edições do visualizador, então esses campos deixam de acompanhar as atualizações do scanner. Faça backup e revise esse banco antes de reconstruí-lo: uma reconstrução completa descarta as alterações locais do visualizador.
