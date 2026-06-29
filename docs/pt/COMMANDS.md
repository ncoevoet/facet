# Referência de Comandos

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · **Português**

[Escaneamento](#scanning) · [Pré-visualização e Exportação](#preview--export) · [Operações de Recálculo](#recompute-operations) · [Reconhecimento Facial](#face-recognition) · [Gerenciamento de Miniaturas](#thumbnail-management) · [Diagnóstico](#diagnostics) · [Informações de Modelos](#model-information) · [Otimização de Pesos](#weight-optimization-pairwise-comparison) · [Configuração](#configuration) · [Marcação](#tagging) · [Validação do Banco de Dados](#database-validation) · [Manutenção do Banco de Dados](#database-maintenance) · [Visualizador Web](#web-viewer) · [Fluxos de Trabalho Comuns](#common-workflows)

> Tags de requisito usadas abaixo: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (perfil de VRAM). Veja a [matriz de recursos](../README.md#feature-availability--requirements).

## Scanning

| Comando | Descrição |
|---------|-------------|
| `python facet.py /path` | Escaneia o diretório (modo multi-passo, detecção automática de VRAM) |
| `python facet.py /path --force` | Re-escaneia arquivos já processados |
| `python facet.py /path --single-pass` | Força o modo de passo único (todos os modelos de uma só vez) |
| `python facet.py /path --pass quality` | Executa apenas o passo de pontuação de qualidade TOPIQ |
| `python facet.py /path --pass quality-iaa` | Executa apenas a pontuação de mérito estético TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Executa apenas a pontuação de qualidade TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Executa apenas o diagnóstico de qualidade + distorção LIQE |
| `python facet.py /path --pass tags` | Executa apenas o passo de marcação (o modelo depende do perfil de VRAM) |
| `python facet.py /path --pass composition` | Executa apenas a detecção de padrão de composição SAMP-Net |
| `python facet.py /path --pass faces` | Executa apenas a detecção facial InsightFace |
| `python facet.py /path --pass embeddings` | Executa apenas a extração de embeddings CLIP/SigLIP |
| `python facet.py /path --pass saliency` | Executa apenas a detecção de saliência do sujeito BiRefNet |
| `python facet.py /path --db custom.db` | Usa um arquivo de banco de dados personalizado |
| `python facet.py /path --config my.json` | Usa uma configuração de pontuação personalizada |
| `python facet.py --resume` | Retoma o último escaneamento interrompido/falho — inclusive um que travou abruptamente por SIGKILL/OOM/queda de energia (uma execução ainda marcada como `running` cujo heartbeat é mais antigo que `processing.scan_stale_seconds`, padrão 120). Reutiliza seus diretórios; com `--force`, ignora arquivos já re-pontuados desde o início daquela execução. Recusa se outro escaneamento parecer genuinamente ativo. |
| `python facet.py --retry-failed` | Reprocessa apenas os arquivos que falharam durante a última execução de escaneamento (`--retry-failed all` para falhas em todas as execuções) |
| `python facet.py /path --force-since 2026-01-01` | Como `--force`, mas reprocessa apenas as fotos escaneadas por último antes da data |
| `python facet.py /path --watch` | Permanece em execução e re-escaneia sempre que novas fotos aparecem (requer `pip install watchdog`; `--watch-debounce N` ajusta o período de inatividade, padrão 30s) |
| `python facet.py /path --force-low-space` | Ignora a proteção de espaço livre pré-escaneamento (prossegue mesmo quando o volume parece pequeno demais para as miniaturas/embeddings que o escaneamento irá gravar) |

### Registro de Escaneamento

Cada escaneamento registra uma linha em `scan_runs` (status, modo, diretórios, contadores)
e erros por arquivo em `scan_failures` (caminho, etapa, erro). Interromper um
escaneamento com Ctrl+C marca a execução como `interrupted` para que `--resume` possa retomá-la;
arquivos com falha ficam visíveis e podem ser reprocessados, em vez de serem silenciosamente reprocessados a
cada escaneamento incremental. A CLI também emite linhas JSON estruturadas `@FACET_PROGRESS`
(fase, atual/total, ETA) que a API de escaneamento do visualizador expõe no
campo `progress` de `/api/scan/status` e no fluxo SSE.

### Modos de Processamento

**Multi-passo (padrão):** detecta a VRAM e carrega os modelos sequencialmente. Cada passo carrega seu modelo, processa todas as fotos e então descarrega para liberar VRAM, de modo que modelos de alta qualidade rodam mesmo com VRAM limitada.

**Passo único (`--single-pass`):** carrega todos os modelos de uma só vez. Mais rápido, precisa de mais VRAM.

**Passo específico (`--pass NAME`):** executa apenas um passo, para atualizar métricas específicas sem o reprocessamento completo. Passos disponíveis:

| Passo | Modelo | Saída | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | pontuação `aesthetic` (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | pontuação `aesthetic_iaa` (mérito artístico vs qualidade técnica, treinado com AVA) | Compartilhado com TOPIQ |
| `quality-face` | TOPIQ NR-Face | pontuação `face_quality_iqa` (qualidade facial dedicada) | Compartilhado com TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + diagnóstico de distorção (desfoque, superexposição, ruído) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Tags semânticas do vocabulário configurado | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (14 padrões) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Detecção facial, landmarks, detecção de piscadas, embeddings de reconhecimento | ~2 GB |
| `embeddings` | CLIP ViT-L-14 ou SigLIP 2 NaFlex | BLOB `clip_embedding` para similaridade/marcação | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~2 GB |

## Preview & Export

| Comando | Descrição |
|---------|-------------|
| `python facet.py /path --dry-run` | Pontua 10 fotos de amostra sem salvar |
| `python facet.py /path --dry-run --dry-run-count 20` | Pontua 20 fotos de amostra |
| `python facet.py --export-csv` | Exporta todas as pontuações para um CSV com data e hora no nome |
| `python facet.py --export-csv output.csv` | Exporta para um arquivo CSV específico |
| `python facet.py --export-json` | Exporta todas as pontuações para um JSON com data e hora no nome |
| `python facet.py --export-json output.json` | Exporta para um arquivo JSON específico |
| `python facet.py --import-sidecars` | Importa avaliações/rótulos/tags dos sidecars `<image>.xmp` de volta para o banco de dados (todas as fotos) |
| `python facet.py --import-sidecars /path` | Importa sidecars apenas para fotos sob uma subárvore de caminho |
| `python facet.py --import-sidecars --user alice` | Modo multiusuário: importa avaliações para o `user_preferences` da Alice em vez das colunas globais (palavras-chave permanecem globais) |
| `python facet.py --export-sidecars` | Grava/mescla sidecars `<image>.xmp` a partir do banco de dados para todas as fotos (somente sidecar) |
| `python facet.py --export-sidecars /path` | Exporta sidecars apenas para fotos sob uma subárvore de caminho |
| `python facet.py --export-sidecars --user alice` | Modo multiusuário: exporta as avaliações do `user_preferences` da Alice em vez das colunas globais (palavras-chave permanecem globais) |
| `python facet.py --export-sidecars --embed-originals` | Também embute os metadados **no arquivo** para JPEG/HEIC/TIFF/PNG/DNG (reescreve os originais) |
| `python facet.py --export-sidecars --score-to-stars` | Deriva `xmp:Rating` da pontuação agregada para fotos que você não avaliou manualmente (uma avaliação/favorito/rejeição manual sempre prevalece) |

> **Sincronização bidirecional de metadados.** O Facet grava avaliações, rótulos de cor, palavras-chave, legendas e regiões de rostos nomeados em um sidecar padrão `<image>.xmp` que o ecossistema lê (Lightroom, darktable, digiKam, immich, …); a imagem original nunca é modificada a menos que você opte por isso com `--export-sidecars --embed-originals` (somente JPEG/HEIC/TIFF/PNG/DNG — RAW nunca é tocado). A incorporação e a mesclagem segura por união de palavras-chave requerem **exiftool**; sem ele, o Facet recorre a um sidecar XML puro, sem dependências.
>
> **Ressalva.** O `--import-sidecars` resolve avaliações/rótulos pelo critério de *mais recente vence* em relação ao `scanned_at` da foto (último escaneamento), e não por um horário de edição por avaliação — portanto, um sidecar mais recente que o último escaneamento pode sobrescrever uma avaliação que você alterou no Facet depois dele. Execute `--import-sidecars` antes de reavaliar se o editor externo for a fonte da verdade, e `python database.py --migrate-tags` após importar se você usa a tabela de consulta `photo_tags`.

## Recompute Operations

Esses comandos atualizam métricas específicas, derivam novos dados (legendas por IA, GPS, embeddings) ou analisam o banco de dados — tudo sem reexecutar o pipeline completo de pontuação. A maioria reutiliza miniaturas/landmarks armazenados e é leve para a CPU, mas as linhas de IA/extração (por exemplo, `--generate-captions`) e as linhas de recálculo a partir da imagem são pesadas para a GPU.

| Comando | Descrição |
|---------|-------------|
| `python facet.py --recompute-average` | Recalcula as pontuações agregadas a partir dos embeddings armazenados (re-derivável; sem snapshot do banco — reverta restaurando um snapshot de pesos e recalculando) |
| `python facet.py --recompute-category portrait` | Recalcula as pontuações apenas para uma única categoria |
| `python facet.py --recompute-tags` | Re-marca todas as fotos usando o modelo configurado |
| `python facet.py --recompute-tags-vlm` | Re-marca todas as fotos usando o marcador VLM |
| `python facet.py --detect-moments` | Rotula novas fotos com seu momento narrativo (semântico de legenda, zero-shot + suavização temporal; executa automaticamente ao final de cada escaneamento). Codifica cada nova legenda uma vez em `caption_embedding`, depois cosseno sobre vetores armazenados — o primeiro backfill completo sobre uma biblioteca existente tem GPU recomendada; adicione `--limit N` para verificar em uma amostra |
| `python facet.py --recompute-moments` | Re-rotula os momentos narrativos de toda a biblioteca (re-suaviza a linha do tempo completa). Adicione `--dry-run --verbose` para visualizar os 3 principais momentos por foto sem gravar |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Recalcula as métricas de saliência do sujeito (BiRefNet_dynamic) |
| `python facet.py --recompute-composition-cpu` | Recalcula a composição, baseada em regras (CPU, qualquer perfil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recalcula a composição com SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` `[8gb/16gb/24gb]` Recalcula métricas IQA suplementares (TOPIQ IAA, NR-Face, LIQE) a partir das miniaturas armazenadas |
| `python facet.py --recompute-ocr` | Extrai o texto presente na imagem para `ocr_text` a partir das miniaturas (opcional; não faz nada sem um mecanismo de OCR; execute `--rebuild-fts` depois para indexar) |
| `python facet.py --recompute-colors` | Extrai a matiz dominante + a temperatura de cor quente/fria das miniaturas (CPU, rápido) para `dominant_hue` / `color_temp` |
| `python facet.py --upgrade-db` | Migra o schema e executa toda a cadeia de backfill: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, average. Idempotente; ignora etapas pesadas como a geração de legendas. |
| `python facet.py --recompute-blinks` | Recalcula a detecção de piscadas a partir dos landmarks armazenados (CPU, rápido) |
| `python facet.py --recompute-eyes-expression` | Recalcula as pontuações de olhos-abertos + expressão a partir dos landmarks armazenados (CPU, rápido) |
| `python facet.py --recompute-burst` | Recalcula os grupos de detecção de rajada |
| `python facet.py --detect-duplicates` | Detecta fotos duplicadas via pHash |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Avalia limiares de cosseno para quase-duplicatas (tabela de precisão/revocação com rótulos; caso contrário, distribuição de cosseno dos candidatos) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Gera legendas por IA para as fotos usando VLM |
| `python facet.py --translate-captions` | Traduz as legendas em inglês para o idioma de destino configurado (CPU, MarianMT) |
| `python facet.py --extract-gps` | Extrai coordenadas GPS dos dados EXIF para colunas do banco de dados |
| `python facet.py --rescan-gps` | Re-extrai as coordenadas GPS do EXIF para todas as fotos (sobrescreve as existentes) |
| `python facet.py --recompute-embeddings` | Recalcula os embeddings CLIP/SigLIP para todas as fotos (necessário após troca de modelo) |
| `python facet.py --score-topiq` | Preenche retroativamente as pontuações de qualidade TOPIQ a partir das miniaturas armazenadas (requer GPU) |
| `python facet.py --backfill-focal-35mm` | Preenche retroativamente a distância focal equivalente a 35mm a partir do EXIF para fotos que não a têm |
| `python facet.py --compute-recommendations` | Analisa o banco de dados, exibe um resumo de pontuação |
| `python facet.py --compute-recommendations --verbose` | Exibe estatísticas detalhadas |
| `python facet.py --compute-recommendations --apply-recommendations` | Aplica automaticamente as correções de pontuação |
| `python facet.py --compute-recommendations --simulate` | Visualiza as mudanças projetadas |

### Modelos de Qualidade Suplementares

Três modelos PyIQA adicionais pontuam além da pontuação estética primária do TOPIQ. Eles compartilham a VRAM com o TOPIQ e rodam como parte do pipeline multi-passo padrão.

- **TOPIQ IAA** (`--pass quality-iaa`): mérito estético artístico treinado com AVA, separado da qualidade técnica. Armazenado como `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): avaliação de qualidade da região do rosto. Armazenado como `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): pontuação de qualidade mais um diagnóstico de tipo de distorção (por exemplo, desfoque de movimento, superexposição, ruído). Armazenado como `liqe_score`.

### Benchmarks e pontuações suplementares

| Comando | Descrição |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Preenche a coluna `aesthetic_clip` projetando os embeddings CLIP/SigLIP em cache sobre um eixo estético derivado de texto. Zero inferência de imagem adicional. Não faz parte do `aggregate` padrão. Veja [docs/SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate). |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcula SRCC + PLCC em relação à referência de pontuação de opinião média (mean-opinion-score) do AVA para cada coluna de pontuação preenchida no banco. Útil ao adicionar ou ajustar uma variante de modelo. |

### Saliência do Sujeito

`--pass saliency` e `--recompute-saliency` usam o BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, via `transformers`) para gerar uma máscara binária do sujeito e então derivar quatro métricas:

- **Nitidez do Sujeito**: variância do Laplaciano na região do sujeito vs fundo — indica se o sujeito está em foco.
- **Proeminência do Sujeito**: área do sujeito / área do quadro — alta para um sujeito dominante (por exemplo, macro).
- **Posicionamento do Sujeito**: pontuação de regra dos terços para o centroide do sujeito.
- **Separação do Fundo**: diferença de gradiente de borda entre o contorno do sujeito e o fundo — qualidade do bokeh.

Requer `transformers` (~2 GB de VRAM).

### Modelos de Marcação

O modelo de marcação é selecionado por perfil de VRAM:

| Perfil | Modelo | Como funciona |
|---------|-------|-------------|
| `legacy` | Similaridade CLIP | Similaridade de cosseno entre o embedding da imagem e os embeddings de texto das tags. Sem carga de modelo extra. |
| `8gb` | Similaridade CLIP | Igual ao legacy, sobre os embeddings CLIP ViT-L-14 armazenados. |
| `16gb` | Qwen3.5-2B | Modelo multimodal para marcação semântica de cenas. |
| `24gb` | Qwen3.5-4B | Modelo multimodal maior. |

Todos os marcadores mapeiam a saída para o vocabulário de tags configurado. Use `--recompute-tags` para re-marcar com o modelo padrão do perfil, ou `--recompute-tags-vlm` para re-marcação baseada em VLM.

### Modelos de Embedding

Dois modelos de embedding disponíveis, selecionados por perfil de VRAM via `clip_config`:

| Config | Modelo | Dimensões | Usado Por |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | perfis 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | perfis legacy, 8gb |

Os embeddings impulsionam a marcação semântica, a detecção de duplicatas, a busca por fotos semelhantes e a estética CLIP+MLP (legacy/8gb). Trocar de modelo requer recalcular os embeddings de todas as fotos (`--force`, `--pass embeddings` ou `--recompute-embeddings`).

## Face Recognition

| Comando | Descrição |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extrai rostos para novas fotos (GPU, paralelo) |
| `python facet.py --extract-faces-gpu-force` | Apaga todos os rostos e re-extrai (GPU) |
| `python facet.py --cluster-faces-incremental` | Clustering HDBSCAN, preserva todas as pessoas (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, preserva apenas as pessoas nomeadas (CPU) |
| `python facet.py --cluster-faces-force` | Re-clustering completo, apaga todas as pessoas (CPU) |
| `python facet.py --suggest-person-merges` | Sugere possíveis fusões de pessoas |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Usa um limiar mais rigoroso |
| `python facet.py --refill-face-thumbnails-incremental` | Gera miniaturas ausentes (CPU, paralelo) |
| `python facet.py --refill-face-thumbnails-force` | Regenera TODAS as miniaturas (CPU, paralelo) |

## Thumbnail Management

| Comando | Descrição |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Corrige a rotação das miniaturas armazenadas usando a orientação EXIF |

Lê a orientação EXIF dos arquivos originais e gira os bytes da miniatura armazenada; para fotos processadas antes de existir o tratamento de EXIF. Lê apenas o cabeçalho EXIF e a miniatura armazenada, não as imagens completas.

## Diagnostics

| Comando | Descrição |
|---------|-------------|
| `python facet.py --doctor` | Executa verificações de diagnóstico (Python, GPU, dependências, configuração, banco de dados) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simula o hardware de GPU para diagnóstico |

Reporta a versão do Python, o build do PyTorch/CUDA, a detecção e o driver da GPU, a recomendação de perfil de VRAM, as dependências opcionais e o status da configuração/banco de dados. Quando o PyTorch não consegue enxergar a GPU mas o `nvidia-smi` consegue, ele imprime o comando `pip install` para corrigir o build do CUDA.

`--simulate-gpu NAME` e `--simulate-vram GB` testam o comportamento com hardware diferente. Ambos requerem `--doctor`; `--simulate-vram` requer `--simulate-gpu`.

## Model Information

| Comando | Descrição |
|---------|-------------|
| `python facet.py --list-models` | Mostra os modelos disponíveis e os requisitos de VRAM |

## Weight Optimization (Pairwise Comparison)

| Comando | Descrição |
|---------|-------------|
| `python facet.py --comparison-stats` | Mostra as estatísticas de comparação pareada |
| `python facet.py --optimize-weights` | Otimiza e salva os pesos a partir das comparações (todas as fontes, ponderadas por confiabilidade); aplicado apenas se a acurácia de validação cruzada k-fold (held-out) superar os pesos atuais |
| `python facet.py --optimize-weights --optimize-force` | Aplica os pesos otimizados mesmo se a barreira de acurácia não for atingida |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Restringe os dados de treino a fontes de comparação específicas |
| `python facet.py --optimize-weights --optimize-category portrait` | Treina apenas em uma categoria e grava seu bloco v4 `categories[].weights` |
| `python facet.py --auto-tune-categories` | **Apenas superadmin** (passe `--user` no modo multiusuário): reporta a prontidão dos rótulos de comparação por categoria para o ajuste automático dos pesos globais compartilhados. Stub — reporta apenas a prontidão; o loop de aplicação automática está adiado, aguardando rótulos |
| `python facet.py --sync-label-comparisons` | Reconstrói os pares derivados de avaliações (source=rating) a partir de estrelas/favoritos/rejeições |
| `python facet.py --train-ranker` | Treina o ranqueador pessoal sobre [embedding + pontuações] e grava learned_scores (condicionado à acurácia de validação cruzada k-fold (held-out) vs a linha de base agregada) |
| `python facet.py --train-ranker --ranker-category portrait` | Treina o ranqueador apenas em uma categoria |
| `python facet.py --train-ranker --train-ranker-force` | Grava learned_scores mesmo se a barreira de acurácia não for atingida |
| `python facet.py --report-unreviewed-bursts` | Reporta quantos grupos de rajada permanecem não revisados (somente leitura) |
| `python facet.py --eval-iqa-srcc` | Reporta o SRCC de Spearman de cada métrica IQA/estética vs suas avaliações por estrelas (somente leitura) |
| `python facet.py --mine-insights` | Relatório de mineração de dados: inventário de rótulos, correlações métrica-rótulo, distribuição de categorias, deriva (drift) de percentis, saúde das comparações |
| `python facet.py --mine-insights report.json` | O mesmo, mas também grava o relatório completo como JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Calibra os pesos de pontuação por categoria em relação ao [conjunto de dados AVA](https://github.com/imfing/ava_downloader) maximizando o SRCC vs as pontuações de opinião média do AVA (somente leitura; imprime os pesos propostos) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Restringe a categorias específicas e grava os pesos otimizados de volta em `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Escolhe o otimizador (`de` = evolução diferencial, padrão; `nelder-mead` = simplex local) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Também calibra em relação às tags semânticas do AVA (`--ava-tags-only` para usar exclusivamente as tags; `--apply-filters` para também ajustar os limiares de filtro de categoria) |

## Configuration

| Comando | Descrição |
|---------|-------------|
| `python facet.py --validate-categories` | Valida as configurações de categoria |

## Tagging

| Comando | Descrição |
|---------|-------------|
| `python tag_existing.py` | Adiciona tags a fotos não marcadas usando os embeddings CLIP armazenados |
| `python tag_existing.py --dry-run` | Pré-visualiza as tags sem salvar |
| `python tag_existing.py --threshold 0.25` | Limiar de similaridade personalizado (padrão: 0.22) |
| `python tag_existing.py --max-tags 3` | Limita as tags por foto (padrão: 5) |
| `python tag_existing.py --force` | Re-marca todas as fotos |
| `python tag_existing.py --db custom.db` | Usa um banco de dados personalizado |
| `python tag_existing.py --config my.json` | Usa uma configuração personalizada |

## Database Validation

| Comando | Descrição |
|---------|-------------|
| `python validate_db.py` | Valida a consistência do banco de dados (interativo) |
| `python validate_db.py --auto-fix` | Corrige automaticamente todos os problemas |
| `python validate_db.py --report-only` | Reporta sem solicitar confirmação |
| `python validate_db.py --db custom.db` | Valida um banco de dados personalizado |

Verifica: faixas de pontuação, métricas faciais, corrupção de BLOB, tamanhos de embedding, rostos órfãos, valores estatísticos atípicos (outliers).

## Database Maintenance

| Comando | Descrição |
|---------|-------------|
| `python database.py` | Inicializa/atualiza o schema |
| `python database.py --info` | Mostra informações do schema |
| `python database.py --migrate-tags` | Popula a tabela de consulta photo_tags (consultas 10-50x mais rápidas) |
| `python database.py --rebuild-fts` | Reconstrói o índice de busca textual completa FTS5 a partir de legendas/tags |
| `python database.py --populate-vec` | Popula a tabela de busca vetorial sqlite-vec a partir dos embeddings |
| `python database.py --refresh-stats` | Atualiza o cache de estatísticas |
| `python database.py --stats-info` | Mostra o status e a idade do cache |
| `python database.py --vacuum` | Recupera espaço, desfragmenta |
| `python database.py --analyze` | Atualiza as estatísticas do planejador de consultas |
| `python database.py --optimize` | Executa VACUUM e ANALYZE |
| `python database.py --backup` | Grava um snapshot do banco com data e hora, seguro para WAL (rotaciona conforme `--keep N`, padrão 3) |
| `python database.py --export-viewer-db` | Exporta um banco de dados leve para o visualizador (remove BLOBs, reduz as miniaturas; incremental se a saída já existir) |
| `python database.py --export-viewer-db --force-export` | Força uma re-exportação completa, mesmo se o banco do visualizador já existir |
| `python database.py --cleanup-orphaned-persons` | Remove pessoas sem rostos associados |
| `python database.py --cleanup-missing-photos` | Remove do banco de dados as fotos que não estão mais no disco (as exclusões em cascata limpam tags, rostos detectados etc.; também limpa associações de álbuns, o índice vetorial e invalida o cache de estatísticas) |
| `python database.py --cleanup-missing-photos --dry-run` | Pré-visualiza os arquivos ausentes sem excluir |
| `python database.py --cleanup-missing-photos --force` | Prossegue mesmo quando todas as fotos parecem ausentes (proteção contra apagar tudo quando um volume está desmontado) |
| `python database.py --migrate-storage-fs` | Migra miniaturas e embeddings dos BLOBs do banco de dados para o sistema de arquivos |
| `python database.py --migrate-storage-db` | Migra miniaturas e embeddings do sistema de arquivos de volta para o banco de dados |
| `python database.py --add-user alice --role admin` | Adiciona um usuário (solicita a senha) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Adiciona um usuário com nome de exibição |
| `python database.py --migrate-user-preferences --user alice` | Copia as avaliações de photos para user_preferences |

**Dica de desempenho:** Para bancos de dados grandes (50k+ fotos), execute `--migrate-tags`, `--rebuild-fts` e `--populate-vec` uma vez, e então `--optimize` periodicamente.

## Web Viewer

| Comando | Descrição |
|---------|-------------|
| `python viewer.py` | Inicia o servidor em http://localhost:5000 (API + Angular SPA) |
| `python viewer.py --port 5001` | Vincula a outra porta (ou defina a variável de ambiente `PORT`; padrão 5000) |
| `python viewer.py --host 127.0.0.1` | Vincula a uma interface específica (padrão `0.0.0.0`) |
| `python viewer.py --production` | Modo de produção (workers do uvicorn) |
| `python viewer.py --production --workers 4` | Modo de produção com N workers (padrão 1) |

## Common Workflows

### Configuração Inicial
```bash
python facet.py /path/to/photos     # Score all photos (auto multi-pass)
python facet.py --cluster-faces-incremental # Cluster faces
python database.py --migrate-tags    # Enable fast tag queries
python viewer.py                    # View results
```

### Após Mudanças de Configuração
```bash
python facet.py --recompute-average                # Update all scores with new weights
python facet.py --recompute-category portrait      # Update only one category (faster)
```

### Configuração do Reconhecimento Facial
```bash
python facet.py /path               # Extract faces during scan
python facet.py --cluster-faces-incremental     # Group into persons
python facet.py --suggest-person-merges         # Find duplicates
# Use /persons in viewer to merge/rename
```

### Configuração Multiusuário
```bash
# Add users (prompts for password)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# Edit scoring_config.json to set directories and shared_directories
# Migrate existing ratings to a user
python database.py --migrate-user-preferences --user alice
```

### Trocar o Modelo de Marcação
```bash
# Edit scoring_config.json: "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Re-tag with new model
```

### Trocar o Perfil de VRAM
```bash
# Edit scoring_config.json: "vram_profile": "auto"
# Or use specific: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Check distributions
python facet.py --recompute-average        # Apply new weights
```
