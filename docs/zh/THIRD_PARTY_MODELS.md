# 第三方模型与许可证

> 🌐 [English](../THIRD_PARTY_MODELS.md) · [Français](../fr/THIRD_PARTY_MODELS.md) · [Deutsch](../de/THIRD_PARTY_MODELS.md) · [Italiano](../it/THIRD_PARTY_MODELS.md) · [Español](../es/THIRD_PARTY_MODELS.md) · [Português](../pt/THIRD_PARTY_MODELS.md) · **简体中文**

Facet 本身采用 MIT 许可证，但它下载并运行的若干模型有各自的许可证，其中一些禁止商业使用。本页列出所有组件，内容由 `licensing.py` 中的注册表生成。

**商业模式**（`scoring_config.json` 中的 `licensing.mode: commercial`）只加载标记为“是”的组件（若设置了 `licensing.allow_unclear`，则包括“不明确”的组件）。受限组件绝不会被导入、排队或下载；每个环节都会改用宽松许可的替代品，或将该指标报告为不可用。

## 默认受限的内容

- **pyiqa**（TOPIQ、TOPIQ-IAA、TOPIQ-NR-Face、LIQE、HyperIQA、DBCNN、MUSIQ、CLIP-IQA+）：0.1.16 版代码采用 PolyForm Noncommercial 1.0.0（更早版本为 CC BY-NC-SA），权重为 CC BY-NC-SA 4.0。PyPI 上的“Apache”分类标签有误（上游 issue #294）。
- **InsightFace buffalo_l**：软件包为 MIT，但预训练权重仅限非商业研究使用。可通过 recognition-oss-pack@insightface.ai 获取商业许可。

## 组件

<!-- BEGIN GENERATED -->
| 组件 | 代码许可证 | 权重许可证 | 商业使用 | 用途 | 替代 |
|---|---|---|---|---|---|
| [pyiqa (package)](https://github.com/chaofengc/IQA-PyTorch) (`pyiqa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | every pyiqa-backed scorer below | `qrealign_native` |
| [TOPIQ NR](https://github.com/chaofengc/IQA-PyTorch) (`topiq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | aesthetic / quality_score (12gb, 16gb, 24gb) | `qrealign_native` |
| [HyperIQA](https://github.com/chaofengc/IQA-PyTorch) (`hyperiqa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | quality (optional) | `qrealign_native` |
| [DBCNN](https://github.com/chaofengc/IQA-PyTorch) (`dbcnn`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | quality (optional) | `qrealign_native` |
| [MUSIQ](https://github.com/chaofengc/IQA-PyTorch) (`musiq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | quality (optional) | `qrealign_native` |
| [MUSIQ (KonIQ)](https://github.com/chaofengc/IQA-PyTorch) (`musiq-koniq`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | quality (optional) | `qrealign_native` |
| [CLIP-IQA+](https://github.com/chaofengc/IQA-PyTorch) (`clipiqa+`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | quality (optional) | `qrealign_native` |
| [TOPIQ IAA](https://github.com/chaofengc/IQA-PyTorch) (`topiq_iaa`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | aesthetic_iaa (supplementary) | - |
| [TOPIQ NR-Face](https://github.com/chaofengc/IQA-PyTorch) (`topiq_nr_face`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | face_quality_iqa (supplementary) | `ofiq` |
| [LIQE](https://github.com/chaofengc/IQA-PyTorch) (`liqe`) | PolyForm-NC 1.0.0 (pyiqa 0.1.16) | CC BY-NC-SA 4.0 (IQA-PyTorch-Weights) | 否 | quality + distortion diagnosis (supplementary) | - |
| [Q-ReAlign Mini/Lite (transformers)](https://huggingface.co/q-future) (`qrealign_native`) | MIT | Apache-2.0 | 是 | qrealign_score (extended IQA); aesthetic / quality_score (commercial mode) | - |
| [InsightFace buffalo_l](https://github.com/deepinsight/insightface) (`insightface`) | MIT (package) | Non-commercial research only | 否 | face detection, recognition, 106-point landmarks | `yunet` |
| [YuNet (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`yunet`) | MIT | MIT | 是 | face detection (commercial mode) | - |
| [SFace (opencv_zoo)](https://github.com/opencv/opencv_zoo) (`sface`) | Apache-2.0 | Apache-2.0 | 是 | face recognition (commercial mode) | - |
| [MediaPipe face_landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) (`mediapipe_face_landmarker`) | Apache-2.0 | Model cards Apache-2.0; bundle licence not stated | 是 | eyes / smile blendshapes | - |
| [OFIQ (BSI, python-ofiq)](https://github.com/BSI-OFIQ/OFIQ-Project) (`ofiq`) | MIT | MIT / Apache-2.0 per LICENSE.md | 是 | face_quality_iqa (optional) | - |
| [SigLIP 2 NaFlex SO400M](https://huggingface.co/google/siglip2-so400m-patch16-naflex) (`siglip2`) | Apache-2.0 | Apache-2.0 | 是 | embeddings (12gb, 16gb, 24gb) | - |
| [OpenCLIP ViT-L-14 (laion2b)](https://github.com/mlfoundations/open_clip) (`clip`) | MIT | MIT | 是 | embeddings + tagging (legacy, 8gb) | - |
| [Qwen2-VL-2B](https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct) (`qwen2_vl`) | Apache-2.0 | Apache-2.0 | 是 | composition (deprecated) | - |
| [Qwen2.5-VL-7B](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) (`qwen2_5_vl_7b`) | Apache-2.0 | Apache-2.0 | 是 | tagging (deprecated) | - |
| [Qwen3-VL-2B](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) (`qwen3_vl_2b`) | Apache-2.0 | Apache-2.0 | 是 | tagging (deprecated) | - |
| [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) (`qwen3_5_2b`) | Apache-2.0 | Apache-2.0 | 是 | tagging (12gb, 16gb) | - |
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (`qwen3_5_4b`) | Apache-2.0 | Apache-2.0 | 是 | tagging (24gb) | - |
| [BiRefNet_dynamic](https://huggingface.co/ZhengPeng7/BiRefNet_dynamic) (`birefnet`) | MIT | MIT | 是 | subject saliency | - |
| [CLIP-MLP aesthetic head (LAION)](https://github.com/christophschuhmann/improved-aesthetic-predictor) (`clip_mlp_head`) | Apache-2.0 | No licence stated; trained on AVA | 不明确 | aesthetic (legacy, 8gb) | `qrealign_native` |
| [SAMP-Net (CADB)](https://github.com/bcmi/Image-Composition-Assessment-Dataset-CADB) (`samp_net`) | MIT | No licence stated; Facet re-hosts | 不明确 | composition (14 patterns) | - |
| [U2-Net-P](https://github.com/xuebinqin/U-2-Net) (`u2netp`) | Apache-2.0 | No licence stated; Facet re-hosts | 不明确 | SAMP-Net saliency input | - |
| [DeQA-Score](https://github.com/zhiyuanyou/DeQA-Score) (`deqa`) | MIT | MIT (Llama-2 base; treat as unclear) | 不明确 | extended IQA (off by default) | - |
| [aesthetic-predictor-v2-5](https://github.com/discus0434/aesthetic-predictor-v2-5) (`aesthetic_v25`) | AGPL-3.0 | - | 否 | extended IQA (deprecated, off by default) | `qrealign_native` |
<!-- END GENERATED -->

## 免责声明

- 权重的许可证不等同于训练数据的许可证。训练数据集（AVA、KonIQ、VGGFace2、MS1MV2、300-W）的许可证尚未核实。
- 本页仅供参考，不构成法律意见，也不提供任何担保。进行任何商业部署之前，请自行核实各项许可证。
- Immich 获得的 InsightFace 个人使用许可不适用于 Immich 的用户，也不适用于 Facet 的用户。
