# Modelli di terze parti e licenze

> 🌐 [English](../THIRD_PARTY_MODELS.md) · [Français](../fr/THIRD_PARTY_MODELS.md) · [Deutsch](../de/THIRD_PARTY_MODELS.md) · **Italiano** · [Español](../es/THIRD_PARTY_MODELS.md) · [Português](../pt/THIRD_PARTY_MODELS.md) · [简体中文](../zh/THIRD_PARTY_MODELS.md)

Facet è distribuito con licenza MIT, ma diversi dei modelli che scarica ed esegue hanno licenze proprie, e alcuni vietano l'uso commerciale. Questa pagina elenca ogni componente ed è generata dal registro in `licensing.py`.

La **modalità commerciale** (`licensing.mode: commercial` in `scoring_config.json`) carica solo i componenti contrassegnati «sì» (e «incerto» se è attivo `licensing.allow_unclear`). I componenti con restrizioni non vengono mai importati, messi in coda o scaricati; ogni slot è indirizzato a un sostituto permissivo oppure la metrica è segnalata come non disponibile.

## Cosa è limitato per impostazione predefinita

- **pyiqa** (TOPIQ, TOPIQ-IAA, TOPIQ-NR-Face, LIQE, HyperIQA, DBCNN, MUSIQ e CLIP-IQA+): il codice 0.1.16 è PolyForm Noncommercial 1.0.0 (le versioni precedenti CC BY-NC-SA) e i pesi sono CC BY-NC-SA 4.0. Il classificatore «Apache» su PyPI è un errore (issue upstream n. 294).
- **InsightFace buffalo_l**: il pacchetto è MIT, ma i pesi preaddestrati sono solo per ricerca non commerciale. Le licenze commerciali si ottengono da recognition-oss-pack@insightface.ai.

## Componenti

<!-- BEGIN GENERATED -->
| Componente | Licenza del codice | Licenza dei pesi | Uso commerciale | Usato per | Sostituto |
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
| [Q-ReAlign Mini/Lite (transformers)](https://huggingface.co/q-future) (`qrealign_native`) | MIT | Apache-2.0 | sì | qrealign_score (extended IQA); aesthetic / quality_score (commercial mode) | - |
| [InsightFace buffalo_l](https://github.com/deepinsight/insightface) (`insightface`) | MIT (package) | Non-commercial research only | no | face detection, recognition, 106-point landmarks | `yunet` |
| [YuNet (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`yunet`) | MIT | MIT | sì | face detection (commercial mode) | - |
| [SFace (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`sface`) | Apache-2.0 | Apache-2.0 | sì | face recognition (commercial mode) | - |
| [MediaPipe face_landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) (`mediapipe_face_landmarker`) | Apache-2.0 | Model cards Apache-2.0; bundle licence not stated | sì | eyes / smile blendshapes | - |
| [OFIQ (BSI, python-ofiq)](https://github.com/BSI-OFIQ/OFIQ-Project) (`ofiq`) | MIT | MIT / Apache-2.0 per LICENSE.md | sì | face_quality_iqa (optional) | - |
| [SigLIP 2 NaFlex SO400M](https://huggingface.co/google/siglip2-so400m-patch16-naflex) (`siglip2`) | Apache-2.0 | Apache-2.0 | sì | embeddings (12gb, 16gb, 24gb) | - |
| [OpenCLIP ViT-L-14 (laion2b)](https://github.com/mlfoundations/open_clip) (`clip`) | MIT | MIT | sì | embeddings + tagging (legacy, 8gb) | - |
| [Qwen2-VL-2B](https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct) (`qwen2_vl`) | Apache-2.0 | Apache-2.0 | sì | composition (deprecated) | - |
| [Qwen2.5-VL-7B](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) (`qwen2_5_vl_7b`) | Apache-2.0 | Apache-2.0 | sì | tagging (deprecated) | - |
| [Qwen3-VL-2B](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) (`qwen3_vl_2b`) | Apache-2.0 | Apache-2.0 | sì | tagging (deprecated) | - |
| [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) (`qwen3_5_2b`) | Apache-2.0 | Apache-2.0 | sì | tagging (12gb, 16gb) | - |
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (`qwen3_5_4b`) | Apache-2.0 | Apache-2.0 | sì | tagging (24gb) | - |
| [BiRefNet_dynamic](https://huggingface.co/ZhengPeng7/BiRefNet_dynamic) (`birefnet`) | MIT | MIT | sì | subject saliency | - |
| [CLIP-MLP aesthetic head (LAION)](https://github.com/christophschuhmann/improved-aesthetic-predictor) (`clip_mlp_head`) | Apache-2.0 | No licence stated; trained on AVA | incerto | aesthetic (legacy, 8gb) | `qrealign_native` |
| [SAMP-Net (CADB)](https://github.com/bcmi/Image-Composition-Assessment-Dataset-CADB) (`samp_net`) | MIT | No licence stated; Facet re-hosts | incerto | composition (14 patterns) | - |
| [U2-Net-P](https://github.com/xuebinqin/U-2-Net) (`u2netp`) | Apache-2.0 | No licence stated; Facet re-hosts | incerto | SAMP-Net saliency input | - |
| [DeQA-Score](https://github.com/zhiyuanyou/DeQA-Score) (`deqa`) | MIT | MIT (Llama-2 base; treat as unclear) | incerto | extended IQA (off by default) | - |
| [aesthetic-predictor-v2-5](https://github.com/discus0434/aesthetic-predictor-v2-5) (`aesthetic_v25`) | AGPL-3.0 | - | no | extended IQA (deprecated, off by default) | `qrealign_native` |
<!-- END GENERATED -->

## Avvertenza

- La licenza dei pesi non è la licenza dei dati di addestramento. Le licenze dei dataset di addestramento (AVA, KonIQ, VGGFace2, MS1MV2, 300-W) non sono state verificate.
- Questa pagina ha scopo informativo, non costituisce consulenza legale ed è fornita senza garanzie. Verificate voi stessi le licenze prima di qualsiasi distribuzione commerciale.
- Il permesso d'uso personale di InsightFace concesso a Immich non si estende agli utenti di Immich né a quelli di Facet.
