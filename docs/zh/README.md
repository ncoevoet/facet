# Facet 文档

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · [Español](../es/README.md) · [Português](../pt/README.md) · **简体中文**

Facet 是一个多维度的照片分析引擎：它为本地照片库评分、排名和选片，
然后提供一个照片库界面供你浏览。请从[安装](INSTALLATION.md)开始——
它用可复制粘贴的代码块覆盖了每一种安装方式。

| 文档 | 说明 |
|----------|-------------|
| [安装](INSTALLATION.md) | 按硬件划分的安装步骤，使用或不使用 Docker；依赖项 |
| [命令](COMMANDS.md) | 全部 CLI 命令参考 |
| [配置](CONFIGURATION.md) | 完整的 `scoring_config.json` 参考 |
| [评分](SCORING.md) | 类别、权重与调优指南 |
| [人脸识别](FACE_RECOGNITION.md) | 人脸处理流程、聚类、人物管理 |
| [查看器](VIEWER.md) | 网页照片库的功能与用法 |
| [互操作](INTEROP.md) | 与 Lightroom、Capture One、digiKam、darktable 双向交换星级／标签 |
| [Immich](IMMICH.md) | 与 Immich 同步星级和收藏，以及入站 webhook |
| [部署](DEPLOYMENT.md) | NAS、远程服务器、HTTPS、备份、多用户 |

## 支持的文件类型

- **JPEG**（.jpg、.jpeg）
- **HEIF/HEIC**（.heic、.heif）——需要 `pillow-heif`
- **RAW**（.cr2、.cr3、.nef、.arw、.raf、.rw2、.dng、.orf、.srw、.pef）——当存在同名的 JPEG/HEIC 时会跳过

## 常见问题

| 问题 | 解答 |
|-------|--------|
| 我该使用哪种配置档？ | [安装 › 哪种配置档适合我的硬件？](INSTALLATION.md#哪种配置档适合我的硬件) |
| 安装时出现“externally-managed-environment” | 使用虚拟环境（或 Docker）——参见[安装](INSTALLATION.md) |
| 处理速度慢 | 检查配置档；`--single-pass` 在大显存 GPU 上有帮助 |
| 人脸检测未使用 GPU | 安装 `onnxruntime-gpu`——参见[安装](INSTALLATION.md#用于人脸检测的-onnx-runtime) |
| 缺少 exiftool | 可选——参见[安装 › exiftool](INSTALLATION.md#exiftool) |
