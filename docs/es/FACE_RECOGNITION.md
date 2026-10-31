# Reconocimiento facial

> 🌐 [English](../FACE_RECOGNITION.md) · [Français](../fr/FACE_RECOGNITION.md) · [Deutsch](../de/FACE_RECOGNITION.md) · [Italiano](../it/FACE_RECOGNITION.md) · **Español** · [Português](../pt/FACE_RECOGNITION.md) · [简体中文](../zh/FACE_RECOGNITION.md)

Facet usa InsightFace para la detección de rostros y HDBSCAN para agrupar los rostros en personas.

## Visión general

1. **Detección** - El modelo buffalo_l de InsightFace detecta rostros y extrae embeddings de 512 dimensiones
2. **Agrupamiento** - HDBSCAN agrupa los embeddings similares en clústeres de personas
3. **Gestión** - Visor web para fusionar, renombrar y organizar personas

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
| `--cluster-faces-force` | Elimina todas las personas, reagrupa por completo |

### Paso 3: Revisar y fusionar

Encuentra clústeres de personas duplicados:

```bash
python facet.py --suggest-person-merges
python facet.py --suggest-person-merges --merge-threshold 0.7  # Más estricto
```

Esto abre en el navegador la página de sugerencias de fusión.

### Paso 4: Gestión en el visor

El trabajo restante ocurre en el visor web, siguiendo el flujo **Extraer → Agrupar → Fusionar → Gestionar**:

- **Fusiona** los clústeres duplicados en la página de sugerencias de fusión.
- **Gestiona** las personas (fusionar, fusión por lotes, dividir, ocultar, renombrar, eliminar) en la página de gestión de personas.

Consulta [Integración con la galería](#integración-con-la-galería) para la referencia completa de la interfaz.

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

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confianza mínima de detección |
| `min_face_size` | `20` | Tamaño mínimo del rostro en píxeles (solo InsightFace, ver nota) |
| `blink_ear_threshold` | `0.28` | Relación de aspecto del ojo (EAR) para la detección de parpadeos |

En modo comercial, el detector YuNet usa valores fijos (0.7 de confianza, 30 px) e ignora `min_confidence_percent` y `min_face_size`.

### Agrupamiento de rostros

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Mínimo de fotos para crear una persona |
| `min_samples` | `2` | Parámetro min_samples de HDBSCAN |
| `thresholds_by_model` | ver JSON | Por modelo: `auto_merge_distance_percent` y `merge_threshold` (ArcFace `15` / `0.6`, SFace `27.5` / `0.65`) |
| `use_gpu` | `"auto"` | Modo de GPU: `auto`, `always`, `never` |

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

Para el agrupamiento en CPU, elige el algoritmo según el tamaño del conjunto de datos:

| Algoritmo | Complejidad | Ideal para |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Alta dimensionalidad (recomendado para más de 50 000 rostros) |
| `boruvka_kdtree` | O(n log n) | Datos de baja dimensionalidad |
| `prims_balltree` | O(n²) | Conjuntos pequeños, memoria limitada |
| `prims_kdtree` | O(n²) | Conjuntos pequeños |
| `best` | Auto | Dejar que HDBSCAN decida |

**Nota de rendimiento:** Para conjuntos grandes, usa `boruvka_balltree`. Con 80 000 rostros termina en 2-5 minutos, mientras que los algoritmos exactos pueden quedarse colgados.

## Agrupamiento por GPU (cuML)

Para conjuntos grandes (más de 80 000 rostros), el agrupamiento por GPU con RAPIDS cuML es más rápido que en CPU.

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
| `"auto"` | Usa la GPU si cuML está disponible, recurre a la CPU si no |
| `"always"` | Intenta la GPU, avisa y recurre a la CPU si no está disponible |
| `"never"` | Usa siempre la CPU |

**Nota:** cuML usa su propia implementación de HDBSCAN. Los parámetros `algorithm` y `leaf_size` solo se aplican al agrupamiento en CPU.

### La GPU y la CPU no producen clústeres idénticos

Con los mismos rostros y parámetros, cuML genera algo más de clústeres, y más pequeños, que el agrupamiento en CPU (aproximadamente 1.1–1.2 veces más). Quién se agrupa con quién se mantiene más o menos igual, pero el *número* de clústeres difiere entre una ejecución en GPU y otra en CPU.

**cuML tampoco es determinista.** Dos ejecuciones en GPU con los mismos rostros dan recuentos de clústeres casi idénticos pero etiquetas distintas.

- **Los ID de persona no son reproducibles entre ejecuciones.** Pon nombre a las personas que te importan; las personas con nombre permanecen estables.
- **No compares dos ejecuciones de agrupamiento por etiqueta.** Compara en su lugar la pertenencia de los rostros.

El agrupamiento en CPU con un `algorithm` fijo es determinista para la misma entrada.

### Reagrupar y las personas ya nombradas

Todos los modos excepto `--cluster-faces-force` conservan los registros de personas existentes, pero todos recalculan la persona de cada rostro.

- **Las interrupciones son seguras.** Los cambios se escriben de una sola vez al final; una ejecución detenida antes no cambia nada.
- **Ediciones en el visor durante una ejecución.** Un rostro que reasignas mientras la ejecución escribe sus resultados (los últimos segundos) conserva tu elección, y la ejecución registra cuántos omitió. Un guardado enviado en ese momento espera a la ejecución; si espera más de 5 s se rechaza con «library busy» y hay que repetirlo. Una edición hecha antes, mientras los rostros aún se están agrupando, se sobrescribe.

Un clúster reconstruido vuelve a una persona existente cuando se cumple una de estas condiciones:

1. su embedding medio está a menos de `merge_threshold` (por defecto 0.6 en coseno para ArcFace, 0.65 para SFace) del centroide almacenado de esa persona, **o**
2. al menos la mitad de sus rostros pertenecían a esa persona antes de la ejecución.

La regla 2 importa para las personas fotografiadas durante muchos años: sus rostros se dividen en subclústeres compactos que quedan lejos del único centroide promedio. Sin ella, la mayoría de los rostros de las personas con nombre no se les devolverían.

Como la regla 2 sigue la asignación anterior, un error previo se arrastra. Usa `--cluster-faces-force` para empezar desde cero. Cuando los rostros de un clúster se reparten a partes iguales entre dos personas, gana la persona que posee el rostro con el número más bajo de los asignados previamente.

## Detección de parpadeos

Usa la relación de aspecto del ojo (EAR) a partir de los 106 puntos de referencia de InsightFace.

### Cómo funciona

La EAR mide la relación entre la altura y la anchura del ojo. Cuando los ojos se cierran, la EAR cae por debajo del umbral.

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

Solo procesa las fotos con rostros, no necesita GPU.

## Calidad facial OFIQ opcional (modo comercial)

En modo comercial, el modelo restringido de calidad facial no está disponible. Como reemplazo opcional, instala `python-ofiq` (los bindings de UNICEF sobre OFIQ del BSI, ISO/IEC 29794-5; MIT):

```bash
pip install python-ofiq
```

- Existen wheels solo para Linux x86-64 y macOS arm64 (en Windows, usa WSL2 o Docker). Funciona con numpy 2 y OpenCV 4.8+.
- En el primer uso, Facet descarga los modelos OFIQ (unos 400 MB, MIT/Apache-2.0, con SHA-256 fijado) en `pretrained_models/ofiq/`.
- La puntuación de OFIQ (0-100) se divide entre 10 y se almacena en `face_quality_iqa`. El valor de una foto es 0.7 x su peor rostro + 0.3 x la media.
- Sin `python-ofiq`, la columna permanece en NULL y su peso se reparte entre las demás métricas.

## Señales de expresión por rostro (ojos abiertos + sonrisa)

Cada rostro almacena dos puntuaciones 0-10, usadas por el panel de rostros de la selección y por las puntuaciones a nivel de foto: `eyes_open_score` (10 = muy abiertos, 0 = totalmente cerrados) y `smile_score` (5 = neutro, 10 = sonrisa amplia, 0 = ceño fruncido).

Dos backends las producen en la misma escala:

1. **Geometría (siempre disponible).** Se calcula a partir de los 106 puntos de referencia
   de InsightFace almacenados: relación de aspecto del ojo para los ojos, elevación de las
   comisuras de la boca para la sonrisa.
   `--recompute-face-signals` puede rellenarlas sin GPU y sin leer imágenes.
2. **Blendshapes de MediaPipe (opcional).** Durante el escaneo y la extracción de rostros,
   cada recorte de rostro pasa por el MediaPipe Face Landmarker, cuyos blendshapes
   (`eyeBlink*`, `mouthSmile*`, `mouthFrown*`) se asignan a las mismas escalas.
   Lee mejor los ojos cerrados, las sonrisas sutiles y las cabezas giradas, así que su valor
   **reemplaza** al geométrico. Si falta MediaPipe o su modelo, o el recorte es demasiado
   pequeño, se conserva el valor geométrico.

### Instalar MediaPipe

MediaPipe es opcional. Instálalo **sin** su `opencv-contrib-python` incluido,
que chocaría con el `opencv-python` de Facet (ambos proporcionan `cv2`):

```bash
pip install mediapipe==0.10.35 --no-deps
pip install absl-py flatbuffers
```

No ejecutes nunca un simple `pip install mediapipe`.

### Paquete de modelo

El paquete `face_landmarker.task` (~3.6 MiB, Apache-2.0) se descarga en el primer uso
a `pretrained_models/face_landmarker.task`. Sin conexión, descárgalo desde
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
y colócalo allí. Si la descarga falla, Facet avisa una vez y usa la geometría.

### Configuración

```json
{
  "face_detection": {
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

- `enabled` (por defecto `true`): usa los blendshapes cuando MediaPipe y el modelo están
  disponibles. Pon `false` para forzar solo la geometría.
- `min_crop_size` (por defecto `192`): los rostros cuyo recorte con margen es menor que esto
  (px, lado más corto) usan la geometría en lugar de un recorte ampliado.
- `blink_pose_gate_deg` (por defecto `null` = desactivado): solo para el analizador del modo comercial (MediaPipe). Un rostro girado más de estos grados (|yaw| o |pitch|) no recibe veredicto de parpadeo ni puntuación de ojos abiertos / sonrisa, ya que una cabeza girada parece tener los ojos cerrados. Las pruebas no encontraron ningún umbral entre 20° y 45° que ayudara, así que se entrega desactivado; actívalo solo si tu biblioteca tiene muchos rostros muy girados. Debe ser un número positivo. Se aplica a las fotos recién escaneadas; los valores `is_blink` existentes cambian solo al reescanear.

### Recálculo

`--recompute-face-signals` usa solo los puntos de referencia almacenados: es **solo
geometría** y no ejecuta MediaPipe. Para refrescar las puntuaciones de MediaPipe,
vuelve a extraer los rostros con `--extract-faces-gpu-force`.

## Miniaturas de rostros

Las miniaturas se almacenan en la base de datos para mostrarlas rápidamente.

### Almacenamiento

- Se generan durante el escaneo a partir de las imágenes a resolución completa
- Se guardan en la columna `faces.face_thumbnail` como BLOB JPEG (~5-10KB cada una)
- El agrupamiento y el visor las usan en lugar de regenerarlas

### Regeneración

```bash
# Generar las miniaturas que faltan
python facet.py --refill-face-thumbnails-incremental

# Regenerar TODAS las miniaturas
python facet.py --refill-face-thumbnails-force
```

Ambos comandos usan procesamiento en paralelo para mayor velocidad.

## Esquema de la base de datos

### Tabla faces

| Columna | Tipo | Descripción |
|--------|------|-------------|
| `id` | INTEGER | Clave primaria |
| `photo_path` | TEXT | Clave externa a photos |
| `face_index` | INTEGER | Índice dentro de la foto |
| `embedding` | BLOB | Embedding facial de 512 dimensiones |
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | INTEGER | Esquinas del cuadro delimitador |
| `confidence` | REAL | Confianza de la detección |
| `person_id` | INTEGER | Clave externa a persons |
| `face_thumbnail` | BLOB | Miniatura JPEG |
| `landmark_2d_106` | BLOB | 106 puntos de referencia (detección de parpadeos) |
| `embedding_model` | TEXT | Etiqueta del modelo de reconocimiento (por defecto `arcface_buffalo_l`) |

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
| `is_hidden` | INTEGER | 1 = excluida de los filtros/sugerencias |

## Modos incremental vs. forzado

### Agrupamiento incremental

- Conserva todas las personas existentes (con nombre y agrupadas automáticamente)
- Agrupa solo los rostros nuevos sin asignar
- Asocia los clústeres nuevos con personas existentes por similitud de centroide
- Actualiza los centroides tras la fusión

**Úsalo cuando:** añades fotos nuevas a una colección existente

### Agrupamiento forzado

- Elimina TODAS las personas, incluidas las que tienen nombre
- Reagrupa por completo desde cero

**Úsalo cuando:** empiezas de nuevo o hay cambios importantes de algoritmo

### Agrupamiento incremental con nombre

- Conserva solo las personas con nombre
- Elimina las personas agrupadas automáticamente
- Reagrupa todos los rostros sin nombre

**Úsalo cuando:** mantienes los nombres curados mientras refrescas los clústeres detectados automáticamente

## Integración con la galería

### Filtro de personas

- El desplegable muestra las personas con miniaturas de rostros
- Filtra la galería por persona

### Galería de persona

- Haz clic en una persona del desplegable para ver todas sus fotos
- Al hacer clic en una persona se aplica un filtro `person_id` en la galería (no hay una ruta dedicada por persona)

### Página de gestión de personas

Accede mediante el botón de la cabecera o `/persons`:

- **Vista de cuadrícula** - Todas las personas reconocidas
- **Fusionar** - Selecciona el origen, haz clic en el destino, confirma
- **Fusión por lotes** - Selecciona varias personas y fusiónalas en un único destino
- **Dividir** - Mueve los rostros seleccionados a una persona nueva
- **Ocultar** - Excluye un clúster de la lista, los filtros y las sugerencias de fusión
- **Eliminar** - Elimina el clúster de la persona
- **Renombrar** - Haz clic en el nombre para editarlo en línea

### Crear una persona

Puedes nombrar un rostro que el agrupador pasó por alto directamente desde la galería:

1. En una tarjeta de foto, abre las acciones de persona y elige un rostro sin asignar.
2. En el selector de persona, elige **Crear nueva persona** y escribe un nombre.
3. El rostro se vincula a la nueva persona (`auto_clustered = 0`).

Un rostro que ya pertenece a otra persona se mueve, y una persona que se queda sin
rostros se elimina. En modo multiusuario solo puedes vincular rostros de fotos de tus
propios directorios o de los compartidos. API: `POST /api/persons` (consulta [API.md](../API.md)).

### Por nombrar

La página de gestión de personas muestra los clústeres grandes sin nombre en una pestaña
**Por nombrar**, cada uno con un campo de nombre. Un clúster aparece allí cuando tiene al menos
`viewer.persons.needs_naming_min_faces` rostros (por defecto `5`).

Sin nombre significa sin nombre o con uno en blanco, venga el clúster del agrupamiento o de una división; las personas ocultas (ignoradas) quedan fuera. La pestaña solo aparece en modo edición, junto a **Con nombre**, que lista solo las personas con nombre, así cada persona aparece una vez; la página se abre en **Con nombre**.

### Página de sugerencias de fusión

Accede mediante `/merge-suggestions` o el botón "Merge Suggestions" en la página de gestión de personas:

- Muestra pares de personas cuyos rostros se parecen
- **Control deslizante de umbral** — límite de similitud (más bajo = más sugerencias)
- **Fusión con un clic** — fusiona un par sugerido
- **Fusión por lotes** — fusiona varias sugerencias a la vez

### Tarjetas de foto

- Se muestran pequeñas miniaturas de rostros (avatares) para las personas reconocidas
- Configurable mediante `viewer.face_thumbnails.output_size_px`

## Marcador del espacio de embeddings (seguridad del modelo de reconocimiento)

Cada rostro almacena en `embedding_model` el modelo de reconocimiento que lo produjo (por defecto `arcface_buffalo_l`, el modelo `buffalo_l` de InsightFace / ArcFace `w600k_r50`). Los embeddings de modelos distintos no se pueden comparar, así que el agrupamiento usa solo los rostros del modelo **activo**. Una etiqueta `NULL` cuenta como ArcFace. Si hay rostros de otro modelo, Facet los excluye y registra una advertencia.

### Cambiar el modelo de reconocimiento (p. ej. AdaFace) — plan diferido

AdaFace (mejor agrupamiento de rostros borrosos o espontáneos) **aún no está implementado**. Adoptarlo exigiría una reextracción y un reagrupamiento completos (`--extract-faces-gpu-force` y luego `--cluster-faces-force`), porque los embeddings de ArcFace y de AdaFace no son comparables.

### Bibliotecas mixtas, reextracción y valores desconocidos

- **Bibliotecas mixtas.** Una biblioteca puede contener a la vez rostros de ArcFace (512-d) y de SFace (128-d). El agrupamiento, las sugerencias de fusión, la búsqueda de personas similares y los centroides usan cada uno un solo modelo a la vez (`persons.centroid_model` lo registra).
  - Los modos incremental y solo-con-nombre dejan intactos los rostros y personas del otro modelo.
  - `--cluster-faces-force` borra todas las asignaciones de rostros y elimina todas las personas, también las que tienen nombre, sea cual sea el modelo.
  - Para llevar una biblioteca al modelo activo, ejecuta `--extract-faces-gpu-force` (extractor permisivo en modo comercial; las personas con nombre se conservan) y luego `--cluster-faces-incremental`.
- **Advertencias.** Un escaneo avisa cuando los rostros almacenados usan un modelo distinto del activo, y `--doctor` también lo informa. En modo comercial, `--doctor` enumera lo que un escaneo realmente carga (YuNet, SFace, Q-ReAlign, más OFIQ cuando `python-ofiq` está instalado). En CUDA, un escaneo avisa una vez cuando InsightFace se ejecuta en la CPU; consulta la sección ONNX Runtime de `--doctor` e [Instalación › ONNX Runtime para la detección de rostros](INSTALLATION.md#onnx-runtime-para-la-detección-de-rostros).
- **Las personas con nombre sobreviven a la reextracción.** `--extract-faces-gpu-force` devuelve cada rostro redetectado a la persona con nombre cuyo cuadro de rostro antiguo se solapa con él (IoU >= 0.5, uno a uno). Los rostros sin correspondencia esperan a la siguiente ejecución de agrupamiento. Una ejecución interrumpida se reanuda en la siguiente extracción. Reescanear una foto conserva sus personas con nombre del mismo modo.
- **Desconocido no es cero.** Sin MediaPipe, el analizador permisivo no puede medir los ojos, la sonrisa ni los parpadeos, así que se almacenan como NULL; los filtros y penalizaciones de parpadeo tratan NULL como «no es un parpadeo». Si falla el paso de rostros de una foto, `face_count`, `face_ratio` e `is_group_portrait` quedan en NULL y se conservan sus rostros almacenados; puntúa como si no tuviera rostro hasta que se reescanee.

## Resolución de problemas

| Problema | Solución |
|-------|----------|
| El agrupamiento se queda colgado | Usa el algoritmo `boruvka_balltree` |
| Demasiados clústeres pequeños | Aumenta `min_faces_per_person` |
| Los rostros no se agrupan | Reduce `merge_threshold` |
| El agrupamiento por GPU falla | Comprueba la instalación de cuML, usa `"never"` para forzar la CPU |
| Faltan miniaturas | Ejecuta `--refill-face-thumbnails-incremental` |
| Detección de parpadeos incorrecta | Ajusta `blink_ear_threshold`, ejecuta `--recompute-blinks` |
| Advertencia "Excluded N faces from non-active embedding space" | Un cambio del modelo de reconocimiento dejó embeddings mezclados — ejecuta `--extract-faces-gpu-force` y luego `--cluster-faces-incremental` |
