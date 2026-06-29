# Referencia de comandos

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · **Español** · [Português](../pt/COMMANDS.md)

[Escaneo](#escaneo) · [Vista previa y exportación](#vista-previa-y-exportación) · [Operaciones de recálculo](#operaciones-de-recálculo) · [Reconocimiento facial](#reconocimiento-facial) · [Gestión de miniaturas](#gestión-de-miniaturas) · [Diagnóstico](#diagnóstico) · [Información de modelos](#información-de-modelos) · [Optimización de pesos](#optimización-de-pesos-comparación-por-pares) · [Configuración](#configuración) · [Etiquetado](#etiquetado) · [Validación de la base de datos](#validación-de-la-base-de-datos) · [Mantenimiento de la base de datos](#mantenimiento-de-la-base-de-datos) · [Galería web](#galería-web) · [Flujos de trabajo habituales](#flujos-de-trabajo-habituales)

> Etiquetas de requisitos usadas a continuación: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (perfil de VRAM). Consulta la [matriz de funciones](../README.md#feature-availability--requirements).

## Escaneo

| Comando | Descripción |
|---------|-------------|
| `python facet.py /path` | Escanea un directorio (modo multipaso, detección automática de VRAM) |
| `python facet.py /path --force` | Vuelve a escanear archivos ya procesados |
| `python facet.py /path --single-pass` | Fuerza el modo de un solo paso (todos los modelos a la vez) |
| `python facet.py /path --pass quality` | Ejecuta solo el paso de puntuación de calidad TOPIQ |
| `python facet.py /path --pass quality-iaa` | Ejecuta solo la puntuación de mérito estético TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Ejecuta solo la puntuación de calidad TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Ejecuta solo la calidad LIQE + diagnóstico de distorsión |
| `python facet.py /path --pass tags` | Ejecuta solo el paso de etiquetado (el modelo depende del perfil de VRAM) |
| `python facet.py /path --pass composition` | Ejecuta solo la detección de patrones de composición SAMP-Net |
| `python facet.py /path --pass faces` | Ejecuta solo la detección facial InsightFace |
| `python facet.py /path --pass embeddings` | Ejecuta solo la extracción de embeddings CLIP/SigLIP |
| `python facet.py /path --pass saliency` | Ejecuta solo la detección de saliencia del sujeto BiRefNet |
| `python facet.py /path --db custom.db` | Usa un archivo de base de datos personalizado |
| `python facet.py /path --config my.json` | Usa una configuración de puntuación personalizada |
| `python facet.py --resume` | Reanuda el último escaneo interrumpido/fallido — incluso uno que sufrió un fallo grave por SIGKILL/OOM/corte de corriente (una ejecución que sigue marcada como `running` cuyo heartbeat es más antiguo que `processing.scan_stale_seconds`, por defecto 120). Reutiliza sus directorios; con `--force`, omite los archivos ya repuntuados desde que comenzó ese escaneo. Se niega si otro escaneo parece estar realmente activo. |
| `python facet.py --retry-failed` | Reprocesa solo los archivos que fallaron durante el último escaneo (`--retry-failed all` para los fallos de todos los escaneos) |
| `python facet.py /path --force-since 2026-01-01` | Como `--force`, pero solo reprocesa las fotos escaneadas por última vez antes de la fecha |
| `python facet.py /path --watch` | Permanece en ejecución y vuelve a escanear cada vez que aparecen fotos nuevas (requiere `pip install watchdog`; `--watch-debounce N` ajusta el periodo de inactividad, por defecto 30 s) |
| `python facet.py /path --force-low-space` | Omite la comprobación previa de espacio libre (continúa incluso cuando el volumen parece demasiado pequeño para las miniaturas/embeddings que el escaneo escribirá) |

### Registro de escaneos

Cada escaneo registra una fila en `scan_runs` (estado, modo, directorios, contadores)
y los errores por archivo en `scan_failures` (ruta, fase, error). Interrumpir un
escaneo con Ctrl+C marca la ejecución como `interrupted` para que `--resume` pueda
retomarla; los archivos fallidos quedan visibles y son reintentables en lugar de
reintentarse silenciosamente en cada escaneo incremental. La CLI también emite líneas
JSON estructuradas `@FACET_PROGRESS` (fase, actual/total, ETA) que la API de escaneo del
visor expone en el campo `progress` de `/api/scan/status` y del flujo SSE.

### Modos de procesamiento

**Multipaso (por defecto):** detecta la VRAM y carga los modelos secuencialmente. Cada paso carga su modelo, procesa todas las fotos y luego lo descarga para liberar VRAM, de modo que los modelos de alta calidad se ejecutan incluso con VRAM limitada.

**Un solo paso (`--single-pass`):** carga todos los modelos a la vez. Más rápido, requiere más VRAM.

**Paso específico (`--pass NAME`):** ejecuta un único paso, para actualizar métricas específicas sin reprocesar todo. Pasos disponibles:

| Paso | Modelo | Salida | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | puntuación `aesthetic` (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | puntuación `aesthetic_iaa` (mérito artístico vs. calidad técnica, entrenado con AVA) | Compartida con TOPIQ |
| `quality-face` | TOPIQ NR-Face | puntuación `face_quality_iqa` (calidad facial específica) | Compartida con TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + diagnóstico de distorsión (desenfoque, sobreexposición, ruido) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Etiquetas semánticas del vocabulario configurado | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (14 patrones) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Detección facial, puntos de referencia, detección de parpadeo, embeddings de reconocimiento | ~2 GB |
| `embeddings` | CLIP ViT-L-14 o SigLIP 2 NaFlex | BLOB `clip_embedding` para similitud/etiquetado | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~2 GB |

## Vista previa y exportación

| Comando | Descripción |
|---------|-------------|
| `python facet.py /path --dry-run` | Puntúa 10 fotos de muestra sin guardar |
| `python facet.py /path --dry-run --dry-run-count 20` | Puntúa 20 fotos de muestra |
| `python facet.py --export-csv` | Exporta todas las puntuaciones a un CSV con marca de tiempo |
| `python facet.py --export-csv output.csv` | Exporta a un archivo CSV específico |
| `python facet.py --export-json` | Exporta todas las puntuaciones a un JSON con marca de tiempo |
| `python facet.py --export-json output.json` | Exporta a un archivo JSON específico |
| `python facet.py --import-sidecars` | Importa valoraciones/etiquetas de color/etiquetas desde los sidecars `<image>.xmp` de vuelta a la BD (todas las fotos) |
| `python facet.py --import-sidecars /path` | Importa los sidecars solo para las fotos bajo un subárbol de ruta |
| `python facet.py --import-sidecars --user alice` | Modo multiusuario: importa las valoraciones a la tabla `user_preferences` de Alice en lugar de a las columnas globales (las palabras clave siguen siendo globales) |
| `python facet.py --export-sidecars` | Escribe/fusiona los sidecars `<image>.xmp` desde la BD para todas las fotos (solo sidecar) |
| `python facet.py --export-sidecars /path` | Exporta los sidecars solo para las fotos bajo un subárbol de ruta |
| `python facet.py --export-sidecars --user alice` | Modo multiusuario: exporta las valoraciones de `user_preferences` de Alice en lugar de las columnas globales (las palabras clave siguen siendo globales) |
| `python facet.py --export-sidecars --embed-originals` | Incrusta además los metadatos **dentro del archivo** para JPEG/HEIC/TIFF/PNG/DNG (reescribe los originales) |
| `python facet.py --export-sidecars --score-to-stars` | Deriva `xmp:Rating` de la puntuación agregada para las fotos que no has valorado manualmente (una valoración/favorito/rechazo manual siempre prevalece) |

> **Sincronización bidireccional de metadatos.** Facet escribe valoraciones, etiquetas de color, palabras clave, leyendas y regiones de rostros con nombre en un sidecar `<image>.xmp` estándar que el ecosistema lee (Lightroom, darktable, digiKam, immich, …); la imagen original nunca se modifica a menos que lo actives explícitamente con `--export-sidecars --embed-originals` (solo JPEG/HEIC/TIFF/PNG/DNG — los RAW nunca se tocan). La incrustación y la fusión segura por unión de palabras clave requieren **exiftool**; sin él, Facet recurre a un sidecar XML puro sin dependencias.
>
> **Advertencia.** `--import-sidecars` resuelve las valoraciones/etiquetas con el criterio *gana el más reciente* frente al `scanned_at` de la foto (último escaneo), no a una hora de edición por valoración: un sidecar más reciente que el último escaneo puede sobrescribir una valoración que cambiaste en Facet después de él. Ejecuta `--import-sidecars` antes de volver a valorar si el editor externo es la fuente de verdad, y `python database.py --migrate-tags` tras importar si usas la tabla de búsqueda `photo_tags`.

## Operaciones de recálculo

Estos comandos actualizan métricas específicas, derivan datos nuevos (leyendas de IA, GPS, embeddings) o analizan la base de datos — todo sin volver a ejecutar el pipeline completo de puntuación. La mayoría reutilizan las miniaturas/puntos de referencia almacenados y son ligeros para la CPU, pero las filas de IA/extracción (p. ej. `--generate-captions`) y las de recálculo a partir de la imagen son intensivas en GPU.

| Comando | Descripción |
|---------|-------------|
| `python facet.py --recompute-average` | Recalcula las puntuaciones globales a partir de los embeddings almacenados (re-derivable; sin instantánea de la BD — para revertir, restaura una instantánea de pesos y recalcula) |
| `python facet.py --recompute-category portrait` | Recalcula las puntuaciones de una sola categoría |
| `python facet.py --recompute-tags` | Vuelve a etiquetar todas las fotos con el modelo configurado |
| `python facet.py --recompute-tags-vlm` | Vuelve a etiquetar todas las fotos con el etiquetador VLM |
| `python facet.py --detect-moments` | Etiqueta las fotos nuevas con su momento narrativo (CLIP zero-shot + suavizado temporal; se ejecuta automáticamente al final de cada escaneo). Económico — coseno sobre los embeddings ya almacenados, sin un paso de modelo por imagen |
| `python facet.py --recompute-moments` | Vuelve a etiquetar los momentos narrativos de toda la biblioteca (re-suaviza la línea de tiempo completa). Añade `--dry-run --verbose` para previsualizar los 3 momentos principales por foto sin escribir |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Recalcula las métricas de saliencia del sujeto (BiRefNet_dynamic) |
| `python facet.py --recompute-composition-cpu` | Recalcula la composición, basada en reglas (CPU, cualquier perfil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recalcula la composición con SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` `[8gb/16gb/24gb]` Recalcula métricas IQA suplementarias (TOPIQ IAA, NR-Face, LIQE) a partir de las miniaturas almacenadas |
| `python facet.py --recompute-ocr` | Extrae el texto presente en la imagen a `ocr_text` desde las miniaturas (opcional; sin efecto si no hay motor OCR; ejecuta `--rebuild-fts` después para indexar) |
| `python facet.py --recompute-colors` | Extrae el tono dominante + la temperatura de color cálida/fría desde las miniaturas (CPU, rápido) a `dominant_hue` / `color_temp` |
| `python facet.py --upgrade-db` | Migra el esquema y ejecuta la cadena completa de relleno: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, average. Idempotente; omite pasos pesados como el subtitulado. |
| `python facet.py --recompute-blinks` | Recalcula la detección de parpadeo a partir de los puntos de referencia almacenados (CPU, rápido) |
| `python facet.py --recompute-eyes-expression` | Recalcula las puntuaciones de ojos abiertos + expresión a partir de los puntos de referencia almacenados (CPU, rápido) |
| `python facet.py --recompute-burst` | Recalcula los grupos de detección de ráfaga |
| `python facet.py --detect-duplicates` | Detecta fotos duplicadas mediante pHash |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Evalúa los umbrales de coseno de casi-duplicados (tabla de precisión/exhaustividad con etiquetas; en su defecto, distribución de coseno de candidatos) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Genera leyendas de IA para las fotos usando VLM |
| `python facet.py --translate-captions` | Traduce las leyendas en inglés al idioma de destino configurado (CPU, MarianMT) |
| `python facet.py --extract-gps` | Extrae las coordenadas GPS de los datos EXIF a columnas de la base de datos |
| `python facet.py --rescan-gps` | Vuelve a extraer las coordenadas GPS del EXIF para todas las fotos (sobrescribe las existentes) |
| `python facet.py --recompute-embeddings` | Recalcula los embeddings CLIP/SigLIP para todas las fotos (necesario tras cambiar de modelo) |
| `python facet.py --score-topiq` | Rellena las puntuaciones de calidad TOPIQ a partir de las miniaturas almacenadas (requiere GPU) |
| `python facet.py --backfill-focal-35mm` | Rellena la distancia focal equivalente a 35 mm desde el EXIF para las fotos que la tengan ausente |
| `python facet.py --compute-recommendations` | Analiza la base de datos y muestra un resumen de puntuación |
| `python facet.py --compute-recommendations --verbose` | Muestra estadísticas detalladas |
| `python facet.py --compute-recommendations --apply-recommendations` | Aplica automáticamente las correcciones de puntuación |
| `python facet.py --compute-recommendations --simulate` | Previsualiza los cambios proyectados |

### Modelos de calidad suplementarios

Tres modelos PyIQA adicionales puntúan más allá de la puntuación estética principal de TOPIQ. Comparten VRAM con TOPIQ y se ejecutan como parte del pipeline multipaso por defecto.

- **TOPIQ IAA** (`--pass quality-iaa`): mérito estético artístico entrenado con AVA, independiente de la calidad técnica. Se almacena como `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): evaluación de la calidad de la región facial. Se almacena como `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): puntuación de calidad más un diagnóstico del tipo de distorsión (p. ej., desenfoque por movimiento, sobreexposición, ruido). Se almacena como `liqe_score`.

### Benchmarks y puntuaciones suplementarias

| Comando | Descripción |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Rellena la columna `aesthetic_clip` proyectando los embeddings CLIP/SigLIP en caché sobre un eje estético derivado de texto. Sin inferencia de imagen adicional. No forma parte del `aggregate` por defecto. Consulta [docs/SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate). |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcula SRCC + PLCC frente a la verdad de referencia de la puntuación media de opinión de AVA para cada columna de puntuación poblada en la base de datos. Útil al añadir o ajustar una variante de modelo. |

### Saliencia del sujeto

`--pass saliency` y `--recompute-saliency` usan BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, mediante `transformers`) para generar una máscara binaria del sujeto y luego derivar cuatro métricas:

- **Nitidez del sujeto**: varianza laplaciana sobre la región del sujeto frente al fondo — si el sujeto está enfocado.
- **Prominencia del sujeto**: área del sujeto / área del encuadre — alta para un sujeto dominante (p. ej., macro).
- **Ubicación del sujeto**: puntuación de la regla de los tercios para el centroide del sujeto.
- **Separación del fondo**: diferencia de gradiente de bordes entre el contorno del sujeto y el fondo — calidad del bokeh.

Requiere `transformers` (~2 GB de VRAM).

### Modelos de etiquetado

El modelo de etiquetado se selecciona según el perfil de VRAM:

| Perfil | Modelo | Cómo funciona |
|---------|-------|-------------|
| `legacy` | Similitud CLIP | Similitud de coseno entre el embedding de la imagen y los embeddings del texto de las etiquetas. Sin carga de modelo adicional. |
| `8gb` | Similitud CLIP | Igual que legacy, sobre los embeddings CLIP ViT-L-14 almacenados. |
| `16gb` | Qwen3.5-2B | Modelo multimodal para el etiquetado semántico de escenas. |
| `24gb` | Qwen3.5-4B | Modelo multimodal más grande. |

Todos los etiquetadores asignan la salida al vocabulario de etiquetas configurado. Usa `--recompute-tags` para volver a etiquetar con el modelo por defecto del perfil, o `--recompute-tags-vlm` para un reetiquetado basado en VLM.

### Modelos de embeddings

Hay dos modelos de embeddings disponibles, seleccionados según el perfil de VRAM mediante `clip_config`:

| Configuración | Modelo | Dimensiones | Usado por |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | perfiles 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | perfiles legacy, 8gb |

Los embeddings impulsan el etiquetado semántico, la detección de duplicados, la búsqueda de fotos similares y la estética CLIP+MLP (legacy/8gb). Cambiar de modelo requiere volver a generar los embeddings de todas las fotos (`--force`, `--pass embeddings` o `--recompute-embeddings`).

## Reconocimiento facial

| Comando | Descripción |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extrae rostros de las fotos nuevas (GPU, en paralelo) |
| `python facet.py --extract-faces-gpu-force` | Elimina todos los rostros y vuelve a extraerlos (GPU) |
| `python facet.py --cluster-faces-incremental` | Agrupación HDBSCAN, conserva todas las personas (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Agrupación, conserva solo las personas con nombre (CPU) |
| `python facet.py --cluster-faces-force` | Reagrupación completa, elimina todas las personas (CPU) |
| `python facet.py --suggest-person-merges` | Sugiere posibles fusiones de personas |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Usa un umbral más estricto |
| `python facet.py --refill-face-thumbnails-incremental` | Genera las miniaturas que faltan (CPU, en paralelo) |
| `python facet.py --refill-face-thumbnails-force` | Regenera TODAS las miniaturas (CPU, en paralelo) |

## Gestión de miniaturas

| Comando | Descripción |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Corrige la rotación de las miniaturas almacenadas usando la orientación EXIF |

Lee la orientación EXIF de los archivos originales y rota los bytes de la miniatura almacenada; para fotos procesadas antes de que existiera el manejo del EXIF. Solo lee la cabecera EXIF y la miniatura almacenada, no las imágenes completas.

## Diagnóstico

| Comando | Descripción |
|---------|-------------|
| `python facet.py --doctor` | Ejecuta comprobaciones de diagnóstico (Python, GPU, dependencias, configuración, base de datos) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simula hardware de GPU para el diagnóstico |

Informa de la versión de Python, la compilación de PyTorch/CUDA, la detección de GPU y el controlador, la recomendación de perfil de VRAM, las dependencias opcionales y el estado de la configuración/base de datos. Cuando PyTorch no puede ver la GPU pero `nvidia-smi` sí, imprime el comando `pip install` para corregir la compilación de CUDA.

`--simulate-gpu NAME` y `--simulate-vram GB` prueban el comportamiento con hardware diferente. Ambos requieren `--doctor`; `--simulate-vram` requiere `--simulate-gpu`.

## Información de modelos

| Comando | Descripción |
|---------|-------------|
| `python facet.py --list-models` | Muestra los modelos disponibles y los requisitos de VRAM |

## Optimización de pesos (comparación por pares)

| Comando | Descripción |
|---------|-------------|
| `python facet.py --comparison-stats` | Muestra las estadísticas de comparación por pares |
| `python facet.py --optimize-weights` | Optimiza y guarda los pesos a partir de las comparaciones (todas las fuentes, ponderado por fiabilidad); se aplica solo si la precisión de validación cruzada k-fold de datos reservados supera la de los pesos actuales |
| `python facet.py --optimize-weights --optimize-force` | Aplica los pesos optimizados aunque no se cumpla el umbral de precisión |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Restringe los datos de entrenamiento a fuentes de comparación específicas |
| `python facet.py --optimize-weights --optimize-category portrait` | Entrena solo en una categoría y escribe su bloque `categories[].weights` v4 |
| `python facet.py --auto-tune-categories` | **Solo superadministrador** (pasa `--user` en modo multiusuario): informa la disponibilidad de etiquetas de comparación por categoría para el autoajuste de los pesos globales compartidos. Stub — solo informa la disponibilidad; el bucle de aplicación automática está aplazado a la espera de etiquetas |
| `python facet.py --sync-label-comparisons` | Reconstruye los pares derivados de valoraciones (source=rating) a partir de valoraciones por estrellas/favoritos/rechazos |
| `python facet.py --train-ranker` | Entrena el clasificador personal sobre [embedding + puntuaciones] y escribe learned_scores (sujeto a la precisión de validación cruzada k-fold de datos reservados frente a la línea base del agregado) |
| `python facet.py --train-ranker --ranker-category portrait` | Entrena el clasificador solo en una categoría |
| `python facet.py --train-ranker --train-ranker-force` | Escribe learned_scores aunque no se cumpla el umbral de precisión |
| `python facet.py --report-unreviewed-bursts` | Informa de cuántos grupos de ráfaga siguen sin revisar (solo lectura) |
| `python facet.py --eval-iqa-srcc` | Informa del SRCC de Spearman de cada métrica IQA/estética frente a tus valoraciones por estrellas (solo lectura) |
| `python facet.py --mine-insights` | Informe de minería de datos: inventario de etiquetas, correlaciones métrica-etiqueta, distribución por categoría, deriva de percentiles, salud de las comparaciones |
| `python facet.py --mine-insights report.json` | Lo mismo, además escribe el informe completo en JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Calibra los pesos de puntuación por categoría frente al [conjunto de datos AVA](https://github.com/imfing/ava_downloader) maximizando el SRCC frente a las puntuaciones medias de opinión de AVA (solo lectura; imprime los pesos propuestos) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Restringe a categorías específicas y escribe los pesos optimizados de vuelta a `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Elige el optimizador (`de` = evolución diferencial, por defecto; `nelder-mead` = símplex local) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Calibra también frente a las etiquetas semánticas de AVA (`--ava-tags-only` para usar las etiquetas exclusivamente; `--apply-filters` para ajustar también los umbrales de los filtros de categoría) |

## Configuración

| Comando | Descripción |
|---------|-------------|
| `python facet.py --validate-categories` | Valida las configuraciones de categorías |

## Etiquetado

| Comando | Descripción |
|---------|-------------|
| `python tag_existing.py` | Añade etiquetas a las fotos sin etiquetar usando los embeddings CLIP almacenados |
| `python tag_existing.py --dry-run` | Previsualiza las etiquetas sin guardar |
| `python tag_existing.py --threshold 0.25` | Umbral de similitud personalizado (por defecto: 0.22) |
| `python tag_existing.py --max-tags 3` | Limita las etiquetas por foto (por defecto: 5) |
| `python tag_existing.py --force` | Vuelve a etiquetar todas las fotos |
| `python tag_existing.py --db custom.db` | Usa una base de datos personalizada |
| `python tag_existing.py --config my.json` | Usa una configuración personalizada |

## Validación de la base de datos

| Comando | Descripción |
|---------|-------------|
| `python validate_db.py` | Valida la coherencia de la base de datos (interactivo) |
| `python validate_db.py --auto-fix` | Corrige automáticamente todos los problemas |
| `python validate_db.py --report-only` | Informa sin pedir confirmación |
| `python validate_db.py --db custom.db` | Valida una base de datos personalizada |

Comprueba: rangos de puntuación, métricas faciales, corrupción de BLOB, tamaños de embeddings, rostros huérfanos, valores atípicos estadísticos.

## Mantenimiento de la base de datos

| Comando | Descripción |
|---------|-------------|
| `python database.py` | Inicializa/actualiza el esquema |
| `python database.py --info` | Muestra información del esquema |
| `python database.py --migrate-tags` | Puebla la tabla de búsqueda photo_tags (consultas 10-50 veces más rápidas) |
| `python database.py --rebuild-fts` | Reconstruye el índice de búsqueda de texto completo FTS5 a partir de leyendas/etiquetas |
| `python database.py --populate-vec` | Puebla la tabla de búsqueda vectorial sqlite-vec a partir de los embeddings |
| `python database.py --refresh-stats` | Actualiza la caché de estadísticas |
| `python database.py --stats-info` | Muestra el estado y la antigüedad de la caché |
| `python database.py --vacuum` | Recupera espacio y desfragmenta |
| `python database.py --analyze` | Actualiza las estadísticas del planificador de consultas |
| `python database.py --optimize` | Ejecuta VACUUM y ANALYZE |
| `python database.py --backup` | Escribe una instantánea de la BD con marca de tiempo y segura para WAL (rota hasta `--keep N`, 3 por defecto) |
| `python database.py --export-viewer-db` | Exporta una base de datos ligera para el visor (elimina los BLOB, reduce las miniaturas; incremental si la salida ya existe) |
| `python database.py --export-viewer-db --force-export` | Fuerza una reexportación completa, incluso si la base de datos del visor ya existe |
| `python database.py --cleanup-orphaned-persons` | Elimina las personas sin rostros asociados |
| `python database.py --cleanup-missing-photos` | Elimina de la base de datos las fotos que ya no están en disco (las eliminaciones en cascada limpian etiquetas, rostros detectados, etc.; también borra las pertenencias a álbumes, el índice vectorial e invalida la caché de estadísticas) |
| `python database.py --cleanup-missing-photos --dry-run` | Previsualiza los archivos ausentes sin eliminar |
| `python database.py --cleanup-missing-photos --force` | Continúa incluso cuando todas las fotos parecen ausentes (protección contra eliminarlo todo cuando un volumen está desmontado) |
| `python database.py --migrate-storage-fs` | Migra las miniaturas y los embeddings de los BLOB de la base de datos al sistema de archivos |
| `python database.py --migrate-storage-db` | Migra las miniaturas y los embeddings del sistema de archivos de vuelta a la base de datos |
| `python database.py --add-user alice --role admin` | Añade un usuario (solicita la contraseña) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Añade un usuario con nombre para mostrar |
| `python database.py --migrate-user-preferences --user alice` | Copia las valoraciones de photos a user_preferences |

**Consejo de rendimiento:** Para bases de datos grandes (50k+ fotos), ejecuta `--migrate-tags`, `--rebuild-fts` y `--populate-vec` una vez, y luego `--optimize` periódicamente.

## Galería web

| Comando | Descripción |
|---------|-------------|
| `python viewer.py` | Inicia el servidor en http://localhost:5000 (API + SPA de Angular) |
| `python viewer.py --port 5001` | Vincula a un puerto diferente (o define la variable de entorno `PORT`; por defecto 5000) |
| `python viewer.py --host 127.0.0.1` | Vincula a una interfaz específica (por defecto `0.0.0.0`) |
| `python viewer.py --production` | Modo de producción (workers de uvicorn) |
| `python viewer.py --production --workers 4` | Modo de producción con N workers (por defecto 1) |

## Flujos de trabajo habituales

### Configuración inicial
```bash
python facet.py /path/to/photos     # Puntúa todas las fotos (multipaso automático)
python facet.py --cluster-faces-incremental # Agrupa rostros
python database.py --migrate-tags    # Habilita consultas rápidas de etiquetas
python viewer.py                    # Ver resultados
```

### Tras cambios de configuración
```bash
python facet.py --recompute-average                # Actualiza todas las puntuaciones con los nuevos pesos
python facet.py --recompute-category portrait      # Actualiza solo una categoría (más rápido)
```

### Configuración del reconocimiento facial
```bash
python facet.py /path               # Extrae rostros durante el escaneo
python facet.py --cluster-faces-incremental     # Agrupa en personas
python facet.py --suggest-person-merges         # Encuentra duplicados
# Usa /persons en el visor para fusionar/renombrar
```

### Configuración multiusuario
```bash
# Añade usuarios (solicita la contraseña)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# Edita scoring_config.json para definir directories y shared_directories
# Migra las valoraciones existentes a un usuario
python database.py --migrate-user-preferences --user alice
```

### Cambiar el modelo de etiquetado
```bash
# Edita scoring_config.json: "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Vuelve a etiquetar con el nuevo modelo
```

### Cambiar el perfil de VRAM
```bash
# Edita scoring_config.json: "vram_profile": "auto"
# O usa uno específico: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Comprueba las distribuciones
python facet.py --recompute-average        # Aplica los nuevos pesos
```
