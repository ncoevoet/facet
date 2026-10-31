# Facet

> 🌐 [English](README.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md) · **Español** · [Português](README.pt.md) · [简体中文](README.zh.md)

Facet es un motor local de análisis y selección de fotos. Puntúa cada imagen en 9 dimensiones —desde la calidad estética hasta la nitidez del rostro— y luego te permite explorar, seleccionar y organizar a través de una galería web. Todo se ejecuta en tu máquina; sin nube, sin cuentas y sin claves de API.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-22-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/screenshots/walkthrough.gif" alt="Facet en acción — galería, puntuación por foto, selección, cápsulas, línea de tiempo, mapa y estadísticas" width="100%">
</p>

## Cómo funciona

1. **Escanear** — Apunta Facet a una carpeta de fotos. Cada imagen se analiza en cuanto a calidad, composición y rostros. Admite JPEG, HEIF/HEIC, 10 formatos RAW, JPEG XL, AVIF, PNG, WebP, TIFF y más — consulta los [tipos de archivo admitidos](docs/es/README.md#tipos-de-archivo-admitidos).
2. **Explorar** — Abre la galería web para recorrer tu biblioteca con filtros, búsqueda y varios modos de visualización.
3. **Seleccionar** — Facet detecta ráfagas, marca parpadeos, agrupa fotos similares y destaca la mejor selección. Los horquillados de exposición y las series panorámicas/HDR se reconocen y se mantienen íntegros en lugar de descartarse por separado.

La GPU se detecta automáticamente y es opcional. Facet funciona solo con CPU o con hasta 24 GB de VRAM.

## Funcionalidades

### Puntuar

Cada foto se puntúa en 9 dimensiones: calidad estética, composición, calidad facial, nitidez ocular, nitidez técnica, color, exposición, saliencia del sujeto y rango dinámico. Las fotos se clasifican por contenido (retrato, paisaje, macro, callejera, etc. —más de 30 categorías) y se puntúan con pesos específicos por categoría. Un filtro de **Selección destacada** clasifica la biblioteca según una puntuación combinada.

Pasa el cursor sobre cualquier foto para ver el desglose de la puntuación y los datos EXIF en el panel lateral de la galería, o cambia a una burbuja al pasar el cursor que resume de un vistazo las puntuaciones clave.

<img src="docs/screenshots/hover-tooltip.jpg" alt="Tooltip al pasar el cursor con el desglose de la puntuación" width="100%">

### Seleccionar

- **Detección de ráfagas** — agrupa las tomas en serie y selecciona automáticamente la mejor según la nitidez, la calidad y la detección de parpadeos
- **Protección de secuencias** — los horquillados de exposición, las panorámicas y las panorámicas HDR (`--detect-sequences` / `--detect-panoramas`) se reconocen como series; el laboratorio de descarte marca todos los fotogramas de una serie como conservados desde el principio
- **Grupos de similitud** — encuentra fotos visualmente similares en toda la biblioteca, sin importar cuándo se tomaron
- **Escenas** — agrupa una sesión en "escenas" cronológicas según los intervalos entre tomas, para seleccionar en orden narrativo; toca para marcar y confirma para rechazar
- **Descarte automático** — un botón descarta todo un ámbito (todos los grupos, o solo ráfagas / similares / escenas, opcionalmente limitado a un álbum o a un intervalo de fechas) con una vista previa de simulación, un presupuesto de fotos conservadas y un álbum opcional de Destacadas
- **Descarte automático desde la terminal** — `python facet.py --auto-cull [PATH]` muestra el descarte como simulación, `--apply` lo escribe y `--copy-keepers DIR` copia las fotos conservadas (consulta [docs/es/COMMANDS.md](docs/es/COMMANDS.md#descarte-desde-la-terminal))
- **Perfiles por género** — los preajustes de deportes / bodas / conciertos / fauna reúnen en una sola elección el rigor, el presupuesto de fotos conservadas, el umbral de similitud y los filtros de rostro
- **Vista previa con el aspecto editado** `[Edition]` — renderiza una foto con un estilo de darktable con nombre dentro del laboratorio de descarte, para seleccionar sobre el aspecto revelado en lugar de la vista previa RAW plana
- **Primeros planos del sujeto** — los grupos sin rostros (fauna, macro, producto) se comparan con una tira recortada automáticamente sobre el sujeto, con insignias de nitidez normalizadas por grupo
- **Limpieza de basura** — detección zero-shot de archivos no fotográficos superfluos (capturas de pantalla, documentos, recibos, memes, diapositivas) con una cola de revisión rápida: conserva o rechaza cada candidato, o recházalos todos de una vez
- **Insignias por rostro en la selección** — el visor de selección muestra insignias por cada rostro (ojos abiertos/cerrados, expresión, confianza de detección) en lugar de una única marca de parpadeo a nivel de foto; los blendshapes opcionales de MediaPipe afinan la lectura de ojos/sonrisa
- **Detección de parpadeos** — marca las tomas con ojos cerrados para ocultarlas o rechazarlas con un solo clic
- **Detección de duplicados** — identifica imágenes casi idénticas mediante hashing perceptual

<table><tr>
<td><img src="docs/screenshots/burst-culling.jpg" alt="Selección de ráfagas" width="100%"></td>
<td><img src="docs/screenshots/similar-photos.jpg" alt="Grupos de similitud para la selección" width="100%"></td>
</tr></table>

### Explorar

- **Modos de galería** — mosaico (filas justificadas que preservan las proporciones) y cuadrícula (tarjetas uniformes con superposición de metadatos)
- **Filtros** — rango de fechas, etiqueta de contenido, patrón de composición, cámara, objetivo, persona, carpeta, nivel de calidad, valoración por estrellas y rangos de métricas personalizados
- **Búsqueda semántica** — escribe una consulta en lenguaje natural como "atardecer en la playa" y encuentra fotos coincidentes mediante búsqueda por embedding y por texto
- **Cronología** — explorador cronológico con navegación por año/mes y desplazamiento infinito
- **Mapa** — fotos geoetiquetadas en un mapa interactivo con agrupación de marcadores
- **Cápsulas** — pases de diapositivas temáticos: viajes con nombres de lugares, colección dorada, paletas estacionales, fotos de una persona y mucho más
- **Carpetas** — explora por estructura de directorios con navegación de migas de pan y fotos de portada
- **Momentos narrativos** — etiquetas zero-shot de escena/actividad (playa, celebración, concierto, …) dan nombre a tus escenas, filtran y ordenan la galería y alimentan la selección de cápsulas
- **Recuerdos** — "En este día": fotos de la misma fecha en años anteriores
- **Pase de diapositivas** — modo de pantalla completa con transiciones temáticas, encadenamiento automático entre cápsulas y controles de teclado

<table><tr>
<td><img src="docs/screenshots/filter-panel.jpg" alt="Barra lateral de filtros" width="100%"></td>
<td><img src="docs/screenshots/semantic-search.jpg" alt="Resultados de búsqueda semántica" width="100%"></td>
</tr></table>

<details><summary>Barra lateral de filtros — todas las secciones desplegadas (haz clic para ver)</summary>
<p align="center"><img src="docs/screenshots/filter-sidebar-full.jpg" alt="Las cinco pestañas de la barra lateral de filtros, una al lado de otra: Explorar, Revisión, Calidad, Sujeto y Visualización" width="900"></p>
</details>

**Consejos de flujo de trabajo:**
- **`/timeline`** desciende de años a meses y a días; haz clic en un día para abrir la galería en esa fecha.
- **`/capsules`** genera diaporamas temáticos (viajes, "Rostros de", estacionales, dorados) que puedes guardar como álbumes: la mejor opción para elegir las mejores tomas de un viaje.
- La galería oculta por defecto los parpadeos, las ráfagas no principales y los duplicados. Cuando aparezca el aviso **"N fotos ocultas por los filtros actuales"**, haz clic en "Mostrar todas" para ampliar la vista.

### Organizar

- **Reconocimiento facial** — detección automática de rostros, agrupación en personas y detección de parpadeos. Busca, renombra, fusiona y organiza los grupos de personas desde la interfaz de gestión. Las **sugerencias de fusión** encuentran grupos de aspecto similar que podrían ser la misma persona.
- **Álbumes** — colecciones manuales con arrastrar y soltar, o álbumes inteligentes que se rellenan automáticamente a partir de combinaciones de filtros guardadas
- **Valoraciones y favoritos** — valoraciones por estrellas (1–5), favoritos y marcas de rechazo. Recorre las valoraciones con un solo clic.
- **Etiquetas** — etiquetas de contenido generadas por IA con vocabulario configurable. Haz clic en cualquier etiqueta para filtrar la galería.
- **Operaciones por lotes** — selección múltiple con Mayús+clic, Ctrl+clic o Ctrl+A (seleccionar todo). Asigna valoraciones, alterna favoritos, marca rechazos o añade a álbumes de forma masiva, con 7 segundos para deshacer cada acción por lotes.
- **Prioridad al teclado** — las teclas de flecha navegan por la galería, Intro abre, Espacio selecciona; pulsa `?` en cualquier lugar para ver la referencia de atajos.

<img src="docs/screenshots/albums.jpg" alt="Álbumes — colecciones manuales e inteligentes" width="100%">

<table><tr>
<td><img src="docs/screenshots/persons-manage.jpg" alt="Página Gestionar personas" width="100%"></td>
<td><img src="docs/screenshots/person-gallery.jpg" alt="Galería de persona" width="100%"></td>
</tr></table>

### Comprender

- **Estadísticas** — paneles de uso de equipo, desglose por categoría, cronología de disparos y correlaciones de métricas
- **Crítica con IA** — desglose de la puntuación que muestra la contribución de cada métrica; evaluación en lenguaje natural por VLM `[GPU]` `[16gb/24gb]`
- **Ajuste de pesos** — editor de pesos por categoría con vista previa de la puntuación en vivo. La comparación A/B de fotos aprende de tus elecciones y sugiere pesos optimizados.
- **Contextos de puntuación** — elige *qué* categoría puntúa una foto: reordena la prioridad de categorías, aplica un contexto con nombre (Acción/Escenario, Sesión de retrato, Vida salvaje, …) por álbum, o fija una categoría en una sola foto.
- **Orden "Mi gusto"** — ordena la galería según la puntuación aprendida del clasificador personal, con una insignia de confianza que muestra la cobertura aprendida y la precisión en datos de validación
- **Aprendizaje a partir de etiquetas** — las decisiones de selección, las valoraciones por estrellas, los favoritos y los rechazos alimentan el optimizador de pesos (`--sync-label-comparisons`, `--mine-insights`)
- **Instantáneas** — guarda, restaura y compara configuraciones de pesos
- **Histograma** — histograma RGB/luminancia con indicadores de recorte, en el panel lateral de la galería y en la vista de detalle
- **Leyendas con IA** `[GPU]` `[16gb/24gb]` — descripciones de texto, editables `[Edition]` y traducibles a 5 idiomas (la visualización está abierta; la generación y la edición requieren edición)

<table><tr>
<td><img src="docs/screenshots/stats-gear.jpg" alt="Estadísticas de equipo" width="100%"></td>
<td><img src="docs/screenshots/stats-categories.jpg" alt="Análisis por categoría" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/stats-timeline.jpg" alt="Cronología de disparos" width="100%"></td>
<td><img src="docs/screenshots/stats-correlations.jpg" alt="Correlaciones de métricas" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/critique.jpg" alt="Diálogo de crítica con IA" width="100%"></td>
<td><img src="docs/screenshots/snapshots.jpg" alt="Instantáneas" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/weights-sliders.jpg" alt="Controles deslizantes de pesos por categoría" width="100%"></td>
<td><img src="docs/screenshots/weights-compare.jpg" alt="Comparación A/B de fotos" width="100%"></td>
</tr></table>

### Compartir

- **Compartir álbumes** — genera enlaces para compartir cualquier álbum, sin que los destinatarios necesiten iniciar sesión. Revoca el acceso en cualquier momento.
- **Revisión de clientes** — un álbum compartido puede funcionar en modo de revisión: los clientes marcan fotos con un corazón y dejan comentarios solo con el enlace (más un PIN opcional), totalmente aislados de tus propias valoraciones
- **Subida automática desde el teléfono** — apunta PhotoSync o cualquier aplicación WebDAV a la bandeja `/dav` integrada; `--watch` puntúa las tomas nuevas a medida que llegan
- **Marcos de fotos y quioscos** — un endpoint protegido por token alimenta tus mejores tomas seleccionadas a marcos de fotos inteligentes y paneles de Home Assistant
- **Agentes de IA (MCP)** — un endpoint [Model Context Protocol](https://modelcontextprotocol.io/) (activado por defecto, `viewer.mcp.enabled`) permite a los asistentes buscar en la biblioteca con tokens personales revocables. Los niveles de token superiores pueden valorar, etiquetar, organizar y seleccionar; las acciones destructivas muestran antes una vista previa y requieren confirmación
- **Exportación de portafolio** `[Edition]` — convierte un álbum en una galería HTML estática autónoma (sin referencias a CDN, funciona sin conexión) que puedes subir a cualquier alojamiento web
- **Recortes para redes sociales** `[Edition]` — exportaciones a resolución completa encuadradas sobre el sujeto detectado para formatos cuadrado, retrato y story
- **Descarga de fotos** — descarga fotos individuales o selecciones desde la galería
- **Exportar** — exporta todas las puntuaciones a CSV o JSON para análisis externo

### Más

- **Modo oscuro y claro** con 10 temas de color de acento; respeta la preferencia del sistema
- **Adaptable** — se adapta del móvil al escritorio, con una hoja de acciones masivas táctil en pantallas pequeñas
- **PWA instalable** — manifiesto de aplicación web + service worker: instálala en la pantalla de inicio, shell de la aplicación sin conexión, miniaturas en caché
- **Galería virtualizada** — renderiza un puñado de nodos del DOM independientemente del tamaño de la biblioteca, de modo que el desplazamiento sigue siendo rápido con más de 100.000 fotos
- **Escaneos reanudables** — los escaneos interrumpidos se reanudan (`--resume`), los archivos fallidos se registran y se pueden reintentar (`--retry-failed`), y el progreso se transmite a la interfaz web
- **7 idiomas en la interfaz** — la interfaz está disponible en inglés, francés, alemán, español, italiano, portugués brasileño y chino simplificado (简体中文); la documentación está disponible en los siete idiomas
- **Multiusuario** — directorios, valoraciones y acceso por roles para cada usuario
- **Plugins y webhooks** — acciones personalizadas activadas por eventos de puntuación
- **Escaneo desde la interfaz web** — inicia escaneos desde el navegador (superadministrador en modo multiusuario; acceso de edición en una instalación de un solo usuario con contraseña de edición)

<table><tr>
<td width="33%"><img src="docs/screenshots/mobile-gallery.jpg" alt="Galería en móvil" width="100%"></td>
<td width="33%"><img src="docs/screenshots/tablet-gallery.jpg" alt="Galería en tableta" width="100%"></td>
<td width="33%"><img src="docs/screenshots/gallery-mosaic.jpg" alt="Mosaico en escritorio" width="100%"></td>
</tr></table>

## Qué necesitas

- **Cualquier equipo (CPU)** ejecuta la mayor parte de Facet: puntuación, rostros, selección, galería, búsqueda, álbumes y exportación de metadatos.
- **Apple Silicon** usa automáticamente el backend Metal (`mps`). El perfil `auto` sigue la memoria unificada: 32 GB alcanzan `16gb`, 48 GB alcanzan `24gb`.
- **Una GPU NVIDIA** con los perfiles `16gb`/`24gb` desbloquea los modelos más potentes: TOPIQ, SigLIP 2, etiquetado VLM, leyendas y crítica con IA, saliencia del sujeto.
- **¿Sin GPU?** Apunta el etiquetado VLM, las leyendas y la crítica a un servidor **Ollama** o **compatible con OpenAI** remoto con `vlm_backend` en `scoring_config.json`.
- **Editar en el visor** (valoraciones, rostros, selección) necesita la **contraseña de edición**. El botón de escaneo necesita `viewer.features.show_scan_button: true` y acceso de edición (el rol de **superadministrador** en modo multiusuario).

→ Requisitos completos por función (GPU, perfil de VRAM, paquetes opcionales, autenticación): **[Instalación › Requisitos por función](docs/es/INSTALLATION.md#requisitos-por-función)**.

## ¿Es Facet para ti?

Facet puntúa, clasifica y selecciona una biblioteca de fotos local y sirve una galería para explorarla. Se ejecuta en tu propio hardware y mantiene las fotos fuera de la nube.

**Encaja bien si:**

- tienes una biblioteca local grande y quieres encontrar tus mejores tomas y descartar ráfagas y casi duplicados;
- quieres una puntuación de calidad, composición y rostros que puedas ajustar a tu propio gusto (aprende de tus comparaciones A/B);
- prefieres lo autoalojado y privado: sin subida a la nube, sin cuenta, sin suscripción;
- ya editas en Lightroom, darktable, digiKam o Immich: Facet escribe valoraciones, etiquetas de color, palabras clave, leyendas y regiones de rostros en sidecars `.xmp` (los originales quedan intactos salvo que pidas incrustarlos: la acción «Escribir metadatos en el archivo» de la galería o `--export-sidecars --embed-originals`) y vuelve a leer las ediciones con `--import-sidecars`. Un plugin de Lightroom `facet.lrplugin` añade un flujo bidireccional. Consulta [Interoperabilidad](docs/es/INTEROP.md).

**Probablemente no sea para ti si quieres:**

- un sustituto de Google Photos llave en mano, móvil y respaldado en la nube, aunque la subida automática desde el teléfono a una bandeja vigilada está integrada mediante WebDAV (receta de PhotoSync en la documentación);
- edición o revelado RAW: Facet puntúa y organiza, no edita;
- una aplicación de escritorio sin configuración: necesita Python, y los mejores modelos necesitan una GPU.

**Cómo se relaciona con otras herramientas**

- Las bibliotecas autoalojadas (Immich, PhotoPrism) se centran en organizar, buscar y respaldar. Facet añade puntuación de calidad, clasificación y un flujo de trabajo de selección que ellas no tienen, pero carece de aplicación móvil y de copia de seguridad en la nube (la subida automática desde el teléfono por WebDAV está integrada, y las valoraciones se pueden sincronizar con Immich).
- Las aplicaciones de selección con IA (Aftershoot, Narrative, FilterPixel) son seleccionadores comerciales pulidos, a menudo con edición integrada. Facet es gratuito, local, más amplio (galería, búsqueda, rostros) y su puntuación es ajustable, pero es un proyecto de un solo desarrollador sin su soporte ni edición RAW.
- Los editores y catálogos (Lightroom, darktable, digiKam) revelan y gestionan fotos. Facet los complementa mediante la interoperabilidad de metadatos XMP descrita arriba en lugar de reemplazarlos.

La puntuación estética se basa en modelos y es aproximada; cuenta con ajustar los pesos para adaptarlos a tu gusto.

## Inicio rápido

### Docker (recomendado)

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env      # abre .env y define PHOTOS_DIR con la carpeta de tus fotos
docker compose up -d      # luego abre http://localhost:5000
```

¿Tienes una tarjeta NVIDIA? Usa el bloque de su tamaño en
[Instalación](docs/es/INSTALLATION.md#instalar-con-docker) — una línea para cada tarjeta
de 8 GB, 16 GB y 24 GB.

### Sin Docker (Linux, macOS)

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh                        # detecta tu hardware, instala todo
source venv/bin/activate
python facet.py /path/to/your/photos   # puntúa fotos
python viewer.py                       # galería → http://localhost:5000
```

> **macOS:** el receptor de AirPlay del Centro de Control ocupa el puerto 5000 por defecto. Si ves "Address already in use", ejecuta `python viewer.py --port 5001`.

Guía completa: **[Instalación](docs/es/INSTALLATION.md)** — configuración por hardware,
descargas de la primera ejecución y
[resolución de conflictos de dependencias](docs/es/INSTALLATION.md#resolución-de-conflictos-de-dependencias).
Ejecuta `python facet.py --doctor` para diagnosticar problemas con la GPU.

¿Primera vez? Sigue el recorrido **[Primeros pasos](docs/es/GETTING_STARTED.md)**: escanear, revisar, entrenar, descartar, etiquetar y exportar.

## Documentación

| Documento | Descripción |
|----------|-------------|
| [Instalación](docs/es/INSTALLATION.md) | Requisitos, configuración de GPU, perfiles de VRAM, dependencias |
| [Primeros pasos](docs/es/GETTING_STARTED.md) | Recorrido de la primera ejecución: de la instalación al escaneo, revisión, entrenamiento, descarte, etiquetado y exportación |
| [Comandos](docs/es/COMMANDS.md) | Referencia de todos los comandos de la CLI |
| [Configuración](docs/es/CONFIGURATION.md) | Referencia completa de `scoring_config.json` |
| [Puntuación](docs/es/SCORING.md) | Categorías, pesos, guía de ajuste |
| [Reconocimiento facial](docs/es/FACE_RECOGNITION.md) | Flujo de trabajo de rostros, agrupación, gestión de personas |
| [Visor](docs/es/VIEWER.md) | Funciones y uso de la galería web |
| [API](docs/API.md) | Referencia de la API HTTP del visor |
| [Interoperabilidad](docs/es/INTEROP.md) | Intercambiar valoraciones/tags con Lightroom, Capture One, digiKam, darktable |
| [Immich](docs/es/IMMICH.md) | Sincronizar valoraciones y favoritos con Immich, más el webhook entrante |
| [Volver a vincular](docs/es/RELINK.md) | Volver a vincular fotos movidas |
| [Agentes de IA](docs/es/AGENTS.md) | Dejar que un asistente compatible con MCP busque en la biblioteca con un token personal |
| [Despliegue](docs/es/DEPLOYMENT.md) | Despliegue en producción (NAS Synology, Linux, Docker) |
| [Contribuir](CONTRIBUTING.md) | Configuración de desarrollo, arquitectura, estilo de código |

## Licencia

[MIT](LICENSE)

### Licencias

El código propio de Facet es MIT. Algunos modelos por defecto son **no comerciales**: pyiqa (TOPIQ, LIQE, …) y los pesos de InsightFace. Define `licensing.mode: commercial` para usar solo reemplazos con licencia permisiva ([Licencias](docs/es/CONFIGURATION.md#licencias), [Modelos de terceros](docs/es/THIRD_PARTY_MODELS.md)).
