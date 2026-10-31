# 配置参考

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · [Português](../pt/CONFIGURATION.md) · **简体中文**

每一项设置都随 `config/scoring_config.default.json` 一起发布。你自己的 `scoring_config.json` 逐键覆盖它 — 参见[默认值与你的覆盖配置](#默认值与你的覆盖配置)。修改之后请运行 `python facet.py --recompute-average` 更新评分（无需 GPU）。

## 目录

- [默认值与你的覆盖配置](#默认值与你的覆盖配置)
- [用户](#用户)
- [扫描](#扫描)
- [类别](#类别)
- [拍摄场景评分方案](#拍摄场景评分方案)
- [评分](#评分)
- [阈值](#阈值)
- [构图](#构图)
- [EXIF 调整](#exif-调整)
- [曝光](#曝光)
- [扣分项](#扣分项)
- [归一化](#归一化)
- [模型](#模型)
- [画质评估模型](#画质评估模型)
- [处理](#处理)
- [RAW 解码](#raw-解码)
- [HDR PQ 色调映射](#hdr-pq-色调映射)
- [连拍检测](#连拍检测)
- [连拍评分](#连拍评分)
- [重复照片检测](#重复照片检测)
- [人脸检测](#人脸检测)
- [人脸聚类](#人脸聚类)
- [人脸处理](#人脸处理)
- [单色检测](#单色检测)
- [标签](#标签)
- [独立标签](#独立标签)
- [分析](#分析)
- [查看器](#查看器)
- [性能](#性能)
- [存储](#存储)
- [插件](#插件)
- [照片胶囊](#照片胶囊)
- [相似照片分组](#相似照片分组)
- [场景](#场景)
- [OCR](#ocr)
- [时间线](#时间线)
- [地图](#地图)
- [翻译](#翻译)

---

## 默认值与你的覆盖配置

`scoring_config.json` 里**只保存你改动过的内容**。Facet 会把它叠加在 `config/scoring_config.default.json` 之上解析，因此凡是你没有写出来的键，都保持随附的值。全新安装没有 `scoring_config.json`，完全依靠默认值运行。

若只想提高人像的美学权重并设置一个编辑密码，整个文件就是：

```json
{
  "viewer": { "edition_password": "your-password" },
  "categories": [ ... ]
}
```

两个文件的合并方式：

- **对象逐键合并。** `{"performance": {"mmap_size_mb": 4096}}` 只改动这一项设置；`cache_size_mb` 以及其他所有 `performance` 键都保持随附的值。
- **数组整体替换。** 你文件里的 `categories` 数组会完整替换随附的那一份。顺序很重要（`categories` 以“首次匹配即生效”的方式求值，`scoring_contexts.*.promote` 按书写顺序读取），而且你从数组中省略的类别就等于被删除。

若只想改动某个类别中的一项权重，请把整个 `categories` 数组从 `config/scoring_config.default.json` 中复制出来，编辑后保留在你的文件里。

### 升级已有安装

无需任何操作：来自旧版本的完整 `scoring_config.json` 仍然照常工作。Facet 对该文件的任何写入（在查看器中保存权重或优先级、全景阈值的改动、把明文密码升级为哈希的首次登录、`validate_weights` 修正了权重的扫描）都会把它重写为覆盖配置，并丢弃所有与随附默认值相同的键。

若要按需精简，并先做一份 `0600` 权限的备份副本：

```bash
python database.py --compact-config
```

精简的结果解析出的配置完全相同。

> **注意：** 与随附默认值相同的值不会留在你的文件里。如果日后某个版本改动了那个默认值，你的行为也会随之改变。若要固定某个值，它必须与默认值不同。

## 用户

可选的多用户模式。当 `users` 键中至少有一个用户时，逐用户登录会取代单密码认证。

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

### 用户字段

| 字段 | 类型 | 说明 |
|-------|------|-------------|
| `password_hash` | string | PBKDF2-HMAC-SHA256 哈希（`salt_hex:dk_hex`），由 `--add-user` 生成 |
| `display_name` | string | 显示在界面顶栏 |
| `role` | string | `user`、`admin` 或 `superadmin` |
| `directories` | array | 该用户的私有照片目录（匹配方式参见[共享目录](#共享目录)） |

### 共享目录

`shared_directories`（与用户对象同级）列出每个用户都能看到的目录。`directories` 与 `shared_directories` 中的条目会与扫描器存储的路径比较：

- 在 Windows 和 macOS 上，以及任何主机上的 UNC 或盘符条目，会忽略 ASCII 大小写。
- 其他情况（例如 Linux）区分大小写：请完全按扫描器存储的写法填写每个条目。
- 不处理：非 ASCII 的大小写差异，以及主机无法解析的映射驱动器。
- 空白条目不授予任何访问权限。

### 角色

| 角色 | 查看自有 + 共享 | 评分/收藏 | 管理人物/人脸 | 触发扫描 |
|------|:-:|:-:|:-:|:-:|
| `user` | 是 | 是 | 否 | 否 |
| `admin` | 是 | 是 | 是 | 否 |
| `superadmin` | 是 | 是 | 是 | 是 |

### 添加用户

用户只能通过命令行创建；没有注册界面，也没有对应的 API：

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# 提示输入密码，并把哈希写入 scoring_config.json
```

然后编辑 `scoring_config.json` 来设置他们的 `directories`。

### 向后兼容

- 没有 `users` 键 = 单用户模式（行为不变）。
- 多用户模式下会忽略 `viewer.password` 和 `viewer.edition_password`。
- `photos` 表中已有的星级仍供单用户模式使用；`--migrate-user-preferences` 会把它们复制过去。

---

## 扫描

控制扫描会访问哪些目录。

```json
{
  "scanning": {
    "skip_hidden_directories": true,
    "skip_directories": ["@eaDir", "#recycle", "#snapshot", "@Recycle"]
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | 跳过名称以 `.` 开头的目录 |
| `skip_directories` | `["@eaDir", "#recycle", "#snapshot", "@Recycle"]` | 在任意深度被跳过的文件夹名通配符 |

关于 `skip_directories`：
- 通配符使用 `fnmatch`，区分大小写，且只匹配文件夹名。
- 默认值涵盖 Synology 的 `@eaDir`（其 `SYNOPHOTO_THUMB_*.jpg` 缩略图）、`#recycle`、`#snapshot` 以及 QNAP 的 `@Recycle`。
- 你的列表会替换默认值；`[]` 表示不按名称跳过。扫描根目录永远不会被跳过。
- 已从这些文件夹索引的照片会保留在数据库中。

---

## 类别

类别定义的数组。完整的类别指南见[评分](SCORING.md)。

每个类别包含：
- `name` - 类别标识符
- `priority` - 数值越小优先级越高（越先求值）
- `filters` - 匹配条件
- `weights` - 各项评分指标的权重（总和必须为 100）
- `modifiers` - 行为调整项
- `tags` - 用于按标签匹配的 CLIP 词表

> **形式与色彩和谐权重。** 每个类别的 `weights` 都有五个由 `--recompute-form` 填充的键：`symmetry_percent`、`balance_percent`、`edge_entropy_percent`、`fractal_percent` 和 `color_harmony_percent`。它们出厂值为 `0`，因此在你给其中某一项赋予权重之前，评分不会改变（赋权之后请运行 `--recompute-average`）。权重总和仍为 100。

> **`quality_percent` 按 `aesthetic` 计算。** 画质没有独立评分，因此 `quality_percent` 会在计算前并入 `aesthetic_percent`。参见 [SCORING.md](SCORING.md)。

> **内置的 `astro` 类别要求画面偏暗。** 除了其中一个标签外，它还要求 `luminance_max: 0.30`（平均亮度不高于 0.30），因此被标为 `aurora` 或 `stars` 的明亮场景不属于 `astro`。如果你的 `scoring_config.json` 带有自己的 `categories` 数组，其中的 `astro` 条目不会获得这个过滤条件：请在 `astro.filters` 中加入 `"luminance_max": 0.30`，或删除该数组。当 `astro` 没有 `luminance_max` 时，`python facet.py --doctor` 会打印一条 “Config notice”。然后运行 `--recompute-average`（升级后：先运行 `--recompute-silhouette`，再运行两次 `--recompute-average`；参见 [COMMANDS.md](COMMANDS.md)）。

---

## 拍摄场景评分方案

拍摄场景评分方案可以改变某个相册或某张照片最终由哪个类别胜出。它把少数类别提到全局 `categories` 顺序的最前面，并排除另一些类别；其余的保持原有的优先级顺序。当全局顺序为某次拍摄选错了类别时就可以用它：一张被打上 `sports` 标签的逆光舞蹈照片，会被 `silhouette`（优先级 42）先于 `sports`（优先级 71）截获。权重滑块解决不了这一点，因为它们只改变*已选中*的类别如何评分。

```json
{
  "scoring_contexts": {
    "default": {
      "label_key": "comparison.context.default",
      "promote": [],
      "excluded": [],
      "suggest_from_moments": []
    },
    "action_stage": {
      "label_key": "comparison.context.action_stage",
      "promote": ["sports", "concert", "candid"],
      "excluded": ["silhouette"],
      "suggest_from_moments": ["sports", "concert", "nightlife"]
    }
  }
}
```

| 字段 | 说明 |
|-------|-------------|
| `label_key` | 该方案显示名称的 i18n 键 |
| `promote` | 按给定顺序移到求值序列最前面的类别 |
| `excluded` | 在此方案下永不匹配的类别 |
| `suggest_from_moments` | 为相册推荐此方案的 `narrative_moment` 取值（`GET /api/albums/{id}/suggested_context`，见 [VIEWER.md](VIEWER.md)） |

**实际顺序** = `promote`（按顺序）→ 去掉已提升和已排除名称的全局优先级顺序 → 最后是 `default`（兜底类别，优先级 999）。

- 同时出现在 `promote` 和 `excluded` 中的名称会被排除。
- `default` 永远不能被提升或排除。
- 不传方案、或传入未知方案名，都使用纯粹的全局顺序（未知名称会记录一条警告）。
- `python facet.py --validate-categories` 会报告未知的类别名、同时出现在两个列表中的名称，以及不是 `narrative_moments.event_types.<default_event_type>` 键的 `suggest_from_moments` 条目。否则这些拼写错误只会悄无声息地失效。

随附的预设（`default` 为空，因此在你指派方案之前不会有任何改变）：

| 方案 | 提升 | 排除 | 由时刻推荐 |
|---------|----------|----------|------------------------|
| `default` | — | — | — |
| `action_stage` | `sports`、`concert`、`candid` | `silhouette` | `sports`、`concert`、`nightlife` |
| `party_event` | `group_portrait`、`candid`、`food` | — | `celebration`、`group_gathering`、`dining` |
| `portrait_session` | `portrait`、`portrait_bw`、`fashion` | — | `portrait`、`children` |
| `wildlife` | `wildlife` | — | `nature_wildlife`、`pets` |
| `landscape` | `landscape`、`golden_hour`、`blue_hour` | — | `scenic_landscape`、`mountains`、`snow_winter` |
| `motorsport` | `sports`、`vehicle` | `silhouette` | `sports`、`road_vehicle` |

### 添加自定义方案

在 `scoring_contexts` 下加一个键，它就和随附的预设一样可用：你可以把它指派给相册，并在**拍摄场景评分方案**标签页中编辑。

```json
{
  "scoring_contexts": {
    "dance_comp": {
      "label_key": "comparison.context.dance_comp",
      "promote": ["sports", "concert"],
      "excluded": ["silhouette", "fashion"],
      "suggest_from_moments": ["sports"]
    }
  }
}
```

如果 `label_key` 没有翻译，选择器会显示方案自身的 **`name`**（例如 `dance_comp`）。把该键加到全部六个 `i18n/translations/*.json` 语言包中，就能得到本地化的标签。

### 编辑方案

在查看器的**拍摄场景评分方案**标签页中（受编辑权限限制，`PUT /api/config/scoring_contexts/{name}`），把类别拖动或移动到提升列表中，点击某个类别切换其排除状态，然后保存。

- 只有 `promote` 和 `excluded` 可编辑；`label_key`、`suggest_from_moments` 以及其他方案会原样保留。
- 当方案不存在、某个条目不是已有类别、`default` 出现在任一列表中，或 `promote` 中重复出现同一名称时，保存会被拒绝。同一名称同时出现在两个列表中会被接受（`excluded` 胜出）；`excluded` 内部的重复项会被合并。
- 每次保存都会保留一份带时间戳的 `.backup.<timestamp>` 配置副本。
- 编辑方案不会重新归类照片：之后请运行一次重新计算（见[调整优先级需要重新计算](#调整全局优先级顺序)）。标签页里有一个**立即重新计算**按钮。

### 指派方案

拍摄场景评分方案是**按相册**指派的，通过 `PUT /api/albums/{id}/scoring_context`（受编辑权限限制）完成。

- 它会应用到当下属于该相册的每张照片，但你手动设置过方案的照片除外。
- 之后加入手动相册的照片会继承该方案。后来匹配智能相册筛选条件的新照片则不会；请再次调用 `PUT` 重新应用。
- 智能相册使用其保存的筛选条件，而不是照片库的隐藏开关，因此它涵盖的照片可能比它的照片库视图显示的更多。
- `DELETE /api/albums/{id}/scoring_context` 会从该相册设置过方案的照片上移除该方案。手动选择保持不变。
- 从相册中移除照片（`DELETE /api/albums/{id}/photos`）会移除这些照片上该相册的方案。仍在另一个带方案的相册中的照片，会采用那个相册的方案。
- `GET /api/albums/{id}/suggested_context` 会根据相册中占主导的 `narrative_moment`，通过 `suggest_from_moments` 推荐一个方案。它不会改动任何内容。

对于个别顽固的照片，请使用**类别覆盖**：`POST /api/comparison/override_category`（受编辑权限限制）直接设定类别，`POST /api/comparison/clear_category_override` 则将其移除。覆盖的优先级高于任何方案。

覆盖和方案在重扫后依然保留。无论用什么方案，只要其 EXIF 值缺失，数值型筛选条件仍然不成立 — 见[评分 — 缺失 EXIF 的陷阱](SCORING.md#缺失-exif-数据的陷阱)。

### 调整全局优先级顺序

`GET|POST /api/config/category_priorities`（受编辑权限限制）读取并保存所有方案据以出发的全局顺序。查看器会重新排列现有的优先级数值，而不是重新编号。

- `default`（优先级 999）始终排在最后，不能移动。
- 优先级缺失或重复的类别，在保存时会被赋予一个超过当前最大值的新值。
- 每次保存都会保留一份带时间戳的 `scoring_config.json` `.backup.<timestamp>` 副本；只保留最近的 20 份。

**调整优先级需要重新计算。** 重排不会改动任何照片已存储的 `category`。请运行 `python facet.py --recompute-average`，或从查看器启动 `POST /api/scan/recompute`（受编辑权限限制）并跟踪 `GET /api/scan/recompute_status`。

- 重新计算与扫描不能同时运行：命令行会拒绝，查看器则会报告是哪个作业占用了照片库。
- 从终端启动的两次扫描只会得到警告（`--resume` 会拒绝）。
- 启用 `normalization.per_category` 时，重新计算可能需要运行两次 — 参见[归一化](#归一化)。

---

## 评分

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `score_min` | `0.0` | 可能的最低分 |
| `score_max` | `10.0` | 可能的最高分 |
| `score_precision` | `2` | 评分保留的小数位数 |

---

## 阈值

评分阈值。现在只剩 `blink_penalty_percent`。一张照片是不是人像、夜景或长曝光，由各类别的 `filters` 决定（参见[类别](#类别)），而不是由这个块决定。

```json
{
  "thresholds": {
    "blink_penalty_percent": 50
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `blink_penalty_percent` | `50` | 检测到闭眼时的评分乘数（0.5 倍） |

---

## 构图

基于规则的构图评分（SAMP-Net 未启用时使用）。

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `power_point_weight` | `2.0` | 三分法构图点位置的权重 |
| `line_weight` | `1.0` | 引导线的权重 |

---

## EXIF 调整

依据相机设置自动进行的评分调整。

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `iso_sharpness_compensation` | `true` | 减轻高 ISO 的清晰度扣分 |
| `aperture_isolation_boost` | `true` | 为大光圈（f/1.4-f/2.8）提升主体分离度 |

---

## 曝光

控制曝光分析与溢出检测。

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `shadow_clip_threshold_percent` | `15` | 纯黑像素 > 15% 时标记 |
| `highlight_clip_threshold_percent` | `10` | 纯白像素 > 10% 时标记 |
| `silhouette_detection` | `true` | 为 `true` 时，被标记为 `is_silhouette` 的照片在综合评分中跳过溢出裁切扣分。该标志本身不可配置：它来自一条基于人脸的固定规则（参见 [SCORING.md](SCORING.md)） |

---

## 扣分项

针对技术问题的评分扣减。

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_penalty_points": 0.5
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | 噪点高于此值即触发扣分 |
| `noise_max_penalty_points` | `1.5` | 噪点扣分的上限 |
| `noise_penalty_per_sigma` | `0.3` | 超出阈值每个 sigma 扣的分数 |
| `leading_lines_blend_percent` | `30` | 混入 comp_score 的比例 |
| `oversaturation_threshold` | `0.9` | 平均饱和度阈值 |
| `oversaturation_penalty_points` | `0.5` | 过饱和扣分 |

**噪点扣分公式：**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## 归一化

控制原始指标如何被缩放到 0-10 分。

```json
{
  "normalization": {
    "method": "percentile",
    "percentile_target": 90,
    "per_category": true,
    "category_min_samples": 50
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `method` | `"percentile"` | 归一化方法 |
| `percentile_target` | `90` | 第 90 百分位 = 10.0 分 |
| `per_category` | `true` | 按类别分别归一化 |
| `category_min_samples` | `50` | 启用按类别归一化所需的最少照片数 |

> **注意：** 启用 `per_category` 时，单跑一次重新计算不会稳定下来。百分位是按每张照片*已存储*的类别分组的，而重新计算会随后才重新指派类别。在任何会让照片在类别之间移动的改动（优先级、拍摄场景评分方案、类别覆盖）之后，请运行两次 `--recompute-average`。

---

## 模型

选择每个显存配置档所使用的模型。

```json
{
  "models": {
    "vram_profile": "auto",
    "keep_in_ram": "auto",
    "profiles": {
      "legacy": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CPU: CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (8GB+ RAM; saliency/IQA are slower on CPU)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (6-14GB VRAM)"
      },
      "16gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-2b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-2B tagging (~14GB VRAM)"
      },
      "24gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-4b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-4B tagging (~18GB VRAM)"
      }
    },
    "clip": {
      "model_name": "google/siglip2-so400m-patch16-naflex",
      "backend": "transformers",
      "embedding_dim": 1152,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 5
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 15
    },
    "qwen2_vl": {
      "model_path": "Qwen/Qwen2-VL-2B-Instruct",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 256
    },
    "qwen3_5_2b": {
      "model_path": "Qwen/Qwen3.5-2B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 4
    },
    "qwen3_5_4b": {
      "model_path": "Qwen/Qwen3.5-4B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 2
    },
    "saliency": {
      "model": "ZhengPeng7/BiRefNet_dynamic",
      "resolution": 1024,
      "mask_threshold": 0.3,
      "min_subject_pixels": 50
    },
    "samp_net": {
      "model_path": "pretrained_models/samp_net.pth"
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `vram_profile` | `"auto"` | 生效的配置档（`auto`、`legacy`、`8gb`、`16gb`、`24gb`）；`FACET_VRAM_PROFILE` 可覆盖它（见下文） |
| `keep_in_ram` | `"auto"` | 在多遍处理的各分块之间把模型留在内存中（`"auto"`、`"always"`、`"never"`）；`auto` 会先检查可用内存 |
| `ram_cache_reserve_gb` | `4.0`（可选，随附文件中没有） | 在 `"auto"` 下，缓存一个模型时要为主机留出的可用内存（GB） |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | 本配置档要运行的 PyIQA 模型（四个配置档都运行完整集合） |
| `profiles.*.saliency_enabled` | `true`（所有配置档） | 本配置档是否运行 BiRefNet 主体显著性 |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | SigLIP 2 NaFlex 嵌入模型（16gb/24gb） |
| `clip.backend` | `"transformers"` | `"transformers"`（SigLIP 2 NaFlex）或 `"open_clip"`（旧版） |
| `clip.embedding_dim` | `1152` | 嵌入维度（SigLIP 2 为 1152） |
| `clip.tag_threshold_percent` | `8` | 16gb/24gb 的 SigLIP 2 标签器判定**标签**匹配所需的最低相似度（取代 `similarity_threshold_percent`） |
| `clip.search_threshold_percent` | `5` | 语义搜索（`GET /api/search`）所需的最低相似度；取 `0-50` 的整数 |
| `clip_legacy.model_name` | `"ViT-L-14"` | 旧版 CLIP 模型（legacy/8gb 配置档） |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | 旧版预训练权重 |
| `clip_legacy.embedding_dim` | `768` | 旧版嵌入维度 |
| `clip_legacy.tag_threshold_percent` | `8` | legacy/8gb 的 CLIP 标签器使用同样的标签门槛；`tagging.max_tags` 限制标签数量 |
| `clip_legacy.search_threshold_percent` | `15` | legacy/8gb 配置档的语义搜索门槛；取 `0-50` 的整数 |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | 手动选用 `composition_model: "qwen2-vl-2b"` 时使用的模型（没有配置档使用它） |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | 16gb 配置档的标签模型 |
| `qwen3_5_2b.vlm_batch_size` | `4` | 每个 VLM 推理批次的图片数 |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | 24gb 配置档的标签模型 |
| `qwen3_5_4b.vlm_batch_size` | `2` | 每个 VLM 推理批次的图片数 |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | BiRefNet 显著性模型 |
| `saliency.resolution` | `1024` | 推理分辨率 |
| `saliency.mask_threshold` | `0.3` | 二值主体掩膜的 sigmoid 阈值 |
| `saliency.min_subject_pixels` | `50` | 判定检测到主体所需的最少主体像素数 |

说明：
- **`ram_cache_reserve_gb`：** 仅当可用内存大于模型大小加上此预留量时，模型才会留在内存中。`"always"` 跳过该检查；`"never"` 不缓存任何内容。它必须是 >= 0 的数字，否则扫描会在启动时终止。在内存压力下，缓存会先释放最晚才会再用到的模型（见[多遍处理的工作方式](#多遍处理的工作方式)）。
- **标签阈值与搜索阈值：** `tag_threshold_percent` 控制打标签（扫描、`--recompute-tags`、`tag_existing.py`）。`search_threshold_percent` 是照片库 0-50% 搜索滑块的默认值（`/api/config` 中的 `search_threshold_default`）。SigLIP 的默认值 `5` 偏向召回：在 34 张照片的样本上，它保留了全部 21 个真实匹配，同时放过了 13 个非匹配中的 3 个。

**语义搜索与在不同配置档下建立索引的照片库：** `GET /api/search` 会根据与*已存储*嵌入维度匹配的 `clip` / `clip_legacy` 来选择文本编码器及其 `search_threshold_percent`，而不是当前生效的 `vram_profile`。因此，用 768 维 CLIP 建立索引、却在 16gb 机器上浏览的照片库，会使用 `clip_legacy` 搜索。如果已存储的维度与两个配置块都不匹配，则使用当前生效配置档的配置块。

### 显存自动检测

当 `vram_profile` 为 `"auto"`（默认）时，Facet 会在启动时检测 GPU 显存，并选择放得下的最大配置档：

| 检测到的显存 | 选中的配置档 |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| 无 GPU | `legacy`（使用系统内存） |

只有当 PyTorch 能看到 CUDA GPU 时它才算数。没有可见设备时（例如 `CUDA_VISIBLE_DEVICES=''`），扫描改用 CPU，报告 0 GB 显存并选择 `legacy`。没有可见设备时设置 `FACET_DEVICE=cuda`，会以 “FACET_DEVICE=cuda was requested, but that device is not available” 中止。

**10-14GB 的显卡可以自行启用完整功能集。** 自动检测在低于 14GB 时仍会选择 `8gb`。设置 `"vram_profile": "16gb"` 或 `FACET_VRAM_PROFILE=16gb` 即可运行 SigLIP 2、TOPIQ、Qwen3.5-2B 标签、Q-ReAlign 和显著性。此时各模型分四个遍次运行，显卡报告 11.8 GiB 或更多时为三个（见[动态遍次分组](#动态遍次分组)）。显著性仍无法评分的照片会存入 NULL 并记录一条 ERROR。

> **警告：** 把已有的 `8gb` 照片库切换到 `16gb` 会更换嵌入模型（CLIP ViT-L-14 的 768 维 → SigLIP 2 的 1152 维）。请重新扫描或运行 `--recompute-embeddings`，否则照片库里会混入两种嵌入维度。在此之前搜索的行为见[模型](#模型)一节中的*语义搜索与在不同配置档下建立索引的照片库*。

### `FACET_VRAM_PROFILE` 环境变量覆盖

`FACET_VRAM_PROFILE` 会在加载时覆盖 `models.vram_profile`，因此一份挂载进去的配置就能服务于每个 Docker 配置档。可接受的取值：`auto`、`legacy`、`8gb`、`16gb`、`24gb`；其他取值会被忽略并给出警告。Docker Compose 覆盖文件（`docker-compose.{legacy,8gb,16gb,24gb}.yml`）已经替你设置好了它。

这项覆盖绝不会被写回 `scoring_config.json`。你在文件里自己设置的 `vram_profile` 在变量未设置时依然生效。

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

---

## 画质评估模型

通过 [pyiqa](https://github.com/chaofengc/IQA-PyTorch) 库选择为图像画质/美学打分的模型。

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `model` | `"auto"` | 画质模型：`auto`、`topiq`、`hyperiqa`、`dbcnn`、`musiq`、`clip-mlp`。`auto` 使用 `topiq`。 |
| `prefer_llm` | `false` | 在有基于 LLM 的评分器可用时优先使用它 |

### 可用的画质模型

SRCC = 在 KonIQ-10k 基准上的斯皮尔曼等级相关系数（1.0 = 完美）。

| 模型 | SRCC | 显存 | 备注 |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | 默认（`auto`）；带自顶向下注意力的 ResNet50 主干 |
| `hyperiqa` | 0.90 | ~2GB | 超网络，随内容自适应 |
| `dbcnn` | 0.90 | ~2GB | 双分支 CNN（合成失真 + 真实失真） |
| `musiq` | 0.87 | ~2GB | 多尺度 transformer；可处理任意分辨率 |
| `clipiqa+` | 0.86 | ~4GB | 带习得画质提示词的 CLIP |
| `clip-mlp` | 0.76 | ~4GB | 旧版 CLIP ViT-L-14 + MLP 头 |

### 切换画质模型

1. 编辑 `scoring_config.json`：
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. 重新为已有照片评分（可选）：
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## 处理

GPU 批处理与多遍模式的设置。

```json
{
  "processing": {
    "mode": "auto",
    "gpu_batch_size": 16,
    "ram_chunk_size": 32,
    "num_workers": 4,
    "auto_tuning": {
      "enabled": true,
      "monitor_interval_seconds": 5,
      "tuning_interval_images": 32,
      "min_processing_workers": 1,
      "max_processing_workers": 32,
      "min_gpu_batch_size": 2,
      "max_gpu_batch_size": 32,
      "min_ram_chunk_size": 10,
      "max_ram_chunk_size": 128,
      "memory_limit_percent": 85,
      "cpu_target_percent": 85,
      "metrics_print_interval_seconds": 30
    },
    "thumbnails": {
      "photo_size": 640,
      "photo_quality": 80,
      "face_padding_ratio": 0.3
    }
  }
}
```

### 核心概念

- **`gpu_batch_size`**：在一次 GPU 前向传播中一起处理的图片数。受显存限制；GPU 显存超出限制时，自动调优会将其下调。
- **`ram_chunk_size`**：在两次模型遍次之间保存在内存中的图片数（仅多遍模式），这样每个分块中每张图片只从磁盘读取一次。受 `memory_limit_percent` 限制。占用超过上限时自动调优会立即下调，只有在整个分块的*峰值*占用都低于上限之后才会上调。

### 设置参考

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `mode` | `"auto"` | 处理模式：`auto`、`multi-pass`、`single-pass`。只有 `single-pass` 会选择单遍；`auto` 始终以多遍运行 |
| `gpu_batch_size` | `16` | 每个 GPU 批次的图片数（受显存限制） |
| `ram_chunk_size` | `32` | 每个内存分块的图片数（多遍模式） |
| `num_workers` | `4` | 图片加载线程数 |
| `load_workers` | `num_workers` | 多遍模式分块加载线程数（上限 8，`1` = 顺序执行） |
| `raw_decode_concurrency` | `0`（自动） | 同时进行的 RAW 解码数上限；按 CPU/内存自动取值（1-4），`1` = 完全串行 |
| `raw_decode_timeout_seconds` | `120` | 超过该延时就放弃卡住的 RAW 解码（`0` = 禁用）；反复卡住后扫描会快速失败 |
| `exif_prefetch` | `true` | 单遍模式：在后台预取 EXIF，而不是阻塞 GPU 线程 |
| **auto_tuning** | | |
| `enabled` | `true` | 启用自动调优 |
| `monitor_interval_seconds` | `5` | 资源检查间隔 |
| `tuning_interval_images` | `32` | 每 N 张图片重新调优一次 |
| `min_processing_workers` | `1` | 加载线程数下限 |
| `max_processing_workers` | `32` | 加载线程数上限 |
| `min_gpu_batch_size` | `2` | GPU 批大小下限 |
| `max_gpu_batch_size` | `32` | GPU 批大小上限 |
| `min_ram_chunk_size` | `10` | 内存分块大小下限 |
| `max_ram_chunk_size` | `128` | 内存分块大小上限 |
| `memory_limit_percent` | `85` | 有效内存上限的百分比（在容器限额下取 cgroup 限额，否则取宿主机内存） |
| `cpu_target_percent` | `85` | CPU 占用目标 |
| `metrics_print_interval_seconds` | `30` | 统计信息打印间隔 |
| **thumbnails** | | |
| `photo_size` | `640` | 存储的缩略图尺寸（像素） |
| `photo_quality` | `80` | 缩略图 JPEG 质量 |
| `face_padding_ratio` | `0.3` | 人脸裁切周围的留白比例 |

### 处理模式

| 模式 | 说明 |
|------|-------------|
| `auto` | 始终以多遍运行（默认）；只有 `single-pass` 会选择单遍 |
| `multi-pass` | 顺序加载模型（显存有限时可用） |
| `single-pass` | 一次加载全部模型（需要大显存）；仅适用于 `legacy`/`8gb` 配置档 |

在 `16gb`/`24gb`（美学使用 TOPIQ）上，`single-pass` 会记录警告并以多遍运行，商业模式除外（参见[许可](#许可licensing)）。

### 多遍处理的工作方式

多遍模式不是一次加载全部模型，而是：

1. 按内存分块加载图片（`ram_chunk_size` 默认为 32）
2. 对每个分块顺序运行各模型：加载模型 → 处理分块 → 卸载模型
3. 在最后的聚合遍次中合并结果

每张图片在每个分块中只解码一次并由所有遍次共享。各遍次会按可用显存分组，因此较大的 VLM 即使在小显存的显卡上也能运行。

- 加载线程还会计算 EXIF、技术指标、基于规则的构图、感知哈希，以及 pyiqa 模型与 Q-ReAlign 共用的 1024 px 副本。
- 构图出错只会让那一张照片失败。它会以 `composition` 阶段记入 `scan_failures`；用 `--retry-failed` 重试。
- 在 CUDA GPU 上，当主机可用内存允许且 `keep_in_ram` 不是 `"never"` 时，一个分块会在下一批模型加载期间解码。否则（在 CPU 和 Apple MPS 上则总是如此）先解码。两种方式的结果完全相同。
- 在某个分块之前内存不足时，内存缓存会先释放最晚才会再用到的模型，并保持 `ram_cache_reserve_gb` 的空闲量。
- 扫描摘要会报告 `Plane rebuilds`、`I/O wait (scan thread blocked on decode)` 和 `Decode wall`。

### 自动调优行为

Facet 会监控资源占用并据此调整。`memory_limit_percent` 是相对*有效*内存上限来衡量的：在容器限额（Docker `mem_limit`、Podman `--memory`、Kubernetes `resources.limits.memory`）下取 cgroup 限额，否则取宿主机内存。因此在 8GB 限额下的 `85` 约为 6.8GB。

| 指标 | 动作 |
|--------|--------|
| GPU 显存 > 上限 | 把 `gpu_batch_size` 下调 25% |
| 内存占用 > 上限 | 把 `ram_chunk_size` 下调 25%（立即） |
| 某个完成的分块峰值占用始终 <（上限 - 20%） | 把 `ram_chunk_size` 上调 25% |
| CPU > 目标 | 建议减少工作线程 |
| 队列超时 > 5% | 建议增加工作线程 |

### 动态遍次分组

显存允许时，多个模型会在同一遍次中运行：

| 显存 | 第 1 遍 | 第 2 遍 | 第 3 遍 | 第 4 遍 |
|---|---|---|---|---|
| 8GB（`8gb` 配置档） | CLIP | Q-ReAlign + 显著性 | TOPIQ IAA + TOPIQ NR-Face + LIQE | SAMP-Net + InsightFace |
| 12GB\*（`16gb` 配置档，需手动启用） | Qwen3.5 标签 VLM + Q-ReAlign | SigLIP + 显著性 + TOPIQ IAA | TOPIQ + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace |
| 16GB（`16gb` 配置档） | Qwen3.5 标签 VLM + SigLIP + TOPIQ | Q-ReAlign + 显著性 + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace | - |
| 24GB（`24gb` 配置档） | Qwen3.5 4B 标签 VLM + SigLIP + Q-ReAlign + 显著性 | TOPIQ + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace | - | - |
| 35GB+（`24gb` 配置档） | 所有模型一起（单遍） | - | - | - |

这几行是显卡报告总显存分别为 8.0、11.7、15.99 和 23.99 GiB 时的分组；报告 34.8 GiB 或更多时只规划一遍。规划器会留出 1.3 GiB 给 CUDA、ONNX Runtime 和桌面。12GB 显卡不会被自动选中（见[显存自动检测](#显存自动检测)）：请设置 `"vram_profile": "16gb"` 或 `FACET_VRAM_PROFILE=16gb`。

\* 12GB 一行是报告 11.7 GiB 的显卡的分组。报告 11.8 GiB 或更多（例如 11.99 GiB）的显卡则规划三遍：Qwen3.5 标签 VLM + Q-ReAlign；SigLIP + 显著性 + TOPIQ；TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace。

### 命令行选项

```bash
# 默认：自动多遍，并采用最优分组
python facet.py /path/to/photos

# 强制单遍（一次加载全部模型；仅限 legacy/8gb 配置档，16gb/24gb 会警告并以多遍运行）
python facet.py /path --single-pass

# 只运行指定的遍次
python facet.py /path --pass quality       # 仅 TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA（美学价值）
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE（画质 + 失真）
python facet.py /path --pass tags          # 仅已配置的标签模型
python facet.py /path --pass composition   # 仅 SAMP-Net
python facet.py /path --pass faces         # 仅 InsightFace
python facet.py /path --pass embeddings    # 仅 CLIP/SigLIP 嵌入
python facet.py /path --pass saliency      # BiRefNet 主体显著性

# 列出可用模型
python facet.py --list-models
```

---

## RAW 解码

RAW 文件如何被转换成像素。Facet 使用两套配置档：

- **指标配置档**：所有评分据以计算的去马赛克（也是人脸框以及 `image_width`/`image_height` 所处的像素空间）。整个图库使用一个固定的曝光增益，不做逐帧自适应。
- **显示配置档**：存储的缩略图、照片库和 `/image` 所展示的内容。它优先采用相机内嵌的预览图（机身自身的色调曲线和曝光），并回退到指标配置档的去马赛克结果。

```json
"raw_decode": {
  "bright": 1.62,
  "prefer_embedded_preview": true,
  "preview_min_sensor_ratio": 0.5,
  "viewer_concurrency": 3,
  "faithful_bracket_render": true
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `bright` | `1.62` | 施加于每一次去马赛克的固定曝光增益（`1.0` = LibRaw 自身的电平；`1.62` ≈ darktable 的 +0.7 EV） |
| `prefer_embedded_preview` | `true` | 有相机预览图时显示它；设为 `false` 则一律去马赛克（更慢，且没有相机的色调曲线） |
| `preview_min_sensor_ratio` | `0.5` | 预览图必须覆盖的传感器比例，`/image` 才会使用它而不去马赛克 |
| `viewer_concurrency` | `3` | 查看器 `/image` 与 `/thumbnail` 同时进行的 RAW 去马赛克数上限，独立于 `processing.raw_decode_concurrency` |
| `faithful_bracket_render` | `true` | 显示包围曝光照片时完全不做校正（无预览、无 `bright` 增益）；见[下文](#包围曝光照片按未校正方式渲染) |

说明：
- `bright` 是这里唯一一个任意常数。在大批量扫描之前，请用 `--check-raw-rendering` 在你的图库上验证它。
- 尼康、宾得、三星和佳能 CR3 内嵌接近全尺寸的预览（0.98-0.99）。松下为 0.52。奥林巴斯、富士、索尼和 DNG 内嵌的预览很小（0.29-0.49），因此会去马赛克。

### 内存取舍

`viewer_concurrency` 与 `processing.raw_decode_concurrency` 是两份独立的预算。最坏情况下两者同时运行，每次去马赛克的峰值大约在 200-400MB。在内存吃紧的主机上请调低 `viewer_concurrency`。实际上只有索尼、富士、奥林巴斯和 DNG 文件会用到查看器的预算，因为其他机身的预览已经足够大。

### 为什么没有自动亮度

LibRaw 的自动亮度会逐帧自适应，所以一组包围曝光的每一帧最终亮度大致相同。固定增益则保留了各帧之间真实的曝光阶梯。

调高 `bright` 会提亮每一次渲染。曝光指标也会随之变化：改动之后请重新运行 `--recompute-average`，并重新扫描以改写这些指标本身。

### 包围曝光照片按未校正方式渲染

`sequence_kind` 为 `bracket` 或 `hdr_panorama` 的照片在显示时既没有相机预览，也没有 `bright` 增益。这两项都会压缩你在包围曝光中要判断的高光。普通的 `panorama` 不受影响。

适用范围：
- `/image`（详情视图、比较放大镜、选片放大镜），即时渲染。
- 照片库图块和比较网格，在 `--refresh-thumbnails` 之后。
- `type=original` 的 `GET /api/download`。

不受影响：`type=raw`（未改动的 RAW）、`type=darktable`（已修图外观的导出）、`GET /api/photo/cull_preview`（由 darktable-cli 渲染）以及评分。

序列检测在扫描之后才运行，所以请先运行 `--detect-sequences`，再运行 `--refresh-thumbnails`，图块才会跟上。

把 `faithful_bracket_render` 设为 `false`，即可把包围曝光照片当作普通照片渲染。

### 迁移在此配置档之前扫描的图库

缩略图和直方图是在扫描时存储的，因此改动配置档并不会改变已扫描的照片。`photos.render_version` 记录了每张存储的缩略图是由哪种渲染产生的：

- `NULL`：早于这个标记
- `1`：优先使用相机预览，去马赛克回退路径上施加 `bright` 增益（每次扫描存储的结果）
- `2`：既无预览也无增益，用于包围曝光中的一帧（只有 `--refresh-thumbnails` 会存储它）

只有两种途径会更新已存储的缩略图：
- **重新扫描**会改写缩略图和直方图，并且总是标记为 `1`。
- **`--refresh-thumbnails`** 会改写 RAW 缩略图，并按当前的 `sequence_kind` 标记为 `1` 或 `2`。它会重建每一行，因此在改动 `bright` 或跑完 `--detect-sequences` 之后请再运行一次。

详情视图（`/image`）始终是最新的；照片库网格只有在上述两种途径之一之后才会改变。

照片库会显示一条可关闭的横幅，统计仍停留在旧渲染上的照片数。它最多可能滞后一小时；`python database.py --refresh-stats` 会立即更新它。

若渲染结果整幅全黑（例如被严重截断的松下 RW2），则会被拒绝，连同文件名一起记入日志，并在后续运行中重试。

---

## HDR PQ 色调映射

佳能 HDR PQ 静态照片（`.HIF`）在 BT.2020 原色之上携带 PQ 传递函数（SMPTE ST 2084），亮度最高可达 10,000 尼特。质量模型与缩略图需要 8-bit SDR sRGB，因此 Facet 会按相机的原生位深解码 PQ 图像，转换到 sRGB 并做色调映射。本段控制这一色调映射。

它**仅**作用于 NCLX 色彩配置声明为 PQ 传递函数（特征值 16）的图像。无论 `enabled` 为何，SDR HEIF、HLG 与 JPEG 都原样透传。旋转过的帧（EXIF 方向不为 1）会以正立方向输出，包括原生位深路径：在 pillow-heif 1.6 及以上版本中，像素平面会在色调映射前转正。

```json
"hdr_pq_tonemap": {
  "enabled": true,
  "method": "hable",
  "white_point": {
    "mode": "percentile",
    "percentile": 99.99,
    "min_nits": 100.0,
    "max_nits": 1200.0,
    "fixed_nits": 1000.0
  },
  "chroma_preserve": "per_channel"
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 把 PQ 图像色调映射到 SDR；设为 `false` 会让它们偏暗发灰（仅用于调试） |
| `method` | `hable` | 色调曲线：`hable`（胶片感，与 ffmpeg 的 `tonemap` 滤镜相同）或 `clip`（线性加硬钳，仅作对照） |
| `white_point.mode` | `percentile` | 逐图白场的确定方式：`percentile`、`max`（最亮像素）或 `fixed`（`fixed_nits`） |
| `white_point.percentile` | `99.99` | `percentile` 模式使用的百分位 |
| `white_point.min_nits` | `100.0` | 白场下限；暗帧绝不会被归一化到 SDR 参考白以下 |
| `white_point.max_nits` | `1200.0` | `percentile` 模式的上限；限制异常明亮的帧把曲线下压的程度 |
| `white_point.fixed_nits` | `1000.0` | `fixed` 模式使用的白场 |
| `chroma_preserve` | `per_channel` | `per_channel`（更亮，高光处色相略有偏移）或 `max_channel`（保持色相，略暗） |

`max` 模式下，夜景里的一个热像素会把整帧压暗；`percentile` 可避免这一点。

### 为什么白场逐图确定

固定的 100 尼特白场会把所有更亮的像素钳成纯白，而真实 HDR 静态照片的峰值往往在数百到数千尼特。Facet 改为按逐图白场归一化，与 ffmpeg（`vf_tonemap.c`）一致。默认的 p99.99 百分位（钳制在 100-1200 尼特）既能保留高光纹理，又能忽略孤立的热像素。

### 为何按相机原生位深解码

在色调映射之前就把 PQ 解码成 8 bit，会让平滑渐变出现色阶断层。Facet 会向 HEIF 解码器索取文件自身的位深（当前相机为 10 bit），并在色调曲线之后才收窄到 8 bit。收益体现在平滑的内容上（晴朗天空、影棚背景、大光圈虚化）；在真实照片上，裁剪标志与 `exposure_score` 保持不变。若解码器无法提供原生位深，会回退到 8 bit。

**参考来源。** PQ EOTF：SMPTE ST 2084:2014。Hable 曲线与逐帧峰值：
ffmpeg `vf_tonemap.c`（John Hable，“Filmic Tonemapping Operators”，2010）。
BT.2020 到 sRGB 矩阵：BT.2020-2 / IEC 61966-2-1（D65）。sRGB OETF：
IEC 61966-2-1。NCLX 传递特征值 16：ISO/IEC 23001-8 / ITU-T H.273。

## 连拍检测

把快速连续拍摄的相似照片归为一组。

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `similarity_threshold_percent` | `70` | 图像哈希相似度阈值 |
| `time_window_minutes` | `0.8` | 照片之间的最大时间间隔 |
| `rapid_burst_seconds` | `0.4` | 在此间隔内的照片自动归为一组 |

---

## 更新提醒

在有更新的 Facet 版本发布时告知编辑用户。它与浏览器里那句“有新版本可用 — 重新加载”不是一回事。

- 运行中的版本始终显示在用户菜单底部，所有能打开查看器的人都能看到。
- 使用 `--build-arg FACET_BUILD=<分支>@<提交>` 构建的镜像还会显示这一行构建信息。`/api/config` 以 `version` 和 `build` 提供两者，但只提供给能读取图库的调用方。
- 服务端每 `interval_days` 至多向 GitHub 询问一次，不携带令牌或图库数据。检查失败会显示为“未知更新”。
- 只有编辑用户会收到提示，每个浏览器每周至多一次。

```json
{
  "updates": {
    "enabled": true,
    "check_url": "https://api.github.com/repos/ncoevoet/facet/releases/latest",
    "interval_days": 7
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | `false` 会禁用检查；不会发出任何请求 |
| `check_url` | GitHub 最新发布 API | 到哪里去查找最新发布的版本 |
| `interval_days` | `7` | 一次结果缓存多久之后才再次询问 |

---

## 序列检测

为包围曝光命名，以免它们被当成互相竞争的备选。每一帧的曝光由已存储的 `f_stop` / `shutter_speed` / `ISO` 推导而来（`EV = log2(N^2 / t) - log2(ISO / 100)`），因此已有图库无需重扫就能被标注。

一段连续照片要成为包围曝光，必须满足：
- 各帧来自同一台相机，且每一帧与前一帧的间隔不超过 `max_gap_seconds`；
- 构图保持一致（pHash 上的 `max_hamming`）；
- 无论拍摄顺序如何（先拍基准帧的 `0、-、+` 与从暗到亮同样适用），都构成一个由不同曝光值组成、等间距、跨度不小于 `min_span_stops`、至少 `min_frames` 帧的阶梯。

每一帧都会被标记 `sequence_ev_offset`，即它相对基准帧的曝光补偿，符号与相机标注 AEB 组的方式一致（`-2` 是暗帧，`+2` 是亮帧）。基准帧是阶梯的正中一级。帧数为偶数时，基准取直方图两端溢出较少的那一张中间帧（并列时取较早的那一帧）；像 `(-2, 0, +2)` 这样的奇数组则始终以中间帧为基准。当某个连拍组恰好就是一组包围曝光时，照片库会显示它的基准帧。

通过 `--detect-sequences` 运行；它也会在每次扫描结束、连拍分组之后自动运行。

**手动修正也覆盖曝光包围。** 检测漏掉的曝光包围可以从照片库或选片暗房手动标记（*标记为曝光包围*）。它需要至少 2 帧，每帧都有可用的曝光数据，且没有两帧曝光值相同。参见 [docs/VIEWER.md — 全景照片与包围曝光](VIEWER.md#全景照片与包围曝光)。

```json
{
  "sequence_detection": {
    "enabled": true,
    "max_gap_seconds": 3.0,
    "max_hamming": 10,
    "min_frames": 3,
    "min_step_stops": 0.5,
    "min_span_stops": 1.0,
    "step_tolerance_stops": 0.34
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 完全关闭包围曝光检测 |
| `max_gap_seconds` | `3.0` | 同一组中相邻两帧之间的最大间隔 |
| `max_hamming` | `10` | 各帧之间允许的 pHash 距离（构图一致） |
| `min_frames` | `3` | 被视为包围曝光的最短连续帧数。`2` 需手动启用 — 见下文的注意事项 |
| `min_step_stops` | `0.5` | 算作有意改变的最小 EV 步长 |
| `min_span_stops` | `1.0` | 从最暗帧到最亮帧的最小总跨度 |
| `step_tolerance_stops` | `0.34` | 允许各步长有多不均匀（三分之一挡） |

**为什么 `min_frames` 出厂值是 `3`。** 相差一挡的两帧，无论是两帧 AEB 还是一次快速的曝光补偿，看起来都一样。设为 `2` 时，在一个测试图库上多找到的组大多并不是包围曝光。一对照片也可能是三张组残留下来的，此时基准帧（`sequence_ev_offset` 为 `0`）可能落在错误的一帧上，而 `hide_brackets`（默认开启）会把另一张藏起来。只有当你确实拍两帧 AEB 并能接受一些误判时，才把它设为 `2`。

---

## 全景检测

标注全景源照片，否则连拍检测会把它们当作互相竞争的备选而藏起。检测依据已存储的 640px 缩略图上相邻帧之间的 SIFT 特征匹配；不解码原图，不用模型，也不需要额外依赖。

- 扫拍沿一个方向稳定行进；连拍则在一处附近抖动。普通扫拍和 HDR 扫拍是两种不同的类别，按曝光跨度区分。
- 在一个测试图库上实测精确率约 96%。部分垂直方向或位置很少的全景会被漏掉。
- 两个方向都可以用按组的手动修正来纠正。

```json
{
  "panorama_detection": {
    "enabled": true,
    "max_gap_seconds": 30.0,
    "min_frames": 8,
    "min_drift": 0.43,
    "min_inliers": 25,
    "hdr_min_span_stops": 1.5,
    "sift_features": 400
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 完全关闭全景检测 |
| `max_gap_seconds` | `30.0` | 同一次扫拍中相邻两帧之间的最大间隔 |
| `min_frames` | `8` | 被视为全景的最短连续帧数（最强的过滤项；非全景都不超过 6 张） |
| `min_drift` | `0.43` | 一段连续照片要成立所需的总扫拍量，以画面宽度计 |
| `min_inliers` | `25` | 一对照片算作匹配所需的 RANSAC 内点数 |
| `max_step` | `0.9` | 单步最大位移，以画面宽度计 — 超过它就算场景切换 |
| `back_tolerance` | `0.02` | 某一步可以逆着扫拍方向移动多少而不终止这一段 |
| `max_ortho` | `0.15` | 整次扫拍中允许的侧向游移 |
| `ortho_ratio` | `0.25` | 按漂移量的比例给出的额外侧向预算，以免长扫拍被误罚 |
| `step_ortho_abs` | `0.02` | 单步中允许的侧向移动，超过即读作重新构图 |
| `step_ortho_ratio` | `0.5` | 同一限制，但按该步自身大小的比例计 |
| `hdr_min_span_stops` | `1.5` | 曝光跨度超过此值的扫拍算作 HDR 全景 |
| `sift_features` | `400` | 每张缩略图的特征数；开销随该值的平方增长 |
| `match_ratio` | `0.75` | 特征匹配必须优于的 Lowe 比率才会被保留 |
| `workers` | `0` | 并行工作进程数；`0` 表示根据核心数自动选择 |
| `probe_stride` | `8` | 用于跳过普通连拍的廉价静态探测之间相隔的帧数 |
| `probe_min_drift` | `0.05` | 探测点处的位移低于此值时，该段会被当作静态而放弃 |
| `max_run_frames` | `500` | 测量的候选段最长帧数（限制内存，每个工作进程每帧约 220 KB） |

说明：
- `sift_features` 为 400 时每对帧约需 2.3 ms，为 3000 时约需 0.12 s。
- 改动设置本身不会带来任何变化，直到检测重新运行：请使用 `--detect-panoramas`（或查看器中的重新运行操作），它会重新测量整个图库。
- 扫描之后运行的全景步骤（以及 `--recompute-average` 和 `--recompute-burst` 之后的那一步）只会重新测量发生变化的段。改动 `enabled` 和 `workers` 之外的任何设置，都会让它重新测量全部内容。
- 你的修正会在下一遍次生效。对未变化的图库运行两遍，会找到相同的组，分组编号也相同。

---

## 连拍评分

连拍选片用来在每个连拍组中挑出最佳照片的权重。各权重之和应为 1.0。

```json
{
  "burst_scoring": {
    "weight_aggregate": 0.4,
    "weight_aesthetic": 0.25,
    "weight_sharpness": 0.2,
    "weight_blink": 0.15
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `weight_aggregate` | `0.4` | 总体聚合评分的权重 |
| `weight_aesthetic` | `0.25` | 美学质量评分的权重 |
| `weight_sharpness` | `0.2` | 技术清晰度评分的权重 |
| `weight_blink` | `0.15` | 检测到闭眼时的扣分权重（越大扣得越狠） |

---

## 重复照片检测

在全库范围内检测重复照片：先用宽松的 pHash 得到候选，再用嵌入相似度检查加以确认。

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `similarity_threshold_percent` | `90` | 严格的 pHash 门限（90% = 64 位中汉明距离 <= 6）；当两张照片中有一张缺少嵌入时，它就是唯一判据 |
| `prefilter_hamming` | `12` | 可选（随附文件中没有）。两张照片都有嵌入时，用于筛出候选的宽松汉明门限（不低于严格门限） |
| `embedding_cosine_threshold` | `0.90` | 可选（随附文件中没有）。只有 SigLIP/CLIP 余弦值 >= 此值时，候选才会合并 |

- `python facet.py --detect-duplicates` 检测并归并重复照片。
- `python facet.py --sweep-dedup-thresholds [labels.json]` 评估余弦门限：提供标注 JSON 时它会打印精确率/召回率，否则打印候选余弦值的分布，以及该门限拒绝了多少次严格 pHash 匹配。

---

## 扩展 IQA 层（可选）

额外的画质评分器，它们会写入各自的列；它们绝不会取代 TOPIQ。它们在普通扫描过程中运行。加载或显存失败会被记入日志，对应的列留作 `NULL`；扫描会继续。

- `qrealign` 默认为 `"auto"`：在 `8gb`/`16gb`/`24gb` 配置档下**开启**，在 `legacy`/CPU 下**关闭**。
- `aesthetic_v25` 和 `deqa` **默认关闭**。

```json
{
  "iqa_extended": {
    "qrealign": "auto",
    "qrealign_size": "mini",
    "aesthetic_v25": false,
    "deqa": false
  }
}
```

| 设置 | 默认值 | 可接受的取值 | 列 | 说明 |
|---------|---------|-----------------|--------|-------------|
| `qrealign` | `"auto"` | `"auto"` · `true` · `false` | `qrealign_score` | Q-ReAlign-Mini 0.8B 美学 IQA（Apache-2.0，约 2-3GB 显存/内存，不依赖 pyiqa） |
| `qrealign_size` | `"mini"` | `"mini"` · `"lite"` | - | `mini`（0.8B）或 `lite`（4B）；也是 `licensing.mode: "commercial"` 下的主要模型 |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5（SigLIP 头，约 2GB）；**已弃用**，请优先使用 `qrealign` |
| `deqa` | `false` | `true` / `false` | `deqa_score` | DeQA-Score VLM IQA（需要 16GB 以上显存的 GPU；否则跳过并留作 NULL） |

说明：
- **排序：** 只要至少有一张照片具有评分，每项指标就会出现在查看器的排序菜单中（**Q-ReAlign（美观度）**、**Aesthetic v2.5**、**DeQA**）。未评分的照片排在最后。
- `qrealign_score` 包含美学任务；画质使用 `quality_score`。
- `aesthetic_v25` 需要 `aesthetic-predictor-v2-5` 包。它采用 AGPL-3.0 许可，上游自 2024-12-18 起不再维护。

**请为你启用的功能安装可选依赖**：`pip install -e .[iqa-extended]`（会装上 `aesthetic-predictor-v2-5`），或者取消 `requirements.txt` 中对应那一行的注释。DeQA-Score 通过 `transformers` 下载。

每项指标都以权重 0 参与加权聚合，因此在你给它赋权之前，`--recompute-average` 不会带来任何变化。运行 `python facet.py --eval-iqa-srcc` 可以衡量每项指标与你自己的星级评分的吻合程度。

**在查看器中的呈现。** 有值时，这些数值会显示在照片详情的**画质**面板中（`Q-ReAlign`、`Aesthetic V2.5`、`DeQA`），并在照片库筛选侧栏的**扩展画质指标**下提供范围滑块（`min_qrealign`/`max_qrealign`、`min_aesthetic_v25`/`max_aesthetic_v25`、`min_deqa`/`max_deqa`）。

> **警告：** 在你启用某项指标之前扫描的照片在该指标上是 `NULL`，只要给其滑块设置了最小值或最大值，这些照片就会被隐藏。请在按新启用的指标筛选之前重新扫描。

**健壮性。** DeQA-Score 会运行远程模型代码（`trust_remote_code`）。如果它在某张图片上失败（签名变化、输出异常、显存不足），该图片的 `deqa_score` 会留作 `NULL`，扫描继续。

---

## 许可（Licensing）

控制 Facet 可以加载哪些模型组件。各组件的许可证表见 [THIRD_PARTY_MODELS.md](THIRD_PARTY_MODELS.md)。

```json
{
  "licensing": {
    "mode": "default",
    "allow_unclear": false
  }
}
```

| 设置 | 默认值 | 可接受的值 | 说明 |
|---------|---------|-----------------|-------------|
| `mode` | `"default"` | `"default"` · `"commercial"` | `"default"` 加载所有模型；`"commercial"` 只加载适合商业使用的组件 |
| `allow_unclear` | `false` | `true` / `false` | 在商业模式下，同时允许许可证*不明确*的组件（SAMP-Net、U2-Net-P、LAION CLIP-MLP 美学头）；必须是 JSON 布尔值 |

在 `"commercial"` 模式下：
- `pyiqa`（TOPIQ、HyperIQA、LIQE 等）和 InsightFace 绝不会被导入或下载。
- 美学与质量由 Q-ReAlign 提供，构图由基于规则的分析器提供。
- 人脸使用 YuNet 检测、128 维 SFace 特征向量，以及可选的 MediaPipe 眼睛/微笑和 OFIQ 人脸质量。
- `liqe` 和 `aesthetic_iaa` 保持为 `NULL`。`deqa`（许可证*不明确*）需要 `allow_unclear`。`aesthetic_v25`（AGPL）始终不可用。
- 被拒绝的组件会让扫描在启动时以 `LicenceError` 终止，其中指明该组件及其替代项。
- `--score-topiq`、`--recompute-iqa`（pyiqa 模型）和 `--recompute-composition-gpu` 会带着该消息退出。
- 非商业许可的组件即使设置了 `allow_unclear` 也仍被拒绝。

以上内容不构成法律建议。

环境变量覆盖（只能收紧；无效值会中止启动）：

| 变量 | 作用 |
|----------|--------|
| `FACET_LICENSING_MODE` | `commercial` 强制使用商业模式；`default` 或为空 = 不覆盖 |
| `FACET_LICENSING_ALLOW_UNCLEAR` | `0`、`false`、`no`、`off` 强制关闭 `allow_unclear`；`1`、`true`、`yes`、`on` 或为空 = 不覆盖 |

查看器会在其启动的每个 `facet.py` 进程中传入 `FACET_LICENSING_MODE=commercial`，并在其策略禁止“不明确”组件时传入 `FACET_LICENSING_ALLOW_UNCLEAR=0`。把 `licensing.allow_unclear` 写成 `"false"` 这样的字符串会在启动时被拒绝。

---

## 人脸检测

InsightFace 人脸检测设置。

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false,
    "eyes_closed_max": 4.0,
    "poor_expression_min": 4.0,
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | 最低检测置信度（仅 InsightFace） |
| `min_face_size` | `20` | 最小人脸尺寸（像素）（仅 InsightFace） |
| `blink_ear_threshold` | `0.28` | 用于闭眼检测的眼睛纵横比 |
| `min_faces_for_group` | `4` | 判定为合影所需的最少人脸数（在 `--recompute-average` 时重新计算） |
| `enable_3d_landmarks` | `false` | 可选（随附文件中没有）。加载 InsightFace 的 `landmark_3d_68` 以提取头部姿态（偏航/俯仰/翻滚）；约 5MB，仅供参考 |
| `eyes_closed_max` | `4.0` | 睁眼评分（0–10），低于或等于此值时选片暗房会标记眨眼（人脸圈、睁眼滑块） |
| `poor_expression_min` | `4.0` | 微笑/表情评分（0–10），低于此值时暗房会标记表情欠佳 |
| `blendshapes.enabled` | `true` | 安装了 MediaPipe 时，用其混合形状得到 `eyes_open_score` / `smile_score`，否则使用关键点几何 |
| `blendshapes.min_crop_size` | `192` | 带留白的裁切图短边小于此值（像素）的人脸使用几何评分 |
| `blendshapes.blink_pose_gate_deg` | `null` | 仅适用于商业模式（MediaPipe）：头部姿态阈值（度）；`null` = 关闭 |

说明：
- 商业模式的 YuNet 检测器使用固定值（置信度 0.7、30 像素），忽略 `min_confidence_percent` 和 `min_face_size`。
- MediaPipe 需要 `face_landmarker.task` 模型包。请用 `pip install mediapipe==0.10.35 --no-deps` 安装，切勿直接 `pip install mediapipe`。见 [FACE_RECOGNITION.md](FACE_RECOGNITION.md#逐张人脸的表情信号睁眼--微笑)。
- `blink_pose_gate_deg`：|yaw| 或 |pitch| 超过该值的人脸不给出眨眼判定，也不给出睁眼 / 微笑评分（NULL），因为转头会让眼睛看起来像闭着。在一个测试图库上，20° 到 45° 之间的任何阈值都没有改善眨眼检测，因此默认关闭。它必须是正数；仅对新扫描的照片生效（`is_blink` 会在重新扫描时改变）。

---

## 人脸聚类

用于人脸识别的 HDBSCAN 聚类。

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 启用人脸聚类 |
| `min_faces_per_person` | `2` | 每个人物最少的照片数 |
| `min_samples` | `2` | HDBSCAN 的 min_samples 参数 |
| `clustering_algorithm` | `"best"` | HDBSCAN 算法 |
| `leaf_size` | `40` | 树的叶子大小（仅 CPU） |
| `use_gpu` | `"auto"` | GPU 模式：`auto`、`always`、`never`（见下文说明） |
| `thresholds_by_model` | 见 JSON | 按识别模型分别设置：`auto_merge_distance_percent` 和 `merge_threshold`。默认值：ArcFace `15` / `0.6`，SFace `27.5` / `0.65` |

`merge_threshold`（匹配用的质心相似度）和 `auto_merge_distance_percent`（自动合并距离）会针对**当前生效的**识别模型（默认 ArcFace，商业模式为 SFace）从 `thresholds_by_model` 读取。没有对应条目的模型会报错。直接放在 `face_clustering` 下的同名键不再被读取。

**GPU 聚类说明（`use_gpu`）：**

- 需要可选的 `cuml` + `cupy` 包。Docker GPU 镜像已内置 cuML。
- `legacy` 配置档无论 `use_gpu` 为何，始终用 CPU 聚类。
- 没有可用的 CUDA 设备时，聚类会回退到 CPU HDBSCAN。
- 若 cuML 不可用，`always` 会给出警告并改用 CPU；聚类过程中出现的 GPU 错误也会回退到 CPU。

**聚类算法：**

| 算法 | 复杂度 | 适用于 |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | 高维数据（推荐） |
| `boruvka_kdtree` | O(n log n) | 低维数据 |
| `prims_balltree` | O(n²) | 内存受限、高维 |
| `prims_kdtree` | O(n²) | 内存受限、低维 |
| `best` | 自动 | 交给 HDBSCAN 决定 |

---

## 人脸处理

控制人脸提取与缩略图生成。

```json
{
  "face_processing": {
    "crop_padding": 0.3,
    "use_db_thumbnails": true,
    "face_thumbnail_size": 640,
    "face_thumbnail_quality": 90,
    "extract_workers": 2,
    "extract_batch_size": 16,
    "refill_workers": 4,
    "refill_batch_size": 100,
    "auto_tuning": {
      "enabled": true,
      "memory_limit_percent": 80,
      "min_batch_size": 8,
      "monitor_interval_seconds": 5
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `crop_padding` | `0.3` | 人脸裁切的留白比例 |
| `use_db_thumbnails` | `true` | 使用已存储的缩略图 |
| `face_thumbnail_size` | `640` | 缩略图尺寸（像素） |
| `face_thumbnail_quality` | `90` | JPEG 质量 |
| `extract_workers` | `2` | 并行提取的工作线程数 |
| `extract_batch_size` | `16` | 提取批大小 |
| `refill_workers` | `4` | 缩略图回填的工作线程数 |
| `refill_batch_size` | `100` | 回填批大小 |
| **auto_tuning** | | |
| `enabled` | `true` | 启用基于内存的调优 |
| `memory_limit_percent` | `80` | 有效内存上限的百分比（在容器限额下取 cgroup 限额，否则取宿主机内存） |
| `min_batch_size` | `8` | 最小批大小 |
| `monitor_interval_seconds` | `5` | 检查间隔 |

---

## 单色检测

黑白照片检测。

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `saturation_threshold_percent` | `5` | 平均饱和度 < 5% = 单色 |

---

## 标签

通用的标签设置。标签模型按配置档在 `models.profiles.*.tagging_model` 中配置。

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 启用打标签 |
| `max_tags` | `5` | 每张照片最多的标签数 |

**注意：** CLIP/SigLIP 的标签阈值是当前配置档所在块中的 `tag_threshold_percent`：`16gb`/`24gb` 用 `models.clip`，`legacy`/`8gb` 用 `models.clip_legacy`。旧键 `similarity_threshold_percent` 已不再读取。如果你自定义过它，请把值复制到 `tag_threshold_percent`；加载配置时和 `python facet.py --doctor` 都会点名这个旧键。

扫描结束时，当 `enabled` 为 `false`，或没有任何照片同时具有嵌入向量和空的标签列表时，标注步骤会跳过（并输出一行日志）。任何标签都无法匹配的照片会一直处于待处理状态，因此每次扫描仍会加载该模型。`python tag_existing.py`（无论是否带 `--force`）和 `python facet.py --tag-untagged` 总是会运行。

### 可用的标签模型

通过 `models.profiles.*.tagging_model` 配置：

| 模型 | 显存 | 标签风格 | 备注 |
|-------|------|-----------|-------|
| `clip` | 0（复用嵌入） | 情绪/氛围（dramatic、golden_hour、vintage） | 无需额外加载模型；物体识别不那么直白 |
| `qwen3.5-2b` | ~4GB | 结构化场景（landscape、architecture、reflection） | 需要 transformers 和额外显存 |
| `qwen3.5-4b` | ~8GB | 更细致入微的场景描述 | 显存需求更高；推理更慢 |

### 各配置档的默认标签模型

| 配置档 | 标签模型 | 嵌入模型 |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14（768 维） |
| `8gb` | `clip` | CLIP ViT-L-14（768 维） |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M（1152 维） |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M（1152 维） |

### 重新为照片打标签

```bash
python facet.py --recompute-tags       # 用各配置档已配置的模型重新打标签
python facet.py --recompute-tags-vlm   # 用 VLM 标签模型重新打标签
```

---

## 独立标签

带同义词列表、且不绑定任何特定类别的标签。无论照片被归到哪个类别，这些标签都适用。每个键是标签名；值是供 CLIP/VLM 匹配用的同义词列表。

```json
{
  "standalone_tags": {
    "bokeh": ["bokeh", "shallow depth of field", "background blur", "out of focus"],
    "surreal": ["surreal", "dreamlike", "fantasy", "composite", "double exposure"],
    "flat_lay": ["flat lay", "overhead shot", "top down", "bird's eye product"],
    "golden_hour": ["golden hour", "magic hour", "warm light", "sunset light"],
    "portrait_tag": ["portrait", "headshot", "face portrait", "close-up portrait"]
  }
}
```

要新增独立标签，只需提供一个键和一个同义词列表。这里定义的标签会与各类别专属的标签合并，构成完整的标签词表。

---

## 分析

`--compute-recommendations` 使用的阈值。

```json
{
  "analysis": {
    "aesthetic_max_threshold": 9.0,
    "aesthetic_target": 9.5,
    "quality_avg_threshold": 7.5,
    "quality_weight_threshold_percent": 10,
    "correlation_dominant_threshold": 0.5,
    "category_min_samples": 50,
    "category_imbalance_threshold": 0.5,
    "score_clustering_std_threshold": 1.0,
    "top_score_threshold": 8.5,
    "exposure_avg_threshold": 8.0
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `aesthetic_max_threshold` | `9.0` | 最高美学评分低于此值时发出警告 |
| `aesthetic_target` | `9.5` | aesthetic_scale 的目标值 |
| `quality_avg_threshold` | `7.5` | 判定为“高价值”的画质阈值 |
| `quality_weight_threshold_percent` | `10` | 画质权重 ≤ 此值时发出警告 |
| `correlation_dominant_threshold` | `0.5` | “主导信号”警告 |
| `category_min_samples` | `50` | 每个类别最少的照片数 |
| `category_imbalance_threshold` | `0.5` | 评分差距警告 |
| `score_clustering_std_threshold` | `1.0` | 标准差小于此值时发出警告 |
| `top_score_threshold` | `8.5` | 最高聚合分低于此值时发出警告 |
| `exposure_avg_threshold` | `8.0` | 平均曝光评分高于此值时发出警告 |

---

## 查看器

网页照片库的显示与行为。

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "learning",
      "candidate_pool_size": 200,
      "show_current_scores": true
    },
    "sort_options": { ... },
    "pagination": {
      "default_per_page": 64
    },
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    },
    "persons": {
      "needs_naming_min_faces": 5
    },
    "raw_processor": {
      "backend": "rawpy",
      "darktable": {
        "executable": "darktable-cli",
        "hq": true,
        "width": null,
        "height": null,
        "extra_args": [],
        "cull_styles": [],
        "preview_max_edge": 1440,
        "preview_timeout_seconds": 60
      }
    },
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96,
      "thumbnail_slider": {
        "min_px": 120,
        "max_px": 400,
        "default_px": 168,
        "step_px": 8
      }
    },
    "face_thumbnails": {
      "output_size_px": 64,
      "jpeg_quality": 80,
      "crop_padding_ratio": 0.2,
      "min_crop_size_px": 20
    },
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    },
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      },
      "low_light_max_luminance": 0.2
    },
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "tooltip_mode": "panel",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 3600,
    "notification_duration_ms": 2000,
    "moment_confidence_min": 0,
    "path_mapping": {}
  }
}
```

> **注意：** `sort_options`（上文以 `{ ... }` 略去）把数据库列映射到下拉菜单标签，很少需要编辑。**内容**分组中包含一项 `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` 排序（NULL 值排在最后）。

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `default_category` | `""` | 默认的类别筛选 |
| `edition_password` | `""` | 解锁编辑模式的密码；留空 = 只读（`trusted_local_editing` 下除外） |
| `trusted_local_editing` | `false` | 无需密码，即授予同一台计算机上的浏览器编辑权限。参见[受信任的本地编辑](#受信任的本地编辑) |
| `place_search_url` | `"https://photon.komoot.io/api"` | 照片库**在线搜索**所用的 Photon 端点；`""` 表示关闭。参见[在线地点搜索](#在线地点搜索) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | 建议权重之前，该类别所需的最少决定性比较次数（平局不计） |
| `pair_selection_strategy` | `"learning"` | 配对策略：`learning`、`uncertainty`、`boundary`、`active`、`random` |
| `candidate_pool_size` | `200` | `learning` 策略从中抽取配对的随机候选池大小 |
| `show_current_scores` | `true` | 比较时显示评分 |
| **pagination** | | |
| `default_per_page` | `64` | 每页照片数 |
| **dropdowns** | | |
| `max_cameras` | `50` | 下拉菜单中最多的相机数 |
| `max_lenses` | `50` | 最多的镜头数 |
| `max_persons` | `50` | 最多的人物数 |
| `max_tags` | `20` | 最多的标签数 |
| `min_photos_for_person` | `10` | 照片数少于此值的人物不在下拉菜单中显示 |
| **persons** | | |
| `needs_naming_min_faces` | `5` | 聚类要出现在 `/persons` 的“待命名”下所需的最少人脸数；`1` 会列出所有未命名的人物 |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | darktable-cli 的可执行文件名或绝对路径 |
| `darktable.profiles` | `[]` | 具名的 darktable 导出配置数组（见下文） |
| `darktable.profiles[].name` | *（必填）* | 配置的显示名称（用于下载菜单和 API 的 `profile` 参数） |
| `darktable.profiles[].hq` | `true` | 传入 `--hq true` 以进行高质量导出 |
| `darktable.profiles[].width` | *（省略）* | 输出最大宽度（省略则为完整分辨率） |
| `darktable.profiles[].height` | *（省略）* | 输出最大高度（省略则为完整分辨率） |
| `darktable.profiles[].style` | *（省略）* | 导出时套用的 darktable 样式名（`--style`） |
| `darktable.profiles[].apply_custom_presets` | `true` | 设为 `false` 会传入 `--apply-custom-presets false`，因此只应用明确指定的 `style` |
| `darktable.profiles[].extra_args` | `[]` | 额外的命令行参数（例如 `["--style-overwrite"]`） |
| `darktable.cull_styles` | `[]` | 在选片暗房中作为修图外观预览提供的 darktable 样式；留空则隐藏选择器 |
| `darktable.cull_styles[].name` | *（必填）* | darktable 样式名称（传给 `--style`） |
| `darktable.cull_styles[].label_key` | *（取样式名）* | 菜单标签的可选 i18n 键；默认取样式名 |
| `darktable.preview_max_edge` | `1440` | 选片预览渲染的最大边长（像素） |
| `darktable.preview_timeout_seconds` | `60` | 单次选片预览渲染的 darktable-cli 超时 |
| **display** | | |
| `tags_per_photo` | `4` | 卡片上显示的标签数 |
| `card_width_px` | `168` | 卡片宽度 |
| `image_width_px` | `160` | 图像宽度 |
| `image_jpeg_quality` | `96` | `/api/download` 和 `/api/image` 中 RAW/HEIF 转换的 JPEG 质量（1–100） |
| `thumbnail_slider.min_px` | `120` | 缩略图最小尺寸（像素） |
| `thumbnail_slider.max_px` | `400` | 缩略图最大尺寸（像素） |
| `thumbnail_slider.default_px` | `168` | 缩略图默认尺寸（像素） |
| `thumbnail_slider.step_px` | `8` | 滑块步进（像素） |
| **face_thumbnails** | | |
| `output_size_px` | `64` | 缩略图尺寸 |
| `jpeg_quality` | `80` | JPEG 质量 |
| `crop_padding_ratio` | `0.2` | 人脸留白 |
| `min_crop_size_px` | `20` | 最小裁切尺寸 |
| **quality_thresholds** | | |
| `good` | `6` | “良好”阈值 |
| `great` | `7` | “很好”阈值 |
| `excellent` | `8` | “优秀”阈值 |
| `best` | `9` | “最佳”阈值 |
| **photo_types** | | |
| `top_picks_min_score` | `7` | 精选照片的最低分 |
| `top_picks_min_face_ratio` | `0.2` | 决定采用哪套权重的人脸占比 |
| `low_light_max_luminance` | `0.2` | 弱光阈值 |
| **defaults** | | |
| `type` | `""` | 默认的照片类型筛选（例如 `"portraits"`、`"landscapes"`，或 `""` 表示全部） |
| `sort` | `"aggregate"` | 默认排序列（浏览器记住的排序优先；见[排序](VIEWER.md#排序)） |
| `sort_direction` | `"DESC"` | 默认排序方向（`"ASC"` 或 `"DESC"`） |
| `hide_blinks` | `true` | 默认隐藏闭眼照片 |
| `hide_bursts` | `true` | 默认只显示连拍最佳照片 |
| `hide_duplicates` | `true` | 默认隐藏非代表帧的重复照片 |
| `hide_brackets` | `true` | 默认只显示包围曝光组的基准曝光 |
| `hide_panoramas` | `true` | 默认每组全景只显示一张代表帧 |
| `hide_details` | `true` | 默认在卡片上隐藏照片详情 |
| `tooltip_mode` | `"panel"` | 提示触发方式：`"hover"`、`"click"`、`"off"` 或 `"panel"`（停靠侧栏）；取代 `hide_tooltip` |
| `panel_activation` | `"both"` | 在 `"panel"` 模式下切换停靠侧栏所示照片的操作：`"hover"`、`"click"` 或 `"both"` |
| `hide_rejected` | `true` | 默认隐藏已淘汰照片 |
| `gallery_mode` | `"mosaic"` | 默认的照片库布局（`"grid"` 或 `"mosaic"`） |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | CORS 允许的来源；远程托管时请加入你的域名或反向代理 URL |
| **security_headers** | | |
| `security_headers.content_security_policy` | _（兼容 SPA 的默认值）_ | Content-Security-Policy 头；`""` 表示关闭，或提供更严格的策略 |
| `security_headers.hsts` | `false` | 发送 `Strict-Transport-Security`。仅在查看器通过 HTTPS 提供服务时才启用。 |
| **其他** | | |
| `cache_ttl_seconds` | `3600` | 内存中统计/查询缓存的 TTL；应比一次完整统计计算（可能耗时数分钟）更长 |
| `notification_duration_ms` | `2000` | 提示条显示时长 |
| `moment_confidence_min` | `0` | 置信度（0–1）低于此值的时刻标签会变暗并显示“（不确定）”；`0` = 从不变暗 |

说明：
- **`trusted_local_editing`** 仅在单用户安装的 `password` 与 `edition_password` 均为空时生效。它涵盖所有需要编辑权限的路由（包括扫描），并允许“连接助手”对话框为来自同一台机器的 `/mcp` 请求创建完全编辑的助手令牌。

> **警告：** 切勿在同一主机的反向代理之后启用 `trusted_local_editing`。

- **`pair_selection_strategy`：** `learning` 起初挑选多样化的配对，之后挑选模型排序前后不一致的配对。
- **`darktable.cull_styles`** 供 `GET /api/photo/cull_preview` 使用。每个样式**必须已存在**于运行查看器的用户的 darktable 配置中。
- 默认的 Content-Security-Policy 允许 SPA 自身的资源：内联的主题脚本/样式、Google Fonts、OpenStreetMap 图块以及同源 API。
- `moment_confidence_min` 会让场景页眉、选片的场景组页眉和照片库提示中的标签变暗。

### 卡片角标与溢出裁切

`viewer.badges` 用来逐个开关照片库卡片上的角标。较早出现的角标默认都是 `true`，因此不写这个块不会改变任何行为。

```json
{
  "viewer": {
    "badges": {
      "favorite": true,
      "star_rating": true,
      "rejected": true,
      "sequence_kind": true,
      "sequence_override_pending": true,
      "stack": true,
      "keeper_hint": true,
      "best_of_burst": true,
      "clipping_highlight": true,
      "clipping_shadow": false
    },
    "clipping": {
      "badge_percent": 5,
      "indicator_percent": 1,
      "histogram_mode": "rgb",
      "tooltip_histogram_mode": "luma"
    }
  }
}
```

| 键 | 默认值 | 说明 |
|-----|---------|-------------|
| `badges.favorite` | `true` | 已收藏照片上的心形角标（编辑模式） |
| `badges.star_rating` | `true` | 已评星照片上的星形 + 数字角标（编辑模式） |
| `badges.rejected` | `true` | 已淘汰照片上的拇指向下角标（编辑模式） |
| `badges.sequence_kind` | `true` | 照片组角标（连拍/包围曝光/全景/重复），仅当对应的隐藏开关把该组折叠起来时才显示 |
| `badges.sequence_override_pending` | `true` | 表示某项全景修正正在等待下一次检测运行的时钟角标 |
| `badges.stack` | `true` | 手动照片堆叠中各张卡片上的图层角标及成员数；点击即可打开堆叠 |
| `badges.keeper_hint` | `true` | 来自习得留存模型的“本组中还有更好的一张”箭头 |
| `badges.best_of_burst` | `true` | 连拍代表帧上的“最佳”角标，仅在 `hide_bursts` 关闭时显示 |
| `badges.clipping_highlight` | `true` | 为高光溢出超过 `clipping.badge_percent` 的照片加角标 |
| `badges.clipping_shadow` | `false` | 暗部死黑的同类角标（默认关闭：暗部溢出在剪影、夜景、低调影像中常常是刻意为之） |

关闭 `badges.stack` 只隐藏角标，“打开照片堆叠”卡片按钮仍然可用。

`viewer.clipping` 为卡片角标、直方图标记和照片库筛选统一定义“溢出”。

| 键 | 默认值 | 说明 |
|-----|---------|-------------|
| `badge_percent` | `5` | R/G/B 中最差通道的像素占比，超过此值的照片会被加角标（在一个样本上约每 25 张照片触发 1 张） |
| `indicator_percent` | `1` | 直方图自身 R/G/B 端点标记的阈值 |
| `histogram_mode` | `"rgb"` | **详情面板**直方图的默认值：`"luma"`、`"rgb"`、`"r"`、`"g"` 或 `"b"` |
| `tooltip_histogram_mode` | `"luma"` | **侧边面板**直方图标签页（`tooltip_mode: "panel"`）的默认值，取值同样是那五种 |

说明：
- 用户自己的直方图选择存在 `localStorage`（`facet_histogram_mode`、`facet_histogram_mode_tooltip`）中，并优先于这些默认值。这两项设置相互独立。
- **悬停**和**点击**气泡不显示直方图。

**溢出是按通道、恰好在第 0 格和第 255 格上测量的。** 它以最差通道的像素百分比存储在 `photos.channel_clip_shadow_pct` / `channel_clip_highlight_pct` 中。这与 `shadow_clipped` / `highlight_clipped` 标志不同，后者覆盖 0–30 和 225–255 的亮度带，并参与 `exposure_score`。

**`NULL` 表示未知，绝不表示干净。** 如果一张照片存储的直方图较旧，它就没有通道数据，因此既不带角标，也不匹配照片库筛选的任何一侧。`python facet.py --backfill-clipping` 会根据已存储的直方图填充这些列；它不解码任何图像，并且可以续跑。

### 功能

开关可选功能，以减少内存占用或简化界面：

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
      "show_memories": true,
      "show_captions": true,
      "show_timeline": true,
      "show_map": true,
      "show_scenes": true,
      "show_my_taste": true
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `show_similar_button` | `true` | 在照片卡片上显示“查找相似照片”按钮（CLIP 相似度计算需要 numpy） |
| `show_merge_suggestions` | `true` | 在管理人物页面启用合并建议功能 |
| `show_rating_controls` | `true` | 显示星级与收藏控件 |
| `show_scan_button` | `false` | 显示触发扫描的按钮（无需 GPU；见下文说明） |
| `metrics_enabled` | `false` | 启用公开的 `GET /metrics` Prometheus 端点（见下文警告） |
| `show_semantic_search` | `true` | 显示语义搜索栏（使用 CLIP/SigLIP 嵌入进行以文搜图） |
| `show_albums` | `true` | 显示相册功能（创建、管理和浏览照片相册） |
| `show_critique` | `true` | 在照片卡片上显示 AI 点评按钮（基于规则的评分拆解） |
| `show_vlm_critique` | `true` | 启用 VLM 点评（16gb/24gb 配置档）；该键缺失时为 `false` |
| `show_embed_metadata` | `true` | 在编辑模式下显示“将元数据写入文件”（通过 exiftool 嵌入星级/关键词） |
| `show_memories` | `true` | 显示“那年今日”回忆对话框（往年同一日期拍摄的照片） |
| `show_captions` | `true` | 在照片卡片上显示 AI 生成的照片描述 |
| `show_timeline` | `true` | 显示可按日期导航、按时间顺序浏览的时间线视图 |
| `show_map` | `true` | 显示 GPS 地图视图（需要 Leaflet）；该键缺失时为 `false` |
| `show_capsules` | `true` | 显示照片胶囊视图（按主题分组的精选照片幻灯片） |
| `show_folders` | `true` | 显示按照片目录结构进行的文件夹浏览 |
| `show_scenes` | `true` | 显示场景视图（`/scenes`），把连拍代表帧按时间顺序聚成场景 |
| `show_my_taste` | `true` | 显示来自个人排序模型的“我的偏好”排序，并附带置信角标 |
| `show_social_export` | `true` | 显示仅编辑模式可用的**社交平台裁切**下载菜单。见[社交平台导出](#社交平台导出) |
| `show_portfolio_export` | `true` | 显示仅编辑模式可用的**导出作品集**相册操作。见[作品集导出](#作品集导出) |
| `show_proofing` | `false` | 在共享相册上启用客户选片。见[客户选片](#客户选片) |

说明：
- **`show_scan_button`：** 多用户模式下对超级管理员可见，单用户模式下对已解锁的编辑模式会话可见。在 `legacy` 配置档下扫描仅使用 CPU 运行。`trusted_local_editing` 下的受信任本地会话无需此项即可扫描。
- **内存优化：** 设置 `show_similar_button: false` 可避免加载 numpy，从而减小查看器的内存占用。

> **警告：** `metrics_enabled` 会暴露照片/人物/人脸数量、数据库大小和进程内存。仅在抓取端网络能够访问的地方启用它，切勿对公网开放。

### 客户选片

`viewer.features.show_proofing`（默认 `false`）可把任意共享相册变成一个客户选片页面。持有分享链接（以及可选的 `viewer.proofing.pin`）的客户无需账号，即可为照片点心形并留言。所有者可在相册卡片上受编辑权限限制的对话框中查看这些选片。客户的选片绝不会触碰所有者自己的评分，也不会用于训练个人排序模型。

```json
{
  "viewer": {
    "features": { "show_proofing": false },
    "proofing": {
      "pin": "",
      "session_minutes": 1440
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `features.show_proofing` | `false` | 共享相册上客户选片功能的总开关 |
| `proofing.pin` | `""` | 客户连同分享链接必须输入的可选 PIN 码；留空 = 不需要 PIN（尝试次数有速率限制） |
| `proofing.session_minutes` | `1440` | 客户会话的有效期（分钟，24 小时）；相册取消共享或选片功能被禁用时，会话立即失效 |

### 路径映射

把数据库中的路径映射到本地路径，适用于照片是在一台机器上评分的（例如使用 UNC 路径的 Windows），而查看器运行在另一台机器上（例如 Linux NAS）的情形。

```json
{
  "viewer": {
    "path_mapping": {
      "\\\\NAS\\Photos": "/mnt/photos",
      "D:\\Pictures": "/volume1/pictures"
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `path_mapping` | `{}` | 源前缀 → 目标前缀，在从磁盘读取文件时应用 |

**工作方式：**
- 只在**从磁盘读取文件**时生效（原尺寸图像、下载、VLM 点评）。数据库中的路径绝不会被修改。
- 反斜杠/正斜杠会被归一化：`\\NAS\Photos\img.jpg` 和 `//NAS/Photos/img.jpg` 都能匹配。
- 各条映射按顺序求值；第一个匹配上的前缀胜出。
- 映射的目标目录会自动加入多用户目录白名单。

**示例：** 一个在 Windows 上建立的数据库存储着形如 `\\NAS\Photos\2024\IMG_001.jpg` 的路径。在 Linux 上，同一个共享挂载在 `/mnt/nas/Photos`。可以这样配置：

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### 密码保护

为查看器提供可选的密码保护：

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

设置之后，用户必须先登录才能使用查看器。

### 受信任的本地编辑

允许仅由同一台计算机上的浏览器使用的单用户查看器，在没有编辑密码的情况下进行编辑：

```json
{
  "viewer": {
    "trusted_local_editing": true
  }
}
```

它仅在 `viewer.password` 与 `viewer.edition_password` **均**为空、多用户模式关闭且配置正常加载时生效。设置编辑密码即会使其失效。它不会设置或泄露任何密码，不会更改令牌，也不会启用多用户管理。

Facet 会检查每一个请求。只有同时满足以下所有条件的请求才被信任：

- TCP 对端是 loopback 地址（`::ffff:127.0.0.1` 这类 IPv4 映射对端按其 IPv4 地址判断）；
- 恰好有一个 `Host` 头，且其值为 `localhost`、`127.0.0.1` 或 `[::1]`，端口可选；
- 请求不带任何 `Forwarded`、`Via`、`X-Real-IP`、`X-Client-IP`、`True-Client-IP`、`CF-Connecting-IP`、`X-Original-Forwarded-For` 或 `X-Forwarded-*` 头；
- 若存在 `Origin` 或 `Referer`，必须与请求的协议、主机和端口完全一致且不含凭据（带路径、查询或片段的 `Origin` 会被拒绝）；若存在 `Sec-Fetch-Site`，其值必须为 `same-origin` 或 `none`。

任何其他请求（包括 GET 请求）都按该选项关闭处理。

受信任的请求在每一条需要编辑权限的路由上都拥有完整的编辑权限：评分、比较、选片（包括会移动文件或将其移入回收站的**选片后导出／清理**，以及单张照片删除）、相册、人物与人脸、权重、优先级与拍摄场景评分方案、元数据嵌入与导出、重算与全景任务，以及描述与点评的生成。它也可以在没有 `viewer.features.show_scan_button` 的情况下扫描。扫描进度流只接受来自同一台本地机器的受信任本地流令牌。

**助手。** 此时“连接助手”对话框可以创建**完全编辑**令牌（仍需 `viewer.mcp.enabled`）。

- 该令牌仅对通过上述检查的 `/mcp` 请求为 `edition`：位于 `:5000` 或 `ng serve` 开发代理 `:4200` 上的 `http://localhost:<port>` 或 `127.0.0.1`。
- 来自局域网客户端、主机名或 `0.0.0.0` 的 URL 或 Docker 部署时，它降为 `readonly`。设置任何密码也会把它降为 `readonly`；清除密码后恢复。
- 删除类工具仍需要 `viewer.mcp.allow_destructive`。参见 [AI 智能体（MCP）](AGENTS.md)。
- 在开放安装上，无论 `trusted_local_editing` 取何值，创建、列出和吊销助手令牌都只对通过这些检查的请求有效（设置了 `viewer.edition_password` 时，也可在编辑会话中进行）。
- `ng serve --host 0.0.0.0`，或不添加任何转发头的同一主机代理，会让发送 `Host: localhost` 的局域网客户端通过。反向代理必须发送 `X-Forwarded-For` 或 `Forwarded`。

> **警告：** 只有 loopback 检查是真正的边界；其他头都由客户端设置。同一主机上不添加上述任何头的反向代理、隧道或端口转发，与你的浏览器无法区分。切勿在同一主机的任何反向代理之后启用此选项。启用期间，本机的任何本地进程和任何账户都可以编辑。

### 在线地点搜索

`viewer.place_search_url` 默认为 `https://photon.komoot.io/api`。

- 设为 `""` 可关闭地址／商家查询，也可指向自托管的 Photon HTTP(S) 端点（不含凭据、查询参数或片段）。
- 浏览器只会收到 `place_search_enabled`，绝不会收到该 URL。
- 搜索需要编辑权限和一次明确的**在线搜索**点击。不会重试，也不会跟随重定向。
- 请求在五秒后超时；DNS 解析遵循操作系统解析器，可能耗时更长。

隐私、缓存与限制参见[在线地点搜索](VIEWER.md#在线地点搜索)。[Photon 演示服务政策](https://github.com/komoot/photon#demo-server)允许合理使用该项目，但不保证可用性；[Photon API 文档](https://github.com/komoot/photon/blob/master/docs/api-v1.md)定义了其 GeoJSON 格式。

### 查看器性能

仅为查看器覆盖全局的 `performance` 设置，例如在内存较小的 NAS 上。

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `mmap_size_mb` | *（取全局值）* | 查看器连接的 SQLite mmap 大小覆盖值。`0` 表示禁用 mmap。 |
| `cache_size_mb` | *（取全局值）* | 查看器连接的 SQLite 缓存大小覆盖值 |
| `pool_size` | `5` | 连接池大小（内存较小的系统请调低） |
| `thumbnail_cache_size` | `2000` | 内存中缩略图缩放缓存的最大条目数 |

未设置时，查看器使用全局的 `performance` 取值。推荐的 NAS 设置见[部署](DEPLOYMENT.md)。

---

## 性能

数据库性能设置。

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | SQLite 内存映射 I/O 的大小 |
| `cache_size_mb` | `128` | SQLite 缓存大小 |
| `wal_checkpoint_minutes` | `30` | 可选（随附文件中没有）。查看器后台 WAL 检查点之间的间隔（分钟）；`0` 表示禁用 |
| `slow_request_ms` | `1000` | 查看器 API 请求耗时超过这么多毫秒时记入日志（WARNING 级别，带 `SLOW` 标记）；`0` 表示禁用 |

周期性检查点（`PRAGMA wal_checkpoint(TRUNCATE)`）可让长期运行的安装保持较小的 WAL 文件；正常关闭时也会执行一次检查点。

---

## 存储

缩略图和嵌入的存放位置：默认是 SQLite 数据库中的 BLOB 列，也可以作为文件存放在磁盘上，以减小数据库体积。

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `mode` | `"database"` | 存储后端：`"database"`（SQLite BLOB）或 `"filesystem"`（磁盘文件） |
| `filesystem_path` | `"./storage"` | 文件系统模式的基准目录（`<path>/thumbnails/` 与 `<path>/embeddings/`） |

**文件系统模式细节：**
- 文件按照片路径的 SHA-256 哈希命名，并放在两个字符的子目录中（例如 `thumbnails/a3/a3f8..._640.jpg`）。
- 删除一张照片会移除与之关联的所有缩略图尺寸和嵌入文件。
- 该目录会在首次使用时自动创建。

---

## 插件

事件驱动的插件系统，用于响应评分事件。插件可以是 Python 模块、Webhook 或内置动作。

### 配置

```json
{
  "plugins": {
    "enabled": true,
    "high_score_threshold": 8.0,
    "webhooks": [
      {
        "url": "https://example.com/hook",
        "events": ["on_score_complete", "on_high_score"],
        "min_score": 8.0
      }
    ],
    "actions": {
      "copy_high_scores": {
        "event": "on_high_score",
        "action": "copy_to_folder",
        "folder": "/path/to/best-photos",
        "min_score": 9.0
      }
    }
  }
}
```

| 键 | 默认值 | 说明 |
|-----|---------|-------------|
| `enabled` | `false` | 总开关 — 为 false 时不会发出任何事件 |
| `high_score_threshold` | `8.0` | 触发 `on_high_score` 事件所需的最低聚合分 |
| `webhooks` | `[]` | 接收 JSON POST 载荷的 Webhook 端点列表 |
| `actions` | `{}` | 由事件触发的具名内置动作 |

### 支持的事件

| 事件 | 触发时机 | 载荷 |
|-------|---------|---------|
| `on_score_complete` | 每张照片评分完成之后 | `path`、`filename`、`aggregate`、`aesthetic`、`comp_score`、`category`、`tags` |
| `on_new_photo` | 当一张照片进入数据库时 | 同 `on_score_complete` |
| `on_high_score` | 当聚合分 ≥ `high_score_threshold` 时 | 同 `on_score_complete` |
| `on_burst_detected` | 当识别出一个连拍组时 | `burst_group_id`、`photo_count`、`best_path`、`paths` |

### 编写插件

把一个 `.py` 文件放进 `plugins/` 目录。按你想处理的事件名定义同名函数：

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

完整接口见 `plugins/example_plugin.py.example`。

### Webhook

每个 Webhook 会收到一个 JSON POST。内网和回环地址会被阻止：

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/IMG_001.jpg",
    "aggregate": 9.2,
    "aesthetic": 9.5,
    "comp_score": 8.8,
    "category": "portrait",
    "tags": "person, outdoor"
  }
}
```

Webhook 选项：`url`（必填）、`events`（事件名列表）、`min_score`（触发所需的最低聚合分）。

### 内置动作

| 动作 | 说明 | 选项 |
|--------|-------------|---------|
| `copy_to_folder` | 把照片复制到某个文件夹 | `folder`、`min_score` |
| `send_notification` | 记录一条通知 | `min_score` |

### API 端点

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/plugins` | 列出已加载的插件、Webhook 和动作 |
| `POST` | `/api/plugins/test-webhook` | 向某个 Webhook URL 发送测试载荷 |

---

## 照片胶囊

按主题分组的精选幻灯片，由你的照片库生成，并缓存 `freshness_hours` 小时。

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
    "mmr_moment_weight": 0.0,
    "freshness_hours": 24,
    "reverse_geocoding": true,
    "journey": {
      "min_distance_km": 50,
      "min_photos": 8,
      "time_gap_hours": 24
    },
    "faces_of": { "min_photos": 10 },
    "seasonal": { "min_photos": 10 },
    "golden": { "percentile": 99, "max_photos": 50 },
    "color_story": { "embedding_threshold": 0.75, "min_group_size": 8, "max_groups": 5 },
    "this_week_years_ago": { "min_photos_per_year": 3 },
    "monthly": { "min_photos": 8 },
    "yearly": { "min_photos": 20, "max_photos": 60 },
    "camera": { "min_photos": 15 },
    "tag_collection": { "min_photos": 15 },
    "seeded": {
      "num_seeds": 10,
      "min_photos": 8,
      "seed_lifetime_minutes": 1440,
      "time_window_days": 7,
      "embedding_threshold": 0.7,
      "location_radius_km": 30
    },
    "progress": { "min_improvement_pct": 5, "min_photos": 10, "period_months": 3 },
    "color_palette": { "min_photos": 8 },
    "rare_pair": { "max_shared_photos": 5, "min_score": 7.0, "min_photos": 3 }
  }
}
```

### 全局设置

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `min_aggregate` | `6.0` | 照片进入照片胶囊所需的最低聚合分 |
| `max_photos_per_capsule` | `40` | 每个胶囊最多的照片数（超过 5 张即启用 MMR 多样性） |
| `max_photo_overlap` | `0.2` | 两个胶囊之间共享照片的最大占比，超过则去重时删掉其中一个 |
| `mmr_lambda` | `0.5` | MMR 多样性权重：0 = 多样性最大化，1 = 质量最大化 |
| `mmr_moment_weight` | `0.0` | 可选权重，把每张照片的 `narrative_moment_confidence` 混入胶囊的 MMR 选择。`0.0` = 行为不变 |
| `freshness_hours` | `24` | 封面照片和种子胶囊的缓存 TTL 与轮换周期 |
| `reverse_geocoding` | `true` | 为位置/旅程胶囊标题启用离线反向地理编码（需要 `reverse_geocoder` 包） |

### 胶囊类型

| 类型 | 说明 |
|------|-------------|
| `journey` | 通过 GPS 聚类 + 时间间隔检测出的旅程。启用地理编码时，标题中会带上目的地名称。 |
| `faces_of` | 每位已识别人物的最佳照片 |
| `seasonal` | 按季节 + 年份分组的照片 |
| `golden` | 聚合分前 1% |
| `color_story` | 通过 CLIP 嵌入聚类得到的视觉相似分组 |
| `this_week` | “那些年的这一周” — 把“那年今日”扩展到 ±3 天 |
| `location` | 带地理标记、并经反向地理编码得到地名的照片簇 |
| `person_pair` | 一同出现的已命名人物两两组合 |
| `seeded` | 基于种子的发现：按时间、相似度、人物、标签、位置、氛围 |
| `progress` | 由季度评分趋势得出的“你的摄影水平正在提升” |
| `color_palette` | 由饱和度/单色特征得出的“本月色彩” |
| `rare_pair` | 高分照片中不常同框的人物组合 |
| `favorites` | 按年份和季节分组的收藏照片 |

### 基于维度的胶囊

由数据库列自动生成：

| 维度 | 分组依据 |
|-----------|-----------|
| `year` | 从 date_taken 提取的年份 |
| `month` | 从 date_taken 提取的年-月 |
| `week` | 从 date_taken 提取的年-周 |
| `camera` | 相机型号 |
| `lens` | 镜头型号 |
| `tag` | 照片标签（需要 `photo_tags` 表） |
| `day_of_week` | 星期（周日–周六） |
| `composition` | SAMP-Net 构图模式（rule_of_thirds、horizontal 等） |
| `focal_range` | 焦距分档：超广角（<24mm）、广角（24–35mm）、标准（36–70mm）、人像（71–135mm）、长焦（136–300mm）、超长焦（300mm 以上） |
| `category` | 照片内容类别（portrait、landscape、street 等） |
| `time_of_day` | 时段分档：清晨金色时刻、上午、正午、下午、傍晚金色时刻、夜晚 |
| `star_rating` | 用户星级（1–5 星） |

系统还会生成跨维度的组合（例如相机 × 年份、焦距分档 × 类别、类别 × 年份）。

### 幻灯片转场

每种胶囊类型都对应一种主题化的幻灯片转场：

| 转场 | 使用者 | 效果 |
|-----------|---------|--------|
| `crossfade` | 默认 | 300ms 的不透明度切换 |
| `slide` | journey、location、this_week | 从右侧滑入（500ms） |
| `zoom` | faces_of、color_story | 缩放 1.05→1.0 并淡入（400ms） |
| `kenburns` | golden、seasonal、star_rating、favorites | 在整张幻灯片时长内从 1.0 缓慢放大到 1.08 |

### 反向地理编码

位置和旅程胶囊通过 `reverse_geocoder` 包进行离线反向地理编码（本地 GeoNames 数据集，约 30MB，不调用任何 API）。结果会以 0.1° 的网格分辨率（约 11 公里）缓存。

安装：`pip install reverse_geocoder`

设置 `"reverse_geocoding": false` 可禁用它并回退为显示坐标。

## 相似照片分组

相似照片选片的设置，它使用 CLIP/SigLIP 嵌入把视觉上相似的照片归为一组：

```json
{
  "similarity_groups": {
    "default_threshold": 0.85,
    "min_group_size": 2,
    "max_photos": 10000,
    "max_group_size": 50
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `default_threshold` | `0.85` | 把两张照片视为相似所需的最低余弦相似度（0.0–1.0）；越低，分组越大也越宽松 |
| `min_group_size` | `2` | 构成一个相似照片分组所需的最少照片数 |
| `max_photos` | `10000` | 参与比较时最多载入的照片数（开销按 O(n²) 增长） |
| `max_group_size` | `50` | 每个分组最多的照片数；更大的分组会被拆开 |

## 自动选片

选片暗房的一键自动选片（`POST /api/culling/auto`，受编辑权限限制）。它会在一次遍历中处理整个范围：全部分组，或仅连拍／相似照片／场景，还可以进一步限定到某个相册或日期区间。每个分组保留其最佳照片，外加落在由严格度设定的余量之内的全部照片（与暗房滑块相同），并以每组的下限兜底，其余的一律淘汰。

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `default_strictness` | `50` | 请求中未给出 `strictness` 时使用的保留预算（0–100）；数值越大，每组保留的照片越少 |
| `highlights_min` | `8.0` | 应用时，某组的最佳照片要被收进可选的**精选**相册所需的最低聚合分 |

- `dry_run` 默认开启，会返回逐组的保留/淘汰预览。
- 应用时会记录 `source='culling'` 的比较行，并计入一次自动重训练。见 [网页查看器 — 自动选片](VIEWER.md#自动选片)。
- 同一设置也供 `python facet.py --auto-cull` 使用（参见[命令行选片](COMMANDS.md#命令行选片)）；其选片规则读取自服务器配置，而不是 `--config`。

## 自动重训练

控制个人排序模型（“我的偏好”）何时重训练。每一次选片确认和每一次评分改动，都会累加到每个用户的计数器上。越过 `threshold` 会武装一次重训练，它在你静止 `idle_seconds` 之后才开始，因此不会拖慢你的评分。

```json
{
  "auto_retrain": {
    "threshold": 25,
    "idle_seconds": 60,
    "backend": "native"
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `threshold` | `25` | 武装一次重训练所需的新比较数；如果你一次评分的批量非常大，可以调高它 |
| `idle_seconds` | `60` | 已武装的重训练开始之前，需要多少秒没有评分/选片活动；`0` 表示立即开始 |
| `backend` | `"native"` | `"native"` 在本地训练；`"external"` 只保留偏好和计数。参见[外部学习后端](#外部学习后端) |

环境变量会覆盖 `threshold` 和 `idle_seconds`（对 Docker 很有用）：

```bash
FACET_RETRAIN_THRESHOLD=100 FACET_RETRAIN_IDLE_S=300 python viewer.py
```

| 变量 | 覆盖的设置 |
|----------|-----------|
| `FACET_RETRAIN_THRESHOLD` | `auto_retrain.threshold` |
| `FACET_RETRAIN_IDLE_S` | `auto_retrain.idle_seconds` |

- 无效的 `threshold` 或 `idle_seconds` 会回退到 JSON 中的取值，再回退到内置默认值。两者都只在启动时读取；改动需要重启。
- 无效的 `auto_retrain.backend` 会回退为 `"external"`（见下文）。
- 一次未能在留出数据上超过当前模型的重训练不会保存任何内容。

### 外部学习后端

`"backend": "external"` 会保留评分、比较和待处理计数，但绝不在本地训练或评估个人排序模型、选片头或学习得到的权重。当由运维人员运行的独立流程来训练并发布分数时使用它。Facet 不会启动任何外部工作进程。

在外部模式下：
- 个人排序模型、选片头和权重学习的手动命令会报告训练已推迟。
- 选片概率不可用；“比较”的学习权重与置信度响应会返回 `available: false`。
- 常规的照片评分和投票不受影响。

格式错误的 `auto_retrain` 块、不是 `"native"` 或 `"external"` 的 `backend`，或无法读取的配置，都会选用外部模式并记录一条警告。没有 `backend` 键的有效配置使用原生模式。

## 按题材区分的选片配置

按题材预设，一次点击即可设置每一个选片旋钮，在选片暗房的选择器中使用。体育只保留一长串连拍中最清晰的一张；婚礼保留更多变体并要求睁眼；演唱会放宽眼睛/表情门槛；野生动物则去掉人脸门槛。

```json
{
  "cull_profiles": {
    "default": "balanced",
    "profiles": {
      "balanced": { "label_key": "culling.profiles.balanced", "strictness": 50, "eyes_closed_max": 4.0, "poor_expression_min": 4.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wedding":  { "label_key": "culling.profiles.wedding",  "strictness": 35, "eyes_closed_max": 5.0, "poor_expression_min": 5.0, "keep_min_per_group": 2, "similarity_threshold": 90 },
      "sports":   { "label_key": "culling.profiles.sports",   "strictness": 85, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 80 },
      "concert":  { "label_key": "culling.profiles.concert",  "strictness": 55, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wildlife": { "label_key": "culling.profiles.wildlife", "strictness": 70, "eyes_closed_max": 0.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 82 }
    }
  }
}
```

| 设置 | 说明 |
|---------|-------------|
| `default` | 客户端未存储任何预设时使用的预设 id |
| `profiles.<id>.label_key` | 该预设显示名称的 i18n 点分路径（`culling.profiles.*`） |
| `profiles.<id>.strictness` | 使用该预设时自动选片的保留预算（0–100） |
| `profiles.<id>.eyes_closed_max` | 睁眼评分（0–10）低于或等于此值时该人脸算作闭眼（覆盖 `face_detection.eyes_closed_max`） |
| `profiles.<id>.poor_expression_min` | 表情/微笑评分（0–10）低于此值时该人脸算作表情欠佳（覆盖 `face_detection.poor_expression_min`） |
| `profiles.<id>.keep_min_per_group` | 该预设下自动选片保留集的每组下限 |
| `profiles.<id>.similarity_threshold` | 选中该预设时暗房采用的相似度分组阈值（百分比） |

`GET /api/culling/profiles` 返回有序的预设列表以及默认值。`POST /api/culling/auto` 和 `POST /api/culling-group/faces` 都接受一个可选的 `profile` id；请求中显式给出的 `strictness`/`min_keep_per_group` 始终优先于预设。

## 场景

场景视图的设置，该视图把连拍代表帧按时间顺序聚成场景（依据拍摄时间间隔切分），便于按故事顺序选片：

```json
{
  "scenes": {
    "gap_minutes": 20.0,
    "min_size": 2,
    "max_photos": 5000,
    "max_scene_size": 60,
    "adaptive": true,
    "adaptive_k": 6.0
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `gap_minutes` | `20.0` | 相邻两张连拍代表帧之间超过这么多分钟时，就开始一个新场景（`adaptive` 开启时它是下限） |
| `min_size` | `2` | 一个场景要被显示所需的最少照片数 |
| `max_photos` | `5000` | 用于场景分组时最多载入的连拍代表帧数 |
| `max_scene_size` | `60` | 更大的场景会在其内部最大的间隔处再次切分 |
| `adaptive` | `true` | 把间隔放宽到本次拍摄相邻间隔中位数的 `adaptive_k` 倍（快速连拍时收紧，稀疏的旅行照片则放宽） |
| `adaptive_k` | `6.0` | `adaptive` 开启时施加于间隔中位数的乘数 |
| `split_on_moment_change` | `false` | 已计算叙事时刻时，还会在主导时刻发生变化并持续 `moment_split_min_run` 帧的位置切分 |
| `moment_split_min_run` | `4` | 新时刻必须连续持续多少帧才会强制产生一个场景边界 |

## 叙事时刻

无需训练，为每张照片的场景/活动“时刻”打标签。默认的 **general** 词表覆盖 `celebration`、`dining`、`beach`、`water_activity`、`mountains`、`nature_wildlife`、`cityscape`、`travel_landmark`、`concert`、`sports`、`group_gathering`、`portrait`、`children`、`pets`、`nightlife`、`ceremony`、`scenic_landscape`、`snow_winter`、`home_indoor`、`road_vehicle` 和 `other`。`wedding` 作为可选题材随附。由 `--detect-moments` 填充（每次扫描结束时也会运行），并以场景名称和照片库筛选条件的形式呈现。

Facet 会把每张照片的 AI 描述（只编码一次并存储，即 `caption_embedding`）与各时刻的文本提示词比较，取最好的匹配。没有描述时则使用图像嵌入。描述的匹配更干净，因此 `caption` 信号采用比 `image` 回退更高的阈值，且按后端分别调校。`transformers`（SigLIP）的取值是保守的默认值；如果你运行的是 SigLIP 配置档，请重新调校它们。

```json
{
  "narrative_moments": {
    "enabled": true,
    "prompt_template": "a photo of {desc}",
    "default_event_type": "general",
    "pooling": "max",
    "caption_min_confidence": 0,
    "thresholds": {
      "caption": {
        "open_clip": { "min_confidence": 0.30, "min_margin": 0.02 },
        "transformers": { "min_confidence": 0.12, "min_margin": 0.01 }
      },
      "image": {
        "open_clip": { "min_confidence": 0.20, "min_margin": 0.01 },
        "transformers": { "min_confidence": 0.10, "min_margin": 0.01 }
      }
    },
    "priors": {
      "enabled": true, "weight": 0.04, "caption_tag_scale": 0.25,
      "rules": [
        { "kind": "structural", "when": { "is_group_portrait": true, "face_count_min": 4 }, "boost": { "group_gathering": 1.0 } },
        { "kind": "tag", "when": { "tags_any": ["beach", "ocean", "sand"] }, "boost": { "beach": 0.8 } }
      ],
      "event_types": { "wedding": { "rules": [ { "kind": "tag", "when": { "tags_any": ["cake"] }, "boost": { "cake_cutting": 1.0 } } ] } }
    },
    "vlm_tiebreak": { "enabled": false, "min_confidence": 0.0, "min_margin": 0.04 },
    "transitions": { "stay_prob": 0.7, "forward_bias": 0.0, "weight": 0.3 },
    "event_types": { "general": { "beach": ["people at a sandy beach by the sea", "..."], "...": [] }, "wedding": { "vows": ["the couple exchanging vows at the altar", "..."] } }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 总开关；关闭时 `--detect-moments` 与扫描钩子都不做任何事 |
| `prompt_template` | `"a photo of {desc}"` | 编码前套用在每条提示词外层的模板 |
| `default_event_type` | `"general"` | 当前生效的 `event_types` 词表（`general` = 20 个时刻；`wedding` 为可选） |
| `pooling` | `"max"` | 每个时刻的得分 = 最好的单条提示词匹配 |
| `caption_min_confidence` | `0` | 大于 0 时，描述生成会跳过未标注、标为 `other`、或置信度低于此值的照片；`0` = 不设门槛 |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`，image `0.20`/`0.10` | top-1 余弦低于此值的照片记为 `other`（先按信号再按后端取值） |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`，image `0.01`/`0.01` | top-1 与 top-2 余弦的最小差距；低于它则该帧记为 `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | 仅用于打破近似平局的轻微人脸/标签修正；`weight` 限制每次加成的上限 |
| `priors.caption_tag_scale` | `0.25` | 在 `caption` 信号上压低**标签**规则的权重；结构性规则保持完整权重 |
| `priors.rules` | （general 规则集） | `{kind, when, boost}` 规则列表（见下文） |
| `priors.event_types.<et>.rules` | `wedding` 覆盖 | 对应词表生效时**替换**全局 `rules` 的规则 |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | 相邻帧之间的时间线平滑（`weight=0` = 不平滑） |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | 在 16gb/24gb 上，仅用配置档的 VLM 重新分类低置信度或低差距的帧 |
| `event_types` | `general` + `wedding` | 每种事件类型的 `{moment: [提示词同义表]}`；设置 `default_event_type` 可切换题材，也可添加你自己的 |

`priors.rules` 的格式：
- `kind`：`structural`（人脸几何）或 `tag`。
- `when`（必须全部满足）：`is_group_portrait`、`face_count_min`/`face_count_max`、`face_ratio_min`/`face_ratio_max`、`tags_any`、`tags_all`。
- `boost`：`{moment: amount}`。当前词表中没有的时刻会被跳过。

VLM 平局裁决在 `--detect-moments` / `--recompute-moments` 期间运行。

> **描述回填的成本。** 描述嵌入只计算一次并存储下来。一次扫描只会编码它新增的描述，但在已有图库上第一次完整跑一遍会编码全部描述：GPU 上很快，CPU 上则要数小时。请运行一次 `python facet.py --detect-moments`（推荐用 GPU）；加上 `--limit N` 可以先在样本上验证。

**发现属于你图库的专属词表。** `python facet.py --discover-moments` 会对存储的 `caption_embedding` 向量做聚类，依据各簇的描述为其命名，并把一个 `event_types.discovered` 块写入 `scoring_config.discovered.json`。它绝不会改写正在生效的配置。要采纳它，请把 `discovered` 复制到 `event_types` 中，把 `default_event_type` 设为 `discovered`，再运行 `--recompute-moments`。`--discover-min-cluster-size N` 控制粒度（越小 = 时刻越多、越细）。

## OCR

照片内文字搜索：把你照片*里面*的文字（路牌、店招、比赛号码布、书脊、幻灯片、白板、扫描文档）读入 `photos.ocr_text`。之后这些文字就能像任何描述或标签一样在照片库搜索框中被检索到；`GET /api/search?scope=text` 只搜索文字字段。

**默认关闭**，而且需要安装一个引擎：

```bash
pip install easyocr           # 或者：pip install -e .[ocr]
```

然后启用它并运行这个遍次：

```json
{
  "ocr": {
    "enabled": false,
    "languages": ["en", "fr"],
    "min_confidence": 0.4,
    "full_resolution": false
  }
}
```

```bash
python facet.py --detect-text      # 仅处理从未评估过的照片
python facet.py --recompute-text   # 重新读取整个图库
```

| 键 | 默认值 | 说明 |
|-----|---------|-------------|
| `enabled` | `false` | 总开关；为 `false` 时 `--detect-text` 会拒绝运行 |
| `languages` | `["en", "fr"]` | 传给引擎的语言代码；每次运行只用一个书写系统族（easyocr 会拒绝例如 `en` + `ja`） |
| `min_confidence` | `0.4` | 丢弃评分低于此值的检测结果（0–1）；噪声多时调高，想抓住模糊文字时调低 |
| `full_resolution` | `false` | 对原始文件而不是 640px 缩略图做 OCR（慢得多；离线时回退到缩略图） |

说明：
- 照片尚未被评估时 `ocr_text` 为 `NULL`，没有文字时为 `''`。`--detect-text` 只读取 `NULL` 的照片；`--recompute-text` 会重读全部。
- **无需 `--rebuild-fts`：** 这个遍次在写入的同时更新搜索索引。只有在 OCR 出现之前创建的数据库才需要 `python database.py --rebuild-fts`，而 `init_database` 会替你处理。
- 640px 缩略图已足以辨认路牌、海报和文档标题。

**引擎。** 默认是 `easyocr`（Apache-2.0，基于 PyTorch），它复用了 Facet 本就安装的技术栈。它的权重（约 113MB）在首次运行时从项目自己的 GitHub 发布页下载。没有 easyocr 时会使用 `tesseract` 二进制文件加上 `pytesseract`，但它识别自然场景文字的效果较差。两者都没有安装时，这个遍次会报错退出。

**成本。** 在 CPU 上每张缩略图大约耗时 0.4 秒，因此 5 万张照片的图库是一次通宵的一次性作业；之后的扫描只会处理新照片。当 torch 报告有 GPU 时会自动使用 GPU。

## 导出与选片目标位置

相册导出（`POST /api/albums/{id}/export`，模式 `copy`/`symlink`）和选片后导出／清理（`POST /api/cull/apply`，动作 `copy_keeps` / `move_rejects`）都会写入一个 `target_dir`。它必须解析到某个被允许的根目录之下，否则请求会在触碰任何文件之前就被拒绝。

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    },
    "cull": {
      "allow_trash": false
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `allowed_target_dirs` | *（键不存在）* | 除扫描目录（始终允许）之外，导出和选片后导出／清理还可以写入的额外根目录 |
| `cull.allow_trash` | `false` | 是否允许选片后导出／清理的 `trash_rejects` 动作（经由 `send2trash` 送入操作系统回收站，可恢复）；关闭时该选项会被隐藏 |

**多帧照片组与批量操作。** 开启 `hide_brackets` / `hide_panoramas`（默认如此，见[网页查看器 — 默认筛选](VIEWER.md#默认筛选条件)）时，选择项只包含每组的代表帧，因此批量操作只作用于那一帧。选片后导出／清理的 `include_sequence_siblings` 选项会把匹配到的照片扩展到它所在的整组；见[网页查看器 — 选片后导出／清理 § 多帧照片组](VIEWER.md#选片后导出清理)。

**解析顺序。** 允许的根目录先取 `allowed_target_dirs`，再取每一个扫描目录（各用户的、共享的，以及 `path_mapping` 的目标）。导出到照片树内部无需任何配置；目标位于其外部时，就需要在这里加一条。检查之前会先解析软链接和 `..`（`os.path.realpath()`），因此指向被允许的根目录之外的链接会被拒绝。

**按设计失败即关闭。** 既没有 `allowed_target_dirs`，也没有扫描目录时，复制/软链接/移动导出会被拒绝。

**排查“拒绝访问”。** 网页界面只显示一条通用的“拒绝访问”提示。要了解原因，请打开浏览器的网络面板，找到失败的 `/api/cull/apply` 或 `/api/albums/{id}/export` 请求，读取其 `detail` 字段：要么是这个白名单，要么是编辑会话已过期。真正的文件系统权限错误看起来则不同：请求本身成功，响应中的 `errors` 计数不为零，而且服务器日志中每个文件都有一条栈回溯。容器场景见[部署 — 容器路径语义](DEPLOYMENT.md#容器路径语义)。

见[网页查看器 — 选片后导出／清理](VIEWER.md#选片后导出清理)和[网页查看器 — 导出到后期软件](VIEWER.md#导出到后期软件)。

## 社交平台导出

按社交比例、以主体取景的裁切预设（`GET /api/photo/social_crop`，受编辑权限限制）。每个预设都会把全分辨率原图裁切为该比例下最大的矩形，并以主体为中心。主体取 BiRefNet 主体框（`photos.subject_bbox`），否则取人脸框并集，再否则取图像中心。见[网页查看器 — 下载](VIEWER.md#下载)。

```json
{
  "social_export": {
    "presets": {
      "square":       { "label_key": "social_export.presets.square",       "aspect": "1:1" },
      "portrait_4x5": { "label_key": "social_export.presets.portrait_4x5", "aspect": "4:5" },
      "story_9x16":   { "label_key": "social_export.presets.story_9x16",   "aspect": "9:16" }
    },
    "jpeg_quality": 92
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | 该预设显示名称的 i18n 点分路径（`social_export.presets.*`） |
| `presets.<id>.aspect` | — | 以 `"w:h"` 表示的目标比例（例如 `1:1`、`4:5`、`9:16`） |
| `jpeg_quality` | `92` | 导出裁切图的 JPEG 质量 |

受 `viewer.features.show_social_export`（默认 `true`）控制。主体框由扫描时的显著性遍次以及 `--recompute-saliency` 写入；较旧的照片使用人脸裁切或居中裁切。

## 作品集导出

把一个相册导出为自包含的静态 HTML 图库，可上传到任意网页主机（`POST /api/albums/{album_id}/export-portfolio`，受编辑权限限制）。

- 输出目录包含 `index.html`（缩略图网格和灯箱，无外部或 CDN 引用）、一个存放按序命名 JPEG 的 `assets/` 文件夹（不含图库路径），以及一个 `manifest.json`。
- 每张照片使用**原图**（缩放到 `max_edge`），原图不可达时使用存储的 640px 缩略图。清单会记录使用的是哪一种。
- 再次导出只会改写它自己的文件。

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `max_photos` | `500` | 更大的相册会被拒绝（导出是同步的） |
| `max_edge` | `2048` | 导出原图的长边上限（像素）；请求中可以覆盖它（限制在 256–8000 之间） |
| `jpeg_quality` | `88` | 导出图像的 JPEG 质量 |

`target_dir` 使用与其他导出相同的白名单（`viewer.export.allowed_target_dirs` 加上扫描目录 — 见[导出与选片目标位置](#导出与选片目标位置)）。受 `viewer.features.show_portfolio_export`（默认 `true`）控制。见[网页查看器 — 作品集导出](VIEWER.md#作品集导出)。

## 智能体端点（MCP）

在 `POST /mcp` 上提供 [AI 智能体（MCP）](AGENTS.md) 中描述的工具：读取、控制已打开的标签页，并按令牌级别修改评分、标签和相册、选片与删除。默认开启。

在开放安装（没有 `viewer.password`）上：
- `/mcp` 只提供一个只读匿名密钥，它不会展示开放的 `/api` 本来没有展示的任何内容。
- 新令牌为 `readonly`，除非已开启 `viewer.trusted_local_editing`，或会话已用 `viewer.edition_password` 登录：两者都可创建完全编辑令牌，但该令牌仅对来自同一台机器的请求具有编辑权限。
- 令牌只能在运行 Facet 的电脑上创建、列出和吊销（设置了 `viewer.edition_password` 时，也可在编辑会话中进行）。

```json
{
  "viewer": {
    "mcp": {
      "enabled": true,
      "bridge": true,
      "max_rows": 100,
      "max_bytes": 60000,
      "max_image_bytes": 262144,
      "call_timeout_s": 30,
      "semantic_timeout_s": 120,
      "rate_per_min": 120,
      "write_rate_per_min": 30,
      "tool_profile": "full",
      "allow_destructive": false,
      "inpage_tools": true,
      "allowed_origins": []
    }
  }
}
```

| 键 | 默认值 | 说明 |
|-----|---------|-------------|
| `enabled` | `true` | `/mcp` 与 `/api/mcp/*` 的总开关 |
| `bridge` | `true` | 允许浏览器标签页桥接（`/api/mcp/bridge`），让 `ui_*` 工具能到达标签页；需要单个 worker |
| `max_rows` | `100` | 单次工具结果的最大行数（1 到 500）；多余的行会被丢弃并设置 `truncated: true` |
| `max_bytes` | `60000` | 单次工具结果序列化后的最大字节数（4000 到 500000）。 |
| `max_image_bytes` | `262144` | `get_thumbnail` 或 `contact_sheet` 返回的图像大小上限（32768 到 2097152）；不计入 `max_bytes` |
| `call_timeout_s` | `30` | 单次工具调用的超时秒数（1 到 300），也是 `ui_*` 等待标签页的时间（`tab_timeout`） |
| `semantic_timeout_s` | `120` | `semantic_search` 的超时秒数（1 到 300）；它要加载嵌入模型，因此需要更长时间。 |
| `rate_per_min` | `120` | 每个令牌每分钟的工具调用次数（最小为 1）。 |
| `write_rate_per_min` | `30` | 每个令牌每分钟的写入调用次数（最小为 1），单独计算，这样读取不会饿死写入 |
| `tool_profile` | `"full"` | `"full"` 列出所有允许的工具；`"core"` 列出适合小模型的 11 个工具 |
| `allow_destructive` | `false` | 允许 `delete_photos`、`cull_apply` 的 `move_rejects`/`trash_rejects`，以及带 `allow_reassign` 的 `assign_faces` |
| `inpage_tools` | `true` | 允许已登录的标签页从页面调用服务器的工具（`GET /api/mcp/inpage_tools`、`POST /api/mcp/call`） |
| `allowed_origins` | `[]` | 在重写 `Host` 的代理之后，允许打开标签页桥接的额外浏览器来源（例如 `["https://photos.example.com"]`）；不是 CORS 键 `viewer.allowed_origins` |

说明：
- **`enabled: false`** 会关闭 `/mcp` 和 `/api/mcp/*`（桥接以关闭码 4404 断开）。**`bridge: false`** 会拒绝桥接，并让 `ui_*` 工具返回错误。
- **`write_rate_per_min`** 涵盖写入类工具，包括 `cull_apply` 和 `delete_photos` 的试运行；参见 [AI 智能体](AGENTS.md#修改内容)。
- **`"core"`** 列出 `status`、`search_photos`、`semantic_search`、`get_photo`、`filter_options`、`library_stats`、`ui_show_photos`、`set_rating`、`set_favorite`、`set_rejected`、`album_add_photos`。只有列表会变化；若密钥的级别允许，其他工具仍可调用。任何其他取值都视为 `"full"`。参见 [AI 智能体](AGENTS.md#权限级别)。
- **`allow_destructive: false`** 会隐藏 `delete_photos`；另外两项会返回 `feature_disabled` 并点名此键。参见 [AI 智能体](AGENTS.md#破坏性操作先预览再确认)。
- **`inpage_tools`** 以该会话当前的级别、以会话的身份运行工具。关闭时，`/api/auth/status` 中的 `features.mcp_inpage` 为 false。参见 [AI 智能体](AGENTS.md#页面内-webmcp浏览器智能体)。
- 超出范围的数字会被限制到边界；类型错误的值会使用默认值。改动在配置重新加载时生效，无需重启。

## 照片相框／展示模式

通过三个使用静态令牌的端点（`GET /api/frame/photos`、`GET /api/frame/image/{id}`、`GET /api/frame/next`），把精选的“最佳照片”提供给无需登录的展示设备：智能相框、Home Assistant 仪表盘、ImmichFrame / Immich-Kiosk 风格的展示屏。`tokens` 列表为空即禁用该功能（这些端点返回 404）。响应中绝不包含文件路径；照片通过签名 id 来寻址。

```json
{
  "frame": {
    "tokens": [],
    "count": 20,
    "max_count": 100,
    "min_aggregate": 7.0,
    "max_edge": 1920,
    "favorites_only": false,
    "categories": []
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `tokens` | `[]` | 相框令牌，每台设备一个长随机字符串；删掉某一个即可吊销它。**为空 = 功能禁用。** |
| `count` | `20` | `/api/frame/photos` 默认返回的照片数 |
| `max_count` | `100` | `count` 查询参数的硬上限 |
| `min_aggregate` | `7.0` | 照片被选入所需的最低聚合分 |
| `max_edge` | `1920` | 提供的 JPEG 的长边上限（像素）；`max_edge` 查询参数只能调低它 |
| `favorites_only` | `false` | 为 `true` 时只选入已收藏的照片 |
| `categories` | `[]` | 类别名白名单（为空 = 所有类别） |

可用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成令牌。

精选过程会排除已淘汰、废片（`junk_kind`）和闭眼照片，再套用分数、收藏和类别筛选，然后按分数加权随机抽样。Home Assistant 的配方见[网页查看器 — 照片相框／展示模式端点](VIEWER.md#数码相框与展示屏端点)。

> **警告：** 相框令牌不是用户登录凭据。在[多用户模式](#用户)下，它会忽略每个用户的私有 `directories`，并可读取所有用户的照片，而不只是 `shared_directories`。只有当每一位用户都能接受这一点时，才签发相框令牌。

## 手机自动上传

在 `/dav` 下提供一个极简的 **WebDAV** 端点，让手机自动上传应用（PhotoSync 之类）可以把照片推送到一个**收件目录**，随后由 `facet.py --watch` 为其评分。访问方式是 HTTP Basic，使用**共享设备凭据**（`username` / `password`），而不是用户账号。

- 在 `username`、`password` 和 `inbox_dir` 都设置之前，`/dav` 返回 **404**。
- 所有操作都被限制在 `inbox_dir` 之内；目录穿越、绝对路径和软链接逃逸都会被拒绝。
- 上传以原子方式写入，并受 `max_file_mb` 上限约束。

```json
{
  "upload": {
    "username": "",
    "password": "",
    "inbox_dir": "",
    "max_file_mb": 500
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `username` | `""` | HTTP Basic 用户名（共享设备凭据）。**为空 = 功能禁用。** |
| `password` | `""` | HTTP Basic 密码；请使用长随机字符串。**为空 = 功能禁用。** |
| `inbox_dir` | `""` | 上传收件目录的绝对路径，按需创建。**为空 = 功能禁用。** |
| `max_file_mb` | `500` | 单个文件的大小上限（MB）；超出上限的上传会被中止，且不会留下部分文件 |

请把 `inbox_dir` 指向某个被扫描的目录（或其子目录），这样 `facet.py --watch` 就能在上传落地时为其评分。

支持的方法：`OPTIONS`、`PROPFIND`（深度 0/1）、`MKCOL`、`PUT`、`MOVE`、`DELETE`、`GET`、`HEAD`（不支持 `LOCK`/`UNLOCK`）。缺失或错误的 `Authorization` 头会得到 `WWW-Authenticate: Basic realm="Facet upload"`。PhotoSync 的配置方法以及一个 `curl` 冒烟测试见[网页查看器 — 手机自动上传](VIEWER.md#手机自动上传)。

## 废片清理

基于**存储的图像嵌入**（不解码图像）标记非照片“废片”：截图、扫描文档、收据、表情包、演示幻灯片。每种类型都带有一组文本提示词，匹配度最高的那条提示词代表该类型。

- 只有当最佳废片类型既达到 `min_confidence`，**并且**比最好的 `not_junk` 提示词高出 `min_margin` 时，照片才会被标记。
- 否则就存为 `not_junk`（已评估且干净）。`NULL` 表示尚未评估。
- `--detect-junk` 只标注 `NULL` 的照片（扫描结束时也会运行）；`--recompute-junk` 会重新检查整个图库。
- 结果写入 `photos.junk_kind`，在查看器的**废片清理**队列中复核（[VIEWER.md](VIEWER.md#废片清理)）。

```json
{
  "junk_sweep": {
    "enabled": true,
    "prompt_template": "{desc}",
    "pooling": "max",
    "thresholds": {
      "open_clip": { "min_confidence": 0.2, "min_margin": 0.06 },
      "transformers": { "min_confidence": 0.1, "min_margin": 0.02 }
    },
    "kinds": {
      "screenshot": ["a screenshot of a phone user interface", "..."],
      "document": ["a scanned document", "..."],
      "receipt": ["a close-up photo of a paper receipt", "..."],
      "meme": ["a meme with overlaid text", "..."],
      "slide": ["a presentation slide", "..."]
    },
    "not_junk_prompts": ["a natural photograph", "a candid photo of people", "..."]
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 在 `--detect-junk` / `--recompute-junk` 期间以及扫描结束时运行废片检测 |
| `prompt_template` | `"{desc}"` | 施加于每条提示词的格式串（`{desc}` = 提示词本身）；默认保持不变 |
| `pooling` | `"max"` | 把各提示词的得分汇总回类型的方式：`max`（最好的单条提示词）或 `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`，transformers `0.1` | 最佳废片类型所需的最低得分（按后端分别设定；CLIP/`open_clip` 的得分低于 SigLIP/`transformers`） |
| `thresholds.<backend>.min_margin` | open_clip `0.06`，transformers `0.02` | 最佳废片类型必须比最好的 `not_junk` 对照提示词高出多少，照片才会被标记 |
| `kinds` | screenshot/document/receipt/meme/slide | `{kind: [提示词同义表]}`；可以自由添加、删除或重命名类型 |
| `not_junk_prompts` | 8 条照片提示词 | 描述真实照片的提示词，用来把真正的照片挡在队列之外 |

## AI 点评

VLM 点评（16gb/24gb 配置档）的提示词设置。点评会把评分拆解、扣分项和 EXIF 提供给 VLM，并把它的回复显示为观察／评价／建议三段。

- 评价部分涵盖构图、色彩与光线、对焦/景深与技术执行、主体与瞬间，并与指标相互印证。
- 它按照片缓存（`photos.vlm_critique`，翻译存放在 `vlm_critique_translated`）；`refresh` 可重新生成。
- 它针对存储的缩略图运行，因此 RAW 文件也能使用。

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `critique.vlm.max_new_tokens` | `320` | 生成结构化 VLM 点评的 token 预算 |

见[网页查看器 — AI 点评](VIEWER.md#ai-点评)。

## VLM 后端

选择用于生成描述/标签的视觉语言模型在哪里运行。`local`（默认）使用 16gb/24gb 配置档内置的 Qwen 模型。两种远程后端则使用外部服务器，从而让**本身不带本地 VLM 的 legacy/8gb 配置档**也能生成描述和做 VLM 打标签。

```json
{
  "vlm_backend": {
    "type": "local",
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen2.5vl:7b",
      "timeout_seconds": 120
    },
    "openai_compatible": {
      "base_url": "http://localhost:1234/v1",
      "api_key": "",
      "model": "qwen2.5-vl-7b",
      "timeout_seconds": 120
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `type` | `"local"` | `local`（内置 Qwen）、`ollama`（Ollama REST API）或 `openai_compatible`（LM Studio、vLLM、OpenRouter 等） |
| `ollama.base_url` | `"http://localhost:11434"` | Ollama 服务器的基础 URL（图片发送到 `POST /api/generate`） |
| `ollama.model` | `"qwen2.5vl:7b"` | Ollama 模型标签（必须是服务器上已拉取的视觉模型） |
| `ollama.timeout_seconds` | `120` | Ollama 调用的单次请求超时 |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | 基础 URL，**需包含 `/v1` 后缀**（请求发往 `{base_url}/chat/completions`，图片作为 `image_url` 的 data URI 传入） |
| `openai_compatible.api_key` | `""` | 以 `Authorization: Bearer <key>` 发送；无需密钥的本地服务器留空即可 |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | 传给该端点的模型名 |
| `openai_compatible.timeout_seconds` | `120` | OpenAI 兼容调用的单次请求超时 |

该后端驱动照片描述生成（`--generate-captions` 和 `/api/caption`）、VLM 点评（`/api/critique?mode=vlm`）、VLM 重新打标签（`--recompute-tags-vlm`），以及叙事时刻的平局裁决。远程请求失败只会让那一张照片失败（记入日志，没有标签或描述）。扫描过程中的打标签仍使用配置档自带的标签模型；要把远程后端应用到已有图库，请运行 `--recompute-tags-vlm`。

## 成像缺陷属性

仅供参考的成像缺陷标签。`--recompute-distortions` 会把每张照片存储的 CLIP/SigLIP 嵌入与常见缺陷（运动模糊、偏色、过度锐化……）的提示词比较，并存储可能存在的缺陷。它们绝不影响评分；这些标签会在点评对话框中以警告标签的形式呈现。

```json
{
  "distortion_attributes": {
    "enabled": true,
    "top_n": 5,
    "thresholds": {
      "open_clip":    { "temperature": 0.02, "min_confidence": 0.6 },
      "transformers": { "temperature": 0.05, "min_confidence": 0.6 }
    },
    "vocabulary": {}
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 在 `--recompute-distortions` 期间计算成像缺陷属性 |
| `top_n` | `5` | 每张照片最多保留的缺陷标签数 |
| `thresholds.<backend>.temperature` | open_clip `0.02`，transformers `0.05` | 施加于提示词得分的 softmax 温度，按嵌入后端分别取值（尺度不同，与 `narrative_moments` 一样） |
| `thresholds.<backend>.min_confidence` | `0.6` | 缺陷标签被保留所需的最低概率 |
| `vocabulary` | `{}` | 对内置提示词的可选覆盖（`{attribute: [提示词同义表]}`）；为空 = 使用默认值 |

## 肤色

人像肤色的参考性检查。`--recompute-skin-tone` 会测量存储的人脸缩略图上的脸颊颜色，并标出肤色偏绿、偏品红、偏蓝或偏黄的人像。它绝不影响评分；结果会在点评对话框中以一条说明的形式呈现。

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `cast_delta_threshold` | `12.0` | 与自然肤色之间的最小 CIEDE2000 距离，超过它才会判定为偏色 |

## Immich 同步

通过 REST API 把 Facet 的星级和收藏单向同步到 [Immich](https://immich.app/) 服务器。资源通过 `path_map` 按 `originalPath` 匹配。运行 `--immich-sync`（先用 `--immich-test` 检查）；见[命令 — Immich 同步](COMMANDS.md#immich-同步)。

```json
{
  "immich": {
    "url": "",
    "api_key": "",
    "path_map": [
      { "facet_prefix": "", "immich_prefix": "" }
    ],
    "push": {
      "ratings": true,
      "favorites": true,
      "rejected": false,
      "top_picks_album": "",
      "top_picks_min_rating": 4
    },
    "webhook": {
      "token_env": "",
      "header": "x-facet-token",
      "max_pending": 500
    },
    "timeout_seconds": 30
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `url` | `""` | Immich 服务器的基础 URL（例如 `http://nas:2283`） |
| `api_key` | `""` | Immich API 密钥，以 `x-api-key` 头发送 |
| `owner_id` | `""` | 可选的精确所有者 ID；缺少该字段或属于他人的资源会被跳过 |
| `library_id` | `""` | 可选的精确图库 ID；留空 = 不按图库筛选 |
| `path_map` | `[{facet_prefix, immich_prefix}]` | 从 Facet 路径到 Immich `originalPath` 的前缀改写；第一个匹配的 `facet_prefix` 胜出 |
| `push.ratings` | `true` | 推送星级（只写入 1–5，绝不写 0/−1） |
| `push.favorites` | `true` | 推送收藏标记 |
| `push.rejected` | `false` | 为在 Facet 选片暗房中被淘汰的照片推送 `rating: -1`。需要 `push.ratings` |
| `push.top_picks_album` | `""` | 可选的 Immich 相册名称，用来收集评分达到阈值的已推送照片。留空 = 不使用相册 |
| `push.top_picks_min_rating` | `4` | 照片要加入 `top_picks_album` 所需的最低星级 |
| `webhook.token_env` | `""` | 保存入站 webhook 共享密钥的环境变量名；留空或未设置则禁用 webhook |
| `webhook.header` | `"x-facet-token"` | Immich 工作流用来发送令牌的头 |
| `webhook.max_pending` | `500` | 下一次同步所报告的、已记住但尚未评分的路径列表的上限 |
| `timeout_seconds` | `30` | 单次 REST 请求超时 |

`--immich-sync` 支持 `--dry-run`（匹配每一个资源但什么都不写）和 `--user`（在多用户模式下推送该用户 `user_preferences` 中的星级）。Facet 只使用 REST API，绝不触碰 Immich 的数据库。

## 时间线

按时间顺序浏览的时间线视图的设置：

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `photos_per_group` | `30` | 每个日期分组载入的照片数；数值越大每个日期显示的照片越多，但页面也越重 |

## 地图

交互式地图视图的设置：

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | 从聚合点切换为单个标记的缩放级别；取值范围 1（世界）到 18（街道） |

## 翻译

通过 MarianMT 进行 AI 照片描述翻译的设置：

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `target_language` | `"fr"` | `--translate-captions` 的目标语言：`fr`、`de`、`es`、`it`、`pt`（巴西葡萄牙语） |

翻译使用 Helsinki-NLP 的 MarianMT 模型，在 CPU 上运行；无需 GPU。

## 美学 CLIP（R2）

由缓存的 CLIP/SigLIP 嵌入和文本提示词得出的补充性美学评分。请用 `scripts/benchmark_aesthetic.py` 衡量提示词改动对 AVA 的影响。

```json
{
  "aesthetic_clip": {
    "positive_prompts": [
      "a professional, high-quality photograph",
      "an aesthetically beautiful image",
      "a masterful, award-winning photograph",
      "a sharp, well-composed photograph",
      "a stunning, visually striking image"
    ],
    "negative_prompts": [
      "a low-quality, amateur photograph",
      "a blurry, poorly composed photograph",
      "an unattractive, mundane snapshot",
      "a noisy, badly lit photograph",
      "a boring, forgettable image"
    ]
  }
}
```

空数组会使用 `analyzers/aesthetic_clip.py` 中的默认值。改动它们之前请重新跑一遍 AVA 基准测试：默认值在 `ava_test/` 上的 SRCC 约为 0.52，而改动很容易让它降到 0.30 左右。

## 添加其他 VLM 标签／点评模型（R3）

每个配置档的 `tagging_model`（例如 `qwen3.5-2b`）都对应同一个 `models` 小节中的一个模型条目。若想试用别的 VLM（Pixtral-12B、InternVL-2.5 等）：

1. 在 `models` 下添加一个模型条目：
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. 让某个配置档指向它：
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. 运行 `python facet.py --recompute-tags-vlm` 重新打标签。

无需改动任何代码。在把它提升为默认之前，请在约 30 张照片上做一次并排抽查。

## 服务器密钥

用来签发会话令牌和照片相框链接的密钥**不是**本文件中的一个键。它位于 `scoring_config.json` 旁边的 `.facet_secret` 中（权限 `0600`，已加入 gitignore），并在首次运行时生成。

- 覆盖方式：`FACET_JWT_SECRET` 环境变量。
- 轮换方式：`python database.py --rotate-secret`。

旧版安装遗留下来的 `share_secret` 会在下一次启动时被移入该文件，并从 `scoring_config.json` 中移除。见[密钥的存放与轮换](DEPLOYMENT.md#密钥的存放与轮换)。
