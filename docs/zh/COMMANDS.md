# 命令参考

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md) · **简体中文**

[扫描](#扫描) · [预览与导出](#预览与导出) · [重新计算操作](#重新计算操作) · [人脸识别](#人脸识别) · [缩略图管理](#缩略图管理) · [诊断](#诊断) · [模型信息](#模型信息) · [权重优化](#权重优化成对比较) · [配置](#配置) · [标签标注](#标签标注) · [数据库校验](#数据库校验) · [数据库维护](#数据库维护) · [网页图库](#网页图库) · [常用工作流](#常用工作流)

> 下文使用的需求标签：`[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]`（VRAM 档位）。参见[功能需求对照表](INSTALLATION.md#各功能的要求)。

## 扫描

| 命令 | 说明 |
|---------|-------------|
| `python facet.py /path` | 扫描目录（多阶段模式，自动检测 VRAM） |
| `python facet.py /path --force` | 重新扫描已处理过的文件 |
| `python facet.py /path --single-pass` | 一次性加载全部模型；仅限 `legacy`/`8gb`（参见[处理模式](#处理模式)） |
| `python facet.py /path --pass quality` | 仅运行 TOPIQ 画质评分 |
| `python facet.py /path --pass quality-iaa` | 仅运行 TOPIQ IAA 美学价值评分 |
| `python facet.py /path --pass quality-face` | 仅运行 TOPIQ NR-Face 人脸画质评分 |
| `python facet.py /path --pass quality-liqe` | 仅运行 LIQE 画质评分与失真诊断 |
| `python facet.py /path --pass tags` | 仅运行标签标注（模型取决于 VRAM 档位） |
| `python facet.py /path --pass composition` | 仅运行 SAMP-Net 构图模式检测 |
| `python facet.py /path --pass faces` | 仅运行 InsightFace 人脸检测 |
| `python facet.py /path --pass embeddings` | 仅运行 CLIP/SigLIP 特征向量提取（不写入标签） |
| `python facet.py /path --pass saliency` | 仅运行 BiRefNet 主体显著性检测 |
| `python facet.py /path --db custom.db` | 使用自定义数据库文件 |
| `python facet.py /path --config my.json` | 使用自定义评分配置 |
| `python facet.py --resume` | 续跑上一次中断、失败或崩溃的扫描 |
| `python facet.py --retry-failed` | 重新处理上一次扫描中失败的文件（`--retry-failed all` 处理所有运行的失败文件） |
| `python facet.py /path --force-since 2026-01-01` | 与 `--force` 类似，但只处理最后一次扫描时间早于该日期的照片 |
| `python facet.py /path --watch` | 一旦出现新照片就重新扫描（需要 `pip install watchdog`；`--watch-debounce N`，默认 30 秒） |
| `python facet.py /path --force-low-space` | 跳过扫描前的可用空间检查 |

**`--resume`** 还能恢复因崩溃、内存耗尽或断电而被终止的扫描：即状态仍为 `running`、且心跳早于 `processing.scan_stale_seconds`（默认 120）的运行。它沿用该次运行的目录。配合 `--force` 时，会跳过自该次运行开始后已重新评分的文件。若另一次扫描看起来仍在运行，则拒绝启动。

### 扫描记录

Facet 会记录每次扫描（状态、模式、目录、计数器）以及每个文件的错误。Ctrl+C 会把该次运行标记为 `interrupted`，以便 `--resume` 接续。失败的文件会被列出，且只有 `--retry-failed` 才会重试。查看器根据命令行的 `@FACET_PROGRESS` 行显示扫描进度。

### 处理模式

**多阶段（默认）：** 检测 VRAM 并按顺序加载模型。每个阶段加载自己的模型、处理全部照片，然后卸载，因此即使 VRAM 有限也能运行高质量模型。

**单阶段（`--single-pass`）：** 一次性加载全部模型。速度更快，但需要更多 VRAM。

- 它用 CLIP+MLP 评分头为美学评分，因此适用于 `legacy` 和 `8gb` 配置档。
- 在 `16gb` 和 `24gb` 上，美学模型是 TOPIQ，只有多阶段运行才会使用它。单阶段请求（`--single-pass` 或 `processing.mode: "single-pass"`）会记录一条警告并改为多阶段运行。
- `--pass NAME` 和 `--dry-run` 不做此检查。
- 商业模式下保留单阶段，因为那里由原生 Q-ReAlign 为美学评分。

**升级说明：** 旧版本在 `16gb`/`24gb` 上做单阶段扫描时，会为每张照片保存中性的 5.0 美学评分。请用 `--force` 以多阶段重新扫描这些文件夹。找出它们：`SELECT path FROM photos WHERE scoring_model = 'topiq' AND aesthetic = 5.0 AND topiq_score IS NULL`。

**指定阶段（`--pass NAME`）：** 只运行一个阶段，用于更新部分指标而无需完整重新处理。

| 阶段 | 模型 | 输出 | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic` 评分（0-10） | 约 2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa`（艺术价值，基于 AVA 训练） | 与 TOPIQ 共用 |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa`（人脸画质） | 与 TOPIQ 共用 |
| `quality-liqe` | LIQE | `liqe_score` 加失真诊断（模糊、过曝、噪点） | 约 2 GB |
| `tags` | CLIP / Qwen VLM | 来自所配置词表的语义标签 | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern`（8 种模式）＋ `comp_score` | 约 2 GB |
| `faces` | InsightFace buffalo_l | 人脸、关键点、闭眼、识别特征向量 | 约 2 GB |
| `embeddings` | CLIP ViT-L-14 或 SigLIP 2 NaFlex | 用于相似度和标签标注的 `clip_embedding` | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`、`subject_prominence`、`subject_placement`、`bg_separation` | 约 3 GB |

多遍扫描使用单调时钟。EXIF 批处理耗时和回退读取的工作线程累计秒数已包含在解码耗时中；并行回退可能重叠。聚合、缩略图生成（包括源文件读取）和不含缩略图的保存分别计时；保存包括结果准备和提交，不仅是 SQL。受限遍次跳过聚合和照片缩略图。现有解码与模型加载的重叠以及嵌套的图像平面重建计时保持不变：请勿累加所有计时，也不要将 EXIF 工作线程秒数解释为总耗时百分比。单遍扫描不在本次计时范围内。收集基线时，将固定的 500 张 RAW/JPEG 副本扫描到临时数据库，保留最终摘要，并记录版本、配置档、工作线程数、分块大小、存储和缓存条件。在相同条件下重复以进行比较。未提供参考照片集或前后基准测试；不声称速度提升。

## 预览与导出

| 命令 | 说明 |
|---------|-------------|
| `python facet.py /path --dry-run` | 对 10 张样本照片评分但不保存 |
| `python facet.py /path --dry-run --dry-run-count 20` | 对 20 张样本照片评分 |
| `python facet.py --export-csv` | 把全部评分导出为带时间戳的 CSV |
| `python facet.py --export-csv output.csv` | 导出到指定的 CSV 文件 |
| `python facet.py --export-json` | 把每个已存储的指标导出为带时间戳的 JSON |
| `python facet.py --export-json output.json` | 导出到指定的 JSON 文件 |
| `python facet.py --export-manifest` | 写入 `facet_manifest.json`，供 Lightroom Classic 增效工具等外部工具使用 |
| `python facet.py --export-manifest /path` | 把清单限定为某个路径下的照片 |
| `python facet.py --export-manifest --user alice` | 多用户模式：使用 Alice 的评分（标签和评分仍为全局） |
| `python facet.py --import-lightroom FILE` | 导入增效工具的星级、留用和淘汰；以 Lightroom 为准 |
| `python facet.py --import-lightroom FILE --user alice` | 多用户模式：写入 Alice 的评分；在多用户安装上**必须**指定 |
| `python facet.py --import-sidecars` | 从 XMP 附属文件导入评分、标记、保留/淘汰、手动 GPS 和关键字 |
| `python facet.py --import-sidecars /path` | 仅导入某个路径下照片的附属文件 |
| `python facet.py --import-sidecars /path --dry-run` | 打印变更和冲突的 JSON 计划；不写入任何内容 |
| `python facet.py --import-sidecars /path --sidecar-fields keywords,gps` | 仅导入这些字段组：`review`（星级、收藏、淘汰、保留）、`gps`、`keywords`（默认：全部） |
| `python facet.py --import-sidecars /path --overwrite-sidecar-review` | 即使存在较新的本地编辑（`newer_local_edit`）也应用审核字段；请先用 `--dry-run` 预览 |
| `python facet.py --import-sidecars --user alice` | 多用户模式：把评分和保留/淘汰导入 Alice 的账户，仅限她可见的照片 |
| `python facet.py --import-sidecars --sidecar-naming full` | 读取 `<image.ext>.xmp` / `<image.ext>.facet.xmp`（默认）；较新的文件优先 |
| `python facet.py --import-sidecars --sidecar-naming basename` | 读取 `<image>.xmp`（去掉扩展名）；拒绝共享基本名 |
| `python facet.py --import-sidecars --sidecar-naming auto` | 两种命名都接受；两者同时存在的照片会被跳过 |
| `python facet.py --import-sidecars --overwrite-manual-gps` | 用附属文件中的位置替换 Facet 中已设置的手动 GPS |
| `python facet.py --export-sidecars` | 为全部照片写入或合并 `<image>.xmp` 附属文件 |
| `python facet.py --export-sidecars /path --reconcile-keywords` | 同时移除不再存在的 Facet 自有关键字（需要 ExifTool） |
| `python facet.py --export-sidecars /path` | 仅导出某个路径下照片的附属文件 |
| `python facet.py --export-sidecars --user alice` | 多用户模式：导出 Alice 的评分和保留/淘汰，仅限她可见的照片 |
| `python facet.py --export-sidecars --embed-originals` | 同时把元数据写入 JPEG/HEIC/TIFF/PNG/DNG 原始文件**本身** |
| `python facet.py --export-sidecars --score-to-stars` | 对你没有评过分的照片，由评分推导出 `xmp:Rating` |

**试运行。** 在 `16gb`/`24gb` 上，美学一列显示 `n/a`，因为 TOPIQ 只在真实扫描中运行（商业模式下显示 Q-ReAlign 评分）。综合评分把它按中性的 5.0 计算。

**CSV 与 JSON。** `tags` 列只含 AI 标签；不包含[手动标签](VIEWER.md#手动标签)。在 JSON 中，每张照片的 `scores` 对象包含每个已存储的指标；NULL、非有限数字与 BLOB 均为 `null`。JSON 导出会拒绝覆盖数据库本身或其 `-wal`/`-shm`/`-journal` 文件。

**清单。**

- 可选参数限定的是*导出哪些照片*。文件始终是工作目录中的 `facet_manifest.json`。
- 它携带 `star_rating`/`is_favorite`/`is_rejected`（全局，或指定 `--user` 的）、`is_burst_lead`、AI 标签加手动标签，以及一个 `pending_corrections` 计数。非零计数会打印一条指向 `--detect-panoramas` 的警告。
- _清单版本 2_ 新增 `burst_group_id`、`sequence_kind`、`sequence_group_id` 和 `score_stars`（评分经 `xmp_export.score_to_rating` 换算）。为此构建的增效工具会拒绝更早的清单：请重新导出。见 [Facet 增效工具](INTEROP.md#facet-增效工具星级留用旗标元数据字段与关键字)。

**`--import-lightroom`** 读取增效工具自己的导出文件 `facet_lightroom_state.json`（`{"format":"facet-lightroom-state","version":1,"photos":[...]}`），而不是清单。格式错误的文件会在任何写入之前被拒绝。文件携带的每个字段都以 Lightroom 的值为准；省略的字段保留 Facet 的值。它会打印 `matched=… unmatched=… changed=…`。见 [Lightroom → Facet](INTEROP.md#lightroom--facet)。

**元数据双向同步。** Facet 会把评分、颜色标记、关键词、照片描述和已命名的人脸区域写入标准的 `<image>.xmp` 附属文件，Lightroom、darktable、digiKam、immich 等都能读取。

- 除非你加上 `--embed-originals`（仅限 JPEG/HEIC/TIFF/PNG/DNG；RAW 绝不会被改动），否则原始文件永远不会被修改。
- 关键字是 AI 标签加上你的[手动标签](VIEWER.md#手动标签)。它们只会被添加，除非 `--reconcile-keywords` 移除 Facet 之前写入的关键字；外部关键字会保留。参见[手动标签与 XMP 关键字](INTEROP.md#手动标签与-xmp-关键字)。
- 嵌入和关键字合并需要 **exiftool**。没有它时，Facet 会写入纯 XML 附属文件。

**附属文件导入。**

- 导入的关键字会成为[手动标签](INTEROP.md#手动标签与-xmp-关键字)；不需要 `--migrate-tags`。
- 没有标准评分或标记的 Facet 决定（保留、淘汰或未决定）会不经扫描时间检查直接应用。
- 使用 `--user` 时，关键字和 GPS 仍为全局。使用 `--export-sidecars --user` 时，关键字、GPS 和拍摄日期仍为全局。
- 附属文件如何与本地编辑比较：[附属文件导入预览与冲突](INTEROP.md#附属文件导入预览与冲突)。

### Immich 同步

把 Facet 的评分和收藏推送到 [Immich](https://immich.app/) 服务器（单向，Facet → Immich，仅使用 REST API）。资源按 `originalPath` 匹配，使用 `immich` 配置块中的路径前缀映射。

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --immich-test` | 检查连接和 API 密钥（`immich.url` ＋ `immich.api_key`，以 `x-api-key` 发送） |
| `python facet.py --immich-sync` | 推送星级评分（1–5）和收藏；遵循 `--dry-run` 和 `--user` |
| `python facet.py --immich-sync --dry-run` | 报告将会发生的变化，但不写入 |

只发送 1–5 的评分（绝不发送 0/−1）。还可选择用一个精选照片相册收集评分高于阈值的照片。参见[配置 — Immich 同步](CONFIGURATION.md#immich-同步)。

### Immich 堆叠计划

这些命令接受 `--config`、`--db` 和 `--user`；多用户模式须有已存在的所有者。预览不会写入。应用需要已审阅的计划摘要。

| CLI | |
|---|---|
| `python facet.py --immich-stacks-plan import --stack-plan-out NEW_JSON` | 预览远程堆叠的本地导入 |
| `python facet.py --immich-stacks-plan push --stack-id UUID --stack-plan-out NEW_JSON` | 预览本地堆叠的远程创建 |
| `python facet.py --immich-stacks-apply PLAN_JSON --ack-stack-plan SHA256` | 应用已审阅的计划 |

- 重复 `--stack-id UUID` 可选择来源组。
- `--stack-plan-out NEW_JSON` 会写入一个新的私有文件（POSIX `0600`），并且绝不覆盖已有文件。在 Windows 上，请选择访问控制列表（ACL）仅允许你的账户访问的文件夹。
- 上限：1000 组、每组 1000 个成员、总计 20000 个成员、16 MiB。
- 映射不完整和重叠会跳过整组。已有的组绝不会被更新。

参阅[权限、冲突及远程竞争限制](IMMICH.md#手动堆叠导入和推送)。

## 重新计算操作

这些命令用于更新指标或派生新数据，而无需重新运行完整的评分流水线。多数命令复用已存储的缩略图和关键点，对 CPU 负担很轻；涉及 AI 的条目（例如 `--generate-captions`）需要 GPU。

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --recompute-average` | 根据已存储的指标重新计算综合评分和类别（不重新读取任何图像） |
| `python facet.py --recompute-category portrait` | 只重新计算单个类别的评分 |
| `python facet.py --tag-untagged` | 只为尚无标签的照片打标签，使用已存储的特征向量 |
| `python facet.py --recompute-tags` | 使用所配置的模型重新标注全部照片 |
| `python facet.py --recompute-tags-vlm` | 使用 VLM 标注器重新标注全部照片 |
| `python facet.py --detect-moments` | 为新照片标注其叙事时刻（每次扫描后运行） |
| `python facet.py --recompute-moments` | 为整个照片库重新标注叙事时刻 |
| `python facet.py --discover-moments` | 根据你的照片描述提出一份时刻词表，写入 `scoring_config.discovered.json` |
| `python facet.py --detect-junk` | 标出截图、文档、收据、表情包和幻灯片（每次扫描后运行） |
| `python facet.py --recompute-junk` | 为整个照片库重新评估 `junk_kind` |
| `python facet.py --recompute-saliency` | `[GPU]` 从已存储的缩略图重新计算主体显著性；`--force` 全部重做 |
| `python facet.py --recompute-composition-cpu` | 用基于规则的方法重新计算构图（CPU，任意档位） |
| `python facet.py --recompute-composition-gpu` | `[GPU]` 用 SAMP-Net 重新计算构图 |
| `python facet.py --recompute-iqa` | `[GPU]` 从已存储的缩略图补齐缺失的 TOPIQ IAA、NR-Face 和 LIQE 评分。所有档位都可运行；在 CPU 上（`legacy`）慢得多 |
| `python facet.py --detect-text` | 把图像中的文字读入 `ocr_text`，使搜索能找到它（需手动开启，见说明） |
| `python facet.py --recompute-text` | 对整个照片库重新运行 OCR |
| `python facet.py --recompute-colors` | 提取主色调与冷暖色温，写入 `dominant_hue` / `color_temp`（CPU，快速） |
| `python facet.py --recompute-form` | 重新计算对称性、平衡感、边缘熵、分形复杂度和色彩和谐度（CPU） |
| `python facet.py --recompute-skin-tone` | 重新计算人像肤色自然度（CPU；仅作为点评中的参考说明） |
| `python facet.py --recompute-distortions` | 标注可能的失真（运动模糊、偏色……），并与 `liqe_score` / `noise_sigma` 做相关性分析（仅供参考） |
| `python facet.py --upgrade-db` | 迁移 schema 并运行完整的回填链（见说明） |
| `python facet.py --recompute-blinks` | 从已存储的关键点重新计算闭眼检测（CPU，快速） |
| `python facet.py --recompute-eyes-expression` | 从已存储的关键点重新计算睁眼与表情评分（CPU，快速） |
| `python facet.py --recompute-face-signals` | 从已存储的关键点回填每张人脸的睁眼与微笑评分（CPU，快速） |
| `python facet.py --recompute-burst` | 重新计算连拍分组（记录 `Burst state: N rows changed`） |
| `python facet.py --detect-sequences` | 检测包围曝光和全景照片组（每次扫描后运行；见说明） |
| `python facet.py --detect-panoramas` | 根据已存储的缩略图检测全景照片组（先运行包围曝光检测；CPU） |
| `python facet.py --detect-duplicates` | 通过 pHash 检测重复照片（记录 `Duplicate state: N rows changed`） |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | 评估近似重复的余弦阈值（有标注时给出精确率/召回率） |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` 使用 VLM 生成 AI 照片描述 |
| `python facet.py --translate-captions` | 把英文照片描述翻译成所配置的语言（CPU，MarianMT） |
| `python facet.py --extract-gps` | 把 EXIF GPS 复制到数据库；跳过在查看器中设置过的位置 |
| `python facet.py --rescan-gps` | 为全部照片重新提取 EXIF GPS（覆盖）；跳过在查看器中设置过的位置 |
| `python facet.py --recompute-embeddings` | 为全部照片重新计算 CLIP/SigLIP 特征向量（更换模型后必须执行） |
| `python facet.py --score-topiq` | `[GPU]` 对每张带缩略图的照片重新计算 `topiq_score`（覆盖） |
| `python facet.py --backfill-focal-35mm` | 为缺少等效 35mm 焦距的照片从 EXIF 回填该值 |
| `python facet.py --backfill-clipping` | 从已存储的直方图推导各通道的溢出百分比（可续跑） |
| `python facet.py --recompute-silhouette` | 用基于人脸的规则重新推导 `is_silhouette`（见说明） |
| `python facet.py --repair-int-columns` | 对外部 EXIF 写入工具存入整数列（例如 ISO）的小数值取整 |
| `python facet.py --repair-neutral-iqa` | 清除 1.20 之前存入的虚假中性 5.0 IQA 评分（见说明） |
| `python facet.py --compute-recommendations` | 分析数据库并显示评分摘要 |
| `python facet.py --compute-recommendations --verbose` | 显示详细统计信息 |
| `python facet.py --compute-recommendations --apply-recommendations` | 自动应用评分修正 |
| `python facet.py --compute-recommendations --simulate` | 预览预计产生的变化 |

**`--recompute-average`** 不保留快照：如需回退，请恢复某个权重快照并重新计算。从 1.20 或更早版本升级后，先运行 `--recompute-silhouette`，再把本命令运行两次。第一遍会存储新的百分位，所以第二遍仍会改动一些行。

**时刻。**

- `--detect-moments` 把每条新描述只编码一次写入 `caption_embedding`。对既有照片库的首次回填最好使用 GPU；可加 `--limit N` 先在样本上试运行。
- 对 `--recompute-moments`（或 `--detect-junk`）加上 `--dry-run --verbose` 可预览而不写入。
- `narrative_moments.vlm_tiebreak`（16gb/24gb）：设置了 `narrative_moments.vlm_tiebreak.enabled` 时，该档位的 VLM 会重新分类低置信度的帧。
- `--discover-moments` 对已存储的描述向量聚类，并为每个簇命名。它绝不会改写正在使用的配置。请先运行 `--detect-moments`；用 `--discover-min-cluster-size N` 调整。
- 当 `narrative_moments.caption_min_confidence > 0` 时，`--generate-captions` 会跳过未标注、`other` 和低置信度的照片。

**废片。** 干净的照片会被标记为 `not_junk`，因此之后的运行只检查新照片。

**`--detect-text`** 需手动开启：要求 `scoring_config.json` 中的 `ocr.enabled` 并 `pip install easyocr`。参见[配置 — OCR](CONFIGURATION.md#ocr)。

**`--detect-sequences`** 先根据 EXIF 找出包围曝光，再根据缩略图几何关系找出全景，并把每个连拍分组的代表帧移到其基准曝光帧上。它也会在 `--upgrade-db` 中运行。在它运行之前，查看器的**包围曝光**／**全景**／**HDR 全景**选片视图以及 `hide_brackets` / `hide_panoramas` 开关都不起作用。每次运行都会重新标注整个照片库，因此在你剔除旧的代表帧之后，重新运行它（或 `--detect-panoramas`）会选出新的代表帧。

**`--upgrade-db`** 迁移 schema 并运行：extract-gps、detect-duplicates、recompute-iqa、saliency、composition-cpu、burst、blinks、eyes-expression、face-signals、average。它可安全重复运行，并跳过生成描述等重步骤。它还会把被 pillow-heif 1.6 弄成横置的 HEIF 缩略图（连同其人脸）转回正向；原始文件绝不会被写入。无法读取的 HEIF 文件会在下一次运行时重试。

**`--recompute-silhouette`** 只读取数据库，按批提交，并遵循 `--dry-run`。

- 报告按照片的人脸框与缩略图的对应情况分组：`exact`、`scaled`、`count_mismatch`（匹配方式尚未经过验证）、`other`。
- 没有人脸，或人脸框无法定位的照片会被置为 0。
- `face_count` 为 NULL，或有人脸但没有缩略图的照片保持不变（`skipped_face_count_null` / `skipped_no_thumbnail`）。
- 之后请运行 `--recompute-average`。参见 [SCORING.md](SCORING.md)。

**`--repair-int-columns`** 只读取数据库。没有它时图库也能正确显示这些值，但范围筛选和排序使用的是实际存储的值，因此显示为 ISO 63 的照片可能会被漏掉。无法成为整数的值会置为 NULL。

**`--repair-neutral-iqa`** 把 `aesthetic_iaa`、`face_quality_iqa` 和 `liqe_score` 中所有恰好等于 5.0 的值置为 NULL，并按列打印数量。

- 它不会改动 `aesthetic`、`topiq_score`、`aesthetic_v25` 或 `quality_score`。
- 真实的恰好 5.00 的评分也会被清除；`--recompute-iqa` 会重新填充，数值可能略有不同。
- 之后运行 `--recompute-iqa` 和 `--recompute-average`。
- 与 `--dry-run` 同用会被拒绝（退出码 2）。不属于 `--upgrade-db`。请重新加载已打开的图库页面以查看新的筛选范围。

### 补充画质模型

除主要的 TOPIQ 美学评分外，还有三个 PyIQA 模型参与评分。它们与 TOPIQ 共用 VRAM，并在默认的多阶段扫描中运行。

- **TOPIQ IAA**（`--pass quality-iaa`）：基于 AVA 训练的艺术价值，与技术质量相互独立。存储为 `aesthetic_iaa`。
- **TOPIQ NR-Face**（`--pass quality-face`）：人脸区域的画质。存储为 `face_quality_iqa`。
- **LIQE**（`--pass quality-liqe`）：画质评分外加失真诊断（运动模糊、过曝、噪点）。存储为 `liqe_score`。

当模型无法为照片评分时：

- 它存入 NULL，而不是中性的 5.0。GPU 显存不足错误会先以一半的批大小重试，直至一张图片。
- LIQE 会跳过缩略图短边小于 224 px 的照片（在把长边限制为 1024 px 之后）。
- NR-Face 会跳过 `face_count` 为 0 的照片。它找不到人脸的照片会记入 `iqa_declined`，直到重新扫描（`--force`）、`--refresh-thumbnails` 或 `--fix-thumbnail-rotation` 为止。升级 pyiqa 不会清除它。
- 其他失败不会被存储；下一次 `--recompute-iqa` 会再试。
- 使用 `--pass quality`、`quality-iaa`、`quality-face` 和 `quality-liqe` 时，失败的照片保留其已存储的值。
- 完整扫描会记录 TOPIQ 模型失败的照片，供 `--retry-failed` 使用；`--pass quality` 不会。

`--recompute-iqa` 只填充为 NULL 的列，绝不替换已存储的值，包括旧版本写入的中性 5.0。请用 `--repair-neutral-iqa` 清除这些值，再运行 `--recompute-iqa` 和 `--recompute-average`，或用 `--force` 重新扫描。见[补充 IQA 维度](SCORING.md#补充-iqa-维度)。

### 基准测试与补充评分

| 命令 | 说明 |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | 从缓存的特征向量填充 `aesthetic_clip`（不做图像推理；不属于默认的 `aggregate`）。参见 [SCORING.md](SCORING.md#补充信号不计入默认综合评分) |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | 针对每个评分列，计算其与 AVA 真值的 SRCC ＋ PLCC |

### 主体显著性

`--pass saliency` 与 `--recompute-saliency` 使用 BiRefNet-dynamic（`ZhengPeng7/BiRefNet_dynamic`，通过 `transformers`，约 3 GB VRAM）找出主体，然后推导四项指标：

- **主体清晰度**：主体是否合焦（拉普拉斯方差，主体对比背景）。
- **主体突出程度**：主体面积／画面面积。主体占据画面时（例如微距）数值较高。
- **主体位置**：主体质心的三分法评分。
- **背景分离度**：主体与背景之间的边缘对比（背景虚化质量）。

所有档位都会运行显著性；`legacy` 在 CPU 上运行，较慢。`--recompute-saliency` 在照片库所在卷离线时也能运行，且可续跑。在 CUDA 上，批大小由空闲显存推算（1024 px 下每张图片约 2.4 GiB，范围 1 至 8 张），遇到显存不足错误时减半。

- **失败的照片**会记录一条 ERROR 且不写入任何内容。从未评分的照片保持 NULL，并会被下一次 `--recompute-saliency` 选中；已有显著性的照片保留其值，即使使用 `--recompute-saliency --force`。完整重新扫描（例如 `python facet.py --force`）则会为其存入 NULL。
- **没有主体的照片**存入 NULL 的清晰度、位置和分离度，突出程度为 0.0，`subject_bbox` 为 NULL（构图步骤中的 `power_point_score` 也为 NULL）。这是最终结果，不会再次测量。
- **较旧的行**存的是中性的 5.0。`--recompute-saliency` 和 `--recompute-composition-cpu` 会将其重写。`--recompute-saliency` 还会选取 `subject_bbox` 出现之前评分的照片。
- NULL 指标在综合评分中按中性计分。见[主体显著性维度](SCORING.md#主体显著性维度)。

### 标签模型

标签模型取决于 VRAM 档位：

| 档位 | 模型 | 工作方式 |
|---------|-------|-------------|
| `legacy` | CLIP 相似度 | 计算图像特征向量与标签文本特征向量之间的余弦相似度。不额外加载模型。 |
| `8gb` | CLIP 相似度 | 与 legacy 相同，在已存储的 CLIP ViT-L-14 特征向量上进行。 |
| `16gb` | Qwen3.5-2B | 用于场景标注的多模态模型。 |
| `24gb` | Qwen3.5-4B | 更大的多模态模型。 |

所有标注器都会把输出映射到所配置的标签词表。用 `--recompute-tags` 以该档位的模型重新标注，或用 `--recompute-tags-vlm` 使用 VLM。

**标签何时写入。** 在 CLIP 相似度档位（`legacy`/`8gb`，以及未安排 VLM 遍的 `16gb`/`24gb`）上，多阶段扫描在特征向量阶段就完成打标签，因此扫描时的类别和综合评分已经能看到标签。只带单个 `--pass` 的运行（例如 `--pass embeddings`）不写入标签。在 CLIP 档位上运行 `--pass tags` 会停止并指向 `--recompute-tags`。已有的行保留其类别，直到运行 `--recompute-average`。

### 特征向量模型

有两个特征向量模型，通过 `clip_config` 按 VRAM 档位选择：

| 配置 | 模型 | 维度 | 使用者 |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | 16gb、24gb 档位 |
| `clip_legacy` | CLIP ViT-L-14 | 768 | legacy、8gb 档位 |

特征向量支撑着标签标注、重复检测、相似照片搜索，以及 CLIP+MLP 美学评分（legacy/8gb）。更换模型后必须为全部照片重新计算特征向量（`--force`、`--pass embeddings` 或 `--recompute-embeddings`）。

## 人脸识别

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | 为新照片提取人脸（GPU，并行） |
| `python facet.py --extract-faces-gpu-force` | 删除全部人脸并重新提取（GPU；已命名人物会保留；商业模式下使用宽松许可的提取器） |
| `python facet.py --cluster-faces-incremental` | HDBSCAN 聚类，保留所有人物（CPU） |
| `python facet.py --cluster-faces-incremental-named` | 聚类，仅保留已命名的人物（CPU） |
| `python facet.py --cluster-faces-force` | 完整重新聚类，删除所有人物（CPU） |
| `python facet.py --suggest-person-merges` | 给出可能的人物合并建议 |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | 使用更严格的阈值 |
| `python facet.py --refill-face-thumbnails-incremental` | 生成缺失的人脸缩略图（CPU，并行） |
| `python facet.py --refill-face-thumbnails-force` | 重新生成全部人脸缩略图（CPU，并行） |

## 缩略图管理

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | 依据 EXIF 方向旋转已存储的缩略图 |
| `python facet.py --refresh-thumbnails` | 从相机内嵌的预览重建 RAW 缩略图 |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | 同上，但并行读取更多 |

**`--fix-thumbnail-rotation`** 适用于在处理 EXIF 方向之前处理过的照片。它只读取 EXIF 头和已存储的缩略图。

**`--refresh-thumbnails`** 会让每张 RAW 照片的已存储缩略图通过显示配置重新渲染（优先使用相机预览，去马赛克作为兜底；参见 [CONFIGURATION.md](CONFIGURATION.md#raw-解码)）。请在该配置出现之前扫描的照片库上使用它：旧的缩略图会抹平包围曝光各帧之间的曝光差异。它不加载任何模型，也不改动任何评分。

- **速度**取决于磁盘或网络吞吐，而不是 CPU。`--refresh-thumbnails-workers`（默认 8）设定同时读取多少个文件：在高速网络挂载上可以调高，在低速本地磁盘上则应调低。过高的取值会占用大量内存。
- **可续跑。** 用 Ctrl-C 中止后，下一次运行会从中断处继续。完整跑完的运行，下次会从头开始。
- **全黑的渲染结果**（例如来自被截断的 RAW）会被丢弃：照片保留其旧缩略图，按文件名记入日志，并在下次运行时重试。
- **包围曝光的帧**在不使用相机预览和曝光增益的情况下渲染，因此每个图块显示的是传感器记录到的内容（参见 [CONFIGURATION.md](CONFIGURATION.md#包围曝光照片按未校正方式渲染)）。请在 `--detect-sequences` 之后运行。

### 哪些操作会更新已存储的缩略图

缩略图是在扫描时生成的，因此在显示配置出现之前扫描过的照片库，在图库网格中仍会保留旧的渲染结果。有两种途径可以更新它们：

| 途径 | 覆盖范围 | 代价 |
|------|--------|------|
| 重新扫描（`python facet.py <dir>`） | 它扫描到的一切，包括缩略图和直方图 | 一次完整的评分运行 |
| `--refresh-thumbnails` | 每一行 RAW 照片的缩略图 | 受存储速度限制，大型照片库需数小时 |

**什么都不会自动发生。** 详情视图始终实时渲染，但图库网格显示的是已存储的缩略图。一条可关闭的横幅会统计还有多少行在等待。其计数在重新扫描之后最多可能滞后一小时；`--refresh-thumbnails` 和 `python database.py --refresh-stats` 会更新它。

## 诊断

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --doctor` | 运行诊断检查（Python、GPU、ONNX Runtime、依赖、配置、数据库） |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | 为诊断模拟 GPU 硬件 |

`--doctor` 会报告 Python 版本、PyTorch/CUDA 构建、GPU 与驱动、ONNX Runtime 构建与执行提供程序、建议的 VRAM 档位、可选依赖，以及配置/数据库状态。在 CUDA 上，它还会在 GPU 上试加载 ONNX Runtime。当 PyTorch 或 ONNX Runtime 的构建不对时，它会打印用于修复的 `pip install` 命令（参见[用于人脸检测的 ONNX Runtime](INSTALLATION.md#用于人脸检测的-onnx-runtime)）。

`--simulate-gpu NAME` 与 `--simulate-vram GB` 需要配合 `--doctor`；`--simulate-vram` 还需要配合 `--simulate-gpu`。

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --check-raw-rendering` | 用旧的和当前的解码设置渲染 20 张抽样 RAW 照片 |
| `python facet.py --check-raw-rendering 50` | 改为抽样 50 张照片 |

只读。它会打印每种渲染方式得到的平均亮度：LibRaw 自动亮度、固定增益的去马赛克，以及相机预览。可以用它在扫描或 `--refresh-thumbnails` 之前，在自己的文件上检验 `raw_decode.bright`。固定增益列和预览列会保留包围曝光的曝光阶梯；自动亮度会把它压平。

## 模型信息

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --list-models` | 显示可用模型及其 VRAM 需求 |

## 权重优化（成对比较）

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --comparison-stats` | 显示成对比较的统计信息 |
| `python facet.py --optimize-weights` | 根据你的比较优化权重；仅当通过留出检验时才应用（见说明） |
| `python facet.py --optimize-weights --optimize-force` | 即使权重未通过检验也应用 |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | 只在这些比较来源上训练 |
| `python facet.py --optimize-weights --optimize-category portrait` | 只在一个类别上训练，并写入其 v4 `categories[].weights` 块 |
| `python facet.py --auto-tune-categories` | **仅限超级管理员**（多用户模式下需传入 `--user`）：报告各类别的标注就绪程度（仅报告） |
| `python facet.py --sync-label-comparisons` | 从星级、收藏和淘汰重建由评分派生的比较对（source=rating） |
| `python facet.py --train-ranker` | 训练个人排序模型，若胜过综合评分则写入 learned_scores |
| `python facet.py --train-ranker --ranker-category portrait` | 只在一个类别上训练排序模型 |
| `python facet.py --train-ranker --train-ranker-force` | 即使未通过准确率门槛也写入 learned_scores |
| `python facet.py --train-ranker --user alice` | 基于该用户的比较进行训练并写入其 learned_scores（多用户模式） |
| `python facet.py --train-keeper` | 基于你的选片决定训练**保留照片排序头**（见说明） |
| `python facet.py --train-keeper --train-keeper-force` | 即使未通过门槛也保存该排序头（同样支持 `--ranker-category` 和 `--user`） |
| `python facet.py --report-unreviewed-bursts` | 统计尚未复核的连拍分组数量（只读） |
| `python facet.py --eval-iqa-srcc` | 报告各 IQA／美学指标与你的星级评分的吻合程度（SRCC；只读） |
| `python facet.py --evaluate-models SLOT` | 按与你的选择的一致程度，对某个槽位的候选模型排序（只读；见说明） |
| `python facet.py --mine-insights` | 报告标注、指标相关性、类别、百分位漂移和比较数据 |
| `python facet.py --mine-insights report.json` | 同上，并把完整报告另存为 JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | 针对 [AVA 数据集](https://github.com/imfing/ava_downloader)校准各类别的权重（只读；打印建议） |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | 限定为指定类别，并把权重写入 `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | 选择优化算法（`de` ＝ 差分进化，默认；`nelder-mead` ＝ 局部单纯形） |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | 同时使用 AVA 标签（`--ava-tags-only` 表示只用标签；`--apply-filters` 用于调优筛选阈值） |

**`--optimize-weights`** 在所有比较来源上训练，并按可靠性加权。只有当新权重在留出比较上优于当前权重时才会应用（5 折交叉验证，单侧 McNemar 检验，p < 0.05，至少高 2 个百分点）。应用时还会重新居中该类别的 `modifiers.bonus`，因此其照片只是重新排序，而不是整体升高或降低。参见 [SCORING.md](SCORING.md)。

**`--train-keeper`** 从 `source='culling'` 的比较对中学习，只有当它在留出数据上胜过自动选片的启发式选择时才会保存。它为自动选片的挑选以及“这一组里还有更好的一张”标记提供支持。在积累到足够的选片比较对之前，使用启发式方法。它与 `--train-ranker` 由同一触发条件重新训练。

**`--evaluate-models SLOT`** 可用槽位：`aesthetic`、`quality`、`faces-detect`、`faces-recognize`、`faces-centroid`、`blink`、`face-quality`、`end-to-end`。

- `--candidates a,b` 指定候选（`stored:<列名>` 或已注册名称）。
- `--eval-out PATH` 设置输出路径（默认 `.facet_cache/eval/<slot>-<时间戳>.json`）。
- 人脸槽位改为与已存储的 InsightFace 人脸比较，而不是与你的选择比较，因此仅适用于默认模式的照片库：`faces-detect`（`yunet`、`yunet@<conf>`、`blazeface`）、`faces-recognize`（`sface`、`sface@<阈值>`）、`faces-centroid`（调节 SFace 的 `merge_threshold` / 自动合并）、`blink`（扫描宽松的闭眼阈值）。
- `--limit N` 限制照片数（默认 600）或参考人脸数（默认 1200）。

## 配置

`scoring_config.json` 是一份**覆盖配置**：它只保存你改动过的设置，并叠加在 `config/scoring_config.default.json` 之上。没有配置文件时，Facet 运行在默认值上。参见[配置](CONFIGURATION.md#默认值与你的覆盖配置)。

读取哪个文件：

1. `--config` 始终优先。
2. 否则使用 `FACET_CONFIG`（如已设置）。它适用于 `facet.py`、`database.py`、`tag_existing.py`、`diagnostics.py`、`calibrate.py` 和 `viewer.py`。`viewer.py` 没有 `--config`，因此这是它唯一的覆盖方式。
3. 否则，对命令行工具（不含 `viewer.py`），使用**工作目录**中的 `scoring_config.json`，因此照片库可以自带配置。
4. 否则使用安装目录旁边的文件。如果那里也没有，则采用随程序分发的默认值。

`--config` 或 `FACET_CONFIG` 指定的路径若不存在，是一个错误，而不是“使用默认值”。查看器会记录缺失的路径，并拒绝以开放模式启动。

> **警告：** `viewer.py` 从不读取你启动它时所在目录中的 `scoring_config.json`。如果你从某个照片库目录启动它，而安装根目录里没有配置，它就会运行在默认值上：`viewer.edition_password` 为空且没有查看器密码，因此任何人都可以浏览。

```bash
# 1. --config 优先于一切。文件缺失是一个错误。
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. 省略 --config 时，由 $FACET_CONFIG 提供默认路径（Docker 会设置它）。
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # 读取 /config/scoring_config.json
python facet.py --config other.json /photos   # --config 仍然优先

# 3. 两者都未设置：对命令行工具而言，工作目录中的配置优先。
cd /photos/client-shoot          # 目录中有自己的 scoring_config.json
python /opt/facet/facet.py .     # 按 /photos/client-shoot/scoring_config.json 评分

# 4. 两者都未设置，这里也没有：退回到安装目录旁边的配置。
cd /tmp
python /opt/facet/facet.py /photos   # 读取 /opt/facet/scoring_config.json
                                     # 那里也没有 ＝ 运行在随程序分发的默认值上

# 5. viewer.py 从不走工作目录这一步。
cd /photos/client-shoot          # 目录中有自己的 scoring_config.json——此处无关
python /opt/facet/viewer.py      # 仍然读取 /opt/facet/scoring_config.json（或 $FACET_CONFIG）
```

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --validate-categories` | 校验类别配置 |

## 标签标注

| 命令 | 说明 |
|---------|-------------|
| `python tag_existing.py` | 使用已存储的 CLIP 特征向量，为尚无标签的照片添加标签 |
| `python tag_existing.py --dry-run` | 预览标签但不保存 |
| `python tag_existing.py --threshold 0.25` | 自定义相似度阈值（默认：当前档位的 `tag_threshold_percent`，出厂值为 8，即 0.08） |
| `python tag_existing.py --max-tags 3` | 限制每张照片的标签数量（默认：5） |
| `python tag_existing.py --force` | 重新标注全部照片 |
| `python tag_existing.py --db custom.db` | 使用自定义数据库 |
| `python tag_existing.py --config my.json` | 使用自定义配置 |

在 CUDA 上，SigLIP 档位（`16gb`、`24gb`）现在以 fp16 编码标签词表，这会改变少数照片的标签。请运行 `python tag_existing.py --force` 重新标注之前打过标签的照片。CPU 以及 `legacy`/`8gb` 档位不受影响。

当 `tagging.enabled` 为 `false`，或没有任何照片在等待标签时，扫描结束时的标注步骤会被跳过。

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
| `python database.py` | 初始化或升级 schema，并构建缺失的索引（见说明） |
| `python database.py --info` | 显示 schema 信息 |
| `python database.py --migrate-tags` | 一次性建立标签查找表（标签筛选快 10-50 倍） |
| `python database.py --rebuild-fts` | 根据照片描述和标签重建全文搜索索引 |
| `python database.py --populate-vec` | 根据特征向量填充 sqlite-vec 向量搜索表 |
| `python database.py --refresh-stats` | 刷新统计缓存 |
| `python database.py --compact-config` | 从 `scoring_config.json` 中删除所有等于随程序分发的默认值的值（先做一份 `0600` 备份） |
| `python database.py --stats-info` | 显示缓存状态和时效 |
| `python database.py --vacuum` | 回收空间、整理碎片 |
| `python database.py --analyze` | 更新查询规划器统计信息 |
| `python database.py --optimize` | 运行 VACUUM 和 ANALYZE |
| `python database.py --backup` | 写入带时间戳、WAL 安全的快照（保留 `--keep N` 份，默认 3） |
| `python database.py --export-viewer-db` | 导出轻量的查看器数据库（无 BLOB、缩略图更小；增量） |
| `python database.py --export-viewer-db --force-export` | 强制完整重新导出 |
| `python database.py --cleanup-orphaned-persons` | 删除没有关联人脸的人物 |
| `python database.py --cleanup-missing-photos` | 删除磁盘上已不存在的照片，连同其标签、人脸和相册条目 |
| `python database.py --cleanup-missing-photos --dry-run` | 列出缺失的文件但不删除 |
| `python database.py --cleanup-missing-photos --force` | 即使全部照片看起来都缺失也继续执行（见警告） |
| `python database.py --relink-photos` | 更新你自行移动的照片的路径（默认仅预览）。参见[重新关联已移动的照片](#重新关联已移动的照片) |
| `python database.py --migrate-storage-fs` | 把缩略图和特征向量从数据库移到文件系统 |
| `python database.py --migrate-storage-db` | 把缩略图和特征向量从文件系统移回数据库 |
| `python database.py --add-user alice --role admin` | 添加用户（会提示输入密码） |
| `python database.py --add-user alice --role user --display-name "Alice"` | 添加带显示名称的用户 |
| `python database.py --migrate-user-preferences --user alice` | 把评分从 photos 复制到 user_preferences |

**`python database.py`** 还会构建缺失的图库索引（参见 [VIEWER.md](VIEWER.md#图库索引与计数缓存)）。在大型照片库上，请在启动查看器之前运行一次；可能需要约一分钟。否则查看器会在后台构建它们，并在此期间拒绝保存。

**`--migrate-tags`** 只需运行一次。此后，扫描、`--recompute-tags`、`--recompute-tags-vlm` 和 `tag_existing.py` 会使该表保持最新。在它被填充之前，标签筛选使用较慢的 `LIKE` 搜索。

**`--cleanup-missing-photos`** 还会清除向量索引，并重置自动重新训练的比较计数。训练好的模型、Immich 同步状态和百分位快照等照片库状态会保留。

> **警告：** 不加 `--force` 时，当全部照片看起来都缺失时，`--cleanup-missing-photos` 会停止，这通常意味着某个卷未挂载。请在加上 `--force` 之前检查挂载。

**性能提示：** 对于大型数据库（5 万张以上照片），请运行一次 `--migrate-tags`、`--rebuild-fts` 和 `--populate-vec`，之后不时运行 `--optimize`。

## 网页图库

| 命令 | 说明 |
|---------|-------------|
| `python viewer.py` | 在 http://localhost:5000 启动服务器（API ＋ Angular SPA） |
| `python viewer.py --port 5001` | 绑定其他端口（或设置 `PORT` 环境变量；默认 5000） |
| `python viewer.py --host 127.0.0.1` | 绑定指定网络接口（默认 `0.0.0.0`） |
| `python viewer.py --production` | 生产模式（uvicorn worker） |
| `python viewer.py --production --workers 4` | 生产模式并使用 N 个 worker（默认 1） |

## 命令行选片

无界面的自动选片：即查看器[自动选片](VIEWER.md#自动选片)的终端版本。淘汰结果会写入数据库。原始文件绝不会被移动或删除；`--copy-keepers` 会把保留下来的照片复制到一个文件夹。

| 命令 | 说明 |
|---------|-------------|
| `python facet.py --auto-cull [PATH]` | 对数据库中 `PATH`（文件夹或文件；省略或 `all` ＝ 整个照片库）下的照片选片。**默认是试运行** |
| `python facet.py /path --auto-cull` | 扫描 `/path`，然后对其下的照片选片 |
| `--apply` | 写入选片结果：淘汰、已复核分组标记和 `source='culling'` 比较对 |
| `--copy-keepers DIR` | 把范围内每张未被淘汰的照片，连同同名 RAW / `.xmp`，复制到 `DIR` |
| `--cull-strictness N` | 保留配额 0–100，越高每组保留得越少（默认：`auto_cull.default_strictness`） |
| `--cull-min-keep N` | 每组至少保留的照片数（默认 `1`） |
| `--cull-group-by {all,burst,similar,scene}` | 对哪些分组选片（默认 `all`） |
| `--cull-min-score X` | 同时淘汰综合评分低于 `X` 的独立照片 |
| `--cull-trim-brackets` | 同时淘汰多余的包围曝光帧（即查看器的 `trim_brackets`） |
| `--user NAME` | 使用谁的评分和淘汰；在多用户安装上**必须**指定 |

- **试运行。** 不加 `--apply` 时不会写入任何内容，也不会创建 `--copy-keepers` 文件夹。摘要会列出 `groups`、`kept`、`rejected_by_groups`、`rejected_by_score`、`spanning_skipped`，以及配合 `--copy-keepers` 时的 `keepers`、`copied`、`already_present`、`skipped`、`errors`（试运行中为 `would_reject_*` / `would_copy`）。`--dry-run` 本身会被拒绝。如果已训练的保留照片模型需要校正其权重，加载它时仍可能改写 `scoring_config.json`。
- **先扫描再选片**总是真实扫描；只有扫描完成后才会选片。它不能与 `--auto-cull PATH`、`--resume`、`--retry-failed` 或 `--watch` 组合使用。
- **规则。** 与[查看器的自动选片](VIEWER.md#自动选片)相同：每组保留最佳照片，外加严格程度容差范围内的所有照片，至少 `--cull-min-keep` 张。包围曝光、全景和 HDR 全景整组保留。`--apply` 会把保留的照片标记为**已保留**，并像 `POST /api/culling/auto` 一样记录比较对；不会填充精选相册。
- **配置。** [`auto_cull`](CONFIGURATION.md#自动选片)、`burst_scoring` 和 `similarity_groups` 设置来自**服务器**配置（`FACET_CONFIG` 或默认路径），而不是 `--config`。如果两者在多用户模式上不一致，命令会以退出码 1 退出。
- **范围**按本地真实路径匹配，因此在设置 `path_mapping` 之前存储的行无法按文件夹限定范围：请使用 `all` 或重新扫描。部分位于范围之外的连拍、包围曝光或全景会整组跳过（`spanning_skipped`）。相似和场景分组在范围之内计算。
- **`--cull-min-score`**（仅限命令行）绝不淘汰包围曝光或全景帧、未评分照片、收藏、已评星级或**已保留**的照片，也不会淘汰先前选片已判定过的照片，因此第二次运行不会再淘汰新的照片。它始终放过连拍成员。当分组找到相似分组的成员时，它会放过这些成员（它读取范围内最新的 `similarity_groups.max_photos` 张照片，默认 `10000`，并丢弃超过 `similarity_groups.max_group_size` 的分组，默认 `50`）。只有在 `--cull-group-by scene` 下才会放过场景分组的成员。
- **复制。** 被淘汰的照片及其配套文件绝不会被复制。来自不同文件夹的同名文件会加 `_1` 后缀；重新运行会跳过相同的文件（`already_present`）。`DIR` 不能是、不能包含，也不能位于范围、照片库或 Facet 扫描过的任何文件夹之内（退出码 1，试运行中同样检查）。文件必须位于扫描目录白名单之内（`users.*.directories` / `viewer.scan_directories`）；如果因此跳过了所有照片，命令以退出码 3 退出。
- **用户。** 在多用户安装上必须指定 `--user`（缺少它或用户未知则退出码 1）。在单用户安装上 `--user` 会被忽略并给出警告，即使设置了查看器密码，命令也能看到所有照片。`--apply` 会获取照片库锁；试运行不会。
- **用法错误（退出码 2）。** 没有 `--auto-cull` 而使用 `--apply`、`--copy-keepers` 或任何 `--cull-*`；`--auto-cull` 与 `--dry-run`、`--resume`、`--retry-failed` 或 `--watch` 同用；`--auto-cull PATH` 同时带有位置参数文件夹；严格程度超出 0–100；`--cull-min-keep` 小于 1。`--apply` 必须完整输入（它不再缩写 `--apply-recommendations`）。
- **退出码。** `0` 成功（包括试运行或零个分组）；`1` 前置条件、配置或数据库失败；`2` 用法错误；`75` 照片库锁被另一个任务持有；`3` 选片成功但复制出错或什么都没复制（所有保留照片都会被跳过的试运行同样以 `3` 退出）。
- **重新训练**不在命令行内运行。比较计数会保留，重新训练会在下一次查看器操作或 `--train-*` 命令时运行。首次运行可能会创建 `.facet_secret`。

## 常用工作流

### 初始设置
```bash
python facet.py /path/to/photos     # 为所有照片评分（自动多阶段）
python facet.py --cluster-faces-incremental # 人脸聚类
python database.py --migrate-tags    # 启用快速标签查询
python viewer.py                    # 查看结果
```

### 修改配置之后
```bash
python facet.py --recompute-average                # 用新权重更新所有评分
python facet.py --recompute-category portrait      # 只更新一个类别（更快）
```

### 人脸识别设置
```bash
python facet.py /path               # 扫描时提取人脸
python facet.py --cluster-faces-incremental     # 归并为人物
python facet.py --suggest-person-merges         # 查找重复
# 在网页图库中使用 /persons 进行合并／重命名
```

### 在终端中对一次拍摄选片
```bash
python facet.py --auto-cull /photos/wedding                     # 预览方案，不写入任何内容
python facet.py --auto-cull /photos/wedding --apply \
    --copy-keepers ~/wedding-keepers                             # 淘汰，然后复制保留下来的照片
python facet.py /photos/new-shoot --auto-cull --apply --cull-min-score 5   # 先扫描，再选片
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
python facet.py --compute-recommendations  # 检查分布
python facet.py --recompute-average        # 应用新权重
```

## 重新关联已移动的照片

自行移动文件后，`python database.py --relink-photos` 会预览旧路径 → 新路径的映射，并保留每张照片的数据库数据。默认只预览。

- **应用**需要已保存计划的 ID 和 `--acknowledge-unverified-identity`，因为 Facet 无法证明新文件就是原文件。请先停止查看器和扫描器，并审核计划。
- **会被拒绝的情况：**超出所配置根目录或用户可见范围的路径、副本、歧义名称、过期计划和路径映射。
- **配套文件**必须明确列出；类型包括用于 `photo.ext.facet.xmp` 的 `sidecar_facet`。手动画出的矩形需在编辑器中重新审核。Immich 状态保持不变。
- **计划**以私有方式保存（POSIX 上为 0600）。
- **挂载：**可读取的文件夹并不能证明卷已挂载，因此 `source_mount_status` 保持为 `not_verified`。请确认原文件是被移动了，而不是离线了。
- **退出码：**75 表示另一个任务持有照片库锁；1 表示锁不可用。预览不获取锁。

完整约定与示例参见[重新关联缺失的照片](RELINK.md)。
