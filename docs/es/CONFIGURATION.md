# Referencia de configuración

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · **Español** · [Português](../pt/CONFIGURATION.md)

Todos los ajustes están en `scoring_config.json`. Tras modificarlos, ejecuta `python facet.py --recompute-average` para actualizar las puntuaciones (no se necesita GPU).

## Tabla de contenidos

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
- [Escenas](#escenas)
- [Línea de tiempo](#línea-de-tiempo)
- [Mapa](#mapa)
- [Traducción](#traducción)

---

## Usuarios

Modo multiusuario opcional. Cuando la clave `users` está presente (con al menos un usuario), la autenticación de contraseña única se sustituye por el inicio de sesión por usuario.

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
| `display_name` | string | Mostrado en la cabecera de la UI |
| `role` | string | `user`, `admin` o `superadmin` |
| `directories` | array | Directorios de fotos privados de este usuario |

### Directorios compartidos

La clave `shared_directories` (hermana de los objetos de usuario) enumera los directorios visibles para todos los usuarios.

### Roles

| Rol | Ver propios + compartidos | Valorar/favoritos | Gestionar personas/rostros | Iniciar escaneos |
|------|:-:|:-:|:-:|:-:|
| `user` | sí | sí | no | no |
| `admin` | sí | sí | sí | no |
| `superadmin` | sí | sí | sí | sí |

### Añadir usuarios

Los usuarios se crean solo por la CLI; no hay interfaz ni API de registro:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Solicita una contraseña, escribe el hash en scoring_config.json
```

Después de añadir un usuario, edita `scoring_config.json` para configurar sus `directories`.

### Compatibilidad con versiones anteriores

- Sin la clave `users` = modo de usuario único heredado (comportamiento sin cambios)
- `viewer.password` y `viewer.edition_password` se ignoran en modo multiusuario
- Las valoraciones existentes en la tabla `photos` se mantienen para el modo de usuario único; usa `--migrate-user-preferences` para copiarlas

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
| `skip_hidden_directories` | `true` | Omite los directorios que empiezan por `.` durante el escaneo de fotos |

---

## Categorías

Array de definiciones de categorías. Consulta [Puntuación](SCORING.md) para una documentación detallada de las categorías.

Cada categoría tiene:
- `name` - Identificador de la categoría
- `priority` - Menor = mayor prioridad (se evalúa primero)
- `filters` - Condiciones de coincidencia
- `weights` - Pesos de las métricas de puntuación (deben sumar 100)
- `modifiers` - Ajustes de comportamiento
- `tags` - Vocabulario CLIP para coincidencia basada en etiquetas

> **Pesos de forma y armonía cromática.** El bloque `weights` de cada categoría incluye cinco claves de métricas explicables — `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` y `color_harmony_percent` — pobladas por `--recompute-form`. Se distribuyen a `0` en todas las categorías, por lo que los agregados permanecen idénticos byte a byte hasta que asignes un peso a alguna (entonces vuelve a ejecutar `--recompute-average`). Los pesos dentro de una categoría deben seguir sumando 100.

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
| `portrait_face_ratio_percent` | `5` | Rostro > 5 % del encuadre = retrato |
| `blink_penalty_percent` | `50` | Multiplicador de la puntuación cuando se detecta un parpadeo (0,5x) |
| `night_luminance_threshold` | `0.15` | Luminancia media por debajo de esto = noche |
| `night_iso_threshold` | `3200` | ISO por encima de esto = poca luz |
| `long_exposure_shutter_threshold` | `1.0` | Obturación > 1 s = exposición larga |
| `astro_shutter_threshold` | `10.0` | Obturación > 10 s = astrofotografía |

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

Ajustes automáticos de puntuación según la configuración de la cámara.

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
| `iso_sharpness_compensation` | `true` | Reduce la penalización por nitidez con ISO alto |
| `aperture_isolation_boost` | `true` | Aumenta el aislamiento con aperturas amplias (f/1.4-f/2.8) |

---

## Exposición

Controla el análisis de exposición y la detección de recortes.

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
| `shadow_clip_threshold_percent` | `15` | Señala si > 15 % de los píxeles son negro puro |
| `highlight_clip_threshold_percent` | `10` | Señala si > 10 % de los píxeles son blanco puro |
| `silhouette_detection` | `true` | Detecta siluetas intencionadas |

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
| `noise_sigma_threshold` | `4.0` | El ruido por encima de esto activa una penalización |
| `noise_max_penalty_points` | `1.5` | Penalización máxima por ruido |
| `noise_penalty_per_sigma` | `0.3` | Puntos por sigma por encima del umbral |
| `bimodality_threshold` | `2.5` | Coeficiente de bimodalidad del histograma |
| `bimodality_penalty_points` | `0.5` | Penalización para histogramas bimodales |
| `leading_lines_blend_percent` | `30` | Mezcla en comp_score |
| `oversaturation_threshold` | `0.9` | Umbral de saturación media |
| `oversaturation_pixel_percent` | `5` | Reservado para la detección a nivel de píxel |
| `oversaturation_penalty_points` | `0.5` | Penalización por sobresaturación |

**Fórmula de penalización por ruido:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalización

Controla cómo se escalan las métricas brutas a puntuaciones de 0 a 10.

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
| `category_min_samples` | `50` | Fotos mínimas para la normalización por categoría |

---

## Modelos

Selecciona qué modelos se usan por cada perfil de VRAM.

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
| `keep_in_ram` | `"auto"` | Mantener los modelos en RAM entre los fragmentos multipase (`"auto"`, `"always"`, `"never"`). `auto` comprueba la RAM disponible antes de almacenar en caché. |
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
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Ruta de HuggingFace (VLM de composición 24gb) |
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

Cuando `vram_profile` es `"auto"` (por defecto), el sistema detecta la VRAM disponible de la GPU al arrancar y selecciona el perfil más grande que quepa:

| VRAM detectada | Perfil seleccionado |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Sin GPU | `legacy` (usa la RAM del sistema) |

---

## Modelos de evaluación de calidad

Selecciona el modelo que puntúa la calidad/estética de la imagen, a través de la biblioteca [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

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
| `prefer_llm` | `false` | Preferir un puntuador basado en LLM cuando hay uno disponible |

### Modelos de calidad disponibles

SRCC = coeficiente de correlación de rangos de Spearman en el benchmark KonIQ-10k (1,0 = perfecto).

| Modelo | SRCC | VRAM | Notas |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Por defecto (`auto`); backbone ResNet50 con atención descendente |
| `hyperiqa` | 0.90 | ~2GB | Híper-red, adaptativa al contenido |
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

Ajustes de procesamiento unificados para el procesamiento por lotes en GPU y el modo multipase.

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

**`gpu_batch_size`** - Cuántas imágenes se procesan juntas en la GPU en un único paso hacia delante. Limitado por la VRAM. Autoajustado: se reduce cuando la memoria de la GPU supera el límite.

**`ram_chunk_size`** - Cuántas imágenes se almacenan en caché en la RAM entre los pases del modelo (solo en modo multipase). Reduce la E/S de disco cargando las imágenes una vez por fragmento. Limitado por la RAM del sistema. Autoajustado: se reduce cuando la memoria del sistema supera el límite.

### Referencia de ajustes

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mode` | `"auto"` | Modo de procesamiento: `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Imágenes por lote de GPU (limitado por la VRAM) |
| `ram_chunk_size` | `32` | Imágenes por fragmento de RAM (multipase) |
| `num_workers` | `4` | Hilos de carga de imágenes |
| `load_workers` | `num_workers` | Hilos de carga de fragmentos multipase (limitado a 8, `1` = secuencial) |
| `raw_decode_concurrency` | `0` (auto) | Decodificaciones RAW simultáneas máximas; dimensionado automáticamente según CPU/RAM (1-4), `1` = totalmente serializado |
| `raw_decode_timeout_seconds` | `120` | Abandonar una decodificación RAW colgada tras este retardo (`0` = desactivado); el escaneo falla rápido tras varios bloqueos |
| `exif_prefetch` | `true` | Modo monopase: precarga EXIF en segundo plano en vez de bloquear el hilo de la GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Activar el autoajuste |
| `monitor_interval_seconds` | `5` | Intervalo de comprobación de recursos |
| `tuning_interval_images` | `32` | Reajustar cada N imágenes |
| `min_processing_workers` | `1` | Hilos de carga mínimos |
| `max_processing_workers` | `32` | Hilos de carga máximos |
| `min_gpu_batch_size` | `2` | Tamaño de lote de GPU mínimo |
| `max_gpu_batch_size` | `32` | Tamaño de lote de GPU máximo |
| `min_ram_chunk_size` | `10` | Tamaño de fragmento de RAM mínimo |
| `max_ram_chunk_size` | `128` | Tamaño de fragmento de RAM máximo |
| `memory_limit_percent` | `85` | Límite de uso de memoria del sistema |
| `cpu_target_percent` | `85` | Objetivo de uso de CPU |
| `metrics_print_interval_seconds` | `30` | Intervalo de impresión de estadísticas |
| **thumbnails** | | |
| `photo_size` | `640` | Tamaño de la miniatura almacenada (píxeles) |
| `photo_quality` | `80` | Calidad JPEG de la miniatura |
| `face_padding_ratio` | `0.3` | Relleno alrededor de los recortes de rostro |

### Modos de procesamiento

| Modo | Descripción |
|------|-------------|
| `auto` | Selecciona automáticamente multipase o monopase según la VRAM |
| `multi-pass` | Carga secuencial de modelos (funciona con VRAM limitada) |
| `single-pass` | Todos los modelos cargados a la vez (requiere mucha VRAM) |

### Cómo funciona el modo multipase

En vez de cargar todos los modelos a la vez, el modo multipase:

1. Carga las imágenes en fragmentos de RAM (`ram_chunk_size` por defecto: 32)
2. Para cada fragmento, ejecuta los modelos secuencialmente: cargar modelo → procesar fragmento → descargar modelo
3. Combina los resultados en un pase de agregación final

Cada imagen se carga una vez por fragmento, y los pases se agrupan para caber en la VRAM disponible, de modo que los VLM de etiquetado/composición más grandes se ejecutan incluso con VRAM limitada.

### Comportamiento del autoajuste

El sistema monitoriza el uso de recursos y ajusta:

| Métrica | Acción |
|--------|--------|
| Memoria de GPU > límite | Reduce `gpu_batch_size` en un 25 % |
| RAM del sistema > límite | Reduce `ram_chunk_size` en un 25 % |
| RAM del sistema < (límite - 20 %) | Aumenta `ram_chunk_size` en un 25 % |
| CPU > objetivo | Sugiere menos workers |
| Tiempos de espera de cola > 5 % | Sugiere más workers |

### Agrupación dinámica de pases

Cuando la VRAM lo permite, varios modelos pequeños se ejecutan juntos:

| VRAM | Pase 1 | Pase 2 |
|------|--------|--------|
| 8GB | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12GB | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16GB | CLIP + SAMP-Net + InsightFace + TOPIQ | VLM de etiquetado |
| 24GB+ | Todos los modelos juntos (monopase) | - |

### Opciones de CLI

```bash
# Por defecto: multipase automático con agrupación óptima
python facet.py /path/to/photos

# Forzar monopase (todos los modelos cargados a la vez)
python facet.py /path --single-pass

# Ejecutar solo un pase concreto
python facet.py /path --pass quality       # Solo TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (mérito estético)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (calidad + distorsión)
python facet.py /path --pass tags          # Solo el etiquetador configurado
python facet.py /path --pass composition   # Solo SAMP-Net
python facet.py /path --pass faces         # Solo InsightFace
python facet.py /path --pass embeddings    # Solo embeddings CLIP/SigLIP
python facet.py /path --pass saliency      # Saliencia del sujeto BiRefNet

# Listar los modelos disponibles
python facet.py --list-models
```

---

## Detección de ráfagas

Agrupa fotos similares tomadas en rápida sucesión.

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

Pesos usados por el descarte de ráfagas para calcular una puntuación compuesta que selecciona la mejor toma dentro de cada grupo de ráfaga. Los pesos deben sumar 1,0.

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
| `weight_aggregate` | `0.4` | Peso de la puntuación agregada global |
| `weight_aesthetic` | `0.25` | Peso de la puntuación de calidad estética |
| `weight_sharpness` | `0.2` | Peso de la puntuación de nitidez técnica |
| `weight_blink` | `0.15` | Peso de penalización por parpadeos detectados (mayor = penalización más fuerte) |

---

## Detección de duplicados

Detecta fotos duplicadas de forma global usando la comparación de hash perceptual (pHash).

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
| `similarity_threshold_percent` | `90` | Filtro pHash estricto (90 % = distancia de Hamming <= 6 de 64 bits); se usa como único criterio cuando falta un embedding para alguna de las fotos |
| `prefilter_hamming` | `12` | Anulación opcional (ausente en el archivo distribuido). Filtro de Hamming flexible de la etapa 1 para el conjunto de candidatos cuando ambas fotos tienen embeddings (forzado a ser >= el filtro estricto) |
| `embedding_cosine_threshold` | `0.90` | Anulación opcional (ausente en el archivo distribuido). Filtro coseno SigLIP/CLIP de la etapa 2: un candidato de pHash flexible solo se fusiona cuando el coseno >= esto |

La detección es de dos etapas: candidatos de pHash flexible (recall) confirmados por un filtro coseno de embedding estricto (precisión). Las fotos sin embedding recurren al criterio estricto solo de pHash, de modo que el comportamiento no cambia cuando faltan embeddings.

Ejecuta `python facet.py --detect-duplicates` para detectar y agrupar duplicados. Ejecuta `python facet.py --sweep-dedup-thresholds [labels.json]` para evaluar el filtro coseno: con un JSON de etiquetas imprime una tabla de precisión/recall, de lo contrario la distribución coseno de los candidatos y cuántas colisiones de pHash estricto rechaza el filtro.

---

## Nivel IQA extendido (opcional)

Puntuadores de calidad pesados/experimentales, **DESACTIVADOS por defecto** y **nunca un sustituto de TOPIQ**: solo añaden columnas suplementarias cuando se activan explícitamente. Cuando están activados, los puntuadores extendidos se ejecutan **durante un escaneo normal** y escriben sus propias columnas; un fallo de carga/VRAM se registra y la columna se deja como `NULL` (el escaneo nunca se aborta).

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
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | IQA basado en LLM Q-Align (respaldado por pyiqa). `"4bit"` (~6-8GB VRAM) es la opción práctica en una tarjeta de 16GB; `"8bit"` ~12-14GB; precisión completa (`true`) requiere 16GB+. 4-/8-bit necesitan `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (cabeza SigLIP, ~2GB). Requiere el paquete `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU de 16GB+; de lo contrario se omite y se deja NULL). |

**Instala las dependencias opcionales** de lo que actives: `pip install -e .[iqa-extended]` (añade `aesthetic-predictor-v2-5` + `bitsandbytes`), o descomenta las líneas correspondientes en `requirements.txt`. Q-Align se distribuye con `pyiqa`; DeQA-Score se descarga a través de `transformers`.

Cuando están activadas, cada métrica se expone al agregado ponderado pero su peso por defecto es 0, por lo que `--recompute-average` es idéntico bit a bit hasta que le des un peso. Ejecuta `python facet.py --eval-iqa-srcc` para medir lo bien que cada métrica clasifica tu biblioteca frente a tus propias valoraciones por estrellas.

**Visualización en el visor.** Cuando alguna de estas columnas está poblada, el visor muestra el valor en el panel de **Calidad** del detalle de la foto (`Q-Align`, `Aesthetic V2.5`, `DeQA`) y expone un control deslizante de rango correspondiente en la barra lateral de filtros de la galería, bajo **Calidad extendida** (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). Las fotos escaneadas antes de activar el nivel simplemente tienen `NULL` en estas columnas y no se ven afectadas por los filtros.

**Robustez.** DeQA-Score carga código remoto con `trust_remote_code` cuya firma de forward varía entre revisiones de checkpoint; su puntuador es defensivo: cualquier fallo de predicción (firma incorrecta, forma de salida inesperada, OOM) se captura y el `deqa_score` de la imagen se deja como `NULL` en vez de bloquear el escaneo.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confianza de detección mínima |
| `min_face_size` | `20` | Tamaño mínimo del rostro en píxeles |
| `blink_ear_threshold` | `0.28` | Relación de aspecto del ojo (EAR) para la detección de parpadeos |
| `min_faces_for_group` | `4` | Rostros mínimos para clasificar como retrato de grupo (recalculado con `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Anulación opcional (ausente en el archivo distribuido; valor por defecto del código `false`). Carga el módulo `landmark_3d_68` de InsightFace para extraer la pose de la cabeza (yaw/pitch/roll). Cuesta ~5MB de pesos ONNX adicionales. Actualmente informativo; futuras mejoras de perfil/silueta lo leerán. |
| `eyes_closed_max` | `4.0` | Puntuación de ojos abiertos por cara (0–10) igual o inferior a la cual el laboratorio de descarte marca una cara como parpadeo. Controla los anillos de cara rojo/naranja/verde y el control deslizante de umbral de ojos (movido desde una constante codificada) |
| `poor_expression_min` | `4.0` | Puntuación de sonrisa/expresión por cara (0–10) por debajo de la cual el laboratorio marca una expresión débil. Controla el anillo de cara de expresión y su control deslizante (movido desde una constante codificada) |
| `blendshapes.enabled` | `true` | Usa las puntuaciones blendshape de MediaPipe (basadas en apariencia) para `eyes_open_score` / `smile_score` por cara cuando MediaPipe y el paquete `face_landmarker.task` están disponibles; si `true`, sustituyen las puntuaciones de geometría de puntos de referencia, en caso contrario el respaldo geométrico se ejecuta automáticamente. Dependencia opcional — instalar con `pip install mediapipe==0.10.35 --no-deps` (nunca un simple `pip install mediapipe`). Ver [FACE_RECOGNITION.md](FACE_RECOGNITION.md#señales-de-expresión-por-rostro-ojos-abiertos--sonrisa). |
| `blendshapes.min_crop_size` | `192` | Las caras cuyo recorte con relleno sea menor que este valor (px, lado más corto) recurren a la puntuación geométrica en lugar de ampliar una cara diminuta |

---

## Agrupación de rostros

Agrupación HDBSCAN para el reconocimiento de rostros.

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
| `min_faces_per_person` | `2` | Fotos mínimas por persona |
| `min_samples` | `2` | Parámetro min_samples de HDBSCAN |
| `auto_merge_distance_percent` | `15` | Fusión automática dentro de esta distancia |
| `clustering_algorithm` | `"best"` | Algoritmo de HDBSCAN |
| `leaf_size` | `40` | Tamaño de hoja del árbol (solo CPU) |
| `use_gpu` | `"auto"` | Modo GPU: `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Similitud de centroide para emparejar |
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
| `crop_padding` | `0.3` | Relación de relleno para los recortes de rostro |
| `use_db_thumbnails` | `true` | Usar las miniaturas almacenadas |
| `face_thumbnail_size` | `640` | Tamaño de la miniatura en píxeles |
| `face_thumbnail_quality` | `90` | Calidad JPEG |
| `extract_workers` | `2` | Workers de extracción en paralelo |
| `extract_batch_size` | `16` | Tamaño del lote de extracción |
| `refill_workers` | `4` | Workers de rellenado de miniaturas |
| `refill_batch_size` | `100` | Tamaño del lote de rellenado |
| **auto_tuning** | | |
| `enabled` | `true` | Activar el ajuste basado en memoria |
| `memory_limit_percent` | `80` | Límite de uso de memoria |
| `min_batch_size` | `8` | Tamaño de lote mínimo |
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
| `saturation_threshold_percent` | `5` | Saturación media < 5 % = monocromo |

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

Configurado a través de `models.profiles.*.tagging_model`:

| Modelo | VRAM | Estilo de etiqueta | Notas |
|-------|------|-----------|-------|
| `clip` | 0 (reutiliza embeddings) | Ambiente/atmósfera (dramatic, golden_hour, vintage) | Sin carga de modelo adicional; menos detección literal de objetos |
| `qwen3.5-2b` | ~4GB | Escenas estructuradas (landscape, architecture, reflection) | Requiere transformers + VRAM adicional |
| `qwen3.5-4b` | ~8GB | Escenas detalladas con matices | Mayor VRAM; inferencia más lenta |

### Modelos de etiquetado por defecto por perfil

| Perfil | Modelo de etiquetado | Modelo de embedding |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Reetiquetar fotos

```bash
python facet.py --recompute-tags       # Reetiquetar usando el modelo configurado por perfil
python facet.py --recompute-tags-vlm   # Reetiquetar usando el etiquetador VLM
```

---

## Etiquetas independientes

Etiquetas con listas de sinónimos que no están vinculadas a ninguna categoría concreta. Están disponibles para todas las fotos independientemente de la asignación de categoría. Cada clave es el nombre de la etiqueta; el valor es una lista de sinónimos para la coincidencia CLIP/VLM.

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

Añade nuevas etiquetas independientes proporcionando una clave y una lista de sinónimos. Las etiquetas definidas aquí se combinan con las etiquetas específicas de categoría para formar el vocabulario de etiquetas completo.

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
| `aesthetic_max_threshold` | `9.0` | Advertir si la estética máxima está por debajo de esto |
| `aesthetic_target` | `9.5` | Objetivo para aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Umbral de calidad de "alto valor" |
| `quality_weight_threshold_percent` | `10` | Advertir si el peso de calidad ≤ esto |
| `correlation_dominant_threshold` | `0.5` | Advertencia de "señal dominante" |
| `category_min_samples` | `50` | Fotos mínimas por categoría |
| `category_imbalance_threshold` | `0.5` | Advertencia de brecha de puntuación |
| `score_clustering_std_threshold` | `1.0` | Advertir si la desviación estándar < esto |
| `top_score_threshold` | `8.5` | Advertir si el agregado máximo < esto |
| `exposure_avg_threshold` | `8.0` | Advertir si la exposición media > esto |

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
    "moment_confidence_min": 0,
    "path_mapping": {}
  }
}
```

> **Nota:** `sort_options` (omitido como `{ ... }` arriba) asigna columnas de la BD a etiquetas de menú desplegable y rara vez se edita. El grupo **Content** incluye una ordenación `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (los NULL se hunden al final).

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `default_category` | `""` | Filtro de categoría por defecto |
| `edition_password` | `""` | Contraseña para desbloquear el modo edición (vacío = desactivado) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Mínimo para la optimización |
| `pair_selection_strategy` | `"learning"` | Estrategia de pares: `learning` (arranque en frío por diversidad de embeddings + desacuerdo de rango una vez entrenado), `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Conjunto de candidatos aleatorio dentro del cual la estrategia `learning` muestrea pares |
| `show_current_scores` | `true` | Mostrar puntuaciones durante la comparación |
| **pagination** | | |
| `default_per_page` | `64` | Fotos por página |
| **dropdowns** | | |
| `max_cameras` | `50` | Máximo de cámaras en el desplegable |
| `max_lenses` | `50` | Máximo de objetivos |
| `max_persons` | `50` | Máximo de personas |
| `max_tags` | `20` | Máximo de etiquetas |
| `min_photos_for_person` | `10` | Ocultar del desplegable a las personas con menos fotos |
| **persons** | | |
| `needs_naming_min_faces` | `5` | face_count mínimo para que un grupo autoagrupado aparezca en la sección "Necesita nombre" de `/persons` |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nombre del binario darktable-cli o ruta absoluta |
| `darktable.profiles` | `[]` | Array de perfiles de exportación darktable con nombre (ver abajo) |
| `darktable.profiles[].name` | *(obligatorio)* | Nombre del perfil mostrado (usado en el menú de descarga y el parámetro `profile` de la API) |
| `darktable.profiles[].hq` | `true` | Pasa `--hq true` para exportación de alta calidad |
| `darktable.profiles[].width` | *(omitir)* | Ancho de salida máximo (omitir para resolución completa) |
| `darktable.profiles[].height` | *(omitir)* | Alto de salida máximo (omitir para resolución completa) |
| `darktable.profiles[].style` | *(omitir)* | Nombre del estilo darktable aplicado durante la exportación (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | Cuando es `false`, pasa `--apply-custom-presets false` para que solo se renderice el `style` explícito (no los presets autoaplicados) |
| `darktable.profiles[].extra_args` | `[]` | Argumentos de CLI adicionales (p. ej., `["--style-overwrite"]`) |
| **display** | | |
| `tags_per_photo` | `4` | Etiquetas mostradas en las tarjetas |
| `card_width_px` | `168` | Ancho de la tarjeta |
| `image_width_px` | `160` | Ancho de la imagen |
| `image_jpeg_quality` | `96` | Calidad JPEG para la conversión RAW/HEIF en `/api/download` y `/api/image` (1-100) |
| `thumbnail_slider.min_px` | `120` | Tamaño mínimo de miniatura (px) |
| `thumbnail_slider.max_px` | `400` | Tamaño máximo de miniatura (px) |
| `thumbnail_slider.default_px` | `168` | Tamaño de miniatura por defecto (px) |
| `thumbnail_slider.step_px` | `8` | Incremento del paso del control deslizante (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Tamaño de la miniatura |
| `jpeg_quality` | `80` | Calidad JPEG |
| `crop_padding_ratio` | `0.2` | Relleno del rostro |
| `min_crop_size_px` | `20` | Tamaño mínimo de recorte |
| **quality_thresholds** | | |
| `good` | `6` | Umbral de bueno |
| `great` | `7` | Umbral de muy bueno |
| `excellent` | `8` | Umbral de excelente |
| `best` | `9` | Umbral de mejor |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Mínimo de Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Relación de rostro para los pesos |
| `low_light_max_luminance` | `0.2` | Umbral de poca luz |
| **defaults** | | |
| `type` | `""` | Filtro de tipo de foto por defecto (p. ej., `"portraits"`, `"landscapes"` o `""` para Todas) |
| `sort` | `"aggregate"` | Columna de ordenación por defecto |
| `sort_direction` | `"DESC"` | Dirección de ordenación por defecto (`"ASC"` o `"DESC"`) |
| `hide_blinks` | `true` | Ocultar fotos con parpadeo por defecto |
| `hide_bursts` | `true` | Mostrar solo la mejor de la ráfaga por defecto |
| `hide_duplicates` | `true` | Ocultar las fotos duplicadas no principales por defecto |
| `hide_details` | `true` | Ocultar los detalles de la foto en las tarjetas por defecto |
| `tooltip_mode` | `"hover"` | Activación del tooltip: `"hover"`, `"click"` u `"off"`. Sustituye al booleano `hide_tooltip` anterior. |
| `hide_rejected` | `true` | Ocultar las fotos rechazadas por defecto |
| `gallery_mode` | `"mosaic"` | Disposición de la galería por defecto (`"grid"` o `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Orígenes permitidos por CORS para el servidor FastAPI. Añade tu dominio o la URL del proxy inverso al alojar de forma remota. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(valor por defecto seguro para SPA)_ | Valor de la cabecera Content-Security-Policy. Por defecto es una política que permite los recursos propios de la SPA (script/estilo de tema en línea, Google Fonts, teselas de OpenStreetMap, API del mismo origen). Establécelo en `""` para desactivarlo, o proporciona una política más estricta. |
| `security_headers.hsts` | `false` | Enviar `Strict-Transport-Security`. Actívalo solo cuando el visor se sirve por HTTPS. |
| **Otros** | | |
| `cache_ttl_seconds` | `60` | TTL de la caché de consultas |
| `notification_duration_ms` | `2000` | Duración del aviso emergente |
| `moment_confidence_min` | `0` | Por debajo de este posterior `narrative_moment_confidence` almacenado (0-1), las etiquetas de momento se muestran atenuadas con un sufijo "(incierto)" en la cabecera de Escenas, la cabecera de grupo de escena del Descarte y el tooltip de foto de la galería. `0` = nunca atenuar |

### Funciones

Activa o desactiva funciones opcionales para reducir el uso de memoria o simplificar la UI:

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `show_similar_button` | `true` | Mostrar el botón "Buscar similares" en las tarjetas de foto (usa numpy para la similitud CLIP) |
| `show_merge_suggestions` | `true` | Activar la función de sugerencias de fusión en la página de gestión de personas |
| `show_rating_controls` | `true` | Mostrar los controles de valoración por estrellas y favoritos |
| `show_rating_badge` | `true` | Mostrar la insignia de valoración en las tarjetas de foto |
| `show_scan_button` | `false` | Mostrar el botón de iniciar escaneo para los usuarios superadmin (requiere GPU en el host del visor) |
| `metrics_enabled` | `false` | Activar el endpoint público de Prometheus `GET /metrics`. Desactivado por defecto: expone recuentos de fotos/personas/rostros, tamaño de la BD y memoria del proceso; actívalo solo cuando el endpoint sea accesible desde la red del scraper, no desde internet público. |
| `show_semantic_search` | `true` | Mostrar la barra de búsqueda semántica (búsqueda de texto a imagen usando embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Mostrar la función de álbumes (crear, gestionar y explorar álbumes de fotos) |
| `show_critique` | `true` | Mostrar el botón de crítica de IA en las tarjetas de foto (desglose de puntuación basado en reglas) |
| `show_vlm_critique` | `true` | Activar el modo de crítica con VLM (requiere perfil de VRAM 16gb/24gb). El código recurre a `false` cuando falta la clave. |
| `show_embed_metadata` | `true` | Mostrar la acción "Escribir metadatos en el archivo" por miniatura en modo edición (incrusta valoraciones/palabras clave en la imagen original a través de exiftool) |
| `show_memories` | `true` | Mostrar el diálogo de recuerdos "Un día como hoy" (fotos tomadas en la misma fecha en años anteriores) |
| `show_captions` | `true` | Mostrar las descripciones generadas por IA en las tarjetas de foto |
| `show_timeline` | `true` | Mostrar la vista de línea de tiempo para la exploración cronológica con navegación por fechas |
| `show_map` | `true` | Mostrar la vista de mapa con las ubicaciones de fotos basadas en GPS (requiere Leaflet). El código recurre a `false` cuando falta la clave. |
| `show_capsules` | `true` | Mostrar la vista de Cápsulas (diaporamas de fotos curados agrupados por tema) |
| `show_folders` | `true` | Mostrar la exploración basada en carpetas de la estructura de directorios de fotos |
| `show_scenes` | `true` | Mostrar la vista de Escenas (`/scenes`) que agrupa las fotos principales de ráfaga en escenas cronológicas para un descarte en orden narrativo |
| `show_my_taste` | `true` | Mostrar la ordenación "Mi gusto" respaldada por la puntuación aprendida del clasificador personal, con una insignia de confianza de cobertura aprendida / precisión |
| `show_social_export` | `true` | Muestra el menú **Recorte social** (solo edición): recortes con reconocimiento del sujeto para relaciones de aspecto de redes sociales. Consulta [Exportación social](#exportación-social) |
| `show_proofing` | `false` | Activar la revisión de cliente en los álbumes compartidos: un enlace de compartir (más un PIN opcional) permite que un cliente sin cuenta marque fotos con un corazón y deje comentarios, que el propietario del álbum revisa desde un diálogo restringido a edición. Desactivado por defecto. Consulta [Revisión del cliente](#revisión-del-cliente) |

**Optimización de memoria:** Establecer `show_similar_button: false` evita que se cargue numpy, reduciendo la huella de memoria del visor. La función de fotos similares calcula la similitud coseno de los embeddings CLIP, lo que requiere numpy.

### Revisión del cliente

`viewer.features.show_proofing` (predeterminado `false`) convierte cualquier álbum compartido en una superficie de revisión de cliente. Un enlace de compartir —opcionalmente protegido por `viewer.proofing.pin`— permite que un cliente sin cuenta canjee el token de compartir por una sesión de corta duración, y luego marque fotos con un corazón y deje comentarios. Las selecciones viven en una tabla dedicada `album_client_picks`, acotada a las fotos de ese álbum y totalmente aislada de las valoraciones del propietario (nunca tocan `photos.is_favorite` / `user_preferences` ni entrenan al clasificador personal). El propietario lee las selecciones desde un diálogo restringido a edición en la tarjeta del álbum.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `features.show_proofing` | `false` | Interruptor principal de la revisión de cliente en los álbumes compartidos |
| `proofing.pin` | `""` | PIN opcional que un cliente debe introducir (junto con el token de compartir) para abrir una sesión de revisión. Vacío = sin PIN. Las comprobaciones tienen límite de frecuencia y son seguras byte a byte |
| `proofing.session_minutes` | `1440` | Duración en minutos del token de sesión de revisión de cliente (predeterminado 24 h). Las sesiones también dejan de funcionar en cuanto se deja de compartir el álbum o se desactiva la revisión |

### Mapeo de rutas

Asigna las rutas de la base de datos a rutas del sistema de archivos local. Útil cuando las fotos se puntuaron en una máquina (p. ej., Windows con rutas UNC) pero el visor se ejecuta en otra (p. ej., un NAS Linux con puntos de montaje).

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
- Solo se aplica al **leer archivos del disco** (servicio de imágenes a tamaño completo, descargas de archivos, crítica VLM). Las rutas de la base de datos nunca se modifican.
- La normalización de barra invertida/barra normal se gestiona automáticamente: `\\NAS\Photos\img.jpg` y `//NAS/Photos/img.jpg` coinciden ambas.
- Los mapeos se evalúan en orden; gana el primer prefijo coincidente.
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

Anula los ajustes globales de `performance` al ejecutar el visor. Útil para despliegues en NAS de poca memoria donde la puntuación necesita muchos recursos pero el visor no.

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
| `mmap_size_mb` | *(global)* | Anulación del tamaño de mmap de SQLite para las conexiones del visor. `0` desactiva mmap. |
| `cache_size_mb` | *(global)* | Anulación del tamaño de caché de SQLite para las conexiones del visor |
| `pool_size` | `5` | Tamaño del pool de conexiones (reduce para sistemas de poca memoria) |
| `thumbnail_cache_size` | `2000` | Máximo de entradas en la caché en memoria de redimensionado de miniaturas |
| `face_cache_size` | `500` | Máximo de entradas en la caché en memoria de miniaturas de rostro |

Cuando no se establecen, el visor usa los valores globales de `performance`. Consulta [Despliegue](DEPLOYMENT.md) para los ajustes recomendados de NAS.

---

## Rendimiento

Ajustes de rendimiento de la base de datos.

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

> **Nota:** `wal_checkpoint_minutes` es una anulación opcional y **no** está presente en el bloque `performance` distribuido (que solo contiene `mmap_size_mb`, `cache_size_mb` y `slow_request_ms`). Añádelo explícitamente para cambiar el valor por defecto de `30`.

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | Tamaño de E/S mapeada en memoria de SQLite |
| `cache_size_mb` | `128` | Tamaño de la caché de SQLite |
| `wal_checkpoint_minutes` | `30` | Anulación opcional (ausente en el archivo distribuido). Intervalo en minutos del `PRAGMA wal_checkpoint(TRUNCATE)` en segundo plano del visor. Evita el crecimiento del WAL en despliegues de larga duración. Establécelo en `0` para desactivarlo. |
| `slow_request_ms` | `1000` | Las solicitudes de la API del visor más lentas que estos milisegundos se registran como WARNING con un marcador `SLOW`. Establécelo en `0` para desactivarlo. |

---

## Almacenamiento

Controla dónde se almacenan las miniaturas y los embeddings. Por defecto son columnas BLOB en la base de datos SQLite; el modo de sistema de archivos los almacena como archivos en disco en su lugar, lo que reduce el tamaño de la base de datos.

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
- Los archivos se organizan por hash SHA-256 de la ruta de la foto, con subdirectorios de dos caracteres para evitar demasiados archivos en un único directorio (p. ej., `thumbnails/a3/a3f8..._640.jpg`).
- Eliminar una foto borra todos los tamaños de miniatura y archivos de embedding asociados.
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
| `high_score_threshold` | `8.0` | Puntuación agregada mínima para activar los eventos `on_high_score` |
| `webhooks` | `[]` | Lista de endpoints de webhook que reciben cargas JSON por POST |
| `actions` | `{}` | Acciones integradas con nombre activadas por eventos |

### Eventos admitidos

| Evento | Activador | Carga |
|-------|---------|---------|
| `on_score_complete` | Después de puntuar cada foto | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Cuando una foto entra en la base de datos | Igual que `on_score_complete` |
| `on_high_score` | Cuando el agregado ≥ `high_score_threshold` | Igual que `on_score_complete` |
| `on_burst_detected` | Cuando se identifica un grupo de ráfaga | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Escribir un plugin

Coloca un archivo `.py` en el directorio `plugins/`. Define funciones con el nombre de los eventos que quieras gestionar:

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

Opciones del webhook: `url` (obligatorio), `events` (lista de nombres de evento), `min_score` (agregado mínimo para activar).

### Acciones integradas

| Acción | Descripción | Opciones |
|--------|-------------|---------|
| `copy_to_folder` | Copia la foto a una carpeta | `folder`, `min_score` |
| `send_notification` | Registra una notificación | `min_score` |

### Endpoints de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/plugins` | Lista los plugins, webhooks y acciones cargados |
| `POST` | `/api/plugins/test-webhook` | Envía una carga de prueba a una URL de webhook |

---

## Cápsulas

Diaporamas de fotos curados (pases de diapositivas) agrupados por tema. Las cápsulas se generan automáticamente a partir de tu biblioteca de fotos y se almacenan en caché con un TTL configurable.

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

### Ajustes globales

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `min_aggregate` | `6.0` | Puntuación agregada mínima para que las fotos se incluyan en las cápsulas |
| `max_photos_per_capsule` | `40` | Máximo de fotos por cápsula (diversidad MMR aplicada por encima de 5) |
| `max_photo_overlap` | `0.2` | Fracción máxima de fotos compartidas entre dos cápsulas antes de que la deduplicación elimine una |
| `mmr_lambda` | `0.5` | Peso de diversidad MMR: 0=maximizar diversidad, 1=maximizar calidad |
| `mmr_moment_weight` | `0.0` | Peso opcional que combina el `narrative_moment_confidence` de cada foto en la selección MMR de la cápsula. `0.0` = comportamiento sin cambios |
| `freshness_hours` | `24` | TTL de la caché y periodo de rotación de las fotos de portada y las cápsulas semilladas |
| `reverse_geocoding` | `true` | Activar la geocodificación inversa sin conexión para los títulos de las cápsulas de ubicación/viaje (requiere el paquete `reverse_geocoder`) |

### Tipos de cápsula

| Tipo | Descripción |
|------|-------------|
| `journey` | Viajes detectados mediante agrupación GPS + intervalos temporales. Los títulos incluyen el nombre del destino cuando la geocodificación está activada. |
| `faces_of` | Las mejores fotos de cada persona reconocida |
| `seasonal` | Fotos agrupadas por estación + año |
| `golden` | El 1 % superior por puntuación agregada |
| `color_story` | Grupos visualmente similares mediante agrupación de embeddings CLIP |
| `this_week` | "Esta semana, hace años": un "Un día como hoy" ampliado a ±3 días |
| `location` | Grupos de fotos geoetiquetadas con nombres de lugar geocodificados inversamente |
| `person_pair` | Parejas de personas con nombre que aparecen juntas |
| `seeded` | Descubrimiento basado en semillas por tiempo, similitud, persona, etiqueta, ubicación, ambiente |
| `progress` | "Tu fotografía está mejorando" a partir de las tendencias de puntuación trimestrales |
| `color_palette` | "Color del mes" a partir de los perfiles de saturación/monocromo |
| `rare_pair` | Parejas de personas poco frecuentes en fotos de alta puntuación |
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
| `tag` | Etiquetas de la foto (requiere la tabla `photo_tags`) |
| `day_of_week` | Día de la semana (domingo-sábado) |
| `composition` | Patrón de composición SAMP-Net (rule_of_thirds, horizontal, etc.) |
| `focal_range` | Tramos de distancia focal: ultra gran angular (<24mm), gran angular (24-35mm), estándar (36-70mm), retrato (71-135mm), teleobjetivo (136-300mm), súper teleobjetivo (300mm+) |
| `category` | Categoría de contenido de la foto (portrait, landscape, street, etc.) |
| `time_of_day` | Tramos horarios: mañana dorada, mañana, mediodía, tarde, tarde dorada, noche |
| `star_rating` | Valoraciones por estrellas del usuario (1-5 estrellas) |

También se generan combinaciones interdimensionales (p. ej., cámara × año, focal_range × categoría, categoría × año).

### Transiciones del pase de diapositivas

Cada tipo de cápsula se asigna a una transición de diapositiva temática:

| Transición | Usada por | Efecto |
|-----------|---------|--------|
| `crossfade` | Por defecto | Cambio de opacidad de 300ms |
| `slide` | journey, location, this_week | Desliza desde la derecha (500ms) |
| `zoom` | faces_of, color_story | Escala 1.05→1.0 con fundido (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lento 1.0→1.08 durante la duración de la diapositiva |

### Geocodificación inversa

Las cápsulas de ubicación y viaje usan geocodificación inversa sin conexión a través del paquete `reverse_geocoder` (conjunto de datos local de GeoNames, ~30MB, sin llamadas a API). Los resultados se almacenan en caché en la tabla de base de datos `location_names` con una resolución de cuadrícula de 0,1° (~11km).

Instalación: `pip install reverse_geocoder`

Establece `"reverse_geocoding": false` para desactivarla y recurrir a la visualización de coordenadas.

## Grupos de similitud

Ajustes para la función de descarte de fotos similares con IA, que agrupa fotos visualmente similares usando embeddings CLIP/SigLIP:

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
| `default_threshold` | `0.85` | Similitud coseno mínima (0.0-1.0) para considerar dos fotos como visualmente similares. Valores más bajos producen grupos más grandes pero con menos similitud visual. |
| `min_group_size` | `2` | Número mínimo de fotos necesarias para formar un grupo de similitud |
| `max_photos` | `10000` | Máximo de fotos a cargar para el cálculo de similitud (coste O(n²)). Auméntalo para bibliotecas más grandes a costa del tiempo de cálculo. |
| `max_group_size` | `50` | Máximo de fotos por grupo de similitud. Los grupos más grandes se dividen para mantener la UI usable. |

## Descarte automático

Descarte automático de un botón para el laboratorio de descarte (`POST /api/culling/auto`, restringido a edición). Descarta todo un ámbito —todos los grupos, o solo ráfagas / similares / escenas, opcionalmente acotado a un álbum o una ventana de fechas— en una sola pasada. Cada grupo conserva su mejor foto más todo lo que quede dentro de un margen derivado del rigor (el mismo presupuesto de fotos a conservar que el control deslizante manual del laboratorio), con un mínimo por grupo como suelo, y descarta el resto.

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `default_strictness` | `50` | Presupuesto de fotos a conservar (0–100) usado cuando la solicitud omite `strictness`. Más alto = conservar menos fotos por grupo (margen más ajustado en torno a la mejor del grupo) |
| `highlights_min` | `8.0` | Puntuación agregada mínima para que la mejor foto de un grupo se recopile en el álbum opcional de **Destacados** cuando se aplica un descarte automático (idempotente) |

`dry_run` está activado por defecto y devuelve una vista previa de conservar/descartar por grupo; una aplicación registra además filas de comparación con `source='culling'` e impulsa un reentrenamiento automático. Consulta [Galería web — Descarte automático](VIEWER.md#auto-cull).

## Perfiles de descarte por género

Preajustes por género que agrupan todos los controles de descarte en un clic: deportes conserva solo la foto más nítida de una ráfaga larga, las bodas conservan más variantes con los ojos abiertos como prioridad, los conciertos relajan los umbrales de ojos/expresión, la fauna elimina por completo el filtro de rostro humano. La sala oscura de descarte muestra un selector de preajuste.

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

| Ajuste | Descripción |
|---|---|
| `default` | Id de perfil aplicado cuando no hay ninguno guardado en el cliente |
| `profiles.<id>.label_key` | Ruta i18n del nombre visible del preajuste (`culling.profiles.*`) |
| `profiles.<id>.strictness` | Presupuesto de conservación (0–100) que alimenta el margen de auto-descarte cuando el preajuste está activo |
| `profiles.<id>.eyes_closed_max` | Puntuación de ojos abiertos (0–10) por debajo de la cual un rostro cuenta como cerrado — anula `face_detection.eyes_closed_max` en las insignias de rostro |
| `profiles.<id>.poor_expression_min` | Puntuación de expresión/sonrisa (0–10) por debajo de la cual un rostro cuenta como pobre — anula `face_detection.poor_expression_min` |
| `profiles.<id>.keep_min_per_group` | Mínimo por grupo del conjunto conservado por el auto-descarte |
| `profiles.<id>.similarity_threshold` | Umbral de agrupación por similitud (porcentaje) que aplica la sala oscura cuando se selecciona el preajuste |

Punto de acceso (solo lectura): `GET /api/culling/profiles` devuelve la lista ordenada de preajustes y el predeterminado. La solicitud de auto-descarte (`POST /api/culling/auto`) y el lote por rostro (`POST /api/culling-group/faces`) aceptan un `profile` opcional; un `strictness`/`min_keep_per_group` explícito en la solicitud siempre prevalece sobre el preajuste.

## Escenas

Ajustes para la vista de Escenas, que agrupa las fotos principales de ráfaga en escenas cronológicas (divididas por intervalos de tiempo de captura) para un descarte en orden narrativo:

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `gap_minutes` | `20.0` | Una nueva escena empieza cuando pasan más de estos minutos entre fotos principales de ráfaga consecutivas (el suelo cuando `adaptive` está activado) |
| `min_size` | `2` | Fotos mínimas para que se muestre una escena |
| `max_photos` | `5000` | Máximo de fotos principales de ráfaga cargadas para la agrupación en escenas |
| `max_scene_size` | `60` | Una escena mayor que esto se subdivide recursivamente en sus mayores intervalos internos, de modo que un evento fotografiado de forma continua nunca colapse en una única escena gigante |
| `adaptive` | `true` | Cuando está activado, el intervalo efectivo se amplía a `adaptive_k × mediana` de los intervalos consecutivos de la sesión (se ajusta para la fotografía rápida, se relaja para vacaciones dispersas) |
| `adaptive_k` | `6.0` | Multiplicador aplicado a la mediana del intervalo cuando `adaptive` está activado |
| `split_on_moment_change` | `false` | Cuando está activado (y los momentos narrativos están calculados), subdivide una secuencia temporal donde el momento dominante cambia y se mantiene durante `moment_split_min_run` fotogramas |
| `moment_split_min_run` | `4` | Histéresis para `split_on_moment_change`: cuántos fotogramas consecutivos debe persistir un nuevo momento para forzar un límite |

## Narrative Moments

Etiquetado zero-shot del «momento» de escena/actividad de cada foto. El vocabulario **general** por defecto cubre `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle` u `other` — de modo que funciona en cualquier biblioteca, no solo en bodas (`wedding` se incluye como género opcional). Poblado por `--detect-moments` (se ejecuta automáticamente al final de cada escaneo) y mostrado como nombres de escena y un filtro de galería. Algo que ni Narrative Select ni AfterShoot hacen.

La señal es **semántica de leyenda**: la leyenda de IA de cada foto se codifica una vez con la torre de texto y se almacena (la columna `caption_embedding`); el momento es el mejor coseno **agrupado por máximo (max-pool)** de ese embedding de leyenda frente a los prompts de texto por momento. El embedding de imagen almacenado es el respaldo cuando una foto no tiene leyenda. El texto de la leyenda coincide con los prompts de los momentos ~2,4× más limpiamente que el embedding de imagen en bruto, por lo que la señal `caption` lleva umbrales más altos que el respaldo `image`; cada uno se ajusta por backend (los cosenos de open_clip son mucho más bajos que los de SigLIP). Los valores de `transformers` (SigLIP) se incluyen como valores por defecto conservadores — vuelve a ajustarlos si ejecutas un perfil SigLIP.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Interruptor maestro; cuando está desactivado, `--detect-moments` y el hook del escaneo no hacen nada |
| `prompt_template` | `"a photo of {desc}"` | Envoltorio aplicado a cada prompt antes de codificarlo |
| `default_event_type` | `"general"` | Qué vocabulario de `event_types` está activo. `general` = 20 momentos de escena/actividad agnósticos; `wedding` se incluye como género opcional |
| `pooling` | `"max"` | Puntuación por momento = el mejor coseno de un único prompt (max-pool), más discriminativo que promediar |
| `caption_min_confidence` | `0` | Filtro de calidad de leyenda: cuando > 0, `--generate-captions` y el endpoint de leyenda bajo demanda omiten las fotos sin etiqueta, `other` o por debajo de esta confianza de momento almacenada. `0` = sin filtro |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Por debajo de este coseno top-1, una foto se etiqueta como `other`. Indexado por **señal** (`caption` frente a `image`) y luego por backend — los cosenos de leyenda son ~2,4× más altos |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Brecha coseno top-1/top-2 mínima; por debajo de ella el fotograma es `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Empujones L1 de rostro/etiqueta que solo deshacen casi-empates; `weight` limita cada ajuste a la escala del coseno |
| `priors.caption_tag_scale` | `0.25` | Reduce las reglas `tag` en la señal caption (L0 ya codifica el pie de foto); las reglas estructurales conservan todo su peso |
| `priors.rules` / `priors.event_types.<et>.rules` | (conjunto general) | Reglas declarativas `{kind, when, boost}` independientes del vocabulario; un `boost` hacia un momento ausente del vocabulario activo se omite. Las reglas por `event_type` reemplazan la lista global. Referencia completa de predicados: doc en inglés |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Suavizado L2 de la línea de tiempo (Viterbi): sesgo fuerte a permanecer sin progresión hacia delante (el vocabulario agnóstico no tiene un orden canónico), aplicado de forma ligera (`weight=0` = sin suavizado) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | Desempate L3 (ahora activo): cuando se activa en perfiles 16gb/24gb, solo los fotogramas de bajo posterior (por debajo de `min_confidence`) o bajo margen (por debajo de `min_margin`) se reclasifican con el VLM del perfil durante `--detect-moments` / `--recompute-moments` |
| `event_types` | `general` + `wedding` | `{moment: [sinónimos de prompt]}` por tipo de evento; establece `default_event_type` para cambiar de género o añadir el tuyo propio |

> **Coste del relleno retroactivo de leyendas.** Los embeddings de leyenda se calculan una vez y se almacenan, así que el coseno por foto es gratis después. Un escaneo codifica solo su puñado de leyendas nuevas (económico, incremental), pero el primer pase completo sobre una biblioteca existente codifica cada leyenda — un pase hacia delante por la torre de texto por leyenda, rápido en GPU y ~horas en CPU. Ejecuta `python facet.py --detect-moments` una vez (GPU recomendada) para ese relleno retroactivo; añade `--limit N` para verificar primero en una muestra.

**Descubrir un vocabulario específico de la biblioteca.** El conjunto `general` es un valor por defecto razonable, pero puedes proponer un vocabulario adaptado a *tu* biblioteca con `python facet.py --discover-moments`: agrupa los vectores `caption_embedding` almacenados (HDBSCAN), nombra cada grupo a partir de sus leyendas (una palabra clave más las leyendas más cercanas al centroide como prompts listos para usar) y escribe el resultado como un bloque `event_types.discovered` en `scoring_config.discovered.json`. Revísalo, copia `discovered` en `event_types` de arriba, establece `default_event_type` en `discovered` y ejecuta `--recompute-moments` para adoptarlo — el descubrimiento propone, nunca reescribe la configuración activa. `--discover-min-cluster-size N` controla la granularidad (más pequeño = más momentos, más finos).

## Exportación social

Recortes con reconocimiento del sujeto para relaciones de aspecto de redes sociales (`GET /api/photo/social_crop`, restringido a edición). Cada preajuste recorta el original a resolución completa a una relación de aspecto objetivo y lo encuadra en el sujeto detectado — el mayor rectángulo de esa relación de aspecto que cabe dentro de la imagen, centrado en el sujeto con un margen y ajustado a los bordes. La caja del sujeto sigue una cadena de reserva: la caja de sujeto BiRefNet persistida (`photos.subject_bbox`) → la unión de las cajas de caras detectadas → un recorte centrado simple. Consulta [Visor web — Descarga](VIEWER.md#download).

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

| Ajuste | Predeterminado | Descripción |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | Ruta de puntos i18n para el nombre visible del preajuste (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Relación de aspecto objetivo como `"an:al"` (p. ej. `1:1`, `4:5`, `9:16`) |
| `subject_margin_percent` | `8` | Margen alrededor de la caja del sujeto (porcentaje de su tamaño) antes de centrar el recorte |
| `jpeg_quality` | `92` | Calidad JPEG del recorte exportado |

Controlado por `viewer.features.show_social_export` (predeterminado `true`). La columna `photos.subject_bbox` la escribe la pasada de saliencia al escanear y `--recompute-saliency`; las filas escaneadas antes de que existiera recurren automáticamente al recorte por caras o centrado.

## Limpieza de basura

Detector zero-shot para archivos no fotográficos "basura" — capturas de pantalla, documentos escaneados, recibos, memes, diapositivas de presentación — sobre el **embedding de imagen almacenado** (sin decodificar la imagen, sin pasada de modelo por imagen; la misma forma que los momentos narrativos sin el suavizado temporal). Cada tipo lleva una lista de prompts de texto; el embedding de la foto se puntúa por coseno contra cada prompt y se agrupa por **máximo** (`max-pooled`) por tipo. Un conjunto de prompts de contraste `not_junk` condiciona la decisión: una foto solo se marca cuando el mejor tipo de basura supera `min_confidence` Y bate al mejor prompt `not_junk` por `min_margin` — si no, se guarda con el centinela `not_junk` (evaluada, limpia). `NULL` significa "no evaluada": `--detect-junk` etiqueta solo las filas `NULL` (y se ejecuta automáticamente al final de cada escaneo), mientras que `--recompute-junk` reevalúa toda la biblioteca. Rellena `photos.junk_kind`; la cola de revisión **Limpieza de basura** del visor ([VIEWER.md](VIEWER.md#limpieza-de-basura)) la consulta.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Ejecuta la detección de basura durante `--detect-junk` / `--recompute-junk` y al final del escaneo |
| `prompt_template` | `"{desc}"` | Cadena de formato aplicada a cada prompt (`{desc}` = el prompt); identidad por defecto ya que los prompts son frases completas |
| `pooling` | `"max"` | Agrupa los cosenos por prompt en una puntuación por tipo, vía `max` (mejor prompt individual, más discriminante) o `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Coseno máximo agrupado mínimo para que se considere el mejor tipo de basura (los cosenos de CLIP/`open_clip` son más bajos que los de SigLIP/`transformers`, de ahí un umbral propio por backend) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Cuánto debe superar el mejor tipo de basura al mejor prompt de contraste `not_junk` antes de que se marque la foto |
| `kinds` | screenshot/document/receipt/meme/slide | `{tipo: [sinónimos de prompt]}`; añade, quita o renombra tipos libremente — la columna y la cola del visor siguen la configuración |
| `not_junk_prompts` | 6 prompts fotográficos | Conjunto de contraste que describe fotografías reales; el filtro que mantiene las fotos genuinas fuera de la cola |

## Backend VLM

Elige dónde se ejecuta el modelo de visión y lenguaje de leyendas/etiquetas. `local` (por defecto) usa la ruta transformers Qwen en proceso, incluida en los perfiles VRAM 16gb/24gb — sin cambios para las instalaciones existentes. Los dos backends remotos apuntan Facet a un servidor externo para que el subtitulado y el etiquetado VLM funcionen en los **perfiles legacy/8gb que no incluyen ningún VLM local**: cuando se selecciona un backend remoto, las funciones VLM ya no dependen del perfil de VRAM.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `type` | `"local"` | Backend: `local` (transformers Qwen en proceso), `ollama` (API REST nativa de Ollama), u `openai_compatible` (cualquier endpoint de chat completions compatible con OpenAI — LM Studio, vLLM, OpenRouter) |
| `ollama.base_url` | `"http://localhost:11434"` | URL base del servidor Ollama; la imagen se envía en base64 a `POST /api/generate` |
| `ollama.model` | `"qwen2.5vl:7b"` | Etiqueta de modelo de Ollama (debe ser un modelo de visión ya descargado en el servidor) |
| `ollama.timeout_seconds` | `120` | Tiempo de espera por solicitud para las llamadas a Ollama |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | URL base compatible con OpenAI **incluyendo el sufijo `/v1`**; las solicitudes van a `{base_url}/chat/completions` con la imagen como URI de datos `image_url` |
| `openai_compatible.api_key` | `""` | Token portador enviado como `Authorization: Bearer <clave>`; déjalo vacío para servidores locales sin clave |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | Nombre del modelo pasado al endpoint |
| `openai_compatible.timeout_seconds` | `120` | Tiempo de espera por solicitud para las llamadas compatibles con OpenAI |

El backend compartido impulsa el subtitulado (`--generate-captions` y el endpoint bajo demanda `/api/caption`), la crítica VLM (`/api/critique?mode=vlm`), el reetiquetado VLM (`--recompute-tags-vlm`) y el desempate VLM de momentos narrativos. Un fallo de solicitud remota se registra como un fallo por foto (registrado, tags vacíos / sin leyenda) y nunca hace fallar la ejecución. El etiquetado durante el escaneo sigue usando el etiquetador propio del perfil; ejecuta `--recompute-tags-vlm` para aplicar un backend remoto a una biblioteca existente.

## Crítica con IA

Configuración de prompt para la crítica basada en VLM (perfiles 16gb/24gb). La crítica inyecta el desglose completo de reglas, las penalizaciones y el EXIF en un prompt escalonado configurable, presenta la respuesta como Observación / Evaluación / Sugerencias y la almacena en caché por foto en `photos.vlm_critique` (traducida bajo demanda a `vlm_critique_translated`). Se ejecuta sobre la miniatura almacenada, de modo que los archivos RAW se critican correctamente en lugar de fallar en silencio; `refresh` la regenera.

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `critique.vlm.max_new_tokens` | `320` | Presupuesto de tokens para la generación estructurada de la crítica con VLM |

Consulta [Galería web — Crítica con IA](VIEWER.md#ai-critique).

## Atributos de distorsión

Etiquetado de distorsiones en zero-shot, solo informativo. `--recompute-distortions` puntúa cada foto frente a prompts contrastivos de tipo ExIQA sobre su embedding CLIP/SigLIP almacenado y guarda los defectos probables (desenfoque por movimiento, dominante de color, exceso de nitidez, …) como una columna JSON informativa. Nunca alimenta el agregado; las etiquetas se muestran como chips de aviso en el diálogo de crítica.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Calcular los atributos de distorsión durante `--recompute-distortions` |
| `top_n` | `5` | Número máximo de etiquetas de distorsión conservadas por foto |
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Temperatura de softmax sobre las puntuaciones de los prompts contrastivos, por backend de embeddings (como en `narrative_moments`, los cosenos de open_clip y transformers operan a escalas diferentes) |
| `thresholds.<backend>.min_confidence` | `0.6` | Probabilidad mínima para conservar una etiqueta de distorsión |
| `vocabulary` | `{}` | Anulación opcional del conjunto de prompts de distorsión integrado (`{attribute: [sinónimos de prompt]}`); vacío = valores por defecto del módulo |

## Tono de piel

Naturalidad del tono de piel en retratos (solo informativo). `--recompute-skin-tone` muestrea el croma CIELAB de la mejilla a partir de las miniaturas de rostro almacenadas + puntos de referencia y mide su distancia CIEDE2000 respecto a un locus de piel de temperatura de color correlacionada, marcando los retratos cuya piel deriva hacia verde / magenta / azul / amarillo. Nunca alimenta el agregado; el resultado se muestra como una nota de tono de piel en el diálogo de crítica.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `cast_delta_threshold` | `12.0` | Delta CIEDE2000 mínima entre el croma de piel medido y el locus de piel antes de marcar una dominante de color |

## Sincronización con Immich

Sincronización unidireccional de las valoraciones por estrellas y los favoritos de Facet a un servidor [Immich](https://immich.app/) mediante su API REST. Los recursos se resuelven por `originalPath` a través de las asignaciones de prefijo de ruta configuradas, en una única pasada de búsqueda masiva. Ejecútala con `--immich-sync` (comprueba primero con `--immich-test`); consulta [Comandos — Sincronización con Immich](COMMANDS.md#immich-sync).

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `url` | `""` | URL base del servidor Immich (p. ej. `http://nas:2283`) |
| `api_key` | `""` | Clave de API de Immich, enviada como la cabecera `x-api-key` |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Reescrituras de prefijo de las rutas de Facet a los valores `originalPath` de Immich; el primer `facet_prefix` coincidente se sustituye por su `immich_prefix` al resolver un recurso |
| `push.ratings` | `true` | Enviar las valoraciones por estrellas. Se respeta la política segura por versión de Immich — solo se escribe 1–5, nunca 0/−1 |
| `push.favorites` | `true` | Enviar la marca de favorito |
| `push.top_picks_album` | `""` | Nombre opcional de un álbum de Immich que recopila las fotos enviadas por encima del umbral de valoración. Vacío = sin álbum |
| `push.top_picks_min_rating` | `4` | Valoración por estrellas mínima para que una foto se añada a `top_picks_album` |
| `timeout_seconds` | `30` | Tiempo de espera REST por solicitud |

`--immich-sync` respeta `--dry-run` (resuelve cada recurso pero no escribe nada) y `--user` (envía las valoraciones de `user_preferences` de ese usuario en modo multiusuario). Solo REST — Facet nunca toca la base de datos de Immich.

## Línea de tiempo

Ajustes para la vista cronológica de línea de tiempo:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `photos_per_group` | `30` | Número de fotos cargadas por grupo de fecha en la vista de línea de tiempo. Valores más altos muestran más fotos por fecha pero aumentan el peso de la página. |

## Mapa

Ajustes para la vista de mapa interactiva:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | Nivel de zoom al que los marcadores individuales sustituyen a los grupos. Valores más bajos muestran los marcadores individuales antes (más detalle con un zoom más amplio). Rango: 1 (mundo) a 18 (calle). |

## Traducción

Ajustes para la traducción de descripciones de IA mediante MarianMT:

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `target_language` | `"fr"` | Código de idioma de destino para `--translate-captions`. Admitidos: `fr` (francés), `de` (alemán), `es` (español), `it` (italiano), `pt` (portugués de Brasil). Usa los modelos MarianMT de Helsinki-NLP (CPU, sin GPU requerida). |

## Aesthetic CLIP (R2)

Puntuación estética suplementaria derivada de los embeddings CLIP/SigLIP en caché mediante proyección de texto. Los prompts son ajustables por el usuario para el benchmarking de AVA; consulta `scripts/benchmark_aesthetic.py` para medir el impacto en el SRCC de cualquier cambio.

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

Los arrays vacíos recurren a los valores por defecto del módulo integrados en `analyzers/aesthetic_clip.py`. No ajustes estos valores sin volver a ejecutar el benchmark de AVA: los valores por defecto puntúan un SRCC de ~0,52 en `ava_test/` y los cambios pueden regresar fácilmente a ~0,30.

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
2. Apunta un perfil a él:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Ejecuta `python facet.py --recompute-tags-vlm` para reetiquetar.

No se necesitan cambios de código. Valida la calidad mediante una comprobación puntual en paralelo sobre ~30 fotos antes de promoverlo a valor por defecto.

## Share Secret

Cadena hexadecimal de 64 caracteres autogenerada para los tokens de sesión/compartición:

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Se genera automáticamente en el primer arranque si no está presente.
