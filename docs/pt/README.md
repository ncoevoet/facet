# Documentação do Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · [Español](../es/README.md) · **Português** · [简体中文](../zh/README.md)

O Facet é um mecanismo multidimensional de análise de fotos: ele pontua, classifica e
seleciona uma biblioteca de fotos local, e depois serve uma galeria para navegá-la. Comece
pela [Instalação](INSTALLATION.md) — ela cobre toda configuração em blocos prontos para
copiar e colar.

| Documento | Descrição |
|----------|-------------|
| [Instalação](INSTALLATION.md) | Configuração por hardware, com ou sem Docker; dependências |
| [Primeiros passos](GETTING_STARTED.md) | Roteiro da primeira execução: da instalação à varredura, revisão, treinamento, descarte, etiquetagem e exportação |
| [Comandos](COMMANDS.md) | Referência de todos os comandos da CLI |
| [Configuração](CONFIGURATION.md) | Referência completa do `scoring_config.json` |
| [Pontuação](SCORING.md) | Categorias, pesos, guia de ajuste |
| [Reconhecimento Facial](FACE_RECOGNITION.md) | Fluxo de trabalho de rostos, agrupamento, gerenciamento de pessoas |
| [Visualizador](VIEWER.md) | Recursos e uso da galeria web |
| [API](../API.md) | Referência da API HTTP do visualizador |
| [Interoperabilidade](INTEROP.md) | Trocar classificações/tags com Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Sincronizar avaliações e favoritos com o Immich, além do webhook de entrada |
| [Implantação](DEPLOYMENT.md) | NAS, servidores remotos, HTTPS, backups, multiusuário |
| [Religar](RELINK.md) | Religar fotos movidas |

## Tipos de arquivo suportados

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC/HIF** (.heic, .heif, .hif) — requer `pillow-heif`; fotos `.HIF` Canon HDR PQ são convertidas (tone mapping) para sRGB SDR
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — pulado quando existe um JPEG/HEIC correspondente. Um RAW que o LibRaw não consegue decodificar (uma mesclagem `-HDR.dng` / `-Pano.dng` do Lightroom ou uma câmera mais nova que o LibRaw) é pontuado a partir da maior pré-visualização incorporada, via `exiftool`; a pré-visualização precisa ter pelo menos 1024 px no lado maior. O Lightroom Classic 13+ armazena essa pré-visualização como JPEG XL, que o Facet decodifica diretamente
- **PNG, GIF, WebP, BMP, TIFF** (.png, .gif, .webp, .bmp, .tif, .tiff) — a escala de cinza de 16 bits é convertida para 8 bits, um canal alfa é composto sobre branco, e GIF/WebP animados são pontuados pelo primeiro quadro. O TIFF é convertido para JPEG para o navegador. PNG, WebP e TIFF contêm EXIF quando o programa que os gravou o armazenou; GIF e BMP não podem, então `date_taken` e câmera/lente ficam vazios para eles
- **AVIF** (.avif) — precisa de um Pillow compilado com suporte a AVIF (nativo a partir de `pillow>=11.3`); fotos HDR PQ são convertidas (tone mapping) para sRGB SDR; o EXIF é lido quando está presente
- **JPEG XL** (.jxl) — funciona de imediato pela dependência principal `imagecodecs`, inclusive no Docker. O HDR não passa por tone mapping, arquivos animados são pontuados pelo primeiro quadro e o EXIF válido é lido quando presente. Os JPEG reconstruídos mantêm a gestão de cor ICC; os perfis de cor JXL nativos não estão disponíveis

## Perguntas frequentes

| Problema | Resposta |
|-------|----------|
| Qual perfil devo usar? | [Instalação › Qual perfil combina com o meu hardware?](INSTALLATION.md#qual-perfil-combina-com-o-meu-hardware) |
| "externally-managed-environment" na instalação | Use um ambiente virtual (ou o Docker) — veja [Instalação](INSTALLATION.md) |
| Processamento lento | Verifique o perfil; `--single-pass` pode ajudar nos perfis `legacy`/`8gb` com muita VRAM (fora do modo comercial, `12gb`/`16gb`/`24gb` sempre executam multi-passo) |
| Detecção de faces não usa a GPU | Execute `python facet.py --doctor` (seção ONNX Runtime) e instale o `onnxruntime-gpu` no lugar do `onnxruntime`, nunca ao lado dele — veja [Instalação](INSTALLATION.md#onnx-runtime-para-detecção-de-faces) |
| exiftool ausente | Opcional — veja [Instalação › exiftool](INSTALLATION.md#exiftool) |
