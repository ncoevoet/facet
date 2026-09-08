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
| `min_face_size` | `20` | 最小人脸尺寸（像素） |
| `blink_ear_threshold` | `0.28` | 用于闭眼检测的 Eye Aspect Ratio |

### 人脸聚类

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "auto_merge_distance_percent": 15,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "merge_threshold": 0.6
  }
}
```

| 设置项 | 默认值 | 说明 |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | 创建一个人物所需的最少照片数 |
| `min_samples` | `2` | HDBSCAN 的 min_samples 参数 |
| `merge_threshold` | `0.6` | 用于匹配的质心相似度 |
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

在一个包含 145,677 张人脸的照片库上实测，特征向量与参数完全相同：

| 人脸数 | cuML 聚类数 | CPU 聚类数 | 比值 |
|------:|--------------:|--------------:|------:|
| 5,000 | 202 | 181 | 1.12× |
| 20,000 | 1,285 | 1,039 | 1.24× |

cuML 的划分略微更细，噪声率相当，聚类规模中位数完全一致（4）。差异小到不会改变谁和谁被归为一组，但确实意味着 GPU 运行与 CPU 运行得到的聚类*数量*不会一致。

**cuML 也不具备确定性。**在同样的 145,677 张人脸上以相同参数连续运行两次 GPU 聚类，标签只有 **41% 一致**，而聚类数量几乎相同（14,809 对 14,807），下游结果也完全一致。结构是稳定的，标签则不是。值得了解的后果：

- **人物 ID 在多次运行之间不可复现。**不要指望重新聚类会保留自动聚类人物的编号——请为你在意的人命名，命名才能让他们保持稳定。
- **不要按标签比较两次聚类运行的差异。**请改为比较人脸的归属。

只要输入相同，指定了固定 `algorithm` 的 CPU 聚类就是确定性的。

### 重新聚类与已整理的人物

除 `--cluster-faces-force` 之外的所有模式都会保留已有的人物记录，但所有模式都会清除人脸→人物的归属关系并重建。重建后的聚类在满足以下任一条件时会重新归入某个人物：

1. 它的平均特征向量与该人物已存储的质心之间的差距在 `merge_threshold` 以内（默认 0.6 余弦），**或者**
2. 它至少有一半的人脸在本次运行前就属于该人物。

第二条规则的作用比听上去更大。人物质心只是一个平均向量，因此跨越多年被拍摄的同一个人会占据很宽的区域——HDBSCAN 会正确地把他们拆成若干紧凑的子聚类，而每个子聚类都远离那个平均值，无法满足规则 1。在上述照片库中，仅靠规则 1 只能找回 38% 原本归属于已命名人物的人脸；加入规则 2 后可找回 96%。

由于规则 2 以先前的归属为准，早先的错误归属会被延续而不是被纠正。对于一个以保留已有人物为目的的模式，这正是预期的行为——若要从零重新推导全部结果，请使用 `--cluster-faces-force`。

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

## 逐张人脸的表情信号（睁眼 + 微笑）

每一条人脸记录都存有两个 0-10 的连续信号，供选片界面的人脸面板
和照片级汇总使用：`eyes_open_score`（10 = 完全睁开，0 = 完全
闭合）与 `smile_score`（5 = 中性，10 = 开怀大笑，0 = 皱眉）。

有两个后端按同一 0-10 标度产生这些分数：

1. **几何方式（始终可用）。**基于已存储的 InsightFace 106 点关键点
   推导：睁眼用 Eye Aspect Ratio，微笑用嘴角上扬幅度。纯几何计算，
   因此 `--recompute-face-signals` 可以直接从已存储的关键点回填，
   既不读取像素，也不需要 GPU。
2. **MediaPipe 混合变形（可选，基于外观）。**在扫描/提取人脸期间，
   每张人脸的宽裁剪图会送入 MediaPipe Face Landmarker，其
   ARKit 风格的混合变形（`eyeBlink*`、`mouthSmile*`、
   `mouthFrown*`）映射到同样的标度。在闭眼、细微微笑和侧脸的情况下，
   外观判断优于关键点几何，因此当一张人脸通过 MediaPipe 得到分数时，
   该分数会**取代**几何值。如果缺少 MediaPipe 或其模型包，或者人脸
   裁剪图太小/未被检测到，则保留几何值——行为与仅有几何方式的安装完全一致。

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
      "min_crop_size": 192
    }
  }
}
```

- `enabled`（默认 `true`）：只要 MediaPipe 及其模型包可用，就使用混合
  变形分数；否则自动运行几何方式回退。设为 `false` 可强制只用几何方式。
- `min_crop_size`（默认 `192`）：带边距裁剪图小于该尺寸（像素，取短边）
  的人脸会回退到几何方式，而不是把一张很小的人脸放大。

### 重新计算

`--recompute-face-signals` 仅根据已存储的关键点重新计算逐张人脸的信号——
它**只用几何方式**，不会运行 MediaPipe（不读取任何像素）。
若要刷新基于外观的分数，请重新提取人脸
（`--extract-faces-gpu-force`），以便重新分析全分辨率裁剪图。

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

人物不再只能来自聚类——你可以直接在照片库中为聚类漏掉的人脸
命名：

1. 在照片卡片上打开人物操作菜单，选择一张未分配的人脸。
2. 在人物选择器中选择**创建新人物**并输入姓名。
3. 该人脸会在一次调用中关联到这个新建的（手动创建、
   `auto_clustered = 0`）人物。

接口：`POST /api/persons`（需要编辑模式），请求体为
`{ "name": "<name>", "face_ids": [<id>, ...] }`。姓名为必填（去除首尾
空白后不能为空）。已属于其他人物的人脸会被重新分配，若某个旧人物
因此不再拥有任何人脸，则会被删除——语义与人脸分配完全一致。在多用户
模式下，调用方只能关联位于自己（或共享）目录内的照片上的人脸；超出
该范围的人脸会以「未找到」被拒绝。

### 待命名

管理人物页面会在**待命名**区域中列出值得命名的自动聚类人物：
未命名的聚类（`name IS NULL`、
`auto_clustered = 1`）且人脸数至少为 `viewer.persons.needs_naming_min_faces`
（默认 `5`），每一项都带有就地命名输入框，无需四处寻找即可为大聚类
命名。数据由
`GET /api/persons/needs_naming?min_faces=N` 提供。

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

每一条人脸记录都带有 `embedding_model` 标记（`faces` 表上的列，默认
`arcface_buffalo_l`，即当前的 InsightFace `buffalo_l` / ArcFace `w600k_r50`
识别模型）。**不同**识别模型产生的特征向量位于**互不兼容的向量空间**中，
绝不能放在一起聚类——那样会在不报错的情况下悄悄产生垃圾人物。

因此 `FaceClusterer.load_embeddings()` 只加载**当前生效的**特征向量空间
（`faces/clusterer.py` 中的 `ACTIVE_EMBEDDING_MODEL`；`NULL` 标记按旧的
ArcFace 空间处理），并在存在并排除了其他空间的人脸时输出醒目的警告。
这是一道向前兼容的防线：它从结构上保证了将来更换识别模型是安全的。

### 更换识别模型（例如 AdaFace）——延后的计划

像 **AdaFace**（画质自适应间隔，对模糊/抓拍人脸的聚类效果更好）这样的
质量升级，可以作为可选启用的 512 维后端接入（相同的存储路径、相同的
HDBSCAN），但**尚未实现**，因为没有真实数据就无法验证。要正确地完成
它，需要：

1. **权重 + 主干网络**——一份 AdaFace 检查点（例如 `adaface_ir101_webface12m`）
   及其 IResNet 主干网络；需要新增一次模型缓存下载。
2. **对齐裁剪图**——在提取阶段用 `norm_crop(img, face.kps, 112)`
   得到对齐后的 112×112 裁剪图再计算特征向量（kps 存在于 InsightFace 的
   `face` 对象上但并未持久化，因此 AdaFace 无法离线回填——
   它必须在提取过程中运行）。还需确认 BGR 通道顺序与归一化方式和检查点一致。
3. **配置开关**——新增 `face_detection.recognition_model: arcface|adaface`
   并据此解析 `ACTIVE_EMBEDDING_MODEL`；同时为新人脸打上相应标记。
4. **完全重新提取 + 重新聚类**——先 `--extract-faces-gpu-force` 再
   `--cluster-faces-force`，因为 ArcFace 与 AdaFace 的特征向量不可比较。
   上面的特征向量空间标记可以防止迁移到一半的数据库悄悄把两个空间混在
   一起聚类（它会改为发出警告并排除）。
5. **质量验证**——用带标注的身份数据衡量聚类质量；「能跑通并输出 512 维
   向量」并不能证明预处理是正确的。

## 故障排查

| 问题 | 解决办法 |
|-------|----------|
| 聚类一直卡住 | 使用 `boruvka_balltree` 算法 |
| 小聚类过多 | 调高 `min_faces_per_person` |
| 人脸没有被归到一起 | 调低 `merge_threshold` |
| GPU 聚类失败 | 检查 cuML 安装，用 `"never"` 强制使用 CPU |
| 缩略图缺失 | 运行 `--refill-face-thumbnails-incremental` |
| 闭眼检测不准 | 调整 `blink_ear_threshold`，然后运行 `--recompute-blinks` |
| 出现「Excluded N faces from non-active embedding space」警告 | 识别模型变更导致特征向量混杂——请先运行 `--extract-faces-gpu-force`，再运行 `--cluster-faces-force` |
