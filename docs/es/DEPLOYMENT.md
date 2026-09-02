# Guía de despliegue

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · **Español** · [Português](../pt/DEPLOYMENT.md)

Ejecuta la galería web de Facet en un servidor remoto o NAS.

> **¿Primera vez aquí?** Esta guía es para servir Facet a otras máquinas. Para ponerlo en
> marcha en tu propio equipo, empieza por [Instalación](INSTALLATION.md).

## Visión general

Facet tiene dos cargas de trabajo:

| Componente | Hardware | Propósito |
|-----------|----------|---------|
| **Puntuación** (`facet.py`) | GPU (6-24 GB VRAM) o CPU (8 GB mínimo, 12 GB recomendado de RAM, más para los perfiles `16gb`/`24gb` — consulta [Límites de memoria del contenedor](#límites-de-memoria-del-contenedor)) | Analizar y puntuar fotos |
| **Galería web** (`viewer.py`) | Cualquier máquina (pocos recursos) | Servir la galería web |

Solo la galería web necesita ejecutarse en el servidor. Puntúa en una estación de trabajo y luego sincroniza la base de datos.

## Mapeo de rutas

Cuando la máquina de puntuación y el servidor de la galería web acceden a las fotos desde puntos de montaje diferentes, configura `viewer.path_mapping` en `scoring_config.json` para traducir las rutas de la base de datos a rutas locales en disco.

**Ejemplo:** fotos puntuadas en Windows a través de UNC/NFS y servidas desde un NAS Linux:

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Usa **barras inclinadas** en las claves de configuración para mejorar la legibilidad — las barras invertidas se normalizan automáticamente. Esto mapea rutas de la base de datos como `\\NAS\share\Photos\2024\IMG_001.jpg` a `/volume1/Photos/2024/IMG_001.jpg`.

Se admiten varios mapeos (gana la primera coincidencia):

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos",
      "//NAS/share/Archive": "/volume1/Archive"
    }
  }
}
```

**Cómo funciona:**
- La base de datos almacena las rutas de escaneo originales (p. ej., `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Las miniaturas se almacenan como BLOB en la base de datos, por lo que navegar no requiere acceso al disco
- El mapeo de rutas se aplica siempre que la galería web abre un archivo original: descargas, vista a resolución completa, generación de leyendas y crítica
- Se admiten tanto las rutas UNC (`\\server\share`) como las letras de unidad (`Z:\`)
- Gana el primer prefijo coincidente

## Semántica de rutas en contenedores

Todo lo que escribas en un campo de carpeta del visor — un destino de "Descartar a carpeta", el destino de exportación copiar/symlink de un álbum, o `viewer.export.allowed_target_dirs` en `scoring_config.json` — lo resuelve el propio proceso de Facet. **En Docker/Podman ese proceso se ejecuta dentro del contenedor**, así que cada ruta es la ruta que *el contenedor* ve: el punto de montaje, nunca la ruta del lado del host.

**Ejemplo.** El `docker-compose.yml` incluido monta tu carpeta de fotos en `/data/photos`:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Para descartar los rechazados a una subcarpeta `rejects`, escribe `/data/photos/rejects` en el diálogo — nunca la ruta del host (`/home/tu/Fotos`, `D:\Fotos`, …), que el contenedor no puede ver en absoluto. Lo mismo aplica a `viewer.export.allowed_target_dirs`: indica la ruta del lado del contenedor.

Para escribir en un sitio distinto del árbol de fotos escaneado — un volumen de exportación separado, por ejemplo —, móntalo primero en el contenedor y luego añade su ruta del lado del contenedor a `viewer.export.allowed_target_dirs`:

```yaml
services:
  facet:
    volumes:
      - ${PHOTOS_DIR:-./photos}:/data/photos
      - /volume1/Exports:/data/exports   # volumen adicional para la salida de cull/export
```

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    }
  }
}
```

Un destino que se resuelve fuera de todo volumen montado se rechaza (`403`) — la comprobación de target-dir de Facet ejecuta `os.path.realpath()` tanto en la solicitud *como* en cada raíz permitida, resolviendo enlaces simbólicos y `..` antes de comparar, así que una ruta que solo parece correcta desde fuera del contenedor (o un enlace simbólico que apunta fuera de un montaje) sigue fallando la prueba de contención. Consulta [Configuración — Destinos de exportación y descarte](CONFIGURATION.md#destinos-de-exportación-y-descarte) para la referencia completa de la lista de permitidos.

**Esto no es un problema de permisos del usuario del contenedor.** El UID del usuario `facet` dentro del contenedor suele diferir del de tu cuenta del host, y eso puede causar un problema real y separado de permisos del sistema de archivos en un montaje bind — pero eso ocurre *después* de que esta comprobación de ruta se supera, cuando la copia/symlink/movimiento se ejecuta realmente, y se registra en el servidor con el error del sistema operativo subyacente para el archivo fallido. Un `403 target_dir is not an allowed export location` (o un "acceso denegado" genérico en la interfaz) ocurre *antes* de que se toque ningún archivo y no tiene nada que ver con los UID.

## Compilar el cliente Angular

El servidor FastAPI sirve la SPA precompilada desde `client/dist/client/browser/`. Compílala antes del despliegue:

```bash
cd client && npm install && npx ng build && cd ..
```

Esto requiere Node.js 20+ únicamente en tiempo de compilación. Los archivos compilados son recursos estáticos — Node.js no es necesario en el servidor en tiempo de ejecución.

## NAS Synology (DS420j / serie J)

La serie J tiene una CPU ARM, 1 GB de RAM y no admite Docker. La galería web se ejecuta directamente con Python.

### Requisitos previos

1. **Habilitar SSH:** DSM > Panel de control > Terminal y SNMP > Habilitar SSH
2. **Instalar Python3:** Centro de paquetes de DSM, o a través de SSH:
   ```bash
   # Comprobar si está disponible
   python3 --version
   pip3 --version
   ```

### Instalación

```bash
ssh admin@your-synology-ip

# Crear directorio
mkdir -p /volume1/facet

# Instalar dependencias (solo galería web)
pip3 install fastapi uvicorn pyjwt pillow
```

### Exportar una base de datos ligera

En tu estación de trabajo de puntuación, exporta una base de datos reducida para el despliegue en el NAS:

```bash
python database.py --export-viewer-db
```

Esto crea `photo_scores_viewer.db`, que:
- Elimina los embeddings de CLIP, los embeddings de subtítulos y los embeddings faciales
- Conserva el histograma por foto (~2 KB cada uno), que lee el widget de histograma RGB de la galería
- Reduce las miniaturas de 640px a 320px
- Normalmente reduce una base de datos de 14 GB a ~4-5 GB

Las exportaciones son incrementales: si `photo_scores_viewer.db` ya existe, solo se sincronizan las fotos nuevas y modificadas. Usa `--force-export` para una reconstrucción completa:

```bash
python database.py --export-viewer-db --force-export
```

La función "Buscar similares" no funcionará en la base de datos exportada (los embeddings de CLIP se eliminan). Usa la máquina de puntuación para ello.

### Sincronizar archivos

En la máquina de puntuación, compila primero el cliente Angular:

```bash
cd client && npm install && npx ng build && cd ..
```

Luego sincroniza la galería web y la base de datos exportada con el NAS:

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` lleva los valores predeterminados distribuidos, así que no se sincroniza
ningún `scoring_config.json`: el NAS funciona con esos valores a menos que pongas tu
propia anulación junto al visor. Si tienes una en la máquina de puntuación, añádela
a la lista de `rsync` — es un archivo específico de la instalación, así que revísalo
primero (contiene la contraseña del visor y cualquier clave de API en texto plano).

La galería web abre `photo_scores_pro.db` de forma predeterminada (se puede anular con la variable de entorno `DB_PATH`). En el NAS, establece `DB_PATH=/volume1/facet/photo_scores_viewer.db` o crea un enlace simbólico:
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Las fotos originales deben estar accesibles en el NAS en la ruta configurada en `path_mapping` para que las descargas funcionen.

### Configuración de baja memoria

Añade `viewer.performance` a `scoring_config.json` en el NAS para reducir el uso de memoria:

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200,
      "face_cache_size": 50
    }
  }
}
```

Esto anula la configuración global de `performance` (ajustada para la puntuación) con valores adecuados para 1 GB de RAM. Consulta [Configuración](CONFIGURATION.md#rendimiento-del-visor) para más detalles.

### Ejecución

```bash
cd /volume1/facet

# Prueba
python3 viewer.py

# Producción (1 worker para 1 GB de RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Accede en `http://your-synology-ip:5000`

### Inicio automático

DSM > Panel de control > Programador de tareas > Crear > Tarea desencadenada > Script definido por el usuario:

- **Evento:** Arranque
- **Usuario:** root
- **Script:**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Usa el proxy inverso integrado de Synology:

DSM > Panel de control > Portal de inicio de sesión > Avanzado > Proxy inverso:

| Origen | Destino |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Combínalo con un certificado de Let's Encrypt desde DSM > Panel de control > Seguridad > Certificado.

## NAS Synology (serie Plus / x86)

Los NAS de la serie Plus admiten Docker (Container Manager).

### Ejecutar la imagen publicada

Instala exactamente como en
[Instalación › Instalar con Docker](INSTALLATION.md#instalar-con-docker):
`docker compose up -d` para un NAS de CPU, o el bloque por perfil si el equipo tiene una
tarjeta NVIDIA. Los controles de `.env` y el montaje de la configuración están
documentados en
[Instalación › Ajustes de Docker que puedes cambiar](INSTALLATION.md#ajustes-de-docker-que-puedes-cambiar).
Lo que sigue es solo lo que difiere en un NAS.

**Las tres imágenes publicadas son únicamente `linux/amd64` (x86_64).** Esto cubre el
hardware NAS x86 (Synology Plus/x86, UGREEN, UnifyDrive y cualquier equipo que ejecute
Coolify, Portainer o Docker normal en una CPU Intel/AMD). No existe una imagen `arm64`:
la compilación cruzada de una pila de ML de varios gigabytes bajo QEMU cuesta horas por
etiqueta, y las variantes CUDA son de todos modos exclusivas de x86. En un NAS ARM o una
Raspberry Pi, compílala localmente con `docker compose build` en lugar de descargarla —
`docker compose up` mantiene `build: .` bajo la clave `image:` precisamente para este
caso.

**Presupuesta el disco.** Ya descomprimida, la imagen CPU pesa aproximadamente
3,34 GB en disco, la imagen CUDA (`latest-cuda`, `sm_75`-`sm_120`) aproximadamente
13,1 GB, y la imagen CUDA legacy (`latest-cuda-legacy`, `sm_50`-`sm_90`)
aproximadamente 13,8 GB — ver [Tamaño de la imagen](#tamaño-de-la-imagen) más
abajo para saber cómo se midieron estas cifras; `docker pull` transfiere menos
que eso, comprimida. Presupuesta espacio en disco para la imagen **más** los
pesos de los modelos que cada perfil descarga en el primer arranque (`legacy`
4,69 GB, `8gb` 6,93 GB, `16gb` 14,55 GB, `24gb` 19,13 GB — tabla completa en
[Instalación › Tamaños de descarga](INSTALLATION.md#tamaños-de-descarga)). `docker
compose down -v` elimina los volúmenes de modelos y fuerza una nueva descarga.

**Etiquetas con versión.** `:latest`, `:latest-cuda` y `:latest-cuda-legacy` se mueven en cada release; fija una versión (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7.2-cuda-legacy`, …) en un NAS que no quieras que cambie bajo tus pies. Las tres variantes se compilan desde el mismo `Dockerfile` mediante los argumentos de compilación `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` y `REQUIREMENTS_LOCK`, fijados por variante en `.github/workflows/docker-publish.yml`. Ese flujo de trabajo también acepta una ejecución manual `workflow_dispatch`, que vuelve a publicar `latest` / `latest-cuda` / `latest-cuda-legacy` a partir de `master` sin cortar una release ni acuñar una etiqueta con versión.

Para un NAS de solo galería web donde la imagen debe permanecer pequeña (sin CUDA), compila una imagen ligera en su lugar. Ten en cuenta que la protección de CI exige que cada fuente de `COPY` esté bajo control de git, por lo que el contexto de compilación debe incluir los archivos listados — por lo que no se copia ningún `scoring_config.json`: ese archivo es una anulación específica de la instalación, sin control de versiones, y su ausencia solo significa que el contenedor funciona con los valores predeterminados dentro de `config/`.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow
COPY viewer.py config_resolve.py database.py tagger.py ./
COPY api/ api/
COPY config/ config/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

```yaml
services:
  facet:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./photo_scores_pro.db:/app/photo_scores_pro.db
      - /volume1/Photos:/volume1/Photos:ro  # Mount photos for downloads
    restart: always
```

## Límites de memoria del contenedor

Facet ahora lee el límite de memoria del cgroup del contenedor (`memory.max` en cgroup v2, `memory.limit_in_bytes` en v1) en lugar de la RAM total del host, y dimensiona en función de ese límite la agrupación de pasadas (qué modelos se cargan juntos), el tamaño del bloque de RAM, el almacenamiento en caché de modelos en CPU y la concurrencia de decodificación RAW. Antes de esta corrección, todo eso se dimensionaba según la RAM del host: `psutil.virtual_memory()` lee `/proc/meminfo`, que Docker no virtualiza, así que un `mem_limit` se ignoraba silenciosamente — un contenedor limitado muy por debajo de la RAM del host seguía planificándose como si tuviera toda la RAM del host disponible, y terminaba muerto por OOM ([issue #111](https://github.com/ncoevoet/facet/issues/111)).

Reproducir el error en una imagen publicada anterior a la corrección (v1.7.2) muestra el mecanismo: un contenedor con perfil `8gb` limitado a `--memory=8g` en un host de 47 GB registra `Mode: CPU-only (47GB RAM)` — la RAM del host, no la del contenedor — y planifica una sola pasada agrupando `clip + topiq_iaa + topiq_nr_face + liqe + saliency + samp_net + insightface [~15.0GB RAM]`. Se le mata (`OOMKilled`, código de salida 137) antes de terminar siquiera un lote de las 200 fotos. Frente a un límite de cgroup de 512 MB, el lector corregido reporta 0,500 GB donde `/proc/meminfo` sigue reportando los 46,8 GB del host.

### Memoria mínima recomendada por perfil

Los pesos de los modelos son solo una parte del pico de memoria — el runtime de torch, el bloque de imagen decodificada y las activaciones por capa se suman a eso — así que trata estas cifras como suelos, no como presupuestos. La fila `legacy`/`8gb` ahora se apoya en pruebas reales en contenedor — escaneos de 50 fotos que se completan con `--memory=8g` en ambos perfiles (ver más abajo); las filas `16gb` y `24gb` siguen siendo marcadores provisionales sin ninguna medición real detrás.

| Perfil VRAM | Pesos de los modelos (total) | Memoria de contenedor recomendada |
|---|---|---|
| `legacy` / `8gb` | 15,0 GB | 12 GB (GPU) / 8 GB mínimo, 12 GB recomendado (CPU) |
| `16gb` | 22,0 GB | al menos 18 GB (provisional) |
| `24gb` | 25,0 GB | al menos 18 GB (provisional) |

**GPU y CPU no son intercambiables aquí, y la cifra de 12 GB de arriba es una cifra de GPU.** En una RTX 3080, el perfil `8gb` del autor del informe alcanzó un pico de 9,23 GB de RAM del sistema para 405 fotos, incluso con `ram_chunk_size: 12` y `num_workers: 2`, y tuvo éxito con `mem_limit: 12g`. En una GPU, los pesos de los modelos residen en la VRAM; la RAM del contenedor contiene principalmente el bloque de imagen decodificada, por lo que esa cifra es mucho más pequeña que lo que necesita el CPU en solitario. Ejecutar ese mismo perfil `8gb` en CPU carga en cambio todo el catálogo de modelos en la RAM del contenedor. Antes de que la corrección de seguimiento del issue #111 añadiera un techo, la capacidad por pasada del planificador escalaba directamente con el límite del contenedor, lo que empeoraba el plan, no lo mejoraba, a medida que crecía el límite: un límite de 8 GB producía 4 pasadas que llegaban hasta 6,0 GB, provocando un OOM en la pasada que agrupa `topiq_nr_face + liqe + saliency` (6,0 GB declarados, pico de RSS de 10,46 GB); un límite de 12 GB se reducía a solo 2 pasadas que llegaban hasta 10,0 GB, y también provocaba un OOM. El regulador de memoria sí se activó en el límite de 12 GB — `Evicted 1 model(s) from RAM cache: topiq_iaa` es una línea de registro real —, pero eso era el regulador interviniendo y aun así sin ser suficiente, no lo que salvó la ejecución.

El techo ahora mantiene la capacidad por pasada en 5,0 GB sin importar cuán grande sea el límite del contenedor, así que deja de crecer con el contenedor: el perfil `8gb` en CPU siempre planifica las mismas 5 pasadas sea cual sea el límite — `Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`, `Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`, `Pass 5: insightface [~2.0GB RAM]`.

Esa forma fija por sí sola seguía sin ser suficiente, porque había dos cosas fuera del plan de pasadas que gastaban el presupuesto. El ajuste automático del tamaño del lote crecía en el valle de memoria entre pasadas — cada descarga hace caer el uso casi hasta el suelo, y tres lecturas seguidas de ese tipo se leían como margen — así que `ram_chunk_size` pasó de 10 a 500 durante el primerísimo lote, y el segundo intentó decodificar todas las fotos restantes de golpe. Y descargar un modelo no le devolvía nada al kernel: glibc conservaba los bloques liberados en sus arenas, de modo que el proceso mantenía un máximo histórico fijado por su primera pasada, y cada pasada posterior se ejecutaba sobre memoria que no podía usar. Con el crecimiento decidido ahora a partir del pico de cada lote y el heap liberado devuelto explícitamente, un escaneo de 50 fotos con `--memory=8g` se completa en ambos perfiles — `legacy` alcanzando un pico de 7,26 GB y `8gb` de 7,56 GB de memoria anónima, cinco lotes de diez, código de salida 0, sin OOM y sin fallo de escaneo registrado.

**8 GB es un suelo, no un presupuesto cómodo.** Ambas ejecuciones terminaron a menos de medio gigabyte del límite, con JPEG de 18-20 MP; imágenes más grandes, la decodificación RAW o un host más cargado erosionarán ese margen, por lo que 12 GB es la recomendación en vez del mínimo. La memoria anónima es la cifra a vigilar — ni el MemUsage de `docker stats` ni el `memory.current` del cgroup, que cuentan ambos la caché de páginas recuperable, así que el primero infravalora el riesgo real y el segundo se queda anclado cerca del límite del contenedor sin importar cuánto margen quede realmente. Se midió un contenedor de 16 GB con al menos 12,55 GB de memoria anónima, lo que también explica por qué una ejecución anterior de 12 GB fue matada antes de que estas dos correcciones llegaran, y coincide con el pico de 9,23 GB que reportó el autor del informe en GPU — el mismo catálogo de modelos, menos lo que reside en la VRAM en vez de en la RAM del contenedor. Un usuario de GPU que se guiara por las cifras de CPU de aquí sobredimensionaría; un usuario de CPU que se guiara por la cifra de GPU infradimensionaría — usa la que corresponda a cómo se ejecuta realmente tu contenedor.

De forma más general: `MODEL_RAM_REQUIREMENTS` solo tasa el coste de los pesos. El pico real de RSS añade además el runtime de torch, el bloque de imagen decodificada y las activaciones por capa, ninguno de los cuales está en esa cifra — dimensionar un contenedor solo a partir de la columna pesos de los modelos (total) lo infradimensionará.

Las estimaciones de `16gb` y `24gb` todavía no tienen ninguna ejecución real detrás, ni en GPU ni en CPU; trata 18 GB como un marcador provisional, no como un suelo validado.

Configura el límite en `docker-compose.yml` (o en un archivo de override):

```yaml
services:
  facet:
    mem_limit: 16g
```

### La agrupación de pasadas tiene un límite máximo, y ningún mínimo

El planificador de pasadas de Facet presupuesta cada pasada de CPU al límite de memoria del cgroup del contenedor menos una reserva de 2 GB para el runtime de torch, con un techo de 5 GB que nunca deja crecer una pasada por grande que sea el límite. No hay un suelo bajo ese límite: un contenedor con poco margen tras la reserva recibe un presupuesto pequeño, que puede bajar hasta cero, lo que simplemente aísla un modelo por pasada.

Cuando no hay ningún límite de memoria de contenedor, el presupuesto sale en cambio de la RAM del sistema: lo que la máquina tiene aparte de su sistema operativo (1 GB reservado para él), dividido entre 1,6 — la proporción medida entre la RSS real y el peso declarado de los modelos. Ese camino tampoco tiene suelo: un host de 4 GB presupuesta 1,9 GB por pasada y uno de 2 GB, 0,6 GB. Las versiones anteriores mantenían aquí un mínimo optimista de 4 GB, que era exactamente el defecto que describe esta página vestido de bare metal: planificaba una pasada de 5 GB dentro de una máquina de 4 GB.

Un modelo más grande que el presupuesto recibe igualmente su propia pasada en lugar de dividirse, y **cada una** de esas pasadas se nombra en una advertencia, no solo la más pesada: con un límite de contenedor de 4 GB, la capacidad es de 2 GB, y el perfil `24gb` todavía planifica una pasada de 8,0 GB, porque `qwen3_5_4b_tagger` por sí solo necesita 8 GB y no se puede dividir, por pequeño que sea el presupuesto. Nunca dimensiones un contenedor por debajo del modelo individual más grande del perfil que uses.

## Windows (WSL2) con una GPU NVIDIA

Ejecuta la pila completa de scoring + galería web en GPU con Docker en Windows a través de WSL2 — sin Docker Desktop. Esto mantiene todo (la distribución Linux, sus imágenes Docker y `/var/lib/docker`) en una **unidad de datos** (p. ej. `D:`), lo cual importa cuando la unidad de sistema `C:` anda escasa de espacio.

**Requisitos previos:** un controlador NVIDIA reciente en Windows (`nvidia-smi` funciona en el símbolo del sistema de Windows — el controlador proporciona el passthrough de CUDA para WSL2; **no** instalas ningún controlador dentro de WSL).

### 1. Instalar WSL2 (admin, una sola vez)

En un PowerShell **elevado** (ejecutado como administrador), y reinicia si te lo pide:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Instalar una distribución cuyo disco resida en la unidad de datos

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` coloca el `ext4.vhdx` de la distribución bajo `D:\wsl\facet`, de modo que el almacén de imágenes de Docker se mantiene fuera de `C:`. `--no-launch` omite el aviso interactivo de primer inicio; los comandos siguientes se ejecutan como `root`, lo cual es correcto para una máquina de propósito único.

### 3. Habilitar systemd (necesario para el servicio docker)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # apply on next start
```

### 4. Instalar Docker CE + el NVIDIA Container Toolkit (dentro de la distribución)

```bash
wsl -d facet -u root
# --- inside the distro ---
apt-get update && apt-get install -y ca-certificates curl gnupg
# Docker repo (fall back to the newest supported codename if yours is too new):
. /etc/os-release; CODE=$VERSION_CODENAME
curl -fsSL -o /dev/null "https://download.docker.com/linux/ubuntu/dists/$CODE/Release" || CODE=noble
install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODE stable" > /etc/apt/sources.list.d/docker.list
# NVIDIA toolkit repo (distribution-agnostic):
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
nvidia-ctk config --set nvidia-container-cli.no-cgroups=true --in-place   # WSL2 has no nvidia cgroup
systemctl enable --now docker
# Verify GPU passthrough:
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi --query-gpu=name,memory.total --format=csv
```

### 5. Ejecutar Facet

El repositorio en la unidad de Windows es visible dentro de WSL en `/mnt/d/...`. Desde
ahí, ejecuta el bloque de tu tarjeta desde
[Instalación › Instalar con Docker](INSTALLATION.md#instalar-con-docker):

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # o el archivo de tu tarjeta
curl -s localhost:5000/health          # -> ok
```

Añade `--build` para compilar desde el checkout en lugar de descargar la imagen
publicada. Los perfiles de GPU (`8gb`/`16gb`/`24gb`) agrupan los rostros en la GPU
mediante el RAPIDS cuML integrado; el perfil legacy siempre agrupa en CPU. El primer
arranque descarga los modelos del perfil en los volúmenes con nombre; restablécelos con
`docker compose down -v`.

### Imagen reproducible y autónoma

- **Versiones fijadas.** La imagen se compila a partir de `requirements.lock.txt` — un `pip freeze` completo de un contenedor validado con `torch`/`torchvision` y `nvidia-*` eliminados (la imagen base de CUDA ya los proporciona). Esto evita la deriva silenciosa hacia versiones no probadas. (Ejemplo de lo que esto evita: transformers 5.3 cambió el procesamiento por lotes de visión de Qwen3.5 y rompió el etiquetador VLM hasta que llegó la corrección de padding; `kornia`, requerido por BiRefNet, no lo arrastra transformers y debe fijarse.) Regenera después de una actualización intencionada: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Agrupación de rostros en GPU integrada.** RAPIDS cuML (`cuml-cu12`) viene incluido en la imagen, así que los perfiles de GPU (8gb/16gb/24gb) agrupan los rostros en la GPU (HDBSCAN vía `face_clustering.use_gpu="auto"`); el perfil legacy — y cualquier host sin dispositivo CUDA — siempre agrupa en CPU. cuML es, con diferencia, la mayor dependencia (~5,75 GB; consulta el desglose de tamaños más abajo).
- **Sin acoplamiento con el host.** Las cachés de modelos son volúmenes con nombre, no montajes del host; el contenedor se ejecuta sin privilegios (el punto de entrada predeterminado cambia al usuario `facet`).
- **Contexto de compilación reducido.** `.dockerignore` excluye el contenido voluminoso solo local (`conda/`, conjuntos de datos de ejemplo, `*.db`, cachés, artefactos de desarrollo) — mantén los nuevos directorios locales grandes fuera del contexto añadiéndolos ahí.

### Tamaño de la imagen

Ninguna de las tres imágenes publicadas contiene los pesos de los modelos — esos se
descargan en el primer arranque en los volúmenes con nombre
([totales por perfil](INSTALLATION.md#tamaños-de-descarga)). Presupuesta espacio en
disco para la imagen **más** esos volúmenes.

| Imagen | En disco (medido) | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 3,34 GB | `python:3.12-slim` + PyTorch en wheels de CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 13,1 GB | PyTorch CUDA 12.8 (`sm_75`-`sm_120`, de Turing a Blackwell) + RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (GPU) | 13,8 GB | PyTorch CUDA 12.6 (`sm_50`-`sm_90`, de Maxwell a Hopper) + RAPIDS cuML |

Las tres imágenes base cambiaron en esta versión (issue #119). "En disco" es la
huella de la imagen ya descomprimida, medida localmente (`docker images`) sobre
imágenes compiladas desde esta rama — un desglose por componente (RAPIDS cuML
frente a runtime de CUDA frente a PyTorch frente a SO base) no se volvió a medir
en esta pasada. `docker pull` transfiere una descarga comprimida más pequeña que
estas cifras; una columna "descarga comprimida" volverá aquí en cuanto se
publiquen estas imágenes y haya un manifiesto de registro real desde el que
medirla.

## Servidor Linux genérico

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

O usa el wrapper (predeterminado a 1 worker; pasa `--workers N` para más):

```bash
python viewer.py --production --workers 4
```

### Uvicorn + Nginx

```nginx
server {
    listen 80;
    server_name photos.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 50M;
    }
}
```

Añade HTTPS:
```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Servicio Systemd

```ini
# /etc/systemd/system/facet.service
[Unit]
Description=Facet Viewer
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/facet
ExecStart=/usr/local/bin/uvicorn api:create_app --factory --host 127.0.0.1 --port 5000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now facet
```

### Caddy (HTTPS automático)

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## Flujo de trabajo

```
 Scoring Machine (GPU)                      Server / NAS
 ─────────────────────                      ─────────────
 python facet.py /photos
         │
         ├─ database.py --export-viewer-db
         │       │
         │       └─ photo_scores_viewer.db ──rsync──▶ viewer.py serves gallery
         └─ scoring_config.json ────────────────────▶ (with path_mapping +
                                                       viewer.performance)
                                                        │
                                                 http://nas:5000
```

Vuelve a ejecutar la exportación y `rsync` después de cada sesión de puntuación para actualizar la base de datos en el servidor. En servidores con mucha memoria, puedes sincronizar directamente la base de datos completa `photo_scores_pro.db` en lugar de exportarla.

### Un solo trabajo de biblioteca a la vez

Un escaneo, `--recompute-average`, `--upgrade-db` y un entrenamiento del clasificador personal reescriben cada uno toda la base de datos, así que Facet solo permite uno a la vez: cada uno toma un archivo de bloqueo en `<db_dir>/.facet_cache/library.lock`, y un segundo trabajo se niega a arrancar y nombra al que ya está en curso.

Ese bloqueo es un bloqueo de archivo del núcleo, por lo que excluye trabajos **solo en una máquina**. Cuando se accede a la base de datos por SMB/CIFS —por ejemplo, una estación de trabajo Windows que puntúa fotos en un recurso compartido de un NAS—, cada máquina toma su propia copia del bloqueo y ninguna ve a la otra. Facet detecta el montaje y registra una advertencia al tomar el bloqueo, pero no puede imponer nada entre máquinas: ejecuta los trabajos de biblioteca desde una sola máquina a la vez. NFS entre clientes Linux no se ve afectado: allí `flock` se convierte en un bloqueo de registro POSIX que el servidor arbitra.

## Almacenamiento y rotación del secreto

Un único secreto firma cada sesión de inicio de sesión (JWT) y cada enlace del marco de fotos. **No** es una clave de `scoring_config.json`: reside en `.facet_secret`, junto a la configuración, creado con modo `0600` en el primer arranque e ignorado por git.

Antes era la clave `share_secret` dentro de `scoring_config.json`. Ese archivo está bajo control de git, así que el valor generado en el primer arranque se confirmó y se publicó — el secreto que distribuyó este proyecto es público y debe considerarse comprometido. En el siguiente arranque Facet traslada cualquier `share_secret` residual al archivo del secreto, elimina la clave de la configuración y registra una advertencia. Un valor que el propio Facet publicó se sustituye en lugar de conservarse, lo que cierra la sesión de todos a propósito.

| Dónde | Cómo |
|-------|------|
| Por defecto | `.facet_secret` junto a `scoring_config.json`, modo `0600` |
| Contenedor / orquestador | Variable de entorno `FACET_JWT_SECRET` — se lee primero, nunca se escribe en disco |
| Rotación | `python database.py --rotate-secret`, luego reinicia el viewer |

En Docker, `/app` es la capa escribible del contenedor: un secreto creado ahí se pierde al recrear el contenedor — con cada actualización de imagen se cierra la sesión de todos. Define `FACET_JWT_SECRET` en `docker-compose.yml`, o monta el archivo con `- ./.facet_secret:/app/.facet_secret`.

Rota siempre que el secreto haya podido ser leído por otra persona: una configuración que se confirmó alguna vez, una copia de seguridad filtrada, un administrador que se marcha. La rotación invalida cada sesión y cada URL firmada del marco: los usuarios vuelven a iniciar sesión y los dispositivos kiosco piden enlaces nuevos.

Con `--workers > 1` todos los workers leen el mismo archivo, así que un JWT firmado por uno se valida en todos — **una vez que ese archivo existe**. Un primer arranque con `--workers > 1` y sin `.facet_secret` es la excepción: cada worker genera su propio secreto y solo uno gana la escritura, de modo que una sesión abierta en un worker es rechazada por los demás hasta que se reinicia el servidor. Crea el secreto antes del primer arranque multi-worker — ejecuta una vez `python database.py --rotate-secret`, arranca una vez con `--workers 1`, o define `FACET_JWT_SECRET`.

Esa misma divergencia se vuelve permanente cuando el directorio de instalación no es escribible: el servidor registra un error y funciona con un secreto en memoria, así que cada sesión muere en cada reinicio y cada worker firma con una clave distinta. Define allí `FACET_JWT_SECRET`.

Respalda el archivo junto con la base de datos — restaurar una base de datos sin él cierra la sesión de todos.

## Configuración multiusuario

Para dar a cada usuario un conjunto privado de directorios de fotos, añade una sección `users` a `scoring_config.json`. Consulta [Configuración](CONFIGURATION.md#usuarios) para la referencia completa.

### Inicio rápido

```bash
# On the scoring machine, add users
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Luego edita `scoring_config.json`:

```json
{
  "users": {
    "alice": {
      "password_hash": "...",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "...",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family"
    ]
  }
}
```

Las rutas de directorio deben coincidir con las rutas de las fotos almacenadas en la base de datos. Si usas `viewer.path_mapping`, los directorios deben usar las rutas **mapeadas** (tal como aparecen en el host de la galería web).

### Migrar valoraciones existentes

Si tenías valoraciones en modo de un solo usuario, migrarlas a un usuario:

```bash
python database.py --migrate-user-preferences --user alice
```

### Botón de escaneo

Para permitir que el superadmin desencadene escaneos de fotos desde la interfaz de la galería web (solo útil cuando la galería web se ejecuta en la máquina con GPU):

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Copias de seguridad continuas con Litestream

La base de datos SQLite puede crecer hasta decenas de gigabytes (`photo_scores_pro.db` alcanza ~14 GB tras puntuar más de 20 000 fotos), y un nuevo escaneo cuesta tiempo de GPU. [Litestream](https://litestream.io/) transmite el WAL a S3, B2, GCS, SFTP u otro disco local de forma continua, con restauración a un punto en el tiempo con precisión de unos pocos segundos.

Facet no incluye Litestream. Instálalo una vez en el host que ejecuta la galería web/puntuación; se ejecuta como un proceso sidecar, transparente para la aplicación.

Facet ya usa el modo WAL (`db/connection.py:apply_pragmas`), y el hilo periódico de checkpoint (predeterminado cada 30 min, configurable mediante `performance.wal_checkpoint_minutes`) mantiene el WAL acotado. Las lecturas no se bloquean durante la replicación.

### Configuración mínima de Litestream

```yaml
# /etc/litestream.yml
dbs:
  - path: /opt/facet/photo_scores_pro.db
    replicas:
      # Cheap object storage; replace with the bucket of your choice.
      - type: s3
        bucket: my-facet-backups
        path: photo_scores_pro
        region: us-east-1
        access-key-id:     $LITESTREAM_AWS_KEY
        secret-access-key: $LITESTREAM_AWS_SECRET
        retention: 72h               # keep 3 days of point-in-time history
        snapshot-interval: 24h        # full snapshot once per day
        validation-interval: 6h       # detect corruption early
```

### Unidad de Systemd

```ini
# /etc/systemd/system/litestream.service
[Unit]
Description=Litestream continuous SQLite replication
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/litestream replicate -config /etc/litestream.yml
Restart=always
User=facet
EnvironmentFile=/etc/litestream.env

[Install]
WantedBy=multi-user.target
```

`litestream.env` contiene las credenciales de AWS / B2 para mantenerlas fuera del YAML.

### Simulacro de restauración

Practícalo antes de necesitarlo:

```bash
sudo systemctl stop facet
sudo systemctl stop litestream
litestream restore -o /tmp/restored.db s3://my-facet-backups/photo_scores_pro
# verify
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM photos;"
# swap in
sudo mv /opt/facet/photo_scores_pro.db /opt/facet/photo_scores_pro.bad
sudo mv /tmp/restored.db /opt/facet/photo_scores_pro.db
sudo chown facet:facet /opt/facet/photo_scores_pro.db
sudo systemctl start litestream
sudo systemctl start facet
```

### Coste aproximado

Para la base de datos de 14 GB con ~50 MB/día de rotación de WAL durante la puntuación activa, espera:
- ~0,30 $/mes de almacenamiento en S3 Standard
- ~0,05 $/mes por operaciones PUT
Insignificante comparado con un nuevo escaneo: ~50 horas de GPU en una RTX de 16 GB.
