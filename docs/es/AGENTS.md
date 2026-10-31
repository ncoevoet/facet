# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · **Español** · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet puede actuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), de modo que un asistente de IA compatible con MCP pueda buscar e inspeccionar tu biblioteca con los mismos filtros que la galería. Expone catorce herramientas de lectura que no cambian nada y quince herramientas `ui_*` que mueven la pestaña del navegador que ya tienes abierta (página, filtros, selección) sin escribir datos de la biblioteca. Los tokens con un nivel suficiente también pueden [modificar la biblioteca](#modificar-la-biblioteca) (valoraciones, indicadores, etiquetas, álbumes, descarte y borrado) y manejar el [cuarto oscuro](#cuarto-oscuro-grupos-de-descarte).

## Activarlo

El endpoint está **activado por defecto**. Para apagarlo, pon `viewer.mcp.enabled` a `false` en `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) y reinicia el visor, o recarga la configuración. `/mcp` y todas las rutas `/api/mcp/*` responden entonces 404.

**Instalaciones abiertas.** Sin `viewer.password` la instalación se considera abierta, aunque `viewer.edition_password` esté definida. En una instalación abierta:

- los tokens son `readonly`, salvo que `viewer.trusted_local_editing` esté activo, o que el token sea de edición completa, creado en una sesión con la contraseña de edición y usado desde el mismo equipo (ver abajo);
- el endpoint solo sirve una clave anónima de solo lectura, que no concede nada que la `/api` abierta no conceda ya;
- los tokens solo se pueden gestionar desde el ordenador donde se ejecuta Facet, o en una sesión de edición cuando `viewer.edition_password` está definido (ver [Crear un token](#crear-un-token)).

El endpoint es `POST /mcp` en el puerto del visor: Streamable HTTP, sin estado, respuestas JSON simples (`GET` responde 405). Solo el puente de pestaña, `/api/mcp/bridge`, es un WebSocket; consulta [Controlar tu pestaña abierta](#controlar-tu-pestaña-abierta).

## Crear un token

Lo más sencillo es el navegador:

1. Con `viewer.mcp.enabled` activado, abre el menú de la cuenta y elige **Conectar un asistente**.
2. Escribe un **Nombre** y elige **Lo que el asistente puede hacer**: **Solo leer y pilotar**, **Actuar como yo** o **Edición completa**. Un token no puede superar a la sesión que lo crea.
3. Haz clic en **Crear token**. El cuadro muestra **Pega esto en tu asistente**, un prompt ya preparado que contiene el token. Se muestra una sola vez: haz clic en **Copiar prompt**, pégalo en tu asistente y haz clic en **Hecho**.

**Gestionar tokens (N)** lista tus tokens con su último uso y permite revocar uno. Una línea de estado indica si esta pestaña está conectada, de modo que los asistentes puedan controlarla.

El cuadro solo ofrece los niveles que el servidor concederá:

- una instalación abierta ofrece **Solo leer y pilotar**, y **Edición completa** en los casos indicados abajo;
- **Actuar como yo** aparece solo en instalaciones multiusuario;
- **Edición completa** aparece solo en una sesión de edición; en una instalación abierta significa un navegador del mismo equipo con `viewer.trusted_local_editing` activo, o una sesión iniciada con `viewer.edition_password` (el token solo edita entonces desde el mismo equipo).

El prompt indica el nivel realmente concedido. En una instalación abierta, desde otra máquina y sin sesión de edición, el diálogo muestra «En una instalación abierta, los tokens del asistente solo se pueden gestionar desde el ordenador donde se ejecuta Facet. Define viewer.password para gestionarlos desde otra máquina.» en lugar del formulario.

Alternativa por script (curl):

Un asistente se autentica con un token personal que empieza por `fct_`. Crea uno con una petición autenticada. El token se devuelve **una sola vez**; Facet solo guarda su hash SHA-256:

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

La respuesta incluye el texto en claro en `token`.

- `GET /api/mcp/tokens` lista tus tokens (nunca el secreto); `DELETE /api/mcp/tokens/{id}` revoca uno.
- Un superadmin puede listar los tokens de todos los propietarios con `?all=1` y revocar cualquiera.
- Cada propietario puede tener como máximo 20 tokens activos.
- Estas rutas rechazan la credencial de un agente, así que un asistente nunca puede crear, listar ni revocar tokens.

En una instalación abierta (sin `viewer.password`), estas rutas también rechazan cualquier petición que no venga del ordenador donde se ejecuta Facet:

- una petición que pase por un proxy inverso (cualquier cabecera `Forwarded`, `X-Forwarded-*` o `X-Real-IP`);
- una petición dirigida a una IP de la red local o a un nombre de host en lugar de `localhost`, `127.0.0.1` o `[::1]`;
- una petición que llegue por la red puente de Docker.

Ejecuta la receta anterior en el host de Facet (por SSH en un NAS; en Docker, `docker compose exec facet python -c "import urllib.request ..."`, porque la imagen no tiene curl) o define `viewer.password`. Una sesión iniciada con `viewer.edition_password` se acepta desde cualquier máquina. Un proxy inverso debe enviar `X-Forwarded-For` o `Forwarded`; de lo contrario se trata como la máquina local.

## Conectar tu asistente

El prompt que genera el cuadro contiene todo lo que necesita un asistente: el nombre del servidor `facet`, la URL (`http://<host>/mcp`), el transporte (Streamable HTTP), la cabecera `Authorization: Bearer fct_...`, el nivel concedido y una llamada a la herramienta `status` para confirmar la conexión. Pégalo en tu asistente, o añade tú mismo el servidor a tu cliente MCP. Usa HTTPS cuando el visor sea accesible más allá de tu propio equipo: el token viaja en una cabecera en cada llamada.

## Niveles de permiso

Un token se crea con un nivel concedido: `readonly`, `user` o `edition`. En cada llamada el nivel **efectivo** se recalcula como el menor entre el concedido y el actual de su propietario. Cada herramienta tiene su propio nivel mínimo, comprobado antes de leer o escribir nada; un token inferior recibe `forbidden_level`.

- **Instalaciones con contraseña única** no tienen nivel `user`. Un nivel `user` se limita a `readonly` al crear el token, y el nivel efectivo es `edition` o `readonly`. Por tanto, las herramientas marcadas `user` en [Modificar la biblioteca](#modificar-la-biblioteca) necesitan un token `edition`; un token inferior recibe `forbidden_level`, indicando que necesita `edition`. Un token `edition` exige una sesión de edición y solo funciona mientras no cambie la contraseña de edición.
- **Instalaciones multiusuario.** Si el propietario pierde el rol, su token `edition` baja a `user`. Un ascenso nunca eleva un token por encima de su nivel concedido.
- **Instalaciones abiertas** (sin `viewer.password`, aunque `viewer.edition_password` esté definida). Los tokens pertenecen a un propietario compartido `_anonymous` y son `readonly`, salvo que `viewer.trusted_local_editing` esté activo o que el token provenga de una sesión de edición (los dos puntos siguientes).
- **Edición local en una instalación abierta.** Con `viewer.trusted_local_editing` activo, el cuadro Conectar puede crear un token de **Edición completa** desde un navegador del mismo equipo. `viewer.mcp.enabled` y un token siguen siendo necesarios (una llamada sin token sigue siendo 401).
  - El token es `edition` solo para las peticiones `/mcp` de la misma máquina: un par en loopback, una URL `http://localhost:<port>` o `127.0.0.1` y sin cabeceras de proxy. Valen tanto `:4200` (el proxy de desarrollo de `ng serve`) como `:5000`.
  - Cualquier otra petición pasa a `readonly`, aunque el prompt diga Edición completa: un cliente de la red local, una URL con nombre de host o `0.0.0.0`, o un despliegue en Docker.
  - Definir cualquier contraseña baja el token a `readonly`; quitar la contraseña lo reactiva.
  - Las herramientas de borrado siguen necesitando `viewer.mcp.allow_destructive`.
  - El escaneo (`start_scan`, `scan_status`) funciona sin `viewer.features.show_scan_button`, como para el navegador local.
- **Contraseña de edición en una instalación abierta.** Con `viewer.edition_password` definida y sin `viewer.password`, una sesión iniciada con la contraseña de edición puede crear **Edición completa**, desde cualquier equipo; cualquier otra sesión obtiene `readonly`.
  - El token es `edition` solo para las peticiones a `/mcp` que pasan la misma comprobación de mismo equipo de arriba. Un cliente de la LAN o una petición a través de un proxy obtiene `readonly`: el token es un secreto al portador en una instalación que cualquiera puede leer.
  - Cambiar o borrar la contraseña de edición lo baja a `readonly`; crea uno nuevo tras el cambio.
  - El escaneo sigue necesitando `viewer.features.show_scan_button`, como una sesión de edición en el navegador. Las herramientas de borrado siguen necesitando `viewer.mcp.allow_destructive`.

> **Advertencia:** `ng serve --host 0.0.0.0`, o cualquier proxy en el mismo equipo que no añada cabeceras de proxy, deja pasar por local a un cliente de la red local que envíe `Host: localhost`. Entonces solo el token protege `/mcp`.

Un token deja de valer cuando cambian las credenciales de su propietario: la contraseña del visor o de edición (modo contraseña única), la contraseña del propietario (modo multiusuario) o la eliminación de su cuenta. Responde entonces 401.

## Herramientas

Las catorce herramientas de datos son de solo lectura:

| Herramienta | Qué hace |
|------|--------------|
| `search_photos` | Filtra y ordena la biblioteca como la galería, aplicando los ocultamientos por defecto del visor (parpadeos, ráfagas, duplicados, brackets, panorámicas, rechazadas) salvo que el filtro los fije (informa `hidden_summary`). Se muestra por defecto en tu pestaña abierta (ver abajo); `fields` añade cualquier columna de la foto |
| `semantic_search` | Encuentra fotos por significado, o por palabras de los pies de foto con `scope: "text"` Las filas devueltas se fijan en la pestaña. `filters` acotan la búsqueda como los de la galería, y cada fila lleva su `similarity`. |
| `get_photo` | Detalle completo de una foto a partir de su ruta (sin el histograma); o `target: "selection"` (con `tab_id`) para la única foto seleccionada |
| `get_photo_stack` | Leer la pila local por ruta exacta, o null |
| `get_thumbnail` | Ver una foto: su miniatura como parte de imagen (`size` de 160 a 640, 512 por defecto). Se usa un tamaño menor si el JPEG superaría `viewer.mcp.max_image_bytes`; `too_large` si ninguno cabe; o `target: "selection"` (con `tab_id`) para la única foto seleccionada |
| `contact_sheet` | Ver de 1 a 16 fotos como una cuadrícula numerada (`columns` de 2 a 4, lado más largo 1024). La parte de texto lista `legend` (número de casilla a ruta, en el orden pedido) y `unavailable` (casillas en blanco porque la foto falta o no es visible); o `target: "selection"` para las fotos seleccionadas (como máximo 16) |
| `possible_faces` | Rostros parecidos a una persona reconocida: similitud coseno con el centroide de la persona, los mejores primero, solo el mismo modelo de embedding. `scope` es `unassigned` (por defecto), `unnamed` (rostros sin grupo o en un grupo que nadie ha nombrado), `other_persons` o `all`; `min_similarity` es 0,30 por defecto; `limit` hasta 100. Un escaneo de más de 192000 rostros se rechaza (`too_large`): acótalo con `scope`, `path_prefix`, `date_from` o `date_to`. Las fotos se muestran en tu pestaña. Cada fila incluye el campo `owner` (`ungrouped`, `unnamed_group` o `named`). `candidates` es el número de rostros del ámbito que puedes ver, antes de la comprobación de la dimensión del embedding; `faces_scanned` es el número de filas realmente puntuadas. |
| `similar_photos` | Fotos parecidas a una foto, por embedding visual o por color; `min_similarity` (de 0 a 1) fija el umbral |
| `filter_options` | El vocabulario que acepta un filtro: cámaras, objetivos, etiquetas, personas, patrones, categorías, momentos narrativos, tipos de descarte, rangos de métricas |
| `list_persons` | Personas reconocidas, filtrables por nombre; `show: true` abre `/persons` con esta búsqueda |
| `list_albums` | Álbumes que puede ver el propietario del token; `show: true` abre `/albums` con esta búsqueda |
| `library_stats` | Estadísticas de la biblioteca: `kind` elige el resumen de tamaño y puntuaciones (por defecto) o cualquier dato de la página Estadísticas (ver abajo) |
| `status` | Quién es el token, su nivel efectivo, las banderas del servidor y las pestañas abiertas que puede manejar |
| `available_actions` | Las tareas que se aplican ahora a tu pestaña abierta y a este token, cada una con sus herramientas; las herramientas por encima del nivel del token no se listan |

Notas sobre los filtros:

- `show_rejected` es un booleano: `true` lista solo las fotos descartadas, `false` u omitido da el listado normal. Los agentes pueden fijarlo con `ui_set_gallery_filters` para mostrar en la pestaña búsquedas solo de descartadas. Los álbumes inteligentes también pueden guardarlo (false se omite).
- Un `review_status` explícito determina la decisión de revisión en lugar de `show_rejected` o `hide_rejected`, y desactiva `show_rejected` en la pestaña.
- Combinar `show_rejected: true` y `favorites_only: true` se rechaza en los cambios de pestaña y en la creación de álbumes inteligentes (`invalid_input`). Una búsqueda sigue devolviendo la intersección, pero informa `shown_in_tab.reason: invalid_combination` y no modifica la pestaña.
- `blinks_only` y `duplicates_only` también son booleanos. `true` conserva solo las fotos marcadas como parpadeo, o los miembros de un grupo de duplicados (líderes incluidos). Como `show_rejected`, muestran cada una de estas fotos con independencia de los interruptores de ocultación.

## Los resultados se muestran en tu pestaña

- **Las búsquedas se muestran en tu pestaña.** `search_photos`, `semantic_search` y `similar_photos` aceptan `show` (por defecto `true`). Tras una búsqueda correcta de la primera página, el servidor la muestra en tu pestaña de Facet abierta, así ves lo que encontró el asistente sin pedirlo.
  - `search_photos` y `similar_photos` aplican la misma consulta a la pestaña, sustituyendo sus filtros.
  - `semantic_search` fija exactamente las filas devueltas (orden de similitud, como máximo `limit`, con o sin `filters` o `scope`) como lista elegida por el asistente (`shown_in_tab.mode` es `paths`), porque la vista semántica propia de la pestaña filtra y ordena de otro modo.
  - `show: false` sirve para sondeos intermedios y recuentos; a los asistentes se les indica que nunca pregunten si mostrar los resultados.
- El resultado incluye `shown_in_tab`: `{"applied": true, "tab_id", "keys", "total"}`, o `{"applied": false, "reason"}`. Motivos: `error` (la propia muestra falló), `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (la pestaña aún puede aplicarla), `forbidden`, `invalid_input`, `upstream_error`, `page_not_first`, `empty_result`, `unsupported_filters` (con `keys`), `invalid_combination`, `unsaved_decisions`, `navigation_refused` (la pestaña rechazó la navegación), `comparison_open` (el usuario está en `/compare`) y `modal_open` (hay un diálogo, una hoja inferior o una presentación abierta en la pestaña). Una muestra fallida nunca hace fallar la búsqueda. Pasa `tab_id` para elegir una pestaña. Cuando se recortan filas, `next_page` (con `suggested_per_page`) indica la página que continúa justo después de la última fila devuelta; si las páginas no pueden expresar ese punto, `next_offset` lo da como desplazamiento de filas.
- Solo se muestra la primera página (la pestaña pagina sola al desplazarte). Un resultado vacío no se muestra, así conservas la vista anterior. Una búsqueda con filtros para los que la barra lateral de la galería no tiene campo (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`) no se aplica parcialmente.
- Mostrar sale de `/photo` hacia la galería. Sale de `/culling` solo si el usuario no tiene allí decisiones sin confirmar (si las tiene, `unsaved_decisions`), y en `/compare` se rechaza con `comparison_open`. Borra una selección de toda la vista. En la página de un álbum, vuelve primero a la galería, de modo que los filtros guardados del álbum nunca se sobrescriben. Una búsqueda cuyo recuento alimenta el `expected_count` de una herramienta de escritura debe usar `show: false`.
- `list_albums`, `list_persons` y `junk_list` aceptan `show` (`false` por defecto: sobre todo son búsquedas de nombres). Con `show: true` abren `/albums`, `/persons` o `/junk` con exactamente esa consulta; una consulta vacía borra la búsqueda de la página y restablece sus demás filtros. `junk_list` solo muestra su primera página (si no, `page_not_first`) y nunca una lista vacía (`empty_result`). `shown_in_tab` lleva los mismos motivos que una búsqueda, con `mode` `route`. `list_culling_groups` no tiene `show`: usa `ui_show_culling_group`.
- `ui_show_photos` fija una lista exacta de fotos, mostradas en tu orden hasta que cualquier cambio de filtros la reemplaza. `ui_get_context` indica si se muestra una lista fijada. La lista es sencilla: sin grupos, marcas ni etiquetas. Para revisar un plan de descarte, el asistente usa `auto_cull`, que abre el plan en el [cuarto oscuro](#cuarto-oscuro-grupos-de-descarte) (`/culling`).
- **Modo plan en `/culling`.** `ui_show_culling_plan` (llamado por `auto_cull` en una simulación) carga un plan de `auto_cull` en el cuarto oscuro. Obtienes los mismos grupos, bordes conservar/descartar, lupa y comparación que en el descarte manual, con las fotos a conservar del plan preseleccionadas. Consulta [Modo plan del asistente](VIEWER.md#modo-plan-del-asistente).
  - El usuario ve un banner «Plan del asistente · x/y confirmados · Salir», un chip «#n · motivo · sugerido: conservar N / descartar M» por grupo, y confirma grupo por grupo como de costumbre. El orden y el umbral están desactivados; el control deslizante del rigor sigue siendo utilizable.
  - Mover el control, o cambiar el rango de fechas de la barra de herramientas, vuelve a planificar (nuevo `plan_digest`). Los grupos que has invertido conservan tu elección. Un grupo se vuelve a formar como confirmado cuando cae dentro de un grupo que has confirmado, grupos de escena incluidos; con `group_by=all`, un burst confirmado cuyas fotos conservadas reaparecen dentro de un grupo similar más grande se ofrece de nuevo (tus rechazos siguen aplicados). Los grupos omitidos vuelven. Una confirmación cuya cuenta atrás sigue en marcha se aplica de inmediato. Confirmar, omitir y «confirmar todo» quedan en pausa hasta que llegue el nuevo plan.
  - Un rango de fechas más estrecho traslada las inversiones y los grupos confirmados según su conjunto de fotos. Los grupos fuera de la ventana desaparecen, y un aviso indica las inversiones perdidas. **Todas las fechas** vuelve a planificar toda la biblioteca y puede alcanzar el límite del plan (`plan_truncated`).
  - **Salir**, o un cambio de agrupación, de ámbito álbum/escena o de orden, abandona el modo plan. Salir de `/culling` y volver restablece el plan. Una recarga completa de la página lo descarta pero conserva su álbum y sus fechas en la URL (`?from=`, `?to=`), sobre un flujo manual. Las confirmaciones en modo plan nunca añaden destacadas.
  - **Insignias de sugerencia.** `ui_suggest_culling` marca las fotos que conservaría o descartaría, con un motivo breve (una insignia discontinua), y añade notas a los grupos (un chip en la cabecera). Un clic en una insignia invierte esa foto; sin clic no cambia nada. Las marcas sobreviven a mover el control o el rango de fechas y a mostrar de nuevo el mismo plan; otro plan, **Salir** o abandonar el modo plan las borra. Las insignias aparecen solo en las miniaturas del grupo, no en la vista a pantalla completa ni en un grupo confirmado u omitido.
  - La respuesta del asistente lista las rutas que no guardó: `redundant` (ya es la elección del plan), `closed` (grupo confirmado u omitido) y `missing` (no están en el plan). Las notas de un grupo que confirmaste, omitiste o estás confirmando se listan como `groups_closed`. `suggestions_total` y `notes_total` indican lo que retiene la pestaña (como máximo 300 sugerencias y 100 notas).
- **Leer tu progreso.** `ui_get_context.culling` es `null` fuera del modo plan. En modo plan devuelve `{plan_digest, groups_total, confirmed, pending, changed, untouched, plan_truncated}`:
  - `confirmed`: los números de grupo del plan cuya confirmación ya llegó.
  - `pending`: los grupos que has invertido respecto al plan y no has confirmado.
  - `untouched`: el número del resto de grupos.
  - `changed`: cada grupo cuyas fotos conservadas difieren del plan, como `{type, group_id, number, keep_paths, reject_paths}`.
  - `plan_truncated` es `true` cuando el propio plan alcanzó su tope de grupos o de fotos y lista solo una parte de los grupos.
  - Un bloque demasiado grande para una respuesta (el tope de 100 KiB de la pestaña, o el del servidor) tiene sus listas acortadas y `truncated` en `true`. Los recuentos reales quedan en `groups_total`, `confirmed_count`, `pending_count` y `changed_count`.
  - `culling.scope` (`{album_id, date_from, date_to}`) es la ventana para la que se calculó el plan.
  - `suggestions_open` (`[{path, action}]`) lista las marcas que aún esperan tu clic, `suggestions_accepted` las marcas cuya foto has puesto en el estado sugerido y `suggestions_total` las marcas de foto que retiene la pestaña (no las notas de grupo). `suggestions_open_count` indica la longitud real cuando esa lista se recorta.

  No vuelvas a decidir nunca un grupo confirmado. Un grupo burst o similar confirmado sale de la siguiente vista previa. Un grupo scene confirmado no se registra en ninguna parte y puede proponerse de nuevo, así que pasa `changed` como `keep_paths` / `remove_paths` en la siguiente simulación y en su aplicación. `auto_cull` toma sus fechas solo de sus propios argumentos: pasa las fechas de `culling.scope` junto con `culling.changed` en la siguiente simulación (el plan nuevo sustituye al mostrado). Mover el control o el rango de fechas vuelve a planificar, así que vuelve a leer `ui_get_context` antes de la siguiente simulación.
- **Valores de descarte por defecto.** `ui_get_context` devuelve además `culling_defaults`, `{profile, strictness}`: los ajustes que `auto_cull` usa cuando no recibe ninguno (consulta **Ajustes tomados de la pestaña** en [Cuarto oscuro](#cuarto-oscuro-grupos-de-descarte)). Se guardan por navegador, así que dos pestañas los comparten. `culling_defaults.strictness` es el valor vivo y guardado del control deslizante: `null` cuando solo hay un perfil guardado, 100 cuando no hay ninguno. Un plan dado con perfil y `strictness` guarda ambos. Mover el control fuera del modo plan borra el perfil guardado (mezcla personalizada); en modo plan lo conserva.
- **Fechas.** Las herramientas de descarte (`auto_cull`, `list_culling_groups`, `suggest_culling_profile`) aceptan una fecha ISO (`2026-06-01`), una fecha y hora ISO (`2026-06-01T08:30:00`, o con espacio) o la forma EXIF (`2026:06:01 08:30:00`). Un `date_to` sin hora cubre todo el día. Las herramientas con granularidad de día (`library_stats`, `possible_faces`, `cull_report` tanto para los recuentos como para los conjuntos del cuarto oscuro) solo aceptan una fecha y rechazan una hora con `invalid_input`.
- Las filas llevan cámara, objetivo, apertura, velocidad de obturación, ISO, distancia focal e `is_monochrome`. `fields` (en las tres herramientas de búsqueda) añade cualquier otra columna de la foto salvo los datos de imagen y de embeddings, por ejemplo `leading_lines_score`. `learned_score` solo se rellena al ordenar por él. Cuando el límite de bytes recorta las filas, el resultado añade `returned` (y `next_offset` o `suggested_per_page`).
- `library_stats` acepta `kind` (por defecto `overview`: tamaño, recuentos por tipo y resumen de puntuaciones). El `basis` de la vista general indica qué cuenta cada total. `total_photos` cuenta las fotos que puedes ver dentro de `date_from`/`date_to` y la categoría (todas si no se indica ninguna); ignora los interruptores de ocultación e incluye las fotos rechazadas. `type_counts` aplica los interruptores de ocultación e ignora la fecha y la categoría. Los demás valores son de solo lectura y devuelven los datos de la página Estadísticas; las listas largas se cortan en 50 entradas con `truncated: true`:

| Valor de kind | Datos |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | Los paneles de la página Estadísticas; aceptan `date_from`, `date_to` y `category`. `correlations` acepta además `x`, `y` (lista separada por comas), `group_by` y `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Estadísticas por categoría (sin parámetros) |
| `timeline_dates`, `timeline_months` | Número de fotos por día o por mes; exigen `year` (`timeline_dates` acepta también `month`) |
| `timeline_years` | Número de fotos por año |

## Controlar tu pestaña abierta

Junto a las herramientas de datos, el servidor siempre lista quince herramientas `ui_*` que actúan sobre la pestaña de Facet que tienes abierta: cambian de página, modifican los filtros o la selección y releen lo que ves. Nunca escriben datos de la biblioteca, así que basta un token `readonly`.

| Herramienta | Qué hace |
|-------------|----------|
| `ui_navigate` | Ir a una página (galería, personas, álbumes, estadísticas, ...) |
| `ui_set_gallery_filters` | Combinar un parche con los filtros y la ordenación de la galería (`null` quita un filtro, `replace: true` parte de cero) |
| `ui_get_gallery_view` | Ruta, filtros activos, total de resultados, las primeras rutas de fotos visibles y el número de fotos seleccionadas; devuelve también `album_filter_json` (los filtros tal como los guardaría un álbum inteligente) y `filters_scopable` (si describen toda la vista) |
| `ui_get_context` | La página abierta (ruta), el estado de la galería (total, cantidad cargada, si se muestra una lista fijada), el número de fotos seleccionadas y las `actions` que aquí se aplican a tu token; además `focused` (la foto en la que está el usuario), `culling` (el plan del asistente en `/culling`: grupos confirmados, pendientes y modificados, y el `scope` para el que se calculó), `culling_defaults` (`{profile, strictness}`: el perfil guardado y el rigor vivo y guardado del control deslizante, por navegador; `auto_cull` usa ambos cuando no se le da ninguno) y `user_activity` (lo que ha hecho el usuario), y acepta `activity_since` (véase abajo); además `page` y `overlays` (véase abajo) |
| `ui_open_photo` | Abrir una foto |
| `ui_open_album` | Abrir un álbum (fijo o inteligente) por `album_id`; un id desconocido o inaccesible responde `not_found` |
| `ui_show_photos` | Muestra exactamente estos `paths` (hasta 200) en este orden como lista de la galería; los inalcanzables vuelven en `missing`. Cualquier cambio de filtros reemplaza la lista |
| `ui_select_photos` | Seleccionar `paths` explícitos, o toda la vista filtrada con `select_view: true`, en modo `replace`, `add` o `remove` |
| `ui_clear_selection` | Vaciar la selección |
| `ui_get_selection` | El `scope` (`paths` o `view`) y el `count`, con los `paths` o, en una vista, los `filters` y los `excluded_paths` |
| `ui_next_page` | Cargar la siguiente página de la galería |
| `ui_show_culling_group` | Abrir el cuarto oscuro en un grupo, identificado por `(type, group_id)` (cuentas de edición) |
| `ui_show_culling_plan` | Abre el cuarto oscuro sobre un plan de `auto_cull` (`plan_digest` y `request` de la vista previa, `focus` opcional: número de grupo), con las fotos a conservar del plan preseleccionadas para que las inviertas y las confirmes (cuentas de edición). `auto_cull` lo llama por ti en una simulación. El mismo digest que el del plan ya mostrado solo mueve el foco; uno distinto reemplaza el plan y se rechaza como `unsaved_decisions` mientras tengas decisiones sin confirmar, y como `plan_changed` cuando la biblioteca cambió desde la vista previa, y como `plan_load_failed` cuando la pestaña no pudo cargar el plan por otro motivo |
| `ui_suggest_culling` | Mientras se muestra un plan en `/culling`, marca las fotos que conservarías o descartarías (`photos`: `path`, `action`, `reason`, hasta 100) y los grupos que quieras comentar (`groups`: el `path` de una foto del grupo y una `note`, hasta 50); un motivo o una nota tiene como máximo 200 caracteres. Ves una insignia por foto y un chip por grupo, y no cambia nada hasta que pulsas una insignia. Las llamadas se fusionan por ruta, `replace: true` descarta primero todo lo retenido, y `replace` con listas vacías lo borra todo. Responde `{plan_digest, applied, redundant, closed, missing, groups_applied, groups_missing, groups_closed, suggestions_total, notes_total}`; los rechazos son `no_plan` (la pestaña no tiene ningún plan), `too_large` (la pestaña retiene como máximo 300 sugerencias y 100 notas: usa `replace`) y `forbidden_level` (solo cuentas de edición). Con varias pestañas abiertas, pasa el `tab_id` de `shown_in_tab` o `status` |
| `ui_show_comparison` | Abrir la página de comparación por pares, opcionalmente en una categoría, una estrategia y un `tab` (`ab`, `snapshots`, `suggestions`, `weights`); solo abre la página, los ganadores los eliges tú |

Cómo funciona:

- **Conexión.** Mientras tengas la sesión iniciada y `viewer.mcp.enabled` y `viewer.mcp.bridge` valgan `true`, cada pestaña de Facet abre un WebSocket del mismo origen hacia `/api/mcp/bridge`, autenticado con tu sesión en su primer mensaje. El puente está activo por defecto. Pon `viewer.mcp.bridge` en `false` para desactivarlo: las pestañas no se conectan en absoluto y las herramientas `ui_*` responden con un error claro.
- **De quién son las pestañas.** Una herramienta solo llega a las pestañas del propietario del token. Con una única contraseña todas las sesiones son el mismo usuario; en una instalación abierta cada pestaña pertenece al usuario compartido `_anonymous`, incluidos los inicios de sesión de edición.
- **Niveles de pestaña.** Cada pestaña lleva el nivel de la sesión que la abrió. Un token solo maneja pestañas de nivel igual o superior a su nivel efectivo: un token `edition` nunca usa una pestaña con una sesión de solo consulta, mientras que un token `readonly` sí puede manejar una pestaña `edition`.
  - Instalación con contraseña única: un token también queda limitado por la sesión que lo creó. Uno creado desde una sesión de solo consulta solo alcanza pestañas de consulta, nunca la pestaña `edition` (un token anterior a esta regla queda limitado a su propio nivel).
  - Instalación abierta: un token solo alcanza pestañas de consulta, nunca una pestaña `edition`, salvo la pestaña de edición local (ver abajo). Un token de edición completa creado en una sesión con la contraseña de edición alcanza una pestaña `edition` cuando se usa desde el mismo equipo.
  - Con `viewer.trusted_local_editing` en una instalación abierta, una pestaña que supera la comprobación de «misma máquina» se registra como `edition` y baja a `readonly` en un ping cuando se desactiva la opción. Las pestañas de la red local o reenviadas siguen siendo `readonly`. Un token usado desde la máquina local alcanza esa pestaña sea cual sea el nivel con que se creó. Un token usado desde la red local nunca la alcanza y recibe `no_tab`, con un mensaje que explica que una petición no local no puede manejar una pestaña de edición local.
  - Una pestaña solo puede ser reemplazada por otra de nivel igual o superior: una sesión de solo consulta que reutiliza el `tab_id` de una pestaña `edition` es rechazada con 4409. Por encima del límite de pestañas por usuario sale primero la de nivel más bajo.
  - `status` lista solo las pestañas que el token puede manejar e informa `out_of_reach_tabs`, el número de pestañas abiertas que no puede.
- **Varias pestañas.** Se usa la que tuvo el foco más recientemente y el campo `tab` del resultado lo indica. Pasa `tab_id` (lo lista `status`) para elegir otra.
- Una pestaña rechaza lo que su cuenta no puede hacer (por ejemplo `/culling` para una cuenta sin edición) y la herramienta devuelve ese rechazo.
- Lo que devuelve una pestaña no es de fiar: se limitan la profundidad y la longitud de cadenas y listas, y todo queda acotado por `max_bytes`.
- Errores: `no_tab` (ninguna pestaña conectada o abierta, o puente desactivado: abre Facet en un navegador e inicia sesión), `tab_timeout` (sin respuesta en `call_timeout_s`) y `tab_outdated` (la pestaña abierta no conoce la herramienta; recarga la página tras actualizar Facet).
- El puente acepta primero el WebSocket y luego lo rechaza con un código de cierre en lugar de un estado HTTP: 4404 si el endpoint o el puente están desactivados (la pestaña queda desconectada hasta que se recargue la página), 4403 si falta `Origin` o no está permitido, 4401 por una sesión ausente o rechazada.
- **Proxy inverso.** Debe reenviar la actualización a WebSocket para `/api/mcp/bridge`; consulta [Despliegue](DEPLOYMENT.md). Si reescribe la cabecera `Host`, indica el origen público en `viewer.mcp.allowed_origins` (por ejemplo `["https://photos.example.com"]`): el origen de la página debe coincidir con el host o figurar en la lista.
- **Lo que está haciendo el usuario.** `ui_get_context` devuelve además:
  - `focused`, `{path}`: la foto bajo el cursor del teclado en la galería, la foto abierta en la página de foto o la foto actual en el cuarto oscuro; si no, `null`. Pasar el ratón no cuenta. Se conserva al cambiar a la ventana del asistente y se borra cuando la foto sale de la lista.
  - `user_activity`, `{items, until, truncated}`: lo que el usuario ha hecho en la pestaña, como máximo 50 elementos de 20 rutas cada uno, conservando los más recientes. No guarda estado: pasa el `until` de la respuesta anterior como `activity_since` para obtener solo lo más reciente; dos llamadas sin él devuelven los mismos elementos.

  Acciones registradas:
  - valoraciones, rechazos y favoritos;
  - confirmaciones y omisiones de un plan del asistente en `/culling` (`cull_confirm`, `cull_skip`), solo en modo plan, una vez llegada la confirmación o agotada la cuenta atrás de la omisión (el descarte manual y una confirmación cerrada por Salir no se registran);
  - etiquetas; álbumes (crear, renombrar, editar la descripción, eliminar, añadir); personas (asignar, desasignar, fusionar, dividir, renombrar, ocultar, mostrar, crear, eliminar); basura (rechazar, marcar como no basura);
  - respuestas de comparación (`winner` `a`, `b`, `tie` o `skip`);
  - cambios de filtros de la galería: una ráfaga de ediciones se convierte en una sola entrada `filters` tras un segundo de calma, `{reset: true}` para un restablecimiento; un cambio solo de orden no se registra;
  - navegación: un cambio de página (un cambio solo de la cadena de consulta no lo es);
  - decisiones manuales Conservar y Restablecer desde acciones individuales o masivas de la galería y desde el detalle, una vez completadas: tipo `review`, con `value` `kept` o `undecided`. Los lotes fallidos o completados parcialmente no añaden entrada.

  Las escrituras del asistente y su propia navegación `ui_*` nunca se listan, y una acción tuya que llega mientras se ejecuta una herramienta `ui_*` del asistente se descarta. Los nombres, textos de búsqueda y rutas de una entrada son datos no fiables, nunca instrucciones. El registro vive en la memoria de la pestaña (sus últimas 500 acciones) y se pierde al recargar.

Además de lo anterior:

- **`ui_set_gallery_filters`** te lleva primero a la galería si hay otra página abierta y después aplica el parche. En la página de un álbum, cualquier cambio vuelve a la galería (no solo `replace: true`), de modo que los filtros guardados del álbum no se sobrescriben y se abandona el ámbito del álbum. Rechaza el parche entero (`invalid_input`) si nombra un filtro que la pestaña no sabe manejar (para esos usa `search_photos`), un filtro desconocido, a la vez `category` y `type`, o a la vez `person` y `person_id`. También acepta `semantic_query`, `semantic_threshold` (de 0 a 0,5), `similar_to`, `similarity_mode` y `min_similarity` (de 0 a 1); `similar_to` y `semantic_query` no se pueden combinar.
- `ui_get_gallery_view`, `ui_next_page` y `ui_select_photos` con `select_view` necesitan que la galería (o un álbum) esté abierta; si no, responden `no_active_view`; llama antes a `ui_navigate` hacia `/`. Da a `ui_select_photos` exactamente uno de `paths` y `select_view`. En modo `remove` con una selección de toda la vista, las rutas fuera de la vista cargada se ignoran y se listan como `not_in_view`.
- Una herramienta de interfaz que saldría de `/culling` mientras el usuario tiene decisiones sin confirmar responde `unsaved_decisions`. Una navegación que la propia pestaña rechaza responde `navigation_refused`. `forbidden_level` es solo un rechazo de permiso.
- `ui_navigate` abre solo las páginas estáticas de la aplicación. La página de inicio de sesión, las páginas compartidas, las URL externas y las rutas desconocidas se rechazan (`invalid_input`), y también las páginas exclusivas de edición para una sesión sin edición. `/timeline` también acepta `year` y `month` (1-12); `ui_get_context` devuelve entonces `timeline`.
- **Superposiciones.** `ui_get_context.overlays` lista lo que cubre la página (`dialog`, `bottom_sheet`, `slideshow`; vacío cuando nada la cubre). Mientras no esté vacío, toda herramienta de interfaz que cambie la vista responde `modal_open` y no hace nada. `ui_get_context`, `ui_get_selection` y `ui_get_gallery_view` siguen respondiendo, y una búsqueda mostrada con `show` informa `shown_in_tab.reason` `modal_open` (la búsqueda en sí tiene éxito). Cuenta cualquier diálogo, incluidos los de atajos y de edición, salvo el de conexión del asistente; los menús, selectores, tooltips y snackbars no cuentan.
- **Estado de la página.** `ui_get_context.page` es `{id, ...estado}` en estas páginas, y `null` en cualquier otra:
  - `/persons` (`persons`: `search`, `sort`, `sort_direction`, `show_hidden`)
  - `/albums` (`albums`: `search`, `sort`, `type`)
  - `/stats` (`stats`: `tab`, `category`, `date_from`, `date_to`)
  - `/map` (`map`: `date_from`, `date_to`)
  - `/timeline` (`timeline`: `date_from`, `date_to`, `sort`)
  - `/scenes` (`scenes`: `album_id`, `total`)
  - `/culling` (`culling`: `mode` (`cull` o `stacks`))
  - `/compare` (`compare`: `tab` (`snapshots`, `ab`, `suggestions`, `weights`, `context` o `panorama`), `category`, `strategy`, `pair_a`, `pair_b`, `pair_loading`). `tab` es `null` hasta que se elige una categoría; el par es `null` mientras la pestaña A/B no se muestra.

  Los valores se leen en vivo y el texto libre se corta a 200 caracteres. Una pestaña más antigua omite `page` y `overlays`.
- La línea de estado del cuadro **Conectar un asistente** muestra si esta pestaña está conectada; `status` lista las pestañas abiertas y sus id.
- Una pestaña deja de reconectarse cuando se rechaza su sesión (inicia sesión de nuevo). Espera a que vuelvas a ella si otra de tus pestañas tomó el relevo.

## Actualizaciones en vivo

Cuando un asistente cambia fotos con una herramienta de escritura, las pestañas de Facet que tienes abiertas lo siguen sin recargar.

- **Galería.** Las tarjetas cambiadas se actualizan en su sitio, se conserva la lista fijada del asistente y una foto eliminada de la biblioteca (`delete_photos`) sale de ella. Una foto que `cull_apply` movió o envió a la papelera conserva su fila en la biblioteca, así que permanece en una lista fijada; las vistas que ocultan las fotos rechazadas (el valor por defecto) ya la ocultan. Una escritura que no puede nombrar sus fotos (véase abajo) recarga la vista, manteniendo en pantalla las filas actuales y tu selección hasta que lleguen las nuevas. Las vistas de búsqueda semántica y de fotos similares actualizan las fotos ya mostradas y nunca retiran ninguna.
- **Página de foto.** Vuelve a pedir su foto; una foto eliminada de la biblioteca te devuelve atrás.
- **Cuarto oscuro** (`/culling`). Actualiza en su sitio rechazo, favorito y valoración, muestra un indicador Rechazada y conserva tus propias decisiones. Ante un cambio que no puede acotar, solo recarga cuando no hay nada en juego; si no, muestra un banner Recargar hasta que recargues.
- **Un solo aviso por ráfaga.** Los cambios se agrupan (antirrebote de 400 ms, 2 s como máximo) en un único aviso «El asistente ha cambiado N fotos».
- **Una entrada por llamada del asistente** en el panel de actividad, con la etiqueta del nombre de la herramienta en tu idioma (o su nombre sin traducir si no tiene etiqueta), contando las fotos de toda la llamada. Por encima de 200 fotos la entrada no nombra ninguna: la vista se recarga y no hay botón **Mostrar las fotos**. Tras aplicar `auto_cull`, **Mostrar las fotos** fija las fotos que rechazó (hasta 200).
- **Qué escrituras.** Valoraciones, favoritos, rechazos, etiquetas, pies de foto, pertenencia a álbumes, descartes, eliminaciones, correcciones de secuencia y de categoría, asignaciones de rostros, vaciado de descartes y confirmaciones del cuarto oscuro. Las lecturas, simulaciones, escrituras rechazadas, creación de álbumes, exportación de metadatos y análisis no actualizan. Una escritura que agota el tiempo (`outcome_unknown`) sí actualiza, porque pudo haberse aplicado; una que sigue en curso en ese momento aparece en la siguiente actualización o recarga.
- **Escrituras sin alcance.** Una escritura dirigida a una vista `filters`, una que incluye los fotogramas hermanos de un conjunto, una de más de 200 fotos o una que no nombra ninguna ruta recarga la vista en lugar de actualizar tarjetas concretas.
- **El puente debe estar activo.** Una escritura hecha por `/mcp` llega a tus pestañas por el puente de pestañas, así que `viewer.mcp.bridge` debe ser `true`. Una escritura hecha por la propia página (`POST /api/mcp/call`) usa su respuesta (`changed_paths`) y actualiza incluso con el puente desactivado.
- **Solo el mismo proceso.** Con `viewer.py --workers N` el aviso puede faltar a una pestaña (consulta [Limitaciones conocidas](#limitaciones-conocidas)).
- **Tras una actualización, recarga las pestañas abiertas.** La lista de herramientas cambió: una pestaña abierta responde `tab_outdated` hasta que se recarga.

## WebMCP en la página (agentes del navegador)

Aparte del endpoint `/mcp`, una pestaña con sesión iniciada ofrece las mismas herramientas `ui_*` a los agentes que se ejecutan dentro del navegador, mediante la API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Un asistente nativo del navegador ve exactamente las herramientas listadas arriba, las ejecuta en la pestaña que estás mirando y no necesita token.

- **Solo en contexto seguro.** Facet registra las herramientas únicamente con HTTPS o en `localhost`. Con HTTP simple no se ofrecen; la conexión con token sigue funcionando.
- Se registran cuando `viewer.mcp.enabled` es true y has iniciado sesión, y se retiran al cerrar sesión.
- El objeto es `document.modelContext` (el alias obsoleto `navigator.modelContext` no se proporciona). Es un polyfill, instalado solo si el navegador no tiene uno nativo, y no se puede desinstalar: puede existir antes de iniciar sesión sin ninguna herramienta de Facet y permanece tras cerrar sesión con una lista de herramientas vacía.
- Las herramientas hacen lo mismo, limitadas por el mismo nivel de cuenta, que en la tabla anterior. Un agente del navegador lee la misma lista `actions` mediante `ui_get_context`.
- **Herramientas de la biblioteca en la página.** La pestaña también ofrece las herramientas propias del servidor (búsqueda, valoraciones, etiquetas, álbumes, cuarto oscuro, informes):
  - `GET /api/mcp/inpage_tools` las lista, con el esquema de cada herramienta, su `required_level` y el `level` actual de la sesión.
  - `POST /api/mcp/call` (`{tool, arguments, selection_snapshot?}`) ejecuta una como tu sesión iniciada, por el mismo envoltorio que `/mcp`, así que niveles, vistas previas, valores `confirm` y límites de frecuencia se comportan igual. Una herramienta fallida da un sobre `ok: false` normal (HTTP 200). Una llamada también informa `changed` (fotos escritas).
- **Nivel.** El menor entre el nivel de tu inicio de sesión y tu rol actual, leído en cada llamada: una cuenta degradada pierde las escrituras al instante y una eliminada se rechaza (401). Por debajo del mínimo de una herramienta la respuesta es `forbidden_level` («This session's level is readonly; set_rating needs edition: unlock edition in Facet»). En una instalación con una sola contraseña, escribir exige la edición desbloqueada.
- **Quién puede llamar.** Solo una persona con sesión iniciada. El token `/mcp` de un agente se rechaza en estas rutas (403), igual que un `Origin` ajeno; una cookie sola nunca autentica. Cada llamada lleva una cabecera `X-Facet-Agent-Session` (de 1 a 64 letras, dígitos, `_` o `-`; 400 si falta o está mal formada). Distingue las pestañas: un valor `confirm` emitido para una pestaña se rechaza en otra. Lo elige la página, así que separa pero no autentica.
- **Qué queda fuera.** Las herramientas de imagen (`get_thumbnail`, `contact_sheet`) y `available_actions` (usa `ui_get_context`). El argumento `show` de una herramienta siempre está desactivado, porque quien llama es la pestaña, y `tab_id` se rechaza. `status` solo informa las versiones del servidor y del contrato de la interfaz. `target: "selection"` usa el `selection_snapshot` que envía la página (lo que devolvió `ui_get_selection`). `create_album` con `target: "view"` necesita el `album_filter_json` y el `filters_scopable` que devolvió `ui_get_gallery_view` (`invalid_input` sin ellos). Las acciones destructivas siguen `viewer.mcp.allow_destructive`.
- **Gusto.** Como toda escritura de un asistente, una llamada a una herramienta hecha desde la página nunca registra comparaciones ni arma el reentrenamiento.
- **Interruptor.** `viewer.mcp.inpage_tools` (por defecto `true`) desactiva ambas rutas (404) y pone `features.mcp_inpage` en falso en `/api/auth/status`. `viewer.mcp.enabled: false` también las desactiva.

## Modificar la biblioteca

Las herramientas de escritura figuran en la misma lista `/mcp` que las de lectura. Cada una pasa por las rutas `/api` del visor, así que las protecciones de la ruta siguen aplicándose, y cada una cuenta contra el presupuesto `write_rate_per_min`. El nivel es el más bajo nivel efectivo que puede llamar a la herramienta (consulta [Niveles de permiso](#niveles-de-permiso)).

| Herramienta | Nivel | Qué hace | Límites |
|-------------|-------|----------|---------|
| `set_rating` | `user` | Fija la valoración en estrellas (0-5) de fotos | 50 rutas |
| `set_favorite` | `user` | Marca o desmarca fotos como favoritas (marcar quita el descarte) | 50 rutas |
| `set_rejected` | `user` | Descarta o anula el descarte de fotos (descartar quita la valoración y el favorito) | 50 rutas |
| `batch_set_rating` | `edition` | Fija la valoración de muchas fotos | 1000 rutas, o `filters` |
| `batch_set_favorite` | `edition` | Marca muchas fotos como favoritas | 1000 rutas, o `filters` |
| `batch_set_rejected` | `edition` | Descarta muchas fotos | 1000 rutas, o `filters` |
| `add_tags` | `edition` | Añade etiquetas manuales (aparte de las etiquetas de IA) | 10 etiquetas; 1000 rutas, o `filters` |
| `remove_tags` | `edition` | Quita etiquetas manuales | 10 etiquetas; 1000 rutas, o `filters` |
| `create_photo_stack` | `edition` | Crear pila explícita; devuelve entrada Deshacer | 2–1000 rutas |
| `update_photo_stack` | `edition` | Reemplazar miembros/orden y portada opcional; rechaza revisión obsoleta | 1000 rutas |
| `unstack_photos` | `edition` | Disolver pila sin cambiar originales |  |
| `undo_photo_stack` | `edition` | Deshacer solo entrada de pila disponible; rechaza cambios posteriores |  |
| `create_album` | `edition` | Crea un álbum (no idempotente: dos veces crea dos álbumes): vacío, o desde `filters` / `target: "view"` como álbum inteligente que sigue esos filtros, o desde `paths` / `target: "selection"` como álbum fijo rellenado en la misma llamada (`added`, `skipped`). Un álbum inteligente usa los interruptores de ocultación del visor y en `list_albums` muestra 0 fotos. Unos `filters` sin ningún filtro efectivo (`{}`, o solo interruptores de visualización desactivados) se rechazan como `invalid_input`: omite `filters` para un álbum vacío | |
| `album_add_photos` | `edition` | Añade fotos a un álbum (las ya presentes se ignoran) | 1000 rutas |
| `album_remove_photos` | `edition` | Quita fotos de un álbum; las fotos no se tocan | 1000 rutas |
| `assign_faces` | `edition` | Mueve rostros a una persona; los de otra persona se dejan como están salvo `allow_reassign`, y el resultado lista lo omitido | 50 ids de rostro |
| `set_caption` | `edition` | Establece el pie de una foto (semántica de conjunto; un pie sin cambios vuelve como `already`) | 1 foto, 2000 caracteres |
| `export_metadata` | `edition` | Escribe sidecars XMP junto a los archivos | 100 rutas, o `filters`, o `target` |
| `junk_list` | `readonly` | Lista los candidatos de la limpieza de descartes, opcionalmente de un solo `kind`; `show: true` abre `/junk` con ese `kind` | 100 por página |
| `junk_reject` | `edition` | Descarta candidatos de la limpieza (igual que `batch_set_rejected`) | 1000 rutas, o `target: "selection"` (solo en la página de la galería) |
| `junk_clear` | `edition` | Conserva candidatos: los marca como evaluados y limpios para que salgan de la cola | 50 rutas |
| `cull_apply` | `edition` | Copia las fotos que se conservan, o mueve o envía a la papelera las descartadas ([vista previa y confirmación](#acciones-destructivas-vista-previa-y-confirmación)) | 10000 rutas, o `filters` |
| `delete_photos` | `edition` | Envía los archivos a la papelera y borra sus filas de la biblioteca ([vista previa y confirmación](#acciones-destructivas-vista-previa-y-confirmación)) | 1000 rutas |

### Pilas manuales locales

- `get_photo_stack(path)` lee la pila local del solicitante, o null. Con visibilidad parcial devuelve solo los miembros permitidos, y la pila es de solo lectura.
- `create_photo_stack(paths, cover_path)` exige 2–1000 fotos explícitas sin apilar.
- `update_photo_stack(stack_id, paths, expected_revision, cover_path?)` reemplaza miembros y orden; 0 o 1 miembro disuelve el grupo.
- `unstack_photos(stack_id, expected_revision)` lo disuelve.
- Estas tres exigen `edition`, además del UUID y la revisión actual para pilas existentes. No repitas creaciones a ciegas.
- Los cambios correctos devuelven `undo.entry_id`. `undo_photo_stack(entry_id)` (solo edición) verifica que la entrada sea de pila y la rechaza tras ediciones posteriores o pérdida de visibilidad.
- Rutas de hasta 4096 caracteres. No cambian archivos, decisiones de revisión ni estado remoto de Immich; las credenciales globales siguen solo en la CLI.
- `stack_truncated: true` tras un cambio grande correcto indica que la pila se devuelve solo como resumen UUID/revision/member_count, no como lista completa editable de miembros. `undo.entry_id` sigue disponible.

`search_photos` y el contexto de la galería distinguen `total` (elementos mostrados) de `photo_total` (originales coincidentes). Usa `photo_total` para el `expected_count` de una escritura por filtros. Las selecciones de toda la vista y `target:view` incluyen los miembros plegados coincidentes: muestra la cantidad real de fotos y el alcance completo antes de aplicar. Seleccionar una tarjeta plegada selecciona solo su foto mostrada. `user_activity` incluye `stack` create/update/unstack/undo. `stack_id`/`collapse_stacks` son solo del servidor, no claves de filtro de pestaña.

- **Las herramientas `user` necesitan un token de edición en una instalación con contraseña única**, que no tiene nivel intermedio (consulta [Niveles de permiso](#niveles-de-permiso)).
- **Semántica de asignación.** Las herramientas por foto solo escriben una diferencia respecto al estado actual, así que repetir una llamada es inofensivo; cada ruta informa `changed` o `already`. Procesan una ruta cada vez y se detienen en el primer `library_busy`, `outcome_unknown` o `forbidden_level`, informando `affected`, los `results` por ruta y `not_attempted`. Las herramientas por lotes fijan el mismo estado.
- **Elegir las fotos.** Las herramientas por lotes, de etiquetas y `cull_apply` aceptan O `paths` O `filters` (el objeto de filtros de `search_photos`), más una lista `exclude` opcional.
  - Un destino `filters` necesita `expected_count`: el número de coincidencias de los filtros antes de aplicar `exclude` (el `photo_total` de `search_photos`). Facet vuelve a contar primero y no escribe nada si los números difieren (`invalid_input`, con `actual_count`).
  - Los ocultamientos por defecto del visor (incluidas las fotos rechazadas) se aplican a `filters` exactamente como en `search_photos`. Por tanto, para `move_rejects` y `trash_rejects`, pasa `show_rejected` (o `hide_rejected: false`) tanto a `search_photos` COMO a `cull_apply`. `copy_keeps` no necesita nada más.
- **De quién es el estado.** Las valoraciones, favoritos y descartes son los del propio propietario del token.
- **Archivos omitidos.** Una lista `skipped` no vacía de `cull_apply` o `delete_photos` viene con un `skipped_reason`: esas rutas no tienen ningún archivo legible en disco (falta, se movió o está fuera de los directorios analizados) y no se hizo nada con ellas.
- **Las fotos que el usuario seleccionó.** Donde una herramienta toma `paths`, `target: "selection"` usa en su lugar la selección de la pestaña abierta (`tab_id` elige la pestaña).
  - Una selección que cambió entre la vista previa y la confirmación responde `invalid_input` con `selection_changed`; una demasiado grande para la respuesta de la pestaña responde `too_large`. `delete_photos` vuelve a leer la selección al confirmar.
  - `get_photo`, `get_thumbnail` (exactamente una foto seleccionada) y `contact_sheet` (como máximo 16) también aceptan `target: "selection"`, desde cualquier página.
  - `junk_reject` lo acepta solo en la página de la galería (si no, `invalid_input`).
- **Pies de foto y exportaciones.** `set_caption` solo guarda el texto. No se recodifica, así que la búsqueda semántica de pies sigue encontrando el texto antiguo hasta una nueva codificación. La exportación incremental a la base de datos del visor conserva un pie existente cuando el de origen está vacío, así que un pie borrado puede volver con una exportación o un escaneo posterior. `export_metadata` espera hasta 180 segundos, informa `written`, `skipped` y `errors` (el primer texto de error en `first_error`), y se niega a escribir con exiftool 13.23 a 13.27.
- **Rostros.** `assign_faces` omite, y lista, los rostros que faltan, ya en esa persona, de otra persona (salvo `allow_reassign`), de otro modelo de embedding o de una persona oculta. `assigned_count` es lo que realmente se movió.

### Acciones destructivas: vista previa y confirmación

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) y `delete_photos` llevan `destructiveHint` y se ejecutan como simulación salvo que se llamen con `dry_run: false`.

1. La simulación no cambia nada y lista los archivos que copiaría, movería o enviaría a la papelera (las listas largas se recortan a `max_rows`, con un `<key>_count`). Para `move_rejects`, `trash_rejects` y `delete_photos` devuelve además un valor `confirm`, de un solo uso y válido durante `confirm_expires_in_s` (5 minutos).
2. La llamada real (`dry_run: false`) debe pasar ese `confirm`. Facet recalcula los archivos y las opciones; si algo cambió, la llamada responde `confirmation_required`: repite la simulación.
3. `copy_keeps` no necesita `confirm`, porque solo escribe copias. Aun así empieza por una vista previa por defecto.

El valor `confirm` está ligado al token, a la acción y al conjunto exacto de archivos y opciones. Vive en memoria en un solo proceso, así que un reinicio descarta todos los valores pendientes.

**Práctica recomendada:** muestra siempre al usuario el resumen de la simulación (recuentos y lista de archivos) y obtén su aprobación explícita antes de la llamada `dry_run: false`. No confirmes nunca por iniciativa propia.

- `move_rejects` y `trash_rejects` solo actúan sobre las fotos que el propietario descartó; las demás se informan como `excluded_by_state`. Los archivos RAW y `.xmp` acompañantes (`include_companions`) y los demás fotogramas de un bracketing o panorama (`include_sequence_siblings`) no se tocan salvo que lo actives.
- **Requisitos previos.** `trash_rejects` y `delete_photos` exigen `viewer.cull.allow_trash` en `true` (por defecto `false`). El `target_dir` de `copy_keeps` y `move_rejects` debe estar en una ubicación de exportación permitida: `viewer.export.allowed_target_dirs` más tus directorios de análisis (consulta [Destinos de exportación y descarte](CONFIGURATION.md#destinos-de-exportación-y-descarte)).

> **Advertencia:** `delete_photos` envía los archivos a la papelera del sistema y **borra sus filas de la biblioteca**. Las puntuaciones, etiquetas y valoraciones no se pueden recuperar, aunque los archivos sí.

## Correcciones y datos de referencia

- **Correcciones** (`edition`). `override_sequence` (`kind`: `panorama`, `bracket`, `hdr_panorama` o `suppress`; al menos 2 rutas salvo para `suppress`) y `clear_sequence_override` registran una corrección que se aplica en la siguiente pasada de detección (el resultado indica `pending`). `override_category` y `clear_category_override` fijan o quitan una categoría persistente que sobrevive a los reescaneos y conserva el contexto de puntuación.
- **Comparar fotogramas** (`readonly`). `group_compare` compara los fotogramas de un grupo de descarte (hasta 12 rutas) con `by: "faces"` (por fotograma: número de rostros, parpadeos, ojos abiertos más bajos, mejor sonrisa, `best_path_by_eyes`) o `by: "subjects"` (nitidez y protagonismo del sujeto, `sharpest_path`). Es un consejo, no una decisión.
- **Informe de descarte.** `cull_report` resume un ámbito en una llamada: total, conservadas, descartadas, favoritas, valoradas, sin revisar, lo que ocultarían los interruptores de ocultación, basura, puntuaciones bajas, las mejores y, con un token edition, los primeros grupos del cuarto oscuro. Los motivos se solapan. Su `basis` indica qué filtros respeta cada recuento (los recuentos ignoran los interruptores de ocultación).
- **Gusto.** `comparison_status` (`edition`) indica cuántas comparaciones por pares has hecho y cuánto cubren la biblioteca. Ninguna herramienta envía, edita ni borra una comparación: cada respuesta es tu propio clic. Las escrituras de un asistente (valoraciones, descartes, confirmaciones del cuarto oscuro, `auto_cull`) nunca registran comparaciones ni activan el reentrenamiento automático; la misma acción hecha por ti en la galería sí lo sigue haciendo. Las valoraciones, favoritos y descartes que escribió un asistente también quedan fuera de los pares de entrenamiento del clasificador personal, hasta que valores tú esa foto.
- **Escaneos.** `start_scan` y `scan_status` (`edition`) inician y siguen un escaneo de los directorios configurados. Solo se listan cuando `viewer.features.show_scan_button` está activo y la instalación está bloqueada (una clave superadmin en modo multiusuario), o para un token local de edición completa bajo `viewer.trusted_local_editing`, que no necesita `show_scan_button`. Un escaneo es aditivo y se rechaza mientras corre otro trabajo (`conflict`). La sincronización con Immich sigue en la línea de comandos. En una instalación abierta con `viewer.edition_password`, también los obtiene un token local de edición completa creado en una sesión de edición, pero solo con `show_scan_button` activo.
- **Recursos.** El servidor también lista cinco recursos `facet://` de solo lectura: `facet://categories`, `facet://tags`, `facet://persons`, `facet://filters` (cada filtro de búsqueda con su dominio de valores, más los rangos de métricas) y `facet://scoring-contexts`. Cada uno muestra la biblioteca como la ve el propietario de la clave, limitado a 200 filas y 32 KiB (`truncated` lo indica). Un sexto, `facet://scoring-weights` (los pesos distintos de cero de cada categoría), se ofrece solo a las claves `edition`.
- **Elegir qué se lista.** `viewer.mcp.tool_profile` es `full` (por defecto) o `core`. `core` lista solo un conjunto de 11 herramientas para modelos pequeños (`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`); solo cambia la lista, nunca lo que una clave puede llamar. `viewer.mcp.allow_destructive` (`false` por defecto) controla `delete_photos` (no se lista si está desactivado), las acciones `move_rejects` y `trash_rejects` de `cull_apply` y `assign_faces` con `allow_reassign`; las llamadas rechazadas responden `feature_disabled`. Tampoco se listan las herramientas por encima del nivel de un token.
- **Dos códigos de error más.** `feature_disabled`: una clave de configuración desactiva la ruta, y el mensaje la nombra. `conflict`: la biblioteca está ocupada con un trabajo que excluye a este (por ejemplo, un escaneo ya en curso).

## Puntuaciones y pesos

Los asistentes pueden leer los pesos de puntuación y simular un cambio. Cuatro herramientas escriben: `apply_weights` y `restore_weight_snapshot` cambian la configuración, `recompute_scores` reescribe las puntuaciones y `override_categories` fija fotos. Cada una exige el nivel `edition` y un `confirm` en dos pasos procedente de una simulación o una vista previa. Las lecturas no cambian nada.

- **Explicar una puntuación** (`readonly`). `explain_score` (`path`, o `target: "selection"` para exactamente una foto seleccionada; `top_n` de 1 a 12, 5 por defecto) explica la puntuación de una foto: su categoría y por qué ninguna categoría de mayor prioridad la tomó, el agregado almacenado, las métricas principales como `{metric_key, value, weight_percent, contribution}`, el resto como recuento y suma, puntos fuertes, puntos débiles y penalizaciones.
  - Se basa en reglas y es de solo lectura; nunca ejecuta el VLM.
  - `weight_percent` es el peso efectivo que usó el cálculo. Puede diferir del `*_percent` configurado: `quality` se pliega en `aesthetic` y las métricas que esta instalación no ejecuta se renormalizan.
  - Requiere `viewer.features.show_critique` (activado por defecto). Si está desactivado, la herramienta no se lista y `status` la nombra en `hidden_tools.disabled`.
- **Leer los pesos** (`edition`). `category_weights` devuelve los pesos distintos de cero, los modificadores, los filtros y la prioridad de una categoría, o los pesos distintos de cero y el bonus de cada categoría. El recurso `facet://scoring-weights` lleva la misma lista. Para una categoría devuelve también `configured_keys`: las claves `*_percent` que la configuración de la categoría contiene realmente (ceros explícitos incluidos).
- **Simular un cambio** (`edition`). `preview_weights(category, weights | deltas, sample)` recalcula hasta `sample` fotos de la categoría (30 por defecto, 100 como máximo) con los pesos actuales y con los propuestos, ambos normalizados como lo hace el cálculo. Indica `weights` (un mapa parcial combinado sobre los valores actuales) o `deltas` (puntos porcentuales con signo).
  - Informa primero de los cambios de posición, después del desplazamiento medio, de `warnings` y de un `preview_digest` de un solo uso (válido 5 minutos, guardado por un único proceso).
  - Es aproximado (`basis: "approximate"`): sin instantánea de percentiles, sin penalizaciones y con las puntuaciones limitadas a 10. Usa solo las métricas almacenadas y no almacena nada.
  - Solo se aplica la regla del propio servidor (cada peso de 0 a 100), más un rechazo cuando todos los pesos suman 0 (`all_weights_zero`). Una suma fuera de 95 a 105 (que el cargador de configuración reescala) y una clave desconocida (se guarda tal cual y una carga con validación la descarta) vuelven como `warnings`, no como rechazos.
  - `bonus` y los modificadores no se pueden editar mediante el asistente.
  - Una categoría con más de 100 fotos se muestrea solo entre sus 100 mejores y 100 peores por agregado (`sample_scope`).
  - El digest no es un consentimiento: muestra primero al usuario la propuesta, el desplazamiento y `basis_note`.
- **Aplicar un cambio** (`edition`). `apply_weights(category, weights | deltas, preview_digest)` escribe un cambio simulado. Repite los MISMOS `weights` o `deltas` que diste a `preview_weights` y pasa su `preview_digest`. Sin el digest de esta propuesta exacta sobre los pesos actuales, la llamada responde `confirmation_required` y no escribe nada. El digest es de un solo uso, está ligado al token que simuló y queda anulado si los pesos cambian.
  - La escritura pasa por la misma ruta que la interfaz web: los pesos anteriores se guardan antes en una instantánea (`auto:edit`) y el resultado nombra esa `snapshot`. El resultado se relee (`verified`).
  - No se recalcula ninguna foto: la respuesta indica `scores_stale: true` y `next: "recompute_scores"`. Las puntuaciones almacenadas, las posiciones y la galería solo cambian tras ese trabajo.
  - Limitación conocida: una página /compare ya abierta conserva los pesos antiguos y los reenviaría en su próxima edición; por eso la respuesta lleva `reload_compare: true` y el asistente pide al usuario que la recargue.
- **Instantáneas** (`edition`). `list_weight_snapshots(category, limit, offset)` lista las instantáneas guardadas, de la más reciente a la más antigua, con sus pesos distintos de cero y un indicador `restorable`. `restore_weight_snapshot(snapshot_id)` es por defecto una simulación: lista el cambio y devuelve un `confirm` de un solo uso. La ejecución real (`dry_run: false` más ese `confirm`) responde `confirmation_required` si los pesos cambiaron entretanto. Antes de sobrescribir nada guarda los pesos actuales como `auto:pre_restore` (`undo_snapshot_id`), de modo que una restauración puede deshacerse a su vez. Una instantánea guardada por la interfaz web en otro formato (nombres de métricas sin más, en lugar de claves `*_percent`) responde `unsupported_snapshot` en ambas ejecuciones: restáurala desde /compare.
- **Recalcular** (`edition`). Un cambio de pesos no recalcula nada hasta que se ejecuta `recompute_scores(category | all: true)`. Inicia el trabajo en segundo plano de inmediato (pregunta antes al usuario) y devuelve `started_at`. `recompute_status(started_at)` informa después `running`, `succeeded`, `failed`, `busy` (otro proceso tiene el bloqueo de la biblioteca) o `idle`; `matches_started_job` indica si el estado describe el trabajo iniciado.
  - Solo corre un trabajo a la vez (`conflict`).
  - El recálculo de una categoría reescribe solo esa categoría y no actualiza los grupos de ráfagas ni de secuencias (`all` sí). Ambas ejecuciones guardan la instantánea de percentiles que lee la siguiente normalización de cada categoría.
  - El estado vive en un solo proceso: con varios workers, una consulta puede llegar a uno que no conoce el trabajo.
- **Lo que favorecen las comparaciones del usuario** (`edition`). `learned_weights(category, with_confidence)` ejecuta el optimizador sobre las comparaciones A/B del propio usuario y devuelve solo los `changes` distintos de cero y una `proposal` para pasar a `preview_weights`; no se guarda nada. En lugar de inventar una sugerencia responde `available: false` con un `reason` (`not_enough_comparisons`, `unavailable_if_external` cuando el motor de aprendizaje es externo, `optimizer_unavailable`). Cuando el optimizador no encuentra mejora, indica al asistente que no proponga ningún cambio.
- **Corregir categorías** (`edition`). `misassigned_categories(category, limit, scan)` lista fotos de una categoría que quizá pertenecen a otra, entre las `scan` mejor puntuadas. Es una heurística (`confidence_basis: "heuristic"`), no una prueba; no escribe nada, omite las fotos con categoría manual y desaparece con `show_critique`.
  - `stale`: la configuración actual clasifica la foto en otra categoría. Se corrige con `recompute_scores`, no con una anulación.
  - `near_miss`: falló por menos del 10 % el primer límite numérico incumplido de una categoría de mayor prioridad.
- **Fijar categorías** (`edition`). `override_categories(category, paths, dry_run, confirm, expected_count)` fija la categoría de hasta 50 fotos.
  - La simulación lista cuáles cambiarían (`would_change`, `already`, `missing`) y devuelve un `confirm` de un solo uso.
  - La ejecución real lo exige junto con un `expected_count` igual a `would_pin`. También se fijan las fotos que ya están en la categoría, para que la elección sobreviva a un recálculo posterior. Se detiene en el primer fallo e informa `affected`, `remaining` y `failed_path`.
  - Cada fijación es duradera y recalcula el agregado de la foto; `clear_category_override` deshace una.
- `ui_show_comparison` acepta un `tab` (`ab`, `snapshots`, `suggestions`, `weights`) para que el asistente abra la página donde el usuario revisa un cambio.

## Prompts

El servidor ofrece además cinco prompts listos, listados por `prompts/list` y filtrados por el nivel del token. Un prompt solo nombra herramientas que el token puede llamar, y una herramienta destructiva solo tras su simulación y su confirmación. Cada llamada cuenta en el límite de lectura y se registra por nombre, nunca con sus argumentos.

| Prompt | Argumentos | Qué pide al asistente |
|--------|------------|-----------------------|
| `find_photo` | `description` | Encontrar una foto a partir de una descripción y mostrarla |
| `cull_shoot` | `scope_hint` | Revisar una sesión, proponer qué rechazar y, cuando decidas, registrar tus decisiones con `confirm_culling_groups`; mover o enviar a la papelera solo ocurre tras una simulación y tu confirmación |
| `build_album` | `theme`, `album_name` | Reunir las fotos que coinciden en un álbum nuevo |
| `tag_people` | `person` | Encontrar rostros parecidos a una persona y asignar los que confirmes |
| `teach_taste` | `category` | Abrir la página de comparación por pares en tu pestaña y llevar la cuenta de las comparaciones hechas; la respuesta a cada par es siempre tu propio clic |

## Cuarto oscuro (grupos de descarte)

Las herramientas del cuarto oscuro reflejan la página `/culling`. Todas exigen el nivel `edition`, también las que solo listan.

| Herramienta | Qué hace |
|-------------|----------|
| `list_culling_groups` | Lista los grupos (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) con sus fotos y puntuaciones, ordenables y acotables por álbum o rango de fechas |
| `culling_profiles` | Los ajustes de descarte por género y el predefinido |
| `suggest_culling_profile` | Nombra el ajuste que encaja con un álbum o un rango de captura |
| `keeper_hints` | Pistas por foto «en esta ráfaga hay una toma mejor» para hasta 100 rutas (vacías si no hay cabeza de clasificación entrenada) |
| `auto_cull` | Descarte automático de un ámbito con un presupuesto de fotos a conservar: vista previa del plan página a página y después aplicación con el valor `confirm` |
| `confirm_culling_groups` | Confirma hasta 20 grupos: conserva sus `keep_paths` y descarta el resto de sus `paths` |

- **Un grupo se identifica por el par `(type, group_id)`**, nunca solo por `group_id`: los ids de los grupos similares se desplazan al fusionarse con las ráfagas.
- **El valor por defecto `group_by: "all"` devuelve solo ráfagas y grupos similares.** Pide explícitamente `scene`, `bracket`, `panorama` o `hdr_panorama`.
- **Una página se recorta para caber en `max_bytes` acortando la lista `photos` de cada grupo, nunca eliminando grupos.** `photo_count` sigue siendo el tamaño real, `photos_truncated` marca una lista cortada y `has_more` indica si sigue otra página.
- **Los bracketings, panoramas y panoramas HDR se conservan enteros.** En `confirm_culling_groups`, `keep_paths` debe ser igual a `paths` para estos tipos (si no, `invalid_input`), y `auto_cull` nunca los divide.
- **Un `keep_paths` vacío descarta todos los fotogramas del grupo.** La primera llamada responde entonces `confirmation_required` con un valor `confirm`: muéstraselo al usuario y repite la llamada con él. Si un lote se detiene en `forbidden_level`, `library_busy` o `rate_limited`, se informan los grupos ya completados.
- **`auto_cull` hace una vista previa por defecto.** Devuelve el reparto conservar/rechazar por grupo, más un valor `confirm` cuando queda algo por rechazar.
  - Cada llamada planifica todo el ámbito y lo devuelve en páginas de grupos completos. La ruta pagina a 200 fotos, un único grupo mayor recibe su propia página, y la herramienta puede devolver menos grupos para ajustarse al tamaño del resultado.
  - Repite la llamada con `cursor` igual al `next_cursor` anterior y `plan_digest` igual al `plan_digest` de la página del cursor 0 (obligatorio si `cursor` > 0) hasta que `next_cursor` sea `null`. Si el plan cambió desde la primera página, la llamada responde `confirmation_required`: reinicia desde el cursor 0.
  - Cada fila lleva su `number` en todo el plan; `kept` y `rejected` cubren el plan completo.
  - Descarta un rango de fechas entero en UNA llamada, nunca mes a mes.
- **Un solo `confirm` cubre todo el plan** (válido 300 s, de un solo uso, emitido solo en la página del cursor 0). La aplicación recalcula el plan y responde `confirmation_required` si cambió desde la vista previa. Devuelve solo recuentos (`groups_processed`, `kept`, `rejected`, `highlights_added`). Los rechazos hechos por un asistente nunca alimentan el clasificador personal, a diferencia del mismo descarte hecho por ti en la galería.
- **Sustituciones.** `keep_paths` y `remove_paths` (hasta 1000 cada una) sustituyen fotogramas sueltos del plan. Pasa las mismas sustituciones en la simulación que emite el `confirm` y en la aplicación.
  - Las rutas que no están en el plan se ignoran y se informan como `ignored_overrides` (las 20 primeras, con `ignored_overrides_count`).
  - Se rechazan como `invalid_input`, nombrando las rutas o los grupos: quitar un fotograma que el plan CONSERVA en un bracketing, un panorama o un panorama HDR; dejar un grupo sin foto conservada; citar una ruta en ambas listas.
  - Quitar un fotograma que el plan ya descarta no hace nada.
  - La regla de las series solo cubre los grupos formados enteramente por un solo tipo de serie. Un grupo que mezcla fotogramas ordinarios y de serie no se conserva entero, así que sus fotogramas se pueden sustituir como los de cualquier ráfaga.
- **La aplicación nunca lee las inversiones del usuario en la pestaña.** Para respetarlas, lee `ui_get_context.culling.changed` y pasa los `keep_paths` / `reject_paths` de esos grupos como `keep_paths` / `remove_paths` en la siguiente simulación y en su aplicación (las mismas listas en ambas). Un grupo confirmado por el usuario en la pestaña sale del plan: el digest del plan cambia, un `confirm` pendiente responde `confirmation_required` y la nueva vista previa ya no contiene ese grupo. No vuelvas a decidirlo nunca.
- **Si el usuario cambia algo entre la vista previa y la aplicación.** La aplicación se comprueba contra la vista previa.
  - Una foto cuya valoración, favorito o estado de rechazo haya cambiado el usuario desde la vista previa se deja fuera y se informa como `skipped_user_changed` (las 50 primeras rutas, con `skipped_user_changed_count`). Un grupo que se queda sin foto conservada se omite entero y se cuenta en `skipped_user_changed_groups`.
  - Esta omisión por foto solo se aplica cuando no se da ni `keep_paths` ni `remove_paths`. Con listas explícitas, la aplicación repite la simulación y rechaza cualquier cambio del plan, incluido un rechazo manual.
  - Una valoración, un favorito o un rechazo escrito por cualquiera entre la vista previa y la aplicación cuenta como cambio, incluidas las escrituras del propio asistente. Un cambio del plan que esas fotos no expliquen se sigue rechazando como `confirmation_required`.
  - Cuando el servidor ya no conserva la vista previa (más de 15 minutos, expulsada o en poder de otro proceso), o el plan tiene más de 12000 fotos en todas las páginas, la respuesta dice `state_guard: "unavailable"` y se aplica el rechazo de todo o nada.
  - La protección cubre solo las peticiones del asistente; la línea de comandos `--auto-cull` no cambia.
- **`scope_dependent_kinds`** nombra los tipos de grupo cuya composición depende del rango de fechas o del conjunto de candidatos (`similar`, `scene`, más `bracket` si `trim_brackets` está activo), con una nota para descartar todo el rango en una llamada. Las ráfagas y los panoramas no cambian con el rango, ni los bracketings mientras `trim_brackets` esté inactivo.
- **`show`** (`true` por defecto, con `tab_id`). En una simulación, el plan se abre en la página `/culling` del usuario mediante `ui_show_culling_plan` (véase Modo plan en `/culling` arriba).
  - El resultado lleva `shown_in_tab`: `{"applied": true, ...}`, o `applied: false` con los motivos de una muestra de búsqueda fallida más `unsaved_decisions` (el usuario tiene en la página decisiones sin confirmar), `stack_mode_active` (la página está en el modo de pilas sugeridas), `plan_changed` (la biblioteca cambió desde la vista previa), `too_large` (las sustituciones son demasiado grandes para enviarlas a la pestaña) y `plan_load_failed` (cualquier otro fallo de carga).
  - Solo la primera página (`cursor` 0) carga el plan; una página con `cursor` > 0 solo mueve el foco de la pestaña a su primer grupo.
  - Una muestra fallida nunca hace fallar la llamada. Una aplicación nunca muestra.
  - La actualización en vivo de una aplicación (y, en la página, el `show_paths` de la respuesta de `/api/mcp/call`) lleva las fotos que rechazó, hasta 200, para el **Mostrar las fotos** de la entrada de actividad; el resultado de la herramienta sigue limitado a recuentos. Una aplicación que no rechazó nada no ofrece **Mostrar las fotos**, y una simulación no emite actualización en vivo.
- **Ajustes tomados de la pestaña.** Sin `strictness` ni `profile`, `auto_cull` planifica con los ajustes con los que arrancaría la página `/culling` de la pestaña abierta.
  - Rigor: el valor guardado del control deslizante; si nunca se movió, el rigor propio del perfil guardado, o 100 sin perfil.
  - Perfil: el perfil de descarte guardado en ese navegador, si lo hay. Aporta sus demás ajustes (como el mínimo de fotos a conservar por grupo); el rigor del control prevalece.
  - Mostrar un plan mueve el control al rigor del plan; aplicar un perfil sugerido guarda su rigor.
  - Sin pestaña alcanzable usa `auto_cull.default_strictness` del servidor.
  - El resultado informa de lo que usó como `knobs_from_tab` (`{profile}`, `{strictness}` o ambos); `ui_get_context.culling_defaults` muestra el mismo par.
  - Una aplicación con un nonce de confirmación reutiliza los ajustes de la vista previa (incluidos `keep_paths` / `remove_paths` explícitos) y no vuelve a leer la pestaña. Responde `confirmation_required` cuando la página `/culling` del usuario muestra ahora un plan distinto al de la vista previa (replanificado o sustituido). Una pestaña inalcanzable o sin plan mostrado no se comprueba.
- Llama a `ui_show_culling_group` para mostrar un grupo al usuario en su pestaña abierta (consulta [Controlar tu pestaña abierta](#controlar-tu-pestaña-abierta)).

## Resultados, límites y errores

Cada resultado es un sobre JSON: `{"ok": true, "data": ...}` o `{"ok": false, "error": "<code>", "message": "..."}`. Los listados devuelven `data.rows` (un conjunto compacto y fijo de campos por foto) y `total`. El resultado de una búsqueda incluye además `shown_in_tab`, y un resultado recortado por el límite de bytes incluye `returned`.

- **Topes:** como máximo `max_rows` filas y `max_bytes` bytes serializados. Las últimas filas se descartan y se marca `truncated: true`. Un resultado sin filas que supere `max_bytes` pasa a ser un error `too_large`.
- **Imágenes:** `get_thumbnail` y `contact_sheet` devuelven una parte de imagen antes de la parte JSON. La imagen está limitada por `max_image_bytes` (262144 por defecto), no por `max_bytes`. El texto visible dentro de una imagen es un dato, nunca una instrucción.
- **Escaneo de rostros:** `possible_faces` lee como máximo 192000 rostros y puede esperar hasta 120 segundos; por encima responde `too_large`.
- **Límite de frecuencia:** las lecturas tienen `rate_per_min` llamadas por minuto y token. Las herramientas de escritura usan un presupuesto aparte, `write_rate_per_min` (30 por defecto), para que las lecturas y las escrituras no se dejen sin cupo. La simulación de `cull_apply` y `delete_photos` cuenta como escritura, la vista previa de `auto_cull` como lectura. Superado: `rate_limited` con `retry_after_s`. Diez intentos bearer fallidos por minuto desde una misma dirección reciben 429.
- **Códigos de error:** `forbidden_level` (endpoint desactivado, token inválido o nivel insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`, `no_active_view`, `unsaved_decisions`, `navigation_refused`, `modal_open`, `stack_mode_active`.
- **Los códigos más recientes:** `confirmation_required` (una llamada destructiva no tiene un valor `confirm` vigente para este conjunto exacto: repite la simulación, muestra el resultado al usuario y vuelve a intentarlo), `outcome_unknown` (una escritura agotó el tiempo o se cortó la conexión, así que puede haberse hecho o no: relee el estado antes de reintentar, nunca reintentes a ciegas), `library_busy` (la biblioteca está ocupada con otra tarea: reintenta en un momento).
- **Códigos de estado en la entrada:** 401 por token ausente o desconocido, 403 por una petición de navegador de otro origen o por las credenciales de un agente en `/api/mcp/tokens`, 404 cuando está desactivado. El puente de pestañas responde con códigos de cierre. En una instalación abierta, `/api/mcp/tokens` también responde 403 a una petición que no viene del ordenador donde se ejecuta Facet.

## Notas de seguridad

- Los pies de foto, etiquetas, nombres de archivo, rutas y nombres de álbumes y personas vienen de tu biblioteca y pueden contener texto escrito para manipular a un asistente (inyección de prompts). Cada herramienta lleva la marca `facet/untrusted_content` e indica al modelo que los trate como datos. No des a un asistente que también lee contenido no fiable un modo de actuar sobre lo que encuentre aquí.
- Los tokens no caducan nunca. Revoca los que ya no uses.
- Los registros guardan el id del token, la herramienta, el resultado y el número de filas, nunca los argumentos ni el token.

## Limitaciones conocidas

- **Instalaciones abiertas** (sin contraseña). Solo la gestión de tokens se limita al ordenador local, así que un equipo de la red no puede llenar el límite de 20 tokens. `/mcp`, las herramientas de la página y el puente de pestaña siguen al alcance de cualquiera que alcance el visor, como el usuario anónimo compartido. Define una contraseña antes de activar el endpoint en una red.
- **Pestañas falsas en una instalación abierta.** Un cliente que no sea un navegador puede enviar un `Origin` inventado y un token nulo, registrar una pestaña `_anonymous` con el foco, responder a las llamadas `ui_*` con los datos que quiera y expulsar pestañas reales mediante el límite de 8 pestañas. Con `viewer.trusted_local_editing`, un proceso local también puede registrar una pestaña `edition` falsa (puede falsificar `Host` y `Origin` en el WebSocket), pero ya podía actuar como el navegador. Un cliente de la red local no puede, porque se exige un par en loopback.
- Los límites de frecuencia y los contadores de autenticaciones fallidas viven en memoria en cada proceso; con `viewer.py --workers N` cada worker cuenta por separado.
- El registro de pestañas vive en memoria en un solo proceso. Usa un único worker (`viewer.py --workers 1`, el valor por defecto) si dependes de las herramientas `ui_*`; con varios workers una llamada puede llegar a un proceso que no conoce tu pestaña y responder `no_tab`.
- Un usuario puede tener como máximo 8 pestañas conectadas; abrir una novena cierra la más antigua.
- Nada se empuja desde la pestaña a un asistente externo: este conoce el progreso del plan y la actividad del usuario solo llamando a `ui_get_context`. La aplicación de `auto_cull` no lee la pestaña.
- La protección de estado de `auto_cull` conserva 8 planes por usuario durante 15 minutos. La memoria de vistas previas es aparte: 300 segundos, 64 entradas para todos los usuarios. Ambas viven en la memoria de un solo proceso; con varios workers, una aplicación puede llegar a un proceso que no tenga ninguna, y la respuesta dice entonces `state_guard: "unavailable"`.
