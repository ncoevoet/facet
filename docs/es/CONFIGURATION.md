# Referencia de configuración

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · **Español** · [Português](../pt/CONFIGURATION.md) · [简体中文](../zh/CONFIGURATION.md)

Cada ajuste se incluye en `config/scoring_config.default.json`. Tu propio `scoring_config.json` lo anula clave por clave — consulta [Valores predeterminados y tu anulación](#valores-predeterminados-y-tu-anulación). Tras un cambio, ejecuta `python facet.py --recompute-average` para actualizar las puntuaciones (no se necesita GPU).

## Tabla de contenidos

- [Valores predeterminados y tu anulación](#valores-predeterminados-y-tu-anulación)
- [Usuarios](#usuarios)
- [Escaneo](#escaneo)
- [Categorías](#categorías)
- [Contextos de puntuación](#contextos-de-puntuación)
- [Puntuación](#puntuación)
- [Umbrales](#umbrales)
- [Composición](#composición)
- [Ajustes EXIF](#ajustes-exif)
- [Exposición](#exposición)
- [Penalizaciones](#penalizaciones)
- [Normalización](#normalización)
- [Modelos](#modelos)
- [Modelos de evaluación de calidad](#modelos-de-evaluación-de-calidad)
- [Procesamiento](#procesamiento)
- [Decodificación RAW](#decodificación-raw)
- [Mapeo de tono HDR PQ](#mapeo-de-tono-hdr-pq)
- [Detección de ráfagas](#detección-de-ráfagas)
- [Puntuación de ráfagas](#puntuación-de-ráfagas)
- [Detección de duplicados](#detección-de-duplicados)
- [Detección de rostros](#detección-de-rostros)
- [Agrupación de rostros](#agrupación-de-rostros)
- [Procesamiento de rostros](#procesamiento-de-rostros)
- [Detección de monocromo](#detección-de-monocromo)
- [Etiquetado](#etiquetado)
- [Etiquetas independientes](#etiquetas-independientes)
- [Análisis](#análisis)
- [Visor](#visor)
- [Rendimiento](#rendimiento)
- [Almacenamiento](#almacenamiento)
- [Plugins](#plugins)
- [Cápsulas](#cápsulas)
- [Grupos de similitud](#grupos-de-similitud)
- [Escenas](#escenas)
- [OCR](#ocr)
- [Línea de tiempo](#línea-de-tiempo)
- [Mapa](#mapa)
- [Traducción](#traducción)

---

## Valores predeterminados y tu anulación

`scoring_config.json` guarda **solo lo que has cambiado**. Facet lo resuelve por encima de `config/scoring_config.default.json`, así que cualquier cosa que omitas conserva el valor incluido. Una instalación nueva no tiene `scoring_config.json` y funciona con los valores predeterminados.

Para subir el peso estético de los retratos y establecer una contraseña de edición, el archivo completo es:

```json
{
  "viewer": { "edition_password": "your-password" },
  "categories": [ ... ]
}
```

Cómo se combinan ambos archivos:

- **Los objetos se combinan clave por clave.** `{"performance": {"mmap_size_mb": 4096}}` cambia solo ese ajuste; `cache_size_mb` y el resto de claves de `performance` conservan sus valores incluidos.
- **Los arrays se sustituyen por completo.** Un array `categories` en tu archivo sustituye por completo al incluido. El orden importa (`categories` es de primera coincidencia gana, `scoring_contexts.*.promote` se lee en orden), y omitir una categoría de tu array la elimina.

Para cambiar un solo peso en una sola categoría, copia el array `categories` completo de `config/scoring_config.default.json`, edítalo y consérvalo en tu archivo.

### Actualizar una instalación existente

No hay que hacer nada: un `scoring_config.json` completo de una versión anterior sigue funcionando. Cualquier escritura de Facet en el archivo (guardar pesos o prioridades en el visor, un cambio de umbral de panorama, el primer inicio de sesión que actualiza una contraseña en texto plano, un escaneo en el que `validate_weights` corrige pesos) lo reescribe como una anulación y descarta cada clave que coincida con el valor predeterminado incluido.

Para compactarlo bajo demanda, tomando antes una copia de seguridad en `0600`:

```bash
python database.py --compact-config
```

El resultado se resuelve exactamente en la misma configuración.

> **Nota:** Un valor igual al predeterminado incluido no permanece en tu archivo. Si una versión posterior cambia ese predeterminado, tu comportamiento cambia también. Para fijar un valor, debe ser distinto del predeterminado.


## Usuarios

Modo multiusuario opcional. Cuando la clave `users` contiene al menos un usuario, el inicio de sesión por usuario sustituye a la autenticación de contraseña única.

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

### Campos de usuario

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `password_hash` | string | Hash PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`), generado por `--add-user` |
| `display_name` | string | Mostrado en la cabecera de la UI |
| `role` | string | `user`, `admin` o `superadmin` |
| `directories` | array | Directorios de fotos privados de este usuario (comparación: ver [Directorios compartidos](#directorios-compartidos)) |

### Directorios compartidos

`shared_directories` (hermana de los objetos de usuario) enumera los directorios que todos los usuarios pueden ver. Las entradas de `directories` y `shared_directories` se comparan con las rutas que guardó el escáner:

- Se ignoran las mayúsculas ASCII en Windows y macOS, y en las entradas UNC o de letra de unidad en cualquier sistema.
- En los demás hosts (Linux, por ejemplo) las mayúsculas cuentan: escribe cada entrada exactamente como la guardó el escáner.
- No se gestionan: las diferencias de mayúsculas fuera de ASCII, y una unidad asignada que el host no puede resolver.
- Una entrada en blanco no concede nada.

### Roles

| Rol | Ver propios + compartidos | Valorar/favoritos | Gestionar personas/rostros | Iniciar escaneos |
|------|:-:|:-:|:-:|:-:|
| `user` | sí | sí | no | no |
| `admin` | sí | sí | sí | no |
| `superadmin` | sí | sí | sí | sí |

### Añadir usuarios

Los usuarios se crean solo desde la CLI; no hay interfaz ni API de registro:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Solicita una contraseña, escribe el hash en scoring_config.json
```

Después edita `scoring_config.json` para definir sus `directories`.

### Compatibilidad con versiones anteriores

- Sin la clave `users` = modo de usuario único (comportamiento sin cambios).
- `viewer.password` y `viewer.edition_password` se ignoran en modo multiusuario.
- Las valoraciones existentes en la tabla `photos` se mantienen para el modo de usuario único; `--migrate-user-preferences` las copia.

---

## Escaneo

Controla qué directorios visita el escaneo.

```json
{
  "scanning": {
    "skip_hidden_directories": true,
    "skip_directories": ["@eaDir", "#recycle", "#snapshot", "@Recycle"]
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | Omite los directorios cuyo nombre empieza por `.` |
| `skip_directories` | `["@eaDir", "#recycle", "#snapshot", "@Recycle"]` | Globs de nombres de carpeta omitidos a cualquier profundidad |

Notas sobre `skip_directories`:
- Los globs usan `fnmatch`, distinguen mayúsculas y solo se aplican al nombre de la carpeta.
- Los valores predeterminados cubren `@eaDir` de Synology (sus miniaturas `SYNOPHOTO_THUMB_*.jpg`), `#recycle`, `#snapshot` y `@Recycle` de QNAP.
- Tu lista reemplaza la predeterminada; `[]` desactiva la omisión por nombre. La raíz del escaneo nunca se omite.
- Las fotos ya indexadas desde estas carpetas permanecen en la base de datos.

---

## Categorías

Array de definiciones de categorías. Consulta [Puntuación](SCORING.md) para la guía completa de categorías.

Cada categoría tiene:
- `name` - Identificador de la categoría
- `priority` - Menor = mayor prioridad (se evalúa primero)
- `filters` - Condiciones de coincidencia
- `weights` - Pesos de las métricas de puntuación (deben sumar 100)
- `modifiers` - Ajustes de comportamiento
- `tags` - Vocabulario CLIP para coincidencia basada en etiquetas

> **Pesos de forma y armonía cromática.** El bloque `weights` de cada categoría tiene cinco claves rellenadas por `--recompute-form`: `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` y `color_harmony_percent`. Se incluyen a `0`, por lo que las puntuaciones no cambian hasta que asignes un peso a alguna (entonces ejecuta `--recompute-average`). Los pesos siguen sumando 100.

> **`quality_percent` cuenta como `aesthetic`.** La calidad no tiene puntuación propia, así que `quality_percent` se suma a `aesthetic_percent` antes de puntuar. Ver [SCORING.md](SCORING.md).

> **La categoría `astro` incluida necesita un fotograma oscuro.** Además de una de sus etiquetas, exige `luminance_max: 0.30` (luminancia media de 0.30 como máximo), así que una escena luminosa etiquetada como `aurora` o `stars` no es `astro`. Si tu `scoring_config.json` tiene su propio array `categories`, su entrada `astro` no recibe este filtro: añade `"luminance_max": 0.30` en `astro.filters`, o borra el array. `python facet.py --doctor` imprime un «Config notice» cuando `astro` no tiene `luminance_max`. Después ejecuta `--recompute-average` (tras una actualización: primero `--recompute-silhouette`, luego `--recompute-average` dos veces; ver [COMMANDS.md](COMMANDS.md)).

---

## Contextos de puntuación

Un contexto de puntuación cambia qué categoría gana para un álbum o una foto. Promueve unas pocas categorías al frente del orden global de `categories` y excluye otras; el resto conserva su orden de prioridad. Úsalo cuando el orden global elija la categoría equivocada para una sesión: un fotograma de baile a contraluz etiquetado `sports` lo captura `silhouette` (prioridad 42) antes que `sports` (prioridad 71). Los controles deslizantes de peso no pueden arreglarlo, porque solo cambian cómo puntúa la categoría seleccionada.

```json
{
  "scoring_contexts": {
    "default": {
      "label_key": "comparison.context.default",
      "promote": [],
      "excluded": [],
      "suggest_from_moments": []
    },
    "action_stage": {
      "label_key": "comparison.context.action_stage",
      "promote": ["sports", "concert", "candid"],
      "excluded": ["silhouette"],
      "suggest_from_moments": ["sports", "concert", "nightlife"]
    }
  }
}
```

| Campo | Descripción |
|-------|-------------|
| `label_key` | Clave i18n para el nombre visible del contexto |
| `promote` | Categorías movidas al frente del orden de evaluación, en el orden dado |
| `excluded` | Categorías que nunca coinciden bajo este contexto |
| `suggest_from_moments` | Valores de `narrative_moment` que sugieren este contexto para un álbum (`GET /api/albums/{id}/suggested_context`, consulta [VIEWER.md](VIEWER.md)) |

**Orden efectivo** = `promote` (en orden) → el orden de prioridad global sin los nombres promovidos ni excluidos → `default` (la categoría comodín, prioridad 999) al final.

- Un nombre que está en `promote` y en `excluded` queda excluido.
- `default` nunca se puede promover ni excluir.
- Sin contexto, o con un nombre desconocido, se usa el orden global sin más (un nombre desconocido registra una advertencia).
- `python facet.py --validate-categories` informa de nombres de categoría desconocidos, de nombres presentes en ambas listas y de entradas `suggest_from_moments` que no son claves de `narrative_moments.event_types.<default_event_type>`. Las erratas, si no, pasan en silencio.

Preajustes incluidos (`default` está vacío, así que nada cambia hasta que asignes un contexto):

| Contexto | Promueve | Excluye | Sugerido a partir de momentos |
|---------|----------|----------|------------------------|
| `default` | — | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` | `sports`, `concert`, `nightlife` |
| `party_event` | `group_portrait`, `candid`, `food` | — | `celebration`, `group_gathering`, `dining` |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — | `portrait`, `children` |
| `wildlife` | `wildlife` | — | `nature_wildlife`, `pets` |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — | `scenic_landscape`, `mountains`, `snow_winter` |
| `motorsport` | `sports`, `vehicle` | `silhouette` | `sports`, `road_vehicle` |

### Añadir tu propio contexto

Añade una clave bajo `scoring_contexts` y funciona como un preajuste incluido: puedes asignarla a un álbum y editarla en la pestaña **Contexto de puntuación**.

```json
{
  "scoring_contexts": {
    "dance_comp": {
      "label_key": "comparison.context.dance_comp",
      "promote": ["sports", "concert"],
      "excluded": ["silhouette", "fashion"],
      "suggest_from_moments": ["sports"]
    }
  }
}
```

Si `label_key` no tiene traducción, el selector muestra el **`name`** del contexto (por ejemplo, `dance_comp`). Añade la clave a los seis paquetes `i18n/translations/*.json` para obtener una etiqueta localizada.

### Editar un contexto

En la pestaña **Contexto de puntuación** del visor (restringido al modo edición, `PUT /api/config/scoring_contexts/{name}`), arrastra o mueve categorías a la lista de promovidas, haz clic en una categoría para alternar su exclusión y guarda.

- Solo `promote` y `excluded` son editables; `label_key`, `suggest_from_moments` y los demás contextos se dejan como estaban.
- Se rechaza un guardado cuando el contexto no existe, cuando una entrada no es una categoría existente, cuando `default` está en alguna de las dos listas o cuando `promote` repite un nombre. Un nombre en ambas listas se acepta (`excluded` gana); una repetición dentro de `excluded` se colapsa.
- Cada guardado conserva una copia `.backup.<timestamp>` con marca de tiempo de la configuración.
- Editar un contexto no recategoriza las fotos: ejecuta un recálculo después (consulta [Cambiar las prioridades requiere un recálculo](#reordenar-la-prioridad-global)). La pestaña tiene un botón **Recalcular ahora**.

### Asignar un contexto

Asigna un contexto **por álbum** con `PUT /api/albums/{id}/scoring_context` (requiere edición).

- Se aplica a cada foto del álbum en ese momento, salvo las fotos cuyo contexto hayas fijado a mano.
- Una foto añadida más tarde a un álbum manual hereda el contexto. Una foto nueva que coincide con el filtro de un álbum inteligente, no; vuelve a llamar a `PUT` para aplicarlo de nuevo.
- Un álbum inteligente usa su filtro guardado, no los interruptores de ocultación de la galería, así que puede abarcar más fotos de las que muestra su vista de galería.
- `DELETE /api/albums/{id}/scoring_context` quita el contexto de las fotos que fijó este álbum. Las elecciones manuales se conservan.
- Retirar fotos de un álbum (`DELETE /api/albums/{id}/photos`) les quita el contexto de este álbum. Una foto que sigue en otro álbum con contexto toma el de ese álbum.
- `GET /api/albums/{id}/suggested_context` propone un contexto a partir del `narrative_moment` dominante del álbum, mediante `suggest_from_moments`. No cambia nada.

Para una sola foto obstinada, usa una **anulación de categoría**: `POST /api/comparison/override_category` (requiere edición) fija la categoría directamente, y `POST /api/comparison/clear_category_override` la elimina. Una anulación prevalece sobre cualquier contexto.

Las anulaciones y los contextos sobreviven a los reescaneos. Un filtro numérico sigue fallando cuando falta su valor EXIF, sea cual sea el contexto — consulta [Puntuación — la trampa de los EXIF faltantes](SCORING.md#la-trampa-de-los-exif-faltantes).

### Reordenar la prioridad global

`GET|POST /api/config/category_priorities` (requiere edición) lee y guarda el orden global del que parte cada contexto. El visor reordena los números de prioridad existentes en lugar de renumerarlos.

- `default` (prioridad 999) queda siempre al final y no se puede mover.
- Una categoría con prioridad ausente o duplicada recibe al guardar un valor nuevo por encima del máximo actual.
- Cada guardado conserva una copia `.backup.<timestamp>` con marca de tiempo de `scoring_config.json`; se conservan las 20 más recientes.

**Cambiar las prioridades requiere un recálculo.** Un reordenamiento no cambia la `category` almacenada de ninguna foto. Ejecuta `python facet.py --recompute-average`, o inicia `POST /api/scan/recompute` desde el visor (requiere edición) y sigue `GET /api/scan/recompute_status`.

- Un recálculo y un escaneo no pueden ejecutarse a la vez: la CLI lo rechaza, y el visor indica qué trabajo tiene la biblioteca.
- Dos escaneos iniciados desde una terminal solo generan un aviso (`--resume` lo rechaza).
- Con `normalization.per_category` activado, un recálculo puede necesitar ejecutarse dos veces — consulta [Normalización](#normalización).

---

## Puntuación

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `score_min` | `0.0` | Puntuación mínima posible |
| `score_max` | `10.0` | Puntuación máxima posible |
| `score_precision` | `2` | Decimales para las puntuaciones |

---

## Umbrales

Umbrales de puntuación. Solo queda `blink_penalty_percent`. Que una foto sea un retrato, una toma nocturna o una larga exposición lo deciden los `filters` de cada categoría (ver [Categorías](#categorías)), no este bloque.

```json
{
  "thresholds": {
    "blink_penalty_percent": 50
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `blink_penalty_percent` | `50` | Multiplicador de la puntuación cuando se detecta un parpadeo (0,5x) |

---

## Composición

Puntuación de composición basada en reglas (usada cuando SAMP-Net no está activo).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `power_point_weight` | `2.0` | Peso para la colocación según la regla de los tercios |
| `line_weight` | `1.0` | Peso para las líneas guía |

---

## Ajustes EXIF

Ajustes automáticos de puntuación según la configuración de la cámara.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `iso_sharpness_compensation` | `true` | Reduce la penalización por nitidez con ISO alto |
| `aperture_isolation_boost` | `true` | Aumenta el aislamiento con aperturas amplias (f/1.4-f/2.8) |

---

## Exposición

Controla el análisis de exposición y la detección de recortes.

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `shadow_clip_threshold_percent` | `15` | Señala si > 15 % de los píxeles son negro puro |
| `highlight_clip_threshold_percent` | `10` | Señala si > 10 % de los píxeles son blanco puro |
| `silhouette_detection` | `true` | Con `true`, una foto marcada `is_silhouette` omite la penalización por recorte en su puntuación agregada. El indicador en sí no es configurable: sale de una regla fija basada en el rostro (ver [SCORING.md](SCORING.md)) |

---

## Penalizaciones

Penalizaciones de puntuación por problemas técnicos.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | El ruido por encima de esto activa una penalización |
| `noise_max_penalty_points` | `1.5` | Penalización máxima por ruido |
| `noise_penalty_per_sigma` | `0.3` | Puntos por sigma por encima del umbral |
| `leading_lines_blend_percent` | `30` | Mezcla en comp_score |
| `oversaturation_threshold` | `0.9` | Umbral de saturación media |
| `oversaturation_penalty_points` | `0.5` | Penalización por sobresaturación |

**Fórmula de penalización por ruido:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalización

Controla cómo se escalan las métricas brutas a puntuaciones de 0 a 10.

```json
{
  "normalization": {
    "method": "percentile",
    "percentile_target": 90,
    "per_category": true,
    "category_min_samples": 50
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `method` | `"percentile"` | Método de normalización |
| `percentile_target` | `90` | El percentil 90 = puntuación de 10,0 |
| `per_category` | `true` | Normalización específica por categoría |
| `category_min_samples` | `50` | Fotos mínimas para la normalización por categoría |

> **Nota:** Con `per_category` activado, un solo recálculo no basta. Los percentiles se agrupan según la categoría *almacenada* de cada foto antes de que el recálculo la reasigne. Tras un cambio que mueva fotos entre categorías (prioridades, un contexto de puntuación, una anulación de categoría), ejecuta `--recompute-average` dos veces.

---

## Modelos

Selecciona qué modelos se usan por cada perfil de VRAM.

```json
{
  "models": {
    "vram_profile": "auto",
    "keep_in_ram": "auto",
    "profiles": {
      "legacy": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CPU: CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (8GB+ RAM; saliency/IQA are slower on CPU)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (6-14GB VRAM)"
      },
      "16gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-2b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-2B tagging (~14GB VRAM)"
      },
      "24gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-4b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-4B tagging (~18GB VRAM)"
      }
    },
    "clip": {
      "model_name": "google/siglip2-so400m-patch16-naflex",
      "backend": "transformers",
      "embedding_dim": 1152,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 5
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 15
    },
    "qwen2_vl": {
      "model_path": "Qwen/Qwen2-VL-2B-Instruct",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 256
    },
    "qwen3_5_2b": {
      "model_path": "Qwen/Qwen3.5-2B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 4
    },
    "qwen3_5_4b": {
      "model_path": "Qwen/Qwen3.5-4B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 2
    },
    "saliency": {
      "model": "ZhengPeng7/BiRefNet_dynamic",
      "resolution": 1024,
      "mask_threshold": 0.3,
      "min_subject_pixels": 50
    },
    "samp_net": {
      "model_path": "pretrained_models/samp_net.pth"
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `vram_profile` | `"auto"` | Perfil activo (`auto`, `legacy`, `8gb`, `16gb`, `24gb`); `FACET_VRAM_PROFILE` lo anula (ver más abajo) |
| `keep_in_ram` | `"auto"` | Mantener los modelos en RAM entre los fragmentos multipase (`"auto"`, `"always"`, `"never"`); `auto` comprueba antes la RAM libre |
| `ram_cache_reserve_gb` | `4.0` (opcional, no está en el archivo incluido) | RAM (GB) que se deja libre junto a un modelo en caché con `"auto"` |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modelos PyIQA a ejecutar para este perfil (los cuatro perfiles ejecutan el conjunto completo) |
| `profiles.*.saliency_enabled` | `true` (todos los perfiles) | Ejecutar la saliencia del sujeto BiRefNet para este perfil |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modelo de embeddings SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) o `"open_clip"` (heredado) |
| `clip.embedding_dim` | `1152` | Dimensiones del embedding (1152 para SigLIP 2) |
| `clip.tag_threshold_percent` | `8` | Similitud mínima para una coincidencia de **etiqueta** con el etiquetador SigLIP 2 de 16gb/24gb (sustituye a `similarity_threshold_percent`) |
| `clip.search_threshold_percent` | `5` | Similitud mínima para la búsqueda semántica (`GET /api/search`); número entero `0-50` |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modelo CLIP heredado (perfiles legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Pesos preentrenados heredados |
| `clip_legacy.embedding_dim` | `768` | Dimensiones del embedding heredado |
| `clip_legacy.tag_threshold_percent` | `8` | El mismo umbral de etiquetas para el etiquetador CLIP de legacy/8gb; `tagging.max_tags` limita el número |
| `clip_legacy.search_threshold_percent` | `15` | Umbral de búsqueda semántica en el perfil legacy/8gb; número entero `0-50` |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Modelo para la opción manual `composition_model: "qwen2-vl-2b"` (ningún perfil lo usa) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modelo de etiquetado para el perfil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Imágenes por lote de inferencia VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modelo de etiquetado para el perfil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Imágenes por lote de inferencia VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modelo de saliencia BiRefNet |
| `saliency.resolution` | `1024` | Resolución de inferencia |
| `saliency.mask_threshold` | `0.3` | Umbral sigmoide para la máscara binaria del sujeto |
| `saliency.min_subject_pixels` | `50` | Píxeles mínimos del sujeto para contar un sujeto como detectado |

Notas:
- **`ram_cache_reserve_gb`:** un modelo se conserva solo mientras la RAM libre supere su tamaño más esta reserva. `"always"` omite la comprobación; `"never"` no almacena nada en caché. Debe ser un número >= 0, o el escaneo se detiene al inicio. Bajo presión de memoria, la caché libera primero el modelo que se necesitará más tarde (ver [Cómo funciona el modo multipase](#cómo-funciona-el-modo-multipase)).
- **Umbrales de etiquetas y de búsqueda:** `tag_threshold_percent` controla el etiquetado (escaneo, `--recompute-tags`, `tag_existing.py`). `search_threshold_percent` es el valor predeterminado del control deslizante de búsqueda 0-50 % de la galería (`search_threshold_default` en `/api/config`). El valor `5` de SigLIP favorece la exhaustividad: en una muestra de 34 fotos conservó las 21 coincidencias verdaderas y dejó pasar 3 de 13 no coincidentes.

**Búsqueda semántica y una biblioteca incrustada con un perfil distinto:** `GET /api/search` elige el codificador de texto y su `search_threshold_percent` a partir del bloque, `clip` o `clip_legacy`, que coincide con la dimensión de embedding *almacenada*, no con el `vram_profile` activo. Una biblioteca incrustada con CLIP de 768 dimensiones y explorada en una máquina 16gb busca, por tanto, con `clip_legacy`. Si la dimensión almacenada no coincide con ninguno de los dos bloques, se usa el bloque del perfil activo.

### Detección automática de VRAM

Cuando `vram_profile` es `"auto"` (por defecto), Facet detecta la VRAM de la GPU al arrancar y elige el perfil más grande que quepa:

| VRAM detectada | Perfil seleccionado |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Sin GPU | `legacy` (usa la RAM del sistema) |

Una GPU CUDA solo cuenta cuando PyTorch la ve. Sin ningún dispositivo visible (por ejemplo con `CUDA_VISIBLE_DEVICES=''`), el escaneo usa la CPU, informa de 0 GB de VRAM y selecciona `legacy`. `FACET_DEVICE=cuda` sin dispositivo visible se detiene con «FACET_DEVICE=cuda was requested, but that device is not available».

**Las tarjetas de 10-14GB pueden optar por el conjunto completo de funciones.** La detección automática sigue eligiendo `8gb` por debajo de 14GB. Define `"vram_profile": "16gb"` o `FACET_VRAM_PROFILE=16gb` para ejecutar SigLIP 2, TOPIQ, etiquetado con Qwen3.5-2B, Q-ReAlign y saliencia. Los modelos se ejecutan entonces en cuatro pases, o tres en una tarjeta que informa de 11,8 GiB o más (consulta [Agrupación dinámica de pases](#agrupación-dinámica-de-pases)). Una foto que la saliencia aun así no puede puntuar guarda NULL y registra un ERROR.

> **Advertencia:** Cambiar una biblioteca `8gb` existente a `16gb` cambia el modelo de embeddings (CLIP ViT-L-14 de 768 dimensiones → SigLIP 2 de 1152 dimensiones). Vuelve a escanear o ejecuta `--recompute-embeddings`, o la biblioteca mezclará dos tamaños de embedding. Hasta entonces, la búsqueda se comporta como se describe en *Búsqueda semántica y una biblioteca incrustada con un perfil distinto* en [Modelos](#modelos).

---

### Anulación mediante la variable de entorno `FACET_VRAM_PROFILE`

`FACET_VRAM_PROFILE` anula `models.vram_profile` en el momento de la carga, de modo que una sola configuración montada puede servir a todos los perfiles de Docker. Valores aceptados: `auto`, `legacy`, `8gb`, `16gb`, `24gb`; cualquier otro valor se ignora con una advertencia. Las superposiciones de Docker Compose (`docker-compose.{legacy,8gb,16gb,24gb}.yml`) la definen por ti.

La anulación nunca se reescribe en `scoring_config.json`. Un `vram_profile` que hayas puesto en el archivo sigue aplicándose cuando la variable no está definida.

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

---

## Modelos de evaluación de calidad

Selecciona el modelo que puntúa la calidad/estética de la imagen, a través de la biblioteca [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `model` | `"auto"` | Modelo de calidad: `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` usa `topiq`. |
| `prefer_llm` | `false` | Preferir un puntuador basado en LLM cuando hay uno disponible |

### Modelos de calidad disponibles

SRCC = coeficiente de correlación de rangos de Spearman en el benchmark KonIQ-10k (1,0 = perfecto).

| Modelo | SRCC | VRAM | Notas |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Por defecto (`auto`); backbone ResNet50 con atención descendente |
| `hyperiqa` | 0.90 | ~2GB | Híper-red, adaptativa al contenido |
| `dbcnn` | 0.90 | ~2GB | CNN de doble rama (distorsiones sintéticas + auténticas) |
| `musiq` | 0.87 | ~2GB | Transformer multiescala; admite cualquier resolución |
| `clipiqa+` | 0.86 | ~4GB | CLIP con prompts de calidad aprendidos |
| `clip-mlp` | 0.76 | ~4GB | CLIP ViT-L-14 heredado + cabeza MLP |

### Cambiar de modelo de calidad

1. Edita `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Vuelve a puntuar las fotos existentes (opcional):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Procesamiento

Ajustes de procesamiento por lotes en GPU y del modo multipase.

```json
{
  "processing": {
    "mode": "auto",
    "gpu_batch_size": 16,
    "ram_chunk_size": 32,
    "num_workers": 4,
    "auto_tuning": {
      "enabled": true,
      "monitor_interval_seconds": 5,
      "tuning_interval_images": 32,
      "min_processing_workers": 1,
      "max_processing_workers": 32,
      "min_gpu_batch_size": 2,
      "max_gpu_batch_size": 32,
      "min_ram_chunk_size": 10,
      "max_ram_chunk_size": 128,
      "memory_limit_percent": 85,
      "cpu_target_percent": 85,
      "metrics_print_interval_seconds": 30
    },
    "thumbnails": {
      "photo_size": 640,
      "photo_quality": 80,
      "face_padding_ratio": 0.3
    }
  }
}
```

### Conceptos clave

- **`gpu_batch_size`**: imágenes procesadas juntas en un único paso hacia delante de la GPU. Limitado por la VRAM; el autoajuste lo reduce cuando la memoria de la GPU supera el límite.
- **`ram_chunk_size`**: imágenes mantenidas en RAM entre los pases del modelo (solo multipase), de modo que cada imagen se lee del disco una vez por fragmento. Limitado por `memory_limit_percent`. El autoajuste lo reduce de inmediato cuando la memoria supera el límite, y lo aumenta solo tras un fragmento cuyo uso *máximo* se mantuvo por debajo del límite.

### Referencia de ajustes

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mode` | `"auto"` | Modo de procesamiento: `auto`, `multi-pass`, `single-pass`. Solo `single-pass` selecciona el modo de un solo paso; `auto` siempre ejecuta multipaso |
| `gpu_batch_size` | `16` | Imágenes por lote de GPU (limitado por la VRAM) |
| `ram_chunk_size` | `32` | Imágenes por fragmento de RAM (multipase) |
| `num_workers` | `4` | Hilos de carga de imágenes |
| `load_workers` | `num_workers` | Hilos de carga de fragmentos multipase (limitado a 8, `1` = secuencial) |
| `raw_decode_concurrency` | `0` (auto) | Decodificaciones RAW simultáneas máximas; dimensionado automáticamente según CPU/RAM (1-4), `1` = totalmente serializado |
| `raw_decode_timeout_seconds` | `120` | Abandonar una decodificación RAW colgada tras este retardo (`0` = desactivado); el escaneo falla rápido tras varios bloqueos |
| `exif_prefetch` | `true` | Modo monopase: precarga EXIF en segundo plano en vez de bloquear el hilo de la GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Activar el autoajuste |
| `monitor_interval_seconds` | `5` | Intervalo de comprobación de recursos |
| `tuning_interval_images` | `32` | Reajustar cada N imágenes |
| `min_processing_workers` | `1` | Hilos de carga mínimos |
| `max_processing_workers` | `32` | Hilos de carga máximos |
| `min_gpu_batch_size` | `2` | Tamaño de lote de GPU mínimo |
| `max_gpu_batch_size` | `32` | Tamaño de lote de GPU máximo |
| `min_ram_chunk_size` | `10` | Tamaño de fragmento de RAM mínimo |
| `max_ram_chunk_size` | `128` | Tamaño de fragmento de RAM máximo |
| `memory_limit_percent` | `85` | Porcentaje del límite de memoria efectivo (límite de cgroup bajo un tope de contenedor, si no, RAM del host) |
| `cpu_target_percent` | `85` | Objetivo de uso de CPU |
| `metrics_print_interval_seconds` | `30` | Intervalo de impresión de estadísticas |
| **thumbnails** | | |
| `photo_size` | `640` | Tamaño de la miniatura almacenada (píxeles) |
| `photo_quality` | `80` | Calidad JPEG de la miniatura |
| `face_padding_ratio` | `0.3` | Relleno alrededor de los recortes de rostro |

### Modos de procesamiento

| Modo | Descripción |
|------|-------------|
| `auto` | Siempre ejecuta multipaso (el valor por defecto); solo `single-pass` selecciona un solo paso |
| `multi-pass` | Carga secuencial de modelos (funciona con VRAM limitada) |
| `single-pass` | Todos los modelos cargados a la vez (mucha VRAM); solo perfiles `legacy`/`8gb` |

En `16gb`/`24gb` (estética con TOPIQ), `single-pass` registra una advertencia y ejecuta multipaso, salvo en el modo comercial (ver [Licencias](#licencias)).

### Cómo funciona el modo multipase

En vez de cargar todos los modelos a la vez, el modo multipase:

1. Carga las imágenes en fragmentos de RAM (`ram_chunk_size` por defecto: 32)
2. Para cada fragmento, ejecuta los modelos secuencialmente: cargar modelo → procesar fragmento → descargar modelo
3. Combina los resultados en un pase de agregación final

Cada imagen se decodifica una vez por fragmento y la comparten todos los pases. Los pases se agrupan para caber en la VRAM disponible, de modo que los VLM más grandes se ejecutan incluso en tarjetas pequeñas.

- Los hilos de carga también calculan EXIF, las métricas técnicas, la composición basada en reglas, el hash perceptual y una copia compartida de 1024 px para los modelos pyiqa y Q-ReAlign.
- Un error de composición hace fallar solo esa foto. Se registra en `scan_failures` con la etapa `composition`; reintenta con `--retry-failed`.
- En una GPU CUDA, un fragmento se decodifica mientras se cargan los siguientes modelos, cuando la memoria libre del host lo permite y `keep_in_ram` no es `"never"`. En caso contrario (y siempre en CPU y Apple MPS) se decodifica primero. Los resultados son idénticos en ambos casos.
- Cuando la memoria escasea antes de un fragmento, la caché de RAM libera primero el modelo que se necesitará más tarde y mantiene libre `ram_cache_reserve_gb`.
- El resumen del escaneo informa de `Plane rebuilds`, `I/O wait (scan thread blocked on decode)` y `Decode wall`.

### Comportamiento del autoajuste

Facet monitoriza el uso de recursos y ajusta de la siguiente manera. `memory_limit_percent` se mide contra el límite de memoria *efectivo*: el límite de cgroup bajo un tope de contenedor (`mem_limit` de Docker, `--memory` de Podman, `resources.limits.memory` de Kubernetes), o la RAM del host en caso contrario. Así, `85` sobre un tope de 8GB da unos 6,8GB.

| Métrica | Acción |
|--------|--------|
| Memoria de GPU > límite | Reduce `gpu_batch_size` en un 25 % |
| Uso de memoria > límite | Reduce `ram_chunk_size` en un 25 % (de inmediato) |
| Un fragmento terminado cuyo uso máximo se mantuvo < (límite - 20 %) | Aumenta `ram_chunk_size` en un 25 % |
| CPU > objetivo | Sugiere menos workers |
| Tiempos de espera de cola > 5 % | Sugiere más workers |

### Agrupación dinámica de pases

Cuando la VRAM lo permite, varios modelos se ejecutan en el mismo pase:

| VRAM | Pase 1 | Pase 2 | Pase 3 | Pase 4 |
|---|---|---|---|---|
| 8GB (perfil `8gb`) | CLIP | Q-ReAlign + saliencia | TOPIQ IAA + TOPIQ NR-Face + LIQE | SAMP-Net + InsightFace |
| 12GB\* (perfil `16gb`, opcional) | Etiquetador Qwen3.5 + Q-ReAlign | SigLIP + saliencia + TOPIQ IAA | TOPIQ + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace |
| 16GB (perfil `16gb`) | Etiquetador Qwen3.5 + SigLIP + TOPIQ | Q-ReAlign + saliencia + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace | - |
| 24GB (perfil `24gb`) | Etiquetador Qwen3.5 4B + SigLIP + Q-ReAlign + saliencia | TOPIQ + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace | - | - |
| 35GB+ (perfil `24gb`) | Todos los modelos juntos (monopase) | - | - | - |

Las filas son los planes para tarjetas que informan de 8,0, 11,7, 15,99 y 23,99 GiB de VRAM total; con 34,8 GiB o más se planifica un solo pase. El planificador deja libres 1,3 GiB para CUDA, ONNX Runtime y el escritorio. Una tarjeta de 12GB no se selecciona automáticamente (consulta [Detección automática de VRAM](#detección-automática-de-vram)): define `"vram_profile": "16gb"` o `FACET_VRAM_PROFILE=16gb`.

\* La fila de 12GB es para una tarjeta que informa de 11,7 GiB. Una que informa de 11,8 GiB o más (por ejemplo, 11,99 GiB) planifica en cambio tres pases: etiquetador Qwen3.5 + Q-ReAlign; SigLIP + saliencia + TOPIQ; TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace.

### Opciones de CLI

```bash
# Por defecto: multipase automático con agrupación óptima
python facet.py /path/to/photos

# Forzar monopase (todos los modelos cargados a la vez; solo perfiles legacy/8gb, en 16gb/24gb avisa y ejecuta multipaso)
python facet.py /path --single-pass

# Ejecutar solo un pase concreto
python facet.py /path --pass quality       # Solo TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (mérito estético)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (calidad + distorsión)
python facet.py /path --pass tags          # Solo el etiquetador configurado
python facet.py /path --pass composition   # Solo SAMP-Net
python facet.py /path --pass faces         # Solo InsightFace
python facet.py /path --pass embeddings    # Solo embeddings CLIP/SigLIP
python facet.py /path --pass saliency      # Saliencia del sujeto BiRefNet

# Listar los modelos disponibles
python facet.py --list-models
```

---

## Decodificación RAW

Cómo se convierten los archivos RAW en píxeles. Facet usa dos perfiles:

- **Perfil de métricas**: el demosaicado a partir del cual se calcula cada puntuación (y el espacio de píxeles de los cuadros de rostro y de `image_width`/`image_height`). Una sola ganancia de exposición fija para toda la biblioteca, sin adaptación por toma.
- **Perfil de visualización**: lo que muestran la miniatura almacenada, la galería y `/image`. Prefiere la vista previa incorporada por la cámara (la curva tonal y la exposición propias de la cámara), y recae en el demosaicado del perfil de métricas.

```json
"raw_decode": {
  "bright": 1.62,
  "prefer_embedded_preview": true,
  "preview_min_sensor_ratio": 0.5,
  "viewer_concurrency": 3,
  "faithful_bracket_render": true
}
```

| Ajuste | Predeterminado | Descripción |
|--------|-----------------|-------------|
| `bright` | `1.62` | Ganancia de exposición fija para cada demosaicado (`1.0` = el nivel propio de LibRaw; `1.62` ≈ el +0,7 EV de darktable) |
| `prefer_embedded_preview` | `true` | Muestra la vista previa de la cámara cuando existe una; `false` demosaica todo (más lento, sin la curva tonal de la cámara) |
| `preview_min_sensor_ratio` | `0.5` | Parte del sensor que debe cubrir una vista previa para que `/image` la use en lugar de demosaicar |
| `viewer_concurrency` | `3` | Máximo de demosaicados RAW simultáneos para `/image` y `/thumbnail` del visor, separado de `processing.raw_decode_concurrency` |
| `faithful_bracket_render` | `true` | Muestra las tomas de un horquillado sin corrección (sin vista previa, sin ganancia `bright`); ver [más abajo](#las-tomas-de-un-horquillado-se-representan-sin-corrección) |

Notas:
- `bright` es la única constante arbitraria aquí. Compruébala en tu biblioteca con `--check-raw-rendering` antes de un escaneo grande.
- Nikon, Pentax, Samsung y Canon CR3 incorporan una vista previa casi a tamaño completo (0,98-0,99). Panasonic se sitúa en 0,52. Olympus, Fuji, Sony y DNG incorporan una pequeña (0,29-0,49), así que se demosaican.

### Compromiso de memoria

`viewer_concurrency` y `processing.raw_decode_concurrency` son presupuestos separados. En el peor de los casos ambos se ejecutan a la vez, y cada demosaicado alcanza un pico de unos 200-400 MB. Reduce `viewer_concurrency` en un host con memoria limitada. En la práctica solo los archivos de Sony, Fuji, Olympus y DNG usan el presupuesto del visor, porque los demás tienen una vista previa suficientemente grande.

### Por qué no hay brillo automático

La luminosidad automática de LibRaw se adapta a cada toma, así que un horquillado sale con todas las tomas con aproximadamente el mismo brillo. La ganancia fija conserva la escala real de exposición entre las tomas.

Aumentar `bright` ilumina cada renderizado. Las métricas de exposición se mueven con él: vuelve a ejecutar `--recompute-average` después de cambiarlo, y vuelve a escanear para reescribir las métricas mismas.

### Las tomas de un horquillado se representan sin corrección

Una foto cuyo `sequence_kind` es `bracket` o `hdr_panorama` se muestra sin vista previa de la cámara y sin ganancia `bright`. Ambas recortarían las altas luces que estás juzgando en un horquillado. Un `panorama` corriente no se ve afectado.

Dónde se aplica:
- `/image` (vista de detalle, lupa de comparación, lupa de descarte), renderizado al vuelo.
- Las tarjetas de galería y la cuadrícula de comparación, tras `--refresh-thumbnails`.
- `GET /api/download` con `type=original`.

No se ven afectados: `type=raw` (el RAW sin tocar), `type=darktable` (la exportación de aspecto editado), `GET /api/photo/cull_preview` (renderizado por darktable-cli) y la puntuación.

La detección de secuencias se ejecuta después de un escaneo, así que ejecuta primero `--detect-sequences`, luego `--refresh-thumbnails`, para que las tarjetas lo reflejen.

Pon `faithful_bracket_render` en `false` para renderizar los horquillados como cualquier otra foto.

### Migrar una biblioteca escaneada antes de este perfil

Las miniaturas y los histogramas se guardan en el momento del escaneo, así que cambiar el perfil no modifica las fotos ya escaneadas. `photos.render_version` registra qué renderizado produjo cada miniatura almacenada:

- `NULL`: anterior a la marca
- `1`: primero la vista previa de la cámara, ganancia `bright` sobre el demosaico de respaldo (lo que guarda todo escaneo)
- `2`: sin vista previa y sin ganancia, para un fotograma de horquillado (solo lo guarda `--refresh-thumbnails`)

Solo dos cosas actualizan las miniaturas almacenadas:
- **Un nuevo escaneo** reescribe la miniatura y el histograma, y siempre marca `1`.
- **`--refresh-thumbnails`** reescribe las miniaturas RAW y marca `1` o `2` según el `sequence_kind` actual. Reconstruye todas las filas, así que vuelve a ejecutarlo tras un cambio de `bright` o un paso de `--detect-sequences`.

La vista de detalle (`/image`) siempre está al día; la cuadrícula de la galería solo cambia tras una de las dos anteriores.

La galería muestra un banner descartable que cuenta las fotos que siguen en el renderizado antiguo. Puede ir con hasta una hora de retraso; `python database.py --refresh-stats` lo actualiza de inmediato.

Un renderizado que resulta completamente negro (por ejemplo, un RW2 Panasonic truncado) se rechaza, se registra con el nombre del archivo y se reintenta en una ejecución posterior.

---

## Mapeo de tono HDR PQ

Las fotos fijas Canon HDR PQ (`.HIF`) llevan la función de transferencia PQ (SMPTE ST 2084) sobre primarios BT.2020, hasta 10.000 nits. Los modelos de calidad y las miniaturas necesitan sRGB SDR de 8 bits, así que Facet decodifica una imagen PQ a la profundidad de bits nativa de la cámara, la convierte a sRGB y le aplica el mapeo de tono. Este bloque controla ese mapeo de tono.

Se aplica **solo** a las imágenes cuyo perfil de color NCLX declara la transferencia PQ (característica 16). El HEIF SDR, HLG y JPEG pasan sin cambios, diga lo que diga `enabled`. Los fotogramas girados (orientación EXIF distinta de 1) salen derechos, también por la ruta de profundidad nativa: con pillow-heif 1.6 y posteriores el plano se gira antes del mapeo de tono.

```json
"hdr_pq_tonemap": {
  "enabled": true,
  "method": "hable",
  "white_point": {
    "mode": "percentile",
    "percentile": 99.99,
    "min_nits": 100.0,
    "max_nits": 1200.0,
    "fixed_nits": 1000.0
  },
  "chroma_preserve": "per_channel"
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Mapea por tono las imágenes PQ a SDR; `false` las deja oscuras y deslavazadas (solo para depuración) |
| `method` | `hable` | Curva de tono: `hable` (fílmica, como el filtro `tonemap` de ffmpeg) o `clip` (lineal con recorte duro, solo como referencia) |
| `white_point.mode` | `percentile` | Cómo se elige el punto blanco por imagen: `percentile`, `max` (el píxel más brillante) o `fixed` (`fixed_nits`) |
| `white_point.percentile` | `99.99` | Percentil usado en el modo `percentile` |
| `white_point.min_nits` | `100.0` | Suelo para el punto blanco; un fotograma oscuro nunca se normaliza por debajo del blanco de referencia SDR |
| `white_point.max_nits` | `1200.0` | Techo en el modo `percentile`; limita cuánto un fotograma inusualmente brillante empuja la curva hacia abajo |
| `white_point.fixed_nits` | `1000.0` | Punto blanco usado en el modo `fixed` |
| `chroma_preserve` | `per_channel` | `per_channel` (más brillante, ligero cambio de matiz en los brillos) o `max_channel` (preserva el matiz, algo más oscuro) |

El modo `max` deja que un píxel caliente en una escena nocturna oscurezca todo el fotograma; `percentile` lo evita.

### Por qué el punto blanco es por imagen

Un punto blanco fijo de 100 nits recorta a blanco puro todo lo que sea más brillante, y las fotos HDR reales alcanzan picos de cientos a miles de nits. Facet normaliza en cambio con un punto blanco por imagen, como ffmpeg (`vf_tonemap.c`). El percentil por defecto p99.99, acotado a 100-1200 nits, conserva la textura de los brillos e ignora los píxeles calientes aislados.

### Por qué la decodificación usa la profundidad nativa de la cámara

Decodificar PQ a 8 bits antes del mapeo de tono posteriza los degradados suaves. Facet pide al decodificador HEIF la profundidad propia del archivo (10 bits en las cámaras actuales) y estrecha a 8 bits solo después de la curva de tono. La mejora se nota en el contenido suave (cielos despejados, fondos de estudio, bokeh intenso); los indicadores de recorte y `exposure_score` no cambian en fotos reales. Un decodificador que no pueda dar la profundidad nativa recae en 8 bits.

**Referencias.** EOTF PQ: SMPTE ST 2084:2014. Curva Hable y pico por fotograma:
ffmpeg `vf_tonemap.c` (John Hable, «Filmic Tonemapping Operators», 2010).
Matriz BT.2020 a sRGB: BT.2020-2 / IEC 61966-2-1 con D65. OETF sRGB:
IEC 61966-2-1. Característica de transferencia NCLX 16: ISO/IEC 23001-8 /
ITU-T H.273.

## Detección de ráfagas

Agrupa fotos similares tomadas en rápida sucesión.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `similarity_threshold_percent` | `70` | Umbral de similitud del hash de imagen |
| `time_window_minutes` | `0.8` | Tiempo máximo entre fotos |
| `rapid_burst_seconds` | `0.4` | Fotos dentro de este intervalo se agrupan automáticamente |

---

## Notificaciones de actualización

Avisa a los usuarios en modo edición cuando existe una versión más reciente de Facet. No confundir con el aviso del navegador «Hay una nueva versión disponible — Recargar».

- La versión en ejecución se muestra al pie del menú de usuario para todos los que pueden abrir el visor.
- Una imagen construida con `--build-arg FACET_BUILD=<rama>@<commit>` muestra además esa línea de compilación. `/api/config` devuelve ambas como `version` y `build`, solo a quien puede leer la biblioteca.
- El servidor consulta a GitHub como mucho una vez cada `interval_days`, sin token ni datos de la biblioteca. Una comprobación fallida aparece como «no se conoce ninguna actualización».
- Solo los usuarios en modo edición ven el aviso, como mucho una vez por semana por navegador.

```json
{
  "updates": {
    "enabled": true,
    "check_url": "https://api.github.com/repos/ncoevoet/facet/releases/latest",
    "interval_days": 7
  }
}
```

| Ajuste | Predeterminado | Descripción |
|---|---|---|
| `enabled` | `true` | `false` desactiva la comprobación; no se solicita nada nunca |
| `check_url` | API de GitHub de la última versión | Dónde buscar la versión publicada más reciente |
| `interval_days` | `7` | Cuánto se cachea un resultado antes de volver a preguntar |

---

## Detección de secuencias

Etiqueta los horquillados de exposición para que no se traten como tomas rivales. La exposición de cada fotograma sale de los valores almacenados `f_stop` / `shutter_speed` / `ISO` (`EV = log2(N^2 / t) - log2(ISO / 100)`), así que una biblioteca existente se etiqueta sin volver a escanear.

Una serie es un horquillado cuando sus fotogramas:
- proceden de la misma cámara, cada uno a menos de `max_gap_seconds` del anterior;
- mantienen el mismo encuadre (`max_hamming` sobre el pHash);
- forman una escalera regular de exposiciones distintas, en cualquier orden de captura (empezar por la base `0, -, +` funciona igual que de oscura a clara), que abarca `min_span_stops`, en al menos `min_frames` fotogramas.

Cada fotograma recibe `sequence_ev_offset`, su exposición respecto a la toma base, con el signo de las etiquetas AEB de una cámara (`-2` oscura, `+2` clara). La base es el peldaño central. Con un número par de fotogramas, la base es el fotograma central que recorta menos extremos de su histograma (el más antiguo en caso de empate); una serie impar como `(-2, 0, +2)` usa siempre su fotograma medio. Cuando un grupo de ráfaga es exactamente un horquillado, la galería muestra su fotograma base.

Se ejecuta con `--detect-sequences`; también corre al final de cada escaneo, después de
agrupar las ráfagas.

**Las correcciones manuales también cubren los horquillados.** Marca a mano un horquillado que la detección pasó por alto, desde la galería o el estudio de descarte (*Marcar como bracketing*). Necesita ≥2 fotogramas, cada uno con datos de exposición utilizables y sin dos con la misma exposición. Véase [docs/VIEWER.md — Panorámicas y bracketing de exposición](VIEWER.md#panorámicas-y-bracketing-de-exposición).

```json
{
  "sequence_detection": {
    "enabled": true,
    "max_gap_seconds": 3.0,
    "max_hamming": 10,
    "min_frames": 3,
    "min_step_stops": 0.5,
    "min_span_stops": 1.0,
    "step_tolerance_stops": 0.34
  }
}
```

| Ajuste | Predeterminado | Descripción |
|---|---|---|
| `enabled` | `true` | Desactiva por completo la detección de horquillado |
| `max_gap_seconds` | `3.0` | Intervalo máximo entre dos tomas consecutivas de una serie |
| `max_hamming` | `10` | Distancia pHash admitida entre tomas (mismo encuadre) |
| `min_frames` | `3` | Serie más corta que se considera un horquillado. `2` es opcional — véase la advertencia siguiente |
| `min_step_stops` | `0.5` | Menor paso de EV que cuenta como cambio deliberado |
| `min_span_stops` | `1.0` | Amplitud mínima entre la toma más oscura y la más clara |
| `step_tolerance_stops` | `0.34` | Irregularidad admitida entre pasos (un tercio de paso) |

**Por qué `min_frames` vale `3` por defecto.** Dos fotogramas a un paso de distancia se ven igual tanto si son un horquillado AEB de dos tomas como una corrección rápida de exposición. Con `2`, la mayoría de las series adicionales encontradas en una biblioteca de prueba no eran horquillados. Una pareja también puede ser lo que queda de una serie de tres tomas, y entonces la base (`sequence_ev_offset` `0`) puede caer en el fotograma equivocado mientras `hide_brackets` (activo por defecto) oculta el otro. Pon `2` solo si disparas horquillado AEB de dos tomas y aceptas algunos falsos positivos.

---

## Detección de panorámicas

Etiqueta los fotogramas de origen de una panorámica, que la detección de ráfagas ocultaría como tomas rivales. La detección empareja rasgos SIFT entre miniaturas consecutivas de 640px ya almacenadas; no necesita descodificar el original, ni modelo, ni dependencias nuevas.

- Un barrido avanza de forma constante en una dirección; una ráfaga oscila en torno a un punto. Las panorámicas simples y HDR son tipos distintos, separados por la amplitud de exposición.
- Precisión medida: en torno al 96 % en una biblioteca de prueba. Algunas panorámicas verticales o de pocas posiciones se pierden.
- Puedes corregir en ambos sentidos con la corrección manual por serie.

```json
{
  "panorama_detection": {
    "enabled": true,
    "max_gap_seconds": 30.0,
    "min_frames": 8,
    "min_drift": 0.43,
    "min_inliers": 25,
    "hdr_min_span_stops": 1.5,
    "sift_features": 400
  }
}
```

| Ajuste | Predet. | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Desactivar por completo la detección de panorámicas |
| `max_gap_seconds` | `30.0` | Intervalo máximo entre fotogramas consecutivos de un barrido |
| `min_frames` | `8` | Serie más corta considerada panorámica (el filtro más fuerte; las no panorámicas tenían 6 fotogramas o menos) |
| `min_drift` | `0.43` | Barrido total, en anchos de encuadre, para que una serie cuente |
| `min_inliers` | `25` | Coincidencias RANSAC necesarias para que un par cuente como emparejado |
| `max_step` | `0.9` | Mayor paso aislado, en anchos de encuadre — más allá es un corte de escena |
| `back_tolerance` | `0.02` | Cuánto puede retroceder un paso contra el barrido antes de terminar la serie |
| `max_ortho` | `0.15` | Desvío lateral tolerado en todo el barrido |
| `ortho_ratio` | `0.25` | Margen lateral adicional como fracción del barrido, para no penalizar series largas |
| `step_ortho_abs` | `0.02` | Movimiento lateral tolerado en un solo paso antes de leerse como reencuadre |
| `step_ortho_ratio` | `0.5` | El mismo límite como fracción del tamaño del propio paso |
| `hdr_min_span_stops` | `1.5` | Amplitud de exposición por encima de la cual un barrido es una panorámica HDR |
| `sift_features` | `400` | Rasgos por miniatura; el coste crece con el cuadrado de este valor |
| `match_ratio` | `0.75` | Razón de Lowe que una coincidencia debe superar para conservarse |
| `workers` | `0` | Procesos de trabajo paralelos; `0` elige según el número de núcleos |
| `probe_stride` | `8` | Fotogramas entre los sondeos baratos de series estáticas que omiten las ráfagas corrientes |
| `probe_min_drift` | `0.05` | Movimiento en un sondeo por debajo del cual la serie se descarta por estática |
| `max_run_frames` | `500` | Serie candidata más larga que se mide (acota la memoria, ~220 KB por fotograma y proceso) |

Notas:
- `sift_features` tarda unos 2,3 ms por pareja de fotogramas con 400, y unos 0,12 s con 3000.
- Cambiar un ajuste no hace nada hasta que la detección se vuelve a ejecutar: usa `--detect-panoramas` (o la acción de nueva ejecución del visor), que vuelve a medir toda la biblioteca.
- El paso de panorámicas tras un escaneo, `--recompute-average` o `--recompute-burst` solo vuelve a medir las series que cambiaron. Editar cualquier ajuste salvo `enabled` y `workers` hace que lo vuelva a medir todo.
- Tus correcciones se aplican en la siguiente pasada. Dos pasadas sobre una biblioteca sin cambios encuentran los mismos conjuntos con los mismos números de grupo.

---

## Puntuación de ráfagas

Pesos que usa el descarte de ráfagas para elegir la mejor toma de cada grupo de ráfaga. Los pesos deben sumar 1,0.

```json
{
  "burst_scoring": {
    "weight_aggregate": 0.4,
    "weight_aesthetic": 0.25,
    "weight_sharpness": 0.2,
    "weight_blink": 0.15
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `weight_aggregate` | `0.4` | Peso de la puntuación agregada global |
| `weight_aesthetic` | `0.25` | Peso de la puntuación de calidad estética |
| `weight_sharpness` | `0.2` | Peso de la puntuación de nitidez técnica |
| `weight_blink` | `0.15` | Peso de penalización por parpadeos detectados (mayor = penalización más fuerte) |

---

## Detección de duplicados

Encuentra fotos duplicadas en toda la biblioteca: candidatos de pHash flexible, confirmados por una comprobación de similitud de embeddings.

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `similarity_threshold_percent` | `90` | Filtro pHash estricto (90 % = distancia de Hamming <= 6 de 64 bits); el único criterio cuando a alguna de las fotos le falta un embedding |
| `prefilter_hamming` | `12` | Opcional (ausente en el archivo incluido). Filtro de Hamming flexible para los candidatos cuando ambas fotos tienen embeddings (como mínimo el filtro estricto) |
| `embedding_cosine_threshold` | `0.90` | Opcional (ausente en el archivo incluido). Un candidato solo se fusiona cuando el coseno SigLIP/CLIP >= esto |

- `python facet.py --detect-duplicates` detecta y agrupa duplicados.
- `python facet.py --sweep-dedup-thresholds [labels.json]` evalúa el filtro coseno: con un JSON de etiquetas imprime una tabla de precisión/recall; de lo contrario, la distribución coseno de los candidatos y cuántas coincidencias de pHash estricto rechaza el filtro.

---

## Nivel IQA extendido (opcional)

Puntuadores de calidad adicionales que escriben sus propias columnas; nunca sustituyen a TOPIQ. Se ejecutan durante un escaneo normal. Un fallo de carga o de VRAM se registra y deja la columna en `NULL`; el escaneo continúa.

- `qrealign` tiene como valor por defecto `"auto"`: **activado** para los perfiles `8gb`/`16gb`/`24gb`, **desactivado** para `legacy`/CPU.
- `aesthetic_v25` y `deqa` están **DESACTIVADOS por defecto**.

```json
{
  "iqa_extended": {
    "qrealign": "auto",
    "qrealign_size": "mini",
    "aesthetic_v25": false,
    "deqa": false
  }
}
```

| Ajuste | Por defecto | Valores aceptados | Columna | Descripción |
|---------|---------|-----------------|--------|-------------|
| `qrealign` | `"auto"` | `"auto"` · `true` · `false` | `qrealign_score` | IQA estético Q-ReAlign-Mini 0.8B (Apache-2.0, ~2-3GB de VRAM/RAM, sin pyiqa) |
| `qrealign_size` | `"mini"` | `"mini"` · `"lite"` | - | `mini` (0.8B) o `lite` (4B); también el modelo principal con `licensing.mode: "commercial"` |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (cabeza SigLIP, ~2GB); **obsoleto**, prefiere `qrealign` |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU de 16GB+; de lo contrario se omite y se deja NULL) |

Notas:
- **Ordenación:** cada métrica aparece en el menú de ordenación del visor en cuanto al menos una foto tiene puntuación (**Q-ReAlign (estética)**, **Estética v2.5**, **DeQA**). Las fotos sin puntuar quedan al final.
- `qrealign_score` contiene la tarea estética; la calidad usa `quality_score`.
- `aesthetic_v25` necesita el paquete `aesthetic-predictor-v2-5`. Tiene licencia AGPL-3.0 y no recibe mantenimiento upstream desde el 2024-12-18.

**Instala las dependencias opcionales** de lo que actives: `pip install -e .[iqa-extended]` (añade `aesthetic-predictor-v2-5`), o descomenta la línea correspondiente en `requirements.txt`. DeQA-Score se descarga a través de `transformers`.

Cada métrica está disponible para el agregado ponderado con peso 0, así que `--recompute-average` no cambia nada hasta que le des un peso. `python facet.py --eval-iqa-srcc` mide lo bien que cada métrica coincide con tus propias valoraciones por estrellas.

**Visualización en el visor.** Los valores presentes se muestran en el panel de **Calidad** del detalle de la foto (`Q-ReAlign`, `Aesthetic V2.5`, `DeQA`), con controles deslizantes de rango bajo **Calidad extendida** en los filtros de la galería (`min_qrealign`/`max_qrealign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`).

> **Advertencia:** Las fotos escaneadas antes de activar una métrica tienen `NULL` en ella, y cualquier mínimo o máximo en su deslizador las oculta. Vuelve a escanear antes de filtrar por una métrica recién activada.

**Robustez.** DeQA-Score ejecuta código de modelo remoto (`trust_remote_code`). Si falla con una imagen (cambio de firma, salida extraña, OOM), el `deqa_score` de esa imagen se queda en `NULL` y el escaneo continúa.

---

## Licencias

Controla qué componentes de modelos puede cargar Facet. Consulte [THIRD_PARTY_MODELS.md](THIRD_PARTY_MODELS.md) para la tabla de licencias por componente.

```json
{
  "licensing": {
    "mode": "default",
    "allow_unclear": false
  }
}
```

| Ajuste | Defecto | Valores aceptados | Descripción |
|---------|---------|-------------------|-------------|
| `mode` | `"default"` | `"default"` · `"commercial"` | `"default"` carga todos los modelos; `"commercial"` carga solo componentes aptos para uso comercial |
| `allow_unclear` | `false` | `true` / `false` | En modo comercial, permite además los componentes con licencia *poco clara* (SAMP-Net, U2-Net-P, la cabeza estética CLIP-MLP de LAION); debe ser un booleano JSON |

En modo `"commercial"`:
- `pyiqa` (TOPIQ, HyperIQA, LIQE, ...) e InsightFace nunca se importan ni se descargan.
- La estética y la calidad provienen de Q-ReAlign, la composición del analizador basado en reglas.
- Los rostros usan detección YuNet, embeddings SFace de 128 dimensiones y, opcionalmente, MediaPipe para ojos/sonrisa y calidad facial OFIQ.
- `liqe` y `aesthetic_iaa` quedan en `NULL`. `deqa` (licencia *poco clara*) necesita `allow_unclear`. `aesthetic_v25` (AGPL) no está disponible nunca.
- Un componente rechazado detiene el escaneo al arrancar con un `LicenceError` que nombra el componente y su reemplazo.
- `--score-topiq`, `--recompute-iqa` (modelos pyiqa) y `--recompute-composition-gpu` terminan con ese mensaje.
- Los componentes con licencia no comercial siguen rechazados incluso con `allow_unclear`.

Nada de esto es asesoramiento legal.

Anulaciones por variable de entorno (solo pueden endurecer; un valor no válido detiene el arranque):

| Variable | Efecto |
|----------|--------|
| `FACET_LICENSING_MODE` | `commercial` fuerza el modo comercial; `default` o vacío = sin anulación |
| `FACET_LICENSING_ALLOW_UNCLEAR` | `0`, `false`, `no`, `off` fuerzan `allow_unclear` a desactivado; `1`, `true`, `yes`, `on` o vacío = sin anulación |

El visor pasa `FACET_LICENSING_MODE=commercial` y, cuando su política prohíbe los componentes poco claros, `FACET_LICENSING_ALLOW_UNCLEAR=0` a cada proceso `facet.py` que lanza. Una cadena como `"false"` para `licensing.allow_unclear` se rechaza al arrancar.

---

## Detección de rostros

Ajustes de detección de rostros de InsightFace.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false,
    "eyes_closed_max": 4.0,
    "poor_expression_min": 4.0,
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confianza de detección mínima (solo InsightFace) |
| `min_face_size` | `20` | Tamaño mínimo del rostro en píxeles (solo InsightFace) |
| `blink_ear_threshold` | `0.28` | Relación de aspecto del ojo (EAR) para la detección de parpadeos |
| `min_faces_for_group` | `4` | Rostros mínimos para clasificar como retrato de grupo (recalculado con `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Opcional (ausente en el archivo incluido). Carga `landmark_3d_68` de InsightFace para la pose de la cabeza (yaw/pitch/roll); ~5MB, solo informativo |
| `eyes_closed_max` | `4.0` | Puntuación de ojos abiertos (0–10) igual o inferior a la cual el estudio de descarte marca un parpadeo (anillos de cara, control deslizante de ojos) |
| `poor_expression_min` | `4.0` | Puntuación de sonrisa/expresión (0–10) por debajo de la cual el estudio marca una expresión débil |
| `blendshapes.enabled` | `true` | Usa los blendshapes de MediaPipe para `eyes_open_score` / `smile_score` cuando está instalado; si no, la geometría de puntos de referencia |
| `blendshapes.min_crop_size` | `192` | Las caras cuyo recorte con relleno sea menor que esto (px, lado más corto) usan la puntuación geométrica |
| `blendshapes.blink_pose_gate_deg` | `null` | Solo modo comercial (MediaPipe): umbral de pose de la cabeza en grados; `null` = desactivado |

Notas:
- El detector YuNet del modo comercial usa valores fijos (0,7 de confianza, 30 px) e ignora `min_confidence_percent` y `min_face_size`.
- MediaPipe necesita el paquete `face_landmarker.task`. Instálalo con `pip install mediapipe==0.10.35 --no-deps`, nunca con un simple `pip install mediapipe`. Ver [FACE_RECOGNITION.md](FACE_RECOGNITION.md#señales-de-expresión-por-rostro-ojos-abiertos--sonrisa).
- `blink_pose_gate_deg`: una cara cuyo |yaw| o |pitch| lo supere no recibe veredicto de parpadeo ni puntuación de ojos abiertos / sonrisa (NULL), porque una cabeza girada parece tener los ojos cerrados. Ningún umbral entre 20° y 45° mejoró la detección de parpadeos en una biblioteca de prueba, así que se incluye desactivado. Debe ser un número positivo; se aplica a las fotos recién escaneadas (`is_blink` cambia al volver a escanear).

---

## Agrupación de rostros

Agrupación HDBSCAN para el reconocimiento de rostros.

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Activar la agrupación de rostros |
| `min_faces_per_person` | `2` | Fotos mínimas por persona |
| `min_samples` | `2` | Parámetro min_samples de HDBSCAN |
| `clustering_algorithm` | `"best"` | Algoritmo de HDBSCAN |
| `leaf_size` | `40` | Tamaño de hoja del árbol (solo CPU) |
| `use_gpu` | `"auto"` | Modo GPU: `auto`, `always`, `never` |
| `thresholds_by_model` | ver JSON | Por modelo de reconocimiento: `auto_merge_distance_percent` y `merge_threshold`. Valores por defecto: ArcFace `15` / `0.6`, SFace `27.5` / `0.65` |

`merge_threshold` (similitud de centroides para la coincidencia) y `auto_merge_distance_percent` (distancia de fusión automática) se leen de `thresholds_by_model` para el modelo de reconocimiento **activo** (ArcFace por defecto, SFace en modo comercial). Un modelo sin entrada es un error. Las mismas claves colocadas directamente bajo `face_clustering` ya no se leen.

**Notas sobre la agrupación en GPU (`use_gpu`):**

- Requiere los paquetes opcionales `cuml` + `cupy`. La imagen Docker de GPU incluye cuML.
- El perfil `legacy` siempre agrupa en CPU, diga lo que diga `use_gpu`.
- Sin un dispositivo CUDA utilizable, la agrupación recurre a HDBSCAN en CPU.
- `always` avisa y usa la CPU si falta cuML; un error de GPU durante la agrupación también recurre a la CPU.

**Algoritmos de agrupación:**

| Algoritmo | Complejidad | Mejor para |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Datos de alta dimensión (recomendado) |
| `boruvka_kdtree` | O(n log n) | Datos de baja dimensión |
| `prims_balltree` | O(n²) | Memoria limitada, alta dimensión |
| `prims_kdtree` | O(n²) | Memoria limitada, baja dimensión |
| `best` | Auto | Dejar que HDBSCAN decida |

---

## Procesamiento de rostros

Controla la extracción de rostros y la generación de miniaturas.

```json
{
  "face_processing": {
    "crop_padding": 0.3,
    "use_db_thumbnails": true,
    "face_thumbnail_size": 640,
    "face_thumbnail_quality": 90,
    "extract_workers": 2,
    "extract_batch_size": 16,
    "refill_workers": 4,
    "refill_batch_size": 100,
    "auto_tuning": {
      "enabled": true,
      "memory_limit_percent": 80,
      "min_batch_size": 8,
      "monitor_interval_seconds": 5
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `crop_padding` | `0.3` | Relación de relleno para los recortes de rostro |
| `use_db_thumbnails` | `true` | Usar las miniaturas almacenadas |
| `face_thumbnail_size` | `640` | Tamaño de la miniatura en píxeles |
| `face_thumbnail_quality` | `90` | Calidad JPEG |
| `extract_workers` | `2` | Workers de extracción en paralelo |
| `extract_batch_size` | `16` | Tamaño del lote de extracción |
| `refill_workers` | `4` | Workers de rellenado de miniaturas |
| `refill_batch_size` | `100` | Tamaño del lote de rellenado |
| **auto_tuning** | | |
| `enabled` | `true` | Activar el ajuste basado en memoria |
| `memory_limit_percent` | `80` | Porcentaje del límite de memoria efectivo (límite de cgroup bajo un tope de contenedor, si no, RAM del host) |
| `min_batch_size` | `8` | Tamaño de lote mínimo |
| `monitor_interval_seconds` | `5` | Intervalo de comprobación |

---

## Detección de monocromo

Detección de fotos en blanco y negro.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `saturation_threshold_percent` | `5` | Saturación media < 5 % = monocromo |

---

## Etiquetado

Ajustes generales de etiquetado. El modelo de etiquetado se configura por perfil en `models.profiles.*.tagging_model`.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Activar el etiquetado |
| `max_tags` | `5` | Máximo de etiquetas por foto |

**Nota:** El umbral de etiquetas de CLIP/SigLIP es `tag_threshold_percent` en el bloque del perfil activo: `models.clip` para `16gb`/`24gb`, `models.clip_legacy` para `legacy`/`8gb`. La antigua clave `similarity_threshold_percent` ya no se lee. Si la habías personalizado, copia el valor a `tag_threshold_percent`; la carga de la configuración y `python facet.py --doctor` señalan la clave antigua.

Al final de un escaneo, el paso de etiquetado se omite (con una línea de registro) cuando `enabled` es `false` o ninguna foto tiene a la vez un embedding y una lista de etiquetas vacía. Las fotos que ninguna etiqueta llega a coincidir siguen pendientes, así que el modelo se carga igualmente en cada escaneo. `python tag_existing.py` (con o sin `--force`) y `python facet.py --tag-untagged` siempre se ejecutan.

### Modelos de etiquetado disponibles

Configurado a través de `models.profiles.*.tagging_model`:

| Modelo | VRAM | Estilo de etiqueta | Notas |
|-------|------|-----------|-------|
| `clip` | 0 (reutiliza embeddings) | Ambiente/atmósfera (dramatic, golden_hour, vintage) | Sin carga de modelo adicional; menos detección literal de objetos |
| `qwen3.5-2b` | ~4GB | Escenas estructuradas (landscape, architecture, reflection) | Requiere transformers + VRAM adicional |
| `qwen3.5-4b` | ~8GB | Escenas detalladas con matices | Mayor VRAM; inferencia más lenta |

### Modelos de etiquetado por defecto por perfil

| Perfil | Modelo de etiquetado | Modelo de embedding |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Reetiquetar fotos

```bash
python facet.py --recompute-tags       # Reetiquetar usando el modelo configurado por perfil
python facet.py --recompute-tags-vlm   # Reetiquetar usando el etiquetador VLM
```

---

## Etiquetas independientes

Etiquetas con listas de sinónimos que no están vinculadas a ninguna categoría concreta. Están disponibles para todas las fotos independientemente de la asignación de categoría. Cada clave es el nombre de la etiqueta; el valor es una lista de sinónimos para la coincidencia CLIP/VLM.

```json
{
  "standalone_tags": {
    "bokeh": ["bokeh", "shallow depth of field", "background blur", "out of focus"],
    "surreal": ["surreal", "dreamlike", "fantasy", "composite", "double exposure"],
    "flat_lay": ["flat lay", "overhead shot", "top down", "bird's eye product"],
    "golden_hour": ["golden hour", "magic hour", "warm light", "sunset light"],
    "portrait_tag": ["portrait", "headshot", "face portrait", "close-up portrait"]
  }
}
```

Añade nuevas etiquetas independientes proporcionando una clave y una lista de sinónimos. Las etiquetas definidas aquí se combinan con las etiquetas específicas de categoría para formar el vocabulario de etiquetas completo.

---

## Análisis

Umbrales para `--compute-recommendations`.

```json
{
  "analysis": {
    "aesthetic_max_threshold": 9.0,
    "aesthetic_target": 9.5,
    "quality_avg_threshold": 7.5,
    "quality_weight_threshold_percent": 10,
    "correlation_dominant_threshold": 0.5,
    "category_min_samples": 50,
    "category_imbalance_threshold": 0.5,
    "score_clustering_std_threshold": 1.0,
    "top_score_threshold": 8.5,
    "exposure_avg_threshold": 8.0
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `aesthetic_max_threshold` | `9.0` | Advertir si la estética máxima está por debajo de esto |
| `aesthetic_target` | `9.5` | Objetivo para aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Umbral de calidad de "alto valor" |
| `quality_weight_threshold_percent` | `10` | Advertir si el peso de calidad ≤ esto |
| `correlation_dominant_threshold` | `0.5` | Advertencia de "señal dominante" |
| `category_min_samples` | `50` | Fotos mínimas por categoría |
| `category_imbalance_threshold` | `0.5` | Advertencia de brecha de puntuación |
| `score_clustering_std_threshold` | `1.0` | Advertir si la desviación estándar < esto |
| `top_score_threshold` | `8.5` | Advertir si el agregado máximo < esto |
| `exposure_avg_threshold` | `8.0` | Advertir si la exposición media > esto |

---

## Visor

Visualización y comportamiento de la galería web.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "learning",
      "candidate_pool_size": 200,
      "show_current_scores": true
    },
    "sort_options": { ... },
    "pagination": {
      "default_per_page": 64
    },
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    },
    "persons": {
      "needs_naming_min_faces": 5
    },
    "raw_processor": {
      "backend": "rawpy",
      "darktable": {
        "executable": "darktable-cli",
        "hq": true,
        "width": null,
        "height": null,
        "extra_args": [],
        "cull_styles": [],
        "preview_max_edge": 1440,
        "preview_timeout_seconds": 60
      }
    },
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96,
      "thumbnail_slider": {
        "min_px": 120,
        "max_px": 400,
        "default_px": 168,
        "step_px": 8
      }
    },
    "face_thumbnails": {
      "output_size_px": 64,
      "jpeg_quality": 80,
      "crop_padding_ratio": 0.2,
      "min_crop_size_px": 20
    },
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    },
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      },
      "low_light_max_luminance": 0.2
    },
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "tooltip_mode": "panel",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 3600,
    "notification_duration_ms": 2000,
    "moment_confidence_min": 0,
    "path_mapping": {}
  }
}
```

> **Nota:** `sort_options` (omitido como `{ ... }` arriba) asigna columnas de la BD a etiquetas de menú desplegable y rara vez se edita. El grupo **Content** incluye una ordenación `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (los NULL se hunden al final).

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `default_category` | `""` | Filtro de categoría por defecto |
| `edition_password` | `""` | Contraseña para desbloquear el modo edición; vacío = solo lectura (salvo bajo `trusted_local_editing`) |
| `trusted_local_editing` | `false` | Concede derechos de edición, sin contraseña, a un navegador del mismo equipo. Consulta [Edición local de confianza](#edición-local-de-confianza) |
| `place_search_url` | `"https://photon.komoot.io/api"` | Endpoint de Photon para la búsqueda **Buscar en línea** de la galería; `""` la desactiva. Véase [Búsqueda de lugares en línea](#búsqueda-de-lugares-en-línea) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Comparaciones decisivas (sin contar empates) necesarias en una categoría antes de sugerir pesos |
| `pair_selection_strategy` | `"learning"` | Estrategia de pares: `learning`, `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Conjunto de candidatos aleatorio dentro del cual la estrategia `learning` muestrea pares |
| `show_current_scores` | `true` | Mostrar puntuaciones durante la comparación |
| **pagination** | | |
| `default_per_page` | `64` | Fotos por página |
| **dropdowns** | | |
| `max_cameras` | `50` | Máximo de cámaras en el desplegable |
| `max_lenses` | `50` | Máximo de objetivos |
| `max_persons` | `50` | Máximo de personas |
| `max_tags` | `20` | Máximo de etiquetas |
| `min_photos_for_person` | `10` | Ocultar del desplegable a las personas con menos fotos |
| **persons** | | |
| `needs_naming_min_faces` | `5` | Rostros mínimos para que un grupo aparezca en «Necesita nombre» de `/persons`; `1` lista todas las personas sin nombre |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nombre del binario darktable-cli o ruta absoluta |
| `darktable.profiles` | `[]` | Array de perfiles de exportación darktable con nombre (ver abajo) |
| `darktable.profiles[].name` | *(obligatorio)* | Nombre del perfil mostrado (usado en el menú de descarga y el parámetro `profile` de la API) |
| `darktable.profiles[].hq` | `true` | Pasa `--hq true` para exportación de alta calidad |
| `darktable.profiles[].width` | *(omitir)* | Ancho de salida máximo (omitir para resolución completa) |
| `darktable.profiles[].height` | *(omitir)* | Alto de salida máximo (omitir para resolución completa) |
| `darktable.profiles[].style` | *(omitir)* | Nombre del estilo darktable aplicado durante la exportación (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | `false` pasa `--apply-custom-presets false`, de modo que solo se aplica el `style` explícito |
| `darktable.profiles[].extra_args` | `[]` | Argumentos de CLI adicionales (p. ej., `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | Estilos de darktable ofrecidos como vista previa de aspecto editado en el estudio de descarte; vacío oculta el selector |
| `darktable.cull_styles[].name` | *(obligatorio)* | Nombre del estilo de darktable (pasado a `--style`) |
| `darktable.cull_styles[].label_key` | *(name)* | Clave i18n opcional para la etiqueta del menú (por defecto, el nombre del estilo) |
| `darktable.preview_max_edge` | `1440` | Borde máximo (px) del render de la vista previa de descarte |
| `darktable.preview_timeout_seconds` | `60` | Tiempo de espera de darktable-cli por render de vista previa |
| **display** | | |
| `tags_per_photo` | `4` | Etiquetas mostradas en las tarjetas |
| `card_width_px` | `168` | Ancho de la tarjeta |
| `image_width_px` | `160` | Ancho de la imagen |
| `image_jpeg_quality` | `96` | Calidad JPEG para la conversión RAW/HEIF en `/api/download` y `/api/image` (1-100) |
| `thumbnail_slider.min_px` | `120` | Tamaño mínimo de miniatura (px) |
| `thumbnail_slider.max_px` | `400` | Tamaño máximo de miniatura (px) |
| `thumbnail_slider.default_px` | `168` | Tamaño de miniatura por defecto (px) |
| `thumbnail_slider.step_px` | `8` | Incremento del paso del control deslizante (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Tamaño de la miniatura |
| `jpeg_quality` | `80` | Calidad JPEG |
| `crop_padding_ratio` | `0.2` | Relleno del rostro |
| `min_crop_size_px` | `20` | Tamaño mínimo de recorte |
| **quality_thresholds** | | |
| `good` | `6` | Umbral de bueno |
| `great` | `7` | Umbral de muy bueno |
| `excellent` | `8` | Umbral de excelente |
| `best` | `9` | Umbral de mejor |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Mínimo de Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Relación de rostro para los pesos |
| `low_light_max_luminance` | `0.2` | Umbral de poca luz |
| **defaults** | | |
| `type` | `""` | Filtro de tipo de foto por defecto (p. ej., `"portraits"`, `"landscapes"` o `""` para Todas) |
| `sort` | `"aggregate"` | Columna de ordenación por defecto (prevalece la ordenación que recuerde el navegador; ver [Ordenación](VIEWER.md#ordenación)) |
| `sort_direction` | `"DESC"` | Dirección de ordenación por defecto (`"ASC"` o `"DESC"`) |
| `hide_blinks` | `true` | Ocultar fotos con parpadeo por defecto |
| `hide_bursts` | `true` | Mostrar solo la mejor de la ráfaga por defecto |
| `hide_duplicates` | `true` | Ocultar las fotos duplicadas no principales por defecto |
| `hide_brackets` | `true` | Mostrar solo la exposición base de cada horquillado por defecto |
| `hide_panoramas` | `true` | Mostrar solo un fotograma representativo por panorámica por defecto |
| `hide_details` | `true` | Ocultar los detalles de la foto en las tarjetas por defecto |
| `tooltip_mode` | `"panel"` | Activación del tooltip: `"hover"`, `"click"`, `"off"` o `"panel"` (panel acoplado); sustituye a `hide_tooltip` |
| `panel_activation` | `"both"` | Gesto que cambia la foto del panel acoplado en modo `"panel"`: `"hover"`, `"click"` o `"both"` |
| `hide_rejected` | `true` | Ocultar las fotos rechazadas por defecto |
| `gallery_mode` | `"mosaic"` | Disposición de la galería por defecto (`"grid"` o `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Orígenes permitidos por CORS; añade tu dominio o la URL del proxy inverso al alojar de forma remota |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(valor por defecto seguro para SPA)_ | Cabecera Content-Security-Policy; `""` la desactiva, o proporciona una política más estricta |
| `security_headers.hsts` | `false` | Enviar `Strict-Transport-Security`. Actívalo solo cuando el visor se sirve por HTTPS. |
| **Otros** | | |
| `cache_ttl_seconds` | `3600` | TTL de las cachés en memoria de estadísticas/consultas; manténlo más largo que un cálculo de estadísticas completo (puede tardar minutos) |
| `notification_duration_ms` | `2000` | Duración del aviso emergente |
| `moment_confidence_min` | `0` | Las etiquetas de momento por debajo de esta confianza (0-1) se muestran atenuadas con «(incierto)»; `0` = nunca atenuar |

Notas:
- **`trusted_local_editing`** solo se aplica mientras `password` y `edition_password` estén vacías en una instalación de un solo usuario. Cubre todas las rutas sujetas a edición, incluidos los escaneos, y permite que el cuadro Conectar cree un token de asistente de edición completa para las peticiones `/mcp` del mismo equipo.

> **Advertencia:** Nunca actives `trusted_local_editing` detrás de un proxy inverso en el mismo equipo.

- **`pair_selection_strategy`:** `learning` elige al principio pares diversos y después pares que el modelo clasifica de forma incoherente.
- **`darktable.cull_styles`** alimenta `GET /api/photo/cull_preview`. Cada estilo **debe existir ya** en la configuración de darktable del usuario que ejecuta el visor.
- La Content-Security-Policy por defecto permite los recursos propios de la SPA: script/estilo de tema en línea, Google Fonts, teselas de OpenStreetMap y la API del mismo origen.
- `moment_confidence_min` atenúa las etiquetas en la cabecera de Escenas, la cabecera de grupo de escena del Descarte y el tooltip de la galería.

### Insignias de tarjeta y recorte

`viewer.badges` activa o desactiva cada insignia de la tarjeta de galería. Las insignias anteriores valen `true` por defecto, así que omitir el bloque no cambia nada.

```json
{
  "viewer": {
    "badges": {
      "favorite": true,
      "star_rating": true,
      "rejected": true,
      "sequence_kind": true,
      "sequence_override_pending": true,
      "stack": true,
      "keeper_hint": true,
      "best_of_burst": true,
      "clipping_highlight": true,
      "clipping_shadow": false
    },
    "clipping": {
      "badge_percent": 5,
      "indicator_percent": 1,
      "histogram_mode": "rgb",
      "tooltip_histogram_mode": "luma"
    }
  }
}
```

| Clave | Predeterminado | Descripción |
|-------|----------------|-------------|
| `badges.favorite` | `true` | Insignia de corazón en una foto favorita (modo edición) |
| `badges.star_rating` | `true` | Insignia de estrella y contador en una foto valorada (modo edición) |
| `badges.rejected` | `true` | Insignia de pulgar abajo en una foto rechazada (modo edición) |
| `badges.sequence_kind` | `true` | Insignia del conjunto (ráfaga/horquillado/panorama/duplicado), visible mientras el interruptor de ocultación correspondiente contrae el conjunto |
| `badges.sequence_override_pending` | `true` | Insignia de reloj para una corrección de panorama pendiente de la próxima detección |
| `badges.stack` | `true` | Insignia de capas con el número de miembros en las tarjetas de una pila de fotos manual; al pulsarla abre la pila |
| `badges.keeper_hint` | `true` | Flecha «existe una toma mejor en este grupo» del modelo de selección aprendido |
| `badges.best_of_burst` | `true` | Insignia «Mejor» en la foto principal de una ráfaga, visible solo con `hide_bursts` desactivado |
| `badges.clipping_highlight` | `true` | Marca una foto cuyas altas luces superan `clipping.badge_percent` |
| `badges.clipping_shadow` | `false` | Lo mismo para sombras empastadas (desactivada: suele ser intencionado en siluetas, noche y clave baja) |

Desactivar `badges.stack` solo oculta la insignia; el botón de tarjeta «Abrir pila de fotos» sigue funcionando.

`viewer.clipping` define «recortado» una sola vez para la insignia de la tarjeta, los marcadores del histograma y el filtro de la galería.

| Clave | Predeterminado | Descripción |
|-------|----------------|-------------|
| `badge_percent` | `5` | Porcentaje de píxeles, en el peor canal R/G/B, por encima del cual se marca la tarjeta (aproximadamente 1 foto de cada 25 en una muestra) |
| `indicator_percent` | `1` | Umbral de los propios marcadores R/G/B de los extremos del histograma |
| `histogram_mode` | `"rgb"` | Valor predeterminado del histograma del **panel de detalle**: `"luma"`, `"rgb"`, `"r"`, `"g"` o `"b"` |
| `tooltip_histogram_mode` | `"luma"` | Valor predeterminado de la pestaña Histograma del **panel lateral** (`tooltip_mode: "panel"`), los mismos cinco valores |

Notas:
- La elección de histograma de cada usuario se guarda en `localStorage` (`facet_histogram_mode`, `facet_histogram_mode_tooltip`) y prevalece sobre estos valores. Los dos ajustes son independientes.
- Las burbujas **Hover** y **Clic** no muestran histograma.

**El recorte se mide por canal, exactamente en los bins 0 y 255.** Se almacena en `photos.channel_clip_shadow_pct` / `channel_clip_highlight_pct` como el porcentaje de píxeles del peor canal. Es distinto de los indicadores `shadow_clipped` / `highlight_clipped`, que cubren las bandas de luminancia 0–30 y 225–255 y alimentan `exposure_score`.

**`NULL` significa desconocido, nunca limpio.** Una foto con un histograma almacenado anterior no tiene datos de canal, así que no lleva insignia y no coincide con ningún lado del filtro de la galería. `python facet.py --backfill-clipping` rellena las columnas a partir de los histogramas almacenados; no descodifica imágenes y es reanudable.

### Funciones

Activa o desactiva funciones opcionales para reducir el uso de memoria o simplificar la UI:

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
      "show_memories": true,
      "show_captions": true,
      "show_timeline": true,
      "show_map": true,
      "show_scenes": true,
      "show_my_taste": true
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `show_similar_button` | `true` | Mostrar el botón "Buscar similares" en las tarjetas de foto (usa numpy para la similitud CLIP) |
| `show_merge_suggestions` | `true` | Activar la función de sugerencias de fusión en la página de gestión de personas |
| `show_rating_controls` | `true` | Mostrar los controles de valoración por estrellas y favoritos |
| `show_scan_button` | `false` | Mostrar el botón de iniciar escaneo (no requiere GPU; ver notas) |
| `metrics_enabled` | `false` | Activar el endpoint público de Prometheus `GET /metrics` (ver advertencia más abajo) |
| `show_semantic_search` | `true` | Mostrar la barra de búsqueda semántica (búsqueda de texto a imagen usando embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Mostrar la función de álbumes (crear, gestionar y explorar álbumes de fotos) |
| `show_critique` | `true` | Mostrar el botón de crítica de IA en las tarjetas de foto (desglose de puntuación basado en reglas) |
| `show_vlm_critique` | `true` | Activar la crítica con VLM (perfil 16gb/24gb); `false` cuando falta la clave |
| `show_embed_metadata` | `true` | Mostrar «Escribir metadatos en el archivo» en modo edición (incrusta valoraciones/palabras clave mediante exiftool) |
| `show_memories` | `true` | Mostrar el diálogo de recuerdos "Un día como hoy" (fotos tomadas en la misma fecha en años anteriores) |
| `show_captions` | `true` | Mostrar las descripciones generadas por IA en las tarjetas de foto |
| `show_timeline` | `true` | Mostrar la vista de línea de tiempo para la exploración cronológica con navegación por fechas |
| `show_map` | `true` | Mostrar la vista de mapa GPS (requiere Leaflet); `false` cuando falta la clave |
| `show_capsules` | `true` | Mostrar la vista de Cápsulas (diaporamas de fotos curados agrupados por tema) |
| `show_folders` | `true` | Mostrar la exploración basada en carpetas de la estructura de directorios de fotos |
| `show_scenes` | `true` | Mostrar la vista de Escenas (`/scenes`), con las fotos principales de ráfaga agrupadas en escenas cronológicas |
| `show_my_taste` | `true` | Mostrar la ordenación «Mi gusto» del clasificador personal, con una insignia de confianza |
| `show_social_export` | `true` | Muestra el menú de descarga **Recorte social** (solo edición). Consulta [Exportación social](#exportación-social) |
| `show_portfolio_export` | `true` | Muestra la acción de álbum **Exportar portafolio** (solo edición). Consulta [Exportación de portafolio](#exportación-de-portafolio) |
| `show_proofing` | `false` | Activar la revisión de cliente en los álbumes compartidos. Consulta [Revisión del cliente](#revisión-del-cliente) |

Notas:
- **`show_scan_button`:** visible para el superadmin en modo multiusuario, o para una sesión de edición desbloqueada en modo de un solo usuario. Los escaneos se ejecutan solo en CPU con el perfil `legacy`. Una sesión local de confianza (`trusted_local_editing`) puede escanear sin él.
- **Optimización de memoria:** `show_similar_button: false` evita que se cargue numpy, lo que reduce la memoria del visor.

> **Advertencia:** `metrics_enabled` expone recuentos de fotos/personas/rostros, el tamaño de la BD y la memoria del proceso. Actívalo solo donde la red del scraper pueda alcanzarlo, nunca en internet público.

### Revisión del cliente

`viewer.features.show_proofing` (predeterminado `false`) convierte cualquier álbum compartido en una página de revisión de cliente. Un cliente con el enlace de compartir (y el `viewer.proofing.pin` opcional) puede marcar fotos con un corazón y dejar comentarios sin cuenta. El propietario los revisa desde un diálogo restringido a edición en la tarjeta del álbum. Las selecciones del cliente nunca tocan las valoraciones del propietario ni entrenan al clasificador personal.

```json
{
  "viewer": {
    "features": { "show_proofing": false },
    "proofing": {
      "pin": "",
      "session_minutes": 1440
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `features.show_proofing` | `false` | Interruptor principal de la revisión de cliente en los álbumes compartidos |
| `proofing.pin` | `""` | PIN opcional que un cliente debe introducir con el enlace de compartir; vacío = sin PIN (los intentos tienen límite de frecuencia) |
| `proofing.session_minutes` | `1440` | Duración de la sesión del cliente en minutos (24 h); termina de inmediato si se deja de compartir el álbum o se desactiva la revisión |

### Mapeo de rutas

Asigna las rutas de la base de datos a rutas locales, para cuando las fotos se puntuaron en una máquina (p. ej., Windows con rutas UNC) y el visor se ejecuta en otra (p. ej., un NAS Linux).

```json
{
  "viewer": {
    "path_mapping": {
      "\\\\NAS\\Photos": "/mnt/photos",
      "D:\\Pictures": "/volume1/pictures"
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `path_mapping` | `{}` | Prefijo de origen → prefijo de destino, aplicado al leer archivos del disco |

**Cómo funciona:**
- Se aplica solo al **leer archivos del disco** (imágenes a tamaño completo, descargas, crítica VLM). Las rutas de la base de datos nunca se modifican.
- Se normalizan las barras invertidas y normales: `\\NAS\Photos\img.jpg` y `//NAS/Photos/img.jpg` coinciden ambas.
- Los mapeos se evalúan en orden; gana el primer prefijo coincidente.
- Los destinos del mapeo se añaden automáticamente a la lista de directorios permitidos del modo multiusuario.

**Ejemplo:** Una base de datos poblada en Windows almacena rutas como `\\NAS\Photos\2024\IMG_001.jpg`. En Linux, el mismo recurso compartido está montado en `/mnt/nas/Photos`. Configura:

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Protección por contraseña

Protección por contraseña opcional para el visor:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Cuando se establece, los usuarios deben iniciar sesión antes de usar el visor.

### Edición local de confianza

Permite que un visor de un solo usuario, usado únicamente desde un navegador del mismo equipo, edite sin contraseña de edición:

```json
{
  "viewer": {
    "trusted_local_editing": true
  }
}
```

Solo se aplica mientras **tanto** `viewer.password` **como** `viewer.edition_password` estén vacías, el modo multiusuario esté desactivado y la configuración se haya cargado sin errores. Definir una contraseña de edición la desactiva. No define ni revela ninguna contraseña, no cambia los tokens ni habilita la administración multiusuario.

Facet comprueba cada petición. Una petición es de confianza solo cuando se cumplen todas estas condiciones:

- el par TCP es una dirección de loopback (un par IPv4 mapeado como `::ffff:127.0.0.1` se evalúa por su dirección IPv4);
- hay exactamente una cabecera `Host`, y es `localhost`, `127.0.0.1` o `[::1]`, con un puerto opcional;
- la petición no lleva ninguna cabecera `Forwarded`, `Via`, `X-Real-IP`, `X-Client-IP`, `True-Client-IP`, `CF-Connecting-IP`, `X-Original-Forwarded-For` ni `X-Forwarded-*`;
- un `Origin` o un `Referer`, si está presente, indica exactamente el esquema, el host y el puerto, sin credenciales (un `Origin` con ruta, consulta o fragmento se rechaza); un `Sec-Fetch-Site`, si está presente, es `same-origin` o `none`.

Cualquier otra petición se trata como si la opción estuviera desactivada, peticiones GET incluidas.

Una petición de confianza tiene todos los derechos de edición en cada ruta sujeta a edición: valoraciones, comparaciones, descarte (incluido **Descartar a carpeta**, que mueve o envía archivos a la papelera, y el borrado de una foto), álbumes, personas y rostros, pesos, prioridades y contextos de puntuación, incrustación de metadatos y exportaciones, trabajos de recálculo y de panorámicas, y generación de subtítulos y críticas. También puede escanear sin `viewer.features.show_scan_button`. El flujo de progreso del escaneo solo acepta un token de flujo local de confianza desde la misma máquina local.

**Asistentes.** El cuadro «Conectar un asistente» puede entonces crear un token de **Edición completa** (sigue siendo necesario `viewer.mcp.enabled`).

- El token actúa como `edition` solo para las peticiones `/mcp` que superan las comprobaciones anteriores: `http://localhost:<port>` o `127.0.0.1`, en `:5000` o en el proxy de desarrollo de `ng serve` `:4200`.
- Desde un cliente de la red local, una URL con nombre de host o `0.0.0.0`, o un despliegue en Docker, actúa como `readonly`. Definir cualquier contraseña también lo deja en `readonly`; quitarla lo reactiva.
- Las herramientas de borrado siguen necesitando `viewer.mcp.allow_destructive`. Consulta [Agentes de IA (MCP)](AGENTS.md).
- En una instalación abierta, crear, listar y revocar tokens de asistente solo funciona desde una petición que supere estas comprobaciones (o en una sesión de edición cuando `viewer.edition_password` está definido), sea cual sea el valor de `trusted_local_editing`.
- `ng serve --host 0.0.0.0`, o un proxy en el mismo equipo que no añada ninguna cabecera de reenvío, deja pasar a un cliente de la red local que envíe `Host: localhost`. Un proxy inverso debe enviar `X-Forwarded-For` o `Forwarded`.

> **Advertencia:** Solo la comprobación de loopback es una frontera real; las demás cabeceras las fija el cliente. Un proxy inverso, un túnel o una redirección de puertos en el mismo equipo que no añada ninguna de las cabeceras anteriores es indistinguible de tu navegador. Nunca actives esta opción detrás de ningún proxy inverso en el mismo equipo. Mientras esté activa, cualquier proceso local y cualquier cuenta del equipo puede editar.

### Búsqueda de lugares en línea

`viewer.place_search_url` vale por defecto `https://photon.komoot.io/api`.

- Indica `""` para desactivar la búsqueda de direcciones y negocios, o un endpoint HTTP(S) de Photon autoalojado (sin credenciales, parámetros de consulta ni fragmentos).
- El navegador recibe solo `place_search_enabled`, nunca la URL.
- Las búsquedas requieren acceso de edición y un clic explícito en **Buscar en línea**. No hay reintentos ni redirecciones.
- Una petición caduca a los cinco segundos; la resolución DNS sigue al resolutor del sistema operativo y puede tardar más.

Para privacidad, caché y límites, véase [Búsqueda de lugares en línea](VIEWER.md#búsqueda-de-lugares-en-línea). La [política de la demo de Photon](https://github.com/komoot/photon#demo-server) permite un uso razonable del proyecto sin garantía de disponibilidad; la [documentación de la API de Photon](https://github.com/komoot/photon/blob/master/docs/api-v1.md) define su formato GeoJSON.

### Rendimiento del visor

Anula los ajustes globales de `performance` solo para el visor, p. ej., en un NAS de poca memoria.

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mmap_size_mb` | *(global)* | Anulación del tamaño de mmap de SQLite para las conexiones del visor. `0` desactiva mmap. |
| `cache_size_mb` | *(global)* | Anulación del tamaño de caché de SQLite para las conexiones del visor |
| `pool_size` | `5` | Tamaño del pool de conexiones (reduce para sistemas de poca memoria) |
| `thumbnail_cache_size` | `2000` | Máximo de entradas en la caché en memoria de redimensionado de miniaturas |

Cuando no se establecen, el visor usa los valores globales de `performance`. Consulta [Despliegue](DEPLOYMENT.md) para los ajustes recomendados de NAS.

---

## Rendimiento

Ajustes de rendimiento de la base de datos.

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | Tamaño de E/S mapeada en memoria de SQLite |
| `cache_size_mb` | `128` | Tamaño de la caché de SQLite |
| `wal_checkpoint_minutes` | `30` | Opcional (ausente en el archivo incluido). Minutos entre los checkpoints WAL en segundo plano del visor; `0` los desactiva |
| `slow_request_ms` | `1000` | Registra las solicitudes de la API del visor más lentas que esto (WARNING, marcador `SLOW`); `0` lo desactiva |

El checkpoint periódico (`PRAGMA wal_checkpoint(TRUNCATE)`) mantiene pequeño el archivo WAL en instalaciones de larga duración; también se ejecuta un checkpoint en un cierre limpio.

---

## Almacenamiento

Dónde se almacenan las miniaturas y los embeddings: columnas BLOB en la base de datos SQLite (por defecto), o archivos en disco para mantener más pequeña la base de datos.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `mode` | `"database"` | Backend de almacenamiento: `"database"` (BLOBs de SQLite) o `"filesystem"` (archivos en disco) |
| `filesystem_path` | `"./storage"` | Directorio base para el modo de sistema de archivos (`<path>/thumbnails/` y `<path>/embeddings/`) |

**Detalles del modo de sistema de archivos:**
- Los archivos se nombran por el hash SHA-256 de la ruta de la foto, en subdirectorios de dos caracteres (p. ej., `thumbnails/a3/a3f8..._640.jpg`).
- Eliminar una foto borra todos los tamaños de miniatura y archivos de embedding asociados.
- El directorio se crea automáticamente en el primer uso.

---

## Plugins

Sistema de plugins basado en eventos para reaccionar a eventos de puntuación. Los plugins pueden ser módulos Python, webhooks o acciones integradas.

### Configuración

```json
{
  "plugins": {
    "enabled": true,
    "high_score_threshold": 8.0,
    "webhooks": [
      {
        "url": "https://example.com/hook",
        "events": ["on_score_complete", "on_high_score"],
        "min_score": 8.0
      }
    ],
    "actions": {
      "copy_high_scores": {
        "event": "on_high_score",
        "action": "copy_to_folder",
        "folder": "/path/to/best-photos",
        "min_score": 9.0
      }
    }
  }
}
```

| Clave | Por defecto | Descripción |
|-----|---------|-------------|
| `enabled` | `false` | Interruptor maestro: cuando es false, no se emite ningún evento |
| `high_score_threshold` | `8.0` | Puntuación agregada mínima para activar los eventos `on_high_score` |
| `webhooks` | `[]` | Lista de endpoints de webhook que reciben cargas JSON por POST |
| `actions` | `{}` | Acciones integradas con nombre activadas por eventos |

### Eventos admitidos

| Evento | Activador | Carga |
|-------|---------|---------|
| `on_score_complete` | Después de puntuar cada foto | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Cuando una foto entra en la base de datos | Igual que `on_score_complete` |
| `on_high_score` | Cuando el agregado ≥ `high_score_threshold` | Igual que `on_score_complete` |
| `on_burst_detected` | Cuando se identifica un grupo de ráfaga | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Escribir un plugin

Coloca un archivo `.py` en el directorio `plugins/`. Define funciones con el nombre de los eventos que quieras gestionar:

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Consulta `plugins/example_plugin.py.example` para la interfaz completa.

### Webhooks

Cada webhook recibe un POST JSON. Las direcciones privadas y de loopback están bloqueadas:

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/IMG_001.jpg",
    "aggregate": 9.2,
    "aesthetic": 9.5,
    "comp_score": 8.8,
    "category": "portrait",
    "tags": "person, outdoor"
  }
}
```

Opciones del webhook: `url` (obligatorio), `events` (lista de nombres de evento), `min_score` (agregado mínimo para activar).

### Acciones integradas

| Acción | Descripción | Opciones |
|--------|-------------|---------|
| `copy_to_folder` | Copia la foto a una carpeta | `folder`, `min_score` |
| `send_notification` | Registra una notificación | `min_score` |

### Endpoints de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/plugins` | Lista los plugins, webhooks y acciones cargados |
| `POST` | `/api/plugins/test-webhook` | Envía una carga de prueba a una URL de webhook |

---

## Cápsulas

Diaporamas de fotos curados agrupados por tema, generados a partir de tu biblioteca y almacenados en caché durante `freshness_hours`.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
    "mmr_moment_weight": 0.0,
    "freshness_hours": 24,
    "reverse_geocoding": true,
    "journey": {
      "min_distance_km": 50,
      "min_photos": 8,
      "time_gap_hours": 24
    },
    "faces_of": { "min_photos": 10 },
    "seasonal": { "min_photos": 10 },
    "golden": { "percentile": 99, "max_photos": 50 },
    "color_story": { "embedding_threshold": 0.75, "min_group_size": 8, "max_groups": 5 },
    "this_week_years_ago": { "min_photos_per_year": 3 },
    "monthly": { "min_photos": 8 },
    "yearly": { "min_photos": 20, "max_photos": 60 },
    "camera": { "min_photos": 15 },
    "tag_collection": { "min_photos": 15 },
    "seeded": {
      "num_seeds": 10,
      "min_photos": 8,
      "seed_lifetime_minutes": 1440,
      "time_window_days": 7,
      "embedding_threshold": 0.7,
      "location_radius_km": 30
    },
    "progress": { "min_improvement_pct": 5, "min_photos": 10, "period_months": 3 },
    "color_palette": { "min_photos": 8 },
    "rare_pair": { "max_shared_photos": 5, "min_score": 7.0, "min_photos": 3 }
  }
}
```

### Ajustes globales

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `min_aggregate` | `6.0` | Puntuación agregada mínima para que las fotos se incluyan en las cápsulas |
| `max_photos_per_capsule` | `40` | Máximo de fotos por cápsula (diversidad MMR aplicada por encima de 5) |
| `max_photo_overlap` | `0.2` | Fracción máxima de fotos compartidas entre dos cápsulas antes de que la deduplicación elimine una |
| `mmr_lambda` | `0.5` | Peso de diversidad MMR: 0=maximizar diversidad, 1=maximizar calidad |
| `mmr_moment_weight` | `0.0` | Peso opcional que combina el `narrative_moment_confidence` de cada foto en la selección MMR de la cápsula. `0.0` = comportamiento sin cambios |
| `freshness_hours` | `24` | TTL de la caché y periodo de rotación de las fotos de portada y las cápsulas semilladas |
| `reverse_geocoding` | `true` | Activar la geocodificación inversa sin conexión para los títulos de las cápsulas de ubicación/viaje (requiere el paquete `reverse_geocoder`) |

### Tipos de cápsula

| Tipo | Descripción |
|------|-------------|
| `journey` | Viajes detectados mediante agrupación GPS + intervalos temporales. Los títulos incluyen el nombre del destino cuando la geocodificación está activada. |
| `faces_of` | Las mejores fotos de cada persona reconocida |
| `seasonal` | Fotos agrupadas por estación + año |
| `golden` | El 1 % superior por puntuación agregada |
| `color_story` | Grupos visualmente similares mediante agrupación de embeddings CLIP |
| `this_week` | "Esta semana, hace años": un "Un día como hoy" ampliado a ±3 días |
| `location` | Grupos de fotos geoetiquetadas con nombres de lugar geocodificados inversamente |
| `person_pair` | Parejas de personas con nombre que aparecen juntas |
| `seeded` | Descubrimiento basado en semillas por tiempo, similitud, persona, etiqueta, ubicación, ambiente |
| `progress` | "Tu fotografía está mejorando" a partir de las tendencias de puntuación trimestrales |
| `color_palette` | "Color del mes" a partir de los perfiles de saturación/monocromo |
| `rare_pair` | Parejas de personas poco frecuentes en fotos de alta puntuación |
| `favorites` | Fotos marcadas como favoritas agrupadas por año y estación |

### Cápsulas basadas en dimensiones

Generadas automáticamente a partir de columnas de la base de datos:

| Dimensión | Agrupa por |
|-----------|-----------|
| `year` | Año extraído de date_taken |
| `month` | Año-mes extraído de date_taken |
| `week` | Año-semana extraído de date_taken |
| `camera` | Modelo de cámara |
| `lens` | Modelo de objetivo |
| `tag` | Etiquetas de la foto (requiere la tabla `photo_tags`) |
| `day_of_week` | Día de la semana (domingo-sábado) |
| `composition` | Patrón de composición SAMP-Net (rule_of_thirds, horizontal, etc.) |
| `focal_range` | Tramos de distancia focal: ultra gran angular (<24mm), gran angular (24-35mm), estándar (36-70mm), retrato (71-135mm), teleobjetivo (136-300mm), súper teleobjetivo (300mm+) |
| `category` | Categoría de contenido de la foto (portrait, landscape, street, etc.) |
| `time_of_day` | Tramos horarios: mañana dorada, mañana, mediodía, tarde, tarde dorada, noche |
| `star_rating` | Valoraciones por estrellas del usuario (1-5 estrellas) |

También se generan combinaciones interdimensionales (p. ej., cámara × año, focal_range × categoría, categoría × año).

### Transiciones del pase de diapositivas

Cada tipo de cápsula se asigna a una transición de diapositiva temática:

| Transición | Usada por | Efecto |
|-----------|---------|--------|
| `crossfade` | Por defecto | Cambio de opacidad de 300ms |
| `slide` | journey, location, this_week | Desliza desde la derecha (500ms) |
| `zoom` | faces_of, color_story | Escala 1.05→1.0 con fundido (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lento 1.0→1.08 durante la duración de la diapositiva |

### Geocodificación inversa

Las cápsulas de ubicación y viaje usan geocodificación inversa sin conexión a través del paquete `reverse_geocoder` (conjunto de datos local de GeoNames, ~30MB, sin llamadas a API). Los resultados se almacenan en caché con una resolución de cuadrícula de 0,1° (~11km).

Instalación: `pip install reverse_geocoder`

Establece `"reverse_geocoding": false` para desactivarla y recurrir a la visualización de coordenadas.

## Grupos de similitud

Ajustes para el descarte de fotos similares, que agrupa fotos visualmente similares mediante embeddings CLIP/SigLIP:

```json
{
  "similarity_groups": {
    "default_threshold": 0.85,
    "min_group_size": 2,
    "max_photos": 10000,
    "max_group_size": 50
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `default_threshold` | `0.85` | Similitud coseno mínima (0.0-1.0) para que dos fotos cuenten como similares; más bajo = grupos más grandes y más laxos |
| `min_group_size` | `2` | Número mínimo de fotos necesarias para formar un grupo de similitud |
| `max_photos` | `10000` | Máximo de fotos cargadas para la comparación (el coste crece como O(n²)) |
| `max_group_size` | `50` | Máximo de fotos por grupo; los grupos más grandes se dividen |

## Descarte automático

Descarte automático de un botón para el estudio de descarte (`POST /api/culling/auto`, restringido a edición). Descarta todo un ámbito en una sola pasada: todos los grupos, o solo ráfagas / similares / escenas, opcionalmente acotado a un álbum o una ventana de fechas. Cada grupo conserva su mejor foto más todo lo que quede dentro de un margen fijado por el rigor (como con el control deslizante del estudio), con al menos un mínimo por grupo, y descarta el resto.

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `default_strictness` | `50` | Presupuesto de fotos a conservar (0–100) cuando la solicitud omite `strictness`; más alto conserva menos fotos por grupo |
| `highlights_min` | `8.0` | Puntuación agregada mínima para que la mejor foto de un grupo se una al álbum opcional de **Destacados** al aplicar |

- `dry_run` está activado por defecto y devuelve una vista previa de conservar/descartar por grupo.
- Aplicar registra comparaciones con `source='culling'` y cuenta para un reentrenamiento automático. Consulta [Galería web — Descarte automático](VIEWER.md#descarte-automático).
- Los mismos ajustes alimentan `python facet.py --auto-cull` (consulta [Descarte desde la terminal](COMMANDS.md#descarte-desde-la-terminal)); sus reglas se leen de la configuración del servidor, no de `--config`.

## Reentrenamiento automático

Controla cuándo se reentrena el clasificador personal («Mi gusto»). Cada confirmación de descarte y cada cambio de valoración suma a un contador por usuario. Superar `threshold` arma el reentrenamiento, que arranca cuando llevas `idle_seconds` sin actividad, de modo que no ralentiza tus valoraciones.

```json
{
  "auto_retrain": {
    "threshold": 25,
    "idle_seconds": 60,
    "backend": "native"
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `threshold` | `25` | Nuevas comparaciones necesarias antes de armar un reentrenamiento; aumenta el valor si valoras lotes muy grandes |
| `idle_seconds` | `60` | Segundos sin actividad de valoración/descarte antes de que arranque el reentrenamiento armado; `0` lo arranca de inmediato |
| `backend` | `"native"` | `"native"` entrena en local; `"external"` solo conserva las preferencias y los contadores. Véase [Backend de aprendizaje externo](#backend-de-aprendizaje-externo) |

Las variables de entorno anulan `threshold` e `idle_seconds` (útil en Docker):

```bash
FACET_RETRAIN_THRESHOLD=100 FACET_RETRAIN_IDLE_S=300 python viewer.py
```

| Variable | Sobrescribe |
|----------|-------------|
| `FACET_RETRAIN_THRESHOLD` | `auto_retrain.threshold` |
| `FACET_RETRAIN_IDLE_S` | `auto_retrain.idle_seconds` |

- Un `threshold` o `idle_seconds` no válido recae en el valor JSON y después en el valor por defecto integrado. Ambos se leen al arrancar; los cambios requieren un reinicio.
- Un `auto_retrain.backend` no válido recae en `"external"` (véase más abajo).
- Un reentrenamiento que no supera al modelo actual con datos reservados no guarda nada.

### Backend de aprendizaje externo

`"backend": "external"` conserva valoraciones, comparaciones y recuentos pendientes, pero nunca entrena ni evalúa en local el clasificador personal, la cabeza de selección ni los pesos aprendidos. Úsalo cuando un flujo aparte, gestionado por el operador, entrene y publique las puntuaciones. Facet no lanza ningún worker externo.

En modo externo:
- Los comandos manuales del clasificador personal, la cabeza de selección y el aprendizaje de pesos indican que el entrenamiento queda aplazado.
- Las probabilidades de selección no están disponibles; las respuestas de pesos aprendidos y confianza de Comparar indican `available: false`.
- La puntuación normal de las fotos y los votos no se ven afectados.

Un bloque `auto_retrain` mal formado, un `backend` distinto de `"native"` o `"external"`, o una configuración ilegible seleccionan el modo externo y registran una advertencia. Una configuración válida sin clave `backend` usa el modo nativo.

## Perfiles de descarte por género

Preajustes por género que fijan todos los controles de descarte con un clic, desde un selector en el estudio de descarte. Deportes conserva solo el fotograma más nítido de una ráfaga larga; las bodas conservan más variantes y exigen ojos abiertos; los conciertos relajan los umbrales de ojos/expresión; la fauna elimina el filtro de rostros.

```json
{
  "cull_profiles": {
    "default": "balanced",
    "profiles": {
      "balanced": { "label_key": "culling.profiles.balanced", "strictness": 50, "eyes_closed_max": 4.0, "poor_expression_min": 4.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wedding":  { "label_key": "culling.profiles.wedding",  "strictness": 35, "eyes_closed_max": 5.0, "poor_expression_min": 5.0, "keep_min_per_group": 2, "similarity_threshold": 90 },
      "sports":   { "label_key": "culling.profiles.sports",   "strictness": 85, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 80 },
      "concert":  { "label_key": "culling.profiles.concert",  "strictness": 55, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wildlife": { "label_key": "culling.profiles.wildlife", "strictness": 70, "eyes_closed_max": 0.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 82 }
    }
  }
}
```

| Ajuste | Descripción |
|---|---|
| `default` | Id de perfil aplicado cuando no hay ninguno guardado en el cliente |
| `profiles.<id>.label_key` | Ruta de puntos i18n del nombre visible del preajuste (`culling.profiles.*`) |
| `profiles.<id>.strictness` | Presupuesto de conservación (0–100) para el auto-descarte con este preajuste |
| `profiles.<id>.eyes_closed_max` | Puntuación de ojos abiertos (0–10) igual o inferior a la cual un rostro cuenta como cerrado (anula `face_detection.eyes_closed_max`) |
| `profiles.<id>.poor_expression_min` | Puntuación de expresión/sonrisa (0–10) por debajo de la cual un rostro cuenta como pobre (anula `face_detection.poor_expression_min`) |
| `profiles.<id>.keep_min_per_group` | Mínimo por grupo del conjunto conservado por el auto-descarte con este preajuste |
| `profiles.<id>.similarity_threshold` | Umbral de agrupación por similitud (porcentaje) que aplica el estudio cuando se selecciona el preajuste |

`GET /api/culling/profiles` devuelve la lista ordenada de preajustes y el predeterminado. `POST /api/culling/auto` y `POST /api/culling-group/faces` aceptan un id `profile` opcional; un `strictness`/`min_keep_per_group` explícito en la solicitud prevalece sobre el preajuste.

## Escenas

Ajustes para la vista de Escenas, que agrupa las fotos principales de ráfaga en escenas cronológicas (divididas por intervalos de tiempo de captura) para un descarte en orden narrativo:

```json
{
  "scenes": {
    "gap_minutes": 20.0,
    "min_size": 2,
    "max_photos": 5000,
    "max_scene_size": 60,
    "adaptive": true,
    "adaptive_k": 6.0
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `gap_minutes` | `20.0` | Intervalo entre fotos principales de ráfaga consecutivas que inicia una nueva escena (el suelo cuando `adaptive` está activado) |
| `min_size` | `2` | Fotos mínimas para que se muestre una escena |
| `max_photos` | `5000` | Máximo de fotos principales de ráfaga cargadas para la agrupación en escenas |
| `max_scene_size` | `60` | Las escenas mayores se vuelven a dividir en sus mayores intervalos internos |
| `adaptive` | `true` | Amplía el intervalo a `adaptive_k × mediana` de los intervalos de la sesión (más ajustado para la fotografía rápida, más laxo para viajes dispersos) |
| `adaptive_k` | `6.0` | Multiplicador aplicado a la mediana del intervalo cuando `adaptive` está activado |
| `split_on_moment_change` | `false` | Con los momentos narrativos calculados, divide también donde el momento dominante cambia durante `moment_split_min_run` fotogramas |
| `moment_split_min_run` | `4` | Fotogramas consecutivos que debe durar un nuevo momento para forzar un límite de escena |

## Narrative Moments

Etiqueta el «momento» de escena o actividad de cada foto sin entrenamiento. El vocabulario **general** por defecto cubre `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle` u `other`. `wedding` se incluye como género opcional. `--detect-moments` los rellena (también se ejecuta al final de cada escaneo); se muestran como nombres de escena y como filtro de la galería.

Facet compara la leyenda de IA de cada foto, codificada una vez y almacenada (`caption_embedding`), con los prompts de texto de cada momento, y se queda con la mejor coincidencia. Sin leyenda, usa el embedding de imagen. Las leyendas coinciden con más limpieza, así que la señal `caption` lleva umbrales más altos que el respaldo `image`, ajustados por backend. Los valores de `transformers` (SigLIP) son valores por defecto conservadores; vuelve a ajustarlos si ejecutas un perfil SigLIP.

```json
{
  "narrative_moments": {
    "enabled": true,
    "prompt_template": "a photo of {desc}",
    "default_event_type": "general",
    "pooling": "max",
    "caption_min_confidence": 0,
    "thresholds": {
      "caption": {
        "open_clip": { "min_confidence": 0.30, "min_margin": 0.02 },
        "transformers": { "min_confidence": 0.12, "min_margin": 0.01 }
      },
      "image": {
        "open_clip": { "min_confidence": 0.20, "min_margin": 0.01 },
        "transformers": { "min_confidence": 0.10, "min_margin": 0.01 }
      }
    },
    "priors": {
      "enabled": true, "weight": 0.04, "caption_tag_scale": 0.25,
      "rules": [
        { "kind": "structural", "when": { "is_group_portrait": true, "face_count_min": 4 }, "boost": { "group_gathering": 1.0 } },
        { "kind": "tag", "when": { "tags_any": ["beach", "ocean", "sand"] }, "boost": { "beach": 0.8 } }
      ],
      "event_types": { "wedding": { "rules": [ { "kind": "tag", "when": { "tags_any": ["cake"] }, "boost": { "cake_cutting": 1.0 } } ] } }
    },
    "vlm_tiebreak": { "enabled": false, "min_confidence": 0.0, "min_margin": 0.04 },
    "transitions": { "stay_prob": 0.7, "forward_bias": 0.0, "weight": 0.3 },
    "event_types": { "general": { "beach": ["people at a sandy beach by the sea", "..."], "...": [] }, "wedding": { "vows": ["the couple exchanging vows at the altar", "..."] } }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Interruptor maestro; cuando está desactivado, `--detect-moments` y el hook del escaneo no hacen nada |
| `prompt_template` | `"a photo of {desc}"` | Envoltorio aplicado a cada prompt antes de codificarlo |
| `default_event_type` | `"general"` | Vocabulario activo de `event_types` (`general` = 20 momentos; `wedding` opcional) |
| `pooling` | `"max"` | Puntuación por momento = la mejor coincidencia de un único prompt |
| `caption_min_confidence` | `0` | Cuando > 0, la generación de leyendas omite las fotos sin etiqueta, `other` o por debajo de esta confianza; `0` = sin filtro |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Por debajo de este coseno top-1 una foto es `other` (indexado por señal y luego por backend) |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Brecha coseno top-1/top-2 mínima; por debajo de ella el fotograma es `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Pequeños empujones de rostro/etiqueta que solo deshacen casi-empates; `weight` limita cada ajuste |
| `priors.caption_tag_scale` | `0.25` | Reduce las reglas **tag** en la señal caption; las reglas estructurales conservan todo su peso |
| `priors.rules` | (conjunto general) | Lista de reglas `{kind, when, boost}` (ver más abajo) |
| `priors.event_types.<et>.rules` | anulación `wedding` | Reglas que **reemplazan** las `rules` globales cuando ese vocabulario está activo |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Suavizado de la línea de tiempo entre fotogramas vecinos (`weight=0` = ninguno) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | En 16gb/24gb, reclasifica con el VLM del perfil solo los fotogramas de baja confianza o bajo margen |
| `event_types` | `general` + `wedding` | `{moment: [sinónimos de prompt]}` por tipo de evento; establece `default_event_type` para cambiar de género o añadir el tuyo propio |

Formato de `priors.rules`:
- `kind`: `structural` (geometría de rostros) o `tag`.
- `when` (deben cumplirse todos): `is_group_portrait`, `face_count_min`/`face_count_max`, `face_ratio_min`/`face_ratio_max`, `tags_any`, `tags_all`.
- `boost`: `{moment: cantidad}`. Un momento ausente del vocabulario activo se omite.

El desempate con VLM se ejecuta durante `--detect-moments` / `--recompute-moments`.

> **Coste del relleno retroactivo de leyendas.** Los embeddings de leyenda se calculan una vez y se almacenan. Un escaneo codifica solo sus leyendas nuevas, pero el primer pase sobre una biblioteca existente codifica todas las leyendas: rápido en GPU, horas en CPU. Ejecuta `python facet.py --detect-moments` una vez (GPU recomendada); añade `--limit N` para probar primero con una muestra.

**Descubrir un vocabulario específico de la biblioteca.** `python facet.py --discover-moments` agrupa los vectores `caption_embedding` almacenados, nombra cada grupo a partir de sus leyendas y escribe un bloque `event_types.discovered` en `scoring_config.discovered.json`. Nunca cambia la configuración activa. Para adoptarlo, copia `discovered` en `event_types`, establece `default_event_type` en `discovered` y ejecuta `--recompute-moments`. `--discover-min-cluster-size N` controla la granularidad (más pequeño = más momentos, más finos).

## OCR

Búsqueda de texto en la foto: lee las palabras *dentro* de tus fotos (carteles de calle, fachadas de tiendas, dorsales de carrera, lomos de libros, diapositivas, pizarras, documentos escaneados) en `photos.ocr_text`. Ese texto es entonces buscable desde la barra de búsqueda de la galería como cualquier leyenda o etiqueta; `GET /api/search?scope=text` busca solo en los campos de texto.

**Desactivado por defecto**, y necesita un motor instalado:

```bash
pip install easyocr           # o: pip install -e .[ocr]
```

Luego actívalo y ejecuta el paso:

```json
{
  "ocr": {
    "enabled": false,
    "languages": ["en", "fr"],
    "min_confidence": 0.4,
    "full_resolution": false
  }
}
```

```bash
python facet.py --detect-text      # solo fotos nunca evaluadas
python facet.py --recompute-text   # vuelve a leer toda la biblioteca
```

| Clave | Por defecto | Descripción |
|-----|---------|-------------|
| `enabled` | `false` | Interruptor maestro; `--detect-text` se niega a ejecutarse mientras sea `false` |
| `languages` | `["en", "fr"]` | Códigos de idioma pasados al motor; una sola familia de escritura por ejecución (easyocr rechaza, p. ej., `en` + `ja`) |
| `min_confidence` | `0.4` | Descarta las detecciones puntuadas por debajo de este valor (0–1); súbelo contra el ruido, bájalo para texto tenue |
| `full_resolution` | `false` | Aplica OCR al original en lugar de a la miniatura de 640px (mucho más lento; recurre a la miniatura si el original está fuera de línea) |

Notas:
- `ocr_text` es `NULL` hasta que se evalúa una foto, y `''` cuando no tiene texto. `--detect-text` lee solo las fotos `NULL`; `--recompute-text` vuelve a leerlo todo.
- **No hace falta `--rebuild-fts`:** el paso actualiza el índice de búsqueda a medida que escribe. `python database.py --rebuild-fts` solo es necesario para una base de datos creada antes de que existiera el OCR, y `init_database` se ocupa de eso por ti.
- La miniatura de 640px ya resuelve carteles, pósteres y encabezados de documentos.

**Motores.** `easyocr` (Apache-2.0, PyTorch) es el motor por defecto y reutiliza la pila que Facet ya instala. Sus pesos (~113MB) se descargan desde las releases de GitHub del proyecto en la primera ejecución. El binario `tesseract` más `pytesseract` se usa cuando easyocr está ausente, pero lee peor el texto de escena. Sin ninguno de los dos instalado, el paso termina con un error.

**Coste.** Unos 0,4s por miniatura en CPU, así que una biblioteca de 50.000 fotos es un trabajo de CPU de toda una noche, una sola vez; los escaneos posteriores solo añaden fotos nuevas. Se usa una GPU automáticamente cuando torch informa de una.

## Destinos de exportación y descarte

La exportación de álbum (`POST /api/albums/{id}/export`, modos `copy`/`symlink`) y el descarte a carpeta (`POST /api/cull/apply`, acciones `copy_keeps` / `move_rejects`) escriben en un `target_dir`. Debe resolverse bajo una raíz permitida, o la solicitud se rechaza antes de tocar ningún archivo.

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    },
    "cull": {
      "allow_trash": false
    }
  }
}
```

| Ajuste | Predeterminado | Descripción |
|---------|---------|-------------|
| `allowed_target_dirs` | *(clave ausente)* | Raíces adicionales en las que pueden escribir la exportación y el descarte a carpeta, además de los directorios de escaneo (siempre permitidos) |
| `cull.allow_trash` | `false` | Permite la acción `trash_rejects` del descarte a carpeta (papelera del sistema mediante `send2trash`, recuperable); desactivado oculta la opción |

**Series multifotograma y acciones masivas.** Con `hide_brackets` / `hide_panoramas` activados (el valor por defecto, consulta [Visor web — Filtros predeterminados](VIEWER.md#filtros-predeterminados)), una selección contiene solo el fotograma representativo de cada serie, así que las acciones masivas actúan solo sobre ese fotograma. La opción `include_sequence_siblings` del descarte a carpeta amplía una foto encontrada a toda su serie; consulta [Visor web — Descartar a carpeta § Series multifotograma](VIEWER.md#descartar-a-carpeta).

**Orden de resolución.** Las raíces permitidas son `allowed_target_dirs` y luego cada directorio de escaneo (por usuario, compartidos y destinos de `path_mapping`). Exportar dentro del árbol de fotos no necesita configuración; un destino fuera de él necesita una entrada aquí. Los enlaces simbólicos y `..` se resuelven antes de la comprobación (`os.path.realpath()`), así que un enlace que apunta fuera de una raíz permitida se rechaza.

**Cerrado por defecto (fail-closed).** Sin `allowed_target_dirs` ni directorios de escaneo, la exportación copiar/symlink/mover se rechaza.

**Solución de problemas de "acceso denegado".** La interfaz web muestra un aviso genérico de "Acceso denegado". Para ver el motivo, abre la pestaña Red del navegador, busca la solicitud fallida a `/api/cull/apply` o `/api/albums/{id}/export` y lee el campo `detail`: o bien esta lista de permitidos, o bien una sesión de edición caducada. Un error real de permisos del sistema de archivos se ve diferente: la solicitud tiene éxito, el recuento `errors` de la respuesta es distinto de cero y el registro del servidor tiene un traceback por archivo. Consulta [Despliegue — Semántica de rutas en contenedores](DEPLOYMENT.md#semántica-de-rutas-en-contenedores) para el caso del contenedor.

Consulta [Visor web — Descartar a carpeta](VIEWER.md#descartar-a-carpeta) y [Visor web — Exportación al editor](VIEWER.md#exportación-al-editor).

## Exportación social

Preajustes de recorte para relaciones de aspecto de redes sociales, encuadrados en el sujeto (`GET /api/photo/social_crop`, restringido a edición). Cada preajuste recorta el original a resolución completa al mayor rectángulo de esa relación de aspecto, centrado en el sujeto. El sujeto es la caja de sujeto BiRefNet (`photos.subject_bbox`); si no, la unión de las cajas de rostros; si no, el centro de la imagen. Consulta [Visor web — Descarga](VIEWER.md#descarga).

```json
{
  "social_export": {
    "presets": {
      "square":       { "label_key": "social_export.presets.square",       "aspect": "1:1" },
      "portrait_4x5": { "label_key": "social_export.presets.portrait_4x5", "aspect": "4:5" },
      "story_9x16":   { "label_key": "social_export.presets.story_9x16",   "aspect": "9:16" }
    },
    "jpeg_quality": 92
  }
}
```

| Ajuste | Predeterminado | Descripción |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | Ruta de puntos i18n para el nombre visible del preajuste (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Relación de aspecto objetivo como `"an:al"` (p. ej. `1:1`, `4:5`, `9:16`) |
| `jpeg_quality` | `92` | Calidad JPEG del recorte exportado |

Controlado por `viewer.features.show_social_export` (predeterminado `true`). La caja del sujeto la escribe la pasada de saliencia al escanear y `--recompute-saliency`; las fotos más antiguas usan el recorte por rostros o centrado.

## Exportación de portafolio

Exporta un álbum como una galería HTML estática y autónoma que puedes subir a cualquier alojamiento web (`POST /api/albums/{album_id}/export-portfolio`, restringido a edición).

- La carpeta de salida contiene `index.html` (cuadrícula de miniaturas y lightbox, sin referencias externas ni CDN), una carpeta `assets/` con JPEG nombrados secuencialmente (sin rutas de la biblioteca) y un `manifest.json`.
- Cada foto usa el **original**, reducido a `max_edge`, o la miniatura de 640px almacenada cuando el original es inaccesible. El manifiesto registra cuál.
- Una reexportación solo reescribe sus propios archivos.

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| Ajuste | Predeterminado | Descripción |
|--------|----------------|-------------|
| `max_photos` | `500` | Los álbumes más grandes se rechazan (la exportación es sincrónica) |
| `max_edge` | `2048` | Límite del lado largo (px) para los originales exportados; la solicitud puede anularlo (acotado 256–8000) |
| `jpeg_quality` | `88` | Calidad JPEG de las imágenes exportadas |

El `target_dir` usa la misma lista de permitidos que las demás exportaciones (`viewer.export.allowed_target_dirs` más los directorios de escaneo — consulta [Destinos de exportación y descarte](#destinos-de-exportación-y-descarte)). Controlado por `viewer.features.show_portfolio_export` (predeterminado `true`). Consulta [Visor web — Exportación de portafolio](VIEWER.md#exportación-de-portafolio).

## Endpoint de agentes (MCP)

Expone las herramientas descritas en [Agentes de IA (MCP)](AGENTS.md) en `POST /mcp`: lectura, control de tu pestaña abierta y, según el nivel del token, modificación de valoraciones, etiquetas y álbumes, descarte y eliminación. Está activado por defecto.

En una instalación abierta (sin `viewer.password`):
- `/mcp` solo sirve una clave anónima de solo lectura, que no muestra nada que la `/api` abierta no muestre ya.
- Un token nuevo es `readonly`, salvo que `viewer.trusted_local_editing` esté activado o la sesión haya iniciado con `viewer.edition_password`: ambos pueden crear un token de edición completa, que solo edita en las peticiones del mismo equipo.
- Los tokens solo se pueden crear, listar y revocar desde el ordenador donde se ejecuta Facet (o en una sesión de edición cuando `viewer.edition_password` está definido).

```json
{
  "viewer": {
    "mcp": {
      "enabled": true,
      "bridge": true,
      "max_rows": 100,
      "max_bytes": 60000,
      "max_image_bytes": 262144,
      "call_timeout_s": 30,
      "semantic_timeout_s": 120,
      "rate_per_min": 120,
      "write_rate_per_min": 30,
      "tool_profile": "full",
      "allow_destructive": false,
      "inpage_tools": true,
      "allowed_origins": []
    }
  }
}
```

| Clave | Predeterminado | Descripción |
|-----|---------|-------------|
| `enabled` | `true` | Interruptor general de `/mcp` y `/api/mcp/*` |
| `bridge` | `true` | Permite el puente con la pestaña del navegador (`/api/mcp/bridge`) para que las herramientas `ui_*` lleguen a una pestaña; requiere un único worker |
| `max_rows` | `100` | Máximo de filas en un resultado de herramienta (1 a 500); las filas sobrantes marcan `truncated: true` |
| `max_bytes` | `60000` | Tamaño serializado máximo de un resultado de herramienta en bytes (4000 a 500000). |
| `max_image_bytes` | `262144` | Tamaño máximo de la imagen de `get_thumbnail` o `contact_sheet` (32768 a 2097152); no se cuenta en `max_bytes` |
| `call_timeout_s` | `30` | Tiempo límite de una llamada a herramienta en segundos (1 a 300), también la espera de `ui_*` a la pestaña (`tab_timeout`) |
| `semantic_timeout_s` | `120` | Tiempo límite de `semantic_search` en segundos (1 a 300); carga el modelo de embeddings, así que necesita más. |
| `rate_per_min` | `120` | Llamadas a herramientas por minuto y token (mínimo 1). |
| `write_rate_per_min` | `30` | Llamadas de escritura por minuto y token (mínimo 1), aparte para que las lecturas no dejen sin cupo a las escrituras |
| `tool_profile` | `"full"` | `"full"` lista cada herramienta permitida; `"core"` lista un conjunto de 11 herramientas para modelos pequeños |
| `allow_destructive` | `false` | Permite `delete_photos`, `move_rejects`/`trash_rejects` de `cull_apply` y `assign_faces` con `allow_reassign` |
| `inpage_tools` | `true` | Permite que una pestaña con sesión iniciada llame a las herramientas del servidor desde la página (`GET /api/mcp/inpage_tools`, `POST /api/mcp/call`) |
| `allowed_origins` | `[]` | Orígenes de navegador adicionales (por ejemplo `["https://photos.example.com"]`) autorizados a abrir el puente de pestaña tras un proxy que reescribe `Host`; no es la clave CORS `viewer.allowed_origins` |

Notas:
- **`enabled: false`** apaga `/mcp` y `/api/mcp/*` (el puente se cierra con el código 4404). **`bridge: false`** rechaza el puente y hace que las herramientas `ui_*` devuelvan un error.
- **`write_rate_per_min`** cubre las herramientas de escritura, incluida la simulación de `cull_apply` y `delete_photos`; consulta [Agentes de IA](AGENTS.md#modificar-la-biblioteca).
- **`"core"`** lista `status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`. Solo cambia la lista; las demás herramientas aún pueden llamarse si el nivel de la clave lo permite. Cualquier otro valor equivale a `"full"`. Consulta [Agentes de IA](AGENTS.md#niveles-de-permiso).
- **`allow_destructive: false`** oculta `delete_photos`; las otras dos responden `feature_disabled` nombrando esta clave. Consulta [Agentes de IA](AGENTS.md#acciones-destructivas-vista-previa-y-confirmación).
- **`inpage_tools`** ejecuta las herramientas como la sesión, a su nivel actual. Desactivado, `features.mcp_inpage` es falso en `/api/auth/status`. Consulta [Agentes de IA](AGENTS.md#webmcp-en-la-página-agentes-del-navegador).
- Los números fuera de rango se ajustan al límite; un valor de tipo incorrecto usa el predeterminado. Los cambios se aplican al recargar la configuración, sin reiniciar.

## Marco de fotos / Quiosco

Sirve las mejores tomas curadas a dispositivos de tipo quiosco sin inicio de sesión: marcos de fotos inteligentes, paneles de Home Assistant, pantallas al estilo ImmichFrame / Immich-Kiosk. Tres endpoints usan un token estático: `GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`. Una lista `tokens` vacía deshabilita la función (los endpoints responden 404). Las respuestas nunca contienen rutas de archivos; las fotos se identifican mediante un id firmado.

```json
{
  "frame": {
    "tokens": [],
    "count": 20,
    "max_count": 100,
    "min_aggregate": 7.0,
    "max_edge": 1920,
    "favorites_only": false,
    "categories": []
  }
}
```

| Ajuste | Predeterminado | Descripción |
|--------|----------------|-------------|
| `tokens` | `[]` | Tokens de marco, una cadena aleatoria larga por dispositivo; elimina uno para revocarlo. **Vacío = función deshabilitada.** |
| `count` | `20` | Número predeterminado de fotos que devuelve `/api/frame/photos` |
| `max_count` | `100` | Tope estricto del parámetro de consulta `count` |
| `min_aggregate` | `7.0` | Puntuación agregada mínima para que una foto se cure |
| `max_edge` | `1920` | Tope del lado largo (px) de los JPEG servidos; el parámetro de consulta `max_edge` solo puede reducirlo |
| `favorites_only` | `false` | Si es `true`, solo se curan las fotos favoritas |
| `categories` | `[]` | Lista blanca de nombres de categorías (vacío = todas) |

Genera un token con `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

La curación omite las fotos rechazadas, basura (`junk_kind`) y con parpadeo, aplica los filtros de puntuación, favoritos y categorías, y luego elige una muestra aleatoria ponderada por puntuación. Consulta [Visor web — Endpoint de marco de fotos / quiosco](VIEWER.md#marco-de-fotos--quiosco) para la receta de Home Assistant.

> **Advertencia:** Un token de marco no es un inicio de sesión de usuario. En [modo multiusuario](#usuarios) ignora los `directories` privados de cada usuario y puede leer las fotos de todos los usuarios, no solo `shared_directories`. Emite tokens de marco únicamente donde todos los usuarios lo acepten.

## Subida automática desde el teléfono

Un endpoint **WebDAV** mínimo en `/dav` permite que las apps de subida automática desde el teléfono (PhotoSync y otras) envíen fotos a un **directorio de entrada** (inbox), que `facet.py --watch` puntúa después. El acceso usa HTTP Basic con **credenciales de dispositivo compartido** (`username` / `password`), no una cuenta de usuario.

- `/dav` devuelve **404** hasta que `username`, `password` e `inbox_dir` estén definidos.
- Cada operación se queda dentro de `inbox_dir`; se rechazan la travesía de rutas, las rutas absolutas y el escape por enlace simbólico.
- Las subidas se escriben de forma atómica y están limitadas por `max_file_mb`.

```json
{
  "upload": {
    "username": "",
    "password": "",
    "inbox_dir": "",
    "max_file_mb": 500
  }
}
```

| Ajuste | Predet. | Descripción |
|--------|---------|-------------|
| `username` | `""` | Usuario de HTTP Basic (credencial de dispositivo compartido). **Vacío = función desactivada.** |
| `password` | `""` | Contraseña de HTTP Basic; usa una cadena aleatoria larga. **Vacío = función desactivada.** |
| `inbox_dir` | `""` | Ruta absoluta del directorio de entrada, creado bajo demanda. **Vacío = función desactivada.** |
| `max_file_mb` | `500` | Límite de tamaño por archivo (MB); una subida mayor se aborta y no deja ningún archivo parcial |

Apunta `inbox_dir` a un directorio escaneado (o un subdirectorio) para que `facet.py --watch` puntúe las subidas según llegan.

Métodos admitidos: `OPTIONS`, `PROPFIND` (profundidad 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD` (sin `LOCK`/`UNLOCK`). Un encabezado `Authorization` ausente o incorrecto recibe `WWW-Authenticate: Basic realm="Facet upload"`. Consulta [Visor web — Subida automática desde el teléfono](VIEWER.md#subida-automática-desde-el-teléfono) para la receta de PhotoSync y una prueba rápida con `curl`.

## Limpieza de basura

Marca los archivos "basura" que no son fotos (capturas de pantalla, documentos escaneados, recibos, memes, diapositivas de presentación) a partir del **embedding de imagen almacenado**, sin decodificar la imagen. Cada tipo lleva una lista de prompts de texto, y el prompt que mejor coincide cuenta para ese tipo.

- Una foto solo se marca cuando su mejor tipo de basura alcanza `min_confidence` **y** supera al mejor prompt `not_junk` por `min_margin`.
- Si no, se guarda como `not_junk` (evaluada, limpia). `NULL` significa que aún no se ha evaluado.
- `--detect-junk` etiqueta solo las fotos `NULL` (también se ejecuta al final del escaneo); `--recompute-junk` vuelve a comprobar toda la biblioteca.
- Los resultados van a `photos.junk_kind`, que se revisa en la cola **Limpieza de basura** del visor ([VIEWER.md](VIEWER.md#limpieza-de-basura)).

```json
{
  "junk_sweep": {
    "enabled": true,
    "prompt_template": "{desc}",
    "pooling": "max",
    "thresholds": {
      "open_clip": { "min_confidence": 0.2, "min_margin": 0.06 },
      "transformers": { "min_confidence": 0.1, "min_margin": 0.02 }
    },
    "kinds": {
      "screenshot": ["a screenshot of a phone user interface", "..."],
      "document": ["a scanned document", "..."],
      "receipt": ["a close-up photo of a paper receipt", "..."],
      "meme": ["a meme with overlaid text", "..."],
      "slide": ["a presentation slide", "..."]
    },
    "not_junk_prompts": ["a natural photograph", "a candid photo of people", "..."]
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Ejecuta la detección de basura durante `--detect-junk` / `--recompute-junk` y al final del escaneo |
| `prompt_template` | `"{desc}"` | Cadena de formato aplicada a cada prompt (`{desc}` = el prompt); sin cambios por defecto |
| `pooling` | `"max"` | Combina las puntuaciones de los prompts por tipo mediante `max` (mejor prompt individual) o `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Puntuación mínima para el mejor tipo de basura (por backend; las puntuaciones de CLIP/`open_clip` son más bajas que las de SigLIP/`transformers`) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Cuánto debe superar el mejor tipo de basura al mejor prompt de contraste `not_junk` antes de que se marque la foto |
| `kinds` | screenshot/document/receipt/meme/slide | `{tipo: [sinónimos de prompt]}`; añade, quita o renombra tipos libremente |
| `not_junk_prompts` | 8 prompts fotográficos | Prompts que describen fotografías reales y mantienen las fotos genuinas fuera de la cola |

## Crítica con IA

Ajustes de prompt para la crítica con VLM (perfiles 16gb/24gb). La crítica alimenta al VLM con el desglose de la puntuación, las penalizaciones y el EXIF, y muestra su respuesta como Observación / Evaluación / Sugerencias.

- La Evaluación cubre composición, color y luz, enfoque/PdC y ejecución técnica, y sujeto y momento, contrastados con las métricas.
- Se almacena en caché por foto (`photos.vlm_critique`, traducciones en `vlm_critique_translated`); `refresh` la regenera.
- Se ejecuta sobre la miniatura almacenada, así que los archivos RAW funcionan.

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `critique.vlm.max_new_tokens` | `320` | Presupuesto de tokens para la generación estructurada de la crítica con VLM |

Consulta [Galería web — Crítica con IA](VIEWER.md#crítica-con-ia).

## Backend VLM

Elige dónde se ejecuta el modelo de visión y lenguaje de leyendas/etiquetas. `local` (por defecto) usa el modelo Qwen integrado de los perfiles 16gb/24gb. Los dos backends remotos usan un servidor externo, así que las leyendas y el etiquetado VLM también funcionan en los **perfiles legacy/8gb, que no incluyen ningún VLM local**.

```json
{
  "vlm_backend": {
    "type": "local",
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen2.5vl:7b",
      "timeout_seconds": 120
    },
    "openai_compatible": {
      "base_url": "http://localhost:1234/v1",
      "api_key": "",
      "model": "qwen2.5-vl-7b",
      "timeout_seconds": 120
    }
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `type` | `"local"` | `local` (Qwen integrado), `ollama` (API REST de Ollama) u `openai_compatible` (LM Studio, vLLM, OpenRouter, …) |
| `ollama.base_url` | `"http://localhost:11434"` | URL base del servidor Ollama (las imágenes van a `POST /api/generate`) |
| `ollama.model` | `"qwen2.5vl:7b"` | Etiqueta de modelo de Ollama (debe ser un modelo de visión ya descargado en el servidor) |
| `ollama.timeout_seconds` | `120` | Tiempo de espera por solicitud para las llamadas a Ollama |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | URL base **incluyendo el sufijo `/v1`** (las solicitudes van a `{base_url}/chat/completions`, con la imagen como URI de datos `image_url`) |
| `openai_compatible.api_key` | `""` | Se envía como `Authorization: Bearer <clave>`; déjalo vacío para servidores locales sin clave |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | Nombre del modelo pasado al endpoint |
| `openai_compatible.timeout_seconds` | `120` | Tiempo de espera por solicitud para las llamadas compatibles con OpenAI |

El backend impulsa las leyendas (`--generate-captions` y `/api/caption`), la crítica VLM (`/api/critique?mode=vlm`), el reetiquetado VLM (`--recompute-tags-vlm`) y el desempate de momentos narrativos. Una solicitud remota fallida hace fallar solo esa foto (registrada, sin tags ni leyenda). El etiquetado durante el escaneo sigue usando el etiquetador propio del perfil; ejecuta `--recompute-tags-vlm` para aplicar un backend remoto a una biblioteca existente.

## Atributos de distorsión

Etiquetas de distorsión informativas. `--recompute-distortions` compara el embedding CLIP/SigLIP almacenado de cada foto con prompts de defectos habituales (desenfoque por movimiento, dominante de color, exceso de nitidez, …) y guarda los probables. Nunca afectan a la puntuación; se muestran como chips de aviso en el diálogo de crítica.

```json
{
  "distortion_attributes": {
    "enabled": true,
    "top_n": 5,
    "thresholds": {
      "open_clip":    { "temperature": 0.02, "min_confidence": 0.6 },
      "transformers": { "temperature": 0.05, "min_confidence": 0.6 }
    },
    "vocabulary": {}
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `enabled` | `true` | Calcular los atributos de distorsión durante `--recompute-distortions` |
| `top_n` | `5` | Número máximo de etiquetas de distorsión conservadas por foto |
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Temperatura de softmax sobre las puntuaciones de los prompts, por backend de embeddings (las escalas difieren, como en `narrative_moments`) |
| `thresholds.<backend>.min_confidence` | `0.6` | Probabilidad mínima para conservar una etiqueta de distorsión |
| `vocabulary` | `{}` | Anulación opcional de los prompts integrados (`{attribute: [sinónimos de prompt]}`); vacío = valores por defecto |

## Tono de piel

Comprobación informativa del tono de piel en retratos. `--recompute-skin-tone` mide el color de la mejilla en las miniaturas de rostro almacenadas y marca los retratos cuya piel deriva hacia verde, magenta, azul o amarillo. Nunca afecta a la puntuación; el resultado se muestra como una nota en el diálogo de crítica.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `cast_delta_threshold` | `12.0` | Distancia CIEDE2000 mínima respecto a los tonos de piel naturales antes de marcar una dominante de color |

## Sincronización con Immich

Sincronización unidireccional de las valoraciones por estrellas y los favoritos de Facet a un servidor [Immich](https://immich.app/) mediante su API REST. Los recursos se emparejan por `originalPath` a través de `path_map`. Ejecuta `--immich-sync` (prueba antes con `--immich-test`); consulta [Comandos — Sincronización con Immich](COMMANDS.md#sincronización-con-immich).

```json
{
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
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `url` | `""` | URL base del servidor Immich (p. ej. `http://nas:2283`) |
| `api_key` | `""` | Clave de API de Immich, enviada como la cabecera `x-api-key` |
| `owner_id` | `""` | ID exacto del propietario, opcional; se omiten los recursos que no lo tienen o son de otra persona |
| `library_id` | `""` | ID exacto de la biblioteca, opcional; vacío = sin filtro de biblioteca |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Reescrituras de prefijo de las rutas de Facet a `originalPath` de Immich; gana el primer `facet_prefix` coincidente |
| `push.ratings` | `true` | Enviar las valoraciones por estrellas (solo se escribe 1–5, nunca 0/−1) |
| `push.favorites` | `true` | Enviar la marca de favorito |
| `push.rejected` | `false` | Envía `rating: -1` para las fotos rechazadas en Facet. Requiere `push.ratings` |
| `push.top_picks_album` | `""` | Nombre opcional de un álbum de Immich que recopila las fotos enviadas por encima del umbral de valoración. Vacío = sin álbum |
| `push.top_picks_min_rating` | `4` | Valoración por estrellas mínima para que una foto se añada a `top_picks_album` |
| `webhook.token_env` | `""` | Variable de entorno que contiene el secreto del webhook entrante; vacío o sin definir desactiva el webhook |
| `webhook.header` | `"x-facet-token"` | Cabecera en la que el flujo de trabajo de Immich envía el token |
| `webhook.max_pending` | `500` | Límite de la lista de rutas recordadas pero sin puntuar, notificada por la siguiente sincronización |
| `timeout_seconds` | `30` | Tiempo de espera REST por solicitud |

`--immich-sync` admite `--dry-run` (empareja cada recurso, no escribe nada) y `--user` (envía las valoraciones de `user_preferences` de ese usuario en modo multiusuario). Facet usa solo la API REST y nunca toca la base de datos de Immich.

## Línea de tiempo

Ajustes para la vista cronológica de línea de tiempo:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `photos_per_group` | `30` | Fotos cargadas por grupo de fecha; un valor más alto muestra más por fecha pero hace las páginas más pesadas |

## Mapa

Ajustes para la vista de mapa interactiva:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | Nivel de zoom en el que los marcadores individuales sustituyen a los grupos; de 1 (mundo) a 18 (calle) |

## Traducción

Ajustes para la traducción de descripciones de IA mediante MarianMT:

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Ajuste | Por defecto | Descripción |
|---------|---------|-------------|
| `target_language` | `"fr"` | Idioma de destino para `--translate-captions`: `fr`, `de`, `es`, `it`, `pt` (portugués de Brasil) |

La traducción usa los modelos MarianMT de Helsinki-NLP en la CPU; no se necesita GPU.

## Aesthetic CLIP (R2)

Una puntuación estética adicional calculada a partir de los embeddings CLIP/SigLIP en caché y prompts de texto. Usa `scripts/benchmark_aesthetic.py` para medir el efecto de un cambio de prompts en AVA.

```json
{
  "aesthetic_clip": {
    "positive_prompts": [
      "a professional, high-quality photograph",
      "an aesthetically beautiful image",
      "a masterful, award-winning photograph",
      "a sharp, well-composed photograph",
      "a stunning, visually striking image"
    ],
    "negative_prompts": [
      "a low-quality, amateur photograph",
      "a blurry, poorly composed photograph",
      "an unattractive, mundane snapshot",
      "a noisy, badly lit photograph",
      "a boring, forgettable image"
    ]
  }
}
```

Los arrays vacíos usan los valores por defecto de `analyzers/aesthetic_clip.py`. Vuelve a ejecutar el benchmark de AVA antes de cambiarlos: los valores por defecto puntúan un SRCC de ~0,52 en `ava_test/`, y las ediciones lo bajan fácilmente a ~0,30.

## Añadir modelos alternativos de etiquetado/crítica VLM (R3)

La clave `tagging_model` de cada perfil (p. ej. `qwen3.5-2b`) nombra una entrada de modelo en la misma sección `models`. Para probar otro VLM (Pixtral-12B, InternVL-2.5, etc.):

1. Añade una entrada de modelo bajo `models`:
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Apunta un perfil a él:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Ejecuta `python facet.py --recompute-tags-vlm` para reetiquetar.

No se necesitan cambios de código. Comprueba ~30 fotos en paralelo antes de convertirlo en el valor por defecto.

## Secreto del servidor

El secreto que firma los tokens de sesión y los enlaces del marco de fotos **no** es una clave de este archivo. Reside en `.facet_secret`, junto a `scoring_config.json` (modo `0600`, ignorado por git), y se genera en el primer arranque.

- Anulación: la variable de entorno `FACET_JWT_SECRET`.
- Rotación: `python database.py --rotate-secret`.

Un `share_secret` de una instalación anterior se traslada a ese archivo en el siguiente arranque y se elimina de `scoring_config.json`. Consulta [Almacenamiento y rotación del secreto](DEPLOYMENT.md#almacenamiento-y-rotación-del-secreto).
