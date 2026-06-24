# Instalación

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · **Español**

## Inicio rápido

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # detecta automáticamente la GPU, crea el venv e instala todo

# Activa el venv que creó install.sh — el script de instalación no puede hacerlo
# por ti porque se ejecuta en una subshell.
source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py --doctor # verifica tu configuración
```

`install.sh` crea el venv, detecta la GPU/CUDA, instala PyTorch con la URL de índice correspondiente, la variante adecuada de ONNX Runtime, el resto de las dependencias y compila el frontend de Angular.

**Opciones:**
| Opción | Efecto |
|------|--------|
| `--cpu` | Forzar PyTorch solo para CPU (sin CUDA) |
| `--cuda VERSION` | Anular la versión de CUDA detectada (p. ej. `--cuda 12.8`) |
| `--skip-client` | Omitir la compilación del frontend de Angular |
| `--no-uv` | Usar pip en lugar de uv |

También hay disponible un `Makefile`: `make install`, `make install-cpu`, `make run`, `make doctor`.

---

## Instalación manual

### Requisitos del sistema

- Python 3.12 (compatible con 3.10+)
- `exiftool` (paquete del sistema, opcional pero recomendado)

#### Instalar exiftool

exiftool ofrece la mejor extracción de EXIF para todos los formatos. Sin él, la aplicación recurre a `exifread` (biblioteca de Python, gestiona todos los formatos RAW) y luego a PIL (solo JPEG/TIFF/DNG).

| SO | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Descárgalo desde [exiftool.org](https://exiftool.org/) |

### Entorno de Python

```bash
# Crear el entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instala primero PyTorch con la URL de índice de CUDA correcta.
# cu128 está pensado para CUDA 12.8+/13.x; para CUDA 11.8 usa cu118, para CUDA 12.4 usa cu124.
# En caso de duda, elige el comando correspondiente en https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Instalar las dependencias (todas a la vez para una resolución de dependencias correcta).
# requirements.txt ya incluye transformers y accelerate, necesarios para
# los modelos SigLIP/BiRefNet/VLM que usan los perfiles 8gb+.
pip install -r requirements.txt
```

> **¿Encuentras errores de dependencias?** Consulta [Resolución de conflictos de dependencias](#resolución-de-conflictos-de-dependencias) más abajo.

### Configuración de la GPU

#### PyTorch con CUDA

Instálalo desde [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) según tu versión de CUDA. El script de instalación lo hace automáticamente.

#### ONNX Runtime para detección de rostros

Elige UNA opción según tu configuración:

| Opción | Comando |
|--------|---------|
| Solo CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

**Comprueba tu versión de CUDA:** Ejecuta `nvidia-smi` y mira en la esquina superior derecha el valor «CUDA Version: X.X».

Si cambias de la versión de CPU a la de GPU:
```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

### RAPIDS cuML para agrupación de rostros en GPU (opcional)

Para bases de datos de rostros grandes (más de 80 000 rostros), la agrupación acelerada por GPU mediante cuML acelera significativamente el agrupamiento de rostros. Requiere un entorno conda:

```bash
# Crear el entorno conda con soporte para CUDA
conda create -n facet python=3.12
conda activate facet

# Instalar cuML (elige tu versión de CUDA)
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Alternativa: pip install
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"

# Instalar las demás dependencias
pip install -r requirements.txt
```

Cuando cuML está disponible, la agrupación de rostros usa la GPU automáticamente (configurable mediante `face_clustering.use_gpu` en `scoring_config.json`).

## Verificar la instalación

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

## Resumen de dependencias

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

Todos estos están en `requirements.txt`; ningún perfil necesita paquetes base adicionales.

### Paquetes opcionales

Cada uno desbloquea una función; sin él, la función se omite o se utiliza una alternativa.

| Paquete | Desbloquea / propósito | Sin él |
|---------|-------------------|-----------|
| `watchdog` | Modo de vigilancia (el demonio `--watch` reescanea archivos nuevos) — **no está en `requirements.txt`**; solo se instala mediante `pip install .[watch]`, por lo que quienes usen directamente `requirements.txt` no obtienen `--watch` | `--watch` no disponible |
| `pillow-heif` | Decodificación HEIF/HEIC | Los archivos HEIF/HEIC se omiten |
| `rawpy` | Decodificación RAW (CR2/CR3/NEF/ARW/…) | Los archivos RAW se omiten (ya incluido en `requirements.txt` base) |
| `cuml`, `cupy` | Agrupación de rostros acelerada por GPU (conda + CUDA) | La agrupación se ejecuta en CPU mediante `hdbscan` (predeterminado) |
| `onnxruntime-gpu` | Detección de rostros acelerada por GPU | `onnxruntime` en CPU (más lento) |
| `aesthetic-predictor-v2-5`, `bitsandbytes` | Nivel de IQA extendido (`pip install -e .[iqa-extended]`; `iqa_extended` en `scoring_config.json`, desactivado de forma predeterminada) | Métricas de IQA extendido no disponibles |
| `darktable-cli` (sistema) | Exportación de perfiles RAW/darktable desde el visor | Solo se ofrece descarga original/incrustada |
| `exiftool` (sistema) | Mejor extracción de EXIF/GPS | Recurre a `exifread` y luego a PIL |

## Requisitos por función

La mayor parte de Facet funciona en cualquier entorno (CPU, cualquier perfil). Algunas funciones necesitan una GPU, un **perfil de VRAM** superior, un paquete opcional o la **contraseña de edición** / el rol de **superadministrador** del visor. Etiquetas usadas a lo largo de la documentación:
`[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Función | GPU | Perfil | Autenticación | Paquete opcional |
|---------|:---:|---------|:----:|------------------|
| Puntuación / escaneo (base) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Estética TOPIQ | sí | `16gb`/`24gb` | — | — |
| IQA suplementario (TOPIQ IAA, NR-Face, LIQE) | sí | `8gb`/`16gb`/`24gb` | — | — |
| Embeddings SigLIP 2 | sí | `16gb`/`24gb` | — | — |
| Etiquetado VLM (Qwen3.5) | sí | `16gb`/`24gb` | — | — |
| Patrón de composición (SAMP-Net) | opcional | cualquiera (`legacy` = CPU) | — | — |
| Composición (Qwen2-VL) | sí | `24gb` | — | — |
| Saliencia del sujeto (BiRefNet) | sí | `16gb`/`24gb` | — | — |
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

> La *agrupación* de rostros se ejecuta en CPU por defecto (`hdbscan` independiente); `cuml`/`cupy` solo añaden aceleración GPU opcional —**no** son obligatorios. La contraseña de edición y los roles de usuario se configuran en `scoring_config.json` —consulta [Configuración](CONFIGURATION.md) para la autenticación.

## Resolución de conflictos de dependencias

Facet tiene muchas dependencias de ML (`torch`, `open-clip-torch`, `insightface`, etc.) que arrastran sus propias dependencias transitivas. pip resuelve las dependencias de forma secuencial, lo que puede provocar errores en cascada en los que al instalar un paquete se rompe otro.

### Síntomas

- Instalar los paquetes uno por uno provoca errores que te piden instalar otro paquete más
- Conflictos de versiones entre `torch`, `numpy`, `huggingface-hub` u `open-clip-torch`
- `pip install` se ejecuta correctamente pero `import` falla en tiempo de ejecución

### Soluciones

**1. Instala todo de una vez** — le da a pip el grafo completo de dependencias para resolverlo:

```bash
pip install -r requirements.txt
```

**No** instales los paquetes individualmente (`pip install open-clip-torch && pip install insightface && ...`) — esto impide que pip resuelva el grafo completo.

**2. Usa [uv](https://docs.astral.sh/uv/) en lugar de pip** — `uv` resuelve el grafo completo de dependencias por adelantado antes de instalar nada, evitando conflictos en cascada:

```bash
# Instalar uv
pip install uv

# Instalar todas las dependencias con resolución completa
uv pip install -r requirements.txt

# Con índice de CUDA para PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Empieza de cero** — si tu entorno ya está en un estado dañado, ejecuta `deactivate`, `rm -rf venv` y vuelve a crearlo repitiendo los pasos de [Entorno de Python](#entorno-de-python) anteriores.

### Problemas de detección de la GPU

Si tu GPU no se detecta (algo habitual con GPU más recientes como la RTX 5070 Ti), ejecuta la herramienta de diagnóstico:

```bash
python facet.py --doctor
```

Esto comprueba la compatibilidad de PyTorch con CUDA, la compatibilidad del controlador y sugiere el comando de instalación de pip correcto. También puedes simular escenarios de GPU para realizar pruebas:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Primera ejecución

En la primera ejecución, Facet descarga automáticamente el modelo de embeddings de tu perfil:
- CLIP ViT-L-14 (perfiles legacy/8gb): ~1,7 GB — o SigLIP 2 NaFlex SO400M (perfiles 16gb/24gb), mayor
- Modelo buffalo_l de InsightFace: ~400 MB
- Pesos de SAMP-Net (todos los perfiles): ~50 MB

Los modelos se almacenan en caché en ubicaciones estándar (`~/.cache/` o `~/.insightface/`).

## Cliente de Angular (opcional)

Solo es necesario para el desarrollo o compilaciones personalizadas; `install.sh` ya lo compila.

```bash
cd client
npm install
npm run build    # Compilación de producción → client/dist/
npm start        # Servidor de desarrollo en http://localhost:4200 (redirige la API a :5000)
```

> **Advertencias de `npm audit`:** Angular arrastra un árbol profundo de
> dependencias transitivas y `npm audit` informará de hallazgos, la mayoría
> de los cuales están en dependencias de desarrollo en tiempo de compilación
> que nunca llegan al navegador. Revisa la lista antes de ejecutar
> `npm audit fix` — puede degradar o eliminar paquetes silenciosamente.

> **Puerto 5000 en macOS:** El receptor AirPlay del Centro de control escucha
> en el puerto 5000 de forma predeterminada. Inicia el visor con
> `python viewer.py --port 5001` (o define la variable de entorno `PORT`)
> para evitar el conflicto.

### Descarga manual de SAMP-Net

Los pesos de SAMP-Net se descargan automáticamente en el primer uso desde la versión de pesos de modelos del proyecto (`github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth`). Normalmente no se requiere ningún paso manual.

Si la descarga automática falla (p. ej. sin conexión o con la red restringida), verás:
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Entonces descárgalos manualmente:
1. Descarga `samp_net.pth` desde la [versión model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth) (o, como alternativa secundaria, desde [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view))
2. Coloca el archivo en `pretrained_models/samp_net.pth`
