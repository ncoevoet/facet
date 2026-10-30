# Sistema de puntuación

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · [Deutsch](../de/SCORING.md) · [Italiano](../it/SCORING.md) · **Español** · [Português](../pt/SCORING.md) · [简体中文](../zh/SCORING.md)

Las fotos se clasifican en una categoría y luego se puntúan con los pesos de esa categoría.

Los valores ausentes o NULL de subject_sharpness, subject_prominence, subject_placement, bg_separation y face_quality_iqa se excluyen del cálculo ponderado. Solo su peso positivo se redistribuye entre las métricas disponibles; cero sigue siendo válido. Si faltan todas las entradas ponderadas, se usa el valor neutro 5.0. Las exclusiones de licencia se aplican primero. Los pesos predeterminados no cambian. `--optimize-weights` deja un peso sin cambios cuando el conjunto de comparaciones no tiene ningún valor para esa métrica. Para completar la saliencia, ejecute `--recompute-saliency` y luego `--recompute-average`.

## Cómo funciona la puntuación

1. **Detección de categoría** - La foto se analiza por su contenido (rostros, etiquetas, datos EXIF)
2. **Evaluación de filtros** - Las categorías se evalúan por orden de prioridad hasta que una coincide (un [contexto de puntuación](#contextos-de-puntuación) puede cambiar esto por álbum o foto)
3. **Aplicación de pesos** - Se aplican los pesos específicos de la categoría a las métricas
4. **Aplicación de modificadores** - Se aplican bonificaciones, penalizaciones e indicadores de comportamiento
5. **Puntuación final** - Suma ponderada acotada al rango 0-10

## Categorías

`scoring_config.json` define 34 categorías (33 con nombre más `default`), evaluadas en orden ascendente de prioridad hasta que una coincide. Gana la prioridad más baja. La lista completa se encuentra en el array `categories`; las principales son:

| Prioridad | Categoría | Método de detección |
|----------|----------|------------------|
| 8 | `art` | Etiquetas: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Etiquetas: aurora, astrophotography, stars, milky way, Y luminancia media ≤ 0.30 |
| 15 | `concert` | Etiquetas: concert |
| 35 | `group_portrait` | Proporción facial ≥ 5% Y is_group_portrait |
| 42 | `silhouette` | Tiene rostro Y `is_silhouette` (el rostro más grande es oscuro frente a un entorno más claro) |
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

En los perfiles con etiquetado CLIP (`legacy`/`8gb`, y `16gb`/`24gb` cuando su etiquetador VLM no se ejecuta), un escaneo etiqueta cada foto antes de calcular su categoría, así que la categoría almacenada usa las etiquetas. Una ejecución suelta con `--pass NAME` no etiqueta.

**Silueta.** `is_silhouette` sale de una regla de píxeles basada en el rostro (ver [Filtros booleanos](#filtros-booleanos)), no de una etiqueta.

- Cuando `exposure.silhouette_detection` es `true` (el valor por defecto), el agregado de una silueta omite la penalización por recorte.
- Un escaneo almacena `exposure_score` con la penalización por recorte. `--recompute-average` lo recalcula sin la penalización para toda foto marcada `is_silhouette`, diga lo que diga `exposure.silhouette_detection`.
- Para volver a derivar los indicadores de una biblioteca existente, ejecuta `python facet.py --recompute-silhouette` y luego `--recompute-average` dos veces (consulta [COMMANDS.md](COMMANDS.md)).

**Astro.** Una foto necesita una etiqueta astro *y* una luminancia media de como máximo 0.30 (`luminance_max`). Una escena luminosa etiquetada como `aurora` o `stars` no es astro, y una foto sin luminancia almacenada nunca coincide. Si tu `scoring_config.json` tiene su propio array `categories`, añade tú mismo `"luminance_max": 0.30` a `astro.filters`; `python facet.py --doctor` te avisa cuando falta.

## Contextos de puntuación

Un **contexto de puntuación** cambia el orden de las categorías para algunas fotos sin tocar las prioridades globales. Promueve unas pocas categorías al frente y excluye otras. `default` (`promote`/`excluded` vacíos) no cambia nada, y las fotos lo usan salvo que asignes otro.

**Orden efectivo** = `promote` (en el orden indicado) → el orden de prioridad global sin los nombres promovidos y excluidos → `default` al final. Un nombre que está en `promote` y en `excluded` se descarta: gana `excluded`.

Preajustes incluidos, editables en la pestaña **Contexto de puntuación** del visor o en el JSON (referencia de campos: [Contextos de puntuación](CONFIGURATION.md#contextos-de-puntuación)):

| Contexto | Promueve | Excluye |
|---------|----------|------------|
| `default` | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` |
| `party_event` | `group_portrait`, `candid`, `food` | — |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — |
| `wildlife` | `wildlife` | — |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — |
| `motorsport` | `sports`, `vehicle` | `silhouette` |

Solo editas la lista de promovidas (modo de edición; arrastra, o sube/baja) y las exclusiones. Las demás categorías conservan siempre el orden global, así que una categoría nueva nunca falta en un contexto. Reglas de validación: [Editar un contexto](CONFIGURATION.md#editar-un-contexto).

**Asignar un contexto:**

- **Por álbum.** Se aplica a toda foto que esté ahora en el álbum. Es una instantánea puntual: las fotos que se añadan más tarde a un álbum inteligente no lo reciben. Consulta [Asignar un contexto](CONFIGURATION.md#contextos-de-puntuación).
- **Por foto.** Una anulación de categoría persistente para una sola foto.

Ambos sobreviven a los reescaneos y se pueden borrar por separado.

**Ninguno afecta a las fotos ya puntuadas hasta que recalcules:** ejecuta `python facet.py --recompute-average`, o recalcula desde el visor (consulta [Cambiar las prioridades requiere un recálculo](CONFIGURATION.md#reordenar-la-prioridad-global)). Con `normalization.per_category` activado, ejecútalo dos veces (consulta [Normalización](CONFIGURATION.md#normalización)).

### La trampa de los EXIF faltantes

Reordenar solo cambia qué categoría se *evalúa primero*. No puede hacer que coincidan los filtros de una categoría. Un filtro de rango numérico falla cuando el valor de la foto falta o es ilegible, exactamente como si estuviera fuera de rango.

Ejemplo: `sports` (prioridad 71) tiene `shutter_speed_max: 0.02`. Un fotograma de baile tomado a una velocidad más lenta que 1/50 s, o sin velocidad de obturación legible, falla ese filtro aunque `action_stage` promueva `sports` al frente. Pasa a la siguiente coincidencia, normalmente `fashion` (prioridad 43, con la etiqueta `fashion` y un rostro) o `silhouette` (prioridad 42, a contraluz y con un rostro).

**Cuando una foto acaba en una categoría inesperada, comprueba esto primero:** ¿pueden los filtros numéricos de la categoría de destino coincidir con el EXIF almacenado de la foto, y no solo con sus etiquetas?

### La trampa de la etiqueta faltante

`required_tags` falla de la misma manera: un filtro no puede coincidir con una etiqueta ausente del vocabulario. Los `required_tags` de `sports` son `sports`, `motion`, `athlete`, `competition`, `action_sport` y `dance`.

`sports.tags.dance` lleva 11 prompts de CLIP (`dance performance`, `dancer on stage`, `ballet dancer`, `contemporary dance`, `ballroom dancing`, `latin dance`, `hip hop dance`, `dance competition`, `dance troupe performing`, `dancer mid leap`, `dancer in motion`), y `dance` está en `sports.filters.required_tags`. Una foto de baile etiquetada puede llegar a `sports`, pero una de obturación lenta o sin EXIF sigue fallando `shutter_speed_max: 0.02`.

**Las fotos existentes conservan sus etiquetas.** Un cambio de vocabulario solo afecta al etiquetado nuevo; ejecuta `python facet.py --recompute-tags` para aplicarlo a la biblioteca.

### Reordenar la prioridad global

Puedes reordenar la prioridad global en el visor (modo de edición). El reordenamiento intercambia los números de prioridad existentes entre categorías en lugar de renumerarlos, así que los números de la tabla de arriba siguen siendo válidos. `default` (prioridad 999) permanece siempre al final. Cada escritura guarda antes una copia `.backup.<timestamp>` con marca de tiempo de `scoring_config.json`.

Reordenar no cambia la `category` almacenada de ninguna foto: ejecuta un recálculo después.

**Limitación conocida:** el menú desplegable de tipo de la galería conserva su orden anterior hasta que se reinicia el visor. La coincidencia y el filtrado usan el nuevo orden de inmediato.

## Definición de categoría

Cada categoría de `scoring_config.json` tiene estos componentes:

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
| `is_silhouette` | El rostro más grande es oscuro frente a un entorno claro (ver abajo). Una foto sin rostro nunca es una silueta |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurable, predeterminado: 4) |

**Regla de `is_silhouette`.** El brillo medio (luma, 0-1) del 60 % central del cuadro del rostro es inferior a 0.12, y la banda alrededor del cuadro (de 0.2 a 0.75 del tamaño del cuadro hacia fuera por cada lado, recortada al encuadre) es más clara en más de 0.20. Ni la etiqueta `silhouette` de CLIP ni el histograma del encuadre completo lo activan.

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
| `quality_percent` | Calidad heredada | Sumada a `aesthetic_percent` antes de puntuar (sin señal separada) | — |
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

**`quality_percent` cuenta como `aesthetic`.** La métrica de calidad no tiene puntuación propia, así que el `quality_percent` de una categoría se redistribuye en `aesthetic`: se suma a `aesthetic_percent` antes de puntuar, y los pesos siguen sumando 100. Las versiones anteriores perdían esa parte en el agregado; ejecuta `--recompute-average` una vez tras actualizar para recuperarla. Las categorías no cambian.

## Modificadores

Ajustan el comportamiento de la puntuación por categoría:

| Modificador | Tipo | Descripción |
|----------|------|-------------|
| `bonus` | float | Se añade a la puntuación final (p. ej., 0.5) |
| `noise_tolerance_multiplier` | float | Escala la penalización por ruido (0.5 = mitad) |
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

**Sin sujeto, sin número.** Cuando no se encuentra sujeto, `subject_sharpness`, `subject_placement` y `bg_separation` se almacenan como NULL (igual que `power_point_score` cuando no hay cuadro de sujeto), `subject_prominence` es 0.0 y `subject_bbox` es NULL.

- Los filtros de rango de la galería omiten un NULL (`min_subject_sharpness=0` no devuelve una foto sin sujeto). Las estadísticas lo dejan fuera de los promedios, y la interfaz lo muestra como ausente.
- Las entradas de saliencia NULL siguen la regla anterior de valores ausentes; los pesos predeterminados no cambian.
- Las versiones anteriores almacenaban un 5.0 neutro. Las filas existentes lo conservan hasta que `--recompute-saliency` y `--recompute-composition-cpu` las reescriben.

**Cuando falla la saliencia**, no se escribe nada; Facet nunca almacena un número neutro para un resultado fallido. Una foto nunca puntuada conserva NULL en las cinco columnas de saliencia (`subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation`, `subject_bbox`), como una foto escaneada antes de que existiera la saliencia. Reglas de reintento y de tamaño de lote: [Saliencia del sujeto](COMMANDS.md#saliencia-del-sujeto).

## Dimensiones IQA complementarias

Tres modelos de calidad adicionales:

| Clave de peso | Modelo | Descripción |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | Mérito estético entrenado con AVA, distinto de la puntuación estética de calidad técnica. Mejor para categorías de arte/creativas. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Evaluación de la calidad de la zona facial. Mejor para categorías de retrato. |
| `liqe_percent` | LIQE | Puntuación de calidad más un diagnóstico de distorsión (desenfoque de movimiento, sobreexposición, ruido). |

Estos modelos se ejecutan como parte de la canalización de puntuación predeterminada en todos los perfiles, incluido el perfil `legacy` de CPU (más lento allí), y comparten la VRAM con TOPIQ en una GPU. Añade sus claves de peso a cualquier categoría donde la evaluación sea útil.

**Cuando un modelo complementario no puede puntuar una foto**, guarda NULL en la columna de ese modelo (`face_quality_iqa`, `liqe_score`, `aesthetic_iaa`, `aesthetic_v25`) en lugar de un 5.0 neutro. Ocurre cuando TOPIQ NR-Face no encuentra ningún rostro, o cuando el lado corto que recibe LIQE mide menos de 224 px; Aesthetic V2.5, si está activado, puede fallar con cualquier imagen. Un error de memoria de CPU no se reintenta con un tamaño de lote menor.

- Un face_quality_iqa NULL sigue la regla anterior; las demás entradas complementarias NULL conservan la imputación neutra 5.0.
- **Galería:** un filtro de rango sobre Estética (IAA), Calidad facial (IQA), LIQE o Aesthetic V2.5 no coincide con una foto sin puntuar (`min_face_quality_iqa=0` omite una foto sin rostro). Una ordenación ascendente por esos campos, por Q-ReAlign o por DeQA coloca las fotos sin puntuar al final, en la galería y en los álbumes.
- **Los antiguos valores neutros 5.0** permanecen hasta que `--repair-neutral-iqa` los borra; después ejecuta `--recompute-iqa` y `--recompute-average`, o reescanea con `--force`.
- **Fallo del modelo principal** (TOPIQ en `16gb` y `24gb`): la foto se registra como fallida en lugar de guardarse con un 5.0 neutro. Una foto nueva se recoge en el siguiente escaneo; una almacenada conserva su fila y la reintenta `--retry-failed all` (un `--retry-failed` a secas cubre solo la última ejecución con fallos) u otro reescaneo con `--force`.

Reglas de reintento de cada comando: [Modelos de calidad complementarios](COMMANDS.md#modelos-de-calidad-suplementarios).

### Señales complementarias (no en el agregado predeterminado)

| Columna | Origen | Descripción |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + embedding CLIP/SigLIP en caché | Puntuación estética gratuita (0-10) a partir de embeddings en caché; **no** está en el `aggregate` predeterminado |

`aesthetic_clip` proyecta el embedding de cada imagen sobre un «eje estético» construido a partir de prompts de texto, así que no necesita inferencia de imagen adicional.

- Rellénala con `python scripts/compute_aesthetic_clip.py --db <path>`.
- Evalúa el rendimiento con `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`.
- SRCC con AVA ≈ 0.52 en el conjunto `ava_test/` de 500 fotos (frente a 0.94 de `aesthetic_iaa`). Úsala como prefiltro barato o cuando TOPIQ-IAA no esté disponible.

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

Cada clave es el nombre canónico de la etiqueta, y el array contiene sinónimos para el emparejamiento con CLIP.

## Puntuación de Selección destacada

El filtro «Selección destacada» del visor usa una puntuación ponderada personalizada:

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**Cálculo de la puntuación:**
- Con rostro (face_ratio ≥ 20%): contribuyen las cuatro métricas
- Sin rostro: `face_quality_percent` se redistribuye a partes iguales (la mitad cada una) a `aesthetic` y `composition` (con los pesos predeterminados: aesthetic 0.40, composition 0.30)

## Consideraciones sobre el perfil de VRAM

Los pesos predeterminados están optimizados para **TOPIQ** (0.93 SRCC), el modelo estético de todos los perfiles.

| Perfil | Modelo estético | Embeddings | Etiquetador | Recomendaciones |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Mejor precisión, pesos predeterminados |
| `16gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Pesos predeterminados |
| `8gb` | CLIP+MLP (0.76 SRCC) | CLIP ViT-L-14 | Similitud CLIP | Los pesos predeterminados funcionan bien |
| `legacy` | CLIP+MLP en CPU | CLIP ViT-L-14 | Similitud CLIP | Pesos predeterminados, más lento |

Todos los perfiles, incluido el perfil `legacy` de CPU, ejecutan además modelos PyIQA complementarios (TOPIQ IAA, TOPIQ NR-Face, LIQE) y, opcionalmente, BiRefNet_dynamic para la saliencia del sujeto.

Ejecuta `--compute-recommendations` tras cambiar de perfil para analizar las distribuciones de puntuación.

## Flujo de ajuste de pesos

### Opción A: a través del visor (recomendada)

1. Abre `/stats` → pestaña **Categorías** → subpestaña **Pesos**
2. Desbloquea el modo de edición
3. Selecciona una categoría en el menú desplegable del editor
4. Ajusta los deslizadores: la **Vista previa de la distribución de puntuaciones** en vivo muestra el impacto estimado
5. Haz clic en **Guardar** y luego en **Recalcular puntuaciones** para aplicar

El visor ejecuta `--recompute-category` internamente, actualizando solo las fotos de esa categoría.

Un asistente MCP puede leer estos pesos y simular un cambio sin tocar nada: `explain_score` (por qué una foto obtuvo su puntuación), `category_weights` y `preview_weights` (una vista previa aproximada con los cambios de clasificación). Consulta [Puntuaciones y pesos](AGENTS.md#puntuaciones-y-pesos).

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

Edita los pesos de las categorías en `scoring_config.json`. Asegúrate de que sumen 100.

#### 3. Recalcular las puntuaciones

```bash
python facet.py --recompute-average               # Todas las categorías
python facet.py --recompute-category portrait      # Una sola categoría (más rápido)
```

Usa los embeddings almacenados: no necesita GPU.

#### 4. Validar los cambios

```bash
python facet.py --compute-recommendations
```

Compara las distribuciones antes y después.

## Modo de comparación por pares

Entrena los pesos comparando pares de fotos:

### Configuración

1. Define un `edition_password` no vacío en la configuración: `"viewer": { "edition_password": "your-password" }`
2. Inicia el visor: `python viewer.py`
3. Haz clic en el botón «Comparar»

### Interfaz de comparación

- Fotos lado a lado
- Teclado: ← (gana la izquierda), → (gana la derecha), T (empate), S (omitir). Los botones en pantalla están rotulados **A** / **B**.
- La barra de progreso muestra las comparaciones realizadas respecto al mínimo de 50

### Orígenes de comparación

Cada comparación tiene un `source`, al que el optimizador da peso según su fiabilidad:

- `vote` — votos A/B explícitos de la interfaz de comparación
- `culling` — a partir de las decisiones de selección de ráfagas/similares: cada foto
  rechazada se empareja con hasta dos fotos conservadas de su grupo (como máximo 12
  pares por grupo). Las fotos conservadas ganan. Los votos explícitos sobre el mismo par
  nunca se sobrescriben.
- `rating` — pares sintéticos a partir de las valoraciones por estrellas y los favoritos

Así, revisar grupos de ráfagas en el visor también hace crecer el conjunto de entrenamiento.

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

Además de los votos A/B, dos flujos de etiquetas alimentan el optimizador:

1. **Las decisiones de selección** se capturan en cada confirmación de ráfaga/similares (`source='culling'`).
2. **Las valoraciones por estrellas, los favoritos y los rechazos** se convierten en pares
   sintéticos con `python facet.py --sync-label-comparisons` (`source='rating'`). Volver
   a ejecutarlo resincroniza a partir de las etiquetas actuales, así que las valoraciones retiradas desaparecen.

**Cómo funciona el ajuste.** El optimizador busca los pesos que mejor predicen el ganador de cada comparación (un modelo de Bradley-Terry).

- Los orígenes cuentan según su fiabilidad: vote 1.0, rating 0.7, culling 0.5.
- Un **empate** cuenta como media victoria y media derrota.
- El ajuste está **anclado a tus pesos actuales**: con pocas comparaciones se mantiene cerca de ellos.
- Usa las mismas métricas 0-10 que el agregado (incluidas `liqe`, `aesthetic_iaa`, `face_quality_iqa` y la saliencia del sujeto), con la nitidez ocular, la nitidez técnica y el color normalizados por los percentiles que guardó el último `--recompute-average`.
- `quality_percent` se integra en `aesthetic`, como hace el puntuador; al aplicar se escribe `quality_percent: 0`.

**Los pesos se aplican solo si generalizan.** La decisión usa comparaciones reservadas: validación cruzada de 5 particiones con **particiones agrupadas por foto** (ninguna foto está a la vez en los pares de entrenamiento y en los reservados).

- Una **prueba exacta de McNemar unilateral** comprueba si los nuevos pesos ganan significativamente más pares de aquellos en los que los dos conjuntos de pesos discrepan.
- Los pesos se aplican solo cuando `p < 0.05` **y** la mejora reservada es de al menos 2 puntos porcentuales. En caso contrario, la ejecución registra las cifras y no escribe nada.
- Pasa `--optimize-force` para aplicarlos de todos modos. Si la prueba no puede ejecutarse (demasiados pocos grupos de fotos independientes), no se aplica nada salvo que se fuerce.
- Cada categoría necesita al menos 30 comparaciones **decisivas** (una foto ganó) **en esa categoría**. Los empates y las demás categorías no cuentan.

Ejemplo de registro:

```
Held-out accuracy:      69.2% +/- 4.0 (5-fold, photo-grouped) - the honest estimate
Held-out gain:          +8.5 pp over the current weights on the same 389 pairs
McNemar (one-sided):    p = 0.0006 (only the fit right: 66, only the current weights right: 33)
NOT applying: the held-out gate needs p < 0.05 and a gain of at least 2.0 pp. ...   (logged when the gate fails)
```

**Aplicar conserva el nivel de la categoría.** `--optimize-weights` cambia cómo se clasifican entre sí las fotos de una categoría, no frente a otras categorías. Mueve `modifiers.bonus` para cancelar el desplazamiento de la puntuación media de la categoría.

- La bonificación se mantiene dentro de [-5, 5]; el registro indica cuándo se aplica ese límite.
- Una categoría sin entrada en `categories` (`others`) no tiene bonificación y no se recentra.
- Restaurar una instantánea de pesos restaura los pesos **y** la bonificación. Las instantáneas más antiguas, las de `calibrate.py` y las de `others` dejan la bonificación como está.
- El botón **Aplicar** del visor y las ediciones manuales en la pestaña Pesos no recentran la bonificación; solo lo hace `--optimize-weights`.

**Tras actualizar, vuelve a entrenar el clasificador personal y la cabeza de selección (`--train-ranker`, `--train-keeper`), y luego ejecuta `--recompute-average`.** Ahora leen la nitidez ocular, la nitidez técnica y el color normalizados por percentiles, y un modelo guardado más antiguo no puede detectar el cambio.

Cadencia recomendada:

```bash
python facet.py --mine-insights          # qué señal existe, deriva, salud
python facet.py --sync-label-comparisons # refrescar los pares derivados de valoraciones
python facet.py --optimize-weights       # aprender pesos de todos los orígenes
python facet.py --recompute-average      # aplicar + persistir la instantánea de percentiles
```

### Ajuste de pesos en la interfaz

Durante la comparación, el panel de vista previa de pesos muestra los cambios de puntuación al mover los deslizadores, y **Sugerir pesos** propone valores optimizados. Guardar y recalcular funcionan como en la [Opción A: a través del visor](#opción-a-a-través-del-visor-recomendada).

**Sugerir pesos** muestra dos cifras, en la pestaña Sugerencias de pesos y en la barra lateral de comparación A/B:

- `accuracy_before`: con qué frecuencia los pesos actuales predicen el ganador de los pares etiquetados de esta categoría.
- `accuracy_after`: lo mismo para los pesos sugeridos. Se mide sobre los pares con los que se ajustó, así que es optimista.

**Aplicar** se ofrece solo cuando pasa la misma prueba de McNemar con datos reservados que usa la CLI (`suggest_changes` es true). La validación cruzada se ejecuta solo cuando la mejora optimista alcanza los 2 puntos porcentuales (`?use_cv=true` la ejecuta siempre). El visor necesita `min_comparisons_for_optimization` (por defecto 50) comparaciones decisivas en la categoría, donde la CLI necesita 30. Por debajo de eso informa «Need at least N decisive comparisons (have K)».

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

Añádela al array `categories` de `scoring_config.json` y luego ejecuta `--recompute-average` (o `--recompute-category underwater` solo para la categoría nueva).

## Ejemplos de flujo de trabajo

### Ajustar la categoría de conciertos

```bash
# Edita scoring_config.json:
# Busca la categoría "concert", ajusta:
#   "noise_tolerance_multiplier": 0.05
#   "exposure_percent": 5

python facet.py --recompute-category concert
```

O usa el editor de pesos del visor en `/stats` → Categorías → Pesos para una vista previa en vivo y un recálculo con un clic.

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
