# Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · [Español](../es/README.md) · **Português**

Avaliação da qualidade de fotos que analisa imagens usando CLIP, TOPIQ, SAMP-Net, InsightFace e OpenCV para classificar fotos quanto à estética, qualidade do rosto, nitidez técnica, cor, exposição e composição.

## Recursos

- **Pontuação multimodelo** - avaliação estética com TOPIQ (0,93 SRCC) ou CLIP+MLP, com perfis de VRAM configuráveis
- **Marcação semântica** - tags geradas automaticamente usando CLIP (paisagem, retrato, pôr do sol, etc.)
- **Reconhecimento facial** - detecção, pontuação de qualidade, detecção de piscadas e agrupamento de pessoas via HDBSCAN
- **Análise de composição** - SAMP-Net (14 padrões) ou pontuação baseada em regras
- **Análise técnica** - nitidez, cor, exposição, faixa dinâmica, ruído, contraste
- **Sistema de categorias** - mais de 30 categorias de conteúdo com pesos de pontuação específicos por categoria
- **Galeria web** - SPA em FastAPI + Angular com filtragem, ordenação, reconhecimento facial e comparação pareada
- **Processamento em lote** - lotes de GPU em fluxo contínuo com tamanhos de lote autoajustados

## Início Rápido

```bash
# Install dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Score photos
python facet.py /path/to/photos

# View results
python viewer.py
# Open http://localhost:5000
```

## Documentação

| Documento | Descrição |
|----------|-------------|
| [Instalação](INSTALLATION.md) | Requisitos, configuração de GPU, dependências |
| [Comandos](COMMANDS.md) | Referência de todos os comandos da CLI |
| [Configuração](CONFIGURATION.md) | Referência completa do `scoring_config.json` |
| [Pontuação](SCORING.md) | Categorias, pesos, guia de ajuste |
| [Reconhecimento Facial](FACE_RECOGNITION.md) | Fluxo de trabalho de rostos, agrupamento, gerenciamento de pessoas |
| [Visualizador](VIEWER.md) | Recursos e uso da galeria web |
| [Interoperabilidade](INTEROP.md) | Trocar classificações/tags com Lightroom, Capture One, digiKam, darktable |
| [Implantação](DEPLOYMENT.md) | Implantação em produção (Synology NAS, Linux, Docker) |

## Perfis de VRAM

| Perfil | VRAM da GPU | Modelos | Ideal Para |
|---------|----------|--------|----------|
| `legacy` | Sem GPU | CLIP+MLP + SAMP-Net + marcação CLIP (CPU) | Sem GPU, 8GB+ de RAM |
| `8gb` | 6-14GB | CLIP+MLP + SAMP-Net + marcação CLIP | GPUs intermediárias |
| `16gb` | 16GB+ | TOPIQ + SAMP-Net + Qwen3.5-2B | Melhor precisão estética |
| `24gb` | 24GB+ | TOPIQ + Qwen2-VL + Qwen3.5-4B | Melhor precisão + explicações de composição |

## Tipos de Arquivo Suportados

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — requer `pillow-heif`
- **Arquivos RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) - ignorados se houver um JPEG/HEIC correspondente

## Solução de Problemas

| Problema | Solução |
|-------|----------|
| "externally-managed-environment" | Use um ambiente virtual |
| Processamento lento | Verifique o perfil de VRAM, use `--single-pass` para GPUs com VRAM alta |
| Detecção facial não usa a GPU | Instale `onnxruntime-gpu` |
| exiftool ausente | Opcional — instale pelo gerenciador de pacotes do sistema para melhores resultados; caso contrário, o `exifread` cuida de todos os formatos RAW |

Consulte [Instalação](INSTALLATION.md) para instruções detalhadas de configuração.
