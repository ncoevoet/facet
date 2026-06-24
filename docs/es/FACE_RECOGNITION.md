# Reconocimiento facial

> 🌐 [English](../FACE_RECOGNITION.md) · [Français](../fr/FACE_RECOGNITION.md) · [Deutsch](../de/FACE_RECOGNITION.md) · [Italiano](../it/FACE_RECOGNITION.md) · **Español**

Facet utiliza InsightFace para la detección de rostros y HDBSCAN para agrupar rostros en personas.

## Visión general

1. **Detección** - El modelo buffalo_l de InsightFace detecta rostros y extrae embeddings de 512 dimensiones
2. **Agrupamiento** - HDBSCAN agrupa embeddings similares en clústeres de personas
3. **Gestión** - Galería web para fusionar, renombrar y organizar personas

## Flujo de trabajo completo

### Paso 1: Extraer rostros

Durante el escaneo de fotos, los rostros se extraen automáticamente:

```bash
python facet.py /path/to/photos
```

Para fotos existentes sin rostros:

```bash
python facet.py --extract-faces-gpu-incremental  # Solo fotos nuevas
python facet.py --extract-faces-gpu-force        # Todas las fotos (elimina las existentes)
```

### Paso 2: Agrupar rostros

Agrupa rostros similares en personas:

```bash
python facet.py --cluster-faces-incremental  # Conserva las personas existentes
```

**Modos de agrupamiento:**

| Comando | Comportamiento |
|---------|----------|
| `--cluster-faces-incremental` | Conserva todas las personas, asocia las nuevas a las existentes |
| `--cluster-faces-incremental-named` | Conserva solo las personas con nombre |
| `--cluster-faces-force` | Elimina todas las personas, reagrupamiento completo |

### Paso 3: Revisar y fusionar

Encuentra clústeres de personas duplicados:

```bash
python facet.py --suggest-person-merges
python facet.py --suggest-person-merges --merge-threshold 0.7  # Más estricto
```

Abre el navegador en la página de sugerencias de fusión.

### Paso 4: Revisar las sugerencias de fusión

La interfaz web en `/merge-suggestions` muestra pares de clústeres de personas que podrían ser el mismo individuo:

- Ajusta el **control deslizante de umbral de similitud** para controlar cuán conservadoras son las sugerencias
- Revisa cada sugerencia lado a lado con las miniaturas de los rostros
- **Fusión con un clic** para combinar dos personas, o **fusión por lotes** para procesar varias sugerencias a la vez
- También disponible a través de la CLI: `python facet.py --suggest-person-merges --merge-threshold 0.7`

### Paso 5: Gestión manual

En la galería web:
- Accede a `/persons` para la gestión de personas
- Fusionar: Selecciona la persona de origen, haz clic en la de destino, confirma
- Fusión por lotes: Selecciona varias personas y fusiónalas en un único destino
- Dividir: Mueve un subconjunto de los rostros de una persona a una persona nueva (si el origen queda vacío, se elimina)
- Ocultar: Marca un clúster como `is_hidden` para excluirlo de la lista, los filtros y las sugerencias de fusión (reversible)
- Renombrar: Haz clic en el nombre de la persona para editarlo en línea
- Eliminar: Elimina el clúster de la persona

## Configuración

### Detección de rostros

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28
  }
}
```

| Ajuste | Predeterminado | Descripción |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confianza mínima de detección |
| `min_face_size` | `20` | Tamaño mínimo del rostro en píxeles |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio para la detección de parpadeos |

### Agrupamiento de rostros

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

| Ajuste | Predeterminado | Descripción |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Mínimo de fotos para crear una persona |
| `min_samples` | `2` | Parámetro min_samples de HDBSCAN |
| `merge_threshold` | `0.6` | Similitud de centroides para la asociación |
| `use_gpu` | `"auto"` | Modo GPU: `auto`, `always`, `never` |

### Procesamiento de rostros

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
    "refill_batch_size": 100
  }
}
```

## Algoritmos de agrupamiento

Para el agrupamiento por CPU, elige el algoritmo según el tamaño del conjunto de datos:

| Algoritmo | Complejidad | Ideal para |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Alta dimensionalidad (recomendado para más de 50K rostros) |
| `boruvka_kdtree` | O(n log n) | Datos de baja dimensionalidad |
| `prims_balltree` | O(n²) | Conjuntos pequeños, memoria limitada |
| `prims_kdtree` | O(n²) | Conjuntos pequeños |
| `best` | Auto | Deja que HDBSCAN decida |

**Nota de rendimiento:** Para conjuntos de datos grandes, usa `boruvka_balltree`. Con 80K rostros se completa en 2-5 minutos, mientras que los algoritmos exactos pueden quedarse colgados.

## Agrupamiento por GPU (cuML)

Para conjuntos de datos grandes (más de 80K rostros), el agrupamiento por GPU mediante RAPIDS cuML es más rápido que por CPU.

### Instalación

```bash
# Conda
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Pip
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
```

### Configuración

```json
{
  "face_clustering": {
    "use_gpu": "auto"
  }
}
```

| Modo | Comportamiento |
|------|----------|
| `"auto"` | Usa GPU si cuML está disponible, recurre a CPU |
| `"always"` | Intenta GPU, avisa y recurre a CPU si no está disponible |
| `"never"` | Usa siempre CPU |

**Nota:** cuML utiliza su propia implementación de HDBSCAN. Los parámetros `algorithm` y `leaf_size` solo se aplican al agrupamiento por CPU.

## Detección de parpadeos

Utiliza el Eye Aspect Ratio (EAR) a partir de los 106 puntos de referencia de InsightFace.

### Cómo funciona

El EAR mide la relación entre la altura y la anchura del ojo. Cuando los ojos se cierran, el EAR cae por debajo del umbral.

### Configuración

```json
{
  "face_detection": {
    "blink_ear_threshold": 0.28
  }
}
```

Umbral más bajo = detección más estricta (más fotos marcadas como parpadeos).

### Recalcular tras cambiar el umbral

```bash
python facet.py --recompute-blinks
```

Solo procesa fotos con rostros, no necesita GPU.

## Miniaturas de rostros

Las miniaturas se almacenan en la base de datos para una visualización rápida.

### Almacenamiento

- Se generan durante el escaneo a partir de imágenes a resolución completa
- Se almacenan en la columna `faces.face_thumbnail` como BLOBs JPEG (~5-10KB cada uno)
- Se utilizan en el agrupamiento y la galería en lugar de regenerarlas

### Regeneración

```bash
# Generar las miniaturas que faltan
python facet.py --refill-face-thumbnails-incremental

# Regenerar TODAS las miniaturas
python facet.py --refill-face-thumbnails-force
```

Ambos comandos usan procesamiento paralelo para mayor velocidad.

## Esquema de la base de datos

### Tabla faces

| Columna | Tipo | Descripción |
|--------|------|-------------|
| `id` | INTEGER | Clave primaria |
| `photo_path` | TEXT | Clave externa a photos |
| `face_index` | INTEGER | Índice dentro de la foto |
| `embedding` | BLOB | Embedding facial de 512 dimensiones |
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | INTEGER | Esquinas del cuadro delimitador |
| `confidence` | REAL | Confianza de detección |
| `person_id` | INTEGER | Clave externa a persons |
| `face_thumbnail` | BLOB | Miniatura JPEG |
| `landmark_2d_106` | BLOB | 106 puntos de referencia (detección de parpadeos) |
| `embedding_model` | TEXT | Etiqueta del modelo de reconocimiento (predeterminado `arcface_buffalo_l`) |

### Tabla persons

| Columna | Tipo | Descripción |
|--------|------|-------------|
| `id` | INTEGER | Clave primaria |
| `name` | TEXT | Nombre de la persona (NULL = agrupada automáticamente) |
| `representative_face_id` | INTEGER | Mejor rostro para el avatar |
| `face_count` | INTEGER | Número de rostros |
| `centroid` | BLOB | Embedding del centroide del clúster |
| `auto_clustered` | INTEGER | 1 si se generó automáticamente |
| `face_thumbnail` | BLOB | Miniatura del avatar de la persona |
| `is_hidden` | INTEGER | 1 = excluida de filtros/sugerencias |

## Modos incremental vs. forzado

### Agrupamiento incremental

- Conserva todas las personas existentes (con nombre y agrupadas automáticamente)
- Agrupa solo los rostros nuevos sin asignar
- Asocia los nuevos clústeres a las personas existentes mediante la similitud de centroides
- Actualiza los centroides tras la fusión

**Úsalo cuando:** Añadas fotos nuevas a una colección existente

### Agrupamiento forzado

- Elimina TODAS las personas, incluidas las que tienen nombre
- Reagrupamiento completo desde cero

**Úsalo cuando:** Empieces de cero o cambies sustancialmente el algoritmo

### Agrupamiento incremental con nombre

- Conserva solo las personas con nombre
- Elimina las personas agrupadas automáticamente
- Reagrupa todos los rostros sin nombre

**Úsalo cuando:** Quieras mantener los nombres curados mientras actualizas los clústeres detectados automáticamente

## Integración con la galería

### Filtro de personas

- El desplegable muestra las personas con miniaturas de rostros
- Filtra la galería por persona

### Galería de persona

- Haz clic en una persona del desplegable para ver todas sus fotos
- URL: `/person/<id>`

### Página de gestión de personas

Accede mediante el botón de la cabecera o `/persons`:

- **Vista de cuadrícula** - Todas las personas reconocidas
- **Fusionar** - Selecciona el origen, haz clic en el destino, confirma
- **Fusión por lotes** - Selecciona varias personas y fusiónalas en un único destino
- **Dividir** - Mueve los rostros seleccionados a una persona nueva
- **Ocultar** - Excluye un clúster de la lista, los filtros y las sugerencias de fusión
- **Eliminar** - Elimina el clúster de la persona
- **Renombrar** - Haz clic en el nombre para editarlo en línea

### Página de sugerencias de fusión

Accede mediante `/merge-suggestions` o el botón "Merge Suggestions" en la página de gestión de personas:

- Muestra pares de personas con embeddings faciales similares que podrían ser el mismo individuo
- **Control deslizante de umbral** — controla el límite de similitud (más bajo = más sugerencias)
- **Fusión con un clic** — fusiona un par sugerido al instante
- **Fusión por lotes** — selecciona varias sugerencias y fusiónalas todas a la vez

### Tarjetas de foto

- Se muestran pequeñas miniaturas de rostros (avatares) para las personas reconocidas
- Configurable mediante `viewer.face_thumbnails.output_size_px`

## Marcador del espacio de embeddings (seguridad del modelo de reconocimiento)

Cada fila de rostro lleva una etiqueta `embedding_model` (columna en `faces`, predeterminada
`arcface_buffalo_l` — el modelo de reconocimiento actual `buffalo_l` de InsightFace / ArcFace
`w600k_r50`). Los embeddings producidos por modelos de reconocimiento **diferentes** viven
en **espacios vectoriales incompatibles** y nunca deben agruparse juntos — hacerlo
produce silenciosamente personas erróneas sin ningún error.

Por ello, `FaceClusterer.load_embeddings()` carga únicamente el espacio de embeddings
**activo** (`ACTIVE_EMBEDDING_MODEL` en `faces/clusterer.py`; una etiqueta `NULL` se trata
como el espacio ArcFace heredado) y registra una advertencia llamativa si hay rostros de
cualquier otro espacio presentes y excluidos. Es una salvaguarda de compatibilidad futura:
hace que un futuro cambio del modelo de reconocimiento sea seguro por diseño.

### Cambiar el modelo de reconocimiento (p. ej. AdaFace) — plan diferido

Una mejora de calidad como **AdaFace** (margen adaptativo según la calidad, mejor agrupamiento
de rostros borrosos/espontáneos) es integrable como backend opcional de 512 dimensiones (misma
ruta de almacenamiento, mismo HDBSCAN), pero **aún no está implementada** porque no se puede
validar sin datos reales. Hacerlo correctamente requiere:

1. **Pesos + backbone** — un checkpoint de AdaFace (p. ej. `adaface_ir101_webface12m`)
   más su backbone IResNet; una nueva descarga a la caché de modelos.
2. **Recortes alineados** — calcular el embedding a partir de un recorte alineado
   `norm_crop(img, face.kps, 112)` de 112×112 en el momento de la extracción (los kps existen
   en el objeto `face` de InsightFace pero no se persisten, por lo que AdaFace no se puede
   rellenar a posteriori sin conexión — debe ejecutarse durante la extracción). Verifica que
   la normalización/BGR coincida con el checkpoint.
3. **Conmutador de configuración** — añadir `face_detection.recognition_model: arcface|adaface`
   y resolver `ACTIVE_EMBEDDING_MODEL` a partir de él; etiquetar los nuevos rostros en consecuencia.
4. **Reextracción + reagrupamiento completos** — `--extract-faces-gpu-force` y luego
   `--cluster-faces-force`, porque los embeddings de ArcFace y AdaFace no son
   comparables. El marcador del espacio de embeddings anterior evita que una base de datos
   migrada a medias agrupe silenciosamente ambos espacios (avisa y los excluye en su lugar).
5. **Validación de calidad** — medir la calidad de los clústeres frente a identidades
   etiquetadas; "se ejecuta y emite vectores de 512 dimensiones" no demuestra que el
   preprocesamiento sea correcto.

## Resolución de problemas

| Problema | Solución |
|-------|----------|
| El agrupamiento se queda colgado | Usa el algoritmo `boruvka_balltree` |
| Demasiados clústeres pequeños | Aumenta `min_faces_per_person` |
| Los rostros no se agrupan | Reduce `merge_threshold` |
| El agrupamiento por GPU falla | Comprueba la instalación de cuML, usa `"never"` para forzar la CPU |
| Faltan miniaturas | Ejecuta `--refill-face-thumbnails-incremental` |
| Detección de parpadeos incorrecta | Ajusta `blink_ear_threshold`, ejecuta `--recompute-blinks` |
| Advertencia "Excluded N faces from non-active embedding space" | Un cambio del modelo de reconocimiento dejó embeddings mezclados — ejecuta `--extract-faces-gpu-force` y luego `--cluster-faces-force` |
