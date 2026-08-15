# Documentación de Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · **Español** · [Português](../pt/README.md)

Facet es un motor de análisis y selección de fotos multidimensional: puntúa, clasifica y
selecciona una biblioteca de fotos local, y luego sirve una galería para explorarla.
Empieza por [Instalación](INSTALLATION.md) — cubre cada configuración con bloques para
copiar y pegar.

| Documento | Descripción |
|----------|-------------|
| [Instalación](INSTALLATION.md) | Configuración por hardware, con o sin Docker; dependencias |
| [Comandos](COMMANDS.md) | Referencia de todos los comandos de la CLI |
| [Configuración](CONFIGURATION.md) | Referencia completa de `scoring_config.json` |
| [Puntuación](SCORING.md) | Categorías, pesos, guía de ajuste |
| [Reconocimiento facial](FACE_RECOGNITION.md) | Flujo de trabajo facial, agrupación, gestión de personas |
| [Visor](VIEWER.md) | Funciones y uso de la galería web |
| [Interoperabilidad](INTEROP.md) | Intercambiar valoraciones/tags con Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Sincronizar valoraciones y favoritos con Immich, más el webhook entrante |
| [Despliegue](DEPLOYMENT.md) | NAS, servidores remotos, HTTPS, copias de seguridad, multiusuario |

## Tipos de archivo admitidos

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — requiere `pillow-heif`
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — se omiten si existe un JPEG/HEIC equivalente

## Preguntas frecuentes

| Problema | Respuesta |
|-------|--------|
| ¿Qué perfil debería usar? | [Instalación › ¿Qué perfil se ajusta a mi hardware?](INSTALLATION.md#qué-perfil-se-ajusta-a-mi-hardware) |
| "externally-managed-environment" al instalar | Usa un entorno virtual (o Docker) — consulta [Instalación](INSTALLATION.md) |
| Procesamiento lento | Comprueba el perfil; `--single-pass` ayuda en GPU con mucha VRAM |
| La detección de rostros no usa la GPU | Instala `onnxruntime-gpu` — consulta [Instalación](INSTALLATION.md#onnx-runtime-para-la-detección-de-rostros) |
| Falta exiftool | Opcional — consulta [Instalación › exiftool](INSTALLATION.md#exiftool) |
