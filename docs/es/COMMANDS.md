# Referencia de comandos

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · **Español** · [Português](../pt/COMMANDS.md) · [简体中文](../zh/COMMANDS.md)

[Escaneo](#escaneo) · [Vista previa y exportación](#vista-previa-y-exportación) · [Operaciones de recálculo](#operaciones-de-recálculo) · [Reconocimiento facial](#reconocimiento-facial) · [Gestión de miniaturas](#gestión-de-miniaturas) · [Diagnóstico](#diagnóstico) · [Información de modelos](#información-de-modelos) · [Optimización de pesos](#optimización-de-pesos-comparación-por-pares) · [Configuración](#configuración) · [Etiquetado](#etiquetado) · [Validación de la base de datos](#validación-de-la-base-de-datos) · [Mantenimiento de la base de datos](#mantenimiento-de-la-base-de-datos) · [Galería web](#galería-web) · [Flujos de trabajo habituales](#flujos-de-trabajo-habituales)

> Etiquetas de requisitos usadas a continuación: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (perfil de VRAM). Consulta la [matriz de funciones](INSTALLATION.md#requisitos-por-función).

## Escaneo

| Comando | Descripción |
|---------|-------------|
| `python facet.py /path` | Escanea un directorio (multipaso, detección automática de VRAM) |
| `python facet.py /path --force` | Vuelve a escanear los archivos ya procesados |
| `python facet.py /path --single-pass` | Carga todos los modelos a la vez; solo `legacy`/`8gb` (ver [Modos de procesamiento](#modos-de-procesamiento)) |
| `python facet.py /path --pass quality` | Ejecuta solo la puntuación de calidad TOPIQ |
| `python facet.py /path --pass quality-iaa` | Ejecuta solo la puntuación de mérito estético TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Ejecuta solo la puntuación de calidad TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Ejecuta solo la calidad LIQE + diagnóstico de distorsión |
| `python facet.py /path --pass tags` | Ejecuta solo el etiquetado (el modelo depende del perfil de VRAM) |
| `python facet.py /path --pass composition` | Ejecuta solo la detección de patrones de composición SAMP-Net |
| `python facet.py /path --pass faces` | Ejecuta solo la detección facial InsightFace |
| `python facet.py /path --pass embeddings` | Ejecuta solo la extracción de embeddings CLIP/SigLIP (no escribe etiquetas) |
| `python facet.py /path --pass saliency` | Ejecuta solo la detección de saliencia del sujeto BiRefNet |
| `python facet.py /path --db custom.db` | Usa un archivo de base de datos personalizado |
| `python facet.py /path --config my.json` | Usa una configuración de puntuación personalizada |
| `python facet.py --resume` | Reanuda el último escaneo interrumpido, fallido o bloqueado |
| `python facet.py --retry-failed` | Reprocesa los archivos que fallaron en el último escaneo (`--retry-failed all` para todas las ejecuciones) |
| `python facet.py /path --force-since 2026-01-01` | Como `--force`, solo para las fotos escaneadas por última vez antes de la fecha |
| `python facet.py /path --watch` | Vuelve a escanear cuando aparecen fotos nuevas (requiere `pip install watchdog`; `--watch-debounce N`, por defecto 30 s) |
| `python facet.py /path --force-low-space` | Omite la comprobación de espacio libre antes del escaneo |

**`--resume`** también recupera un escaneo interrumpido por un fallo, falta de memoria o corte de corriente: una ejecución aún marcada como `running` cuyo heartbeat es más antiguo que `processing.scan_stale_seconds` (por defecto 120). Reutiliza los directorios de esa ejecución. Con `--force`, omite los archivos ya repuntuados desde que comenzó la ejecución. Se niega a iniciarse si otro escaneo parece activo.

### Registro de escaneos

Facet registra cada escaneo (estado, modo, directorios, contadores) y cada error por archivo. Ctrl+C marca la ejecución como `interrupted`, para que `--resume` pueda continuarla. Los archivos fallidos se listan y solo se reintentan con `--retry-failed`. El visor muestra el progreso del escaneo a partir de las líneas `@FACET_PROGRESS` de la CLI.

### Modos de procesamiento

**Multipaso (por defecto):** detecta la VRAM y carga los modelos de uno en uno. Cada paso carga su modelo, procesa todas las fotos y luego lo descarga, de modo que los modelos de alta calidad se ejecutan incluso con VRAM limitada.

**Un solo paso (`--single-pass`):** carga todos los modelos a la vez. Es más rápido, pero requiere más VRAM.

- Puntúa la estética con el cabezal CLIP+MLP, así que se aplica a los perfiles `legacy` y `8gb`.
- En `16gb` y `24gb` el modelo de estética es TOPIQ, que solo ejecuta el modo multipaso. Una petición de un solo paso (`--single-pass` o `processing.mode: "single-pass"`) registra una advertencia y se ejecuta en multipaso.
- `--pass NAME` y `--dry-run` omiten esa comprobación.
- El modo comercial mantiene el modo de un solo paso, porque allí el Q-ReAlign nativo puntúa la estética.

**Nota de actualización:** las versiones anteriores guardaban una estética neutra de 5,0 para cada foto de un escaneo de un solo paso en `16gb`/`24gb`. Vuelve a escanear esas carpetas con `--force` en multipaso. Para encontrarlas: `SELECT path FROM photos WHERE scoring_model = 'topiq' AND aesthetic = 5.0 AND topiq_score IS NULL`.

**Paso específico (`--pass NAME`):** ejecuta un único paso, para actualizar algunas métricas sin reprocesar todo.

| Paso | Modelo | Salida | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | puntuación `aesthetic` (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` (mérito artístico, entrenado con AVA) | Compartida con TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` (calidad facial) | Compartida con TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + diagnóstico de distorsión (desenfoque, sobreexposición, ruido) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Etiquetas semánticas del vocabulario configurado | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (8 patrones) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Rostros, puntos de referencia, parpadeos, embeddings de reconocimiento | ~2 GB |
| `embeddings` | CLIP ViT-L-14 o SigLIP 2 NaFlex | `clip_embedding` para similitud y etiquetado | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~3 GB |

Las mediciones multipaso usan relojes monótonos. El tiempo EXIF del lote y los segundos de trabajo acumulados de las lecturas alternativas están incluidos en la decodificación; las alternativas paralelas pueden solaparse. Agregación, miniaturas (incluida la lectura de origen) y guardado sin miniaturas son intervalos separados; guardar incluye preparación y commit. Los pasos restringidos omiten agregación y miniaturas de fotos. No cambian los solapamientos de decodificación/modelos ni las reconstrucciones anidadas: no sumar todos los tiempos ni interpretar los segundos de trabajo EXIF como porcentaje del tiempo total. El modo de un paso queda fuera. Para una referencia, analizar una copia fija de 500 RAW/JPEG en una base temporal y conservar resumen, revisión, perfil, workers, tamaño de bloque, almacenamiento y condiciones de caché. Repetir en condiciones idénticas. No se aporta colección de referencia ni benchmark antes/después; no se afirma mejora de velocidad.

## Vista previa y exportación

| Comando | Descripción |
|---------|-------------|
| `python facet.py /path --dry-run` | Puntúa 10 fotos de muestra sin guardar |
| `python facet.py /path --dry-run --dry-run-count 20` | Puntúa 20 fotos de muestra |
| `python facet.py --export-csv` | Exporta todas las puntuaciones a un CSV con marca de tiempo |
| `python facet.py --export-csv output.csv` | Exporta a un archivo CSV específico |
| `python facet.py --export-json` | Exporta todas las métricas almacenadas a un JSON con marca de tiempo |
| `python facet.py --export-json output.json` | Exporta a un archivo JSON específico |
| `python facet.py --export-manifest` | Escribe `facet_manifest.json` para herramientas externas, como el plugin de Lightroom Classic |
| `python facet.py --export-manifest /path` | Limita el manifiesto a las fotos bajo una ruta |
| `python facet.py --export-manifest --user alice` | Modo multiusuario: usa las valoraciones de Alice (las etiquetas y puntuaciones siguen siendo globales) |
| `python facet.py --import-lightroom FILE` | Importa las valoraciones, picks y rechazos del plugin; gana Lightroom |
| `python facet.py --import-lightroom FILE --user alice` | Modo multiusuario: escribe las valoraciones de Alice; **obligatorio** en una instalación multiusuario |
| `python facet.py --import-sidecars` | Importa valoraciones, etiquetas de color, Keep/rechazo, GPS manual y palabras clave desde sidecars XMP |
| `python facet.py --import-sidecars /path` | Importa solo para las fotos bajo una ruta |
| `python facet.py --import-sidecars /path --dry-run` | Muestra un plan JSON de cambios y conflictos; no escribe nada |
| `python facet.py --import-sidecars /path --sidecar-fields keywords,gps` | Importa solo estos grupos: `review` (estrellas, favorito, rechazo, Keep), `gps`, `keywords` (por defecto: todos) |
| `python facet.py --import-sidecars /path --overwrite-sidecar-review` | Aplica los campos de revisión incluso sobre una edición local más reciente (`newer_local_edit`); revisa antes con `--dry-run` |
| `python facet.py --import-sidecars --user alice` | Modo multiusuario: importa valoraciones y Keep/rechazo a la cuenta de Alice, para las fotos que ella ve |
| `python facet.py --import-sidecars --sidecar-naming full` | Lee `<image.ext>.xmp` / `<image.ext>.facet.xmp` (por defecto); gana el archivo más reciente |
| `python facet.py --import-sidecars --sidecar-naming basename` | Lee `<image>.xmp` (sin la extensión); rechaza los nombres base compartidos |
| `python facet.py --import-sidecars --sidecar-naming auto` | Acepta cualquiera de los dos nombres; omite la foto que tiene ambos |
| `python facet.py --import-sidecars --overwrite-manual-gps` | Sustituye el GPS manual ya definido en Facet por el del sidecar |
| `python facet.py --export-sidecars` | Escribe o fusiona sidecars `<image>.xmp` para todas las fotos |
| `python facet.py --export-sidecars /path --reconcile-keywords` | Elimina además las palabras clave de Facet que ya no existen (requiere ExifTool) |
| `python facet.py --export-sidecars /path` | Exporta sidecars solo para las fotos bajo una ruta |
| `python facet.py --export-sidecars --user alice` | Modo multiusuario: exporta las valoraciones y Keep/rechazo de Alice, para las fotos que ella ve |
| `python facet.py --export-sidecars --embed-originals` | Escribe además los metadatos **dentro** de los originales JPEG/HEIC/TIFF/PNG/DNG |
| `python facet.py --export-sidecars --score-to-stars` | Define `xmp:Rating` a partir de la puntuación para las fotos que no has valorado |

**Simulación (dry run).** En `16gb`/`24gb` la columna de estética muestra `n/a`, porque TOPIQ solo se ejecuta en un escaneo real (el modo comercial muestra la puntuación de Q-ReAlign). El agregado la cuenta como un 5,0 neutro.

**CSV y JSON.** La columna `tags` contiene solo los tags de IA; los [tags manuales](VIEWER.md#tags-manuales) no se incluyen. En el JSON, el objeto `scores` de cada foto contiene todas las métricas almacenadas; NULL, los números no finitos y los BLOB pasan a `null`. La exportación JSON se niega a escribir sobre la base de datos o sus archivos `-wal`/`-shm`/`-journal`.

**Manifiesto.**

- El argumento opcional limita *qué fotos* se exportan. El archivo es siempre `facet_manifest.json` en el directorio de trabajo.
- Lleva `star_rating`/`is_favorite`/`is_rejected` (globales, o los del `--user`), `is_burst_lead`, tags de IA más manuales, y un recuento `pending_corrections`. Un recuento distinto de cero imprime un aviso que remite a `--detect-panoramas`.
- _manifiesto versión 2_ añade `burst_group_id`, `sequence_kind`, `sequence_group_id` y `score_stars` (la puntuación convertida mediante `xmp_export.score_to_rating`). Un plugin compilado para esta versión rechaza un manifiesto más antiguo: reexporta. Ver [el plugin de Facet](INTEROP.md#el-plugin-de-facet-valoraciones-marcas-pick-campos-de-metadatos-y-palabras-clave).

**`--import-lightroom`** lee la exportación propia del plugin, `facet_lightroom_state.json` (`{"format":"facet-lightroom-state","version":1,"photos":[...]}`), no el manifiesto. Un archivo con formato incorrecto se rechaza antes de escribir nada. El valor de Lightroom gana para cada campo que lleve el archivo; los campos omitidos conservan el valor de Facet. Imprime `matched=… unmatched=… changed=…`. Ver [Lightroom → Facet](INTEROP.md#lightroom--facet).

**Sincronización bidireccional de metadatos.** Facet escribe valoraciones, etiquetas de color, palabras clave, leyendas y regiones de rostros con nombre en un sidecar `<image>.xmp` estándar que leen Lightroom, darktable, digiKam, immich y otros.

- Los originales nunca se modifican a menos que añadas `--embed-originals` (solo JPEG/HEIC/TIFF/PNG/DNG; los RAW nunca se tocan).
- Las palabras clave son los tags de IA más tus [tags manuales](VIEWER.md#tags-manuales). Solo se añaden, salvo que `--reconcile-keywords` elimine las que Facet escribió antes; las palabras clave ajenas se conservan. Ver [Tags manuales y palabras clave XMP](INTEROP.md#tags-manuales-y-palabras-clave-xmp).
- La incrustación y la fusión de palabras clave requieren **exiftool**. Sin él, Facet escribe un sidecar XML simple.

**Importación de sidecars.**

- Las palabras clave importadas pasan a ser [tags manuales](INTEROP.md#tags-manuales-y-palabras-clave-xmp); no hace falta `--migrate-tags`.
- Una decisión de Facet (Keep, rechazo o indeciso) sin valoración ni etiqueta de color estándar se aplica sin la comprobación de la fecha de escaneo.
- Con `--user`, las palabras clave y el GPS siguen siendo globales. Con `--export-sidecars --user`, las palabras clave, el GPS y la fecha de captura siguen siendo globales.
- Cómo se compara un sidecar con las ediciones locales: [Vista previa de importación y conflictos](INTEROP.md#vista-previa-de-importación-de-sidecars-y-conflictos-de-revisión).

### Sincronización con Immich

Envía las valoraciones y favoritos de Facet a un servidor [Immich](https://immich.app/) (unidireccional, Facet → Immich, solo API REST). Los recursos se resuelven por `originalPath` mediante las asignaciones de prefijo de ruta del bloque de configuración `immich`.

| Comando | Descripción |
|---------|-------------|
| `python facet.py --immich-test` | Comprueba la conexión y la clave de API (`immich.url` + `immich.api_key`, enviada como `x-api-key`) |
| `python facet.py --immich-sync` | Envía las valoraciones por estrellas (1–5) y los favoritos; respeta `--dry-run` y `--user` |
| `python facet.py --immich-sync --dry-run` | Informa de lo que cambiaría sin escribir |

Solo se envían las valoraciones 1–5 (nunca 0/−1). Un álbum opcional de mejores fotos recopila las fotos por encima de un umbral de valoración. Ver [Configuración — Sincronización con Immich](CONFIGURATION.md#sincronización-con-immich).

### Planes de pilas Immich

Aceptan `--config`, `--db` y `--user`; el modo multiusuario necesita un propietario existente. La vista previa nunca escribe. Aplicar requiere el resumen del plan revisado.

| CLI | |
|---|---|
| `python facet.py --immich-stacks-plan import --stack-plan-out NEW_JSON` | Previsualizar pilas remotas para importarlas |
| `python facet.py --immich-stacks-plan push --stack-id UUID --stack-plan-out NEW_JSON` | Previsualizar pilas locales para crearlas a distancia |
| `python facet.py --immich-stacks-apply PLAN_JSON --ack-stack-plan SHA256` | Aplicar el plan revisado |

- Repite `--stack-id UUID` para elegir los grupos de origen.
- `--stack-plan-out NEW_JSON` escribe un archivo privado nuevo (POSIX `0600`) y nunca sobrescribe uno existente. En Windows, elige una carpeta cuya ACL limite el acceso a tu cuenta.
- Límites: 1000 grupos, 1000 miembros por grupo, 20000 miembros en total, 16 MiB.
- Los mapas incompletos y los solapamientos omiten el grupo entero. Los grupos existentes nunca se actualizan.

Ver [permisos, conflictos y límites de concurrencia remota](IMMICH.md#importar-y-enviar-pilas-manuales).

## Operaciones de recálculo

Estos comandos actualizan métricas o derivan datos nuevos sin volver a ejecutar el pipeline completo de puntuación. La mayoría reutilizan las miniaturas y puntos de referencia almacenados y son ligeros para la CPU; las filas de IA (como `--generate-captions`) necesitan una GPU.

| Comando | Descripción |
|---------|-------------|
| `python facet.py --recompute-average` | Recalcula las puntuaciones agregadas y las categorías a partir de las métricas almacenadas (no se vuelve a leer ninguna imagen) |
| `python facet.py --recompute-category portrait` | Recalcula las puntuaciones de una sola categoría |
| `python facet.py --tag-untagged` | Etiqueta solo las fotos que aún no tienen etiquetas, a partir de los embeddings almacenados |
| `python facet.py --recompute-tags` | Vuelve a etiquetar todas las fotos con el modelo configurado |
| `python facet.py --recompute-tags-vlm` | Vuelve a etiquetar todas las fotos con el etiquetador VLM |
| `python facet.py --detect-moments` | Etiqueta las fotos nuevas con su momento narrativo (se ejecuta tras cada escaneo) |
| `python facet.py --recompute-moments` | Vuelve a etiquetar los momentos narrativos de toda la biblioteca |
| `python facet.py --discover-moments` | Propone un vocabulario de momentos a partir de tus leyendas en `scoring_config.discovered.json` |
| `python facet.py --detect-junk` | Marca capturas de pantalla, documentos, recibos, memes y diapositivas (se ejecuta tras cada escaneo) |
| `python facet.py --recompute-junk` | Reevalúa `junk_kind` para toda la biblioteca |
| `python facet.py --recompute-saliency` | `[GPU]` Recalcula la saliencia del sujeto desde las miniaturas almacenadas; `--force` lo rehace todo |
| `python facet.py --recompute-composition-cpu` | Recalcula la composición, basada en reglas (CPU, cualquier perfil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recalcula la composición con SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` Rellena las puntuaciones TOPIQ IAA, NR-Face y LIQE que faltan desde las miniaturas almacenadas. Funciona en todos los perfiles; en CPU (`legacy`) es mucho más lento |
| `python facet.py --detect-text` | Lee el texto presente en la imagen en `ocr_text` para que la búsqueda lo encuentre (opcional, ver nota) |
| `python facet.py --recompute-text` | Vuelve a ejecutar el OCR sobre toda la biblioteca |
| `python facet.py --recompute-colors` | Extrae el tono dominante y la temperatura cálida/fría a `dominant_hue` / `color_temp` (CPU, rápido) |
| `python facet.py --recompute-form` | Recalcula simetría, equilibrio, entropía de bordes, complejidad fractal y armonía cromática (CPU) |
| `python facet.py --recompute-skin-tone` | Recalcula la naturalidad del tono de piel en retratos (CPU; solo una nota informativa en la crítica) |
| `python facet.py --recompute-distortions` | Etiqueta las distorsiones probables (desenfoque por movimiento, dominante de color, …) y las correlaciona con `liqe_score` / `noise_sigma` (informativo) |
| `python facet.py --upgrade-db` | Migra el esquema y ejecuta la cadena completa de relleno (ver nota) |
| `python facet.py --recompute-blinks` | Recalcula la detección de parpadeo a partir de los puntos de referencia almacenados (CPU, rápido) |
| `python facet.py --recompute-eyes-expression` | Recalcula las puntuaciones de ojos abiertos + expresión a partir de los puntos de referencia almacenados (CPU, rápido) |
| `python facet.py --recompute-face-signals` | Rellena las puntuaciones de ojos abiertos + sonrisa por cara a partir de los puntos de referencia almacenados (CPU, rápido) |
| `python facet.py --recompute-burst` | Recalcula los grupos de ráfaga (registra `Burst state: N rows changed`) |
| `python facet.py --detect-sequences` | Detecta bracketings de exposición y panorámicas (se ejecuta tras cada escaneo; ver nota) |
| `python facet.py --detect-panoramas` | Detecta panorámicas desde las miniaturas almacenadas (ejecuta primero la pasada de bracketing; CPU) |
| `python facet.py --detect-duplicates` | Detecta fotos duplicadas mediante pHash (registra `Duplicate state: N rows changed`) |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Evalúa los umbrales de coseno de casi-duplicados (precisión/exhaustividad con etiquetas) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Genera leyendas de IA con el VLM |
| `python facet.py --translate-captions` | Traduce las leyendas en inglés al idioma configurado (CPU, MarianMT) |
| `python facet.py --extract-gps` | Copia el GPS del EXIF a la base de datos; omite las ubicaciones definidas en el visor |
| `python facet.py --rescan-gps` | Vuelve a extraer el GPS del EXIF para todas las fotos (sobrescribe); omite las ubicaciones definidas en el visor |
| `python facet.py --recompute-embeddings` | Recalcula los embeddings CLIP/SigLIP para todas las fotos (necesario tras cambiar de modelo) |
| `python facet.py --score-topiq` | `[GPU]` Vuelve a puntuar `topiq_score` para cada foto con miniatura (sobrescribe) |
| `python facet.py --backfill-focal-35mm` | Rellena la distancia focal equivalente a 35 mm desde el EXIF donde falta |
| `python facet.py --backfill-clipping` | Deriva los porcentajes de recorte por canal a partir de los histogramas almacenados (reanudable) |
| `python facet.py --recompute-silhouette` | Vuelve a derivar `is_silhouette` con la regla basada en el rostro (ver nota) |
| `python facet.py --repair-int-columns` | Redondea los valores fraccionarios que una herramienta EXIF externa guardó en columnas enteras (como ISO) |
| `python facet.py --repair-neutral-iqa` | Borra los falsos 5,0 neutros de IQA guardados antes de la 1.20 (ver nota) |
| `python facet.py --compute-recommendations` | Analiza la base de datos y muestra un resumen de puntuación |
| `python facet.py --compute-recommendations --verbose` | Muestra estadísticas detalladas |
| `python facet.py --compute-recommendations --apply-recommendations` | Aplica automáticamente las correcciones de puntuación |
| `python facet.py --compute-recommendations --simulate` | Previsualiza los cambios proyectados |

**`--recompute-average`** no guarda ninguna instantánea: para revertir, restaura una instantánea de pesos y recalcula. Tras actualizar desde la 1.20 o anterior, ejecuta primero `--recompute-silhouette` y después `--recompute-average` dos veces. La primera pasada guarda los nuevos percentiles, así que la segunda aún cambia algunas filas.

**Momentos.**

- `--detect-moments` codifica cada leyenda nueva una sola vez en `caption_embedding`. Conviene hacer el primer relleno de una biblioteca existente en una GPU; añade `--limit N` para probarlo en una muestra.
- Añade `--dry-run --verbose` a `--recompute-moments` (o `--detect-junk`) para previsualizar sin escribir.
- `narrative_moments.vlm_tiebreak` (16gb/24gb): cuando `narrative_moments.vlm_tiebreak.enabled` está activado, el VLM del perfil reclasifica los fotogramas de baja confianza.
- `--discover-moments` agrupa los embeddings de leyenda almacenados y nombra cada grupo. Nunca reescribe la configuración activa. Ejecuta primero `--detect-moments`; ajústalo con `--discover-min-cluster-size N`.
- `--generate-captions` omite las fotos sin etiquetar, `other` y de baja confianza cuando `narrative_moments.caption_min_confidence > 0`.

**Basura.** Las fotos limpias se marcan como `not_junk`, así que las ejecuciones posteriores solo comprueban las nuevas.

**`--detect-text`** es opcional: necesita `ocr.enabled` en `scoring_config.json` y `pip install easyocr`. Ver [Configuración — OCR](CONFIGURATION.md#ocr).

**`--detect-sequences`** encuentra bracketings de exposición a partir del EXIF y luego panorámicas a partir de la geometría de las miniaturas, y coloca la principal de cada ráfaga en su exposición base. También se ejecuta en `--upgrade-db`. Las vistas de descarte **Horquillados de exposición** / **Panorámicas** / **Panorámicas HDR** del visor y los interruptores `hide_brackets` / `hide_panoramas` no hacen nada hasta que se ha ejecutado. Cada ejecución vuelve a etiquetar toda la biblioteca, así que repetirla (o `--detect-panoramas`) elige un nuevo fotograma representativo tras descartar el anterior.

**`--upgrade-db`** migra el esquema y ejecuta: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, eyes-expression, face-signals, average. Es seguro repetirlo y omite los pasos pesados como la generación de leyendas. También endereza las miniaturas HEIF que pillow-heif 1.6 dejó giradas, junto con sus rostros; nunca se escriben los archivos originales. Los archivos HEIF que no puede leer se reintentan en la siguiente ejecución.

**`--recompute-silhouette`** lee solo la base de datos, confirma por lotes y respeta `--dry-run`.

- El informe agrupa las fotos según cómo encajan sus cuadros de rostros con la miniatura: `exact`, `scaled`, `count_mismatch` (emparejamiento no validado), `other`.
- Una foto sin rostros, o cuyos cuadros no se pueden ubicar, se escribe como 0.
- Las fotos con `face_count` NULL, o con rostros pero sin miniatura, se dejan como están (`skipped_face_count_null` / `skipped_no_thumbnail`).
- Ejecuta después `--recompute-average`. Ver [SCORING.md](SCORING.md).

**`--repair-int-columns`** lee solo la base de datos. La galería los muestra correctamente sin él, pero los filtros de rango y las ordenaciones usan el valor almacenado, así que una foto mostrada como ISO 63 puede quedar fuera. Los valores que no pueden ser enteros pasan a NULL.

**`--repair-neutral-iqa`** pone a NULL todo valor exactamente igual a 5,0 en `aesthetic_iaa`, `face_quality_iqa` y `liqe_score`, e imprime el recuento por columna.

- No toca `aesthetic`, `topiq_score`, `aesthetic_v25` ni `quality_score`.
- Un valor genuino de exactamente 5,00 también se borra; `--recompute-iqa` lo rellena, posiblemente con una ligera diferencia.
- Ejecuta después `--recompute-iqa` y `--recompute-average`.
- Se rechaza con `--dry-run` (código de salida 2). No forma parte de `--upgrade-db`. Recarga las páginas de la galería abiertas para ver los nuevos rangos de filtro.

### Modelos de calidad suplementarios

Tres modelos PyIQA puntúan más allá de la estética principal de TOPIQ. Comparten VRAM con TOPIQ y se ejecutan en el escaneo multipaso por defecto.

- **TOPIQ IAA** (`--pass quality-iaa`): mérito artístico entrenado con AVA, independiente de la calidad técnica. Se almacena como `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): calidad de la región facial. Se almacena como `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): puntuación de calidad más un diagnóstico de distorsión (desenfoque por movimiento, sobreexposición, ruido). Se almacena como `liqe_score`.

Cuando un modelo no puede puntuar una foto:

- Guarda NULL, no un 5,0 neutro. Un error de memoria agotada de la GPU se reintenta primero con la mitad del tamaño de lote, hasta una sola imagen.
- LIQE omite las miniaturas cuyo lado corto es inferior a 224 px (tras limitar el lado largo a 1024 px).
- NR-Face omite las fotos con `face_count` 0. Una foto en la que no encuentra ningún rostro se recuerda en `iqa_declined` hasta un reescaneo (`--force`), `--refresh-thumbnails` o `--fix-thumbnail-rotation`. Actualizar pyiqa no la borra.
- Los demás fallos no se guardan; el siguiente `--recompute-iqa` lo vuelve a intentar.
- Con `--pass quality`, `quality-iaa`, `quality-face` y `quality-liqe`, una foto que falla conserva su valor guardado.
- Un escaneo completo registra una foto cuyo modelo TOPIQ falla, para `--retry-failed`; `--pass quality` no lo hace.

`--recompute-iqa` solo rellena las columnas NULL y nunca sustituye un valor guardado, incluido un 5,0 neutro de una versión anterior. Bórralos con `--repair-neutral-iqa` y ejecuta después `--recompute-iqa` y `--recompute-average`, o reescanea con `--force`. Ver [Dimensiones IQA complementarias](SCORING.md#dimensiones-iqa-complementarias).

### Benchmarks y puntuaciones suplementarias

| Comando | Descripción |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Rellena `aesthetic_clip` desde los embeddings en caché (sin inferencia de imagen; no forma parte del `aggregate` por defecto). Ver [SCORING.md](SCORING.md#señales-complementarias-no-en-el-agregado-predeterminado) |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcula SRCC + PLCC frente a la verdad de referencia de AVA para cada columna de puntuación |

### Saliencia del sujeto

`--pass saliency` y `--recompute-saliency` usan BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, mediante `transformers`, ~3 GB de VRAM) para encontrar el sujeto y luego derivan cuatro métricas:

- **Nitidez del sujeto**: si el sujeto está enfocado (varianza laplaciana, sujeto frente al fondo).
- **Prominencia del sujeto**: área del sujeto / área del encuadre. Alta para un sujeto dominante (p. ej., macro).
- **Ubicación del sujeto**: puntuación de la regla de los tercios para el centroide del sujeto.
- **Separación del fondo**: contraste de bordes entre el sujeto y el fondo (calidad del bokeh).

La saliencia se ejecuta en todos los perfiles; `legacy` la ejecuta en CPU, más lento. `--recompute-saliency` funciona con el volumen de la biblioteca sin conexión y es reanudable. En CUDA, el tamaño de lote sigue la VRAM libre (unos 2,4 GiB por imagen a 1024 px, entre 1 y 8 imágenes) y se reduce a la mitad tras un error de memoria agotada.

- **Una foto que falla** se registra como ERROR y no se escribe nada. Una foto nunca puntuada sigue en NULL y la recoge el siguiente `--recompute-saliency`; una que ya tenía saliencia conserva sus valores, incluso con `--recompute-saliency --force`. Un reescaneo completo (por ejemplo `python facet.py --force`) guarda NULL para ella.
- **Una foto sin sujeto** guarda NULL en nitidez, ubicación y separación, prominencia 0,0 y un `subject_bbox` NULL (y un `power_point_score` NULL desde el paso de composición). Es un resultado final; no se vuelve a medir.
- **Las filas antiguas** guardaban en su lugar un 5,0 neutro. `--recompute-saliency` y `--recompute-composition-cpu` las reescriben. `--recompute-saliency` también recoge las fotos puntuadas antes de que existiera `subject_bbox`.
- Una métrica opcional NULL se excluye del agregado y su peso se redistribuye entre las métricas presentes; solo si faltan todas, el agregado usa el valor neutro 5.0. Ver [Sistema de puntuación](SCORING.md).

### Modelos de etiquetado

El modelo de etiquetado depende del perfil de VRAM:

| Perfil | Modelo | Cómo funciona |
|---------|-------|-------------|
| `legacy` | Similitud CLIP | Similitud de coseno entre los embeddings de la imagen y del texto de las etiquetas. Sin modelo adicional. |
| `8gb` | Similitud CLIP | Igual que legacy, sobre los embeddings CLIP ViT-L-14 almacenados. |
| `16gb` | Qwen3.5-2B | Modelo multimodal para el etiquetado de escenas. |
| `24gb` | Qwen3.5-4B | Modelo multimodal más grande. |

Todos los etiquetadores asignan su salida al vocabulario de etiquetas configurado. Usa `--recompute-tags` para volver a etiquetar con el modelo del perfil, o `--recompute-tags-vlm` para el VLM.

**Cuándo se escriben las etiquetas.** En los perfiles de similitud CLIP (`legacy`/`8gb`, y `16gb`/`24gb` cuando no está programada la pasada VLM), un escaneo multipaso etiqueta durante la pasada de embeddings, así que la categoría y el agregado del escaneo ya las usan. Una ejecución con un solo `--pass` (por ejemplo `--pass embeddings`) no escribe etiquetas. `--pass tags` en un perfil CLIP se detiene y remite a `--recompute-tags`. Las filas existentes conservan su categoría hasta `--recompute-average`.

### Modelos de embeddings

Dos modelos de embeddings, seleccionados según el perfil de VRAM mediante `clip_config`:

| Configuración | Modelo | Dimensiones | Usado por |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | perfiles 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | perfiles legacy, 8gb |

Los embeddings impulsan el etiquetado, la detección de duplicados, la búsqueda de fotos similares y la estética CLIP+MLP (legacy/8gb). Cambiar de modelo requiere volver a generar los embeddings de todas las fotos (`--force`, `--pass embeddings` o `--recompute-embeddings`).

## Reconocimiento facial

| Comando | Descripción |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extrae rostros de las fotos nuevas (GPU, en paralelo) |
| `python facet.py --extract-faces-gpu-force` | Elimina todos los rostros y vuelve a extraerlos (GPU; las personas con nombre se conservan; extractor permisivo en modo comercial) |
| `python facet.py --cluster-faces-incremental` | Agrupación HDBSCAN, conserva todas las personas (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Agrupación, conserva solo las personas con nombre (CPU) |
| `python facet.py --cluster-faces-force` | Reagrupación completa, elimina todas las personas (CPU) |
| `python facet.py --suggest-person-merges` | Sugiere posibles fusiones de personas |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Usa un umbral más estricto |
| `python facet.py --refill-face-thumbnails-incremental` | Genera las miniaturas de rostro que faltan (CPU, en paralelo) |
| `python facet.py --refill-face-thumbnails-force` | Regenera TODAS las miniaturas de rostro (CPU, en paralelo) |

## Gestión de miniaturas

| Comando | Descripción |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Rota las miniaturas almacenadas para que coincidan con la orientación EXIF |
| `python facet.py --refresh-thumbnails` | Reconstruye las miniaturas RAW a partir de la vista previa incorporada de la cámara |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | Lo mismo, con más lecturas en paralelo |

**`--fix-thumbnail-rotation`** es para fotos procesadas antes de que se tuviera en cuenta la orientación EXIF. Solo lee la cabecera EXIF y la miniatura almacenada.

**`--refresh-thumbnails`** vuelve a renderizar la miniatura almacenada de cada foto RAW a través del perfil de visualización (primero la vista previa de la cámara, con el demosaicado como respaldo; ver [CONFIGURATION.md](CONFIGURATION.md#decodificación-raw)). Úsalo en una biblioteca escaneada antes de que existiera ese perfil: las miniaturas antiguas aplanan las diferencias de exposición entre los fotogramas de un bracketing. No carga ningún modelo y no cambia ninguna puntuación.

- **La velocidad** depende del rendimiento del disco o de la red, no de la CPU. `--refresh-thumbnails-workers` (8 por defecto) define cuántos archivos se leen a la vez: auméntalo en un montaje de red rápido y redúcelo en un disco local lento. Valores muy altos cuestan memoria.
- **Es reanudable.** Detenlo con Ctrl-C y la siguiente ejecución continúa donde se quedó. Una ejecución completada empieza de nuevo la próxima vez.
- **Los renderizados negros** (por ejemplo, de un RAW truncado) se descartan: la foto conserva su miniatura anterior, se registra por su nombre y se reintenta en la siguiente ejecución.
- **Los fotogramas de un bracketing** se renderizan sin la vista previa de la cámara ni ganancia de exposición, de modo que cada miniatura muestra lo que registró el sensor (ver [CONFIGURATION.md](CONFIGURATION.md#las-tomas-de-un-horquillado-se-representan-sin-corrección)). Ejecútalo después de `--detect-sequences`.

### Qué actualiza una miniatura almacenada

Las miniaturas se generan en el momento del escaneo, así que una biblioteca escaneada antes de que existiera el perfil de visualización conserva el renderizado antiguo en la cuadrícula de la galería. Dos caminos las actualizan:

| Camino | Cubre | Coste |
|------|--------|------|
| Un nuevo escaneo (`python facet.py <directorio>`) | Todo lo que escanea, miniatura e histograma | Escaneo completo |
| `--refresh-thumbnails` | La miniatura de cada fila RAW | Limitado por el almacenamiento, horas en una biblioteca grande |

**Nada ocurre por sí solo.** La vista de detalle siempre se renderiza de nuevo, pero la cuadrícula de la galería muestra la miniatura almacenada. Un banner descartable cuenta las filas que aún esperan. Su recuento puede ir hasta una hora por detrás tras un reescaneo; `--refresh-thumbnails` y `python database.py --refresh-stats` lo actualizan.

## Diagnóstico

| Comando | Descripción |
|---------|-------------|
| `python facet.py --doctor` | Ejecuta comprobaciones de diagnóstico (Python, GPU, ONNX Runtime, dependencias, configuración, base de datos) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simula hardware de GPU para el diagnóstico |

`--doctor` informa de la versión de Python, la compilación de PyTorch/CUDA, la GPU y el controlador, la compilación y los proveedores de ONNX Runtime, el perfil de VRAM recomendado, las dependencias opcionales y el estado de la configuración y la base de datos. En CUDA también prueba la carga de ONNX Runtime en la GPU. Cuando PyTorch u ONNX Runtime son la compilación equivocada, imprime el comando `pip install` que lo corrige (ver [ONNX Runtime para la detección de rostros](INSTALLATION.md#onnx-runtime-para-la-detección-de-rostros)).

`--simulate-gpu NAME` y `--simulate-vram GB` requieren `--doctor`; `--simulate-vram` requiere además `--simulate-gpu`.

| Comando | Descripción |
|---------|-------------|
| `python facet.py --check-raw-rendering` | Renderiza 20 fotos RAW muestreadas con los ajustes de decodificación antiguos y actuales |
| `python facet.py --check-raw-rendering 50` | Muestrea 50 fotos en su lugar |

Solo lectura. Imprime el brillo medio de cada renderizado: el brillo automático de LibRaw, el demosaicado de ganancia fija y la vista previa de la cámara. Úsalo para comprobar `raw_decode.bright` en tus archivos antes de un escaneo o de `--refresh-thumbnails`. Las columnas fija y vista previa conservan los pasos de exposición de un bracketing; el brillo automático los aplana.

## Información de modelos

| Comando | Descripción |
|---------|-------------|
| `python facet.py --list-models` | Muestra los modelos disponibles y los requisitos de VRAM |

## Optimización de pesos (comparación por pares)

| Comando | Descripción |
|---------|-------------|
| `python facet.py --comparison-stats` | Muestra las estadísticas de comparación por pares |
| `python facet.py --optimize-weights` | Optimiza los pesos a partir de tus comparaciones; solo se aplican si superan una prueba con datos reservados (ver nota) |
| `python facet.py --optimize-weights --optimize-force` | Aplica los pesos optimizados aunque no superen la prueba |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Entrena solo con estas fuentes de comparación |
| `python facet.py --optimize-weights --optimize-category portrait` | Entrena una categoría y escribe su bloque `categories[].weights` v4 |
| `python facet.py --auto-tune-categories` | **Solo superadministrador** (`--user` en modo multiusuario): informa la disponibilidad de etiquetas por categoría (solo informe) |
| `python facet.py --sync-label-comparisons` | Reconstruye los pares derivados de valoraciones (source=rating) a partir de estrellas, favoritos y rechazos |
| `python facet.py --train-ranker` | Entrena el clasificador personal y escribe learned_scores si supera al agregado |
| `python facet.py --train-ranker --ranker-category portrait` | Entrena el clasificador en una sola categoría |
| `python facet.py --train-ranker --train-ranker-force` | Escribe learned_scores aunque no se cumpla el umbral de precisión |
| `python facet.py --train-ranker --user alice` | Entrena con las comparaciones de ese usuario y escribe sus learned_scores (modo multiusuario) |
| `python facet.py --train-keeper` | Entrena la **cabeza de clasificación de conservación** (keeper-ranking) a partir de tus decisiones de descarte (ver nota) |
| `python facet.py --train-keeper --train-keeper-force` | Conserva la cabeza aunque no pase su umbral (también respeta `--ranker-category` y `--user`) |
| `python facet.py --report-unreviewed-bursts` | Cuenta los grupos de ráfaga aún sin revisar (solo lectura) |
| `python facet.py --eval-iqa-srcc` | Informa de cuánto coincide cada métrica IQA/estética con tus valoraciones por estrellas (SRCC; solo lectura) |
| `python facet.py --evaluate-models SLOT` | Clasifica los modelos candidatos de un slot según su coincidencia con tus elecciones (solo lectura; ver nota) |
| `python facet.py --mine-insights` | Informe sobre etiquetas, correlaciones de métricas, categorías, deriva de percentiles y comparaciones |
| `python facet.py --mine-insights report.json` | Lo mismo, y escribe el informe completo en JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Calibra los pesos de categoría frente al [conjunto de datos AVA](https://github.com/imfing/ava_downloader) (solo lectura; imprime propuestas) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Limita a estas categorías y escribe los pesos en `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Elige el optimizador (`de` = evolución diferencial, por defecto; `nelder-mead` = símplex local) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Usa también las etiquetas de AVA (`--ava-tags-only` solo para etiquetas; `--apply-filters` para ajustar los umbrales de los filtros) |

**`--optimize-weights`** entrena con todas las fuentes de comparación, ponderadas por fiabilidad. Los pesos nuevos solo se aplican si superan a los actuales en comparaciones reservadas (validación cruzada de 5 particiones, prueba de McNemar unilateral, p < 0.05, ganancia de al menos 2 puntos porcentuales). Al aplicar también se recentra el `modifiers.bonus` de la categoría, de modo que sus fotos se reordenan en lugar de subir o bajar todas. Ver [SCORING.md](SCORING.md).

**`--train-keeper`** aprende de los pares `source='culling'` y solo se conserva si supera a la heurística del descarte automático con datos reservados. Mejora las selecciones del descarte automático y alimenta la insignia "existe una foto mejor en este grupo". Hasta que haya suficientes pares de descarte, se usa la heurística. Se reentrena con el mismo disparador que `--train-ranker`.

**`--evaluate-models SLOT`** slots: `aesthetic`, `quality`, `faces-detect`, `faces-recognize`, `faces-centroid`, `blink`, `face-quality`, `end-to-end`.

- `--candidates a,b` elige los candidatos (`stored:<columna>` o un nombre registrado).
- `--eval-out PATH` define la salida (por defecto `.facet_cache/eval/<slot>-<marca de tiempo>.json`).
- Los slots de rostros comparan con los rostros InsightFace almacenados en lugar de con tus elecciones, así que solo sirven para bibliotecas en modo predeterminado: `faces-detect` (`yunet`, `yunet@<conf>`, `blazeface`), `faces-recognize` (`sface`, `sface@<umbral>`), `faces-centroid` (ajusta el `merge_threshold` de SFace / la fusión automática), `blink` (barre el umbral de parpadeo permisivo).
- `--limit N` limita las fotos (por defecto 600) o los rostros de referencia (por defecto 1200).

## Configuración

`scoring_config.json` es una **anulación**: contiene solo los ajustes que has cambiado, sobre `config/scoring_config.default.json`. Sin archivo de configuración, Facet funciona con los valores predeterminados. Ver [Configuración](CONFIGURATION.md#valores-predeterminados-y-tu-anulación).

Qué archivo se lee:

1. `--config` siempre manda.
2. Si no, `FACET_CONFIG`, si está definida. Se aplica a `facet.py`, `database.py`, `tag_existing.py`, `diagnostics.py`, `calibrate.py` y `viewer.py`. `viewer.py` no tiene `--config`, así que es su única anulación.
3. Si no, para las herramientas CLI (no `viewer.py`), un `scoring_config.json` en el **directorio de trabajo**, de modo que una biblioteca puede llevar su propia configuración.
4. Si no, el archivo junto a la instalación. Si no existe, se aplican los valores predeterminados distribuidos.

Una ruta indicada con `--config` o `FACET_CONFIG` que no existe es un error, no "usar los valores predeterminados". El visor registra la ruta que falta y se niega a iniciarse en modo abierto.

> **Advertencia:** `viewer.py` nunca lee un `scoring_config.json` del directorio desde el que lo inicias. Si lo inicias desde una biblioteca y la raíz de la instalación no tiene configuración, funciona con los valores predeterminados: un `viewer.edition_password` vacío y ninguna contraseña del visor, de modo que cualquiera puede navegar.

```bash
# 1. --config manda sobre todo lo demás. Un archivo que falte es un error.
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. $FACET_CONFIG aporta el valor predeterminado si se omite --config (Docker lo define).
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # lee /config/scoring_config.json
python facet.py --config other.json /photos   # --config sigue anulándola

# 3. Ninguna de las dos: gana una configuración del DIRECTORIO DE TRABAJO para las herramientas CLI.
cd /photos/client-shoot          # contiene su propio scoring_config.json
python /opt/facet/facet.py .     # puntuado con /photos/client-shoot/scoring_config.json

# 4. Ninguna de las dos y aquí no hay nada: recurre a la configuración junto a la instalación.
cd /tmp
python /opt/facet/facet.py /photos   # lee /opt/facet/scoring_config.json
                                     # si falta allí = funciona con los valores predeterminados distribuidos

# 5. viewer.py nunca da el paso del directorio de trabajo.
cd /photos/client-shoot          # contiene su propio scoring_config.json -- irrelevante aquí
python /opt/facet/viewer.py      # sigue leyendo /opt/facet/scoring_config.json (o $FACET_CONFIG)
```

| Comando | Descripción |
|---------|-------------|
| `python facet.py --validate-categories` | Valida las configuraciones de categorías |

## Etiquetado

| Comando | Descripción |
|---------|-------------|
| `python tag_existing.py` | Etiqueta las fotos sin etiquetar a partir de los embeddings CLIP almacenados |
| `python tag_existing.py --dry-run` | Previsualiza las etiquetas sin guardar |
| `python tag_existing.py --threshold 0.25` | Umbral de similitud personalizado (por defecto: el `tag_threshold_percent` del perfil, distribuido como 8, es decir, 0.08) |
| `python tag_existing.py --max-tags 3` | Limita las etiquetas por foto (por defecto: 5) |
| `python tag_existing.py --force` | Vuelve a etiquetar todas las fotos |
| `python tag_existing.py --db custom.db` | Usa una base de datos personalizada |
| `python tag_existing.py --config my.json` | Usa una configuración personalizada |

En CUDA, los perfiles SigLIP (`16gb`, `24gb`) ahora codifican el vocabulario de etiquetas en fp16, lo que cambia las etiquetas de unas pocas fotos. Ejecuta `python tag_existing.py --force` para volver a etiquetar las fotos etiquetadas antes. La CPU y los perfiles `legacy`/`8gb` no cambian.

El paso de etiquetado al final de un escaneo se omite cuando `tagging.enabled` es `false` o ninguna foto está esperando etiquetas.

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
| `python database.py` | Inicializa o actualiza el esquema y construye los índices que falten (ver nota) |
| `python database.py --info` | Muestra información del esquema |
| `python database.py --migrate-tags` | Configuración única de la tabla de búsqueda de etiquetas (filtros de etiquetas 10-50x más rápidos) |
| `python database.py --rebuild-fts` | Reconstruye el índice de búsqueda de texto completo a partir de leyendas y etiquetas |
| `python database.py --populate-vec` | Rellena la tabla de búsqueda vectorial sqlite-vec a partir de los embeddings |
| `python database.py --refresh-stats` | Actualiza la caché de estadísticas |
| `python database.py --compact-config` | Elimina de `scoring_config.json` todo valor igual al predeterminado distribuido (toma antes una copia de seguridad en `0600`) |
| `python database.py --stats-info` | Muestra el estado y la antigüedad de la caché |
| `python database.py --vacuum` | Recupera espacio y desfragmenta |
| `python database.py --analyze` | Actualiza las estadísticas del planificador de consultas |
| `python database.py --optimize` | Ejecuta VACUUM y ANALYZE |
| `python database.py --backup` | Escribe una instantánea con marca de tiempo y segura para WAL (conserva `--keep N`, 3 por defecto) |
| `python database.py --export-viewer-db` | Exporta una base de datos ligera para el visor (sin BLOB, miniaturas más pequeñas; incremental) |
| `python database.py --export-viewer-db --force-export` | Fuerza una reexportación completa |
| `python database.py --cleanup-orphaned-persons` | Elimina las personas sin rostros |
| `python database.py --cleanup-missing-photos` | Elimina las fotos que ya no están en disco, con sus etiquetas, rostros y entradas de álbum |
| `python database.py --cleanup-missing-photos --dry-run` | Lista los archivos ausentes sin eliminar |
| `python database.py --cleanup-missing-photos --force` | Continúa aunque todas las fotos parezcan ausentes (ver advertencia) |
| `python database.py --relink-photos` | Actualiza las rutas de las fotos que has movido tú mismo (vista previa por defecto). Ver [Volver a vincular fotos movidas](#volver-a-vincular-fotos-movidas) |
| `python database.py --migrate-storage-fs` | Mueve las miniaturas y los embeddings de la base de datos al sistema de archivos |
| `python database.py --migrate-storage-db` | Mueve las miniaturas y los embeddings del sistema de archivos de vuelta a la base de datos |
| `python database.py --add-user alice --role admin` | Añade un usuario (solicita la contraseña) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Añade un usuario con nombre para mostrar |
| `python database.py --migrate-user-preferences --user alice` | Copia las valoraciones de photos a user_preferences |

**`python database.py`** también construye los índices de la galería que falten (ver [VIEWER.md](VIEWER.md#índices-de-la-galería-y-caché-de-recuentos)). En una biblioteca grande, ejecútalo una vez antes de iniciar el visor; puede tardar cerca de un minuto. De lo contrario, el visor los construye en segundo plano y rechaza los guardados mientras tanto.

**`--migrate-tags`** hace falta una sola vez. Después, los escaneos, `--recompute-tags`, `--recompute-tags-vlm` y `tag_existing.py` mantienen la tabla al día. Mientras no esté rellena, los filtros de etiquetas usan una búsqueda `LIKE` más lenta.

**`--cleanup-missing-photos`** también borra el índice vectorial y reinicia los contadores de comparaciones del reentrenamiento automático. El estado de la biblioteca, como los modelos entrenados, el estado de sincronización con Immich y la instantánea de percentiles, se conserva.

> **Advertencia:** sin `--force`, `--cleanup-missing-photos` se detiene cuando todas las fotos parecen ausentes, lo que suele significar que un volumen está desmontado. Comprueba el montaje antes de añadir `--force`.

**Consejo de rendimiento:** para bases de datos grandes (50k+ fotos), ejecuta `--migrate-tags`, `--rebuild-fts` y `--populate-vec` una vez, y luego `--optimize` de vez en cuando.

## Galería web

| Comando | Descripción |
|---------|-------------|
| `python viewer.py` | Inicia el servidor en http://localhost:5000 (API + SPA de Angular) |
| `python viewer.py --port 5001` | Vincula a un puerto diferente (o define la variable de entorno `PORT`; por defecto 5000) |
| `python viewer.py --host 127.0.0.1` | Vincula a una interfaz específica (por defecto `0.0.0.0`) |
| `python viewer.py --production` | Modo de producción (workers de uvicorn) |
| `python viewer.py --production --workers 4` | Modo de producción con N workers (por defecto 1) |

## Descarte desde la terminal

Descarte automático sin interfaz: la versión de terminal del [descarte automático](VIEWER.md#descarte-automático) de la galería. Los rechazos se escriben en la base de datos. Los originales nunca se mueven ni se eliminan; `--copy-keepers` copia las fotos conservadas a una carpeta.

| Comando | Descripción |
|---------|-------------|
| `python facet.py --auto-cull [PATH]` | Descarta las fotos que ya están en la base de datos bajo `PATH` (carpeta o archivo; sin argumento o `all` = toda la biblioteca). **Simulación por defecto** |
| `python facet.py /path --auto-cull` | Escanea `/path` y luego descarta las fotos que contiene |
| `--apply` | Escribe el descarte: rechazos, marcas de grupos revisados y pares de comparación `source='culling'` |
| `--copy-keepers DIR` | Copia en `DIR` cada foto no rechazada del ámbito, con sus acompañantes RAW / `.xmp` del mismo nombre |
| `--cull-strictness N` | Presupuesto de fotos conservadas de 0 a 100; más alto conserva menos por grupo (por defecto: `auto_cull.default_strictness`) |
| `--cull-min-keep N` | Mínimo de fotos conservadas por grupo (por defecto `1`) |
| `--cull-group-by {all,burst,similar,scene}` | Qué grupos descartar (por defecto `all`) |
| `--cull-min-score X` | Rechaza también las fotos sueltas cuya puntuación agregada sea inferior a `X` |
| `--cull-trim-brackets` | Rechaza también los fotogramas redundantes de los bracketings de exposición (el `trim_brackets` del visor) |
| `--user NAME` | De quién se usan las valoraciones y los rechazos; **obligatorio** en una instalación multiusuario |

- **Simulación por defecto.** Sin `--apply` no se escribe nada y la carpeta de `--copy-keepers` no se crea. El resumen lista `groups`, `kept`, `rejected_by_groups`, `rejected_by_score`, `spanning_skipped` y, con `--copy-keepers`, `keepers`, `copied`, `already_present`, `skipped`, `errors` (`would_reject_*` / `would_copy` en simulación). `--dry-run` se rechaza. Si un modelo de conservación entrenado necesita corregir sus pesos, cargarlo aún puede reescribir `scoring_config.json`.
- **Escanear y luego descartar** siempre escanea de verdad; el descarte solo se ejecuta si el escaneo terminó. No se puede combinar con `--auto-cull PATH`, `--resume`, `--retry-failed` ni `--watch`.
- **Reglas.** Las mismas que el [descarte automático del visor](VIEWER.md#descarte-automático): cada grupo conserva su mejor foto más todas las que caigan dentro del margen de rigor, con un mínimo de `--cull-min-keep`. Los bracketings, panorámicas y panorámicas HDR se conservan enteros. `--apply` marca las fotos conservadas como **Conservar** y registra pares de comparación como lo hace `POST /api/culling/auto`; no se rellena ningún álbum de Destacadas.
- **Configuración.** Los ajustes [`auto_cull`](CONFIGURATION.md#descarte-automático), `burst_scoring` y `similarity_groups` proceden de la configuración del **servidor** (`FACET_CONFIG` o la ruta por defecto), no de `--config`. Si ambas discrepan sobre el modo multiusuario, termina con código 1.
- **Ámbito.** Compara rutas reales locales, así que las filas guardadas antes de definir un `path_mapping` no se pueden limitar por carpeta: usa `all` o vuelve a escanear. Una ráfaga, un bracketing o una panorámica parcialmente fuera del ámbito se omite entera (`spanning_skipped`). Los grupos de similares y de escenas se calculan dentro del ámbito.
- **`--cull-min-score`** (solo CLI) nunca rechaza fotogramas de bracketing o panorámica, fotos sin puntuación, favoritas, con valoración o marcadas como **Conservar**, ni fotos que un descarte anterior ya juzgó, así que una segunda ejecución no rechaza nada nuevo. Siempre salva a los miembros de una ráfaga. Salva a los miembros de un grupo de similares cuando el agrupamiento los encontró (lee las `similarity_groups.max_photos` fotos más recientes del ámbito, `10000` por defecto, y descarta los grupos mayores que `similarity_groups.max_group_size`, `50` por defecto). Salva a los miembros de un grupo de escena solo con `--cull-group-by scene`.
- **Copia.** Las fotos rechazadas y sus acompañantes nunca se copian. Los archivos con el mismo nombre de carpetas distintas reciben el sufijo `_1`; una nueva ejecución omite los archivos idénticos (`already_present`). `DIR` no puede ser, contener ni estar dentro del ámbito, de la biblioteca ni de ninguna carpeta que Facet haya escaneado (código 1, también se comprueba en simulación). Los archivos deben estar dentro de la lista de carpetas de escaneo permitidas (`users.*.directories` / `viewer.scan_directories`); si por ello se omite toda foto, el comando termina con código 3.
- **Usuarios.** En una instalación multiusuario `--user` es obligatorio (código 1 sin él o con un usuario desconocido). En una instalación de un solo usuario `--user` se ignora con una advertencia, y el comando ve todas las fotos aunque haya una contraseña del visor. `--apply` toma el bloqueo de la biblioteca; una simulación no.
- **Errores de uso (código 2).** `--apply`, `--copy-keepers` o cualquier `--cull-*` sin `--auto-cull`; `--dry-run`, `--resume`, `--retry-failed` o `--watch` con `--auto-cull`; `--auto-cull PATH` con carpetas posicionales; rigor fuera de 0–100; `--cull-min-keep` menor que 1. `--apply` debe escribirse completo (ya no abrevia `--apply-recommendations`).
- **Códigos de salida.** `0` éxito (incluida una simulación o cero grupos); `1` fallo de requisito previo, configuración o base de datos; `2` error de uso; `75` el bloqueo de la biblioteca lo tiene otro trabajo; `3` el descarte funcionó pero la copia tuvo errores o no copió nada (una simulación en la que se omitiría toda foto conservada también termina con `3`).
- **Reentrenamiento.** No se ejecuta dentro de la CLI. El contador de comparaciones persiste, y el reentrenamiento se ejecuta en la siguiente acción del visor o con un comando `--train-*`. La primera ejecución puede crear `.facet_secret`.

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

### Descartar una sesión desde la terminal
```bash
python facet.py --auto-cull /photos/wedding                     # Vista previa del plan, no se escribe nada
python facet.py --auto-cull /photos/wedding --apply \
    --copy-keepers ~/wedding-keepers                             # Rechaza y luego copia las fotos conservadas
python facet.py /photos/new-shoot --auto-cull --apply --cull-min-score 5   # Escanea y luego descarta
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

## Volver a vincular fotos movidas

Tras mover los archivos tú mismo, `python database.py --relink-photos` previsualiza las asignaciones de ruta antigua → nueva y conserva los datos de cada foto en la base. La vista previa es el modo predeterminado.

- **Aplicar** requiere el ID del plan guardado y `--acknowledge-unverified-identity`, porque Facet no puede demostrar que el archivo nuevo sea el original. Detén los visores y escáneres y revisa antes el plan.
- **Se rechazan:** rutas fuera de tus raíces configuradas o de la visibilidad de usuarios, copias, nombres ambiguos, planes obsoletos y asignaciones de rutas.
- **Los acompañantes** deben indicarse explícitamente; los tipos incluyen `sidecar_facet` para `photo.ext.facet.xmp`. Los rectángulos manuales requieren revisión en el editor. El estado de Immich no cambia.
- **Los planes** se guardan de forma privada (0600 en POSIX).
- **Montajes:** una carpeta legible no demuestra que el volumen esté montado, así que `source_mount_status` sigue en `not_verified`. Confirma que el original se movió y no está sin conexión.
- **Códigos de salida:** 75 significa que otro trabajo tiene el bloqueo de la biblioteca; 1 significa que el bloqueo es inutilizable. La vista previa no toma el bloqueo.

Consulta [Volver a vincular una foto ausente](RELINK.md) para el contrato completo y ejemplos.
