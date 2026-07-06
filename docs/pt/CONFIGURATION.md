# Referência de Configuração

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · **Português**

Todas as configurações ficam em `scoring_config.json`. Após modificar, execute `python facet.py --recompute-average` para atualizar as pontuações (não é necessário GPU).

## Sumário

- [Usuários](#users)
- [Escaneamento](#scanning)
- [Categorias](#categories)
- [Pontuação](#scoring)
- [Limiares](#thresholds)
- [Composição](#composition)
- [Ajustes de EXIF](#exif-adjustments)
- [Exposição](#exposure)
- [Penalidades](#penalties)
- [Normalização](#normalization)
- [Modelos](#models)
- [Modelos de Avaliação de Qualidade](#quality-assessment-models)
- [Processamento](#processing)
- [Detecção de Rajadas](#burst-detection)
- [Pontuação de Rajadas](#burst-scoring)
- [Detecção de Duplicatas](#duplicate-detection)
- [Detecção de Faces](#face-detection)
- [Agrupamento de Faces](#face-clustering)
- [Processamento de Faces](#face-processing)
- [Detecção de Monocromático](#monochrome-detection)
- [Marcação de Tags](#tagging)
- [Tags Independentes](#standalone-tags)
- [Análise](#analysis)
- [Visualizador](#viewer)
- [Desempenho](#performance)
- [Armazenamento](#storage)
- [Plugins](#plugins)
- [Cápsulas](#capsules)
- [Grupos de Similaridade](#similarity-groups)
- [Cenas](#scenes)
- [Linha do Tempo](#timeline)
- [Mapa](#map)
- [Tradução](#translation)

---

## Users

Modo multiusuário opcional. Quando a chave `users` está presente (com pelo menos um usuário), a autenticação por senha única é substituída pelo login por usuário.

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

### Campos de usuário

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `password_hash` | string | Hash PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`). Gerado pelo CLI `--add-user`. |
| `display_name` | string | Exibido no cabeçalho da interface |
| `role` | string | `user`, `admin` ou `superadmin` |
| `directories` | array | Diretórios de fotos privados deste usuário |

### Diretórios compartilhados

A chave `shared_directories` (irmã dos objetos de usuário) lista diretórios visíveis a todos os usuários.

### Funções (roles)

| Função | Ver próprias + compartilhadas | Avaliar/favoritar | Gerenciar pessoas/faces | Disparar escaneamentos |
|------|:-:|:-:|:-:|:-:|
| `user` | sim | sim | não | não |
| `admin` | sim | sim | sim | não |
| `superadmin` | sim | sim | sim | sim |

### Adicionando usuários

Usuários são criados somente via CLI — não há interface de registro nem API:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Solicita a senha, grava o hash em scoring_config.json
```

Após adicionar um usuário, edite `scoring_config.json` para configurar seus `directories`.

### Compatibilidade retroativa

- Sem a chave `users` = modo legado de usuário único (comportamento inalterado)
- `viewer.password` e `viewer.edition_password` são ignorados no modo multiusuário
- As avaliações existentes na tabela `photos` permanecem para o modo de usuário único; use `--migrate-user-preferences` para copiá-las

---

## Scanning

Controla o comportamento de escaneamento de diretórios.

```json
{
  "scanning": {
    "skip_hidden_directories": true
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `skip_hidden_directories` | `true` | Ignora diretórios que começam com `.` durante o escaneamento de fotos |

---

## Categories

Array de definições de categorias. Veja [Pontuação](SCORING.md) para a documentação detalhada de categorias.

Cada categoria possui:
- `name` - Identificador da categoria
- `priority` - Menor = maior prioridade (avaliada primeiro)
- `filters` - Condições para correspondência
- `weights` - Pesos das métricas de pontuação (devem somar 100)
- `modifiers` - Ajustes de comportamento
- `tags` - Vocabulário CLIP para correspondência baseada em tags

> **Pesos de forma e harmonia de cores.** O bloco `weights` de cada categoria carrega cinco chaves de métrica explicáveis — `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` e `color_harmony_percent` — preenchidas por `--recompute-form`. Elas são distribuídas com valor `0` em todas as categorias, então os agregados permanecem idênticos byte a byte até você atribuir um peso a alguma (depois execute `--recompute-average` novamente). Os pesos dentro de uma categoria ainda devem somar 100.

---

## Scoring

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `score_min` | `0.0` | Pontuação mínima possível |
| `score_max` | `10.0` | Pontuação máxima possível |
| `score_precision` | `2` | Casas decimais das pontuações |

---

## Thresholds

Limiares de detecção para categorização automática.

```json
{
  "thresholds": {
    "portrait_face_ratio_percent": 5,
    "blink_penalty_percent": 50,
    "night_luminance_threshold": 0.15,
    "night_iso_threshold": 3200,
    "long_exposure_shutter_threshold": 1.0,
    "astro_shutter_threshold": 10.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `portrait_face_ratio_percent` | `5` | Face > 5% do quadro = retrato |
| `blink_penalty_percent` | `50` | Multiplicador de pontuação quando um piscar é detectado (0,5x) |
| `night_luminance_threshold` | `0.15` | Luminância média abaixo disso = noite |
| `night_iso_threshold` | `3200` | ISO acima disso = pouca luz |
| `long_exposure_shutter_threshold` | `1.0` | Obturador > 1s = longa exposição |
| `astro_shutter_threshold` | `10.0` | Obturador > 10s = astrofotografia |

---

## Composition

Pontuação de composição baseada em regras (usada quando o SAMP-Net não está ativo).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `power_point_weight` | `2.0` | Peso para o posicionamento pela regra dos terços |
| `line_weight` | `1.0` | Peso para linhas-guia |

---

## EXIF Adjustments

Ajustes automáticos de pontuação com base nas configurações da câmera.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `iso_sharpness_compensation` | `true` | Reduz a penalidade de nitidez para ISO alto |
| `aperture_isolation_boost` | `true` | Aumenta o isolamento para aberturas amplas (f/1.4-f/2.8) |

---

## Exposure

Controla a análise de exposição e a detecção de clipping.

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `shadow_clip_threshold_percent` | `15` | Sinaliza se > 15% dos pixels forem preto puro |
| `highlight_clip_threshold_percent` | `10` | Sinaliza se > 10% dos pixels forem branco puro |
| `silhouette_detection` | `true` | Detecta silhuetas intencionais |

---

## Penalties

Penalidades de pontuação para problemas técnicos.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "bimodality_threshold": 2.5,
    "bimodality_penalty_points": 0.5,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_pixel_percent": 5,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `noise_sigma_threshold` | `4.0` | Ruído acima disso aciona penalidade |
| `noise_max_penalty_points` | `1.5` | Penalidade máxima de ruído |
| `noise_penalty_per_sigma` | `0.3` | Pontos por sigma acima do limiar |
| `bimodality_threshold` | `2.5` | Coeficiente de bimodalidade do histograma |
| `bimodality_penalty_points` | `0.5` | Penalidade para histogramas bimodais |
| `leading_lines_blend_percent` | `30` | Mescla no comp_score |
| `oversaturation_threshold` | `0.9` | Limiar de saturação média |
| `oversaturation_pixel_percent` | `5` | Reservado para detecção em nível de pixel |
| `oversaturation_penalty_points` | `0.5` | Penalidade por supersaturação |

**Fórmula da penalidade de ruído:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalization

Controla como as métricas brutas são escalonadas para pontuações de 0 a 10.

```json
{
  "normalization": {
    "method": "percentile",
    "percentile_target": 90,
    "per_category": true,
    "category_min_samples": 50
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `method` | `"percentile"` | Método de normalização |
| `percentile_target` | `90` | 90º percentil = pontuação de 10,0 |
| `per_category` | `true` | Normalização específica por categoria |
| `category_min_samples` | `50` | Mínimo de fotos para normalização por categoria |

---

## Models

Seleciona quais modelos são usados por perfil de VRAM.

```json
{
  "models": {
    "vram_profile": "auto",
    "keep_in_ram": "auto",
    "profiles": {
      "legacy": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": [],
        "saliency_enabled": false,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging (8GB+ RAM)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": false,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging (6-14GB VRAM)"
      },
      "16gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-2b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-2B tagging (~14GB VRAM)"
      },
      "24gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "qwen2-vl-2b",
        "tagging_model": "qwen3.5-4b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-4B tagging (~18GB VRAM)"
      }
    },
    "clip": {
      "model_name": "google/siglip2-so400m-patch16-naflex",
      "backend": "transformers",
      "embedding_dim": 1152,
      "similarity_threshold_percent": 8
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "similarity_threshold_percent": 22
    },
    "qwen2_vl": {
      "model_path": "Qwen/Qwen2-VL-2B-Instruct",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 256
    },
    "qwen3_5_2b": {
      "model_path": "Qwen/Qwen3.5-2B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 4
    },
    "qwen3_5_4b": {
      "model_path": "Qwen/Qwen3.5-4B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 2
    },
    "saliency": {
      "model": "ZhengPeng7/BiRefNet_dynamic",
      "resolution": 1024,
      "mask_threshold": 0.3,
      "min_subject_pixels": 50
    },
    "samp_net": {
      "model_path": "pretrained_models/samp_net.pth",
      "download_url": "https://github.com/bcmi/Image-Composition-Assessment-with-SAMP/releases/download/v1.0/samp_net.pth",
      "input_size": 384,
      "patterns": [
        "none", "center", "rule_of_thirds", "golden_ratio", "triangle",
        "horizontal", "vertical", "diagonal", "symmetric", "curved",
        "radial", "vanishing_point", "pattern", "fill_frame"
      ]
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `vram_profile` | `"auto"` | Perfil ativo (`auto`, `legacy`, `8gb`, `16gb`, `24gb`) |
| `keep_in_ram` | `"auto"` | Mantém os modelos na RAM entre os blocos de múltiplas passagens (`"auto"`, `"always"`, `"never"`). `auto` verifica a RAM disponível antes de fazer cache. |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modelos PyIQA a executar para este perfil (vazio em `legacy`) |
| `profiles.*.saliency_enabled` | `true` (16gb/24gb) | Executa a saliência de assunto do BiRefNet para este perfil |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modelo de embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) ou `"open_clip"` (legado) |
| `clip.embedding_dim` | `1152` | Dimensões do embedding (1152 para SigLIP 2) |
| `clip.similarity_threshold_percent` | `8` | Similaridade de cosseno CLIP mínima para uma correspondência de tag |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modelo CLIP legado (perfis legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Pesos pré-treinados legados |
| `clip_legacy.embedding_dim` | `768` | Dimensões do embedding legado |
| `clip_legacy.similarity_threshold_percent` | `22` | Limiar de correspondência de tag para o CLIP legado |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Caminho no HuggingFace (VLM de composição 24gb) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modelo de tagging para o perfil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Imagens por lote de inferência do VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modelo de tagging para o perfil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Imagens por lote de inferência do VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modelo de saliência BiRefNet |
| `saliency.resolution` | `1024` | Resolução de inferência |
| `saliency.mask_threshold` | `0.3` | Limiar sigmoide para a máscara binária do assunto |
| `saliency.min_subject_pixels` | `50` | Mínimo de pixels de assunto para contar um assunto como detectado |
| `samp_net.input_size` | `384` | Tamanho de entrada do modelo de composição |

### Detecção Automática de VRAM

Quando `vram_profile` é `"auto"` (padrão), o sistema detecta a VRAM de GPU disponível na inicialização e seleciona o maior perfil que couber:

| VRAM detectada | Perfil selecionado |
|----------------|--------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Sem GPU | `legacy` (usa a RAM do sistema) |

---

## Quality Assessment Models

Seleciona o modelo que pontua a qualidade/estética da imagem, via biblioteca [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `model` | `"auto"` | Modelo de qualidade: `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` usa `topiq`. |
| `prefer_llm` | `false` | Prefere um pontuador baseado em LLM quando houver um disponível |

### Modelos de Qualidade Disponíveis

SRCC = Coeficiente de Correlação de Postos de Spearman no benchmark KonIQ-10k (1,0 = perfeito).

| Modelo | SRCC | VRAM | Notas |
|--------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Padrão (`auto`); backbone ResNet50 com atenção top-down |
| `hyperiqa` | 0.90 | ~2GB | Hyper-network, adaptável ao conteúdo |
| `dbcnn` | 0.90 | ~2GB | CNN de ramo duplo (distorções sintéticas + autênticas) |
| `musiq` | 0.87 | ~2GB | Transformer multiescala; lida com qualquer resolução |
| `clipiqa+` | 0.86 | ~4GB | CLIP com prompts de qualidade aprendidos |
| `clip-mlp` | 0.76 | ~4GB | CLIP ViT-L-14 legado + cabeça MLP |

### Trocando os Modelos de Qualidade

1. Edite `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Repontue as fotos existentes (opcional):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Processing

Configurações unificadas de processamento para o processamento em lote na GPU e o modo de múltiplas passagens.

```json
{
  "processing": {
    "mode": "auto",
    "gpu_batch_size": 16,
    "ram_chunk_size": 32,
    "num_workers": 4,
    "auto_tuning": {
      "enabled": true,
      "monitor_interval_seconds": 5,
      "tuning_interval_images": 32,
      "min_processing_workers": 1,
      "max_processing_workers": 32,
      "min_gpu_batch_size": 2,
      "max_gpu_batch_size": 32,
      "min_ram_chunk_size": 10,
      "max_ram_chunk_size": 128,
      "memory_limit_percent": 85,
      "cpu_target_percent": 85,
      "metrics_print_interval_seconds": 30
    },
    "thumbnails": {
      "photo_size": 640,
      "photo_quality": 80,
      "face_padding_ratio": 0.3
    }
  }
}
```

### Conceitos-Chave

**`gpu_batch_size`** - Quantas imagens são processadas juntas na GPU em uma única passagem direta. Limitado pela VRAM. Ajustado automaticamente: reduzido quando a memória da GPU excede o limite.

**`ram_chunk_size`** - Quantas imagens são armazenadas em cache na RAM entre as passagens dos modelos (apenas no modo de múltiplas passagens). Reduz a E/S de disco ao carregar as imagens uma vez por bloco. Limitado pela RAM do sistema. Ajustado automaticamente: reduzido quando a memória do sistema excede o limite.

### Referência de Configurações

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `mode` | `"auto"` | Modo de processamento: `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Imagens por lote de GPU (limitado pela VRAM) |
| `ram_chunk_size` | `32` | Imagens por bloco de RAM (múltiplas passagens) |
| `num_workers` | `4` | Threads de carregamento de imagens |
| `load_workers` | `num_workers` | Threads de carregamento de blocos em múltiplas passagens (limitado a 8, `1` = sequencial) |
| `raw_decode_concurrency` | `0` (auto) | Máximo de decodificações RAW simultâneas; dimensionado automaticamente a partir de CPU/RAM (1-4), `1` = totalmente serializado |
| `raw_decode_timeout_seconds` | `120` | Abandona uma decodificação RAW travada após este atraso (`0` = desativado); o escaneamento falha rapidamente após travamentos repetidos |
| `exif_prefetch` | `true` | Modo de passagem única: pré-busca o EXIF em segundo plano em vez de bloquear a thread da GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Ativa o ajuste automático |
| `monitor_interval_seconds` | `5` | Intervalo de verificação de recursos |
| `tuning_interval_images` | `32` | Reajusta a cada N imagens |
| `min_processing_workers` | `1` | Mínimo de threads de carregamento |
| `max_processing_workers` | `32` | Máximo de threads de carregamento |
| `min_gpu_batch_size` | `2` | Tamanho mínimo do lote de GPU |
| `max_gpu_batch_size` | `32` | Tamanho máximo do lote de GPU |
| `min_ram_chunk_size` | `10` | Tamanho mínimo do bloco de RAM |
| `max_ram_chunk_size` | `128` | Tamanho máximo do bloco de RAM |
| `memory_limit_percent` | `85` | Limite de uso de memória do sistema |
| `cpu_target_percent` | `85` | Meta de uso de CPU |
| `metrics_print_interval_seconds` | `30` | Intervalo de impressão de estatísticas |
| **thumbnails** | | |
| `photo_size` | `640` | Tamanho da miniatura armazenada (pixels) |
| `photo_quality` | `80` | Qualidade JPEG da miniatura |
| `face_padding_ratio` | `0.3` | Margem ao redor dos recortes de face |

### Modos de Processamento

| Modo | Descrição |
|------|-----------|
| `auto` | Seleciona automaticamente múltiplas passagens ou passagem única com base na VRAM |
| `multi-pass` | Carregamento sequencial de modelos (funciona com VRAM limitada) |
| `single-pass` | Todos os modelos carregados de uma vez (requer VRAM alta) |

### Como Funcionam as Múltiplas Passagens

Em vez de carregar todos os modelos de uma vez, as múltiplas passagens:

1. Carregam imagens em blocos de RAM (padrão de `ram_chunk_size`: 32)
2. Para cada bloco, executam os modelos sequencialmente: carregar modelo → processar bloco → descarregar modelo
3. Combinam os resultados em uma passagem final de agregação

Cada imagem é carregada uma vez por bloco, e as passagens são agrupadas para caber na VRAM disponível, de modo que os VLMs maiores de tagging/composição rodem mesmo com VRAM limitada.

### Comportamento do Ajuste Automático

O sistema monitora o uso de recursos e ajusta:

| Métrica | Ação |
|---------|------|
| Memória de GPU > limite | Reduz `gpu_batch_size` em 25% |
| RAM do sistema > limite | Reduz `ram_chunk_size` em 25% |
| RAM do sistema < (limite - 20%) | Aumenta `ram_chunk_size` em 25% |
| CPU > meta | Sugere menos workers |
| Timeouts de fila > 5% | Sugere mais workers |

### Agrupamento Dinâmico de Passagens

Quando a VRAM permite, vários modelos pequenos rodam juntos:

| VRAM | Passagem 1 | Passagem 2 |
|------|------------|------------|
| 8GB | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12GB | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16GB | CLIP + SAMP-Net + InsightFace + TOPIQ | VLM de tagging |
| 24GB+ | Todos os modelos juntos (passagem única) | - |

### Opções de CLI

```bash
# Padrão: múltiplas passagens automáticas com agrupamento ideal
python facet.py /path/to/photos

# Força passagem única (todos os modelos carregados de uma vez)
python facet.py /path --single-pass

# Executa apenas uma passagem específica
python facet.py /path --pass quality       # Apenas TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (mérito estético)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (qualidade + distorção)
python facet.py /path --pass tags          # Apenas o tagger configurado
python facet.py /path --pass composition   # Apenas SAMP-Net
python facet.py /path --pass faces         # Apenas InsightFace
python facet.py /path --pass embeddings    # Apenas embeddings CLIP/SigLIP
python facet.py /path --pass saliency      # Saliência de assunto BiRefNet

# Lista os modelos disponíveis
python facet.py --list-models
```

---

## Burst Detection

Agrupa fotos similares tiradas em sucessão rápida.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `similarity_threshold_percent` | `70` | Limiar de similaridade do hash da imagem |
| `time_window_minutes` | `0.8` | Tempo máximo entre fotos |
| `rapid_burst_seconds` | `0.4` | Fotos dentro deste intervalo são agrupadas automaticamente |

---

## Burst Scoring

Pesos usados pela seleção de rajadas para calcular uma pontuação composta na escolha do melhor disparo dentro de cada grupo de rajada. Os pesos devem somar 1,0.

```json
{
  "burst_scoring": {
    "weight_aggregate": 0.4,
    "weight_aesthetic": 0.25,
    "weight_sharpness": 0.2,
    "weight_blink": 0.15
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `weight_aggregate` | `0.4` | Peso da pontuação agregada geral |
| `weight_aesthetic` | `0.25` | Peso da pontuação de qualidade estética |
| `weight_sharpness` | `0.2` | Peso da pontuação de nitidez técnica |
| `weight_blink` | `0.15` | Peso de penalidade para piscadas detectadas (maior = penalidade mais forte) |

---

## Duplicate Detection

Detecta fotos duplicadas globalmente usando comparação de hash perceptual (pHash).

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `similarity_threshold_percent` | `90` | Filtro estrito de pHash (90% = distância de Hamming <= 6 de 64 bits); usado como critério único quando falta o embedding de alguma das fotos |
| `prefilter_hamming` | `12` | Override opcional (ausente no arquivo distribuído). Filtro frouxo de Hamming do estágio 1 para o conjunto de candidatos quando ambas as fotos têm embeddings (forçado a ser >= o filtro estrito) |
| `embedding_cosine_threshold` | `0.90` | Override opcional (ausente no arquivo distribuído). Filtro de cosseno SigLIP/CLIP do estágio 2: um candidato de pHash frouxo só é mesclado quando o cosseno >= este valor |

A detecção é em dois estágios: candidatos de pHash frouxo (recall) confirmados por um filtro estrito de cosseno do embedding (precisão). Fotos sem embedding recorrem ao critério estrito apenas de pHash, então o comportamento permanece inalterado quando os embeddings estão ausentes.

Execute `python facet.py --detect-duplicates` para detectar e agrupar duplicatas. Execute `python facet.py --sweep-dedup-thresholds [labels.json]` para avaliar o filtro de cosseno — com um JSON de rótulos ele imprime uma tabela de precisão/recall, caso contrário a distribuição de cosseno dos candidatos e quantas colisões de pHash estrito o filtro rejeita.

---

## Camada IQA estendida (opcional)

Pontuadores de qualidade pesados/experimentais, **DESLIGADOS por padrão** e **nunca um substituto para o TOPIQ** — eles adicionam colunas suplementares apenas quando explicitamente habilitados. Quando habilitados, os pontuadores estendidos rodam **durante um escaneamento normal** e gravam suas próprias colunas; uma falha de carregamento/VRAM é registrada e a coluna fica `NULL` (o escaneamento nunca é abortado).

```json
{
  "iqa_extended": {
    "qalign": "4bit",
    "aesthetic_v25": true,
    "deqa": false
  }
}
```

| Configuração | Padrão | Valores aceitos | Coluna | Descrição |
|--------------|--------|-----------------|--------|-----------|
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | IQA baseado em LLM Q-Align (suportado por pyiqa). `"4bit"` (~6-8GB VRAM) é a escolha prática em uma placa de 16GB; `"8bit"` ~12-14GB; precisão total (`true`) requer 16GB+. 4-/8-bit precisam de `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (cabeça SigLIP, ~2GB). Requer o pacote `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU 16GB+; ignorado e deixado NULL caso contrário). |

**Instale as dependências opcionais** para o que você habilitar: `pip install -e .[iqa-extended]` (adiciona `aesthetic-predictor-v2-5` + `bitsandbytes`), ou descomente as linhas correspondentes em `requirements.txt`. O Q-Align em si acompanha o `pyiqa`; o DeQA-Score é baixado via `transformers`.

Quando habilitada, cada métrica é exposta ao agregado ponderado, mas tem peso 0 por padrão, de modo que `--recompute-average` é idêntico byte a byte até você atribuir um peso. Execute `python facet.py --eval-iqa-srcc` para medir o quão bem cada métrica ordena sua biblioteca em relação às suas próprias avaliações por estrelas.

**Exibição no visualizador.** Quando qualquer uma dessas colunas é preenchida, o visualizador mostra o valor no painel **Quality** dos detalhes da foto (`Q-Align`, `Aesthetic V2.5`, `DeQA`) e expõe um controle deslizante de faixa correspondente na barra lateral de filtros da galeria sob **Extended Quality** (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). As fotos escaneadas antes de a camada ser habilitada simplesmente têm `NULL` nessas colunas e não são afetadas pelos filtros.

**Robustez.** O DeQA-Score carrega código remoto `trust_remote_code` cuja assinatura de forward varia entre revisões de checkpoint; seu pontuador é defensivo — qualquer falha de previsão (assinatura incorreta, formato de saída inesperado, OOM) é capturada e o `deqa_score` da imagem fica `NULL` em vez de travar o escaneamento.

---

## Face Detection

Configurações de detecção de faces do InsightFace.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false,
    "eyes_closed_max": 4.0,
    "poor_expression_min": 4.0,
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `min_confidence_percent` | `65` | Confiança mínima de detecção |
| `min_face_size` | `20` | Tamanho mínimo da face em pixels |
| `blink_ear_threshold` | `0.28` | Razão de Aspecto do Olho (EAR) para detecção de piscar |
| `min_faces_for_group` | `4` | Mínimo de faces para classificar como retrato de grupo (recalculado em `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Override opcional (ausente no arquivo distribuído; padrão `false` no código). Carrega o módulo `landmark_3d_68` do InsightFace para extração da pose da cabeça (yaw/pitch/roll). Custa ~5MB extras de pesos ONNX. Atualmente informativo; futuros refinamentos de perfil/silhueta vão ler isto. |
| `eyes_closed_max` | `4.0` | Pontuação de olhos-abertos por rosto (0–10) igual ou abaixo da qual o laboratório de triagem sinaliza um rosto como piscando. Controla os anéis de rosto vermelho/laranja/verde e o controle deslizante de limiar de olhos (movido de uma constante fixa no código) |
| `poor_expression_min` | `4.0` | Pontuação de sorriso/expressão por rosto (0–10) abaixo da qual o laboratório sinaliza uma expressão fraca. Controla o anel de rosto de expressão e o controle deslizante (movido de uma constante fixa no código) |
| `blendshapes.enabled` | `true` | Usa as pontuações de blendshape do MediaPipe (baseadas em aparência) para `eyes_open_score` / `smile_score` por rosto quando o MediaPipe e o pacote `face_landmarker.task` estão disponíveis; quando `true`, elas substituem as pontuações de geometria de pontos de referência, caso contrário o retorno geométrico é executado automaticamente. Dependência opcional — instale com `pip install mediapipe==0.10.35 --no-deps` (nunca um simples `pip install mediapipe`). Veja [FACE_RECOGNITION.md](FACE_RECOGNITION.md#sinais-de-expressão-por-rosto-olhos-abertos--sorriso). |
| `blendshapes.min_crop_size` | `192` | Rostos cujo recorte com margem seja menor que este valor (px, lado mais curto) recorrem à pontuação geométrica em vez de ampliar um rosto minúsculo |

---

## Face Clustering

Agrupamento HDBSCAN para reconhecimento de faces.

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "auto_merge_distance_percent": 15,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "merge_threshold": 0.6,
    "chunk_size": 10000
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Ativa o agrupamento de faces |
| `min_faces_per_person` | `2` | Mínimo de fotos por pessoa |
| `min_samples` | `2` | Parâmetro min_samples do HDBSCAN |
| `auto_merge_distance_percent` | `15` | Mescla automaticamente dentro desta distância |
| `clustering_algorithm` | `"best"` | Algoritmo HDBSCAN |
| `leaf_size` | `40` | Tamanho da folha da árvore (apenas CPU) |
| `use_gpu` | `"auto"` | Modo de GPU: `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Similaridade de centroide para correspondência |
| `chunk_size` | `10000` | Tamanho do bloco de processamento |

**Algoritmos de agrupamento:**

| Algoritmo | Complexidade | Melhor Para |
|-----------|--------------|-------------|
| `boruvka_balltree` | O(n log n) | Dados de alta dimensionalidade (recomendado) |
| `boruvka_kdtree` | O(n log n) | Dados de baixa dimensionalidade |
| `prims_balltree` | O(n²) | Memória limitada, alta dimensionalidade |
| `prims_kdtree` | O(n²) | Memória limitada, baixa dimensionalidade |
| `best` | Auto | Deixa o HDBSCAN decidir |

---

## Face Processing

Controla a extração de faces e a geração de miniaturas.

```json
{
  "face_processing": {
    "crop_padding": 0.3,
    "use_db_thumbnails": true,
    "face_thumbnail_size": 640,
    "face_thumbnail_quality": 90,
    "extract_workers": 2,
    "extract_batch_size": 16,
    "refill_workers": 4,
    "refill_batch_size": 100,
    "auto_tuning": {
      "enabled": true,
      "memory_limit_percent": 80,
      "min_batch_size": 8,
      "monitor_interval_seconds": 5
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `crop_padding` | `0.3` | Razão de margem para recortes de face |
| `use_db_thumbnails` | `true` | Usa as miniaturas armazenadas |
| `face_thumbnail_size` | `640` | Tamanho da miniatura em pixels |
| `face_thumbnail_quality` | `90` | Qualidade JPEG |
| `extract_workers` | `2` | Workers de extração paralelos |
| `extract_batch_size` | `16` | Tamanho do lote de extração |
| `refill_workers` | `4` | Workers de reabastecimento de miniaturas |
| `refill_batch_size` | `100` | Tamanho do lote de reabastecimento |
| **auto_tuning** | | |
| `enabled` | `true` | Ativa o ajuste baseado em memória |
| `memory_limit_percent` | `80` | Limite de uso de memória |
| `min_batch_size` | `8` | Tamanho mínimo do lote |
| `monitor_interval_seconds` | `5` | Intervalo de verificação |

---

## Monochrome Detection

Detecção de fotos em preto e branco.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `saturation_threshold_percent` | `5` | Saturação média < 5% = monocromático |

---

## Tagging

Configurações gerais de tagging. O modelo de tagging é configurado por perfil em `models.profiles.*.tagging_model`.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Ativa o tagging |
| `max_tags` | `5` | Máximo de tags por foto |

**Nota:** Configurações específicas do CLIP, como `similarity_threshold_percent`, ficam na seção `models.clip`.

### Modelos de Tagging Disponíveis

Configurados via `models.profiles.*.tagging_model`:

| Modelo | VRAM | Estilo de Tag | Notas |
|--------|------|---------------|-------|
| `clip` | 0 (reutiliza embeddings) | Clima/atmosfera (dramatic, golden_hour, vintage) | Sem carga extra de modelo; detecção de objetos menos literal |
| `qwen3.5-2b` | ~4GB | Cenas estruturadas (landscape, architecture, reflection) | Requer transformers + VRAM extra |
| `qwen3.5-4b` | ~8GB | Cenas detalhadas com nuance | VRAM maior; inferência mais lenta |

### Modelos de Tagging Padrão por Perfil

| Perfil | Modelo de Tagging | Modelo de Embedding |
|--------|-------------------|---------------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Repetindo o Tagging de Fotos

```bash
python facet.py --recompute-tags       # Refaz as tags usando o modelo configurado por perfil
python facet.py --recompute-tags-vlm   # Refaz as tags usando o tagger VLM
```

---

## Standalone Tags

Tags com listas de sinônimos que não estão vinculadas a nenhuma categoria específica. Elas ficam disponíveis para todas as fotos independentemente da categoria atribuída. Cada chave é o nome da tag; o valor é uma lista de sinônimos para correspondência CLIP/VLM.

```json
{
  "standalone_tags": {
    "bokeh": ["bokeh", "shallow depth of field", "background blur", "out of focus"],
    "surreal": ["surreal", "dreamlike", "fantasy", "composite", "double exposure"],
    "flat_lay": ["flat lay", "overhead shot", "top down", "bird's eye product"],
    "golden_hour": ["golden hour", "magic hour", "warm light", "sunset light"],
    "portrait_tag": ["portrait", "headshot", "face portrait", "close-up portrait"]
  }
}
```

Adicione novas tags independentes fornecendo uma chave e uma lista de sinônimos. As tags definidas aqui são mescladas com as tags específicas de categoria para formar o vocabulário completo de tags.

---

## Analysis

Limiares para `--compute-recommendations`.

```json
{
  "analysis": {
    "aesthetic_max_threshold": 9.0,
    "aesthetic_target": 9.5,
    "quality_avg_threshold": 7.5,
    "quality_weight_threshold_percent": 10,
    "correlation_dominant_threshold": 0.5,
    "category_min_samples": 50,
    "category_imbalance_threshold": 0.5,
    "score_clustering_std_threshold": 1.0,
    "top_score_threshold": 8.5,
    "exposure_avg_threshold": 8.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `aesthetic_max_threshold` | `9.0` | Avisa se a estética máxima estiver abaixo disso |
| `aesthetic_target` | `9.5` | Meta para aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Limiar de qualidade "alto valor" |
| `quality_weight_threshold_percent` | `10` | Avisa se o peso de qualidade ≤ este valor |
| `correlation_dominant_threshold` | `0.5` | Aviso de "sinal dominante" |
| `category_min_samples` | `50` | Mínimo de fotos por categoria |
| `category_imbalance_threshold` | `0.5` | Aviso de diferença de pontuação |
| `score_clustering_std_threshold` | `1.0` | Avisa se o desvio padrão < este valor |
| `top_score_threshold` | `8.5` | Avisa se o agregado máximo < este valor |
| `exposure_avg_threshold` | `8.0` | Avisa se a exposição média > este valor |

---

## Viewer

Exibição e comportamento da galeria web.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "learning",
      "candidate_pool_size": 200,
      "show_current_scores": true
    },
    "sort_options": { ... },
    "pagination": {
      "default_per_page": 64
    },
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    },
    "persons": {
      "needs_naming_min_faces": 5
    },
    "raw_processor": {
      "backend": "rawpy",
      "darktable": {
        "executable": "darktable-cli",
        "hq": true,
        "width": null,
        "height": null,
        "extra_args": [],
        "cull_styles": [],
        "preview_max_edge": 1440,
        "preview_timeout_seconds": 60
      }
    },
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96,
      "thumbnail_slider": {
        "min_px": 120,
        "max_px": 400,
        "default_px": 168,
        "step_px": 8
      }
    },
    "face_thumbnails": {
      "output_size_px": 64,
      "jpeg_quality": 80,
      "crop_padding_ratio": 0.2,
      "min_crop_size_px": 20
    },
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    },
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      },
      "low_light_max_luminance": 0.2
    },
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "tooltip_mode": "hover",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 60,
    "notification_duration_ms": 2000,
    "moment_confidence_min": 0,
    "path_mapping": {}
  }
}
```

> **Nota:** `sort_options` (elidido como `{ ... }` acima) mapeia colunas do banco de dados para rótulos de menu suspenso e raramente é editado. O grupo **Conteúdo** inclui uma ordenação `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (NULLs ao final).

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `default_category` | `""` | Filtro de categoria padrão |
| `edition_password` | `""` | Senha para desbloquear o modo de edição (vazio = desativado) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Mínimo para otimização |
| `pair_selection_strategy` | `"learning"` | Estratégia de pares: `learning` (partida a frio por diversidade de embeddings + discordância de classificação uma vez treinado), `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Conjunto aleatório de candidatos dentro do qual a estratégia `learning` amostra os pares |
| `show_current_scores` | `true` | Mostra as pontuações durante a comparação |
| **pagination** | | |
| `default_per_page` | `64` | Fotos por página |
| **dropdowns** | | |
| `max_cameras` | `50` | Máximo de câmeras no menu suspenso |
| `max_lenses` | `50` | Máximo de lentes |
| `max_persons` | `50` | Máximo de pessoas |
| `max_tags` | `20` | Máximo de tags |
| `min_photos_for_person` | `10` | Oculta do menu suspenso pessoas com menos fotos |
| **persons** | | |
| `needs_naming_min_faces` | `5` | face_count mínimo para que um cluster auto-agrupado apareça na seção "Precisa de nome" de `/persons` |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nome do binário darktable-cli ou caminho absoluto |
| `darktable.profiles` | `[]` | Array de perfis de exportação darktable nomeados (veja abaixo) |
| `darktable.profiles[].name` | *(obrigatório)* | Nome de exibição do perfil (usado no menu de download e no parâmetro `profile` da API) |
| `darktable.profiles[].hq` | `true` | Passa `--hq true` para exportação de alta qualidade |
| `darktable.profiles[].width` | *(omitir)* | Largura máxima de saída (omita para resolução total) |
| `darktable.profiles[].height` | *(omitir)* | Altura máxima de saída (omita para resolução total) |
| `darktable.profiles[].style` | *(omitir)* | Nome do estilo darktable aplicado durante a exportação (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | Quando `false`, passa `--apply-custom-presets false` para que apenas o `style` explícito seja renderizado (e não os presets aplicados automaticamente) |
| `darktable.profiles[].extra_args` | `[]` | Argumentos de CLI adicionais (ex.: `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | Estilos darktable nomeados oferecidos como pré-visualização editada no estúdio de seleção (`GET /api/photo/cull_preview`). Vazio = o seletor de estilo fica oculto. Cada estilo **tem de já existir** na configuração darktable do utilizador que executa o visualizador. O nome é passado tal como está para `--style`. |
| `darktable.cull_styles[].name` | *(obrigatório)* | Nome do estilo darktable (passado a `--style` e validado pelo endpoint) |
| `darktable.cull_styles[].label_key` | *(name)* | Chave i18n opcional para o rótulo do menu (predefinição: o nome do estilo) |
| `darktable.preview_max_edge` | `1440` | Borda máxima (px) do render da pré-visualização de seleção |
| `darktable.preview_timeout_seconds` | `60` | Tempo limite do darktable-cli por render de pré-visualização |
| **display** | | |
| `tags_per_photo` | `4` | Tags exibidas nos cartões |
| `card_width_px` | `168` | Largura do cartão |
| `image_width_px` | `160` | Largura da imagem |
| `image_jpeg_quality` | `96` | Qualidade JPEG para conversão de RAW/HEIF em `/api/download` e `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Tamanho mínimo de miniatura (px) |
| `thumbnail_slider.max_px` | `400` | Tamanho máximo de miniatura (px) |
| `thumbnail_slider.default_px` | `168` | Tamanho padrão de miniatura (px) |
| `thumbnail_slider.step_px` | `8` | Incremento de passo do controle deslizante (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Tamanho da miniatura |
| `jpeg_quality` | `80` | Qualidade JPEG |
| `crop_padding_ratio` | `0.2` | Margem da face |
| `min_crop_size_px` | `20` | Tamanho mínimo do recorte |
| **quality_thresholds** | | |
| `good` | `6` | Limiar de "Bom" |
| `great` | `7` | Limiar de "Ótimo" |
| `excellent` | `8` | Limiar de "Excelente" |
| `best` | `9` | Limiar de "Melhor" |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Mínimo de Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Razão de face para os pesos |
| `low_light_max_luminance` | `0.2` | Limiar de pouca luz |
| **defaults** | | |
| `type` | `""` | Filtro de tipo de foto padrão (ex.: `"portraits"`, `"landscapes"`, ou `""` para Todas) |
| `sort` | `"aggregate"` | Coluna de ordenação padrão |
| `sort_direction` | `"DESC"` | Direção de ordenação padrão (`"ASC"` ou `"DESC"`) |
| `hide_blinks` | `true` | Oculta fotos com piscar por padrão |
| `hide_bursts` | `true` | Mostra apenas a melhor da rajada por padrão |
| `hide_duplicates` | `true` | Oculta fotos duplicadas que não sejam a principal por padrão |
| `hide_details` | `true` | Oculta os detalhes da foto nos cartões por padrão |
| `tooltip_mode` | `"hover"` | Gatilho do tooltip: `"hover"`, `"click"` ou `"off"`. Substitui o antigo booleano `hide_tooltip`. |
| `hide_rejected` | `true` | Oculta fotos rejeitadas por padrão |
| `gallery_mode` | `"mosaic"` | Layout padrão da galeria (`"grid"` ou `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origens permitidas de CORS para o servidor FastAPI. Adicione seu domínio ou URL de proxy reverso ao hospedar remotamente. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(padrão seguro para SPA)_ | Valor do cabeçalho Content-Security-Policy. Por padrão, uma política que permite os recursos próprios da SPA (script/estilo de tema inline, Google Fonts, tiles do OpenStreetMap, API de mesma origem). Defina como `""` para desativar, ou forneça uma política mais estrita. |
| `security_headers.hsts` | `false` | Envia `Strict-Transport-Security`. Habilite apenas quando o visualizador for servido por HTTPS. |
| **Outros** | | |
| `cache_ttl_seconds` | `60` | TTL do cache de consultas |
| `notification_duration_ms` | `2000` | Duração do toast |
| `moment_confidence_min` | `0` | Abaixo deste posterior de `narrative_moment_confidence` armazenado (0–1), os rótulos de momento são renderizados esmaecidos com um sufixo "(incerto)" no cabeçalho de Cenas, no cabeçalho de grupo de cena da Triagem e na dica da foto na galeria. `0` = nunca esmaecer |

### Recursos

Ative/desative recursos opcionais para reduzir o uso de memória ou simplificar a interface:

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
      "show_rating_badge": true,
      "show_memories": true,
      "show_captions": true,
      "show_timeline": true,
      "show_map": true,
      "show_scenes": true,
      "show_my_taste": true
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `show_similar_button` | `true` | Mostra o botão "Encontrar Similares" nos cartões de foto (usa numpy para similaridade CLIP) |
| `show_merge_suggestions` | `true` | Ativa o recurso de sugestões de mesclagem na página de gerenciamento de pessoas |
| `show_rating_controls` | `true` | Mostra os controles de avaliação por estrelas e favoritos |
| `show_rating_badge` | `true` | Mostra o selo de avaliação nos cartões de foto |
| `show_scan_button` | `false` | Mostra o botão de disparo de escaneamento para usuários superadmin (requer GPU no host do visualizador) |
| `metrics_enabled` | `false` | Ativa o endpoint público Prometheus `GET /metrics`. Desligado por padrão — ele expõe contagens de fotos/pessoas/faces, tamanho do banco de dados e memória do processo; habilite apenas quando o endpoint for acessível pela rede do coletor, não pela internet pública. |
| `show_semantic_search` | `true` | Mostra a barra de busca semântica (busca de texto para imagem usando embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Mostra o recurso de álbuns (criar, gerenciar e navegar por álbuns de fotos) |
| `show_critique` | `true` | Mostra o botão de crítica por IA nos cartões de foto (detalhamento de pontuação baseado em regras) |
| `show_vlm_critique` | `true` | Ativa o modo de crítica com VLM (requer perfil de VRAM 16gb/24gb). O código recorre a `false` quando a chave está ausente. |
| `show_embed_metadata` | `true` | Mostra a ação por miniatura "Gravar metadados no arquivo" no modo de edição (embute avaliações/palavras-chave na imagem original via exiftool) |
| `show_memories` | `true` | Mostra o diálogo de memórias "Neste Dia" (fotos tiradas na mesma data em anos anteriores) |
| `show_captions` | `true` | Mostra as legendas geradas por IA nos cartões de foto |
| `show_timeline` | `true` | Mostra a visualização de linha do tempo para navegação cronológica com navegação por data |
| `show_map` | `true` | Mostra a visualização de mapa com localizações de fotos baseadas em GPS (requer Leaflet). O código recorre a `false` quando a chave está ausente. |
| `show_capsules` | `true` | Mostra a visualização de Cápsulas (diaporamas de fotos curados e agrupados por tema) |
| `show_folders` | `true` | Mostra a navegação por pastas da estrutura de diretórios das fotos |
| `show_scenes` | `true` | Mostra a visualização de Cenas (`/scenes`) que agrupa fotos principais de rajada em cenas cronológicas para seleção em ordem narrativa |
| `show_my_taste` | `true` | Mostra a ordenação "My Taste", baseada na pontuação aprendida do ranqueador pessoal, com um selo de confiança de cobertura/acurácia aprendida |
| `show_social_export` | `true` | Mostra o menu **Recorte social** (somente edição): recortes com reconhecimento do sujeito para proporções de redes sociais. Veja [Exportação social](#exportação-social) |
| `show_portfolio_export` | `true` | Mostra a ação de álbum **Exportar portefólio** (somente edição): galeria HTML estática autónoma. Veja [Exportação de portefólio](#exportação-de-portefólio) |
| `show_proofing` | `false` | Ativa a aprovação de cliente em álbuns compartilhados: um link de compartilhamento (mais um PIN opcional) permite que um cliente sem conta curta fotos e deixe comentários, que o dono do álbum revisa em um diálogo restrito à edição. Desativado por padrão. Veja [Aprovação de Cliente](#aprovação-de-cliente) |

**Otimização de memória:** Definir `show_similar_button: false` evita que o numpy seja carregado, reduzindo o consumo de memória do visualizador. O recurso de fotos similares calcula a similaridade de cosseno dos embeddings CLIP, o que requer numpy.

### Aprovação de Cliente

`viewer.features.show_proofing` (padrão `false`) transforma qualquer álbum compartilhado em uma superfície de aprovação de cliente. Um link de compartilhamento — opcionalmente protegido por `viewer.proofing.pin` — permite que um cliente sem conta troque o token de compartilhamento por uma sessão de curta duração e, então, curta fotos e deixe comentários. As escolhas ficam em uma tabela dedicada `album_client_picks`, limitadas às fotos daquele álbum e totalmente isoladas das avaliações do dono (elas nunca tocam `photos.is_favorite` / `user_preferences` e nunca treinam o ranqueador pessoal). O dono lê as escolhas em um diálogo restrito à edição no cartão do álbum.

```json
{
  "viewer": {
    "features": { "show_proofing": false },
    "proofing": {
      "pin": "",
      "session_minutes": 1440
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `features.show_proofing` | `false` | Interruptor mestre para a aprovação de cliente em álbuns compartilhados |
| `proofing.pin` | `""` | PIN opcional que um cliente deve inserir (com o token de compartilhamento) para abrir uma sessão de aprovação. Vazio = sem PIN. As verificações têm limite de taxa e usam comparação segura byte a byte |
| `proofing.session_minutes` | `1440` | Tempo de vida em minutos do token de sessão de aprovação de cliente (padrão 24h). As sessões também param no momento em que o álbum deixa de ser compartilhado ou a aprovação é desativada |

### Mapeamento de Caminhos

Mapeia caminhos do banco de dados para caminhos do sistema de arquivos local. Útil quando as fotos foram pontuadas em uma máquina (ex.: Windows com caminhos UNC) mas o visualizador roda em outra (ex.: NAS Linux com pontos de montagem).

```json
{
  "viewer": {
    "path_mapping": {
      "\\\\NAS\\Photos": "/mnt/photos",
      "D:\\Pictures": "/volume1/pictures"
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `path_mapping` | `{}` | Dicionário de prefixo de origem para prefixo de destino. Ao servir imagens em tamanho completo ou crítica VLM, os caminhos do banco de dados que começam com um prefixo de origem são reescritos para usar o prefixo de destino. |

**Como funciona:**
- Aplica-se apenas ao **ler arquivos do disco** (serviço de imagens em tamanho completo, downloads de arquivos, crítica VLM). Os caminhos do banco de dados nunca são modificados.
- A normalização de barra invertida/barra é tratada automaticamente: `\\NAS\Photos\img.jpg` e `//NAS/Photos/img.jpg` correspondem ambos.
- Os mapeamentos são avaliados em ordem; o primeiro prefixo correspondente vence.
- Os destinos de mapeamento de caminho são incluídos automaticamente na lista de permissões de diretórios de escaneamento para as verificações de segurança multiusuário.

**Exemplo:** Um banco de dados populado no Windows armazena caminhos como `\\NAS\Photos\2024\IMG_001.jpg`. No Linux, o mesmo compartilhamento é montado em `/mnt/nas/Photos`. Configure:

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Proteção por Senha

Proteção por senha opcional para o visualizador:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Quando definida, os usuários precisam se autenticar antes de acessar o visualizador.

### Desempenho do Visualizador

Sobrescreve as configurações globais de `performance` ao executar o visualizador. Útil para implantação em NAS com pouca memória, onde a pontuação precisa de muitos recursos mas o visualizador não.

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200,
      "face_cache_size": 50
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `mmap_size_mb` | *(global)* | Override do tamanho de mmap do SQLite para conexões do visualizador. `0` desativa o mmap. |
| `cache_size_mb` | *(global)* | Override do tamanho de cache do SQLite para conexões do visualizador |
| `pool_size` | `5` | Tamanho do pool de conexões (reduza para sistemas com pouca memória) |
| `thumbnail_cache_size` | `2000` | Máximo de entradas no cache em memória de redimensionamento de miniaturas |
| `face_cache_size` | `500` | Máximo de entradas no cache em memória de miniaturas de faces |

Quando não definido, o visualizador usa os valores globais de `performance`. Veja [Implantação](DEPLOYMENT.md) para as configurações de NAS recomendadas.

---

## Performance

Configurações de desempenho do banco de dados.

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

> **Nota:** `wal_checkpoint_minutes` é um override opcional e **não** está presente no bloco `performance` distribuído (que contém apenas `mmap_size_mb`, `cache_size_mb` e `slow_request_ms`). Adicione-o explicitamente para alterar o padrão de `30`.

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `mmap_size_mb` | `2048` | Tamanho de E/S mapeada em memória do SQLite |
| `cache_size_mb` | `128` | Tamanho do cache do SQLite |
| `wal_checkpoint_minutes` | `30` | Override opcional (ausente no arquivo distribuído). Intervalo em minutos para o `PRAGMA wal_checkpoint(TRUNCATE)` em segundo plano do visualizador. Evita o inchaço do WAL em implantações de longa duração. Defina como `0` para desativar. |
| `slow_request_ms` | `1000` | Requisições da API do visualizador mais lentas que esta quantidade de milissegundos são registradas em WARNING com um marcador `SLOW`. Defina como `0` para desativar. |

---

## Storage

Controla onde as miniaturas e os embeddings são armazenados. O padrão são colunas BLOB no banco de dados SQLite; o modo de sistema de arquivos os armazena como arquivos em disco, o que reduz o tamanho do banco de dados.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `mode` | `"database"` | Backend de armazenamento: `"database"` (BLOBs SQLite) ou `"filesystem"` (arquivos em disco) |
| `filesystem_path` | `"./storage"` | Diretório base para o modo de sistema de arquivos. As miniaturas são armazenadas em `<path>/thumbnails/` e os embeddings em `<path>/embeddings/`, organizados em subdiretórios por hash de conteúdo. |

**Detalhes do modo de sistema de arquivos:**
- Os arquivos são organizados pelo hash SHA-256 do caminho da foto, com subdiretórios de dois caracteres para evitar muitos arquivos em um único diretório (ex.: `thumbnails/a3/a3f8..._640.jpg`).
- Excluir uma foto remove todos os tamanhos de miniatura e arquivos de embedding associados.
- O diretório é criado automaticamente no primeiro uso.

---

## Plugins

Sistema de plugins orientado a eventos para reagir a eventos de pontuação. Os plugins podem ser módulos Python, webhooks ou ações integradas.

### Configuração

```json
{
  "plugins": {
    "enabled": true,
    "high_score_threshold": 8.0,
    "webhooks": [
      {
        "url": "https://example.com/hook",
        "events": ["on_score_complete", "on_high_score"],
        "min_score": 8.0
      }
    ],
    "actions": {
      "copy_high_scores": {
        "event": "on_high_score",
        "action": "copy_to_folder",
        "folder": "/path/to/best-photos",
        "min_score": 9.0
      }
    }
  }
}
```

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `enabled` | `false` | Interruptor mestre — quando falso, nenhum evento é emitido |
| `high_score_threshold` | `8.0` | Pontuação agregada mínima para disparar eventos `on_high_score` |
| `webhooks` | `[]` | Lista de endpoints de webhook que recebem cargas úteis JSON via POST |
| `actions` | `{}` | Ações integradas nomeadas disparadas por eventos |

### Eventos Suportados

| Evento | Gatilho | Carga útil |
|--------|---------|------------|
| `on_score_complete` | Após cada foto ser pontuada | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Quando uma foto entra no banco de dados | Igual a `on_score_complete` |
| `on_high_score` | Quando o agregado ≥ `high_score_threshold` | Igual a `on_score_complete` |
| `on_burst_detected` | Quando um grupo de rajada é identificado | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Escrevendo um Plugin

Coloque um arquivo `.py` no diretório `plugins/`. Defina funções nomeadas conforme os eventos que você deseja tratar:

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Veja `plugins/example_plugin.py.example` para a interface completa.

### Webhooks

Cada webhook recebe um POST JSON com proteção contra SSRF (endereços privados/loopback são bloqueados):

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/IMG_001.jpg",
    "aggregate": 9.2,
    "aesthetic": 9.5,
    "comp_score": 8.8,
    "category": "portrait",
    "tags": "person, outdoor"
  }
}
```

Opções de webhook: `url` (obrigatório), `events` (lista de nomes de eventos), `min_score` (agregado mínimo para disparar).

### Ações Integradas

| Ação | Descrição | Opções |
|------|-----------|--------|
| `copy_to_folder` | Copia a foto para uma pasta | `folder`, `min_score` |
| `send_notification` | Registra uma notificação | `min_score` |

### Endpoints da API

| Método | Caminho | Descrição |
|--------|---------|-----------|
| `GET` | `/api/plugins` | Lista os plugins, webhooks e ações carregados |
| `POST` | `/api/plugins/test-webhook` | Envia uma carga útil de teste para uma URL de webhook |

---

## Capsules

Diaporamas de fotos (slideshows) curados e agrupados por tema. As cápsulas são geradas automaticamente a partir da sua biblioteca de fotos e armazenadas em cache com um TTL configurável.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
    "mmr_moment_weight": 0.0,
    "freshness_hours": 24,
    "reverse_geocoding": true,
    "journey": {
      "min_distance_km": 50,
      "min_photos": 8,
      "time_gap_hours": 24
    },
    "faces_of": { "min_photos": 10 },
    "seasonal": { "min_photos": 10 },
    "golden": { "percentile": 99, "max_photos": 50 },
    "color_story": { "embedding_threshold": 0.75, "min_group_size": 8, "max_groups": 5 },
    "this_week_years_ago": { "min_photos_per_year": 3 },
    "monthly": { "min_photos": 8 },
    "yearly": { "min_photos": 20, "max_photos": 60 },
    "camera": { "min_photos": 15 },
    "tag_collection": { "min_photos": 15 },
    "seeded": {
      "num_seeds": 10,
      "min_photos": 8,
      "seed_lifetime_minutes": 1440,
      "time_window_days": 7,
      "embedding_threshold": 0.7,
      "location_radius_km": 30
    },
    "progress": { "min_improvement_pct": 5, "min_photos": 10, "period_months": 3 },
    "color_palette": { "min_photos": 8 },
    "rare_pair": { "max_shared_photos": 5, "min_score": 7.0, "min_photos": 3 }
  }
}
```

### Configurações Globais

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `min_aggregate` | `6.0` | Pontuação agregada mínima para que as fotos sejam incluídas nas cápsulas |
| `max_photos_per_capsule` | `40` | Máximo de fotos por cápsula (diversidade MMR aplicada acima de 5) |
| `max_photo_overlap` | `0.2` | Fração máxima de fotos compartilhadas entre duas cápsulas antes que a deduplicação remova uma |
| `mmr_lambda` | `0.5` | Peso de diversidade do MMR: 0=maximizar diversidade, 1=maximizar qualidade |
| `mmr_moment_weight` | `0.0` | Peso opcional que mescla o `narrative_moment_confidence` de cada foto na seleção MMR da cápsula. `0.0` = comportamento inalterado |
| `freshness_hours` | `24` | TTL do cache e período de rotação para fotos de capa e cápsulas com seed |
| `reverse_geocoding` | `true` | Ativa a geocodificação reversa offline para títulos de cápsulas de localização/jornada (requer o pacote `reverse_geocoder`) |

### Tipos de Cápsula

| Tipo | Descrição |
|------|-----------|
| `journey` | Viagens detectadas por agrupamento de GPS + lacunas temporais. Os títulos incluem o nome do destino quando a geocodificação está ativada. |
| `faces_of` | Melhores fotos de cada pessoa reconhecida |
| `seasonal` | Fotos agrupadas por estação + ano |
| `golden` | Top 1% por pontuação agregada |
| `color_story` | Grupos visualmente similares via agrupamento de embeddings CLIP |
| `this_week` | "Esta Semana, Anos Atrás" — "Neste Dia" estendido por ±3 dias |
| `location` | Clusters de fotos geotagueadas com nomes de lugares por geocodificação reversa |
| `person_pair` | Pares de pessoas nomeadas que aparecem juntas |
| `seeded` | Descoberta baseada em seed por tempo, similaridade, pessoa, tag, localização, clima |
| `progress` | "Sua Fotografia Está Melhorando" a partir de tendências trimestrais de pontuação |
| `color_palette` | "Cor do Mês" a partir de perfis de saturação/monocromático |
| `rare_pair` | Pares de pessoas pouco frequentes em fotos de alta pontuação |
| `favorites` | Fotos favoritadas agrupadas por ano e estação |

### Cápsulas Baseadas em Dimensão

Geradas automaticamente a partir das colunas do banco de dados:

| Dimensão | Agrupa Por |
|----------|------------|
| `year` | Ano extraído de date_taken |
| `month` | Ano-mês extraído de date_taken |
| `week` | Ano-semana extraído de date_taken |
| `camera` | Modelo da câmera |
| `lens` | Modelo da lente |
| `tag` | Tags da foto (requer a tabela `photo_tags`) |
| `day_of_week` | Dia da semana (domingo–sábado) |
| `composition` | Padrão de composição SAMP-Net (rule_of_thirds, horizontal, etc.) |
| `focal_range` | Faixas de distância focal: ultra wide (<24mm), wide (24–35mm), standard (36–70mm), portrait (71–135mm), telephoto (136–300mm), super telephoto (300mm+) |
| `category` | Categoria de conteúdo da foto (portrait, landscape, street, etc.) |
| `time_of_day` | Faixas de horário: golden morning, morning, midday, afternoon, golden evening, night |
| `star_rating` | Avaliações por estrelas do usuário (1–5 estrelas) |

Combinações entre dimensões também são geradas (ex.: camera × year, focal_range × category, category × year).

### Transições do Slideshow

Cada tipo de cápsula mapeia para uma transição de slide temática:

| Transição | Usada Por | Efeito |
|-----------|-----------|--------|
| `crossfade` | Padrão | Troca de opacidade em 300ms |
| `slide` | journey, location, this_week | Desliza da direita (500ms) |
| `zoom` | faces_of, color_story | Escala 1,05→1,0 com fade (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lento 1,0→1,08 ao longo da duração do slide |

### Geocodificação Reversa

As cápsulas de localização e jornada usam geocodificação reversa offline via pacote `reverse_geocoder` (conjunto de dados GeoNames local, ~30MB, sem chamadas de API). Os resultados são armazenados em cache na tabela `location_names` do banco de dados em resolução de grade de 0,1° (~11km).

Instale: `pip install reverse_geocoder`

Defina `"reverse_geocoding": false` para desativar e recorrer à exibição de coordenadas.

## Similarity Groups

Configurações do recurso de seleção de fotos similares por IA, que agrupa fotos visualmente similares usando embeddings CLIP/SigLIP:

```json
{
  "similarity_groups": {
    "default_threshold": 0.85,
    "min_group_size": 2,
    "max_photos": 10000,
    "max_group_size": 50
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `default_threshold` | `0.85` | Similaridade de cosseno mínima (0,0–1,0) para considerar duas fotos como visualmente similares. Valores menores produzem grupos maiores, porém com menos similaridade visual. |
| `min_group_size` | `2` | Número mínimo de fotos necessário para formar um grupo de similaridade |
| `max_photos` | `10000` | Máximo de fotos a carregar para o cálculo de similaridade (custo O(n²)). Aumente para bibliotecas maiores à custa do tempo de computação. |
| `max_group_size` | `50` | Máximo de fotos por grupo de similaridade. Grupos maiores são divididos para manter a interface utilizável. |

## Auto-Cull

Triagem automática de um botão só para o laboratório de triagem (`POST /api/culling/auto`, restrito à edição). Ela tria um escopo inteiro — todos os grupos, ou apenas rajadas / semelhantes / cenas, opcionalmente restrito a um álbum ou janela de datas — em uma única passagem. Cada grupo mantém sua melhor foto mais tudo dentro de uma margem derivada do rigor (o mesmo orçamento de fotos mantidas do controle deslizante do laboratório manual), com um piso mínimo por grupo, e rejeita o resto.

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `default_strictness` | `50` | Orçamento de fotos mantidas (0–100) usado quando a requisição omite `strictness`. Maior = manter menos fotos por grupo (margem mais estreita em torno da melhor do grupo) |
| `highlights_min` | `8.0` | Pontuação agregada mínima para que a melhor foto de um grupo seja reunida no álbum opcional **Highlights** quando uma triagem automática é aplicada (idempotente) |

`dry_run` vem ativado por padrão e retorna uma prévia de manter/rejeitar por grupo; uma aplicação também registra linhas de comparação `source='culling'` e dispara um re-treinamento automático. Veja [Visualizador Web — Triagem automática](VIEWER.md#triagem-automática).

## Perfis de seleção por gênero

Predefinições por gênero que agrupam todos os controles de seleção em um clique: esportes mantém apenas a foto mais nítida de uma longa sequência, casamentos mantêm mais variantes com olhos abertos como prioridade, shows relaxam os limiares de olhos/expressão, a vida selvagem remove por completo o filtro de rosto humano. A câmara escura de seleção mostra um seletor de predefinição.

```json
{
  "cull_profiles": {
    "default": "balanced",
    "profiles": {
      "balanced": { "label_key": "culling.profiles.balanced", "strictness": 50, "eyes_closed_max": 4.0, "poor_expression_min": 4.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wedding":  { "label_key": "culling.profiles.wedding",  "strictness": 35, "eyes_closed_max": 5.0, "poor_expression_min": 5.0, "keep_min_per_group": 2, "similarity_threshold": 90 },
      "sports":   { "label_key": "culling.profiles.sports",   "strictness": 85, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 80 },
      "concert":  { "label_key": "culling.profiles.concert",  "strictness": 55, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wildlife": { "label_key": "culling.profiles.wildlife", "strictness": 70, "eyes_closed_max": 0.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 82 }
    }
  }
}
```

| Configuração | Descrição |
|---|---|
| `default` | Id do perfil aplicado quando nenhum está armazenado no cliente |
| `profiles.<id>.label_key` | Caminho i18n do nome exibido da predefinição (`culling.profiles.*`) |
| `profiles.<id>.strictness` | Orçamento de seleção (0–100) injetado na margem de auto-seleção quando a predefinição está ativa |
| `profiles.<id>.eyes_closed_max` | Pontuação de olhos abertos (0–10) abaixo da qual um rosto conta como fechado — substitui `face_detection.eyes_closed_max` nos selos de rosto |
| `profiles.<id>.poor_expression_min` | Pontuação de expressão/sorriso (0–10) abaixo da qual um rosto conta como ruim — substitui `face_detection.poor_expression_min` |
| `profiles.<id>.keep_min_per_group` | Mínimo por grupo do conjunto mantido pela auto-seleção |
| `profiles.<id>.similarity_threshold` | Limiar de agrupamento por similaridade (porcentagem) aplicado pela câmara escura quando a predefinição é selecionada |

Endpoint (somente leitura): `GET /api/culling/profiles` retorna a lista ordenada de predefinições e o padrão. A requisição de auto-seleção (`POST /api/culling/auto`) e o lote por rosto (`POST /api/culling-group/faces`) aceitam um `profile` opcional; um `strictness`/`min_keep_per_group` explícito na requisição sempre prevalece sobre a predefinição.

## Scenes

Configurações da visualização de Cenas, que agrupa fotos principais de rajada em cenas cronológicas (divididas por lacunas no tempo de captura) para seleção em ordem narrativa:

```json
{
  "scenes": {
    "gap_minutes": 20.0,
    "min_size": 2,
    "max_photos": 5000,
    "max_scene_size": 60,
    "adaptive": true,
    "adaptive_k": 6.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `gap_minutes` | `20.0` | Uma nova cena começa quando passam mais que esta quantidade de minutos entre fotos principais de rajada consecutivas (o piso quando `adaptive` está ligado) |
| `min_size` | `2` | Mínimo de fotos para que uma cena seja exibida |
| `max_photos` | `5000` | Máximo de fotos principais de rajada carregadas para o agrupamento de cenas |
| `max_scene_size` | `60` | Uma cena maior que isto é subdividida recursivamente em suas maiores lacunas internas, para que um evento fotografado continuamente nunca colapse em uma única cena gigante |
| `adaptive` | `true` | Quando ligado, a lacuna efetiva se amplia para `adaptive_k × mediana` das lacunas consecutivas da sessão (aperta para fotografia rápida, afrouxa para férias esparsas) |
| `adaptive_k` | `6.0` | Multiplicador aplicado à lacuna mediana quando `adaptive` está ligado |
| `split_on_moment_change` | `false` | Quando ligado (e os momentos narrativos estão computados), subdivide um trecho de tempo onde o momento dominante muda e se mantém por `moment_split_min_run` quadros |
| `moment_split_min_run` | `4` | Histerese para `split_on_moment_change` — quantos quadros consecutivos um novo momento precisa persistir para forçar um limite |

## Narrative Moments

Rotulagem zero-shot do "momento" de cena/atividade de cada foto. O vocabulário **general** padrão cobre `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle` ou `other` — então funciona em qualquer biblioteca, não apenas em casamentos (`wedding` vem como um gênero opcional). Preenchido por `--detect-moments` (executado automaticamente ao final de cada escaneamento) e exibido como nomes de cenas e um filtro de galeria. Algo que nem o Narrative Select nem o AfterShoot fazem.

O sinal é **semântico de legenda** (caption-semantic): a legenda por IA de cada foto é codificada uma vez com a torre de texto e armazenada (a coluna `caption_embedding`); o momento é o melhor cosseno com **max-pooling** desse embedding de legenda contra os prompts de texto por momento. O embedding de imagem armazenado é o fallback quando uma foto não tem legenda. O texto da legenda corresponde aos prompts de momento ~2,4× de forma mais limpa do que o embedding de imagem bruto, então o sinal `caption` carrega limiares mais altos que o fallback `image`; cada um é ajustado por backend (os cossenos do open_clip ficam muito mais baixos que os do SigLIP). Os valores de `transformers` (SigLIP) vêm como padrões conservadores — reajuste-os se você usar um perfil SigLIP.

```json
{
  "narrative_moments": {
    "enabled": true,
    "prompt_template": "a photo of {desc}",
    "default_event_type": "general",
    "pooling": "max",
    "caption_min_confidence": 0,
    "thresholds": {
      "caption": {
        "open_clip": { "min_confidence": 0.30, "min_margin": 0.02 },
        "transformers": { "min_confidence": 0.12, "min_margin": 0.01 }
      },
      "image": {
        "open_clip": { "min_confidence": 0.20, "min_margin": 0.01 },
        "transformers": { "min_confidence": 0.10, "min_margin": 0.01 }
      }
    },
    "priors": { "enabled": true, "weight": 0.04 },
    "vlm_tiebreak": { "enabled": false, "min_confidence": 0.0, "min_margin": 0.04 },
    "transitions": { "stay_prob": 0.7, "forward_bias": 0.0, "weight": 0.3 },
    "event_types": { "general": { "beach": ["people at a sandy beach by the sea", "..."], "...": [] }, "wedding": { "vows": ["the couple exchanging vows at the altar", "..."] } }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Interruptor mestre; quando desligado, `--detect-moments` e o hook de escaneamento não fazem nada |
| `prompt_template` | `"a photo of {desc}"` | Invólucro aplicado a cada prompt antes da codificação |
| `default_event_type` | `"general"` | Qual vocabulário de `event_types` está ativo. `general` = 20 momentos de cena/atividade agnósticos; `wedding` vem como um gênero opcional |
| `pooling` | `"max"` | Pontuação por momento = o melhor cosseno de prompt individual (max-pool), mais discriminativo que a média |
| `caption_min_confidence` | `0` | Portão de qualidade de legenda: quando > 0, `--generate-captions` e o endpoint de legenda sob demanda ignoram fotos sem rótulo, `other`, ou abaixo desta confiança de momento armazenada. `0` = sem portão |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Abaixo deste cosseno top-1, uma foto é `other`. Indexado por **sinal** (`caption` vs `image`) e depois por backend — os cossenos de legenda ficam ~2,4× mais altos |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Diferença mínima de cosseno entre top-1/top-2; abaixo dela o quadro vira `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Ajustes L1 de face/tag que só desempatam quase-empates; `weight` limita cada ajuste à escala do cosseno |
| `priors.caption_tag_scale` | `0.25` | Reduz as regras `tag` no sinal caption (o L0 já codifica a legenda); as regras estruturais mantêm o peso total |
| `priors.rules` / `priors.event_types.<et>.rules` | (conjunto geral) | Regras declarativas `{kind, when, boost}` independentes do vocabulário; um `boost` para um momento ausente do vocabulário ativo é ignorado. As regras por `event_type` substituem a lista global. Referência completa dos predicados: doc em inglês |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Suavização L2 da linha do tempo (Viterbi): pesada em auto-laço, sem progressão adiante (o vocabulário agnóstico não tem ordem canônica), aplicada de forma leve (`weight=0` = sem suavização) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | Desempate L3 (agora ativo): quando habilitado nos perfis 16gb/24gb, apenas quadros de baixo posterior (abaixo de `min_confidence`) ou de baixa margem (abaixo de `min_margin`) são reclassificados pelo VLM do perfil durante `--detect-moments` / `--recompute-moments` |
| `event_types` | `general` + `wedding` | `{momento: [sinônimos de prompt]}` por tipo de evento; defina `default_event_type` para trocar de gênero ou adicionar o seu próprio |

> **Custo do backfill de legendas.** Os embeddings de legenda são computados uma vez e armazenados, então o cosseno por foto é gratuito depois disso. Um escaneamento codifica apenas seu punhado de novas legendas (barato, incremental), mas a primeira passagem completa sobre uma biblioteca existente codifica cada legenda — uma passagem direta pela torre de texto por legenda, rápida na GPU e ~horas na CPU. Execute `python facet.py --detect-moments` uma vez (GPU recomendada) para esse backfill; adicione `--limit N` para verificar primeiro em uma amostra.

**Descobrindo um vocabulário específico da biblioteca.** O conjunto `general` é um padrão sensato, mas você pode propor um vocabulário ajustado à *sua* biblioteca com `python facet.py --discover-moments`: ele agrupa os vetores `caption_embedding` armazenados (HDBSCAN), nomeia cada cluster a partir de suas legendas (uma palavra-chave mais as legendas mais próximas do centroide como prompts prontos) e grava o resultado como um bloco `event_types.discovered` em `scoring_config.discovered.json`. Revise-o, copie `discovered` para `event_types` acima, defina `default_event_type` como `discovered` e execute `--recompute-moments` para adotá-lo — a descoberta propõe, ela nunca reescreve a configuração ativa. `--discover-min-cluster-size N` controla a granularidade (menor = mais momentos, mais finos).

## Exportação social

Recortes com reconhecimento do sujeito para proporções de redes sociais (`GET /api/photo/social_crop`, restrito à edição). Cada predefinição recorta o original em resolução total para uma proporção alvo e o enquadra no sujeito detectado — o maior retângulo dessa proporção que cabe na imagem, centrado no sujeito com uma margem e limitado às bordas. A caixa do sujeito segue uma cadeia de fallback: a caixa de sujeito BiRefNet persistida (`photos.subject_bbox`) → a união das caixas de rostos detectados → um recorte centralizado simples. Veja [Visualizador web — Download](VIEWER.md#download).

```json
{
  "social_export": {
    "presets": {
      "square":       { "label_key": "social_export.presets.square",       "aspect": "1:1" },
      "portrait_4x5": { "label_key": "social_export.presets.portrait_4x5", "aspect": "4:5" },
      "story_9x16":   { "label_key": "social_export.presets.story_9x16",   "aspect": "9:16" }
    },
    "subject_margin_percent": 8,
    "jpeg_quality": 92
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | Caminho i18n com pontos para o nome exibido da predefinição (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Proporção alvo como `"l:a"` (ex.: `1:1`, `4:5`, `9:16`) |
| `subject_margin_percent` | `8` | Margem ao redor da caixa do sujeito (porcentagem do seu tamanho) antes de centralizar o recorte |
| `jpeg_quality` | `92` | Qualidade JPEG do recorte exportado |

Controlado por `viewer.features.show_social_export` (padrão `true`). A coluna `photos.subject_bbox` é escrita pela passagem de saliência na varredura e por `--recompute-saliency`; linhas varridas antes de existir recorrem automaticamente ao recorte por rostos ou centralizado.

## Exportação de portefólio

Exporte um álbum como uma galeria HTML estática e autónoma que um fotógrafo pode colocar em qualquer alojamento web — sem ferramenta externa (thumbsup/sigal) (`POST /api/albums/{album_id}/export-portfolio`, somente edição). O diretório gerado contém `index.html` (uma grelha de miniaturas responsiva apenas em CSS mais uma lightbox vanilla-JS integrada, com **zero** referências externas/CDN — totalmente offline), uma pasta `assets/` de JPEG com nomes sequenciais (nenhum caminho da biblioteca é divulgado) e um `manifest.json`. Cada foto usa o **original** em disco (reduzido para `max_edge`) quando legível e recorre à miniatura de 640 px armazenada quando o original está inacessível (partilhas de rede offline); a origem utilizada é registada por foto no manifesto. A geração é determinista e idempotente — uma reexportação reescreve apenas os seus próprios ficheiros.

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| Definição | Padrão | Descrição |
|-----------|--------|-----------|
| `max_photos` | `500` | Álbuns maiores são recusados com um 400 (a exportação é síncrona) |
| `max_edge` | `2048` | Limite do lado maior (px) para os originais exportados; o pedido pode substituí-lo (limitado 256–8000) |
| `jpeg_quality` | `88` | Qualidade JPEG das imagens exportadas |

O `target_dir` passa pela mesma lista de permissões que os endpoints de exportação copiar/mover (`viewer.export.allowed_target_dirs` mais os diretórios de varredura). Controlado por `viewer.features.show_portfolio_export` (padrão `true`).

## Moldura digital / Quiosque

Serve as «melhores fotos» curadas para dispositivos de quiosque sem início de sessão — molduras digitais inteligentes, painéis do Home Assistant, ecrãs ao estilo ImmichFrame / Immich-Kiosk — através de três endpoints anónimos com token estático (`GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`). O acesso é um **token de moldura** opaco e de longa duração; uma lista `tokens` vazia desativa toda a funcionalidade (cada endpoint devolve 404). As respostas nunca contêm caminhos de ficheiros — cada foto é identificada por um id assinado opaco derivado do `rowid` da linha.

```json
{
  "frame": {
    "tokens": [],
    "count": 20,
    "max_count": 100,
    "min_aggregate": 7.0,
    "max_edge": 1920,
    "favorites_only": false,
    "categories": []
  }
}
```

| Definição | Padrão | Descrição |
|-----------|--------|-----------|
| `tokens` | `[]` | Tokens de moldura opacos (lista). **Vazio = funcionalidade desativada (404).** Use cadeias aleatórias longas, uma por dispositivo; remova uma para a revogar. Gere uma com `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `count` | `20` | Número predefinido de fotos devolvidas por `/api/frame/photos` |
| `max_count` | `100` | Limite máximo do parâmetro de consulta `count` |
| `min_aggregate` | `7.0` | Pontuação agregada mínima para uma foto ser curada |
| `max_edge` | `1920` | Limite do lado maior (px) dos JPEG servidos; o parâmetro `max_edge` pode reduzi-lo mas nunca ultrapassá-lo |
| `favorites_only` | `false` | Se `true`, apenas as fotos favoritas são curadas |
| `categories` | `[]` | Lista de nomes de categorias permitidas (vazio = todas) |

Os tokens são comparados em tempo constante como bytes UTF-8, por isso um token em falta é 401 e um token errado ou não ASCII é 403 (nunca 500). A curadoria exclui as fotos rejeitadas, lixo (`junk_kind`) e com olhos fechados, e depois aplica o limiar de pontuação / favoritos / categorias; o conjunto devolvido é uma amostra aleatória ponderada pela pontuação.

Um token de moldura não é um login de usuário: ele não carrega nenhum `user_id` e é verificado contra toda a biblioteca, portanto, no [modo multiusuário](#users), ele ignora os `directories` privados de cada usuário e concede acesso de leitura às fotos de todos os usuários, não apenas a `shared_directories`. Emita tokens de moldura apenas em instalações onde cada usuário configurado esteja confortável com isso.

## Envio automático do telemóvel

Um endpoint **WebDAV** mínimo em `/dav` permite que apps de envio automático do telemóvel (PhotoSync e outras) enviem fotos para uma **pasta de entrada** (inbox) que o `facet.py --watch` pontua depois automaticamente — o padrão de sincronização móvel do PhotoPrism. Apenas infraestrutura de envio: nunca toca em sessões de utilizador nem em JWT. O acesso é HTTP Basic com **credenciais de dispositivo partilhado** (`username` / `password`), não uma conta de utilizador. Toda a árvore `/dav` devolve **404 enquanto estiver desativada** — a funcionalidade só fica ativa quando `username`, `password` e `inbox_dir` estão todos definidos. Cada operação é confinada a `inbox_dir` (traversal / caminhos absolutos / fuga por ligação simbólica são recusados), e os envios são gravados em disco de forma atómica com o limite `max_file_mb`.

```json
{
  "upload": {
    "username": "",
    "password": "",
    "inbox_dir": "",
    "max_file_mb": 500
  }
}
```

| Definição | Padrão | Descrição |
|-----------|--------|-----------|
| `username` | `""` | Nome de utilizador HTTP Basic (credencial de dispositivo partilhado). **Vazio = funcionalidade desativada (404).** |
| `password` | `""` | Palavra-passe HTTP Basic (credencial de dispositivo partilhado). **Vazio = funcionalidade desativada (404).** Use uma cadeia aleatória longa. |
| `inbox_dir` | `""` | Caminho absoluto da pasta de entrada. **Vazio = funcionalidade desativada (404).** Aponte-a para um dos diretórios analisados (ou um subdiretório) para que o `facet.py --watch` pontue os envios à medida que chegam. Criada a pedido. |
| `max_file_mb` | `500` | Limite de tamanho por ficheiro (MB); um envio que o exceda é abortado com `413` e não deixa qualquer ficheiro parcial. |

As credenciais são comparadas em tempo constante como bytes UTF-8; um cabeçalho `Authorization` ausente ou incorreto devolve um `401` com `WWW-Authenticate: Basic realm="Facet upload"`. Métodos implementados: `OPTIONS`, `PROPFIND` (profundidade 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD` (`LOCK`/`UNLOCK` não estão implementados). A receita PhotoSync e um teste rápido com `curl` estão descritos na documentação do Visualizador Web.

## Junk Sweep

Detector zero-shot para "lixo" não fotográfico — capturas de tela, documentos escaneados, recibos, memes, slides de apresentação — sobre o **embedding de imagem armazenado** (sem decodificação de imagem, sem passagem de modelo por imagem; o mesmo formato dos momentos narrativos sem a suavização temporal). Cada tipo carrega uma lista de prompts de texto; o embedding da foto é pontuado por cosseno contra cada prompt e agrupado por **máximo** (max-pooling) por tipo. Um conjunto de prompts de contraste `not_junk` condiciona a decisão: uma foto só é sinalizada quando o melhor tipo de lixo ultrapassa `min_confidence` E supera o melhor prompt `not_junk` por `min_margin` — caso contrário, é armazenada com a sentinela `not_junk` (avaliada, limpa). `NULL` significa "não avaliada": `--detect-junk` rotula apenas as linhas `NULL` (e roda automaticamente ao final da varredura), enquanto `--recompute-junk` reavalia a biblioteca inteira. Preenche `photos.junk_kind`; a fila de revisão **Limpeza de lixo** do visualizador ([VIEWER.md](VIEWER.md#limpeza-de-lixo)) a consome.

```json
{
  "junk_sweep": {
    "enabled": true,
    "prompt_template": "{desc}",
    "pooling": "max",
    "thresholds": {
      "open_clip": { "min_confidence": 0.2, "min_margin": 0.06 },
      "transformers": { "min_confidence": 0.1, "min_margin": 0.02 }
    },
    "kinds": {
      "screenshot": ["a screenshot of a phone user interface", "..."],
      "document": ["a scanned document", "..."],
      "receipt": ["a photo of a receipt", "..."],
      "meme": ["a meme with overlaid text", "..."],
      "slide": ["a presentation slide", "..."]
    },
    "not_junk_prompts": ["a natural photograph", "a candid photo of people", "..."]
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Executa a detecção de lixo durante `--detect-junk` / `--recompute-junk` e ao final da varredura |
| `prompt_template` | `"{desc}"` | String de formato aplicada a cada prompt (`{desc}` = o prompt); identidade por padrão, já que os prompts são frases completas |
| `pooling` | `"max"` | Agrupa os cossenos por prompt em uma pontuação por tipo, via `max` (melhor prompt individual, mais discriminante) ou `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Cosseno mínimo com max-pooling para que o melhor tipo de lixo seja considerado (os cossenos de CLIP/`open_clip` são mais baixos que os de SigLIP/`transformers`, daí um limiar próprio por backend) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Quanto o melhor tipo de lixo precisa superar o melhor prompt de contraste `not_junk` antes de a foto ser sinalizada |
| `kinds` | screenshot/document/receipt/meme/slide | `{tipo: [sinônimos de prompt]}`; adicione, remova ou renomeie tipos livremente — a coluna e a fila do visualizador seguem a configuração |
| `not_junk_prompts` | 6 prompts fotográficos | Conjunto de contraste que descreve fotografias reais; o filtro que mantém as fotos genuínas fora da fila |

## VLM Backend

Seleciona onde o modelo visão-linguagem de legendas/tags é executado. `local` (padrão) usa o caminho transformers Qwen em processo, incluído nos perfis de VRAM 16gb/24gb — nenhuma mudança para instalações existentes. Os dois backends remotos apontam o Facet para um servidor externo, de modo que legendagem e marcação por VLM funcionem nos **perfis legacy/8gb que não trazem VLM local**: quando um backend remoto é selecionado, os recursos de VLM deixam de depender do perfil de VRAM.

```json
{
  "vlm_backend": {
    "type": "local",
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen2.5vl:7b",
      "timeout_seconds": 120
    },
    "openai_compatible": {
      "base_url": "http://localhost:1234/v1",
      "api_key": "",
      "model": "qwen2.5-vl-7b",
      "timeout_seconds": 120
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `type` | `"local"` | Backend: `local` (transformers Qwen em processo), `ollama` (API REST nativa do Ollama) ou `openai_compatible` (qualquer endpoint de chat completions compatível com OpenAI — LM Studio, vLLM, OpenRouter) |
| `ollama.base_url` | `"http://localhost:11434"` | URL base do servidor Ollama; a imagem é enviada em base64 para `POST /api/generate` |
| `ollama.model` | `"qwen2.5vl:7b"` | Tag do modelo Ollama (precisa ser um modelo de visão já baixado no servidor) |
| `ollama.timeout_seconds` | `120` | Tempo limite por requisição para as chamadas ao Ollama |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | URL base compatível com OpenAI **incluindo o sufixo `/v1`**; as requisições vão para `{base_url}/chat/completions` com a imagem como URI de dados `image_url` |
| `openai_compatible.api_key` | `""` | Token bearer enviado como `Authorization: Bearer <chave>`; deixe vazio para servidores locais sem chave |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | Nome do modelo passado ao endpoint |
| `openai_compatible.timeout_seconds` | `120` | Tempo limite por requisição para as chamadas compatíveis com OpenAI |

O backend compartilhado alimenta a legendagem (`--generate-captions` e o endpoint sob demanda `/api/caption`), a crítica por VLM (`/api/critique?mode=vlm`), a remarcação por VLM (`--recompute-tags-vlm`) e o desempate por VLM dos momentos narrativos. Uma falha de requisição remota é registrada como falha por foto (log gravado, tags vazias / sem legenda) e nunca derruba a execução. A marcação durante a varredura ainda usa o marcador próprio do perfil; execute `--recompute-tags-vlm` para aplicar um backend remoto a uma biblioteca existente.

## AI Critique

Configuração de prompt para a crítica com VLM (perfis 16gb/24gb). A crítica injeta o detalhamento completo de regras, penalidades e EXIF em um prompt em escada configurável, apresenta a resposta como Observação / Avaliação / Sugestões e a armazena em cache por foto em `photos.vlm_critique` (traduzida sob demanda para `vlm_critique_translated`). Ela roda sobre a miniatura armazenada, então arquivos RAW são criticados corretamente em vez de falharem silenciosamente; `refresh` regenera.

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `critique.vlm.max_new_tokens` | `320` | Orçamento de tokens para a geração estruturada da crítica com VLM |

Veja [Visualizador Web — Crítica por IA](VIEWER.md#crítica-por-ia).

## Distortion Attributes

Rotulagem de distorções zero-shot, apenas informativa. `--recompute-distortions` pontua cada foto contra prompts contrastivos no estilo ExIQA sobre seu embedding CLIP/SigLIP armazenado e guarda os defeitos prováveis (desfoque de movimento, dominante de cor, nitidez excessiva, …) como uma coluna JSON informativa. Nunca alimenta o agregado; os rótulos aparecem como chips de aviso no diálogo de crítica.

```json
{
  "distortion_attributes": {
    "enabled": true,
    "top_n": 5,
    "thresholds": {
      "open_clip":    { "temperature": 0.02, "min_confidence": 0.6 },
      "transformers": { "temperature": 0.05, "min_confidence": 0.6 }
    },
    "vocabulary": {}
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Calcula os atributos de distorção durante `--recompute-distortions` |
| `top_n` | `5` | Número máximo de rótulos de distorção mantidos por foto |
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Temperatura do softmax sobre as pontuações dos prompts contrastivos, por backend de embedding (como em `narrative_moments`, os cossenos do open_clip e do transformers operam em escalas diferentes) |
| `thresholds.<backend>.min_confidence` | `0.6` | Probabilidade mínima para que um rótulo de distorção seja mantido |
| `vocabulary` | `{}` | Substituição opcional do conjunto de prompts de distorção embutido (`{atributo: [sinônimos de prompt]}`); vazio = padrões do módulo |

## Skin Tone

Naturalidade do tom de pele em retratos (apenas informativa). `--recompute-skin-tone` amostra o croma CIELAB das bochechas a partir das miniaturas de rosto + landmarks armazenados e mede sua distância CIEDE2000 de um locus de pele por temperatura de cor correlata, sinalizando retratos cuja pele desvia para verde / magenta / azul / amarelo. Nunca alimenta o agregado; o resultado aparece como uma nota de tom de pele no diálogo de crítica.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `cast_delta_threshold` | `12.0` | Delta CIEDE2000 mínimo entre o croma de pele medido e o locus de pele antes de uma dominante de cor ser sinalizada |

## Immich Sync

Sincronização unidirecional das avaliações por estrelas e favoritos do Facet para um servidor [Immich](https://immich.app/) por meio da API REST dele. Os ativos são resolvidos por `originalPath` através dos mapeamentos de prefixo de caminho configurados, em uma única passagem de busca em massa. Execute-a com `--immich-sync` (verifique antes com `--immich-test`); veja [Comandos — Immich Sync](COMMANDS.md#sincronização-com-o-immich).

```json
{
  "immich": {
    "url": "",
    "api_key": "",
    "path_map": [
      { "facet_prefix": "", "immich_prefix": "" }
    ],
    "push": {
      "ratings": true,
      "favorites": true,
      "top_picks_album": "",
      "top_picks_min_rating": 4
    },
    "timeout_seconds": 30
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `url` | `""` | URL base do servidor Immich (ex.: `http://nas:2283`) |
| `api_key` | `""` | Chave de API do Immich, enviada como o cabeçalho `x-api-key` |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Reescritas de prefixo dos caminhos do Facet para os valores de `originalPath` do Immich; o primeiro `facet_prefix` correspondente é trocado pelo seu `immich_prefix` ao resolver um ativo |
| `push.ratings` | `true` | Envia as avaliações por estrelas. A política segura de versão do Immich é respeitada — apenas 1–5 é gravado, nunca 0/−1 |
| `push.favorites` | `true` | Envia a marcação de favorito |
| `push.top_picks_album` | `""` | Nome opcional de álbum no Immich que reúne as fotos enviadas acima do limiar de avaliação. Vazio = sem álbum |
| `push.top_picks_min_rating` | `4` | Avaliação por estrelas mínima para que uma foto seja adicionada a `top_picks_album` |
| `timeout_seconds` | `30` | Timeout REST por requisição |

`--immich-sync` respeita `--dry-run` (resolve cada ativo mas não grava nada) e `--user` (envia as avaliações de `user_preferences` daquele usuário no modo multiusuário). Somente REST — o Facet nunca toca no banco de dados do Immich.

## Timeline

Configurações da visualização cronológica em linha do tempo:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `photos_per_group` | `30` | Número de fotos carregadas por grupo de data na visualização de linha do tempo. Valores maiores mostram mais fotos por data, mas aumentam o peso da página. |

## Map

Configurações da visualização de mapa interativo:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `cluster_zoom_threshold` | `10` | Nível de zoom em que marcadores individuais substituem os clusters. Valores menores mostram marcadores individuais mais cedo (mais detalhe em zoom mais amplo). Faixa: 1 (mundo) a 18 (rua). |

## Translation

Configurações para a tradução de legendas por IA via MarianMT:

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `target_language` | `"fr"` | Código do idioma de destino para `--translate-captions`. Suportados: `fr` (francês), `de` (alemão), `es` (espanhol), `it` (italiano), `pt` (português do Brasil). Usa os modelos MarianMT da Helsinki-NLP (CPU, sem GPU). |

## Aesthetic CLIP (R2)

Pontuação estética suplementar derivada dos embeddings CLIP/SigLIP em cache via projeção de texto. Os prompts são ajustáveis pelo usuário para benchmarking AVA — veja `scripts/benchmark_aesthetic.py` para medir o impacto no SRCC de qualquer alteração.

```json
{
  "aesthetic_clip": {
    "positive_prompts": [
      "a professional, high-quality photograph",
      "an aesthetically beautiful image",
      "a masterful, award-winning photograph",
      "a sharp, well-composed photograph",
      "a stunning, visually striking image"
    ],
    "negative_prompts": [
      "a low-quality, amateur photograph",
      "a blurry, poorly composed photograph",
      "an unattractive, mundane snapshot",
      "a noisy, badly lit photograph",
      "a boring, forgettable image"
    ]
  }
}
```

Arrays vazios recorrem aos padrões do módulo embutidos em `analyzers/aesthetic_clip.py`. Não ajuste estes sem rerodar o benchmark AVA — os padrões pontuam SRCC ~0,52 em `ava_test/` e mudanças podem facilmente regredir para ~0,30.

## Adicionando modelos alternativos de VLM tagger / crítica (R3)

A chave `tagging_model` de cada perfil de VRAM (ex.: `qwen3.5-2b`) mapeia para uma entrada de modelo na mesma seção `models`. Para experimentar um VLM diferente (Pixtral-12B, InternVL-2.5, etc.):

1. Adicione uma entrada de modelo sob `models`:
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Aponte um perfil para ele:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Execute `python facet.py --recompute-tags-vlm` para refazer as tags.

Sem necessidade de alterações de código. Valide a qualidade por meio de uma verificação lado a lado em ~30 fotos antes de promover para padrão.

## Share Secret

String hexadecimal de 64 caracteres gerada automaticamente para tokens de sessão/compartilhamento:

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Gerada automaticamente no primeiro uso se não estiver presente.
