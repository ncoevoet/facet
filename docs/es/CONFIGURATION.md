# Referencia de configuración

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · **Español**

Todos los ajustes están en `scoring_config.json`. Tras modificarlos, ejecuta `python facet.py --recompute-average` para actualizar las puntuaciones (no se necesita GPU).

## Índice de contenidos

- [Usuarios](#usuarios)
- [Escaneo](#escaneo)
- [Categorías](#categorías)
- [Puntuación](#puntuación)
- [Umbrales](#umbrales)
- [Composición](#composición)
- [Ajustes EXIF](#ajustes-exif)
- [Exposición](#exposición)
- [Penalizaciones](#penalizaciones)
- [Normalización](#normalización)
- [Modelos](#modelos)
- [Modelos de evaluación de calidad](#modelos-de-evaluación-de-calidad)
- [Procesamiento](#procesamiento)
- [Detección de ráfagas](#detección-de-ráfagas)
- [Puntuación de ráfagas](#puntuación-de-ráfagas)
- [Detección de duplicados](#detección-de-duplicados)
- [Detección de rostros](#detección-de-rostros)
- [Agrupación de rostros](#agrupación-de-rostros)
- [Procesamiento de rostros](#procesamiento-de-rostros)
- [Detección de monocromo](#detección-de-monocromo)
- [Etiquetado](#etiquetado)
- [Etiquetas independientes](#etiquetas-independientes)
- [Análisis](#análisis)
- [Visor](#visor)
- [Rendimiento](#rendimiento)
- [Almacenamiento](#almacenamiento)
- [Plugins](#plugins)
- [Cápsulas](#cápsulas)
- [Grupos de similitud](#grupos-de-similitud)
- [Cronología](#cronología)
- [Mapa](#mapa)
- [Traducción](#traducción)

---

## Usuarios

Modo multiusuario opcional. Cuando la clave `users` está presente (con al menos un usuario), la autenticación de contraseña única se sustituye por un inicio de sesión por usuario.

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

### Campos de usuario

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `password_hash` | string | Hash PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`). Generado por la CLI `--add-user`. |
| `display_name` | string | Mostrado en la cabecera de la interfaz |
| `role` | string | `user`, `admin` o `superadmin` |
| `directories` | array | Directorios de fotos privados para este usuario |

### Directorios compartidos

La clave `shared_directories` (hermana de los objetos de usuario) lista los directorios visibles para todos los usuarios.

### Roles

| Rol | Ver propios + compartidos | Valorar/favorito | Gestionar personas/rostros | Lanzar escaneos |
|------|:-:|:-:|:-:|:-:|
| `user` | sí | sí | no | no |
| `admin` | sí | sí | sí | no |
| `superadmin` | sí | sí | sí | sí |

### Añadir usuarios

Los usuarios se crean solo por CLI: no hay interfaz de registro ni API:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Solicita la contraseña, escribe el hash en scoring_config.json
```

Tras añadir un usuario, edita `scoring_config.json` para configurar sus `directories`.

### Compatibilidad con versiones anteriores

- Sin clave `users` = modo monousuario heredado (comportamiento sin cambios)
- `viewer.password` y `viewer.edition_password` se ignoran en modo multiusuario
- Las valoraciones existentes en la tabla `photos` se conservan para el modo monousuario; usa `--migrate-user-preferences` para copiarlas

---

## Escaneo

Controla el comportamiento del escaneo de directorios.

```json
{
  "scanning": {
    "skip_hidden_directories": true
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | Omitir directorios que empiezan por `.` durante el escaneo de fotos |

---

## Categorías

Array de definiciones de categorías. Consulta [Puntuación](SCORING.md) para la documentación detallada de las categorías.

Cada categoría tiene:
- `name` - Identificador de la categoría
- `priority` - Menor = mayor prioridad (se evalúa primero)
- `filters` - Condiciones de coincidencia
- `weights` - Pesos de las métricas de puntuación (deben sumar 100)
- `modifiers` - Ajustes de comportamiento
- `tags` - Vocabulario CLIP para coincidencia basada en etiquetas

---

## Puntuación

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `score_min` | `0.0` | Puntuación mínima posible |
| `score_max` | `10.0` | Puntuación máxima posible |
| `score_precision` | `2` | Decimales para las puntuaciones |

---

## Umbrales

Umbrales de detección para la categorización automática.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `portrait_face_ratio_percent` | `5` | Rostro > 5% del encuadre = retrato |
| `blink_penalty_percent` | `50` | Multiplicador de puntuación cuando se detecta parpadeo (0,5x) |
| `night_luminance_threshold` | `0.15` | Luminancia media por debajo de este valor = nocturna |
| `night_iso_threshold` | `3200` | ISO por encima de este valor = poca luz |
| `long_exposure_shutter_threshold` | `1.0` | Obturador > 1 s = larga exposición |
| `astro_shutter_threshold` | `10.0` | Obturador > 10 s = astrofotografía |

---

## Composición

Puntuación de composición basada en reglas (usada cuando SAMP-Net no está activo).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `power_point_weight` | `2.0` | Peso para la colocación según la regla de los tercios |
| `line_weight` | `1.0` | Peso para las líneas guía |

---

## Ajustes EXIF

Ajustes automáticos de la puntuación según los parámetros de la cámara.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `iso_sharpness_compensation` | `true` | Reduce la penalización de nitidez para ISO alto |
| `aperture_isolation_boost` | `true` | Aumenta el aislamiento para aperturas amplias (f/1.4-f/2.8) |

---

## Exposición

Controla el análisis de exposición y la detección de recorte.

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `shadow_clip_threshold_percent` | `15` | Marcar si > 15% de píxeles negro puro |
| `highlight_clip_threshold_percent` | `10` | Marcar si > 10% de píxeles blanco puro |
| `silhouette_detection` | `true` | Detectar siluetas intencionadas |

---

## Penalizaciones

Penalizaciones de puntuación por problemas técnicos.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | Ruido por encima de este valor desencadena una penalización |
| `noise_max_penalty_points` | `1.5` | Penalización máxima por ruido |
| `noise_penalty_per_sigma` | `0.3` | Puntos por sigma por encima del umbral |
| `bimodality_threshold` | `2.5` | Coeficiente de bimodalidad del histograma |
| `bimodality_penalty_points` | `0.5` | Penalización para histogramas bimodales |
| `leading_lines_blend_percent` | `30` | Mezcla en comp_score |
| `oversaturation_threshold` | `0.9` | Umbral de saturación media |
| `oversaturation_pixel_percent` | `5` | Reservado para detección a nivel de píxel |
| `oversaturation_penalty_points` | `0.5` | Penalización por sobresaturación |

**Fórmula de penalización por ruido:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalización

Controla cómo las métricas brutas se escalan a puntuaciones de 0 a 10.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `method` | `"percentile"` | Método de normalización |
| `percentile_target` | `90` | El percentil 90 = puntuación de 10,0 |
| `per_category` | `true` | Normalización específica por categoría |
| `category_min_samples` | `50` | Mínimo de fotos para normalización por categoría |

---

## Modelos

Selecciona qué modelos se usan por perfil de VRAM.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `vram_profile` | `"auto"` | Perfil activo (`auto`, `legacy`, `8gb`, `16gb`, `24gb`) |
| `keep_in_ram` | `"auto"` | Mantener los modelos en RAM entre los fragmentos multipasada (`"auto"`, `"always"`, `"never"`). `auto` comprueba la RAM disponible antes de almacenar en caché. |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modelos PyIQA a ejecutar para este perfil (vacío en `legacy`) |
| `profiles.*.saliency_enabled` | `true` (16gb/24gb) | Ejecutar la saliencia del sujeto BiRefNet para este perfil |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modelo de embeddings SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) o `"open_clip"` (heredado) |
| `clip.embedding_dim` | `1152` | Dimensiones del embedding (1152 para SigLIP 2) |
| `clip.similarity_threshold_percent` | `8` | Similitud coseno CLIP mínima para una coincidencia de etiqueta |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modelo CLIP heredado (perfiles legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Pesos preentrenados heredados |
| `clip_legacy.embedding_dim` | `768` | Dimensiones del embedding heredado |
| `clip_legacy.similarity_threshold_percent` | `22` | Umbral de coincidencia de etiqueta para CLIP heredado |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Ruta HuggingFace (VLM de composición 24gb) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modelo de etiquetado para el perfil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Imágenes por lote de inferencia VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modelo de etiquetado para el perfil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Imágenes por lote de inferencia VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modelo de saliencia BiRefNet |
| `saliency.resolution` | `1024` | Resolución de inferencia |
| `saliency.mask_threshold` | `0.3` | Umbral sigmoide para la máscara binaria del sujeto |
| `saliency.min_subject_pixels` | `50` | Píxeles mínimos del sujeto para contar un sujeto como detectado |
| `samp_net.input_size` | `384` | Tamaño de entrada del modelo de composición |

### Detección automática de VRAM

Cuando `vram_profile` es `"auto"` (por defecto), el sistema detecta la VRAM de GPU disponible al inicio y selecciona el perfil más grande que quepa:

| VRAM detectada | Perfil seleccionado |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Sin GPU | `legacy` (usa la RAM del sistema) |

---

## Modelos de evaluación de calidad

Selecciona el modelo que puntúa la calidad/estética de la imagen, mediante la biblioteca [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `model` | `"auto"` | Modelo de calidad: `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` usa `topiq`. |
| `prefer_llm` | `false` | Preferir un puntuador basado en LLM cuando haya uno disponible |

### Modelos de calidad disponibles

SRCC = coeficiente de correlación de rangos de Spearman en el benchmark KonIQ-10k (1,0 = perfecto).

| Modelo | SRCC | VRAM | Notas |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Por defecto (`auto`); backbone ResNet50 con atención descendente |
| `hyperiqa` | 0.90 | ~2GB | Hiperred, adaptativa al contenido |
| `dbcnn` | 0.90 | ~2GB | CNN de doble rama (distorsiones sintéticas + auténticas) |
| `musiq` | 0.87 | ~2GB | Transformer multiescala; admite cualquier resolución |
| `clipiqa+` | 0.86 | ~4GB | CLIP con prompts de calidad aprendidos |
| `clip-mlp` | 0.76 | ~4GB | CLIP ViT-L-14 heredado + cabeza MLP |

### Cambiar de modelo de calidad

1. Edita `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Vuelve a puntuar las fotos existentes (opcional):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Procesamiento

Ajustes unificados de procesamiento para el procesamiento por lotes en GPU y el modo multipasada.

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

### Conceptos clave

**`gpu_batch_size`** - Cuántas imágenes se procesan juntas en la GPU en una sola pasada hacia adelante. Limitado por la VRAM. Autoajustado: se reduce cuando la memoria de la GPU supera el límite.

**`ram_chunk_size`** - Cuántas imágenes se almacenan en caché en RAM entre pasadas de modelos (solo en modo multipasada). Reduce la E/S de disco al cargar las imágenes una vez por fragmento. Limitado por la RAM del sistema. Autoajustado: se reduce cuando la memoria del sistema supera el límite.

### Referencia de ajustes

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mode` | `"auto"` | Modo de procesamiento: `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Imágenes por lote de GPU (limitado por VRAM) |
| `ram_chunk_size` | `32` | Imágenes por fragmento de RAM (multipasada) |
| `num_workers` | `4` | Hilos del cargador de imágenes |
| `load_workers` | `num_workers` | Hilos del cargador de fragmentos multipasada (limitado a 8, `1` = secuencial) |
| `raw_decode_concurrency` | `0` (auto) | Máximo de decodificaciones RAW simultáneas; dimensionado automáticamente según CPU/RAM (1-4), `1` = totalmente serializado |
| `raw_decode_timeout_seconds` | `120` | Abandonar una decodificación RAW colgada tras este retraso (`0` = desactivado); el escaneo falla rápido tras varios cuelgues |
| `exif_prefetch` | `true` | Modo single-pass: prefijar EXIF en segundo plano en lugar de bloquear el hilo de la GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Activar el autoajuste |
| `monitor_interval_seconds` | `5` | Intervalo de comprobación de recursos |
| `tuning_interval_images` | `32` | Reajustar cada N imágenes |
| `min_processing_workers` | `1` | Mínimo de hilos del cargador |
| `max_processing_workers` | `32` | Máximo de hilos del cargador |
| `min_gpu_batch_size` | `2` | Tamaño mínimo del lote de GPU |
| `max_gpu_batch_size` | `32` | Tamaño máximo del lote de GPU |
| `min_ram_chunk_size` | `10` | Tamaño mínimo del fragmento de RAM |
| `max_ram_chunk_size` | `128` | Tamaño máximo del fragmento de RAM |
| `memory_limit_percent` | `85` | Límite de uso de memoria del sistema |
| `cpu_target_percent` | `85` | Objetivo de uso de CPU |
| `metrics_print_interval_seconds` | `30` | Intervalo de impresión de estadísticas |
| **thumbnails** | | |
| `photo_size` | `640` | Tamaño de la miniatura almacenada (píxeles) |
| `photo_quality` | `80` | Calidad JPEG de la miniatura |
| `face_padding_ratio` | `0.3` | Relleno alrededor de los recortes de rostros |

### Modos de procesamiento

| Modo | Descripción |
|------|-------------|
| `auto` | Selecciona automáticamente multipasada o pasada única según la VRAM |
| `multi-pass` | Carga secuencial de modelos (funciona con VRAM limitada) |
| `single-pass` | Todos los modelos cargados a la vez (requiere VRAM alta) |

### Cómo funciona la multipasada

En lugar de cargar todos los modelos a la vez, la multipasada:

1. Carga las imágenes en fragmentos de RAM (`ram_chunk_size` por defecto: 32)
2. Para cada fragmento, ejecuta los modelos secuencialmente: cargar modelo → procesar fragmento → descargar modelo
3. Combina los resultados en una pasada final de agregación

Cada imagen se carga una vez por fragmento, y las pasadas se agrupan para ajustarse a la VRAM disponible, de modo que los VLM más grandes de etiquetado/composición se ejecutan incluso con VRAM limitada.

### Comportamiento del autoajuste

El sistema supervisa el uso de recursos y se ajusta:

| Métrica | Acción |
|--------|--------|
| Memoria de GPU > límite | Reducir `gpu_batch_size` un 25% |
| RAM del sistema > límite | Reducir `ram_chunk_size` un 25% |
| RAM del sistema < (límite - 20%) | Aumentar `ram_chunk_size` un 25% |
| CPU > objetivo | Sugerir menos workers |
| Tiempos de espera de cola > 5% | Sugerir más workers |

### Agrupación dinámica de pasadas

Cuando la VRAM lo permite, varios modelos pequeños se ejecutan juntos:

| VRAM | Pasada 1 | Pasada 2 |
|------|--------|--------|
| 8GB | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12GB | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16GB | CLIP + SAMP-Net + InsightFace + TOPIQ | VLM etiquetador |
| 24GB+ | Todos los modelos juntos (pasada única) | - |

### Opciones de la CLI

```bash
# Por defecto: multipasada automática con agrupación óptima
python facet.py /path/to/photos

# Forzar pasada única (todos los modelos cargados a la vez)
python facet.py /path --single-pass

# Ejecutar solo una pasada específica
python facet.py /path --pass quality       # Solo TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (mérito estético)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (calidad + distorsión)
python facet.py /path --pass tags          # Solo el etiquetador configurado
python facet.py /path --pass composition   # Solo SAMP-Net
python facet.py /path --pass faces         # Solo InsightFace
python facet.py /path --pass embeddings    # Solo embeddings CLIP/SigLIP
python facet.py /path --pass saliency      # Saliencia del sujeto BiRefNet

# Listar modelos disponibles
python facet.py --list-models
```

---

## Detección de ráfagas

Agrupa fotos similares tomadas en sucesión rápida.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `similarity_threshold_percent` | `70` | Umbral de similitud del hash de imagen |
| `time_window_minutes` | `0.8` | Tiempo máximo entre fotos |
| `rapid_burst_seconds` | `0.4` | Fotos dentro de este intervalo se agrupan automáticamente |

---

## Puntuación de ráfagas

Pesos usados por la selección de ráfagas para calcular una puntuación compuesta que elige la mejor toma dentro de cada grupo de ráfaga. Los pesos deberían sumar 1,0.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `weight_aggregate` | `0.4` | Peso de la puntuación global general |
| `weight_aesthetic` | `0.25` | Peso de la puntuación de calidad estética |
| `weight_sharpness` | `0.2` | Peso de la puntuación de nitidez técnica |
| `weight_blink` | `0.15` | Peso de penalización para parpadeos detectados (mayor = penalización más fuerte) |

---

## Detección de duplicados

Detecta fotos duplicadas globalmente usando la comparación de hash perceptual (pHash).

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `similarity_threshold_percent` | `90` | Filtro pHash estricto (90% = distancia de Hamming <= 6 de 64 bits); usado como único criterio cuando falta un embedding para alguna de las fotos |
| `prefilter_hamming` | `12` | Filtro Hamming amplio de la etapa 1 para el conjunto de candidatas cuando ambas fotos tienen embeddings (forzado a ser >= el filtro estricto) |
| `embedding_cosine_threshold` | `0.90` | Filtro coseno SigLIP/CLIP de la etapa 2: una candidata de pHash amplio solo se fusiona cuando el coseno es >= a este valor |

La detección tiene dos etapas: candidatas de pHash amplio (recall) confirmadas por un filtro coseno de embedding estricto (precisión). Las fotos sin embedding recurren al criterio estricto basado solo en pHash, así que el comportamiento no cambia cuando faltan los embeddings.

Ejecuta `python facet.py --detect-duplicates` para detectar y agrupar duplicados. Ejecuta `python facet.py --sweep-dedup-thresholds [labels.json]` para evaluar el filtro coseno: con un JSON de etiquetas imprime una tabla de precisión/recall, de lo contrario la distribución coseno de las candidatas y cuántas colisiones de pHash estricto rechaza el filtro.

---

## Nivel IQA extendido (opcional)

Puntuadores de calidad pesados/experimentales, **DESACTIVADOS por defecto** y **nunca un reemplazo de TOPIQ**: añaden columnas suplementarias solo cuando se activan explícitamente. Cuando están activados, los puntuadores extendidos se ejecutan **durante un escaneo normal** y escriben sus propias columnas; un fallo de carga/VRAM se registra y la columna se deja `NULL` (el escaneo nunca se aborta).

```json
{
  "iqa_extended": {
    "qalign": "4bit",
    "aesthetic_v25": true,
    "deqa": false
  }
}
```

| Ajuste | Por defecto | Valores aceptados | Columna | Descripción |
|---------|---------|-----------------|--------|-------------|
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | IQA basado en LLM Q-Align (respaldado por pyiqa). `"4bit"` (~6-8GB VRAM) es la opción práctica en una tarjeta de 16GB; `"8bit"` ~12-14GB; precisión completa (`true`) requiere 16GB+. 4/8 bits necesitan `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (cabeza SigLIP, ~2GB). Requiere el paquete `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA de VLM DeQA-Score (GPU de 16GB+; en caso contrario se omite y se deja NULL). |

**Instala las dependencias opcionales** de lo que actives: `pip install -e .[iqa-extended]` (añade `aesthetic-predictor-v2-5` + `bitsandbytes`), o descomenta las líneas correspondientes en `requirements.txt`. Q-Align ya viene con `pyiqa`; DeQA-Score se descarga mediante `transformers`.

Cuando se activan, cada métrica se expone a la agregación ponderada pero con peso 0 por defecto, así que `--recompute-average` es idéntico a nivel de byte hasta que le des un peso. Ejecuta `python facet.py --eval-iqa-srcc` para medir lo bien que cada métrica clasifica tu biblioteca frente a tus propias valoraciones por estrellas.

**Visibilidad en el visor.** Cuando cualquiera de estas columnas está poblada, el visor muestra el valor en el panel **Calidad** del detalle de la foto (`Q-Align`, `Aesthetic V2.5`, `DeQA`) y expone un control de rango correspondiente en la barra lateral de filtros de la galería bajo **Calidad extendida** (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). Las fotos escaneadas antes de activar el nivel simplemente tienen `NULL` en estas columnas y no se ven afectadas por los filtros.

**Robustez.** DeQA-Score carga código remoto `trust_remote_code` cuya firma de forward varía entre revisiones de checkpoint; su puntuador es defensivo: cualquier fallo de predicción (firma incorrecta, forma de salida inesperada, OOM) se captura y el `deqa_score` de la imagen se deja `NULL` en lugar de bloquear el escaneo.

---

## Detección de rostros

Ajustes de detección de rostros de InsightFace.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confianza mínima de detección |
| `min_face_size` | `20` | Tamaño mínimo del rostro en píxeles |
| `blink_ear_threshold` | `0.28` | Relación de aspecto del ojo (EAR) para la detección de parpadeo |
| `min_faces_for_group` | `4` | Mínimo de rostros para clasificar como retrato de grupo (recalculado con `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Cargar el módulo `landmark_3d_68` de InsightFace para la extracción de la pose de cabeza (yaw/pitch/roll). Cuesta ~5MB extra de pesos ONNX. Actualmente es informativo; futuros refinamientos de perfil/silueta lo leerán. |

---

## Agrupación de rostros

Agrupación HDBSCAN para el reconocimiento facial.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Activar la agrupación de rostros |
| `min_faces_per_person` | `2` | Mínimo de fotos por persona |
| `min_samples` | `2` | Parámetro min_samples de HDBSCAN |
| `auto_merge_distance_percent` | `15` | Fusión automática dentro de esta distancia |
| `clustering_algorithm` | `"best"` | Algoritmo HDBSCAN |
| `leaf_size` | `40` | Tamaño de hoja del árbol (solo CPU) |
| `use_gpu` | `"auto"` | Modo GPU: `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Similitud de centroide para la coincidencia |
| `chunk_size` | `10000` | Tamaño del fragmento de procesamiento |

**Algoritmos de agrupación:**

| Algoritmo | Complejidad | Mejor para |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Datos de alta dimensión (recomendado) |
| `boruvka_kdtree` | O(n log n) | Datos de baja dimensión |
| `prims_balltree` | O(n²) | Memoria limitada, alta dimensión |
| `prims_kdtree` | O(n²) | Memoria limitada, baja dimensión |
| `best` | Auto | Dejar que HDBSCAN decida |

---

## Procesamiento de rostros

Controla la extracción de rostros y la generación de miniaturas.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `crop_padding` | `0.3` | Relación de relleno para los recortes de rostros |
| `use_db_thumbnails` | `true` | Usar las miniaturas almacenadas |
| `face_thumbnail_size` | `640` | Tamaño de la miniatura en píxeles |
| `face_thumbnail_quality` | `90` | Calidad JPEG |
| `extract_workers` | `2` | Workers de extracción paralela |
| `extract_batch_size` | `16` | Tamaño del lote de extracción |
| `refill_workers` | `4` | Workers de relleno de miniaturas |
| `refill_batch_size` | `100` | Tamaño del lote de relleno |
| **auto_tuning** | | |
| `enabled` | `true` | Activar el ajuste basado en memoria |
| `memory_limit_percent` | `80` | Límite de uso de memoria |
| `min_batch_size` | `8` | Tamaño mínimo del lote |
| `monitor_interval_seconds` | `5` | Intervalo de comprobación |

---

## Detección de monocromo

Detección de fotos en blanco y negro.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `saturation_threshold_percent` | `5` | Saturación media < 5% = monocromo |

---

## Etiquetado

Ajustes generales de etiquetado. El modelo de etiquetado se configura por perfil en `models.profiles.*.tagging_model`.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Activar el etiquetado |
| `max_tags` | `5` | Máximo de etiquetas por foto |

**Nota:** Los ajustes específicos de CLIP como `similarity_threshold_percent` están en la sección `models.clip`.

### Modelos de etiquetado disponibles

Configurados mediante `models.profiles.*.tagging_model`:

| Modelo | VRAM | Estilo de etiquetas | Notas |
|-------|------|-----------|-------|
| `clip` | 0 (reutiliza embeddings) | Estado de ánimo/atmósfera (dramatic, golden_hour, vintage) | Sin carga de modelo extra; detección de objetos menos literal |
| `qwen3.5-2b` | ~4GB | Escenas estructuradas (landscape, architecture, reflection) | Requiere transformers + VRAM extra |
| `qwen3.5-4b` | ~8GB | Escenas detalladas con matices | Mayor VRAM; inferencia más lenta |

### Modelos de etiquetado por defecto por perfil

| Perfil | Modelo de etiquetado | Modelo de embeddings |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Reetiquetar fotos

```bash
python facet.py --recompute-tags       # Reetiquetar con el modelo configurado por perfil
python facet.py --recompute-tags-vlm   # Reetiquetar con el etiquetador VLM
```

---

## Etiquetas independientes

Etiquetas con listas de sinónimos que no están ligadas a ninguna categoría específica. Están disponibles para todas las fotos independientemente de la asignación de categoría. Cada clave es el nombre de la etiqueta; el valor es una lista de sinónimos para la coincidencia CLIP/VLM.

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

Añade nuevas etiquetas independientes proporcionando una clave y una lista de sinónimos. Las etiquetas definidas aquí se fusionan con las etiquetas específicas de categoría para formar el vocabulario de etiquetas completo.

---

## Análisis

Umbrales para `--compute-recommendations`.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `aesthetic_max_threshold` | `9.0` | Advertir si la estética máxima está por debajo de este valor |
| `aesthetic_target` | `9.5` | Objetivo para aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Umbral de calidad "de alto valor" |
| `quality_weight_threshold_percent` | `10` | Advertir si el peso de calidad ≤ este valor |
| `correlation_dominant_threshold` | `0.5` | Advertencia de "señal dominante" |
| `category_min_samples` | `50` | Mínimo de fotos por categoría |
| `category_imbalance_threshold` | `0.5` | Advertencia de brecha de puntuación |
| `score_clustering_std_threshold` | `1.0` | Advertir si la desviación estándar < este valor |
| `top_score_threshold` | `8.5` | Advertir si el máximo global < este valor |
| `exposure_avg_threshold` | `8.0` | Advertir si la exposición media > este valor |

---

## Visor

Visualización y comportamiento de la galería web.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "uncertainty",
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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `default_category` | `""` | Filtro de categoría por defecto |
| `edition_password` | `""` | Contraseña para desbloquear el modo edición (vacío = desactivado) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Mínimo para la optimización |
| `pair_selection_strategy` | `"uncertainty"` | Estrategia por defecto |
| `show_current_scores` | `true` | Mostrar las puntuaciones durante la comparación |
| **pagination** | | |
| `default_per_page` | `64` | Fotos por página |
| **dropdowns** | | |
| `max_cameras` | `50` | Máximo de cámaras en el desplegable |
| `max_lenses` | `50` | Máximo de objetivos |
| `max_persons` | `50` | Máximo de personas |
| `max_tags` | `20` | Máximo de etiquetas |
| `min_photos_for_person` | `10` | Ocultar del desplegable las personas con menos fotos |
| **persons** | | |
| `needs_naming_min_faces` | `5` | face_count mínimo para que un clúster agrupado automáticamente aparezca en la sección "Por nombrar" de `/persons` |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nombre del binario darktable-cli o ruta absoluta |
| `darktable.profiles` | `[]` | Array de perfiles de exportación de darktable con nombre (ver abajo) |
| `darktable.profiles[].name` | *(obligatorio)* | Nombre visible del perfil (usado en el menú de descarga y el parámetro `profile` de la API) |
| `darktable.profiles[].hq` | `true` | Pasar `--hq true` para una exportación de alta calidad |
| `darktable.profiles[].width` | *(omitir)* | Ancho máximo de salida (omitir para resolución completa) |
| `darktable.profiles[].height` | *(omitir)* | Alto máximo de salida (omitir para resolución completa) |
| `darktable.profiles[].style` | *(omitir)* | Nombre del estilo de darktable aplicado durante la exportación (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | Cuando es `false`, pasa `--apply-custom-presets false` para que solo se renderice el `style` explícito (no los presets aplicados automáticamente) |
| `darktable.profiles[].extra_args` | `[]` | Argumentos CLI adicionales (p. ej., `["--style-overwrite"]`) |
| **display** | | |
| `tags_per_photo` | `4` | Etiquetas mostradas en las tarjetas |
| `card_width_px` | `168` | Ancho de la tarjeta |
| `image_width_px` | `160` | Ancho de la imagen |
| `image_jpeg_quality` | `96` | Calidad JPEG para la conversión RAW/HEIF en `/api/download` y `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Tamaño mínimo de miniatura (px) |
| `thumbnail_slider.max_px` | `400` | Tamaño máximo de miniatura (px) |
| `thumbnail_slider.default_px` | `168` | Tamaño de miniatura por defecto (px) |
| `thumbnail_slider.step_px` | `8` | Incremento del paso del control (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Tamaño de la miniatura |
| `jpeg_quality` | `80` | Calidad JPEG |
| `crop_padding_ratio` | `0.2` | Relleno del rostro |
| `min_crop_size_px` | `20` | Tamaño mínimo del recorte |
| **quality_thresholds** | | |
| `good` | `6` | Umbral bueno |
| `great` | `7` | Umbral muy bueno |
| `excellent` | `8` | Umbral excelente |
| `best` | `9` | Umbral óptimo |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Mínimo de Selección destacada |
| `top_picks_min_face_ratio` | `0.2` | Proporción facial para los pesos |
| `low_light_max_luminance` | `0.2` | Umbral de poca luz |
| **defaults** | | |
| `type` | `""` | Filtro de tipo de foto por defecto (p. ej., `"portraits"`, `"landscapes"`, o `""` para Todas) |
| `sort` | `"aggregate"` | Columna de ordenación por defecto |
| `sort_direction` | `"DESC"` | Dirección de ordenación por defecto (`"ASC"` o `"DESC"`) |
| `hide_blinks` | `true` | Ocultar las fotos con parpadeo por defecto |
| `hide_bursts` | `true` | Mostrar solo la mejor de la ráfaga por defecto |
| `hide_duplicates` | `true` | Ocultar las fotos duplicadas no principales por defecto |
| `hide_details` | `true` | Ocultar los detalles de las fotos en las tarjetas por defecto |
| `tooltip_mode` | `"hover"` | Disparador del tooltip: `"hover"`, `"click"` o `"off"`. Sustituye al anterior booleano `hide_tooltip`. |
| `hide_rejected` | `true` | Ocultar las fotos rechazadas por defecto |
| `gallery_mode` | `"mosaic"` | Disposición de galería por defecto (`"grid"` o `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Orígenes permitidos por CORS para el servidor FastAPI. Añade tu dominio o la URL del proxy inverso cuando alojes de forma remota. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(valor por defecto seguro para SPA)_ | Valor de la cabecera Content-Security-Policy. Por defecto una política que permite los recursos propios de la SPA (script/estilo de tema en línea, Google Fonts, mosaicos de OpenStreetMap, API del mismo origen). Ponlo a `""` para desactivarla, o proporciona una política más estricta. |
| `security_headers.hsts` | `false` | Enviar `Strict-Transport-Security`. Actívalo solo cuando el visor se sirve por HTTPS. |
| **Otros** | | |
| `cache_ttl_seconds` | `60` | TTL de la caché de consultas |
| `notification_duration_ms` | `2000` | Duración del toast |

### Funciones

Activa o desactiva funciones opcionales para reducir el uso de memoria o simplificar la interfaz:

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
      "show_map": true
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `show_similar_button` | `true` | Mostrar el botón "Buscar similares" en las tarjetas de fotos (usa numpy para la similitud CLIP) |
| `show_merge_suggestions` | `true` | Activar la función de sugerencias de fusión en la página de gestión de personas |
| `show_rating_controls` | `true` | Mostrar los controles de valoración por estrellas y favorito |
| `show_rating_badge` | `true` | Mostrar la insignia de valoración en las tarjetas de fotos |
| `show_scan_button` | `false` | Mostrar el botón de lanzar escaneo para usuarios superadmin (requiere GPU en el host del visor) |
| `metrics_enabled` | `false` | Activar el endpoint Prometheus público `GET /metrics`. Desactivado por defecto: expone los recuentos de fotos/personas/rostros, el tamaño de la BD y la memoria del proceso; actívalo solo cuando el endpoint sea accesible desde la red del recolector, no desde Internet público. |
| `show_semantic_search` | `true` | Mostrar la barra de búsqueda semántica (búsqueda texto-a-imagen usando embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Mostrar la función de álbumes (crear, gestionar y explorar álbumes de fotos) |
| `show_critique` | `true` | Mostrar el botón de crítica con IA en las tarjetas de fotos (desglose de puntuación basado en reglas) |
| `show_vlm_critique` | `false` | Activar el modo de crítica impulsada por VLM (requiere perfil de VRAM 16gb/24gb) |
| `show_embed_metadata` | `true` | Muestra la acción «Escribir metadatos en el archivo» por miniatura en modo edición (incrusta valoraciones/palabras clave en la imagen original mediante exiftool) |
| `show_memories` | `true` | Mostrar el diálogo de recuerdos "En este día" (fotos tomadas en la misma fecha de años anteriores) |
| `show_captions` | `true` | Mostrar las leyendas generadas por IA en las tarjetas de fotos |
| `show_timeline` | `true` | Mostrar la vista de cronología para la navegación cronológica con navegación por fechas |
| `show_map` | `false` | Mostrar la vista de mapa con ubicaciones de fotos basadas en GPS (requiere Leaflet; desactivado por defecto ya que las fotos pueden carecer de datos GPS) |

**Optimización de memoria:** Poner `show_similar_button: false` evita que se cargue numpy, reduciendo la huella de memoria del visor. La función de fotos similares calcula la similitud coseno del embedding CLIP, que requiere numpy.

### Mapeo de rutas

Mapea rutas de la base de datos a rutas del sistema de archivos local. Útil cuando las fotos se puntuaron en una máquina (p. ej., Windows con rutas UNC) pero el visor se ejecuta en otra (p. ej., un NAS Linux con puntos de montaje).

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `path_mapping` | `{}` | Diccionario de prefijo de origen a prefijo de destino. Al servir imágenes a tamaño completo o crítica VLM, las rutas de la base de datos que empiezan por un prefijo de origen se reescriben para usar el prefijo de destino. |

**Cómo funciona:**
- Solo se aplica al **leer archivos del disco** (servir imágenes a tamaño completo, descargas de archivos, crítica VLM). Las rutas de la base de datos nunca se modifican.
- La normalización de barra invertida/barra normal se gestiona automáticamente: `\\NAS\Photos\img.jpg` y `//NAS/Photos/img.jpg` coinciden ambas.
- Los mapeos se evalúan en orden; gana el primer prefijo que coincida.
- Los destinos del mapeo de rutas se incluyen automáticamente en la lista de directorios de escaneo permitidos para las comprobaciones de seguridad multiusuario.

**Ejemplo:** Una base de datos poblada en Windows almacena rutas como `\\NAS\Photos\2024\IMG_001.jpg`. En Linux, el mismo recurso compartido está montado en `/mnt/nas/Photos`. Configura:

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Protección por contraseña

Protección por contraseña opcional para el visor:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Cuando se establece, los usuarios deben autenticarse antes de acceder al visor.

### Rendimiento del visor

Sobrescribe los ajustes globales de `performance` al ejecutar el visor. Útil para despliegues en NAS con poca memoria, donde la puntuación necesita muchos recursos pero el visor no.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mmap_size_mb` | *(global)* | Sobrescritura del tamaño mmap de SQLite para las conexiones del visor. `0` desactiva mmap. |
| `cache_size_mb` | *(global)* | Sobrescritura del tamaño de caché de SQLite para las conexiones del visor |
| `pool_size` | `5` | Tamaño del pool de conexiones (reducir para sistemas con poca memoria) |
| `thumbnail_cache_size` | `2000` | Máximo de entradas en la caché en memoria de redimensionamiento de miniaturas |
| `face_cache_size` | `500` | Máximo de entradas en la caché en memoria de miniaturas de rostros |

Cuando no se establece, el visor usa los valores globales de `performance`. Consulta [Despliegue](DEPLOYMENT.md) para los ajustes recomendados de NAS.

---

## Rendimiento

Ajustes de rendimiento de la base de datos.

```json
{
  "performance": {
    "mmap_size_mb": 12288,
    "cache_size_mb": 64,
    "wal_checkpoint_minutes": 30,
    "slow_request_ms": 1000
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mmap_size_mb` | `12288` | Tamaño de E/S mapeada en memoria de SQLite |
| `cache_size_mb` | `64` | Tamaño de caché de SQLite |
| `wal_checkpoint_minutes` | `30` | Intervalo en minutos para el `PRAGMA wal_checkpoint(TRUNCATE)` en segundo plano del visor. Evita el crecimiento excesivo del WAL en despliegues de larga duración. Ponlo a `0` para desactivarlo. |
| `slow_request_ms` | `1000` | Las solicitudes a la API del visor más lentas que estos milisegundos se registran como WARNING con un marcador `SLOW`. Ponlo a `0` para desactivarlo. |

---

## Almacenamiento

Controla dónde se almacenan las miniaturas y los embeddings. Por defecto son columnas BLOB en la base de datos SQLite; el modo de sistema de archivos los almacena como archivos en disco, lo que reduce el tamaño de la base de datos.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mode` | `"database"` | Backend de almacenamiento: `"database"` (BLOBs de SQLite) o `"filesystem"` (archivos en disco) |
| `filesystem_path` | `"./storage"` | Directorio base para el modo de sistema de archivos. Las miniaturas se almacenan en `<path>/thumbnails/` y los embeddings en `<path>/embeddings/`, organizados en subdirectorios por hash de contenido. |

**Detalles del modo de sistema de archivos:**
- Los archivos se organizan por hash SHA-256 de la ruta de la foto, con subdirectorios de dos caracteres para evitar demasiados archivos en un solo directorio (p. ej., `thumbnails/a3/a3f8..._640.jpg`).
- Al eliminar una foto se eliminan todos los tamaños de miniatura y archivos de embedding asociados.
- El directorio se crea automáticamente en el primer uso.

---

## Plugins

Sistema de plugins basado en eventos para reaccionar a eventos de puntuación. Los plugins pueden ser módulos Python, webhooks o acciones integradas.

### Configuración

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

| Clave | Por defecto | Descripción |
|-----|---------|-------------|
| `enabled` | `false` | Interruptor maestro: cuando es false, no se emite ningún evento |
| `high_score_threshold` | `8.0` | Puntuación global mínima para desencadenar eventos `on_high_score` |
| `webhooks` | `[]` | Lista de endpoints webhook que reciben cargas útiles POST JSON |
| `actions` | `{}` | Acciones integradas con nombre desencadenadas por eventos |

### Eventos admitidos

| Evento | Desencadenante | Carga útil |
|-------|---------|---------|
| `on_score_complete` | Tras puntuar cada foto | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Cuando una foto entra en la base de datos | Igual que `on_score_complete` |
| `on_high_score` | Cuando el global ≥ `high_score_threshold` | Igual que `on_score_complete` |
| `on_burst_detected` | Cuando se identifica un grupo de ráfaga | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Escribir un plugin

Coloca un archivo `.py` en el directorio `plugins/`. Define funciones nombradas según los eventos que quieras gestionar:

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Consulta `plugins/example_plugin.py.example` para la interfaz completa.

### Webhooks

Cada webhook recibe un POST JSON con protección SSRF (las direcciones privadas/loopback están bloqueadas):

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

Opciones de webhook: `url` (obligatorio), `events` (lista de nombres de eventos), `min_score` (global mínimo para desencadenar).

### Acciones integradas

| Acción | Descripción | Opciones |
|--------|-------------|---------|
| `copy_to_folder` | Copiar la foto a una carpeta | `folder`, `min_score` |
| `send_notification` | Registrar una notificación | `min_score` |

### Endpoints de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/plugins` | Listar los plugins, webhooks y acciones cargados |
| `POST` | `/api/plugins/test-webhook` | Enviar una carga útil de prueba a una URL de webhook |

---

## Cápsulas

Diaporamas (pases de diapositivas) de fotos seleccionadas agrupadas por tema. Las cápsulas se generan automáticamente a partir de tu biblioteca de fotos y se almacenan en caché con un TTL configurable.

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

### Ajustes globales

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `min_aggregate` | `6.0` | Puntuación global mínima para que las fotos se incluyan en las cápsulas |
| `max_photos_per_capsule` | `40` | Máximo de fotos por cápsula (la diversidad MMR se aplica por encima de 5) |
| `max_photo_overlap` | `0.2` | Fracción máxima de fotos compartidas entre dos cápsulas antes de que la deduplicación elimine una |
| `mmr_lambda` | `0.5` | Peso de diversidad MMR: 0=maximizar diversidad, 1=maximizar calidad |
| `freshness_hours` | `24` | TTL de la caché y periodo de rotación para las fotos de portada y las cápsulas con semilla |
| `reverse_geocoding` | `true` | Activar la geocodificación inversa sin conexión para los títulos de cápsulas de ubicación/viaje (requiere el paquete `reverse_geocoder`) |

### Tipos de cápsula

| Tipo | Descripción |
|------|-------------|
| `journey` | Viajes detectados mediante agrupación GPS + lapsos temporales. Los títulos incluyen el nombre del destino cuando la geocodificación está activada. |
| `faces_of` | Mejores fotos de cada persona reconocida |
| `seasonal` | Fotos agrupadas por estación + año |
| `golden` | El 1% superior por puntuación global |
| `color_story` | Grupos visualmente similares mediante agrupación de embeddings CLIP |
| `this_week` | "Esta semana, hace años": una versión ampliada de "En este día" en un rango de ±3 días |
| `location` | Grupos de fotos geoetiquetadas con nombres de lugar geocodificados inversamente |
| `person_pair` | Parejas de personas con nombre que aparecen juntas |
| `seeded` | Descubrimiento basado en semillas por tiempo, similitud, persona, etiqueta, ubicación, estado de ánimo |
| `progress` | "Tu fotografía está mejorando" a partir de tendencias de puntuación trimestrales |
| `color_palette` | "Color del mes" a partir de perfiles de saturación/monocromo |
| `rare_pair` | Parejas de personas infrecuentes en fotos de alta puntuación |
| `favorites` | Fotos marcadas como favoritas agrupadas por año y estación |

### Cápsulas basadas en dimensiones

Generadas automáticamente a partir de columnas de la base de datos:

| Dimensión | Agrupa por |
|-----------|-----------|
| `year` | Año extraído de date_taken |
| `month` | Año-mes extraído de date_taken |
| `week` | Año-semana extraído de date_taken |
| `camera` | Modelo de cámara |
| `lens` | Modelo de objetivo |
| `tag` | Etiquetas de foto (requiere la tabla `photo_tags`) |
| `day_of_week` | Día de la semana (domingo–sábado) |
| `composition` | Patrón de composición SAMP-Net (rule_of_thirds, horizontal, etc.) |
| `focal_range` | Rangos de distancia focal: ultra gran angular (<24mm), gran angular (24–35mm), estándar (36–70mm), retrato (71–135mm), teleobjetivo (136–300mm), súper teleobjetivo (300mm+) |
| `category` | Categoría de contenido de la foto (portrait, landscape, street, etc.) |
| `time_of_day` | Rangos horarios: mañana dorada, mañana, mediodía, tarde, atardecer dorado, noche |
| `star_rating` | Valoraciones por estrellas del usuario (1–5 estrellas) |

También se generan combinaciones interdimensionales (p. ej., camera × year, focal_range × category, category × year).

### Transiciones del pase de diapositivas

Cada tipo de cápsula se asocia a una transición de diapositiva temática:

| Transición | Usada por | Efecto |
|-----------|---------|--------|
| `crossfade` | Por defecto | Intercambio de opacidad de 300ms |
| `slide` | journey, location, this_week | Deslizar desde la derecha (500ms) |
| `zoom` | faces_of, color_story | Escala 1.05→1.0 con fundido (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lento 1.0→1.08 durante la duración de la diapositiva |

### Geocodificación inversa

Las cápsulas de ubicación y viaje usan geocodificación inversa sin conexión mediante el paquete `reverse_geocoder` (conjunto de datos local de GeoNames, ~30MB, sin llamadas a la API). Los resultados se almacenan en caché en la tabla `location_names` de la base de datos a una resolución de cuadrícula de 0,1° (~11km).

Instalar: `pip install reverse_geocoder`

Pon `"reverse_geocoding": false` para desactivarla y recurrir a la visualización de coordenadas.

## Grupos de similitud

Ajustes para la función de selección de fotos similares con IA, que agrupa fotos visualmente similares usando embeddings CLIP/SigLIP:

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `default_threshold` | `0.85` | Similitud coseno mínima (0,0–1,0) para considerar dos fotos como visualmente similares. Valores más bajos producen grupos más grandes pero con menos similitud visual. |
| `min_group_size` | `2` | Número mínimo de fotos necesario para formar un grupo de similitud |
| `max_photos` | `10000` | Máximo de fotos a cargar para el cálculo de similitud (coste O(n²)). Auméntalo para bibliotecas más grandes a costa del tiempo de cálculo. |
| `max_group_size` | `50` | Máximo de fotos por grupo de similitud. Los grupos más grandes se dividen para mantener la interfaz usable. |

## Cronología

Ajustes para la vista cronológica de la cronología:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `photos_per_group` | `30` | Número de fotos cargadas por grupo de fecha en la vista de cronología. Valores más altos muestran más fotos por fecha pero aumentan el peso de la página. |

## Mapa

Ajustes para la vista de mapa interactivo:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | Nivel de zoom en el que los marcadores individuales sustituyen a los clústeres. Valores más bajos muestran los marcadores individuales antes (más detalle con un zoom más amplio). Rango: 1 (mundo) a 18 (calle). |

## Traducción

Ajustes para la traducción de leyendas con IA mediante MarianMT:

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `target_language` | `"fr"` | Código de idioma de destino para `--translate-captions`. Admitidos: `fr` (francés), `de` (alemán), `es` (español), `it` (italiano). Usa los modelos MarianMT de Helsinki-NLP (CPU, no se requiere GPU). |

## CLIP estético (R2)

Puntuación estética suplementaria derivada de los embeddings CLIP/SigLIP en caché mediante proyección de texto. Los prompts son ajustables por el usuario para el benchmarking AVA: consulta `scripts/benchmark_aesthetic.py` para medir el impacto SRCC de cualquier cambio.

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

Los arrays vacíos recurren a los valores por defecto del módulo integrados en `analyzers/aesthetic_clip.py`. No ajustes estos prompts sin volver a ejecutar el benchmark AVA: los valores por defecto puntúan un SRCC ~0,52 en `ava_test/` y los cambios pueden regresar fácilmente a ~0,30.

## Añadir modelos alternativos de etiquetado/crítica VLM (R3)

La clave `tagging_model` de cada perfil de VRAM (p. ej. `qwen3.5-2b`) se asigna a una entrada de modelo en la misma sección `models`. Para experimentar con un VLM diferente (Pixtral-12B, InternVL-2.5, etc.):

1. Añade una entrada de modelo bajo `models`:
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Apunta un perfil hacia él:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Ejecuta `python facet.py --recompute-tags-vlm` para reetiquetar.

No se necesitan cambios de código. Valida la calidad mediante una comprobación puntual lado a lado en ~30 fotos antes de promoverlo como predeterminado.

## Secreto de compartición

Cadena hexadecimal de 64 caracteres autogenerada para los tokens de sesión/compartición:

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Se genera automáticamente en el primer arranque si no está presente.
