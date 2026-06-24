# Sistema de puntuación

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · [Deutsch](../de/SCORING.md) · [Italiano](../it/SCORING.md) · **Español**

Las fotos se clasifican en una categoría y luego se puntúan con los pesos de esa categoría.

## Cómo funciona la puntuación

1. **Detección de categoría** - La foto se analiza por su contenido (rostros, etiquetas, datos EXIF)
2. **Evaluación de filtros** - Las categorías se evalúan por orden de prioridad hasta que una coincide
3. **Aplicación de pesos** - Se aplican los pesos específicos de la categoría a las métricas
4. **Aplicación de modificadores** - Se aplican bonificaciones, penalizaciones e indicadores de comportamiento
5. **Puntuación final** - Suma ponderada acotada al rango 0-10

## Categorías

`scoring_config.json` define 34 categorías (33 con nombre más `default`), evaluadas en orden ascendente de prioridad hasta que una coincide. Gana la prioridad más baja. La lista completa se encuentra en el array `categories`; las principales son:

| Prioridad | Categoría | Método de detección |
|----------|----------|------------------|
| 8 | `art` | Etiquetas: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Etiquetas: aurora, astrophotography, stars, milky way |
| 15 | `concert` | Etiquetas: concert |
| 35 | `group_portrait` | Proporción facial ≥ 5% Y is_group_portrait |
| 42 | `silhouette` | Tiene rostro Y is_silhouette |
| 45 | `portrait` | Proporción facial ≥ 5%, no silueta/grupo/mono |
| 46 | `portrait_bw` | Retrato monocromo (rostro ≥ 5%) |
| 55 | `macro` | Etiquetas: macro, insect, butterfly, dewdrop, ... |
| 65 | `wildlife` | Etiquetas: animal, bird, marine, reptile, primate |
| 80 | `long_exposure` | Obturación 1-10 segundos |
| 85 | `night` | Luminancia < 0.15 |
| 88 | `monochrome` | is_monochrome (saturación < 5%) |
| 95 | `street` | Etiquetas: street, urban_culture |
| 96 | `human_others` | Tiene rostro Y proporción facial < 5% |
| 100 | `landscape` | Etiquetas: landscape, mountain, beach, forest, ... |
| 999 | `default` | Reserva (sin filtro) |

Otras categorías basadas en etiquetas son `aerial`, `food`, `sports`, `vehicle`, `travel`, `fashion`, `candid`, `product`, `architecture`, `urban`, `golden_hour`, `blue_hour`, `cinematic`, `vintage`, `abstract`, `minimalist`, `dramatic` y `weather`.

## Definición de categoría

Cada categoría en `scoring_config.json` tiene estos componentes:

```json
{
  "name": "portrait",
  "priority": 45,
  "filters": {
    "face_ratio_min": 0.05,
    "has_face": true,
    "is_silhouette": false,
    "is_group_portrait": false,
    "is_monochrome": false
  },
  "weights": {
    "aesthetic_percent": 32,
    "eye_sharpness_percent": 16,
    "face_quality_percent": 14,
    "composition_percent": 12,
    "liqe_percent": 8,
    "exposure_percent": 4,
    "tech_sharpness_percent": 4,
    "color_percent": 4,
    "contrast_percent": 4,
    "aesthetic_iaa_percent": 2
  },
  "modifiers": {
    "bonus": 0.419,
    "_apply_blink_penalty": true,
    "noise_tolerance_multiplier": 0.006,
    "_clipping_multiplier": 0.5
  },
  "tags": {}
}
```

## Referencia de filtros

### Filtros de rango numérico

| Filtro | Campo | Descripción |
|--------|-------|-------------|
| `face_ratio_min` / `face_ratio_max` | `face_ratio` | Área facial como fracción (0.0-1.0) |
| `face_count_min` / `face_count_max` | `face_count` | Número de rostros |
| `iso_min` / `iso_max` | `ISO` | ISO de la cámara |
| `shutter_speed_min` / `shutter_speed_max` | `shutter_speed` | Tiempo de exposición (segundos) |
| `luminance_min` / `luminance_max` | `mean_luminance` | Brillo (0.0-1.0) |
| `focal_length_min` / `focal_length_max` | `focal_length` | Distancia focal (mm) |
| `f_stop_min` / `f_stop_max` | `f_stop` | Número f de apertura |

### Filtros booleanos

| Filtro | Descripción |
|--------|-------------|
| `has_face` | Al menos un rostro detectado |
| `is_monochrome` | Saturación < 5% |
| `is_silhouette` | A contraluz con sombras/altas luces pronunciadas |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurable, predeterminado: 4) |

### Filtros de etiquetas

| Filtro | Descripción |
|--------|-------------|
| `required_tags` | Lista de etiquetas que la foto debe tener |
| `excluded_tags` | Lista de etiquetas que la foto NO debe tener |
| `tag_match_mode` | `"any"` (predeterminado) o `"all"` |

## Claves de peso

Todos los pesos usan el sufijo `_percent`. Se normalizan mediante `get_weights()`, por lo que los totales no tienen por qué sumar exactamente 100, pero mantenerlos en 100 conserva las puntuaciones en la escala 0-10.

| Clave | Métrica | Origen | Mejor para |
|-----|--------|--------|----------|
| `aesthetic_percent` | Atractivo visual | TOPIQ o CLIP+MLP | Todas |
| `quality_percent` | Calidad heredada | Redistribuida en `aesthetic` (sin señal separada) | — |
| `face_quality_percent` | Claridad facial | InsightFace | Retratos |
| `eye_sharpness_percent` | Nitidez ocular | Puntos de referencia de InsightFace | Retratos |
| `tech_sharpness_percent` | Nitidez general | Varianza de Laplaciano | Paisajes |
| `composition_percent` | Composición | SAMP-Net o basado en reglas | Todas |
| `exposure_percent` | Equilibrio de exposición | Análisis de histograma | Todas |
| `color_percent` | Armonía cromática | Análisis HSV | Fotos en color |
| `contrast_percent` | Contraste tonal | Dispersión de histograma | B/N |
| `dynamic_range_percent` | Rango tonal | Análisis de histograma | HDR, paisajes |
| `isolation_percent` | Separación del sujeto | Rostro frente al fondo | Retratos, fauna |
| `leading_lines_percent` | Líneas guía | Detección de bordes | Arquitectura |
| `power_point_percent` | Regla de los tercios | Ubicación del sujeto | Todas |
| `saturation_percent` | Saturación cromática | Análisis HSV | Fotos vibrantes |
| `noise_percent` | Nivel de ruido | Estimación de ruido | Baja iluminación |
| `face_sharpness_percent` | Nitidez de la zona facial | Análisis facial | Retratos |
| `aesthetic_iaa_percent` | Mérito estético artístico | TOPIQ IAA (entrenado con AVA) | Arte, creativo |
| `face_quality_iqa_percent` | Calidad facial (IQA) | TOPIQ NR-Face | Retratos |
| `liqe_percent` | Puntuación de calidad LIQE | LIQE | Diagnósticos |
| `subject_sharpness_percent` | Nitidez de la zona del sujeto | BiRefNet + Laplaciano | Retratos, fauna |
| `subject_prominence_percent` | Proporción de área del sujeto | BiRefNet | Macro, fauna |
| `subject_placement_percent` | Regla de los tercios del sujeto | BiRefNet | Todas |
| `bg_separation_percent` | Separación del fondo | BiRefNet | Retratos, macro |

## Modificadores

Ajustan el comportamiento de la puntuación por categoría:

| Modificador | Tipo | Descripción |
|----------|------|-------------|
| `bonus` | float | Se añade a la puntuación final (p. ej., 0.5) |
| `noise_tolerance_multiplier` | float | Escala la penalización por ruido (0.5 = mitad) |
| `iso_tolerance_multiplier` | float | Escala la penalización por ISO |
| `min_saturation_bonus` | float | Bonificación por saturación alta |
| `contrast_bonus` | float | Bonificación por contraste alto |
| `_skip_clipping_penalty` | bool | Omitir la penalización por recorte de exposición |
| `_skip_oversaturation_penalty` | bool | Omitir la penalización por sobresaturación |
| `_clipping_multiplier` | float | Escala la penalización por recorte |
| `_apply_blink_penalty` | bool | Aplicar la penalización por detección de parpadeo |

## Dimensiones de saliencia del sujeto

Cuatro dimensiones derivadas de la segmentación del sujeto por BiRefNet:

| Clave de peso | Métrica | Descripción |
|-----------|--------|-------------|
| `subject_sharpness_percent` | Nitidez del sujeto | Calidad de enfoque de la zona del sujeto frente al fondo. Alta = sujeto nítido, fondo suave. |
| `subject_prominence_percent` | Prominencia del sujeto | Área del sujeto como fracción del encuadre. Alta para macro y sujetos muy encuadrados, baja para escenas amplias. |
| `subject_placement_percent` | Ubicación del sujeto | Puntuación de la regla de los tercios para el centro de masa del sujeto. |
| `bg_separation_percent` | Separación del fondo | Diferencia de gradiente de bordes en el límite del sujeto (calidad del bokeh). |

Usa `subject_sharpness_percent` y `bg_separation_percent` para retrato/fauna; `subject_prominence_percent` para macro.

## Dimensiones IQA complementarias

Tres modelos de calidad adicionales:

| Clave de peso | Modelo | Descripción |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | Mérito estético entrenado con AVA, distinto de la puntuación estética de calidad técnica. Mejor para categorías de arte/creativas. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Evaluación de la calidad de la zona facial. Mejor para categorías de retrato. |
| `liqe_percent` | LIQE | Puntuación de calidad más un diagnóstico de distorsión (desenfoque de movimiento, sobreexposición, ruido). |

Estos modelos se ejecutan como parte de la canalización de puntuación predeterminada y comparten la VRAM con TOPIQ. Añade sus claves de peso a cualquier categoría donde la evaluación sea útil.

### Señales complementarias (no en el agregado predeterminado)

| Columna | Origen | Descripción |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + embedding CLIP/SigLIP en caché | Una puntuación estética complementaria gratuita (0-10) derivada de los embeddings de imagen en caché proyectándolos sobre un "eje estético" construido a partir de prompts de texto positivos/negativos. Cero inferencia de imagen adicional durante el escaneo. **No** forma parte del `aggregate` predeterminado. Pobla con `python scripts/compute_aesthetic_clip.py --db <path>`. Compara con `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`. AVA SRCC ≈ 0.52 en el conjunto `ava_test/` de 500 fotos (frente a 0.94 para `aesthetic_iaa`): útil como prefiltro económico o cuando TOPIQ-IAA no está disponible. |

## Etiquetas de categoría (vocabulario CLIP)

Las etiquetas activan las categorías basadas en etiquetas y se emparejan mediante similitud CLIP:

```json
{
  "tags": {
    "landscape": ["landscape", "scenic view", "nature scene"],
    "mountain": ["mountain", "alpine", "peaks"],
    "beach": ["beach", "ocean", "seaside", "coastal"]
  }
}
```

Cada clave es el nombre canónico de la etiqueta, y el array contiene sinónimos para el emparejamiento CLIP.

## Puntuación de Selección destacada

El filtro "Selección destacada" del visor usa una puntuación ponderada personalizada:

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**Cálculo de la puntuación:**
- Con rostro (proporción facial ≥ 20%): las cuatro métricas contribuyen
- Sin rostro: `face_quality_percent` se redistribuye a `aesthetic` y `composition`

## Consideraciones sobre el perfil de VRAM

Los pesos predeterminados están optimizados para **TOPIQ** (0.93 SRCC), el modelo estético para todos los perfiles.

| Perfil | Modelo estético | Embeddings | Etiquetador | Recomendaciones |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Mejor precisión, pesos predeterminados |
| `16gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Pesos predeterminados |
| `8gb` | CLIP+MLP (0.76 SRCC) | CLIP ViT-L-14 | similitud CLIP | Los pesos predeterminados funcionan bien |
| `legacy` | CLIP+MLP en CPU | CLIP ViT-L-14 | similitud CLIP | Pesos predeterminados, más lento |

Todos los perfiles ejecutan además modelos complementarios de PyIQA (TOPIQ IAA, TOPIQ NR-Face, LIQE) y, opcionalmente, BiRefNet_dynamic para la saliencia del sujeto.

Ejecuta `--compute-recommendations` después de cambiar de perfil para analizar las distribuciones de puntuación.

## Flujo de ajuste de pesos

### Opción A: a través del visor (recomendada)

1. Abre `/stats` → pestaña **Categorías** → subpestaña **Pesos**
2. Desbloquea el modo edición
3. Selecciona una categoría en el desplegable del editor
4. Ajusta los controles deslizantes — la **vista previa de distribución de puntuaciones** en vivo muestra el impacto estimado
5. Haz clic en **Guardar** y luego en **Recalcular puntuaciones** para aplicar

El visor ejecuta `--recompute-category` internamente, actualizando solo las fotos de esa categoría.

### Opción B: a través de la CLI

#### 1. Analizar las puntuaciones actuales

```bash
python facet.py --compute-recommendations
```

Muestra:
- Distribuciones de puntuación por categoría
- Análisis de correlación de pesos
- Ajustes sugeridos

#### 2. Ajustar los pesos

Edita los pesos de categoría en `scoring_config.json`. Asegúrate de que sumen 100.

#### 3. Recalcular las puntuaciones

```bash
python facet.py --recompute-average               # Todas las categorías
python facet.py --recompute-category portrait      # Una sola categoría (más rápido)
```

Usa los embeddings almacenados: no se necesita GPU.

#### 4. Validar los cambios

```bash
python facet.py --compute-recommendations
```

Compara las distribuciones antes/después.

## Modo de comparación por pares

Entrena los pesos comparando pares de fotos:

### Configuración

1. Establece un `edition_password` no vacío en la configuración: `"viewer": { "edition_password": "your-password" }`
2. Inicia el visor: `python viewer.py`
3. Haz clic en el botón "Comparar"

### Interfaz de comparación

- Fotos en paralelo
- Teclado: A (gana la izquierda), B (gana la derecha), T (empate), S (omitir)
- La barra de progreso muestra las comparaciones hacia el mínimo de 50

### Orígenes de comparación

Las comparaciones llevan un marcador `source` para que el optimizador pueda ponderarlas por fiabilidad:

- `vote` — votos A/B explícitos desde la interfaz de comparación
- `culling` — derivados automáticamente de las decisiones de selección de ráfagas/similares: cada
  foto rechazada se empareja con hasta dos fotos conservadas del mismo grupo
  (con un tope de 12 pares por grupo). Las fotos conservadas ganan. Los votos explícitos sobre el mismo
  par nunca se sobrescriben.
- `rating` — pares sintéticos generados a partir de valoraciones por estrellas y favoritos

Por lo tanto, revisar los grupos de ráfaga en el visor amplía el conjunto de entrenamiento para la
optimización de pesos sin ningún esfuerzo adicional.

### Optimización de pesos

```bash
# Comprobar las estadísticas de comparación
python facet.py --comparison-stats

# Optimizar los pesos a partir de las comparaciones (se aplica solo si generaliza)
python facet.py --optimize-weights --optimize-category portrait

# Restringir los datos de entrenamiento a orígenes específicos
python facet.py --optimize-weights --optimize-category portrait --optimize-sources vote,culling

# Aplicar aunque no se cumpla el umbral de validación reservada
python facet.py --optimize-weights --optimize-category portrait --optimize-force

# Aplicar a todas las fotos
python facet.py --recompute-average
```

### Canalización de etiqueta a peso

Más allá de los votos A/B explícitos, otros dos flujos de etiquetas alimentan el optimizador:

1. Las **decisiones de selección** se capturan automáticamente en cada
   confirmación de ráfaga/similar (`source='culling'`).
2. Las **valoraciones por estrellas, los favoritos y los rechazos** se materializan en pares
   sintéticos con `python facet.py --sync-label-comparisons` (`source='rating'`).
   Volver a ejecutarlo re-sincroniza a partir de las etiquetas actuales, de modo que las valoraciones retiradas desaparecen.

El optimizador pondera cada origen por fiabilidad (vote 1.0, rating 0.7,
culling 0.5) al maximizar la verosimilitud de Bradley-Terry. Entrena sobre el
vector de métricas 0-10 exacto que usa el puntuador (incluidos `liqe`, `aesthetic_iaa`,
`face_quality_iqa` y las métricas de saliencia del sujeto), por lo que los pesos optimizados se asignan
directamente a la puntuación de producción.

Los pesos se **aplican solo si generalizan**: los pesos finales se ajustan sobre
todas las comparaciones, pero la decisión de escribirlos depende de la precisión de validación
cruzada k-fold reservada, no de la precisión de entrenamiento. Si la ganancia reservada sobre los pesos actuales
está por debajo del umbral (2 pp de forma predeterminada), la ejecución informa de las cifras y no escribe
nada — pasa `--optimize-force` para anularlo. La optimización es por categoría y
necesita comparaciones etiquetadas **para esa categoría**; las categorías sin votos
no pueden ajustarse a partir de datos.

Cadencia recomendada:

```bash
python facet.py --mine-insights          # qué señal existe, deriva, salud
python facet.py --sync-label-comparisons # actualizar los pares derivados de valoraciones
python facet.py --optimize-weights       # aprender los pesos de todos los orígenes
python facet.py --recompute-average      # aplicar + persistir la instantánea de percentiles
```

### Ajuste de pesos en la interfaz

1. Abre el panel de vista previa de pesos durante la comparación
2. Ajusta los controles deslizantes para ver los cambios de puntuación en tiempo real
3. Haz clic en "Sugerir pesos" para obtener valores optimizados
4. Actualiza manualmente la configuración

## Añadir categorías personalizadas

```json
{
  "name": "underwater",
  "priority": 62,
  "filters": {
    "required_tags": ["underwater"],
    "tag_match_mode": "any"
  },
  "weights": {
    "aesthetic_percent": 40,
    "color_percent": 25,
    "composition_percent": 20,
    "exposure_percent": 15
  },
  "modifiers": {
    "noise_tolerance_multiplier": 0.3,
    "bonus": 0.5
  },
  "tags": {
    "underwater": ["underwater", "scuba", "diving", "ocean"],
    "fish": ["fish", "coral", "reef"]
  }
}
```

Añádela al array `categories` en `scoring_config.json`, luego ejecuta `--recompute-average` (o `--recompute-category underwater` solo para la nueva categoría).

## Ejemplos de flujo de trabajo

### Ajustar la categoría de conciertos

```bash
# Edita scoring_config.json:
# Busca la categoría "concert", ajusta:
#   "noise_tolerance_multiplier": 0.05
#   "exposure_percent": 5

python facet.py --recompute-category concert
```

O usa el editor de pesos del visor en `/stats` → Categorías → Pesos para vista previa en vivo y recálculo con un clic.

### Cambiar al perfil 8gb

```bash
# Edita: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Analizar
# Reduce aesthetic_percent en las categorías si es necesario
python facet.py --recompute-average
```

### Añadir la categoría submarina

1. Añade la definición de la categoría (ver arriba)
2. Ejecuta `python facet.py --validate-categories`
3. Ejecuta `python facet.py --recompute-average`
