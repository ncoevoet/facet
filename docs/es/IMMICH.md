# Integración con Immich

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · [Deutsch](../de/IMMICH.md) · [Italiano](../it/IMMICH.md) · **Español** · [Português](../pt/IMMICH.md) · [简体中文](../zh/IMMICH.md)

[Immich](https://immich.app/) almacena, respalda y sirve tus fotos. Facet las puntúa, las clasifica y las descarta. Esta página conecta ambas piezas:

- Las valoraciones y los favoritos de Facet aparecen en Immich.
- Una subida a Immich le dice a Facet que hay trabajo nuevo esperando.

Ambos sentidos usan solo la API REST de Immich. Ninguna de las dos herramientas toca la base de datos de la otra.

**Facet requiere Immich ≥ 3.0.** Facet borra una valoración con `null` y marca un rechazo con `-1`. Un servidor 2.x rechaza el borrado, así que las valoraciones obsoletas se quedan en tus recursos.

---

## Tabla de contenidos

- [Cómo los dos ven el mismo archivo](#cómo-los-dos-ven-el-mismo-archivo)
- [Paso 1 — comparte la biblioteca con Immich](#paso-1--comparte-la-biblioteca-con-immich)
- [Paso 2 — crea una clave de API](#paso-2--crea-una-clave-de-api)
- [Paso 3 — asigna las rutas](#paso-3--asigna-las-rutas)
- [Paso 4 — prueba y luego envía](#paso-4--prueba-y-luego-envía)
- [Envío de rechazos](#envío-de-rechazos)
- [Importar y enviar pilas manuales](#importar-y-enviar-pilas-manuales)
- [El webhook entrante](#el-webhook-entrante)
- [Diagnóstico en el visor](#diagnóstico-en-el-visor)
- [Referencia de configuración](#referencia-de-configuración)
- [Solución de problemas](#solución-de-problemas)

---

## Cómo los dos ven el mismo archivo

Facet e Immich ven el mismo archivo en disco bajo rutas distintas:

- **Facet** usa la ruta absoluta en la máquina que ejecuta el escaneo, p. ej. `/mnt/photos/2026/07/IMG_1234.jpg`.
- **Immich** usa su `originalPath`: la ruta tal como se ve *desde dentro del contenedor de Immich*. A menudo es `/usr/src/app/upload/…` para las subidas, o el punto de montaje de una biblioteca externa.

Le indicas a Facet la reescritura de prefijo una sola vez, en `immich.path_map`. Toda búsqueda pasa por ella. Si está mal, todo informa "unmatched" — consulta [Solución de problemas](#solución-de-problemas).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

La asignación funciona en ambos sentidos. `--immich-sync` la usa para encontrar el recurso de Immich a partir de una ruta de Facet. El webhook la usa para encontrar la foto de Facet a partir de un `originalPath` de Immich.

## Paso 1 — comparte la biblioteca con Immich

La disposición más sencilla es una **biblioteca externa** de Immich: Immich lee las fotos donde ya están, y Facet escanea el mismo directorio.

1. En Immich, ve a **Administración → Bibliotecas externas → Crear biblioteca**, elige el propietario y añade una ruta de importación para el directorio tal como lo ve el contenedor de Immich.
2. Monta ese directorio (bind mount) de solo lectura en el contenedor de Immich. En `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Escanea la biblioteca en Immich (**Escanear todas las bibliotecas**), y escanea el mismo directorio con Facet:

   ```bash
   python facet.py /mnt/photos
   ```

No se duplica ningún archivo en disco.

También puedes subir a Immich de forma normal (copia de seguridad automática móvil, el subidor web) y apuntar Facet al directorio de subida de Immich. Solo cambian los prefijos. Vuelve a ejecutar el escaneo de Facet después de las subidas, o usa `--watch`.

## Paso 2 — crea una clave de API

En Immich: **haz clic en tu avatar → Configuración de la cuenta → Claves de API → Nueva clave de API**.

Immich ≥ 3.0 permite limitar una clave a ciertos ámbitos. La sincronización de valoraciones y favoritos necesita estos (las pilas manuales necesitan más, ver abajo):

| Ámbito | Qué hace Facet con él |
|-------|-------------------------|
| `server.about` | Comprobación de conectividad/autenticación de `--immich-test` |
| `asset.read` | Resolver recursos por `originalPath` |
| `asset.update` | Escribir `rating` e `isFavorite` |
| `album.read` | Encontrar el álbum de mejores fotos por nombre y leer sus miembros |
| `album.create` | Crear el álbum de mejores fotos la primera vez |
| `albumAsset.create` | Añadir fotos al álbum de mejores fotos |
| `albumAsset.delete` | Eliminar las fotos que caigan por debajo del umbral de mejores fotos |

Puedes omitir los cuatro ámbitos de álbum si `push.top_picks_album` está vacío. Facet solo toca los álbumes cuando ese nombre está definido. Sin `albumAsset.delete` la sincronización continúa: las eliminaciones rechazadas se omiten y se cuentan en el resumen, y la simulación las previsualiza.

Facet envía la clave en una cabecera `x-api-key`. Ponla en `scoring_config.json`:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Nota:** Facet escribe las valoraciones con `PUT /api/assets`. Immich lo marca como obsoleto, pero su sustituto aún no está publicado, así que Facet sigue usándolo.

## Paso 3 — asigna las rutas

Añade un par por cada raíz compartida. Reglas:

- Gana la primera coincidencia de prefijo. Es una comparación de cadenas literal, no de directorios.
- Termina los prefijos de directorio con `/`.
- Coloca las asignaciones más específicas antes que las más generales.

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

El marcador de posición de fábrica (`{"facet_prefix": "", "immich_prefix": ""}`) deja las rutas sin cambios. Eso solo funciona si Facet e Immich ven rutas absolutas idénticas, algo raro salvo que Facet se ejecute dentro del contenedor de Immich.

Para encontrar el valor real, abre una foto en Immich y pulsa `i` para el panel de información. Compara su ruta de archivo con la ruta que Facet muestra para esa misma foto.

## Paso 4 — prueba y luego envía

```bash
# Solo conectividad + autenticación. Sin escrituras.
python facet.py --immich-test

# Resuelve cada recurso e informa de lo que CAMBIARÍA. Sigue sin escrituras.
python facet.py --immich-sync --dry-run

# De verdad.
python facet.py --immich-sync
```

La sincronización informa de `matched` / `unmatched` / `updated` / `skipped (unrated)` / `identity_conflicts` / álbumes creados. En una simulación, `updated` cuenta los recursos que cambiarían, y no se escribe nada. Un recuento grande de `unmatched` en la primera ejecución casi siempre significa que la asignación de rutas está mal — consulta [Solución de problemas](#solución-de-problemas).

Qué se envía:

- **Valoraciones por estrellas 1–5** → el `rating` de Immich. Una foto sin valorar no envía nada.
- **Favoritos** → el `isFavorite` de Immich.
- **Borrados.** Si valoraste una foto, sincronizaste, y luego la restableciste a sin valorar, la siguiente sincronización envía `rating: null` para que Immich también la borre. Facet recuerda lo último que envió (en `stats_cache`) para esto. Envía `null`, nunca `0`: Immich v3 rechaza `0`, y un solo lote rechazado aborta toda la sincronización.
- **Un álbum de mejores fotos** (opcional), cuando `push.top_picks_album` está definido: las fotos valoradas con al menos `push.top_picks_min_rating` son miembros, y un miembro que caiga por debajo del umbral se elimina en una sincronización global mientras Facet pueda atribuirlo (una foto eliminada o el asset de otra aplicación queda como está); un miembro existente nunca se vuelve a añadir.

En modo multiusuario, `--immich-sync --user alice` envía las valoraciones propias de Alice (`user_preferences`) en lugar de las globales, y sigue su estado de sincronización por separado.

## Envío de rechazos

Desactivado por defecto. Cuando se activa, una foto que rechazas en la vista de descarte de Facet recibe el marcador de rechazo de Immich:

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
- **El rechazo prevalece sobre las estrellas.** Una foto rechazada con 5 estrellas envía `-1`, no `5`.
- **Quitar el rechazo lo borra.** La foto envía entonces su valoración por estrellas actual, o `rating: null` si no tiene ninguna.
- Una foto rechazada nunca se une al álbum de mejores fotos.
- `push.ratings: false` también lo desactiva, ya que `-1` es una valoración.

Déjalo desactivado si otras personas (o tu teléfono) consultan la biblioteca de Immich: verán el `-1`.

## Importar y enviar pilas manuales

Las pilas manuales tienen su propio flujo de **plan y aplicación desde la CLI local**, con las opciones habituales `--config`, `--db` y `--user`. La sincronización de valoraciones y favoritos no se ve afectada.

Requisitos:

- Immich **≥ 3.0** (Facet también comprueba la compatibilidad con pilas en tiempo de ejecución).
- Permisos de la clave: `user.read` y `stack.read` además de `asset.read`; el envío necesita también `stack.create` y `asset.update`. No hacen falta `stack.update` ni `stack.delete`.
- Las instalaciones multiusuario deben indicar un usuario existente.
- La clave de Immich nunca se usa en operaciones de pilas desde el visor web, los asistentes (MCP) ni el webhook de subida.

Flujo de trabajo:

1. Vista previa. Es de solo lectura en ambos lados y no migra la base de datos.
2. Revisa el plan y su resumen SHA-256.
3. Aplica de forma explícita.

Opciones y límites:

- `--stack-id UUID` (repetible) limita la ejecución a esas pilas de origen.
- `--stack-plan-out` escribe un JSON privado nuevo (modo POSIX `0600`) y se niega a sobrescribir.
- Un plan admite como máximo **1000 grupos, 1000 miembros por grupo, 20000 miembros totales y 16 MiB**. Usa `--stack-id` para acotarlo.
- En Windows, elige una carpeta de salida cuya ACL limite el acceso a tu cuenta; los bits de permisos POSIX no protegen el archivo allí.

Reglas de coincidencia:

- Cada miembro debe corresponder exactamente a una foto indexada, visible y disponible del propietario remoto. Un solo miembro ausente o ambiguo omite todo el grupo.
- El envío solo crea una pila a partir de recursos remotos que aún no están apilados.
- Una coincidencia exacta de miembros y portada vincula las dos pilas al aplicar.
- Los solapamientos parciales, las portadas diferentes, la membresía modificada y los casos de desapilado en un solo lado se omiten como conflictos. Las pilas existentes nunca se actualizan.
- Solo la portada se transfiere; el orden de los demás miembros no.
- No hay sincronización bidireccional automática, sondeo ni propagación del desapilado.

Los planes, vínculos y recibos están ligados al servidor, la cuenta remota, el propietario local y el mapa de rutas. Si cambia cualquiera de ellos, el plan antiguo ya no se aplica. Los recibos guardan resultados e ID de recursos remotos, nunca credenciales.

Aplicar revalida cada grupo antes de escribir y lo relee después. Si se pierde una respuesta de creación, Facet la reconcilia antes de cualquier reintento en lugar de enviarla de nuevo. Cancelar para entre grupos; una aplicación posterior continúa a partir de los recibos.

> **Advertencia:** Immich no puede crear una pila de forma condicional. Otro cliente puede cambiar los recursos entre la última comprobación de Facet y la escritura, y Facet no puede revertirlo.

## El webhook entrante

El webhook funciona en sentido contrario: Immich le dice a Facet que un recurso cambió, y Facet responde con lo que sabe.

**Está desactivado por defecto y nunca inicia un escaneo.** En su lugar:

- **Foto conocida y puntuada** → Facet envía de vuelta a Immich su valoración y favorito de inmediato. Puntúas una foto, la subes, y la valoración llega a Immich sin esperar a `--immich-sync`.
- **Foto desconocida o aún no puntuada** → Facet añade la ruta a una lista pendiente acotada, y la siguiente `--immich-sync` la registra en el log.

### Actívalo

El token es un secreto, así que vive en una variable de entorno, no en `scoring_config.json` (ese archivo es legible por cualquiera en la mayoría de las instalaciones). La configuración nombra la variable; la variable contiene el valor.

1. Genera un token y expórtalo allí donde arranque el visor — unidad de systemd, `docker-compose.yml` o perfil del shell:

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

Si `token_env` está vacío, o la variable no está definida o está vacía, el endpoint queda desactivado y devuelve **404** (igual que `frame.tokens` y `upload.username`).

### Apunta Immich hacia él

En Immich ≥ 3.0: **Administración → Flujos de trabajo → Crear flujo de trabajo**.

1. **Activador** — `Asset uploaded`. Añade `Asset updated` si también quieres que las ediciones lo disparen.
2. **Acción** — **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, en una dirección a la que el contenedor de Immich pueda llegar. Si ambos se ejecutan en Docker en el mismo host, usa el nombre del servicio (`http://facet:5000/…`), no `localhost`.
4. **Cabecera** — nombre `x-facet-token`, valor tu token. El nombre debe coincidir con `webhook.header`. También se acepta `Authorization: Bearer <token>`, para los proxies que solo ofrecen eso.
5. Guarda, y luego sube una foto para comprobarlo.

### Qué responde el endpoint

| Estado | Descripción |
|--------|---------|
| `202` | Aceptado. El JSON cuenta los recursos de esta entrega: `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | JSON válido, pero ningún recurso que Facet reconociera. Se registra en el log, no es un error. |
| `400` | El cuerpo no era JSON. |
| `401` | No hay token en la solicitud. |
| `403` | Token incorrecto. |
| `404` | La función está desactivada (no hay token configurado). |

Facet lee `originalPath` de la carga, esté donde esté: un recurso suelto, `{"asset": {…}}`, una lista, o cualquiera de ellos bajo `data` / `items` / `assets`. Si la carga incluye el `id` del recurso, Facet consulta ese recurso en Immich y comprueba su ruta y su propietario/biblioteca antes de actualizar. Una discrepancia cuenta como `failed`.

La siguiente sincronización registra las rutas pendientes:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Escanea esas fotos (`python facet.py /mnt/photos`) y saldrán de la lista en la siguiente sincronización. La lista conserva como máximo `max_pending` entradas y descarta primero las más antiguas.

### Notas de seguridad

- El token se compara en tiempo constante; un token incorrecto recibe un `403` sin más, sin ninguna señal de temporización.
- Sirve el visor sobre HTTPS salvo que Immich lo alcance a través de una red privada: el token viaja en una cabecera en cada entrega.
- Para rotar el token, cambia a la vez la variable de entorno y la cabecera del flujo de trabajo de Immich, y reinicia el visor.
- El webhook envía la valoración global, no la de ningún usuario concreto. Si quieres valoraciones por usuario en Immich, deja el webhook desactivado y ejecuta `--immich-sync --user <nombre>` según una programación.

## Diagnóstico en el visor

Abre **Diagnóstico de Immich** desde el submenú **Tareas y diagnóstico** del menú de usuario. Requiere acceso de superadministrador en modo multiusuario, y acceso de edición (o edición local de confianza) en modo individual.

- No se lee nada de Immich hasta que haces clic en **Probar conexión**. La prueba lee la versión del servidor y el acceso a la cuenta, y no escribe nada.
- La cobertura de rutas comprueba como máximo 200 fotos indexadas. No confirma que cada una coincida con un recurso de Immich.
- La hora de la última sincronización puede ser anterior a un cambio del servidor configurado.
- La comprobación de versión no verifica los permisos de pilas.
- Nunca se muestran credenciales ni rutas del servidor.

## Referencia de configuración

El bloque `immich` completo, con los valores por defecto de fábrica:

```json
"immich": {
  "url": "",
  "api_key": "",
  "owner_id": "",
  "library_id": "",
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
| `owner_id` | `""` | Solo coincide con recursos con este `ownerId` exacto de Immich. |
| `library_id` | `""` | Solo coincide con recursos de este `libraryId` exacto de Immich. Vacío significa cualquier biblioteca. |
| `path_map` | un par vacío | Reescrituras de prefijo entre las rutas de Facet y el `originalPath` de Immich. Gana la primera coincidencia; se usa en ambos sentidos. |
| `push.ratings` | `true` | Envía las valoraciones por estrellas 1–5 (y sus borrados). |
| `push.favorites` | `true` | Envía `isFavorite` (y sus borrados). |
| `push.rejected` | `false` | Envía `rating: -1` para las fotos rechazadas en Facet. Requiere `push.ratings`. |
| `push.top_picks_album` | `""` | Nombre del álbum a mantener poblado: los miembros por debajo de `push.top_picks_min_rating` se eliminan en una sincronización global mientras Facet pueda atribuirlos. Vacío significa que Facet nunca toca los álbumes. |
| `push.top_picks_min_rating` | `4` | Valoración por estrellas mínima para ese álbum. |
| `webhook.token_env` | `""` | Variable de entorno que contiene el secreto del webhook. Vacío desactiva el endpoint. |
| `webhook.header` | `"x-facet-token"` | Cabecera en la que Immich envía el token. |
| `webhook.max_pending` | `500` | Longitud máxima de la lista de rutas pendientes (sin puntuar). |
| `timeout_seconds` | `30` | Tiempo de espera HTTP por solicitud. |

## Solución de problemas

### Todo vuelve como `unmatched`

La asignación de rutas está mal. Este es, con diferencia, el fallo más frecuente.

1. Abre una foto en Immich y pulsa `i`. Anota la ruta del panel de información.
2. Busca la ruta de esa misma foto en Facet (el panel de detalle de la galería, o `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. Las dos rutas terminan igual. Las partes que difieren son tu `facet_prefix` y tu `immich_prefix`.

Trampas habituales:

- **Falta una barra final.** `"/mnt/photos"` → `"/usr/src/app/external"` también reescribe `/mnt/photosXYZ/a.jpg`. Termina ambos prefijos con `/`.
- **Ruta del host frente a ruta del contenedor.** La ruta de Immich es lo que ve el *contenedor*. Compruébalo con `docker compose exec immich-server ls /usr/src/app/external`.
- **Enlaces simbólicos y bind mounts.** Immich almacena la ruta que recorrió. Un enlace simbólico en uno de los lados hace que las cadenas difieran.
- **Mayúsculas/minúsculas y Unicode.** La comparación es exacta. En un recurso compartido que no distingue mayúsculas de minúsculas, `/Photos/` y `/photos/` no coinciden entre sí.
- **Immich aún no ha indexado el archivo.** Ejecuta **Escanear todas las bibliotecas** y comprueba que el recurso existe en Immich.

`--immich-sync --dry-run` registra en el log las primeras 20 rutas sin coincidencia, lo que suele mostrar el prefijo equivocado.

### `--immich-test` falla

- `Unsupported Immich URL scheme` — `url` necesita `http://` o `https://`.
- `HTTP 401` — la clave de API es incorrecta o fue revocada.
- `HTTP 403` — a la clave le falta `server.about`. Vuelve a crearla con los siete ámbitos anteriores.
- Conexión rechazada / tiempo de espera agotado — el puerto es incorrecto, o Facet no puede alcanzar el contenedor. Pruébalo con `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` desde la máquina que ejecuta Facet.

### El webhook devuelve 404

La función está desactivada: `webhook.token_env` está vacío, o la variable que nombra no está definida o está vacía *en el entorno del visor*. Exportarla en tu shell no llega a un visor gestionado por systemd o Docker. Defínela en la unidad o en el archivo compose y reinicia.

### El webhook devuelve 401 o 403

`401`: no llegó ningún token, así que el nombre de cabecera que envía Immich no coincide con `webhook.header`. `403`: el token es incorrecto. Compara el valor de la cabecera del flujo de trabajo con la variable de entorno.

### `ModuleNotFoundError: No module named 'sync'`

El servidor parece sano, pero el webhook falla cuando Immich lo llama y `--immich-sync` falla directamente. Compruébalo con:

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

Si obtienes `ModuleNotFoundError: No module named 'sync'`, tu imagen de Docker es demasiado antigua. Descarga la imagen actual o reconstrúyela a partir de un checkout actual.

### Las valoraciones se envían, pero los borrados no

Facet solo borra una valoración que envió antes, y las recuerda en `stats_cache`, en la base de datos de Facet. Restaurar una base de datos más antigua, o usar una nueva, pierde esa memoria: una valoración borrada en ese hueco se queda en Immich. Vuelve a valorar y a borrar la foto, o corrígelo en Immich.

### Las valoraciones aparecen en las fotos equivocadas

Facet omite las coincidencias ambiguas y las informa como `identity_conflicts`:

- una ruta de Facet que coincide con varios recursos de Immich
- varias rutas de Facet que se asignan a la misma ruta de Immich

No se escribe nada para esas rutas; las demás fotos se siguen sincronizando.

Un lote de webhook es más estricto: si varias rutas de Facet reclaman el mismo destino o ID de recurso, se rechazan todas las entradas elegibles del lote y se cuentan como `failed`. Corrige las raíces solapadas en `path_map`, o define `owner_id` y `library_id`, y reintenta. No adivines el propietario a partir del nombre de una persona o de la ruta.

Las respuestas de Immich deben incluir `id` y `originalPath`, y deben coincidir con el propietario y la biblioteca configurados. Una actualización correcta significa que Immich la aceptó; su propio trabajo de metadatos en segundo plano puede seguir en curso.

### `rating: 0 is not valid`

El servidor Immich es anterior a la versión 3.0. Actualízalo: Facet necesita `null` para borrar y `-1` para `push.rejected`, y no hay ningún modo de evitarlo en 2.x.

---

**Consulta también:** [Comandos — Sincronización con Immich](COMMANDS.md#sincronización-con-immich) · [Configuración](CONFIGURATION.md) · [Recetas de interoperabilidad con editores](INTEROP.md) para el ida y vuelta de XMP con Lightroom, darktable y digiKam.
