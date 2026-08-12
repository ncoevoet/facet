# Integración con Immich

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · [Deutsch](../de/IMMICH.md) · [Italiano](../it/IMMICH.md) · **Español** · [Português](../pt/IMMICH.md)

Facet e [Immich](https://immich.app/) hacen trabajos distintos sobre las mismas fotos. Immich es la biblioteca: las ingiere, las respalda y las sirve a tu teléfono. Facet es el juicio: las puntúa, las clasifica y las descarta. Esta página conecta ambas piezas para que los veredictos a los que llega Facet aparezcan como valoraciones y favoritos en Immich, y para que una subida a Immich le diga a Facet que hay trabajo nuevo esperando.

La conexión es solo REST en ambos sentidos. Facet nunca toca la base de datos de Immich, ni Immich toca la de Facet.

**Facet requiere Immich ≥ 3.0.** Los servidores más antiguos rechazan la semántica de valoración de la que depende Facet: `null` para borrar una valoración y `-1` para marcarla como rechazada. En un servidor 2.x el borrado se rechaza y las valoraciones obsoletas se quedan pegadas a tus recursos para siempre.

---

## Tabla de contenidos

- [Cómo los dos ven el mismo archivo](#cómo-los-dos-ven-el-mismo-archivo)
- [Paso 1 — comparte la biblioteca con Immich](#paso-1--comparte-la-biblioteca-con-immich)
- [Paso 2 — crea una clave de API](#paso-2--crea-una-clave-de-api)
- [Paso 3 — asigna las rutas](#paso-3--asigna-las-rutas)
- [Paso 4 — prueba y luego envía](#paso-4--prueba-y-luego-envía)
- [Envío de rechazos](#envío-de-rechazos)
- [El webhook entrante](#el-webhook-entrante)
- [Referencia de configuración](#referencia-de-configuración)
- [Solución de problemas](#solución-de-problemas)

---

## Cómo los dos ven el mismo archivo

Todo lo que sigue se apoya en una sola idea: **la misma foto en disco, vista desde dos contenedores**.

Facet conoce una foto por su ruta absoluta en la máquina que ejecuta el escaneo — `/mnt/photos/2026/07/IMG_1234.jpg`. Immich conoce el mismo archivo por su propio `originalPath`, que es el aspecto que tiene ese archivo *desde dentro del contenedor de Immich* — a menudo `/usr/src/app/upload/…` para los recursos subidos, o el punto de montaje que le diste a una biblioteca externa.

Ninguno de los dos lados puede adivinar la vista del otro, así que le indicas a Facet la reescritura de prefijo una sola vez (`immich.path_map`) y toda búsqueda en ambos sentidos pasa por ella. Si lo haces bien, el resto es mecánico; si lo haces mal, todo informa en silencio "unmatched" — consulta [Solución de problemas](#solución-de-problemas).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

La asignación se usa en ambos sentidos: saliente (`--immich-sync` traduce una ruta de Facet para encontrar el recurso) y entrante (el webhook traduce el `originalPath` de Immich de vuelta para encontrar la foto).

## Paso 1 — comparte la biblioteca con Immich

La disposición más limpia es una **biblioteca externa**: Immich lee las fotos donde ya viven, en lugar de poseer una segunda copia. Facet escanea el mismo directorio por su propio lado.

1. En Immich, ve a **Administración → Bibliotecas externas → Crear biblioteca**, elige el propietario y añade una ruta de importación que apunte al directorio tal como lo ve el contenedor de Immich.
2. Asegúrate de que ese directorio esté montado (bind mount) de solo lectura en el contenedor de Immich. En `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Escanea la biblioteca desde la interfaz de Immich (**Escanear todas las bibliotecas**), y escanea el mismo directorio con Facet:

   ```bash
   python facet.py /mnt/photos
   ```

Ambas herramientas guardan ahora una fila por archivo. Nada se duplica en disco.

Si en cambio subes a Immich de forma normal (copia de seguridad automática móvil, el subidor web) y apuntas Facet al propio directorio de subida de Immich, la integración funciona exactamente igual — solo difieren los prefijos. En ese caso Immich es quien decide la disposición de archivos, así que vuelve a ejecutar el escaneo de Facet después de las subidas (o usa `--watch`).

## Paso 2 — crea una clave de API

En Immich: **haz clic en tu avatar → Configuración de la cuenta → Claves de API → Nueva clave de API**.

Immich ≥ 3.0 te permite acotar el ámbito de una clave en lugar de concederle acceso a todo. Facet necesita exactamente seis ámbitos:

| Ámbito | Qué hace Facet con él |
|-------|-------------------------|
| `server.about` | Comprobación de conectividad/autenticación de `--immich-test` |
| `asset.read` | Resolver recursos por `originalPath` |
| `asset.update` | Escribir `rating` e `isFavorite` |
| `album.read` | Encontrar un álbum de mejores fotos existente por nombre |
| `album.create` | Crear el álbum de mejores fotos la primera vez |
| `albumAsset.create` | Añadir fotos al álbum de mejores fotos |

Omite los tres últimos si dejas `push.top_picks_album` vacío — Facet solo toca los álbumes cuando ese nombre está definido.

La clave se envía como una cabecera `x-api-key` en cada solicitud. Ponla en `scoring_config.json`:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Una nota sobre `PUT /api/assets`.** Facet escribe las valoraciones con `PUT /api/assets`, que el documento OpenAPI de Immich marca como *obsoleto* (deprecated). Los alias `PATCH` de sustitución están anunciados pero **ausentes de la especificación publicada**, así que todavía no hay nada a lo que migrar — `PUT` sigue siendo el único endpoint que realmente existe, y Facet lo sigue usando. Cada ruta de Immich que toca Facet vive en `ImmichClient` (`sync/immich.py`), así que el día que se publiquen las rutas `PATCH`, el cambio será de una sola clase.

## Paso 3 — asigna las rutas

Añade un par por cada raíz que compartas. Gana el primer par cuyo `facet_prefix` coincida con una foto:

```json
"immich": {
  "path_map": [
    { "facet_prefix": "/mnt/photos/", "immich_prefix": "/usr/src/app/external/" }
  ]
}
```

Dos raíces, dos pares:

```json
"path_map": [
  { "facet_prefix": "/mnt/photos/",  "immich_prefix": "/usr/src/app/external/" },
  { "facet_prefix": "/mnt/archive/", "immich_prefix": "/usr/src/app/archive/" }
]
```

Deja el marcador de posición de fábrica (`{"facet_prefix": "", "immich_prefix": ""}`) tal cual y las rutas pasan sin cambios — correcto solo cuando Facet e Immich ven de verdad rutas absolutas idénticas, lo cual ocurre si ejecutas Facet dentro del espacio de nombres del contenedor de Immich, y casi nunca en otro caso.

Para leer el valor real, abre cualquier foto en Immich, pulsa `i` para el panel de información, y compara la ruta de archivo que se muestra allí con la ruta que Facet informa para esa misma foto.

## Paso 4 — prueba y luego envía

```bash
# Solo conectividad + autenticación. Sin escrituras.
python facet.py --immich-test

# Resuelve cada recurso e informa de lo que CAMBIARÍA. Sigue sin escrituras.
python facet.py --immich-sync --dry-run

# De verdad.
python facet.py --immich-sync
```

La sincronización informa de `matched` / `unmatched` / `updated` / `skipped (unrated)` / álbumes creados. Una primera ejecución con un recuento grande de `unmatched` casi siempre significa que la asignación de rutas está mal — consulta [Solución de problemas](#solución-de-problemas).

Qué se envía:

- **Valoraciones por estrellas 1–5** → el `rating` de Immich. Una foto que nunca valoraste no envía nada.
- **Favoritos** → el `isFavorite` de Immich.
- **Borrados.** Si valoraste una foto con 5, sincronizaste, y luego la restableciste a sin valorar, la siguiente sincronización envía `rating: null` para que Immich también la olvide. Facet recuerda lo último que envió (en la tabla auxiliar `stats_cache`) precisamente para que esta transición no se pierda. Es `null` y nunca `0` — Immich v3 rechaza `0` de plano, y un solo lote rechazado aborta toda la sincronización.
- **Un álbum de mejores fotos opcional**, poblado a partir de `push.top_picks_min_rating`, cuando `push.top_picks_album` nombra uno.

En modo multiusuario, `--immich-sync --user alice` envía las valoraciones de `user_preferences` de Alice en lugar de las columnas globales, y sigue el estado dentro de su propio ámbito.

## Envío de rechazos

Desactivado por defecto. Actívalo y una foto que rechazaste en el laboratorio de descarte de Facet recibe el propio marcador de rechazo de Immich:

```json
"immich": {
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": true
  }
}
```

Con `push.rejected` activado:

- Una foto rechazada envía `rating: -1`, el valor de Immich v3 para "rechazada".
- **El rechazo prevalece sobre las estrellas.** Una foto rechazada con 5 estrellas envía `-1`, no `5` — la descartaste, y ese es el hecho que merece la pena reflejar.
- **Quitar el rechazo lo borra.** Una foto que envió `-1` y más tarde deja de estar rechazada envía en su lugar su valoración por estrellas actual, o `rating: null` si no tiene ninguna. Mismo mecanismo de estado rastreado que cualquier otro borrado.
- Una foto rechazada nunca se une al álbum de mejores fotos.
- `push.ratings: false` lo suprime. `-1` es una escritura de valoración, así que una configuración que desactivó el envío de valoraciones no ve colarse una por la puerta de atrás.

Déjalo desactivado si otras personas (o tu teléfono) consultan la biblioteca de Immich: un `-1` es visible allí, y "rechazada en Facet" es un juicio de trabajo que quizá no quieras difundir.

## El webhook entrante

Todo lo anterior es Facet → Immich. El webhook es la dirección contraria: Immich le dice a Facet que un recurso acaba de cambiar, y Facet responde de inmediato con lo que sabe sobre él.

**Está desactivado por defecto y nunca inicia un escaneo.** Un webhook es una llamada sin autenticación de sesión procedente de otro demonio; dejar que uno lance trabajo de GPU le daría a cualquier poseedor del token una forma de tumbar tu máquina. Lo que hace en su lugar:

- **Foto conocida y puntuada** → su valoración/favorito se envía de vuelta a Immich de inmediato, en ese mismo momento, como una actualización de un solo recurso. Esto es lo que cierra el bucle después de un escaneo: puntúas una foto, la subes, y la valoración llega a Immich sin esperar a la siguiente `--immich-sync`.
- **Foto desconocida o aún no puntuada** → la ruta se recuerda en una lista pendiente acotada y deduplicada, y la siguiente `--immich-sync` la registra en el log. No se escanea nada.

### Actívalo

El token es un secreto compartido, así que vive en el entorno, nunca en `scoring_config.json` (ese archivo lo reescriben in situ varios endpoints y es legible por cualquiera en la mayoría de las instalaciones). La configuración nombra la *variable*; la variable contiene el *valor*.

1. Genera un token y expórtalo allí donde arranque el visor — tu unidad de systemd, `docker-compose.yml`, o el perfil de tu shell:

   ```bash
   export FACET_IMMICH_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
   ```

2. Nombra esa variable en `scoring_config.json`:

   ```json
   "immich": {
     "webhook": {
       "token_env": "FACET_IMMICH_WEBHOOK_TOKEN",
       "header": "x-facet-token",
       "max_pending": 500
     }
   }
   ```

3. Reinicia el visor (`python viewer.py`).

Un `token_env` vacío, o una variable que no está definida o está vacía, desactiva el endpoint por completo — devuelve **404**, exactamente igual que `frame.tokens` y `upload.username`. No existe un estado intermedio.

### Apunta Immich hacia él

En Immich ≥ 3.0: **Administración → Flujos de trabajo → Crear flujo de trabajo**.

1. **Activador** — elige el evento de recurso que quieres reflejar. `Asset uploaded` es el útil; añade `Asset updated` si también quieres que las ediciones vuelvan a disparar el webhook.
2. **Acción** — elige **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, usando una dirección a la que el contenedor de Immich pueda llegar de verdad. Si ambos se ejecutan en Docker en el mismo host, eso es el nombre del servicio (`http://facet:5000/…`), no `localhost`.
4. **Cabecera** — nombre `x-facet-token`, valor el token que generaste. El nombre debe coincidir con `webhook.header`; renombra ambos a la vez si tu instalación necesita uno distinto. También se acepta `Authorization: Bearer <token>`, para los proxies que solo ofrecen eso.
5. Guarda, y luego sube una foto para confirmar.

### Qué responde el endpoint

| Estado | Descripción |
|--------|---------|
| `202` | Cuerpo entendido. El recuento JSON informa de `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | JSON válido, pero ningún recurso que Facet reconociera. Se registra en el log, no es un error — la forma de la carga es cosa de Immich, puede cambiar. |
| `400` | El cuerpo no era JSON en absoluto. |
| `401` | No hay token en la solicitud. |
| `403` | Token incorrecto. |
| `404` | La función está desactivada (no hay token configurado). |

Facet lee `originalPath` de la carga y es deliberadamente permisivo sobre dónde se encuentra — un objeto de recurso a secas, `{"asset": {…}}`, una lista, o cualquiera de esos anidados bajo `data` / `items` / `assets` funcionan todos. Si la carga lleva el `id` del recurso, Facet lo usa y se ahorra una ida y vuelta de búsqueda.

Las rutas pendientes las informa la siguiente sincronización:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Escanea esas fotos (`python facet.py /mnt/photos`) y caerán de la lista en la siguiente sincronización. La lista está limitada a `max_pending` entradas, y se descartan primero las más antiguas, de modo que un Immich parlanchín nunca puede hacerla crecer sin límite.

### Notas de seguridad

- El token se compara en tiempo constante. Un token incorrecto es un `403` sin más, sin ninguna señal de temporización.
- Sirve el visor sobre HTTPS si Immich lo alcanza a través de algo menos confiable que una red bridge privada — el token viaja en una cabecera en cada entrega.
- Rota el token cambiando a la vez la variable de entorno y la cabecera del flujo de trabajo de Immich, y reiniciando después el visor.
- El webhook lee las columnas de valoración globales, así que en modo multiusuario refleja la valoración compartida/global, no la capa de ningún usuario concreto. Si lo que quieres en Immich son valoraciones por usuario, deja el webhook desactivado y usa `--immich-sync --user <nombre>` según una programación.

## Referencia de configuración

El bloque `immich` completo, con los valores por defecto de fábrica:

```json
"immich": {
  "url": "",
  "api_key": "",
  "path_map": [
    { "facet_prefix": "", "immich_prefix": "" }
  ],
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": false,
    "top_picks_album": "",
    "top_picks_min_rating": 4
  },
  "webhook": {
    "token_env": "",
    "header": "x-facet-token",
    "max_pending": 500
  },
  "timeout_seconds": 30
}
```

| Clave | Por defecto | Descripción |
|-----|---------|---------|
| `url` | `""` | URL base de Immich, `http` o `https`. Se recorta una barra final. |
| `api_key` | `""` | Clave de API, enviada como `x-api-key`. Vacía aborta cualquier sincronización con un error claro. |
| `path_map` | un par vacío | Reescrituras de prefijo entre las rutas de Facet y los valores `originalPath` de Immich. Gana la primera coincidencia; se usa en ambos sentidos. |
| `push.ratings` | `true` | Envía las valoraciones por estrellas 1–5 (y sus borrados). |
| `push.favorites` | `true` | Envía `isFavorite` (y sus borrados). |
| `push.rejected` | `false` | Envía `rating: -1` para las fotos rechazadas en Facet. Requiere `push.ratings`. |
| `push.top_picks_album` | `""` | Nombre del álbum a poblar. Vacío significa que Facet nunca toca los álbumes. |
| `push.top_picks_min_rating` | `4` | Valoración por estrellas mínima para ese álbum. |
| `webhook.token_env` | `""` | Nombre de la variable de entorno que contiene el secreto del webhook. Vacío ⇒ el endpoint devuelve 404. |
| `webhook.header` | `"x-facet-token"` | Cabecera en la que Immich envía el token. |
| `webhook.max_pending` | `500` | Límite de la lista de rutas recordadas pero sin puntuar. |
| `timeout_seconds` | `30` | Tiempo de espera HTTP por solicitud. |

## Solución de problemas

### Todo vuelve como `unmatched`

La asignación de rutas está mal — este es, con diferencia, el fallo más frecuente.

1. Abre una foto en Immich y pulsa `i`. Anota la ruta del panel de información.
2. Busca la ruta de esa misma foto en Facet (el panel de detalle de la galería, o `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. Las dos comparten un *sufijo*. Lo que difiere es el prefijo, y esos dos prefijos son exactamente `facet_prefix` e `immich_prefix`.

Trampas habituales:

- **Falta una barra final.** `"/mnt/photos"` → `"/usr/src/app/external"` también reescribe `/mnt/photosXYZ/a.jpg`. Termina siempre ambos prefijos con `/`.
- **Ruta del host frente a ruta del contenedor.** La ruta de Immich es lo que ve el *contenedor*. `docker compose exec immich-server ls /usr/src/app/external` lo aclara.
- **Enlaces simbólicos y bind mounts.** Immich almacena la ruta que recorrió. Si tu biblioteca se alcanza a través de un enlace simbólico en un lado, las cadenas difieren aunque el archivo sea el mismo.
- **Mayúsculas/minúsculas y Unicode.** La comparación es exacta. Una biblioteca en un recurso compartido que no distingue mayúsculas de minúsculas puede contener tanto `/Photos/` como `/photos/`; solo coincide la grafía almacenada.
- **Immich aún no ha indexado el archivo.** Ejecuta **Escanear todas las bibliotecas** y comprueba que el recurso realmente existe en Immich antes de culpar a la asignación.

`--immich-sync --dry-run` enumera en el log las primeras 20 rutas sin coincidencia; esa lista suele identificar a simple vista el prefijo equivocado.

### `--immich-test` falla

- `Unsupported Immich URL scheme` — `url` necesita `http://` o `https://`.
- `HTTP 401` — la clave de API es incorrecta o fue revocada.
- `HTTP 403` — la clave es válida pero le falta `server.about`. Vuelve a crearla con los seis ámbitos anteriores.
- Conexión rechazada / tiempo de espera agotado — el puerto es incorrecto, o Facet no puede alcanzar el contenedor. Pruébalo con `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` desde la máquina que ejecuta Facet.

### El webhook devuelve 404

La función está desactivada. O bien `webhook.token_env` está vacío, o la variable que nombra no está definida o está vacía *en el propio entorno del visor*. Exportarla en tu shell interactiva no sirve de nada para un visor gestionado por systemd o Docker — defínela en el archivo de la unidad o en el archivo compose y reinicia.

### El webhook devuelve 401 o 403

`401` significa que no llegó ningún token: el nombre de cabecera que envía Immich no coincide con `webhook.header`. `403` significa que llegó un token y era incorrecto — compara el valor de la cabecera del flujo de trabajo con la variable de entorno, carácter a carácter.

### Las valoraciones se envían, pero los borrados no

Facet solo envía un borrado para una foto que realmente envió antes; esa memoria vive en `stats_cache`, en la base de datos de Facet. Restaurar una base de datos más antigua (o ejecutar contra una nueva) la pierde, y una valoración borrada durante ese hueco no se anulará en Immich. Vuelve a valorar y a borrar la foto, o corrígelo directamente en Immich.

### Las valoraciones aparecen en las fotos equivocadas

Dos archivos con el mismo `originalPath` no pueden darse dentro de Immich, pero dos raíces de *Facet* que se asignan a un mismo prefijo de Immich sí pueden colisionar. Comprueba que tus pares de `path_map` no se solapen: gana el primer par que coincida, así que un par amplio listado antes de uno más específico se lo traga.

### `rating: 0 is not valid`

El servidor Immich es anterior a la versión 3.0. Actualízalo — la semántica de borrado de Facet necesita `null`, y `push.rejected` necesita `-1`; no hay ningún respaldo que funcione en 2.x.

---

**Consulta también:** [Comandos — Sincronización con Immich](COMMANDS.md#sincronización-con-immich) · [Configuración](CONFIGURATION.md) · [Recetas de interoperabilidad con editores](INTEROP.md) para el ida y vuelta de XMP con Lightroom, darktable y digiKam.
