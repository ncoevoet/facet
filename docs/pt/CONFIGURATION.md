# Referência de Configuração

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · **Português**

Todas as configurações estão em `scoring_config.json`. Após modificar, execute `python facet.py --recompute-average` para atualizar as pontuações (sem necessidade de GPU).

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
- [Detecção de Rostos](#face-detection)
- [Agrupamento de Rostos](#face-clustering)
- [Processamento de Rostos](#face-processing)
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

### Campos do usuário

| Campo | Tipo | Descrição |
|-------|------|-------------|
| `password_hash` | string | Hash PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`). Gerado pela CLI `--add-user`. |
| `display_name` | string | Exibido no cabeçalho da interface |
| `role` | string | `user`, `admin` ou `superadmin` |
| `directories` | array | Diretórios privados de fotos deste usuário |

### Diretórios compartilhados

A chave `shared_directories` (irmã dos objetos de usuário) lista os diretórios visíveis a todos os usuários.

### Perfis (roles)

| Perfil | Ver próprias + compartilhadas | Avaliar/favoritar | Gerenciar pessoas/rostos | Disparar escaneamentos |
|------|:-:|:-:|:-:|:-:|
| `user` | sim | sim | não | não |
| `admin` | sim | sim | sim | não |
| `superadmin` | sim | sim | sim | sim |

### Adicionando usuários

Os usuários são criados somente via CLI — não há interface ou API de registro:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Solicita a senha, grava o hash em scoring_config.json
```

Após adicionar um usuário, edite `scoring_config.json` para configurar seus `directories`.

### Compatibilidade retroativa

- Sem a chave `users` = modo de usuário único legado (comportamento inalterado)
- `viewer.password` e `viewer.edition_password` são ignorados no modo multiusuário
- As avaliações existentes na tabela `photos` permanecem para o modo de usuário único; use `--migrate-user-preferences` para copiá-las

---

## Scanning

Controla o comportamento do escaneamento de diretórios.

```json
{
  "scanning": {
    "skip_hidden_directories": true
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | Ignora diretórios que começam com `.` durante o escaneamento de fotos |

---

## Categories

Array de definições de categorias. Veja [Pontuação](SCORING.md) para a documentação detalhada das categorias.

Cada categoria possui:
- `name` - Identificador da categoria
- `priority` - Menor = maior prioridade (avaliada primeiro)
- `filters` - Condições de correspondência
- `weights` - Pesos das métricas de pontuação (devem somar 100)
- `modifiers` - Ajustes de comportamento
- `tags` - Vocabulário CLIP para correspondência baseada em tags

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
|---------|---------|-------------|
| `score_min` | `0.0` | Pontuação mínima possível |
| `score_max` | `10.0` | Pontuação máxima possível |
| `score_precision` | `2` | Casas decimais para as pontuações |

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
|---------|---------|-------------|
| `portrait_face_ratio_percent` | `5` | Rosto > 5% do quadro = retrato |
| `blink_penalty_percent` | `50` | Multiplicador de pontuação quando uma piscada é detectada (0,5x) |
| `night_luminance_threshold` | `0.15` | Luminância média abaixo deste valor = noite |
| `night_iso_threshold` | `3200` | ISO acima deste valor = pouca luz |
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
|---------|---------|-------------|
| `power_point_weight` | `2.0` | Peso para o posicionamento na regra dos terços |
| `line_weight` | `1.0` | Peso para as linhas-guia |

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
|---------|---------|-------------|
| `iso_sharpness_compensation` | `true` | Reduz a penalidade de nitidez para ISO alto |
| `aperture_isolation_boost` | `true` | Aumenta a isolação para aberturas grandes (f/1.4-f/2.8) |

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
|---------|---------|-------------|
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
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | Ruído acima deste valor aciona a penalidade |
| `noise_max_penalty_points` | `1.5` | Penalidade máxima de ruído |
| `noise_penalty_per_sigma` | `0.3` | Pontos por sigma acima do limiar |
| `bimodality_threshold` | `2.5` | Coeficiente de bimodalidade do histograma |
| `bimodality_penalty_points` | `0.5` | Penalidade para histogramas bimodais |
| `leading_lines_blend_percent` | `30` | Mescla no comp_score |
| `oversaturation_threshold` | `0.9` | Limiar de saturação média |
| `oversaturation_pixel_percent` | `5` | Reservado para detecção em nível de pixel |
| `oversaturation_penalty_points` | `0.5` | Penalidade de supersaturação |

**Fórmula da penalidade de ruído:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalization

Controla como as métricas brutas são escaladas para pontuações de 0 a 10.

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
|---------|---------|-------------|
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
|---------|---------|-------------|
| `vram_profile` | `"auto"` | Perfil ativo (`auto`, `legacy`, `8gb`, `16gb`, `24gb`) |
| `keep_in_ram` | `"auto"` | Manter os modelos na RAM entre os blocos de passagens múltiplas (`"auto"`, `"always"`, `"never"`). `auto` verifica a RAM disponível antes de fazer cache. |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modelos PyIQA a executar neste perfil (vazio em `legacy`) |
| `profiles.*.saliency_enabled` | `true` (16gb/24gb) | Executa a saliência de sujeito do BiRefNet neste perfil |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modelo de embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) ou `"open_clip"` (legado) |
| `clip.embedding_dim` | `1152` | Dimensões do embedding (1152 para SigLIP 2) |
| `clip.similarity_threshold_percent` | `8` | Similaridade de cosseno CLIP mínima para uma correspondência de tag |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modelo CLIP legado (perfis legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Pesos pré-treinados legados |
| `clip_legacy.embedding_dim` | `768` | Dimensões do embedding legado |
| `clip_legacy.similarity_threshold_percent` | `22` | Limiar de correspondência de tags para o CLIP legado |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Caminho HuggingFace (VLM de composição 24gb) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modelo de marcação de tags para o perfil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Imagens por lote de inferência do VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modelo de marcação de tags para o perfil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Imagens por lote de inferência do VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modelo de saliência BiRefNet |
| `saliency.resolution` | `1024` | Resolução de inferência |
| `saliency.mask_threshold` | `0.3` | Limiar sigmoide para a máscara binária do sujeito |
| `saliency.min_subject_pixels` | `50` | Mínimo de pixels do sujeito para que um sujeito seja considerado detectado |
| `samp_net.input_size` | `384` | Tamanho de entrada do modelo de composição |

### Detecção Automática de VRAM

Quando `vram_profile` é `"auto"` (padrão), o sistema detecta a VRAM de GPU disponível na inicialização e seleciona o maior perfil que couber:

| VRAM Detectada | Perfil Selecionado |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Sem GPU | `legacy` (usa a RAM do sistema) |

---

## Quality Assessment Models

Seleciona o modelo que pontua a qualidade/estética da imagem, por meio da biblioteca [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `model` | `"auto"` | Modelo de qualidade: `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` usa `topiq`. |
| `prefer_llm` | `false` | Prefere um avaliador baseado em LLM quando houver um disponível |

### Modelos de Qualidade Disponíveis

SRCC = Coeficiente de Correlação de Postos de Spearman no benchmark KonIQ-10k (1.0 = perfeito).

| Modelo | SRCC | VRAM | Notas |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Padrão (`auto`); backbone ResNet50 com atenção top-down |
| `hyperiqa` | 0.90 | ~2GB | Hyper-rede, adaptativa ao conteúdo |
| `dbcnn` | 0.90 | ~2GB | CNN de dois ramos (distorções sintéticas + autênticas) |
| `musiq` | 0.87 | ~2GB | Transformer multiescala; lida com qualquer resolução |
| `clipiqa+` | 0.86 | ~4GB | CLIP com prompts de qualidade aprendidos |
| `clip-mlp` | 0.76 | ~4GB | CLIP ViT-L-14 legado + cabeça MLP |

### Trocando de Modelo de Qualidade

1. Edite `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Pontue novamente as fotos existentes (opcional):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Processing

Configurações unificadas de processamento para o processamento em lote na GPU e o modo de passagens múltiplas.

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

### Conceitos-chave

**`gpu_batch_size`** - Quantas imagens são processadas em conjunto na GPU em uma única passagem direta. Limitado pela VRAM. Ajustado automaticamente: reduzido quando a memória da GPU excede o limite.

**`ram_chunk_size`** - Quantas imagens são mantidas em cache na RAM entre as passagens de modelo (apenas no modo de passagens múltiplas). Reduz a E/S de disco carregando as imagens uma vez por bloco. Limitado pela RAM do sistema. Ajustado automaticamente: reduzido quando a memória do sistema excede o limite.

### Referência das Configurações

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `mode` | `"auto"` | Modo de processamento: `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Imagens por lote de GPU (limitado pela VRAM) |
| `ram_chunk_size` | `32` | Imagens por bloco de RAM (passagens múltiplas) |
| `num_workers` | `4` | Threads de carregamento de imagens |
| `load_workers` | `num_workers` | Threads de carregamento de blocos em passagens múltiplas (limitado a 8, `1` = sequencial) |
| `raw_decode_concurrency` | `0` (auto) | Máximo de decodificações RAW simultâneas; dimensionado automaticamente a partir de CPU/RAM (1-4), `1` = totalmente serializado |
| `raw_decode_timeout_seconds` | `120` | Abandona uma decodificação RAW travada após este atraso (`0` = desativado); o escaneamento falha rapidamente após travamentos repetidos |
| `exif_prefetch` | `true` | Modo de passagem única: pré-busca o EXIF em segundo plano em vez de bloquear a thread da GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Ativa o ajuste automático |
| `monitor_interval_seconds` | `5` | Intervalo de verificação de recursos |
| `tuning_interval_images` | `32` | Reajusta a cada N imagens |
| `min_processing_workers` | `1` | Mínimo de threads de carregamento |
| `max_processing_workers` | `32` | Máximo de threads de carregamento |
| `min_gpu_batch_size` | `2` | Tamanho mínimo de lote de GPU |
| `max_gpu_batch_size` | `32` | Tamanho máximo de lote de GPU |
| `min_ram_chunk_size` | `10` | Tamanho mínimo de bloco de RAM |
| `max_ram_chunk_size` | `128` | Tamanho máximo de bloco de RAM |
| `memory_limit_percent` | `85` | Limite de uso de memória do sistema |
| `cpu_target_percent` | `85` | Alvo de uso de CPU |
| `metrics_print_interval_seconds` | `30` | Intervalo de impressão das estatísticas |
| **thumbnails** | | |
| `photo_size` | `640` | Tamanho da miniatura armazenada (pixels) |
| `photo_quality` | `80` | Qualidade JPEG da miniatura |
| `face_padding_ratio` | `0.3` | Margem em torno dos recortes de rosto |

### Modos de Processamento

| Modo | Descrição |
|------|-------------|
| `auto` | Seleciona automaticamente passagens múltiplas ou passagem única com base na VRAM |
| `multi-pass` | Carregamento sequencial de modelos (funciona com VRAM limitada) |
| `single-pass` | Todos os modelos carregados de uma vez (requer VRAM alta) |

### Como as Passagens Múltiplas Funcionam

Em vez de carregar todos os modelos de uma vez, as passagens múltiplas:

1. Carregam as imagens em blocos de RAM (padrão de `ram_chunk_size`: 32)
2. Para cada bloco, executam os modelos sequencialmente: carregar modelo → processar bloco → descarregar modelo
3. Combinam os resultados em uma passagem final de agregação

Cada imagem é carregada uma vez por bloco, e as passagens são agrupadas para caber na VRAM disponível, de modo que os VLMs maiores de marcação/composição rodem mesmo com VRAM limitada.

### Comportamento do Ajuste Automático

O sistema monitora o uso de recursos e ajusta:

| Métrica | Ação |
|--------|------|
| Memória da GPU > limite | Reduz `gpu_batch_size` em 25% |
| RAM do sistema > limite | Reduz `ram_chunk_size` em 25% |
| RAM do sistema < (limite - 20%) | Aumenta `ram_chunk_size` em 25% |
| CPU > alvo | Sugere menos workers |
| Timeouts de fila > 5% | Sugere mais workers |

### Agrupamento Dinâmico de Passagens

Quando a VRAM permite, vários modelos pequenos rodam juntos:

| VRAM | Passagem 1 | Passagem 2 |
|------|--------|--------|
| 8GB | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12GB | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16GB | CLIP + SAMP-Net + InsightFace + TOPIQ | VLM de marcação |
| 24GB+ | Todos os modelos juntos (passagem única) | - |

### Opções de CLI

```bash
# Padrão: passagens múltiplas automáticas com agrupamento ótimo
python facet.py /path/to/photos

# Forçar passagem única (todos os modelos carregados de uma vez)
python facet.py /path --single-pass

# Executar apenas uma passagem específica
python facet.py /path --pass quality       # Apenas TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (mérito estético)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (qualidade + distorção)
python facet.py /path --pass tags          # Apenas o marcador configurado
python facet.py /path --pass composition   # Apenas SAMP-Net
python facet.py /path --pass faces         # Apenas InsightFace
python facet.py /path --pass embeddings    # Apenas embeddings CLIP/SigLIP
python facet.py /path --pass saliency      # Saliência de sujeito BiRefNet

# Listar os modelos disponíveis
python facet.py --list-models
```

---

## Burst Detection

Agrupa fotos semelhantes tiradas em sequência rápida.

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
|---------|---------|-------------|
| `similarity_threshold_percent` | `70` | Limiar de similaridade de hash de imagem |
| `time_window_minutes` | `0.8` | Tempo máximo entre fotos |
| `rapid_burst_seconds` | `0.4` | Fotos dentro deste intervalo são agrupadas automaticamente |

---

## Burst Scoring

Pesos usados pela seleção de rajadas (culling) para calcular uma pontuação composta na escolha da melhor foto dentro de cada grupo de rajada. Os pesos devem somar 1,0.

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
|---------|---------|-------------|
| `weight_aggregate` | `0.4` | Peso da pontuação agregada geral |
| `weight_aesthetic` | `0.25` | Peso da pontuação de qualidade estética |
| `weight_sharpness` | `0.2` | Peso da pontuação de nitidez técnica |
| `weight_blink` | `0.15` | Peso de penalidade para piscadas detectadas (maior = penalidade mais forte) |

---

## Duplicate Detection

Detecta fotos duplicadas globalmente usando a comparação de hash perceptual (pHash).

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
|---------|---------|-------------|
| `similarity_threshold_percent` | `90` | Gate estrito de pHash (90% = distância de Hamming <= 6 de 64 bits); usado como único critério quando falta um embedding para qualquer uma das fotos |
| `prefilter_hamming` | `12` | Substituição opcional (ausente do arquivo fornecido). Gate de Hamming frouxo de estágio 1 para o conjunto de candidatos quando ambas as fotos têm embeddings (coagido a ser >= o gate estrito) |
| `embedding_cosine_threshold` | `0.90` | Substituição opcional (ausente do arquivo fornecido). Gate de cosseno SigLIP/CLIP de estágio 2: um candidato de pHash frouxo só é mesclado quando o cosseno >= este valor |

A detecção tem dois estágios: candidatos de pHash frouxo (recall) confirmados por um gate estrito de cosseno de embedding (precisão). Fotos sem um embedding recorrem ao critério estrito apenas de pHash, de modo que o comportamento permanece inalterado quando os embeddings estão ausentes.

Execute `python facet.py --detect-duplicates` para detectar e agrupar duplicatas. Execute `python facet.py --sweep-dedup-thresholds [labels.json]` para avaliar o gate de cosseno — com um JSON de rótulos ele imprime uma tabela de precisão/recall, caso contrário a distribuição de cosseno dos candidatos e quantas colisões de pHash estrito o gate rejeita.

---

## Extended IQA tier (optional)

Avaliadores de qualidade pesados/experimentais, **DESLIGADOS por padrão** e **nunca um substituto para o TOPIQ** — eles adicionam colunas suplementares apenas quando explicitamente habilitados. Quando habilitados, os avaliadores estendidos rodam **durante um escaneamento normal** e gravam suas próprias colunas; uma falha de carregamento/VRAM é registrada e a coluna fica como `NULL` (o escaneamento nunca é abortado).

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
|---------|---------|-----------------|--------|-------------|
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | IQA baseado em LLM Q-Align (apoiado em pyiqa). `"4bit"` (~6-8GB VRAM) é a escolha prática numa placa de 16GB; `"8bit"` ~12-14GB; precisão total (`true`) requer 16GB+. 4-/8-bit precisam de `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (cabeça SigLIP, ~2GB). Requer o pacote `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU 16GB+; ignorado e deixado como NULL caso contrário). |

**Instale as dependências opcionais** para tudo o que você habilitar: `pip install -e .[iqa-extended]` (adiciona `aesthetic-predictor-v2-5` + `bitsandbytes`), ou descomente as linhas correspondentes em `requirements.txt`. O próprio Q-Align acompanha o `pyiqa`; o DeQA-Score é baixado via `transformers`.

Quando habilitada, cada métrica é exposta ao agregado ponderado, mas assume peso 0 por padrão, de modo que `--recompute-average` é idêntico byte a byte até que você lhe atribua um peso. Execute `python facet.py --eval-iqa-srcc` para medir quão bem cada métrica classifica sua biblioteca em relação às suas próprias avaliações por estrelas.

**Exibição no visualizador.** Quando qualquer uma dessas colunas está preenchida, o visualizador mostra o valor no painel **Quality** dos detalhes da foto (`Q-Align`, `Aesthetic V2.5`, `DeQA`) e disponibiliza um controle deslizante de faixa correspondente na barra lateral de filtros da galeria em **Extended Quality** (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). Fotos escaneadas antes de a camada ser habilitada simplesmente têm `NULL` nessas colunas e não são afetadas pelos filtros.

**Robustez.** O DeQA-Score carrega código remoto `trust_remote_code` cuja assinatura de forward varia entre as revisões de checkpoint; seu avaliador é defensivo — qualquer falha de predição (assinatura errada, formato de saída inesperado, OOM) é capturada e o `deqa_score` da imagem fica como `NULL` em vez de travar o escaneamento.

---

## Face Detection

Configurações de detecção de rostos do InsightFace.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confiança mínima de detecção |
| `min_face_size` | `20` | Tamanho mínimo do rosto em pixels |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio para detecção de piscadas |
| `min_faces_for_group` | `4` | Mínimo de rostos para classificar como retrato em grupo (recalculado em `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Substituição opcional (ausente do arquivo fornecido; padrão do código `false`). Carrega o módulo `landmark_3d_68` do InsightFace para a extração de pose da cabeça (yaw/pitch/roll). Custa ~5MB extras de pesos ONNX. Atualmente informativo; refinamentos futuros de perfil/silhueta lerão isto. |

---

## Face Clustering

Agrupamento HDBSCAN para reconhecimento de rostos.

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
|---------|---------|-------------|
| `enabled` | `true` | Ativa o agrupamento de rostos |
| `min_faces_per_person` | `2` | Mínimo de fotos por pessoa |
| `min_samples` | `2` | Parâmetro min_samples do HDBSCAN |
| `auto_merge_distance_percent` | `15` | Mescla automaticamente dentro desta distância |
| `clustering_algorithm` | `"best"` | Algoritmo HDBSCAN |
| `leaf_size` | `40` | Tamanho da folha da árvore (apenas CPU) |
| `use_gpu` | `"auto"` | Modo de GPU: `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Similaridade de centroide para correspondência |
| `chunk_size` | `10000` | Tamanho do bloco de processamento |

**Algoritmos de agrupamento:**

| Algoritmo | Complexidade | Melhor para |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Dados de alta dimensão (recomendado) |
| `boruvka_kdtree` | O(n log n) | Dados de baixa dimensão |
| `prims_balltree` | O(n²) | Memória limitada, alta dimensão |
| `prims_kdtree` | O(n²) | Memória limitada, baixa dimensão |
| `best` | Auto | Deixar o HDBSCAN decidir |

---

## Face Processing

Controla a extração de rostos e a geração de miniaturas.

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
|---------|---------|-------------|
| `crop_padding` | `0.3` | Razão de margem para os recortes de rosto |
| `use_db_thumbnails` | `true` | Usa as miniaturas armazenadas |
| `face_thumbnail_size` | `640` | Tamanho da miniatura em pixels |
| `face_thumbnail_quality` | `90` | Qualidade JPEG |
| `extract_workers` | `2` | Workers de extração paralela |
| `extract_batch_size` | `16` | Tamanho do lote de extração |
| `refill_workers` | `4` | Workers de regeneração de miniaturas |
| `refill_batch_size` | `100` | Tamanho do lote de regeneração |
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
|---------|---------|-------------|
| `saturation_threshold_percent` | `5` | Saturação média < 5% = monocromático |

---

## Tagging

Configurações gerais de marcação de tags. O modelo de marcação é configurado por perfil em `models.profiles.*.tagging_model`.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `enabled` | `true` | Ativa a marcação de tags |
| `max_tags` | `5` | Máximo de tags por foto |

**Nota:** Configurações específicas do CLIP, como `similarity_threshold_percent`, estão na seção `models.clip`.

### Modelos de Marcação Disponíveis

Configurados via `models.profiles.*.tagging_model`:

| Modelo | VRAM | Estilo de Tag | Notas |
|-------|------|-----------|-------|
| `clip` | 0 (reutiliza embeddings) | Clima/atmosfera (dramatic, golden_hour, vintage) | Sem carga de modelo extra; detecção de objetos menos literal |
| `qwen3.5-2b` | ~4GB | Cenas estruturadas (landscape, architecture, reflection) | Requer transformers + VRAM extra |
| `qwen3.5-4b` | ~8GB | Cenas detalhadas com nuance | VRAM maior; inferência mais lenta |

### Modelos de Marcação Padrão por Perfil

| Perfil | Modelo de Marcação | Modelo de Embedding |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Remarcando Fotos

```bash
python facet.py --recompute-tags       # Remarca usando o modelo configurado por perfil
python facet.py --recompute-tags-vlm   # Remarca usando o marcador VLM
```

---

## Standalone Tags

Tags com listas de sinônimos que não estão vinculadas a nenhuma categoria específica. Elas estão disponíveis para todas as fotos, independentemente da categoria atribuída. Cada chave é o nome da tag; o valor é uma lista de sinônimos para correspondência CLIP/VLM.

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
|---------|---------|-------------|
| `aesthetic_max_threshold` | `9.0` | Avisa se a estética máxima ficar abaixo deste valor |
| `aesthetic_target` | `9.5` | Alvo para aesthetic_scale |
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
        "extra_args": []
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
    "path_mapping": {}
  }
}
```

> **Nota:** `sort_options` (omitido como `{ ... }` acima) mapeia colunas do banco de dados para rótulos do menu suspenso e raramente é editado.

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `default_category` | `""` | Filtro de categoria padrão |
| `edition_password` | `""` | Senha para desbloquear o modo de edição (vazio = desativado) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Mínimo para otimização |
| `pair_selection_strategy` | `"learning"` | Estratégia de pares: `learning` (início frio por diversidade de embeddings + desacordo de ranking depois de treinado), `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Pool aleatório de candidatos dentro do qual a estratégia `learning` amostra os pares |
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
| `needs_naming_min_faces` | `5` | face_count mínimo para que um agrupamento automático apareça na seção "Precisa de nome" de `/persons` |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nome do binário darktable-cli ou caminho absoluto |
| `darktable.profiles` | `[]` | Array de perfis de exportação darktable nomeados (veja abaixo) |
| `darktable.profiles[].name` | *(obrigatório)* | Nome de exibição do perfil (usado no menu de download e no parâmetro `profile` da API) |
| `darktable.profiles[].hq` | `true` | Passa `--hq true` para exportação de alta qualidade |
| `darktable.profiles[].width` | *(omitir)* | Largura máxima de saída (omitir para resolução completa) |
| `darktable.profiles[].height` | *(omitir)* | Altura máxima de saída (omitir para resolução completa) |
| `darktable.profiles[].style` | *(omitir)* | Nome do estilo darktable aplicado durante a exportação (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | Quando `false`, passa `--apply-custom-presets false` para que apenas o `style` explícito seja renderizado (e não as predefinições aplicadas automaticamente) |
| `darktable.profiles[].extra_args` | `[]` | Argumentos de CLI adicionais (ex.: `["--style-overwrite"]`) |
| **display** | | |
| `tags_per_photo` | `4` | Tags exibidas nos cartões |
| `card_width_px` | `168` | Largura do cartão |
| `image_width_px` | `160` | Largura da imagem |
| `image_jpeg_quality` | `96` | Qualidade JPEG para a conversão RAW/HEIF em `/api/download` e `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Tamanho mínimo da miniatura (px) |
| `thumbnail_slider.max_px` | `400` | Tamanho máximo da miniatura (px) |
| `thumbnail_slider.default_px` | `168` | Tamanho padrão da miniatura (px) |
| `thumbnail_slider.step_px` | `8` | Incremento do passo do controle deslizante (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Tamanho da miniatura |
| `jpeg_quality` | `80` | Qualidade JPEG |
| `crop_padding_ratio` | `0.2` | Margem do rosto |
| `min_crop_size_px` | `20` | Tamanho mínimo do recorte |
| **quality_thresholds** | | |
| `good` | `6` | Limiar "bom" |
| `great` | `7` | Limiar "ótimo" |
| `excellent` | `8` | Limiar "excelente" |
| `best` | `9` | Limiar "melhor" |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Mínimo do Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Razão de rosto para os pesos |
| `low_light_max_luminance` | `0.2` | Limiar de pouca luz |
| **defaults** | | |
| `type` | `""` | Filtro de tipo de foto padrão (ex.: `"portraits"`, `"landscapes"` ou `""` para Todas) |
| `sort` | `"aggregate"` | Coluna de ordenação padrão |
| `sort_direction` | `"DESC"` | Direção de ordenação padrão (`"ASC"` ou `"DESC"`) |
| `hide_blinks` | `true` | Oculta fotos com piscadas por padrão |
| `hide_bursts` | `true` | Mostra apenas a melhor da rajada por padrão |
| `hide_duplicates` | `true` | Oculta fotos duplicadas não principais por padrão |
| `hide_details` | `true` | Oculta os detalhes da foto nos cartões por padrão |
| `tooltip_mode` | `"hover"` | Gatilho do tooltip: `"hover"`, `"click"` ou `"off"`. Substitui o antigo booleano `hide_tooltip`. |
| `hide_rejected` | `true` | Oculta fotos rejeitadas por padrão |
| `gallery_mode` | `"mosaic"` | Layout padrão da galeria (`"grid"` ou `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origens permitidas por CORS para o servidor FastAPI. Adicione seu domínio ou URL de proxy reverso ao hospedar remotamente. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(padrão seguro para SPA)_ | Valor do cabeçalho Content-Security-Policy. O padrão é uma política que permite os próprios recursos da SPA (script/estilo de tema inline, Google Fonts, tiles do OpenStreetMap, API de mesma origem). Defina como `""` para desativar, ou forneça uma política mais estrita. |
| `security_headers.hsts` | `false` | Envia `Strict-Transport-Security`. Habilite apenas quando o visualizador for servido por HTTPS. |
| **Outros** | | |
| `cache_ttl_seconds` | `60` | TTL do cache de consultas |
| `notification_duration_ms` | `2000` | Duração do toast |

### Recursos

Ative ou desative recursos opcionais para reduzir o uso de memória ou simplificar a interface:

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
|---------|---------|-------------|
| `show_similar_button` | `true` | Mostra o botão "Encontrar semelhantes" nos cartões de foto (usa numpy para a similaridade CLIP) |
| `show_merge_suggestions` | `true` | Ativa o recurso de sugestões de mesclagem na página de gerenciamento de pessoas |
| `show_rating_controls` | `true` | Mostra os controles de avaliação por estrelas e favorito |
| `show_rating_badge` | `true` | Mostra o selo de avaliação nos cartões de foto |
| `show_scan_button` | `false` | Mostra o botão de disparar escaneamento para usuários superadmin (requer GPU no host do visualizador) |
| `metrics_enabled` | `false` | Ativa o endpoint público Prometheus `GET /metrics`. Desligado por padrão — ele expõe contagens de fotos/pessoas/rostos, tamanho do banco de dados e memória do processo; habilite apenas quando o endpoint estiver acessível a partir da rede do coletor, não da internet pública. |
| `show_semantic_search` | `true` | Mostra a barra de busca semântica (busca texto-para-imagem usando embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Mostra o recurso de álbuns (criar, gerenciar e navegar por álbuns de fotos) |
| `show_critique` | `true` | Mostra o botão de crítica por IA nos cartões de foto (detalhamento de pontuação baseado em regras) |
| `show_vlm_critique` | `true` | Ativa o modo de crítica com VLM (requer perfil de VRAM 16gb/24gb). O código recorre a `false` quando a chave está ausente. |
| `show_embed_metadata` | `true` | Mostra a ação "Gravar metadados no arquivo" por miniatura no modo de edição (incorpora avaliações/palavras-chave na imagem original via exiftool) |
| `show_memories` | `true` | Mostra o diálogo de memórias "Neste Dia" (fotos tiradas na mesma data em anos anteriores) |
| `show_captions` | `true` | Mostra as legendas geradas por IA nos cartões de foto |
| `show_timeline` | `true` | Mostra a visualização em linha do tempo para navegação cronológica com navegação por data |
| `show_map` | `true` | Mostra a visualização em mapa com localizações de fotos baseadas em GPS (requer Leaflet). O código recorre a `false` quando a chave está ausente. |
| `show_capsules` | `true` | Mostra a visualização de Cápsulas (diaporamas curados de fotos agrupadas por tema) |
| `show_folders` | `true` | Mostra a navegação baseada em pastas da estrutura de diretórios de fotos |
| `show_scenes` | `true` | Mostra a visualização de Cenas (`/scenes`) que agrupa fotos principais de rajada em cenas cronológicas para seleção em ordem narrativa |
| `show_my_taste` | `true` | Mostra a ordenação "Meu Gosto" apoiada na pontuação aprendida do classificador pessoal, com um selo de confiança de cobertura/precisão aprendidas |

**Otimização de memória:** Definir `show_similar_button: false` evita o carregamento do numpy, reduzindo o consumo de memória do visualizador. O recurso de fotos semelhantes calcula a similaridade de cosseno do embedding CLIP, o que requer numpy.

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
|---------|---------|-------------|
| `path_mapping` | `{}` | Dicionário de prefixo de origem para prefixo de destino. Ao servir imagens em tamanho completo ou crítica VLM, os caminhos do banco de dados que começam com um prefixo de origem são reescritos para usar o prefixo de destino. |

**Como funciona:**
- Aplica-se apenas ao **ler arquivos do disco** (serviço de imagem em tamanho completo, downloads de arquivos, crítica VLM). Os caminhos do banco de dados nunca são modificados.
- A normalização de barra invertida/barra normal é tratada automaticamente: `\\NAS\Photos\img.jpg` e `//NAS/Photos/img.jpg` correspondem ambos.
- Os mapeamentos são avaliados em ordem; o primeiro prefixo correspondente vence.
- Os alvos do mapeamento de caminhos são incluídos automaticamente na lista de permissões de diretórios de escaneamento para as verificações de segurança multiusuário.

**Exemplo:** Um banco de dados preenchido no Windows armazena caminhos como `\\NAS\Photos\2024\IMG_001.jpg`. No Linux, o mesmo compartilhamento é montado em `/mnt/nas/Photos`. Configure:

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

Quando definida, os usuários devem se autenticar antes de acessar o visualizador.

### Desempenho do Visualizador

Substitui as configurações globais de `performance` ao executar o visualizador. Útil para implantações em NAS de baixa memória, onde a pontuação precisa de muitos recursos, mas o visualizador não.

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
|---------|---------|-------------|
| `mmap_size_mb` | *(global)* | Substituição do tamanho de mmap do SQLite para as conexões do visualizador. `0` desativa o mmap. |
| `cache_size_mb` | *(global)* | Substituição do tamanho de cache do SQLite para as conexões do visualizador |
| `pool_size` | `5` | Tamanho do pool de conexões (reduza para sistemas de baixa memória) |
| `thumbnail_cache_size` | `2000` | Máximo de entradas no cache em memória de redimensionamento de miniaturas |
| `face_cache_size` | `500` | Máximo de entradas no cache em memória de miniaturas de rosto |

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

> **Nota:** `wal_checkpoint_minutes` é uma substituição opcional e **não** está presente no bloco `performance` fornecido (que contém apenas `mmap_size_mb`, `cache_size_mb` e `slow_request_ms`). Adicione-a explicitamente para alterar o padrão de `30`.

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | Tamanho da E/S mapeada em memória do SQLite |
| `cache_size_mb` | `128` | Tamanho do cache do SQLite |
| `wal_checkpoint_minutes` | `30` | Substituição opcional (ausente do arquivo fornecido). Intervalo em minutos para o `PRAGMA wal_checkpoint(TRUNCATE)` em segundo plano do visualizador. Evita o inchaço do WAL em implantações de longa duração. Defina como `0` para desativar. |
| `slow_request_ms` | `1000` | Requisições da API do visualizador mais lentas que este número de milissegundos são registradas em WARNING com um marcador `SLOW`. Defina como `0` para desativar. |

---

## Storage

Controla onde as miniaturas e os embeddings são armazenados. O padrão são colunas BLOB no banco de dados SQLite; o modo de sistema de arquivos os armazena como arquivos no disco, o que reduz o tamanho do banco de dados.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `mode` | `"database"` | Backend de armazenamento: `"database"` (BLOBs do SQLite) ou `"filesystem"` (arquivos no disco) |
| `filesystem_path` | `"./storage"` | Diretório base para o modo de sistema de arquivos. As miniaturas são armazenadas em `<path>/thumbnails/` e os embeddings em `<path>/embeddings/`, organizados em subdiretórios por hash de conteúdo. |

**Detalhes do modo de sistema de arquivos:**
- Os arquivos são organizados pelo hash SHA-256 do caminho da foto, com subdiretórios de dois caracteres para evitar arquivos demais em um único diretório (ex.: `thumbnails/a3/a3f8..._640.jpg`).
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
|-----|---------|-------------|
| `enabled` | `false` | Interruptor mestre — quando falso, nenhum evento é emitido |
| `high_score_threshold` | `8.0` | Pontuação agregada mínima para disparar eventos `on_high_score` |
| `webhooks` | `[]` | Lista de endpoints de webhook para receber payloads JSON via POST |
| `actions` | `{}` | Ações integradas nomeadas disparadas por eventos |

### Eventos Suportados

| Evento | Gatilho | Payload |
|-------|---------|---------|
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
|--------|-------------|---------|
| `copy_to_folder` | Copia a foto para uma pasta | `folder`, `min_score` |
| `send_notification` | Registra uma notificação | `min_score` |

### Endpoints da API

| Método | Caminho | Descrição |
|--------|------|-------------|
| `GET` | `/api/plugins` | Lista plugins, webhooks e ações carregados |
| `POST` | `/api/plugins/test-webhook` | Envia um payload de teste para uma URL de webhook |

---

## Capsules

Diaporamas (apresentações de slides) curados de fotos agrupadas por tema. As cápsulas são geradas automaticamente a partir da sua biblioteca de fotos e mantidas em cache com um TTL configurável.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
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
|---------|---------|-------------|
| `min_aggregate` | `6.0` | Pontuação agregada mínima para que as fotos sejam incluídas nas cápsulas |
| `max_photos_per_capsule` | `40` | Máximo de fotos por cápsula (diversidade MMR aplicada acima de 5) |
| `max_photo_overlap` | `0.2` | Fração máxima de fotos compartilhadas entre duas cápsulas antes que a deduplicação remova uma |
| `mmr_lambda` | `0.5` | Peso de diversidade MMR: 0=maximizar diversidade, 1=maximizar qualidade |
| `freshness_hours` | `24` | TTL do cache e período de rotação das fotos de capa e das cápsulas seeded |
| `reverse_geocoding` | `true` | Ativa a geocodificação reversa offline para os títulos das cápsulas de localização/jornada (requer o pacote `reverse_geocoder`) |

### Tipos de Cápsula

| Tipo | Descrição |
|------|-------------|
| `journey` | Viagens detectadas via agrupamento por GPS + lacunas temporais. Os títulos incluem o nome do destino quando a geocodificação está habilitada. |
| `faces_of` | Melhores fotos de cada pessoa reconhecida |
| `seasonal` | Fotos agrupadas por estação + ano |
| `golden` | Top 1% por pontuação agregada |
| `color_story` | Grupos visualmente semelhantes via agrupamento de embeddings CLIP |
| `this_week` | "Esta Semana, Anos Atrás" — Neste Dia estendido por ±3 dias |
| `location` | Grupos de fotos geolocalizadas com nomes de lugares por geocodificação reversa |
| `person_pair` | Pares de pessoas nomeadas que aparecem juntas |
| `seeded` | Descoberta baseada em sementes via tempo, similaridade, pessoa, tag, localização, clima |
| `progress` | "Sua Fotografia Está Melhorando" a partir das tendências trimestrais de pontuação |
| `color_palette` | "Cor do Mês" a partir dos perfis de saturação/monocromático |
| `rare_pair` | Pares de pessoas pouco frequentes em fotos de alta pontuação |
| `favorites` | Fotos favoritadas agrupadas por ano e estação |

### Cápsulas Baseadas em Dimensão

Geradas automaticamente a partir de colunas do banco de dados:

| Dimensão | Agrupa Por |
|-----------|-----------|
| `year` | Ano extraído de date_taken |
| `month` | Ano-mês extraído de date_taken |
| `week` | Ano-semana extraído de date_taken |
| `camera` | Modelo de câmera |
| `lens` | Modelo de lente |
| `tag` | Tags da foto (requer a tabela `photo_tags`) |
| `day_of_week` | Dia da semana (domingo–sábado) |
| `composition` | Padrão de composição SAMP-Net (rule_of_thirds, horizontal, etc.) |
| `focal_range` | Faixas de distância focal: ultra grande-angular (<24mm), grande-angular (24–35mm), padrão (36–70mm), retrato (71–135mm), teleobjetiva (136–300mm), super teleobjetiva (300mm+) |
| `category` | Categoria de conteúdo da foto (portrait, landscape, street, etc.) |
| `time_of_day` | Faixas de horário: manhã dourada, manhã, meio-dia, tarde, fim de tarde dourado, noite |
| `star_rating` | Avaliações por estrelas do usuário (1–5 estrelas) |

Combinações entre dimensões também são geradas (ex.: câmera × ano, focal_range × category, category × year).

### Transições de Slideshow

Cada tipo de cápsula é mapeado para uma transição de slide temática:

| Transição | Usada Por | Efeito |
|-----------|---------|--------|
| `crossfade` | Padrão | Troca de opacidade em 300ms |
| `slide` | journey, location, this_week | Desliza da direita (500ms) |
| `zoom` | faces_of, color_story | Escala 1.05→1.0 com fade (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lento 1.0→1.08 ao longo da duração do slide |

### Geocodificação Reversa

As cápsulas de localização e jornada usam geocodificação reversa offline via o pacote `reverse_geocoder` (conjunto de dados GeoNames local, ~30MB, sem chamadas de API). Os resultados são mantidos em cache na tabela `location_names` do banco de dados na resolução de grade de 0,1° (~11km).

Instalar: `pip install reverse_geocoder`

Defina `"reverse_geocoding": false` para desativar e recorrer à exibição de coordenadas.

## Similarity Groups

Configurações para o recurso de seleção (culling) de fotos semelhantes por IA, que agrupa fotos visualmente semelhantes usando embeddings CLIP/SigLIP:

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
|---------|---------|-------------|
| `default_threshold` | `0.85` | Similaridade de cosseno mínima (0,0–1,0) para considerar duas fotos como visualmente semelhantes. Valores menores produzem grupos maiores, mas com menos similaridade visual. |
| `min_group_size` | `2` | Número mínimo de fotos necessárias para formar um grupo de similaridade |
| `max_photos` | `10000` | Máximo de fotos a carregar para o cálculo de similaridade (custo O(n²)). Aumente para bibliotecas maiores à custa do tempo de computação. |
| `max_group_size` | `50` | Máximo de fotos por grupo de similaridade. Grupos maiores são divididos para manter a interface utilizável. |

## Scenes

Configurações para a visualização de Cenas, que agrupa fotos principais de rajada em cenas cronológicas (divididas por lacunas no horário de captura) para seleção em ordem narrativa:

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
|---------|---------|-------------|
| `gap_minutes` | `20.0` | Uma nova cena começa quando mais do que este número de minutos se passa entre fotos principais de rajada consecutivas (o piso quando `adaptive` está ativado) |
| `min_size` | `2` | Mínimo de fotos para que uma cena seja exibida |
| `max_photos` | `5000` | Máximo de fotos principais de rajada carregadas para o agrupamento em cenas |
| `max_scene_size` | `60` | Uma cena maior que isto é subdividida recursivamente em suas maiores lacunas internas, de modo que um evento fotografado continuamente nunca colapse em uma cena gigante |
| `adaptive` | `true` | Quando ativado, a lacuna efetiva se amplia para `adaptive_k × mediana` das lacunas consecutivas da sessão (aperta para fotografia rápida, afrouxa para férias esparsas) |
| `adaptive_k` | `6.0` | Multiplicador aplicado à lacuna mediana quando `adaptive` está ativado |

## Timeline

Configurações para a visualização cronológica em linha do tempo:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `photos_per_group` | `30` | Número de fotos carregadas por grupo de data na visualização em linha do tempo. Valores maiores mostram mais fotos por data, mas aumentam o peso da página. |

## Map

Configurações para a visualização interativa em mapa:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | Nível de zoom no qual marcadores individuais substituem os agrupamentos. Valores menores mostram marcadores individuais mais cedo (mais detalhe em zoom mais amplo). Faixa: 1 (mundo) a 18 (rua). |

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
|---------|---------|-------------|
| `target_language` | `"fr"` | Código do idioma de destino para `--translate-captions`. Suportados: `fr` (francês), `de` (alemão), `es` (espanhol), `it` (italiano). Usa os modelos Helsinki-NLP MarianMT (CPU, sem necessidade de GPU). |

## Aesthetic CLIP (R2)

Pontuação estética suplementar derivada de embeddings CLIP/SigLIP em cache via projeção de texto. Os prompts são ajustáveis pelo usuário para o benchmark AVA — veja `scripts/benchmark_aesthetic.py` para medir o impacto no SRCC de qualquer alteração.

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

Arrays vazios recorrem aos padrões do módulo embutidos em `analyzers/aesthetic_clip.py`. Não ajuste estes valores sem reexecutar o benchmark AVA — os padrões pontuam SRCC ~0,52 em `ava_test/` e as alterações podem facilmente regredir para ~0,30.

## Adding alternative VLM tagger / critique models (R3)

A chave `tagging_model` de cada perfil de VRAM (ex.: `qwen3.5-2b`) é mapeada para uma entrada de modelo na mesma seção `models`. Para experimentar um VLM diferente (Pixtral-12B, InternVL-2.5, etc.):

1. Adicione uma entrada de modelo em `models`:
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
3. Execute `python facet.py --recompute-tags-vlm` para remarcar.

Nenhuma alteração de código é necessária. Valide a qualidade por meio de uma verificação lado a lado em ~30 fotos antes de promover a padrão.

## Share Secret

String hexadecimal de 64 caracteres gerada automaticamente para tokens de sessão/compartilhamento:

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Gerada automaticamente na primeira execução, caso não esteja presente.
