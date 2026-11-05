# Third-party models and licences

> 🌐 **English** · [Français](fr/THIRD_PARTY_MODELS.md) · [Deutsch](de/THIRD_PARTY_MODELS.md) · [Italiano](it/THIRD_PARTY_MODELS.md) · [Español](es/THIRD_PARTY_MODELS.md) · [Português](pt/THIRD_PARTY_MODELS.md) · [简体中文](zh/THIRD_PARTY_MODELS.md)

Facet itself is MIT-licensed, but several of the models it downloads and runs carry their own licences, and some of them forbid commercial use. This page lists every component, generated from the registry in `licensing.py`.

**Commercial mode** (`licensing.mode: commercial` in `scoring_config.json`) makes Facet load only components marked "yes" (and "unclear" ones if `licensing.allow_unclear` is set). Restricted components are never imported, queued or downloaded; each slot is routed to a permissive replacement or the metric is reported as unavailable.

## What is restricted by default

- **pyiqa** (TOPIQ, TOPIQ-IAA, TOPIQ-NR-Face, LIQE, HyperIQA, DBCNN, MUSIQ and CLIP-IQA+): the 0.1.16 code is PolyForm Noncommercial 1.0.0 (earlier releases CC BY-NC-SA) and the weights are CC BY-NC-SA 4.0. The "Apache" classifier on PyPI is an error (upstream issue #294).
- **InsightFace buffalo_l**: the package is MIT, but the pretrained weights are for non-commercial research only. Commercial licences are available from recognition-oss-pack@insightface.ai.

## Components

<!-- BEGIN GENERATED -->
| Component | Code licence | Weights licence | Commercial use | Used for | Replacement |
|---|---|---|---|---|---|
| [pyiqa (package)](https://github.com/chaofengc/IQA-PyTorch) (`pyiqa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | every pyiqa-backed scorer below | `qrealign_native` |
| [TOPIQ NR](https://github.com/chaofengc/IQA-PyTorch) (`topiq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | aesthetic / quality_score (12gb, 16gb, 24gb) | `qrealign_native` |
| [HyperIQA](https://github.com/chaofengc/IQA-PyTorch) (`hyperiqa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | quality (optional) | `qrealign_native` |
| [DBCNN](https://github.com/chaofengc/IQA-PyTorch) (`dbcnn`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | quality (optional) | `qrealign_native` |
| [MUSIQ](https://github.com/chaofengc/IQA-PyTorch) (`musiq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | quality (optional) | `qrealign_native` |
| [MUSIQ (KonIQ)](https://github.com/chaofengc/IQA-PyTorch) (`musiq-koniq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | quality (optional) | `qrealign_native` |
| [CLIP-IQA+](https://github.com/chaofengc/IQA-PyTorch) (`clipiqa+`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | quality (optional) | `qrealign_native` |
| [TOPIQ IAA](https://github.com/chaofengc/IQA-PyTorch) (`topiq_iaa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | aesthetic_iaa (supplementary) | - |
| [TOPIQ NR-Face](https://github.com/chaofengc/IQA-PyTorch) (`topiq_nr_face`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | face_quality_iqa (supplementary) | `ofiq` |
| [LIQE](https://github.com/chaofengc/IQA-PyTorch) (`liqe`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | no | quality + distortion diagnosis (supplementary) | - |
| [Q-ReAlign Mini/Lite (transformers)](https://huggingface.co/q-future) (`qrealign_native`) | MIT | Apache-2.0 | yes | qrealign_score (extended IQA); aesthetic / quality_score (commercial mode) | - |
| [InsightFace buffalo_l](https://github.com/deepinsight/insightface) (`insightface`) | MIT (package) | Non-commercial research only | no | face detection, recognition, 106-point landmarks | `yunet` |
| [YuNet (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`yunet`) | MIT | MIT | yes | face detection (commercial mode) | - |
| [SFace (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`sface`) | Apache-2.0 | Apache-2.0 | yes | face recognition (commercial mode) | - |
| [MediaPipe face_landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) (`mediapipe_face_landmarker`) | Apache-2.0 | Model cards Apache-2.0; bundle licence not stated | yes | eyes / smile blendshapes | - |
| [OFIQ (BSI, python-ofiq)](https://github.com/BSI-OFIQ/OFIQ-Project) (`ofiq`) | MIT | MIT / Apache-2.0 per LICENSE.md | yes | face_quality_iqa (optional) | - |
| [SigLIP 2 NaFlex SO400M](https://huggingface.co/google/siglip2-so400m-patch16-naflex) (`siglip2`) | Apache-2.0 | Apache-2.0 | yes | embeddings (12gb, 16gb, 24gb) | - |
| [OpenCLIP ViT-L-14 (laion2b)](https://github.com/mlfoundations/open_clip) (`clip`) | MIT | MIT | yes | embeddings + tagging (legacy, 8gb) | - |
| [Qwen2-VL-2B](https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct) (`qwen2_vl`) | Apache-2.0 | Apache-2.0 | yes | composition (deprecated) | - |
| [Qwen2.5-VL-7B](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) (`qwen2_5_vl_7b`) | Apache-2.0 | Apache-2.0 | yes | tagging (deprecated) | - |
| [Qwen3-VL-2B](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) (`qwen3_vl_2b`) | Apache-2.0 | Apache-2.0 | yes | tagging (deprecated) | - |
| [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) (`qwen3_5_2b`) | Apache-2.0 | Apache-2.0 | yes | tagging (12gb, 16gb) | - |
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (`qwen3_5_4b`) | Apache-2.0 | Apache-2.0 | yes | tagging (24gb) | - |
| [BiRefNet_dynamic](https://huggingface.co/ZhengPeng7/BiRefNet_dynamic) (`birefnet`) | MIT | MIT | yes | subject saliency | - |
| [CLIP-MLP aesthetic head (LAION)](https://github.com/christophschuhmann/improved-aesthetic-predictor) (`clip_mlp_head`) | Apache-2.0 | No licence stated; trained on AVA | unclear | aesthetic (legacy, 8gb) | `qrealign_native` |
| [SAMP-Net (CADB)](https://github.com/bcmi/Image-Composition-Assessment-Dataset-CADB) (`samp_net`) | MIT | No licence stated; Facet re-hosts | unclear | composition (14 patterns) | - |
| [U2-Net-P](https://github.com/xuebinqin/U-2-Net) (`u2netp`) | Apache-2.0 | No licence stated; Facet re-hosts | unclear | SAMP-Net saliency input | - |
| [DeQA-Score](https://github.com/zhiyuanyou/DeQA-Score) (`deqa`) | MIT | MIT (Llama-2 base; treat as unclear) | unclear | extended IQA (off by default) | - |
| [aesthetic-predictor-v2-5](https://github.com/discus0434/aesthetic-predictor-v2-5) (`aesthetic_v25`) | AGPL-3.0 | - | no | extended IQA (deprecated, off by default) | `qrealign_native` |
<!-- END GENERATED -->

## Disclaimer

- A weights licence is not the licence of the training data. The licences of the training datasets (AVA, KonIQ, VGGFace2, MS1MV2, 300-W) have not been verified.
- This page is information, not legal advice, and comes with no warranty. Check the licences yourself before any commercial deployment.
- Immich's personal-use permission for InsightFace does not extend to Immich's users or to Facet's.
