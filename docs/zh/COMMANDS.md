# 命令参考

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md) · **简体中文**

[扫描](#扫描) · [预览与导出](#预览与导出) · [重新计算操作](#重新计算操作) · [人脸识别](#人脸识别) · [缩略图管理](#缩略图管理) · [诊断](#诊断) · [模型信息](#模型信息) · [权重优化](#权重优化成对比较) · [配置](#配置) · [标签标注](#标签标注) · [数据库校验](#数据库校验) · [数据库维护](#数据库维护) · [网页图库](#网页图库) · [常用工作流](#常用工作流)

> 下文使用的需求标签：`[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]`（VRAM 档位）。参见[功能需求对照表](INSTALLATION.md#各功能的要求)。

## 扫描

| 命令 | 说明 |
|---------|-------------|
| `python facet.py /path` | 扫描目录（多阶段模式，自动检测 VRAM） |
| `python facet.py /path --force` | 重新扫描已处理过的文件 |
| `python facet.py /path --single-pass` | 强制单阶段模式（一次性加载全部模型） |
| `python facet.py /path --pass quality` | 仅运行 TOPIQ 画质评分阶段 |
| `python facet.py /path --pass quality-iaa` | 仅运行 TOPIQ IAA 美学价值评分 |
| `python facet.py /path --pass quality-face` | 仅运行 TOPIQ NR-Face 人脸画质评分 |
| `python facet.py /path --pass quality-liqe` | 仅运行 LIQE 画质评分与失真诊断 |
| `python facet.py /path --pass tags` | 仅运行标签标注阶段（模型取决于 VRAM 档位） |
| `python facet.py /path --pass composition` | 仅运行 SAMP-Net 构图模式检测 |
| `python facet.py /path --pass faces` | 仅运行 InsightFace 人脸检测 |
| `python facet.py /path --pass embeddings` | 仅运行 CLIP/SigLIP 特征向量提取 |
| `python facet.py /path --pass saliency` | 仅运行 BiRefNet 主体显著性检测 |
| `python facet.py /path --db custom.db` | 使用自定义数据库文件 |
| `python facet.py /path --config my.json` | 使用自定义评分配置 |
| `python facet.py --resume` | 续跑上一次中断或失败的扫描——包括被 SIGKILL、内存耗尽或断电硬性终止的扫描（状态仍为 `running`、且心跳早于 `processing.scan_stale_seconds`（默认 120）的运行）。沿用该次运行的目录；配合 `--force` 时，会跳过自该次运行开始后已重新评分的文件。若另一次扫描看起来确实还在运行，则拒绝执行。 |
| `python facet.py --retry-failed` | 仅重新处理上一次扫描运行中失败的文件（`--retry-failed all` 处理所有运行的失败文件） |
| `python facet.py /path --force-since 2026-01-01` | 与 `--force` 类似，但只重新处理最后一次扫描时间早于该日期的照片 |
| `python facet.py /path --watch` | 保持运行，一旦出现新照片就重新扫描（需要 `pip install watchdog`；`--watch-debounce N` 可调整静默期，默认 30 秒） |
| `python facet.py /path --force-low-space` | 跳过扫描前的可用空间检查（即使卷的剩余空间看起来不足以写入本次扫描产生的缩略图和特征向量，也继续执行） |

### 扫描记录

每次扫描都会在 `scan_runs` 中记录一行（状态、模式、目录、计数器），
并把逐文件的错误记入 `scan_failures`（路径、阶段、错误）。用 Ctrl+C 中断
扫描会把该次运行标记为 `interrupted`，以便 `--resume` 接续；失败的文件
是可见、可重试的，而不是在每次增量扫描时被静默重试。命令行还会输出结构化的
`@FACET_PROGRESS` JSON 行（阶段、当前数/总数、预计剩余时间），网页图库的扫描
API 会将其呈现在 `/api/scan/status` 的 `progress` 字段以及 SSE 数据流中。

### 处理模式

**多阶段（默认）：** 检测 VRAM 并按顺序加载模型。每个阶段加载自己的模型、处理全部照片，然后卸载以释放 VRAM，因此即使 VRAM 有限也能运行高质量模型。

**单阶段（`--single-pass`）：** 一次性加载全部模型。速度更快，但需要更多 VRAM。

**指定阶段（`--pass NAME`）：** 只运行一个阶段，用于更新特定指标而无需完整重新处理。可用阶段：

| 阶段 | 模型 | 输出 | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic` 评分（0-10） | 约 2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` 评分（艺术价值而非技术质量，基于 AVA 训练） | 与 TOPIQ 共用 |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` 评分（专为人脸画质设计） | 与 TOPIQ 共用 |
| `quality-liqe` | LIQE | `liqe_score` 加失真诊断（模糊、过曝、噪点） | 约 2 GB |
| `tags` | CLIP / Qwen VLM | 来自所配置词表的语义标签 | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern`（8 种模式）＋ `comp_score` | 约 2 GB |
| `faces` | InsightFace buffalo_l | 人脸检测、关键点、闭眼检测、识别特征向量 | 约 2 GB |
| `embeddings` | CLIP ViT-L-14 或 SigLIP 2 NaFlex | 用于相似度／标签标注的 `clip_embedding` BLOB | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`、`subject_prominence`、`subject_placement`、`bg_separation` | 约 2 GB |

## 预览与导出

| 命令 | 说明 |
|---------|-------------|
| `python facet.py /path --dry-run` | 对 10 张样本照片评分但不保存 |
| `python facet.py /path --dry-run --dry-run-count 20` | 对 20 张样本照片评分 |
| `python facet.py --export-csv` | 把全部评分导出为带时间戳的 CSV |
| `python facet.py --export-csv output.csv` | 导出到指定的 CSV 文件 |
| `python facet.py --export-json` | 把全部评分导出为带时间戳的 JSON |
| `python facet.py --export-json output.json` | 导出到指定的 JSON 文件 |
| `python facet.py --export-manifest` | 导出紧凑的 JSON 清单（路径、类别、评分、标签、星级评分、收藏／淘汰、连拍代表帧）到 `facet_manifest.json`，供 Lightroom Classic 插件等外部工具使用 |
| `python facet.py --export-manifest /path` | 把清单限定为某个路径子树下的照片 |
| `python facet.py --export-manifest --user alice` | 多用户模式：把 Alice 的 `user_preferences` 评分导出到清单，而不是全局列（标签和评分仍为全局） |
| `python facet.py --import-sidecars` | 把 `<image>.xmp` 附属文件中的评分／标记／标签导回数据库（全部照片） |
| `python facet.py --import-sidecars /path` | 仅导入某个路径子树下照片的附属文件 |
| `python facet.py --import-sidecars --user alice` | 多用户模式：把评分导入 Alice 的 `user_preferences`，而不是全局列（关键词仍为全局） |
| `python facet.py --export-sidecars` | 为全部照片从数据库写入／合并 `<image>.xmp` 附属文件（仅附属文件） |
| `python facet.py --export-sidecars /path` | 仅导出某个路径子树下照片的附属文件 |
| `python facet.py --export-sidecars --user alice` | 多用户模式：导出 Alice 的 `user_preferences` 评分，而不是全局列（关键词仍为全局） |
| `python facet.py --export-sidecars --embed-originals` | 同时把元数据**写入文件本身**，适用于 JPEG/HEIC/TIFF/PNG/DNG（会重写原始文件） |
| `python facet.py --export-sidecars --score-to-stars` | 对你没有手动评分过的照片，由综合评分推导出 `xmp:Rating`（手动评分／收藏／淘汰始终优先） |

> **元数据双向同步。** Facet 会把评分、颜色标记、关键词、照片描述和已命名的人脸区域写入标准的 `<image>.xmp` 附属文件，整个生态都能读取（Lightroom、darktable、digiKam、immich 等）；除非你用 `--export-sidecars --embed-originals` 主动开启，否则原始图像永远不会被修改（仅限 JPEG/HEIC/TIFF/PNG/DNG——RAW 绝不会被改动）。写入文件本身以及安全的关键词并集合并需要 **exiftool**；没有它时，Facet 会退回到零依赖的纯 XML 附属文件。
>
> **注意事项。** `--import-sidecars` 依据照片的 `scanned_at`（最后一次扫描时间）以*较新者优先*的方式处理评分／标记，而不是依据每条评分的编辑时间——因此比最后一次扫描更新的附属文件，可能覆盖你在扫描之后于 Facet 中改过的评分。如果外部编辑器才是权威来源，请在重新评分之前运行 `--import-sidecars`；如果你使用 `photo_tags` 查找表，则在导入之后运行 `python database.py --migrate-tags`。
>
> **`--export-manifest` 与 `--export-csv`／`--export-json` 的区别。** 清单的可选参数限定的是*导出哪些照片*（与 `--export-sidecars` 一样），而不是输出文件名——它始终在工作目录中（重新）写入 `facet_manifest.json`，因为它的用途就是就地重新生成，供反复读取固定路径的工具使用。它携带的 `star_rating`／`is_favorite`／`is_rejected` 值与 `--export-sidecars` 相同——默认取全局列，给出 `--user` 时则取指定用户的 `user_preferences` 行，于是多用户安装不会再导出一份全是零的清单——另外还有 `is_burst_lead`（始终为全局），并以紧凑（非美化缩进）的 JSON 写出：在约 10 万张照片的规模下，`--export-json` 的 `indent=2` 输出会达到几十兆字节，而机器读取方并不会从中获益。

### Immich 同步

通过 REST API 把你在 Facet 中的评分和收藏推送到 [Immich](https://immich.app/) 服务器（单向——Facet → Immich）。资源按 `originalPath` 解析，使用 `immich` 配置块中的路径前缀映射，在一次批量搜索中完成。

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --immich-test` | 检查与所配置 Immich 服务器的连通性和身份验证（`immich.url` ＋ `immich.api_key`，以 `x-api-key` 发送） |
| `python facet.py --immich-sync` | 把星级评分（1–5）和收藏推送到 Immich，按 `originalPath` 解析资源。遵循 `--dry-run`（只解析、不写入）和 `--user`（多用户模式下的按用户评分） |
| `python facet.py --immich-sync --dry-run` | 解析每一个资源并报告将会发生的变化，但不写入 |

评分遵循 Immich 的版本安全策略（只用 1–5，绝不用 0/−1）；还可选择用一个精选照片相册收集评分高于阈值的照片。仅使用 REST——不与 Immich 数据库直接耦合。完整配置块参见 [配置 — Immich 同步](CONFIGURATION.md#immich-同步)。

## 重新计算操作

这些命令用于更新特定指标、派生新数据（AI 照片描述、GPS、特征向量）或分析数据库——全部无需重新运行完整的评分流水线。多数命令复用已存储的缩略图／关键点，对 CPU 负担很轻，但涉及 AI／提取的条目（例如 `--generate-captions`）以及需要从原图重新计算的条目会大量占用 GPU。

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --recompute-average` | 从已存储的特征向量重新计算综合评分（可再次推导；不做数据库快照——如需回退，请恢复某个权重快照并重新计算） |
| `python facet.py --recompute-category portrait` | 只重新计算单个类别的评分 |
| `python facet.py --tag-untagged` | 只为尚无标签的照片打标签，使用已存储的特征向量（不读取图像文件）。这与扫描结束时所做的工作相同；用它来补齐缺口，而不必重新标注已经有标签的照片 |
| `python facet.py --recompute-tags` | 使用所配置的模型重新标注全部照片 |
| `python facet.py --recompute-tags-vlm` | 使用 VLM 标注器重新标注全部照片 |
| `python facet.py --detect-moments` | 为新照片标注其叙事时刻（基于照片描述语义，零样本＋时间平滑；每次扫描结束时自动运行）。每条新描述只编码一次写入 `caption_embedding`，随后在已存储向量上做余弦计算——对既有照片库做首次完整回填时建议使用 GPU；可加 `--limit N` 先在样本上验证。当设置了 `narrative_moments.vlm_tiebreak.enabled`（16gb/24gb 档位）时，后验概率低／区分度低的照片会由该档位的 VLM 重新分类 |
| `python facet.py --recompute-moments` | 为整个照片库重新标注叙事时刻（对完整时间线重新平滑）。加上 `--dry-run --verbose` 可预览每张照片得分最高的 3 个时刻而不写入。启用时（16gb/24gb）同样遵循 `narrative_moments.vlm_tiebreak` 对低置信度照片的 VLM 重新分类 |
| `python facet.py --discover-moments` | 通过对已存储的照片描述向量做聚类（HDBSCAN），并依据各簇的描述为其命名，提出一份贴合本照片库的时刻词表。结果写入 `scoring_config.discovered.json` 供你审阅——绝不会改写正在使用的配置。请先运行 `--detect-moments` 以填充 `caption_embedding`；用 `--discover-min-cluster-size N` 调整粒度 |
| `python facet.py --detect-junk` | 在新增／尚未评估的照片中，通过对已存储特征向量做零样本 CLIP 判别，标出非摄影类杂图（截屏、文档、票据、表情包、幻灯片）；每次扫描结束时自动运行。判定干净的照片会被标记为 `not_junk`，因此重新运行时不会再次扫描它们；加上 `--dry-run --verbose` 可预览逐张照片的分数而不写入 |
| `python facet.py --recompute-junk` | 为整个照片库重新评估 `junk_kind`（所有已存储特征向量的照片） |
| `python facet.py --recompute-saliency` | `[GPU]` 从已存储的缩略图重新计算主体显著性指标（BiRefNet_dynamic）——照片库所在卷离线时也能运行。会跳过已有 `subject_bbox` 的照片（可续跑）；`--force` 则全部重做。所有档位都启用了显著性（legacy 档位在 CPU 上运行，较慢）；强烈建议使用 GPU |
| `python facet.py --recompute-composition-cpu` | 用基于规则的方法重新计算构图（CPU，任意档位） |
| `python facet.py --recompute-composition-gpu` | `[GPU]` 用 SAMP-Net 重新计算构图 |
| `python facet.py --recompute-iqa` | `[GPU]` 从已存储的缩略图重新计算补充 IQA 指标（TOPIQ IAA、NR-Face、LIQE）。所有档位都已启用（legacy 档位在 CPU 上运行，较慢）；强烈建议使用 GPU |
| `python facet.py --detect-text` | 通过对已存储缩略图做 OCR，把图像中的文字（招牌、海报、文件）提取到 `ocr_text`，使其可在照片库搜索框中被检索到。会跳过已评估过的照片，因此重新运行时只读取新照片。需手动开启：要求 `scoring_config.json` 中的 `ocr.enabled` 并 `pip install easyocr`——参见 [配置 — OCR](CONFIGURATION.md#ocr) |
| `python facet.py --recompute-text` | 对整个照片库重新运行 OCR，包括 `--detect-text` 已经评估过的照片 |
| `python facet.py --recompute-colors` | 从缩略图提取主色调与冷暖色温（CPU，快速），写入 `dominant_hue` ／ `color_temp` |
| `python facet.py --recompute-form` | 从已存储的缩略图重新计算五项可解释的形式／色彩指标——左右对称性、视觉平衡、边缘方向熵、盒计数分形复杂度，以及 Matsuda 色相模板色彩和谐度（CPU，无需模型）。它们会出现在点评分析、改进建议和照片提示框中，也可作为类别权重使用（出厂值为 0） |
| `python facet.py --recompute-skin-tone` | 从已存储的人脸缩略图和关键点重新计算人像肤色自然度（脸颊 CIELAB 色度与 CCT 肤色轨迹的 CIEDE2000 色差；CPU，无需模型）。仅供参考——只呈现为一条点评说明，不参与综合评分 |
| `python facet.py --recompute-distortions` | 通过在已存储的 CLIP/SigLIP 特征向量上使用 ExIQA 风格的零样本对比式提示，为每张照片标注可能的失真属性（运动模糊、偏色、过度锐化等），随后打印与 `liqe_score` ／ `noise_sigma` 的 Spearman 相关性报告。仅供参考（点评中的警示标签），不参与综合评分 |
| `python facet.py --upgrade-db` | 迁移表结构并运行完整的回填链：提取 GPS、检测重复、重算 IQA、显著性、CPU 构图、连拍、闭眼、眼睛与表情、人脸信号、平均分。幂等；会跳过生成照片描述之类的重负载步骤。 |
| `python facet.py --recompute-blinks` | 从已存储的关键点重新计算闭眼检测（CPU，快速） |
| `python facet.py --recompute-eyes-expression` | 从已存储的关键点重新计算睁眼与表情评分（CPU，快速） |
| `python facet.py --recompute-face-signals` | 从已存储的 106 点关键点回填每张人脸的睁眼与微笑评分（CPU，快速；无需模型）。也是 `--upgrade-db` 的一个步骤 |
| `python facet.py --recompute-burst` | 重新计算连拍分组 |
| `python facet.py --detect-sequences` | 检测有意拍摄的多帧照片组：先根据已存储的 EXIF 识别包围曝光，再根据缩略图几何关系识别全景照片组，并把每个连拍分组的代表帧移到其基准曝光帧上。每次扫描结束时以及作为 `--upgrade-db` 的一个步骤运行。它是网页图库中**包围曝光**／**全景照片组**／**HDR 全景照片组**选片粒度的前提，也是 `hide_brackets` ／ `hide_panoramas` 有内容可筛选的前提——在照片组被标注之前，两者都不起作用。由于每次运行都会从零开始重新标注整个照片库，重新运行它（或 `--detect-panoramas`）也正是在上一个代表帧被选片剔除后，重新推导照片组代表帧的方式 |
| `python facet.py --detect-panoramas` | 通过在几何上匹配已存储的缩略图来检测全景照片组（整个照片库，CPU，不解码图像）。与 `--detect-sequences` 一样会先运行包围曝光识别：HDR 全景在每个位置都做了包围曝光，因此两者必须保持同步。对全景／HDR 全景选片粒度和 `hide_panoramas` 开关而言，前提条件与 `--detect-sequences` 相同 |
| `python facet.py --detect-duplicates` | 通过 pHash 检测重复照片 |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | 评估近似重复的余弦阈值（有标注时给出精确率／召回率表格，否则给出候选余弦分布） |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` 使用 VLM 为照片生成 AI 照片描述。当 `narrative_moments.caption_min_confidence > 0` 时，会跳过未标注／标为 `other` ／低于阈值的照片（按需生成描述的接口同样适用该门槛） |
| `python facet.py --translate-captions` | 把英文照片描述翻译成所配置的目标语言（CPU，MarianMT） |
| `python facet.py --extract-gps` | 从 EXIF 数据中提取 GPS 坐标写入数据库列 |
| `python facet.py --rescan-gps` | 为全部照片重新从 EXIF 提取 GPS 坐标（覆盖已有值） |
| `python facet.py --recompute-embeddings` | 为全部照片重新计算 CLIP/SigLIP 特征向量（更换模型后必须执行） |
| `python facet.py --score-topiq` | 从已存储的缩略图回填 TOPIQ 画质评分（需要 GPU） |
| `python facet.py --backfill-focal-35mm` | 为缺少等效 35mm 焦距的照片从 EXIF 回填该值 |
| `python facet.py --backfill-clipping` | 从已存储的直方图推导各通道的溢出百分比。仅使用数据库（不解码图像）且可续跑；直方图早于 RGB 格式的照片保持未知（NULL） |
| `python facet.py --compute-recommendations` | 分析数据库并显示评分摘要 |
| `python facet.py --compute-recommendations --verbose` | 显示详细统计信息 |
| `python facet.py --compute-recommendations --apply-recommendations` | 自动应用评分修正 |
| `python facet.py --compute-recommendations --simulate` | 预览预计产生的变化 |

### 补充画质模型

除主要的 TOPIQ 美学评分外，还有三个 PyIQA 模型参与评分。它们与 TOPIQ 共用 VRAM，并作为默认多阶段流水线的一部分运行。

- **TOPIQ IAA**（`--pass quality-iaa`）：基于 AVA 训练的艺术美学价值，与技术质量相互独立。存储为 `aesthetic_iaa`。
- **TOPIQ NR-Face**（`--pass quality-face`）：人脸区域的画质评估。存储为 `face_quality_iqa`。
- **LIQE**（`--pass quality-liqe`）：画质评分外加失真类型诊断（例如运动模糊、过曝、噪点）。存储为 `liqe_score`。

### 基准测试与补充评分

| 命令 | 说明 |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | 把缓存的 CLIP/SigLIP 特征向量投影到由文本派生的美学轴上，从而填充 `aesthetic_clip` 列。不产生额外的图像推理。不属于默认的 `aggregate`。参见 [docs/SCORING.md](SCORING.md#补充信号不计入默认综合评分)。 |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | 针对数据库中每一个已填充的评分列，计算其与 AVA 平均主观评分真值的 SRCC ＋ PLCC。在新增或调优模型变体时很有用。 |

### 主体显著性

`--pass saliency` 与 `--recompute-saliency` 使用 BiRefNet-dynamic（`ZhengPeng7/BiRefNet_dynamic`，通过 `transformers`）生成主体二值掩膜，然后据此推导四项指标：

- **主体清晰度**：主体区域与背景的拉普拉斯方差对比——判断主体是否合焦。
- **主体占比**：主体面积／画面面积——主体占据画面时（例如微距）数值较高。
- **主体位置**：按三分法为主体质心打分。
- **背景分离度**：主体边界与背景之间的边缘梯度差——即背景虚化质量。

需要 `transformers`（约 2 GB VRAM）。

### 标签模型

标签模型按 VRAM 档位选择：

| 档位 | 模型 | 工作方式 |
|---------|-------|-------------|
| `legacy` | CLIP 相似度 | 计算图像特征向量与标签文本特征向量之间的余弦相似度。不额外加载模型。 |
| `8gb` | CLIP 相似度 | 与 legacy 相同，在已存储的 CLIP ViT-L-14 特征向量上进行。 |
| `16gb` | Qwen3.5-2B | 用于语义场景标注的多模态模型。 |
| `24gb` | Qwen3.5-4B | 更大的多模态模型。 |

所有标注器都会把输出映射到所配置的标签词表。用 `--recompute-tags` 以档位默认模型重新标注，或用 `--recompute-tags-vlm` 进行基于 VLM 的重新标注。

### 特征向量模型

有两个特征向量模型可用，通过 `clip_config` 按 VRAM 档位选择：

| 配置 | 模型 | 维度 | 使用者 |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | 16gb、24gb 档位 |
| `clip_legacy` | CLIP ViT-L-14 | 768 | legacy、8gb 档位 |

特征向量支撑着语义标注、重复检测、相似照片搜索，以及 CLIP+MLP 美学评分（legacy/8gb）。更换模型后必须为全部照片重新计算特征向量（`--force`、`--pass embeddings` 或 `--recompute-embeddings`）。

## 人脸识别

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | 为新照片提取人脸（GPU，并行） |
| `python facet.py --extract-faces-gpu-force` | 删除全部人脸并重新提取（GPU） |
| `python facet.py --cluster-faces-incremental` | HDBSCAN 聚类，保留所有人物（CPU） |
| `python facet.py --cluster-faces-incremental-named` | 聚类，仅保留已命名的人物（CPU） |
| `python facet.py --cluster-faces-force` | 完整重新聚类，删除所有人物（CPU） |
| `python facet.py --suggest-person-merges` | 给出可能的人物合并建议 |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | 使用更严格的阈值 |
| `python facet.py --refill-face-thumbnails-incremental` | 生成缺失的缩略图（CPU，并行） |
| `python facet.py --refill-face-thumbnails-force` | 重新生成全部缩略图（CPU，并行） |

## 缩略图管理

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | 依据 EXIF 方向修正已存储缩略图的旋转 |
| `python facet.py --refresh-thumbnails` | 从相机内嵌的预览重建 RAW 缩略图 |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | 同上，但并行读取更多 |

从原始文件读取 EXIF 方向并旋转已存储的缩略图字节；适用于在支持 EXIF 之前处理过的照片。它只读取 EXIF 头和已存储的缩略图，不读取完整图像。

`--refresh-thumbnails` 会让每张 RAW 照片的已存储缩略图通过显示配置重新渲染（优先使用相机预览，去马赛克作为兜底——参见 [CONFIGURATION.md](CONFIGURATION.md#raw-解码)）。它是为在该显示配置出现之前扫描过的照片库准备的迁移手段：旧扫描写入的缩略图带有 LibRaw 的逐帧自动亮度，这会抹平包围曝光各帧之间的曝光差异。不加载任何模型，也不改动任何评分列——只重写 `photos.thumbnail`。

该命令受限于存储吞吐而非 CPU，因此其耗时取决于照片库规模以及照片库所在磁盘或网络挂载的速度，而不是机器的核心数。`--refresh-thumbnails-workers`（默认 8）设定同时读取多少个文件：在读取多半在等待的高速网络挂载上可以调高，在低速本地磁盘上则应调低。它同时限制了没有预览的 RAW 需要回退到完整去马赛克的并发数，因此过高的取值会占用大量内存。

它可以续跑。每个已提交的批次都会记录进度，因此被 Ctrl-C（或断开的挂载）中止的运行会留下一致的数据库，下一次 `--refresh-thumbnails` 会从中断处继续。完整跑完的运行会清除该标记，因此之后再次运行会从头开始。

如果某张照片重新渲染的结果整幅全黑，它会保留原有缩略图并按文件名记入日志。这并非杞人忧天：严重截断的松下 RW2 文件并不会解码失败——LibRaw 会把缺失数据补零并返回一帧有效的全尺寸黑图——因此若没有这道检查，损坏的文件会悄悄用黑图替换掉好的缩略图。这类照片不会被打上版本标记，下一次运行时仍会重试，所以只要修复文件即可解决。

属于包围曝光的照片会在不使用相机预览、也不施加任何曝光增益的情况下重新渲染，因此它的图块显示的就是传感器记录到的内容（参见 [CONFIGURATION.md](CONFIGURATION.md#包围曝光照片按未校正方式渲染)）。由于包围曝光归属来自扫描之后运行的序列检测，请在 `--detect-sequences` 之后再运行本命令，这些图块才会采用该渲染。

### 哪些操作会更新已存储的缩略图

缩略图是在扫描时生成的，因此在显示配置出现之前扫描过的照片库，在图库网格中仍会显示旧的渲染结果。`photos.render_version` 记录了每一行的缩略图由哪条流水线生成，有两条途径可以让它保持最新：

| 途径 | 覆盖范围 | 代价 |
|------|--------|------|
| 重新扫描（`python facet.py <dir>`） | 它扫描到的一切，包括缩略图和直方图 | 一次完整的评分运行 |
| `--refresh-thumbnails` | 每一行 RAW 照片的缩略图 | 受存储速度限制，大型照片库需数小时 |

**什么都不会自动发生。** 详情视图始终是最新的，因为 `/image` 是实时渲染的；但图库网格提供的是 `photos.thumbnail`，再怎么浏览也不会重写它。这正是 `--refresh-thumbnails` 存在的意义，也是图库会显示一条可关闭的横幅、统计还有多少行等待更新的原因。

横幅中的计数来自统计缓存，TTL 为一小时，由 `--refresh-thumbnails` 和 `python database.py --refresh-stats` 直接刷新，因此在重新扫描之后，它最多可能滞后现实一小时。

## 诊断

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --doctor` | 运行诊断检查（Python、GPU、依赖、配置、数据库） |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | 为诊断模拟 GPU 硬件 |

报告 Python 版本、PyTorch/CUDA 构建、GPU 检测与驱动、VRAM 档位建议、可选依赖，以及配置／数据库状态。当 PyTorch 看不到 GPU 而 `nvidia-smi` 能看到时，它会打印用于修复 CUDA 构建的 `pip install` 命令。

`--simulate-gpu NAME` 与 `--simulate-vram GB` 用于测试在不同硬件下的行为。两者都需要配合 `--doctor`；`--simulate-vram` 需要配合 `--simulate-gpu`。

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --check-raw-rendering` | 用旧的和当前的解码设置渲染 20 张抽样 RAW 照片 |
| `python facet.py --check-raw-rendering 50` | 改为抽样 50 张照片 |

只读：它直接从磁盘解码一批随机样本，并打印每种渲染方式得到的平均亮度——LibRaw 的逐帧自动亮度、固定增益的指标去马赛克，以及缩略图和网页图库所使用的相机内嵌预览。可以用它在自己的文件上检验 `raw_decode.bright`，再决定是否执行一次扫描或 `--refresh-thumbnails`；固定增益列和预览列会保留包围曝光的曝光阶梯，而自动亮度列会把它压平。

## 模型信息

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --list-models` | 显示可用模型及其 VRAM 需求 |

## 权重优化（成对比较）

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --comparison-stats` | 显示成对比较的统计信息 |
| `python facet.py --optimize-weights` | 根据比较结果优化并保存权重（所有来源，按可靠性加权）；只有当留出集 k 折准确率优于当前权重时才会应用 |
| `python facet.py --optimize-weights --optimize-force` | 即使未通过准确率门槛也应用优化后的权重 |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | 把训练数据限定为指定的比较来源 |
| `python facet.py --optimize-weights --optimize-category portrait` | 只在一个类别上训练，并写入其 v4 `categories[].weights` 块 |
| `python facet.py --auto-tune-categories` | **仅限超级管理员**（多用户模式下需传入 `--user`）：报告各类别的比较标注是否足以自动调优共享的全局权重。目前为占位实现——只报告就绪程度；自动应用的循环因标注不足而暂缓 |
| `python facet.py --sync-label-comparisons` | 从星级评分／收藏／淘汰重建由评分派生的比较对（source=rating） |
| `python facet.py --train-ranker` | 在 [特征向量 ＋ 评分] 上训练个人排序模型并写入 learned_scores（以留出集 k 折准确率相对综合评分基线是否更优为门槛） |
| `python facet.py --train-ranker --ranker-category portrait` | 只在一个类别上训练排序模型 |
| `python facet.py --train-ranker --train-ranker-force` | 即使未通过准确率门槛也写入 learned_scores |
| `python facet.py --train-ranker --user alice` | 把训练限定为该用户自己的比较结果（外加多用户模式之前的历史行），并写入该用户自己的 learned_scores（多用户模式） |
| `python facet.py --train-keeper` | 基于你的选片决定（`source='culling'` 的比较对）训练**保留照片排序头**，只有当它在留出集 k 折准确率上胜过自动选片的启发式选择时才会保存。它为更聪明的自动选片以及“这一组里还有更好的一张”标记提供支持。在积累到足够的选片比较对之前，会退回到启发式方法。在选片确认之后，与 `--train-ranker` 由同一触发条件自动运行 |
| `python facet.py --train-keeper --train-keeper-force` | 即使未通过准确率门槛也保存保留照片排序头（同样支持 `--ranker-category` 和 `--user`） |
| `python facet.py --report-unreviewed-bursts` | 报告还有多少个连拍分组尚未复核（只读） |
| `python facet.py --eval-iqa-srcc` | 报告各 IQA／美学指标与你的星级评分之间的 Spearman SRCC（只读） |
| `python facet.py --mine-insights` | 数据挖掘报告：标注清单、指标与标注的相关性、类别分布、百分位漂移、比较数据健康度 |
| `python facet.py --mine-insights report.json` | 同上，并把完整报告另存为 JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | 以最大化与 AVA 平均主观评分的 SRCC 为目标，针对 [AVA 数据集](https://github.com/imfing/ava_downloader) 校准各类别的评分权重（只读；打印建议的权重） |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | 限定为指定类别，并把优化后的权重写回 `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | 选择优化算法（`de` ＝ 差分进化，默认；`nelder-mead` ＝ 局部单纯形） |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | 同时针对 AVA 语义标签进行校准（`--ava-tags-only` 表示只使用标签；`--apply-filters` 还会调优类别筛选阈值） |

## 配置

`scoring_config.json` 是一份**覆盖配置**：它只保存你改动过的设置，并叠加在 `config/scoring_config.default.json` 中随程序分发的默认值之上。因此，配置文件不存在意味着这套安装完全运行在那些默认值上，而不是坏掉了——参见[配置](CONFIGURATION.md#默认值与你的覆盖配置)。

若设置了 `FACET_CONFIG`，它会在 `facet.py`、`database.py`、`tag_existing.py`、`diagnostics.py`、`calibrate.py` 和 `viewer.py` 未显式指定 `--config` 时，提供 `scoring_config.json` 的默认路径；`--config` 始终优先于它。`viewer.py`（以及它启动的 `api/` 服务）本身没有 `--config` 选项，因此 `FACET_CONFIG` 是重定向它的唯一途径。如果该变量——或 `--config`——指向一个不存在的文件，那是一个错误，而不是一份空的覆盖配置：有人明确**指定**却又缺失的路径，说明是拼写错误或挂载损坏，因此网页图库会拒绝启动“开放安装”的认证路径，而不是据此断定这套安装没有任何密码，并记录一条指明缺失路径的错误日志。只有*继承而来*的默认路径才允许不存在。

两者都未设置时，`facet.py`、`database.py`、`tag_existing.py`、`diagnostics.py` 和 `calibrate.py` 会读取**工作目录**中的 `scoring_config.json`（如果存在）——因此自带配置的照片库会按它自己的配置评分——否则读取安装目录旁边的那一份。只有这条继承而来的兜底路径才允许不存在；它意味着这套安装运行在随程序分发的默认值上。

`viewer.py` 及其启动的 `api/` 服务**不会**走工作目录这一步——它们只解析 `FACET_CONFIG`，否则读取安装目录旁边的文件，绝不会读取你启动它们时所在目录里的 `scoring_config.json`。这一点很重要，因为网页图库的配置正是承载着运维人员密码的那一份：从照片库目录里启动它并不会采用该照片库的配置，而如果安装根目录里也没有配置，它就会悄悄退回到随程序分发的默认值——一个空的 `viewer.edition_password`，从而对所有路由都以匿名身份提供服务。

```bash
# 1. --config 优先于一切。这里文件缺失是一个错误，而不是一份空的覆盖配置。
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. 省略 --config 时，由 $FACET_CONFIG 提供默认路径（Docker 会设置它）。
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # 读取 /config/scoring_config.json
python facet.py --config other.json /photos   # --config 仍然优先

# 3. 两者都未设置：对命令行工具而言，工作目录中的配置优先，因此照片库可以
#    自带配置。viewer.py 没有这一步——见下文。
cd /photos/client-shoot          # 目录中有自己的 scoring_config.json
python /opt/facet/facet.py .     # 按 /photos/client-shoot/scoring_config.json 评分

# 4. 两者都未设置，这里也没有：退回到安装目录旁边的配置。
cd /tmp
python /opt/facet/facet.py /photos   # 读取 /opt/facet/scoring_config.json
                                     # 那里也没有 ＝ 运行在随程序分发的默认值上

# 5. 与上面的情形 1-4 不同，viewer.py 从不走工作目录这一步。
cd /photos/client-shoot          # 目录中有自己的 scoring_config.json——此处无关
python /opt/facet/viewer.py      # 仍然读取 /opt/facet/scoring_config.json（或 $FACET_CONFIG）
```

只有情形 4 和 5 可能什么都找不到。情形 1 和 2 指定了路径，因此文件缺失会中止命令，而不是悄悄使用无人选择的默认值来评分。

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --validate-categories` | 校验类别配置 |

## 标签标注

| 命令 | 说明 |
|---------|-------------|
| `python tag_existing.py` | 使用已存储的 CLIP 特征向量，为尚无标签的照片添加标签 |
| `python tag_existing.py --dry-run` | 预览标签但不保存 |
| `python tag_existing.py --threshold 0.25` | 自定义相似度阈值（默认：0.22） |
| `python tag_existing.py --max-tags 3` | 限制每张照片的标签数量（默认：5） |
| `python tag_existing.py --force` | 重新标注全部照片 |
| `python tag_existing.py --db custom.db` | 使用自定义数据库 |
| `python tag_existing.py --config my.json` | 使用自定义配置 |

## 数据库校验

| 命令 | 说明 |
|---------|-------------|
| `python validate_db.py` | 校验数据库一致性（交互式） |
| `python validate_db.py --auto-fix` | 自动修复所有问题 |
| `python validate_db.py --report-only` | 只报告，不询问确认 |
| `python validate_db.py --db custom.db` | 校验自定义数据库 |

检查项：评分范围、人脸指标、BLOB 损坏、特征向量长度、孤立人脸、统计离群值。

## 数据库维护

| 命令 | 说明 |
|---------|-------------|
| `python database.py` | 初始化／升级表结构 |
| `python database.py --info` | 显示表结构信息 |
| `python database.py --migrate-tags` | 填充 photo_tags 查找表（查询快 10-50 倍） |
| `python database.py --rebuild-fts` | 从照片描述／标签重建 FTS5 全文检索索引 |
| `python database.py --populate-vec` | 从特征向量填充 sqlite-vec 向量检索表 |
| `python database.py --refresh-stats` | 刷新统计缓存 |
| `python database.py --compact-config` | 把 `scoring_config.json` 重写成它本应有的覆盖配置形态，丢弃每一个与随程序分发默认值相同的取值（无损；会先做一份 `0600` 权限的备份） |
| `python database.py --stats-info` | 显示缓存状态与新旧程度 |
| `python database.py --vacuum` | 回收空间、整理碎片 |
| `python database.py --analyze` | 更新查询规划器统计信息 |
| `python database.py --optimize` | 运行 VACUUM 和 ANALYZE |
| `python database.py --backup` | 写入一份带时间戳、对 WAL 安全的数据库快照（按 `--keep N` 轮换，默认 3） |
| `python database.py --export-viewer-db` | 导出轻量版图库数据库（剥离 BLOB，缩小缩略图；若输出已存在则增量导出） |
| `python database.py --export-viewer-db --force-export` | 强制完整重新导出，即使图库数据库已存在 |
| `python database.py --cleanup-orphaned-persons` | 删除没有关联人脸的人物 |
| `python database.py --cleanup-missing-photos` | 从数据库中删除磁盘上已不存在的照片（级联删除会清理标签、检测到的人脸等；同时清除相册归属和向量索引，并使统计缓存失效） |
| `python database.py --cleanup-missing-photos --dry-run` | 预览缺失的文件但不删除 |
| `python database.py --cleanup-missing-photos --force` | 即使全部照片看起来都缺失也继续执行（用于防止卷未挂载时把一切删光） |
| `python database.py --migrate-storage-fs` | 把缩略图和特征向量从数据库 BLOB 迁移到文件系统 |
| `python database.py --migrate-storage-db` | 把缩略图和特征向量从文件系统迁回数据库 |
| `python database.py --add-user alice --role admin` | 添加用户（会提示输入密码） |
| `python database.py --add-user alice --role user --display-name "Alice"` | 添加带显示名的用户 |
| `python database.py --migrate-user-preferences --user alice` | 把评分从 photos 复制到 user_preferences |

**性能提示：** 对于大型数据库（5 万张以上照片），先各运行一次 `--migrate-tags`、`--rebuild-fts` 和 `--populate-vec`，之后定期运行 `--optimize`。

## 网页图库

| 命令 | 说明 |
|---------|-------------|
| `python viewer.py` | 在 http://localhost:5000 启动服务器（API ＋ Angular SPA） |
| `python viewer.py --port 5001` | 绑定其他端口（或设置 `PORT` 环境变量；默认 5000） |
| `python viewer.py --host 127.0.0.1` | 绑定指定网络接口（默认 `0.0.0.0`） |
| `python viewer.py --production` | 生产模式（uvicorn worker） |
| `python viewer.py --production --workers 4` | 生产模式并使用 N 个 worker（默认 1） |

## 常用工作流

### 初始设置
```bash
python facet.py /path/to/photos     # 为全部照片评分（自动多阶段）
python facet.py --cluster-faces-incremental # 聚类人脸
python database.py --migrate-tags    # 启用快速标签查询
python viewer.py                    # 查看结果
```

### 修改配置之后
```bash
python facet.py --recompute-average                # 用新权重更新全部评分
python facet.py --recompute-category portrait      # 只更新一个类别（更快）
```

### 人脸识别设置
```bash
python facet.py /path               # 扫描过程中提取人脸
python facet.py --cluster-faces-incremental     # 聚合成人物
python facet.py --suggest-person-merges         # 找出重复人物
# 在网页图库中使用 /persons 进行合并／重命名
```

### 多用户设置
```bash
# 添加用户（会提示输入密码）
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# 编辑 scoring_config.json 以设置 directories 和 shared_directories
# 把已有评分迁移给某个用户
python database.py --migrate-user-preferences --user alice
```

### 切换标签模型
```bash
# 编辑 scoring_config.json："tagging": {"model": "clip"}
python facet.py --recompute-tags     # 用新模型重新标注
```

### 切换 VRAM 档位
```bash
# 编辑 scoring_config.json："vram_profile": "auto"
# 或指定具体档位："vram_profile": "8gb"
python facet.py --compute-recommendations  # 检查分布情况
python facet.py --recompute-average        # 应用新权重
```
