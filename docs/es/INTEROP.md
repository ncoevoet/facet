# Recetas de interoperabilidad con editores

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · **Español** · [Português](../pt/INTEROP.md)

Recetas prácticas, paso a paso, para hacer circular en ambos sentidos las valoraciones, etiquetas de color y tags de Facet con los editores externos y las herramientas de gestión de fototeca (DAM) que los fotógrafos usan de verdad. Esta página asume que ya sabes *que* Facet escribe XMP — consulta [Comandos — Vista previa y exportación](COMMANDS.md#vista-previa-y-exportación) para la referencia completa de las opciones `--export-sidecars` / `--import-sidecars` y la correspondencia de campos (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## La trampa del nombre de los sidecars RAW

Facet nombra un sidecar `<imagen><ext>.xmp` — por ejemplo `IMG_1234.CR2.xmp` junto a `IMG_1234.CR2` — la misma convención que usan darktable y digiKam. **Lightroom Classic y Capture One esperan lo contrario: `IMG_1234.xmp`, sin la extensión RAW.** Ninguno de los dos detectará un sidecar escrito por Facet para un archivo RAW propietario (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — todo salvo el DNG), y el `--import-sidecars` de Facet tampoco encontrará un sidecar escrito por una aplicación del ecosistema Adobe para ese mismo RAW. Es un desajuste de convenciones de nombre entre ecosistemas, no un fallo de ninguno de los dos lados.

Esto **no** afecta a:
- **JPEG, HEIC, TIFF, PNG, DNG** — pasa `--embed-originals` y Facet escribe los metadatos *directamente en el archivo* (vía exiftool), así que no hay ningún nombre de sidecar que Lightroom/Capture One puedan pasar por alto.
- **digiKam** — comprueba ambas convenciones de nombre y encuentra el sidecar de Facet en cualquier caso (ver [digiKam](#digikam) más abajo).
- **darktable** — usa la misma convención `<imagen><ext>.xmp` que Facet (ver [darktable](#darktable) más abajo).

Así que, para un flujo con Lightroom o Capture One: usa `--embed-originals` para todo lo que no sea RAW propietario, y espera que el ida y vuelta por sidecar quede en silencio (sin error, simplemente no se lee nada) para los archivos RAW puros. Si disparas en RAW+JPEG, el JPEG acompañante es el vehículo práctico de interoperabilidad — el RAW se queda en el disco, intacto, mientras la base de datos de Facet conserva la valoración que hace autoridad.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (añade una ruta para acotar el alcance, por ejemplo `--export-sidecars /fotos/boda-2026`). Añade `--embed-originals` para además escribir directamente en archivos JPEG/HEIC/TIFF/PNG/DNG.
2. En el módulo Biblioteca de Lightroom Classic, selecciona las fotos (Ctrl/Cmd+A para todas) y elige **Metadatos → Leer metadatos del archivo**. Lightroom sobrescribe la valoración, la etiqueta de color y las palabras clave de su catálogo a partir del sidecar (o de los metadatos incrustados, para los formatos anteriores).

El marcador de rechazo de Facet (`xmp:Rating = -1`) se relee como la marca de Rechazo de Lightroom. Un favorito de Facet escribe `xmp:Label = Yellow`, que Lightroom muestra como **etiqueta de color Amarilla** — no como la marca de Selección (Pick). Si tu flujo de Lightroom se basa en las marcas Pick en lugar de las etiquetas de color, añade un paso de conversión etiqueta-de-color → pick, o filtra en su lugar por la etiqueta Amarilla.

### Lightroom → Facet

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

digiKam lee los sidecars XMP de forma nativa — no necesita exiftool en su lado — y busca ambas convenciones de nombre (primero `<imagen><ext>.xmp`, luego `<imagen>.xmp` como respaldo), así que encuentra los sidecars de Facet para archivos RAW sin la trampa anterior. Después de `python facet.py --export-sidecars`, abre (o actualiza) la carpeta en digiKam: recupera automáticamente la valoración, la etiqueta de color, las palabras clave y las zonas de rostro con nombre, siempre que **Settings → Configure digiKam → Metadata → Read from sidecar files** esté activado (el valor predeterminado).

### Gancho del Batch Queue Manager

Puedes integrar una reimportación de Facet en un flujo del Batch Queue Manager (BQM) de digiKam con la herramienta **Custom Script**, de modo que las fotos que valores o etiquetes en digiKam vuelvan a la base de datos de Facet sin salir de digiKam. Activa **Settings → Configure digiKam → Metadata → Write to sidecar files** para que digiKam persista tus cambios de inmediato en `<imagen>.xmp`, y luego añade una cola cuya única herramienta sea Custom Script:

```bash
#!/bin/bash
python /ruta/a/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` son los marcadores de posición por archivo de digiKam (el BQM ejecuta el script mediante `/bin/bash` en Linux/macOS y espera un archivo de salida, de ahí el paso `cp`). Como `--import-sidecars` recorre toda la carpeta, ejecutarlo una vez por foto en un lote grande es redundante, aunque inofensivo (es idempotente — las fotos sin cambios se omiten). Para lotes grandes, evita el gancho de BQM y simplemente ejecuta a mano `python facet.py --import-sidecars /ruta/a/la/carpeta` una vez que la cola haya terminado.

## darktable

darktable ya recibe un tratamiento de primer nivel en [Configuración — Visor](CONFIGURATION.md#visor) (perfiles/estilos de exportación `viewer.raw_processor.darktable`) y [Visor — Descarga](VIEWER.md#endpoints-de-la-api) (conversiones `type=darktable`). En el lado XMP: darktable escribe su propio `<imagen>.xmp` para almacenar su historial de edición, y el escritor de sidecars de Facet, apoyado en exiftool, se fusiona en ese mismo archivo en el sitio — los nodos `darktable:history`/máscaras se conservan, nunca se sobrescriben. No hace falta una receta aparte aquí: el comportamiento bidireccional de sidecar descrito arriba para Lightroom (exportar/importar, gana la más reciente, unión de tags) se aplica del mismo modo, sin la trampa del nombre RAW, ya que darktable y Facet coinciden en `<imagen><ext>.xmp`.

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
