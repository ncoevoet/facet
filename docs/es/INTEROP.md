# Recetas de interoperabilidad con editores

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · **Español** · [Português](../pt/INTEROP.md) · [简体中文](../zh/INTEROP.md)

Recetas prácticas, paso a paso, para hacer circular en ambos sentidos las valoraciones, etiquetas de color y tags de Facet con los editores externos y las herramientas de gestión de fototeca (DAM) que los fotógrafos usan de verdad. Esta página asume que ya sabes *que* Facet escribe XMP — consulta [Comandos — Vista previa y exportación](COMMANDS.md#vista-previa-y-exportación) para la referencia completa de las opciones `--export-sidecars` / `--import-sidecars` y la correspondencia de campos (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## La trampa del nombre de los sidecars RAW

Facet nombra un sidecar `<imagen><ext>.xmp` — por ejemplo `IMG_1234.CR2.xmp` junto a `IMG_1234.CR2` — la misma convención que usan darktable y digiKam. **Lightroom Classic y Capture One esperan lo contrario: `IMG_1234.xmp`, sin la extensión RAW.** Ninguno de los dos detectará un sidecar escrito por Facet para un archivo RAW propietario (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — todo salvo el DNG), y el `--import-sidecars` de Facet tampoco encontrará un sidecar escrito por una aplicación del ecosistema Adobe para ese mismo RAW. Es un desajuste de convenciones de nombre entre ecosistemas, no un fallo de ninguno de los dos lados.

Esto **no** afecta a:
- **JPEG, HEIC, TIFF, PNG, DNG** — pasa `--embed-originals` y Facet escribe los metadatos *directamente en el archivo* (vía exiftool), así que no hay ningún nombre de sidecar que Lightroom/Capture One puedan pasar por alto.
- **digiKam** — comprueba ambas convenciones de nombre y encuentra el sidecar de Facet en cualquier caso (ver [digiKam](#digikam) más abajo).
- **darktable** — usa la misma convención `<imagen><ext>.xmp` que Facet (ver [darktable](#darktable) más abajo).

**GIF, WebP, BMP y AVIF son la excepción: son los que peor lleva el desajuste.** Quedan fuera del conjunto incrustable de Facet, así que `--embed-originals` no hace nada por ellos y su único vehículo de ida y vuelta es un sidecar XMP con el nombre que usa Facet (`photo.webp.xmp`). El desajuste anterior se aplica por tanto a estos cuatro igual que al RAW propietario: digiKam y darktable encuentran el sidecar, Lightroom Classic y Capture One no.

Así que, para un flujo con Lightroom o Capture One: usa `--embed-originals` para todo lo que esté en el conjunto incrustable (JPEG, HEIC, TIFF, PNG, DNG), y espera que el ida y vuelta por sidecar quede en silencio (sin error, simplemente no se lee nada) para los RAW propietarios, y también para GIF, WebP, BMP y AVIF. Si disparas en RAW+JPEG, el JPEG acompañante es el vehículo práctico de interoperabilidad — el RAW se queda en el disco, intacto, mientras la base de datos de Facet conserva la valoración que hace autoridad.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (añade una ruta para acotar el alcance, por ejemplo `--export-sidecars /fotos/boda-2026`). Añade `--embed-originals` para además escribir directamente en archivos JPEG/HEIC/TIFF/PNG/DNG.
2. En el módulo Biblioteca de Lightroom Classic, selecciona las fotos (Ctrl/Cmd+A para todas) y elige **Metadatos → Leer metadatos del archivo**. Lightroom sobrescribe la valoración, la etiqueta de color y las palabras clave de su catálogo a partir del sidecar (o de los metadatos incrustados, para los formatos anteriores).

El marcador de rechazo de Facet (`xmp:Rating = -1`) se relee como la marca de Rechazo de Lightroom. Un favorito de Facet escribe `xmp:Label = Yellow`, que Lightroom muestra como **etiqueta de color Amarilla** — no como la marca de Selección (Pick). Si tu flujo de Lightroom se basa en las marcas Pick en lugar de las etiquetas de color, añade un paso de conversión etiqueta-de-color → pick, o filtra en su lugar por la etiqueta Amarilla.

Ahora existe un feed `python facet.py --export-manifest` (ruta, categoría, todas las puntuaciones, tags y las mismas columnas de valoración que `--export-sidecars` — incluidas las valoraciones por usuario mediante `--export-manifest --user alice` en una instalación multiusuario) para las herramientas que quieren los datos de Facet sin analizar el XMP — consulta [Comandos — Vista previa y exportación](COMMANDS.md#vista-previa-y-exportación). Es justamente ese feed el que consume el plugin de Facet descrito a continuación.

**Manifiesto versión 2.** El manifiesto ahora también incluye `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` y un recuento de nivel superior `pending_corrections` (correcciones manuales de bracket/panorama que una ejecución de detección aún no ha aplicado — vuelve a ejecutar `--detect-panoramas`). El plugin usa los campos por foto para las opciones de selección/rechazo de rachas y de respaldo de estrellas descritas abajo, y muestra `pending_corrections` como línea de aviso en su Vista previa, para que sepas que otra ejecución de la detección aún puede cambiar qué fotogramas son guía. No hay una ruta de lectura retrocompatible: un plugin compilado para la versión 2 rechaza directamente un manifiesto en versión 1, con un diálogo que pide reexportarlo, y un plugin más antiguo tampoco puede leer un manifiesto en versión 2. Si ves ese diálogo, vuelve a ejecutar `--export-manifest`.

En el viewer, el diálogo **Export to editor** de la galería ofrece el mismo manifiesto mediante un botón **Download Lightroom manifest**, acotado a la misma selección/filtro que la exportación de sidecars de al lado — véase [Editor Export](VIEWER.md#exportación-al-editor). Escribe exactamente la misma forma de `facet_manifest.json` que `--export-manifest`, así que el diálogo del plugin de abajo funciona igual sea cual sea el lado que generó el archivo.

### El plugin de Facet (valoraciones, marcas Pick, campos de metadatos y palabras clave)

`facet.lrplugin/`, en el repositorio de Facet, es un plugin de Lightroom Classic que escribe la valoración en estrellas y el estado favorito/rechazado de Facet **directamente en el catálogo**. Existe porque dos de las cosas anteriores no tienen solución desde el lado XMP: Lightroom nunca encuentra un sidecar de Facet para un archivo RAW propietario, y el XMP no tiene ningún canal para la marca de Selección (Pick) de Lightroom. El plugin lee un archivo de manifiesto: nunca habla con el servidor de Facet, no necesita contraseña y funciona con Facet apagado — y como empareja las fotos por ruta en lugar de por sidecar, **una biblioteca íntegramente RAW funciona igual que una de JPEG**.

El plugin registra dos elementos en **Biblioteca → Extras de plugin** (**Library → Plug-in Extras**): **Facet: Apply ratings and flags...** (el sentido manifiesto → catálogo, descrito en esta sección) y **Facet: Export Lightroom State to Facet...** (el sentido inverso — véase [Lightroom → Facet](#lightroom--facet) abajo).

**Instalación** (una sola vez):

1. Copia la carpeta `facet.lrplugin` a la máquina que ejecuta Lightroom. En macOS, comprímela primero en zip — el Finder trata una carpeta `.lrplugin` como un paquete.
2. En Lightroom Classic: **Archivo → Administrador de plugins → Añadir**, selecciona la carpeta `facet.lrplugin` y pulsa **Listo**.

**Uso** (cada vez que quieras el veredicto de Facet en el catálogo):

1. `python facet.py --export-manifest /fotos/boda-2026` (la ruta acota la exportación; el archivo siempre se escribe como `facet_manifest.json` en el directorio actual). Cópialo a la máquina con Lightroom si Facet se ejecuta en otro sitio.
2. En el módulo Biblioteca selecciona las fotos y elige **Biblioteca → Extras de plugin → Facet: Apply ratings and flags...** (la interfaz del plugin está en inglés).
3. Indica el archivo `facet_manifest.json`. La ruta se recuerda para la próxima vez.
4. **Si Facet analizó las fotos desde otra máquina, rellena los dos prefijos de ruta.** El manifiesto guarda las rutas de la máquina que hizo el análisis (`/volume1/photos/...` en un NAS), mientras que Lightroom conoce las del equipo de trabajo (`Z:\photos\...`). Introduce el prefijo de Lightroom y el de Facet que designan la misma carpeta; déjalos vacíos cuando coincidan. Es el único fallo de primera ejecución que realmente importa — sencillamente no empareja ninguna foto.
5. Elige el alcance: las fotos seleccionadas (por defecto) o todas las fotos de la carpeta actual.
6. Pulsa **Preview...** (Vista previa). **Todavía no se escribe nada.** El plugin informa de cuántas fotos ha encontrado en el manifiesto, cuántas no, y cuántas valoraciones y marcas escribiría. Si el número de coincidencias es 0, muestra una ruta de ejemplo de Lightroom junto a una del manifiesto para que veas cómo deben ser los prefijos.
7. Pulsa **Apply** (Aplicar). El progreso se muestra y se puede cancelar; un diálogo de resumen indica qué se escribió, qué se omitió y qué no se encontró.

**Qué escribe** — nada más, y nunca en tus archivos de imagen:

| Estado de Facet | Campo de Lightroom |
|---|---|
| `star_rating` 1-5 | valoración en estrellas |
| favorito | marca de Selección (Pick) |
| rechazado | marca de Rechazo (Reject) |

Una valoración de Facet de 0 significa «sin opinión» (véase `xmp_export.score_to_rating`) y nunca se escribe.

**Semántica de sobrescritura** — por defecto el plugin nunca te lleva la contraria: solo pone una valoración si la foto está *sin valorar* en Lightroom, y una marca solo si la foto está *sin marcar*. Todo lo que hayas valorado o marcado a mano se deja intacto y se cuenta como «kept as they are» (se dejan como están) en la vista previa. Marca **Overwrite ratings and flags that are already set in Lightroom** para reemplazarlas de todos modos. Esto refleja `only_when_unrated` de `xmp_export.score_to_rating`, de modo que el plugin y la vía de los sidecars tratan igual tus ediciones manuales.

**Nuevas opciones del diálogo** (todas opcionales, cada una se recuerda para la próxima vez):

- **Fill in star ratings from Facet scores for photos you have not rated** — cuando una foto no tiene `star_rating` en el manifiesto (o es 0) pero la puntuación `aggregate` de Facet corresponde a un número de estrellas, esa valoración derivada rellena el hueco. Como es un respaldo para una foto *sin valorar*, y no una valoración real del manifiesto, **nunca sobrescribe una valoración que Lightroom ya tenga — ni siquiera con Overwrite marcada.** Una `star_rating` real del manifiesto sigue la regla de sobrescritura normal de arriba, sin cambios.
- **Pick the recommended frame of each burst** — para cada grupo de racha con al menos 2 miembros en el manifiesto, cada miembro que el manifiesto marca como `is_burst_lead` (una racha puede conservar más de un fotograma) se pone en Seleccionada (Pick). Un fotograma aislado que el manifiesto nunca agrupó con otros nunca se toca con esta opción, y un grupo de racha sin ningún miembro `is_burst_lead` en todo el manifiesto se omite por completo (no hay nada de dónde derivar). Una marca Pick/Reject puesta a mano — o un favorito/rechazo de Facet en el manifiesto — siempre gana sobre esta selección derivada.
- **Reject the other frames** (anidada bajo la opción anterior, solo se activa junto con ella) — pone en Rechazada cada miembro de la racha que *no* es el fotograma guía, con dos excepciones: un miembro de un bracket, panorama o panorama HDR nunca se rechaza con esta regla, aunque su `burst_group_id` también lo agrupe con otros — esos conjuntos se conservan íntegros; y un grupo sin ningún fotograma guía en todo el manifiesto (ver arriba) tampoco recibe rechazos.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — para cada grupo con al menos 2 fotos emparejadas en el ámbito actual, crea o reutiliza una colección llamada `<yyyy-mm-dd HH:MM:SS> – <filename>` (la hora de captura y el nombre de archivo del miembro más antiguo; `~ (no date) – <filename>` cuando ese miembro no tiene hora de captura), anidada bajo `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` o `Facet › HDR panoramas` según corresponda. Un grupo de racha normal cuyos miembros pertenecen *todos* ya por completo a un conjunto bracket/panorama/panorama HDR no obtiene una colección Bursts separada, porque duplicaría la de Brackets/Panoramas/HDR panoramas. **Volver a ejecutar solo añade** — las fotos se añaden a una colección que vuelve a encontrar, nunca se quitan, así que una colección puede quedar desactualizada respecto a un conjunto reagrupado o redetectado más tarde (una foto que sale de un bracket en un escaneo posterior no se quita de la colección). Los nombres de colección también chocan cuando los miembros más antiguos de dos grupos distintos comparten la misma hora de captura al segundo y el mismo nombre de archivo — dos cámaras que escribieron ambas `IMG_0001` en el mismo instante terminan compartiendo una sola colección en lugar de tener una cada una. Es una limitación conocida, no un error que reportar.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (anidada bajo la opción anterior) — en vez de solo añadir, vacía y vuelve a rellenar una colección, pero solo cuando la colección Y todo su grupo caben enteramente dentro del ámbito de esta ejecución; una colección solo parcialmente cubierta (algún miembro fuera de la selección) o que apunta a una colección inteligente/no resuelta se deja intacta y se cuenta como omitida, y el resumen indica cuántas se reconstruyeron, eliminaron, omitieron y fallaron. También alcanza a una colección Facet cuyo grupo se DISOLVIÓ en esta ejecución (ya no tiene al menos 2 miembros dentro del ámbito, por lo que no hay entrada en el plan) — esa colección también se vacía y elimina, pero solo cuando cada foto que contiene fue encontrada por esta ejecución; una colección con alguna foto fuera de esta ejecución se deja intacta. Rebuild solo se ofrece — y solo se ejecuta — mientras **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** esté activada; desmarcar esa opción también desactiva Rebuild. El barrido de colecciones disueltas solo toca una colección cuyo nombre coincide exactamente con la forma que genera Facet (una fecha-hora ISO, o el prefijo sin fecha `~ (no date)`, seguido de ` – <filename>`), así que una colección que usted mismo nombró bajo un conjunto Facet nunca se vacía ni elimina. Cuando el barrido tiene algo que eliminar, el Preview añade una línea `Facet collections to delete: N`, y el barrido se ejecuta incluso cuando es el único cambio pendiente, en lugar de informarse como nada que cambiar.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — escribe la puntuación `aggregate` (p. ej. `8.4`), una banda entera (`0`-`10`), la categoría y el tipo de conjunto en los propios campos de metadatos del plugin de Facet, visibles en el panel de Metadatos y usables como criterios de texto (`sdktext:`) en el Filtro de biblioteca o en colecciones inteligentes — por ejemplo, una colección inteligente que coincida con la banda en «cualquiera de 8, 9, 10». Un campo que ya no aplica a una foto (por ejemplo, salió de un bracket, así que el tipo de conjunto desapareció) se borra en lugar de dejarse obsoleto — de lo contrario, una colección inteligente o un criterio del Filtro de biblioteca basado en ese campo seguiría coincidiendo con una foto que ya no cumple. El SDK de Adobe solo admite los campos propios de un plugin en el vocabulario de búsqueda como texto o enumeración, nunca como rango numérico, así que sigue sin haber una colección inteligente «aggregate > 8» — la banda es el sustituto de texto más cercano. Dos propiedades de seguimiento adicionales (la valoración/el pick que esta ejecución derivó) se escriben a la vez pero quedan fuera del Filtro de biblioteca y de los criterios de colección inteligente — véase la nota sobre la exportación inversa bajo [Lightroom → Facet](#lightroom--facet). **NO VERIFICADO en un catálogo real:** si un campo de metadatos sin título es realmente invisible en el panel de Metadatos y el Filtro de biblioteca no está confirmado solo con la documentación del SDK de Lightroom; las dos propiedades de seguimiento se marcan por tanto como `searchable = false, browsable = false`, el respaldo más seguro y confirmado en lugar de confiar en un comportamiento de omisión de título no confirmado — podrían seguir siendo visibles en algunas versiones de Lightroom Classic.
- **Create "Facet" keywords from Facet tags (never included on export)** — crea una palabra clave raíz `Facet` con un hijo por cada tag de Facet que lleven tus fotos, y mantiene las palabras clave hijas `Facet ›` de cada foto exactamente iguales a sus tags del manifiesto (añade y quita a medida que cambian los tags entre ejecuciones). Toda palabra clave que esta opción crea o toca tiene `Include on Export` desactivado, así que los tags automáticos de Facet nunca se filtran a una exportación JPEG/TIFF ni a una galería de cliente. Tus propias palabras clave fuera de la raíz `Facet` nunca son leídas, añadidas ni quitadas por esta opción.

**Por qué colecciones y no pilas.** El SDK de Lightroom no tiene ninguna llamada para crear o gestionar una pila (Stack) — `stackInFolder`/`stackPositionInFolder` son de solo lectura en `LrPhoto`. Una colección es el sustituto escribible más parecido, y `canReturnPrior` hace que volver a ejecutar el plugin encuentre la misma colección en lugar de duplicarla. Si quieres una pila real de Lightroom, selecciona las fotos de una colección y usa tú mismo **Foto → Apilado → Agrupar en pila** (Ctrl/Cmd+G) — el plugin no puede hacer ese paso por ti.

**Limitaciones**, con honestidad:

- **Las marcas Pick solo existen en el catálogo.** Es un diseño de Lightroom, no del plugin: Lightroom nunca escribe la marca Pick en el XMP, así que no llega a ninguna otra aplicación y se pierde si reconstruyes el catálogo a partir de los archivos. Las valoraciones en estrellas sí sobreviven, mediante **Metadatos → Guardar metadatos en el archivo**.
- **La vía de colección inteligente por campo de metadatos sigue siendo solo de texto.** El SDK de Adobe solo admite los campos propios de un plugin en el vocabulario de búsqueda como texto o enumeración (`sdktext:`); los operadores numéricos (`>`, `<`, «está en el rango») quedan reservados a los criterios integrados de Lightroom. El campo de banda anterior es el sustituto de texto más cercano a «aggregate > 8»; hacer pasar la puntuación en bruto por la **valoración en estrellas** (la opción de respaldo anterior) sigue siendo el único canal que el propio Lightroom filtra y ordena numéricamente.
- **Deshacer** funciona por lotes: el plugin escribe en bloques de 200 fotos, así que Ctrl/Cmd+Z deshace 200 fotos de una vez.
- Marca **Write facet-apply.log next to the manifest** antes de una ejecución si necesitas ver, línea a línea, qué rutas coincidieron y qué se escribió.

### Lightroom → Facet

**Valoraciones, picks y rechazos — gana Lightroom (vía el plugin).** **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** escribe `facet_lightroom_state.json` (un registro por foto: `path`, y `rating`/`pick` solo cuando todavía necesitan viajar — véase abajo) junto al manifiesto. Vuelve a incorporarlo con `python facet.py --import-lightroom facet_lightroom_state.json` (añade `--user alice` en una instalación multiusuario; ahí obligatorio) o, en el viewer, el botón **Import Lightroom state…** del diálogo **Export to editor** de la galería, que envía directamente el contenido del archivo al servidor. El valor de Lightroom gana sin condiciones para cada clave presente en un registro — el CLI y el viewer comparten el mismo importador `processing/lightroom_sync.py`, que informa de los recuentos `matched`/`unmatched`/`changed`:

| Estado de Lightroom | Resultado en Facet |
|---|---|
| Marca Pick = Seleccionada (`pick = 1`) | favorito = activado, rechazado = desactivado |
| Marca Pick = Rechazada (`pick = -1`) | favorito = desactivado, rechazado = activado |
| Marca Pick = ninguna (`pick = 0`) | favorito = desactivado, rechazado = desactivado |
| valoración en estrellas (`rating`, 0-5) | `star_rating` (`0` la borra) |

Un registro que omite `rating` o `pick` deja intacto el valor correspondiente de Facet — la exportación solo incluye una clave cuando el valor actual de Lightroom difiere del que el sentido Apply derivó por última vez para esa foto (dos propiedades ocultas y no buscables del plugin registran esa referencia), así que reexportar una foto no tocada escribe un registro vacío y no cambia nada. Una importación que cambia algo también reconstruye los pares de entrenamiento derivados de las valoraciones e impulsa el mismo reentrenamiento automático activado por inactividad que cualquier otra escritura de valoración. Las copias virtuales se deduplican hacia su original por ruta antes de la exportación, prefiriendo el original cuando existen ambos para el mismo archivo.

**Valoraciones, etiquetas y palabras clave vía XMP.** Por separado, y todavía de sentido único en esta dirección:

1. En Lightroom, selecciona las fotos y elige **Metadatos → Guardar metadatos en el archivo** (Ctrl/Cmd+S). Esto vuelca la valoración, la etiqueta y las palabras clave del catálogo en el sidecar XMP (RAW) o las incrusta directamente en el archivo (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars` (opcionalmente acotado a una ruta) las relee en la base de datos de Facet.

### Reglas de conflicto

- **Las valoraciones y etiquetas siguen la regla "gana la más reciente"**, comparando el `xmp:MetadataDate` del sidecar con el `scanned_at` de la foto (la última vez que Facet la evaluó) — no una marca de tiempo por valoración. Un sidecar más reciente que el último escaneo puede sobrescribir una valoración que cambiaste en Facet *después* de ese escaneo. Mantén simple el ida y vuelta: exportar → Lightroom lee → edición en Lightroom → Lightroom guarda → importar, sin volver a valorar en Facet entre medias.
- **Los tags y palabras clave siempre se fusionan** (unión, deduplicados) en ambas direcciones — las palabras clave de Lightroom nunca borran los tags automáticos de Facet, y viceversa.
- **Multiusuario** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): las valoraciones se enrutan a la fila `user_preferences` de Alice en lugar de a las columnas globales. Las palabras clave siguen siendo globales sea cual sea `--user` — se comparten entre usuarios.
- Ejecuta `python database.py --migrate-tags` después de `--import-sidecars` si usas la tabla de búsqueda `photo_tags`, para que los filtros de tags vean de inmediato las palabras clave fusionadas.

## Capture One

Capture One nunca escribe en el archivo original ni en un sidecar XMP sincronizado de forma continua como hace el guardado automático de Lightroom — mantiene sus propios ajustes en archivos `.cos` (Sesiones) o en su base de datos de catálogo, y su preferencia **Sync Metadata** tiene un modo bidireccional "Full Sync" que puede sobrescribir en silencio el lado que escribió en último lugar. Hacer funcionar un bucle bidireccional mediante ese ajuste arriesga perder los cambios de Facet o los de Capture One. El patrón seguro es **unidireccional, Facet → Capture One**:

1. `python facet.py --export-sidecars /ruta/a/la/sesión --embed-originals`.
2. En Capture One, deja **Preferences → General → Sync Metadata** en su valor predeterminado (no "Full Sync").
3. Selecciona las imágenes importadas, haz clic derecho y elige **Load Metadata** para traer una sola vez la valoración, la etiqueta y las palabras clave del sidecar (o de los metadatos incrustados) a los campos de catálogo de Capture One.

Trata a Facet como la fuente de verdad aguas arriba para las valoraciones y tags derivados de la IA de esa sesión: haz la importación puntual mediante `Load Metadata`, y luego toma más decisiones en Capture One sin volver a conectar su sincronización de metadatos con el sidecar de Facet. Si quieres recuperar en Facet las decisiones de Capture One, expórtalas explícitamente desde Capture One a XMP y ejecuta `--import-sidecars` sobre esa carpeta como un paso separado y deliberado en lugar de una sincronización automática — y recuerda la [trampa del nombre de los sidecars RAW](#la-trampa-del-nombre-de-los-sidecars-raw) de arriba: esto solo funciona para JPEG/HEIC/TIFF/PNG/DNG, ya que Capture One también nombra los sidecars RAW `<imagen>.xmp` en vez del `<imagen><ext>.xmp` de Facet.

## digiKam

Desde digiKam 9.1.0 (publicada el 2026-06-07), digiKam lee los sidecars XMP de forma nativa — no necesita exiftool en su lado — y busca ambas convenciones de nombre (primero `<imagen><ext>.xmp`, luego `<imagen>.xmp` como respaldo), así que encuentra los sidecars de Facet para archivos RAW sin la trampa anterior. Después de `python facet.py --export-sidecars`, abre (o actualiza) la carpeta en digiKam: recupera automáticamente la valoración, la etiqueta de color, las palabras clave y las zonas de rostro con nombre, siempre que **Settings → Configure digiKam → Metadata → Read from sidecar files** esté activado (el valor predeterminado).

### Gancho del Batch Queue Manager

Puedes integrar una reimportación de Facet en un flujo del Batch Queue Manager (BQM) de digiKam con la herramienta **Custom Script**, de modo que las fotos que valores o etiquetes en digiKam vuelvan a la base de datos de Facet sin salir de digiKam. Activa **Settings → Configure digiKam → Metadata → Write to sidecar files** para que digiKam persista tus cambios de inmediato en `<imagen>.xmp`, y luego añade una cola cuya única herramienta sea Custom Script:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` son los marcadores de posición por archivo de digiKam (el BQM ejecuta el script mediante `/bin/bash` en Linux/macOS y espera un archivo de salida, de ahí el paso `cp`). Como `--import-sidecars` recorre toda la carpeta, ejecutarlo una vez por foto en un lote grande es redundante, aunque inofensivo (es idempotente — las fotos sin cambios se omiten). Para lotes grandes, evita el gancho de BQM y simplemente ejecuta a mano `python facet.py --import-sidecars /ruta/a/la/carpeta` una vez que la cola haya terminado.

## darktable

darktable ya recibe un tratamiento de primer nivel en [Configuración — Visor](CONFIGURATION.md#visor) (perfiles/estilos de exportación `viewer.raw_processor.darktable`) y [Visor — Descarga](VIEWER.md#endpoints-de-la-api) (conversiones `type=darktable`). En el lado XMP: darktable escribe su propio `<imagen><ext>.xmp` para almacenar su historial de edición, y el escritor de sidecars de Facet, apoyado en exiftool, se fusiona en ese mismo archivo en el sitio — los nodos `darktable:history`/máscaras se conservan, nunca se sobrescriben. No hace falta una receta aparte aquí: el comportamiento bidireccional de sidecar descrito arriba para Lightroom (exportar/importar, gana la más reciente, unión de tags) se aplica del mismo modo, sin la trampa del nombre RAW, ya que darktable y Facet coinciden en `<imagen><ext>.xmp`.

**Advertencia: la recarga del XMP por parte del propio darktable no es fiable.** Independientemente de la ruta de escritura de Facet, volver a importar una imagen que darktable ya ha editado puede hacer que darktable sobrescriba el historial de edición del sidecar con uno en blanco en lugar de recargarlo — un fallo abierto en el proyecto ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), reportado el 2026-03-15) frente al que la preferencia "check for new/updated xmp files on start" no protege. Facet no es la causa (la fusión vía exiftool de arriba ya conserva `darktable:history`), pero el riesgo está justo en el paso de relectura del que depende el ida y vuelta de esta página. Solución práctica, siguiendo la misma disciplina de "una sola vez" que la receta de Capture One de arriba: después de `--export-sidecars`, no reimportes en bloque una carpeta ya editada — recarga los sidecars solo de las imágenes que Facet acaba de tocar, y comprueba que el historial de edición sigue ahí antes de confiar en el resto del lote.

## Cómo fusiona Facet

| Campo | Facet escribe | Facet relee | Regla de conflicto |
|---|---|---|---|
| Valoración (estrellas/rechazo) | `xmp:Rating` (`-1` = rechazada) | `xmp:Rating` | Gana la más reciente, vs. `scanned_at` |
| Etiqueta de color | `xmp:Label` (`Red` = rechazada, `Yellow` = favorita) | `xmp:Label` | Gana la más reciente, vs. `scanned_at` |
| Tags / palabras clave | `dc:subject` (plano, incluye los nombres de las personas de las zonas de rostro con nombre) | `dc:subject` | Siempre fusionado (unión, deduplicado) |
| Tags jerárquicos | `lr:hierarchicalSubject` (`Category\|<cat>`, `People\|<nombre>`) | No se reimporta | Solo exportación |
| Leyenda | `dc:description` (+ `IPTC:Caption-Abstract` vía exiftool) | No se reimporta | Solo exportación |
| Zonas de rostro con nombre | `mwg-rs:RegionList` MWG (centrada-normalizada, `Type=Face`) | No se reimporta | Solo exportación; leída de forma nativa por digiKam, **no** leída por Lightroom (una limitación conocida de Adobe — Lightroom solo consume las zonas MWG que él mismo escribió) |

Consulta [Comandos — Vista previa y exportación](COMMANDS.md#vista-previa-y-exportación) para la referencia completa de la CLI (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).
