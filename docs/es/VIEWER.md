# Visor web

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · **Español** · [Português](../pt/VIEWER.md) · [简体中文](../zh/VIEWER.md)

El visor es una aplicación web FastAPI + Angular para explorar, filtrar, descartar y gestionar tus fotos.

## Contenido

- [Iniciar el visor](#iniciar-el-visor) · [Autenticación](#autenticación) · [Opciones de filtrado](#opciones-de-filtrado) · [Ordenación](#ordenación) · [Decisiones de revisión](#decisiones-de-revisión) · [Funciones de la galería](#funciones-de-la-galería)
- [Panorámicas y bracketing de exposición](#panorámicas-y-bracketing-de-exposición)
- [Gestión de personas](#gestión-de-personas) · [Activador de escaneo](#activador-de-escaneo) · [Búsqueda semántica](#búsqueda-semántica) · [Álbumes](#álbumes)
- [Crítica con IA](#crítica-con-ia) · [Subtitulado con IA](#subtitulado-con-ia-gpu-16gb24gb-edition) · [Recuerdos ("En este día")](#recuerdos-en-este-día) · [Vista de línea de tiempo](#vista-de-línea-de-tiempo) · [Vista de mapa](#vista-de-mapa) · [Cápsulas](#cápsulas)
- [Vista de carpetas](#vista-de-carpetas) · [Diálogo de filtro GPS](#diálogo-de-filtro-gps) · [Sugerencias de fusión](#sugerencias-de-fusión) · [Exportación al editor](#exportación-al-editor) · [Descarga](#descarga) · [Descarte](#descarte) · [Limpieza de basura](#limpieza-de-basura) · [Modo de comparación por pares](#modo-de-comparación-por-pares)
- [Estadísticas EXIF](#estadísticas-exif) · [Atajos de teclado](#atajos-de-teclado-galería) · [Deshacer](#deshacer) · [Aplicación web progresiva](#aplicación-web-progresiva) · [Móvil](#móvil) · [Marco de fotos / Quiosco](#marco-de-fotos--quiosco) · [Subida automática desde el teléfono](#subida-automática-desde-el-teléfono)
- [Configuración](#configuración-2) · [Rendimiento](#rendimiento) · [Endpoints de la API](#endpoints-de-la-api) · [Fotos JPEG XL](#fotos-jpeg-xl) · [Solución de problemas](#solución-de-problemas)

> **Los requisitos de cada función** se indican en línea: `[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` (contraseña de edición) · `[Superadmin]`. Consulta la [matriz de funciones](INSTALLATION.md#requisitos-por-función).

> **Asistentes de IA**: Facet puede ofrecer sus herramientas a los asistentes compatibles con MCP. Con el nivel de token adecuado, pueden buscar, modificar y descartar fotos de la biblioteca. Ver [Agentes de IA (MCP)](AGENTS.md).

## Iniciar el visor

### Producción

```bash
python viewer.py
# Open http://localhost:5000
```

Esto sirve la API y la aplicación Angular precompilada en un solo puerto.

Para un mayor rendimiento, usa el modo de producción (Uvicorn, sin recarga automática). Añade `--workers N` para escalar (por defecto 1):

```bash
python viewer.py --production --workers 4
```

### Desarrollo

Ejecuta por separado el servidor de la API y el servidor de desarrollo de Angular:

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

Protege el visor con una contraseña opcional:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Dos contraseñas controlan el acceso:

- **`viewer.password`** decide quién puede *explorar*. Vacía, cualquiera puede explorar toda la biblioteca. Definida, los usuarios deben iniciar sesión primero.
- **`viewer.edition_password`** es necesaria para cualquier edición: valoraciones, favoritos y rechazos, descarte, álbumes, gestión de personas y rostros, modo de comparación, cambios de pesos y prioridades, y exportaciones. Vacía (el valor predeterminado distribuido), la instalación queda en **solo lectura**: las ediciones se rechazan con `403` ("Set viewer.edition_password to enable editing").

La generación de IA bajo demanda (leyendas, críticas VLM) también necesita la contraseña de edición. Sin ella solo obtienes lo que ya está en caché (`source: "none"` o `vlm_available: false`). Sin contraseña de edición, la galería también oculta las insignias de estrellas, favoritos y rechazos existentes, igual que para los visores sin edición en una instalación protegida con contraseña.

Reinicia el visor tras definir `viewer.edition_password`: la configuración no se recarga en caliente.

> **Advertencia:** con un `viewer.password` vacío (el valor predeterminado distribuido), cualquiera que alcance el puerto del visor puede explorar la biblioteca y descargar los originales. `viewer.py` escucha en todas las interfaces por defecto (`--host 0.0.0.0`, de lo que depende la imagen de Docker). Define `viewer.password` antes de exponerlo más allá de tu propio equipo, o vincúlalo al bucle local con `--host 127.0.0.1`. En Docker, publica el puerto como `127.0.0.1:5000:5000`. El visor registra una advertencia al iniciarse mientras `viewer.password` está vacío (salvo que se le indique vincularse al bucle local).

El inicio de sesión también guarda el token de sesión en una cookie `HttpOnly` `SameSite=Lax`, de modo que las miniaturas y el flujo de progreso del escaneo se cargan en instalaciones protegidas con contraseña. La cookie solo se acepta en peticiones de solo lectura (GET/HEAD); las ediciones siguen necesitando el token Bearer. Cerrar sesión (`POST /api/auth/logout`) la borra.

### Modo multiusuario

Para un NAS familiar donde cada miembro tiene carpetas de fotos privadas. Añade una sección `users` a `scoring_config.json`:

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

Escribe cada entrada de `directories` y `shared_directories` exactamente como el escáner guardó la ruta. La coincidencia ignora las mayúsculas ASCII en Windows, macOS y en las entradas UNC o con letra de unidad. En el resto de casos (Linux, por ejemplo) distingue mayúsculas. Las diferencias de mayúsculas no ASCII y las unidades asignadas que el equipo no puede resolver no coinciden.

Crea los usuarios desde la CLI (no hay página de registro):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Consulta [Configuración](CONFIGURATION.md#usuarios) para la referencia completa.

### Roles

| Rol | Ver propias + compartidas | Valorar/favorito | Gestionar personas/rostros | Lanzar escaneos |
|------|:-:|:-:|:-:|:-:|
| `user` | sí | sí | no | no |
| `admin` | sí | sí | sí | no |
| `superadmin` | sí | sí | sí | sí |

### Visibilidad de las fotos

Cada usuario ve las fotos de sus propios directorios más las de los directorios compartidos. Esto se aplica en todas partes: galería, miniaturas, descargas, estadísticas, opciones de filtro y páginas de personas.

### Valoraciones por usuario

En modo multiusuario, las valoraciones por estrellas, los favoritos y los rechazos se guardan por usuario en la tabla `user_preferences`. Los favoritos de Alice no afectan a la vista de Bob.

Para migrar las valoraciones existentes de un solo usuario:

```bash
python database.py --migrate-user-preferences --user alice
```

## Opciones de filtrado

La búsqueda de texto de la galería conserva las palabras Unicode y trata la puntuación de los nombres de archivo como separadores de palabras. `IMG_0042.JPG` busca a la vez los prefijos `IMG`, `0042` y `JPG`. Los términos en cirílico y CJK funcionan. Los operadores FTS como `OR` se tratan como palabras literales.

### Pestañas de la barra lateral

La barra lateral de filtros agrupa sus secciones en cinco pestañas, mostradas como iconos (pasa el ratón para ver el nombre). Una pequeña insignia en un icono cuenta los filtros activos de la pestaña, y la pestaña conserva su nombre para los lectores de pantalla («Explorar, 2 activos»). La última pestaña usada se recuerda en este navegador (`facet_sidebar_tab`). Explorar, Calidad y Sujeto tienen paneles plegables, cada uno recuerda si está abierto; Revisión y Visualización no los tienen.

| Pestaña | Secciones |
|---------|-----------|
| **Explorar** | Búsqueda semántica, Personas, Rango de fechas, Contenido, Álbumes, Ubicación, Carpeta, Equipo |
| **Revisión** | Una fila con menú cada una para la decisión, y después para ráfagas, duplicados, parpadeos, horquillados, panorámicas y rechazadas, una valoración por estrellas, los interruptores Favoritos y Monocromo y, para editores, *Rostros manuales por revisar* y *Correcciones de panorama* |
| **Calidad** | Calidad, Color y calidad, Calidad extendida, Técnica, Exposición & Rango (qué tan buena es la imagen) |
| **Sujeto** | Métricas faciales, Composición, Saliencia del sujeto, Momentos (qué hay en el encuadre) |
| **Visualización** | Vista (tamaño de las tarjetas, diseño, desplazamiento rápido, acciones de las tarjetas) |

La cabecera, **Buscar un filtro**, el aviso de álbum inteligente y la búsqueda por nombre de archivo permanecen sobre las pestañas en todas ellas, así que `/` funciona desde cualquiera. Escribir en **Buscar un filtro** oculta las pestañas y lista los controles coincidentes de todas.

El número junto a **Filtros** es el total de todos los filtros activos. Un rango mín./máx. cuenta una vez, igual que el filtro de ubicación. La búsqueda por nombre de archivo y *Similar a* no tienen sección y solo se cuentan en este total, igual que un filtro sobre una métrica que esta instalación oculta, para que **Restablecer filtros** aún pueda borrarlo. **Restablecer filtros** (con información emergente) aparece junto al número mientras haya al menos un filtro activo; la simple **X** del extremo derecho solo cierra la barra lateral en pantallas estrechas.

En la pestaña Revisión, la decisión y cada grupo (por ejemplo Duplicados) es una fila que muestra su valor actual (como Ocultos, Mostrados o Solo estos) y abre un menú de opciones, cada una con una explicación de una línea. Una fila que se deja en su valor por defecto no cuenta en la insignia de la pestaña ni de la cabecera. *Solo* y *Ocultos* se excluyen entre sí. Mientras hay una decisión elegida, Rechazadas queda bloqueada, y su información emergente explica por qué. El botón de estrella fija una valoración mínima: cada clic la sube en uno, y el clic después de 5, o después de un máximo llegado desde un enlace, la borra. Comparte fila con los interruptores Favoritos y Monocromo, solo con icono y con información emergente. En las pestañas Calidad y Sujeto, pasar el cursor sobre el nombre de un ajuste explica qué se puntúa y con qué modelo, y los controles de Revisión también tienen información emergente.

<details><summary>Barra lateral de filtros completa: todas las secciones expandidas (haz clic para ver)</summary>
<p align="center"><img src="../screenshots/filter-sidebar-full.jpg" alt="Las cinco pestañas de la barra lateral de filtros, una al lado de otra: Explorar, Revisión, Calidad, Sujeto y Visualización" width="900"></p>
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
| **Color** | Puntuación de color, saturación, luminancia, dispersión del histograma; temperatura de color y grupo de tono (requieren `--recompute-colors`) |
| **Exposición** | Puntuación de exposición |
| **Valoraciones del usuario** | Valoración por estrellas |
| **Ajustes de cámara** | ISO, apertura (control deslizante de rango de diafragma), distancia focal (control deslizante de rango) |
| **Contenido** | Etiquetas, interruptor monocromático |
| **Momentos** | Confianza del momento narrativo (control deslizante 0–1: `min_moment_confidence` / `max_moment_confidence`) |

Algunos filtros de rango solo incluyen las fotos que tienen un valor, así que incluso un filtro que empieza en 0 excluye las fotos sin puntuar:

- **Estética IAA, Calidad facial IQA, LIQE, Aesthetic V2.5, Q-ReAlign, DeQA**: una foto que el modelo no pudo puntuar no tiene valor. Una ordenación ascendente por estos criterios la coloca al final, en la galería y en los álbumes. Ver [Dimensiones IQA complementarias](SCORING.md#dimensiones-iqa-complementarias).
- **Nitidez del sujeto, Ubicación del sujeto, Separación del fondo, Puntos de poder**: una foto sin sujeto detectable no tiene valor, y el panel de detalle omite la fila. La prominencia del sujeto es 0,0 para una foto así. Ver [SCORING.md](SCORING.md).

### Patrones de composición

Filtra por los 8 patrones que detecta SAMP-Net (de `models/samp_net.py`):
- global, horizontal, vertical, triangular
- surround, quarter, cross, rule_of_thirds

## Ordenación

El botón de ordenación de la cabecera (y de la barra de herramientas móvil) muestra el icono de la ordenación actual; su información emergente dice `Ordenar por: <ordenación actual>`. Abre un menú agrupado con todas las ordenaciones. El conmutador ascendente/descendente está a su lado. Los modelos de puntuación alternativos usan etiquetas breves (IAA, 2.5, Q-R, DeQA, LIQE e IQA).

**Ordenación recordada.** La galería se abre con la última ordenación elegida, que prevalece sobre `viewer.defaults.sort`. La elección se guarda en `localStorage` por navegador, no por cuenta.

- Solo se recuerda una elección hecha en el menú de ordenación. Una ordenación que llega por un enlace compartido o por un asistente no se recuerda, y el `sort` propio de un enlace prevalece.
- Elegir de nuevo la ordenación predeterminada configurada, o restablecer los filtros, olvida la elección.
- **Relevancia** nunca se recuerda, porque necesita una consulta de búsqueda.

Las velocidades de obturación se ordenan por duración, así que `1/250` y `0.004` son iguales. Los valores ausentes o no válidos van al final en cualquier dirección.

Columnas ordenables por grupo (de `viewer.sort_options`):

| Grupo | Columnas |
|-------|---------|
| **General** | Puntuación agregada, Estética, Puntuación de calidad, Fecha de captura, Valoración por estrellas, Estética (IAA), Puntuación LIQE, Q-ReAlign (Estética), DeQA, Aesthetic v2.5 (las tres últimas aparecen cuando una foto tiene esa puntuación) |
| **Métricas faciales** | Calidad facial, Calidad facial (IQA), Nitidez de ojos, Nitidez facial, Proporción de cara, Número de caras |
| **Técnica** | Nitidez técnica, Contraste, Nivel de ruido |
| **Color** | Puntuación de color, Saturación |
| **Exposición** | Puntuación de exposición, Luminancia media, Dispersión del histograma, Rango dinámico |
| **Composición** | Puntuación de composición, Puntuación de puntos de poder, Líneas guía, Bonificación de aislamiento, Patrón de composición |
| **Prominencia del sujeto** | Nitidez del sujeto, Prominencia del sujeto, Ubicación del sujeto, Separación del fondo |
| **Contenido** | Confianza del momento (los NULL van al final) |

### My Taste

Ordena por el `learned_score` del clasificador personal: lo que ha aprendido de tus comparaciones A/B, valoraciones y decisiones de descarte. Una insignia junto a la ordenación muestra la cobertura (% de fotos con una puntuación aprendida) y la precisión del clasificador con datos reservados, para que juzgues cuánto fiarte de él. Entrena o actualiza el clasificador con `python facet.py --train-ranker`.

Se controla con `viewer.features.show_my_taste` (por defecto: `true`). Estado del clasificador: `GET /api/ranker/status`.

### Métricas ocultas en modo comercial

Con `licensing.mode` definido como `commercial`, el visor oculta las métricas cuyos modelos no pueden usarse comercialmente: LIQE, IAA estética, Calidad facial IQA (salvo que OFIQ esté instalado), DeQA (salvo que `licensing.allow_unclear` esté definido) y Aesthetic V2.5. Sus filtros, chips y opciones de ordenación desaparecen; `/api/config` las lista en `unavailable_metrics`. En la página de ajuste de pesos sus controles siguen visibles pero deshabilitados, y la puntuación descarta y renormaliza esos pesos. Reinicia el visor tras cambiar el modo de licencia.

## Decisiones de revisión

Usa **Estado de revisión → Por revisar** en la galería para recorrer las fotos sin decidir. Esta vista ordena por **Fecha de captura, la más antigua primero**; puedes invertirla o acotarla por fecha, carpeta o álbum. Elegir un estado de revisión sale de las búsquedas semánticas y de Fotos similares.

- **Conserva** una foto que quieras; **Rechaza** la que no. Ambas acciones la sacan de Por revisar. Encuentra las fotos conservadas con el filtro de estado **Conservada**.
- Conservar es independiente de los favoritos y de las valoraciones por estrellas.
- Conservar y **Restablecer decisión** están en el detalle de la foto, el menú contextual y las acciones masivas. Pulsa **K** (reasignable, ver [Atajos de teclado](#atajos-de-teclado-galería)) para conservar la foto actual. En el detalle de la foto, Conservar alterna.
- **Restablecer decisión** borra Conservar y Rechazar sin tocar las estrellas ni el favorito.
- Las decisiones sobreviven a recargas, reinicios y reescaneos. En instalaciones multiusuario pertenecen al usuario actual.
- Confirmar un grupo de descarte marca sus fotos conservadas como Conservada. Las valoraciones y favoritos existentes no se convierten en decisiones de Conservar.

**Recuentos de progreso.** La galería muestra los recuentos de **sin decidir**, **conservadas** y **rechazadas** para toda la carpeta, álbum o ámbito filtrado visible, no solo la página cargada. El porcentaje es `(conservadas + rechazadas) / total`. El estado de revisión y los interruptores de Ocultar rechazadas no reducen el total; los demás filtros sí.

**Reanudar una cola.** **Revisar sin decidir** inicia una cola. **Continuar revisión** reabre en este navegador tu cola de Por revisar más reciente en su primera foto sin decidir restante.

- El marcador es por navegador y por identidad con sesión iniciada (hasta 20 identidades). No se sincroniza entre dispositivos.
- Cambiar los filtros no lo sustituye, salvo que abras otra cola de Por revisar.
- Las colas de álbum usan los criterios guardados actuales del álbum.
- Los grupos temporales de ráfaga/secuencia no se marcan, porque un reescaneo puede renumerarlos.
- Cerrar sesión borra todos los marcadores de colas de revisión de este navegador.

**Avisos flotantes.** El progreso de revisión, **Continuar revisión**, el aviso de fotos ocultas, el aviso de filtros activos (con **Restablecer todos los filtros**) y el aviso de migración de miniaturas se apilan abajo a la derecha.

- La × de cada tarjeta la oculta durante la pestaña actual del navegador. Vuelve en una pestaña nueva, o cuando el aviso cambia (otro ámbito, un recuento de ocultas distinto, un filtro añadido o quitado).
- Para ocultar el progreso de revisión de forma permanente, usa **Ocultar el progreso de revisión** / **Mostrar el progreso de revisión** del menú de usuario. Se guarda por navegador y también oculta el botón **Revisar sin decidir**.
- Tras unos segundos de inactividad, la pila se pliega en una pequeña píldora con un recuento. Pasa el cursor o haz clic para desplegarla.

## Funciones de la galería

### Pilas de fotos manuales

Selecciona **2–1000 fotos explícitas** y elige **Apilar fotos** en la barra o pulsa **S** para abrir el editor de página completa en `/stacks/edit`. Una selección de toda la vista no crea pilas. S abre una vista previa; nunca guarda directamente. Menú de usuario → **Personalizar atajos** cambia la tecla de la galería; la ayuda emergente, Ayuda y la referencia `?` muestran la tecla actual. Si una configuración anterior ya usa S, se conserva y Apilar queda **Sin asignar** hasta elegir una tecla libre. Se requieren permisos de edición. Cada foto pertenece a una pila por propietario. La página centra una vista previa con zoom sobre una tira de miniaturas permanente. Pulsa una miniatura o usa `←`/`→` para enfocar una foto y sus controles de portada, orden o eliminación de la pila. El botón de zoom, la rueda o un doble clic permiten examinar los detalles.

Usa **Cmd+Mayús+S** o **Ctrl+Mayús+S** para apilar fotos explícitas sin pila en orden de selección; la primera será la portada. Los miembros de pilas existentes abren el editor. El éxito borra la selección guardada y Deshacer la restaura; cancelar o fallar la conserva. Escape en el editor vuelve a la galería de origen sin guardar.

**Rechazar al apilar.** Enfoca una foto en el editor de página completa o su diálogo y usa **Rechazar** o **R**. La foto activa en el cuarto oscuro de pilas sugeridas tiene la misma acción; ábrelo primero para elegirla. Rechazar guarda de inmediato la decisión habitual, borra Conservar, favorito y estrellas, y excluye solo esa foto de la pila propuesta. No elimina ni modifica archivos originales. El contador y las miniaturas atenuadas muestran las exclusiones. Deshacer restaura los valores anteriores y la pertenencia al borrador vigente sin reemplazar cambios posteriores de orden o portada; una revisión posterior puede impedir Deshacer. Las fotos ya rechazadas permanecen hasta excluirlas explícitamente, sin otra decisión. La agrupación espera a Guardar; salir sin guardar no deshace Rechazar.

Si las fotos seleccionadas ya pertenecen a pilas, **Combinar pilas** es la opción inicial: la vista previa incluye sus demás miembros. **Solo fotos seleccionadas** mueve únicamente la selección explícita. El editor muestra los recuentos seleccionado y final, miembros adicionales y un resumen de efectos; despliega los detalles para revisar cada pila de origen. Dos o más miembros restantes conservan su pila; uno solo queda sin apilar y un origen vacío desaparece. Excluir una foto de la nueva pila la deja en su origen según las mismas reglas. La pila final y el total de fotos afectadas tienen un límite de 1000 cada uno; se rechazan orígenes no disponibles o parcialmente visibles. Cambiar de modo conserva el orden, la portada y las exclusiones que sigan siendo aplicables.

Revisa la vista previa actualizada por el servidor y pulsa **Apilar fotos** para guardar. La página sigue abierta para examinar el resultado; la notificación ofrece **Deshacer** mientras esté disponible y coincidan las revisiones. **Seguir editando** obtiene una vista previa nueva antes de volver a guardar. **Volver a la galería** regresa a la galería o al álbum de origen con su URL exacta y caduca el Deshacer anterior. Salir sin guardar descarta la agrupación; un rechazo explícito persiste. Recargar el navegador restaura la selección solo para la misma cuenta, tras una autorización nueva; abrir la URL sin una selección válida ofrece una forma de volver.

La insignia o una foto apilada abre el visor con miniaturas, botones anterior/siguiente y contador en el orden guardado. Las flechas permanecen en la pila. **Gestionar pila** abre un diálogo secundario: pulsa una miniatura o usa Izquierda/Derecha para ver su vista previa grande, elige **Portada**, reordena con los botones de flecha o quita miembros. Abrirlo por sí solo conserva la edición habitual: los miembros retirados quedan sin apilar, quitar la portada elige el primer miembro restante y menos de dos miembros o **Desapilar** disuelve la pila. **Añadir fotos seleccionadas** de otra pila activa explícitamente la vista previa de reagrupación y sus dos modos. Los cambios de agrupación conservan archivos y valores de revisión; Rechazar explícitamente cambia los valores de revisión de inmediato.

- Las acciones de valoración, Conservar/Rechazar, metadatos, descarga, álbum y eliminación nunca expanden una pila de forma implícita.

**En la galería.** Una pila se pliega en una sola miniatura; **Expandir todas las pilas** es una preferencia recordada. Los filtros y la pertenencia a álbumes se aplican a las fotos individuales: la portada se muestra si coincide; si no, el primer miembro que coincide. La exploración de pilas omite el ocultado automático de ráfagas/duplicados. La línea de tiempo y el mapa muestran fotos individuales.

**Selección.** Seleccionar una miniatura plegada selecciona solo la foto mostrada. Abre la pila y usa **Seleccionar los N miembros** para todos. **Seleccionar todo en la vista**, la selección por percentil y `target:view` del asistente incluyen todas las fotos coincidentes, también los miembros plegados, y las acciones sobre toda la vista muestran antes el número real de fotos. En los resúmenes de la API y del asistente, `total` cuenta las miniaturas mostradas y `photo_total` cuenta las fotos.

**Privacidad y persistencia.**

- Las pilas son privadas de su propietario (la instalación, en modo de un solo usuario). Editarlas requiere acceso de edición.
- No aparecen en los enlaces públicos compartidos ni en las exportaciones del visor. Una pila parcialmente visible es de solo lectura.
- Los reescaneos conservan la portada, el orden y los miembros. Las copias de seguridad normales de la base de datos conservan las pilas.
- Las exportaciones completas de la base de datos del visor omiten las pilas y los álbumes inteligentes cuyos filtros nombran una pila privada, además de los álbumes inteligentes con filtros ilegibles (JSON no válido, anidamiento excesivo o más de 1 MiB). Las actualizaciones incrementales conservan los álbumes y pilas propios del destino.
- La [importación/envío de pilas de Immich](IMMICH.md#importar-y-enviar-pilas-manuales) es una operación de CLI independiente.

**Pilas sugeridas** abre la revisión de página completa en `/culling?mode=stacks`, con los filtros actuales y la vuelta a la galería o al álbum de origen. Requiere permisos de edición. Revisa grupos de duplicados y ráfagas existentes sin ocultar sus miembros.

- En la cuadrícula, `↑`/`↓` seleccionan un grupo, **Intro** abre su cuarto oscuro y **S** lo apila con la portada propuesta. En el cuarto oscuro, `←`/`→` enfocan una foto y **S** o **Intro** apilan con esa portada. **X** omite el grupo; apilar y omitir ofrecen Deshacer.
- **Rechazar** o **R** en el cuarto oscuro excluye la foto activa. Apilar guarda las fotos restantes y requiere al menos dos. Omitir descarta la propuesta original. Si quedan pocas, puedes examinar las excluidas, cambiar de grupo, deshacer, omitir o volver. El rechazo sigue guardado al terminar una propuesta. Deshacer Apilar u Omitir restaura sus exclusiones; una sugerencia posterior inicia un borrador nuevo.
- El cuarto oscuro conserva la vista previa grande con zoom, la lupa, la comparación y la tira de miniaturas. **Z** alterna el zoom, **P** el resaltado de enfoque, **F** la pantalla completa; **G** recorre las cuadrículas de composición; **Escape** vuelve a la cuadrícula de grupos. **Editar miembros** abre un diálogo secundario; reducir la sugerencia a una foto ofrece **Omitir esta pila**.
- Las omisiones se guardan por cuenta hasta que cambien los miembros del grupo. Se excluyen grupos con fotos ya apiladas o de horquillado/panorama; los grupos solapados se excluyen enteros, priorizando duplicados.
- La cabecera cuenta sugerencias cargadas, no el total de la biblioteca. Cada lote contiene hasta 20 propuestas y 2000 fotos (1000 por grupo). El siguiente se carga automáticamente solo cuando todas las sugerencias cargadas se hayan apilado u omitido. **Recargar sugerencias** recarga el mismo ámbito; **Volver a la galería** regresa al origen.
- No se ofrece en listas fijadas, Fotos similares ni búsqueda semántica. Apilar y Omitir no cambian decisiones de revisión ni originales. Solo Rechazar explícitamente cambia los valores de revisión.

### Tarjetas de foto

- Miniatura con insignia de puntuación. Pasa el cursor para ver dónde se sitúa la puntuación en tu biblioteca ("Top 18 % de la biblioteca").
- Etiquetas en las que se puede hacer clic para filtrar rápidamente
- Avatares de persona para los rostros reconocidos
- Insignia de categoría
- Clic derecho (o Shift+F10) abre el [menú contextual](#selección-múltiple-y-acciones-masivas)

En el detalle de la foto, las métricas se organizan en pestañas con icono: datos EXIF (cuando existen), Calidad, Composición (con la saliencia del sujeto), Técnica e Histograma. Se recuerda la última pestaña que abriste. Cada puntuación aparece junto a su distribución en la biblioteca, con la barra de la foto resaltada; pasa el cursor sobre una barra para ver el rango de la foto y el rango de la biblioteca. La posición se calcula sobre toda la biblioteca, no sobre los filtros actuales, con la precisión de 20 barras.

### Selección múltiple y acciones masivas

Haz clic en las fotos para seleccionarlas; Shift+clic selecciona un rango. Abajo a la izquierda aparece una barra de acciones con botones de icono (pasa el cursor para ver las etiquetas). Las acciones masivas requieren el modo de edición.

- **Favorito**: marca todas como favoritas (borra el rechazo)
- **Rechazar**: marca todas como rechazadas (borra el favorito y la valoración)
- **Calificar**: define o borra una valoración de 1–5 estrellas
- **Añadir al álbum**: añade a un álbum existente o nuevo
- **Editar etiquetas**: añade o quita un [tag manual](#tags-manuales) en cada foto seleccionada
- **Seleccionar todo**: con una selección vacía, selecciona todas las fotos que coinciden con los filtros, no solo las páginas cargadas. Con fotos ya seleccionadas, añade las cargadas y ofrece ampliar a toda la vista. Las acciones sobre toda la vista confirman antes el número exacto de fotos.
- **Invertir**: cambia la selección por su complemento. Desde una selección vacía es toda la vista. Desde una selección no vacía se queda dentro de las fotos cargadas: elige las que conservas, invierte, rechaza.
- **Comparar**: abre de 2 a 4 fotos en paralelo con desplazamiento y zoom sincronizados (rueda para el zoom, arrastrar para desplazar, doble clic para restablecer). Los paneles pasan a resolución completa al ampliar.
- **Copiar nombres**: copia los nombres de archivo al portapapeles. Una copia de toda la vista pide confirmación antes; más de 10 000 fotos se rechaza.
- **Exportar**: escribe sidecars XMP junto a los archivos (ver [Exportación al editor](#exportación-al-editor))
- **Descartar a carpeta**: copia las conservadas, o mueve/envía a la papelera las rechazadas, a una carpeta (ver [Descartar a carpeta](#descartar-a-carpeta))
- **Eliminar**: envía las fotos a la papelera del sistema (ver [Eliminar](#eliminar)). Solo se muestra cuando `viewer.cull.allow_trash` está activado. Deshabilitado para una selección de "seleccionar todo en la vista": selecciona las fotos de forma explícita.
- **Descargar**: descarga las fotos seleccionadas
- Borra la selección con Escape o con el botón Borrar.

Haz doble clic en una foto para abrirla.

**Menú contextual.** Haz clic derecho en una foto, o enfócala y pulsa Shift+F10 / la tecla Menú.

- En una foto dentro de una selección de varias, actúa sobre toda la selección con las acciones de la barra (salvo Invertir y Seleccionar todo), incluida **Editar etiquetas**.
- En cualquier otra foto, actúa solo sobre esa foto y añade Abrir foto, Buscar similares, ¿Por qué esta puntuación?, Escribir metadatos en el archivo y Asignar rostro a persona (cuando la foto tiene rostros sin asignar), según sus condiciones.
- Descartar una foto desde el menú quita de la selección solo esa foto.
- No se ofrece en dispositivos táctiles (`hover: none` y `pointer: coarse`); usa allí la hoja de Acciones.

### Conservar el N% superior

El control **Conservar el % superior** de la barra de herramientas (modo de edición) descarta toda la vista filtrada de una vez. Define un porcentaje. Facet clasifica la vista por la **ordenación actual** (agregada, My Taste, Mejores selecciones, nitidez…), conserva la parte superior y **selecciona el resto**. Recházalas desde la barra de acciones, tras deseleccionar las que quieras salvar.

- No se mueve ni se elimina nada; solo rellena la selección. Los rechazos siguen entrenando My Taste.
- La selección está limitada a 5000 fotos. En una vista mayor, acota el filtro (álbum, fecha, persona…).
- Con los valores por defecto de `hide_brackets` / `hide_panoramas`, un conjunto de bracketing o panorámica cuenta como **una** foto.

### Lista fijada por el asistente

Cuando un asistente conectado mediante [Agentes de IA (MCP)](AGENTS.md) te muestra una lista exacta de fotos, la galería la muestra en el orden del asistente. Una línea de estado indica cuántas fotos se eligieron; **Volver a la vista habitual** restaura tus filtros.

- Mientras se muestra la lista, la barra de filtros, los chips de etiquetas, los avatares de personas, **Buscar similares** y las acciones con ámbito de filtro (como **Conservar el N% superior**) están ocultos. Cambiar de álbum sigue sustituyendo la lista.
- Mostrar una lista borra tu selección y el panel lateral.
- Las escrituras del asistente aparecen sin recargar: las tarjetas modificadas se actualizan y las fotos eliminadas salen de la lista. Una foto que `cull_apply` movió o envió a la papelera permanece. Aparece un solo aviso "El asistente cambió N fotos" por cada ráfaga de cambios. Ver [Actualizaciones en vivo](AGENTS.md#actualizaciones-en-vivo).

**Chip Asistente activo.** Mientras un asistente trabaja en tu pestaña, un chip **Asistente activo** aparece en la cabecera durante unos segundos tras cada escritura o comando. Haz clic para ver **Actividad del asistente**: las últimas 50 acciones de esta sesión (se pierden al recargar), con la herramienta, el número de fotos y la hora. Las acciones que nombraron fotos tienen **Mostrar las fotos**. Cuando el asistente lo pide, la pestaña le indica sobre qué foto está tu cursor (`focused`) y qué hiciste desde su última consulta (`user_activity`). No se envía nada sin que se pida. Ver [Controla tu pestaña abierta](AGENTS.md#controlar-tu-pestaña-abierta).

### Descartar a carpeta

**Descartar a carpeta…** en la barra de acciones masivas (modo de edición) copia las conservadas, o mueve/envía a la papelera las rechazadas, a una carpeta de destino. Papelera significa la papelera del sistema, nunca un borrado permanente, y requiere `viewer.cull.allow_trash`.

- **Toda ejecución empieza como simulación.** Ves una vista previa antes de que se escriba nada; mover/enviar a la papelera solo se ejecuta con un `dry_run=false` explícito.
- **El servidor elige los archivos según el estado de cada foto.** Copiar actúa solo sobre las conservadas, mover/papelera solo sobre las rechazadas. Todo lo demás se informa como `excluded_by_state`. El cliente no puede entregar una lista de archivos que eliminar.
- **Los acompañantes son opcionales.** Rechazar un JPEG no se lleva su RAW salvo que marques **Incluir RAW / XMP acompañante** (`include_companions`).
- En macOS y Windows, los RAW acompañantes conservan sus nombres en disco, incluidas las extensiones en mayúsculas; en Windows, los sidecars `.xmp` también.

**Disponibilidad de enviar rechazadas a la papelera.** La opción "Enviar rechazadas a la papelera" solo aparece cuando `viewer.cull.allow_trash` está activado *y* el paquete `send2trash` está instalado (`/api/config` informa `cull.trash_available: true`). Si no, el diálogo explica por qué: "el paquete `send2trash` no está instalado" o "un administrador deshabilitó el envío a la papelera".

**Conjuntos de varios fotogramas.** Con los valores por defecto de `hide_brackets` / `hide_panoramas`, la selección contiene solo la exposición base de un bracketing o el fotograma central de una panorámica. Así, por defecto, descartar un conjunto actúa sobre **un** solo archivo. Dos casillas opcionales lo amplían:

- **Incluir RAW / XMP acompañante** (`include_companions`) añade el RAW y el sidecar `.xmp` del mismo fotograma.
- **Incluir fotogramas hermanos de la secuencia** (`include_sequence_siblings`) añade los demás fotogramas del conjunto, pero solo aquellos cuyo propio estado de conservar/rechazar coincide con la acción. Los fotogramas conservados nunca se envían a la papelera porque un hermano fue rechazado. Un fotograma que deseleccionaste nunca vuelve a incluirse.
- La vista previa siempre informa de cuántos fotogramas hermanos existen (`sequence_siblings`). `matched` distingue "nada cumplía" de un resultado vacío.
- Mover o enviar a la papelera la principal de un conjunto promueve a un hermano superviviente, de modo que el conjunto sigue visible.
- Para elegir un subconjunto exacto de un conjunto, ábrelo antes con la acción "abrir este conjunto en la galería" del detalle de la foto. Esa vista muestra todos los fotogramas.

Un descarte con ámbito de filtro sigue las mismas reglas de filtro que la galería, incluido el Tipo de foto. Una vista de más de 10 000 fotos se rechaza en lugar de truncarse, incluso en simulación: acótala (álbum, fecha, persona…) y reinténtalo. Detalles: [API.md](../API.md).

**Dónde puedes escribir.** Sin `viewer.export.allowed_target_dirs`, Facet escribe solo dentro de tus directorios de escaneo. Una subcarpeta del árbol de fotos (p. ej. `_rejected`) funciona sin configuración. Para una carpeta en otro lugar, añádela a `viewer.export.allowed_target_dirs`. Ver [Configuración — Destinos de exportación y descarte](CONFIGURATION.md#destinos-de-exportación-y-descarte). En Docker/Podman, las rutas se resuelven **dentro del contenedor**: ver [Despliegue — Semántica de rutas en contenedores](DEPLOYMENT.md#semántica-de-rutas-en-contenedores).

**"Acceso denegado" en cada acción.** Es un rechazo deliberado: la carpeta de destino no está permitida, o tu sesión de edición caducó. Revisa el campo `detail` de la petición fallida en la pestaña Red del navegador. Un problema real del sistema de archivos se ve distinto: éxito parcial con un recuento de `errors` distinto de cero, y el error del sistema operativo en el registro del servidor.

### Eliminar

**Eliminar** en el detalle de la foto y en la barra de selección envía los archivos directamente a la papelera del sistema (recuperable, mediante `send2trash`). Es independiente de Descartar a carpeta y del cuarto oscuro `/culling`. Usa el mismo indicador `viewer.cull.allow_trash`.

- **La entrada de la biblioteca desaparece al instante.** A diferencia de Descartar a carpeta, la fila de la foto se elimina en cuanto su archivo va a la papelera; no hace falta `--cleanup-missing-photos`. Un RAW acompañante incluido que se había escaneado como foto propia también se va.
- **Solo selección explícita.** Hasta 10000 rutas; "seleccionar todo en la vista" está deshabilitado.
- **Alcance.** Por defecto, solo el archivo nombrado. **Incluir RAW / XMP acompañante** (`include_companions`) e **Incluir fotogramas hermanos de la secuencia** (`include_sequence_siblings`) lo amplían, como en Descartar a carpeta. Ambos están desactivados por defecto.
- **Las exposiciones base de un bracketing están protegidas.** El fotograma base de un bracketing (`sequence_ev_offset = 0`) se rechaza (`refused_bracket_lead`) salvo que incluyas los hermanos; entonces todo el bracketing se va junto. Una principal de panorámica eliminada promueve a un hermano superviviente.
- **Resultados parciales.** Cada ruta se informa por separado. Una principal de bracketing rechazada no detiene el resto. Un archivo cuyo envío a la papelera falló (`errors`) conserva su fila.
- **Archivos que ya faltan en disco.** **Eliminar también las entradas de la biblioteca cuyo archivo ya falta en disco** (activado por defecto) elimina también esas filas, informadas como `removed_missing`. Sin marcar, vuelven en `skipped` con sus filas conservadas. Una ruta fuera de los directorios de escaneo, o en una carpeta ausente o vacía (un volumen sin conexión), permanece siempre en `skipped`. Usa `--cleanup-missing-photos` para limpiar toda una biblioteca.

Campos de respuesta y códigos de estado: [API.md](../API.md).

### Opciones de visualización

- **Modo de diseño**: **Cuadrícula** (tarjetas uniformes) o **Mosaico** (filas justificadas que conservan las proporciones), en cualquier ancho de pantalla.
- **Tamaño de miniatura**: control deslizante de altura de tarjeta/fila (120–400 px, guardado en localStorage)
- **Ocultar detalles**: oculta los metadatos de las tarjetas (solo en modo cuadrícula)
- **Información emergente**: cómo aparecen los detalles de la foto: **Panel lateral** (por defecto), **Al pasar el cursor**, **Clic** o **Desactivada**.
  - El panel lateral muestra los detalles completos en el cajón de la derecha, con la misma disposición que el detalle de la foto. Sigue tanto al cursor como al clic, así que funciona en pantallas táctiles. Conserva la última foto cuando el cursor sale de la cuadrícula.
  - Hacer clic en una foto mantiene el panel en ella hasta que pulsas **Deseleccionar** (que también deselecciona la foto). **Escape** hace lo mismo y borra la selección.
  - El panel comparte el cajón con los filtros; abrir los filtros lo oculta. Necesita una ventana de al menos 1280 px de ancho.
  - **Al pasar el cursor** y **Clic** muestran una burbuja breve: categoría, agregada y posición, estética, composición, nitidez, exposición y una línea de EXIF.
- **Personalizar los botones de la tarjeta**: reordena y muestra/oculta los botones de la fila que aparece al pasar el cursor sobre una tarjeta. Hay nueve acciones: buscar similares, por qué esta puntuación, escribir metadatos, asignar un rostro, abrir el grupo de duplicados, el grupo de ráfaga, el conjunto de bracketing/panorámica o la pila de fotos, y abrir la página de la foto. Los botones de grupo solo aparecen en las fotos de un grupo así. Los botones de grupo de duplicados y de pila de fotos están activados por defecto; los demás son opcionales. Se guarda por navegador.
- **Ocultar parpadeos**: oculta las fotos con parpadeos detectados
- **Solo parpadeos / Solo duplicados**: muestra solo las fotos con parpadeo, o todos los miembros de cada grupo de duplicados. Los interruptores de ocultar se suspenden en esa vista.
- **Mostrar solo rechazadas**: lista solo tus fotos rechazadas. Procésalas con seleccionar todo y **Descartar a carpeta**, o con **Enviar todas las rechazadas a la papelera (del sistema)** en Descarte. Ambos limitan el ámbito del filtro a 10 000 fotos; acota por fecha o álbum para más, y desactiva los filtros que ocultan grupos para incluir todos los fotogramas rechazados. Deshabilitado mientras hay un estado de revisión seleccionado.
- **Mejor de ráfaga**: muestra solo la foto mejor puntuada de cada ráfaga
- **Mejor del horquillado**: muestra solo la exposición base de cada bracketing. **Activado por defecto.** Independiente de Mejor de ráfaga, porque la principal de la ráfaga de un bracketing no siempre es su exposición base.
- **Mejor del panorama**: muestra solo el fotograma central de cada conjunto de panorámica o panorámica HDR. **Activado por defecto.**
- **Desplazamiento infinito**: las fotos se cargan al desplazarte
- **Desplazamiento rápido (virtualizado)**: renderiza solo las filas cercanas a la ventana, de modo que el desplazamiento profundo sigue siendo rápido. Activado por defecto. Desactívalo en la pestaña Visualización de la barra lateral si tienes problemas de diseño. El modo cuadrícula con detalles visibles siempre se renderiza por completo. Se guarda en localStorage (`facet_virtual_scroll`).

### Fotos similares

Haz clic en **Similar** en una foto y elige un modo:

- **Visual** (por defecto): similitud pHash (70 %) + similitud CLIP/SigLIP (30 %). Cuando dos fotos comparten solo una de las dos señales, cuenta con su peso completo; las fotos que no comparten ninguna nunca se listan. Se devuelven todas las coincidencias por encima del umbral, página a página. Si la foto no tiene ninguna señal, reescanéala con `--force` (un simple `python facet.py <dir>` omite los archivos procesados).
- **Color**: intersección de histogramas (70 %) + distancia de saturación (10 %) + distancia de luminancia (10 %) + bonificación monocroma (10 %). Prefiltra por el indicador monocromo y el rango de saturación.
- **Persona**: fotos con la misma(s) persona(s), por `person_id` cuando está disponible; si no, por similitud de embeddings faciales.

El **control deslizante del umbral de similitud** (0–90 %) define lo estricta que es la coincidencia (no en el modo persona). Los resultados se desplazan sin fin.

### Chips de filtro

Los filtros activos aparecen como chips que se pueden quitar, con recuentos, en la parte superior de la galería.

### Tags manuales

Los tags manuales son etiquetas que escribes tú mismo, guardadas junto a las etiquetas de IA. Se almacenan aparte (`photo_manual_tags`, no la columna `tags` de la foto), así que los reescaneos y reetiquetados nunca las borran.

- **Dónde se muestran.** Solo en el **detalle** de la foto, como chips marcados de forma distinta a las etiquetas de IA. Las tarjetas y las informaciones emergentes muestran las etiquetas de IA.
- **Quién puede editarlas.** Los usuarios de edición. En una instalación sin `viewer.edition_password` son de solo lectura. Las etiquetas de IA no se pueden quitar.
- **Edición masiva.** Selecciona fotos y usa **Editar etiquetas** (barra de selección, hoja de Acciones móvil o menú contextual) para añadir o quitar una etiqueta. Funcionan las selecciones de toda la vista. Las fotos que ya tienen 50 tags manuales se omiten; `count` informa de las fotos realmente modificadas.
- **Formato.** Las etiquetas se recortan, se pasan a minúsculas y se colapsan los espacios (NFC). Máximo 64 caracteres, máximo 50 por foto. Se rechazan las etiquetas vacías, las comas y los caracteres de control. Una etiqueta igual a una de las etiquetas de IA de la foto no se guarda.
- **La búsqueda y los filtros las ven.** El filtro de etiquetas, la búsqueda de texto, la búsqueda semántica (`/api/search`, salvo el ámbito de texto solo de leyendas), el desplegable de etiquetas, las estadísticas y las exportaciones de sidecar/incrustación/Lightroom usan etiquetas de IA + manuales. La búsqueda de texto encuentra un tag manual como frase completa.
- **Excepciones.** Las cápsulas cuentan solo las etiquetas de IA. Los tags manuales nunca afectan a las puntuaciones, categorías ni momentos narrativos.
- **Ocultas en los enlaces compartidos.** Quienes ven un enlace compartido nunca las ven. Un álbum inteligente compartido sigue aplicando el filtro guardado del propietario.
- **Compartidas por todos los usuarios.** En modo multiusuario, cualquier usuario de edición puede quitar un tag que añadió otro.
- **No se pueden deshacer.** [Deshacer](#deshacer) no las cubre. Una etiqueta quitada puede volver desde un sidecar; ver [Reglas de conflicto](INTEROP.md#reglas-de-conflicto).
- **Etiquetas importadas.** `--import-sidecars` guarda las palabras clave desconocidas del sidecar (que no sean etiquetas de IA ni nombres de personas) como tags manuales con origen `xmp`.
- **Ligadas a la ruta del archivo.** Mover o renombrar un archivo hace perder sus tags manuales.

## Panorámicas y bracketing de exposición

Los fotogramas de una panorámica están pensados para coserse y los de un bracketing para fusionarse; no son tomas que compiten. La detección de ráfagas por sí sola los agruparía y ocultaría todos menos uno, así que Facet detecta estos conjuntos por separado.

**En la galería.** `Mejor del horquillado` y `Mejor del panorama` (ambos activados por defecto) muestran un fotograma por conjunto: la exposición base de un bracketing, el fotograma central de una panorámica. Ese fotograma lleva un pequeño icono junto a la estrella y el corazón: barrido simple, barrido HDR o bracketing de exposición. El icono aparece solo mientras el interruptor oculta el resto del conjunto.

**En el descarte.** El menú de granularidad ofrece `Horquillados de exposición`, `Panorámicas` y `Panorámicas HDR` como flujos propios, que nunca se mezclan con `Todas`. Todos los fotogramas empiezan conservados, y confirmar un conjunto no registra pares de comparación, de modo que el clasificador no se entrena con cómo se hizo un conjunto.

**Corregir un conjunto.** La detección falla en cerca del 4 % de los conjuntos. Las correcciones son persistentes: sobreviven a todas las ejecuciones de detección posteriores. Ambas requieren el modo de edición, al menos dos fotogramas, y se pueden deshacer desde la barra de aviso.

- **Falso positivo** (no es una panorámica, o simple frente a HDR): usa el menú de corrección de la barra de acciones del grupo en el descarte.
- **Panorámica no detectada**: selecciona sus fotogramas en la galería y elige *Marcar como serie* → *Marcar como un panorama*.

**Marcar un bracketing no detectado.** Para una escalera de exposición detectada como una ráfaga normal:

- En el cuarto oscuro, un grupo de ráfaga simple (sin ningún fotograma ya en un bracketing o panorámica) ofrece *Marcar como serie de exposición*.
- En la barra de selección de la galería, usa *Marcar como serie* → *Marcar como un horquillado*.
- Los fotogramas deben formar una escalera real: al menos 2 fotogramas, cada uno con datos de exposición (diafragma, velocidad de obturación, ISO) y una fecha de captura, y dos nunca con el mismo valor de exposición. Si no, la marca se rechaza con un mensaje y no se guarda nada.
- Marcar fotogramas que se solapan con un bracketing marcado existente lo amplía. El conjunto combinado debe seguir siendo una escalera válida.
- El flujo del cuarto oscuro oculta los fotogramas rechazados, así que una marca desde el cuarto oscuro nunca incluye un peldaño rechazado.
- Un grupo `bracket` ofrece en su lugar *Descartar la corrección*.
- Si un fotograma marcado desaparece o pierde sus datos de exposición o de fecha, todo el conjunto espera hasta que todos los miembros vuelvan a cumplir los requisitos.
- **Marcar prevalece sobre la detección de panorámicas**: una panorámica detectada que contiene fotogramas marcados se descarta en la siguiente ejecución.

**Las correcciones se aplican en la siguiente ejecución de detección.** Una corrección se guarda al instante y se muestra como pendiente: una insignia de reloj en la miniatura de la galería, un chip *Corrección pendiente* en el descarte. La página de descarte muestra un banner con un botón **Volver a ejecutar la detección**. El filtro *Correcciones de panorama* de la barra lateral (solo edición, en la pestaña Revisión) lista las correcciones pendientes de toda la biblioteca. *Descartar la corrección* quita una más tarde.

**Ajustarla.** La pestaña Panorámicas bajo Comparar contiene los umbrales calibrados: fotogramas mínimos, barrido mínimo, mayor intervalo y dispersión de exposición HDR. Guardarlos no cambia nada hasta que vuelvas a ejecutar la detección (el botón está junto a Guardar). Ver [CONFIGURATION.md](CONFIGURATION.md#detección-de-panorámicas).

## Gestión de personas

> Explorar personas está abierto a todos los visores; renombrar, fusionar, cambiar avatares y asignar rostros requieren `[Edition]`.

### Filtro de persona

El desplegable lista las personas con miniaturas de rostro. Haz clic en una para filtrar la galería.

### Galería de persona

Haz clic en el nombre de una persona para ver todas sus fotos en `/person/<id>`. En la página de gestión de personas, hacer doble clic en una tarjeta (con nombre, sin nombre en «Por nombrar» o ignorada) abre la galería con las fotos de esa persona; los dobles clics en el campo de nombre, la casilla y los botones quedan para ellos.

**Nombrar desde la galería.** Cuando la galería está filtrada por una persona (`?person_id=95`), su etiqueta en la fila de filtros activos muestra su cara y su nombre, o **Sin nombre**, resaltado con un contorno como recordatorio; su × (**Quitar del filtro**) quita a la persona del filtro. Para los usuarios de edición hay dos botones antes de la ×. **Renombrar** (el lápiz) renombra a la persona allí mismo: el campo de nombre muestra «¿Quién es? Escribe o elige un nombre» para una persona sin nombre y «Renombrar o fusionar con…» para una con nombre, sus sugerencias muestran la cara, el nombre y el número de fotos de cada persona, y **Guardar** o **Cancelar** lo cierra (Escape también cancela). El nombre siempre se guarda primero (`POST /api/persons/{id}/rename`); si otros grupos ya lo llevan (sin distinguir mayúsculas ni espacios, estén o no entre las sugerencias), la etiqueta ofrece después la misma fusión que la página Gestionar personas (ver **Renombrar** más abajo), y tras una fusión la galería pasa a la persona que se conserva. **Más** (⋮) abre el menú de la persona: **Ver todas las fotos de {name}**, **Buscar más caras de {name}** e **Ignorar** (**Restaurar** para una persona ignorada). Cuando las opciones de ocultación de la galería dejan fuera de la vista algunas fotos de la persona, los avisos de la galería indican cuántas, desglosadas en fotos de ráfaga, de parpadeo, duplicadas, de horquillado y de panorámica, para que las muestres antes de nombrar.

### Página Gestionar personas

En modo edición la página tiene dos pestañas, **Con nombre (N)** y **Por nombrar (N)**, y siempre se abre en **Con nombre**. **Por nombrar** lista los grupos sin nombre, cada uno con un campo de nombre; **Con nombre** reúne a las personas con nombre, con las ignoradas en una sección plegable **Ignoradas** al final. Los usuarios de solo lectura ven únicamente la cuadrícula de personas con nombre. Las sugerencias de nombre, aquí como en la etiqueta de persona de la galería y en el menú de caras de la foto, muestran la cara, el nombre y el número de fotos de cada persona. En **Por nombrar** el menú de orden ofrece **Cantidad de caras** y **Más recientes**. Cuando no queda nadie por nombrar, la pestaña muestra «Todos tienen nombre. Las caras nuevas que necesiten un nombre aparecerán aquí.»

Ábrela desde el botón de la cabecera o `/persons`:

| Acción | Cómo |
|--------|------|
| **Fusionar** | Selecciona la persona de origen, haz clic en el destino, confirma |
| **Eliminar** | Haz clic en el botón de eliminar de la tarjeta de la persona |
| **Renombrar** | Haz clic en el nombre de la persona para editarlo en línea. Si otros grupos ya llevan ese nombre (sin distinguir mayúsculas ni espacios alrededor), una confirmación muestra una ficha por persona (cara, nombre, número de caras), todas seleccionadas, con la persona que se conservará marcada: la más grande de las seleccionadas, que conserva su grafía. Deselecciona a un homónimo, o cancela, para mantenerlo aparte. Una fusión no se puede deshacer |
| **Dividir** | Abre los rostros de una persona, selecciona un subconjunto y divídelos en una persona nueva |
| **Buscar más caras** | El botón de búsqueda de la tarjeta de una persona, o **Buscar más caras de {name}** en un menú de persona, lista las caras que se le parecen, las más parecidas primero, comparadas con el centroide de la persona (`GET /api/person/{id}/possible_faces`). En **Qué caras incluir**, tres chips muestran cada uno su número: **Sin grupo** y **Grupos sin nombre**, activados por defecto, y **Personas con nombre**, desactivado. Una cara que pertenece a una persona con nombre lleva una etiqueta **de {name}**, y al marcar una aparece un aviso de que añadirla la pasa a esta persona. Sobre las caras, **Grupos parecidos** lista otros grupos cuyo centroide se parece al de esta persona (los sin nombre, más los con nombre mientras **Personas con nombre** está activado); cada uno muestra su foto, su nombre o **Grupo sin nombre**, su número de caras y **{percent} % parecido**, con **Fusionar todo** para incorporar el grupo entero a esta persona. Fusionar un grupo con nombre pide confirmación, y una fusión no se puede deshacer. Cada cara lleva **Fuerte** (50 % de parecido o más) o **Posible**, con su porcentaje, y **Cuánto parecido** fija el umbral: un botón de barras de señal que muestra `≥NN%` y abre el menú de niveles, con cinco niveles, **Muy estricto** 60 %, **Estricto** 50 %, **Normal** 35 % (por defecto), **Amplio** 25 % y **Muy amplio** 20 %. Si ninguna cara alcanza el umbral, el diálogo muestra «Ninguna cara se parece a {name} (la más cercana: N %).» y ofrece **Probar Amplio** o **Incluir personas con nombre**. Si una búsqueda tuviera que comparar demasiadas caras, busca solo entre las caras sin grupo; si siguen siendo demasiadas, pide un **Año** en el que buscar. **Seleccionar las fuertes**, Mayús+clic para un rango y Espacio sobre la cara enfocada agilizan la selección, y el botón Añadir muestra cuántas hay marcadas. Añadir recalcula el centroide, así que la siguiente ronda se ordena según lo que acabas de confirmar; las caras que dejas sin marcar no se vuelven a ofrecer mientras el diálogo esté abierto |
| **Ignorar** | Ignorar un grupo (personal, desconocidos): el botón ⊘ de una tarjeta, también en las tarjetas «Por nombrar». Las personas ignoradas salen de la lista, «Por nombrar», los filtros, las sugerencias de fusión y la búsqueda de caras, y aparecen en la sección plegable **Ignoradas** al final de la pestaña **Con nombre**, con **Restaurar** (`GET /api/persons?hidden_only=true`). Usa el mismo indicador `is_hidden` que antes. Ignorar se aplica al instante y muestra durante 10 segundos un aviso con **Deshacer**, aquí y en cada menú de persona. |
| Acción | Cómo hacerlo |
|--------|--------|

### Caras en la foto

En la vista de foto aparece un recuadro alrededor de cada cara detectada mientras el puntero está sobre la foto, y al pasar por una cara se muestra su nombre (recuadro rojo: aún sin nombre). Los recuadros siguen el zoom y el desplazamiento, y arrastrar o hacer doble clic sobre una cara sigue desplazando o restableciendo el zoom. El recuadro de una cara sin nombre además es discontinuo, para no depender solo del color, y cada recuadro tiene un contorno oscuro para verse sobre cualquier fondo. Salvo que los recuadros estén en **Desactivado**, con el teclado Tab pasa de una cara a otra, cada una anunciada por su nombre (o como cara desconocida), e Intro o Espacio abre su menú. En una pantalla táctil, un toque abre el menú de una cara solo mientras se muestran los recuadros (los recuadros están en **Siempre**, o, salvo en **Desactivado**, la cara es de la persona por la que se filtró la galería); si no, tocar la foto no hace nada con la cara. En modo edición, hacer clic en una cara abre un menú: **Cambiar de persona…** (o **Nombrar esta cara…**) para elegir una persona existente o escribir un nombre nuevo, **Buscar más caras de …** para esa persona y **No es …** para quitar solo esa cara a esa persona (`POST /api/face/{id}/unassign`); sus otras caras en la foto siguen asignadas a ella. No se dibujan las caras cuyas dimensiones guardadas no son fiables. Los recuadros vienen de `GET /api/photo/faces`, que devuelve el `box` de cada cara normalizado al encuadre. Toda cara que pertenece a una persona, con o sin nombre, ofrece también **Ver todas las fotos de …** (o **Ver todas las fotos de este grupo**), que abre la galería filtrada por esa persona; esto funciona también en modo de solo lectura. Un botón de la barra alterna los recuadros entre tres estados, que se recuerdan por navegador: **Desactivado** (sin recuadros, y las caras no se pueden pulsar ni enfocar), **Al pasar el puntero** (el predeterminado, como se describe arriba) y **Siempre** (todos los recuadros y nombres quedan visibles). Si la galería está filtrada por una persona, sus caras quedan enmarcadas con un trazo más grueso, salvo que los recuadros estén en **Desactivado**. **Usar como foto de …** convierte la cara pulsada en la foto de la tarjeta; una persona que recibe caras sin tener foto obtiene automáticamente la más fiable. En la galería filtrada por una persona, cada miniatura marca su cara en rojo, para ver de qué cara trata un grupo antes de nombrarlo. En la lista **Personas** del panel derecho, hacer clic en el avatar de una persona abre el mismo menú que hacer clic en el recuadro de esa cara, incluso con los recuadros en **Desactivado**; **Ver todas las fotos de …** en ese menú abre la galería.

### Marcar una cara no detectada

En modo de edición, abre una foto y elige **Marcar un rostro ausente**, incluso cuando no se detectó ningún rostro. Dibuja un rectángulo (o escribe sus coordenadas), elige una persona existente o escribe un nombre nuevo, y pulsa **Guardar**. Cancelar no guarda nada.

Al guardar, editar o eliminar un rostro manual, los recuadros y las personas de la foto se actualizan sin volver a abrirla.

- Usa el mismo editor para ajustar, reasignar o quitar una marca manual.
- Las marcas manuales siguen ligadas a su persona a través de los reescaneos y la sincronización del visor. No entrenan el reconocimiento ni cambian las puntuaciones de calidad facial.
- El editor trabaja desde la imagen original, de modo que las fotos RAW y giradas encajan. Sin el original puedes listar y quitar marcas, pero no dibujar.
- Una marca que no se puede verificar se muestra como **Requiere revisión**. Las marcas de compilaciones de vista previa anteriores necesitan una revisión: abre el original, edita y guarda la marca.
- Una imagen sustituida marca sus marcas. Un retoque sutil o un pequeño recorte del mismo tamaño puede pasar desapercibido. Las escrituras de metadatos, los remontajes y otros equipos mantienen las marcas al día.
- El editor reutiliza un fotograma decodificado de hasta 128 MiB; los fotogramas mayores pueden necesitar otra decodificación. El límite es fijo.
- Las marcas eliminadas siguen eliminadas durante la sincronización posterior.
- Los cambios viven en la base de datos de la biblioteca; los originales y los sidecars no se tocan.

> **Advertencia:** una reconstrucción forzada de la base de datos del visor sustituye las ediciones exclusivas del visor, incluidas las marcas manuales, por las de la base de datos de origen. Expórtalas o haz una copia de seguridad antes. La sincronización incremental normal las conserva.

El ajuste heredado `viewer.performance.face_cache_size` se ignora y se puede quitar.

## Activador de escaneo

Inicia un escaneo desde el navegador. El botón Escanear aparece cuando se cumplen **ambas** condiciones:

- `viewer.features.show_scan_button` es `true` (se distribuye como **`false`**).
- Tienes acceso de escaneo: el rol `superadmin` en modo multiusuario, o una sesión de edición en una instalación de un solo usuario con un `viewer.edition_password` no vacío.

En una instalación abierta de un solo usuario (`viewer.edition_password` vacío, el valor predeterminado), nadie puede escanear desde el navegador. Excepción: con `viewer.trusted_local_editing`, una sesión de navegador local de confianza, o un asistente local con un token de edición completa, puede escanear sin `show_scan_button` ni contraseña de edición.

El botón está en la galería vacía (**Escanea fotos para empezar**) y al final de la cabecera (**Buscar fotos nuevas**; barra inferior en pantallas pequeñas). Ambos abren el lanzador de escaneo:

- Elige un directorio de la lista e inicia el escaneo.
- El progreso en vivo y las líneas de salida se muestran en el diálogo. La galería se actualiza cuando termina el escaneo.
- El escaneo ejecuta `facet.py` en segundo plano; un escaneo a la vez.
- La lista de directorios combina los `directories` de cada usuario, los directorios compartidos, los destinos de `path_mapping` y `viewer.scan_directories`. Define `viewer.scan_directories` (p. ej. `/data/photos`) para que las instalaciones de un solo usuario y Docker tengan un destino.

No se necesita GPU: ver [¿Qué perfil se ajusta a mi hardware?](INSTALLATION.md#qué-perfil-se-ajusta-a-mi-hardware) y [Sin tarjeta gráfica](INSTALLATION.md#sin-tarjeta-gráfica). El escaneo se ejecuta en el equipo del visor, así que es más rápido cuando ese equipo tiene GPU.

Para repuntuar fotos existentes sin escanear archivos nuevos, usa `POST /api/scan/recompute` (solo edición): ver [Prioridad de categorías y contextos de puntuación](#prioridad-de-categorías-y-contextos-de-puntuación).

## Búsqueda semántica

Escribe una consulta como "atardecer sobre montañas" y obtén las fotos que coinciden. El ranking combina la similitud de embeddings CLIP/SigLIP (70 %) con la coincidencia de texto FTS5 BM25 sobre leyendas y etiquetas (30 %).

- **Requisitos.** Las fotos necesitan datos `clip_embedding` almacenados (calculados durante la puntuación). Ejecuta `database.py --rebuild-fts` para activar la parte de texto de leyendas/etiquetas.
- **Modelo.** Usa el modelo de embeddings del perfil de VRAM activo (SigLIP 2 para 16gb/24gb, CLIP ViT-L-14 para legacy/8gb), o el de `models.clip`/`clip_legacy` que coincida con los embeddings almacenados (ver [CONFIGURATION.md](CONFIGURATION.md)).
- **Velocidad.** Instalar sqlite-vec acelera la búsqueda; si no, Facet mantiene una matriz en memoria. La primera consulta en una biblioteca grande puede tardar varios segundos.
- **Umbral.** El umbral de coincidencia es por defecto `models.clip.search_threshold_percent` (`5%`) o `models.clip_legacy.search_threshold_percent` (15 %), independiente de `tag_threshold_percent`. El control deslizante de la galería abarca 0–50 %; `search_threshold_default` de `/api/config` define su inicio. Incluso `0%` rechaza la similitud negativa. El 5 % predeterminado de SigLIP favorece la exhaustividad: ver `clip.search_threshold_percent` en [CONFIGURATION.md](CONFIGURATION.md).
- **Solo texto.** `scope=text` restringe la consulta a coincidencias FTS5 literales en el texto de OCR/leyendas.
- **Funciona con todos los filtros de la galería**, incluidos los interruptores de ocultar. Con los valores por defecto, los miembros ocultos de ráfagas, duplicados, bracketings y panorámicas, los parpadeos y los rechazos siguen ocultos.
- **Sin límite de resultados.** La galería pagina los resultados y muestra el total real.
- **Orden por relevancia.** Con una consulta activa, la ordenación es por defecto **Relevancia** (mejor coincidencia primero). Borrar la consulta restaura la ordenación predeterminada.
- **Selección.** Seleccionar todo cubre solo las fotos cargadas; aquí no está disponible el ámbito de toda la vista.
- Se controla con `viewer.features.show_semantic_search` (por defecto: `true`).

Los resultados informan `similarity` (la puntuación combinada) y `embedding_similarity` (el coseno bruto comparado con el umbral, ausente en los resultados solo de texto). Los parámetros de galería `semantic_q`, `semantic_threshold` y `sort=relevance` están documentados en [API.md](../API.md).

## Álbumes

Organiza las fotos en álbumes con nombre en `/albums`. Se controla con `viewer.features.show_albums` (por defecto: `true`).

### Álbumes manuales

Crea álbumes y añade fotos desde la galería con la selección múltiple. Los álbumes admiten:
- Nombre y descripción
- Foto de portada personalizada
- Orden personalizado
- Explorar el contenido del álbum en `/album/:albumId`

### Álbumes inteligentes

Guarda una combinación de filtros (cámara, etiqueta, persona, fechas, umbrales de puntuación…) como álbum inteligente. Se actualiza a medida que coinciden fotos nuevas. Los filtros se guardan como JSON en `smart_filter_json`.

### Contexto de puntuación

Un álbum puede llevar un contexto de puntuación que decide qué categoría gana para sus fotos, independientemente de la prioridad global: ver [Contextos de puntuación](CONFIGURATION.md#contextos-de-puntuación). Defínelo desde el diálogo del álbum (modo de edición).

- Al definirlo, el contexto se aplica a los miembros **actuales** del álbum. Una foto con su propia anulación manual se deja como está.
- Los miembros de un álbum inteligente proceden de su filtro guardado, ignorando los interruptores de ocultar de la galería, así que el recuento puede superar lo que muestra la vista del álbum.
- Las fotos añadidas más tarde a un álbum manual heredan el contexto. Las nuevas coincidencias de un álbum inteligente no; vuelve a definir el contexto.
- **Borrar contexto** (no es lo mismo que elegir `default`) quita la marca. Una foto que sigue en otro álbum con contexto recibe ese contexto.
- Facet puede sugerir un contexto a partir del momento narrativo dominante del álbum (mediante el `suggest_from_moments` de cada contexto). No escribe nada hasta que confirmes.
- Ejecuta un recálculo (`POST /api/scan/recompute`) para que el nuevo contexto cambie las categorías almacenadas.

Endpoints y recuentos de respuesta: [API.md](../API.md#albums).

### Exportación de portafolio

Convierte un álbum manual en una galería HTML estática autónoma. Con `viewer.features.show_portfolio_export` activado (por defecto `true`) y la edición desbloqueada, cada tarjeta de álbum manual tiene **Exportar portafolio**. Elige un título, una carpeta de destino y si se incluyen las leyendas.

- La salida contiene `index.html` (una cuadrícula de miniaturas con un visor integrado, sin referencias externas ni a CDN, funciona sin conexión), una carpeta `assets/` con JPEG de nombre secuencial (sin filtrar rutas de la biblioteca) y un `manifest.json`.
- Cada foto usa el original, reducido a `portfolio.max_edge`, o la miniatura almacenada de 640 px si el original no es accesible.
- La carpeta de destino debe estar en la lista de permitidas de exportación (`viewer.export.allowed_target_dirs` más los directorios de escaneo, ver [Configuración — Destinos de exportación y descarte](CONFIGURATION.md#destinos-de-exportación-y-descarte)).
- Los álbumes de más de `portfolio.max_photos` (por defecto 500) se rechazan.
- Reexportar reescribe solo los archivos propios de la exportación.

Ver [configuración de Exportación de portafolio](CONFIGURATION.md#exportación-de-portafolio). Endpoint: `POST /api/albums/{album_id}/export-portfolio`.

### Compartir fotos

Comparte álbumes mediante enlaces con token. Ver un álbum compartido no requiere iniciar sesión.

| Acción | Cómo |
|--------|------|
| **Compartir** | Abre el álbum y haz clic en el botón "Compartir" para generar un enlace |
| **Revocar** | Haz clic en "Dejar de compartir" para invalidar el token |
| **Ver** | Los destinatarios abren el enlace para explorar el álbum compartido en `/shared/album/:id` |

### Revisión del cliente

Deja que un cliente elija favoritas de una entrega. Con `viewer.features.show_proofing` activado (por defecto `false`), un enlace compartido puede funcionar en **modo de revisión**: el cliente lo abre, introduce un PIN si está definido (`viewer.proofing.pin`), y luego marca fotos con un **corazón** y deja **comentarios**.

- Las elecciones del cliente se guardan aparte (`album_client_picks`) y nunca tocan tus favoritos ni valoraciones, ni entrenan el clasificador.
- Lee las elecciones desde un diálogo `[Edition]` en la tarjeta del álbum.
- Las sesiones duran `viewer.proofing.session_minutes` (por defecto 24 h) y terminan cuando se deja de compartir el álbum o se desactiva la revisión.

Ver [Configuración — Revisión del cliente](CONFIGURATION.md#revisión-del-cliente).

## Crítica con IA

Explica la puntuación de una foto como fortalezas, debilidades y sugerencias. Se controla con `viewer.features.show_critique` (por defecto: `true`).

### Crítica basada en reglas

Disponible en todos los perfiles de VRAM. Facet recalcula la puntuación a partir de las métricas almacenadas de la foto y la configuración actual, y muestra el cálculo.

- La **Categoría** es la que asigna la fórmula actual (respetando una anulación de categoría y un contexto de puntuación). Puede diferir de la categoría almacenada hasta el siguiente `--recompute-average`.
- Las **filas de desglose** muestran cada entrada de 0–10 que pondera el puntuador (más alto es mejor, así que el ruido y el rango dinámico se leen como calidad), con su peso y contribución.
- Los **ajustes netos y el redondeo** (bonificación, multiplicador de parpadeo, recorte, penalizaciones de ruido y sobresaturación, límites) concilian las filas con el total del **Cálculo actual**, mostrado junto a la **Puntuación almacenada**.
- Las **Condiciones detectadas** listan el parpadeo y una dominante en el tono de piel.
- La nitidez, el color y la nitidez de ojos usan la instantánea de percentiles del último `--recompute-average`. Una biblioteca que solo se ha escaneado usa los valores del escaneo.
- Las **filas informativas**, mostradas solo cuando se calculan: forma y armonía de color (simetría, equilibrio, entropía de orientación de bordes, complejidad fractal, armonía de color de Matsuda; `--recompute-form`), chips de distorsión (desenfoque por movimiento, dominante de color, exceso de nitidez…; `--recompute-distortions`) y una nota de tono de piel para retratos (`--recompute-skin-tone`). Explican la foto pero no cambian el agregado.

Si el cálculo no está disponible, solo se muestra la puntuación almacenada, con la solución:

| Motivo | Solución |
|--------|----------|
| Esquema desactualizado | `python database.py` |
| Instantánea de normalización no disponible | Reintenta y luego `python facet.py --recompute-average` |
| Métricas almacenadas no válidas | Vuelve a escanear con `--force` |

El diálogo también distingue una foto *aún sin puntuar* de otra cuya *puntuación almacenada es inutilizable*.

### Crítica con VLM `[GPU]` `[16gb/24gb]`

Usa el VLM configurado (Qwen3.5-2B o Qwen3.5-4B) para una crítica con contexto. Necesita el perfil 16gb o 24gb, `viewer.features.show_vlm_critique` en `true` (el valor por defecto) y una sesión de edición para generarla. Sin edición, solo se muestra una crítica en caché y `vlm_available` es `false`. El diálogo genera mediante `POST /api/critique/vlm` (solo edición; las peticiones simultáneas para una misma foto comparten una sola generación); `GET /api/critique` solo lee la caché y nunca genera, traduce ni escribe.

- El prompt (`critique.vlm`) incluye el desglose de la puntuación, las puntuaciones almacenada y recalculada, las condiciones detectadas y el EXIF.
- La respuesta se lee como **Observación / Valoración / Sugerencias**. Se guarda en caché por foto (`photos.vlm_critique`), se traduce cuando una sesión de edición la abre en el idioma de destino (luego se guarda y se sirve tal cual), y **Regenerar** la recalcula. Sin una sesión de edición ves el texto sin traducir, salvo que ya exista una traducción guardada.
- Se ejecuta sobre la miniatura almacenada, así que los archivos RAW funcionan.

**Superposición visual de "por qué esta puntuación".** Con `viewer.features.show_saliency_overlay` activado (por defecto `true`), el diálogo de crítica tiene **Mostrar superposición**. Dibuja el mapa de saliencia de BiRefNet como mapa de calor (`GET /api/saliency_overlay`), además de los cuadros de rostro y las marcas de ojos a partir de los puntos de referencia almacenados (`GET /api/photo/face_markers`). Los cuadros son verdes con los ojos abiertos y ámbar con un parpadeo. El mapa de calor tiene la resolución de la miniatura, así que es aproximado. El interruptor se oculta en los perfiles que no pueden producir una máscara de saliencia.

## Subtitulado con IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtén una leyenda en lenguaje natural para cualquier foto. Una sesión de edición la genera en la primera petición; después se guarda en caché en la columna `caption`. Edita las leyendas en el detalle de la foto (modo de edición). Una instalación abierta de solo lectura nunca genera una. `POST /api/caption` la genera (y la traduce); `GET /api/caption` solo devuelve la leyenda o la traducción guardada y nunca genera, traduce ni escribe.

Generación y traducción masivas desde la CLI:

```bash
python facet.py --generate-captions      # Generate captions for all uncaptioned photos
python facet.py --translate-captions     # Translate captions to configured target language
```

La traducción usa MarianMT en CPU (no hace falta GPU). Define el idioma con `translation.target_language` (por defecto: `"fr"`). Compatibles: francés, alemán, español, italiano.

Se controla con `viewer.features.show_captions` (por defecto: `true`). Sin el perfil 16gb/24gb o un `vlm_backend` remoto, el botón Generar leyenda está oculto y las críticas siguen basadas en reglas.

## Recuerdos ("En este día")

Mira las fotos tomadas en la fecha de hoy en años anteriores. Recuerdos abre una presentación aleatoria a pantalla completa.

Se controla con `viewer.features.show_memories` (por defecto: `true`).

## Flujos de trabajo habituales

- **Descartar unas vacaciones**: abre Cápsulas y busca la cápsula `journey` del viaje. Cada cápsula se puede guardar como álbum.
- **Revisar día a día**: abre la Línea de tiempo y profundiza en años → meses → días. Haz clic en un día para abrir la galería filtrada por él.
- **Mostrar lo que está oculto**: por defecto la galería oculta los parpadeos y las ráfagas y duplicados que no son la principal. Cuando algo está oculto, aparece abajo a la derecha el aviso "N fotos ocultas por los filtros actuales · Mostrar todo".
- **Volver a tus filtros**: el icono de fotos de la cabecera vuelve a la galería con los filtros, la ordenación y la posición en que la dejaste. Púlsalo dos veces, o restablece los filtros, para empezar desde los valores por defecto.

## Vista de línea de tiempo

Explora cronológicamente: los años se desglosan en meses y luego en un calendario de días. Cada mosaico muestra un recuento de fotos y una foto de portada. Haz clic en un día para abrir la galería filtrada por esa fecha; ordena allí.

Se aplican los cinco interruptores de ocultar de la galería (`hide_blinks`, `hide_bursts`, `hide_duplicates`, `hide_brackets`, `hide_panoramas`), con `viewer.defaults` como valor inicial, de modo que los recuentos de los mosaicos coinciden con lo que muestra la galería. Cuando algo está oculto, aparece en la barra de herramientas un botón `visibility_off` ("Algunas fotos están ocultas por tus filtros"); haz clic para borrar los cinco.

Abre `/timeline`. Se controla con `viewer.features.show_timeline` (por defecto: `true`).

## Vista de mapa

Mira las fotos en un mapa interactivo de Leaflet, agrupadas por nivel de zoom, a partir de sus coordenadas GPS del EXIF.

### Configuración inicial

Extrae las coordenadas GPS de las fotos existentes:

```bash
python facet.py --extract-gps    # Extract GPS lat/lng from EXIF into database
```

Las fotos nuevas obtienen sus coordenadas durante la puntuación.

Abre `/map`. Se controla con `viewer.features.show_map` (por defecto: `true`). Los fondos del mapa proceden de OpenStreetMap y necesitan conexión a internet, incluso en la aplicación instalada.

### Lugares guardados y GPS manual

**Encuentra fotos sin ubicación.** En los filtros, abre **Ubicación** y activa **Sin geolocalización**. Se puede guardar en un álbum inteligente. Se desactiva al iniciar una búsqueda semántica/de similares o al elegir un radio en el mapa.

**Define la ubicación de una foto.** En modo de edición, abre **Añadir ubicación** o **Editar ubicación** en una foto. Busca en **Lugares guardados**, elige una **Ubicación reciente**, coloca un marcador o escribe coordenadas. **Guardar** la aplica.

**Define muchas a la vez.** Selecciona fotos y elige **Definir ubicación** (barra de selección, acciones móviles o menú contextual).

- **Solo fotos sin ubicación** está activado por defecto; desactívalo para sustituir las ubicaciones existentes.
- **Previsualizar cambios de ubicación** muestra cuántas cambiarán o se omitirán. Si algo cambia entretanto, previsualiza de nuevo.
- Hasta 1000 fotos visibles por lote, incluidas las selecciones de toda la vista.

**Lugares guardados.** Elige un punto y usa **Guardar este lugar** con un nombre (p. ej. "Trabajo"), o marca como favorito el punto de una foto geoetiquetada. Renombra o elimina desde la lista; eso no mueve las fotos ya asignadas. Cada editor tiene una lista privada: hasta 100 lugares guardados y 20 puntos recientes.

**Las ubicaciones manuales se mantienen.** Una ubicación definida en el visor sobrevive a los reescaneos y a la reextracción del EXIF, incluida una borrada. **Usar la ubicación del archivo** elimina la anulación y vuelve a leer el GPS del archivo (o lo borra si el archivo no tiene).

**Escritura en archivos.** Guardar nunca escribe el archivo de imagen. Una exportación explícita de metadatos escribe las ubicaciones manuales (y los borrados explícitos) en el sidecar XMP: en el visor o con `--export-sidecars`. La incrustación (**Escribir metadatos en el archivo**, o `--embed-originals`) también escribe el GPS EXIF en los originales compatibles. Ver [INTEROP](INTEROP.md).

### Búsqueda de lugares en línea

Usa **Dirección o negocio → Buscar en línea** para buscar un lugar con Photon (datos de OpenStreetMap, © colaboradores de OpenStreetMap). La consulta se envía solo cuando haces clic en **Buscar en línea** o pulsas Intro. Elige un resultado para previsualizarlo y luego **Guardar**. Los lugares guardados y las coordenadas funcionan sin conexión.

- `viewer.place_search_url` (por defecto `https://photon.komoot.io/api`) apunta al proveedor. Usa un Photon autoalojado, o `""` para desactivar la búsqueda.
- La demo pública no tiene garantía de disponibilidad. Usa un solo worker del visor con ella, ya que cada worker tiene su propio límite de frecuencia.
- Las consultas admiten entre 3 y 200 puntos de código Unicode y devuelven hasta cinco resultados en cinco segundos, en una respuesta de como máximo 64 KiB. Las etiquetas de resultado se limitan a 600 caracteres Unicode.
- Una caché por proceso guarda 128 búsquedas durante 15 minutos. En modo multiusuario cada cuenta ve solo sus propias entradas, pero la capacidad de 128 entradas y la limitación del proveedor se comparten en todo el proceso.
- Facet espera al menos un segundo entre llamadas al proveedor y nunca envía dos a la vez.
- Facet no registra las consultas. Configura tu proxy inverso para que no registre las cadenas de consulta.

## Cápsulas

Presentaciones temáticas agrupadas por tema, lugar, personas y tiempo. Abre `/capsules` y haz clic en una cápsula para reproducirla.

### Tipos de cápsula

Facet genera cápsulas a partir de tu biblioteca:

- **Journey**: viajes detectados mediante agrupación por GPS, con nombres de destino obtenidos por geocodificación inversa ("Viaje a Roma — marzo de 2025")
- **Moments with [Person]**: las mejores fotos de cada persona reconocida
- **Seasonal Palette**: fotos agrupadas por estación + año
- **Golden Collection**: el 1 % superior por puntuación agregada
- **Color Story**: grupos visualmente similares mediante agrupación de embeddings CLIP
- **This Week, Years Ago**: "En este día" ampliado a ±3 días
- **Location**: grupos de fotos geoetiquetadas con nombres de lugar
- **Favorites**: fotos favoritas agrupadas por año y estación
- **Basadas en dimensiones**: por cámara, objetivo, categoría, patrón de composición, rango de distancia focal, hora del día, valoración por estrellas y combinaciones

### Pase de diapositivas

Haz clic en la tarjeta de una cápsula para iniciar una presentación:
- **Transiciones temáticas**: deslizamiento (viajes), zoom (retratos), kenburns (doradas/estacionales), fundido (por defecto)
- **Encadenado automático**: cuando termina una cápsula, una tarjeta muestra la siguiente
- **Mezclar y reanudar**: las fotos se mezclan; tu posición se conserva por cápsula
- **Agrupación adaptativa**: los retratos se muestran en paralelo para ajustarse a la pantalla
- **Guardar como álbum**: conserva cualquier cápsula como álbum

### Frescura

Las cápsulas rotan según un horario (por defecto: 24 horas). **Regenerar** en la cabecera las actualiza ahora.

### Geocodificación inversa

Las cápsulas de ubicación y de viaje muestran nombres de lugar (p. ej., "París, Francia") mediante el paquete sin conexión `reverse_geocoder`. Sin llamadas a API; los resultados se guardan en caché en la base de datos.

Instalación: `pip install reverse_geocoder`

### Configuración

Consulta [Configuración — Cápsulas](CONFIGURATION.md#cápsulas) para todos los ajustes.

## Vista de carpetas

Explora por directorio en `/folders`.

- Las migas de pan suben por el árbol.
- Cada carpeta muestra como portada su foto de mayor puntuación.
- Haz clic en una carpeta para abrirla, o en una foto para abrirla en la galería.
- Cada tarjeta de carpeta tiene una acción de filtro que abre la galería restringida a esa carpeta.
- En modo multiusuario, solo ves tus directorios.

### Filtro por carpeta

La sección **Carpeta** de la barra lateral de filtros tiene **Elegir carpeta…**, un selector que recorre el árbol. Al aplicarlo, la galería se restringe a esa carpeta **y sus subcarpetas**. Se muestra como chip, se combina con otros filtros, sobrevive a una recarga (parámetro de URL `path_prefix`) y se guarda en los álbumes inteligentes.

Solo acota la cuadrícula de fotos. Los desplegables de la barra lateral, los recuentos por tipo, las estadísticas, la línea de tiempo, el mapa y la búsqueda siguen abarcando toda la biblioteca.

## Diálogo de filtro GPS

Filtra las fotos por ubicación con un selector de mapa:

- Haz clic en el botón del filtro de ubicación para abrir el mapa.
- Haz clic o arrastra para definir un punto central.
- Ajusta el control deslizante del radio.
- Las fotos dentro del radio aparecen en la galería.
- Requiere coordenadas GPS (ejecuta `--extract-gps` si las fotos tienen datos GPS en el EXIF).

## Sugerencias de fusión

Encuentra grupos de personas que pueden ser la misma persona. Abre `/merge-suggestions` o ve desde la página Gestionar personas.

- **Control deslizante del umbral de similitud**: más bajo muestra más sugerencias, más alto menos
- **Fusionar**: acepta una sugerencia
- **Fusión por lotes**: fusiona varias sugerencias a la vez
- Las sugerencias descartadas no se vuelven a proponer
- CLI: `python facet.py --suggest-person-merges`

## Exportación al editor

Escribe valoraciones, favoritos y rechazos en sidecars XMP para que darktable, Lightroom y otros editores los recojan. Requiere el modo de edición.

- **Desde la galería**: selecciona fotos y luego **Acciones → Exportar** escribe un sidecar junto a cada archivo.
- **Desde un álbum**: exporta todo el álbum como sidecars, o copia/enlaza simbólicamente sus archivos a una carpeta (misma lista de permitidas que [Descartar a carpeta](#descartar-a-carpeta)). Los álbumes usan su pertenencia almacenada, álbumes inteligentes incluidos.
- **Escribir metadatos en el archivo**: en el detalle de la foto, incrusta la valoración y las palabras clave en el original (JPEG/HEIC/TIFF/PNG/DNG mediante exiftool) además de escribir el sidecar. Los archivos RAW propietarios nunca se modifican. Se controla con `viewer.features.show_embed_metadata` (por defecto: `true`).
- **Lightroom** (modo de edición): **Descargar manifiesto de Lightroom** guarda `facet_manifest.json` para la selección del diálogo, para el paso **Facet: Apply ratings and flags...** de `facet.lrplugin`. **Importar estado de Lightroom…** lee el `facet_lightroom_state.json` del menú **Facet: Export Lightroom State to Facet...** del plugin (gana Lightroom en valoración y pick/rechazo) e informa de los recuentos de coincidentes/no coincidentes/cambiados. No hace falta ejecutar `--import-lightroom`. Ver [Lightroom Classic](INTEROP.md#lightroom-classic).

**Límites y progreso.**

- Las exportaciones están limitadas a 10 000 fotos, tanto para selecciones como para vistas filtradas y álbumes. Un conjunto mayor se rechaza antes de escribir nada; acota los filtros y reinténtalo.
- Las exportaciones se ejecutan en segundo plano, con progreso y recuentos de escritos/omitidos/errores. **Detener tras el archivo actual** cancela entre archivos; los sidecars completados permanecen.
- Solo se ejecuta un trabajo de biblioteca a la vez. Mientras se ejecuta una exportación, los escaneos, recálculos y reentrenamientos automáticos esperan o se rechazan, y una exportación se rechaza mientras se ejecuta alguno de ellos.
- Cerrar el diálogo deja de vigilar el progreso, no la exportación.
- Vuelve a abrir Exportar al editor para ver tus 20 exportaciones más recientes. **Reintentar archivos sin terminar** inicia un trabajo nuevo para los archivos fallidos, omitidos y sin procesar. Un archivo interrumpido durante la escritura puede escribirse de nuevo.

## Descarga

Descarga fotos desde el detalle de la foto o la barra de selección. El menú de descarga por foto lista los tipos disponibles para esa foto, incluidos los perfiles de darktable configurados:

- **Original** (`original`): el archivo tal cual (JPG/HEIF), o un RAW convertido a JPEG con el mismo renderizado que muestra el visor. Por tanto, un fotograma de bracketing se descarga sin corrección de exposición: ver [CONFIGURATION.md](CONFIGURATION.md#las-tomas-de-un-horquillado-se-representan-sin-corrección).
- **darktable** (`darktable`): el RAW acompañante convertido con un perfil darktable con nombre. Recurre al original si no hay RAW acompañante.
- **RAW** (`raw`): el archivo RAW acompañante tal cual. No disponible en álbumes compartidos.

**Recorte social con detección de saliencia.** Con `viewer.features.show_social_export` activado (por defecto `true`) y la edición desbloqueada, la barra de descarga del detalle de la foto tiene un menú **Recorte social**. Lista `social_export.presets` (cuadrado 1:1, retrato 4:5, historia 9:16 por defecto). Al elegir uno se descarga un JPEG a resolución completa recortado a esa proporción y centrado en el sujeto. El sujeto procede del cuadro de sujeto de BiRefNet (`photos.subject_bbox`, de `--recompute-saliency`), si no de los rostros detectados, si no del centro. La información emergente del menú muestra cuál se usó (`saliency` / `faces` / `center`).

Endpoints: [API.md — Descarga](../API.md#download).

## Descarte

La página de descarte (`/culling`, modo de edición) agrupa tomas casi idénticas para que conserves la mejor de cada una y rechaces el resto. Elige las mejores de cada grupo; al confirmar se rechazan las demás. Las confirmaciones se aplazan y se pueden deshacer (ver [Deshacer](#deshacer)).

La **Granularidad** (el primer control de la barra de herramientas) elige cómo se agrupan las fotos:

- **Todas** (por defecto): ráfagas y grupos de similares combinados.
- **Ráfagas**: fotos tomadas muy cerca en el tiempo.
- **Similares**: fotos parecidas sea cual sea su momento, por similitud CLIP/SigLIP. Un control deslizante define lo estricta que es.
- **Escenas**: tramos cronológicos de captura, cada uno encabezado por su intervalo de tiempo y su momento narrativo principal. Requiere `viewer.features.show_scenes`.
- **Horquillados de exposición**: conjuntos encontrados por [`--detect-sequences`](COMMANDS.md), la exposición base primero, cada fotograma con la insignia de su compensación (`-2 EV` … `+2 EV`).
- **Panorámicas**: barridos encontrados por [`--detect-panoramas`](COMMANDS.md), en orden de captura, con el fotograma central marcado.
- **Panorámicas HDR**: barridos de panorámica con una dispersión de exposición superior a `hdr_min_span_stops`. Un conjunto HDR con trípode aparece primero en **Horquillados de exposición** y pasa aquí (como `hdr_panorama`) cuando la pasada de panorámicas reconoce el barrido. Si nunca lo hace, sigue siendo un bracketing.

**Conjuntos que se conservan enteros.** Los horquillados de exposición, las panorámicas y las panorámicas HDR no forman parte de **Todas**. Todos los fotogramas empiezan conservados y confirmar no registra pares de comparación. El doble clic ("conservar solo esta") no hace nada allí. Estos flujos ignoran los interruptores `hide_*` de la galería y muestran todos los fotogramas. Para descartar las exposiciones laterales, usa el recorte de bracketings del descarte automático (más abajo).

Un grupo que se queda con menos de 2 fotogramas tras quitar las fotos ya rechazadas se elimina del flujo.

**Ordenación.** El **modo de ordenación** (más fácil primero, más redundante, mejor, más reciente, necesita comparaciones, **más antigua primero**) está junto a la granularidad, con un botón de flecha que lo invierte. Más antigua primero también ordena las fotos *dentro* de cada grupo por hora de captura, lo que conviene a bracketings y panorámicas.

La granularidad, la ordenación y la categoría se guardan en `localStorage`. Los controles que no se aplican se ocultan (sin ordenación ni umbral en el modo de escenas; sin botón de ámbito si no hay álbumes manuales). En pantallas pequeñas, la barra de herramientas pasa a ser una barra inferior desplazable.

**Enviar todas las rechazadas a la papelera (del sistema).** Este botón de la barra de herramientas previsualiza todas las fotos rechazadas visibles para ti en toda la biblioteca, incluidos los fotogramas ocultos. Ignora los filtros de álbum, fecha y galería. **Aplicar** envía los archivos a la papelera del sistema del equipo de Facet. A diferencia de **Eliminar**, las filas de la biblioteca y las decisiones permanecen, para My Taste.

- Requiere acceso de edición, `viewer.cull.allow_trash` y compatibilidad con la papelera.
- Limitado a 10 000 fotos. Para más, usa Mostrar solo rechazadas en la galería, acota por fecha o álbum, y usa Descartar a carpeta → Enviar rechazadas a la papelera por lotes. Desactiva los filtros que ocultan grupos para incluir todos los fotogramas rechazados.
- Los archivos RAW/XMP acompañantes son opcionales.
- Si los archivos resueltos, las opciones o el destino cambiaron desde la vista previa, Aplicar se rechaza; previsualiza de nuevo. La comprobación compara nombres de archivo y ajustes, no el contenido de los archivos, y no bloquea los archivos.
- Un fallo del sistema de archivos a mitad deja enviados a la papelera los archivos completados; el diálogo permanece abierto para una nueva vista previa.
- En contenedores, la papelera y la recuperación dependen del sistema de archivos del servidor.

> **Advertencia:** en una biblioteca compartida, Enviar todas las rechazadas a la papelera usa solo *tus* rechazos. Envía a la papelera los archivos compartidos aunque otro usuario los haya conservado, marcado como favoritos o valorado. Revisa la vista previa.

**Descarte con ámbito.** Acota el cuarto oscuro con parámetros de URL: `?group_by=scene` para escenas, `?album=<id>` para un álbum, `?from=&to=` para una ventana de hora de captura (texto EXIF o fechas ISO como `2026-06-01`). Un banner muestra el ámbito con **Salir de la escena**. Las ráfagas que cruzan el borde de la ventana siguen mostrando todos sus fotogramas.

**Intervalo de fechas.** El botón de **intervalo de fechas** (icono `date_range`) ofrece **Últimos 7 días**, **Últimos 30 días**, **Este año**, **El año pasado**, **Intervalo personalizado...** y **Todas las fechas**. Las fechas se muestran como dd/MM/yyyy.

- Se combina con el ámbito del álbum. Las fotos sin fecha de captura salen de un intervalo con fechas.
- Los valores predefinidos se resuelven al elegirlos, así que un "Últimos 7 días" guardado en marcadores es una ventana fija.
- El intervalo vive solo en la URL (`?from=2026-07-01&to=2026-07-31`), no en `localStorage`.
- Cambiarlo recarga el flujo: se confirma una confirmación pendiente y se descartan las selecciones y omisiones sin confirmar.

**Línea de My Taste.** Cada confirmación registra comparaciones `source='culling'` que entrenan el clasificador personal. El diálogo de Ayuda (menú de usuario → Ayuda) muestra "My Taste · N comparaciones" (`GET /api/ranker/status`) y lista los atajos de descarte.

**Perfiles por género.** El selector de **Perfil** aplica un preajuste de género que define de una vez el rigor, el presupuesto de fotos conservadas, el umbral de similitud y los límites de ojos cerrados / mala expresión. Deportes conserva solo la más nítida de una ráfaga, las bodas conservan más variantes con los ojos abiertos, los conciertos y la fauna relajan los límites de rostro. La elección y el control deslizante de rigor se guardan en `localStorage`. Cambiar un control a mano muestra "Personalizado". Los preajustes viven en [`cull_profiles`](CONFIGURATION.md#perfiles-de-descarte-por-género) (`GET /api/culling/profiles`).

### Descarte automático

El **Descarte automático** de la barra de herramientas descarta todo un ámbito de una pasada.

1. Elige el ámbito: todos los grupos, o solo ráfagas / similares / escenas, opcionalmente un álbum o una ventana de fechas.
2. Define el **rigor** (más alto conserva menos por grupo).
3. Previsualiza. Cada grupo conserva su mejor foto más todo lo que caiga dentro del margen de rigor (al menos un mínimo por grupo), y rechaza el resto.
4. Confirma. Se registran los rechazos, las fotos conservadas se marcan como **Conservada**, y My Taste aprende de ello.

- La vista previa es una **simulación**: no se escribe nada.
- Un álbum opcional de **Destacadas** reúne la mejor foto de cada grupo con una puntuación de al menos `auto_cull.highlights_min`.
- Una insignia "mejor foto en este grupo" señala los grupos donde el descarte automático conservaría un fotograma distinto de la principal actual.
- Cuando se ha entrenado una cabeza de clasificación de conservación y supera su umbral de precisión, elige ella la foto a conservar (`keeper_prob`). Si no, lo hace la heurística habitual.
- El botón está oculto en las granularidades que se conservan enteras. En un ámbito mixto, los bracketings se deciden primero.
- Configúralo con el bloque [`auto_cull`](CONFIGURATION.md#descarte-automático) (`POST /api/culling/auto`). Ejecútalo desde la terminal con `python facet.py --auto-cull`: ver [Descarte](COMMANDS.md#descarte-desde-la-terminal).

**Recorte de bracketings redundantes** (`trim_brackets`, desactivado por defecto) es la única forma en que el descarte automático reduce un conjunto. Cuando la exposición base de un bracketing no recorta ni sombras ni luces, los fotogramas laterales no aportan nada, así que solo se conserva el fotograma base. Los conjuntos cuyo recorte base nunca se midió se dejan como están.

### Modo plan del asistente

Cuando un asistente conectado mediante [Agentes de IA (MCP)](AGENTS.md) previsualiza un descarte automático (`auto_cull`, o `ui_show_culling_plan`), tu pestaña abierta carga ese plan en `/culling`. Es el cuarto oscuro normal (lupa `Z`, comparar 2 / 4 a la vez, peaking), con las fotos a conservar del plan ya preseleccionadas.

- Un banner dice **Plan del asistente · x/y confirmados · Salir**.
- Cada grupo tiene un chip como **#3 · motivo · conservar 2 / rechazar 1 sugeridos**. Un chip azul de cabecera es la nota del asistente sobre el grupo.
- Un punto en un fotograma significa que lo cambiaste respecto al plan.
- Una insignia discontinua **Asistente: conservar** / **Asistente: rechazar** es la sugerencia del asistente, con su motivo en la información emergente. Haz clic (o Intro/Espacio) para aplicarla; aun así confirmas el grupo.
- Confirma grupo a grupo como de costumbre, con la cuenta atrás y **Deshacer**. Las confirmaciones en modo plan nunca añaden a un álbum de destacadas.
- Un grupo de ráfaga o de similares confirmado sale del plan. Un grupo de escena confirmado no se registra, así que la siguiente vista previa puede proponerlo de nuevo.
- Confirmar una ráfaga rechaza solo los miembros mostrados; los miembros fuera del álbum o de la ventana de fechas no se tocan.
- La ordenación y el umbral están bloqueados. Mover el control de rigor o cambiar el **intervalo de fechas** vuelve a planificar; tus cambios y los grupos confirmados se conservan. **Todas las fechas** puede alcanzar el límite del plan (`plan_truncated`).
- **Salir**, o cambiar la agrupación, el ámbito o la ordenación, abandona el modo plan. Salir de `/culling` y volver lo restaura; recargar lo descarta.
- Si la biblioteca cambió desde la vista previa, un aviso indica que el plan está desactualizado. Los grupos demasiado grandes se dejan fuera y se cuentan en un aviso.

El asistente lee tu progreso con `ui_get_context` (`culling`: grupos confirmados, pendientes y modificados) y no aplica nada desde la pestaña. Ver [Modo plan en `/culling`](AGENTS.md#los-resultados-se-muestran-en-tu-pestaña).

### Pantalla completa

Pulsa **`F`** (o el interruptor de la cabecera) para revisar a pantalla completa sin la interfaz de la aplicación. Pulsa `F` o `Esc` para salir.

Pulsa **`S`** (o el botón de pila de la cabecera) para apilar el grupo abierto con el fotograma enfocado como portada. Las decisiones no se tocan y se ofrece Deshacer. No se ofrece para grupos con fotogramas de bracketing o panorámica, ni con una foto ya en una pila.

### Lupa / zoom con la tecla Z

Pulsa **`Z`** en la vista individual para alternar una lupa (ajustar ↔ 2×; rueda o `+`/`-` hasta 800 %). Al ampliar más allá del ajuste, el panel carga el `/image` a resolución completa, para que juzgues el enfoque sobre píxeles reales. Las miniaturas son de 640 px y la vista ajustada es un renderizado de hasta 1920 px; la lupa va más allá.

- En la tira de contactos de Escenas, `Z` alterna una lupa al pasar el cursor con un control deslizante de zoom.
- Los paneles muestran primero la miniatura almacenada y luego pasan al renderizado nítido. Los fotogramas siguiente y anterior se precargan (salvo con el ahorro de datos activado).
- Un renderizado que no puede empezar en 5 s se sustituye por la miniatura durante 60 segundos.

**Lupa al pasar el cursor en el cuarto oscuro.** Una lupa redonda sigue al cursor sobre el fotograma principal, cada panel de comparación y los primeros planos de rostros, mostrando píxeles a resolución completa. Un interruptor de la barra de herramientas la activa o desactiva (activada por defecto, guardada por navegador). Se pausa mientras el fotograma está ampliado más allá del ajuste, funciona a pantalla completa y sigue a `←`/`→`.

### Insignias por cara

En el visor ampliado del descarte, cada rostro lleva sus propias insignias: ojos abiertos/cerrados, mala expresión y confianza de detección. Puedes ver qué rostro de una foto de grupo tiene los ojos cerrados. Se obtienen por grupo con `POST /api/culling-group/faces`.

**Panel de rostros.** Los recortes de rostro se colorean en verde / naranja / rojo según sus puntuaciones de ojos abiertos y sonrisa.

- Los controles de **ojos** y **sonrisa** ajustan lo que cuenta como parpadeo o expresión débil. Empiezan en `face_detection.eyes_closed_max` y `face_detection.poor_expression_min` (ambos `4.0` por defecto).
- **Tamaño** (64–256 px, pasos de 16, `112px` por defecto) cambia el tamaño de los recortes. Los valores de los controles se guardan por navegador.
- Tras usar un control con el ratón, las teclas de flecha vuelven al cuarto oscuro (`←`/`→` fotograma, `↑`/`↓` conservar/rechazar). Pulsa Tab hasta un control para ajustarlo con el teclado.

**Tira de primeros planos del sujeto (grupos sin rostros).** Para los grupos sin rostros significativos (fauna, macro, productos), el cuarto oscuro muestra lado a lado el sujeto principal de cada fotograma, recortado del cuadro de sujeto de BiRefNet. Cada recorte tiene una insignia de nitidez (10 = la más nítida del grupo) y un aro verde / ámbar / rojo. Haz clic en un recorte para saltar a esa foto. No se ejecuta ningún modelo (`POST /api/culling-group/subjects`). Para una biblioteca existente, ejecuta antes `python facet.py --recompute-saliency` (GPU); hasta entonces la tira no aparece.

**Sujeto clave (destino del zoom + persona clave).** Ampliar (**`Z`**, doble clic o el primer paso de la rueda) se centra en el sujeto clave del fotograma en lugar del centro: su mejor rostro, o el cuadro de sujeto si no tiene. Cuando haces tú mismo un desplazamiento o zoom en un fotograma, Facet deja de reencuadrarlo. Una persona con nombre que gana recibe una píldora ámbar con su nombre en la tira de rostros. Las personas con nombre a media distancia vencen a desconocidos más grandes; un rostro diminuto del fondo no gana. No se guarda nada. Los cuadros son fracciones del fotograma completo (`normalized_frame_xyxy`). Endpoints: `POST /api/photos/key_subjects`, `GET /api/photo/key_subject`.

**Comparación sincronizada (2 / 4 a la vez).** Los botones Individual / Comparar 2 / Comparar 4 de la cabecera cambian de vista. En el modo de comparación todos los paneles comparten un mismo desplazamiento/zoom, así que comparas el recorte idéntico. El doble clic alterna ajustar ↔ zoom. Al ajustar, cada panel muestra `/thumbnail?size=1920`; ampliado, carga el `/image` a resolución completa. El pellizco táctil aún no está implementado; usa la rueda del ratón.

**Deslizar para conservar o rechazar (táctil).** En un dispositivo táctil, arrastra el fotograma a la derecha para conservar o a la izquierda para rechazar. Se inclina y se tiñe de verde (CONSERVAR) o rojo (RECHAZAR).

- Pasado el 35 % del ancho (al menos 48 px), soltar confirma la misma decisión que `↑` / `↓` y pasa al siguiente fotograma. Si no llega, vuelve a su sitio.
- Un arrastre vertical se ignora.
- Cada deslizamiento muestra **Deshacer**, que restaura la decisión y vuelve a ese fotograma.
- Solo en la vista individual, a escala ajustada, con un dedo o lápiz. Una pista de una línea se muestra hasta que se descarta.

**Vista previa del aspecto editado.** En la vista individual, el menú de la **paleta** lista "Original" más cada estilo de darktable configurado, para que puedas descartar con el aspecto revelado.

- Facet renderiza el original mediante darktable-cli (`--style`, limitado a `preview_max_edge`). Si falla, vuelve a Original.
- El estilo permanece para el grupo actual y se restablece al reabrir el cuarto oscuro.
- Solo se muestra cuando hay un estilo configurado **y** se encuentra darktable-cli. Los estilos deben existir en la configuración de darktable del usuario que ejecuta el visor.
- Los renderizados se guardan en caché en disco.
- Endpoint: `GET /api/photo/cull_preview?path=&style=` (edición). Se configura mediante [`raw_processor.darktable.cull_styles`](CONFIGURATION.md#decodificación-raw).

## Vista de escenas

Una vista de **solo lectura** de la biblioteca como escenas cronológicas, en orden narrativo, con cabeceras de fecha/momento y una lupa al pasar el cursor. Abierta a **todos los usuarios autenticados**.

- Una escena nueva empieza cuando pasan más de `scenes.gap_minutes` entre tomas (ampliado en sesiones espaciadas). Los tramos muy largos se dividen.
- Ábrela con la acción **Mostrar escenas de este álbum** de la cuadrícula de Álbumes; un selector cambia de álbum. No hay un elemento Escenas en la navegación principal.
- Cada escena tiene un botón **Descartar esta escena**, solo de edición, que abre el [Descarte](#descarte) en esa escena (`/culling?group_by=scene&album=&from=&to=`).
- Con los momentos narrativos calculados, cada escena se titula con su momento principal, y `scenes.split_on_moment_change` puede dividir un tramo donde cambia el momento.
- Las escenas menores que `scenes.min_size` se omiten; se cargan como máximo `scenes.max_photos` fotos.

Se controla con `viewer.features.show_scenes` (por defecto: `true`). Ver [Configuración — Escenas](CONFIGURATION.md#escenas) para `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` y `adaptive_k`.

## Momentos narrativos

Facet etiqueta cada foto con la actividad que muestra. El vocabulario **general** por defecto: celebración, comida, playa, actividad acuática, montañas, naturaleza y fauna, paisaje urbano, monumento de viaje, concierto, deporte, reunión de grupo, retrato, niños, mascotas, vida nocturna, ceremonia, paisaje escénico, nieve e invierno, interior del hogar, carretera y vehículo, u `other`. Hay disponible un vocabulario `wedding` como género opcional.

- Se ejecuta en local, sin pasada de modelo adicional: la leyenda de IA de cada foto se compara con los prompts de texto de cada momento (se usa el embedding de la imagen cuando no hay leyenda). El suavizado de la línea de tiempo corrige las lecturas erróneas aisladas.
- Un desempate VLM opcional (16gb/24gb) vuelve a comprobar los fotogramas de baja confianza.
- Se **ejecuta automáticamente al final de cada escaneo**. La primera pasada sobre una biblioteca existente codifica todas las leyendas (se recomienda GPU). Vuelve a etiquetarlo todo con `python facet.py --recompute-moments`.
- Los momentos aparecen como títulos de escena y como filtro de la galería (`GET /api/photos?narrative_moment=beach`, opciones desde `GET /api/filter_options/narrative_moments`).
- El vocabulario es configurable: ver [Configuración — Momentos narrativos](CONFIGURATION.md#narrative-moments).

**Confianza del momento.** Cada etiqueta tiene una confianza (`narrative_moment_confidence`). Las etiquetas por debajo de `viewer.moment_confidence_min` (por defecto `0` = nunca atenuar) aparecen atenuadas con "(incierto)" en las cabeceras de Escenas y Descarte y en la información emergente. La confianza también es una ordenación (**Confianza del momento**, bajo Contenido) y un filtro de rango 0–1 (`min_moment_confidence` / `max_moment_confidence`, sección **Momentos** de la barra lateral).

## Limpieza de basura

Una cola de revisión rápida para capturas de pantalla, documentos escaneados, recibos, memes y diapositivas. Ejecuta `python facet.py --detect-junk` (también se ejecuta tras cada escaneo) para rellenar `junk_kind`. Ver [Configuración — Limpieza de basura](CONFIGURATION.md#limpieza-de-basura).

Abre **Limpieza de basura** en la navegación (`/junk`, solo edición):

- **Chips de filtro por tipo**: "Todos los tipos" más un chip por tipo con su recuento (`GET /api/filter_options/junk_kinds`).
- **Recuento de candidatas**: baja a medida que decides.
- **Conservar**: quita la foto de la cola **para siempre** (`not_junk`); las ejecuciones posteriores de `--detect-junk` la omiten.
- **Rechazar**: marca la foto como rechazada (no se elimina nada).
- **Rechazar todas las mostradas**: rechaza todas las candidatas cargadas, tras confirmar.
- **Lupa**: pulsa **`Z`** (o el interruptor de la barra de herramientas) para ampliar texto pequeño.

Las fotos basura siguen visibles en la galería normal. Filtra por ellas con `?junk_kind=<kind>` o `?junk_kind=any` (excluye `not_junk`).

Se controla con `viewer.features.show_junk_sweep` (por defecto: `true`).

## Modo de comparación por pares

Clasifica fotos juzgándolas de dos en dos; los votos alimentan el ajuste de pesos. Abre `/compare` (botón Comparar en la cabecera). Requiere un `edition_password` no vacío (un solo usuario) o el rol `admin`/`superadmin` (multiusuario).

### Pestaña Comparación A/B

Elige un ganador, marca un empate u omite. Una barra de progreso cuenta hasta 50 votos, con los totales de victorias de A/B y empates. Un filtro de categoría acota la sesión; un desplegable de estrategia elige los pares:

| Estrategia | Descripción |
|----------|-------------|
| `learning` | Por defecto. Primero pares diversos, luego los pares en los que más discrepa el clasificador personal (los más informativos) |
| `uncertainty` | Fotos con puntuaciones similares (las más informativas) |
| `boundary` | Rango de puntuación 6–8 (zona ambigua) |
| `active` | Fotos con menos comparaciones (garantiza la cobertura) |
| `random` | Pares aleatorios (línea base) |

**Atajos de teclado:**

| Tecla | Acción |
|-----|--------|
| `A` | Gana la foto izquierda |
| `B` | Gana la foto derecha |
| `T` | Empate |
| `S` | Omitir el par |
| `Escape` | Cerrar el modal de anulación de categoría |

### Pestaña Sugerencias de pesos

Compara los pesos aprendidos de tus votos con los actuales, con la precisión del modelo antes/después y las 10 mejores fotos ahora frente a tras recalcular.

- **Aplicar** escribe los pesos sugeridos; **Recalcular** repuntúa la categoría (ambos en modo de edición).
- **Aplicar** aparece solo cuando la sugerencia supera a los pesos actuales en comparaciones reservadas (`suggest_changes`, la misma prueba que `--optimize-weights`, ver [COMMANDS.md](COMMANDS.md)).
- A diferencia de `--optimize-weights`, **Aplicar** no recentra la bonificación de la categoría, así que su puntuación media puede moverse.

### Pestaña Pesos

Un control deslizante por métrica para la categoría seleccionada, con una vista previa de la puntuación en vivo. **Guardar** escribe `scoring_config.json` (con copia de seguridad); **Recalcular puntuaciones** lo aplica; **Restablecer** recarga los pesos almacenados.

### Pestaña Instantáneas

Guarda los pesos actuales como una instantánea con nombre y restaura cualquier anterior. Una instantánea también restaura la bonificación de la categoría (`modifiers.bonus`). Las instantáneas anteriores a la 1.21, de `calibrate.py`, o de `others` no llevan bonificación y la dejan sin cambios.

### Prioridad de categorías y contextos de puntuación

Las categorías se comprueban en orden ascendente de `priority`; gana la primera que coincide. Ver [Evaluación de filtros](SCORING.md#cómo-funciona-la-puntuación) y [Contextos de puntuación](CONFIGURATION.md#contextos-de-puntuación). Dos herramientas solo de edición cambian esto sin editar `scoring_config.json`:

- **Prioridad global**: reordena el orden de evaluación base.
- **Contextos de puntuación**: preajustes (`default`, `action_stage`, `party_event`, `portrait_session`, `wildlife`, `landscape`, `motorsport`) que promueven algunas categorías y excluyen otras, sin cambiar el orden global. Edita cualquier preajuste que no sea `default` en la pestaña **Contexto de puntuación**: arrastra (o sube/baja) las categorías promovidas, alterna las exclusiones, guarda. Una categoría listada en ambas gana como excluida. `label_key` y `suggest_from_moments` no se pueden editar aquí. Asigna un contexto por álbum (ver [Contexto de puntuación](#contexto-de-puntuación)) o por foto (más abajo).

Ninguna de las dos repuntúa fotos por sí sola. Después, ejecuta un recálculo (`POST /api/scan/recompute`) y vigila `GET /api/scan/recompute_status`. Un escaneo o recálculo que ya se ejecute desde una terminal impide iniciar otro desde el visor. Con `normalization.per_category` activado, un recálculo puede no converger del todo: ver [Normalización](CONFIGURATION.md#normalización) y [Reordenar la prioridad global](CONFIGURATION.md#reordenar-la-prioridad-global).

**Colisiones de categoría** (`GET /api/stats/categories/overlap`) muestra qué categoría de mayor prioridad está capturando las fotos de una categoría. Por categoría lista **Asignadas**, **Coinciden con los filtros** (si se evaluara sola) y **Capturadas por una de mayor prioridad** (`matched - assigned`, con mínimo 0). **Pares con más colisiones** clasifica las categorías por fotos compartidas. La categoría comodín `default` se deja fuera, ya que coincide con todo.

### Anulación de categoría

Reasigna la categoría de una foto desde la vista de comparación: edita la insignia de categoría, elige una categoría, ejecuta "Analizar conflictos de filtros" para ver qué filtros la excluyen, y aplica. La anulación es persistente: sobrevive a los recálculos hasta que la borres (`POST /api/comparison/override_category`, `POST /api/comparison/clear_category_override`).

El visor ampliado de fotos tiene las mismas acciones en **Definir categoría de puntuación…** / **Borrar anulación** (solo edición). La flecha del chip de categoría abre **¿por qué no es de otra categoría?**: elige una categoría y lista los filtros que excluyen la foto y lo que necesitaría cada uno, p. ej. *"Sube shutter_speed_max de 0.02 a 0.033"*. Esto se muestra cuando una categoría es inalcanzable para una foto, algo que reordenar no puede arreglar (`POST /api/comparison/suggest_filters`).

## Estadísticas EXIF

La página Estadísticas (`/stats`) tiene 5 pestañas. Los selectores de **categoría** e **intervalo de fechas** filtran todos los gráficos. En modo multiusuario cada usuario ve las estadísticas de sus propias fotos visibles.

### Pestañas

| Pestaña | Descripción |
|-----|-------------|
| **Equipo** | Cuerpos de cámara, objetivos y combinaciones (los 20 principales de cada uno) |
| **Ajustes de disparo** | Distribuciones de ISO, apertura, distancia focal y velocidad de obturación |
| **Línea de tiempo** | Fotos a lo largo del tiempo |
| **Categorías** | Análisis de categorías, gestión de pesos y correlaciones de puntuación |
| **Correlaciones** | Gráficos de correlación X/Y personalizados entre métricas, con agrupación |

### Pestaña Categorías

Cuatro subpestañas:

| Subpestaña | Descripción |
|---------|-------------|
| **Desglose** | Recuentos de fotos por categoría, puntuaciones medias, histogramas de distribución de puntuaciones |
| **Pesos** | Comparación en gráfico de radar (hasta 5 categorías), mapa de calor de pesos y editor de pesos (modo de edición) |
| **Correlaciones** | Mapa de calor de correlación de Pearson que muestra cómo influye cada dimensión en el agregado, con vista de detalle al hacer clic |
| **Solapamiento** | Análisis de solapamiento de filtros que muestra qué categorías comparten fotos coincidentes |

Cada gráfico tiene un botón `?` que explica cómo leerlo; un interruptor en la barra de subpestañas muestra todas las explicaciones.

### Editor de pesos (modo de edición)

En la subpestaña Pesos, con el modo de edición activado:

1. Selecciona una categoría en el desplegable
2. Ajusta los controles deslizantes de peso (uno por métrica, deben sumar 100 %)
3. Usa "Normalizar a 100" para equilibrar automáticamente
4. Expande la sección Modificadores para ajustar bonificaciones/penalizaciones
5. La **Vista previa de la distribución de puntuaciones** muestra un histograma en vivo de antes/después
6. Haz clic en **Guardar** para actualizar `scoring_config.json` (crea una copia de seguridad con marca de tiempo)
7. Haz clic en **Recalcular puntuaciones** (aparece tras guardar) para aplicar los pesos a esa categoría

## Atajos de teclado (galería)

Los atajos de una sola tecla están inactivos mientras el foco está en un campo de texto, menú o lista.

| Tecla | Acción |
|-----|--------|
| `←` `→` `↑` `↓` | Mueve el marcador de foto actual entre las tarjetas de foto (columnas de la cuadrícula y filas del mosaico) |
| `Enter` | Abre la foto enfocada |
| `Space` | Selecciona / deselecciona la foto enfocada |
| `Ctrl+A` / `Cmd+A` | Seleccionar todo: toda la vista filtrada desde una selección vacía, si no las fotos cargadas |
| `Escape` | Borra la selección (en modo de panel lateral, también suelta la foto retenida) / cierra el cajón de filtros |
| `Shift+Click` | Selecciona un rango de fotos entre la última seleccionada y la pulsada |
| `Double-click` | Abre la foto |
| `Shift+F10` / `Menu` | Abre el menú contextual de la tarjeta de foto enfocada (el clic derecho hace lo mismo) |
| `1`–`5` | Valora la foto enfocada con 1–5 estrellas (modo de edición; avanza automáticamente a la siguiente foto) |
| `K` | Conserva la foto enfocada (modo de edición) |
| `F` | Marca / desmarca como favorita la foto enfocada (modo de edición) |
| `X` o `0` | Rechaza / deshace el rechazo de la foto enfocada (modo de edición; avanza automáticamente) |
| `/` | Enfoca la búsqueda de la barra de herramientas (se muestra desde 1360 px de ancho); más estrecho, abre la búsqueda de la barra lateral de filtros |
| `S` | Abre el editor de pilas para la selección explícita (modo de edición; reasignable, puede quedar sin asignar) |
| `Ctrl+Mayús+S` / `Cmd+Mayús+S` | Apila al instante la selección explícita sin pila en orden de selección, con la primera foto como portada (modo de edición; los miembros de pilas existentes abren el editor) |
| `B` | Muestra / oculta la barra lateral de filtros |
| `V` | Cambia entre el diseño de cuadrícula y de mosaico |
| `?` | Muestra la referencia de atajos de teclado (todas las páginas; también en menú de usuario → Ayuda) |

**Reasignar teclas.** `K`, `F`, `X`, `/`, `B`, `V` y `S` son valores por defecto. Menú de usuario → **Personalizar atajos** te permite hacer clic en una acción y pulsar una tecla nueva (`Esc` o `Tab` cancela). Los dígitos, `Space` y `?` están reservados, y una tecla ya en uso se rechaza. **Restablecer todo** restaura los valores por defecto. La asignación se guarda por navegador (`localStorage`). La página de la foto usa las mismas teclas, y la referencia `?` siempre muestra las teclas en vigor.

**Foto actual.** La foto sobre la que actúan las teclas de valoración, favorito y rechazo tiene un contorno de 4 px; las demás tarjetas se atenúan al 50 %. No se marca nada hasta que te mueves a una foto. Hacer clic en una foto mueve el marcador a ella. Volver desde una foto deja el marcador en la última que viste. La pista de la tarjeta enfocada aparece solo en modo de edición con `viewer.features.show_rating_controls` activado.

**En la página de la foto**, `1`–`5`, la tecla de favorito y la de rechazo (`F` y `X` por defecto; `0` también rechaza) actúan sobre la foto abierta, en modo de edición con `viewer.features.show_rating_controls` activado. No avanzan; usa `←` `→`. La referencia `?` los lista en *Vista de foto*.

## Deshacer

Los cambios por lotes de favorito/rechazo/valoración y las confirmaciones de descarte muestran una barra de aviso con **Deshacer** durante ~7 segundos.

- Los cambios de indicadores por lotes se aplican al instante y se deshacen invirtiéndolos (hasta 500 fotos).
- Las confirmaciones de descarte se aplazan: el grupo desaparece al instante, pero no se guarda nada hasta que termina el plazo de deshacer.
- Las ediciones de [tags manuales](#tags-manuales) no se pueden deshacer.

Para cambios más antiguos, ver [Historial de organización](#historial-de-organización).

## Aplicación web progresiva

Las compilaciones de producción se pueden instalar en la pantalla de inicio. El armazón de la aplicación se carga sin conexión, y hasta 1000 miniaturas se guardan en caché durante 7 días (los tamaños mayores, como los renderizados de 1920 px del cuarto oscuro, dependen de la caché del navegador). Las respuestas de la API nunca se guardan en caché, salvo los paquetes de traducción. Una barra de aviso ofrece recargar cuando se despliega una versión nueva.

> **Advertencia:** cerrar sesión borra la caché de miniaturas de la aplicación pero no la caché HTTP del navegador, que puede conservar las imágenes vistas (miniaturas, renderizados, imágenes a resolución completa) hasta un año. Las cuentas que no deben ver las fotos de las demás no deberían compartir un perfil de navegador.

## Móvil

En pantallas pequeñas, la tarjeta de selección flotante conserva el recuento y los botones de borrar, seleccionar todo e invertir, más un botón de **Acciones**. Abre una hoja inferior con todas las operaciones masivas (favorito, rechazar, valorar, álbumes, copiar, descargar). Aparece un botón de comparar cuando la selección cabe en la vista de comparación.

## Marco de fotos / Quiosco

Los marcos de fotos inteligentes, los paneles de Home Assistant y las pantallas al estilo ImmichFrame / Immich-Kiosk pueden obtener tus mejores tomas sin iniciar sesión. **No hay interfaz de cliente**: los dispositivos llaman a los endpoints con un **token de marco** de larga duración del bloque de configuración `frame`. Con `frame.tokens` vacío (el valor por defecto), la función está desactivada y todos los endpoints devuelven 404.

- **Qué se muestra.** Las fotos proceden de toda la biblioteca, no de las carpetas de un solo usuario. Se excluyen las fotos rechazadas, basura y con parpadeo. `frame.min_aggregate` (por defecto 7.0) define el mínimo de puntuación; `frame.favorites_only` y `frame.categories` lo acotan más.
- **Variedad.** Las fotos son una muestra aleatoria ponderada por puntuación, así que ves buenas tomas distintas en lugar de las mismas pocas.
- **Sin rutas de archivo.** Cada foto se direcciona con un id firmado opaco, de modo que quien tenga un token no puede saber dónde están tus archivos ni explorar otras filas.

| Endpoint | Devuelve | Caché |
|----------|---------|-------|
| `GET /api/frame/photos?token=&count=` | `{photos: [{id, caption?, date_taken?, width, height}]}` — `count` limitado por `frame.max_count` (por defecto 100), por defecto `frame.count` (20) | — |
| `GET /api/frame/image/{id}?token=&max_edge=` | el JPEG de la foto — original reducido a `max_edge` (limitado por `frame.max_edge`, por defecto 1920), o la miniatura almacenada si el original no es accesible | inmutable de larga duración |
| `GET /api/frame/next?token=` | un JPEG curado aleatorio, distinto en cada llamada — para marcos sencillos y Home Assistant | `no-store` |

### Generar un token

Un token es cualquier cadena que elijas. Usa una larga y aleatoria y trátala como una contraseña:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Añádela a `frame.tokens` en `scoring_config.json`. Lista una por dispositivo; quita una para revocarla:

```json
"frame": {
  "tokens": ["Xu8w…your-random-token…"],
  "count": 20,
  "min_aggregate": 7.0,
  "max_edge": 1920,
  "favorites_only": false,
  "categories": []
}
```

### Receta de Home Assistant

`/api/frame/next` funciona como una [cámara genérica](https://www.home-assistant.io/integrations/generic/) de Home Assistant; cada actualización obtiene una toma nueva:

```yaml
camera:
  - platform: generic
    name: Facet Frame
    still_image_url: "http://facet.local:5000/api/frame/next?token=Xu8w…your-random-token…"
    verify_ssl: false
    framerate: 0.05  # actualiza cada ~20 s
```

Añade la cámara a una tarjeta Picture Glance / Picture Entity para tener un marco de fotos que se actualiza solo.

Para un cliente **al estilo ImmichFrame** que ejecuta su propia presentación, consulta periódicamente `GET /api/frame/photos?token=…&count=30` para obtener ids, y luego descarga cada `GET /api/frame/image/{id}?token=…&max_edge=1920`. Los ids son estables y las imágenes se guardan en caché a largo plazo, así que cada foto se descarga una vez.

## Subida automática desde el teléfono

Envía fotos de tu teléfono a Facet. Un pequeño servidor **WebDAV** en `/dav` permite a PhotoSync (o a cualquier cliente WebDAV) subir a un **directorio de bandeja de entrada**. Pon la bandeja de entrada dentro de un directorio escaneado y ejecuta `facet.py --watch` sobre él: cada foto se puntúa a medida que llega.

- **Credenciales separadas.** El acceso usa HTTP Basic con un inicio de sesión de dispositivo compartido del bloque `upload` (`upload.username` / `upload.password`), no una cuenta de usuario.
- **Desactivado por defecto.** `/dav` devuelve **404** hasta que `upload.username`, `upload.password` y `upload.inbox_dir` estén todos definidos.
- **Confinado a la bandeja de entrada.** No se puede acceder a nada fuera de `upload.inbox_dir`. Los archivos están limitados a `upload.max_file_mb` (por defecto 500).
- **Métodos:** `OPTIONS`, `PROPFIND` (profundidad 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD`. `LOCK`/`UNLOCK` no están implementados; las aplicaciones de subida funcionan sin ellos.

### Configuración

```json
"upload": {
  "username": "phone",
  "password": "…a-long-random-shared-secret…",
  "inbox_dir": "/photos/inbox",
  "max_file_mb": 500
}
```

Mantén `inbox_dir` bajo un directorio escaneado para que `--watch` vea las subidas:

```bash
python facet.py /photos --watch
```

### Receta de PhotoSync

1. En PhotoSync, añade una configuración **WebDAV** (Configure → Add Configuration → WebDAV).
2. **URL / Servidor**: `http://<host>:5000/dav/` (`https://` tras un proxy inverso).
3. **Usuario / Contraseña**: tu `upload.username` / `upload.password`.
4. **Carpeta de destino**: la raíz (`/`) para la bandeja de entrada, o una subcarpeta.
5. En el equipo de Facet, vigila la bandeja de entrada para que se puntúen las subidas:

   ```bash
   python facet.py /photos --watch
   ```

### Prueba rápida con curl

```bash
curl -T photo.jpg -u phone:'…a-long-random-shared-secret…' http://<host>:5000/dav/photo.jpg
```

`201 Created` (o `204 No Content` al sobrescribir) significa que el archivo llegó a la bandeja de entrada; `--watch` lo puntúa poco después.

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

Aumenta `min_photos_for_person` para ocultar del desplegable de filtro a las personas con pocas fotos.

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
      "hide_brackets": true,
      "hide_panoramas": true,
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

Ejecuta esto para mejorar el rendimiento:

```bash
python database.py --migrate-tags    # Consultas de etiquetas 10-50x más rápidas
python database.py --refresh-stats   # Precalcula las agregaciones
python database.py --optimize        # Desfragmenta la base de datos
```

`--migrate-tags` es una configuración única. Después, los escaneos, `--recompute-tags`, `--recompute-tags-vlm` y `tag_existing.py` mantienen la tabla de etiquetas al día. Hasta que lo ejecutes, los filtros de etiquetas usan un recurso más lento.

Comprueba la caché de estadísticas (vida de 5 minutos) con:

```bash
python database.py --stats-info
```

### Índices de la galería y caché de recuentos

Facet añade índices que mantienen rápidas las páginas y los recuentos de la galería en bibliotecas grandes. En una biblioteca de 130k fotos redujeron la página por defecto de unos 1,2 s a entre 26 y 38 ms con el recuento en caché, y a unos 104 ms justo después de un cambio en la base de datos.

- **Se construyen una vez, en segundo plano.** El primer inicio del visor tras una actualización construye los índices que falten mientras el visor ya sirve. En una biblioteca de 130k fotos el índice más grande tardó de 45 a 55 s en construirse y añadió unos 106 a 111 MB al tamaño de la base de datos. Mientras se escribe un índice, los guardados se rechazan brevemente con un mensaje "inténtalo de nuevo en un momento". Un escaneo con `python facet.py` o una ejecución de `python database.py` los construye antes. Ver [DEPLOYMENT.md](DEPLOYMENT.md#arranque-del-visor-e-índices-de-la-galería) para las escrituras durante la construcción, el apagado, `--workers N` y Docker.
- **Las escrituras se vuelven algo más lentas**: unos 0,5 a 0,7 ms más por fila cuando cambia una columna que llevan estos índices.
- **Caché de recuentos.** Los recuentos de la galería se guardan en caché durante 5 minutos. Cualquier cambio desde un proceso del mismo equipo (incluidos `--detect-junk` y `--recompute-*`) los actualiza. Un cambio hecho desde otra máquina a través de un recurso compartido de red aparece cuando caduca la caché.

## Endpoints de la API

La referencia de la API HTTP está en [API.md](../API.md). La documentación interactiva se sirve en `/api/docs`.

## Fotos JPEG XL

Facet escanea JPEG XL (`.jxl`) con la dependencia principal `imagecodecs`, incluida en las instalaciones estándar y Docker. No hace falta ningún paquete adicional; los escaneos omiten `.jxl` solo si ese códec no está disponible.

- **Visualización.** Los navegadores que aceptan `image/jxl` reciben el archivo original; los demás reciben un JPEG. Las miniaturas de la galería son JPEG.
- **Metadatos.** Los originales siguen siendo `.jxl`. Las ediciones de revisión van a sidecars, no al archivo.
- **Animaciones.** Solo se usa el primer fotograma.
- **Color.** Un JXL que reconstruye un JPEG conserva su perfil ICC y las vistas previas se convierten a sRGB. Para JXL nativo, el perfil de color incorporado no está disponible, así que las puntuaciones y vistas previas de archivos de amplia gama o HDR pueden no ser exactas en color. Las descargas del original conservan su profundidad de bits y perfil.
- **Límites.** La decodificación comprueba el límite de píxeles de Pillow antes de reservar píxeles, y la inspección de la cabecera del contenedor se detiene en 4096 cajas. El EXIF codificado y el descomprimido están limitados cada uno a 16 MiB; el EXIF excesivo se descarta y la imagen sigue siendo legible. Se guardan en caché como máximo cinco conversiones a JPEG. Los archivos con disposiciones de canal auxiliar no compatibles se rechazan.

## Solución de problemas

| Problema | Solución |
|-------|----------|
| Carga lenta de la página | Ejecuta `--migrate-tags` y `--optimize` |
| Los filtros no aparecen | Comprueba `--stats-info`, ejecuta `--refresh-stats` |
| El filtro de persona está vacío | Ejecuta `--cluster-faces-incremental` |
| Falta el botón Comparar | Define un `edition_password` no vacío (un solo usuario) o usa el rol `admin`/`superadmin` (multiusuario) |
| La contraseña no funciona | Comprueba `viewer.password` (un solo usuario) o verifica el hash de la contraseña (multiusuario) |
| Un usuario no ve fotos | Comprueba `directories` en su configuración de usuario y `shared_directories` |
| Falta el botón Escanear | Necesita `viewer.features.show_scan_button: true` más acceso de escaneo: ver [Activador de escaneo](#activador-de-escaneo) |
| La búsqueda no devuelve resultados | Asegúrate de que las fotos tienen datos `clip_embedding` (ejecuta antes la puntuación) |
| La búsqueda dice que la aceleración de Apple Silicon está ocupada | Reintenta cuando termine la tarea de modelo en curso |
| Crítica VLM no disponible | Necesita el perfil 16gb/24gb, `viewer.features.show_vlm_critique: true` y una sesión de edición |
| El mapa no muestra fotos | Ejecuta `--extract-gps`; comprueba que las fotos tienen datos GPS en el EXIF |
| Las leyendas no se generan | Requiere el perfil de VRAM 16gb/24gb para el subtitulado con VLM |
| Línea de tiempo vacía | Asegúrate de que las fotos tienen valores `date_taken` |
| Puerto 5000 en uso | Ejecuta `python viewer.py --port 5001` (o define `PORT=5001`). En macOS, el receptor AirPlay usa el 5000: elige otro puerto o desactívalo en Ajustes del Sistema → General → AirDrop y Handoff. |

### Revisar las marcas manuales de rostros guardadas

Encuentra las fotos cuyos rectángulos de rostro guardados necesitan comprobación. En la pestaña Revisión de la barra lateral de la galería, activa **Rostros manuales por revisar** (editores). Abre el editor de rostros de una foto y ajusta y guarda, o elimina, cada rectángulo marcado. La foto sale entonces de la lista. El filtro funciona en álbumes inteligentes y selecciones de toda la vista, y se muestra como un chip que se puede quitar.

- La lista refleja el último escaneo o comprobación del editor, no una vigilancia de archivos en vivo. Los escaneos comprueban las fotos con marcas manuales incluso con la detección de rostros desactivada.
- Abrir el editor vuelve a comprobar el original y es la referencia definitiva.
- Las marcas trasladadas por una revinculación (`relink_unverified`) siguen marcadas hasta que se vuelvan a guardar en el editor.
- Revisar nunca cambia los archivos originales. Las exportaciones y actualizaciones de la base de datos del visor conservan el estado de revisión.

## Corregir la fecha de captura

Corrige un reloj de cámara equivocado. En modo de edición, elige **Corregir fecha de captura** desde el icono de calendario junto a la fecha de la foto, o desde la barra de selección de la galería. Hasta 1000 fotos visibles, "Seleccionar todo en la vista" incluido.

- **Desplazar en** (por defecto): elige **Antes** o **Después** e introduce Días, Horas, Minutos y Segundos. Por defecto: 1 hora después. Los botones rápidos −1 h, +1 h, −1 d y +1 d se suman al desplazamiento.
- **Definir hora exacta**: introduce la fecha y hora correctas de una foto de referencia (la foto abierta, o la primera foto con fecha de la selección; no para "Seleccionar todo en la vista"). El desplazamiento se deduce de ella.
- El desplazamiento no debe ser cero y como máximo de ±366 días.
- Un resumen indica el desplazamiento ("1 h 30 min después"), y la vista previa muestra los recuentos de cambiadas/omitidas y las 20 primeras marcas de tiempo antiguas/nuevas.
- **Aplicar corrección (N)** la aplica. Si algo cambió entretanto, un error ofrece **Previsualizar** para actualizar.

**Qué cambia.**

- La hora de la cámara se desplaza tal cual: sin lógica de zona horaria ni de horario de verano.
- Solo se admiten fechas completas `YYYY:MM:DD HH:MM:SS` o `YYYY-MM-DD[T o espacio]HH:MM:SS`. Las fechas desconocidas, solo con día, con zona horaria/subsegundos y las no válidas se omiten.
- Las fechas corregidas sobreviven a los reescaneos y a las exportaciones incrementales de la base de datos del visor.
- **Usar la fecha del archivo** quita la corrección y vuelve a leer el archivo. Sin fecha de archivo, la fecha de captura es desconocida.
- Aplicar una corrección nunca escribe el original ni cambia la hora de su archivo. La exportación XMP escribe `exif:DateTimeOriginal`; **Escribir metadatos en el archivo** también actualiza el EXIF `DateTimeOriginal` en los formatos compatibles.
- Los grupos de ráfaga y secuencia no se recalculan; vuelve a ejecutar la detección si necesitas reagrupar.

Endpoints: `POST /api/photos/capture_date/preview`, `POST /api/photos/capture_date/apply`, `DELETE /api/photo/capture_date?path=` — ver [API.md](../API.md).

## Historial de organización

Revisa y revierte tus ediciones recientes en toda la biblioteca. En modo de edición, abre **Historial de organización** desde el icono de reloj de la navegación principal (después de En este día). Expande una entrada para ver los valores exactos de antes/después, y luego **Revertir esta entrada**.

- **Qué se registra:** GPS, fechas de captura, decisiones de revisión, estrellas, favoritos y pilas manuales. No los archivos ni el reconocimiento facial.
- El GPS y las fechas de captura son valores compartidos de la biblioteca. Las decisiones de revisión, estrellas y favoritos son tuyos.
- La lista corta de Deshacer y la de actividad del asistente son independientes.
- **Límites.** Las últimas **50 entradas por cuenta**, cada una con hasta **1000 fotos y 1 MiB** de valores. Las acciones de revisión filtradas más grandes se dividen en partes; revertir restaura una parte. Un reemplazo de pilas puede cubrir hasta 2000 fotos en una entrada.
- El historial sobrevive a los reinicios y a las actualizaciones incrementales de la base de datos del visor. Una exportación del visor nueva/completa empieza vacía. No se sincroniza con otra base de datos.
- **Revertir es todo o nada.** Se rechaza si el valor de alguna foto ha cambiado desde entonces, aunque se haya vuelto a cambiar. La edición de revisión privada de otra cuenta no bloquea la tuya. Los reescaneos, las importaciones y Deshacer también pueden invalidar entradas más antiguas.
- Una entrada se oculta cuando una de sus fotos se elimina o deja de ser visible para ti.
- Una reversión añade su propia entrada y marca la original como revertida.

## Caras sin nombre

Encuentra rostros sin asignar y grupos de personas sin nombre: `Filtros → Personas → Rostros sin nombre` (`faces_need_names=true`). Usa + para asignar un rostro, o pon nombre a un grupo en Personas. Las fotos sin rostros detectados se excluyen.

Los usuarios de solo lectura pueden explorar este filtro; asignar o poner nombre requiere acceso de edición.

## Asignar personas

El selector **Asignar rostro a persona** lista primero hasta 12 personas que asignaste recientemente en este navegador (por identidad con sesión iniciada). Después siguen las demás personas con nombre por número de rostros en las fotos que puedes ver. La búsqueda y la paginación cubren a todos.

- Una persona pasa a ser reciente solo tras una asignación correcta o al guardar un rostro manual.
- En local solo se guardan los id de persona. Cerrar sesión borra la lista.

## Actualizar metadatos y vista previa

Vuelve a leer los metadatos de una foto y reconstruye su vista previa sin un reescaneo completo. Las anotaciones manuales, valoraciones, rostros y puntuaciones de IA se conservan. Los originales nunca se escriben. Reescanea si los píxeles modificados necesitan nuevas puntuaciones o detección de rostros.

- Hasta 100 fotos seleccionadas; no se admiten selecciones de toda la vista.
- Los valores de origen ausentes no borran los almacenados. Sin `exiftool`, solo se actualiza la vista previa.
- El GPS y las fechas manuales se conservan.
- Se rechaza mientras se ejecuta otro trabajo de biblioteca; reinténtalo más tarde.
- Cada foto se guarda por separado; reintentar procesa los fallos.
- Hasta el siguiente reescaneo, los histogramas usan la nueva vista previa y la búsqueda por similitud de color omite la foto.
