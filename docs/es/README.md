# Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · **Español** · [Português](../pt/README.md)

Evaluación de la calidad fotográfica que analiza imágenes usando CLIP, TOPIQ, SAMP-Net, InsightFace y OpenCV para valorar las fotos según su estética, calidad facial, nitidez técnica, color, exposición y composición.

## Funcionalidades

- **Puntuación multimodelo** - Evaluación estética con TOPIQ (0,93 SRCC) o CLIP+MLP, con perfiles de VRAM configurables
- **Etiquetado semántico** - etiquetas autogeneradas usando CLIP (paisaje, retrato, atardecer, etc.)
- **Reconocimiento facial** - detección, puntuación de calidad, detección de parpadeo y agrupación de personas mediante HDBSCAN
- **Análisis de composición** - SAMP-Net (14 patrones) o puntuación basada en reglas
- **Análisis técnico** - nitidez, color, exposición, rango dinámico, ruido, contraste
- **Sistema de categorías** - más de 30 categorías de contenido con pesos de puntuación específicos por categoría
- **Galería web** - SPA con FastAPI + Angular con filtrado, ordenación, reconocimiento facial y comparación por pares
- **Procesamiento por lotes** - agrupación en lotes en GPU de flujo continuo con tamaños de lote autoajustados

## Inicio rápido

```bash
# Instalar las dependencias
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Puntuar fotos
python facet.py /path/to/photos

# Ver los resultados
python viewer.py
# Abre http://localhost:5000
```

## Documentación

| Documento | Descripción |
|----------|-------------|
| [Instalación](INSTALLATION.md) | Requisitos, configuración de GPU, dependencias |
| [Comandos](COMMANDS.md) | Referencia de todos los comandos de la CLI |
| [Configuración](CONFIGURATION.md) | Referencia completa de `scoring_config.json` |
| [Puntuación](SCORING.md) | Categorías, pesos, guía de ajuste |
| [Reconocimiento facial](FACE_RECOGNITION.md) | Flujo de trabajo facial, agrupación, gestión de personas |
| [Visor](VIEWER.md) | Funcionalidades y uso de la galería web |
| [Interoperabilidad](INTEROP.md) | Intercambiar valoraciones/tags con Lightroom, Capture One, digiKam, darktable |

## Perfiles de VRAM

| Perfil | VRAM de GPU | Modelos | Ideal para |
|---------|----------|--------|----------|
| `legacy` | Sin GPU | CLIP+MLP + SAMP-Net + etiquetado CLIP (CPU) | Sin GPU, 8 GB+ de RAM |
| `8gb` | 6-14 GB | CLIP+MLP + SAMP-Net + etiquetado CLIP | GPU de gama media |
| `16gb` | 16 GB+ | TOPIQ + SAMP-Net + Qwen3.5-2B | Mejor precisión estética |
| `24gb` | 24 GB+ | TOPIQ + Qwen2-VL + Qwen3.5-4B | Mejor precisión + explicaciones de composición |

## Tipos de archivo admitidos

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — requiere `pillow-heif`
- **Archivos RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) - se omiten si existe un JPEG/HEIC equivalente

## Solución de problemas

| Problema | Solución |
|-------|----------|
| "externally-managed-environment" | Usa un entorno virtual |
| Procesamiento lento | Comprueba el perfil de VRAM, usa `--single-pass` para GPU con mucha VRAM |
| La detección facial no usa la GPU | Instala `onnxruntime-gpu` |
| Falta exiftool | Opcional — instálalo con el gestor de paquetes del sistema para mejores resultados; de lo contrario, `exifread` gestiona todos los formatos RAW |

Consulta [Instalación](INSTALLATION.md) para ver instrucciones de configuración detalladas.
