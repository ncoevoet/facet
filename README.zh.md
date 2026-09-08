# Facet

> 🌐 [English](README.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md) · [Español](README.es.md) · [Português](README.pt.md) · **简体中文**

Facet 是一款本地的照片分析与选片引擎。它从美观度到人脸清晰度，在 9 个维度上为每张照片评分，然后让你通过网页照片库浏览、选片和整理。一切都在你自己的机器上运行，无需云服务、账号或 API 密钥。

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-21-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/screenshots/walkthrough.gif" alt="Facet 实际运行——照片库、单张照片评分、选片、照片胶囊、时间线、地图与统计" width="100%">
</p>

## 工作原理

1. **扫描**——把 Facet 指向一个照片文件夹。每张照片都会针对画质、构图和人脸进行分析。支持 JPG、HEIF/HEIC 以及 10 种 RAW 格式（CR2、CR3、NEF、ARW、RAF、RW2、DNG、ORF、SRW、PEF）。
2. **浏览**——打开网页照片库，用筛选、搜索和多种视图模式探索你的照片库。
3. **选片**——Facet 会检测连拍、标记闭眼照片、把相似照片分组，并把精选照片推到前面。包围曝光和全景／HDR 组会被识别出来并整组保留，而不会在选片时被拆散。

GPU 会被自动检测，并非必需。Facet 既能纯 CPU 运行，也能使用最高 24 GB 显存。

## 功能特性

### 评分

每张照片都会在 9 个维度上评分：美观度、构图、人脸画质、眼睛清晰度、技术清晰度、色彩、曝光、主体显著性和动态范围。照片会按内容分类（人像、风光、微距、街拍等，共 30 多个类别），并用各类别专属的权重来评分。**精选照片**筛选器会按综合得分为整个照片库排序。

把鼠标悬停在任意照片上，即可看到带评分明细和 EXIF 数据的提示框。

<img src="docs/screenshots/hover-tooltip.jpg" alt="带评分明细的悬停提示框" width="100%">

### 选片

- **连拍检测**——把快速连拍的照片分为一组，并根据清晰度、画质和闭眼检测自动选出最好的一张
- **组照保护**——包围曝光、全景扫拍和 HDR 全景（`--detect-sequences` / `--detect-panoramas`）会被识别为有意拍摄的多张组照并整组保留：选片暗房会把一组中的每一张都预设为保留，绝不会把它压缩成唯一的“赢家”
- **相似照片组**——在整个照片库中找出视觉上相似的照片，无论拍摄时间相隔多久
- **场景**——按拍摄时间的间隔把一次拍摄分成按先后顺序排列的“场景”，让你按叙事顺序选片；轻点标记，确认后淘汰
- **自动选片**——一键对整个范围选片（全部分组，或只针对连拍／相似／场景，还可进一步限定到某个相册或日期区间），并提供试运行预览、保留数量预算和可选的“精选”相册
- **题材预设**——体育／婚礼／演唱会／野生动物预设，一次选择即可同时设定严格程度、保留数量预算、相似度阈值和人脸门槛
- **修图效果预览** `[Edition]`——在选片暗房中用指定的 darktable 风格渲染照片，让你基于冲洗后的效果而不是平淡的 RAW 预览来选片
- **主体特写**——没有人脸的分组（野生动物、微距、产品）会以自动裁切出的主体条带来对比，并显示组内归一化的清晰度徽章
- **废片清理**——零样本检测非照片类杂图（截图、文档、收据、表情包、幻灯片），并配有快速审阅队列：逐张保留或淘汰，也可一次性全部淘汰
- **逐张人脸的选片徽章**——选片灯箱会为每张人脸显示睁眼／闭眼、表情和检测置信度徽章，而不只是一个照片级的闭眼标记；可选的 MediaPipe blendshapes 能让眼睛／笑容的判断更准确
- **闭眼检测**——标记出闭眼的照片，一键隐藏或淘汰
- **重复照片检测**——通过感知哈希识别几乎相同的照片

<table><tr>
<td><img src="docs/screenshots/burst-culling.jpg" alt="连拍选片" width="100%"></td>
<td><img src="docs/screenshots/similar-photos.jpg" alt="用于选片的相似照片组" width="100%"></td>
</tr></table>

### 浏览

- **照片库视图模式**——拼贴（保留原始比例的对齐行）和网格（带元数据浮层的统一卡片）
- **筛选**——日期区间、内容标签、构图模式、相机、镜头、人物、文件夹、画质等级、星级评分，以及自定义的指标区间
- **语义搜索**——输入“海滩上的日落”这样的自然语言查询，通过向量嵌入和文本搜索找到匹配的照片
- **时间线**——按时间顺序浏览，支持年／月导航和无限滚动
- **地图**——在交互式地图上显示带地理位置的照片，并对标记做聚合分组
- **照片胶囊**——主题幻灯片：带地名的旅程、佳作合集、四季配色、某个人物的照片等等
- **文件夹**——按目录结构浏览，带面包屑导航和封面照片
- **拍摄时刻**——零样本的场景／活动标签（海滩、庆祝、演唱会……）为你的场景命名，可用来筛选和排序照片库，也会参与照片胶囊的选片
- **回忆**——“那年今日”：往年同一天拍摄的照片
- **幻灯片播放**——全屏模式，带主题化转场、照片胶囊之间自动接续和键盘控制

<table><tr>
<td><img src="docs/screenshots/filter-panel.jpg" alt="筛选侧边栏" width="100%"></td>
<td><img src="docs/screenshots/semantic-search.jpg" alt="语义搜索结果" width="100%"></td>
</tr></table>

<details><summary>完整的筛选侧边栏——展开全部分区（点击查看）</summary>
<p align="center"><img src="docs/screenshots/filter-sidebar-full.jpg" alt="展开全部选项的筛选侧边栏" width="380"></p>
</details>

**工作流小贴士：**
- **`/timeline`** 视图会逐级下钻：年 → 月 → 日历——点击某一天即可打开筛选到该日期的照片库。这里没有排序；如果想从一次旅行中挑出最好的照片，请改用下面的 **`/capsules`**，它会在你指定的日期区间上做一次多样性筛选，结果可保存为相册。
- **`/capsules`** 视图会生成主题幻灯片（旅程、“某人的面孔”、四季、佳作），你可以把它们保存为相册。
- 照片库默认隐藏闭眼照片、非代表帧的连拍照片和重复照片。当出现 **“当前筛选条件隐藏了 N 张照片”** 横幅时，点击“显示全部”即可展开视图。

### 整理

- **人脸识别**——自动检测人脸、归组为人物，并检测闭眼。你可以在管理界面中搜索、重命名、合并和整理人物分组。**人物合并建议**会找出可能属于同一个人的相似分组。
- **相册**——支持拖放的手动合集，或根据已保存的筛选条件自动收集照片的智能相册
- **星级与收藏**——星级评分（1–5）、收藏和淘汰标记。单击即可循环切换星级。
- **标签**——由 AI 生成的内容标签，词表可配置。点击任意标签即可筛选照片库。
- **批量操作**——用 Shift+点击、Ctrl+点击或 Ctrl+A（全选）进行多选。批量设置星级、切换收藏、标记淘汰或加入相册——每次批量操作都有 7 秒的撤销时间。
- **键盘优先**——方向键在照片库中导航，Enter 打开，空格选择；在任意界面按 `?` 查看键盘快捷键。

<img src="docs/screenshots/albums.jpg" alt="相册——手动合集与智能相册" width="100%">

<table><tr>
<td><img src="docs/screenshots/persons-manage.jpg" alt="人物管理页面" width="100%"></td>
<td><img src="docs/screenshots/person-gallery.jpg" alt="某个人物的照片库" width="100%"></td>
</tr></table>

### 洞察

- **统计**——器材使用、类别分布、拍摄时间线和指标相关性的仪表盘
- **AI 点评**——展示每个指标贡献度的评分明细；由 VLM 生成的自然语言评价 `[GPU]` `[16gb/24gb]`
- **权重调节**——按类别调节权重的编辑器，带实时评分预览。A/B 照片比较会从你的选择中学习，并给出优化后的权重建议。
- **拍摄场景评分方案**——控制一张照片*按哪个类别*来评分，这与只在类别确定之后才起作用的权重滑块相互独立：你可以重排全局的类别优先级、为某个相册应用一个命名方案（动作／舞台、人像拍摄、野生动物……），或为单张照片设置一个能在每次重算后依然保留的类别覆盖。
- **“我的偏好”排序**——按个人排序模型学到的评分为照片库排序，并显示一个标明学习覆盖率和留出集准确率的置信度徽章
- **从标注中学习**——选片决策、星级评分、收藏和淘汰都会反馈给权重优化器（`--sync-label-comparisons`、`--mine-insights`）
- **配置快照**——保存、恢复和比较权重配置
- **直方图**——带溢出指示的 RGB／亮度直方图，出现在照片提示框和详情视图中
- **AI 照片描述** `[GPU]` `[16gb/24gb]`——文字描述，可编辑 `[Edition]`，并可翻译成 5 种语言（生成和查看无需授权）

<table><tr>
<td><img src="docs/screenshots/stats-gear.jpg" alt="器材统计" width="100%"></td>
<td><img src="docs/screenshots/stats-categories.jpg" alt="类别分析" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/stats-timeline.jpg" alt="拍摄时间线" width="100%"></td>
<td><img src="docs/screenshots/stats-correlations.jpg" alt="指标相关性" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/critique.jpg" alt="AI 点评对话框" width="100%"></td>
<td><img src="docs/screenshots/snapshots.jpg" alt="配置快照" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/weights-sliders.jpg" alt="按类别调节的权重滑块" width="100%"></td>
<td><img src="docs/screenshots/weights-compare.jpg" alt="A/B 照片比较" width="100%"></td>
</tr></table>

### 分享

- **相册分享**——为任意相册生成可分享的链接，接收方无需登录。你可以随时撤销分享。
- **客户选片**——分享出去的相册可以运行在客户选片模式：客户只凭链接（还可选配一个 PIN 码）就能选中喜欢的照片并留言，与你自己的评分完全隔离
- **手机自动上传**——把 PhotoSync 或任意 WebDAV 应用指向内置的 `/dav` 收件箱；`--watch` 会在新照片到达时立即为其评分
- **数码相框与展示屏**——一个受令牌保护的接口，把你精选的最佳照片推送给智能相框和 Home Assistant 仪表盘
- **作品集导出** `[Edition]`——把一个相册渲染成自包含的静态 HTML 照片库（不引用任何 CDN，可离线使用），你可以把它放到任意网站空间上
- **社交平台裁切** `[Edition]`——以检测到的主体为中心构图的全分辨率导出，支持方形、竖版和快拍等比例预设
- **照片下载**——从照片库中下载单张照片或所选照片
- **导出**——把全部评分导出为 CSV 或 JSON，供外部分析使用

### 更多

- **深色与浅色模式**，提供 10 种强调色主题；并会遵循系统偏好
- **响应式**——从手机到桌面自适应，小屏幕上提供便于触控的批量操作面板
- **可安装的 PWA**——Web 应用清单 + Service Worker：可添加到主屏幕、离线应用外壳、缓存缩略图
- **虚拟化照片库**——无论照片库多大都只渲染少量 DOM 节点，因此在 10 万张以上照片时滚动依然流畅
- **可恢复的扫描**——中断的扫描可以继续（`--resume`），失败的文件会被记录并可重试（`--retry-failed`），进度会实时推送到网页界面
- **7 种界面语言**——查看器提供英语、法语、德语、西班牙语、意大利语、巴西葡萄牙语和简体中文；这七种语言的文档也都齐备
- **多用户**——按用户区分的目录、评分和基于角色的访问控制
- **插件与 webhook**——在评分事件上触发的自定义动作
- **从网页界面扫描**——直接在浏览器中触发扫描（需要 superadmin 角色）

<table><tr>
<td width="33%"><img src="docs/screenshots/mobile-gallery.jpg" alt="手机上的照片库" width="100%"></td>
<td width="33%"><img src="docs/screenshots/tablet-gallery.jpg" alt="平板上的照片库" width="100%"></td>
<td width="33%"><img src="docs/screenshots/gallery-mosaic.jpg" alt="桌面端拼贴视图" width="100%"></td>
</tr></table>

## 你需要什么

Facet 的绝大部分功能在**任何机器（CPU）**上都能运行——评分、人脸检测、选片、照片库、搜索、相册和元数据导出都不需要 GPU。在 **Apple Silicon** 上，Facet 会自动为 Torch 模型启用 PyTorch 的 Metal（`mps`）后端，`auto` 配置档则按统一内存总量来选定——32 GB 的 Mac 能用上 `16gb` 配置档，48 GB 的能用上 `24gb` 配置档；InsightFace 仍然使用 ONNX Runtime 的 CPU provider。**NVIDIA GPU**（配合 `16gb` 或 `24gb` 配置档）可以解锁最强的模型：TOPIQ 美观度评分、SigLIP 2 向量嵌入、VLM 打标签、AI 照片描述与点评，以及主体显著性。没有本地 GPU？把 VLM 打标签／照片描述／点评通过 `scoring_config.json` 中的 `vlm_backend` 指向远程的 **Ollama** 或 **兼容 OpenAI** 的服务器——这样这些功能在 CPU 的 `legacy`/`8gb` 配置档上也能使用。在查看器中，编辑类操作（星级、人脸、选片）需要**编辑密码**，触发扫描则需要 **superadmin** 角色。

→ 按功能列出的完整要求（GPU、显存配置档、可选依赖包、鉴权）：**[安装 › 各功能的要求](docs/zh/INSTALLATION.md#各功能的要求)**。

## Facet 适合你吗？

Facet 会为本地照片库评分、排序和选片，并提供一个照片库网页界面供你浏览。它运行在你自己的硬件上，让照片不必上传到云端。

**如果你符合以下情况，它会很合适：**

- 拥有庞大的本地照片库，想找出自己最好的照片，并清理连拍和近似重复的照片；
- 希望画质、构图和人脸评分能按自己的口味调节（它会从你的 A/B 比较中学习）；
- 偏好自托管和隐私——不上传云端、无需账号、无需订阅；
- 已经在用 Lightroom、darktable、digiKam 或 immich 修图——Facet 会把星级、色标、关键词、照片描述和带人名的人脸区域写入 `.xmp` 附属文件（默认不改动原片），也可以选择为 JPEG/HEIC/TIFF/PNG/DNG 把它们直接嵌入文件（照片库中的“将元数据写入文件”操作，或 `--export-sidecars --embed-originals`），并可用 `--import-sidecars` 把外部的修改读回来。

**如果你想要下面这些，它多半不适合你：**

- 一个开箱即用、面向移动端、以云端为后盾的 Google 相册替代品——不过通过 WebDAV 把手机照片自动上传到受监视的收件箱是内置功能（文档中有 PhotoSync 配置示例）；
- RAW 编辑或冲洗——Facet 只做评分和整理，不做修图；
- 零配置的桌面应用——它需要 Python，而最好的模型需要 GPU。

**它与其他工具的关系**

- 自托管照片库（Immich、PhotoPrism）专注于整理、搜索和备份。Facet 补上了它们没有的画质评分、排序和选片流程，但它没有移动应用，也没有云备份（通过 WebDAV 的手机自动上传是内置的，星级也可以同步到 Immich）。
- AI 选片应用（Aftershoot、Narrative、FilterPixel）是打磨精良的商业选片工具，通常还内置修图功能。Facet 免费、本地、覆盖面更广（照片库、搜索、人脸），评分也可调节——但它是单人开发的项目，没有它们那样的支持服务，也不做 RAW 编辑。
- 编辑器和图库管理软件（Lightroom、darktable、digiKam）负责冲洗和管理照片。Facet 通过上面提到的 XMP 元数据互操作与它们配合，而不是取代它们。

美观度评分基于模型，只是近似值；请预留出调节权重的时间，让它贴合你自己的口味。

## 快速开始

### Docker（推荐）

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env      # 打开 .env，把 PHOTOS_DIR 设为你的照片文件夹
docker compose up -d      # 然后打开 http://localhost:5000
```

有 NVIDIA 显卡？请使用
[安装](docs/zh/INSTALLATION.md#使用-docker-安装)中与显存大小对应的配置块——8 GB、16 GB
和 24 GB 显卡各有一行。

### 不使用 Docker（Linux、macOS）

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh                        # 检测硬件并安装所有依赖
source venv/bin/activate
python facet.py /path/to/your/photos   # 为照片评分
python viewer.py                       # 照片库 → http://localhost:5000
```

> **macOS：**控制中心的“隔空播放接收器”默认占用 5000 端口。如果看到 “Address already in use”，请运行 `python viewer.py --port 5001`。

完整指南：**[安装](docs/zh/INSTALLATION.md)**——按硬件区分的配置说明、首次运行时的
下载内容，以及[依赖冲突排查](docs/zh/INSTALLATION.md#排查依赖冲突)。
运行 `python facet.py --doctor` 可以诊断 GPU 问题。

## 文档

| 文档 | 说明 |
|----------|-------------|
| [安装](docs/zh/INSTALLATION.md) | 系统需求、GPU 配置、显存配置档、依赖 |
| [命令](docs/zh/COMMANDS.md) | 全部 CLI 命令参考 |
| [配置](docs/zh/CONFIGURATION.md) | `scoring_config.json` 完整参考 |
| [评分](docs/zh/SCORING.md) | 类别、权重、调节指南 |
| [人脸识别](docs/zh/FACE_RECOGNITION.md) | 人脸处理流程、聚类、人物管理 |
| [查看器](docs/zh/VIEWER.md) | 网页照片库的功能与用法 |
| [互操作](docs/zh/INTEROP.md) | 与 Lightroom、Capture One、digiKam、darktable 往返同步星级／标签 |
| [Immich](docs/zh/IMMICH.md) | 与 Immich 同步星级和收藏，以及入站 webhook |
| [部署](docs/zh/DEPLOYMENT.md) | 生产环境部署（Synology NAS、Linux、Docker） |
| [贡献指南](CONTRIBUTING.md) | 开发环境搭建、架构、代码风格 |

## 许可证

[MIT](LICENSE)
