# Facet 文档

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · [Español](../es/README.md) · [Português](../pt/README.md) · **简体中文**

Facet 是一个多维度的照片分析引擎：它为本地照片库评分、排名和选片，
然后提供一个照片库界面供你浏览。请从[安装](INSTALLATION.md)开始——
它用可复制粘贴的代码块覆盖了每一种安装方式。

| 文档 | 说明 |
|----------|-------------|
| [安装](INSTALLATION.md) | 按硬件划分的安装步骤，使用或不使用 Docker；依赖项 |
| [快速上手](GETTING_STARTED.md) | 首次运行指南：从安装到扫描、审阅、训练、淘汰、打标签和导出 |
| [命令](COMMANDS.md) | 全部 CLI 命令参考 |
| [配置](CONFIGURATION.md) | 完整的 `scoring_config.json` 参考 |
| [评分](SCORING.md) | 类别、权重与调优指南 |
| [人脸识别](FACE_RECOGNITION.md) | 人脸处理流程、聚类、人物管理 |
| [查看器](VIEWER.md) | 网页照片库的功能与用法 |
| [API](../API.md) | 查看器 HTTP API 参考 |
| [互操作](INTEROP.md) | 与 Lightroom、Capture One、digiKam、darktable 双向交换星级／标签 |
| [Immich](IMMICH.md) | 与 Immich 同步星级和收藏，以及入站 webhook |
| [部署](DEPLOYMENT.md) | NAS、远程服务器、HTTPS、备份、多用户 |
| [重新关联](RELINK.md) | 重新关联已移动照片 |

## 支持的文件类型

- **JPEG**（.jpg、.jpeg）
- **HEIF/HEIC/HIF**（.heic、.heif、.hif）——需要 `pillow-heif`；佳能 HDR PQ `.HIF` 照片会被 tone map 到 SDR sRGB
- **RAW**（.cr2、.cr3、.nef、.arw、.raf、.rw2、.dng、.orf、.srw、.pef）——当存在同名的 JPEG/HEIC 时会跳过。LibRaw 无法解码的 RAW（Lightroom 的 `-HDR.dng` / `-Pano.dng` 合并文件，或比 LibRaw 更新的相机）会通过 `exiftool` 使用其最大的内嵌预览评分；预览的长边必须至少为 1024 px。Lightroom Classic 13+ 以 JPEG XL 存储该预览，Facet 可直接解码
- **PNG、GIF、WebP、BMP、TIFF**（.png、.gif、.webp、.bmp、.tif、.tiff）——16 位灰度会缩放为 8 位，alpha 通道会合成到白色背景上，动图 GIF/WebP 只对第一帧评分；TIFF 会被转换成 JPEG 提供给浏览器。PNG、WebP 与 TIFF 在写入方保存了 EXIF 时会携带它；GIF 与 BMP 无法携带，因此这两种格式的 `date_taken` 与相机/镜头信息为空
- **AVIF**（.avif）——需要编译了 AVIF 支持的 Pillow（`pillow>=11.3` 起原生支持）；HDR PQ 照片会被 tone map 到 SDR sRGB；存在 EXIF 时会读取
- **JPEG XL**（.jxl）——通过核心依赖 `imagecodecs` 开箱即用，Docker 同样适用。不进行 HDR 色调映射，动画文件只对第一帧评分，存在有效 EXIF 时会读取。重建的 JPEG 保留 ICC 色彩管理；原生 JXL 色彩配置不可用

## 常见问题

| 问题 | 解答 |
|-------|--------|
| 我该使用哪种配置档？ | [安装 › 哪种配置档适合我的硬件？](INSTALLATION.md#哪种配置档适合我的硬件) |
| 安装时出现“externally-managed-environment” | 使用虚拟环境（或 Docker）——参见[安装](INSTALLATION.md) |
| 处理速度慢 | 检查配置档。`--single-pass` 在显存充足的 `legacy`/`8gb` 配置档上可能有帮助；`12gb`/`16gb`/`24gb` 始终以多阶段运行（商业模式除外） |
| 人脸检测未使用 GPU | 运行 `python facet.py --doctor`（ONNX Runtime 一节），然后安装 `onnxruntime-gpu` 来替换 `onnxruntime`，不要并存——参见[安装](INSTALLATION.md#用于人脸检测的-onnx-runtime) |
| 缺少 exiftool | 可选——参见[安装 › exiftool](INSTALLATION.md#exiftool) |
