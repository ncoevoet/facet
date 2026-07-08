# Receitas de Interoperabilidade com Editores

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · **Português**

Receitas práticas, passo a passo, para fazer as classificações, os rótulos e as tags do Facet irem e voltarem entre os editores externos e as ferramentas de gerenciamento de fotos (DAM) que os fotógrafos realmente usam. Esta página assume que você já sabe *que* o Facet grava XMP — veja [Comandos — Preview & Export](COMMANDS.md#preview--export) para a referência completa das opções `--export-sidecars` / `--import-sidecars` e o mapeamento de campos (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## A armadilha do nome dos sidecars RAW

O Facet nomeia um sidecar como `<imagem><ext>.xmp` — por exemplo, `IMG_1234.CR2.xmp` ao lado de `IMG_1234.CR2` — a mesma convenção usada pelo darktable e pelo digiKam. **O Lightroom Classic e o Capture One esperam o oposto: `IMG_1234.xmp`, sem a extensão RAW.** Nenhum dos dois vai descobrir um sidecar gravado pelo Facet para um arquivo RAW proprietário (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — tudo exceto DNG), e o `--import-sidecars` do Facet tampouco vai encontrar um sidecar que um aplicativo do ecossistema Adobe gravou para o mesmo RAW. É uma incompatibilidade de convenções de nome entre ecossistemas, não um defeito de nenhum dos lados.

Isso **não** afeta:
- **JPEG, HEIC, TIFF, PNG, DNG** — passe `--embed-originals` e o Facet grava os metadados *dentro do próprio arquivo* (via exiftool), então não há nome de sidecar para o Lightroom/Capture One deixarem de encontrar.
- **digiKam** — verifica as duas convenções de nome e encontra o sidecar do Facet de qualquer forma (veja [digiKam](#digikam) abaixo).
- **darktable** — usa a mesma convenção `<imagem><ext>.xmp` do Facet (veja [darktable](#darktable) abaixo).

Portanto, para um fluxo com Lightroom ou Capture One: use `--embed-originals` para tudo que não for RAW proprietário, e espere que a ida e volta por sidecar fique em silêncio (nenhum erro, apenas nada é lido) para arquivos RAW puros. Se você fotografa em RAW+JPEG, o JPEG companheiro é o veículo prático de interoperabilidade — o RAW permanece no disco, intocado, enquanto o banco de dados do Facet mantém a classificação que faz autoridade.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (adicione um caminho para limitar o escopo, por exemplo `--export-sidecars /fotos/casamento-2026`). Adicione `--embed-originals` para também gravar diretamente em arquivos JPEG/HEIC/TIFF/PNG/DNG.
2. No módulo Biblioteca do Lightroom Classic, selecione as fotos (Ctrl/Cmd+A para todas) e escolha **Metadados → Ler metadados do arquivo**. O Lightroom sobrescreve a classificação, o rótulo de cor e as palavras-chave do seu catálogo a partir do sidecar (ou dos metadados incorporados, para os formatos acima).

O marcador de rejeição do Facet (`xmp:Rating = -1`) é relido como o sinalizador de Rejeição do Lightroom. Um favorito do Facet grava `xmp:Label = Yellow`, que o Lightroom exibe como o **rótulo de cor Amarelo** — não como o sinalizador de Seleção (Pick). Se o seu fluxo no Lightroom depende dos sinalizadores Pick em vez dos rótulos de cor, adicione uma etapa de conversão rótulo-de-cor → pick, ou filtre pelo rótulo Amarelo.

### Lightroom → Facet

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

O digiKam lê sidecars XMP nativamente — nenhum exiftool é necessário do lado do digiKam — e ele procura pelas duas convenções de nome (`<imagem><ext>.xmp` primeiro, com `<imagem>.xmp` como reserva), então encontra os sidecars do Facet para arquivos RAW sem a armadilha acima. Depois de `python facet.py --export-sidecars`, abra (ou atualize) a pasta no digiKam: ele captura automaticamente a classificação, o rótulo de cor, as palavras-chave e as regiões de rosto nomeadas, desde que **Settings → Configure digiKam → Metadata → Read from sidecar files** esteja habilitado (o padrão).

### Gancho no Batch Queue Manager

Você pode encaixar uma reimportação do Facet em um fluxo do Batch Queue Manager (BQM) do digiKam com a ferramenta **Custom Script**, para que as fotos que você classifica ou rotula no digiKam voltem para o banco de dados do Facet sem sair do digiKam. Habilite **Settings → Configure digiKam → Metadata → Write to sidecar files** para que o digiKam persista suas edições imediatamente em `<imagem>.xmp`, e então adicione uma fila cuja única ferramenta seja o Custom Script:

```bash
#!/bin/bash
python /caminho/para/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` são os marcadores por arquivo do digiKam (o BQM executa o script via `/bin/bash` no Linux/macOS e espera um arquivo de saída, daí o repasse com `cp`). Como `--import-sidecars` varre a pasta inteira, executá-lo uma vez por foto em um lote grande é redundante, embora inofensivo (é idempotente — fotos sem alteração são puladas). Para lotes grandes, dispense o gancho do BQM e simplesmente execute `python facet.py --import-sidecars /caminho/da/pasta` uma vez, manualmente, depois que a fila terminar.

## darktable

O darktable já recebe tratamento de primeira classe em [Configuração — Viewer](CONFIGURATION.md#viewer) (perfis/estilos de exportação `viewer.raw_processor.darktable`) e [Visualizador — Download](VIEWER.md#endpoints-da-api) (conversões `type=darktable`). No lado do XMP: o darktable grava o seu próprio `<imagem>.xmp` para armazenar o histórico de edições, e o gravador de sidecar do Facet, apoiado no exiftool, mescla nesse mesmo arquivo no lugar — os nós `darktable:history`/máscaras são preservados, nunca sobrescritos. Nenhuma receita separada é necessária aqui: o comportamento bidirecional de sidecar descrito acima para o Lightroom (exportar/importar, o mais recente vence, união de tags) se aplica da mesma forma, sem a armadilha de nome RAW, já que darktable e Facet concordam em `<imagem><ext>.xmp`.

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
