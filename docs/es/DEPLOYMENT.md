# Guía de despliegue

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · **Español** · [Português](../pt/DEPLOYMENT.md)

Ejecuta la galería web de Facet en un servidor remoto o NAS.

## Visión general

Facet tiene dos cargas de trabajo:

| Componente | Hardware | Propósito |
|-----------|----------|---------|
| **Puntuación** (`facet.py`) | GPU (6-24 GB VRAM) o CPU (8 GB+ de RAM) | Analizar y puntuar fotos |
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
- Elimina los embeddings de CLIP, los datos de histograma y los embeddings faciales
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
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

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

Esto anula la configuración global de `performance` (ajustada para la puntuación) con valores adecuados para 1 GB de RAM. Consulta [Configuración](CONFIGURATION.md#viewer-performance) para más detalles.

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

### Descargar (pull) la imagen publicada

`docker-compose.yml` y `docker-compose.gpu.yml` llevan una clave `image:` junto a `build: .`, así que `docker compose up` **descarga (pull)** una imagen precompilada desde GHCR en lugar de compilar localmente el stack CPU de ~3,3 GB (o el stack CUDA de ~21 GB):

```bash
# Solo galería web (CPU) — descarga ghcr.io/ncoevoet/facet:latest
docker compose up -d

# Con GPU NVIDIA para puntuación (requiere el NVIDIA Container Toolkit) —
# descarga ghcr.io/ncoevoet/facet:latest-cuda
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`docker compose build` (o `up --build`) sigue compilando desde el `Dockerfile` de este repositorio para experimentar en local — la clave `build:` se mantiene bajo `image:` precisamente para eso. Las capas por perfil (`docker-compose.{8gb,16gb,24gb}.yml`) también descargan `:latest-cuda`, ya que las tres son perfiles de GPU; `docker-compose.legacy.yml` (CPU) descarga la imagen base `:latest`.

**Dos etiquetas publicadas, un solo Dockerfile.** `ghcr.io/ncoevoet/facet:latest` es una compilación ligera solo para CPU (sin runtime de CUDA, sin RAPIDS cuML — la agrupación de rostros recurre a HDBSCAN en CPU). `ghcr.io/ncoevoet/facet:latest-cuda` es el stack completo de CUDA + cuML descrito a lo largo de este documento, idéntico a un `docker build .` local. Ambas provienen del mismo `Dockerfile`, parametrizado mediante argumentos de compilación (`BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`) fijados por variante en `.github/workflows/docker-publish.yml`. Las etiquetas con versión (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7-cuda`, …) se publican junto a `latest`/`latest-cuda` en cada etiqueta git `vX.Y.Z`.

**Publicar sin una release.** `.github/workflows/docker-publish.yml` también acepta un disparador manual `workflow_dispatch` desde el botón *Run workflow* de la pestaña Actions, independiente del push de etiqueta `vX.Y.Z` anterior — reconstruye y vuelve a publicar `latest`/`latest-cuda` a partir del estado actual de `master`, sin necesidad de cortar una release. No genera una etiqueta con versión: los patrones `type=semver` de `docker/metadata-action` solo se disparan con una etiqueta git `vX.Y.Z` real, así que una ejecución manual solo mueve `latest`/`latest-cuda`.

**Ambas imágenes publicadas son únicamente `linux/amd64` (x86_64).** Esto cubre el hardware NAS x86 (Synology Plus/x86, UGREEN, UnifyDrive y cualquier equipo que ejecute Coolify, Portainer o Docker normal en una CPU Intel/AMD). No existe una imagen `arm64`: la compilación cruzada de una pila de ML de varios gigabytes bajo QEMU cuesta horas por etiqueta, y la variante CUDA es de todos modos exclusiva de x86. En un NAS ARM o una Raspberry Pi, compílala localmente con `docker compose build` en lugar de descargarla — `docker compose up` mantiene `build: .` bajo la clave `image:` precisamente para este caso.

> **Solo en la primera publicación:** un paquete GHCR nuevo es **privado** de forma predeterminada. Tras la primera ejecución del flujo de trabajo `docker-publish`, un propietario debe cambiar `ghcr.io/ncoevoet/facet` a **público** (Settings del paquete → Change visibility) — de lo contrario, un `docker compose up` desde un clon nuevo fallará al descargar con un error 401. Ese cambio ya se hizo para `ghcr.io/ncoevoet/facet` — `:latest` (la compilación ligera para CPU, ~3,3 GB) y `:latest-cuda` se descargan ambas de forma anónima hoy; por ahora solo existen esas dos etiquetas, las etiquetas con versión (`:1.7.2`, …) aparecerán la primera vez que se haga push de una etiqueta `vX.Y.Z`.

`scoring_config.json` se monta como un volumen (no se integra en la imagen), así que edítalo en el host y reinicia. La ruta de la base de datos se establece con `DB_PATH` (predeterminado `/app/data/photo_scores_pro.db`). Las cachés de modelos persisten en `./model-cache/`, por lo que sobreviven a los reinicios.

Para un NAS de solo galería web donde la imagen debe permanecer pequeña (sin CUDA), compila una imagen ligera en su lugar. Ten en cuenta que la protección de CI exige que cada fuente de `COPY` esté bajo control de git, por lo que el contexto de compilación debe incluir los archivos listados:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow
COPY viewer.py config.py database.py tagger.py scoring_config.json ./
COPY api/ api/
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

### 5. Compilar y ejecutar Facet, un archivo por perfil

El repositorio en la unidad de Windows es visible dentro de WSL en `/mnt/d/...`. La imagen es **autónoma**: las dependencias están fijadas en `requirements.lock.txt` (un conjunto de versiones probado y congelado — consulta "Imagen reproducible y autónoma" más abajo) y todas las cachés de modelos viven en **volúmenes con nombre** gestionados por Docker, de modo que el contenedor nunca lee las cachés de modelos nativas del host ni ningún estado local compartido. Los modelos se descargan una sola vez en el primer arranque a esos volúmenes y persisten.

Elige el perfil con un archivo de capa por perfil — sin necesidad de editar ningún JSON:

```bash
cd /mnt/d/photo-llm
# legacy (CPU-only): CLIP ViT-L-14 + CLIP-MLP aesthetic + CLIP tagging
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d --build
# 8gb (GPU): CLIP + TOPIQ + SAMP-Net + faces + saliency
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d --build
# 16gb (GPU): SigLIP2 + TOPIQ + Qwen3.5-2B tagging + BiRefNet saliency
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d --build

curl -s localhost:5000/health          # -> ok
```

Cada capa establece `FACET_VRAM_PROFILE` (respetado por `config/scoring_config.py`, que prevalece sobre `models.vram_profile` en la configuración — sin editar ningún JSON) y, para los perfiles de GPU, reserva la GPU NVIDIA. Los perfiles de GPU (8gb/16gb/24gb) agrupan los rostros en la GPU mediante el RAPIDS cuML integrado; el perfil legacy siempre agrupa en CPU. El `docker-compose.gpu.yml` genérico se mantiene para una ejecución simple con GPU usando el `vram_profile` propio de la configuración (predeterminado `auto`).

El primer arranque descarga los modelos del perfil en los volúmenes con nombre; restablécelos con `docker compose down -v`.

### Imagen reproducible y autónoma

- **Versiones fijadas.** La imagen se compila a partir de `requirements.lock.txt` — un `pip freeze` completo de un contenedor validado con `torch`/`torchvision` y `nvidia-*` eliminados (la imagen base de CUDA ya los proporciona). Esto evita la deriva silenciosa hacia versiones no probadas. (Ejemplo de lo que esto evita: transformers 5.3 cambió el procesamiento por lotes de visión de Qwen3.5 y rompió el etiquetador VLM hasta que llegó la corrección de padding; `kornia`, requerido por BiRefNet, no lo arrastra transformers y debe fijarse.) Regenera después de una actualización intencionada: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Agrupación de rostros en GPU integrada.** RAPIDS cuML (`cuml-cu12`) viene incluido en la imagen, así que los perfiles de GPU (8gb/16gb/24gb) agrupan los rostros en la GPU (HDBSCAN vía `face_clustering.use_gpu="auto"`); el perfil legacy — y cualquier host sin dispositivo CUDA — siempre agrupa en CPU. cuML es, con diferencia, la mayor dependencia (~5,75 GB; consulta el desglose de tamaños más abajo).
- **Sin acoplamiento con el host.** Las cachés de modelos son volúmenes con nombre, no montajes del host; el contenedor se ejecuta sin privilegios (el punto de entrada predeterminado cambia al usuario `facet`).
- **Contexto de compilación reducido.** `.dockerignore` excluye el contenido voluminoso solo local (`conda/`, conjuntos de datos de ejemplo, `*.db`, cachés, artefactos de desarrollo) — mantén los nuevos directorios locales grandes fuera del contexto añadiéndolos ahí.

### Tamaño de la imagen y descargas de modelos

Se publican dos variantes desde el mismo `Dockerfile` — **ninguna contiene los pesos de los modelos**:

| Imagen | Tamaño medido | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | ~3,3 GB | `python:3.12-slim` + PyTorch en wheels de CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | ~21 GB | PyTorch CUDA + RAPIDS cuML |

**Imagen CPU** — el tamaño principal para la mayoría de los usuarios, dominado por la pila de dependencias ML más que por PyTorch en sí:

| Capa | Tamaño |
|-------|------|
| Dependencias ML de Python (opencv, transformers, insightface, pyiqa, scipy, hdbscan, …) | ~1,9 GB |
| PyTorch + torchvision (wheels de CPU) | ~960 MB |
| Bibliotecas del sistema (`libgl1`, `libglib2.0-0`, `exiftool`, `gosu`) | ~288 MB |
| SO base (`python:3.12-slim`) + código de la aplicación | ~150 MB |

**Imagen CUDA** — sin cambios respecto a la imagen única que este repositorio publicaba antes, todavía dominada por la pila de GPU:

| Capa | Tamaño |
|-------|------|
| RAPIDS cuML (agrupación de rostros en GPU) | ~5,75 GB |
| Bibliotecas de runtime de CUDA (`nvidia-*`) | ~3,7 GB |
| PyTorch + Triton | ~1,9 GB |
| Dependencias ML de Python (transformers, pyiqa, insightface, …) | ~1,9 GB |
| SO base + conda | ~2-3 GB |

Los pesos de los modelos se **descargan en el primer arranque** en los volúmenes con nombre (`facet-hf-cache`, `facet-insightface`, `facet-pretrained`) — nunca en la imagen —, de modo que el tamaño en disco depende del perfil activo:

| Modelo | Tamaño | Perfiles |
|-------|------|----------|
| SigLIP 2 NaFlex SO400M (embeddings) | ~4,3 GB | 16gb / 24gb |
| Qwen3.5-2B (etiquetado) | ~4,2 GB | 16gb |
| Qwen3.5-4B (etiquetado) | ~8 GB | 24gb |
| Qwen2-VL-2B (composición) | ~4,2 GB | 24gb |
| CLIP ViT-L-14 (embeddings + etiquetado) | ~1,6 GB | legacy / 8gb |
| BiRefNet (prominencia) | ~424 MB | todos |
| InsightFace buffalo_l (rostros) | ~600 MB | todos |
| SAMP-Net (composición) | ~175 MB | todos |

**Total de descarga en el primer arranque por perfil:** legacy / 8gb ~3-4 GB, 16gb ~10-11 GB, 24gb ~18 GB. Reserva espacio en disco para la imagen **más** estos volúmenes; `docker compose down -v` elimina los volúmenes y fuerza una nueva descarga en el siguiente inicio.

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

Con `--workers > 1` todos los workers leen el mismo archivo, así que un JWT firmado por uno se valida en todos. Respalda el archivo junto con la base de datos — restaurar una base de datos sin él cierra la sesión de todos.

## Configuración multiusuario

Para dar a cada usuario un conjunto privado de directorios de fotos, añade una sección `users` a `scoring_config.json`. Consulta [Configuración](CONFIGURATION.md#users) para la referencia completa.

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
