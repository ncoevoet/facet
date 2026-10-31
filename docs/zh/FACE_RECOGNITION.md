# 人脸识别

> 🌐 [English](../FACE_RECOGNITION.md) · [Français](../fr/FACE_RECOGNITION.md) · [Deutsch](../de/FACE_RECOGNITION.md) · [Italiano](../it/FACE_RECOGNITION.md) · [Español](../es/FACE_RECOGNITION.md) · [Português](../pt/FACE_RECOGNITION.md) · **简体中文**

Facet 使用 InsightFace 进行人脸检测，并使用 HDBSCAN 将人脸聚类为人物。

## 概述

1. **检测** - InsightFace buffalo_l 模型检测人脸并提取 512 维特征向量
2. **聚类** - HDBSCAN 把相似的特征向量归为人物聚类
3. **管理** - 在网页查看器中合并、重命名和整理人物

## 完整流程

### 第 1 步：提取人脸

扫描照片时会自动提取人脸：

```bash
python facet.py /path/to/photos
```

对于已入库但尚未提取人脸的照片：

```bash
python facet.py --extract-faces-gpu-incremental  # 仅处理新照片
python facet.py --extract-faces-gpu-force        # 处理全部照片（删除已有结果）
```

### 第 2 步：聚类人脸

把相似的人脸归为人物：

```bash
python facet.py --cluster-faces-incremental  # 保留已有人物
```

**聚类模式：**

| 命令 | 行为 |
|---------|----------|
| `--cluster-faces-incremental` | 保留全部人物，把新人脸匹配到已有人物 |
| `--cluster-faces-incremental-named` | 仅保留已命名的人物 |
| `--cluster-faces-force` | 删除全部人物，完全重新聚类 |

### 第 3 步：审核与合并

查找重复的人物聚类：

```bash
python facet.py --suggest-person-merges
python facet.py --suggest-person-merges --merge-threshold 0.7  # 更严格
```

这会在浏览器中打开人物合并建议页面。

### 第 4 步：在查看器中管理

其余工作在网页查看器中完成，遵循 **提取 → 聚类 → 合并 → 管理** 的流程：

- 在人物合并建议页面**合并**重复的聚类。
- 在管理人物页面**管理**人物（合并、批量合并、拆分、隐藏、重命名、删除）。

完整的界面说明见[查看器集成](#查看器集成)。

## 配置

### 人脸检测

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28
  }
}
```

| 设置项 | 默认值 | 说明 |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | 最低检测置信度 |
| `min_face_size` | `20` | 最小人脸尺寸（像素）（仅适用于 InsightFace，见说明） |
| `blink_ear_threshold` | `0.28` | 用于闭眼检测的 Eye Aspect Ratio |

在商业模式下，YuNet 检测器使用固定值（置信度 0.7、30 像素），忽略 `min_confidence_percent` 和 `min_face_size`。

### 人脸聚类

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

| 设置项 | 默认值 | 说明 |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | 创建一个人物所需的最少照片数 |
| `min_samples` | `2` | HDBSCAN 的 min_samples 参数 |
| `thresholds_by_model` | 见 JSON | 按识别模型分别设置：`auto_merge_distance_percent`（自动合并距离）和 `merge_threshold`（质心相似度）。默认值：ArcFace `15` / `0.6`，SFace `27.5` / `0.65` |
| `use_gpu` | `"auto"` | GPU 模式：`auto`、`always`、`never` |

### 人脸处理

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
    "refill_batch_size": 100
  }
}
```

## 聚类算法

进行 CPU 聚类时，请根据数据集规模选择算法：

| 算法 | 复杂度 | 适用场景 |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | 高维数据（推荐用于 5 万张以上人脸） |
| `boruvka_kdtree` | O(n log n) | 低维数据 |
| `prims_balltree` | O(n²) | 小数据集、内存受限 |
| `prims_kdtree` | O(n²) | 小数据集 |
| `best` | 自动 | 交给 HDBSCAN 决定 |

**性能提示：**对于大数据集，请使用 `boruvka_balltree`。在 8 万张人脸的规模下它可在 2-5 分钟内完成，而精确算法可能会一直卡住。

## GPU 聚类（cuML）

对于大型数据集（8 万张以上人脸），通过 RAPIDS cuML 进行 GPU 聚类比 CPU 更快。

### 安装

```bash
# Conda
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Pip
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
```

### 配置

```json
{
  "face_clustering": {
    "use_gpu": "auto"
  }
}
```

| 模式 | 行为 |
|------|----------|
| `"auto"` | cuML 可用时使用 GPU，否则回退到 CPU |
| `"always"` | 尝试使用 GPU；不可用时发出警告并回退 |
| `"never"` | 始终使用 CPU |

**注意：**cuML 使用自带的 HDBSCAN 实现。`algorithm` 和 `leaf_size` 参数仅对 CPU 聚类生效。

### GPU 与 CPU 得到的聚类并不相同

在相同的人脸和参数下，cuML 得到的聚类略多也略小（约为 CPU 聚类的 1.1–1.2 倍）。谁和谁被归为一组大致不变，但 GPU 运行与 CPU 运行得到的聚类*数量*并不一致。

**cuML 也不具备确定性。**在同样的人脸上运行两次 GPU 聚类，聚类数量几乎相同，但标签不同。

- **人物 ID 在多次运行之间不可复现。**请为你在意的人命名；已命名的人物会保持稳定。
- **不要按标签比较两次聚类运行的差异。**请改为比较人脸的归属。

只要输入相同，指定了固定 `algorithm` 的 CPU 聚类就是确定性的。

### 重新聚类与已整理的人物

除 `--cluster-faces-force` 之外的所有模式都会保留已有的人物记录，但所有模式都会重新计算每一张人脸所属的人物。

- **中断是安全的。**更改在最后一步一次性写入；在此之前被中断的运行不会改变任何内容。
- **运行期间在查看器中的修改。**在运行写入结果时（最后几秒）重新指派的人脸会保留你的选择，运行会记录它跳过了多少张。此时发出的保存请求会等待运行完成；等待超过 5 秒的请求会被以“library busy”拒绝，需要重新操作。更早的时候、人脸仍在聚类期间所做的修改会被覆盖。

重建后的聚类在满足以下任一条件时会重新归入某个人物：

1. 它的平均特征向量与该人物已存储的质心之间的差距在 `merge_threshold` 以内（ArcFace 默认 0.6 余弦，SFace 为 0.65），**或者**
2. 它至少有一半的人脸在本次运行前就属于该人物。

第二条规则对跨越多年被拍摄的人很重要：他们的人脸会拆成若干紧凑的子聚类，而这些子聚类都远离那个单一的平均质心。没有它，已命名人物的大多数人脸都无法回到他们名下。

由于规则 2 以先前的归属为准，早先的错误归属会被延续。若要从零开始，请使用 `--cluster-faces-force`。当一个聚类的人脸恰好在两个人物之间平分时，拥有该聚类中编号最小的、此前已有归属的人脸的那位人物胜出。

## 闭眼检测

使用 InsightFace 106 点关键点计算的 Eye Aspect Ratio（EAR）。

### 工作原理

EAR 衡量的是眼睛高度与宽度之比。眼睛闭合时，EAR 会降到阈值以下。

### 配置

```json
{
  "face_detection": {
    "blink_ear_threshold": 0.28
  }
}
```

阈值越低，检测越严格（更多照片被标记为闭眼）。

### 修改阈值后重新计算

```bash
python facet.py --recompute-blinks
```

只处理包含人脸的照片，无需 GPU。

## 可选的 OFIQ 人脸质量（商业模式）

商业模式下受限的人脸质量模型不可用。作为可选的替代方案，请安装 `python-ofiq`（UNICEF 对 BSI OFIQ 的绑定，ISO/IEC 29794-5；MIT）：

```bash
pip install python-ofiq
```

- 只提供 Linux x86-64 和 macOS arm64 的 wheel（Windows 请用 WSL2 或 Docker）。它可与 numpy 2 和 OpenCV 4.8+ 共存。
- 首次使用时，Facet 会把 OFIQ 模型（约 400 MB，MIT/Apache-2.0，固定 SHA-256）下载到 `pretrained_models/ofiq/`。
- OFIQ 的分数（0-100）除以 10 后存入 `face_quality_iqa`。一张照片的值为 0.7 x 最差人脸 + 0.3 x 平均值。
- 未安装 `python-ofiq` 时该列保持 NULL，其权重会分摊到其他指标上。

## 逐张人脸的表情信号（睁眼 + 微笑）

每张人脸存有两个 0-10 的分数，供选片界面的人脸面板和照片级分数使用：`eyes_open_score`（10 = 完全睁开，0 = 完全闭合）与 `smile_score`（5 = 中性，10 = 开怀大笑，0 = 皱眉）。

有两个后端按同一标度产生这些分数：

1. **几何方式（始终可用）。**基于已存储的 InsightFace 106 点
   关键点计算：睁眼用 Eye Aspect Ratio，微笑用嘴角上扬幅度。
   `--recompute-face-signals` 可以回填它们，不需要 GPU，也不读取图像。
2. **MediaPipe 混合变形（可选）。**在扫描和提取人脸期间，每张
   人脸裁剪图会送入 MediaPipe Face Landmarker，其混合变形
   （`eyeBlink*`、`mouthSmile*`、`mouthFrown*`）映射到同样的标度。
   它对闭眼、细微微笑和侧脸的判断更好，因此其分数会**取代**
   几何值。如果缺少 MediaPipe 或其模型，或者裁剪图太小，
   则保留几何值。

### 安装 MediaPipe

MediaPipe 是可选的，并且**必须**在不安装其捆绑的
`opencv-contrib-python` 的前提下安装，否则会在 Facet 的 `opencv-python`
之外再装入一个 `cv2` 命名空间：

```bash
pip install mediapipe==0.10.35 --no-deps
pip install absl-py flatbuffers
```

切勿直接运行 `pip install mediapipe`。

### 模型包

`face_landmarker.task` 模型包（约 3.6 MiB，Apache-2.0）会在首次使用时
自动下载到 `pretrained_models/face_landmarker.task`。如果机器处于
离线状态，请手动从
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
下载并放到该路径。下载失败时只会记录一次警告，并回退
到几何分数。

### 配置

```json
{
  "face_detection": {
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

- `enabled`（默认 `true`）：只要 MediaPipe 及其模型包可用，就使用混合
  变形分数；否则自动运行几何方式回退。设为 `false` 可强制只用几何方式。
- `min_crop_size`（默认 `192`）：带边距裁剪图小于该尺寸（像素，取短边）
  的人脸会回退到几何方式，而不是把一张很小的人脸放大。
- `blink_pose_gate_deg`（默认 `null` = 关闭）：仅适用于商业模式的 MediaPipe 分析器。转头超过该度数（|yaw| 或 |pitch|）的人脸不给出眨眼判定，也不给出睁眼 / 微笑评分，因为转头会让眼睛看起来像闭着。测试发现 20° 到 45° 之间没有任何有帮助的阈值，因此默认关闭；仅当你的图库中有大量明显转头的人脸时才设置。必须是正数。它对新扫描的照片生效；已有的 `is_blink` 值只有在重新扫描时才会改变。

### 重新计算

`--recompute-face-signals` 只使用已存储的关键点：它**只用几何方式**，不会运行 MediaPipe。若要刷新 MediaPipe 分数，请用 `--extract-faces-gpu-force` 重新提取人脸。

## 人脸缩略图

缩略图存储在数据库中，以便快速显示。

### 存储

- 扫描时从全分辨率图像生成
- 以 JPEG BLOB 形式存储在 `faces.face_thumbnail` 列中（每张约 5-10KB）
- 聚类和查看器直接使用它们，而不是重新生成

### 重新生成

```bash
# 生成缺失的缩略图
python facet.py --refill-face-thumbnails-incremental

# 重新生成全部缩略图
python facet.py --refill-face-thumbnails-force
```

这两条命令都使用并行处理以提高速度。

## 数据库结构

### faces 表

| 列 | 类型 | 说明 |
|--------|------|-------------|
| `id` | INTEGER | 主键 |
| `photo_path` | TEXT | 指向 photos 的外键 |
| `face_index` | INTEGER | 在照片内的序号 |
| `embedding` | BLOB | 512 维人脸特征向量 |
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | INTEGER | 边界框角点 |
| `confidence` | REAL | 检测置信度 |
| `person_id` | INTEGER | 指向 persons 的外键 |
| `face_thumbnail` | BLOB | JPEG 缩略图 |
| `landmark_2d_106` | BLOB | 106 点关键点（用于闭眼检测） |
| `embedding_model` | TEXT | 识别模型标记（默认 `arcface_buffalo_l`） |

### persons 表

| 列 | 类型 | 说明 |
|--------|------|-------------|
| `id` | INTEGER | 主键 |
| `name` | TEXT | 人物姓名（NULL = 自动聚类生成） |
| `representative_face_id` | INTEGER | 用作头像的最佳人脸 |
| `face_count` | INTEGER | 人脸数量 |
| `centroid` | BLOB | 聚类质心特征向量 |
| `auto_clustered` | INTEGER | 1 表示自动生成 |
| `face_thumbnail` | BLOB | 人物头像缩略图 |
| `is_hidden` | INTEGER | 1 = 从筛选和合并建议中排除 |

## 增量模式与强制模式

### 增量聚类

- 保留全部已有人物（已命名的和自动聚类的）
- 只对新的、未分配的人脸进行聚类
- 通过质心相似度把新聚类匹配到已有人物
- 合并后更新质心

**适用场景：**向已有图库中添加新照片

### 强制聚类

- 删除全部人物，包括已命名的
- 从零开始完全重新聚类

**适用场景：**重新开始，或算法发生重大变化

### 增量命名聚类

- 仅保留已命名的人物
- 删除自动聚类的人物
- 对所有未命名的人脸重新聚类

**适用场景：**在刷新自动识别出的聚类的同时保留已整理好的姓名

## 查看器集成

### 人物筛选

- 下拉列表显示带人脸缩略图的人物
- 按人物筛选照片库

### 人物照片库

- 在下拉列表中点击某个人物即可查看其全部照片
- 点击人物会在照片库上应用 `person_id` 筛选（没有单独的人物专属路由）

### 管理人物页面

通过顶栏按钮或 `/persons` 访问：

- **网格视图** - 全部已识别的人物
- **合并** - 选择来源人物，点击目标人物，确认
- **批量合并** - 选择多个人物并合并到一个目标人物
- **拆分** - 把选中的人脸移到一个新人物
- **隐藏** - 把某个聚类从列表、筛选和合并建议中排除
- **删除** - 移除人物聚类
- **重命名** - 点击姓名即可就地编辑

### 创建人物

你可以直接在照片库中为聚类漏掉的人脸命名：

1. 在照片卡片上打开人物操作菜单，选择一张未分配的人脸。
2. 在人物选择器中选择**创建新人物**并输入姓名。
3. 该人脸会关联到这个新人物（`auto_clustered = 0`）。

已属于其他人物的人脸会被移动，不再拥有任何人脸的人物会被删除。在多用户模式下，你只能关联位于自己或共享目录内的照片上的人脸。接口：`POST /api/persons`（见 [API.md](../API.md)）。

### 待命名

管理人物页面会在**待命名**标签页中列出较大的未命名聚类，每一项都带有命名输入框。当聚类的人脸数至少为 `viewer.persons.needs_naming_min_faces`（默认 `5`）时，它就会出现在那里。

未命名指没有名称或名称为空，无论聚类来自自动聚类还是拆分；已隐藏（忽略）的人物不会列出。该标签页仅在编辑模式下显示，位于 **已命名** 旁边；**已命名** 只列出已命名的人物，因此每个人只出现一次，页面总是打开 **已命名**。

### 人物合并建议页面

通过 `/merge-suggestions` 或管理人物页面上的「人物合并建议」按钮访问：

- 显示人脸特征向量相似、可能是同一个人的人物配对
- **阈值滑块**——控制相似度门槛（越低建议越多）
- **一键合并**——立即合并一对建议
- **批量合并**——选择多条建议并一次性全部合并

### 照片卡片

- 为已识别的人物显示小尺寸人脸缩略图（头像）
- 可通过 `viewer.face_thumbnails.output_size_px` 配置

## 特征向量空间标记（识别模型安全性）

每张人脸都会在 `embedding_model` 中记录产生它的识别模型（默认 `arcface_buffalo_l`，即 InsightFace `buffalo_l` / ArcFace `w600k_r50` 模型）。不同模型的特征向量无法比较，因此聚类只使用**当前生效**模型的人脸。`NULL` 标记按 ArcFace 处理。如果存在来自其他模型的人脸，Facet 会排除它们并记录一条警告。

### 更换识别模型（例如 AdaFace）——延后的计划

AdaFace（对模糊或抓拍人脸的聚类效果更好）**尚未实现**。采用它需要完全重新提取并重新聚类（先 `--extract-faces-gpu-force` 再 `--cluster-faces-force`），因为 ArcFace 与 AdaFace 的特征向量不可比较。

### 混合库、重新提取与未知值

- **混合库。**同一个库可以同时包含 ArcFace（512 维）和 SFace（128 维）人脸。聚类、合并建议、相似人物搜索和质心每次都只使用一个模型（`persons.centroid_model` 记录它）。
  - 增量聚类与仅保留已命名人物的模式不会改动另一个模型的人脸和人物。
  - `--cluster-faces-force` 会清除所有人脸的归属并删除所有人物，包括已命名的，不论其模型。
  - 要把库迁移到当前模型，请运行 `--extract-faces-gpu-force`（商业模式下使用宽松许可的提取器；已命名人物会保留），然后运行 `--cluster-faces-incremental`。
- **警告。**扫描时若存储的人脸属于非当前模型，会记录一条警告，`--doctor` 也会报告。在商业模式下，`--doctor` 会列出扫描实际会加载的组件（YuNet、SFace、Q-ReAlign，以及已安装 `python-ofiq` 时的 OFIQ）。在 CUDA 上，若 InsightFace 运行在 CPU 上，扫描会记录一次警告；见 `--doctor` 的 ONNX Runtime 一节和[安装 › 用于人脸检测的 ONNX Runtime](INSTALLATION.md#用于人脸检测的-onnx-runtime)。
- **已命名人物在重新提取后保留。**`--extract-faces-gpu-force` 会把每张重新检测到的人脸还给旧人脸框与其重叠的已命名人物（IoU >= 0.5，一对一）。未匹配的人脸等待下次聚类。被中断的运行会由下一次提取接续。重新扫描照片时，已命名人物同样会被保留。
- **未知不等于零。**没有 MediaPipe 时，宽松分析器无法测量眼睛、微笑或眨眼，这些值存为 NULL；眨眼过滤和扣分把 NULL 视为“不是眨眼”。如果某张照片的人脸处理失败，其 `face_count`、`face_ratio` 和 `is_group_portrait` 为 NULL，并保留其已存储的人脸；在重新扫描之前，它按没有人脸计分。

## 故障排查

| 问题 | 解决办法 |
|-------|----------|
| 聚类一直卡住 | 使用 `boruvka_balltree` 算法 |
| 小聚类过多 | 调高 `min_faces_per_person` |
| 人脸没有被归到一起 | 调低 `merge_threshold` |
| GPU 聚类失败 | 检查 cuML 安装，用 `"never"` 强制使用 CPU |
| 缩略图缺失 | 运行 `--refill-face-thumbnails-incremental` |
| 闭眼检测不准 | 调整 `blink_ear_threshold`，然后运行 `--recompute-blinks` |
| 出现「Excluded N faces from non-active embedding space」警告 | 识别模型变更导致特征向量混杂——请先运行 `--extract-faces-gpu-force`，再运行 `--cluster-faces-incremental` |
