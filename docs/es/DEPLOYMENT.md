# Guía de despliegue

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · **Español** · [Português](../pt/DEPLOYMENT.md) · [简体中文](../zh/DEPLOYMENT.md)

Ejecuta la galería web de Facet en un servidor remoto o NAS.

> **¿Primera vez aquí?** Esta guía es para servir Facet a otras máquinas. Para ponerlo en
> marcha en tu propio equipo, empieza por [Instalación](INSTALLATION.md).

## Visión general

Facet tiene dos cargas de trabajo:

| Componente | Hardware | Propósito |
|-----------|----------|---------|
| **Puntuación** (`facet.py`) | GPU (6-24 GB VRAM) o CPU (8 GB mínimo, 12 GB recomendado de RAM, más para los perfiles `12gb`/`16gb`/`24gb`; consulta [Límites de memoria del contenedor](#límites-de-memoria-del-contenedor)) | Analizar y puntuar fotos |
| **Galería web** (`viewer.py`) | Cualquier máquina (pocos recursos) | Servir la galería web |

Solo la galería web necesita ejecutarse en el servidor. Puntúa en una estación de trabajo y luego sincroniza la base de datos.

> **Advertencia:** mientras `viewer.password` esté vacío (el valor por defecto), cualquiera que pueda llegar al puerto
> de la galería web puede explorar toda la biblioteca y descargar los originales. Define
> `viewer.password` antes de exponer el puerto más allá de la máquina; consulta
> [Modo de un solo usuario](VIEWER.md#modo-de-un-solo-usuario-predeterminado).

En una instalación abierta (sin `viewer.password`), los tokens del asistente (**Conectar un asistente**) solo
se pueden gestionar desde el ordenador donde se ejecuta Facet. Detrás de Docker o de un proxy inverso, define
`viewer.password`, o ejecuta la petición en el host
(`docker compose exec facet python -c "import urllib.request ..."`). Un proxy inverso debe
enviar `X-Forwarded-For` o `Forwarded`; de lo contrario se trata como la máquina local.

## Mapeo de rutas

Cuando la máquina de puntuación y la galería web ven las fotos en rutas diferentes, define
`viewer.path_mapping` en `scoring_config.json` para traducir las rutas de la base de datos a rutas locales.

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

Esto mapea `\\NAS\share\Photos\2024\IMG_001.jpg` a `/volume1/Photos/2024/IMG_001.jpg`.
Usa barras inclinadas en las claves; las barras invertidas se normalizan.

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

- La base de datos conserva las rutas de escaneo originales (p. ej., `\\NAS\share\Photos\2024\IMG_001.jpg`).
- Las miniaturas viven en la base de datos, por lo que navegar no requiere acceso al disco.
- El mapeo se aplica siempre que la galería web abre un original: descargas, vista a resolución completa,
  generación de leyendas y crítica.
- Se admiten tanto las rutas UNC (`\\server\share`) como las letras de unidad (`Z:\`).

## Semántica de rutas en contenedores

En Docker/Podman, cada carpeta que escribes en el visor es una ruta **dentro del contenedor**.
Esto abarca un destino de «Descartar a carpeta», un destino de exportación de álbum y
`viewer.export.allowed_target_dirs`. Usa el punto de montaje, nunca la ruta del host.

**Ejemplo.** El `docker-compose.yml` incluido monta tus fotos en `/data/photos`:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Para descartar los rechazados a una subcarpeta `rejects`, escribe `/data/photos/rejects`, no
`/home/tu/Fotos` ni `D:\Fotos`, que el contenedor no puede ver.

Para escribir fuera del árbol de fotos, monta primero el destino y luego indica su ruta del contenedor en
`viewer.export.allowed_target_dirs`:

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

Un destino fuera de todas las raíces permitidas se rechaza, tras resolver enlaces simbólicos y `..`.
Consulta [Destinos de exportación y descarte](CONFIGURATION.md#destinos-de-exportación-y-descarte).

**Este rechazo no es un problema de permisos.** Ocurre antes de que se toque ningún archivo. Una
discrepancia de uid entre el usuario `facet` del contenedor y tu cuenta del host es un fallo distinto:
ocurre durante la copia/movimiento y se registra con el error del sistema operativo.

### Adónde va la papelera de un contenedor

Con `viewer.cull.allow_trash` activado, `trash_rejects` usa `send2trash`. En la disposición incluida
(fotos montadas con bind en `/data/photos`, uid 1000, `HOME=/home/facet`), las fotos y
`$HOME` están en sistemas de archivos distintos, así que los archivos enviados a la papelera van a la papelera propia del volumen de fotos:

- archivos: `/data/photos/.Trash-1000/files/<nombre>`
- metadatos: `<nombre>.trashinfo` (con `Path=` y `DeletionDate=`) en `/data/photos/.Trash-1000/info/`
- el directorio se crea con modo `0700`

`.Trash-1000` es visible en el **host**, así que un simple `mv` fuera de `files/` restaura una foto.
Los reescaneos lo omiten mientras `scanning.skip_hidden_directories` sea verdadero (el valor por defecto).

Dos excepciones:

- **Sin montaje bind** para las fotos (p. ej. `docker run` con las fotos dentro del contenedor):
  la papelera va a `~/.local/share/Trash` en el contenedor y **se pierde al eliminar el
  contenedor**.
- **Podman sin root**: `.Trash-1000` pertenece al subuid del host asignado, no a tu cuenta;
  restaurar puede requerir `podman unshare`.

Para elegir tú el destino, usa en su lugar `move_rejects` a un `target_dir`
([Descartar a carpeta](VIEWER.md#descartar-a-carpeta)).

### Propiedad del archivo de configuración

Facet solo toma posesión de un `/config/scoring_config.json` que él mismo creó; un archivo existente
conserva su propietario y sus permisos. La única excepción (una configuración que el usuario `facet` del contenedor no puede
leer) y la receta para Podman sin root están en
[Instalación — Propiedad del archivo en el contenedor](INSTALLATION.md#propiedad-del-archivo-en-el-contenedor).

Con `group_add` de compose (véase [Recursos compartidos de fotos legibles solo mediante un grupo](#recursos-compartidos-de-fotos-legibles-solo-mediante-un-grupo-group_add)),
la comprobación de legibilidad también usa esos grupos, así que una configuración legible mediante un grupo así
se deja como está. Si la propia comprobación con `setpriv` falla, el archivo se considera ilegible.

## Compilar el cliente Angular

El servidor sirve la SPA precompilada desde `client/dist/client/browser/`. Compílala antes de
desplegar:

```bash
cd client && npm install && npx ng build && cd ..
```

Esto requiere Node.js 20+ únicamente en tiempo de compilación, no en el servidor.

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
pip3 install fastapi uvicorn pyjwt pillow aiosqlite
```

### Exportar una base de datos ligera

En tu estación de trabajo de puntuación, exporta una base de datos más pequeña para el NAS:

```bash
python database.py --export-viewer-db
```

Esto crea `photo_scores_viewer.db`, que:

- elimina los embeddings de CLIP, de leyendas y faciales;
- conserva el histograma por foto (~2 KB cada uno) para el widget de histograma RGB;
- reduce las miniaturas de 640px a 320px;
- normalmente reduce una base de datos de 14 GB a ~4-5 GB.

Las exportaciones son incrementales: solo se sincronizan las fotos nuevas y modificadas. Para una reconstrucción completa:

```bash
python database.py --export-viewer-db --force-export
```

> **Advertencia:** `--force-export` descarta las valoraciones, ubicaciones y tags manuales establecidos en el
> visor del NAS. Solo una exportación incremental los conserva.

La función «Buscar similares» no funciona en la base de datos exportada (sin embeddings). Usa la máquina
de puntuación para ello.

**Tags manuales.** La exportación incluye los [tags manuales](VIEWER.md#tags-manuales)
(`photo_manual_tags`). Una exportación incremental solo añade los tags de la base de datos de puntuación:

- Un tag quitado en el NAS vuelve si la base de datos de puntuación todavía lo tiene.
- Un tag añadido en el NAS nunca se copia de vuelta; añádelo también en la máquina de puntuación.
- Un tag quitado en la máquina de puntuación permanece en el NAS hasta `--force-export`.
- El límite de 50 tags por foto no se aplica en la fusión, así que una foto puede superarlo.

### Sincronizar archivos

Compila primero el cliente Angular ([Compilar el cliente Angular](#compilar-el-cliente-angular)),
y luego sincroniza con el NAS:

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` lleva los valores predeterminados distribuidos, así que el NAS funciona con ellos. Para usar tu propio
`scoring_config.json`, añádelo a la lista de `rsync`. Revísalo antes: contiene la contraseña
del visor y las claves de API en texto plano.

La galería web abre `photo_scores_pro.db` de forma predeterminada (se puede anular con `DB_PATH`). En el NAS,
establece `DB_PATH=/volume1/facet/photo_scores_viewer.db` o crea un enlace simbólico:

```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Para las descargas, los originales deben estar accesibles en el NAS en la ruta de `path_mapping`.

### Configuración de baja memoria

Añade `viewer.performance` a `scoring_config.json` en el NAS:

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

Esto anula la configuración global de `performance` (ajustada para la puntuación) con valores para 1 GB
de RAM. Consulta [Configuración](CONFIGURATION.md#rendimiento-del-visor).

### Ejecución

```bash
cd /volume1/facet

# Prueba
python3 viewer.py

# Producción (1 worker para 1 GB de RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Abre `http://your-synology-ip:5000`.

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

Usa el proxy inverso de Synology: DSM > Panel de control > Portal de inicio de sesión > Avanzado > Proxy inverso:

| Origen | Destino |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Añade un certificado de Let's Encrypt desde DSM > Panel de control > Seguridad > Certificado.

Para el puente de pestaña para agentes ([Agentes de IA](AGENTS.md)), abre la pestaña **Encabezado personalizado** de la regla
y elige **Crear > WebSocket**. Esto añade las cabeceras `Upgrade` y `Connection` que
necesita `/api/mcp/bridge`. Si la regla reescribe la cabecera `Host`, indica tu origen público en
`viewer.mcp.allowed_origins`.

## NAS Synology (serie Plus / x86)

Los NAS de la serie Plus admiten Docker (Container Manager).

### Ejecutar la imagen publicada

Instala como en [Instalación › Instalar con Docker](INSTALLATION.md#instalar-con-docker):
`docker compose up -d` en un NAS de CPU, o el bloque por perfil con una tarjeta NVIDIA. Los
ajustes de `.env` y el montaje de la configuración están en
[Instalación › Ajustes de Docker que puedes cambiar](INSTALLATION.md#ajustes-de-docker-que-puedes-cambiar).
Lo que sigue es solo lo que difiere en un NAS.

**Las imágenes son únicamente `linux/amd64` (x86_64).** Esto cubre el hardware NAS x86 (Synology
Plus/x86, UGREEN, UnifyDrive, Coolify, Portainer o Docker normal en Intel/AMD). No existe una
imagen `arm64`. En un NAS ARM o una Raspberry Pi, compílala localmente con
`docker compose build`; el archivo compose mantiene `build: .` bajo la clave `image:` para esto.

**Presupuesta el disco:** la imagen más los modelos que cada perfil descarga en el primer arranque.

- Imágenes, descomprimidas: CPU ~3,34 GB, `latest-cuda` (`sm_75`-`sm_120`) ~13,1 GB,
  `latest-cuda-legacy` (`sm_50`-`sm_90`) ~13,8 GB ([Tamaño de la imagen](#tamaño-de-la-imagen)).
  `docker pull` transfiere menos, comprimida.
- Modelos: `legacy` 4,69 GB, `8gb` 6,93 GB, `16gb` 14,55 GB, `24gb` 19,32 GB
  ([Tamaños de descarga](INSTALLATION.md#tamaños-de-descarga)).
- `docker compose down -v` elimina los volúmenes de modelos y fuerza una nueva descarga.

**Etiquetas con versión.** `:latest`, `:latest-cuda` y `:latest-cuda-legacy` se mueven en cada
release. Fija una versión (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7.2-cuda-legacy`, …) en un NAS
que no quieras que cambie bajo tus pies. Las variantes se compilan desde un mismo `Dockerfile` mediante los
argumentos de compilación `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` y `REQUIREMENTS_LOCK`, fijados
en `.github/workflows/docker-publish.yml`. Una ejecución manual `workflow_dispatch` de ese flujo de trabajo
vuelve a publicar `latest` / `latest-cuda` / `latest-cuda-legacy` a partir de `master` sin una release.

**Compilación comercial.** Añade `--build-arg FACET_LICENSING=commercial` (compose:
`build.args.FACET_LICENSING: commercial`). Esto omite el lock restringido (`insightface`,
`pyiqa` y sus dependencias) y fija `FACET_LICENSING_MODE=commercial`. El valor por defecto
`FACET_LICENSING=default` mantiene el comportamiento publicado. El lock restringido sigue a
`REQUIREMENTS_LOCK` (`requirements.legacy.restricted.lock.txt` para el lock legacy). Consulta
[Instalación](INSTALLATION.md#instalación-comercial-y-paquetes-restringidos).

Para una imagen pequeña solo de galería web (sin CUDA), compila una ligera. Cada fuente de `COPY` debe estar
bajo control de git, por eso no se copia `scoring_config.json`; sin él el contenedor
funciona con los valores predeterminados de `config/`.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
COPY viewer.py config_resolve.py database.py tagger.py ./
COPY api/ api/
COPY config/ config/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

> **El puente de pestaña para agentes necesita un solo worker.** Con más de un worker, una llamada `ui_*` puede llegar a
> un proceso que no conoce tu pestaña y responder `no_tab`. Usa `--workers 1` si usas
> los [Agentes de IA](AGENTS.md).

```yaml
services:
  facet:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./photo_scores_pro.db:/app/photo_scores_pro.db
      - /volume1/Photos:/volume1/Photos:ro  # Montar las fotos para las descargas
    restart: always
```

### Recursos compartidos de fotos legibles solo mediante un grupo (`group_add`)

En un NAS, el recurso compartido de fotos suele ser legible solo mediante un grupo (en Synology, normalmente
`users`, gid 100). Da ese grupo al contenedor con `group_add`, usando el gid numérico
de `id <tu-usuario>` en el NAS:

```yaml
services:
  facet:
    group_add:
      - "100"
```

El entrypoint pasa de root a `facet` con `setpriv` y conserva esos gids. Compruébalo con
`docker compose exec facet grep Groups /proc/1/status`: lista `1000` más tus gids.

Alternativa: ejecutar con `user: "1000:1000"` más `group_add`. El entrypoint entonces ni hace chown ni
inicializa `/config`, así que todos los montajes deben ser ya escribibles por el uid 1000.

## Límites de memoria del contenedor

Facet lee el límite de memoria del contenedor (`memory.max` en cgroup v2,
`memory.limit_in_bytes` en v1) en lugar de la RAM del host. Dimensiona según ese límite qué modelos se cargan
juntos, el tamaño del bloque de RAM, el almacenamiento en caché de modelos y la decodificación RAW. Las versiones
anteriores (v1.7.2 y anteriores) ignoraban `mem_limit` y podían ser matadas por OOM
([issue #111](https://github.com/ncoevoet/facet/issues/111)).

### Memoria mínima recomendada por perfil

Los pesos de los modelos son solo una parte del pico de memoria: el runtime de torch, las imágenes decodificadas y
las activaciones se suman a eso. Trata estas cifras como suelos.

| Perfil VRAM | Pesos de los modelos (total) | Memoria de contenedor recomendada |
|---|---|---|
| `legacy` / `8gb` | 15,0 GB | 12 GB (GPU) / 8 GB mínimo, 12 GB recomendado (CPU) |
| `16gb` | 22,0 GB | al menos 18 GB (provisional) |
| `24gb` | 25,0 GB | al menos 18 GB (provisional) |

- **GPU y CPU difieren.** En una GPU los pesos residen en la VRAM, y la RAM contiene principalmente imágenes
  decodificadas: una ejecución `8gb` en una RTX 3080 (405 fotos, `ram_chunk_size: 12`, `num_workers: 2`) alcanzó un pico de
  9,23 GB y se completó con `mem_limit: 12g`. En
  CPU, todos los modelos se cargan en la RAM. Dimensiona según la fila que corresponda a cómo ejecutas.
- **8 GB es un suelo en CPU.** Escaneos de 50 fotos con `--memory=8g` se completaron en `legacy` (pico 7,26 GB) y
  `8gb` (7,56 GB), a menos de medio gigabyte del límite con JPEG de 18-20 MP. Fotogramas más grandes, la decodificación
  RAW o un host cargado necesitan más, de ahí los 12 GB recomendados.
- **`16gb` y `24gb` no están medidos.** 18 GB es un marcador provisional.
- **Vigila la memoria anónima.** El MemUsage de `docker stats` y el `memory.current` del cgroup
  cuentan ambos la caché de páginas recuperable, así que engañan.
- **Almacenamiento en caché de modelos.** Con `models.keep_in_ram` en `"auto"`, un modelo permanece en RAM entre
  fragmentos solo mientras su tamaño más `models.ram_cache_reserve_gb` (por defecto 4 GB) esté libre. Una
  reserva menor almacena más en caché ([Configuración](CONFIGURATION.md#modelos)).

En CPU el perfil `8gb` siempre planifica las mismas 5 pasadas, sea cual sea el límite:
`Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`,
`Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`,
`Pass 5: insightface [~2.0GB RAM]`.

Configura el límite en `docker-compose.yml` (o en un archivo de override):

```yaml
services:
  facet:
    mem_limit: 16g
```

### La agrupación de pasadas tiene un límite máximo, y ningún mínimo

- **Con un límite de contenedor**, cada pasada de CPU recibe el límite menos una reserva de 2 GB, con un techo de
  5 GB. Un límite ajustado significa un modelo por pasada.
- **Sin límite**, el presupuesto es (RAM del sistema − 1 GB) ÷ 1,6. Un host de 4 GB obtiene 1,9 GB por
  pasada, uno de 2 GB, 0,6 GB.
- **Un modelo mayor que el presupuesto** recibe igualmente su propia pasada, con una advertencia que lo nombra. Por
  ejemplo, `qwen3_5_4b_tagger` (`24gb`) por sí solo da una pasada de 8,0 GB.

> **Advertencia:** nunca dimensiones un contenedor por debajo del modelo individual más grande de tu perfil.

## Windows (WSL2) con una GPU NVIDIA

Ejecuta la pila de puntuación en GPU y galería web en Docker en Windows a través de WSL2, sin Docker
Desktop. Todo (la distribución, sus imágenes, `/var/lib/docker`) permanece en una **unidad de datos**
(p. ej. `D:`), útil cuando `C:` anda escasa de espacio.

**Requisitos previos:** un controlador NVIDIA reciente en Windows (`nvidia-smi` funciona en el símbolo
del sistema de Windows). **No** instales ningún controlador dentro de WSL.

### 1. Instalar WSL2 (admin, una sola vez)

En un PowerShell **elevado**, y reinicia si te lo pide:

```powershell
wsl --install --no-distribution   # solo la plataforma WSL2, sin distribución en C:
```

### 2. Instalar una distribución cuyo disco resida en la unidad de datos

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` coloca el `ext4.vhdx` de la distribución bajo `D:\wsl\facet`. `--no-launch` omite el
aviso de primer inicio; los comandos siguientes se ejecutan como `root`.

### 3. Habilitar systemd (necesario para el servicio docker)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # se aplica en el próximo arranque
```

### 4. Instalar Docker CE + el NVIDIA Container Toolkit (dentro de la distribución)

```bash
wsl -d facet -u root
# --- dentro de la distribución ---
apt-get update && apt-get install -y ca-certificates curl gnupg
# Repositorio de Docker (usa el nombre en clave más reciente compatible si el tuyo es demasiado nuevo):
. /etc/os-release; CODE=$VERSION_CODENAME
curl -fsSL -o /dev/null "https://download.docker.com/linux/ubuntu/dists/$CODE/Release" || CODE=noble
install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODE stable" > /etc/apt/sources.list.d/docker.list
# Repositorio del toolkit de NVIDIA (independiente de la distribución):
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
nvidia-ctk config --set nvidia-container-cli.no-cgroups=true --in-place   # WSL2 no tiene cgroup de nvidia
systemctl enable --now docker
# Verificar el passthrough de GPU:
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi --query-gpu=name,memory.total --format=csv
```

### 5. Ejecutar Facet

El repositorio en la unidad de Windows está en `/mnt/d/...` dentro de WSL. Ejecuta el bloque de tu tarjeta
de [Instalación › Instalar con Docker](INSTALLATION.md#instalar-con-docker):

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # o el archivo de tu tarjeta
curl -s localhost:5000/health          # -> ok
```

Añade `--build` para compilar desde el checkout en lugar de descargar la imagen. Los perfiles de GPU
(`8gb`/`12gb`/`16gb`/`24gb`) agrupan los rostros en la GPU mediante el RAPIDS cuML integrado; `legacy`
agrupa en CPU. El primer arranque descarga los modelos en los volúmenes con nombre; restablécelos con
`docker compose down -v`.

### Imagen reproducible y autónoma

- **Versiones fijadas.** La imagen se compila a partir de `requirements.lock.txt`, un `pip freeze` de un
  contenedor validado sin `torch`/`torchvision` ni `nvidia-*` (la imagen base de CUDA los
  proporciona). `kornia`, requerido por BiRefNet, también está fijado ahí. Regenera después de una actualización
  intencionada: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Agrupación de rostros en GPU incluida.** RAPIDS cuML (`cuml-cu12`, ~5,75 GB) permite a los perfiles de GPU
  agrupar en la GPU (`face_clustering.use_gpu="auto"`). `legacy`, y los hosts sin CUDA,
  agrupan en CPU.
- **Sin acoplamiento con el host.** Las cachés de modelos son volúmenes con nombre; el contenedor se ejecuta como el
  usuario sin privilegios `facet`.
- **Contexto de compilación reducido.** `.dockerignore` excluye el contenido voluminoso local (`conda/`, conjuntos de datos de ejemplo,
  `*.db`, cachés); añade ahí los nuevos directorios locales grandes.

### Tamaño de la imagen

Ninguna imagen contiene los pesos de los modelos; esos se descargan en el primer arranque en los volúmenes con nombre
([totales por perfil](INSTALLATION.md#tamaños-de-descarga)). Presupuesta disco para ambos.

| Imagen | En disco (medido) | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 3,34 GB | `python:3.12-slim` + PyTorch en wheels de CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 13,1 GB | PyTorch CUDA 12.8 (`sm_75`-`sm_120`, de Turing a Blackwell) + RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (GPU) | 13,8 GB | PyTorch CUDA 12.6 (`sm_50`-`sm_90`, de Maxwell a Hopper) + RAPIDS cuML |

«En disco» es el tamaño descomprimido (`docker images`). `docker pull` transfiere menos; los tamaños
comprimidos todavía no se han medido.

## Servidor Linux genérico

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

O usa el wrapper (1 worker por defecto; `--workers N` para más):

```bash
python viewer.py --production --workers 4
```

El puente de pestaña para agentes necesita `--workers 1` (consulta
[Ejecutar la imagen publicada](#ejecutar-la-imagen-publicada)).

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

    location /api/mcp/bridge {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $http_host;
        proxy_read_timeout 3600s;
    }
}
```

El puente de pestaña para agentes (`/api/mcp/bridge`, consulta [Agentes de IA](AGENTS.md)) es un WebSocket. Necesita
las cabeceras `Upgrade` y `Connection` del segundo bloque `location` y un único worker
(`--workers 1`, el valor por defecto); de lo contrario las herramientas `ui_*` responden `no_tab`.

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

Usa `--workers 1` si usas el puente de pestaña para agentes.

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

Vuelve a ejecutar la exportación y `rsync` después de cada sesión de puntuación. En un servidor con mucha
memoria, puedes sincronizar en su lugar la base de datos completa `photo_scores_pro.db`.

### Un solo trabajo de biblioteca a la vez

Un escaneo, `--recompute-average`, `--upgrade-db` y un entrenamiento del clasificador reescriben cada uno la
base de datos, así que solo se ejecuta uno a la vez. Un segundo trabajo se niega a arrancar, nombra al que está en curso
y termina con el código 75 (código 1 si el archivo de bloqueo `<db_dir>/.facet_cache/library.lock` es
inutilizable).

> **Advertencia:** este bloqueo funciona **solo en una máquina**. Por SMB/CIFS (p. ej. una
> estación de trabajo Windows que puntúa en un recurso compartido de un NAS), cada máquina tiene su propio bloqueo. Facet registra una
> advertencia pero no puede impedirlo: ejecuta los trabajos de biblioteca desde una sola máquina a la vez. NFS entre
> clientes Linux no se ve afectado.

### Arranque del visor e índices de la galería

El primer inicio tras una actualización desde la 1.20 construye los índices de la galería que faltan
([detalles](VIEWER.md#índices-de-la-galería-y-caché-de-recuentos)). En una biblioteca de ~130k fotos
esto tarda unos minutos y añade aproximadamente 130 MB a la base de datos.

**Recomendado:** tras actualizar, ejecuta `python database.py` (Docker:
`docker compose exec facet python database.py`) una vez **antes** de iniciar el visor. Un
escaneo `python facet.py` también los construye al iniciar.

Si en cambio los construye el visor:

- Sirve mientras construye, pero la galería es lenta y los **guardados (valoraciones, rechazos, cambios de
  álbum…) pueden rechazarse** con un mensaje «biblioteca ocupada, vuelve a intentarlo».
- El registro muestra `Creating index ...` y `Created index ... in N s` por índice, y luego
  `Gallery indexes ready`. `/health` informa del progreso como `gallery_indexes` (`state`:
  `building`, `ready`, `deferred`, `failed` o `stopped`; `done` de `total`).
- Detener el visor conserva los índices terminados; el siguiente inicio continúa.
- Si hay un escaneo u otro trabajo de biblioteca en curso, el visor sirve sin los índices y
  registra una advertencia. Reinícialo cuando termine el trabajo, o ejecuta `python database.py`.
- Si `.facet_cache/library.lock` junto a la base de datos es inutilizable (permisos, montaje de solo
  lectura), el visor no construye. Corrige la ruta y reinicia.
- Con `--workers N`, un worker construye y los demás sirven.
- En Docker, el `start_period` de 30 s del healthcheck no necesita cambios: `/health` responde durante la construcción.

En un SQLite anterior a la 3.48.0 (la imagen de CPU incluye la 3.46.1), la detección de panorámicas no puede leer
solo del nuevo índice; no se midió su rapidez ahí. En un SQLite distinto de la 3.51,
las fotos con marcas de tiempo idénticas pueden agruparse de otro modo en la primera pasada de ráfagas tras
la actualización (consulta el CHANGELOG).

> **Advertencia:** copia o reemplaza la base de datos solo después de detener el visor. Mientras se ejecuta,
> los cambios recientes están en los archivos `-wal` y `-shm`, no solo en el `.db`; un cierre limpio
> los fusiona (también con `performance.wal_checkpoint_minutes: 0`). En Windows el archivo
> no se puede reemplazar en absoluto mientras el visor lo tiene abierto.

## Almacenamiento y rotación del secreto

Un único secreto firma cada sesión de inicio de sesión (JWT) y cada enlace del marco de fotos. Reside en
`.facet_secret` junto a la configuración (modo `0600`, ignorado por git), no en `scoring_config.json`.

Las versiones anteriores lo guardaban como `share_secret` en la configuración, y el valor distribuido era público.
Al iniciar, Facet traslada un `share_secret` residual al archivo del secreto y elimina la clave.
Un valor que el propio Facet publicó se sustituye, lo que cierra la sesión de todos una vez.

| Dónde | Cómo |
|-------|------|
| Por defecto | `.facet_secret` junto a `scoring_config.json`, modo `0600` |
| Contenedor / orquestador | Variable de entorno `FACET_JWT_SECRET` — se lee primero, nunca se escribe en disco |
| Rotación | `python database.py --rotate-secret`, luego reinicia el viewer |

- **Docker:** `/app` es la capa escribible del contenedor, así que un secreto creado ahí se pierde
  al recrearlo y se cierra la sesión de todos con cada actualización de imagen. Define `FACET_JWT_SECRET` en
  `docker-compose.yml`, o monta el archivo con `- ./.facet_secret:/app/.facet_secret`.
- **Rota** siempre que el secreto haya podido filtrarse (una configuración confirmada, una copia de seguridad
  filtrada, un administrador que se marcha). Todos vuelven a iniciar sesión y los dispositivos kiosco piden de nuevo sus enlaces de marco.
- **Varios workers:** crea el secreto antes del primer arranque con `--workers > 1` (ejecuta
  `python database.py --rotate-secret` una vez, arranca una vez con `--workers 1`, o define
  `FACET_JWT_SECRET`). De lo contrario cada worker genera el suyo y las sesiones fallan hasta reiniciar.
- **Directorio de instalación de solo lectura:** el servidor funciona con un secreto en memoria, así que las sesiones mueren
  en cada reinicio. Define `FACET_JWT_SECRET`.
- **Respáldalo** junto con la base de datos; restaurar una base de datos sin él cierra la sesión de todos.

## Configuración multiusuario

Para dar a cada usuario un conjunto privado de directorios de fotos, añade una sección `users` a
`scoring_config.json`. Consulta [Configuración](CONFIGURATION.md#usuarios).

### Inicio rápido

```bash
# En la máquina de puntuación, añade usuarios
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

Las rutas de los directorios deben coincidir con las rutas de las fotos en la base de datos. Con `viewer.path_mapping`,
usa las rutas **mapeadas** (tal como las ve el host de la galería web).

### Migrar valoraciones existentes

Para pasar las valoraciones de un solo usuario a un usuario:

```bash
python database.py --migrate-user-preferences --user alice
```

### Botón de escaneo

Para permitir que la galería web inicie escaneos (el superadmin en modo multiusuario; una sesión de edición en una
instalación de un solo usuario con `viewer.edition_password` no vacía), actívalo. El escaneo se ejecuta en
la máquina de la galería y no requiere GPU ([Sin tarjeta gráfica](INSTALLATION.md#sin-tarjeta-gráfica)):

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

La base de datos puede crecer hasta decenas de gigabytes (~14 GB tras más de 20k fotos), y volver a escanear
cuesta tiempo de GPU. [Litestream](https://litestream.io/) transmite los cambios de forma continua a S3,
B2, GCS, SFTP u otro disco, con restauración a un punto en el tiempo con precisión de unos pocos segundos.

Facet no incluye Litestream. Instálalo en el host que ejecuta Facet; se ejecuta en paralelo
sin cambios en Facet. El checkpoint periódico del WAL de Facet (cada 30 min por defecto,
`performance.wal_checkpoint_minutes`; `0` lo desactiva, un cierre limpio del visor sigue haciendo
checkpoint) mantiene el WAL pequeño.

### Configuración mínima de Litestream

```yaml
# /etc/litestream.yml
dbs:
  - path: /opt/facet/photo_scores_pro.db
    replicas:
      # Almacenamiento de objetos barato; sustituye por el bucket que prefieras.
      - type: s3
        bucket: my-facet-backups
        path: photo_scores_pro
        region: us-east-1
        access-key-id:     $LITESTREAM_AWS_KEY
        secret-access-key: $LITESTREAM_AWS_SECRET
        retention: 72h               # conserva 3 días de historial punto en el tiempo
        snapshot-interval: 24h        # instantánea completa una vez al día
        validation-interval: 6h       # detecta la corrupción pronto
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

`litestream.env` contiene las credenciales de AWS / B2, fuera del YAML.

### Simulacro de restauración

Practícalo antes de necesitarlo:

```bash
sudo systemctl stop facet
sudo systemctl stop litestream
litestream restore -o /tmp/restored.db s3://my-facet-backups/photo_scores_pro
# verificar
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM photos;"
# sustituir
sudo mv /opt/facet/photo_scores_pro.db /opt/facet/photo_scores_pro.bad
sudo mv /tmp/restored.db /opt/facet/photo_scores_pro.db
sudo chown facet:facet /opt/facet/photo_scores_pro.db
sudo systemctl start litestream
sudo systemctl start facet
```

### Coste aproximado

Para una base de datos de 14 GB con ~50 MB/día de rotación de WAL durante la puntuación activa:

- ~0,30 $/mes de almacenamiento en S3 Standard
- ~0,05 $/mes por operaciones PUT

Insignificante comparado con un nuevo escaneo: ~50 horas de GPU en una RTX de 16 GB.
