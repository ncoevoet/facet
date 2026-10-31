# Instalación

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · **Español** · [Português](../pt/INSTALLATION.md) · [简体中文](../zh/INSTALLATION.md)

Facet se ejecuta en tu propia máquina. Elige la sección que coincide con tu configuración y copia el
bloque. La parte [Avanzado](#avanzado) solo es para cuando la necesites.

## ¿Qué instalación me conviene?

Las dos vías ejecutan el mismo Facet; intercambian sencillez de instalación por
rendimiento. Elige la que te encaje.

| | Docker | Sin Docker |
|---|---|---|
| Instalación | Un comando: todo viene en la imagen | `install.sh` (Linux, macOS) o el instalador de Windows crea un entorno Python en la máquina |
| Actualización | Descargar la imagen nueva | Actualizar el código y volver a ejecutar `install.sh`, o instalar el nuevo instalador de Windows |
| Rendimiento | Un contenedor se sitúa entre Facet y tus archivos y tu tarjeta gráfica; en Windows funciona dentro de WSL2 | Facet usa directamente la tarjeta gráfica y los archivos de la máquina |

| Tu situación | Ve a |
|----------------|-------|
| Windows, macOS o Linux, en un contenedor | [Instalar con Docker](#instalar-con-docker) |
| Windows, macOS o Linux, sin contenedores | [Instalar sin Docker](#instalar-sin-docker) |
| Un NAS, o un servidor al que quieras acceder desde otras máquinas | [Despliegue](DEPLOYMENT.md) |

## ¿Qué perfil se ajusta a mi hardware?

Un *perfil* es un conjunto de modelos de IA dimensionado para tu máquina. Eliges uno al instalar y puedes
cambiarlo más tarde.

| Tu hardware | Perfil | Qué obtienes |
|---------------|---------|--------------|
| Sin tarjeta gráfica | `legacy` | Todo funciona, solo que más despacio. |
| Tarjeta NVIDIA, 6–14 GB | `8gb` | Los modelos de `legacy`, ejecutados en la tarjeta gráfica. |
| Tarjeta NVIDIA, 14–20 GB | `16gb` | La puntuación más potente, además de etiquetas y leyendas con IA. |
| Tarjeta NVIDIA, 20 GB o más | `24gb` | Los modelos más grandes, además de explicaciones escritas de la composición. |
| Mac con Apple Silicon (M1–M4) | se elige por ti | Usa los núcleos gráficos del Mac; perfil dimensionado según la memoria. |

¿No sabes cuánta memoria tiene tu tarjeta? Usa el bloque de *Detección automática* de abajo.

## Instalar con Docker

Necesitas [Docker](https://docs.docker.com/get-started/get-docker/). Con una tarjeta NVIDIA
también necesitas el
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
En Windows eso significa ejecutar Facet dentro de WSL2
([guía paso a paso](DEPLOYMENT.md#windows-wsl2-con-una-gpu-nvidia)).

Cada bloque parte de cero. Elige **uno**.

### Detectar mi hardware automáticamente

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con tu carpeta de fotos
docker compose up -d
```

Abre <http://localhost:5000>.

### Sin tarjeta gráfica

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con tu carpeta de fotos
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d
```

Abre <http://localhost:5000>.

### Tarjeta gráfica de 8 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con tu carpeta de fotos
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d
```

Abre <http://localhost:5000>.

### Tarjeta gráfica de 16 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con tu carpeta de fotos
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

Abre <http://localhost:5000>.

### Tarjeta gráfica de 24 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con tu carpeta de fotos
docker compose -f docker-compose.yml -f docker-compose.24gb.yml up -d
```

Abre <http://localhost:5000>.

### Tarjeta NVIDIA más antigua (Maxwell, Pascal, Volta)

Los bloques de GPU de arriba y `docker-compose.gpu.yml` descargan `ghcr.io/ncoevoet/facet:latest-cuda`,
que cubre `sm_75`-`sm_120` (de Turing a Blackwell).

Para una tarjeta Maxwell, Pascal (serie GTX 900/10) o Volta (p. ej. una Titan V), edita la línea
`image:` del archivo compose que usaste (`docker-compose.8gb.yml`, `.16gb.yml`, `.24gb.yml` o
`.gpu.yml`) antes de `docker compose up -d`:

- de `ghcr.io/ncoevoet/facet:latest-cuda`
- a `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (`sm_50`-`sm_90`, de Maxwell a Hopper)

Esta etiqueta de imagen `-cuda-legacy` no tiene relación con `docker-compose.legacy.yml`, que selecciona
el perfil `legacy` solo de CPU. Las tarjetas anteriores a Maxwell (Kepler, Fermi) no tienen imagen
CUDA: usa el bloque [Sin tarjeta gráfica](#sin-tarjeta-gráfica).

### Comandos del día a día

La galería está vacía hasta que puntúes tus fotos. Dentro de Docker tu carpeta de fotos es
siempre `/data/photos`:

```bash
docker compose exec facet python facet.py /data/photos   # puntúa tus fotos
docker compose logs -f                                   # observa lo que está haciendo
docker compose down                                      # detenlo
```

Para volver a iniciarlo, vuelve a ejecutar la línea `docker compose … up -d` que usaste arriba.

## Instalar sin Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` detecta tu tarjeta gráfica, instala los paquetes correspondientes y compila la
galería web. Luego, cada vez:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # puntúa tus fotos
python viewer.py                       # inicia la galería
```

Abre <http://localhost:5000>.

### macOS

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

En Apple Silicon usa los núcleos gráficos automáticamente. Luego, cada vez:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # puntúa tus fotos
python viewer.py                       # inicia la galería
```

Abre <http://localhost:5000>.

> **¿El puerto 5000 ya está ocupado?** macOS lo usa para AirPlay. Ejecuta
> `python viewer.py --port 5001` y abre <http://localhost:5001>.

### Windows

Un instalador por usuario (MSI) instala Facet sin permisos de administrador:

| Carpeta | Contenido |
|---|---|
| `%LOCALAPPDATA%\Facet\app` | el programa, que se sustituye en cada actualización |
| `%LOCALAPPDATA%\Facet\venv` | el entorno Python, creado al terminar el instalador |
| `%LOCALAPPDATA%\Facet\data` | la base de datos (`photo_scores_pro.db`) y los registros |
| `%LOCALAPPDATA%\Facet\config` | `scoring_config.json` |

**Conseguir el instalador.** Ninguna versión publicada lo incluye todavía. Constrúyelo desde un
clon con `installer\build-msi.ps1` (necesita WiX 3.14, `uv` y el cliente compilado, e indica
dónde conseguir WiX), o descarga el artefacto `facet-msi` de una ejecución del flujo *Windows
install (MSI)*. Construirlo necesita Node.js 22.22.3 o posterior para el cliente (22.14 falla
en `npm run build`).

**Primer arranque.** El instalador inicia la creación del entorno Python en cuanto termina. El entorno ocupa unos 6 GB, y la caché de descargas de uv
(`%LOCALAPPDATA%\uv\cache`) ocupa otro tanto. La entrada *Facet* del menú Inicio ejecuta la
instalación si nunca se completó, y de nuevo tras una actualización que cambie las dependencias
de Facet. Elige la versión de PyTorch para tu tarjeta NVIDIA y su controlador como lo hace
`install.sh`, o la versión de CPU si no hay tarjeta NVIDIA. Si la versión de GPU instalada no
llega a la tarjeta, la instalación se detiene y lo explica: actualiza el controlador, o ejecuta
`Setup-Facet.ps1 -Force -Cpu`.

Si la galería no puede arrancar (puerto en uso, fallo de la instalación, sin respuesta tras 90
s), la ventana de la entrada del menú Inicio muestra el error y espera a Intro. Tras 90 s sin
respuesta, la galería sigue en marcha y aún puede arrancar.

**En el día a día:**

```powershell
cd "$env:LOCALAPPDATA\Facet\app\installer"
.\Scan-Facet.ps1 "\\NAS\Photos"   # puntuar fotos; los argumentos extra van a facet.py
.\Start-Facet.ps1                # la galería, en http://localhost:5000
.\Stop-Facet.ps1                 # detener la galería y cualquier escaneo
```

La galería solo responde en este equipo. `Start-Facet.ps1 -Lan` la abre a otros
dispositivos y se niega a arrancar hasta que `viewer.password` esté definido en la
configuración.

**Una sola forma de escribir cada carpeta.** Facet guarda cada foto con la ruta con la que se
escaneó: `\\NAS\Photos` y la misma carpeta compartida conectada como `Z:\` son para él dos
carpetas distintas, y escanear las dos añade cada foto dos veces. Elige una y mantenla.

**Equipos administrados.** Los accesos directos ejecutan los scripts de PowerShell sin firmar de Facet con `-ExecutionPolicy Bypass`. Una directiva de ejecución fijada por directiva de grupo tiene prioridad, así que en un PC administrado puede que los scripts no se ejecuten; pide a su administrador que los permita.

**Desinstalar** (Configuración, Aplicaciones) detiene Facet y quita el programa, los accesos
directos, el entorno Python y ExifTool (también bajo un `FACET_HOME` propio), y conserva `data` y
`config`. Lo que no pueda borrar queda anotado en `data\logs\uninstall.log`. La caché de
descargas de uv (`%LOCALAPPDATA%\uv\cache`) y los modelos descargados se quedan (`.cache`,
`.insightface` en tu carpeta de usuario). Una actualización conserva una carpeta de instalación
propia y solo vuelve a preparar el entorno si cambiaron las dependencias de Facet.

**Traer una biblioteca desde Docker.** La base de datos guarda la ruta completa de cada foto,
y la instalación de Windows ve las mismas fotos con otra (`\\NAS\Photos\...` en lugar de
`/data/photos/...`). Copia la base de datos a `data`, detén Facet y reescribe las rutas,
primero en simulacro:

```powershell
cd "$env:LOCALAPPDATA\Facet\app"
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos" --dry-run
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos"
```

La herramienta guarda una copia de la base de datos
(`photo_scores_pro.db.before-rewrite-<hora>`), se niega a fusionar una foto ya escaneada con la
ruta nueva y vacía el índice vectorial, que `..\venv\Scripts\python.exe database.py --db
..\data\photo_scores_pro.db --populate-vec` reconstruye. El historial de deshacer anterior al
traslado deja de aplicarse. Estos comandos suponen la carpeta de instalación predeterminada. Se
rechazan un prefijo antiguo y uno nuevo cuando uno está dentro del otro (por ejemplo,
`D:\Photos` a `D:\Photos\new`); pasa por un prefijo temporal.

Docker también funciona en Windows; para una tarjeta NVIDIA, sigue la [guía de WSL2](DEPLOYMENT.md#windows-wsl2-con-una-gpu-nvidia).

## Primera ejecución: qué esperar

- **Una descarga.** El primer escaneo obtiene los modelos de tu perfil: aproximadamente 4,7 GB para
  `legacy`, 6,9 GB para `8gb`, 14,6 GB para `16gb`, 19,3 GB para `24gb`
  ([Tamaños de descarga](#tamaños-de-descarga)). Esto ocurre una sola vez.
- **Sin configuración para escanear.** Facet crea su base de datos en el primer escaneo.
- **Solo lectura hasta que definas una contraseña.** Para editar (valorar, seleccionar, álbumes, personas), define
  `viewer.edition_password` en `scoring_config.json` y reinicia el visor. Con el
  `docker-compose.yml` incluido, la imagen genera una en el primer arranque.
- **Tus fotos no se modifican.** El escaneo solo las lee. Escribir valoraciones y palabras clave
  de vuelta en los archivos es una acción aparte, que activas tú ([Interoperabilidad](INTEROP.md)).
- **Tiempo.** Un primer escaneo de una biblioteca grande lleva su tiempo, más en un procesador que en una
  tarjeta gráfica. Puedes explorar la galería mientras trabaja.

## Comprobar que funciona

```bash
python facet.py --doctor                             # sin Docker
docker compose exec facet python facet.py --doctor   # con Docker
```

Esto imprime tu tarjeta gráfica, el perfil elegido y lo que falte. Mientras la galería
está en marcha, <http://localhost:5000/health> responde `ok`.

¿Algo no funciona? Consulta [Resolución de conflictos de dependencias](#resolución-de-conflictos-de-dependencias)
y [Problemas de detección de la GPU](#problemas-de-detección-de-la-gpu).

---

# Avanzado

Opcional: qué hace la instalación, cómo cambiarla y la referencia de dependencias.

- [Ajustes de Docker que puedes cambiar](#ajustes-de-docker-que-puedes-cambiar)
- [Elegir el perfil tú mismo](#elegir-el-perfil-tú-mismo)
- [Instalación manual, sin install.sh](#instalación-manual-sin-installsh)
- [Opciones de install.sh y atajos de Makefile](#opciones-de-installsh-y-atajos-de-makefile)
- [exiftool](#exiftool)
- [ONNX Runtime para la detección de rostros](#onnx-runtime-para-la-detección-de-rostros)
- [Compilación headless de OpenCV](#compilación-headless-de-opencv)
- [Agrupación de rostros en GPU con RAPIDS cuML](#agrupación-de-rostros-en-gpu-con-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Tamaños de descarga](#tamaños-de-descarga)
- [Dependencias](#dependencias)
- [Requisitos por función](#requisitos-por-función)
- [Resolución de conflictos de dependencias](#resolución-de-conflictos-de-dependencias)
- [Cliente de Angular](#cliente-de-angular)

## Ajustes de Docker que puedes cambiar

Los ajustes de despliegue viven en `.env` (copia `.env.example`):

| Clave | Predeterminado | Propósito |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Carpeta del host montada en lectura-escritura en `/data/photos` (para poder escribir los sidecars XMP) |
| `PORT` | `5000` | Puerto del host para la galería |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb`; anula `models.vram_profile` |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Ruta de la base de datos dentro del contenedor, ubicada en el bind mount `./data` |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` de la configuración | Disparador del reentrenamiento del clasificador personal, para quienes valoran mucho |

`scoring_config.json` es tu **anulación**. Los valores distribuidos viven en
`config/scoring_config.default.json` dentro de la imagen. Tu archivo solo contiene lo que
cambiaste; todo lo demás conserva el valor distribuido y sigue las actualizaciones. Consulta
[Configuración](CONFIGURATION.md#valores-predeterminados-y-tu-anulación) y
[la referencia completa de claves](CONFIGURATION.md).

En el primer arranque, `docker-entrypoint.sh` crea `./facet-config/scoring_config.json`:

- `docker-compose.yml` lo monta con bind como `FACET_CONFIG=/config/scoring_config.json`, de modo que los
  cambios de configuración hechos en el visor sobreviven a `docker compose down && up`.
- Con compose, contiene una `viewer.edition_password` generada, impresa una sola vez en
  `docker compose logs facet`. Un simple `docker run` sin `FACET_CONFIG` crea una anulación vacía
  y ninguna contraseña.
- Un archivo ya existente nunca se sobrescribe, y su propietario y permisos quedan intactos.

### Propiedad del archivo en el contenedor

Facet solo hace `chown` y `chmod` sobre un `scoring_config.json` que él mismo creó.

Una excepción: si una configuración existente no es **legible** por el usuario `facet` del contenedor
(uid 1000), el entrypoint toma posesión de ella y lo indica por stderr. Una configuración ilegible
te dejaría sin acceso a la interfaz. Para conservar la propiedad, hazla legible en su lugar:
`chmod o+r facet-config/scoring_config.json`.

Con Podman/Docker sin root, tu archivo pertenece a un uid en el que el usuario `facet` del contenedor
no puede convertirse. Hazlo **escribible por el usuario del contenedor sin perder la propiedad**:

```bash
# 100999 = el subuid del host al que se asigna el usuario facet del contenedor (uid 1000);
# léelo de un archivo que el contenedor ya haya creado: stat -c %u facet-config/.facet_secret
chown "$USER":100999 facet-config/scoring_config.json
chmod 664 facet-config/scoring_config.json
```

El archivo sigue siendo tuyo y editable, y las escrituras de Facet lo mantienen así. Alternativas:
`podman unshare chown` para editar un archivo propiedad del contenedor, o `--userns=keep-id` (o un
`user:` de compose) para que el usuario del contenedor *seas tú*.

> **Advertencia — actualización desde un archivo compose antiguo.** Las versiones anteriores montaban
> `- ./scoring_config.json:/app/scoring_config.json`. El archivo compose incluido ya no lo
> hace. Si adoptas el nuevo, **traslada primero tu configuración**, o tus pesos,
> categorías y contraseña del visor dejarán de leerse:
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> Si conservas tu propio `docker-compose.yml` con el montaje antiguo, `./facet-config` se inicializa
> a partir de ese archivo y no se pierde nada.
>
> Una configuración trasladada es una copia completa de los valores predeterminados antiguos. Sigue funcionando, pero tus
> cambios son difíciles de ver. Ejecuta `python database.py --compact-config` (Docker:
> `docker compose exec facet python database.py --compact-config`) para reducirla a lo que
> cambiaste. Antes hace una copia de seguridad `0600` y se resuelve en la misma configuración.

Las cachés de modelos viven en volúmenes con nombre (`facet-hf-cache`, `facet-torch-cache`,
`facet-insightface`, `facet-pretrained`) y sobreviven a los reinicios. `docker compose down -v`
las elimina y fuerza una nueva descarga.

La imagen incluye `exiftool` pero **no** darktable. La descarga RAW/perfil de darktable del visor
permanece desactivada salvo que añadas un binario `darktable-cli` a la imagen.

## Elegir el perfil tú mismo

- `docker-compose.legacy.yml`, `docker-compose.8gb.yml`, `docker-compose.16gb.yml`,
  `docker-compose.24gb.yml` fijan cada uno `FACET_VRAM_PROFILE`; los de GPU además reservan el
  dispositivo NVIDIA.
- `docker-compose.gpu.yml` reserva la GPU y deja el perfil al `vram_profile` de la
  configuración (predeterminado `auto`).

Se publican tres imágenes:

| Imagen | Contenido | Descomprimida |
|-------|----------|----------|
| `ghcr.io/ncoevoet/facet:latest` | Compilación ligera para CPU | 3,34 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda` | CUDA 12.8, RAPIDS cuML, PyTorch `sm_75`-`sm_120` (Turing–Blackwell, incl. serie RTX 50); predeterminada para `8gb`/`16gb`/`24gb` | 13,1 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` | CUDA 12.6, PyTorch `sm_50`-`sm_90` (Maxwell, Pascal, Volta–Hopper); ver [Tarjeta NVIDIA más antigua](#tarjeta-nvidia-más-antigua-maxwell-pascal-volta) | 13,8 GB |

- Las dos imágenes CUDA incluyen `onnxruntime-gpu` (1.26.0, CUDA 12) en lugar de `onnxruntime`, de modo que
  la detección de rostros se ejecuta en la GPU. La imagen de CPU conserva `onnxruntime`.
- Las tres son únicamente `linux/amd64`. En ARM, compila en local con `docker compose build`.
- `docker compose build` (o `up --build`) compila desde este repositorio. Argumentos de compilación:
  `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`, `REQUIREMENTS_LOCK`, `ORT_GPU_VERSION`
  (consulta el `Dockerfile`).

Sin Docker, usa la variable de entorno o la clave de configuración:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Los umbrales que usa `auto` están en
[Configuración › Detección automática de VRAM](CONFIGURATION.md#detección-automática-de-vram).

## Instalación comercial y paquetes restringidos

`insightface` y `pyiqa` (más `openai-clip`, `facexlib` y `onnxruntime`, que solo ellos
necesitan) distribuyen pesos de modelos bajo términos no comerciales. No están en la instalación base. Viven
en los extras `faces-insightface` e `iqa` y en `requirements.restricted.txt` (más
`requirements.restricted.lock.txt` y `requirements.legacy.restricted.lock.txt` para Docker).

> **Cambio incompatible.** `pip install -e .` y `pip install -r requirements.txt` por sí solos ya no
> incluyen insightface ni pyiqa. Usa `pip install -e .[all]` o
> `pip install -r requirements.txt -r requirements.restricted.txt`. `install.sh` y la
> imagen Docker predeterminada instalan ambos.

| Objetivo | Comando |
|------|---------|
| Todo (predeterminado) | `bash install.sh`, o `pip install -e .[all]` |
| Seguro para uso comercial | `bash install.sh --commercial` |
| Seguro para uso comercial, a mano | `pip install -r requirements.txt`, luego `pip install -e .[commercial]` y `pip install mediapipe==0.10.35 --no-deps` |
| Seguro para uso comercial, Docker | `docker build --build-arg FACET_LICENSING=commercial .` |

- `pip install -e .[all]` y el extra `faces-insightface` instalan el `onnxruntime` de CPU.
  En una máquina CUDA, continúa con el comando de GPU de
  [ONNX Runtime para la detección de rostros](#onnx-runtime-para-la-detección-de-rostros). `bash install.sh`
  y las imágenes CUDA ya lo hacen.
- Instala siempre `mediapipe` con `--no-deps`, o su `opencv-contrib-python` instala dos veces
  el espacio de nombres `cv2`. El extra `commercial` declara sus dependencias de ejecución (`absl-py`,
  `flatbuffers`).
- `python-ofiq` (bindings de calidad facial OFIQ) tiene wheels solo para Linux x86-64 y macOS arm64.
  Instálalo a mano con `pip install python-ofiq` donde esté disponible.

Instalar para uso comercial no cambia el modo. Defínelo en tu anulación:
`{ "licensing": { "mode": "commercial" } }`. El argumento de compilación de Docker también fija
`FACET_LICENSING_MODE=commercial`. `python facet.py --doctor` muestra el modo de licencia activo
y, en modo comercial, los componentes que cargaría un escaneo (YuNet, SFace, Q-ReAlign).

## Instalación manual, sin install.sh

Requiere Python 3.12 (3.10+ funciona) y Node.js 20+ para compilar la galería.

```bash
# 1. Crea y activa un entorno virtual
python3 -m venv venv
source venv/bin/activate

# 2. Instala primero PyTorch, acorde con tu versión de CUDA:
#    cu128 = CUDA 12.8+/13.x, cu126 = 12.6-12.7, cu124 = 12.4-12.5, cu118 = 11.8-12.3.
#    También importa tu TARJETA: Maxwell/Pascal/Volta (GTX 900/10, Titan V) necesitan cu126,
#    incluso con un controlador CUDA 12.8. Comprueba: `nvidia-smi --query-gpu=compute_cap --format=csv`
#    ¿Dudas? Copia el comando de https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Instala el resto de una vez para que pip resuelva todo el grafo
pip install -r requirements.txt -r requirements.restricted.txt

# 4. Solo CUDA, DESPUÉS del paso 3: cambia a ONNX Runtime para GPU (acorde con tu compilación CUDA de PyTorch)
pip uninstall -y onnxruntime onnxruntime-gpu
pip install "onnxruntime-gpu>=1.19.0,<1.27"   # PyTorch con CUDA 12.x (cu124, cu126, cu128)
# Solo CPU, o CUDA 11.8 (cu118): conserva lo que instaló el paso 3, o reinstálalo con
# pip install "onnxruntime>=1.15.0"

# 5. DESPUÉS de los pasos 3 y 4: conserva solo la compilación headless de OpenCV (la de GUI necesita libGL.so.1)
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"

# 6. Compila la galería web
cd client && npm install && npx ng build && cd ..

# 7. Ejecútala
python facet.py /path/to/photos
python viewer.py
```

El orden de los pasos importa: en los paquetes que comparten archivos (`onnxruntime`/`onnxruntime-gpu`,
`opencv-python`/`opencv-python-headless`) gana el que se instala el último.
`install.sh` aplica automáticamente el mínimo de la tarjeta y ambos cambios.

Verifica el entorno:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

¿Errores? Consulta [Resolución de conflictos de dependencias](#resolución-de-conflictos-de-dependencias).

## Opciones de install.sh y atajos de Makefile

`install.sh`:

1. busca un Python 3.10+ y crea el `venv`;
2. detecta el SO y la GPU (Apple Silicon → Metal; si no, `nvidia-smi` → compilación CUDA correspondiente);
3. instala PyTorch, `requirements.txt`, `transformers` y `accelerate`;
4. cambia al [ONNX Runtime](#onnx-runtime-para-la-detección-de-rostros) adecuado y a la
   [compilación headless de OpenCV](#compilación-headless-de-opencv);
5. busca `exiftool`, compila el cliente Angular y verifica todas las importaciones (estado de salida 1 si alguna falla).

| Opción | Efecto |
|------|--------|
| `--cpu` | Fuerza PyTorch solo CPU (sin CUDA) |
| `--cuda VERSION` | Anula la versión de CUDA detectada (p. ej. `--cuda 12.8`) |
| `--skip-client` | Omite la compilación del frontend Angular |
| `--no-uv` | Usa pip en lugar de uv |
| `--commercial` | Instalación segura para uso comercial: omite insightface, pyiqa y ONNX Runtime, instala mediapipe con `--no-deps`; define tú mismo `licensing.mode` como `commercial` |

| Objetivo de Make | Ejecuta |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`, autodetectado o solo CPU |
| `make client` | Recompila el frontend Angular |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`, CPU o NVIDIA |
| `make test` / `make test-cov` | pytest, con o sin cobertura |
| `make clean` | Elimina `venv`, `client/dist`, `client/node_modules` |

## exiftool

exiftool da la mejor extracción de EXIF para todos los formatos. Sin él, Facet recurre a
`exifread` (admite todos los formatos RAW) y luego a PIL (solo JPEG/TIFF/DNG).

| SO | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Descarga desde [exiftool.org](https://exiftool.org/) |

## ONNX Runtime para la detección de rostros

La detección de rostros (InsightFace) se ejecuta en ONNX Runtime: `onnxruntime` (CPU) u
`onnxruntime-gpu` (CUDA). Ambos comparten el directorio `onnxruntime/`, así que solo se puede instalar uno; gana el último
que instala pip. `insightface` depende de la compilación de CPU, así que instalarlo
(`requirements.restricted.txt`, `pip install -e .[all]`, el extra `faces-insightface`)
devuelve la compilación de CPU. En una máquina CUDA, instala el paquete de GPU **después** de eso,
eliminando antes ambos nombres.

`bash install.sh` lo hace en x86_64 con un PyTorch CUDA 12, y luego prueba una sesión CUDA real
(como hace `--doctor`). Vuelve a ejecutarlo para reparar un `venv` roto o cambiar entre CPU/GPU. Las
imágenes Docker CUDA hacen lo mismo. Las instalaciones de CPU, CUDA 11.8 (cu118), macOS, la imagen de CPU y
aarch64 (sin wheel de `onnxruntime-gpu` para CUDA 12) conservan `onnxruntime`.

A mano, elige la fila de tu compilación CUDA de **PyTorch**:

| Compilación de PyTorch | Comando |
|---------------|---------|
| Solo CPU, o CUDA 11.8 (cu118) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"` |
| CUDA 12.x (cu124, cu126, cu128) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"` |

- **Acorde con PyTorch, no con el controlador.** La versión de CUDA que imprime `nvidia-smi` es la más reciente que admite el
  controlador; un controlador CUDA 13 sigue ejecutando el PyTorch cu128. `python facet.py --doctor`
  muestra la compilación de PyTorch en su línea `CUDA (compiled)`.
- **Conserva el rango de versiones.** `onnxruntime-gpu` 1.19–1.26 son compilaciones CUDA 12; 1.27+ necesitan
  bibliotecas CUDA 13. Una instalación sin fijar parece correcta pero se ejecuta en silencio en la CPU. Para un PyTorch
  CUDA 13 instalado a mano, `"onnxruntime-gpu>=1.27.0"` encaja (sin probar).
- **CUDA 11.8 no tiene una compilación de GPU utilizable.** El antiguo `onnxruntime-gpu` para CUDA 11 necesita cuDNN 8,
  pero el PyTorch cu118 usa cuDNN 9. Para la detección de rostros en GPU, actualiza el controlador a uno que informe
  CUDA 12.4 o superior y vuelve a ejecutar `install.sh`.
- **Entrecomilla el requisito.** Sin comillas, `pip install onnxruntime-gpu>=1.19.0,<1.27` crea un
  archivo vacío llamado `=1.19.0,` y falla con `1.27: No such file or directory`. Elimina ese archivo.
- **Desinstala ambos nombres.** `pip uninstall onnxruntime` y luego `pip install onnxruntime-gpu`
  deja `import onnxruntime` como un paquete vacío, y InsightFace falla con
  `module 'onnxruntime' has no attribute 'InferenceSession'`.

Tras el cambio, `pip check` informa «insightface ... requires onnxruntime, which is not
installed» (`uv pip check`: «The package `insightface` requires `onnxruntime`, but it's not
installed»). Es inofensivo: `onnxruntime-gpu` proporciona el mismo módulo. Del mismo modo, tras
el cambio de OpenCV, que `insightface` y `facexlib` requieran `opencv-python` es inofensivo. Un
`pip install -r requirements.txt` posterior devuelve el OpenCV de GUI; repite el
[cambio de OpenCV](#compilación-headless-de-opencv) o vuelve a ejecutar `install.sh`.

**Compruébalo:** la sección **ONNX Runtime** de `python facet.py --doctor` lista el paquete, la
versión y los proveedores de ejecución, y avisa (con la solución) cuando ambos paquetes están instalados
o la importación falla. En CUDA ejecuta una sesión de prueba; la línea `CUDA session` es OK solo cuando
realmente se ejecuta en `CUDAExecutionProvider`. La prueba necesita el paquete `onnx` y se omite
en CPU y en modo comercial. Un escaneo en CUDA también avisa una vez cuando InsightFace se ejecuta en la CPU.

En Docker, una reparación dentro del contenedor se pierde en el siguiente `docker run`: descarga una imagen
actual o recompila. Las imágenes CUDA fijan `onnxruntime-gpu` 1.26.0 mediante el argumento de compilación
`ORT_GPU_VERSION`; nunca fijes 1.27 o posterior (CUDA 13).

## Compilación headless de OpenCV

`opencv-python` (GUI) y `opencv-python-headless` comparten el directorio `cv2/`; gana el último
instalado. Las dependencias de Facet traen ambos. La compilación de GUI necesita `libGL.so.1`, que
Debian, WSL y los hosts slim no tienen, así que `import cv2` falla con
`ImportError: libGL.so.1: cannot open shared object file`. Facet no abre ventanas de OpenCV,
así que la compilación headless basta.

`bash install.sh` conserva solo la compilación headless en todos los modos, incluido `--commercial`.
Las imágenes Docker no se ven afectadas (instalan `libgl1`). Para reparar un `venv` a mano,
sustituye `<version>` por la versión que muestra `pip list` para cualquiera de los dos paquetes:

```bash
pip uninstall -y opencv-python opencv-python-headless && pip install --no-deps "opencv-python-headless==<version>"
```

La sección **OpenCV** de `python facet.py --doctor` muestra `[OK]` cuando `cv2` se importa, o
el error de importación y el comando de reparación con tu versión rellenada. Tener ambos paquetes con una
importación que funciona está bien (las imágenes Docker incluyen ambos, con `libgl1`). Si falla una importación
principal como `cv2`, `install.sh` imprime «Installation finished with errors» y termina con
el estado 1.

## Agrupación de rostros en GPU con RAPIDS cuML

Para bases de datos de rostros grandes (80k+ rostros), cuML acelera mucho la agrupación. Necesita conda:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# o: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
# requirements.txt instala opencv-python, la compilación de GUI (necesita libGL.so.1): conserva solo la headless
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"
```

Con cuML instalado, la agrupación usa la GPU automáticamente (`face_clustering.use_gpu` en
`scoring_config.json`). Las imágenes Docker CUDA lo incluyen, así que los contenedores `8gb`/`16gb`/`24gb`
agrupan en la GPU. `legacy` siempre agrupa en el procesador.

## Apple Silicon (Metal/MPS)

No hace falta ningún paquete de GPU aparte. Instala con `bash install.sh` y comprueba que
`python facet.py --doctor` informe `Facet runtime device: mps`. Facet activa el repliegue a
CPU de PyTorch para los operadores no admitidos. Para comparar:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

- `FACET_DEVICE=cpu` desactiva la aceleración; `FACET_DEVICE=mps` la exige y falla si
  no está disponible. `FACET_DEVICE=cuda` falla igual cuando PyTorch no ve ningún dispositivo CUDA
  (p. ej. `CUDA_VISIBLE_DEVICES=''`).
- InsightFace permanece en el procesador (es un modelo de ONNX Runtime).
- Las puntuaciones de TOPIQ pueden diferir ligeramente de CPU/CUDA. En MPS, una foto cuyos lados no son
  múltiplos de 32 se recorta primero por el centro (1024×682 pasa a 1024×672).

`vram_profile: "auto"` dimensiona el perfil a partir de la memoria unificada total:

| Memoria unificada total | Perfil que selecciona `auto` |
|----------------------|----------------------------|
| menos de 16 GB | `legacy` |
| 16-31 GB | `8gb` |
| 32-47 GB | `16gb` |
| 48 GB o más | `24gb` |

Cada umbral es aproximadamente el doble de la huella de modelos del perfil, porque macOS y otras aplicaciones
comparten esa memoria. Un Mac que recurre al swap es más lento que uno con un perfil más pequeño. Un perfil
configurado explícitamente se usa siempre tal cual.

### Memoria en un Mac

Si el Monitor de Actividad muestra que Facet usa más memoria de la que tiene el Mac, o el swap sigue creciendo
durante un escaneo, prueba esto, en orden.

**1. Limita el pool de memoria de PyTorch:**

```bash
PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.0 python facet.py /path/to/photos
```

`1.0` significa «el conjunto de trabajo recomendado del Mac, nada más». Una pasada puede entonces detenerse con «out of
memory» en lugar de recurrir al swap, lo cual es preferible a que el Mac se atasque.

**Los pesos se cargan de uno en uno.** En macOS, Facet establece por defecto `HF_DEACTIVATE_ASYNC_LOAD=1`,
porque la carga concurrente puede hacer fallar un escaneo en MPS. No hay nada que configurar; define
`HF_DEACTIVATE_ASYNC_LOAD=0` tú mismo para recuperar la carga concurrente.

**2. Desactiva los dos modelos opcionales más pesados.** Añade solo estas claves a
`scoring_config.json`:

```json
{
  "models": { "profiles": { "16gb": { "saliency_enabled": false } } },
  "iqa_extended": { "qrealign": false }
}
```

`saliency_enabled` desactiva la detección del sujeto; `qrealign` desactiva un modelo de calidad
adicional. La estética, la composición, los rostros y la calidad técnica se siguen puntuando. Usa la clave de perfil de
tu Mac: `"16gb"` con 32-47 GB, `"24gb"` con 48 GB o más.

**3. Procesa menos fotos a la vez:**

```json
{ "processing": { "ram_chunk_size": 4,
                  "auto_tuning": { "min_ram_chunk_size": 4, "max_ram_chunk_size": 4 } } }
```

Configura las tres, o el ajuste automático mueve el tamaño del bloque entre `min_ram_chunk_size` y
`max_ram_chunk_size`.

## Tamaños de descarga

Los modelos se descargan en el primer uso en:

- `~/.cache/huggingface/` (modelos Hugging Face)
- `~/.cache/torch/hub/` (pesos de PyIQA)
- `~/.insightface/` (detección/reconocimiento facial)
- `pretrained_models/` en la raíz del repositorio: `samp_net.pth`, `u2netp.pth`,
  `face_landmarker.task` y `aesthetic_predictor_weights.pth` (solo `legacy`/`8gb`)

En Docker son volúmenes con nombre (`pretrained_models/` es `facet-pretrained`), así que nada
se vuelve a descargar al recrear el contenedor. No hay pesos integrados en la imagen.

Los tamaños son decimales (GB = 10⁹ bytes, MB = 10⁶ bytes).

| Modelo | Tamaño | Perfiles |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embeddings + etiquetado CLIP + estética CLIP-MLP) | 1,711 GB | `legacy`/`8gb` |
| Cabeza estética MLP (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 MB | solo `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M (embeddings) | 4,581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (etiquetado VLM) | 4,571 GB | `16gb` |
| Qwen3.5-4B (etiquetado VLM) | 9,343 GB | `24gb` |
| Qwen2-VL-2B (composición) | 4,430 GB | ninguno por defecto; ver nota 1 |
| InsightFace buffalo_l (rostros) | 289 MB de descarga / 630 MB en disco (el zip se conserva junto a los archivos `.onnx`) | todos |
| Pesos de SAMP-Net (composición) | 183 MB | todos |
| U2-Net-P (submodelo de saliencia de SAMP-Net) | 4,7 MB | los mismos que SAMP-Net |
| BiRefNet_dynamic (saliencia del sujeto) | 445 MB | todos |
| TOPIQ NR (modelo estético) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (estética complementaria) | 873 MB | todos |
| TOPIQ NR-Face (calidad facial complementaria) | 376 MB | todos |
| LIQE (calidad/distorsión complementaria) | 708 MB | todos |
| timm resnet50.a1_in1k (backbone PyIQA compartido) | 102 MB | todos |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 GB | `8gb`/`16gb`/`24gb`, **activado por defecto** (`"auto"`) |

1. Qwen2-VL-2B solo se carga si defines `composition_model: "qwen2-vl-2b"` **y**
   `processing.mode: "single-pass"`, en sustitución de SAMP-Net/U2-Net-P. Fuera del modo comercial
   esto solo funciona en `legacy`/`8gb`: en `16gb`/`24gb` el modo de un solo paso recurre a multipaso,
   que no tiene paso de Qwen2-VL.

Totales por perfil (descarga): `legacy` 4,69 GB · `8gb` 6,93 GB · `16gb` 14,55 GB ·
`24gb` 19,32 GB · `24gb` con composición Qwen2-VL 23,56 GB (solo modo comercial, ver nota 1).

Las propias imágenes Docker, antes de cualquier descarga de modelos: `latest` 3,34 GB descomprimida,
`latest-cuda` 13,1 GB, `latest-cuda-legacy` 13,8 GB
([Despliegue › Tamaño de la imagen](DEPLOYMENT.md#tamaño-de-la-imagen)). Los tamaños de descarga comprimidos aún no se han
medido.

Modelos opcionales, no incluidos en los totales:

| Modelo | Tamaño | Activación |
|-------|------|----------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 GB | desactivado por defecto |
| Backbone SigLIP so400m-patch14-384 (`iqa_extended.aesthetic_v25`) | 3,515 GB | desactivado por defecto, **obsoleto** (se prefiere `qrealign`) |
| Helsinki-NLP OPUS-MT, por idioma de destino (traducción de leyendas) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | solo para los idiomas que actives |
| MediaPipe `face_landmarker.task` | 3,76 MB | solo si `mediapipe` está instalado |

`reverse_geocoder` no necesita ninguna descarga; sus datos van incluidos en el wheel.

Los pesos de SAMP-Net provienen de la
[versión model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth).
Si ves `Failed to download SAMP-Net weights: HTTP Error 404: Not Found` (sin conexión o con red
restringida), descarga el archivo y colócalo en `pretrained_models/samp_net.pth`.

## Dependencias

### Paquetes obligatorios

| Paquete | Propósito |
|---------|---------|
| `torch`, `torchvision` | Framework de aprendizaje profundo (se instala por separado, ver arriba) |
| `open-clip-torch` | Embeddings/etiquetado CLIP (perfiles legacy/8gb) |
| `pyiqa` | TOPIQ y otros modelos de calidad/estética |
| `opencv-python` | Procesamiento de imágenes |
| `pillow` | Carga de imágenes, incl. PNG/GIF/WebP/BMP/TIFF/AVIF (AVIF necesita pillow>=11.3) |
| `imagehash` | Hashing perceptual para la detección de ráfagas |
| `rawpy` | Compatibilidad con archivos RAW |
| `fastapi`, `uvicorn` | Servidor de la API |
| `pyjwt` | Autenticación JWT |
| `numpy` | Operaciones numéricas |
| `tqdm` | Barras de progreso |
| `exifread` | Extracción de metadatos EXIF |
| `insightface` | Detección y reconocimiento de rostros |
| `transformers`, `accelerate` | Modelos SigLIP/BiRefNet/VLM (perfiles 8gb+) |
| `scipy` | Computación científica |
| `hdbscan` | Agrupación de rostros (incluye scikit-learn) |
| `reverse_geocoder` | Geocodificación inversa para GPS |
| `psutil` | Autoajuste del procesamiento por lotes (supervisión del sistema) |
| `aiosqlite` | SQLite asíncrono para los endpoints de lectura de FastAPI |
| `sqlite-vec` | Búsqueda semántica en disco (recurre a una caché NumPy en memoria); `pip install -e .[vec]` |
| `tifffile`, `imagecodecs` | Fotos JPEG XL y vistas previas de DNG combinados por Lightroom Classic 13+ (HDR/Panorama/Mejorar) |

Todos estos están en `requirements.txt` salvo `pyiqa` e `insightface`, que están en `requirements.restricted.txt` (consulta [Instalación comercial y paquetes restringidos](#instalación-comercial-y-paquetes-restringidos)). Ningún perfil necesita paquetes base adicionales.

### Paquetes opcionales

Cada uno desbloquea una función; sin él, la función se omite o se utiliza una alternativa.

| Paquete | Desbloquea | Sin él |
|---------|---------|-----------|
| `watchdog` | Modo de vigilancia (`--watch`); **no está en `requirements.txt`**, se instala con `pip install .[watch]` | `--watch` no disponible |
| `pillow-heif` | Decodificación HEIF/HEIC | Los archivos HEIF/HEIC se omiten |
| `rawpy` | Decodificación RAW (CR2/CR3/NEF/ARW/…), ya en `requirements.txt` | Los archivos RAW se omiten |
| `cuml`, `cupy` | Agrupación de rostros en GPU (conda + CUDA) | Agrupación en CPU mediante `hdbscan` (predeterminado) |
| `onnxruntime-gpu` | Detección de rostros en GPU, **en lugar de** `onnxruntime` ([detalles](#onnx-runtime-para-la-detección-de-rostros)) | `onnxruntime` en CPU (más lento) |
| `aesthetic-predictor-v2-5` | Puntuador `aesthetic_v25` (`pip install -e .[iqa-extended]`, `iqa_extended.aesthetic_v25`, desactivado por defecto). **Obsoleto** (AGPL-3.0, sin mantenimiento desde el 2024-12-18); prefiere `qrealign`, que no necesita ningún paquete adicional | `aesthetic_v25` no disponible |
| `darktable-cli` (sistema) | Exportación de perfiles RAW/darktable desde el visor | Solo se ofrece descarga original/incrustada |
| `exiftool` (sistema) | Mejor extracción de EXIF/GPS | Recurre a `exifread` y luego a PIL |

## Requisitos por función

La mayor parte de Facet funciona en cualquier entorno (CPU, cualquier perfil). Algunas funciones necesitan una GPU, un **perfil
de VRAM** superior, un paquete opcional o la **contraseña de edición** / el rol de **superadmin** del visor.
Etiquetas usadas en la documentación:
`[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Función | GPU | Perfil | Autenticación | Paquete opcional |
|---------|:---:|---------|:----:|------------------|
| Puntuación / escaneo (base) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Estética TOPIQ | sí | `16gb`/`24gb` | — | — |
| IQA suplementario (TOPIQ IAA, NR-Face, LIQE) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Embeddings SigLIP 2 | sí | `16gb`/`24gb` | — | — |
| Etiquetado VLM (Qwen3.5) | sí | `16gb`/`24gb` | — | — |
| Patrón de composición (SAMP-Net) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Saliencia del sujeto (BiRefNet) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Leyendas con IA (generar / ver) | sí | `16gb`/`24gb` | edición (generar) | — |
| Leyendas con IA (editar) | sí | `16gb`/`24gb` | edición | — |
| Crítica VLM | sí | `16gb`/`24gb` | edición (generar) | — |
| Detección / extracción de rostros (InsightFace) | recomendada (la CPU funciona, pero es lenta) | cualquiera | — | — |
| Agrupación de rostros (HDBSCAN) | no (CPU) | cualquiera | — | `cuml`/`cupy` (aceleración GPU opcional) |
| Búsqueda semántica | no | cualquiera | — | `sqlite-vec` (recurre a NumPy) |
| Decodificación RAW / HEIF | no | cualquiera | — | `rawpy` / `pillow-heif` |
| Modo de vigilancia (`--watch`) | no | cualquiera | — | `watchdog` |
| Extracción de GPS / exportación a darktable | no | cualquiera | — | `exiftool` / `darktable-cli` |
| Valoraciones, favoritos, edición de rostros y personas, selección | no | cualquiera | edición | — |
| Iniciar escaneos desde la interfaz web | no | cualquiera | edición (un usuario) / superadmin (multiusuario) | — |
| Multiusuario (valoraciones y roles por usuario) | no | cualquiera | basada en roles | — |

La contraseña de edición y los roles de usuario se definen en `scoring_config.json`; consulta
[Configuración](CONFIGURATION.md).

> ¿Sin GPU local? Apunta el etiquetado VLM, las leyendas y la crítica a un servidor Ollama o
> compatible con OpenAI remoto mediante `vlm_backend` en `scoring_config.json`. Esas funciones
> también funcionan entonces en los perfiles `legacy`/`8gb`.

## Resolución de conflictos de dependencias

Los paquetes de ML de Facet (`torch`, `open-clip-torch`, `insightface`, …) arrastran muchas
dependencias, y instalarlos uno por uno puede hacer que se rompan entre sí.

**Síntomas:** cada instalación pide aún otro paquete; conflictos de versiones entre
`torch`, `numpy`, `huggingface-hub` u `open-clip-torch`; `pip install` se ejecuta correctamente pero
`import` falla.

**1. Instala todo de una vez:** `pip install -r requirements.txt`, para que pip resuelva el
grafo completo. No instales los paquetes de forma individual
(`pip install open-clip-torch && pip install insightface && ...`).

**2. Usa [uv](https://docs.astral.sh/uv/):** `uv` resuelve el grafo completo antes de
instalar:

```bash
pip install uv
uv pip install -r requirements.txt
# Con el índice de CUDA para PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Empieza de cero:** `deactivate`, `rm -rf venv`, y repite la
[Instalación manual](#instalación-manual-sin-installsh) (o vuelve a ejecutar `install.sh`).

### Problemas de detección de la GPU

Si tu GPU no se detecta (algo habitual con tarjetas más recientes), ejecuta:

```bash
python facet.py --doctor
```

Comprueba la compatibilidad de PyTorch con CUDA y del controlador, y sugiere el comando de pip correcto. También
detecta lo que `torch.cuda.is_available()` no ve: una GPU para la que el PyTorch instalado no tiene kernels (p. ej. serie RTX 50 en una compilación de
CUDA anterior a la 12.8). En ese caso Facet recurre a la CPU en lugar de fallar, y `--doctor` indica
la solución: en Docker, la etiqueta de imagen correcta (`ghcr.io/ncoevoet/facet:latest-cuda-legacy` para
Maxwell/Pascal/Volta); en una instalación nativa, el `--index-url` correcto.

Para simular hardware en pruebas:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Cliente de Angular

Solo es necesario para el desarrollo o compilaciones personalizadas; `install.sh` y la imagen Docker ya
lo compilan.

```bash
cd client
npm install
npm run build    # Compilación de producción → client/dist/
npm start        # Servidor de desarrollo en http://localhost:4200 (redirige la API a :5000)
```

> **Advertencias de `npm audit`:** la mayoría de los hallazgos están en dependencias de desarrollo en tiempo de compilación que nunca
> llegan al navegador. Revísalos antes de ejecutar `npm audit fix`, que puede degradar o
> eliminar paquetes.
