# Documentación de Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · **Español** · [Português](../pt/README.md) · [简体中文](../zh/README.md)

Facet es un motor de análisis y selección de fotos multidimensional: puntúa, clasifica y
selecciona una biblioteca de fotos local, y luego sirve una galería para explorarla.
Empieza por [Instalación](INSTALLATION.md) — cubre cada configuración con bloques para
copiar y pegar.

| Documento | Descripción |
|----------|-------------|
| [Instalación](INSTALLATION.md) | Configuración por hardware, con o sin Docker; dependencias |
| [Primeros pasos](GETTING_STARTED.md) | Recorrido de la primera ejecución: de la instalación al escaneo, revisión, entrenamiento, descarte, etiquetado y exportación |
| [Comandos](COMMANDS.md) | Referencia de todos los comandos de la CLI |
| [Configuración](CONFIGURATION.md) | Referencia completa de `scoring_config.json` |
| [Puntuación](SCORING.md) | Categorías, pesos, guía de ajuste |
| [Reconocimiento facial](FACE_RECOGNITION.md) | Flujo de trabajo facial, agrupación, gestión de personas |
| [Visor](VIEWER.md) | Funciones y uso de la galería web |
| [API](../API.md) | Referencia de la API HTTP del visor |
| [Interoperabilidad](INTEROP.md) | Intercambiar valoraciones/tags con Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Sincronizar valoraciones y favoritos con Immich, más el webhook entrante |
| [Despliegue](DEPLOYMENT.md) | NAS, servidores remotos, HTTPS, copias de seguridad, multiusuario |
| [Volver a vincular](RELINK.md) | Volver a vincular fotos movidas |

## Tipos de archivo admitidos

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC/HIF** (.heic, .heif, .hif) — requiere `pillow-heif`; las imágenes `.HIF` Canon HDR PQ se convierten (tone mapping) a sRGB SDR
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — se omiten si existe un JPEG/HEIC equivalente. Un RAW que LibRaw no puede decodificar (una fusión `-HDR.dng` / `-Pano.dng` de Lightroom, o una cámara más reciente que LibRaw) se puntúa a partir de su vista previa incrustada más grande mediante `exiftool`; la vista previa debe medir al menos 1024 px en el lado largo. Lightroom Classic 13+ guarda esa vista previa como JPEG XL, que Facet decodifica directamente
- **PNG, GIF, WebP, BMP, TIFF** (.png, .gif, .webp, .bmp, .tif, .tiff) — la escala de grises de 16 bits se escala a 8 bits, un canal alfa se compone sobre blanco, y los GIF/WebP animados se puntúan según el primer fotograma; el TIFF se convierte a JPEG para el navegador. PNG, WebP y TIFF contienen EXIF cuando el programa que los escribió lo guardó; GIF y BMP no pueden, así que para esos dos `date_taken` y la cámara/objetivo quedan vacíos
- **AVIF** (.avif) — necesita un Pillow compilado con soporte AVIF (nativo a partir de `pillow>=11.3`); las imágenes HDR PQ se convierten (tone mapping) a sRGB SDR; el EXIF se lee cuando está presente
- **JPEG XL** (.jxl) — funciona de inmediato mediante la dependencia principal `imagecodecs`, también en Docker. El HDR no se convierte (tone mapping), los archivos animados puntúan el primer fotograma y se lee el EXIF válido cuando está presente. Los JPEG reconstruidos conservan la gestión de color ICC; los perfiles de color JXL nativos no están disponibles

## Preguntas frecuentes

| Problema | Respuesta |
|-------|--------|
| ¿Qué perfil debería usar? | [Instalación › ¿Qué perfil se ajusta a mi hardware?](INSTALLATION.md#qué-perfil-se-ajusta-a-mi-hardware) |
| "externally-managed-environment" al instalar | Usa un entorno virtual (o Docker) — consulta [Instalación](INSTALLATION.md) |
| Procesamiento lento | Comprueba el perfil. `--single-pass` puede ayudar en los perfiles `legacy`/`8gb` con mucha VRAM; `12gb`/`16gb`/`24gb` siempre ejecutan multipaso (salvo en modo comercial) |
| La detección de rostros no usa la GPU | Ejecuta `python facet.py --doctor` (sección ONNX Runtime) e instala `onnxruntime-gpu` en lugar de `onnxruntime`, nunca junto a él — consulta [Instalación](INSTALLATION.md#onnx-runtime-para-la-detección-de-rostros) |
| Falta exiftool | Opcional — consulta [Instalación › exiftool](INSTALLATION.md#exiftool) |
