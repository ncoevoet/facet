# Modelos de terceiros e licenças

> 🌐 [English](../THIRD_PARTY_MODELS.md) · [Français](../fr/THIRD_PARTY_MODELS.md) · [Deutsch](../de/THIRD_PARTY_MODELS.md) · [Italiano](../it/THIRD_PARTY_MODELS.md) · [Español](../es/THIRD_PARTY_MODELS.md) · **Português** · [简体中文](../zh/THIRD_PARTY_MODELS.md)

O Facet tem licença MIT, mas vários dos modelos que baixa e executa têm licenças próprias, e alguns proíbem o uso comercial. Esta página lista cada componente e é gerada a partir do registro em `licensing.py`.

O **modo comercial** (`licensing.mode: commercial` em `scoring_config.json`) carrega apenas componentes marcados como «sim» (e «incerto» se `licensing.allow_unclear` estiver ativo). Componentes restritos nunca são importados, enfileirados nem baixados; cada slot é redirecionado a um substituto permissivo ou a métrica é informada como indisponível.

## O que é restrito por padrão

- **pyiqa** (TOPIQ, TOPIQ-IAA, TOPIQ-NR-Face, LIQE, HyperIQA, DBCNN, MUSIQ e CLIP-IQA+): o código 0.1.16 é PolyForm Noncommercial 1.0.0 (versões anteriores CC BY-NC-SA) e os pesos são CC BY-NC-SA 4.0. O classificador «Apache» no PyPI é um erro (issue upstream n.º 294).
- **InsightFace buffalo_l**: o pacote é MIT, mas os pesos pré-treinados são apenas para pesquisa não comercial. Licenças comerciais estão disponíveis em recognition-oss-pack@insightface.ai.

## Componentes

<!-- BEGIN GENERATED -->
| Componente | Licença do código | Licença dos pesos | Uso comercial | Usado para | Substituto |
|---|---|---|---|---|---|
| [pyiqa (package)](https://github.com/chaofengc/IQA-PyTorch) (`pyiqa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | every pyiqa-backed scorer below | `qrealign_native` |
| [TOPIQ NR](https://github.com/chaofengc/IQA-PyTorch) (`topiq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | aesthetic / quality_score (12gb, 16gb, 24gb) | `qrealign_native` |
| [HyperIQA](https://github.com/chaofengc/IQA-PyTorch) (`hyperiqa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | quality (optional) | `qrealign_native` |
| [DBCNN](https://github.com/chaofengc/IQA-PyTorch) (`dbcnn`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | quality (optional) | `qrealign_native` |
| [MUSIQ](https://github.com/chaofengc/IQA-PyTorch) (`musiq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | quality (optional) | `qrealign_native` |
| [MUSIQ (KonIQ)](https://github.com/chaofengc/IQA-PyTorch) (`musiq-koniq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | quality (optional) | `qrealign_native` |
| [CLIP-IQA+](https://github.com/chaofengc/IQA-PyTorch) (`clipiqa+`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | quality (optional) | `qrealign_native` |
| [TOPIQ IAA](https://github.com/chaofengc/IQA-PyTorch) (`topiq_iaa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | aesthetic_iaa (supplementary) | - |
| [TOPIQ NR-Face](https://github.com/chaofengc/IQA-PyTorch) (`topiq_nr_face`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | face_quality_iqa (supplementary) | `ofiq` |
| [LIQE](https://github.com/chaofengc/IQA-PyTorch) (`liqe`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | não | quality + distortion diagnosis (supplementary) | - |
| [Q-ReAlign Mini/Lite (transformers)](https://huggingface.co/q-future) (`qrealign_native`) | MIT | Apache-2.0 | sim | qrealign_score (extended IQA); aesthetic / quality_score (commercial mode) | - |
| [InsightFace buffalo_l](https://github.com/deepinsight/insightface) (`insightface`) | MIT (package) | Non-commercial research only | não | face detection, recognition, 106-point landmarks | `yunet` |
| [YuNet (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`yunet`) | MIT | MIT | sim | face detection (commercial mode) | - |
| [SFace (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`sface`) | Apache-2.0 | Apache-2.0 | sim | face recognition (commercial mode) | - |
| [MediaPipe face_landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) (`mediapipe_face_landmarker`) | Apache-2.0 | Model cards Apache-2.0; bundle licence not stated | sim | eyes / smile blendshapes | - |
| [OFIQ (BSI, python-ofiq)](https://github.com/BSI-OFIQ/OFIQ-Project) (`ofiq`) | MIT | MIT / Apache-2.0 per LICENSE.md | sim | face_quality_iqa (optional) | - |
| [SigLIP 2 NaFlex SO400M](https://huggingface.co/google/siglip2-so400m-patch16-naflex) (`siglip2`) | Apache-2.0 | Apache-2.0 | sim | embeddings (12gb, 16gb, 24gb) | - |
| [OpenCLIP ViT-L-14 (laion2b)](https://github.com/mlfoundations/open_clip) (`clip`) | MIT | MIT | sim | embeddings + tagging (legacy, 8gb) | - |
| [Qwen2-VL-2B](https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct) (`qwen2_vl`) | Apache-2.0 | Apache-2.0 | sim | composition (deprecated) | - |
| [Qwen2.5-VL-7B](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) (`qwen2_5_vl_7b`) | Apache-2.0 | Apache-2.0 | sim | tagging (deprecated) | - |
| [Qwen3-VL-2B](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) (`qwen3_vl_2b`) | Apache-2.0 | Apache-2.0 | sim | tagging (deprecated) | - |
| [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) (`qwen3_5_2b`) | Apache-2.0 | Apache-2.0 | sim | tagging (12gb, 16gb) | - |
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (`qwen3_5_4b`) | Apache-2.0 | Apache-2.0 | sim | tagging (24gb) | - |
| [BiRefNet_dynamic](https://huggingface.co/ZhengPeng7/BiRefNet_dynamic) (`birefnet`) | MIT | MIT | sim | subject saliency | - |
| [CLIP-MLP aesthetic head (LAION)](https://github.com/christophschuhmann/improved-aesthetic-predictor) (`clip_mlp_head`) | Apache-2.0 | No licence stated; trained on AVA | incerto | aesthetic (legacy, 8gb) | `qrealign_native` |
| [SAMP-Net (CADB)](https://github.com/bcmi/Image-Composition-Assessment-Dataset-CADB) (`samp_net`) | MIT | No licence stated; Facet re-hosts | incerto | composition (14 patterns) | - |
| [U2-Net-P](https://github.com/xuebinqin/U-2-Net) (`u2netp`) | Apache-2.0 | No licence stated; Facet re-hosts | incerto | SAMP-Net saliency input | - |
| [DeQA-Score](https://github.com/zhiyuanyou/DeQA-Score) (`deqa`) | MIT | MIT (Llama-2 base; treat as unclear) | incerto | extended IQA (off by default) | - |
| [aesthetic-predictor-v2-5](https://github.com/discus0434/aesthetic-predictor-v2-5) (`aesthetic_v25`) | AGPL-3.0 | - | não | extended IQA (deprecated, off by default) | `qrealign_native` |
<!-- END GENERATED -->

## Aviso legal

- A licença dos pesos não é a licença dos dados de treinamento. As licenças dos conjuntos de treinamento (AVA, KonIQ, VGGFace2, MS1MV2, 300-W) não foram verificadas.
- Esta página é informativa, não constitui aconselhamento jurídico e é fornecida sem garantia. Verifique as licenças por conta própria antes de qualquer implantação comercial.
- A permissão de uso pessoal do InsightFace concedida ao Immich não se estende aos usuários do Immich nem aos do Facet.
