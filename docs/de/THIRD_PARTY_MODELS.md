# Modelle von Drittanbietern und Lizenzen

> 🌐 [English](../THIRD_PARTY_MODELS.md) · [Français](../fr/THIRD_PARTY_MODELS.md) · **Deutsch** · [Italiano](../it/THIRD_PARTY_MODELS.md) · [Español](../es/THIRD_PARTY_MODELS.md) · [Português](../pt/THIRD_PARTY_MODELS.md) · [简体中文](../zh/THIRD_PARTY_MODELS.md)

Facet selbst steht unter der MIT-Lizenz, doch mehrere der heruntergeladenen und ausgeführten Modelle haben eigene Lizenzen, und einige verbieten die kommerzielle Nutzung. Diese Seite listet alle Komponenten und wird aus der Registry in `licensing.py` erzeugt.

Der **kommerzielle Modus** (`licensing.mode: commercial` in `scoring_config.json`) lädt nur Komponenten mit „ja“ (und „unklar“, wenn `licensing.allow_unclear` gesetzt ist). Eingeschränkte Komponenten werden nie importiert, eingeplant oder heruntergeladen; jeder Slot wird auf einen freizügigen Ersatz umgeleitet, oder die Metrik wird als nicht verfügbar gemeldet.

## Was standardmäßig eingeschränkt ist

- **pyiqa** (TOPIQ, TOPIQ-IAA, TOPIQ-NR-Face, LIQE, HyperIQA, DBCNN, MUSIQ und CLIP-IQA+): Der Code 0.1.16 steht unter PolyForm Noncommercial 1.0.0 (frühere Versionen unter CC BY-NC-SA), die Gewichte unter CC BY-NC-SA 4.0. Die Klassifizierung „Apache“ auf PyPI ist ein Fehler (Upstream-Issue #294).
- **InsightFace buffalo_l**: Das Paket ist MIT, die vortrainierten Gewichte sind jedoch nur für nichtkommerzielle Forschung freigegeben. Kommerzielle Lizenzen gibt es über recognition-oss-pack@insightface.ai.

## Komponenten

<!-- BEGIN GENERATED -->
| Komponente | Code-Lizenz | Gewichte-Lizenz | Kommerzielle Nutzung | Verwendet für | Ersatz |
|---|---|---|---|---|---|
| [pyiqa (package)](https://github.com/chaofengc/IQA-PyTorch) (`pyiqa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | every pyiqa-backed scorer below | `qrealign_native` |
| [TOPIQ NR](https://github.com/chaofengc/IQA-PyTorch) (`topiq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | aesthetic / quality_score (12gb, 16gb, 24gb) | `qrealign_native` |
| [HyperIQA](https://github.com/chaofengc/IQA-PyTorch) (`hyperiqa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | quality (optional) | `qrealign_native` |
| [DBCNN](https://github.com/chaofengc/IQA-PyTorch) (`dbcnn`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | quality (optional) | `qrealign_native` |
| [MUSIQ](https://github.com/chaofengc/IQA-PyTorch) (`musiq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | quality (optional) | `qrealign_native` |
| [MUSIQ (KonIQ)](https://github.com/chaofengc/IQA-PyTorch) (`musiq-koniq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | quality (optional) | `qrealign_native` |
| [CLIP-IQA+](https://github.com/chaofengc/IQA-PyTorch) (`clipiqa+`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | quality (optional) | `qrealign_native` |
| [TOPIQ IAA](https://github.com/chaofengc/IQA-PyTorch) (`topiq_iaa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | aesthetic_iaa (supplementary) | - |
| [TOPIQ NR-Face](https://github.com/chaofengc/IQA-PyTorch) (`topiq_nr_face`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | face_quality_iqa (supplementary) | `ofiq` |
| [LIQE](https://github.com/chaofengc/IQA-PyTorch) (`liqe`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | nein | quality + distortion diagnosis (supplementary) | - |
| [Q-ReAlign Mini/Lite (transformers)](https://huggingface.co/q-future) (`qrealign_native`) | MIT | Apache-2.0 | ja | qrealign_score (extended IQA); aesthetic / quality_score (commercial mode) | - |
| [InsightFace buffalo_l](https://github.com/deepinsight/insightface) (`insightface`) | MIT (package) | Non-commercial research only | nein | face detection, recognition, 106-point landmarks | `yunet` |
| [YuNet (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`yunet`) | MIT | MIT | ja | face detection (commercial mode) | - |
| [SFace (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`sface`) | Apache-2.0 | Apache-2.0 | ja | face recognition (commercial mode) | - |
| [MediaPipe face_landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) (`mediapipe_face_landmarker`) | Apache-2.0 | Model cards Apache-2.0; bundle licence not stated | ja | eyes / smile blendshapes | - |
| [OFIQ (BSI, python-ofiq)](https://github.com/BSI-OFIQ/OFIQ-Project) (`ofiq`) | MIT | MIT / Apache-2.0 per LICENSE.md | ja | face_quality_iqa (optional) | - |
| [SigLIP 2 NaFlex SO400M](https://huggingface.co/google/siglip2-so400m-patch16-naflex) (`siglip2`) | Apache-2.0 | Apache-2.0 | ja | embeddings (12gb, 16gb, 24gb) | - |
| [OpenCLIP ViT-L-14 (laion2b)](https://github.com/mlfoundations/open_clip) (`clip`) | MIT | MIT | ja | embeddings + tagging (legacy, 8gb) | - |
| [Qwen2-VL-2B](https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct) (`qwen2_vl`) | Apache-2.0 | Apache-2.0 | ja | composition (deprecated) | - |
| [Qwen2.5-VL-7B](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) (`qwen2_5_vl_7b`) | Apache-2.0 | Apache-2.0 | ja | tagging (deprecated) | - |
| [Qwen3-VL-2B](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) (`qwen3_vl_2b`) | Apache-2.0 | Apache-2.0 | ja | tagging (deprecated) | - |
| [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) (`qwen3_5_2b`) | Apache-2.0 | Apache-2.0 | ja | tagging (12gb, 16gb) | - |
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (`qwen3_5_4b`) | Apache-2.0 | Apache-2.0 | ja | tagging (24gb) | - |
| [BiRefNet_dynamic](https://huggingface.co/ZhengPeng7/BiRefNet_dynamic) (`birefnet`) | MIT | MIT | ja | subject saliency | - |
| [CLIP-MLP aesthetic head (LAION)](https://github.com/christophschuhmann/improved-aesthetic-predictor) (`clip_mlp_head`) | Apache-2.0 | No licence stated; trained on AVA | unklar | aesthetic (legacy, 8gb) | `qrealign_native` |
| [SAMP-Net (CADB)](https://github.com/bcmi/Image-Composition-Assessment-Dataset-CADB) (`samp_net`) | MIT | No licence stated; Facet re-hosts | unklar | composition (14 patterns) | - |
| [U2-Net-P](https://github.com/xuebinqin/U-2-Net) (`u2netp`) | Apache-2.0 | No licence stated; Facet re-hosts | unklar | SAMP-Net saliency input | - |
| [DeQA-Score](https://github.com/zhiyuanyou/DeQA-Score) (`deqa`) | MIT | MIT (Llama-2 base; treat as unclear) | unklar | extended IQA (off by default) | - |
| [aesthetic-predictor-v2-5](https://github.com/discus0434/aesthetic-predictor-v2-5) (`aesthetic_v25`) | AGPL-3.0 | - | nein | extended IQA (deprecated, off by default) | `qrealign_native` |
<!-- END GENERATED -->

## Haftungsausschluss

- Die Lizenz der Gewichte ist nicht die Lizenz der Trainingsdaten. Die Lizenzen der Trainingsdatensätze (AVA, KonIQ, VGGFace2, MS1MV2, 300-W) wurden nicht geprüft.
- Diese Seite dient der Information, ist keine Rechtsberatung und erfolgt ohne Gewähr. Prüfen Sie die Lizenzen vor jedem kommerziellen Einsatz selbst.
- Die private Nutzungserlaubnis für InsightFace, die Immich erhalten hat, gilt weder für die Nutzer von Immich noch für die von Facet.
