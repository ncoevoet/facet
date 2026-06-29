# Visor web

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · **Español** · [Português](../pt/VIEWER.md)

Aplicación de página única (SPA) basada en FastAPI + Angular para explorar, filtrar y gestionar fotos.

## Contenido

- [Iniciar el visor](#iniciar-el-visor) · [Autenticación](#autenticación) · [Opciones de filtrado](#opciones-de-filtrado) · [Ordenación](#ordenación) · [Funciones de la galería](#funciones-de-la-galería)
- [Gestión de personas](#gestión-de-personas) · [Activador de escaneo (superadmin)](#activador-de-escaneo-superadmin) · [Búsqueda semántica](#búsqueda-semántica) · [Álbumes](#álbumes)
- [Crítica con IA](#crítica-con-ia) · [Subtitulado con IA](#subtitulado-con-ia-gpu-16gb24gb-edition) · [Recuerdos ("En este día")](#recuerdos-en-este-día) · [Vista de línea de tiempo](#vista-de-línea-de-tiempo) · [Vista de mapa](#vista-de-mapa) · [Cápsulas](#cápsulas)
- [Vista de carpetas](#vista-de-carpetas) · [Diálogo de filtro GPS](#diálogo-de-filtro-gps) · [Sugerencias de fusión](#sugerencias-de-fusión) · [Exportación al editor](#exportación-al-editor) · [Descarte](#descarte) · [Modo de comparación por pares](#modo-de-comparación-por-pares)
- [Estadísticas EXIF](#estadísticas-exif) · [Atajos de teclado](#atajos-de-teclado-galería) · [Deshacer](#deshacer) · [Aplicación web progresiva](#aplicación-web-progresiva) · [Móvil](#móvil)
- [Configuración](#configuración) · [Rendimiento](#rendimiento) · [Endpoints de la API](#endpoints-de-la-api) · [Solución de problemas](#solución-de-problemas)

> **Los requisitos de cada función** se indican en línea: `[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` (contraseña de edición) · `[Superadmin]`. Consulta la [matriz de funciones](../README.md#feature-availability--requirements).

## Iniciar el visor

### Producción

```bash
python viewer.py
# Open http://localhost:5000
```

Esto sirve tanto la API como la aplicación Angular precompilada en un único puerto.

Para mayor rendimiento, ejecútalo en modo producción (Uvicorn, sin recarga automática). Añade `--workers N` para escalar (predeterminado 1):

```bash
python viewer.py --production --workers 4
```

### Desarrollo

Ejecuta el servidor de la API y el servidor de desarrollo de Angular por separado:

```bash
# Terminal 1: API server
python viewer.py
# API available at http://localhost:5000

# Terminal 2: Angular dev server with hot reload
cd client && npx ng serve
# Open http://localhost:4200 (proxies API calls to :5000)
```

## Autenticación

### Modo de un solo usuario (predeterminado)

Protección opcional con contraseña mediante la configuración:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Cuando se define, los usuarios deben autenticarse antes de acceder al visor. Una `edition_password` opcional concede acceso a la gestión de personas y al modo de comparación.

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

Los usuarios se crean únicamente por CLI (no hay interfaz de registro):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Consulta [Configuración](CONFIGURATION.md#users) para la referencia completa.

### Roles

| Rol | Ver propias + compartidas | Valorar/favorito | Gestionar personas/caras | Lanzar escaneos |
|------|:-:|:-:|:-:|:-:|
| `user` | sí | sí | no | no |
| `admin` | sí | sí | sí | no |
| `superadmin` | sí | sí | sí | sí |

### Visibilidad de las fotos

Cada usuario ve las fotos de sus directorios configurados más los directorios compartidos. La visibilidad se aplica en todos los endpoints: galería, miniaturas, descargas, estadísticas, opciones de filtro y páginas de personas.

### Valoraciones por usuario

En modo multiusuario, las valoraciones por estrellas, los favoritos y las marcas de descartado se almacenan por usuario en la tabla `user_preferences`. Cada usuario valora de forma independiente: los favoritos de Alice no afectan a la vista de Bob.

Para migrar las valoraciones existentes de un solo usuario:

```bash
python database.py --migrate-user-preferences --user alice
```

## Opciones de filtrado

<details><summary>Barra lateral de filtros completa: todas las secciones expandidas (haz clic para ver)</summary>
<p align="center"><img src="screenshots/filter-sidebar-full.jpg" alt="Filter sidebar with every section expanded" width="360"></p>
</details>

### Filtros principales

| Filtro | Opciones |
|--------|---------|
| **Tipo de foto** | Mejores selecciones, Retratos, Personas en escena, Paisajes, Arquitectura, Naturaleza, Animales, Arte y estatuas, Blanco y negro, Poca luz, Siluetas, Macro, Astrofotografía, Calle, Larga exposición, Aérea y dron, Conciertos |
| **Nivel de calidad** | Bueno (6+), Genial (7+), Excelente (8+), Mejor (9+) |
| **Cámara y objetivo** | Filtrado según el equipo |
| **Persona** | Filtrar por persona reconocida |
| **Categoría** | Filtrar por categoría de foto |

### Filtros avanzados

| Categoría | Filtros |
|----------|---------|
| **Fecha** | Fecha de inicio y de fin |
| **Puntuaciones** | Agregada, estética, puntuación TOPIQ, puntuación de calidad |
| **Calidad extendida** | IAA estética (mérito artístico), Calidad facial IQA, puntuación LIQE |
| **Métricas faciales** | Calidad facial, nitidez de ojos, nitidez facial, proporción de cara, confianza facial, número de caras |
| **Composición** | Puntuación de composición, puntos de poder, líneas guía, aislamiento, patrón de composición |
| **Prominencia del sujeto** | Nitidez del sujeto, prominencia del sujeto, ubicación del sujeto, separación del fondo |
| **Técnica** | Nitidez, contraste, rango dinámico, nivel de ruido |
| **Color** | Puntuación de color, saturación, luminancia, dispersión del histograma; temperatura de color (cálido/frío/neutro) y grupo de tono (requiere `--recompute-colors`) |
| **Exposición** | Puntuación de exposición |
| **Valoraciones del usuario** | Valoración por estrellas |
| **Ajustes de cámara** | ISO, apertura (control deslizante de rango de diafragma), distancia focal (control deslizante de rango) |
| **Contenido** | Etiquetas, interruptor monocromático |
| **Momentos** | Confianza del momento narrativo (control deslizante de rango 0–1: `min_moment_confidence` / `max_moment_confidence`) |

### Patrones de composición

Filtra por los patrones detectados por SAMP-Net:
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Ordenación

Columnas ordenables agrupadas por categoría (desde `viewer.sort_options`):

| Grupo | Columnas |
|-------|---------|
| **General** | Puntuación agregada, Estética, Puntuación de calidad, Fecha de captura, Valoración por estrellas, Estética (IAA), Puntuación LIQE |
| **Métricas faciales** | Calidad facial, Calidad facial (IQA), Nitidez de ojos, Nitidez facial, Proporción de cara, Número de caras |
| **Técnica** | Nitidez técnica, Contraste, Nivel de ruido |
| **Color** | Puntuación de color, Saturación |
| **Exposición** | Puntuación de exposición, Luminancia media, Dispersión del histograma, Rango dinámico |
| **Composición** | Puntuación de composición, Puntuación de puntos de poder, Líneas guía, Bonificación por aislamiento, Patrón de composición |
| **Prominencia del sujeto** | Nitidez del sujeto, Prominencia del sujeto, Ubicación del sujeto, Separación del fondo |
| **Contenido** | Confianza del momento (los NULL al final) |

### My Taste

Una opción de ordenación de primer nivel respaldada por el `learned_score` del clasificador personal (renombrada de "Picked for you"). Ordena las fotos según lo que el clasificador ha aprendido de tus comparaciones A/B, tus valoraciones y tus decisiones de descarte. Una insignia de confianza junto a la ordenación muestra la cobertura aprendida (% de fotos con una puntuación aprendida) y la precisión del clasificador sobre datos reservados, para que puedas juzgar cuánto fiarte del orden. Entrena o actualiza el clasificador con `python facet.py --train-ranker`.

Controlada por `viewer.features.show_my_taste` (predeterminado: `true`). El estado del clasificador se expone mediante `GET /api/ranker/status`.

## Funciones de la galería

### Tarjetas de foto

- Miniatura con insignia de puntuación
- Etiquetas en las que se puede hacer clic para filtrar rápidamente
- Avatares de personas para las caras reconocidas
- Insignia de categoría

### Selección múltiple y acciones masivas

- Haz clic en las fotos para seleccionarlas, Mayús+clic para seleccionar un rango
- Aparece una barra de acciones con el recuento de la selección y las acciones disponibles
- **Favorito** — Marca todas las seleccionadas como favoritas (quita el descartado)
- **Descartar** — Marca todas las seleccionadas como descartadas (quita el favorito y la valoración)
- **Valorar** — Establece la valoración por estrellas (1–5) para todas las seleccionadas, o borra la valoración
- **Añadir al álbum** — Añade las seleccionadas a un álbum existente o nuevo
- **Copiar nombres de archivo** — Copia los nombres de archivo seleccionados al portapapeles
- **Exportar** — Escribe sidecars XMP (valoración/favorito/descartado) junto a los archivos seleccionados (consulta [Exportación al editor](#exportación-al-editor))
- **Descargar** — Descarga las fotos seleccionadas
- Borra la selección con Escape o el botón Borrar

Las acciones masivas requieren el modo de edición. Haz doble clic en cualquier foto para descargarla directamente.

### Opciones de visualización

- **Modo de diseño** - Alterna entre **Cuadrícula** (tarjetas uniformes) y **Mosaico** (filas justificadas que preservan las proporciones). El mosaico es solo para escritorio; el móvil siempre usa cuadrícula.
- **Tamaño de miniatura** - Control deslizante para ajustar la altura de la tarjeta/fila (120–400px, persistido en localStorage)
- **Ocultar detalles** - Oculta los metadatos de la foto en las tarjetas (solo en modo cuadrícula)
- **Ocultar información emergente** - Desactiva la información emergente al pasar el cursor que muestra los detalles de la foto en escritorio
- **Ocultar parpadeos** - Filtra las fotos con parpadeos detectados
- **Mejor de la ráfaga** - Muestra solo la foto mejor puntuada de cada ráfaga
- **Desplazamiento infinito** - Las fotos se cargan a medida que te desplazas
- **Desplazamiento rápido (virtualizado)** - Renderizado por ventanas de filas: solo las
  filas cercanas a la ventana de visualización están en el DOM, de modo que el desplazamiento profundo
  a través de decenas de miles de fotos sigue siendo fluido. Activado por defecto; desactívalo en la sección
  Visualización de la barra lateral de filtros si encuentras problemas de diseño (el modo cuadrícula
  con detalles mostrados siempre usa el renderizado completo, ya que las alturas de fila no son
  deterministas allí). Persistido en localStorage (`facet_virtual_scroll`).

### Fotos similares

Haz clic en el botón "Similar" de cualquier foto para elegir un modo de similitud:

- **Visual** (predeterminado) — distancia de Hamming de pHash (70%) + similitud coseno de CLIP/SigLIP (30%). Recurre solo a CLIP cuando no hay pHash disponible.
- **Color** — Intersección de histogramas (70%) + distancia de saturación (10%) + distancia de luminancia (10%) + bonificación monocromática (10%). Prefiltra por la marca monocromática y el rango de saturación.
- **Persona** — Encuentra fotos que contengan a la misma persona o personas. Usa `person_id` cuando está disponible (rápido), de lo contrario recurre a la similitud coseno de los embeddings faciales.

Usa el **control deslizante de umbral de similitud** (0–90%) para controlar lo estricta que es la coincidencia (no se muestra en el modo persona). El panel admite desplazamiento infinito para conjuntos de resultados grandes.

### Chips de filtro

Los filtros activos se muestran como chips eliminables con recuentos en la parte superior de la galería.

## Gestión de personas

> Explorar personas está abierto a todos los visores; renombrar, fusionar, cambiar avatares y asignar caras requiere `[Edition]`.

### Filtro de persona

El desplegable muestra las personas con miniaturas de cara. Haz clic para filtrar la galería.

### Galería de persona

Haz clic en el nombre de una persona para ver todas sus fotos en `/person/<id>`.

### Página Gestionar personas

Accede mediante el botón de la cabecera o `/persons`:

| Acción | Cómo hacerlo |
|--------|--------|
| **Fusionar** | Selecciona la persona de origen, haz clic en la de destino, confirma |
| **Eliminar** | Haz clic en el botón eliminar de la tarjeta de la persona |
| **Renombrar** | Haz clic en el nombre de la persona para editarlo en línea |
| **Dividir** | Abre las caras de una persona, selecciona un subconjunto y divídelas en una persona nueva |
| **Ocultar** | Oculta un grupo de la lista de personas, los filtros y las sugerencias de fusión (reversible) |

## Activador de escaneo (superadmin)

Cuando `viewer.features.show_scan_button` está en `true` y el usuario tiene el rol `superadmin`, aparece un botón **Escanear fotos para empezar** en el estado de galería vacía. Se entrega configurado en **`false`** en `scoring_config.json` (activación opcional para superadmin). El botón abre el diálogo de lanzamiento de escaneo (`ScanLauncherComponent`).

- Elige un directorio de la lista del lanzador e inicia el escaneo dentro de la aplicación
- El lanzador transmite el progreso en vivo (SSE con recurso automático a sondeo) a una `mat-progress-bar` impulsada por el campo estructurado `progress`, más una cola de líneas de salida, y actualiza la galería cuando finaliza el escaneo
- El escaneo se ejecuta como un subproceso en segundo plano (`facet.py`); solo un escaneo a la vez (bloqueo global)
- Las opciones de directorio provienen de `get_all_scan_directories()`, que reúne los `directories` de cada usuario, los directorios compartidos, los destinos de `path_mapping` y la lista independiente `viewer.scan_directories`: rellena esta última (p. ej. `/data/photos`) para que las instalaciones de un solo usuario / Docker tengan un destino seleccionable

Esto resulta útil cuando el visor se ejecuta en la misma máquina que tiene acceso a la GPU para la puntuación.

## Búsqueda semántica

Búsqueda híbrida que combina la similitud de embeddings de CLIP/SigLIP (70%) con la coincidencia de texto BM25 de FTS5 sobre subtítulos y etiquetas (30%). Escribe una consulta como "sunset over mountains" o "child playing in snow" y el visor devuelve las fotos coincidentes ordenadas por puntuación combinada.

- Requiere datos de `clip_embedding` almacenados (calculados durante la puntuación)
- Usa sqlite-vec para la búsqueda vectorial KNN cuando está instalado, y recurre a NumPy en memoria
- La búsqueda de texto FTS5 sobre subtítulos/etiquetas de IA aporta coincidencia adicional por palabras clave (ejecuta `database.py --rebuild-fts` para habilitarla)
- Usa el mismo modelo de embedding que el perfil de VRAM activo (SigLIP 2 para 16gb/24gb, CLIP ViT-L-14 para legacy/8gb)
- `scope=text` restringe la consulta a las coincidencias literales de FTS5 en el texto de OCR/subtítulos y omite la búsqueda por embeddings
- Controlada por `viewer.features.show_semantic_search` (predeterminado: `true`)

## Álbumes

Organiza las fotos en álbumes con nombre. Accede mediante la ruta `/albums`.

### Álbumes manuales

Crea álbumes y añade fotos desde la galería usando la selección múltiple. Los álbumes admiten:
- Nombre y descripción
- Foto de portada personalizada
- Orden personalizado
- Explorar el contenido del álbum en `/album/:albumId`

### Álbumes inteligentes

Guarda una combinación de filtros (cámara, etiqueta, persona, rango de fechas, umbrales de puntuación, etc.) como un álbum inteligente. Los álbumes inteligentes se actualizan dinámicamente a medida que nuevas fotos coinciden con los criterios de filtro guardados. La combinación de filtros se almacena como JSON en `smart_filter_json`.

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

Controlado por `viewer.features.show_albums` (predeterminado: `true`).

### Compartir fotos

Comparte álbumes con usuarios externos mediante enlaces con token. No se requiere autenticación para ver los álbumes compartidos.

| Acción | Cómo hacerlo |
|--------|--------|
| **Compartir** | Abre el álbum, haz clic en el botón "Compartir" para generar un enlace compartible |
| **Revocar** | Haz clic en "Dejar de compartir" para invalidar el token de compartir |
| **Ver** | Los destinatarios abren el enlace para explorar el álbum compartido en `/shared/album/:id` |

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

## Crítica con IA

Desglosa las puntuaciones de una foto en fortalezas, debilidades y sugerencias.

### Crítica basada en reglas

Disponible en todos los perfiles de VRAM. Analiza las métricas almacenadas (estética, composición, nitidez, calidad facial, etc.) y genera una explicación estructurada de la puntuación.

### Crítica con VLM `[GPU]` `[16gb/24gb]`

Usa el VLM configurado (Qwen3.5-2B o Qwen3.5-4B) para una crítica con conciencia de contexto. Requiere el perfil de VRAM de 16gb o 24gb y `viewer.features.show_vlm_critique: true`.

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

Controlada por `viewer.features.show_critique` (predeterminado: `true`) y `viewer.features.show_vlm_critique` (predeterminado: `true`).

**Superposición visual "por qué esta puntuación".** Cuando `viewer.features.show_saliency_overlay` está en `true` (predeterminado), el diálogo de crítica obtiene un interruptor **Mostrar superposición**: dibuja el mapa de prominencia de BiRefNet como un mapa de calor translúcido sobre la foto (recalculado bajo demanda a partir de la miniatura almacenada — `GET /api/saliency_overlay`), más cuadros suaves por cara y marcadores de ojos reconstruidos a partir de los puntos de referencia almacenados (`GET /api/photo/face_markers`). Los cuadros son verdes cuando los ojos están abiertos, ámbar en un parpadeo. El mapa de calor es ilustrativo (a resolución de miniatura), no exacto al píxel; el interruptor se oculta en los perfiles donde no se puede producir ninguna máscara de prominencia.

## Subtitulado con IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtén un subtítulo en lenguaje natural generado por IA para cualquier foto. Los subtítulos se generan en la primera solicitud y se almacenan en caché en la columna `caption` de la base de datos. Los subtítulos se pueden editar manualmente en modo de edición desde la página de detalle de la foto. (La *traducción* de subtítulos se ejecuta en CPU; consulta más abajo.)

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

También disponible por CLI para la generación y traducción masivas:

```bash
python facet.py --generate-captions      # Generate captions for all uncaptioned photos
python facet.py --translate-captions     # Translate captions to configured target language
```

La traducción de subtítulos usa MarianMT (CPU, no requiere GPU). Configura el idioma de destino en `scoring_config.json` en `translation.target_language` (predeterminado: `"fr"`). Idiomas admitidos: francés, alemán, español, italiano.

Controlado por `viewer.features.show_captions` (predeterminado: `true`). Requiere el perfil de VRAM de 16gb o 24gb para el subtitulado basado en VLM.

## Recuerdos ("En este día")

Explora las fotos tomadas en la misma fecha del calendario en años anteriores. Al abrir Recuerdos se inicia un diaporama (pase de diapositivas) a pantalla completa y aleatorizado de las fotos coincidentes, en lugar de una cuadrícula; la información emergente del botón de navegación detalla lo que hace.

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

Controlado por `viewer.features.show_memories` (predeterminado: `true`).

## Flujos de trabajo habituales

- **Descartar unas vacaciones** — abre Cápsulas → busca la cápsula `journey` autogenerada para las fechas del viaje. Cada cápsula ofrece una acción Guardar como álbum.
- **Recorrer una revisión día a día** — abre la línea de tiempo → ordena por agregada → avanza por el año. Las mejores tomas suben primero cuando has activado `hide_bursts` y `hide_duplicates` (predeterminados: activados).
- **Mostrar lo que está oculto** — la galería oculta por defecto los parpadeos / ráfagas no líderes / duplicados no líderes. Cuando al menos uno de esos filtros está activo y excluiría filas, aparece un banner "N fotos ocultas por los filtros actuales · Mostrar todas" sobre la cuadrícula.

## Vista de línea de tiempo

Explorador de fotos cronológico con navegación por fechas. Desplázate por las fotos organizadas por fecha con una barra lateral que muestra los años y meses disponibles.

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

Accede mediante la ruta `/timeline`. Controlado por `viewer.features.show_timeline` (predeterminado: `true`).

## Vista de mapa

Visualiza las fotos en un mapa interactivo según las coordenadas GPS extraídas de los datos EXIF. Usa Leaflet para el renderizado del mapa con agrupación en distintos niveles de zoom.

### Configuración inicial

Extrae las coordenadas GPS de las fotos existentes:

```bash
python facet.py --extract-gps    # Extract GPS lat/lng from EXIF into database
```

Las coordenadas GPS también se extraen automáticamente durante la puntuación de las fotos nuevas.

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

Accede mediante la ruta `/map`. Controlado por `viewer.features.show_map` (predeterminado: `true`).

## Cápsulas

Diaporamas (pases de diapositivas) de fotos seleccionadas agrupadas por tema, lugar, personas y tiempo: haz clic en una cápsula para reproducirla. Accede mediante la ruta `/capsules`.

### Tipos de cápsula

Las cápsulas se autogeneran a partir de tu biblioteca usando múltiples algoritmos:

- **Journey** — viajes detectados mediante agrupación por GPS, con nombres de destino geocodificados de forma inversa ("Journey to Rome — March 2025")
- **Moments with [Person]** — las mejores fotos de cada persona reconocida
- **Seasonal Palette** — fotos agrupadas por temporada + año
- **Golden Collection** — el 1% superior por puntuación agregada
- **Color Story** — grupos visualmente similares mediante agrupación de embeddings de CLIP
- **This Week, Years Ago** — "En este día" extendido a ±3 días
- **Location** — grupos de fotos geoetiquetadas con nombres de lugar
- **Favorites** — fotos marcadas como favoritas agrupadas por año y temporada
- **Basadas en dimensiones** — autogeneradas a partir de cámara, objetivo, categoría, patrón de composición, rango de distancia focal, hora del día, valoración por estrellas y combinaciones cruzadas

### Pase de diapositivas

Haz clic en cualquier tarjeta de cápsula para iniciar un pase de diapositivas. Características:
- **Transiciones temáticas** — deslizamiento (viajes), zoom (retratos), kenburns (golden/seasonal), fundido cruzado (predeterminado)
- **Encadenamiento automático** — cuando una cápsula termina, una tarjeta de transición muestra la siguiente cápsula antes de continuar
- **Mezcla y reanudación** — las fotos se mezclan para dar variedad; la posición de reanudación se registra por cápsula
- **Agrupación adaptativa** — las fotos en vertical se agrupan lado a lado según la relación de aspecto de la ventana de visualización
- **Guardar como álbum** — guarda cualquier cápsula como un álbum permanente

### Frescura

Las cápsulas rotan según una programación configurable (predeterminado: 24 horas). Las fotos de portada y las cápsulas de descubrimiento sembradas se alinean con el mismo periodo de rotación. El botón "Regenerar" de la cabecera fuerza una actualización inmediata.

### Geocodificación inversa

Las cápsulas de ubicación y viaje muestran nombres de lugar (p. ej. "Paris, France") en lugar de coordenadas. Esto usa geocodificación sin conexión mediante el paquete `reverse_geocoder`: no se necesitan llamadas a API. Los resultados se almacenan en caché en la base de datos.

Instalación: `pip install reverse_geocoder`

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

### Configuración

Consulta [Configuración — Cápsulas](CONFIGURATION.md#capsules) para todos los ajustes.

## Vista de carpetas

Explora tu biblioteca de fotos por la estructura de directorios. Accede mediante la ruta `/folders`.

- Navegación por migas de pan para subir en el árbol de directorios
- Cada carpeta muestra una foto de portada (la imagen con mayor puntuación de ese directorio)
- Haz clic en una carpeta para entrar en ella, o haz clic en una foto para abrirla en la galería
- Respeta la visibilidad de directorios multiusuario en modo multiusuario

## Diálogo de filtro GPS

Filtra las fotos por ubicación geográfica usando un selector de mapa interactivo:

- Haz clic en el botón de filtro de ubicación para abrir el diálogo del mapa
- Haz clic o arrastra en el mapa para fijar un punto central
- Ajusta el control deslizante de radio para controlar el área de búsqueda
- Las fotos dentro del radio seleccionado se filtran en la galería
- Requiere coordenadas GPS (ejecuta `--extract-gps` si las fotos tienen datos GPS EXIF)

## Sugerencias de fusión

Encuentra grupos de personas que podrían ser el mismo individuo. Accede mediante `/merge-suggestions` o desde la página Gestionar personas.

- **Control deslizante de umbral de similitud** — cuánto deben parecerse dos personas para que se sugiera la fusión (menor = más sugerencias, mayor = menos)
- **Fusionar** — acepta una sugerencia para fusionar las dos personas
- **Fusión por lotes** — selecciona varias sugerencias y fusiónalas a la vez
- Las sugerencias descartadas se recuerdan y no se vuelven a proponer
- También disponible por CLI: `python facet.py --suggest-person-merges`

## Exportación al editor

Escribe tus valoraciones, favoritos y descartes en el disco como sidecars XMP, para que los editores externos (darktable, Lightroom) los recojan. Requiere el modo de edición.

- **Desde la galería** — selecciona fotos, y luego **Acciones → Exportar** escribe un sidecar junto a cada archivo.
- **Desde un álbum** ("cesta") — exporta todo el álbum como sidecars, o copia/enlaza simbólicamente los archivos a un directorio de destino.
- **Escribir metadatos en el archivo** — la acción "Escribir metadatos en el archivo" del detalle de la foto incrusta la valoración/palabras clave directamente en el archivo original (JPEG/HEIC/TIFF/PNG/DNG mediante exiftool) además de escribir el sidecar, para que todo el ecosistema fotográfico las vea. Los originales RAW propietarios nunca se modifican. Controlado por `viewer.features.show_embed_metadata` (predeterminado: `true`).

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

## Descarte

La página de descarte (`/culling`, modo de edición) agrupa las tomas casi idénticas para que puedas conservar la mejor de cada una y descartar el resto. Un selector de **granularidad** —el primer control y el de mayor impacto en la barra de herramientas— elige cómo se agrupan las fotos:

- **Todas** (predeterminado) — grupos combinados de ráfaga + similares.
- **Ráfagas** — fotos tomadas muy seguidas en el tiempo (de la detección de ráfagas).
- **Similar** — fotos que se parecen entre sí independientemente de cuándo se tomaron, agrupadas por la similitud de embeddings de CLIP/SigLIP. Un control deslizante de umbral controla lo estricta que es la agrupación.
- **Escenas** — grupos de escena cronológicos (series por hora de captura), cada uno encabezado por su intervalo de tiempo y su momento narrativo dominante. Sujeto a `viewer.features.show_scenes`.

Para cada grupo, elige la foto o fotos a conservar; al confirmar se descartan el resto. Las confirmaciones se difieren y se pueden deshacer (consulta [Deshacer](#deshacer)). La granularidad, la ordenación y la categoría elegidas se conservan en `localStorage`. Los controles que no se aplican a la granularidad actual se ocultan: el desplegable de ordenación y el control deslizante de umbral de similitud desaparecen en el modo escena, y el botón de ámbito se oculta cuando no tienes álbumes manuales. Cada botón de la barra de herramientas y de acción de grupo lleva una información emergente, y en pantallas pequeñas la barra de herramientas se desprende en una barra inferior desplazable.

**Descarte con ámbito acotado.** El laboratorio se puede acotar a un subconjunto mediante parámetros de consulta: `?group_by=scene` cambia a la granularidad de escena, `?album=<id>` lo restringe a un álbum, y `?from=&to=` (ventana de hora de captura EXIF, la base de **Descartar esta escena**) lo restringe a una sola escena. Un banner muestra el ámbito activo con un control **Salir de la escena**; la obtención de los miembros de la ráfaga permanece acotada al álbum pero ignora la ventana, de modo que una ráfaga que cruza el límite de la escena sigue mostrando todos sus fotogramas.

**Chip de My Taste.** Cada confirmación registra filas de comparación con `source='culling'` que entrenan al clasificador personal, así que la cabecera muestra un pequeño chip "My Taste · N comparaciones" que se actualiza tras cada decisión: la IA aprende tu ojo mientras descartas (`GET /api/ranker/status`).

### Lupa / zoom con la tecla Z

Pulsa **`Z`** en la caja de luz de vista única para alternar una lupa estilo Photo Mechanic (ajustar ↔ 2×; rueda/`+`/`-` hacen zoom hasta el 800%). Más allá de la escala de ajuste, el panel cambia su miniatura por la fuente `/image` a resolución completa, de modo que juzgas el enfoque crítico con píxeles reales sin salir de la vista. En la tira de contactos de Escenas, `Z` alterna una lupa flotante que sigue al cursor sobre una baldosa (obtenida de la imagen a resolución completa), con un control deslizante de zoom ajustable. Las miniaturas almacenadas se limitan a 640px, así que la lupa es la forma de inspeccionar los píxeles más allá de eso.

### Insignias por cara

En la caja de luz de descarte por ráfaga/similar, cada cara detectada lleva sus propias insignias —ojos abiertos/cerrados, expresión deficiente y confianza de detección— en lugar de una única marca de parpadeo a nivel de foto. Esto facilita descartar fotos de grupo: puedes ver de un vistazo qué cara tiene los ojos cerrados o una expresión débil. Las insignias se obtienen para todo un grupo en una sola llamada por lotes (`POST /api/culling-group/faces`).

**Comparación sincronizada (2-up / 4-up).** La cabecera de la caja de luz tiene botones Única / Comparar 2 / Comparar 4. En modo de comparación, los paneles comparten una única transformación de panorámica/zoom, de modo que el zoom con la rueda del ratón o el arrastre de panorámica en cualquier panel los mueve todos al recorte idéntico: la forma de elegir el fotograma más nítido de una ráfaga inspeccionando realmente los píxeles. Al hacer doble clic se alterna ajustar ↔ zoom; más allá de la escala de ajuste, cada panel cambia de forma diferida su miniatura de 1920px por la fuente `/image` a resolución completa para que la inspección sea nítida. Sin cambios en el backend: ambas rutas de imagen ya existen. (El pellizco táctil aún no está implementado; usa la rueda en escritorio.)

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

## Vista de escenas

Una exploración de **solo lectura** de tu biblioteca agrupada en "escenas" cronológicas: series por hora de captura mostradas en orden narrativo con una cuadrícula, una lupa al pasar el cursor y cabeceras de fecha/momento. Abierta a **todos los usuarios autenticados** (tanto de solo lectura como de edición). Las fotos se dividen en escenas por los intervalos de la hora de captura (una nueva escena comienza cuando transcurren más de `scenes.gap_minutes` entre tomas consecutivas, ampliados de forma adaptativa en sesiones dispersas), y cualquier serie demasiado larga se subdivide para que un evento fotografiado de forma continua nunca se reduzca a una única escena gigante.

El único punto de entrada es el botón de acción **Mostrar las escenas de este álbum** por álbum en la cuadrícula de Álbumes (un selector de ámbito de álbum dentro de la exploración te permite cambiar el ámbito). No hay ninguna entrada de Escenas en la navegación principal. Cada escena lleva un botón **Descartar esta escena** solo de edición que enlaza directamente con la superficie de [Descarte](#descarte) en granularidad de escena (`/culling?group_by=scene&album=&from=&to=`); los usuarios de edición también pueden acceder a las Escenas-como-descarte directamente desde la navegación de Descarte. La exploración en sí no tiene cuadrícula de descarte ni confirmación masiva: todo el descarte se realiza ahora a través de la superficie unificada de Descarte.

Cuando se calculan los momentos narrativos (más abajo), cada escena también se titula según su momento dominante, y `scenes.split_on_moment_change` puede subdividir una serie larga donde cambia el momento.

## Momentos narrativos

Facet etiqueta cada foto con el «momento» de escena/actividad que representa. El vocabulario **general** por defecto es agnóstico respecto a la biblioteca — celebración, comida, playa, actividad acuática, montañas, naturaleza y fauna, paisaje urbano, lugar turístico de viaje, concierto, deportes, reunión de grupo, retrato, niños, mascotas, vida nocturna, ceremonia, paisaje escénico, nieve e invierno, interior del hogar, carretera y vehículos — o `other` (un vocabulario `wedding` se incluye como género opcional). Ni Narrative Select ni AfterShoot hacen esto; agrupan solo por tiempo y similitud visual.

Es **zero-shot y totalmente local**, y **semántico de leyenda**: la leyenda de IA de cada foto se codifica una vez y se almacena, y el momento es el mejor coseno **agrupado por máximo (max-pool)** de ese embedding de leyenda frente a los prompts de texto de cada momento (L0) — el embedding de imagen almacenado es el respaldo cuando una foto no tiene leyenda. La señal de leyenda coincide con los momentos ~2,4× más limpiamente que la imagen en bruto. Pequeños priors de caras/etiquetas deshacen los casi-empates (L1), y luego un pase de Viterbi **suaviza a lo largo de la línea de tiempo** para que una lectura errónea aislada se reincorpore a la serie circundante (L2). Un desempate opcional con VLM (L3, 16gb/24gb) puede rejuzgar los fotogramas de baja confianza. Los embeddings de leyenda se calculan una vez y se reutilizan, así que volver a etiquetar es un producto escalar económico sobre vectores almacenados — sin decodificar la imagen, sin pase de modelo por imagen; **se ejecuta automáticamente al final de cada escaneo** (codificando solo las leyendas nuevas). El primer pase completo sobre una biblioteca existente codifica cada leyenda (GPU recomendada); vuelve a etiquetar toda la biblioteca con `python facet.py --recompute-moments`.

Los momentos aparecen como títulos de escena y como filtro de galería (`GET /api/photos?narrative_moment=beach`, con opciones de `GET /api/filter_options/narrative_moments`). El vocabulario se basa en la configuración por tipo de evento; consulta [Configuración — Momentos narrativos](CONFIGURATION.md#narrative-moments) para ajustar prompts/umbrales o cambiar de género.

**Confianza del momento.** Cada etiqueta almacena una confianza posterior (`narrative_moment_confidence`). Las etiquetas por debajo de `viewer.moment_confidence_min` (predeterminado `0` = nunca atenuar) se muestran atenuadas con un sufijo "(incierto)" en la cabecera de Escenas, la cabecera del grupo de escena en Descarte y la información emergente de la foto en la galería (que también muestra el % de confianza). La confianza es también una opción de ordenación —**Confianza del momento** (los NULL al final) bajo el grupo Contenido— y un filtro de rango de galería (`min_moment_confidence` / `max_moment_confidence`, un control deslizante 0–1 en la sección **Momentos** de la barra lateral).

- Cada escena muestra sus fotos líderes en orden de captura
- Descarta una escena desde su botón **Descartar esta escena**, que abre la superficie de descarte acotada a esa escena
- Las escenas más pequeñas que `scenes.min_size` se omiten; se cargan como máximo `scenes.max_photos` fotos

API: consulta la sección [Endpoints de la API](#endpoints-de-la-api) más abajo.

Controlado por `viewer.features.show_scenes` (predeterminado: `true`). Consulta [Configuración — Escenas](CONFIGURATION.md#scenes) para `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` y `adaptive_k`.

## Modo de comparación por pares

Clasifica las fotos juzgándolas de dos en dos. Los votos acumulados alimentan el ajuste de pesos. Accede mediante la ruta `/compare` (botón Comparar en la cabecera). Requiere una `edition_password` no vacía (un solo usuario) o el rol `admin`/`superadmin` (multiusuario).

La página tiene cuatro pestañas:

### Pestaña Comparación A/B

Pares de fotos lado a lado. Elige un ganador, marca un empate u omite. Una barra de progreso registra los votos hacia 50, con recuentos en vivo de victorias-A/victorias-B/empates. Un filtro de categoría acota la sesión, y un desplegable de estrategia de selección controla cómo se eligen los pares.

| Estrategia | Descripción |
|----------|-------------|
| `uncertainty` | Fotos con puntuaciones similares (las más informativas) |
| `boundary` | Rango de puntuación 6–8 (zona ambigua) |
| `active` | Fotos con menos comparaciones (asegura la cobertura) |
| `random` | Pares aleatorios (referencia base) |

**Atajos de teclado:**

| Tecla | Acción |
|-----|--------|
| `A` | Gana la foto de la izquierda |
| `B` | Gana la foto de la derecha |
| `T` | Empate |
| `S` | Omitir par |
| `Escape` | Cerrar el modal de anulación de categoría |

### Pestaña Sugerencias de pesos

Muestra los pesos aprendidos de las comparaciones frente a los pesos actuales, lado a lado, con la precisión del modelo antes/después. Las 10 mejores fotos actuales y las 10 mejores previstas tras el recálculo se previsualizan en columnas adyacentes. **Aplicar** escribe los pesos sugeridos; **Recalcular** vuelve a puntuar la categoría para aplicarlos (ambos requieren el modo de edición).

### Pestaña Pesos

Editor manual de pesos: un control deslizante por métrica para la categoría seleccionada con una vista previa de puntuación en vivo. **Guardar** escribe en `scoring_config.json` (con una copia de seguridad); **Recalcular puntuaciones** los aplica; **Restablecer** recarga los pesos almacenados.

### Pestaña Instantáneas

Guarda los pesos actuales como una instantánea con nombre y restaura cualquier instantánea anterior.

### Anulación de categoría

Para reasignar la categoría de una foto desde la vista de comparación: edita la insignia de categoría, selecciona una categoría de destino, ejecuta "Analizar conflictos de filtro" para ver qué filtros la excluyen, y luego aplica la anulación.

## Estadísticas EXIF

La página de estadísticas (`/stats`) proporciona análisis en 5 pestañas. Usa los selectores de **categoría** y **rango de fechas** de la barra de herramientas para filtrar todos los gráficos a un subconjunto específico de tu biblioteca.

### Pestañas

| Pestaña | Descripción |
|-----|-------------|
| **Equipo** | Cuerpos de cámara, objetivos y combinaciones (los 20 mejores de cada uno) |
| **Ajustes de disparo** | Distribuciones de ISO, apertura, distancia focal y velocidad de obturación |
| **Línea de tiempo** | Fotos a lo largo del tiempo |
| **Categorías** | Análisis de categorías, gestión de pesos y correlaciones de puntuación |
| **Correlaciones** | Gráficos de correlación de métricas X/Y personalizados con agrupación |

### Pestaña Categorías

Cuatro subpestañas:

| Subpestaña | Descripción |
|---------|-------------|
| **Desglose** | Recuentos de fotos por categoría, puntuaciones medias, histogramas de distribución de puntuaciones |
| **Pesos** | Comparación con gráfico radar (hasta 5 categorías), mapa de calor de pesos y editor de pesos (modo de edición) |
| **Correlaciones** | Mapa de calor de correlación de Pearson que muestra cómo influye cada dimensión en la agregada, vista de detalle al hacer clic |
| **Solapamiento** | Análisis de solapamiento de filtros que muestra qué categorías comparten fotos coincidentes |

Cada gráfico tiene un botón de ayuda `?` conmutable que explica cómo leerlo. Un interruptor de ayuda global en la barra de subpestañas muestra las explicaciones de todas las subpestañas.

### Editor de pesos (modo de edición)

Disponible en la subpestaña Pesos cuando el modo de edición está activo:

1. Selecciona una categoría del desplegable
2. Ajusta los controles deslizantes de peso (uno por métrica, deben sumar 100%)
3. Usa "Normalizar a 100" para autobalancear
4. Expande la sección plegable Modificadores para ajustar bonificaciones/penalizaciones
5. La **Vista previa de distribución de puntuaciones** muestra un histograma en vivo de antes/después a medida que mueves los controles
6. Haz clic en **Guardar** para actualizar `scoring_config.json` (crea una copia de seguridad con marca de tiempo)
7. Haz clic en **Recalcular puntuaciones** (aparece tras guardar) para aplicar los nuevos pesos a todas las fotos de esa categoría

Todas las estadísticas tienen conciencia de usuario en modo multiusuario: cada usuario ve los análisis solo de sus fotos visibles.

## Atajos de teclado (galería)

| Tecla | Acción |
|-----|--------|
| `←` `→` `↑` `↓` | Mover el foco del teclado entre las tarjetas de foto (columnas de cuadrícula y filas de mosaico) |
| `Enter` | Abrir la foto enfocada |
| `Space` | Seleccionar / deseleccionar la foto enfocada |
| `Ctrl+A` | Seleccionar todas las fotos cargadas |
| `Escape` | Borrar la selección / cerrar el cajón de filtros |
| `Shift+Click` | Seleccionar el rango de fotos entre la última seleccionada y la pulsada |
| `Double-click` | Abrir la foto |
| `?` | Mostrar la referencia de atajos de teclado (funciona en todas las páginas) |

## Deshacer

Las operaciones masivas de favorito/descarte/valoración y las confirmaciones de descarte muestran una barra de notificación
con una acción **Deshacer** durante unos 7 segundos. Las operaciones masivas de marcas se confirman
de inmediato y se deshacen mediante llamadas inversas a la API (limitadas a 500 fotos); las confirmaciones
de descarte se difieren: el grupo desaparece al instante pero la llamada a la API solo
se dispara una vez que transcurre la ventana de deshacer.

## Aplicación web progresiva

El visor incluye un manifiesto de aplicación web y un service worker de Angular (solo en compilaciones
de producción): se puede instalar en la pantalla de inicio, el shell de la aplicación se carga
sin conexión, y hasta 1000 miniaturas se almacenan en caché LRU durante 7 días. Las respuestas de la API
nunca se almacenan en caché (excepto los paquetes de i18n con una estrategia de frescura), y al cerrar sesión
se borra la caché de miniaturas para que las configuraciones multiusuario que comparten un navegador no puedan filtrar
vistas previas entre cuentas. Una barra de notificación ofrece recargar cuando se ha desplegado una nueva versión.

## Móvil

En pantallas pequeñas, la barra de selección masiva se reduce al recuento de la selección,
los botones de borrar, seleccionar todo y un único botón **Acciones** que abre una hoja inferior
apta para el tacto con todas las operaciones masivas (favorito, descartar, valorar, álbumes, copiar,
descargar).

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

Aumenta `min_photos_for_person` para ocultar del desplegable de filtros las personas con pocas fotos.

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

### Pesos de las mejores selecciones

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

### Bases de datos grandes (más de 50k fotos)

Ejecuta lo siguiente para un mejor rendimiento:

```bash
python database.py --migrate-tags    # 10-50x faster tag queries
python database.py --refresh-stats   # Precompute aggregations
python database.py --optimize        # Defragment database
```

### SQLite asíncrono (opcional, para rutas de lectura de alta concurrencia)

`api.database.get_async_db()` es un gestor de contexto asíncrono respaldado por aiosqlite,
paralelo a `get_db()`. Los endpoints son actualmente síncronos (FastAPI los delega
a un grupo de hilos de trabajo, lo cual está bien con la concurrencia habitual). Para rutas de lectura
de alta concurrencia (>5 usuarios simultáneos), los endpoints individuales se pueden
migrar así:

1. Cambia `def foo(...)` por `async def foo(...)`.
2. Reemplaza `with get_db() as conn:` por `async with get_async_db() as conn:`.
3. Usa `await` en cada `.execute()` y `.fetchone()` / `.fetchall()`.
4. Mantén síncronas las rutas de escritura: aiosqlite serializa las escrituras de todos modos, y la
   ruta síncrona ya las gestiona con su grupo de conexiones.

Los candidatos más calientes del plan son `/api/photos`, `/api/timeline` y
`/api/search`. Migra de uno en uno y haz benchmarks antes de promover.

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

Los desplegables de filtros se cargan bajo demanda mediante la API:
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
| `GET /api/type_counts` | Recuentos de fotos por tipo |
| `GET /api/similar_photos/{path}` | Fotos similares (modos: `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Búsqueda semántica de texto a imagen (`scope=text` = solo texto de OCR/subtítulos) |
| `GET /api/critique?path=&mode=` | Crítica con IA (basada en reglas o VLM) |
| `GET /api/ranker/status` | Estado del clasificador personal para la ordenación "My Taste" (% de cobertura aprendida, precisión sobre datos reservados) |
| `GET /api/config` | Configuración del visor |

### Autenticación

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/auth/login` | Autenticarse y recibir un token |
| `POST /api/auth/edition/login` | Desbloquear el modo de edición |
| `POST /api/auth/edition/logout` | Bloquear el modo de edición (revocar privilegios, seguir autenticado) |
| `GET /api/auth/status` | Comprobar el estado de autenticación |

### Miniaturas e imágenes

| Endpoint | Descripción |
|----------|-------------|
| `GET /thumbnail` | Miniatura de foto |
| `GET /face_thumbnail/{id}` | Miniatura del recorte de cara |
| `GET /person_thumbnail/{id}` | Miniatura representativa de persona |
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
| `GET /api/filter_options/apertures` | Valores de diafragma distintos con recuentos |
| `GET /api/filter_options/focal_lengths` | Distancias focales distintas con recuentos |
| `GET /api/filter_options/colors` | Facetas de temperatura de color y grupo de tono con recuentos |
| `GET /api/filter_options/metric_ranges` | Mín/máx observados e histograma por métrica numérica (para los límites del control deslizante) |

### Operaciones por lotes

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Marcar varias fotos como favoritas |
| `POST /api/photos/batch_reject` | Marcar varias fotos como descartadas |
| `POST /api/photos/batch_rating` | Establecer la valoración por estrellas de varias fotos |

### Personas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/persons` | Listar todas las personas |
| `POST /api/persons` | Crear una persona nueva, opcionalmente adjuntando caras (restringido a edición). Cuerpo: `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Listar las personas autoagrupadas sin nombre con `face_count >= N` (predeterminado desde `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Renombrar una persona |
| `POST /api/persons/{id}/assign_faces` | Adjuntar caras en bloque a una persona; las personas antiguas vacías se eliminan automáticamente (restringido a edición). Cuerpo: `{face_ids}` |
| `POST /api/persons/{id}/split` | Dividir un subconjunto de las caras de una persona en una persona nueva (restringido a edición). Cuerpo: `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Ocultar una persona de la lista, los filtros y las sugerencias de fusión |
| `POST /api/persons/{id}/unhide` | Mostrar una persona previamente oculta |
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
| `POST /api/albums` | Crear un álbum |
| `GET /api/albums/{id}` | Obtener los detalles de un álbum |
| `PUT /api/albums/{id}` | Actualizar un álbum |
| `DELETE /api/albums/{id}` | Eliminar un álbum |
| `GET /api/albums/{id}/photos` | Listar las fotos de un álbum (paginado) |
| `POST /api/albums/{id}/photos` | Añadir fotos a un álbum |
| `DELETE /api/albums/{id}/photos` | Quitar fotos de un álbum |
| `POST /api/albums/{id}/share` | Generar un token de compartir |
| `DELETE /api/albums/{id}/share` | Revocar un token de compartir |
| `GET /api/shared/album/{id}?token=` | Ver un álbum compartido (sin autenticación) |

### Recuerdos, línea de tiempo, mapa y subtítulos

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/memories?date=` | Fotos tomadas en esta fecha en años anteriores |
| `GET /api/memories/check` | Comprobar si existen recuerdos para una fecha |
| `GET /api/caption?path=` | Obtener o generar un subtítulo con IA |
| `PUT /api/caption` | Actualizar el subtítulo de una foto (modo de edición) |
| `GET /api/timeline?cursor=&limit=&direction=` | Fotos de la línea de tiempo paginadas |
| `GET /api/timeline/dates?year=&month=` | Fechas disponibles para la navegación |
| `GET /api/timeline/years` | Años disponibles con recuentos de fotos |
| `GET /api/timeline/months` | Meses disponibles para un año |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Fotos geoetiquetadas dentro de los límites |
| `GET /api/photos/map/count` | Recuento de fotos geoetiquetadas |

### Cápsulas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/capsules` | Lista paginada de cápsulas (en caché) |
| `GET /api/capsules/{id}/photos` | Fotos de una cápsula específica |
| `POST /api/capsules/{id}/save-album` | Guardar la cápsula como álbum (modo de edición) |

### Estadísticas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/stats/overview` | Resumen general de las estadísticas de puntuación |
| `GET /api/stats/score_distribution` | Datos del histograma de distribución de puntuaciones |
| `GET /api/stats/top_cameras` | Cámaras principales por número de fotos |
| `GET /api/stats/categories` | Recuentos y medias por categoría |
| `GET /api/stats/gear` | Recuentos de cámara/objetivo/combinación |
| `GET /api/stats/settings` | Distribuciones de los ajustes de disparo |
| `GET /api/stats/timeline` | Datos de la línea de tiempo |
| `GET /api/stats/correlations` | Correlaciones de métricas personalizadas |
| `GET /api/stats/categories/breakdown` | Recuentos de fotos y distribuciones de puntuación por categoría |
| `GET /api/stats/categories/weights` | Pesos y modificadores de categoría desde la configuración |
| `GET /api/stats/categories/correlations` | r de Pearson por dimensión y por categoría |
| `GET /api/stats/categories/metrics?category=X` | Valores de métricas en bruto para la vista previa en el cliente |
| `GET /api/stats/categories/overlap` | Análisis de solapamiento de filtros entre categorías |
| `POST /api/stats/categories/update` | Actualizar pesos/modificadores de categoría (modo de edición) |
| `POST /api/stats/categories/recompute` | Recalcular las puntuaciones de una categoría (modo de edición) |

### Modo de comparación

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/comparison/next_pair` | Obtener el siguiente par de fotos para comparar |
| `POST /api/comparison/submit` | Enviar el resultado de una comparación |
| `POST /api/comparison/reset` | Restablecer los datos de comparación |
| `GET /api/comparison/stats` | Estadísticas de la sesión de comparación |
| `GET /api/comparison/history` | Listar comparaciones anteriores |
| `POST /api/comparison/edit` | Editar el resultado de una comparación |
| `POST /api/comparison/delete` | Eliminar una comparación |
| `GET /api/comparison/coverage` | Cobertura de comparaciones por categoría |
| `GET /api/comparison/confidence` | Métricas de confianza de las puntuaciones aprendidas |
| `GET /api/comparison/photo_metrics` | Métricas en bruto de las fotos |
| `GET /api/comparison/category_weights` | Pesos/filtros de categoría |
| `GET /api/comparison/learned_weights` | Pesos sugeridos a partir de las comparaciones |
| `POST /api/comparison/preview_score` | Vista previa con pesos personalizados |
| `POST /api/comparison/suggest_filters` | Analizar conflictos de filtro |
| `POST /api/comparison/override_category` | Anular la categoría de una foto |
| `POST /api/recalculate` | Recalcular las puntuaciones con los pesos actuales |

### Descarte de ráfagas

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/burst-groups` | Listar los grupos de ráfaga para el descarte |
| `POST /api/burst-groups/select` | Seleccionar las fotos a conservar de un grupo de ráfaga |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Grupos de fotos visualmente similares |
| `POST /api/similar-groups/select` | Seleccionar las fotos a conservar de un grupo similar |
| `GET /api/culling-groups?group_by=all\|burst\|similar\|scene&exclude_rejected=true&similarity_threshold=&page=&per_page=` | Grupos de ráfaga/similares/escena para descarte. `group_by` (predeterminado `all`) selecciona los grupos combinados de ráfaga+similares, solo de ráfaga, solo de similares o de escena cronológicos (los grupos de escena añaden `type`/`start`/`end`/`moment`/`moment_confidence`; el parámetro `sort` se ignora en el modo escena). `exclude_rejected` (predeterminado `true`) oculta las fotos con `is_rejected=1`; los grupos con menos de 2 fotos restantes se descartan |
| `POST /api/culling-groups/confirm` | Confirmar las selecciones de descarte (ráfaga, similares o escena). Cuerpo `{group_id, type, paths, keep_paths}`; `type:'scene'` registra las filas de comparación del descarte de escena |
| `POST /api/culling-group/faces` | Insignias por cara (ojos abiertos/cerrados, expresión, confianza) de un grupo, en un solo lote |
| `GET /api/scenes` | Escenas cronológicas de fotos líderes de ráfaga (exploración de solo lectura) |

### Escaneo

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Iniciar un escaneo de puntuación |
| `GET /api/scan/status` | Comprobar el progreso del escaneo (estructura `progress`: `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Progreso en tiempo real mediante Server-Sent Events; el token se pasa como parámetro de consulta (la API `EventSource` no puede establecer cabeceras), con recurso automático a sondeo de `/status` |
| `GET /api/scan/directories` | Listar los directorios de escaneo configurados |

### Gestión de caras

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/person/{id}/faces` | Listar las caras de una persona |
| `POST /api/person/{id}/avatar` | Establecer la cara de avatar de una persona |
| `GET /api/photo/faces` | Listar las caras detectadas en una foto |
| `POST /api/face/{id}/assign` | Asignar una cara a una persona |
| `POST /api/photo/assign_all_faces` | Asignar todas las caras de una foto a una persona |
| `POST /api/photo/unassign_person` | Desasignar una persona de una foto |

### Acciones sobre fotos

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/photo/set_rating` | Establecer la valoración por estrellas de una foto |
| `POST /api/photo/toggle_favorite` | Alternar el estado de favorito |
| `POST /api/photo/toggle_rejected` | Alternar el estado de descartado |

### Gestión de la configuración

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

- `original` — Sirve el archivo tal cual (JPG/HEIF) o convertido a JPEG con rawpy (archivos RAW).
- `darktable` — Convierte el RAW complementario con un perfil de darktable con nombre (requiere el parámetro `profile`). Recurre al original si no existe un RAW complementario.
- `raw` — Sirve el archivo RAW complementario tal cual (no disponible en álbumes compartidos).

El endpoint `/api/download/options` detecta automáticamente los archivos RAW complementarios y devuelve las opciones disponibles, incluidos los perfiles de darktable configurados. El visor lo usa para rellenar un menú de descarga por foto.

### Exportación al editor

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/photo/export_xmp` | `[Edition]` Escribir un sidecar XMP |
| `POST /api/export/sidecars` | `[Edition]` Escribir sidecars para rutas explícitas o un conjunto de filtros |
| `POST /api/photo/embed_metadata` | `[Edition]` Incrustar los metadatos en el archivo original (JPEG/HEIC/TIFF/PNG/DNG; los RAW nunca se modifican) y escribir el sidecar |
| `POST /api/albums/{id}/export` | `[Edition]` Exportación de álbum como sidecars, copia o enlace simbólico |

### Plugins

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/plugins` | Listar los plugins configurados |
| `POST /api/plugins/test-webhook` | Probar un plugin de webhook |

### Salud

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
| `GET /api/filter_options/location_name?lat=&lng=` | Geocodificar de forma inversa las coordenadas a un nombre de lugar |

## Solución de problemas

| Problema | Solución |
|-------|----------|
| Carga lenta de la página | Ejecuta `--migrate-tags` y `--optimize` |
| Los filtros no se muestran | Comprueba `--stats-info`, ejecuta `--refresh-stats` |
| Filtro de persona vacío | Ejecuta `--cluster-faces-incremental` |
| Falta el botón Comparar | Define una `edition_password` no vacía (un solo usuario) o usa el rol `admin`/`superadmin` (multiusuario) |
| La contraseña no funciona | Comprueba `viewer.password` (un solo usuario) o verifica el hash de la contraseña (multiusuario) |
| El usuario no puede ver las fotos | Comprueba `directories` en su configuración de usuario y `shared_directories` |
| Falta el botón de escaneo | Requiere el rol `superadmin` y `viewer.features.show_scan_button: true` |
| La búsqueda no devuelve resultados | Asegúrate de que las fotos tengan datos `clip_embedding` (ejecuta primero la puntuación) |
| La crítica con VLM no está disponible | Requiere el perfil de VRAM de 16gb/24gb y `viewer.features.show_vlm_critique: true` |
| El mapa no muestra fotos | Ejecuta `--extract-gps` para rellenar las columnas GPS, asegúrate de que las fotos tengan datos GPS EXIF |
| Los subtítulos no se generan | Requiere el perfil de VRAM de 16gb/24gb para el subtitulado con VLM |
| Línea de tiempo vacía | Asegúrate de que las fotos tengan valores `date_taken` |
| El puerto 5000 está en uso | Ejecuta `python viewer.py --port 5001` (o define `PORT=5001`). En macOS, el Receptor de AirPlay del Centro de Control ocupa el 5000 por defecto: elige otro puerto o desactiva el Receptor de AirPlay en Ajustes del Sistema → General → AirDrop y Handoff. |
