# Instalación

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · **Español** · [Português](../pt/INSTALLATION.md)

Facet se ejecuta en tu propia máquina. Elige la sección que coincide con tu configuración,
copia el bloque, y ya está. La mitad [Avanzado](#avanzado) del final solo está ahí para
cuando la necesites.

## ¿Qué instalación me conviene?

| Tu situación | Ve a |
|----------------|-------|
| Windows, macOS o Linux, y solo quieres tenerlo en marcha | [Instalar con Docker](#instalar-con-docker) |
| Linux o macOS, y prefieres no usar contenedores | [Instalar sin Docker](#instalar-sin-docker) |
| Un NAS, o un servidor al que quieras acceder desde otras máquinas | [Despliegue](DEPLOYMENT.md) |

## ¿Qué perfil se ajusta a mi hardware?

Facet incluye cuatro *perfiles*. Un perfil no es más que un conjunto de modelos de IA
dimensionado para tu máquina — eliges uno durante la instalación y puedes cambiarlo más
tarde.

| Tu hardware | Perfil | Qué obtienes |
|---------------|---------|--------------|
| Sin tarjeta gráfica | `legacy` | Todo funciona — puntuación, rostros, etiquetas, selección, la galería — solo que más despacio. |
| Tarjeta NVIDIA, 6–14 GB | `8gb` | Los mismos modelos que `legacy`, ejecutados en la tarjeta gráfica en lugar del procesador. |
| Tarjeta NVIDIA, 14–20 GB | `16gb` | La puntuación de fotos más potente, además de etiquetas y leyendas con IA redactadas por la máquina. |
| Tarjeta NVIDIA, 20 GB o más | `24gb` | Los modelos más grandes, además de explicaciones escritas de la composición de una foto. |
| Mac con Apple Silicon (M1–M4) | se elige por ti | Facet usa los núcleos gráficos del Mac y dimensiona el perfil según tu memoria. |

¿No sabes cuánta memoria tiene tu tarjeta? Sáltate esto — el bloque de *Detección
automática* de abajo lo averigua por ti.

## Instalar con Docker

Necesitas [Docker](https://docs.docker.com/get-started/get-docker/). Si tu máquina tiene
una tarjeta NVIDIA, también necesitas el
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
para que Docker pueda acceder a ella — en Windows, eso significa ejecutar Facet dentro de
WSL2 ([guía paso a paso](DEPLOYMENT.md#windows-wsl2-con-una-gpu-nvidia)).

Cada bloque de abajo parte de cero. Elige **uno**.

### Detectar mi hardware automáticamente

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con la carpeta de tus fotos
docker compose up -d
```

Abre <http://localhost:5000>.

### Sin tarjeta gráfica

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con la carpeta de tus fotos
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d
```

Abre <http://localhost:5000>.

### Tarjeta gráfica de 8 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con la carpeta de tus fotos
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d
```

Abre <http://localhost:5000>.

### Tarjeta gráfica de 16 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con la carpeta de tus fotos
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

Abre <http://localhost:5000>.

### Tarjeta gráfica de 24 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abre .env y define PHOTOS_DIR con la carpeta de tus fotos
docker compose -f docker-compose.yml -f docker-compose.24gb.yml up -d
```

Abre <http://localhost:5000>.

### Tarjeta NVIDIA más antigua (Maxwell, Pascal, Volta)

Los bloques de 8 GB, 16 GB y 24 GB de arriba, y el overlay genérico
`docker-compose.gpu.yml`, descargan todos `ghcr.io/ncoevoet/facet:latest-cuda`,
cuya compilación de PyTorch cubre `sm_75`-`sm_120` — de Turing a Blackwell. Una
tarjeta Maxwell, Pascal (serie GTX 900/10) o Volta (p. ej. una Titan V) necesita
en su lugar la otra imagen CUDA: edita la línea `image:` en el archivo compose
que usaste arriba (`docker-compose.8gb.yml`, `.16gb.yml`, `.24gb.yml` o
`.gpu.yml`) cambiando `ghcr.io/ncoevoet/facet:latest-cuda` por
`ghcr.io/ncoevoet/facet:latest-cuda-legacy` (`sm_50`-`sm_90`, de Maxwell a Hopper)
antes de ejecutar `docker compose up -d`. No confundas esta etiqueta de imagen
con `docker-compose.legacy.yml`: ese archivo selecciona el **perfil de VRAM**
`legacy` (solo CPU) y no tiene relación con la etiqueta de **arquitectura**
`-cuda-legacy` de arriba. Una tarjeta anterior a Maxwell (Kepler, Fermi —
`sm_50` es el límite propio de la imagen legacy) no tiene ninguna imagen CUDA
compatible; usa en su lugar el perfil de VRAM `legacy` en CPU — el bloque
["Sin tarjeta gráfica"](#sin-tarjeta-gráfica) de arriba.

### Comandos del día a día

La galería está vacía hasta que puntúes tus fotos. Dentro de Docker, tu carpeta de fotos
siempre se llama `/data/photos`, sea cual sea su nombre en tu máquina:

```bash
docker compose exec facet python facet.py /data/photos   # puntúa tus fotos
docker compose logs -f                                   # observa lo que está haciendo
docker compose down                                      # detenlo
```

Para volver a iniciarlo más tarde, vuelve a ejecutar la misma línea `docker compose … up
-d` que usaste arriba.

## Instalar sin Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` detecta tu tarjeta gráfica, instala todo lo que le corresponde y compila la
galería web. Luego, cada vez que uses Facet:

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

En un Mac con Apple Silicon, esto usa automáticamente los núcleos gráficos del Mac.
Luego, cada vez que uses Facet:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # puntúa tus fotos
python viewer.py                       # inicia la galería
```

Abre <http://localhost:5000>.

> **¿El puerto 5000 ya está en uso?** macOS lo usa para AirPlay. Inicia la galería con
> `python viewer.py --port 5001` y abre <http://localhost:5001> en su lugar.

### Windows

Usa [Docker](#instalar-con-docker). Para usar una tarjeta NVIDIA en Windows, sigue la
[guía de WSL2](DEPLOYMENT.md#windows-wsl2-con-una-gpu-nvidia) — es la vía probada.

## Primera ejecución: qué esperar

- **Una descarga.** El primer escaneo obtiene los modelos de IA de tu perfil —
  aproximadamente 4,7 GB para `legacy`, 6,9 GB para `8gb`, 14,6 GB para `16gb`, 19,1 GB
  para `24gb` (desglose completo en [Tamaños de descarga](#tamaños-de-descarga)).
  Esto ocurre una sola vez; las siguientes ejecuciones arrancan de inmediato.
- **Sin configuración.** No hay nada que configurar. Facet crea su base de datos en el
  primer escaneo y viene con ajustes que funcionan de fábrica.
- **Tus fotos no se modifican.** El escaneo solo las lee; los resultados van a la base de
  datos propia de Facet. Escribir valoraciones y palabras clave de vuelta en tus archivos
  es una acción aparte, que lanzas tú ([Interoperabilidad](INTEROP.md)).
- **Tiempo.** Un primer escaneo de una biblioteca grande lleva su tiempo, y es
  notablemente más lento en un procesador que en una tarjeta gráfica. El progreso se
  muestra sobre la marcha, y puedes explorar la galería mientras trabaja.

## Comprobar que funciona

```bash
python facet.py --doctor                             # sin Docker
docker compose exec facet python facet.py --doctor   # con Docker
```

Esto imprime lo que Facet encontró: tu tarjeta gráfica, el perfil que eligió y lo que
falte. Si la galería está en marcha, <http://localhost:5000/health> responde `ok`.

¿Algo no funciona? Consulta
[Resolución de conflictos de dependencias](#resolución-de-conflictos-de-dependencias) y
[Problemas de detección de la GPU](#problemas-de-detección-de-la-gpu) más abajo.

---

# Avanzado

Todo lo que sigue a partir de aquí es opcional: qué hace exactamente la instalación,
cómo cambiarla y la referencia completa de dependencias.

- [Ajustes de Docker que puedes cambiar](#ajustes-de-docker-que-puedes-cambiar)
- [Elegir el perfil tú mismo](#elegir-el-perfil-tú-mismo)
- [Instalación manual, sin install.sh](#instalación-manual-sin-installsh)
- [Opciones de install.sh y atajos de Makefile](#opciones-de-installsh-y-atajos-de-makefile)
- [exiftool](#exiftool)
- [ONNX Runtime para la detección de rostros](#onnx-runtime-para-la-detección-de-rostros)
- [Agrupación de rostros en GPU con RAPIDS cuML](#agrupación-de-rostros-en-gpu-con-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Tamaños de descarga](#tamaños-de-descarga)
- [Dependencias](#dependencias)
- [Requisitos por función](#requisitos-por-función)
- [Resolución de conflictos de dependencias](#resolución-de-conflictos-de-dependencias)
- [Cliente de Angular](#cliente-de-angular)

## Ajustes de Docker que puedes cambiar

Los controles de despliegue viven en `.env` (copia `.env.example`):

| Clave | Predeterminado | Propósito |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Carpeta del host montada en lectura-escritura en `/data/photos` (con escritura habilitada para que los sidecars XMP se puedan escribir junto a los originales) |
| `PORT` | `5000` | Puerto del host para la galería |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb` — anula `models.vram_profile` sin editar ningún JSON |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Ruta de la base de datos dentro del contenedor, ubicada en el bind mount `./data` |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` de la configuración | Disparador del reentrenamiento del clasificador personal, para quienes valoran mucho |

Un `scoring_config.default.json` depurado viene integrado en la imagen como
configuración inicial. `docker-entrypoint.sh` lo copia, solo en el primer arranque, al
archivo persistente `./facet-config/scoring_config.json`, que `docker-compose.yml` ya
monta (como `FACET_CONFIG=/config/scoring_config.json` dentro del contenedor) — así que
el contenedor funciona sin ninguna configuración en el host, y cada escritura de
configuración en tiempo de ejecución (la migración de la contraseña del visor, los pesos,
las prioridades, los contextos de puntuación) ahora sobrevive a un `docker compose down
&& up`. Edita `./facet-config/scoring_config.json` directamente para personalizar a mano
los pesos, la contraseña del visor o las categorías; un archivo ya existente nunca se
sobrescribe.

> **¿Actualizas desde una versión anterior a este cambio?** Las versiones anteriores
> indicaban hacer `cp scoring_config.default.json scoring_config.json` y descomentar una
> línea `- ./scoring_config.json:/app/scoring_config.json` en `docker-compose.yml`. Ese
> montaje ya no está en el fichero compose que se distribuye. Si adoptas el nuevo,
> **mueve antes tu configuración existente**:
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> De lo contrario el entrypoint crea una configuración por defecto nueva y tus pesos, tus
> categorías y **tu contraseña del visor dejan de leerse** — y un
> `viewer.edition_password` vacío desactiva por completo el control de edición. Si
> conservas tu propio `docker-compose.yml` con el montaje antiguo, el entrypoint
> inicializa `./facet-config` a partir de *ese* fichero y no se pierde nada.

Las cachés de modelos viven en volúmenes con nombre gestionados por Docker
(`facet-hf-cache`, `facet-torch-cache`, `facet-insightface`, `facet-pretrained`), así que
la imagen nunca lee las cachés propias de tu máquina y los modelos sobreviven a los
reinicios. `docker compose down -v` los elimina y fuerza una nueva descarga.

La imagen incluye `exiftool` pero **no** darktable, así que la descarga opcional de
perfiles RAW/darktable del visor queda inactiva a menos que extiendas la imagen con un
binario `darktable-cli`. Todo lo demás funciona de todas formas.

## Elegir el perfil tú mismo

Los archivos por perfil (`docker-compose.legacy.yml`, `docker-compose.8gb.yml`,
`docker-compose.16gb.yml`, `docker-compose.24gb.yml`) fijan cada uno
`FACET_VRAM_PROFILE` y, en los perfiles de GPU, reservan el dispositivo NVIDIA.
`docker-compose.gpu.yml` es la alternativa genérica: reserva la GPU pero deja el perfil
al `vram_profile` propio de la configuración (predeterminado `auto`).

Se publican tres imágenes desde un único `Dockerfile`: `ghcr.io/ncoevoet/facet:latest`
es una compilación ligera para CPU (3,34 GB descomprimidos en disco; ver
[Tamaños de descarga](#tamaños-de-descarga)). `ghcr.io/ncoevoet/facet:latest-cuda`
incluye CUDA 12.8, RAPIDS cuML y la compilación de PyTorch `sm_75`-`sm_120` — de
Turing a Blackwell, incluida la serie RTX 50 (13,1 GB descomprimidos) — y es la que
descargan por defecto los archivos compose `8gb`/`16gb`/`24gb`.
`ghcr.io/ncoevoet/facet:latest-cuda-legacy` incluye CUDA 12.6 y la compilación de
PyTorch `sm_50`-`sm_90` — de Maxwell, Pascal (serie GTX 900/10) y Volta a Hopper
(13,8 GB descomprimidos) — para las tarjetas que `latest-cuda` ya no cubre; ver
[Tarjeta NVIDIA más antigua](#tarjeta-nvidia-más-antigua-maxwell-pascal-volta) más
arriba. Las tres son únicamente `linux/amd64` — en una máquina ARM, compila en local
con `docker compose build` en lugar de descargar. `docker compose build`
(o `up --build`) siempre compila desde este repositorio; consulta los argumentos de
compilación `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` y `REQUIREMENTS_LOCK` en el
`Dockerfile`.

Sin Docker, la misma elección es una variable de entorno o una clave de configuración:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Los umbrales exactos que aplica `auto` están en
[Configuración › Detección automática de VRAM](CONFIGURATION.md#detección-automática-de-vram).

## Instalación manual, sin install.sh

Requiere Python 3.12 (3.10+ funciona) y Node.js 20+ para compilar la galería.

```bash
# 1. Crea y activa un entorno virtual
python3 -m venv venv
source venv/bin/activate

# 2. Instala primero PyTorch, con la URL de índice correspondiente a tu versión de CUDA.
#    cu128 está pensado para CUDA 12.8+/13.x; usa cu126 para CUDA 12.6-12.7, cu124
#    para CUDA 12.4-12.5, o cu118 para CUDA 11.8-12.3.
#    En caso de duda, copia el comando de https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Instala el resto de una vez, para que pip pueda resolver todo el grafo a la vez.
#    requirements.txt ya incluye transformers y accelerate, necesarios para
#    los modelos SigLIP/BiRefNet/VLM que usan los perfiles 8gb+.
pip install -r requirements.txt

# 4. Instala UN ÚNICO ONNX Runtime para la detección de rostros (consulta la tabla siguiente)
pip install onnxruntime-gpu>=1.17.0   # o bien: pip install onnxruntime>=1.15.0

# 5. Compila la galería web
cd client && npm install && npx ng build && cd ..

# 6. Ejecútalo
python facet.py /path/to/photos
python viewer.py
```

Verifica el entorno en una línea:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

¿Te encuentras con errores? Consulta
[Resolución de conflictos de dependencias](#resolución-de-conflictos-de-dependencias).

## Opciones de install.sh y atajos de Makefile

`install.sh` localiza un Python 3.10+, crea el `venv`, detecta el sistema operativo y la
GPU (Apple Silicon → Metal, o si no, `nvidia-smi` → la compilación de CUDA
correspondiente), instala PyTorch, el ONNX Runtime adecuado, `requirements.txt`,
`transformers` y `accelerate`, comprueba si existe `exiftool`, compila el cliente de
Angular y verifica todas las importaciones.

| Opción | Efecto |
|------|--------|
| `--cpu` | Forzar PyTorch solo para CPU (sin CUDA) |
| `--cuda VERSION` | Anular la versión de CUDA detectada (p. ej. `--cuda 12.8`) |
| `--skip-client` | Omitir la compilación del frontend de Angular |
| `--no-uv` | Usar pip en lugar de uv |

| Objetivo de Make | Ejecuta |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`, autodetectado o solo CPU |
| `make client` | Recompilar el frontend de Angular |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`, CPU o NVIDIA |
| `make test` / `make test-cov` | pytest, con o sin cobertura |
| `make clean` | Eliminar `venv`, `client/dist`, `client/node_modules` |

## exiftool

exiftool ofrece la mejor extracción de EXIF para todos los formatos. Sin él, Facet
recurre a `exifread` (una biblioteca de Python que gestiona todos los formatos RAW) y
luego a PIL (solo JPEG/TIFF/DNG).

| SO | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Descárgalo desde [exiftool.org](https://exiftool.org/) |

## ONNX Runtime para la detección de rostros

La detección de rostros (InsightFace) se ejecuta sobre ONNX Runtime, que se distribuye
en variantes de CPU y de GPU. Instala exactamente una:

| Configuración | Comando |
|--------|---------|
| Solo CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

Comprueba tu versión de CUDA con `nvidia-smi` — se muestra en la esquina superior
derecha. Para cambiar una instalación existente de CPU a GPU:

```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

## Agrupación de rostros en GPU con RAPIDS cuML

Para bases de datos de rostros grandes (más de 80 000 rostros), cuML acelera
considerablemente la agrupación. Necesita un entorno conda:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# o bien: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
```

Cuando cuML está disponible, la agrupación usa la GPU automáticamente
(`face_clustering.use_gpu` en `scoring_config.json`). La imagen Docker CUDA ya lo
incluye, así que los perfiles `8gb`/`16gb`/`24gb` en contenedor agrupan en la GPU sin
ningún paso adicional; `legacy` siempre agrupa en el procesador.

## Apple Silicon (Metal/MPS)

No hace falta ningún paquete de GPU aparte. Instala con `bash install.sh` y luego
comprueba que `python facet.py --doctor` informe `Facet runtime device: mps`. Facet
activa por defecto el repliegue a CPU de PyTorch para los operadores no admitidos. Para
comparar:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

Define `FACET_DEVICE=cpu` para desactivar la aceleración, o `FACET_DEVICE=mps` para
exigirla (y fallar con claridad si no está disponible). InsightFace permanece en el
procesador porque es un modelo de ONNX Runtime, no de PyTorch.

Metal no tiene memoria de vídeo dedicada, así que `vram_profile: "auto"` se dimensiona a
partir de la memoria unificada total:

| Memoria unificada total | Perfil que selecciona `auto` |
|----------------------|----------------------------|
| menos de 16 GB | `legacy` |
| 16-31 GB | `8gb` |
| 32-47 GB | `16gb` |
| 48 GB o más | `24gb` |

Cada umbral pide aproximadamente el doble de la huella de memoria de los modelos del
perfil, porque la memoria unificada se comparte con macOS, el servidor de ventanas y
cualquier otra aplicación en ejecución — un Mac que recurre al swap es más lento que uno
con un perfil más pequeño. Un perfil configurado explícitamente siempre se respeta tal
cual, así que define uno para anular estos umbrales en cualquiera de los dos sentidos.

## Tamaños de descarga

Los modelos se descargan en el primer uso a `~/.cache/huggingface/` (modelos Hugging
Face), `~/.cache/torch/hub/` (pesos de PyIQA) y `~/.insightface/` (detección/reconocimiento
facial), o a los volúmenes con nombre de Docker. `samp_net.pth`, `u2netp.pth`,
`face_landmarker.task` y el `aesthetic_predictor_weights.pth` de la cabeza estética CLIP-MLP
(solo `legacy`/`8gb`) van todos a `pretrained_models/`, resuelto respecto a la raíz del
repositorio y no al directorio de trabajo del proceso — en Docker eso es el volumen montado
`facet-pretrained`, así que ninguno de ellos se vuelve a descargar al recrear el
contenedor. Ningún peso de modelo viene integrado en la imagen.

Los tamaños siguientes son decimales (GB = 10⁹ bytes, MB = 10⁶ bytes), medidos a partir
de las cachés de modelos locales y de la API de Hugging Face.

| Modelo | Tamaño | Perfiles |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embeddings + etiquetado CLIP + estética CLIP-MLP) | 1,711 GB | `legacy`/`8gb` |
| Cabeza estética MLP (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 MB | solo `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M (embeddings) | 4,581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (etiquetado VLM) | 4,571 GB | `16gb` |
| Qwen3.5-4B (etiquetado VLM) | 9,343 GB | `24gb` |
| Qwen2-VL-2B (composición) | 4,430 GB | ninguno por defecto — solo si estableces manualmente `composition_model: "qwen2-vl-2b"` **y** `processing.mode: "single-pass"` |
| InsightFace buffalo_l (rostros) | 289 MB de descarga / 630 MB en disco (el zip se conserva junto a los archivos `.onnx` extraídos) | todos |
| Pesos de SAMP-Net (composición) | 183 MB | todos |
| U2-Net-P (submodelo de saliencia de SAMP-Net) | 4,7 MB | los mismos perfiles que SAMP-Net |
| BiRefNet_dynamic (saliencia del sujeto) | 445 MB | todos |
| TOPIQ NR (modelo estético) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (estética complementaria) | 873 MB | todos |
| TOPIQ NR-Face (calidad facial complementaria) | 376 MB | todos |
| LIQE (calidad/distorsión complementaria) | 708 MB | todos |
| timm resnet50.a1_in1k (backbone PyIQA compartido) | 102 MB | todos |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 GB | `8gb`/`16gb`/`24gb`, **activado por defecto** (`"auto"` se resuelve como activado en todos los perfiles salvo `legacy`) |

Totales por perfil (descarga): `legacy` 4,69 GB · `8gb` 6,93 GB · `16gb` 14,55 GB ·
`24gb` 19,32 GB · `24gb` con `composition_model: "qwen2-vl-2b"` y
`processing.mode: "single-pass"` 23,56 GB (la sustitución manual reemplaza a
SAMP-Net/U2-Net-P en lugar de sumarse a ellos).

Como referencia, la propia imagen de Docker (antes de cualquier descarga de
modelos) pesa, descomprimida, 3,34 GB en `latest`, 13,1 GB en `latest-cuda` y
13,8 GB en `latest-cuda-legacy` — ver [Deployment › Tamaño de la imagen](DEPLOYMENT.md#tamaño-de-la-imagen)
para saber cómo se midieron estas cifras. Las tres imágenes cambiaron de base en
esta versión (issue #119); sus tamaños de descarga comprimidos se añadirán en
cuanto se publiquen estas bases y haya un manifiesto desde el que medirlos.

Modelos opcionales no incluidos en los totales anteriores:

| Modelo | Tamaño | Activación |
|-------|------|----------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 GB | desactivado por defecto |
| Backbone SigLIP so400m-patch14-384 (`iqa_extended.aesthetic_v25`) | 3,515 GB | desactivado por defecto, **obsoleto** (AGPL-3.0, sin mantenimiento upstream — se prefiere `qrealign`) |
| Helsinki-NLP OPUS-MT, por idioma de destino (traducción de leyendas) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | solo para los idiomas activados |
| MediaPipe `face_landmarker.task` | 3,76 MB | solo si `mediapipe` está instalado |

`reverse_geocoder` no necesita ninguna descarga: sus datos van incluidos en el wheel.

Los pesos de SAMP-Net provienen de la
[versión model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth)
del proyecto. Si esa descarga falla (sin conexión o con la red restringida), verás
`Failed to download SAMP-Net weights: HTTP Error 404: Not Found` — descarga el archivo
manualmente y colócalo en `pretrained_models/samp_net.pth`.

## Dependencias

### Paquetes obligatorios

| Paquete | Propósito |
|---------|---------|
| `torch`, `torchvision` | Framework de aprendizaje profundo (se instala por separado, ver arriba) |
| `open-clip-torch` | Embeddings/etiquetado CLIP (perfiles legacy/8gb) |
| `pyiqa` | TOPIQ y otros modelos de calidad/estética |
| `opencv-python` | Procesamiento de imágenes |
| `pillow` | Carga de imágenes |
| `imagehash` | Hashing perceptual para detección de ráfagas |
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
| `sqlite-vec` | KNN en disco para búsqueda semántica y similitud (recurre a la caché en memoria con NumPy si falta) |

Todos estos están en `requirements.txt`; ningún perfil necesita paquetes base
adicionales.

### Paquetes opcionales

Cada uno desbloquea una función; sin él, la función se omite o se utiliza una
alternativa.

| Paquete | Desbloquea / propósito | Sin él |
|---------|-------------------|-----------|
| `watchdog` | Modo de vigilancia (el demonio `--watch` reescanea archivos nuevos) — **no está en `requirements.txt`**; solo se instala mediante `pip install .[watch]`, por lo que quienes usen directamente `requirements.txt` no obtienen `--watch` | `--watch` no disponible |
| `pillow-heif` | Decodificación HEIF/HEIC | Los archivos HEIF/HEIC se omiten |
| `rawpy` | Decodificación RAW (CR2/CR3/NEF/ARW/…) | Los archivos RAW se omiten (ya incluido en `requirements.txt` base) |
| `cuml`, `cupy` | Agrupación de rostros acelerada por GPU (conda + CUDA) | La agrupación se ejecuta en CPU mediante `hdbscan` (predeterminado) |
| `onnxruntime-gpu` | Detección de rostros acelerada por GPU | `onnxruntime` en CPU (más lento) |
| `aesthetic-predictor-v2-5` | Nivel de IQA extendido — puntuador `aesthetic_v25` (`pip install -e .[iqa-extended]`; `iqa_extended.aesthetic_v25` en `scoring_config.json`, desactivado de forma predeterminada). **Obsoleto** — AGPL-3.0, sin mantenimiento desde el 2024-12-18; prefiere `qrealign`, que no necesita ningún paquete adicional (viene con la dependencia base `pyiqa`) | `aesthetic_v25` no disponible |
| `darktable-cli` (sistema) | Exportación de perfiles RAW/darktable desde el visor | Solo se ofrece descarga original/incrustada |
| `exiftool` (sistema) | Mejor extracción de EXIF/GPS | Recurre a `exifread` y luego a PIL |

## Requisitos por función

La mayor parte de Facet funciona en cualquier entorno (CPU, cualquier perfil). Algunas
funciones necesitan una GPU, un **perfil de VRAM** superior, un paquete opcional o la
**contraseña de edición** / el rol de **superadministrador** del visor. Etiquetas usadas
a lo largo de la documentación:
`[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Función | GPU | Perfil | Autenticación | Paquete opcional |
|---------|:---:|---------|:----:|------------------|
| Puntuación / escaneo (base) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Estética TOPIQ | sí | `16gb`/`24gb` | — | — |
| IQA suplementario (TOPIQ IAA, NR-Face, LIQE) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Embeddings SigLIP 2 | sí | `16gb`/`24gb` | — | — |
| Etiquetado VLM (Qwen3.5) | sí | `16gb`/`24gb` | — | — |
| Patrón de composición (SAMP-Net) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Composición (Qwen2-VL) | sí | `24gb` | — | — |
| Saliencia del sujeto (BiRefNet) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Leyendas con IA (generar / ver) | sí | `16gb`/`24gb` | — | — |
| Leyendas con IA (editar) | sí | `16gb`/`24gb` | edición | — |
| Crítica VLM | sí | `16gb`/`24gb` | — | — |
| Detección / extracción de rostros (InsightFace) | recomendada (la CPU funciona, pero es lenta) | cualquiera | — | — |
| Agrupación de rostros (HDBSCAN) | no (CPU) | cualquiera | — | `cuml`/`cupy` (aceleración GPU opcional) |
| Búsqueda semántica | no | cualquiera | — | `sqlite-vec` (recurre a NumPy) |
| Decodificación RAW / HEIF | no | cualquiera | — | `rawpy` / `pillow-heif` |
| Modo de vigilancia (`--watch`) | no | cualquiera | — | `watchdog` |
| Extracción de GPS / exportación a darktable | no | cualquiera | — | `exiftool` / `darktable-cli` |
| Valoraciones, favoritos, edición de rostros y personas, selección | no | cualquiera | edición | — |
| Iniciar escaneos desde la interfaz web | no | cualquiera | superadministrador | — |
| Multiusuario (valoraciones y roles por usuario) | no | cualquiera | basada en roles | — |

> La *agrupación* de rostros se ejecuta en CPU por defecto (`hdbscan` independiente);
> `cuml`/`cupy` solo añaden aceleración GPU opcional — **no** son obligatorios. La
> contraseña de edición y los roles de usuario se configuran en `scoring_config.json` —
> consulta [Configuración](CONFIGURATION.md) para la autenticación.

> ¿Sin GPU local? Apunta el etiquetado VLM, las leyendas y la crítica a un servidor
> Ollama o compatible con OpenAI remoto mediante `vlm_backend` en `scoring_config.json`
> — así esas funciones también funcionan en los perfiles de CPU `legacy`/`8gb`.

## Resolución de conflictos de dependencias

Facet tiene muchas dependencias de ML (`torch`, `open-clip-torch`, `insightface`, etc.)
que arrastran sus propias dependencias transitivas. pip resuelve las dependencias de
forma secuencial, lo que puede provocar errores en cascada en los que instalar un
paquete rompe otro.

**Síntomas:** instalar los paquetes uno por uno provoca errores que piden aún otro
paquete; conflictos de versiones entre `torch`, `numpy`, `huggingface-hub` u
`open-clip-torch`; `pip install` se ejecuta correctamente pero `import` falla en tiempo
de ejecución.

**1. Instala todo de una vez** — `pip install -r requirements.txt` le da a pip el grafo
completo de dependencias para resolverlo. No instales los paquetes de forma individual
(`pip install open-clip-torch && pip install insightface && ...`); eso impide que pip
resuelva el grafo completo.

**2. Usa [uv](https://docs.astral.sh/uv/) en lugar de pip** — `uv` resuelve el grafo
completo de dependencias por adelantado antes de instalar nada, evitando los conflictos
en cascada:

```bash
pip install uv
uv pip install -r requirements.txt
# Con el índice de CUDA para PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Empieza de cero** — si tu entorno ya está roto, ejecuta `deactivate`, `rm -rf venv`,
y repite los pasos de [Instalación manual](#instalación-manual-sin-installsh) (o
simplemente vuelve a ejecutar `install.sh`).

### Problemas de detección de la GPU

Si tu GPU no se detecta (algo habitual con tarjetas más recientes), ejecuta el
diagnóstico:

```bash
python facet.py --doctor
```

Comprueba la compatibilidad de PyTorch con CUDA y del controlador, y sugiere el comando
de pip correcto. También detecta un caso que `torch.cuda.is_available()` no puede: una
GPU que el controlador ve pero para la que la compilación de PyTorch instalada no
incluye kernels — las RTX serie 50 (Blackwell, `sm_120`) en una compilación anterior a
CUDA 12.8 eran exactamente eso. Facet compara la capacidad de cómputo del dispositivo
con la lista de arquitecturas de la compilación y lanza un kernel de prueba antes de
fijar un perfil de VRAM; si hay un desajuste, recurre a la CPU en lugar de fallar en
la primera operación real, y `--doctor` indica el desajuste y la solución — la
etiqueta de imagen correcta en Docker (`ghcr.io/ncoevoet/facet:latest-cuda-legacy`
para tarjetas Maxwell/Pascal/Volta), o el `--index-url` correcto en una instalación
nativa.

También puedes simular hardware para hacer pruebas:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Cliente de Angular

Solo es necesario para el desarrollo o compilaciones personalizadas — `install.sh` y la
imagen Docker ya lo compilan.

```bash
cd client
npm install
npm run build    # Compilación de producción → client/dist/
npm start        # Servidor de desarrollo en http://localhost:4200 (redirige la API a :5000)
```

> **Advertencias de `npm audit`:** Angular arrastra un árbol profundo de dependencias
> transitivas y `npm audit` informará de hallazgos, la mayoría en dependencias de
> desarrollo en tiempo de compilación que nunca llegan al navegador. Revisa la lista
> antes de ejecutar `npm audit fix` — puede degradar o eliminar paquetes silenciosamente.
