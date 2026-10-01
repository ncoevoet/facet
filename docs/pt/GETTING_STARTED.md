# Primeiros Passos

> 🌐 [English](../GETTING_STARTED.md) · [Français](../fr/GETTING_STARTED.md) · [Deutsch](../de/GETTING_STARTED.md) · [Italiano](../it/GETTING_STARTED.md) · [Español](../es/GETTING_STARTED.md) · **Português** · [简体中文](../zh/GETTING_STARTED.md)

Um passo a passo da primeira sessão para o caso mais comum: você acabou de fotografar ou
importar um lote de fotos e quer terminar com um conjunto selecionado. Ele segue seis
etapas — importar, agrupar fotos parecidas, ensinar ao Facet o seu gosto, descartar,
marcar com tags, exportar — e aponta para a página que explica cada uma em vez de
repeti-la.

![Passo a passo da galeria do Facet](../screenshots/walkthrough.gif)

## Antes de começar

### 1. Defina uma senha de edição

Uma instalação nova é **somente leitura**. Você pode navegar (sujeito a `viewer.password`,
se você definir uma), mas toda edição — avaliações, triagem, rostos, álbuns, tags e o botão
Escanear — é recusada até que você defina `viewer.edition_password` em
`scoring_config.json` e reinicie o visualizador (a configuração não é recarregada a quente).

Com o `docker-compose.yml` incluído, você não precisa inventar uma: a imagem gera uma senha
na primeira inicialização e a exibe uma única vez. Leia-a com:

```bash
docker compose logs facet
```

Depois, entre como editor a partir da galeria. Detalhes: [Modo de Usuário Único](VIEWER.md#modo-de-usuário-único-padrão) e [Configurações do Docker que você pode alterar](INSTALLATION.md#configurações-do-docker-que-você-pode-alterar).

![Login de edição](../screenshots/getting-started-edition-login.jpg)

### 2. Escolha um caminho de instalação

O Docker é o caminho mais curto no Windows, macOS e Linux; a instalação nativa é para quem
prefere não usar contêineres. [Qual instalação é para mim?](INSTALLATION.md#qual-instalação-é-para-mim)
traz a tabela.

Duas coisas costumam atrapalhar com contêineres:

- **Configuração e propriedade dos arquivos.** O contêiner roda como uid 1000, que o Podman
  rootless mapeia para um subuid do host, então os arquivos que ele cria em `./facet-config`
  podem não pertencer ao seu usuário. Veja
  [Propriedade do arquivo no contêiner](INSTALLATION.md#propriedade-do-arquivo-no-contêiner).
- **Os caminhos são os do contêiner, não os do host.** Você escaneia `/data/photos`, não
  `~/Pictures`. Veja [Semântica de caminhos em contêiner](DEPLOYMENT.md#semântica-de-caminhos-em-contêiner).

### 3. Sem GPU? Tudo bem

Tudo — pontuação, rostos, tags, triagem, o botão Escanear — funciona em um processador com o
perfil `legacy` de CPU; só fica mais lento. Leia
[Sem placa de vídeo](INSTALLATION.md#sem-placa-de-vídeo) e
[Qual perfil combina com o meu hardware?](INSTALLATION.md#qual-perfil-combina-com-o-meu-hardware). Uma placa
nunca é condição para o botão Escanear aparecer.

### 4. Atenção à memória

Um contêiner com limite de memória pode ser encerrado no meio de uma varredura nos perfis
maiores. Consulte
[Limites de memória do contêiner](DEPLOYMENT.md#limites-de-memória-do-contêiner) antes de limitar um; em um
Mac, veja [Memória em um Mac](INSTALLATION.md#memória-em-um-mac).

## O fluxo de trabalho

### Etapa 1: Importar imagens

Coloque suas fotos na pasta para a qual o Facet aponta (JPEG, HEIF/HEIC, PNG e os formatos
RAW mais comuns — veja [tipos de arquivo suportados](README.md#tipos-de-arquivo-suportados)) e escaneie-a. Você pode
fazer isso pelo terminal ([Scanning](COMMANDS.md#scanning)) ou pelo navegador:

- Defina `viewer.features.show_scan_button` como `true` (vem desativado).
- Usuário único: você precisa de uma senha de edição **e** de estar logado como editor.
  Multiusuário: você precisa do papel de superadmin.
- Adicione a pasta a `viewer.scan_directories` para que o lançador tenha algo a oferecer.

Um botão **Escanear novas fotos** fica então acima da grade da galeria em qualquer largura
de tela, e não apenas na galeria vazia. Regras completas: [Disparo de Varredura](VIEWER.md#disparo-de-varredura). A primeira
varredura baixa os modelos de IA uma única vez ([Primeira execução](INSTALLATION.md#primeira-execução-o-que-esperar)).

![Botão Escanear acima da galeria](../screenshots/getting-started-scan-button.jpg)

### Etapa 2: Encontrar duplicatas, sequências e fotos parecidas

O Facet agrupa sozinho frames de sequência, quase-duplicatas, brackets de exposição e
panorâmicas, e a galeria **oculta a maior parte de um conjunto por padrão**, para você ver
um representante. Se a contagem de fotos parecer menor que o esperado, são os alternadores
de ocultação, não arquivos ausentes — veja
[Opções de Exibição](VIEWER.md#opções-de-exibição) e [Filtros Padrão](VIEWER.md#filtros-padrão).
Para ver um conjunto inteiro lado a lado, abra [Fotos Semelhantes](VIEWER.md#fotos-semelhantes) ou a câmara escura de
[Triagem](VIEWER.md#triagem); os conjuntos que devem permanecer inteiros estão descritos em
[Panorâmicas e brackets de exposição](VIEWER.md#panorâmicas-e-brackets-de-exposição).

![Triagem de sequências](../screenshots/burst-culling.jpg)

### Etapa 3: Ensinar ao Facet qual você prefere

Cada escolha que você faz durante a triagem, e cada escolha A/B no modo de comparação, é um
sinal. O Facet aprende um ranking pessoal a partir deles e o expõe como **Meu gosto**
([Meu Gosto](VIEWER.md#meu-gosto)). Escolha "esta vence aquela" no
[Modo de Comparação Pareada](VIEWER.md#modo-de-comparação-pareada), ou simplesmente faça a triagem — a tela de
[Triagem](VIEWER.md#triagem) registra o que você mantém e rejeita. O ranker é retreinado
sozinho depois de escolhas novas suficientes, e só quando você faz uma pausa
([Re-treinamento automático](CONFIGURATION.md#re-treinamento-automático)).

![Comparando duas fotos](../screenshots/getting-started-teach.jpg)

### Etapa 4: Descartar o que você não quer

Rejeite fotos durante a triagem, ou selecione um conjunto e aja sobre ele
([Seleção Múltipla e Ações em Lote](VIEWER.md#seleção-múltipla-e-ações-em-lote)):
[Manter top %](VIEWER.md#manter-top-n), [Selecionar para pasta](VIEWER.md#selecionar-para-pasta) ou
[Excluir](VIEWER.md#excluir). Selecionar para pasta mostra uma simulação até você aplicar. Excluir envia os arquivos para
a lixeira do sistema na hora, e só quando `viewer.cull.allow_trash` está ativo (vem `false`).
[Desfazer](VIEWER.md#desfazer) cobre alterações de flags em lote e confirmações de triagem, não essas
operações de arquivo. As pastas nas quais uma seleção pode gravar formam uma lista de permissão: seus
diretórios de varredura mais `viewer.export.allowed_target_dirs`, então uma subpasta da árvore de fotos funciona sem
configuração, enquanto uma pasta fora dela é recusada até você adicioná-la. Veja
[Destinos de exportação e seleção](CONFIGURATION.md#destinos-de-exportação-e-seleção). Para fazer a triagem
sem interface: [Triar uma sessão pelo terminal](COMMANDS.md#triar-uma-sessão-pelo-terminal).

As fotos que você exclui fora do Facet deixam sua linha no banco de dados até você executar a limpeza em
[Database Maintenance](COMMANDS.md#database-maintenance).

![Ações em lote em uma seleção](../screenshots/getting-started-discard.jpg)

### Etapa 5: Adicionar tags e metadados às escolhidas

O Facet marca as fotos com tags automaticamente, e você também pode adicionar **suas próprias tags**: na
visualização de detalhe da foto, para uma foto, ou pelas ações em lote, para uma seleção. As tags manuais sobrevivem a novas varreduras,
o filtro de tags e a busca as encontram, e elas ficam ocultas nos links de compartilhamento. As palavras-chave de
sidecars XMP externos são importadas como tags manuais; remover uma tag no Facet não a remove
dos sidecars que o Facet já gravou. Veja [Tags manuais](VIEWER.md#tags-manuais) e
[Tags manuais e palavras-chave XMP](INTEROP.md#tags-manuais-e-palavras-chave-xmp). Para levar avaliações
e palavras-chave para o Lightroom, Capture One, digiKam ou darktable, veja [Interoperabilidade](INTEROP.md)
(isso exige o [exiftool](INSTALLATION.md#exiftool) para a incorporação).

![Tags manuais na vista de detalhe](../screenshots/getting-started-manual-tags.jpg)

### Etapa 6: Exportar o conjunto selecionado

Coloque suas escolhidas em um álbum e exporte a partir dele, ou use a
[Exportação para Editor](VIEWER.md#exportação-para-editor) para entregar a um editor, ou
[Selecionar para pasta](VIEWER.md#selecionar-para-pasta) para copiar as escolhidas para uma pasta. A
mesma lista de permissão de destinos da etapa 4 se aplica
([Destinos de exportação e seleção](CONFIGURATION.md#destinos-de-exportação-e-seleção)).

![Exportar para um editor](../screenshots/getting-started-export.jpg)

## Para onde ir depois

[Visualizador](VIEWER.md) para todos os recursos da galeria, [Comandos](COMMANDS.md) para o terminal,
[Pontuação](SCORING.md) para ajustar o que conta como uma boa foto, e
[Implantação](DEPLOYMENT.md) para um NAS ou um servidor compartilhado.
