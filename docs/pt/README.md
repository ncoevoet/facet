# Documentação do Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · [Español](../es/README.md) · **Português**

O Facet é um mecanismo multidimensional de análise de fotos: ele pontua, classifica e
seleciona uma biblioteca de fotos local, e depois serve uma galeria para navegá-la. Comece
pela [Instalação](INSTALLATION.md) — ela cobre toda configuração em blocos prontos para
copiar e colar.

| Documento | Descrição |
|----------|-------------|
| [Instalação](INSTALLATION.md) | Configuração por hardware, com ou sem Docker; dependências |
| [Comandos](COMMANDS.md) | Referência de todos os comandos da CLI |
| [Configuração](CONFIGURATION.md) | Referência completa do `scoring_config.json` |
| [Pontuação](SCORING.md) | Categorias, pesos, guia de ajuste |
| [Reconhecimento Facial](FACE_RECOGNITION.md) | Fluxo de trabalho de rostos, agrupamento, gerenciamento de pessoas |
| [Visualizador](VIEWER.md) | Recursos e uso da galeria web |
| [Interoperabilidade](INTEROP.md) | Trocar classificações/tags com Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Sincronizar avaliações e favoritos com o Immich, além do webhook de entrada |
| [Implantação](DEPLOYMENT.md) | NAS, servidores remotos, HTTPS, backups, multiusuário |

## Tipos de arquivo suportados

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — requer `pillow-heif`
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — pulado quando existe um JPEG/HEIC correspondente

## Perguntas frequentes

| Problema | Resposta |
|-------|----------|
| Qual perfil devo usar? | [Instalação › Qual perfil combina com o meu hardware?](INSTALLATION.md#qual-perfil-combina-com-o-meu-hardware) |
| "externally-managed-environment" na instalação | Use um ambiente virtual (ou o Docker) — veja [Instalação](INSTALLATION.md) |
| Processamento lento | Verifique o perfil; `--single-pass` ajuda em GPUs com VRAM alta |
| Detecção de faces não usa a GPU | Instale o `onnxruntime-gpu` — veja [Instalação](INSTALLATION.md#onnx-runtime-para-detecção-de-faces) |
| exiftool ausente | Opcional — veja [Instalação › exiftool](INSTALLATION.md#exiftool) |
