# 评分系统

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · [Deutsch](../de/SCORING.md) · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md) · [Português](../pt/SCORING.md) · **简体中文**

照片先被归入某个类别，再按该类别的权重进行评分。

subject_sharpness、subject_prominence、subject_placement、bg_separation 和 face_quality_iqa 的缺失值或 NULL 不参与加权评分。仅当被排除指标的权重大于零时，才将其权重重新分配给可用指标；零仍是有效值。如果所有加权输入均缺失，则采用中性值 5.0。许可证排除规则优先适用。默认权重保持不变。当比较集中没有某个指标的任何值时，`--optimize-weights` 会保持该指标的权重不变。要补充显著性指标，请先运行 `--recompute-saliency`，再运行 `--recompute-average`。

## 评分的工作原理

1. **类别判定** - 分析照片内容（人脸、标签、EXIF 数据）
2. **筛选条件评估** - 按优先级顺序依次尝试类别，直到某一类别匹配（[拍摄场景评分方案](#拍摄场景评分方案)可以按相册或按照片改变这一顺序）
3. **权重应用** - 将该类别专属的权重应用到各项指标
4. **修正项应用** - 应用加分、扣分和行为开关
5. **最终评分** - 加权求和后钳制到 0-10 区间

## 类别

`scoring_config.json` 定义了 34 个类别（33 个具名类别加上 `default`），按优先级升序依次尝试，直到某一类别匹配。优先级数值越小越优先。完整列表见 `categories` 数组；主要类别如下：

| 优先级 | 类别 | 判定方式 |
|----------|----------|------------------|
| 8 | `art` | 标签：painting, statue, drawing, cartoon, anime |
| 10 | `astro` | 标签：aurora、astrophotography、stars、milky way，并且平均亮度 ≤ 0.30 |
| 15 | `concert` | 标签：concert |
| 35 | `group_portrait` | 人脸占比 ≥ 5% 且 is_group_portrait |
| 42 | `silhouette` | 含有人脸 且 `is_silhouette`（最大的人脸偏暗，而周围环境更亮） |
| 45 | `portrait` | 人脸占比 ≥ 5%，且非剪影／合影／黑白 |
| 46 | `portrait_bw` | 黑白人像（人脸 ≥ 5%） |
| 55 | `macro` | 标签：macro, insect, butterfly, dewdrop, ... |
| 65 | `wildlife` | 标签：animal, bird, marine, reptile, primate |
| 80 | `long_exposure` | 快门 1-10 秒 |
| 85 | `night` | 亮度 < 0.15 |
| 88 | `monochrome` | is_monochrome（饱和度 < 5%） |
| 95 | `street` | 标签：street, urban_culture |
| 96 | `human_others` | 含有人脸 且 人脸占比 < 5% |
| 100 | `landscape` | 标签：landscape, mountain, beach, forest, ... |
| 999 | `default` | 兜底类别（无筛选条件） |

其他基于标签的类别还包括 `aerial`、`food`、`sports`、`vehicle`、`travel`、`fashion`、`candid`、`product`、`architecture`、`urban`、`golden_hour`、`blue_hour`、`cinematic`、`vintage`、`abstract`、`minimalist`、`dramatic` 和 `weather`。

在使用 CLIP 打标签的配置档上（`legacy`/`8gb`，以及其 VLM 标签器不运行时的 `16gb`/`24gb`），扫描会在计算每张照片的类别之前先为其打标签，因此存储的类别会用到这些标签。只带单个 `--pass NAME` 的运行不打标签。

**剪影。** `is_silhouette` 来自一条基于人脸的像素规则（参见[布尔筛选条件](#布尔筛选条件)），不是来自标签。

- 当 `exposure.silhouette_detection` 为 `true`（默认）时，剪影的综合评分会跳过溢出裁切扣分。
- 扫描存储的 `exposure_score` 带有溢出裁切扣分。`--recompute-average` 会对每张标记为 `is_silhouette` 的照片去掉该扣分重新计算，无论 `exposure.silhouette_detection` 取何值。
- 要重新推导已有照片库的标志，请运行 `python facet.py --recompute-silhouette`，然后运行两次 `--recompute-average`（参见 [COMMANDS.md](COMMANDS.md)）。

**星空。** 照片需要有星空标签，*并且*平均亮度不超过 0.30（`luminance_max`）。被标为 `aurora` 或 `stars` 的明亮场景不属于星空，而没有存储亮度的照片永远不匹配。如果你的 `scoring_config.json` 有自己的 `categories` 数组，请自行把 `"luminance_max": 0.30` 加入 `astro.filters`；缺少它时，`python facet.py --doctor` 会告诉你。

## 拍摄场景评分方案

**拍摄场景评分方案**会改变部分照片的类别顺序，而不触动全局优先级。它把少数类别提升到最前面，并排除另一些类别。`default`（`promote`／`excluded` 均为空）不改变任何内容，除非你指派其他方案，否则照片都使用它。

**实际判断顺序** = `promote`（按给定顺序）→ 全局优先顺序中去掉已提升和已排除的名称 → `default` 排在最后。同时出现在 `promote` 和 `excluded` 中的名称会被丢弃：`excluded` 优先。

随附的预设方案，可在查看器的**拍摄场景评分方案**选项卡中编辑，也可直接改 JSON（字段参考：[拍摄场景评分方案](CONFIGURATION.md#拍摄场景评分方案)）：

| 方案 | 优先判断 | 排除 |
|---------|----------|----------|
| `default` | — | — |
| `action_stage` | `sports`、`concert`、`candid` | `silhouette` |
| `party_event` | `group_portrait`、`candid`、`food` | — |
| `portrait_session` | `portrait`、`portrait_bw`、`fashion` | — |
| `wildlife` | `wildlife` | — |
| `landscape` | `landscape`、`golden_hour`、`blue_hour` | — |
| `motorsport` | `sports`、`vehicle` | `silhouette` |

你只编辑已提升的列表（编辑模式；拖动，或上移／下移）和排除项。其他类别始终保持全局顺序，因此新增的类别绝不会在某个方案中被漏掉。验证规则见[编辑方案](CONFIGURATION.md#编辑方案)。

**指派方案：**

- **按相册。** 应用到当前属于该相册的每一张照片。这是一次性快照：之后加入智能相册的照片不会获得它。参见[指派方案](CONFIGURATION.md#拍摄场景评分方案)。
- **按照片。** 针对单张照片的持久类别覆盖。

两者都能在重新扫描后保留，并且可以分别清除。

**在重新计算之前，两者都不会对已评分的照片生效：**请运行 `python facet.py --recompute-average`，或在查看器中重新计算（参见[调整优先级需要重新计算](CONFIGURATION.md#调整全局优先级顺序)）。如果启用了 `normalization.per_category`，请运行两次（参见[归一化](CONFIGURATION.md#归一化)）。

### 缺失 EXIF 数据的陷阱

重新排序只会改变哪个类别被*先尝试*，无法让某个类别的筛选条件匹配上。照片的值缺失或无法读取时，数值范围筛选条件会失败，与超出范围完全一样。

举个例子：`sports`（优先级 71）带有 `shutter_speed_max: 0.02`。一张快门慢于 1/50 秒拍摄的舞蹈照片，或者读不到快门时间的照片，即使 `action_stage` 把 `sports` 提到最前面也过不了这个筛选条件。它会继续往下匹配，通常落到 `fashion`（优先级 43，带 `fashion` 标签，含有人脸）或 `silhouette`（优先级 42，逆光且含有人脸）。

**当一张照片被归入意料之外的类别时，请先检查这一点：**目标类别的数值筛选条件能否匹配这张照片存储的 EXIF，而不仅仅是它的标签？

### 标签缺失的陷阱

`required_tags` 也会以同样的方式失败：筛选条件无法匹配词表中不存在的标签。`sports` 的 `required_tags` 是 `sports`、`motion`、`athlete`、`competition`、`action_sport` 和 `dance`。

`sports.tags.dance` 带有 11 条 CLIP 提示词（`dance performance`、`dancer on stage`、`ballet dancer`、`contemporary dance`、`ballroom dancing`、`latin dance`、`hip hop dance`、`dance competition`、`dance troupe performing`、`dancer mid leap`、`dancer in motion`），并且 `dance` 在 `sports.filters.required_tags` 中。带有舞蹈标签的照片可以到达 `sports`，但慢门或缺少 EXIF 的照片仍会在 `shutter_speed_max: 0.02` 上失败。

**已有照片仍保留它们原有的标签。**词表变更只影响新的打标签；运行 `python facet.py --recompute-tags` 可将其应用到整个照片库。

### 调整全局优先级顺序

你可以在查看器中（编辑模式）调整全局优先级顺序。调整是在类别之间交换现有的优先级数值，而不是重新编号，因此上表中的数字依然有意义。`default`（优先级 999）始终排在最后。每次写入都会先为 `scoring_config.json` 生成一份带时间戳的 `.backup.<timestamp>` 副本。

调整顺序不会改动任何照片已存储的 `category`：之后请运行一次重新计算。

**已知限制：**图库的类型下拉列表会保持旧的排列顺序，直到查看器重启。匹配和筛选会立即使用新顺序。

## 类别定义

`scoring_config.json` 中的每个类别都包含以下部分：

```json
{
  "name": "portrait",
  "priority": 45,
  "filters": {
    "face_ratio_min": 0.05,
    "has_face": true,
    "is_silhouette": false,
    "is_group_portrait": false,
    "is_monochrome": false
  },
  "weights": {
    "aesthetic_percent": 32,
    "eye_sharpness_percent": 16,
    "face_quality_percent": 14,
    "composition_percent": 12,
    "liqe_percent": 8,
    "exposure_percent": 4,
    "tech_sharpness_percent": 4,
    "color_percent": 4,
    "contrast_percent": 4,
    "aesthetic_iaa_percent": 2
  },
  "modifiers": {
    "bonus": 0.419,
    "_apply_blink_penalty": true,
    "noise_tolerance_multiplier": 0.006,
    "_clipping_multiplier": 0.5
  },
  "tags": {}
}
```

## 筛选条件参考

### 数值范围筛选条件

| 筛选条件 | 字段 | 说明 |
|--------|-------|-------------|
| `face_ratio_min` / `face_ratio_max` | `face_ratio` | 人脸面积占比（0.0-1.0） |
| `face_count_min` / `face_count_max` | `face_count` | 人脸数量 |
| `iso_min` / `iso_max` | `ISO` | 相机 ISO |
| `shutter_speed_min` / `shutter_speed_max` | `shutter_speed` | 曝光时间（秒） |
| `luminance_min` / `luminance_max` | `mean_luminance` | 亮度（0.0-1.0） |
| `focal_length_min` / `focal_length_max` | `focal_length` | 焦距（毫米） |
| `f_stop_min` / `f_stop_max` | `f_stop` | 光圈 f 值 |

### 布尔筛选条件

| 筛选条件 | 说明 |
|--------|-------------|
| `has_face` | 至少检测到一张人脸 |
| `is_monochrome` | 饱和度 < 5% |
| `is_silhouette` | 最大的人脸偏暗而其周围环境明亮（见下文）。没有人脸的照片永远不是剪影 |
| `is_group_portrait` | face_count >= `min_faces_for_group`（可配置，默认为 4） |
**`is_silhouette` 规则。**人脸框中央 60 % 的平均亮度（luma，0-1）低于 0.12，且框外围的环带（在每一侧向外延伸框尺寸的 0.2 至 0.75 倍，裁到画面范围内）亮出 0.20 以上。CLIP 的 `silhouette` 标签和整幅画面的直方图都不会设置它。

### 标签筛选条件

| 筛选条件 | 说明 |
|--------|-------------|
| `required_tags` | 照片必须具备的标签列表 |
| `excluded_tags` | 照片**不得**具备的标签列表 |
| `tag_match_mode` | `"any"`（默认）或 `"all"` |

## 权重键

所有权重都使用 `_percent` 后缀。`get_weights()` 会对它们做归一化，因此合计不必正好等于 100 — 但保持在 100 可以让评分维持在 0-10 区间。

| 键 | 指标 | 来源 | 适用场景 |
|-----|--------|--------|----------|
| `aesthetic_percent` | 视觉美感 | TOPIQ 或 CLIP+MLP | 全部 |
| `quality_percent` | 旧版画质 | 计算前并入 `aesthetic_percent`（没有独立信号） | — |
| `face_quality_percent` | 面部清晰程度 | InsightFace | 人像 |
| `eye_sharpness_percent` | 眼睛清晰度 | InsightFace 关键点 | 人像 |
| `tech_sharpness_percent` | 整体清晰度 | 拉普拉斯方差 | 风光 |
| `composition_percent` | 构图 | SAMP-Net 或基于规则的算法 | 全部 |
| `exposure_percent` | 曝光平衡 | 直方图分析 | 全部 |
| `color_percent` | 色彩和谐度 | HSV 分析 | 彩色照片 |
| `contrast_percent` | 影调对比 | 直方图分布 | 黑白 |
| `dynamic_range_percent` | 影调范围 | 直方图分析 | HDR、风光 |
| `isolation_percent` | 主体与背景的分离 | 人脸与背景对比 | 人像、野生动物 |
| `leading_lines_percent` | 引导线 | 边缘检测 | 建筑 |
| `power_point_percent` | 三分法 | 主体位置 | 全部 |
| `saturation_percent` | 色彩饱和度 | HSV 分析 | 色彩鲜艳的照片 |
| `noise_percent` | 噪点水平 | 噪点估计 | 弱光 |
| `face_sharpness_percent` | 人脸区域清晰度 | 人脸分析 | 人像 |
| `aesthetic_iaa_percent` | 艺术美学水准 | TOPIQ IAA（基于 AVA 训练） | 艺术、创意 |
| `face_quality_iqa_percent` | 人脸画质（IQA） | TOPIQ NR-Face | 人像 |
| `liqe_percent` | LIQE 画质评分 | LIQE | 诊断 |
| `subject_sharpness_percent` | 主体区域清晰度 | BiRefNet + 拉普拉斯 | 人像、野生动物 |
| `subject_prominence_percent` | 主体面积占比 | BiRefNet | 微距、野生动物 |
| `subject_placement_percent` | 主体三分法 | BiRefNet | 全部 |
| `bg_separation_percent` | 背景分离度 | BiRefNet | 人像、微距 |

**`quality_percent` 按 `aesthetic` 计算。** 画质指标没有独立评分，因此类别的 `quality_percent` 会并入 `aesthetic`：它在计算前加到 `aesthetic_percent` 上，权重总和仍为 100。早期版本丢失了综合评分中的这一份；升级后运行一次 `--recompute-average` 即可补回。类别不会改变。

## 修正项

按类别调整评分行为：

| 修正项 | 类型 | 说明 |
|----------|------|-------------|
| `bonus` | float | 加到最终评分上（例如 0.5） |
| `noise_tolerance_multiplier` | float | 缩放噪点扣分（0.5 表示减半） |
| `_skip_clipping_penalty` | bool | 不因曝光溢出扣分 |
| `_skip_oversaturation_penalty` | bool | 不因过饱和扣分 |
| `_clipping_multiplier` | float | 缩放溢出扣分 |
| `_apply_blink_penalty` | bool | 启用闭眼检测扣分 |

## 主体显著性维度

由 BiRefNet 主体分割衍生出的四个维度：

| 权重键 | 指标 | 说明 |
|-----------|--------|-------------|
| `subject_sharpness_percent` | 主体清晰度 | 主体区域相对背景的对焦质量。数值高 = 主体锐利、背景柔和。 |
| `subject_prominence_percent` | 主体突出程度 | 主体面积占画面的比例。微距和构图紧凑的主体数值高，大场景数值低。 |
| `subject_placement_percent` | 主体位置 | 主体重心的三分法评分。 |
| `bg_separation_percent` | 背景分离度 | 主体边界处的边缘梯度差异（焦外成像质量）。 |

人像／野生动物题材可使用 `subject_sharpness_percent` 和 `bg_separation_percent`；微距题材可使用 `subject_prominence_percent`。

**没有主体就没有数值。** 找不到主体时，`subject_sharpness`、`subject_placement` 和 `bg_separation` 存为 NULL（没有主体框时 `power_point_score` 也一样），`subject_prominence` 为 0.0，`subject_bbox` 为 NULL。

- 图库的范围筛选会跳过 NULL（`min_subject_sharpness=0` 不会返回没有主体的照片）。统计数据在计算平均值时不计入它，界面显示为缺失。
- NULL 显著性输入遵循上文的缺失值规则；默认权重保持不变。
- 早期版本存的是中性的 5.0。已有的行保留它，直到 `--recompute-saliency` 和 `--recompute-composition-cpu` 将其重写。

**显著性失败时**，不会写入任何内容；Facet 绝不会为失败的结果存入中性数值。从未评分的照片，其五个显著性列（`subject_sharpness`、`subject_prominence`、`subject_placement`、`bg_separation`、`subject_bbox`）保持 NULL，与显著性功能出现之前扫描的照片一样。重试和批大小规则见[主体显著性](COMMANDS.md#主体显著性)。

## 补充 IQA 维度

三个额外的画质模型：

| 权重键 | 模型 | 说明 |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | 基于 AVA 训练的美学水准，区别于偏技术画质的美观度评分。最适合艺术／创意类别。 |
| `face_quality_iqa_percent` | TOPIQ NR-Face | 人脸区域的画质评估。最适合人像类别。 |
| `liqe_percent` | LIQE | 画质评分外加失真诊断（运动模糊、过曝、噪点）。 |

这些模型在每个配置档上都作为默认评分流程的一部分运行，包括 CPU 的 `legacy` 配置档（那里更慢），并在 GPU 上与 TOPIQ 共享显存。凡是这类评估有用的类别，都可以把它们的权重键加进去。

**补充模型无法为照片评分时**，会在该模型对应的列（`face_quality_iqa`、`liqe_score`、`aesthetic_iaa`、`aesthetic_v25`）中存入 NULL，而不是中性的 5.0。TOPIQ NR-Face 找不到人脸，或 LIQE 的短边小于 224 px 时会出现这种情况；Aesthetic V2.5（启用时）可能对任何图片失败。CPU 内存错误不会以更小的批大小重试。

- face_quality_iqa 为 NULL 时遵循上文的缺失值规则；其他补充指标的 NULL 输入仍使用中性值 5.0。
- **图库：**对美学（IAA）、人脸画质（IQA）、LIQE 或 Aesthetic V2.5 的范围筛选不会匹配没有评分的照片（`min_face_quality_iqa=0` 会跳过没有人脸的照片）。按这些列、Q-ReAlign 或 DeQA 升序排序时，没有评分的照片排在最后，图库和相册中都是如此。
- **旧的中性 5.0 值**会保留，直到 `--repair-neutral-iqa` 将其清除；之后运行 `--recompute-iqa` 和 `--recompute-average`，或用 `--force` 重新扫描。
- **主画质模型失败**（`16gb` 与 `24gb` 上的 TOPIQ）：该照片会被记为失败，而不是以中性的 5.0 保存。新照片会在下次扫描时重新处理；已存储的照片保留其原有记录，可由 `--retry-failed all`（不带参数的 `--retry-failed` 只覆盖最近一次记录了失败的运行）或再次 `--force` 重新扫描来重试。

各命令的重试规则见[补充画质模型](COMMANDS.md#补充画质模型)。

### 补充信号（不计入默认综合评分）

| 列 | 来源 | 说明 |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + 已缓存的 CLIP/SigLIP 特征向量 | 来自缓存特征向量的零成本美观度评分（0-10）；**不**计入默认的 `aggregate` |

`aesthetic_clip` 把每张图像的特征向量投影到由文本提示词构建的“美学轴”上，因此不需要任何额外的图像推理。

- 用 `python scripts/compute_aesthetic_clip.py --db <path>` 填充。
- 用 `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` 做基准测试。
- 在 500 张照片的 `ava_test/` 集合上，AVA SRCC ≈ 0.52（`aesthetic_iaa` 为 0.94）。可用作低成本的预筛选，或在 TOPIQ-IAA 不可用时使用。

## 类别标签（CLIP 词表）

标签用于触发基于标签的类别，通过 CLIP 相似度进行匹配：

```json
{
  "tags": {
    "landscape": ["landscape", "scenic view", "nature scene"],
    "mountain": ["mountain", "alpine", "peaks"],
    "beach": ["beach", "ocean", "seaside", "coastal"]
  }
}
```

每个键是标准标签名，数组中则是供 CLIP 匹配使用的同义词。

## 精选照片评分

查看器的“精选照片”筛选使用一套自定义的加权评分：

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**评分计算方式：**
- 含有人脸（face_ratio ≥ 20%）：四项指标全部参与
- 不含人脸：`face_quality_percent` 均分（各一半）到 `aesthetic` 和 `composition`（按默认权重即：美观度 0.40、构图 0.30）

## VRAM 配置档考量

默认权重是针对 **TOPIQ**（0.93 SRCC）优化的，它是所有配置档使用的美观度模型。

| 配置档 | 美观度模型 | 特征向量 | 标签模型 | 建议 |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ（0.93 SRCC） | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | 精度最佳，使用默认权重 |
| `16gb` | TOPIQ（0.93 SRCC） | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | 使用默认权重 |
| `8gb` | CLIP+MLP（0.76 SRCC） | CLIP ViT-L-14 | CLIP 相似度 | 默认权重效果良好 |
| `legacy` | CPU 上的 CLIP+MLP | CLIP ViT-L-14 | CLIP 相似度 | 使用默认权重，速度较慢 |

所有配置档，包括 CPU 的 `legacy` 配置档，还会额外运行补充的 PyIQA 模型（TOPIQ IAA、TOPIQ NR-Face、LIQE），并可选运行 BiRefNet_dynamic 计算主体显著性。

切换配置档后运行 `--compute-recommendations` 以分析评分分布。

## 权重调优流程

### 方案 A：通过查看器（推荐）

1. 打开 `/stats` → **类别**选项卡 → **权重**子选项卡
2. 解锁编辑模式
3. 在编辑器下拉菜单中选择一个类别
4. 调整滑块 — 实时的**评分分布预览**会显示预计影响
5. 点击**保存**，再点击**重新计算评分**使其生效

查看器在后台运行 `--recompute-category`，只更新该类别下的照片。

MCP 助手可以读取这些权重并试算更改，而不会改动任何内容：`explain_score`（照片为何得到该评分）、`category_weights` 与 `preview_weights`（带排名变化的近似预览）。参见[评分与权重](AGENTS.md#评分与权重)。

### 方案 B：通过命令行

#### 1. 分析当前评分

```bash
python facet.py --compute-recommendations
```

输出内容：
- 各类别的评分分布
- 权重相关性分析
- 建议的调整

#### 2. 调整权重

编辑 `scoring_config.json` 中的类别权重，确保合计为 100。

#### 3. 重新计算评分

```bash
python facet.py --recompute-average               # 全部类别
python facet.py --recompute-category portrait      # 单个类别（更快）
```

使用已存储的特征向量 - 无需 GPU。

#### 4. 验证变更

```bash
python facet.py --compute-recommendations
```

对比调整前后的分布。

## 成对比较模式

通过两两比较照片来训练权重：

### 准备工作

1. 在配置中设置一个非空的 `edition_password`：`"viewer": { "edition_password": "your-password" }`
2. 启动查看器：`python viewer.py`
3. 点击“比较”按钮

### 比较界面

- 并排显示两张照片
- 快捷键：←（左边更好）、→（右边更好）、T（平局）、S（跳过）。屏幕上的按钮标注为 **A** / **B**。
- 进度条显示已完成的比较次数，最少需要 50 次

### 比较来源

每次比较都带有 `source` 标记，供优化器按可靠性对其加权：

- `vote` — 来自比较界面的显式 A/B 投票
- `culling` — 从连拍／相似照片的选片决定中自动衍生：每张被
  淘汰的照片会与同组中最多两张保留的照片配成对
  （每组最多 12 对）。保留的照片胜出。同一照片对上的显式
  投票绝不会被覆盖。
- `rating` — 由星级和收藏生成的合成照片对

因此，在查看器中复核连拍分组，就能不费额外功夫地
扩充权重优化的训练集。

### 权重优化

```bash
# 查看比较统计
python facet.py --comparison-stats

# 从比较结果优化权重（只有在能够泛化时才会应用）
python facet.py --optimize-weights --optimize-category portrait

# 将训练数据限定为特定来源
python facet.py --optimize-weights --optimize-category portrait --optimize-sources vote,culling

# 即使未达到留出验证门槛也强制应用
python facet.py --optimize-weights --optimize-category portrait --optimize-force

# 应用到全部照片
python facet.py --recompute-average
```

### 从标注到权重的流程

除了显式的 A/B 投票，还有另外两条标注流会喂给优化器：

1. **选片决定**会在每次确认连拍／相似分组时自动记录
   （`source='culling'`）。
2. **星级、收藏和淘汰标记**通过 `python facet.py --sync-label-comparisons`
   物化为合成照片对（`source='rating'`）。
   重新运行会按当前标注重新同步，因此撤销掉的星级也会随之消失。

优化器拟合的是最能预测每次比较中哪张照片获胜的权重（Bradley-Terry 模型）。

- 各来源按可靠性计数：vote 1.0、rating 0.7、culling 0.5。
- **平局**算作半胜加半负。
- 拟合**锚定在你当前的权重上**：比较很少时，结果会贴近这些权重。
- 它使用与综合评分相同的 0-10 指标（包括 `liqe`、`aesthetic_iaa`、`face_quality_iqa` 和主体显著性），其中眼部清晰度、技术清晰度和色彩按上一次 `--recompute-average` 保存的百分位归一化。
- `quality_percent` 像评分器那样折入 `aesthetic`；应用时会写入 `quality_percent: 0`。

**权重只有在能够泛化时才会应用。**是否写入取决于留出的比较：5 折交叉验证，且**折按照片分组**（任何一张照片都不会同时出现在训练对和留出对中）。

- **单侧精确 McNemar 检验**考察：在两组权重意见不一致的配对中，新权重是否显著赢得更多。
- 只有当 `p < 0.05` **并且**留出增益至少为 2 个百分点时才会应用权重。否则本次运行记录这些数字而不写入任何内容。
- 传入 `--optimize-force` 可强制应用。如果检验无法运行（相互独立的照片组太少），除非强制，否则什么也不应用。
- 每个类别需要在**该类别中**至少 30 次**决定性**比较（一方获胜）。平局和其他类别的比较不计入。

日志示例：

```
Held-out accuracy:      69.2% +/- 4.0 (5-fold, photo-grouped) - the honest estimate
Held-out gain:          +8.5 pp over the current weights on the same 389 pairs
McNemar (one-sided):    p = 0.0006 (only the fit right: 66, only the current weights right: 33)
NOT applying: the held-out gate needs p < 0.05 and a gain of at least 2.0 pp. ...   (logged when the gate fails)
```

**应用时保持该类别的整体水平。** `--optimize-weights` 改变的是类别内部各照片之间的排序，而不是该类别相对其他类别的位置。它会调整 `modifiers.bonus`，抵消该类别平均得分的偏移。

- bonus 被限制在 [-5, 5]；达到该限制时，日志会说明。
- 在 `categories` 中没有条目的类别（`others`）没有 bonus，也不会重新居中。
- 恢复权重快照会同时恢复权重**和** bonus。较早的快照、由 `calibrate.py` 记录的快照以及属于 `others` 的快照保持 bonus 不变。
- 查看器的**应用**按钮和“权重”选项卡中的手动编辑不会重新居中 bonus；只有 `--optimize-weights` 会。

**升级之后，请重新训练个人排序器和 keeper 头（`--train-ranker`、`--train-keeper`），然后运行 `--recompute-average`。**它们现在读取按百分位归一化的眼部清晰度、技术清晰度和色彩，早期版本保存的模型无法察觉这一变化。

建议的执行节奏：

```bash
python facet.py --mine-insights          # 存在哪些信号、是否漂移、整体健康度
python facet.py --sync-label-comparisons # 刷新由星级衍生的照片对
python facet.py --optimize-weights       # 从所有来源学习权重
python facet.py --recompute-average      # 应用并持久化百分位快照
```

### 界面内权重调优

在比较过程中，权重预览面板会在你移动滑块时显示评分变化，**建议权重**则会给出优化后的取值。保存和重新计算的方式与[方案 A：通过查看器](#方案-a通过查看器推荐)相同。

**建议权重**会显示两个数字，位于“权重建议”选项卡和 A/B 比较选项卡的侧边栏中：

- `accuracy_before`：当前权重正确预测出该类别带标签的配对中胜者的比例。
- `accuracy_after`：建议权重的同一数字。它是在拟合所用的配对上测得的，所以偏乐观。

只有当与 CLI 相同的留出 McNemar 检验通过时（`suggest_changes` 为真），才会提供**应用**。仅当偏乐观的增益达到 2 个百分点时才会运行交叉验证（`?use_cv=true` 在任何情况下都会运行）。查看器需要该类别有 `min_comparisons_for_optimization`（默认 50）次决定性比较，而 CLI 只需要 30 次。不足时会报告“Need at least N decisive comparisons (have K)”。

## 添加自定义类别

```json
{
  "name": "underwater",
  "priority": 62,
  "filters": {
    "required_tags": ["underwater"],
    "tag_match_mode": "any"
  },
  "weights": {
    "aesthetic_percent": 40,
    "color_percent": 25,
    "composition_percent": 20,
    "exposure_percent": 15
  },
  "modifiers": {
    "noise_tolerance_multiplier": 0.3,
    "bonus": 0.5
  },
  "tags": {
    "underwater": ["underwater", "scuba", "diving", "ocean"],
    "fish": ["fish", "coral", "reef"]
  }
}
```

把它加入 `scoring_config.json` 的 `categories` 数组，然后运行 `--recompute-average`（若只处理新类别，可用 `--recompute-category underwater`）。

## 流程示例

### 调整演唱会类别

```bash
# 编辑 scoring_config.json：
# 找到 "concert" 类别，调整：
#   "noise_tolerance_multiplier": 0.05
#   "exposure_percent": 5

python facet.py --recompute-category concert
```

也可以使用查看器中 `/stats` → 类别 → 权重 处的权重编辑器，支持实时预览和一键重新计算。

### 切换到 8gb 配置档

```bash
# 编辑："vram_profile": "8gb"
python facet.py --compute-recommendations  # 分析
# 如有需要，降低各类别中的 aesthetic_percent
python facet.py --recompute-average
```

### 添加水下摄影类别

1. 添加类别定义（见上文）
2. 运行 `python facet.py --validate-categories`
3. 运行 `python facet.py --recompute-average`
