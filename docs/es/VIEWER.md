# Galería web

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · **Español**

Aplicación de página única FastAPI + Angular para explorar, filtrar y gestionar fotos.

## Contenido

- [Iniciar la galería](#iniciar-la-galería) · [Autenticación](#autenticación) · [Opciones de filtrado](#opciones-de-filtrado) · [Ordenación](#ordenación) · [Funciones de la galería](#funciones-de-la-galería)
- [Gestión de personas](#gestión-de-personas) · [Disparador de escaneo (superadmin)](#disparador-de-escaneo-superadmin) · [Búsqueda semántica](#búsqueda-semántica) · [Álbumes](#álbumes)
- [Crítica con IA](#crítica-con-ia) · [Generación de leyendas con IA](#generación-de-leyendas-con-ia-gpu-16gb24gb-edition) · [Recuerdos ("En este día")](#recuerdos-en-este-día) · [Vista de cronología](#vista-de-cronología) · [Vista de mapa](#vista-de-mapa) · [Cápsulas](#cápsulas)
- [Vista de carpetas](#vista-de-carpetas) · [Diálogo de filtro GPS](#diálogo-de-filtro-gps) · [Sugerencias de fusión](#sugerencias-de-fusión) · [Exportación al editor](#exportación-al-editor) · [Selección](#selección) · [Modo de comparación por pares](#modo-de-comparación-por-pares)
- [Estadísticas EXIF](#estadísticas-exif) · [Atajos de teclado](#atajos-de-teclado-galería) · [Deshacer](#deshacer) · [Aplicación web progresiva](#aplicación-web-progresiva) · [Móvil](#móvil)
- [Configuración](#configuración) · [Rendimiento](#rendimiento) · [Endpoints de la API](#endpoints-de-la-api) · [Resolución de problemas](#resolución-de-problemas)

> Los **requisitos de cada función** están etiquetados en línea: `[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` (contraseña de edición) · `[Superadmin]`. Consulta la [matriz de funciones](../README.md#feature-availability--requirements).

## Iniciar la galería

### Producción

```bash
python viewer.py
# Abre http://localhost:5000
```

Esto sirve tanto la API como la aplicación Angular precompilada en un único puerto.

Para mayor rendimiento, ejecútalo en modo producción (Uvicorn, sin recarga automática). Añade `--workers N` para escalar (predeterminado 1):

```bash
python viewer.py --production --workers 4
```

### Desarrollo

Ejecuta el servidor de la API y el servidor de desarrollo de Angular por separado:

```bash
# Terminal 1: servidor de la API
python viewer.py
# API disponible en http://localhost:5000

# Terminal 2: servidor de desarrollo de Angular con recarga en caliente
cd client && npx ng serve
# Abre http://localhost:4200 (redirige las llamadas a la API a :5000)
```

## Autenticación

### Modo de usuario único (predeterminado)

Protección opcional por contraseña a través de la configuración:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Cuando se establece, los usuarios deben autenticarse antes de acceder a la galería. Una `edition_password` opcional otorga acceso a la gestión de personas y al modo de comparación.

### Modo multiusuario

Para escenarios de NAS familiar donde cada miembro tiene directorios de fotos privados. Se habilita añadiendo una sección `users` a `scoring_config.json`:

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

Los usuarios se crean únicamente desde la CLI (no hay interfaz de registro):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Consulta [Configuración](CONFIGURATION.md#users) para la referencia completa.

### Roles

| Rol | Ver propias + compartidas | Valorar/favorito | Gestionar personas/rostros | Lanzar escaneos |
|------|:-:|:-:|:-:|:-:|
| `user` | sí | sí | no | no |
| `admin` | sí | sí | sí | no |
| `superadmin` | sí | sí | sí | sí |

### Visibilidad de las fotos

Cada usuario ve las fotos de sus directorios configurados más los directorios compartidos. La visibilidad se aplica en todos los endpoints: galería, miniaturas, descargas, estadísticas, opciones de filtro y páginas de personas.

### Valoraciones por usuario

En modo multiusuario, las valoraciones por estrellas, los favoritos y las marcas de rechazo se almacenan por usuario en la tabla `user_preferences`. Cada usuario valora de forma independiente: los favoritos de Alice no afectan a la vista de Bob.

Para migrar las valoraciones existentes de usuario único:

```bash
python database.py --migrate-user-preferences --user alice
```

## Opciones de filtrado

<p align="center"><img src="../screenshots/filter-sidebar-full.jpg" alt="Barra lateral de filtros con todas las secciones desplegadas" width="360"></p>

### Filtros principales

| Filtro | Opciones |
|--------|---------|
| **Tipo de foto** | Selección destacada, Retratos, Personas en escena, Paisajes, Arquitectura, Naturaleza, Animales, Arte y estatuas, Blanco y negro, Baja iluminación, Siluetas, Macro, Astrofotografía, Callejera, Larga exposición, Aérea y dron, Conciertos |
| **Nivel de calidad** | Buena (6+), Estupenda (7+), Excelente (8+), Mejor (9+) |
| **Cámara y objetivo** | Filtrado por equipo |
| **Persona** | Filtrar por persona reconocida |
| **Categoría** | Filtrar por categoría de foto |

### Filtros avanzados

| Categoría | Filtros |
|----------|---------|
| **Fecha** | Fecha de inicio y de fin |
| **Puntuaciones** | Global, estética, puntuación TOPIQ, puntuación de calidad |
| **Calidad extendida** | Estética IAA (mérito artístico), Calidad facial IQA, puntuación LIQE |
| **Métricas faciales** | Calidad facial, nitidez ocular, nitidez facial, proporción facial, confianza facial, cantidad de rostros |
| **Composición** | Puntuación de composición, puntos de fuerza, líneas guía, aislamiento, patrón de composición |
| **Saliencia del sujeto** | Nitidez del sujeto, prominencia del sujeto, ubicación del sujeto, separación del fondo |
| **Técnico** | Nitidez, contraste, rango dinámico, nivel de ruido |
| **Color** | Puntuación de color, saturación, luminancia, dispersión del histograma; temperatura de color (cálida/fría/neutra) y agrupación de tono (requiere `--recompute-colors`) |
| **Exposición** | Puntuación de exposición |
| **Valoraciones del usuario** | Valoración por estrellas |
| **Ajustes de cámara** | ISO, apertura (control deslizante de rango de F-Stop), distancia focal (control deslizante de rango) |
| **Contenido** | Etiquetas, alternancia de monocromo |

### Patrones de composición

Filtrar por los patrones detectados por SAMP-Net:
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Ordenación

Columnas ordenables agrupadas por categoría (desde `viewer.sort_options`):

| Grupo | Columnas |
|-------|---------|
| **General** | Puntuación global, Estética, Puntuación de calidad, Fecha de captura, Valoración por estrellas, Estética (IAA), Puntuación LIQE |
| **Métricas faciales** | Calidad facial, Calidad facial (IQA), Nitidez ocular, Nitidez facial, Proporción facial, Cantidad de rostros |
| **Técnico** | Nitidez técnica, Contraste, Nivel de ruido |
| **Color** | Puntuación de color, Saturación |
| **Exposición** | Puntuación de exposición, Luminancia media, Dispersión del histograma, Rango dinámico |
| **Composición** | Puntuación de composición, Puntuación de puntos de fuerza, Líneas guía, Bonificación de aislamiento, Patrón de composición |
| **Saliencia del sujeto** | Nitidez del sujeto, Prominencia del sujeto, Ubicación del sujeto, Separación del fondo |

## Funciones de la galería

### Tarjetas de foto

- Miniatura con insignia de puntuación
- Etiquetas en las que se puede hacer clic para filtrar rápidamente
- Avatares de personas para los rostros reconocidos
- Insignia de categoría

### Selección múltiple y acciones por lotes

- Haz clic en las fotos para seleccionarlas, Mayús+Clic para seleccionar un rango
- Aparece una barra de acciones con el recuento de la selección y las acciones disponibles
- **Favorito** — Marca todas las seleccionadas como favoritas (elimina el rechazo)
- **Rechazar** — Marca todas las seleccionadas como rechazadas (elimina el favorito y la valoración)
- **Valorar** — Establece la valoración por estrellas (1–5) para todas las seleccionadas, o borra la valoración
- **Añadir al álbum** — Añade las seleccionadas a un álbum existente o nuevo
- **Copiar nombres de archivo** — Copia los nombres de archivo seleccionados al portapapeles
- **Exportar** — Escribe sidecars XMP (valoración/favorito/rechazo) junto a los archivos seleccionados (consulta [Exportación al editor](#exportación-al-editor))
- **Descargar** — Descarga las fotos seleccionadas
- Borra la selección con Escape o el botón Borrar

Las acciones por lotes requieren el modo de edición. Haz doble clic en cualquier foto para descargarla directamente.

### Opciones de visualización

- **Modo de disposición** - Alterna entre **Cuadrícula** (tarjetas uniformes) y **Mosaico** (filas justificadas que conservan las proporciones). El mosaico es solo para escritorio; el móvil siempre usa la cuadrícula.
- **Tamaño de miniatura** - Control deslizante para ajustar la altura de las tarjetas/filas (120–400 px, persistido en localStorage)
- **Ocultar detalles** - Oculta los metadatos de la foto en las tarjetas (solo en modo cuadrícula)
- **Ocultar tooltip** - Desactiva el tooltip que muestra los detalles de la foto al pasar el ratón en escritorio
- **Ocultar parpadeos** - Filtra las fotos con parpadeos detectados
- **Mejor de ráfaga** - Muestra solo la foto mejor puntuada de cada ráfaga
- **Desplazamiento infinito** - Las fotos se cargan a medida que te desplazas
- **Desplazamiento rápido (virtualizado)** - Renderizado por ventana de filas: solo las
  filas cercanas al viewport están en el DOM, de modo que desplazarse en
  profundidad por decenas de miles de fotos sigue siendo fluido. Activado por
  defecto; desactívalo en la sección Visualización de la barra lateral de filtros
  si tienes problemas de disposición (el modo cuadrícula con detalles mostrados
  siempre usa el renderizado completo, ya que ahí las alturas de fila no son
  deterministas). Persistido en localStorage (`facet_virtual_scroll`).

### Fotos similares

Haz clic en el botón "Similares" de cualquier foto para elegir un modo de similitud:

- **Visual** (predeterminado) — distancia de Hamming de pHash (70%) + similitud coseno de CLIP/SigLIP (30%). Recurre a solo CLIP cuando no hay pHash disponible.
- **Color** — Intersección de histograma (70%) + distancia de saturación (10%) + distancia de luminancia (10%) + bonificación de monocromo (10%). Prefiltra por la marca de monocromo y el rango de saturación.
- **Persona** — Encuentra fotos que contienen la(s) misma(s) persona(s). Usa `person_id` cuando está disponible (rápido); de lo contrario recurre a la similitud coseno de los embeddings faciales.

Usa el **control deslizante de umbral de similitud** (0–90%) para controlar cuán estricta es la coincidencia (no se muestra en el modo persona). El panel admite desplazamiento infinito para grandes conjuntos de resultados.

### Chips de filtro

Los filtros activos se muestran como chips eliminables con recuentos en la parte superior de la galería.

## Gestión de personas

> La exploración de personas está abierta a todos los visualizadores; renombrar, fusionar, cambiar avatares y asignar rostros requiere `[Edition]`.

### Filtro de personas

El desplegable muestra las personas con miniaturas de rostros. Haz clic para filtrar la galería.

### Galería de una persona

Haz clic en el nombre de una persona para ver todas sus fotos en `/person/<id>`.

### Página de gestión de personas

Acceso mediante el botón de la cabecera o `/persons`:

| Acción | Cómo hacerlo |
|--------|--------|
| **Fusionar** | Selecciona la persona de origen, haz clic en la de destino, confirma |
| **Eliminar** | Haz clic en el botón de eliminar en la tarjeta de la persona |
| **Renombrar** | Haz clic en el nombre de la persona para editarlo en línea |
| **Dividir** | Abre los rostros de una persona, selecciona un subconjunto y divídelos en una nueva persona |
| **Ocultar** | Oculta un grupo de la lista de personas, los filtros y las sugerencias de fusión (reversible) |

## Disparador de escaneo (superadmin)

Cuando `viewer.features.show_scan_button` es `true` y el usuario tiene el rol `superadmin`, aparece un botón de escaneo en la cabecera de la galería.

- Selecciona los directorios a escanear en el modal
- El escaneo se ejecuta como un subproceso en segundo plano (`facet.py`)
- Solo un escaneo a la vez (bloqueo global)
- El progreso se muestra en un área de salida de estilo terminal

Esto resulta útil cuando la galería se ejecuta en la misma máquina que tiene acceso a la GPU para la puntuación.

## Búsqueda semántica

Búsqueda híbrida que combina la similitud de embeddings de CLIP/SigLIP (70%) con la coincidencia de texto FTS5 BM25 en leyendas y etiquetas (30%). Escribe una consulta como "atardecer sobre las montañas" o "niño jugando en la nieve" y la galería devuelve las fotos coincidentes ordenadas por la puntuación combinada.

- Requiere datos de `clip_embedding` almacenados (calculados durante la puntuación)
- Usa sqlite-vec para la búsqueda vectorial KNN cuando está instalado; recurre a NumPy en memoria
- La búsqueda de texto FTS5 en las leyendas/etiquetas de IA proporciona coincidencias adicionales por palabra clave (ejecuta `database.py --rebuild-fts` para habilitarla)
- Usa el mismo modelo de embeddings que el perfil de VRAM activo (SigLIP 2 para 16gb/24gb, CLIP ViT-L-14 para legacy/8gb)
- `scope=text` restringe la consulta a coincidencias literales de FTS5 en el texto OCR/leyenda y omite la búsqueda de embeddings
- Controlada por `viewer.features.show_semantic_search` (predeterminado: `true`)

## Álbumes

Organiza las fotos en álbumes con nombre. Acceso a través de la ruta `/albums`.

### Álbumes manuales

Crea álbumes y añade fotos desde la galería mediante la selección múltiple. Los álbumes admiten:
- Nombre y descripción
- Foto de portada personalizada
- Orden personalizado
- Explorar el contenido del álbum en `/album/:albumId`

### Álbumes inteligentes

Guarda una combinación de filtros (cámara, etiqueta, persona, rango de fechas, umbrales de puntuación, etc.) como un álbum inteligente. Los álbumes inteligentes se actualizan dinámicamente a medida que nuevas fotos coinciden con los criterios de filtro guardados. La combinación de filtros se almacena como JSON en `smart_filter_json`.

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/albums` | Listar todos los álbumes |
| `POST /api/albums` | Crear álbum |
| `GET /api/albums/{id}` | Obtener los detalles del álbum |
| `PUT /api/albums/{id}` | Actualizar el álbum (nombre, descripción, portada) |
| `DELETE /api/albums/{id}` | Eliminar el álbum |
| `GET /api/albums/{id}/photos` | Listar las fotos del álbum (admite `page`, `per_page`, `sort`, `sort_direction`) |
| `POST /api/albums/{id}/photos` | Añadir fotos al álbum |
| `DELETE /api/albums/{id}/photos` | Quitar fotos del álbum |

Controlado por `viewer.features.show_albums` (predeterminado: `true`).

### Compartir fotos

Comparte álbumes con usuarios externos mediante enlaces con token. No se requiere autenticación para ver los álbumes compartidos.

| Acción | Cómo hacerlo |
|--------|--------|
| **Compartir** | Abre el álbum y haz clic en el botón "Compartir" para generar un enlace compartible |
| **Revocar** | Haz clic en "Dejar de compartir" para invalidar el token de compartición |
| **Ver** | Los destinatarios abren el enlace para explorar el álbum compartido en `/shared/album/:id` |

### API

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/albums/{id}/share` | Generar el token de compartición del álbum |
| `DELETE /api/albums/{id}/share` | Revocar el token de compartición |
| `GET /api/shared/album/{id}?token=` | Ver el álbum compartido (no requiere autenticación) |

## Crítica con IA

Desglosa las puntuaciones de una foto en fortalezas, debilidades y sugerencias.

### Crítica basada en reglas

Disponible en todos los perfiles de VRAM. Analiza las métricas almacenadas (estética, composición, nitidez, calidad facial, etc.) y genera una explicación estructurada de la puntuación.

### Crítica VLM `[GPU]` `[16gb/24gb]`

Usa el VLM configurado (Qwen3.5-2B o Qwen3.5-4B) para una crítica que tiene en cuenta el contexto. Requiere el perfil de VRAM de 16gb o 24gb y `viewer.features.show_vlm_critique: true`.

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/critique?path=<photo_path>&mode=rule` | Desglose de puntuación basado en reglas |
| `GET /api/critique?path=<photo_path>&mode=vlm` | Crítica con tecnología VLM (requiere GPU) |

Controlada por `viewer.features.show_critique` (predeterminado: `true`) y `viewer.features.show_vlm_critique` (predeterminado: `true`).

## Generación de leyendas con IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtén una leyenda en lenguaje natural generada por IA para cualquier foto. Las leyendas se generan en la primera solicitud y se almacenan en caché en la columna de base de datos `caption`. Las leyendas pueden editarse manualmente en modo edición desde la página de detalle de la foto. (La *traducción* de leyendas se ejecuta en la CPU — ver más abajo.)

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/caption?path=<photo_path>` | Obtener o generar la leyenda de una foto |
| `PUT /api/caption` | Actualizar el texto de la leyenda (requiere modo edición) |

También disponible vía CLI para la generación y traducción por lotes:

```bash
python facet.py --generate-captions      # Generar descripciones para todas las fotos sin descripción
python facet.py --translate-captions     # Traducir las descripciones al idioma de destino configurado
```

La traducción de leyendas usa MarianMT (CPU, no requiere GPU). Configura el idioma de destino en `scoring_config.json` bajo `translation.target_language` (predeterminado: `"fr"`). Idiomas admitidos: francés, alemán, español, italiano.

Controlada por `viewer.features.show_captions` (predeterminado: `true`). Requiere el perfil de VRAM de 16gb o 24gb para la generación de leyendas basada en VLM.

## Recuerdos ("En este día")

Explora las fotos tomadas en la misma fecha del calendario en años anteriores. Un diálogo de recuerdos muestra una retrospectiva año a año de las fotos coincidentes.

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/memories?date=YYYY-MM-DD` | Obtener las fotos tomadas en esta fecha en años anteriores |

Controlada por `viewer.features.show_memories` (predeterminado: `true`).

## Flujos de trabajo habituales

- **Seleccionar las de unas vacaciones** — abre Cápsulas → busca la cápsula `journey` autogenerada para las fechas del viaje. Cada cápsula ofrece una acción de guardar como álbum.
- **Hacer una revisión día a día** — abre Cronología → ordena por global → recorre el año. Las mejores tomas suben primero cuando has activado `hide_bursts` y `hide_duplicates` (predeterminados: activados).
- **Mostrar lo oculto** — la galería oculta por defecto los parpadeos / las ráfagas no principales / los duplicados no principales. Cuando al menos uno de esos filtros está activo y excluiría filas, aparece sobre la cuadrícula un banner "N fotos ocultas por los filtros actuales · Mostrar todas".

## Vista de cronología

Explorador cronológico de fotos con navegación por fechas. Desplázate por las fotos organizadas por fecha con una barra lateral que muestra los años y meses disponibles.

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/timeline?cursor=&limit=&direction=` | Fotos paginadas de la cronología con navegación basada en cursor |
| `GET /api/timeline/dates?year=&month=` | Fechas disponibles para la navegación por año/mes |

Acceso a través de la ruta `/timeline`. Controlada por `viewer.features.show_timeline` (predeterminado: `true`).

## Vista de mapa

Visualiza las fotos en un mapa interactivo basado en las coordenadas GPS extraídas de los datos EXIF. Usa Leaflet para renderizar el mapa con agrupación en distintos niveles de zoom.

### Configuración

Extrae las coordenadas GPS de las fotos existentes:

```bash
python facet.py --extract-gps    # Extraer la latitud/longitud GPS de EXIF a la base de datos
```

Las coordenadas GPS también se extraen automáticamente durante la puntuación de las fotos nuevas.

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/photos/map?bounds=&zoom=&limit=` | Fotos dentro de los límites del mapa (agrupadas por zoom) |
| `GET /api/photos/map/count` | Recuento total de fotos geoetiquetadas |

Acceso a través de la ruta `/map`. Controlada por `viewer.features.show_map` (predeterminado: `true`).

## Cápsulas

Diaporamas (pases de diapositivas) de fotos curadas agrupadas por tema. Acceso a través de la ruta `/capsules`.

### Tipos de cápsula

Las cápsulas se autogeneran a partir de tu biblioteca usando múltiples algoritmos:

- **Viaje** — viajes detectados mediante la agrupación de GPS, con nombres de destino obtenidos por geocodificación inversa ("Viaje a Roma — marzo de 2025")
- **Momentos con [Persona]** — las mejores fotos de cada persona reconocida
- **Paleta estacional** — fotos agrupadas por estación + año
- **Colección dorada** — el 1% superior por puntuación global
- **Historia de color** — grupos visualmente similares mediante la agrupación de embeddings de CLIP
- **Esta semana, hace años** — un "En este día" extendido a ±3 días
- **Ubicación** — grupos de fotos geoetiquetadas con nombres de lugares
- **Favoritas** — fotos marcadas como favoritas agrupadas por año y estación
- **Basadas en dimensiones** — autogeneradas a partir de cámara, objetivo, categoría, patrón de composición, rango de distancia focal, hora del día, valoración por estrellas y combinaciones interdimensionales

### Pase de diapositivas

Haz clic en cualquier tarjeta de cápsula para iniciar un pase de diapositivas. Funciones:
- **Transiciones temáticas** — slide (viajes), zoom (retratos), kenburns (dorada/estacional), crossfade (predeterminada)
- **Encadenamiento automático** — cuando una cápsula termina, una tarjeta de transición muestra la siguiente cápsula antes de continuar
- **Mezclar y reanudar** — las fotos se mezclan para variar; la posición de reanudación se registra por cápsula
- **Agrupación adaptativa** — las fotos en formato retrato se agrupan lado a lado según la relación de aspecto del viewport
- **Guardar como álbum** — guarda cualquier cápsula como un álbum permanente

### Frescura

Las cápsulas rotan según un calendario configurable (predeterminado: 24 horas). Las fotos de portada y las cápsulas de descubrimiento sembradas se alinean con el mismo periodo de rotación. El botón "Regenerar" de la cabecera fuerza una actualización inmediata.

### Geocodificación inversa

Las cápsulas de ubicación y de viaje muestran nombres de lugares (p. ej. "París, Francia") en lugar de coordenadas. Esto usa geocodificación sin conexión a través del paquete `reverse_geocoder` — no se necesitan llamadas a la API. Los resultados se almacenan en caché en la base de datos.

Instalar: `pip install reverse_geocoder`

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/capsules` | Lista paginada de cápsulas (en caché) |
| `GET /api/capsules/{id}/photos` | Fotos de una cápsula específica |
| `POST /api/capsules/{id}/save-album` | Guardar la cápsula como álbum (modo edición) |

### Configuración

Consulta [Configuración — Cápsulas](CONFIGURATION.md#capsules) para todos los ajustes.

## Vista de carpetas

Explora tu biblioteca de fotos por la estructura de directorios. Acceso a través de la ruta `/folders`.

- Navegación por migas de pan para subir por el árbol de directorios
- Cada carpeta muestra una foto de portada (la imagen mejor puntuada de ese directorio)
- Haz clic en una carpeta para entrar en ella, o haz clic en una foto para abrirla en la galería
- Respeta la visibilidad de directorios por usuario en modo multiusuario

## Diálogo de filtro GPS

Filtra las fotos por ubicación geográfica usando un selector de mapa interactivo:

- Haz clic en el botón de filtro de ubicación para abrir el diálogo del mapa
- Haz clic o arrastra en el mapa para fijar un punto central
- Ajusta el control deslizante de radio para controlar el área de búsqueda
- Las fotos dentro del radio seleccionado se filtran en la galería
- Requiere coordenadas GPS (ejecuta `--extract-gps` si las fotos tienen datos GPS en EXIF)

## Sugerencias de fusión

Encuentra grupos de personas que podrían ser el mismo individuo. Acceso a través de `/merge-suggestions` o desde la página de gestión de personas.

- **Control deslizante de umbral de similitud** — cuán parecidas deben verse dos personas para ser sugeridas (más bajo = más sugerencias, más alto = menos)
- **Fusionar** — acepta una sugerencia para fusionar las dos personas
- **Fusión por lotes** — selecciona varias sugerencias y fusiónalas a la vez
- Las sugerencias descartadas se recuerdan y no se vuelven a proponer
- También disponible vía CLI: `python facet.py --suggest-person-merges`

## Exportación al editor

Escribe tus valoraciones, favoritos y rechazos en disco como sidecars XMP, para que los editores externos (darktable, Lightroom) los recojan. Requiere el modo edición.

- **Desde la galería** — selecciona fotos, luego **Acciones → Exportar** escribe un sidecar junto a cada archivo.
- **Desde un álbum** ("cesta") — exporta todo el álbum como sidecars, o copia/crea enlaces simbólicos de los archivos en un directorio de destino.

### API

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/photo/export_xmp` | Escribir un sidecar XMP (`path`, opcional `overwrite`) |
| `POST /api/export/sidecars` | Escribir sidecars para `paths` explícitos o un conjunto de filtros |
| `POST /api/albums/{id}/export` | Exportación de álbum — `mode` = `sidecars`, `copy` o `symlink` (los dos últimos necesitan `target_dir`) |

## Selección

La página de selección (`/culling`, modo edición) agrupa tomas casi idénticas para que puedas conservar la mejor de cada una y rechazar el resto. Dos fuentes de grupos:

- **Ráfaga** — fotos tomadas muy próximas en el tiempo (de la detección de ráfagas).
- **Similares** — fotos que se parecen independientemente de cuándo se tomaron, agrupadas por la similitud de embeddings de CLIP/SigLIP. Un control deslizante de umbral controla cuán estricta es la agrupación.

Para cada grupo, elige la(s) que conservar; al confirmar se rechaza el resto. Las confirmaciones se difieren y pueden deshacerse (consulta [Deshacer](#deshacer)).

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/burst-groups` | Grupos de ráfaga para la selección |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Grupos paginados de fotos visualmente similares |
| `GET /api/culling-groups` | Grupos combinados de ráfaga y similares |
| `POST /api/culling-groups/confirm` | Confirmar las selecciones de selección |

## Modo de comparación por pares

Clasifica las fotos juzgándolas de dos en dos. Los votos acumulados alimentan el ajuste de pesos. Acceso a través de la ruta `/compare` (botón Comparar en la cabecera). Requiere una `edition_password` no vacía (usuario único) o el rol `admin`/`superadmin` (multiusuario).

La página tiene cuatro pestañas:

### Pestaña Comparar A/B

Pares de fotos lado a lado. Elige un ganador, marca un empate u omite. Una barra de progreso registra los votos hacia 50, con recuentos en curso de victorias A/victorias B/empates. Un filtro de categoría acota la sesión, y un desplegable de estrategia de selección controla cómo se eligen los pares.

| Estrategia | Descripción |
|----------|-------------|
| `uncertainty` | Fotos con puntuaciones similares (las más informativas) |
| `boundary` | Rango de puntuación 6–8 (zona ambigua) |
| `active` | Fotos con menos comparaciones (asegura la cobertura) |
| `random` | Pares aleatorios (referencia) |

**Atajos de teclado:**

| Tecla | Acción |
|-----|--------|
| `A` | Gana la foto de la izquierda |
| `B` | Gana la foto de la derecha |
| `T` | Empate |
| `S` | Omitir par |
| `Escape` | Cerrar el modal de anulación de categoría |

### Pestaña Sugerencias de pesos

Muestra los pesos aprendidos de las comparaciones frente a los pesos actuales, lado a lado, con la precisión del modelo antes/después. Las 10 fotos principales actuales y las 10 principales previstas tras el recálculo se previsualizan en columnas adyacentes. **Aplicar** escribe los pesos sugeridos; **Recalcular** vuelve a puntuar la categoría para aplicarlos (ambos requieren el modo edición).

### Pestaña Pesos

Editor manual de pesos: un control deslizante por métrica para la categoría seleccionada con una vista previa de puntuación en vivo. **Guardar** escribe en `scoring_config.json` (con una copia de seguridad); **Recalcular puntuaciones** los aplica; **Restablecer** recarga los pesos almacenados.

### Pestaña Instantáneas

Guarda los pesos actuales como una instantánea con nombre y restaura cualquier instantánea anterior.

### Anulación de categoría

Para reasignar la categoría de una foto desde la vista de comparación: edita la insignia de categoría, selecciona una categoría de destino, ejecuta "Analizar conflictos de filtros" para ver qué filtros la excluyen y luego aplica la anulación.

## Estadísticas EXIF

La página de estadísticas (`/stats`) ofrece análisis en 5 pestañas. Usa los selectores de **categoría** y **rango de fechas** de la barra de herramientas para filtrar todos los gráficos a un subconjunto específico de tu biblioteca.

### Pestañas

| Pestaña | Descripción |
|-----|-------------|
| **Equipo** | Cuerpos de cámara, objetivos y combinaciones (los 20 principales de cada uno) |
| **Ajustes de disparo** | Distribuciones de ISO, apertura, distancia focal y velocidad de obturación |
| **Cronología** | Fotos a lo largo del tiempo |
| **Categorías** | Análisis de categorías, gestión de pesos y correlaciones de puntuación |
| **Correlaciones** | Gráficos de correlación de métricas X/Y personalizados con agrupación |

### Pestaña Categorías

Cuatro subpestañas:

| Subpestaña | Descripción |
|---------|-------------|
| **Desglose** | Recuento de fotos por categoría, puntuaciones promedio, histogramas de distribución de puntuación |
| **Pesos** | Comparación de gráfico radar (hasta 5 categorías), mapa de calor de pesos y editor de pesos (modo edición) |
| **Correlaciones** | Mapa de calor de correlación de Pearson que muestra cómo influye cada dimensión en la puntuación global, vista detallada al hacer clic |
| **Solapamiento** | Análisis de solapamiento de filtros que muestra qué categorías comparten fotos coincidentes |

Cada gráfico tiene un botón de ayuda `?` conmutable que explica cómo leerlo. Una alternancia de ayuda global en la barra de subpestañas muestra las explicaciones de todas las subpestañas.

### Editor de pesos (modo edición)

Disponible en la subpestaña Pesos cuando el modo edición está activo:

1. Selecciona una categoría del desplegable
2. Ajusta los controles deslizantes de peso (uno por métrica, deberían sumar 100%)
3. Usa "Normalizar a 100" para autoequilibrar
4. Despliega la sección colapsable de Modificadores para ajustar las bonificaciones/penalizaciones
5. La **Vista previa de distribución de puntuación** muestra un histograma antes/después en vivo a medida que mueves los controles
6. Haz clic en **Guardar** para actualizar `scoring_config.json` (crea una copia de seguridad con marca de tiempo)
7. Haz clic en **Recalcular puntuaciones** (aparece después de guardar) para aplicar los nuevos pesos a todas las fotos de esa categoría

Todas las estadísticas tienen en cuenta al usuario en modo multiusuario: cada usuario ve los análisis solo de sus fotos visibles.

## Atajos de teclado (galería)

| Tecla | Acción |
|-----|--------|
| `←` `→` `↑` `↓` | Mover el foco del teclado entre las tarjetas de foto (columnas de la cuadrícula y filas del mosaico) |
| `Enter` | Abrir la foto enfocada |
| `Space` | Seleccionar / deseleccionar la foto enfocada |
| `Ctrl+A` | Seleccionar todas las fotos cargadas |
| `Escape` | Borrar la selección / cerrar el cajón de filtros |
| `Shift+Click` | Selección por rango de fotos entre la última seleccionada y la clicada |
| `Double-click` | Abrir la foto |
| `?` | Mostrar la referencia de atajos de teclado (funciona en todas las páginas) |

## Deshacer

Las operaciones por lotes de favorito/rechazo/valoración y las confirmaciones de selección
muestran un snackbar con una acción **Deshacer** durante ~7 segundos. Las operaciones
de marca por lotes se confirman de inmediato y se deshacen mediante llamadas de API
inversas (con un límite de 500 fotos); las confirmaciones de selección se difieren — el
grupo desaparece al instante pero la llamada de API solo se dispara una vez transcurrida
la ventana de deshacer.

## Aplicación web progresiva

La galería incluye un manifiesto de aplicación web y un service worker de Angular (solo
en compilaciones de producción): puede instalarse en la pantalla de inicio, el shell de
la aplicación carga sin conexión, y hasta 1000 miniaturas se almacenan en caché LRU
durante 7 días. Las respuestas de la API nunca se almacenan en caché (excepto los
paquetes de i18n con una estrategia de frescura), y al cerrar sesión se borra la caché
de miniaturas para que las configuraciones multiusuario que comparten un navegador no
puedan filtrar vistas previas entre cuentas. Un snackbar ofrece recargar cuando se ha
desplegado una nueva versión.

## Móvil

En pantallas pequeñas la barra de selección por lotes se reduce al recuento de la
selección, borrar, seleccionar todo y un único botón **Acciones** que abre una hoja
inferior adaptada al táctil con todas las operaciones por lotes (favorito, rechazar,
valorar, álbumes, copiar, descargar).

## Configuración

### Ajustes de visualización

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Paginación

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Límites de los desplegables

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Establece `min_photos_for_person` más alto para ocultar del desplegable de filtros a las personas con pocas fotos.

### Umbrales de calidad

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Filtros predeterminados

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Pesos de Selección destacada

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Rendimiento

### Bases de datos grandes (50k+ fotos)

Ejecuta estos comandos para un mejor rendimiento:

```bash
python database.py --migrate-tags    # consultas de etiquetas de 10 a 50 veces más rápidas
python database.py --refresh-stats   # Precalcular las agregaciones
python database.py --optimize        # Desfragmentar la base de datos
```

### SQLite asíncrono (opcional, para rutas de lectura de alta concurrencia)

`api.database.get_async_db()` es un gestor de contexto asíncrono respaldado por aiosqlite,
paralelo a `get_db()`. Los endpoints son actualmente síncronos (FastAPI los descarga
a un grupo de hilos de trabajo, lo cual está bien con una concurrencia típica). Para rutas
de lectura de alta concurrencia (>5 usuarios simultáneos), se pueden migrar endpoints
individuales mediante:

1. Cambiar `def foo(...)` a `async def foo(...)`.
2. Reemplazar `with get_db() as conn:` por `async with get_async_db() as conn:`.
3. Usar `await` en cada `.execute()` y `.fetchone()` / `.fetchall()`.
4. Mantener las rutas de escritura síncronas — aiosqlite serializa las escrituras de todos
   modos, y el grupo de conexiones de la ruta síncrona ya las gestiona.

Los candidatos más urgentes del plan son `/api/photos`, `/api/timeline`,
`/api/search`. Migra uno a la vez y haz pruebas de rendimiento antes de promoverlo.

### Caché de estadísticas

Agregaciones precalculadas con un TTL de 5 minutos:
- Recuentos totales de fotos
- Recuentos de modelos de cámara/objetivo
- Recuentos de personas
- Recuentos de categorías y patrones

Comprobar el estado:
```bash
python database.py --stats-info
```

### Carga diferida de filtros

Los desplegables de filtros se cargan bajo demanda a través de la API:
- `/api/filter_options/cameras`
- `/api/filter_options/lenses`
- `/api/filter_options/tags`
- `/api/filter_options/persons`
- `/api/filter_options/patterns`
- `/api/filter_options/categories`
- `/api/filter_options/apertures`
- `/api/filter_options/focal_lengths`
- `/api/filter_options/colors`
- `/api/filter_options/metric_ranges`

## Endpoints de la API

La documentación interactiva de la API está disponible en `/api/docs` (Swagger UI) y el esquema OpenAPI en `/api/openapi.json`.

### Galería

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/photos` | Lista paginada de fotos con filtros |
| `GET /api/photo` | Detalles de una sola foto |
| `GET /api/type_counts` | Recuento de fotos por tipo |
| `GET /api/similar_photos/{path}` | Fotos similares (modos: `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Búsqueda semántica de texto a imagen (`scope=text` = solo texto OCR/leyenda) |
| `GET /api/critique?path=&mode=` | Crítica con IA (basada en reglas o VLM) |
| `GET /api/config` | Configuración de la galería |

### Autenticación

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/auth/login` | Autenticarse y recibir un token |
| `POST /api/auth/edition/login` | Desbloquear el modo edición |
| `POST /api/auth/edition/logout` | Bloquear el modo edición (renunciar a los privilegios, seguir autenticado) |
| `GET /api/auth/status` | Comprobar el estado de autenticación |

### Miniaturas e imágenes

| Endpoint | Descripción |
|----------|-------------|
| `GET /thumbnail` | Miniatura de la foto |
| `GET /face_thumbnail/{id}` | Miniatura del recorte del rostro |
| `GET /person_thumbnail/{id}` | Miniatura representativa de la persona |
| `GET /image` | Imagen a resolución completa |

### Opciones de filtro

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/filter_options/cameras` | Modelos de cámara con recuentos |
| `GET /api/filter_options/lenses` | Modelos de objetivo con recuentos |
| `GET /api/filter_options/tags` | Etiquetas con recuentos |
| `GET /api/filter_options/persons` | Personas con recuentos |
| `GET /api/filter_options/patterns` | Patrones de composición |
| `GET /api/filter_options/categories` | Categorías con recuentos |
| `GET /api/filter_options/apertures` | Valores de F-Stop distintos con recuentos |
| `GET /api/filter_options/focal_lengths` | Distancias focales distintas con recuentos |
| `GET /api/filter_options/colors` | Facetas de temperatura de color y agrupación de tono con recuentos |
| `GET /api/filter_options/metric_ranges` | Mín./máx. observados e histograma por métrica numérica (para los límites de los controles deslizantes) |

### Operaciones por lotes

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Marcar varias fotos como favoritas |
| `POST /api/photos/batch_reject` | Marcar varias fotos como rechazadas |
| `POST /api/photos/batch_rating` | Establecer la valoración por estrellas de varias fotos |

### Personas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/persons` | Listar todas las personas |
| `POST /api/persons` | Crear una nueva persona, adjuntando rostros opcionalmente (restringido a edición). Cuerpo: `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Listar las personas autoagrupadas sin nombre con `face_count >= N` (predeterminado desde `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Renombrar una persona |
| `POST /api/persons/{id}/assign_faces` | Adjuntar rostros en bloque a una persona; las personas antiguas vacías se eliminan automáticamente (restringido a edición). Cuerpo: `{face_ids}` |
| `POST /api/persons/{id}/split` | Dividir un subconjunto de los rostros de una persona en una nueva persona (restringido a edición). Cuerpo: `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Ocultar una persona de la lista, los filtros y las sugerencias de fusión |
| `POST /api/persons/{id}/unhide` | Mostrar de nuevo una persona oculta previamente |
| `POST /api/persons/merge` | Fusionar dos personas (cuerpo JSON) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Fusionar la persona de origen en la de destino |
| `POST /api/persons/merge_batch` | Fusionar varias personas a la vez |
| `POST /api/persons/merge_suggestions/reject` | Descartar una sugerencia de fusión para que no se vuelva a proponer |
| `POST /api/persons/{id}/delete` | Eliminar una persona |
| `POST /api/persons/delete_batch` | Eliminar varias personas a la vez |

### Álbumes

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/albums` | Listar todos los álbumes |
| `POST /api/albums` | Crear álbum |
| `GET /api/albums/{id}` | Obtener los detalles del álbum |
| `PUT /api/albums/{id}` | Actualizar el álbum |
| `DELETE /api/albums/{id}` | Eliminar el álbum |
| `GET /api/albums/{id}/photos` | Listar las fotos del álbum (paginado) |
| `POST /api/albums/{id}/photos` | Añadir fotos al álbum |
| `DELETE /api/albums/{id}/photos` | Quitar fotos del álbum |
| `POST /api/albums/{id}/share` | Generar el token de compartición |
| `DELETE /api/albums/{id}/share` | Revocar el token de compartición |
| `GET /api/shared/album/{id}?token=` | Ver el álbum compartido (sin autenticación) |

### Recuerdos, Cronología, Mapa y Leyendas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/memories?date=` | Fotos tomadas en esta fecha en años anteriores |
| `GET /api/memories/check` | Comprobar si existen recuerdos para una fecha |
| `GET /api/caption?path=` | Obtener o generar la leyenda con IA |
| `PUT /api/caption` | Actualizar la leyenda de la foto (modo edición) |
| `GET /api/timeline?cursor=&limit=&direction=` | Fotos paginadas de la cronología |
| `GET /api/timeline/dates?year=&month=` | Fechas disponibles para la navegación |
| `GET /api/timeline/years` | Años disponibles con recuentos de fotos |
| `GET /api/timeline/months` | Meses disponibles para un año |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Fotos geoetiquetadas dentro de los límites |
| `GET /api/photos/map/count` | Recuento de fotos geoetiquetadas |

### Estadísticas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/stats/overview` | Resumen general de las estadísticas de puntuación |
| `GET /api/stats/score_distribution` | Datos del histograma de distribución de puntuación |
| `GET /api/stats/top_cameras` | Cámaras principales por recuento de fotos |
| `GET /api/stats/categories` | Recuentos y promedios por categoría |
| `GET /api/stats/gear` | Recuentos de cámara/objetivo/combinación |
| `GET /api/stats/settings` | Distribuciones de los ajustes de disparo |
| `GET /api/stats/timeline` | Datos de la cronología |
| `GET /api/stats/correlations` | Correlaciones de métricas personalizadas |
| `GET /api/stats/categories/breakdown` | Recuentos de fotos y distribuciones de puntuación por categoría |
| `GET /api/stats/categories/weights` | Pesos y modificadores de categoría desde la configuración |
| `GET /api/stats/categories/correlations` | Correlación de Pearson r por dimensión y por categoría |
| `GET /api/stats/categories/metrics?category=X` | Valores de métricas en bruto para la vista previa en el cliente |
| `GET /api/stats/categories/overlap` | Análisis de solapamiento de filtros entre categorías |
| `POST /api/stats/categories/update` | Actualizar los pesos/modificadores de categoría (modo edición) |
| `POST /api/stats/categories/recompute` | Recalcular las puntuaciones de una categoría (modo edición) |

### Modo de comparación

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/comparison/next_pair` | Obtener el siguiente par de fotos para comparar |
| `POST /api/comparison/submit` | Enviar el resultado de la comparación |
| `POST /api/comparison/reset` | Restablecer los datos de comparación |
| `GET /api/comparison/stats` | Estadísticas de la sesión de comparación |
| `GET /api/comparison/history` | Listar las comparaciones pasadas |
| `POST /api/comparison/edit` | Editar el resultado de una comparación |
| `POST /api/comparison/delete` | Eliminar una comparación |
| `GET /api/comparison/coverage` | Cobertura de las comparaciones por categoría |
| `GET /api/comparison/confidence` | Métricas de confianza de las puntuaciones aprendidas |
| `GET /api/comparison/photo_metrics` | Métricas en bruto de las fotos |
| `GET /api/comparison/category_weights` | Pesos/filtros de categoría |
| `GET /api/comparison/learned_weights` | Pesos sugeridos a partir de las comparaciones |
| `POST /api/comparison/preview_score` | Vista previa con pesos personalizados |
| `POST /api/comparison/suggest_filters` | Analizar los conflictos de filtros |
| `POST /api/comparison/override_category` | Anular la categoría de la foto |
| `POST /api/recalculate` | Recalcular las puntuaciones con los pesos actuales |

### Selección de ráfagas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/burst-groups` | Listar los grupos de ráfaga para la selección |
| `POST /api/burst-groups/select` | Seleccionar las que conservar de un grupo de ráfaga |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Grupos de fotos visualmente similares |
| `POST /api/similar-groups/select` | Seleccionar las que conservar de un grupo de similares |
| `GET /api/culling-groups?exclude_rejected=true&similarity_threshold=&page=&per_page=` | Grupos combinados de ráfaga y similares. `exclude_rejected` (predeterminado `true`) oculta las fotos con `is_rejected=1`; los grupos con menos de 2 fotos restantes se descartan |
| `POST /api/culling-groups/confirm` | Confirmar las selecciones de selección |

### Escaneo

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Iniciar un escaneo de puntuación |
| `GET /api/scan/status` | Comprobar el progreso del escaneo (`progress` estructurado: `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Progreso en tiempo real vía Server-Sent Events; el token se pasa como parámetro de consulta (la API `EventSource` no puede establecer cabeceras), con recurso automático al sondeo de `/status` |
| `GET /api/scan/directories` | Listar los directorios de escaneo configurados |

### Gestión de rostros

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/person/{id}/faces` | Listar los rostros de una persona |
| `POST /api/person/{id}/avatar` | Establecer el rostro avatar de la persona |
| `GET /api/photo/faces` | Listar los rostros detectados en una foto |
| `POST /api/face/{id}/assign` | Asignar un rostro a una persona |
| `POST /api/photo/assign_all_faces` | Asignar todos los rostros de una foto a una persona |
| `POST /api/photo/unassign_person` | Desasignar una persona de una foto |

### Acciones de foto

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/photo/set_rating` | Establecer la valoración por estrellas de una foto |
| `POST /api/photo/toggle_favorite` | Alternar el estado de favorito |
| `POST /api/photo/toggle_rejected` | Alternar el estado de rechazo |

### Gestión de configuración

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/config/update_weights` | Actualizar los pesos de puntuación |
| `GET /api/config/weight_snapshots` | Listar las instantáneas de pesos guardadas |
| `POST /api/config/save_snapshot` | Guardar los pesos actuales como instantánea |
| `POST /api/config/restore_weights` | Restaurar los pesos desde una instantánea |

### Sugerencias de fusión

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/merge_suggestions` | Fusiones de personas sugeridas según la similitud facial |

### Carpetas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/folders` | Listar la estructura de carpetas de fotos |

### Descarga

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/download/options` | Tipos de descarga disponibles para una foto (`path`, opcional `is_shared`) |
| `GET /api/download` | Descargar una foto (`path`, `type=original\|darktable\|raw`, opcional `profile`) |

**Tipos de descarga:**

- `original` — Sirve el archivo tal cual (JPG/HEIF) o convertido a JPEG mediante rawpy (archivos RAW).
- `darktable` — Convierte el RAW asociado con un perfil de darktable con nombre (requiere el parámetro `profile`). Recurre al original si no existe un RAW asociado.
- `raw` — Sirve el archivo RAW asociado tal cual (no disponible en álbumes compartidos).

El endpoint `/api/download/options` detecta automáticamente los archivos RAW asociados y devuelve las opciones disponibles, incluidos los perfiles de darktable configurados. La galería usa esto para rellenar un menú de descarga por foto.

### Exportación al editor

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/photo/export_xmp` | Escribir un sidecar XMP (modo edición) |
| `POST /api/export/sidecars` | Escribir sidecars para rutas explícitas o un conjunto de filtros (modo edición) |
| `POST /api/albums/{id}/export` | Exportación de álbum como sidecars, copia o enlace simbólico (modo edición) |

### Plugins

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/plugins` | Listar los plugins configurados |
| `POST /api/plugins/test-webhook` | Probar un plugin de webhook |

### Estado

| Endpoint | Descripción |
|----------|-------------|
| `GET /health` | Comprobación de salud del servidor |
| `GET /ready` | Comprobación de disponibilidad del servidor |
| `GET /metrics` | Métricas en formato Prometheus: recuentos de fotos, cobertura de embeddings, tamaño de la BD, memoria del proceso |

### Internacionalización

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/i18n/languages` | Listar los idiomas disponibles |
| `GET /api/i18n/{lang}` | Obtener las traducciones de un idioma |

### Opciones de filtro (adicionales)

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Geocodificación inversa de coordenadas a nombre de lugar |

## Resolución de problemas

| Problema | Solución |
|-------|----------|
| Carga lenta de la página | Ejecuta `--migrate-tags` y `--optimize` |
| Los filtros no aparecen | Comprueba `--stats-info`, ejecuta `--refresh-stats` |
| El filtro de personas está vacío | Ejecuta `--cluster-faces-incremental` |
| Falta el botón Comparar | Establece una `edition_password` no vacía (usuario único) o usa el rol `admin`/`superadmin` (multiusuario) |
| La contraseña no funciona | Comprueba `viewer.password` (usuario único) o verifica el hash de la contraseña (multiusuario) |
| El usuario no puede ver fotos | Comprueba `directories` en su configuración de usuario y `shared_directories` |
| Falta el botón de escaneo | Requiere el rol `superadmin` y `viewer.features.show_scan_button: true` |
| La búsqueda no devuelve resultados | Asegúrate de que las fotos tengan datos `clip_embedding` (ejecuta primero la puntuación) |
| La crítica VLM no está disponible | Requiere el perfil de VRAM de 16gb/24gb y `viewer.features.show_vlm_critique: true` |
| El mapa no muestra fotos | Ejecuta `--extract-gps` para rellenar las columnas GPS, asegúrate de que las fotos tengan datos GPS en EXIF |
| Las leyendas no se generan | Requiere el perfil de VRAM de 16gb/24gb para la generación de leyendas con VLM |
| La cronología está vacía | Asegúrate de que las fotos tengan valores `date_taken` |
| El puerto 5000 está en uso | Ejecuta `python viewer.py --port 5001` (o establece `PORT=5001`). En macOS, el receptor AirPlay de ControlCenter vincula el puerto 5000 por defecto — elige otro puerto o desactiva el receptor AirPlay en Ajustes del Sistema → General → AirDrop y Handoff. |
