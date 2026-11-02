# Referência de Comandos

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · **Português** · [简体中文](../zh/COMMANDS.md)

[Escaneamento](#scanning) · [Pré-visualização e Exportação](#preview--export) · [Operações de Recálculo](#recompute-operations) · [Reconhecimento Facial](#face-recognition) · [Gerenciamento de Miniaturas](#thumbnail-management) · [Diagnósticos](#diagnostics) · [Informações dos Modelos](#model-information) · [Otimização de Pesos](#weight-optimization-pairwise-comparison) · [Configuração](#configuration) · [Marcação](#tagging) · [Validação do Banco de Dados](#database-validation) · [Manutenção do Banco de Dados](#database-maintenance) · [Visualizador Web](#web-viewer) · [Fluxos de Trabalho Comuns](#common-workflows)

> Tags de requisito usadas abaixo: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (perfil de VRAM). Veja a [matriz de recursos](INSTALLATION.md#requisitos-por-recurso).

## Scanning

| Comando | Descrição |
|---------|-------------|
| `python facet.py /path` | Escaneia um diretório (multi-passo, detecção automática de VRAM) |
| `python facet.py /path --force` | Reescaneia arquivos já processados |
| `python facet.py /path --single-pass` | Carrega todos os modelos de uma vez; apenas `legacy`/`8gb` (veja [Modos de Processamento](#modos-de-processamento)) |
| `python facet.py /path --pass quality` | Executa apenas a pontuação de qualidade TOPIQ |
| `python facet.py /path --pass quality-iaa` | Executa apenas a pontuação de mérito estético TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Executa apenas a pontuação de qualidade TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Executa apenas o diagnóstico de qualidade + distorção LIQE |
| `python facet.py /path --pass tags` | Executa apenas a marcação (o modelo depende do perfil de VRAM) |
| `python facet.py /path --pass composition` | Executa apenas a detecção de padrão de composição SAMP-Net |
| `python facet.py /path --pass faces` | Executa apenas a detecção facial InsightFace |
| `python facet.py /path --pass embeddings` | Executa apenas a extração de embeddings CLIP/SigLIP (não grava tags) |
| `python facet.py /path --pass saliency` | Executa apenas a detecção de saliência do sujeito BiRefNet |
| `python facet.py /path --db custom.db` | Usa um arquivo de banco de dados personalizado |
| `python facet.py /path --config my.json` | Usa uma configuração de pontuação personalizada |
| `python facet.py --resume` | Retoma o último escaneamento interrompido, com falha ou travado |
| `python facet.py --retry-failed` | Reprocessa os arquivos que falharam no último escaneamento (`--retry-failed all` para todas as execuções) |
| `python facet.py /path --force-since 2026-01-01` | Como `--force`, apenas para fotos escaneadas pela última vez antes da data |
| `python facet.py /path --watch` | Reescaneia quando novas fotos aparecem (requer `pip install watchdog`; `--watch-debounce N`, padrão 30s) |
| `python facet.py /path --force-low-space` | Ignora a verificação de espaço livre antes do escaneamento |

**`--resume`** também recupera um escaneamento encerrado por uma queda, falta de memória ou falta de energia: uma execução ainda marcada como `running` cujo heartbeat é mais antigo que `processing.scan_stale_seconds` (padrão 120). Ele reutiliza os diretórios dessa execução. Com `--force`, ignora os arquivos já repontuados desde o início da execução. Recusa-se a iniciar se outro escaneamento parecer ativo.

### Registro de Escaneamento

O Facet registra cada escaneamento (estado, modo, diretórios, contadores) e cada erro por arquivo. Ctrl+C marca a execução como `interrupted`, para que `--resume` possa continuá-la. Os arquivos com falha são listados e reprocessados somente com `--retry-failed`. O visualizador mostra o progresso do escaneamento a partir das linhas `@FACET_PROGRESS` da CLI.

### Modos de Processamento

**Multi-passo (padrão):** detecta a VRAM e carrega os modelos um de cada vez. Cada passo carrega o seu modelo, processa todas as fotos e então o baixa, de modo que os modelos de alta qualidade rodam mesmo com pouca VRAM.

**Passo único (`--single-pass`):** carrega todos os modelos de uma vez. Mais rápido, mas exige mais VRAM.

- Pontua a estética com a cabeça CLIP+MLP, então se aplica aos perfis `legacy` e `8gb`.
- Em `16gb` e `24gb` o modelo estético é o TOPIQ, que só roda em multi-passo. Um pedido de passo único (`--single-pass` ou `processing.mode: "single-pass"`) registra um aviso e roda em multi-passo.
- `--pass NAME` e `--dry-run` pulam essa verificação.
- O modo comercial mantém o passo único, porque o Q-ReAlign nativo pontua a estética ali.

**Nota de atualização:** versões anteriores salvavam uma estética neutra de 5.0 para cada foto de um escaneamento de passo único em `16gb`/`24gb`. Reescaneie essas pastas com `--force` em multi-passo. Para encontrá-las: `SELECT path FROM photos WHERE scoring_model = 'topiq' AND aesthetic = 5.0 AND topiq_score IS NULL`.

**Passo específico (`--pass NAME`):** roda um único passo, para atualizar algumas métricas sem reprocessar tudo.

| Passo | Modelo | Saída | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | pontuação `aesthetic` (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` (mérito artístico, treinado no AVA) | Compartilhada com o TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` (qualidade do rosto) | Compartilhada com o TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + diagnóstico de distorção (desfoque, superexposição, ruído) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Tags semânticas do vocabulário configurado | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (8 padrões) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Rostos, pontos de referência, piscadas, embeddings de reconhecimento | ~2 GB |
| `embeddings` | CLIP ViT-L-14 ou SigLIP 2 NaFlex | `clip_embedding` para similaridade e marcação | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~3 GB |

As medições multipassagem usam relógios monotónicos. O tempo EXIF do lote e a soma dos segundos de trabalho das alternativas estão incluídos na descodificação; alternativas paralelas podem sobrepor-se. Agregação, miniaturas (incluindo leitura da origem) e gravação sem miniaturas são intervalos separados; gravar inclui preparação e commit. Passagens restritas omitem agregação e miniaturas de fotos. A sobreposição descodificação/modelos e as reconstruções aninhadas não mudam: não somar todos os tempos nem interpretar segundos de trabalho EXIF como percentagem do tempo total. O modo de passagem única fica excluído. Para uma referência, analisar uma cópia fixa de 500 RAW/JPEG numa base temporária e guardar resumo, revisão, perfil, workers, tamanho dos blocos, armazenamento e condições de cache. Repetir em condições idênticas. Não há coleção de referência nem benchmark antes/depois; não se afirma ganho de velocidade.

## Preview & Export

| Comando | Descrição |
|---------|-------------|
| `python facet.py /path --dry-run` | Pontua 10 fotos de amostra sem salvar |
| `python facet.py /path --dry-run --dry-run-count 20` | Pontua 20 fotos de amostra |
| `python facet.py --export-csv` | Exporta todas as pontuações para um CSV com data e hora |
| `python facet.py --export-csv output.csv` | Exporta para um arquivo CSV específico |
| `python facet.py --export-json` | Exporta todas as métricas armazenadas para um JSON com data e hora |
| `python facet.py --export-json output.json` | Exporta para um arquivo JSON específico |
| `python facet.py --export-manifest` | Grava `facet_manifest.json` para ferramentas externas como o plug-in do Lightroom Classic |
| `python facet.py --export-manifest /path` | Limita o manifesto às fotos sob um caminho |
| `python facet.py --export-manifest --user alice` | Modo multiusuário: usa as avaliações da Alice (tags e pontuações continuam globais) |
| `python facet.py --import-lightroom FILE` | Importa avaliações, escolhas e rejeições do plug-in; o Lightroom prevalece |
| `python facet.py --import-lightroom FILE --user alice` | Modo multiusuário: grava as avaliações da Alice; **obrigatório** em uma instalação multiusuário |
| `python facet.py --import-sidecars` | Importa avaliações, rótulos, Manter/Rejeitar, GPS manual e palavras-chave de sidecars XMP |
| `python facet.py --import-sidecars /path` | Importa apenas para fotos sob um caminho |
| `python facet.py --import-sidecars /path --dry-run` | Imprime um plano JSON de alterações e conflitos; não grava nada |
| `python facet.py --import-sidecars /path --sidecar-fields keywords,gps` | Importa apenas estes grupos: `review` (estrelas, favorito, rejeição, Manter), `gps`, `keywords` (padrão: todos) |
| `python facet.py --import-sidecars /path --overwrite-sidecar-review` | Aplica os campos de revisão mesmo sobre uma edição local mais recente (`newer_local_edit`); pré-visualize antes com `--dry-run` |
| `python facet.py --import-sidecars --user alice` | Modo multiusuário: importa avaliações e Manter/Rejeitar para a conta da Alice, nas fotos que ela vê |
| `python facet.py --import-sidecars --sidecar-naming full` | Lê `<image.ext>.xmp` / `<image.ext>.facet.xmp` (padrão); vence o arquivo mais recente |
| `python facet.py --import-sidecars --sidecar-naming basename` | Lê `<image>.xmp` (sem a extensão); recusa nomes-base compartilhados |
| `python facet.py --import-sidecars --sidecar-naming auto` | Aceita qualquer um dos nomes; ignora uma foto que tenha ambos |
| `python facet.py --import-sidecars --overwrite-manual-gps` | Substitui o GPS manual já definido no Facet pelo do sidecar |
| `python facet.py --export-sidecars` | Grava ou mescla sidecars `<image>.xmp` para todas as fotos |
| `python facet.py --export-sidecars /path --reconcile-keywords` | Remove também as palavras-chave do Facet que não existem mais (requer ExifTool) |
| `python facet.py --export-sidecars /path` | Exporta sidecars apenas para fotos sob um caminho |
| `python facet.py --export-sidecars --user alice` | Modo multiusuário: exporta avaliações e Manter/Rejeitar da Alice, nas fotos que ela vê |
| `python facet.py --export-sidecars --embed-originals` | Grava também metadados **dentro** dos originais JPEG/HEIC/TIFF/PNG/DNG |
| `python facet.py --export-sidecars --score-to-stars` | Define `xmp:Rating` a partir da pontuação nas fotos que você não avaliou |

**Simulação (dry run).** Em `16gb`/`24gb` a coluna de estética mostra `n/a`, porque o TOPIQ roda apenas em um escaneamento real (o modo comercial mostra a pontuação Q-ReAlign). O agregado a conta como um 5.0 neutro.

**CSV e JSON.** A coluna `tags` contém apenas tags de IA; as [tags manuais](VIEWER.md#tags-manuais) não são incluídas. No JSON, o objeto `scores` de cada foto contém todas as métricas armazenadas; NULL, números não finitos e BLOBs viram `null`. A exportação JSON se recusa a gravar sobre o banco de dados ou os seus arquivos `-wal`/`-shm`/`-journal`.

**Manifesto.**

- O argumento opcional limita *quais fotos* são exportadas. O arquivo é sempre `facet_manifest.json` no diretório de trabalho.
- Ele traz `star_rating`/`is_favorite`/`is_rejected` (globais, ou os do `--user`), `is_burst_lead`, tags de IA mais manuais e uma contagem `pending_corrections`. Uma contagem diferente de zero imprime um aviso que aponta para `--detect-panoramas`.
- _manifest version 2_ acrescenta `burst_group_id`, `sequence_kind`, `sequence_group_id` e `score_stars` (a pontuação mapeada por `xmp_export.score_to_rating`). Um plug-in construído para ele recusa um manifesto mais antigo: reexporte. Veja [o plug-in do Facet](INTEROP.md#o-plug-in-do-facet-classificações-por-estrelas-sinalizadores-pick-campos-de-metadados-e-palavras-chave).

**`--import-lightroom`** lê a exportação própria do plug-in, `facet_lightroom_state.json` (`{"format":"facet-lightroom-state","version":1,"photos":[...]}`), não o manifesto. Um arquivo no formato errado é recusado antes de qualquer gravação. O valor do Lightroom prevalece em todos os campos que o arquivo traz; os campos omitidos mantêm o valor do Facet. Imprime `matched=… unmatched=… changed=…`. Veja [Lightroom → Facet](INTEROP.md#lightroom--facet).

**Sincronização bidirecional de metadados.** O Facet grava avaliações, rótulos de cor, palavras-chave, legendas e regiões de rostos nomeados em um sidecar `<image>.xmp` padrão que Lightroom, darktable, digiKam, immich e outros leem.

- Os originais nunca são modificados, a menos que você adicione `--embed-originals` (apenas JPEG/HEIC/TIFF/PNG/DNG; o RAW nunca é tocado).
- As palavras-chave são as tags de IA mais as suas [tags manuais](VIEWER.md#tags-manuais). Elas só são acrescentadas, a menos que `--reconcile-keywords` remova as que o Facet gravou antes; as palavras-chave de terceiros são mantidas. Veja [Manual tags and XMP keywords](INTEROP.md#tags-manuais-e-palavras-chave-xmp).
- A incorporação e a fusão de palavras-chave exigem o **exiftool**. Sem ele, o Facet grava um sidecar XML simples.

**Importação de sidecar.**

- As palavras-chave importadas viram [tags manuais](INTEROP.md#tags-manuais-e-palavras-chave-xmp); não é preciso `--migrate-tags`.
- Uma decisão do Facet (Manter, Rejeitar ou sem decisão) sem avaliação ou rótulo padrão é aplicada sem a verificação do momento do escaneamento.
- Com `--user`, palavras-chave e GPS continuam globais. Com `--export-sidecars --user`, palavras-chave, GPS e data de captura continuam globais.
- Como um sidecar é pesado contra edições locais: [Sidecar import preview and review conflicts](INTEROP.md#prévia-de-importação-de-sidecars-e-conflitos-de-revisão).

### Sincronização com o Immich

Envie avaliações e favoritos do Facet a um servidor [Immich](https://immich.app/) (mão única, Facet → Immich, somente API REST). Os ativos são associados por `originalPath` através dos mapeamentos de prefixo de caminho do bloco de configuração `immich`.

| Comando | Descrição |
|---------|-------------|
| `python facet.py --immich-test` | Verifica a conexão e a chave de API (`immich.url` + `immich.api_key`, enviada como `x-api-key`) |
| `python facet.py --immich-sync` | Envia avaliações por estrelas (1–5) e favoritos; respeita `--dry-run` e `--user` |
| `python facet.py --immich-sync --dry-run` | Informa o que mudaria sem gravar |

Apenas as avaliações 1–5 são enviadas (nunca 0/−1). Um álbum opcional de melhores escolhas reúne as fotos acima de um limiar de avaliação. Veja [Configuração — Sincronização com o Immich](CONFIGURATION.md#immich-sync).

### Planos de pilhas Immich

Aceitam `--config`, `--db` e `--user`; o modo multiusuário exige um proprietário existente. A prévia nunca grava. Aplicar exige o digest do plano revisado.

| CLI | |
|---|---|
| `python facet.py --immich-stacks-plan import --stack-plan-out NEW_JSON` | Pré-visualiza as pilhas remotas para importação local |
| `python facet.py --immich-stacks-plan push --stack-id UUID --stack-plan-out NEW_JSON` | Pré-visualiza as pilhas locais para criação remota |
| `python facet.py --immich-stacks-apply PLAN_JSON --ack-stack-plan SHA256` | Aplica o plano revisado |

- Repita `--stack-id UUID` para escolher os grupos de origem.
- `--stack-plan-out NEW_JSON` grava um novo arquivo privado (POSIX `0600`) e nunca sobrescreve um existente. No Windows, escolha uma pasta cuja ACL restrinja o acesso à sua conta.
- Limites: 1000 grupos, 1000 membros por grupo, 20000 membros no total, 16 MiB.
- Mapeamentos incompletos e sobreposições ignoram o grupo inteiro. Os grupos existentes nunca são atualizados.

Veja [permissões, conflitos e limites de corrida remota](IMMICH.md#importar-e-enviar-pilhas-manuais).

## Recompute Operations

Estes comandos atualizam métricas ou derivam novos dados sem reexecutar todo o pipeline de pontuação. A maioria reutiliza miniaturas e pontos de referência armazenados e pesa pouco na CPU; as linhas de IA (como `--generate-captions`) exigem uma GPU.

| Comando | Descrição |
|---------|-------------|
| `python facet.py --recompute-average` | Recalcula pontuações agregadas e categorias a partir das métricas armazenadas (nenhuma imagem é relida) |
| `python facet.py --recompute-category portrait` | Recalcula as pontuações de uma única categoria |
| `python facet.py --tag-untagged` | Marca apenas as fotos ainda sem tags, a partir dos embeddings armazenados |
| `python facet.py --recompute-tags` | Remarca todas as fotos com o modelo configurado |
| `python facet.py --recompute-tags-vlm` | Remarca todas as fotos com o marcador VLM |
| `python facet.py --detect-moments` | Rotula as fotos novas com o seu momento narrativo (roda após cada escaneamento) |
| `python facet.py --recompute-moments` | Rotula de novo os momentos narrativos de toda a biblioteca |
| `python facet.py --discover-moments` | Propõe um vocabulário de momentos a partir das suas legendas em `scoring_config.discovered.json` |
| `python facet.py --detect-junk` | Sinaliza capturas de tela, documentos, recibos, memes e slides (roda após cada escaneamento) |
| `python facet.py --recompute-junk` | Reavalia `junk_kind` de toda a biblioteca |
| `python facet.py --recompute-saliency` | `[GPU]` Recalcula a saliência do sujeito a partir das miniaturas armazenadas; `--force` refaz tudo |
| `python facet.py --recompute-composition-cpu` | Recalcula a composição, baseada em regras (CPU, qualquer perfil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recalcula a composição com o SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` Preenche as pontuações TOPIQ IAA, NR-Face e LIQE ausentes a partir das miniaturas armazenadas. Roda em todos os perfis; na CPU (`legacy`) é bem mais lento |
| `python facet.py --detect-text` | Lê o texto presente nas imagens em `ocr_text` para que a busca o encontre (opcional, veja a nota) |
| `python facet.py --recompute-text` | Reexecuta o OCR em toda a biblioteca |
| `python facet.py --recompute-colors` | Extrai o matiz dominante e a temperatura quente/fria em `dominant_hue` / `color_temp` (CPU, rápido) |
| `python facet.py --recompute-form` | Recalcula simetria, equilíbrio, entropia de bordas, complexidade fractal e harmonia de cores (CPU) |
| `python facet.py --recompute-skin-tone` | Recalcula a naturalidade do tom de pele em retratos (CPU; apenas nota informativa da crítica) |
| `python facet.py --recompute-distortions` | Rotula distorções prováveis (desfoque de movimento, dominante de cor, …) e as correlaciona com `liqe_score` / `noise_sigma` (informativo) |
| `python facet.py --upgrade-db` | Migra o esquema e executa toda a cadeia de preenchimento retroativo (veja a nota) |
| `python facet.py --recompute-blinks` | Recalcula a detecção de piscadas a partir dos pontos de referência armazenados (CPU, rápido) |
| `python facet.py --recompute-eyes-expression` | Recalcula as pontuações de olhos abertos + expressão a partir dos pontos de referência armazenados (CPU, rápido) |
| `python facet.py --recompute-face-signals` | Preenche as pontuações de olhos abertos + sorriso por rosto a partir dos pontos de referência armazenados (CPU, rápido) |
| `python facet.py --recompute-burst` | Recalcula os grupos de rajada (registra `Burst state: N rows changed`) |
| `python facet.py --detect-sequences` | Detecta bracketings de exposição e panorâmicas (roda após cada escaneamento; veja a nota) |
| `python facet.py --detect-panoramas` | Detecta conjuntos de panorâmica a partir das miniaturas armazenadas (executa antes o passo de bracketing; CPU) |
| `python facet.py --detect-duplicates` | Detecta fotos duplicadas por pHash (registra `Duplicate state: N rows changed`) |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Avalia limiares de cosseno de quase-duplicatas (precisão/revocação com rótulos) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Gera legendas de IA com o VLM |
| `python facet.py --translate-captions` | Traduz as legendas em inglês para o idioma configurado (CPU, MarianMT) |
| `python facet.py --extract-gps` | Copia o GPS do EXIF para o banco de dados; ignora localizações definidas no visualizador |
| `python facet.py --rescan-gps` | Reextrai o GPS do EXIF de todas as fotos (sobrescreve); ignora localizações definidas no visualizador |
| `python facet.py --recompute-embeddings` | Recalcula os embeddings CLIP/SigLIP de todas as fotos (necessário após trocar de modelo) |
| `python facet.py --score-topiq` | `[GPU]` Repontua `topiq_score` de toda foto com miniatura (sobrescreve) |
| `python facet.py --backfill-focal-35mm` | Preenche a distância focal equivalente a 35 mm a partir do EXIF onde faltar |
| `python facet.py --backfill-clipping` | Deriva as porcentagens de clipping por canal a partir dos histogramas armazenados (retomável) |
| `python facet.py --recompute-silhouette` | Rederiva `is_silhouette` com a regra que considera rostos (veja a nota) |
| `python facet.py --repair-int-columns` | Arredonda valores fracionários que um gravador EXIF externo salvou em colunas inteiras (como ISO) |
| `python facet.py --repair-neutral-iqa` | Limpa as falsas pontuações IQA neutras de 5.0 armazenadas antes da 1.20 (veja a nota) |
| `python facet.py --compute-recommendations` | Analisa o banco de dados e mostra um resumo da pontuação |
| `python facet.py --compute-recommendations --verbose` | Mostra estatísticas detalhadas |
| `python facet.py --compute-recommendations --apply-recommendations` | Aplica automaticamente as correções de pontuação |
| `python facet.py --compute-recommendations --simulate` | Pré-visualiza as alterações projetadas |

**`--recompute-average`** não salva nenhum instantâneo: para reverter, restaure um snapshot de pesos e recalcule. Depois de atualizar da 1.20 ou anterior, execute primeiro `--recompute-silhouette` e depois `--recompute-average` duas vezes. A primeira passagem armazena novos percentis, então a segunda ainda altera algumas linhas.

**Momentos.**

- `--detect-moments` codifica cada legenda nova uma vez em `caption_embedding`. O primeiro preenchimento de uma biblioteca existente é melhor em uma GPU; acrescente `--limit N` para experimentar em uma amostra.
- Acrescente `--dry-run --verbose` a `--recompute-moments` (ou `--detect-junk`) para pré-visualizar sem gravar.
- `narrative_moments.vlm_tiebreak` (16gb/24gb): quando `narrative_moments.vlm_tiebreak.enabled` está definido, o VLM do perfil reclassifica os quadros de baixa confiança.
- `--discover-moments` agrupa os embeddings de legenda armazenados e dá nome a cada grupo. Nunca reescreve a configuração ativa. Execute antes `--detect-moments`; ajuste com `--discover-min-cluster-size N`.
- `--generate-captions` ignora fotos sem rótulo, `other` e de baixa confiança quando `narrative_moments.caption_min_confidence > 0`.

**Lixo.** As fotos limpas são marcadas `not_junk`, então as execuções seguintes verificam apenas as novas.

**`--detect-text`** é opcional: exige `ocr.enabled` no `scoring_config.json` e `pip install easyocr`. Veja [Configuração — OCR](CONFIGURATION.md#ocr).

**`--detect-sequences`** encontra bracketings de exposição pelo EXIF, depois panorâmicas pela geometria das miniaturas, e move o líder de cada rajada para a sua exposição base. Também roda em `--upgrade-db`. As visões de triagem **Bracketings de exposição** / **Panoramas** / **Panoramas HDR** do visualizador e os alternadores `hide_brackets` / `hide_panoramas` não fazem nada até ele rodar. Cada execução rotula de novo toda a biblioteca, então rodá-lo de novo (ou `--detect-panoramas`) escolhe um novo quadro representativo depois que você faz a triagem do antigo.

**`--upgrade-db`** migra o esquema e executa: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, eyes-expression, face-signals, average. É seguro rodar de novo e pula passos pesados como a legendagem. Também endireita as miniaturas HEIF deixadas de lado pelo pillow-heif 1.6, com os seus rostos; os arquivos originais nunca são gravados. Os arquivos HEIF que ele não consegue ler são tentados de novo na execução seguinte.

**`--recompute-silhouette`** lê apenas o banco de dados, faz commit por lote e respeita `--dry-run`.

- O relatório agrupa as fotos conforme a correspondência das caixas de rostos com a miniatura: `exact`, `scaled`, `count_mismatch` (correspondência não validada), `other`.
- Uma foto sem rostos, ou cujas caixas não podem ser posicionadas, é definida como 0.
- Fotos com `face_count` NULL, ou com rostos mas sem miniatura, são deixadas em paz (`skipped_face_count_null` / `skipped_no_thumbnail`).
- Execute `--recompute-average` depois. Veja [SCORING.md](SCORING.md).

**`--repair-int-columns`** lê apenas o banco de dados. A galeria os mostra corretamente sem ele, mas filtros de intervalo e ordenações usam o valor armazenado, então uma foto mostrada como ISO 63 pode ser perdida. Valores que não podem ser inteiros viram NULL.

**`--repair-neutral-iqa`** define como NULL todo valor exatamente 5.0 em `aesthetic_iaa`, `face_quality_iqa` e `liqe_score`, e imprime a contagem por coluna.

- Deixa em paz `aesthetic`, `topiq_score`, `aesthetic_v25` e `quality_score`.
- Uma pontuação real de exatamente 5.00 também é limpa; `--recompute-iqa` a preenche de novo, possivelmente um pouco diferente.
- Depois, execute `--recompute-iqa` e `--recompute-average`.
- Recusado com `--dry-run` (código de saída 2). Não faz parte de `--upgrade-db`. Recarregue as páginas abertas da galeria para ver os novos intervalos de filtro.

### Modelos de Qualidade Suplementares

Três modelos PyIQA pontuam além da estética principal do TOPIQ. Compartilham VRAM com o TOPIQ e rodam no escaneamento multi-passo padrão.

- **TOPIQ IAA** (`--pass quality-iaa`): mérito artístico treinado no AVA, separado da qualidade técnica. Armazenado como `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): qualidade da região do rosto. Armazenado como `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): pontuação de qualidade mais um diagnóstico de distorção (desfoque de movimento, superexposição, ruído). Armazenado como `liqe_score`.

Quando um modelo não consegue pontuar uma foto:

- Armazena NULL, não um 5.0 neutro. Um erro de falta de memória da GPU é tentado de novo primeiro com metade do tamanho do lote, até uma imagem.
- O LIQE ignora miniaturas cujo lado menor tem menos de 224 px (após limitar o lado maior a 1024 px).
- O NR-Face ignora fotos com `face_count` 0. Uma foto em que ele não encontra rosto é lembrada em `iqa_declined` até um novo escaneamento (`--force`), `--refresh-thumbnails` ou `--fix-thumbnail-rotation`. Atualizar o pyiqa não a limpa.
- Outras falhas não são armazenadas; o próximo `--recompute-iqa` tenta de novo.
- Em `--pass quality`, `quality-iaa`, `quality-face` e `quality-liqe`, uma foto que falha mantém o valor armazenado.
- Um escaneamento completo registra uma foto cujo modelo TOPIQ falha, para `--retry-failed`; `--pass quality` não.

`--recompute-iqa` preenche apenas colunas NULL e nunca substitui um valor armazenado, inclusive um 5.0 neutro de uma versão anterior. Limpe-os com `--repair-neutral-iqa`, depois execute `--recompute-iqa` e `--recompute-average`, ou reescaneie com `--force`. Veja [Supplementary IQA Dimensions](SCORING.md#dimensões-suplementares-de-iqa).

### Benchmarks e pontuações suplementares

| Comando | Descrição |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Preenche `aesthetic_clip` a partir dos embeddings em cache (sem inferência de imagem; fora do `aggregate` padrão). Veja [SCORING.md](SCORING.md#sinais-suplementares-não-no-agregado-padrão) |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcula SRCC + PLCC contra a verdade de referência do AVA para toda coluna de pontuação |

### Saliência do Sujeito

`--pass saliency` e `--recompute-saliency` usam o BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, via `transformers`, ~3 GB de VRAM) para encontrar o sujeito e então derivam quatro métricas:

- **Nitidez do Sujeito**: o sujeito está em foco (variância do Laplaciano, sujeito vs fundo).
- **Proeminência do Sujeito**: área do sujeito / área do quadro. Alta para um sujeito dominante (por exemplo, macro).
- **Posicionamento do Sujeito**: pontuação da regra dos terços para o centroide do sujeito.
- **Separação do Fundo**: contraste de bordas entre sujeito e fundo (qualidade do bokeh).

A saliência roda em todos os perfis; `legacy` a roda na CPU, mais lento. `--recompute-saliency` funciona com o volume da biblioteca offline e é retomável. Em CUDA, o tamanho do lote acompanha a VRAM livre (cerca de 2,4 GiB por imagem a 1024 px, 1 a 8 imagens) e cai pela metade após um erro de falta de memória.

- **Uma foto com falha** é registrada como ERROR e nada é gravado. Uma foto nunca pontuada continua NULL e é pega pelo próximo `--recompute-saliency`; uma que já tinha saliência mantém os seus valores, mesmo com `--recompute-saliency --force`. Um novo escaneamento completo (por exemplo, `python facet.py --force`) grava NULL para ela.
- **Uma foto sem sujeito** grava nitidez, posicionamento e separação NULL, proeminência 0.0 e `subject_bbox` NULL (e `power_point_score` NULL, do passo de composição). Isso é definitivo; não é medido de novo.
- **Linhas antigas** gravavam um 5.0 neutro. `--recompute-saliency` e `--recompute-composition-cpu` as reescrevem. `--recompute-saliency` também pega fotos pontuadas antes de `subject_bbox` existir.
- Uma métrica opcional NULL é excluída do agregado e o seu peso é redistribuído pelas métricas presentes; só se faltarem todas, o agregado usa o valor neutro 5.0. Veja [Sistema de Pontuação](SCORING.md).

### Modelos de Marcação

O modelo de marcação depende do perfil de VRAM:

| Perfil | Modelo | Como funciona |
|---------|-------|-------------|
| `legacy` | Similaridade CLIP | Similaridade de cosseno entre os embeddings da imagem e do texto das tags. Nenhum modelo extra. |
| `8gb` | Similaridade CLIP | Igual ao legacy, sobre os embeddings CLIP ViT-L-14 armazenados. |
| `16gb` | Qwen3.5-2B | Modelo multimodal para marcação de cenas. |
| `24gb` | Qwen3.5-4B | Modelo multimodal maior. |

Todos os marcadores mapeiam a sua saída para o vocabulário de tags configurado. Use `--recompute-tags` para remarcar com o modelo do perfil, ou `--recompute-tags-vlm` para o VLM.

**Quando as tags são gravadas.** Nos perfis de similaridade CLIP (`legacy`/`8gb`, e `16gb`/`24gb` quando o passo VLM não está agendado), um escaneamento multi-passo marca durante o passo de embeddings, então a categoria e o agregado do escaneamento já as usam. Uma execução com um único `--pass` (por exemplo `--pass embeddings`) não grava tags. `--pass tags` em um perfil CLIP para e aponta para `--recompute-tags`. As linhas existentes mantêm a categoria até `--recompute-average`.

### Modelos de Embedding

Dois modelos de embedding, selecionados por perfil de VRAM via `clip_config`:

| Config | Modelo | Dimensões | Usado por |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | Perfis 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | Perfis legacy, 8gb |

Os embeddings alimentam a marcação, a detecção de duplicatas, a busca de fotos semelhantes e a estética CLIP+MLP (legacy/8gb). Trocar de modelo exige recalcular os embeddings de todas as fotos (`--force`, `--pass embeddings` ou `--recompute-embeddings`).

## Face Recognition

| Comando | Descrição |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extrai rostos das fotos novas (GPU, paralelo) |
| `python facet.py --extract-faces-gpu-force` | Exclui todos os rostos e reextrai (GPU; as pessoas nomeadas são mantidas; extrator permissivo no modo comercial) |
| `python facet.py --cluster-faces-incremental` | Agrupamento HDBSCAN, mantém todas as pessoas (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Agrupamento, mantém apenas as pessoas nomeadas (CPU) |
| `python facet.py --cluster-faces-force` | Reagrupamento completo, exclui todas as pessoas (CPU) |
| `python facet.py --suggest-person-merges` | Sugere possíveis mesclagens de pessoas |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Usa um limiar mais rigoroso |
| `python facet.py --refill-face-thumbnails-incremental` | Gera as miniaturas de rostos que faltam (CPU, paralelo) |
| `python facet.py --refill-face-thumbnails-force` | Regenera TODAS as miniaturas de rostos (CPU, paralelo) |

## Thumbnail Management

| Comando | Descrição |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Gira as miniaturas armazenadas para coincidir com a orientação EXIF |
| `python facet.py --refresh-thumbnails` | Reconstrói as miniaturas RAW a partir da pré-visualização embutida na câmera |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | Igual, com mais leituras em paralelo |

**`--fix-thumbnail-rotation`** é para fotos processadas antes de a orientação EXIF ser tratada. Lê apenas o cabeçalho EXIF e a miniatura armazenada.

**`--refresh-thumbnails`** renderiza de novo a miniatura armazenada de toda foto RAW pelo perfil de exibição (primeiro a pré-visualização da câmera, demosaico como alternativa; veja [CONFIGURATION.md](CONFIGURATION.md#decodificação-raw)). Use-o em uma biblioteca escaneada antes de esse perfil existir: as miniaturas antigas achatam as diferenças de exposição entre quadros de bracketing. Não carrega nenhum modelo e não altera nenhuma pontuação.

- A **velocidade** depende da vazão do disco ou da rede, não da CPU. `--refresh-thumbnails-workers` (padrão 8) define quantos arquivos são lidos ao mesmo tempo: aumente em um compartilhamento de rede rápido, diminua em um disco local lento. Valores muito altos custam memória.
- **Retomável.** Interrompa com Ctrl-C e a próxima execução continua de onde parou. Uma execução concluída recomeça do zero na vez seguinte.
- As **renderizações pretas** (por exemplo, de um RAW truncado) são descartadas: a foto mantém a miniatura antiga, é registrada pelo nome e é tentada de novo na próxima execução.
- Os **quadros de bracketing** são renderizados sem a pré-visualização da câmera nem ganho de exposição, de modo que cada bloco mostra o que o sensor registrou (veja [CONFIGURATION.md](CONFIGURATION.md#quadros-de-bracketing-são-renderizados-sem-correção)). Execute-o depois de `--detect-sequences`.

### O que atualiza uma miniatura armazenada

As miniaturas são feitas no momento do escaneamento, então uma biblioteca escaneada antes de o perfil de exibição existir mantém a renderização antiga na grade da galeria. Duas coisas as atualizam:

| Caminho | Cobre | Custo |
|------|--------|------|
| Um novo escaneamento (`python facet.py <dir>`) | Tudo o que ele escaneia, miniatura e histograma | Execução completa de pontuação |
| `--refresh-thumbnails` | A miniatura de toda linha RAW | Limitado pelo armazenamento, horas em uma biblioteca grande |

**Nada acontece por conta própria.** A visão de detalhe sempre renderiza do zero, mas a grade da galeria mostra a miniatura armazenada. Um banner dispensável conta as linhas ainda pendentes. A contagem pode atrasar até uma hora após um novo escaneamento; `--refresh-thumbnails` e `python database.py --refresh-stats` a atualizam.

## Diagnostics

| Comando | Descrição |
|---------|-------------|
| `python facet.py --doctor` | Executa verificações de diagnóstico (Python, GPU, ONNX Runtime, dependências, configuração, banco de dados) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simula hardware de GPU para o diagnóstico |

`--doctor` informa a versão do Python, a versão do PyTorch/CUDA, a GPU e o driver, a versão e os provedores do ONNX Runtime, o perfil de VRAM recomendado, as dependências opcionais e o estado da configuração/banco de dados. Em CUDA, ele também testa o carregamento do ONNX Runtime na GPU. Quando o PyTorch ou o ONNX Runtime é a versão errada, imprime o comando `pip install` que a corrige (veja [ONNX Runtime for face detection](INSTALLATION.md#onnx-runtime-para-detecção-de-faces)).

`--simulate-gpu NAME` e `--simulate-vram GB` exigem `--doctor`; `--simulate-vram` exige também `--simulate-gpu`.

| Comando | Descrição |
|---------|-------------|
| `python facet.py --check-raw-rendering` | Renderiza 20 fotos RAW amostradas com a configuração de decodificação antiga e a atual |
| `python facet.py --check-raw-rendering 50` | Amostra 50 fotos em vez disso |

Somente leitura. Imprime o brilho médio de cada renderização: o auto-brilho do LibRaw, o demosaico de ganho fixo e a pré-visualização da câmera. Use-o para conferir `raw_decode.bright` nos seus arquivos antes de um escaneamento ou de `--refresh-thumbnails`. As colunas de ganho fixo e de pré-visualização preservam os passos de exposição de um bracketing; o auto-brilho os achata.

## Model Information

| Comando | Descrição |
|---------|-------------|
| `python facet.py --list-models` | Mostra os modelos disponíveis e os requisitos de VRAM |

## Weight Optimization (Pairwise Comparison)

| Comando | Descrição |
|---------|-------------|
| `python facet.py --comparison-stats` | Mostra estatísticas das comparações pareadas |
| `python facet.py --optimize-weights` | Otimiza os pesos a partir das suas comparações; aplicados só se passarem em um teste com dados retidos (veja a nota) |
| `python facet.py --optimize-weights --optimize-force` | Aplica os pesos otimizados mesmo que falhem no teste |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Treina apenas com estas fontes de comparação |
| `python facet.py --optimize-weights --optimize-category portrait` | Treina uma categoria e grava o seu bloco v4 `categories[].weights` |
| `python facet.py --auto-tune-categories` | **Somente superadmin** (`--user` no modo multiusuário): informa a prontidão de rótulos por categoria (apenas relatório) |
| `python facet.py --sync-label-comparisons` | Reconstrói os pares derivados de avaliações (source=rating) a partir de estrelas, favoritos e rejeições |
| `python facet.py --train-ranker` | Treina o ranqueador pessoal e grava learned_scores se superar o agregado |
| `python facet.py --train-ranker --ranker-category portrait` | Treina o ranqueador em uma única categoria |
| `python facet.py --train-ranker --train-ranker-force` | Grava learned_scores mesmo que o limite de precisão falhe |
| `python facet.py --train-ranker --user alice` | Treina com as comparações desse usuário e grava os seus learned_scores (modo multiusuário) |
| `python facet.py --train-keeper` | Treina a **cabeça de classificação de fotos mantidas** a partir das suas decisões de triagem (veja a nota) |
| `python facet.py --train-keeper --train-keeper-force` | Mantém a cabeça mesmo que o seu limite falhe (também respeita `--ranker-category` e `--user`) |
| `python facet.py --report-unreviewed-bursts` | Conta os grupos de rajada ainda não revisados (somente leitura) |
| `python facet.py --eval-iqa-srcc` | Informa o quanto cada métrica IQA/estética coincide com as suas avaliações por estrelas (SRCC; somente leitura) |
| `python facet.py --evaluate-models SLOT` | Classifica modelos candidatos de um slot pela concordância com as suas escolhas (somente leitura; veja a nota) |
| `python facet.py --mine-insights` | Relatório sobre rótulos, correlações de métricas, categorias, deriva de percentis e comparações |
| `python facet.py --mine-insights report.json` | Igual, e grava o relatório completo em JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Calibra os pesos das categorias contra o [conjunto de dados AVA](https://github.com/imfing/ava_downloader) (somente leitura; imprime propostas) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Limita a estas categorias e grava os pesos no `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Escolhe o otimizador (`de` = evolução diferencial, padrão; `nelder-mead` = simplex local) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Usa também as tags do AVA (`--ava-tags-only` só para tags; `--apply-filters` para ajustar limiares de filtros) |

**`--optimize-weights`** treina com todas as fontes de comparação, ponderadas pela confiabilidade. Os novos pesos só são aplicados se superarem os atuais em comparações retidas (validação cruzada de 5 partes, teste de McNemar unilateral, p < 0.05, ganho de pelo menos 2 pontos percentuais). Aplicar também recentraliza o `modifiers.bonus` da categoria, de modo que as suas fotos são reordenadas em vez de todas deslocadas. Veja [SCORING.md](SCORING.md).

**`--train-keeper`** aprende com os pares `source='culling'` e só é mantido se superar a heurística da seleção automática em dados retidos. Ele alimenta as escolhas da seleção automática e o emblema "existe uma foto melhor neste grupo". Enquanto não há pares de triagem suficientes, a heurística é usada. Retreina sob o mesmo gatilho de `--train-ranker`.

**`--evaluate-models SLOT`** slots: `aesthetic`, `quality`, `faces-detect`, `faces-recognize`, `faces-centroid`, `blink`, `face-quality`, `end-to-end`.

- `--candidates a,b` escolhe os candidatos (`stored:<column>` ou um nome registrado).
- `--eval-out PATH` define a saída (padrão `.facet_cache/eval/<slot>-<timestamp>.json`).
- Os slots de rostos comparam com os rostos InsightFace armazenados em vez das suas escolhas, então servem apenas para bibliotecas em modo padrão: `faces-detect` (`yunet`, `yunet@<conf>`, `blazeface`), `faces-recognize` (`sface`, `sface@<threshold>`), `faces-centroid` (ajusta o `merge_threshold` do SFace / a mesclagem automática), `blink` (varre o limiar permissivo de piscada).
- `--limit N` limita as fotos (padrão 600) ou os rostos de referência (padrão 1200).

## Configuration

O `scoring_config.json` é um **override**: contém apenas as configurações que você alterou, sobre `config/scoring_config.default.json`. Sem arquivo de configuração, o Facet roda com os padrões. Veja [Configuração](CONFIGURATION.md#padrões-e-seu-override).

Qual arquivo é lido:

1. `--config` sempre vence.
2. Senão `FACET_CONFIG`, se definida. Aplica-se a `facet.py`, `database.py`, `tag_existing.py`, `diagnostics.py`, `calibrate.py` e `viewer.py`. O `viewer.py` não tem `--config`, então esta é a sua única forma de override.
3. Senão, para as ferramentas CLI (não o `viewer.py`), um `scoring_config.json` no **diretório de trabalho**, para que uma biblioteca possa carregar a sua própria configuração.
4. Senão o arquivo ao lado da instalação. Se ele não existir, valem os padrões distribuídos.

Um caminho nomeado por `--config` ou `FACET_CONFIG` que não existe é um erro, não "usar os padrões". O visualizador registra o caminho ausente e se recusa a iniciar em modo aberto.

> **Aviso:** o `viewer.py` nunca lê um `scoring_config.json` do diretório em que você o inicia. Se você o inicia a partir de uma biblioteca e a raiz da instalação não tem configuração, ele roda com os padrões: um `viewer.edition_password` vazio e nenhuma senha do visualizador, de modo que qualquer pessoa pode navegar.

```bash
# 1. --config vence sobre tudo. Um arquivo ausente é um erro.
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. $FACET_CONFIG fornece o padrão quando --config é omitido (o Docker define isso).
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # lê /config/scoring_config.json
python facet.py --config other.json /photos   # --config ainda o sobrepõe

# 3. Nenhum dos dois: uma configuração no DIRETÓRIO DE TRABALHO vence para as ferramentas CLI.
cd /photos/client-shoot          # tem o seu próprio scoring_config.json
python /opt/facet/facet.py .     # pontuado por /photos/client-shoot/scoring_config.json

# 4. Nenhum dos dois e nada aqui: recai na configuração ao lado da instalação.
cd /tmp
python /opt/facet/facet.py /photos   # lê /opt/facet/scoring_config.json
                                     # ausente ali = roda com os padrões distribuídos

# 5. O viewer.py nunca faz a etapa do diretório de trabalho.
cd /photos/client-shoot          # tem o seu próprio scoring_config.json -- irrelevante aqui
python /opt/facet/viewer.py      # ainda lê /opt/facet/scoring_config.json (ou $FACET_CONFIG)
```

| Comando | Descrição |
|---------|-------------|
| `python facet.py --validate-categories` | Valida as configurações de categoria |

## Tagging

| Comando | Descrição |
|---------|-------------|
| `python tag_existing.py` | Marca as fotos sem tags a partir dos embeddings CLIP armazenados |
| `python tag_existing.py --dry-run` | Pré-visualiza as tags sem salvar |
| `python tag_existing.py --threshold 0.25` | Limiar de similaridade personalizado (padrão: o `tag_threshold_percent` do perfil, distribuído como 8, ou seja 0.08) |
| `python tag_existing.py --max-tags 3` | Limita as tags por foto (padrão: 5) |
| `python tag_existing.py --force` | Remarca todas as fotos |
| `python tag_existing.py --db custom.db` | Usa um banco de dados personalizado |
| `python tag_existing.py --config my.json` | Usa uma configuração personalizada |

Em CUDA, os perfis SigLIP (`16gb`, `24gb`) agora codificam o vocabulário de tags em fp16, o que altera as tags de algumas fotos. Execute `python tag_existing.py --force` para remarcar as fotos marcadas antes. A CPU e os perfis `legacy`/`8gb` não mudam.

O passo de marcação ao fim de um escaneamento é pulado quando `tagging.enabled` é `false` ou nenhuma foto aguarda tags.

## Database Validation

| Comando | Descrição |
|---------|-------------|
| `python validate_db.py` | Valida a consistência do banco de dados (interativo) |
| `python validate_db.py --auto-fix` | Corrige todos os problemas automaticamente |
| `python validate_db.py --report-only` | Relata sem perguntar |
| `python validate_db.py --db custom.db` | Valida um banco de dados personalizado |

Verificações: intervalos de pontuação, métricas de rostos, corrupção de BLOB, tamanhos de embeddings, rostos órfãos, valores atípicos estatísticos.

## Database Maintenance

| Comando | Descrição |
|---------|-------------|
| `python database.py` | Inicializa ou atualiza o esquema e cria os índices que faltam (veja a nota) |
| `python database.py --info` | Mostra informações do esquema |
| `python database.py --migrate-tags` | Configuração única da tabela de consulta de tags (filtros de tags 10-50x mais rápidos) |
| `python database.py --rebuild-fts` | Reconstrói o índice de busca de texto completo a partir de legendas e tags |
| `python database.py --populate-vec` | Preenche a tabela de busca vetorial sqlite-vec a partir dos embeddings |
| `python database.py --refresh-stats` | Atualiza o cache de estatísticas |
| `python database.py --compact-config` | Remove do `scoring_config.json` todo valor igual ao padrão distribuído (faz antes um backup `0600`) |
| `python database.py --stats-info` | Mostra o estado e a idade do cache |
| `python database.py --vacuum` | Recupera espaço, desfragmenta |
| `python database.py --analyze` | Atualiza as estatísticas do planejador de consultas |
| `python database.py --optimize` | Executa VACUUM e ANALYZE |
| `python database.py --backup` | Grava um snapshot com data e hora, seguro com WAL (mantém `--keep N`, padrão 3) |
| `python database.py --export-viewer-db` | Exporta um banco de dados leve para o visualizador (sem BLOBs, miniaturas menores; incremental) |
| `python database.py --export-viewer-db --force-export` | Força uma reexportação completa |
| `python database.py --cleanup-orphaned-persons` | Remove pessoas sem rostos |
| `python database.py --cleanup-missing-photos` | Remove fotos que não estão mais no disco, com as suas tags, rostos e entradas de álbum |
| `python database.py --cleanup-missing-photos --dry-run` | Lista os arquivos ausentes sem excluir |
| `python database.py --cleanup-missing-photos --force` | Prossegue mesmo quando todas as fotos parecem ausentes (veja o aviso) |
| `python database.py --relink-photos` | Atualiza os caminhos de fotos que você mesmo moveu (pré-visualização por padrão). Veja [Religar fotos movidas](#religar-fotos-movidas) |
| `python database.py --migrate-storage-fs` | Move miniaturas e embeddings do banco de dados para o sistema de arquivos |
| `python database.py --migrate-storage-db` | Move miniaturas e embeddings do sistema de arquivos de volta para o banco de dados |
| `python database.py --add-user alice --role admin` | Adiciona um usuário (pede a senha) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Adiciona um usuário com um nome de exibição |
| `python database.py --migrate-user-preferences --user alice` | Copia as avaliações das fotos para user_preferences |

**`python database.py`** também cria os índices da galeria que faltam (veja [VIEWER.md](VIEWER.md#índices-da-galeria-e-cache-de-contagem)). Em uma biblioteca grande, execute-o uma vez antes de iniciar o visualizador; pode levar cerca de um minuto. Caso contrário, o visualizador os cria em segundo plano e recusa gravações nesse meio-tempo.

**`--migrate-tags`** é necessário uma vez. Depois, escaneamentos, `--recompute-tags`, `--recompute-tags-vlm` e `tag_existing.py` mantêm a tabela atualizada. Enquanto ela não está preenchida, os filtros de tags usam uma busca `LIKE` mais lenta.

**`--cleanup-missing-photos`** também limpa o índice vetorial e zera os contadores de comparação do retreinamento automático. O estado da biblioteca, como modelos treinados, o estado da sincronização com o Immich e o instantâneo de percentis, é mantido.

> **Aviso:** sem `--force`, `--cleanup-missing-photos` para quando todas as fotos parecem ausentes, o que geralmente significa que um volume está desmontado. Confira a montagem antes de acrescentar `--force`.

**Dica de desempenho:** para bancos de dados grandes (50k+ fotos), execute `--migrate-tags`, `--rebuild-fts` e `--populate-vec` uma vez, depois `--optimize` de tempos em tempos.

## Web Viewer

| Comando | Descrição |
|---------|-------------|
| `python viewer.py` | Inicia o servidor em http://localhost:5000 (API + SPA Angular) |
| `python viewer.py --port 5001` | Usa outra porta (ou defina a variável de ambiente `PORT`; padrão 5000) |
| `python viewer.py --host 127.0.0.1` | Associa-se a uma interface específica (padrão `0.0.0.0`) |
| `python viewer.py --production` | Modo de produção (workers do uvicorn) |
| `python viewer.py --production --workers 4` | Modo de produção com N workers (padrão 1) |

## Triagem pelo terminal

Seleção automática sem interface: a versão de terminal da [Seleção automática](VIEWER.md#seleção-automática) do visualizador. As rejeições são gravadas no banco de dados. Os originais nunca são movidos nem excluídos; `--copy-keepers` copia os sobreviventes para uma pasta.

| Comando | Descrição |
|---------|-------------|
| `python facet.py --auto-cull [PATH]` | Faz a triagem das fotos já no banco de dados sob `PATH` (pasta ou arquivo; nada ou `all` = biblioteca inteira). **Simulação por padrão** |
| `python facet.py /path --auto-cull` | Escaneia `/path` e depois faz a triagem das fotos sob ele |
| `--apply` | Grava a triagem: rejeições, marcas de grupos revisados e pares de comparação `source='culling'` |
| `--copy-keepers DIR` | Copia para `DIR` toda foto não rejeitada do escopo, com o seu RAW / `.xmp` de mesmo nome-base |
| `--cull-strictness N` | Orçamento de fotos mantidas 0–100, mais alto mantém menos por grupo (padrão: `auto_cull.default_strictness`) |
| `--cull-min-keep N` | Mínimo de fotos mantidas por grupo (padrão `1`) |
| `--cull-group-by {all,burst,similar,scene}` | Quais grupos triar (padrão `all`) |
| `--cull-min-score X` | Rejeita também as fotos avulsas com pontuação agregada abaixo de `X` |
| `--cull-trim-brackets` | Rejeita também os quadros redundantes de bracketing de exposição (o `trim_brackets` do visualizador) |
| `--user NAME` | De quem usar as avaliações e rejeições; **obrigatório** em uma instalação multiusuário |

- **Simulação.** Sem `--apply` nada é gravado e a pasta de `--copy-keepers` não é criada. O resumo lista `groups`, `kept`, `rejected_by_groups`, `rejected_by_score`, `spanning_skipped` e, com `--copy-keepers`, `keepers`, `copied`, `already_present`, `skipped`, `errors` (`would_reject_*` / `would_copy` em uma simulação). O próprio `--dry-run` é recusado. Se um modelo de fotos mantidas treinado precisar ter os pesos corrigidos, carregá-lo ainda pode reescrever o `scoring_config.json`.
- **Escanear e depois triar** sempre escaneia de verdade; a triagem só roda se o escaneamento terminou. Não pode ser combinado com `--auto-cull PATH`, `--resume`, `--retry-failed` nem `--watch`.
- **Regras.** As mesmas da [Seleção automática do visualizador](VIEWER.md#seleção-automática): cada grupo mantém a sua melhor foto mais todas as que estão dentro da margem de rigor, no mínimo `--cull-min-keep`. Bracketings, panorâmicas e panorâmicas HDR são mantidos inteiros. `--apply` marca as fotos mantidas como **Mantida** e registra pares de comparação como faz `POST /api/culling/auto`; nenhum álbum de Destaques é preenchido.
- **Configuração.** As configurações [`auto_cull`](CONFIGURATION.md#auto-cull), `burst_scoring` e `similarity_groups` vêm da configuração do **servidor** (`FACET_CONFIG` ou o caminho padrão), não de `--config`. Se as duas discordarem no modo multiusuário, ele sai com 1.
- O **escopo** corresponde a caminhos reais locais, então as linhas armazenadas antes de um `path_mapping` ser definido não podem ser delimitadas por pasta: use `all` ou reescaneie. Uma rajada, bracketing ou panorâmica parcialmente fora do escopo é ignorada inteira (`spanning_skipped`). Os grupos de semelhantes e de cenas são calculados dentro do escopo.
- **`--cull-min-score`** (somente CLI) nunca rejeita quadros de bracketing ou panorâmica, fotos sem pontuação, favoritas, avaliadas ou **Mantidas**, nem fotos que uma triagem anterior já julgou, então uma segunda execução não rejeita nada de novo. Sempre poupa membros de rajadas. Poupa membros de grupos de semelhantes quando o agrupamento os encontrou (lê as `similarity_groups.max_photos` fotos mais recentes do escopo, padrão `10000`, e descarta grupos acima de `similarity_groups.max_group_size`, padrão `50`). Poupa membros de grupos de cenas somente com `--cull-group-by scene`.
- **Cópia.** As fotos rejeitadas e os seus acompanhantes nunca são copiados. Arquivos de mesmo nome vindos de pastas diferentes recebem o sufixo `_1`; uma nova execução pula os arquivos idênticos (`already_present`). `DIR` não pode ser, conter nem estar dentro do escopo, da biblioteca ou de qualquer pasta que o Facet tenha escaneado (saída 1, verificado também em uma simulação). Os arquivos precisam estar dentro da lista de permissão de diretórios de varredura (`users.*.directories` / `viewer.scan_directories`); se todas as fotos forem ignoradas por causa disso, o comando sai com 3.
- **Usuários.** Em uma instalação multiusuário `--user` é obrigatório (saída 1 sem ele, ou com um usuário desconhecido). Em uma instalação de usuário único `--user` é ignorado com um aviso, e o comando vê todas as fotos mesmo com uma senha de visualizador definida. `--apply` toma o bloqueio da biblioteca; uma simulação não.
- **Erros de uso (saída 2).** `--apply`, `--copy-keepers` ou qualquer `--cull-*` sem `--auto-cull`; `--dry-run`, `--resume`, `--retry-failed` ou `--watch` com `--auto-cull`; `--auto-cull PATH` com pastas posicionais; rigor fora de 0–100; `--cull-min-keep` abaixo de 1. `--apply` deve ser digitado por inteiro (ele não abrevia mais `--apply-recommendations`).
- **Códigos de saída.** `0` sucesso (inclusive uma simulação ou zero grupos); `1` falha de pré-condição, configuração ou banco de dados; `2` erro de uso; `75` o bloqueio da biblioteca está com outro trabalho; `3` a triagem funcionou mas a cópia teve erros ou não copiou nada (uma simulação em que toda foto mantida seria ignorada também sai com `3`).
- O **retreinamento** não roda dentro da CLI. O contador de comparações persiste, e o retreinamento roda na próxima ação do visualizador ou comando `--train-*`. A primeira execução pode criar `.facet_secret`.

## Common Workflows

### Configuração Inicial
```bash
python facet.py /path/to/photos     # Pontua todas as fotos (multi-passo automático)
python facet.py --cluster-faces-incremental # Agrupa os rostos
python database.py --migrate-tags    # Habilita consultas de tags rápidas
python viewer.py                    # Veja os resultados
```

### Após Mudanças de Configuração
```bash
python facet.py --recompute-average                # Atualiza todas as pontuações com os novos pesos
python facet.py --recompute-category portrait      # Atualiza só uma categoria (mais rápido)
```

### Configuração do Reconhecimento Facial
```bash
python facet.py /path               # Extrai os rostos durante o escaneamento
python facet.py --cluster-faces-incremental     # Agrupa em pessoas
python facet.py --suggest-person-merges         # Encontra duplicatas
# Use /persons no visualizador para mesclar/renomear
```

### Triar uma sessão pelo terminal
```bash
python facet.py --auto-cull /photos/wedding                     # Pré-visualiza o plano, nada é gravado
python facet.py --auto-cull /photos/wedding --apply \
    --copy-keepers ~/wedding-keepers                             # Rejeita e depois copia os sobreviventes
python facet.py /photos/new-shoot --auto-cull --apply --cull-min-score 5   # Escaneia e depois tria
```

### Configuração Multiusuário
```bash
# Adicione usuários (pede a senha)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# Edite scoring_config.json para definir directories e shared_directories
# Migre as avaliações existentes para um usuário
python database.py --migrate-user-preferences --user alice
```

### Trocar o Modelo de Marcação
```bash
# Edite scoring_config.json: "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Remarca com o novo modelo
```

### Trocar o Perfil de VRAM
```bash
# Edite scoring_config.json: "vram_profile": "auto"
# Ou use um específico: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Verifica as distribuições
python facet.py --recompute-average        # Aplica os novos pesos
```

## Religar fotos movidas

Depois de mover arquivos por conta própria, `python database.py --relink-photos` pré-visualiza os mapeamentos de caminho antigo → novo e mantém os dados do banco de dados de cada foto. A prévia é o padrão.

- **Aplicar** exige o ID do plano salvo e `--acknowledge-unverified-identity`, porque o Facet não pode provar que o novo arquivo é o original. Pare visualizadores e escaneadores e revise o plano antes.
- **Recusados:** caminhos fora das suas raízes configuradas ou da visibilidade do usuário, cópias, nomes ambíguos, planos desatualizados e mapeamentos de caminho.
- Os **acompanhantes** devem ser listados explicitamente; os tipos incluem `sidecar_facet` para `photo.ext.facet.xmp`. Os retângulos manuais precisam de revisão no editor. O estado do Immich não muda.
- Os **planos** são salvos de forma privada (0600 em POSIX).
- **Montagens:** uma pasta legível não prova que um volume está montado, então `source_mount_status` permanece `not_verified`. Confirme que o original foi movido, e não que está offline.
- **Códigos de saída:** 75 significa que outro trabalho detém o bloqueio da biblioteca; 1 significa que o bloqueio é inutilizável. A prévia não toma bloqueio.

Veja [Relink a missing photo](RELINK.md) para o contrato completo e exemplos.
