# Recetas de interoperabilidad con editores

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · **Español** · [Português](../pt/INTEROP.md) · [简体中文](../zh/INTEROP.md)

Recetas paso a paso para llevar las valoraciones, etiquetas de color y tags de Facet hacia y desde Lightroom, Capture One, digiKam y darktable. Para la referencia completa de las opciones `--export-sidecars` / `--import-sidecars` y la correspondencia de campos (`xmp:Rating`, `xmp:Label`, `dc:subject`), consulta [Comandos — Vista previa y exportación](COMMANDS.md#vista-previa-y-exportación).

Los originales nunca se modifican salvo que pidas incrustar: `--embed-originals` en la línea de comandos, o **Escribir metadatos en el archivo** en el visor.

## Qué se transfiere

Las ubicaciones manuales y las decisiones de revisión se transfieren solo cuando exportas los metadatos en el visor o ejecutas `--export-sidecars`.

- **GPS** usa `exif:GPSLatitude` / `exif:GPSLongitude`. Solo se exportan las ubicaciones definidas manualmente, así que el GPS del escaneo nunca sustituye el GPS del archivo. `--embed-originals` también escribe GPS EXIF en los originales compatibles. Borrar una ubicación exporta un borrado explícito; un campo ausente nunca borra una ubicación al importar.
- **Fecha de captura.** Una fecha corregida se exporta como `exif:DateTimeOriginal` (y como EXIF `DateTimeOriginal` con `--embed-originals`). Tras **Usar fecha del archivo**, la siguiente exportación la elimina del sidecar, pero deja intacta una fecha escrita por otro editor.
- **Conservar y rechazar.** Conservar es independiente de las estrellas y los favoritos. Rechazar borra Conservar, las estrellas y el favorito.

El espacio de nombres XMP propio de Facet, `https://github.com/ncoevoet/facet/ns/1.0/`, añade:

| Tag | Valores | Finalidad |
|---|---|---|
| `facet:ReviewDecision` | `kept`, `rejected`, `undecided` | La decisión de revisión de Facet |
| `facet:GPSState` | `set`, `cleared` | Si Facet definió o borró la ubicación |
| `facet:DateState` | `set` | La fecha de captura del sidecar procede de Facet |
| `facet:KeywordState` | JSON (`version` 1; listas `owned`, `deleted`, `ai`, `manual`) | Qué palabras clave escribió Facet |
| `facet:RegionOwner` | `Facet` | Las regiones de rostro MWG que escribió Facet |

`facet:KeywordState` permite a `--reconcile-keywords` eliminar solo los nombres que son propiedad de Facet, e impide que una etiqueta de IA antigua se convierta en un tag manual al importar. `facet:RegionOwner` permite a ExifTool reemplazar solo las regiones de rostro de Facet.

Cómo aplica `--import-sidecars` una decisión de Facet:

- Aplica una decisión cuando los campos de revisión estándar coinciden con ella o están ausentes.
- Si el estado de rechazo estándar discrepa, otro editor cambió los campos estándar. Facet ignora su decisión privada y usa la comprobación de «gana el más reciente» con la hora del escaneo sobre los campos estándar.
- Una decisión exportada junto con campos de revisión estándar también usa la comprobación de «gana el más reciente», de modo que una exportación antigua no puede deshacer una decisión más reciente. La excepción es una foto sin estado de revisión todavía (sin estrellas, favorito, Conservar ni rechazo): una biblioteca reescaneada sigue recuperando sus decisiones.
- Las importaciones solo de decisión siguen siendo explícitas (las pides tú) y se aplican sin la comprobación con la hora del escaneo.

Otras reglas:

- El GPS manual que ya está en Facet se conserva salvo que añadas `--overwrite-manual-gps`. Las coordenadas no válidas o incompletas se ignoran.
- `--user alice` limita las importaciones y exportaciones a las carpetas visibles de ese usuario y a sus decisiones privadas. El GPS sigue siendo compartido. Sin `--user`, la CLI trabaja sobre el estado global.
- Las importaciones globales (sin `--user`), incluidas las vistas previas con `--dry-run`, no necesitan el secreto de inicio de sesión del visor.
- Con ExifTool, la exportación se fusiona en los sidecars existentes. Sin él, la exportación deja intacto un sidecar de editor existente y escribe un archivo alternativo.
- Las exportaciones con ExifTool necesitan las definiciones de tags incluidas con Facet. Si faltan, la exportación se detiene antes de cambiar nada; reinstala Facet.

## La trampa del nombre de los sidecars RAW

Facet exporta `IMG_1234.CR2.xmp` junto a `IMG_1234.CR2` (la convención de nombre completo de darktable). Lightroom Classic y Capture One suelen usar `IMG_1234.xmp` para los RAW propietarios. Los nombres de exportación nunca cambian.

Para JPEG/HEIC/TIFF/PNG/DNG, `--embed-originals` escribe dentro del archivo. GIF/WebP/BMP/AVIF/JPEG XL y los RAW propietarios siguen necesitando un sidecar con la nomenclatura correspondiente.

Al importar, elige la nomenclatura con `--import-sidecars --sidecar-naming full|basename|auto`:

- `full` (por defecto): lee `<image.ext>.xmp` o `<image.ext>.facet.xmp`, el que se haya modificado en último lugar. El principal gana un empate.
- `basename`: lee `<image>.xmp` (solo se quita la última extensión). Los sidecars de nombre completo se ignoran.
- `auto`: acepta el tipo que exista. Si existen ambos, la foto se omite por ambigua; elige `full` o `basename`.

Con `basename` y `auto`, un nombre base compartido por varias imágenes (p. ej. `same.CR3` y `same.jpg`) se rechaza, aunque solo una esté dentro del alcance. Usa sidecars de nombre completo para esos casos. `same_v1.jpg` tiene otro nombre base y no hay problema.

- Un archivo de doble extensión como `IMG.CR2.jpg` nunca lee `IMG.CR2.xmp`, que pertenece a `IMG.CR2`. Lo mismo vale para el sidecar alternativo `.facet.xmp` de otra imagen.
- Las discrepancias, la ambigüedad y los sidecars ilegibles se informan. Facet no prueba otra nomenclatura tras un fallo de análisis.
- El resumen cuenta cada foto afectada, incluidos los sidecars ignorados por la nomenclatura elegida. Los avisos muestran un ejemplo por tipo.
- No se renombra ningún archivo.

La importación no necesita ExifTool. La fusión en la exportación, la incrustación y los rectángulos de rostro MWG sí lo necesitan. Sin él, Facet deja intacto un sidecar de editor existente y escribe `<image.ext>.facet.xmp` sin rectángulos de rostro. Otros editores no buscan ese nombre, así que entrégalo de forma deliberada.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (añade una ruta para acotar el alcance, p. ej. `--export-sidecars /photos/2026-wedding`). Añade `--embed-originals` para escribir además directamente en archivos JPEG/HEIC/TIFF/PNG/DNG.
2. En el módulo Biblioteca de Lightroom Classic, selecciona las fotos (Ctrl/Cmd+A para todas) y elige **Metadatos → Leer metadatos del archivo**. Lightroom reemplaza su valoración, etiqueta de color y palabras clave por las del sidecar (o las de los metadatos incrustados).

El rechazo de Facet (`xmp:Rating = -1`) se relee como la marca de Rechazo de Lightroom. Un favorito de Facet escribe `xmp:Label = Yellow`, que Lightroom muestra como la **etiqueta de color Amarilla**, no como un Pick. Para obtener Picks, usa el plugin de abajo o filtra por la etiqueta Amarilla.

`python facet.py --export-manifest` escribe los datos de Facet sin XMP: ruta, categoría, todas las puntuaciones, tags y las mismas columnas de valoración que `--export-sidecars`. Usa `--export-manifest --user alice` para las valoraciones por usuario. Consulta [Comandos — Vista previa y exportación](COMMANDS.md#vista-previa-y-exportación). El plugin de Facet de abajo lo lee.

El **manifiesto versión 2** añade `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` y un recuento `pending_corrections` de nivel superior. Ese recuento es el número de correcciones manuales de bracket/panorama aún no aplicadas; vuelve a ejecutar `--detect-panoramas` para aplicarlas. El plugin lo muestra como una advertencia en su vista previa. Un plugin de la versión 2 rechaza un manifiesto de la versión 1 (y viceversa); vuelve a ejecutar `--export-manifest` si ves ese diálogo.

En el visor, el diálogo **Exportar al editor** de la galería tiene un botón **Descargar manifiesto de Lightroom** para la misma selección o filtro — consulta [Exportación al editor](VIEWER.md#exportación-al-editor). Produce el mismo `facet_manifest.json` que `--export-manifest`.

### El plugin de Facet (valoraciones, marcas Pick, campos de metadatos y palabras clave)

`facet.lrplugin/` en el repositorio de Facet es un plugin de Lightroom Classic. Escribe las valoraciones por estrellas y el estado de favorito/rechazo de Facet **directamente en el catálogo**. Esto resuelve dos cosas que XMP no puede: Lightroom nunca encuentra un sidecar de Facet para los RAW propietarios, y XMP no puede transportar la marca Pick de Lightroom.

El plugin lee un archivo de manifiesto. Nunca contacta con el servidor de Facet, no necesita contraseña y funciona con Facet detenido. Asocia las fotos por ruta, así que **una biblioteca solo RAW funciona como una de JPEG**.

Añade dos elementos al menú **Library → Plug-in Extras**:

- **Facet: Apply ratings and flags...** — manifiesto → catálogo (esta sección).
- **Facet: Export Lightroom State to Facet...** — catálogo → Facet, consulta [Lightroom → Facet](#lightroom--facet).

**Instalar** (una vez):

1. Copia la carpeta `facet.lrplugin` a la máquina de Lightroom. En macOS, comprímela primero en zip: el Finder trata una carpeta `.lrplugin` como un paquete.
2. En Lightroom Classic: **File → Plug-in Manager → Add**, selecciona la carpeta `facet.lrplugin` y luego **Done**.

**Usar:**

1. `python facet.py --export-manifest /photos/2026-wedding` (la ruta acota la exportación; el archivo siempre es `facet_manifest.json` en el directorio actual). Cópialo a la máquina de Lightroom si es necesario.
2. En el módulo Biblioteca, selecciona las fotos y luego **Library → Plug-in Extras → Facet: Apply ratings and flags...**
3. Apunta el diálogo a `facet_manifest.json`. La ruta se recuerda.
4. **Si Facet escaneó en otra máquina, rellena los dos prefijos de ruta.** El manifiesto contiene las rutas de la máquina que escaneó (p. ej. `/volume1/photos/...` en un NAS); Lightroom contiene las del escritorio (p. ej. `Z:\photos\...`). Introduce el prefijo de Lightroom y el prefijo de Facet para la misma carpeta. Deja ambos vacíos si las rutas coinciden. Si son incorrectos, nada coincide.
5. Elige el alcance: las fotos seleccionadas (por defecto) o toda la carpeta actual.
6. Pulsa **Preview...**. **Todavía no se escribe nada.** Muestra cuántas fotos coincidieron, cuántas no, y qué establecería. Si nada coincidió, muestra una ruta de ejemplo de Lightroom junto a una ruta de ejemplo del manifiesto para que puedas corregir los prefijos.
7. Pulsa **Apply**. Puedes cancelar durante el progreso. Un resumen muestra lo que se estableció, se omitió y no se encontró.

**Qué escribe** (nunca en tus archivos de imagen):

| Estado de Facet | Campo de Lightroom |
|---|---|
| `star_rating` 1-5 | valoración en estrellas |
| favorito | marca Pick |
| rechazado | marca Reject |

Una valoración de Facet de 0 estrellas significa «sin opinión» y nunca se escribe.

**Regla de sobrescritura.** Por defecto, el plugin solo establece una valoración en una foto *sin valorar* en Lightroom, y una marca en una *sin marcar*. Tus propias valoraciones y marcas se conservan y se cuentan como «se dejan como están». Marca **Overwrite ratings and flags that are already set in Lightroom** para reemplazarlas. La exportación de sidecars sigue la misma regla (`xmp_export.score_to_rating.only_when_unrated`, por defecto `true`).

**Opciones del diálogo** (todas desactivadas por defecto, se recuerdan entre ejecuciones):

- **Fill in star ratings from Facet scores for photos you have not rated** — si el manifiesto no tiene `star_rating` (o es 0), la puntuación `aggregate` se convierte en estrellas. Este recurso **nunca sobrescribe una valoración existente de Lightroom, ni siquiera con Overwrite marcado.**
- **Pick the recommended frame of each burst** — en cada grupo de ráfaga con al menos 2 miembros, todo miembro marcado `is_burst_lead` recibe Pick (una ráfaga puede conservar más de uno). Los fotogramas sueltos y los grupos sin líder se omiten. Tus propias marcas Pick/Reject y los favoritos/rechazos de Facet siempre prevalecen.
- **Reject the other frames** (solo con la opción de pick) — rechaza todo miembro de ráfaga que no sea líder. Los miembros de un bracket, una panorámica o una panorámica HDR nunca se rechazan, y los grupos sin líder no reciben rechazos.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — para cada grupo con al menos 2 fotos coincidentes dentro del alcance, crea o reutiliza una colección bajo `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` o `Facet › HDR panoramas`.
  - Nombre: `<yyyy-mm-dd HH:MM:SS> – <filename>` del miembro más antiguo, o `~ (no date) – <filename>` si no tiene hora de captura.
  - Una ráfaga cuyos miembros pertenecen todos a un mismo conjunto de bracket o panorámica no recibe una colección de Bursts aparte.
  - **Volver a ejecutar solo añade fotos.** Una foto que más tarde sale de un conjunto permanece en su colección.
  - Limitación conocida: dos grupos cuyos miembros más antiguos comparten el mismo segundo de captura y nombre de archivo (p. ej. dos cámaras que escriben `IMG_0001`) comparten una colección.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (solo con la opción anterior) — vacía y rellena una colección, pero solo cuando la colección y todo su grupo están dentro del alcance actual. Las colecciones cubiertas parcialmente y las colecciones inteligentes se omiten.
    - También vacía y elimina la colección de un grupo que se disolvió en esta ejecución, pero solo si todas sus fotos coincidieron en esta ejecución.
    - Solo toca colecciones cuyo nombre tiene el formato propio de Facet (una fecha-hora o `~ (no date)`, y luego ` – <filename>`). Las colecciones a las que tú pusiste nombre nunca se tocan.
    - La vista previa muestra una línea `Facet collections to delete: N` cuando hay algo que eliminar. El resumen informa de las colecciones reconstruidas, eliminadas, omitidas y fallidas.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — escribe la puntuación agregada (p. ej. `8.4`), una banda de puntos enteros (`0`-`10`), la categoría y el tipo de conjunto en campos de metadatos propios de Facet. Aparecen en el panel Metadatos y funcionan como criterios de texto (`sdktext:`) en el Filtro de biblioteca y en las colecciones inteligentes, p. ej. banda «cualquiera de 8, 9, 10». Un campo que ya no se aplica se borra. También se escriben dos campos ocultos de control (la valoración y el pick que derivó esta ejecución); se excluyen de la búsqueda pero aún pueden ser visibles en algunas versiones de Lightroom Classic (sin verificar).
- **Create "Facet" keywords from Facet tags (never included on export)** — crea una palabra clave raíz `Facet` con un hijo por tag (de IA y [tags manuales](#tags-manuales-y-palabras-clave-xmp)). Los hijos `Facet ›` de cada foto se ajustan a sus tags, así que un tag eliminado en Facet desaparece en el siguiente Apply. `Include on Export` está desactivado para todos ellos, de modo que nunca se filtran a las exportaciones ni a las galerías de clientes. Tus palabras clave fuera de la raíz `Facet` nunca se modifican. Una palabra clave `Facet` de primer nivel existente se adopta como raíz, y cualquier hijo que hayas añadido tú bajo ella se elimina.

**Por qué colecciones y no pilas.** El SDK de Lightroom no puede crear pilas. Para apilar las fotos de una colección, selecciónalas y usa **Foto → Apilar → Agrupar en pila** (Ctrl/Cmd+G).

**Limitaciones:**

- **Las marcas Pick se quedan en el catálogo.** Lightroom nunca las escribe en XMP, así que ninguna otra aplicación las ve, y reconstruir el catálogo desde los archivos las pierde. Las valoraciones por estrellas sobreviven mediante **Metadatos → Guardar metadatos en el archivo**.
- **No hay colecciones inteligentes numéricas sobre los campos de Facet.** Los campos del plugin son solo texto (`sdktext:`); los operadores numéricos (`>`, `<`, `in range`) funcionan solo sobre los campos integrados de Lightroom. Usa el campo de banda, o la opción de rellenar estrellas, que Lightroom sí ordena y filtra numéricamente.
- **Deshacer** revierte un lote de 200 fotos por cada Ctrl/Cmd+Z.
- Marca **Write facet-apply.log next to the manifest** para registrar qué rutas coincidieron y qué se escribió.

### Lightroom → Facet

**Valoraciones, picks y rechazos — gana Lightroom (vía el plugin).**

1. **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** abre un panel de guardado. El archivo contiene un registro por foto: `path`, más `rating`/`pick` cuando necesitan transferirse.
2. Impórtalo con `python facet.py --import-lightroom facet_lightroom_state.json` (`--user alice` es obligatorio en una instalación multiusuario), o con **Importar estado de Lightroom…** en el diálogo **Exportar al editor** de la galería.

El valor de Lightroom gana en todos los campos de un registro. La importación informa de los recuentos `matched`/`unmatched`/`changed`.

| Estado de Lightroom | Resultado en Facet |
|---|---|
| Marca Pick = Picked (`pick = 1`) | favorito = activado, rechazado = desactivado |
| Marca Pick = Rejected (`pick = -1`) | favorito = desactivado, rechazado = activado |
| Marca Pick = ninguna (`pick = 0`) | favorito = desactivado, rechazado = desactivado |
| valoración en estrellas (`rating`, 0-5) | `star_rating` (`0` la borra) |

- Un registro sin `rating` ni `pick` deja intacto ese valor de Facet. La exportación solo incluye un campo cuando el valor de Lightroom difiere del que estableció el último Apply, así que una foto sin tocar no cambia nada.
- Las copias virtuales se fusionan con su original antes de exportar.
- Una importación correcta que cambie algo actualiza los pares de entrenamiento y arma el reentrenamiento automático, como cualquier cambio de valoración.

> **Advertencia:** Como gana Lightroom, una foto que el paso Apply nunca tocó y que está sin valorar y sin marcar en Lightroom (`pick = 0`, sin `rating`) borra en la importación su valoración por estrellas, favorito y rechazo de Facet.

**Valoraciones, etiquetas y palabras clave vía XMP** (en un solo sentido):

1. En Lightroom, selecciona las fotos y elige **Metadatos → Guardar metadatos en el archivo** (Ctrl/Cmd+S). Esto escribe la valoración, la etiqueta y las palabras clave en el sidecar XMP (RAW) o dentro del archivo (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars /path --sidecar-naming basename` lee los sidecars RAW. Los nombres base RAW/JPEG compartidos se rechazan. Este comando no lee los metadatos incrustados. Las palabras clave importadas se convierten en tags manuales.

### Reglas de conflicto

- **Los tags y las palabras clave se fusionan por defecto.** Las exportaciones añaden palabras clave de Facet; `--reconcile-keywords` elimina además los nombres obsoletos propiedad de Facet. Las importaciones añaden tags manuales y nunca reemplazan los de IA. Consulta [Tags manuales y palabras clave XMP](#tags-manuales-y-palabras-clave-xmp).
- **Multiusuario** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): las valoraciones van a las valoraciones propias de Alice (`user_preferences`) en lugar de a las globales. Las palabras clave son siempre globales: los tags manuales se comparten.
- Las palabras clave importadas se guardan en `photo_manual_tags`, que los filtros de tags leen directamente. No hace falta `python database.py --migrate-tags` después de `--import-sidecars`.

## Capture One

Capture One guarda sus ajustes en archivos `.cos` (Sesiones) o en su catálogo. Su modo «Full Sync» de **Sync Metadata** puede sobrescribir el lado que escribió en último lugar, así que un bucle bidireccional puede perder ediciones. Usa **un solo sentido, Facet → Capture One**:

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`.
2. En Capture One, deja **Preferences → General → Sync Metadata** en su valor por defecto (no «Full Sync»).
3. Selecciona las imágenes, haz clic derecho y elige **Load Metadata** para traer de una vez la valoración, la etiqueta y las palabras clave.

Después sigue trabajando en Capture One sin sincronización automática. Para traer de vuelta a Facet el XMP guardado, ejecuta `--import-sidecars /path/to/shoot --sidecar-naming basename` para sidecars RAW sin extensión, o `full` para nombres de archivo completos. Los nombres base RAW/JPEG compartidos se rechazan. Esto lee sidecars, no metadatos incrustados.

## digiKam

Los [ajustes de sidecars](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings) de digiKam usan una única nomenclatura: `filename.ext.xmp` por defecto, o `filename.xmp` con **Sidecar file names are compatible with commercial programs** activado. No prueba ambas.

- **Facet → digiKam:** usa el ajuste de nombre completo, activa **Read from sidecar files**, vuelve a leer los metadatos de los archivos y comprueba los campos.
- **digiKam → Facet:** pasa `--sidecar-naming full` o `basename` para que coincida con tu ajuste de digiKam.

Las estrellas, las etiquetas de color y las marcas Pick significan cosas ligeramente distintas en cada aplicación, así que comprueba el resultado.

### Gancho del Batch Queue Manager

Puedes ejecutar una importación de Facet desde la herramienta **Custom Script** del Batch Queue Manager (BQM) de digiKam. Primero activa la escritura de sidecars, guarda el ajuste de nomenclatura y aplica los cambios de metadatos pendientes (digiKam puede retrasar las escrituras). Este ejemplo supone sidecars de nombre completo; usa `basename` solo para una colección sin nombres base compartidos:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` son los marcadores por archivo de digiKam. BQM espera un archivo de salida, de ahí el `cp`. `--import-sidecars` escanea toda la carpeta, así que ejecutarlo por foto es redundante pero inofensivo. Para lotes grandes, ejecuta `python facet.py --import-sidecars /path/to/folder` una vez cuando termine la cola.

## darktable

Consulta [Configuración — Visor](CONFIGURATION.md#visor) (perfiles de exportación y estilos de `viewer.raw_processor.darktable`) y [Visor — Descarga](VIEWER.md#descarga) (conversiones `type=darktable`).

darktable guarda su historial de edición en su propio `<image><ext>.xmp`. El escritor ExifTool de Facet se fusiona en ese archivo y conserva los nodos `darktable:history` y de máscaras. El comportamiento de sidecars de Lightroom descrito arriba (exportación/importación, gana el más reciente, unión de tags) se aplica tal cual, y no hay discrepancia de nombres RAW: ambos usan `<image><ext>.xmp`.

**Versión de ExifTool:**

- Se recomienda la **13.28 o posterior**.
- Las actualizaciones de rostros necesitan la **12.65 o posterior**. Las versiones anteriores o desconocidas omiten los cambios de rostros con una advertencia y exportan el resto.
- Las **13.23 a 13.27** corrompen los sidecars que llevan historial de darktable, así que Facet se niega a escribir con ellas y te pide actualizar. La imagen de Docker fija una versión segura. Los paquetes de las distribuciones pueden no hacerlo (el `libimage-exiftool-perl` de Debian trixie es el 13.25).

> **Advertencia:** darktable puede borrar su propio historial de edición al reimportar una imagen ya editada: puede sobrescribir el historial del sidecar con uno vacío. Es un error abierto upstream ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), notificado el 2026-03-15), y el ajuste «check for new/updated xmp files on start» no lo evita. Tras `--export-sidecars`, no reimportes en bloque una carpeta editada. Recarga solo las imágenes que Facet tocó y comprueba antes su historial.

## Tags manuales y palabras clave XMP

Facet guarda los tags que escribes (consulta [Visor — Tags manuales](VIEWER.md#tags-manuales)) en `photo_manual_tags`, separados de los tags de IA en `photos.tags`. Un reescaneo o un nuevo etiquetado nunca los toca.

- **Exportación.** Todo escritor de palabras clave emite los tags de IA, luego los tags manuales y luego los nombres de personas, sin duplicados ignorando mayúsculas. Esto cubre `--export-sidecars`, la exportación XMP de la galería y las acciones «Escribir metadatos en el archivo», y el manifiesto de Lightroom (`--export-manifest`, `/api/lightroom/manifest`).
- **Importación.** `--import-sidecars` lee palabras clave planas de `dc:subject` y rutas jerárquicas por separado de `lr:hierarchicalSubject`. Las palabras clave planas se normalizan como los tags escritos: sin espacios en los extremos, en minúsculas, como máximo 64 caracteres, 50 tags manuales por foto. Cada una se convierte en un tag manual con origen `xmp`, salvo que:
  - ya sea uno de los tags de IA o nombres de personas de la foto,
  - duplique una ruta presente explícitamente en `lr:hierarchicalSubject`,
  - contenga una coma o un carácter de control, o
  - superara el límite.
- **La eliminación de palabras clave es explícita.** Por defecto las exportaciones solo añaden. `--export-sidecars /path --reconcile-keywords` (necesita ExifTool) elimina además los nombres que Facet escribió antes y que ya no están en Facet. Las palabras clave que Facet nunca escribió nunca se eliminan, aunque el nombre coincida, y los sidecars antiguos sin marcar no dan a Facet ninguna propiedad. Si vuelves a añadir en otro editor una palabra clave eliminada, Facet puede importarla de nuevo y la trata como ajena a partir de entonces. Las palabras clave son compartidas incluso con `--user`.
- **Las palabras clave de Facet ganan al exportar.** Una palabra clave que sigue en Facet se vuelve a escribir aunque otro editor la haya quitado del archivo. Para eliminarla definitivamente, quita el tag en Facet. La reconciliación nunca borra tags de Facet.
- Los nombres como `2024`, `1.50`, `1e3`, `true`, `false` y `null` conservan su grafía.
- Si Facet no puede leer los metadatos de un archivo existente, la exportación se detiene antes de escribir.
- **El manifiesto de Lightroom sí propaga las eliminaciones.** La opción de palabras clave del plugin reescribe los hijos `Facet ›` de cada foto en cada Apply.
- **Los tags de IA siguen siendo tags de IA.** Los sidecars registran qué palabras clave eran de IA y cuáles manuales, así que un nuevo etiquetado no convierte una palabra clave de IA antigua en un tag manual. Los sidecars de versiones antiguas de Facet conservan el comportamiento aditivo anterior.
- **Jerarquías.** Las rutas importadas se añaden a la jerarquía compartida; los nombres planos que contienen `|` o `/` no crean una jerarquía por sí solos. Las rutas marcadas como generadas por Facet no se importan como asignaciones manuales, salvo que también estén marcadas como manuales. Las exportaciones incluyen las asignaciones explícitas y las rutas generadas de categorías/personas. Por defecto, la exportación añade rutas; `--reconcile-keywords` elimina solo las rutas obsoletas propiedad de Facet y conserva las ajenas.
- **Límites de propiedad:** 10 000 nombres por lista y 1024 caracteres por nombre. Una exportación que los superara se detiene antes de escribir. Archiva y limpia a mano un sidecar así antes de empezar de nuevo.
- **Las palabras clave importadas por un Facet antiguo se quedan donde están.** Las versiones antiguas fusionaban las palabras clave en `photos.tags`, donde parecen tags de IA, y nada las migra. Para convertir una en un tag manual, borra o vuelve a etiquetar `photos.tags` y ejecuta `--import-sidecars` de nuevo — o añade el tag a mano.
- **Un archivo movido o renombrado pierde sus tags manuales.** Están ligados a la ruta de la foto.
- **`--export-csv` y `--export-json` siguen siendo solo de IA.** Su valor `tags` no incluye tags manuales.

## Cómo fusiona Facet

| Campo | Facet escribe | Facet relee | Regla de conflicto |
|---|---|---|---|
| Valoración por estrellas / rechazo | `xmp:Rating` (`-1` = rechazada) | `xmp:Rating` | Relojes de revisión registrados; recurso heredado con la hora del escaneo |
| Etiqueta de color | `xmp:Label` (`Red` = rechazada, `Yellow` = favorita) | `xmp:Label` | Relojes de revisión registrados; recurso heredado con la hora del escaneo |
| Tags / palabras clave | `dc:subject` (plano, tags de IA + tags manuales, incluye los nombres de personas de rostros con nombre) | `dc:subject` (guardado como tags manuales) | Aditivo por defecto; `--reconcile-keywords` elimina solo los nombres obsoletos propiedad de Facet; las importaciones siguen siendo aditivas ([Tags manuales y palabras clave XMP](#tags-manuales-y-palabras-clave-xmp)) |
| Tags jerárquicos | `lr:hierarchicalSubject` (asignaciones explícitas y rutas generadas de categorías/personas) | `lr:hierarchicalSubject` (asignaciones a la jerarquía compartida) | Importación aditiva; la reconciliación al exportar elimina solo rutas obsoletas de Facet |
| Leyenda | `dc:description` en el idioma por defecto (+ `IPTC:Caption-Abstract` vía exiftool) | No se reimporta | Solo exportación |
| Regiones de rostro con nombre | MWG `mwg-rs:RegionList` + `facet:RegionOwner=Facet` (centro normalizado, `Type=Face`) | No se reimporta | Solo exportación; lo lee digiKam de forma nativa, **no** lo lee Lightroom (una limitación conocida de Adobe: Lightroom solo consume las regiones MWG que escribió él mismo) |

Consulta [Comandos — Vista previa y exportación](COMMANDS.md#vista-previa-y-exportación) para la referencia completa de la CLI (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).

**Borrados de GPS.** Si un sidecar tiene tanto los campos GPS estándar como un antiguo `facet:GPSState=cleared`, gana un par latitud/longitud completo y válido. Un par parcial o no válido se ignora y nunca borra una ubicación. Solo un par ausente o vacío más el marcador de borrado borra el GPS. El GPS manual sigue protegido salvo que pidas sobrescribirlo.

**Leyendas.** Con ExifTool, la exportación actualiza solo el idioma por defecto (`x-default`) de `dc:description` y conserva los demás idiomas. Una leyenda vacía en Facet deja intactas las leyendas existentes. Sin ExifTool, Facet escribe una leyenda en el idioma por defecto y, cuando existe un sidecar de editor, escribe en `<image>.facet.xmp` en su lugar.

**Regiones de rostro.** Con ExifTool, la exportación reemplaza solo los rectángulos MWG marcados con `facet:RegionOwner=Facet`.

- Las regiones sin marcar, incluidas las de versiones antiguas de Facet, se conservan. Tras actualizar, un rostro antiguo sin marcar y su nueva copia marcada pueden aparecer a la vez, y borrar los rostros deja el antiguo.
- Las exportaciones repetidas reemplazan las copias marcadas; no se acumulan.
- Si las dimensiones de la imagen difieren de aquellas sobre las que se dibujaron las regiones existentes (o se desconocen), los cambios de rostros se omiten con una advertencia. La valoración, la etiqueta, las palabras clave y el GPS se siguen exportando.
- Los metadatos de rostros ilegibles o no válidos detienen antes de escribir la exportación o incrustación de una sola foto.
- El escritor alternativo (sin ExifTool) no exporta rectángulos de rostro.
- Una región marcada que editas en otro lugar sigue siendo de Facet. Quita su marcador de propiedad para conservarla como propia.

> **Advertencia:** Las escrituras en archivos separados no son atómicas. Un fallo de E/S o un cambio externo durante la exportación puede dejar unos archivos actualizados y otros no.

Si falla la comprobación de la versión de ExifTool, Facet la reintenta la próxima vez. Mientras la versión es desconocida, las regiones de rostro se omiten y el resto se exporta. Las versiones conocidas como defectuosas se rechazan siempre.

## Vista previa de importación de sidecars y conflictos de revisión

Ejecuta `--import-sidecars /path --dry-run` para ver el plan en JSON antes de escribir: el sidecar elegido, los campos antes/después, las palabras clave a añadir, la hora de origen y los motivos de omisión/conflicto. La vista previa abre la base de datos en solo lectura y nunca la modifica. Aplicar vuelve a leer todo, así que la vista previa no es un token que se reutilice.

Si la base de datos falta, es ilegible o no es válida, la vista previa termina con el código 1 y no la crea ni la repara. `--dry-run-count` limita solo las muestras del escaneo, no las vistas previas de importación.

`--sidecar-fields review,gps,keywords` selecciona qué grupos importar; deja fuera un grupo para omitirlo.

- **review** importa juntas las estrellas, el favorito, el rechazo y Conservar, de modo que un conflicto nunca aplica media decisión.
- **gps** conserva las ubicaciones manuales salvo que se indique `--overwrite-manual-gps`.
- **keywords** son aditivas y compartidas, incluso con `--user`.

**Relojes de edición.** Facet registra cuándo se cambió por última vez cada campo de revisión, por foto y cuenta, incluidos los restablecimientos. Un sidecar más antiguo que ese cambio es un conflicto `newer_local_edit`, y ese grupo de revisión se deja sin cambios. `--overwrite-sidecar-review` anula esto y la comprobación con la hora del escaneo. Un origen `local` significa un escritor desconocido, no necesariamente una persona. Las leyendas, los rostros y el GPS externo sin marcar nunca se importan.

- Los campos cambiados antes de que Facet empezara a registrar ediciones no tienen hora de edición conocida. Se aplica la regla de la hora del escaneo, informada como `untracked_legacy_edit`.
- La vista previa también abre bases de datos antiguas sin actualizarlas; un campo Conservar ausente se lee como sin decidir.
- La hora del sidecar es `xmp:MetadataDate`, o la hora de modificación del archivo si falta o no es válida.
- Los detalles enumeran las primeras 1000 fotos del alcance y 100 notas por foto, con los recuentos de lo que se dejó fuera.

Los relojes de edición permanecen en su propia base de datos. Una exportación nueva del visor no copia relojes de edición del escáner ni rutas de sidecars. Una exportación incremental conserva los relojes propios del visor, de modo que los restablecimientos hechos en el visor (incluidas las valoraciones por usuario eliminadas) sobreviven. Los valores del escáner que el visor nunca editó siguen actualizándose.

> **Advertencia:** Una base de datos de visor creada por una compilación no publicada anterior a la 1.24.0 puede contener relojes del escáner copiados. Ahora cuentan como ediciones del visor, así que esos campos dejan de seguir las actualizaciones del escáner. Haz una copia de seguridad y revisa esa base de datos antes de reconstruirla: una reconstrucción completa descarta los cambios locales del visor.
