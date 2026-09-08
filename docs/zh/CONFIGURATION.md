# 配置参考

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · [Português](../pt/CONFIGURATION.md) · **简体中文**

每一项设置都随 `config/scoring_config.default.json` 一起发布，再由你自己的 `scoring_config.json` 逐键覆盖 — 参见[默认值与你的覆盖配置](#默认值与你的覆盖配置)。修改之后请运行 `python facet.py --recompute-average` 更新评分（无需 GPU）。

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

`scoring_config.json` 里**只保存你改动过的内容**。Facet 随附的全部配置都放在
`config/scoring_config.default.json` 中，你的文件则叠加在它之上解析：凡是你没有写出来的
键，都保持随附的值。全新安装根本没有 `scoring_config.json` 文件，
完全依靠默认值运行。

因此，若只想提高人像的美学权重并设置一个编辑密码，
整个文件就是：

```json
{
  "viewer": { "edition_password": "your-password" },
  "categories": [ ... ]
}
```

两者的合并遵循两条规则：

- **对象逐键合并。** `{"performance": {"mmap_size_mb": 4096}}` 只改动这一项设置，
  `cache_size_mb` 以及其他所有 `performance` 键都保持随附的
  值。
- **数组整体替换。** 如果你的文件里有 `categories` 数组，它会完整替换随附的那一份 —
  而不是逐个类别地合并。这是有意为之：`categories` 按优先级顺序
  以“首次匹配即生效”的方式求值，而
  `scoring_contexts.*.promote` 会按你书写的顺序读取，因此逐元素合并数组
  会悄悄打乱评分顺序。这也是**删除**某项内容的唯一办法：
  你从数组中省略掉的类别就此消失，而合并式的数组
  只会把它重新塞回来。

  实际后果是：只要你改动某个类别中的一项权重，你的文件就得
  带上全部权重。请把 `categories` 数组从
  `config/scoring_config.default.json` 中复制出来，编辑后保留下来 — 随附配置里
  其余约 1500 行仍然不必进入你的文件。

### 升级已有安装

无需任何操作：来自旧版本的完整 `scoring_config.json` 解析后仍是它自己，
照常工作。但你自己的改动会淹没在 3700 行随附值里，而那些你从未选择过的
设置，也被冻结在你复制文件那一刻的取值上。

要让文件重新精简，你同样什么都不用做 — `scoring_config.json` 的每一个写入方
都会把整个文件按其覆盖配置的本质重写一遍，丢弃所有仍与随附默认值相同的键，
而不只是它本想改动的那一个。在查看器界面里保存权重或类别优先级会触发这一点，
全景阈值的改动、首次使用明文密码成功登录（同一次写入会把它升级为哈希）
也会，甚至一次普通扫描也会 — 只要 `validate_weights` 在途中修正了某个类别的
权重。

```bash
python database.py --compact-config
```

可以按需执行同样的精简，而不必等到下一次写入来触发。这个过程是无损的 —
文件之后解析出的配置完全相同 — 它真正剩下的优势是备份：写入之前它会对文件
做一份 `0600` 权限的副本。并非每个写入方都会这么做；扫描路径
（`ScoringConfig.save_config`）按设计不做备份（见 `config/scoring_config.py:481`
处的文档字符串），所以当你希望留下一份备份、而不是听凭下一个写入方处置时，
就该用 `--compact-config`。

> **把这项取舍说清楚。** 一旦某个值因为与默认值相同而被丢弃，日后 Facet 发布新版
> 并改动那个默认值时，你的行为也会随之改变 — 而且丢弃它的是任何一次写入，不只是
> `--compact-config`。这正是设计意图 — 新的调优就是这样在你不必编辑文件的情况下
> 传递到你手上。真正能让某个值抵御未来默认值变化的，只有把它设成与随附默认值
> *不同* 的取值：一个恰好等于默认值的值无法留在文件里 —
> 下一次写入就会丢弃它，无论那次写入是不是有意在做精简。


## 用户

可选的多用户模式。当存在 `users` 键（且至少有一个用户）时，单密码认证会被逐用户登录取代。

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
| `password_hash` | string | PBKDF2-HMAC-SHA256 哈希（`salt_hex:dk_hex`）。由 `--add-user` 命令行生成。 |
| `display_name` | string | 显示在界面顶栏 |
| `role` | string | `user`、`admin` 或 `superadmin` |
| `directories` | array | 该用户的私有照片目录 |

### 共享目录

`shared_directories` 键（与用户对象同级）列出对所有用户可见的目录。

### 角色

| 角色 | 查看自有 + 共享 | 评分/收藏 | 管理人物/人脸 | 触发扫描 |
|------|:-:|:-:|:-:|:-:|
| `user` | 是 | 是 | 否 | 否 |
| `admin` | 是 | 是 | 是 | 否 |
| `superadmin` | 是 | 是 | 是 | 是 |

### 添加用户

用户只能通过命令行创建 — 没有注册界面，也没有对应的 API：

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# 提示输入密码，并把哈希写入 scoring_config.json
```

添加用户之后，请编辑 `scoring_config.json` 来配置他们的 `directories`。

### 向后兼容

- 没有 `users` 键 = 传统单用户模式（行为不变）
- 多用户模式下会忽略 `viewer.password` 和 `viewer.edition_password`
- `photos` 表中已有的星级仍供单用户模式使用；用 `--migrate-user-preferences` 把它们复制过去

---

## 扫描

控制目录扫描的行为。

```json
{
  "scanning": {
    "skip_hidden_directories": true
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | 扫描照片时跳过以 `.` 开头的目录 |

---

## 类别

类别定义的数组。详细的类别说明见[评分](SCORING.md)。

每个类别包含：
- `name` - 类别标识符
- `priority` - 数值越小优先级越高（越先求值）
- `filters` - 匹配条件
- `weights` - 各项评分指标的权重（总和必须为 100）
- `modifiers` - 行为调整项
- `tags` - 用于按标签匹配的 CLIP 词表

> **形式与色彩和谐权重。** 每个类别的 `weights` 块都带有五个可解释的指标键 — `symmetry_percent`、`balance_percent`、`edge_entropy_percent`、`fractal_percent` 和 `color_harmony_percent` — 由 `--recompute-form` 填充。它们在所有类别中出厂值都是 `0`，因此在你给其中某一项赋予权重之前，聚合评分保持逐字节不变（赋权之后请重新运行 `--recompute-average`）。同一类别内部的权重总和仍必须为 100。

---

## 拍摄场景评分方案

拍摄场景评分方案是针对上文全局 `categories` 优先级顺序的一份具名**增量**：它把一小批类别提到最前面、把另一些彻底排除，其余的都保持原有的优先级顺序。它之所以存在，是因为优先级是全局共享的，可究竟*应该*由哪个类别胜出却因拍摄题材而异：一张被打上 `sports` 标签的逆光舞蹈照片，会被 `silhouette`（优先级 42）远早于 `sports`（优先级 71）截获，而权重滑块也解决不了这一点 — 它们决定的是*已选中*的类别如何评分，而不是哪个类别被选中。

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
| `promote` | 按给定顺序移到求值序列最前面的类别名 |
| `excluded` | 完全从求值中移除的类别名（在此方案下永不匹配） |
| `suggest_from_moments` | 为相册推荐此方案的 `narrative_moment` 取值 — 由 `GET /api/albums/{id}/suggested_context` 读取（见 [VIEWER.md](VIEWER.md)） |

**实际顺序** = `promote`（按顺序）→ 全局优先级顺序减去已提升和已排除的名称 → 最后是 `default`（兜底类别，优先级 999）。同时出现在 `promote` 和 `excluded` 中的名称会被彻底移出顺序 — `excluded` 胜出，`promote` 条目不生效。`default` 本身永远不能被提升或排除。不传方案、或传入未知方案名，都会退回纯粹的全局优先级顺序（未知名称还会记录一条警告）；解析得到的 `[(category_name, CategoryFilter)]` 列表会按方案名在已加载配置的生命周期内做记忆化（`ScoringConfig.resolve_context_order`）。`python facet.py --validate-categories` 会报告（但不会导致加载失败）任何不是真实类别的 `promote`/`excluded` 名称、同时出现在两个列表中的名称，以及任何不是 `narrative_moments.event_types.<default_event_type>` 键的 `suggest_from_moments` 条目 — 否则这些地方的拼写错误只会悄无声息地失效。

随附的预设 — `default` 是一份空增量，因此在没有显式指派方案之前，现有行为不变：

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

随附的预设并不是一个封闭集合 — 在 `scoring_contexts` 下加一个键，它就是一个与其他方案完全同等的方案：能被解析、能指派给相册，其增量也能在**拍摄场景评分方案**标签页中编辑。不需要在代码里注册任何东西。

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

有一个细节：`label_key` 会在 i18n 语言包中查找，而找不到该键时现在会回退到方案自身的 **`name`**（例如 `dance_comp`），而不是渲染出一条原始的点分路径 — 这样一个自定义方案即使还没有翻译，在选择器里、在每种语言下都保持可读。把该键加到全部六个 `i18n/translations/*.json` 语言包中，就能用正规的本地化标签取代这个裸名称。

### 编辑方案

`PUT /api/config/scoring_contexts/{name}`（受编辑权限限制）从查看器的**拍摄场景评分方案**标签页重写某个方案的增量 — 把提升到前面的那一段拖成你想要的顺序（或使用上移/下移按钮），点击某个类别切换其排除状态，然后保存。请求体是 `{"promote": [name, ...], "excluded": [name, ...]}`。只有这两个字段可编辑：`label_key` 和 `suggest_from_moments` 会原样保留，其他方案也完全不受影响。**界面刻意只提供编辑增量这一种方式** — 方案永远不携带一份独立的完整顺序，因此未被提升的类别始终保持全局优先级顺序，日后新增的类别也绝不会在六份互不相干的列表里悄悄缺席。

当方案不存在、当某个 `promote`/`excluded` 条目不是已有类别、当 `default` 出现在任一列表中（它是钉在末尾的兜底类别，既不能提升也不能排除），或当 `promote` 中重复出现同一名称（其顺序有意义，重复即产生歧义）时，写入会被拒绝并返回 400，同时指名出错的条目。把同一个类别同时列在**两个**列表中仍然会被接受 — `excluded` 胜出、`promote` 条目被丢弃，与上文所述完全一致 — 而 `excluded` 内部的重复项会被合并而不是拒绝，因为它是一个集合。每次写入都会照样生成带时间戳、会被定期清理的 `.backup.<timestamp>` 副本，并持有与优先级、权重写入方相同的锁，因此并发的配置保存不会互相丢弃。`resolve_context_order` 是按 `ScoringConfig` 实例做记忆化的，而每个读取方都会为每个请求新建一个实例，所以写入之后没有任何顺序缓存需要失效。

和调整优先级一样，编辑方案本身不会改动任何照片已存储的 `category` — 之后请运行一次重新计算（见[调整优先级需要重新计算](#调整全局优先级顺序)）；标签页里就有一个**立即重新计算**按钮专门用于此事。

### 指派方案

拍摄场景评分方案是**按相册**指派的，通过 `PUT /api/albums/{id}/scoring_context`（受编辑权限限制）完成：它会写入相册的 `scoring_context` 列，并把同一个值固化到**当下**属于该相册的每张照片的 `photo_scoring_overrides.scoring_context` 中，同时跳过任何手动设置过覆盖值的成员（`source = 'manual'`）— 相册指派绝不会悄悄把照片自己的手动选择改成来自相册的选择。响应中的 `conflicts` 计数表示有多少非手动成员原本已带有不同的方案（后写入者胜出），`manual_skipped` 表示有多少手动成员被原样保留，`updated` 表示实际写入了多少条。手动相册的成员由其 `album_photos` 行决定；智能相册（`is_smart`）没有这些行，因此成员改为通过对实时数据库求值其保存的 `smart_filter_json` 来确定（`_resolve_album_member_paths`，与 `_fetch_album_photos` 的智能分支一致）。这里用的是相册的**筛选定义**，而不是照片库视图：`smart_filter_json` 只携带用户选择的筛选条件（排序、人物等），并刻意排除照片库的 `hide_blinks`/`hide_bursts`/`hide_duplicates`/`hide_rejected` 视图偏好（它们是全局的、可在运行时切换的 `viewer.defaults`，不属于相册自身的定义），因此在这些开关打开时，`updated` 完全可能超过相册自身照片库视图所显示的照片数 — 一张本来就匹配的照片的连拍后续帧，仍然是真实成员。若智能相册的筛选条件当前什么都匹配不到，返回结果会是 `updated: 0` 并带上一条 `warning`。无论哪种情况，这个标记都是一次快照而非订阅：对手动相册来说，*之后*通过 `append_album_photos` 加入的照片确实会自动继承方案（同样跳过手动成员），但智能相册的筛选条件日后匹配到*新*照片时，**不会**追溯性地为其套用方案 — 只有再次调用 `PUT` 才会对当前匹配的内容重新打标。`DELETE /api/albums/{id}/scoring_context` 会清除相册的 `scoring_context`，并精确撤销由本相册打下的标记（`source = 'album:<id>'`），照片自身的手动覆盖不受影响。从相册中移除特定照片（`DELETE /api/albums/{id}/photos`）会以同样方式精确撤销本相册在这些照片上的标记，唯一的例外是：被移除的照片*仍然*属于另一个本身声明了方案的相册 — 单个 `source` 列无法表达多相册归属，因此那张照片会改用另一个相册的方案重新打标，而不是被置于无方案状态（这项重新推导仅限于移除请求中涉及的照片；整册删除或显式清除方案不会尝试它，因为对智能相册的完整成员来说，把每张被清除的照片与每个声明了方案的相册逐一比对是无界的）。从智能相册中移除照片是空操作（`album_photos` 里没有它的行，而被移除的照片通常仍是成员）。`GET /api/albums/{id}/suggested_context` 会根据相册中占主导地位的 `narrative_moment`（同样用 `_resolve_album_member_paths` 解析）经 `suggest_from_moments` 映射后给出一个方案建议，并附上该主导时刻在相册中的占比 `share` — 它不写入任何内容；上文的指派仍须显式调用。

对于个别顽固的照片，**类别覆盖**是应急出口 — 它不是方案，而是直接指定类别：`POST /api/comparison/override_category`（受编辑权限限制）会对照配置校验类别名，并把它记录到 `photo_scoring_overrides.category_override`；`POST /api/comparison/clear_category_override` 会移除它，让筛选求值在下一次重新计算时重新做出判断。

这两个开关都持久化在同一张附表 `photo_scoring_overrides(photo_path PK, scoring_context, category_override, source, created_at, created_by)` 中，而不是作为 `photos` 上的列 — `save_photo`/`save_photos_batch` 用 `INSERT OR REPLACE` 写入照片行（`processing/scorer.py`），那样会在下一次重扫时悄悄丢掉该行上的任何新列。`processing/scorer.py` 中的 `Facet._determine_photo_category` 是同时解析这两者的唯一收口点，扫描路径和 `--recompute-average` 一视同仁：有效的 `category_override` 直接胜出；否则由 `ScoringConfig.determine_category(photo_data, context=scoring_context)` 按方案的实际顺序求值。无论用什么方案，只要底层 EXIF 值缺失或无法解析，数值型筛选条件仍然不成立 — 关于仅靠提升无法解决的 `sports`/`shutter_speed_max` 情形，见[评分 — 缺失 EXIF 的陷阱](SCORING.md#缺失-exif-数据的陷阱)。

### 调整全局优先级顺序

`GET|POST /api/config/category_priorities`（受编辑权限限制）读取并重写所有方案据以做增量的基准顺序。`POST` 接受 `{"order": [name, ...]}` — 一个包含全部非 `default` 类别名的等集排列 — 并且是把**现有的优先级多重集重新映射到新顺序上**，而不是重新编号（例如 10/20/30）：这样，对于存储优先级本就唯一的类别，文档中记载的优先级数值依然有意义。优先级缺失或重复的类别 — `--validate-categories` 只把它记为一条日志问题、而非致命错误 — 会在同一次写入中被治愈，而不是以 400 拒绝整次写入：它会被赋予一个超过当前最大值的新值，因此一份手工编辑坏了优先级的配置只要提交任意一个有效顺序就能修复，而不会永远卡住（本端点是 `priority` 的唯一写入方，所以它必须与 `--validate-categories` 在“何为日志问题、何为致命失败”上保持一致）。`default`（优先级 999）被钉在最后，不参与重排。每次写入都会先取一份带时间戳的 `scoring_config.json` `.backup.<timestamp>` 副本 — 只保留最近的 20 份，更旧的会在每次写入时清理 — 并且本写入方与权重编辑器（`update_category_weights`）共用一把锁 — 此前无保护的读-改-写会让两者的并发保存悄悄丢掉对方的改动。

**调整优先级需要重新计算。** 重排本身不会改动任何照片已存储的 `category` — 请运行 `python facet.py --recompute-average`，或从查看器触发 `POST /api/scan/recompute`（受编辑权限限制）并轮询 `GET /api/scan/recompute_status`。`update_all_aggregates` 会输出 `@FACET_PROGRESS` 行（此前只有 `tqdm`），因此可以据此驱动进度条。一次重新计算会在整张 `photos` 表上持有一个长写事务，所以 `--recompute-average`/`--recompute-category` 在整个运行期间会获取一把跨进程的 `facet.LibraryLock`（一个带 PID 标记的 `<db_dir>/.facet_cache/library.lock`），而不只是查看器的内存作业锁：如果扫描已在运行，命令行的重新计算会直接拒绝；如果重新计算正在运行，命令行的扫描也会直接拒绝；查看器的 `POST /api/scan/start`/`POST /api/scan/recompute` 会在派生进程之前查看同一个锁文件，并返回 409 指明持有者（种类、pid、来源）— 这样终端作业与查看器触发的作业就不会再撞车并以 `SQLITE_BUSY` 崩溃。持有者崩溃时会通过操作系统的 PID 存活性检查立刻被发现，因此陈旧的锁会自愈，而不会卡住后续作业。剩下的唯一缺口是命令行的扫描对扫描：从终端启动的两次并发扫描目前仍只是软警告，而不会被拒绝（这是有意的；`--resume` 仍然会硬性拒绝）。如果启用了 `normalization.per_category`，请参见[归一化](#归一化)了解为什么即使是一次无人争抢的重新计算也可能需要跑两遍。

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

用于自动归类的检测阈值。

```json
{
  "thresholds": {
    "portrait_face_ratio_percent": 5,
    "blink_penalty_percent": 50,
    "night_luminance_threshold": 0.15,
    "night_iso_threshold": 3200,
    "long_exposure_shutter_threshold": 1.0,
    "astro_shutter_threshold": 10.0
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `portrait_face_ratio_percent` | `5` | 人脸占画面 > 5% = 人像 |
| `blink_penalty_percent` | `50` | 检测到闭眼时的评分乘数（0.5 倍） |
| `night_luminance_threshold` | `0.15` | 平均亮度低于此值 = 夜景 |
| `night_iso_threshold` | `3200` | ISO 高于此值 = 弱光 |
| `long_exposure_shutter_threshold` | `1.0` | 快门 > 1 秒 = 长曝光 |
| `astro_shutter_threshold` | `10.0` | 快门 > 10 秒 = 星空摄影 |

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
| `silhouette_detection` | `true` | 检测有意为之的剪影 |

---

## 扣分项

针对技术问题的评分扣减。

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "bimodality_threshold": 2.5,
    "bimodality_penalty_points": 0.5,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_pixel_percent": 5,
    "oversaturation_penalty_points": 0.5
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | 噪点高于此值即触发扣分 |
| `noise_max_penalty_points` | `1.5` | 噪点扣分的上限 |
| `noise_penalty_per_sigma` | `0.3` | 超出阈值每个 sigma 扣的分数 |
| `bimodality_threshold` | `2.5` | 直方图双峰系数 |
| `bimodality_penalty_points` | `0.5` | 双峰直方图的扣分 |
| `leading_lines_blend_percent` | `30` | 混入 comp_score 的比例 |
| `oversaturation_threshold` | `0.9` | 平均饱和度阈值 |
| `oversaturation_pixel_percent` | `5` | 预留给像素级检测 |
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

**启用 `per_category` 时，单跑一次重新计算不会收敛。** `compute_percentiles_per_category`（`config/percentile_normalizer.py`）按*当前已存储*的 `photos.category` 列给照片分组，而且它只在最前面运行一次，早于 `update_all_aggregates` 依据新配置重新判定并改写每张照片的类别。因此在任何可能让照片在类别之间移动的改动之后 — 重排优先级、指派或清除拍摄场景评分方案、添加或清除类别覆盖 — 第一次 `--recompute-average` 都是按照片的**旧**类别分组得到的百分位来做归一化，而不是它即将被指派的那个类别。请再运行一次 `--recompute-average`，让按类别的百分位基于此时已正确的 `category` 列计算；只有这样，归一化后的评分才会稳定下来。

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
      "similarity_threshold_percent": 8
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "similarity_threshold_percent": 22
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
| `vram_profile` | `"auto"` | 生效的配置档（`auto`、`legacy`、`8gb`、`16gb`、`24gb`）。可在运行时由 `FACET_VRAM_PROFILE` 环境变量覆盖（见下文）。 |
| `keep_in_ram` | `"auto"` | 在多遍处理的各分块之间把模型留在内存中（`"auto"`、`"always"`、`"never"`）。`auto` 会先检查可用内存再决定是否缓存。 |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | 本配置档要运行的 PyIQA 模型（四个配置档都运行完整集合） |
| `profiles.*.saliency_enabled` | `true`（所有配置档） | 本配置档是否运行 BiRefNet 主体显著性 |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | SigLIP 2 NaFlex 嵌入模型（16gb/24gb） |
| `clip.backend` | `"transformers"` | `"transformers"`（SigLIP 2 NaFlex）或 `"open_clip"`（旧版） |
| `clip.embedding_dim` | `1152` | 嵌入维度（SigLIP 2 为 1152） |
| `clip.similarity_threshold_percent` | `8` | 标签匹配所需的最低 CLIP 余弦相似度 |
| `clip_legacy.model_name` | `"ViT-L-14"` | 旧版 CLIP 模型（legacy/8gb 配置档） |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | 旧版预训练权重 |
| `clip_legacy.embedding_dim` | `768` | 旧版嵌入维度 |
| `clip_legacy.similarity_threshold_percent` | `22` | 旧版 CLIP 的标签匹配阈值 |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | 手动启用 `composition_model: "qwen2-vl-2b"` 时使用的 HuggingFace 路径 — 没有任何配置档默认选用它 |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | 16gb 配置档的标签模型 |
| `qwen3_5_2b.vlm_batch_size` | `4` | 每个 VLM 推理批次的图片数 |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | 24gb 配置档的标签模型 |
| `qwen3_5_4b.vlm_batch_size` | `2` | 每个 VLM 推理批次的图片数 |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | BiRefNet 显著性模型 |
| `saliency.resolution` | `1024` | 推理分辨率 |
| `saliency.mask_threshold` | `0.3` | 二值主体掩膜的 sigmoid 阈值 |
| `saliency.min_subject_pixels` | `50` | 判定检测到主体所需的最少主体像素数 |

### 显存自动检测

当 `vram_profile` 为 `"auto"`（默认）时，系统会在启动时检测可用的 GPU 显存，并选择放得下的最大配置档：

| 检测到的显存 | 选中的配置档 |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| 无 GPU | `legacy`（使用系统内存） |

### `FACET_VRAM_PROFILE` 环境变量覆盖

`FACET_VRAM_PROFILE` 环境变量会在加载时覆盖 `models.vram_profile`（由 `config/scoring_config.py` 处理），因此一份挂载进去的配置无需修改 JSON 就能服务于每个 Docker 配置档。可接受的取值是 `auto`、`legacy`、`8gb`、`16gb` 和 `24gb`；其他取值会被忽略并给出警告（这样拼写错误就不会导致悄无声息的错误扫描）。各配置档的 Docker Compose 覆盖文件（`docker-compose.{legacy,8gb,16gb,24gb}.yml`）已经替你设置好了这个变量。

这项覆盖**只在运行时生效，绝不会被写回 `scoring_config.json`**，即便某个别的编辑（比如一次自动的权重修正）触发了保存也是如此。正是这项保证，才让一份挂载的配置可以同时被多个容器使用：否则，第一个执行保存的容器会把 `models.vram_profile` 钉死为自己的取值，而读取同一文件的其他容器都会继承它，无论它们自己的变量写的是什么。你在文件里自己设置的 `vram_profile` 不会被改动，并且在变量未设置时依然生效。

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

用于 GPU 批处理与多遍模式的统一处理设置。

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

**`gpu_batch_size`** - 在 GPU 上一次前向传播中一起处理多少张图片。受显存限制。会被自动调优：GPU 显存超出限制时下调。

**`ram_chunk_size`** - 在两次模型遍次之间于内存中缓存多少张图片（仅多遍模式）。每个分块只加载一次图片，从而减少磁盘 I/O。受有效内存上限约束（见下文 `memory_limit_percent`）。双向自动调优：占用超过上限时立即下调，而上调只发生在分块边界，并且只有当整个分块的*峰值*占用都低于上限时才会上调。之所以要看峰值，是因为一个分块并不是一次读数 — 各遍次之间每次卸载模型都会让占用几乎跌到谷底，而按谷底扩张，正是让 `ram_chunk_size` 在一个 8GB 容器里从 10 涨到 500、并让下一个分块被 OOM 杀死的原因。

### 设置参考

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `mode` | `"auto"` | 处理模式：`auto`、`multi-pass`、`single-pass` |
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
| `auto` | 依据显存自动选择多遍或单遍 |
| `multi-pass` | 顺序加载模型（显存有限时可用） |
| `single-pass` | 一次加载全部模型（需要大显存） |

### 多遍处理的工作方式

多遍模式不是一次加载全部模型，而是：

1. 按内存分块加载图片（`ram_chunk_size` 默认为 32）
2. 对每个分块顺序运行各模型：加载模型 → 处理分块 → 卸载模型
3. 在最后的聚合遍次中合并结果

每张图片在每个分块中只加载一次，各遍次会按可用显存分组，因此较大的标签/构图 VLM 即使在显存有限时也能运行。

### 自动调优行为

系统会监控资源占用并据此调整：

`memory_limit_percent` 是相对*有效*内存上限来衡量的：在容器或编排器限额（Docker `mem_limit`、Podman `--memory`、Kubernetes `resources.limits.memory`）下取 cgroup 限额，否则取宿主机内存。在 cgroup 限额下，占用现在来自 cgroup 自身的计量，而不是宿主机的空闲内存，因此 `mem_limit` 才真正约束住了自动调优 — 此前即使在受限容器里它读的也是宿主机内存，可能低估占用，让 `ram_chunk_size` 一路涨到被 OOM 杀死。`memory_limit_percent` 是该上限的百分比：在 8GB 限额下的 `85` 约为 6.8GB，而不是宿主机内存的 85%。

| 指标 | 动作 |
|--------|--------|
| GPU 显存 > 上限 | 把 `gpu_batch_size` 下调 25% |
| 内存占用 > 上限 | 把 `ram_chunk_size` 下调 25%（立即） |
| 某个完成的分块峰值占用始终 <（上限 - 20%） | 把 `ram_chunk_size` 上调 25% |
| CPU > 目标 | 建议减少工作线程 |
| 队列超时 > 5% | 建议增加工作线程 |

### 动态遍次分组

显存允许时，多个小模型会一起运行：

| 显存 | 第 1 遍 | 第 2 遍 |
|------|--------|--------|
| 8GB | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12GB | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16GB | CLIP + SAMP-Net + InsightFace + TOPIQ | 标签 VLM |
| 24GB+ | 所有模型一起（单遍） | - |

### 命令行选项

```bash
# 默认：自动多遍，并采用最优分组
python facet.py /path/to/photos

# 强制单遍（一次加载全部模型）
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

RAW 文件如何被转换成像素。这里有两套配置档，而且它们
并不可以互换。

**指标配置档** — 所有评分据以计算的那次去马赛克，也是存储
的人脸框以及 `image_width`/`image_height` 所处的像素空间。它
刻意保持忠实：不做逐帧自适应，整个图库只用一个固定的曝光
增益。

**显示配置档** — 存储的缩略图、照片库和 `/image` 所展示的内容。
它优先采用相机内嵌的预览图，因为其中已经带有机身自身的
色调曲线、动态范围模式和曝光；当没有可用预览时，才回退到
指标配置档的去马赛克结果。

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
| `bright` | `1.62` | 施加于每一次去马赛克的固定曝光增益（`1.0` = LibRaw 自身的电平）。这是本文件中唯一一个任意常数：它对应 darktable 的 +0.7 EV 默认值，文件里没有任何东西决定它 — 在大批量扫描之前，请用 `--check-raw-rendering` 在你自己的图库上验证它 |
| `prefer_embedded_preview` | `true` | 有相机预览图时用它来渲染显示图像。设为 `false` 则一律去马赛克，速度更慢，而且会丢掉相机的色调曲线 |
| `preview_min_sensor_ratio` | `0.5` | 预览图必须覆盖多大比例的传感器，`/image` 才会直接使用它而不去马赛克。尼康、宾得、三星和佳能 CR3 内嵌接近全尺寸的预览（0.98-0.99）；松下为 0.52，而奥林巴斯、富士、索尼和 DNG 内嵌的预览很小（0.29-0.49），因此会去马赛克 |
| `viewer_concurrency` | `3` | `/image` 查看路径同时进行的 RAW 去马赛克数上限，它有独立于上文 `processing.raw_decode_concurrency` 的预算，因此查看器请求绝不会排在扫描或命令行解码作业后面 |
| `faithful_bracket_render` | `true` | 渲染包围曝光照片时完全不做任何校正 — 既不用相机预览，也不施加 `bright` 增益。见[下文](#包围曝光照片按未校正方式渲染)。设为 `false` 则把包围曝光照片当作普通照片渲染 |

### 内存取舍

`viewer_concurrency` 与 `processing.raw_decode_concurrency` 是两份
互相独立的预算，各有各的信号量，谁也不会向对方借用
余量。因此最坏情况下，进程可能同时进行 `library + viewer`
次去马赛克，每次的中间结果峰值大约在 200-400MB — 在内存
吃紧的主机上请调低 `viewer_concurrency`。实际上这份预算多数
时候是闲置的：只有当 `/image` 不得不回退到完整去马赛克时
才会花掉它，而上文的 `preview_min_sensor_ratio` 已经为内嵌预览
足够大的 RAW（尼康、宾得、三星、佳能 CR3）跳过了这一步。
真正会消耗它的，是索尼、富士、奥林巴斯和 DNG
这些机身。

### 为什么没有自动亮度

LibRaw 会把每一帧提亮到大约 1% 的*该帧自身*像素溢出为止，
并用同一帧中最亮的像素替代相机白电平。这两项都是逐帧的，
所以一组包围曝光会被拉平：实测一组跨度从 -3.4 到 +3.3 EV 的
佳能 5 张照片，其中三张暗帧渲染出来的平均亮度是 54-56，
彼此难以区分。而采用固定增益后，同一组的跨度是 8.7 到 160 —
是 18 倍的阶梯，而不是 2.6 倍。

调高 `bright` 会线性地缩放每一次渲染；它永远无法恢复逐帧
行为。曝光指标会随之变化，因此改动之后请重新运行
`--recompute-average`，并重新扫描以改写这些指标
本身。

### 包围曝光照片按未校正方式渲染

`sequence_kind` 为 `bracket` 或 `hdr_panorama` 的照片在显示时
上述两项校正都不施加：既没有相机内嵌预览，也没有 `bright`
增益。其余一切仍遵循显示配置档。普通的 `panorama` *不属于*
包围曝光，因此被排除在外 — 只有每个位置都做了包围曝光的
HDR 全景才和包围曝光照片一同适用这条规则。

原因在于这两项校正都会压缩高光，而高光余量正是包围曝光
中 +EV 那些帧的全部意义。统一增益保留了各帧之间的*相对*
曝光关系，但会削掉亮部：在 `bright` 为 2.0 时，实测 4.85 倍的
阶梯渲染出来只有 3.67 倍，差距完全来自溢出裁切。相机内嵌
的 JPEG 自带色调曲线，出于同样的原因压缩了同一段范围。
对普通照片来说那是更好看的画面；但对包围曝光照片来说，
它恰恰藏起了摄影师正要判断的东西。

这条规则适用于每一个会渲染包围曝光照片的界面，因此它们
不会互相矛盾：`/image`（详情视图、比较放大镜和选片放大镜）
会即时按此渲染，`--refresh-thumbnails` 会把它烘焙进
`photos.thumbnail` 供照片库图块和比较网格使用，而
`GET /api/download` 加 `type=original` 也做同样的转换 — 下载
一张包围曝光照片通常是为了做 HDR 合成，而其他渲染方式
引入的高光溢出在那里是不可恢复的。

有两种下载类型是刻意不受影响的：`type=raw` 复制未经改动
的 RAW 文件，而 `type=darktable` 是“已修图外观”的导出，其全部
意义就在于色调曲线。`GET /api/photo/cull_preview` 同样不受
影响 — 它通过 darktable-cli 渲染，而不是 rawpy。

它*不会*在扫描时生效，因为序列检测在扫描之后才运行，
此时还不知道是否属于包围曝光 — 请先运行 `--detect-sequences`，
再运行 `--refresh-thumbnails`，图块才会跟上。

评分不受影响。指标由 `load_image_from_path` 计算，那是一次
按传感器尺寸进行的独立解码，也是所有存储的人脸框和
`image_width`/`image_height` 的来源；这里的内容都触及不到它。

把 `faithful_bracket_render` 设为 `false`，即可把包围曝光照片
当作普通照片渲染。

### 迁移在此配置档之前扫描的图库

缩略图和直方图是在扫描时烘焙好的，因此改动配置档并不会
追溯性地改变某一行已扫描的内容。`photos.render_version` 记录
了每一行存储的缩略图是由两种 RAW 显示渲染中的哪一种
产生的：

- `NULL` — 早于这个标记
- `1` — 优先使用相机内嵌预览，去马赛克回退路径上施加已配置
  的 `bright` 增益：这是每次扫描烘焙出来的结果
- `2` — 既无预览也无增益：这是包围曝光组中的一帧应当显示的
  样子，也只有 `--refresh-thumbnails` 才能烘焙出来，因为它是
  第一个知道该帧属于包围曝光的遍次（序列检测在扫描之后
  运行，所以扫描永远只能标记为 `1`）

请把这个标记与该行的 `sequence_kind` 对照着读，绝不要单独看：
对普通照片来说 `1` 是最新的，而对后续遍次归入包围曝光组的
照片来说它就是陈旧的。

这里没有什么需要配置的 — 这个标记是记账，不是设置 — 但值得
知道哪些路径会推进它：

- **重新扫描**会改写缩略图和直方图，并且总是标记为
  `1` — 扫描时还不知道序列归属。
- **`--refresh-thumbnails`** 会改写 RAW 缩略图，并按每行当前的
  `sequence_kind` 把它标记为 `1` 或 `2`。这里不会因为标记相同
  而跳过任何行，因此在改动 `bright` 或跑完 `--detect-sequences`
  之后再运行一次，会把一切重建。

只有这两条路径。浏览图库不会修复任何东西：`/image` 是即时
渲染的，所以详情视图始终是最新的，但照片库网格读取的是
`photos.thumbnail`，而只有扫描或 `--refresh-thumbnails` 会改写它。

照片库中那条可关闭的横幅会统计仍停留在旧渲染上的行数。
它读取的是一条 TTL 为一小时的 `stats_cache` 条目，而不是在
每次加载页面时扫描 `photos`，因此重新扫描之后它可能滞后于
实际情况；`python database.py
--refresh-stats` 会立即重新计算它。

若渲染结果整幅全黑，则会被拒绝而不是被存储，该行也会保持
未标记状态，以便后续运行重试。对于严重截断的松下 RW2 文件，
LibRaw 不会失败，而是零填充成一张有效的全尺寸黑图，而无人
值守的迁移正是最不该让这种情况被忽略的场合。这类拒绝会
连同文件名一起记入日志。

---

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

在有更新的 Facet 版本发布时告知安装的管理者。它与浏览器里那句“有新版本可用 —
重新加载”不是一回事：后者只是把页面切换到已经下载好的
资源包；这里说的是还没有人安装过的新版本。

刻意做得很克制。检查在服务端运行，结果会被缓存，因此无论有多少人在看查看器，
一个安装每 `interval_days` 至多向 GitHub 询问一次。请求除了它本身之外不携带任何内容 —
没有令牌，没有标识符，也没有关于图库的任何信息。失败是静默的：GitHub 不可达
只会显示为“未知更新”，绝不会显示为错误。只有拥有编辑权限的用户会收到提示，因为
升级是运维者的工作，别人也无从处理，而且每个浏览器每周至多显示一次这条提示。

把 `enabled` 设为 `false` 可完全停止这次对外请求。

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

为有意为之的多帧照片组命名 — 目前是包围曝光 — 以免它们被当成互相竞争的
备选。曝光阶梯由每张照片已存储的 `f_stop` / `shutter_speed` / `ISO` 推导而来
（`EV = log2(N^2 / t) - log2(ISO / 100)`），因此已有图库仅靠算术就能被标注：
无需重扫，无需解码图像，也不需要模型。

一段连续照片要成为候选，必须满足：各帧来自同一台相机、彼此间隔不超过
`max_gap_seconds`、构图保持一致（pHash 上的 `max_hamming`），且它们的 EV 构成
一个单向、等间距、至少 `min_frames` 帧、跨度不小于 `min_span_stops` 的阶梯。
正是“等间距”把包围曝光与手持连拍穿过变化光线的漂移区分开来。

每一帧都会被标记 `sequence_ev_offset`，即它相对该组基准帧的曝光补偿 — 符号
与相机标注 AEB 组的方式一致，因此 `-2` 是暗帧、`+2` 是亮帧。当某个连拍组
恰好就是一组包围曝光时，它的 `is_burst_lead` 会移到那张基准帧上，这样默认的
照片库展示的就是曝光正确的那张，而不是碰巧得分最高的那一档
曝光。

基准帧是阶梯的正中一级。帧数为偶数时会有两级与中心等距，此时基准取直方图
两端溢出较少的那一张（`shadow_clipped` / `highlight_clipped`）— 按测光拍摄的
那一帧承载着场景，它两侧的级都被推得足够远而产生溢出。若两帧都未被测量，
或溢出的端数相同，则较早的那一帧胜出。奇数级的阶梯无论溢出情况如何都以
中间帧为中心，因此对称的 `(-2, 0, +2)` 组不受影响。

通过 `--detect-sequences` 运行；它也会在每次扫描结束、连拍分组之后自动运行。

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

**为什么 `min_frames` 出厂值是 `3`。** 阶梯的四项检验中有两项对只有两帧的情况
是空洞的：单个步长必然是单向的、也必然是均匀的，于是只剩下“两帧、相隔片刻、
构图相似、相差一挡以上”— 而这既能描述一组两帧 AEB，也同样能描述摄影师调了
个补偿再拍一张。在一个 124,886 张照片的图库上实测，`2` 会在默认设置找到的
226 组之外再多收 381 组，而证据表明其中多数并不是包围曝光：56% 的跨度不足两挡，
而已确认的组里有 99.6% 跨度在两挡以上；它们最常见的溢出形态是两帧都偏暗，
而不是已确认组那种一端暗、一端亮的跨接。

更糟的是，一对确实*是*三张组残留下来的照片，其实是相邻的两个侧级，而存储的
任何信息都说不出缺失的那一级在哪一侧 — 于是 `sequence_ev_offset` 的 `0` 会落在
一张相机从未测光过的帧上，而 `hide_brackets`（默认开启）会把另一张藏起来。
只有当你确实拍两帧 AEB，并且宁愿承担这些误判也不愿漏掉这些组时，才把它
设为 `2`。

---

## 全景检测

全景源照片是为了拼接而拍的，不是为了互相竞争，因此连拍检测会把它们当作互相竞争的备选，只留一张、藏起其余。这一遍次依据几何证据为它们命名 — 在已存储的 640px 缩略图上计算相邻帧之间的 SIFT 特征和 RANSAC 单应矩阵。不解码原图，不用模型，也不需要额外依赖。

把扫拍与连拍区分开的是*累积*漂移，而不是单帧位移：真正的全景大约以 90% 的重叠拍摄，因此一步只移动画面的 5-18%，而在一整段中，连拍是在零附近抖动，扫拍则是持续行进。普通扫拍和 HDR 扫拍是两种不同的类别，按曝光跨度区分。

阈值是对照一个 12.6 万张照片的图库中人工确认的 26 组全景和 8 组非全景校准出来的。实测精确率约 96%；召回率则是刻意不完整的 — 垂直方向的低漂移扫拍和位置很少的全景会低于漂移下限而被漏掉。漏掉一组全景没有代价；把纪实照片误标却会损害信任，而按组粘性的手动修正可以纠正这两个方向。

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
| `min_frames` | `8` | 被视为全景的最短连续帧数。这是最强的单一判别项：已确认的非全景组都不超过 6 张 |
| `min_drift` | `0.43` | 一段连续照片要成立所需的总扫拍量，以画面宽度计。已确认的反例集中在 0.36-0.40，而最低的已确认正例是 0.46 |
| `min_inliers` | `25` | 一对照片算作匹配所需的 RANSAC 内点数 |
| `max_step` | `0.9` | 单步最大位移，以画面宽度计 — 超过它就算场景切换 |
| `back_tolerance` | `0.02` | 某一步可以逆着扫拍方向移动多少而不终止这一段 |
| `max_ortho` | `0.15` | 整次扫拍中允许的侧向游移 |
| `ortho_ratio` | `0.25` | 按漂移量的比例给出的额外侧向预算，以免长扫拍被误罚 |
| `step_ortho_abs` | `0.02` | 单步中允许的侧向移动，超过即读作重新构图 |
| `step_ortho_ratio` | `0.5` | 同一限制，但按该步自身大小的比例计 |
| `hdr_min_span_stops` | `1.5` | 曝光跨度超过此值的扫拍算作 HDR 全景。已确认的普通扫拍跨度为 0.0-0.7 挡，HDR 的为 2.0-4.4 |
| `sift_features` | `400` | 每张缩略图的特征数。该语料在 250 时仍能检出；400 留有余量 |
| `match_ratio` | `0.75` | 特征匹配必须优于的 Lowe 比率才会被保留 |
| `workers` | `0` | 并行工作进程数；`0` 表示按核心数选取。其扩展性达不到核心数 —— 开销主要来自各工作进程争抢的随机缩略图读取 |
| `probe_stride` | `8` | 用于跳过普通连拍的低成本静止段探测之间相隔的帧数 |
| `probe_min_drift` | `0.05` | 探测点处低于该移动量就把这一段判为静止而放弃 |
| `max_run_frames` | `500` | 参与测量的候选段最长帧数。一次扫拍从不需要这么多帧，这个上限也约束了每段的特征缓存（每个工作进程每帧约 220 KB） |

改动这些设置本身不会带来任何变化 — 检测是一个批处理遍次，因此请重新运行 `--detect-panoramas`（或使用查看器中的重新运行操作），改动才会体现在照片库和选片信息流中。改动其中任何一项都会让增量水位线失效，这样下一次运行会重新测量整个图库，而不是复用按旧阈值校准出来的标注。

---

## 连拍评分

连拍选片用来计算综合分、从而在每个连拍组中挑出最佳照片的权重。各权重之和应为 1.0。

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

使用感知哈希（pHash）比对，在全库范围内检测重复照片。

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
| `prefilter_hamming` | `12` | 可选覆盖项（随附文件中没有）。两张照片都有嵌入时，用于筛出候选集的第一阶段宽松汉明门限（会被强制 >= 严格门限） |
| `embedding_cosine_threshold` | `0.90` | 可选覆盖项（随附文件中没有）。第二阶段的 SigLIP/CLIP 余弦门限：宽松 pHash 候选只有余弦值 >= 此值时才会合并 |

检测分两个阶段：先用宽松的 pHash 得到候选（保召回），再用严格的嵌入余弦门限确认（保精确）。没有嵌入的照片会回退到仅用严格 pHash 的判据，因此在缺少嵌入时行为不变。

运行 `python facet.py --detect-duplicates` 来检测并归并重复照片。运行 `python facet.py --sweep-dedup-thresholds [labels.json]` 来评估余弦门限 — 提供标注 JSON 时它会打印一张精确率/召回率表格，否则打印候选余弦值的分布，以及该门限拒绝了多少次严格 pHash 碰撞。

---

## 扩展 IQA 层（可选）

较重的/实验性的画质评分器，会添加额外的列；**它们绝不是 TOPIQ 的替代品**。`qrealign` 默认为 `"auto"` — 在 `8gb`/`16gb`/`24gb` 配置档下**开启**，在 `legacy`/CPU 下**关闭** — 它是扩展层中第一个从 `8gb` 配置档起就能用的评分器（它所取代的 Q-Align 从来放不进 16GB）。`aesthetic_v25` 和 `deqa` 仍然**默认关闭**。启用之后，这些扩展评分器会**在普通扫描过程中**运行并写入各自的列；加载或显存失败会被记入日志，对应的列留作 `NULL`（扫描绝不会中止）。

```json
{
  "iqa_extended": {
    "qrealign": "auto",
    "aesthetic_v25": true,
    "deqa": false
  }
}
```

| 设置 | 默认值 | 可接受的取值 | 列 | 说明 |
|---------|---------|-----------------|--------|-------------|
| `qrealign` | `"auto"` | `"auto"` · `true` · `false` | `qrealign_score` | Q-ReAlign-Mini 0.8B 基于 LLM 的 IQA（由 pyiqa 提供，Apache-2.0 权重，约 2-3GB 显存/内存）。`"auto"` 会在 `8gb`/`16gb`/`24gb` 配置档下开启它、在 `legacy`/CPU 下关闭它；`true`/`false` 则显式覆盖配置档默认值。 |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5（SigLIP 头，约 2GB）。需要 `aesthetic-predictor-v2-5` 包。**已弃用：** 采用 AGPL-3.0 许可，且上游自 2024-12-18 起无人维护 — 请优先使用 `qrealign`。 |
| `deqa` | `false` | `true` / `false` | `deqa_score` | DeQA-Score 视觉语言模型 IQA（需 16GB 以上 GPU；否则跳过并留作 NULL）。 |

**请为你启用的功能安装可选依赖**：`pip install -e .[iqa-extended]`（会装上 `aesthetic-predictor-v2-5`），或者取消 `requirements.txt` 中对应那一行的注释。Q-ReAlign 随 `pyiqa` 一同提供；DeQA-Score 通过 `transformers` 下载。

启用之后，每项指标都会被纳入加权聚合，但默认权重为 0，因此在你给它赋权之前，`--recompute-average` 的结果逐字节不变。运行 `python facet.py --eval-iqa-srcc` 可以衡量每项指标对照你自己的星级评分在图库上的排序表现如何。

**在查看器中的呈现。** 当这些列中任何一列有值时，查看器会在照片详情的**画质**面板中显示该数值（`Q-ReAlign`、`Aesthetic V2.5`、`DeQA`），并在照片库筛选侧栏的**扩展画质指标**下提供相应的范围滑块（`min_qrealign`/`max_qrealign`、`min_aesthetic_v25`/`max_aesthetic_v25`、`min_deqa`/`max_deqa`）。在该层启用之前扫描的照片在这些列上是 `NULL`，而只要给其中某个滑块设置了最小值或最大值，这些照片就会被**排除** — `NULL` 永远不满足 `>=`/`<=` 比较。请在按新启用的指标筛选之前重新扫描，否则那些照片会悄无声息地从照片库中消失。

**健壮性。** DeQA-Score 会加载远程的 `trust_remote_code` 代码，其前向调用签名在不同检查点修订版之间并不一致；它的评分器采取了防御式写法 — 任何预测失败（签名不符、输出形状异常、显存不足）都会被捕获，该图片的 `deqa_score` 留作 `NULL`，而不会让扫描崩溃。

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
      "min_crop_size": 192
    }
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | 最低检测置信度 |
| `min_face_size` | `20` | 最小人脸尺寸（像素） |
| `blink_ear_threshold` | `0.28` | 用于闭眼检测的眼睛纵横比 |
| `min_faces_for_group` | `4` | 判定为合影所需的最少人脸数（在 `--recompute-average` 时重新计算） |
| `enable_3d_landmarks` | `false` | 可选覆盖项（随附文件中没有；代码默认 `false`）。加载 InsightFace 的 `landmark_3d_68` 模块以提取头部姿态（偏航/俯仰/翻滚）。额外占用约 5MB 的 ONNX 权重。目前仅供参考；日后的侧脸/剪影优化会读取它。 |
| `eyes_closed_max` | `4.0` | 单张人脸的睁眼评分（0–10），低于或等于此值时选片暗房会把该人脸标记为闭眼。它驱动红/橙/绿的人脸圈以及睁眼阈值滑块（原本是硬编码常量） |
| `poor_expression_min` | `4.0` | 单张人脸的微笑/表情评分（0–10），低于此值时暗房会标记表情欠佳。它驱动表情人脸圈和对应滑块（原本是硬编码常量） |
| `blendshapes.enabled` | `true` | 当 MediaPipe 及 `face_landmarker.task` 模型包可用时，使用基于外观的 MediaPipe 混合形状评分来得到单张人脸的 `eyes_open_score` / `smile_score`；为 true 时它们会取代基于关键点几何的评分，否则会自动运行几何回退方案。这是可选依赖 — 请用 `pip install mediapipe==0.10.35 --no-deps` 安装（切勿直接 `pip install mediapipe`）。见 [FACE_RECOGNITION.md](FACE_RECOGNITION.md#逐张人脸的表情信号睁眼--微笑)。 |
| `blendshapes.min_crop_size` | `192` | 若人脸带留白的裁切图短边小于此值（像素），则回退到几何评分，而不是把一张很小的人脸放大 |

---

## 人脸聚类

用于人脸识别的 HDBSCAN 聚类。

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

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `enabled` | `true` | 启用人脸聚类 |
| `min_faces_per_person` | `2` | 每个人物最少的照片数 |
| `min_samples` | `2` | HDBSCAN 的 min_samples 参数 |
| `auto_merge_distance_percent` | `15` | 在此距离内自动合并 |
| `clustering_algorithm` | `"best"` | HDBSCAN 算法 |
| `leaf_size` | `40` | 树的叶子大小（仅 CPU） |
| `use_gpu` | `"auto"` | GPU 模式：`auto`、`always`、`never`（见下文说明） |
| `merge_threshold` | `0.6` | 用于匹配的质心相似度 |

**GPU 聚类说明（`use_gpu`）：**

- 需要可选的 `cuml` + `cupy` 包。Docker GPU 镜像已内置 cuML，因此 GPU 配置档开箱即可在 GPU 上聚类。
- `legacy` 配置档无论 `use_gpu` 为何都会被**强制使用 CPU** 聚类（它刻意回避 GPU 模型），因此即便在有 GPU 的主机上也始终用 CPU 聚类。
- 即使在 GPU 配置档下，聚类器也只有在确实存在 CUDA 设备时才会使用 GPU — 当 cuML/cupy 能导入但找不到可用 GPU 时（例如以 `legacy` 模式运行 GPU 镜像），一道 `cupy` 设备计数保护会回退到 CPU HDBSCAN。
- 若 cuML 不可用，`always` 会给出警告并回退到 CPU；聚类过程中出现的任何 GPU/cuML 错误也会优雅降级为 CPU HDBSCAN，而不是中止整次运行。

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

**注意：** 诸如 `similarity_threshold_percent` 之类 CLIP 专属的设置位于 `models.clip` 一节中。

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
      "tooltip_mode": "hover",
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
| `edition_password` | `""` | 解锁编辑模式的密码（留空 = 禁用） |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | 进行优化所需的最少比较次数 |
| `pair_selection_strategy` | `"learning"` | 配对策略：`learning`（冷启动阶段按嵌入多样性，训练完成后按排序分歧）、`uncertainty`、`boundary`、`active`、`random` |
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
| `needs_naming_min_faces` | `5` | 自动聚类出的簇要出现在 `/persons` 的“待命名”区域所需的最少 face_count |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | darktable-cli 的可执行文件名或绝对路径 |
| `darktable.profiles` | `[]` | 具名的 darktable 导出配置数组（见下文） |
| `darktable.profiles[].name` | *（必填）* | 配置的显示名称（用于下载菜单和 API 的 `profile` 参数） |
| `darktable.profiles[].hq` | `true` | 传入 `--hq true` 以进行高质量导出 |
| `darktable.profiles[].width` | *（省略）* | 输出最大宽度（省略则为完整分辨率） |
| `darktable.profiles[].height` | *（省略）* | 输出最大高度（省略则为完整分辨率） |
| `darktable.profiles[].style` | *（省略）* | 导出时套用的 darktable 样式名（`--style`） |
| `darktable.profiles[].apply_custom_presets` | `true` | 为 `false` 时会传入 `--apply-custom-presets false`，从而只渲染显式指定的 `style`（不套用自动应用的预设） |
| `darktable.profiles[].extra_args` | `[]` | 额外的命令行参数（例如 `["--style-overwrite"]`） |
| `darktable.cull_styles` | `[]` | 在选片暗房中作为“已修图外观”预览提供的具名 darktable 样式（`GET /api/photo/cull_preview`）。为空 = 隐藏样式选择器。每个样式**必须已经存在**于运行查看器那个用户的 darktable 配置中；样式名会原样传给 `--style`。 |
| `darktable.cull_styles[].name` | *（必填）* | darktable 样式名（传给 `--style`，并由端点校验） |
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
| `sort` | `"aggregate"` | 默认排序列 |
| `sort_direction` | `"DESC"` | 默认排序方向（`"ASC"` 或 `"DESC"`） |
| `hide_blinks` | `true` | 默认隐藏闭眼照片 |
| `hide_bursts` | `true` | 默认只显示连拍最佳照片 |
| `hide_duplicates` | `true` | 默认隐藏非代表帧的重复照片 |
| `hide_brackets` | `true` | 默认只显示包围曝光组的基准曝光 |
| `hide_panoramas` | `true` | 默认每组全景只显示一张代表帧 |
| `hide_details` | `true` | 默认在卡片上隐藏照片详情 |
| `tooltip_mode` | `"hover"` | 提示浮层的触发方式：`"hover"`、`"click"`、`"off"` 或 `"panel"`（停靠侧栏，而非浮动提示 — 见下文的 `panel_activation`）。取代了此前的 `hide_tooltip` 布尔值。 |
| `panel_activation` | `"both"` | 当 `tooltip_mode` 为 `"panel"` 时，哪种手势会重新指定停靠侧栏所选的照片：`"hover"`、`"click"` 或 `"both"`。对其他提示模式无效。默认的 `"both"` 保持原有的面板行为 |
| `hide_rejected` | `true` | 默认隐藏已淘汰照片 |
| `gallery_mode` | `"mosaic"` | 默认的照片库布局（`"grid"` 或 `"mosaic"`） |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | FastAPI 服务器允许的 CORS 来源。在远程托管时请加上你的域名或反向代理 URL。 |
| **security_headers** | | |
| `security_headers.content_security_policy` | _（对 SPA 安全的默认值）_ | Content-Security-Policy 响应头的值。默认是一条允许 SPA 自身资源的策略（内联主题脚本/样式、Google Fonts、OpenStreetMap 图块、同源 API）。设为 `""` 可禁用，或提供一条更严格的策略。 |
| `security_headers.hsts` | `false` | 发送 `Strict-Transport-Security`。仅在查看器通过 HTTPS 提供服务时才启用。 |
| **其他** | | |
| `cache_ttl_seconds` | `3600` | 内存中统计/查询缓存的 TTL。全库统计计算可能耗时数分钟，因此 TTL 短于计算耗时就意味着缓存永远命中不了 |
| `notification_duration_ms` | `2000` | 提示条显示时长 |
| `moment_confidence_min` | `0` | 存储的 `narrative_moment_confidence` 后验概率（0–1）低于此值时，时刻标签会在场景页头部、选片场景分组头部以及照片库的照片提示浮层中以变暗方式渲染，并加上“（不确定）”后缀。`0` = 永不变暗 |

### 卡片角标与溢出裁切

`viewer.badges` 用来逐个开关照片库卡片上的角标。所有早于这个配置块
就已存在的角标默认都是 `true`，因此不写这个块不会改变任何
行为。

```json
{
  "viewer": {
    "badges": {
      "favorite": true,
      "star_rating": true,
      "rejected": true,
      "sequence_kind": true,
      "sequence_override_pending": true,
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
| `badges.sequence_kind` | `true` | 包围曝光/全景角标，仅当对应的隐藏开关把该组折叠起来时才显示 |
| `badges.sequence_override_pending` | `true` | 表示某项全景修正正在等待下一次检测运行的时钟角标 |
| `badges.keeper_hint` | `true` | 来自习得留存模型的“本组中还有更好的一张”箭头 |
| `badges.best_of_burst` | `true` | 连拍代表帧上的“最佳”角标。仅在 `hide_bursts` 关闭时显示 — 开启时，屏幕上的每张连拍照片本来就是所在组的代表帧 |
| `badges.clipping_highlight` | `true` | 为高光溢出超过 `clipping.badge_percent` 的照片加角标 |
| `badges.clipping_shadow` | `false` | 暗部死黑的同类角标。默认关闭：暗部溢出常常是刻意为之（剪影、夜景、低调影像） |

`viewer.clipping` 是卡片角标、直方图标记和照片库筛选三者共用的
唯一一份“溢出”定义，因此这三者不会互相
矛盾。

| 键 | 默认值 | 说明 |
|-----|---------|-------------|
| `badge_percent` | `5` | R/G/B 中最差通道的像素占比，超过此值的照片会在照片库卡片上加角标。在 28 张照片的样本上实测：最差通道的高光溢出中位数为 0.31%、p90 为 2.35%，因此 5% 大约每 25 张触发 1 张 |
| `indicator_percent` | `1` | 直方图自身 R/G/B 端点标记的阈值。比角标更精细，因为此时你已经在看单张照片 |
| `histogram_mode` | `"rgb"` | **详情面板**直方图的官方默认值：`"luma"`、`"rgb"`，或单个通道（`"r"` / `"g"` / `"b"`）。用户为该界面自己做的选择会存在 `localStorage` 的 `facet_histogram_mode` 下，并优先于此项 |
| `tooltip_histogram_mode` | `"luma"` | **悬停/固定提示浮层**直方图的官方默认值，取值同样是那五种。它刻意独立于 `histogram_mode`，并持久化在自己的 `localStorage` 键（`facet_histogram_mode_tooltip`）下：面板是用来细看一张照片的，逐通道细节值得占用空间；提示浮层是用来快速扫过许多照片的，一条朴素的亮度曲线通常读起来更快。设置其中一个绝不会改动另一个，而且只有在提示浮层被固定时（停靠侧栏，或 `tooltip_mode: "click"`）才会渲染切换控件 — 在普通悬停模式下它只以只读方式显示解析出的模式 |

**溢出是按通道、恰好在第 0 格和第 255 格上测量的。** 它以最差通道的
像素百分比存储在 `photos.channel_clip_shadow_pct` / `channel_clip_highlight_pct`
中 — 这与 `shadow_clipped` / `highlight_clipped` 标志是*不同的*测量：
后者是二值的，覆盖 0–30 和 225–255 的亮度带，并参与
`exposure_score`。

**`NULL` 表示未知，绝不表示干净。** 如果一张照片存储的直方图早于逐通道
格式，它就没有通道数据，因此既不带角标，也不匹配照片库筛选的任何一侧。
运行 `python facet.py --backfill-clipping` 可为已经保存了完整直方图的行推导
出这些列 — 它只读取数据库，不解码任何图像，并且可以中断续跑。

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
| `show_scan_button` | `false` | 为超级管理员用户显示触发扫描的按钮（要求查看器所在主机有 GPU） |
| `metrics_enabled` | `false` | 启用公开的 `GET /metrics` Prometheus 端点。默认关闭 — 它会暴露照片/人物/人脸数量、数据库大小和进程内存；仅当该端点只能从抓取端网络、而非公网访问时才启用。 |
| `show_semantic_search` | `true` | 显示语义搜索栏（使用 CLIP/SigLIP 嵌入进行以文搜图） |
| `show_albums` | `true` | 显示相册功能（创建、管理和浏览照片相册） |
| `show_critique` | `true` | 在照片卡片上显示 AI 点评按钮（基于规则的评分拆解） |
| `show_vlm_critique` | `true` | 启用由 VLM 驱动的点评模式（需要 16gb/24gb 显存配置档）。该键缺失时代码回退为 `false`。 |
| `show_embed_metadata` | `true` | 在编辑模式下为每张缩略图显示“将元数据写入文件”操作（通过 exiftool 把星级/关键词嵌入原图） |
| `show_memories` | `true` | 显示“那年今日”回忆对话框（往年同一日期拍摄的照片） |
| `show_captions` | `true` | 在照片卡片上显示 AI 生成的照片描述 |
| `show_timeline` | `true` | 显示可按日期导航、按时间顺序浏览的时间线视图 |
| `show_map` | `true` | 显示基于 GPS 位置的地图视图（需要 Leaflet）。该键缺失时代码回退为 `false`。 |
| `show_capsules` | `true` | 显示照片胶囊视图（按主题分组的精选照片幻灯片） |
| `show_folders` | `true` | 显示按照片目录结构进行的文件夹浏览 |
| `show_scenes` | `true` | 显示场景视图（`/scenes`），它把连拍代表帧按时间顺序聚成场景，便于按故事顺序选片 |
| `show_my_taste` | `true` | 显示由个人排序模型习得评分支撑的“我的偏好”排序，并附带覆盖率/准确率的置信角标 |
| `show_social_export` | `true` | 显示仅编辑模式可用的**社交平台裁切**下载菜单（按社交比例预设、感知主体位置的裁切）。见[社交平台导出](#社交平台导出) |
| `show_portfolio_export` | `true` | 显示仅编辑模式可用的**导出作品集**相册操作（自包含的静态 HTML 图库）。见[作品集导出](#作品集导出) |
| `show_proofing` | `false` | 在共享相册上启用客户选片：一个分享链接（可再加 PIN 码）让没有账号的客户为照片点心形并留言，相册所有者可在受编辑权限限制的对话框中查看。默认关闭。见[客户选片](#客户选片) |

**内存优化：** 设置 `show_similar_button: false` 可避免加载 numpy，从而减小查看器的内存占用。相似照片功能需要用 numpy 计算 CLIP 嵌入的余弦相似度。

### 客户选片

`viewer.features.show_proofing`（默认 `false`）可把任意共享相册变成一个客户选片界面。一个分享链接 — 可再由 `viewer.proofing.pin` 加以限制 — 让没有账号的客户用分享令牌换取一个短期会话，然后为照片点心形并留言。选片结果存放在专用的 `album_client_picks` 表中，范围限定于该相册的照片，并与所有者自己的评分完全隔离（它们绝不触碰 `photos.is_favorite` / `user_preferences`，也绝不用于训练个人排序模型）。所有者可在相册卡片上受编辑权限限制的对话框中查看这些选片。

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
| `proofing.pin` | `""` | 客户（连同分享令牌）必须输入才能开启选片会话的可选 PIN 码。留空 = 不需要 PIN。校验有速率限制，且按字节安全比较 |
| `proofing.session_minutes` | `1440` | 客户选片会话令牌的有效期（分钟，默认 24 小时）。相册取消共享或选片功能被禁用时，会话也会立即失效 |

### 路径映射

把数据库中的路径映射到本地文件系统路径。当照片是在一台机器上评分的（例如使用 UNC 路径的 Windows），而查看器运行在另一台机器上（例如带挂载点的 Linux NAS）时，这很有用。

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
| `path_mapping` | `{}` | 从源前缀到目标前缀的字典。在提供原尺寸图像或做 VLM 点评时，以源前缀开头的数据库路径会被改写为使用目标前缀。 |

**工作方式：**
- 只在**从磁盘读取文件**时生效（提供原尺寸图像、文件下载、VLM 点评）。数据库中的路径绝不会被修改。
- 反斜杠/正斜杠的归一化会自动处理：`\\NAS\Photos\img.jpg` 和 `//NAS/Photos/img.jpg` 都能匹配。
- 各条映射按顺序求值；第一个匹配上的前缀胜出。
- 路径映射的目标目录会自动加入扫描目录白名单，用于多用户安全检查。

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

设置之后，用户必须先通过认证才能访问查看器。

### 查看器性能

在运行查看器时覆盖全局的 `performance` 设置。这对内存较小的 NAS 部署很有用 — 评分需要较多资源，而查看器并不需要。

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200,
      "face_cache_size": 50
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
| `face_cache_size` | `500` | 内存中人脸缩略图缓存的最大条目数 |

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

> **注意：** `wal_checkpoint_minutes` 是一个可选覆盖项，**不**存在于随附的 `performance` 块中（后者只包含 `mmap_size_mb`、`cache_size_mb` 和 `slow_request_ms`）。要改变其默认值 `30`，请显式添加它。

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | SQLite 内存映射 I/O 的大小 |
| `cache_size_mb` | `128` | SQLite 缓存大小 |
| `wal_checkpoint_minutes` | `30` | 可选覆盖项（随附文件中没有）。查看器后台执行 `PRAGMA wal_checkpoint(TRUNCATE)` 的间隔（分钟）。可防止长期运行的部署出现 WAL 膨胀。设为 `0` 可禁用。 |
| `slow_request_ms` | `1000` | 查看器 API 请求耗时超过这么多毫秒时，会以 WARNING 级别并带 `SLOW` 标记记入日志。设为 `0` 可禁用。 |

---

## 存储

控制缩略图和嵌入存放在哪里。默认是 SQLite 数据库中的 BLOB 列；文件系统模式则把它们作为文件存放在磁盘上，从而减小数据库体积。

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
| `filesystem_path` | `"./storage"` | 文件系统模式的基准目录。缩略图存放在 `<path>/thumbnails/`，嵌入存放在 `<path>/embeddings/`，并按内容哈希组织到子目录中。 |

**文件系统模式细节：**
- 文件按照片路径的 SHA-256 哈希组织，并使用两个字符的子目录以避免单个目录中文件过多（例如 `thumbnails/a3/a3f8..._640.jpg`）。
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

每个 Webhook 会收到一个带 SSRF 防护的 JSON POST（内网/回环地址会被阻止）：

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

按主题分组的精选照片幻灯片。照片胶囊由你的照片库自动生成，并按可配置的 TTL 缓存。

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

位置和旅程胶囊通过 `reverse_geocoder` 包进行离线反向地理编码（本地 GeoNames 数据集，约 30MB，不调用任何 API）。结果会以 0.1° 的网格分辨率（约 11 公里）缓存在数据库的 `location_names` 表中。

安装：`pip install reverse_geocoder`

设置 `"reverse_geocoding": false` 可禁用它并回退为显示坐标。

## 相似照片分组

用于 AI 相似照片选片功能的设置，它使用 CLIP/SigLIP 嵌入把视觉上相似的照片归为一组：

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
| `default_threshold` | `0.85` | 把两张照片视为视觉相似所需的最低余弦相似度（0.0–1.0）。值越低分组越大，但视觉相似度也越低。 |
| `min_group_size` | `2` | 构成一个相似照片分组所需的最少照片数 |
| `max_photos` | `10000` | 参与相似度计算时最多载入的照片数（开销为 O(n²)）。图库更大时可以调高，代价是计算时间。 |
| `max_group_size` | `50` | 每个相似照片分组最多的照片数。更大的分组会被拆开，以保持界面可用。 |

## 自动选片

选片暗房的一键自动选片（`POST /api/culling/auto`，受编辑权限限制）。它会在一次遍历中处理整个范围 — 全部分组，或仅连拍／相似照片／场景，还可以进一步限定到某个相册或日期区间。每个分组保留其最佳照片，外加落在由严格度推导出的余量之内的全部照片（与手动暗房滑块相同的保留预算），并以每组的下限兜底，其余的一律淘汰。

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
| `default_strictness` | `50` | 请求中未给出 `strictness` 时使用的保留预算（0–100）。数值越大，每组保留的照片越少（围绕该组最佳照片的余量越紧） |
| `highlights_min` | `8.0` | 应用自动选片时，某组的最佳照片要被收进可选的**精选**相册所需的最低聚合分（幂等） |

`dry_run` 默认开启，会返回逐组的保留/淘汰预览；实际应用时还会额外记录 `source='culling'` 的比较行，并推动一次自动重训练。见 [网页查看器 — 自动选片](VIEWER.md#自动选片)。

## 自动重训练

控制个人排序模型（“我的偏好”）何时自我重训练。每一次选片确认和每一次评分改动，都会累加到该用户“自上次训练以来的新比较数”计数器上；越过 `threshold` 会启动一个空闲计时器，而重训练只有在你静止 `idle_seconds` 之后才开始。

这个空闲窗口很关键：重训练会为每张照片改写一行，而 SQLite 对一个数据库文件只允许一个写入方。在评分连续操作过程中派发它，会与你自己的评分写入争抢，而这正是过去一次长时间重训练导致评分操作失败的原因。等待一次停顿，能把两者分开。

```json
{
  "auto_retrain": {
    "threshold": 25,
    "idle_seconds": 60
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `threshold` | `25` | 用户必须累积多少次新比较才会武装一次重训练。如果你一次评分的批量非常大，并希望这次训练（CPU，耗时数秒到数分钟）摊到更多信号上，可以调高它 |
| `idle_seconds` | `60` | 已武装的重训练真正开始之前，需要多少秒没有评分/选片活动。每一次新操作都会把计时器往后推。`0` 表示立即派发（1.7.3 之前的行为） |

两者都可在运行时由环境变量覆盖，且环境变量优先于 JSON 中的取值 — 这对 Docker 很有用，因为配置常常被烘焙进镜像：

```bash
FACET_RETRAIN_THRESHOLD=100 FACET_RETRAIN_IDLE_S=300 python viewer.py
```

| 变量 | 覆盖的设置 |
|----------|-----------|
| `FACET_RETRAIN_THRESHOLD` | `auto_retrain.threshold` |
| `FACET_RETRAIN_IDLE_S` | `auto_retrain.idle_seconds` |

无法解析的取值会回退到 JSON 设置，而缺失或格式错误的配置块会回退到内置默认值，因此一个拼写错误只会退化成随附行为，而不会禁用自动重训练。这两个值只在启动时读取一次 — 改动它们需要重启。

重训练仍然保留其留出集交叉验证门槛：一次未能超过当前基线的运行不会写入任何内容。

## 按题材区分的选片配置

把每一个选片旋钮打包成一次点击的题材预设：体育只保留一长串连拍中最清晰的一张，婚礼保留更多变体且睁眼与否至关重要，演唱会放宽眼睛/表情门槛，野生动物则完全去掉人脸门槛。选片暗房中提供了预设选择器。

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
| `profiles.<id>.strictness` | 该预设生效时送入自动选片余量计算的保留预算（0–100） |
| `profiles.<id>.eyes_closed_max` | 睁眼评分（0–10）低于或等于此值时该人脸算作闭眼 — 在暗房的人脸角标中覆盖全局的 `face_detection.eyes_closed_max` |
| `profiles.<id>.poor_expression_min` | 表情/微笑评分（0–10）低于此值时该人脸算作表情欠佳 — 覆盖 `face_detection.poor_expression_min` |
| `profiles.<id>.keep_min_per_group` | 该预设下自动选片保留集的每组下限 |
| `profiles.<id>.similarity_threshold` | 选中该预设时暗房采用的相似度分组阈值（百分比） |

端点（只读）：`GET /api/culling/profiles` 返回有序的预设列表以及默认值。自动选片请求（`POST /api/culling/auto`）和逐张人脸的批量接口（`POST /api/culling-group/faces`）都接受一个可选的 `profile` id；请求中显式给出的 `strictness`/`min_keep_per_group` 始终优先于预设。

## 场景

场景视图的设置。该视图把连拍代表帧按时间顺序（依据拍摄时间间隔切分）聚成场景，便于按故事顺序选片：

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
| `max_scene_size` | `60` | 超过此规模的场景会在其内部最大的间隔处递归再切分，这样连续拍摄的活动就不会坍缩成一个巨大的场景 |
| `adaptive` | `true` | 开启时，实际间隔会放宽到本次拍摄相邻间隔中位数的 `adaptive_k` 倍（快速连拍时收紧，稀疏的假期照片则放宽） |
| `adaptive_k` | `6.0` | `adaptive` 开启时施加于间隔中位数的乘数 |
| `split_on_moment_change` | `false` | 开启时（且已计算叙事时刻），会在主导时刻发生变化并持续 `moment_split_min_run` 帧的时间段处再切分 |
| `moment_split_min_run` | `4` | `split_on_moment_change` 的滞回参数 — 新时刻必须连续持续多少帧才会强制产生一个边界 |

## 叙事时刻

对每张照片的场景/活动“时刻”做零样本标注。默认的 **general** 词表覆盖 `celebration`、`dining`、`beach`、`water_activity`、`mountains`、`nature_wildlife`、`cityscape`、`travel_landmark`、`concert`、`sports`、`group_gathering`、`portrait`、`children`、`pets`、`nightlife`、`ceremony`、`scenic_landscape`、`snow_winter`、`home_indoor`、`road_vehicle` 和 `other` — 因此它适用于任何图库，而不只是婚礼（`wedding` 作为可选题材随附）。由 `--detect-moments` 填充（每次扫描结束时自动运行），并以场景名称和照片库筛选条件的形式呈现。这是 Narrative Select 和 AfterShoot 都不具备的能力。

这个信号是**基于描述语义**的：每张照片的 AI 描述用文本塔编码一次并存储下来（`caption_embedding` 列）；时刻则取该描述嵌入与各时刻文本提示词之间**最大池化**后最好的余弦值。当照片没有描述时，存储的图像嵌入是回退方案。描述文本与时刻提示词的匹配比原始图像嵌入干净约 2.4 倍，因此 `caption` 信号采用比 `image` 回退更高的阈值；两者都按后端分别调校（open_clip 的余弦值远低于 SigLIP 的）。`transformers`（SigLIP）的取值是随附的保守默认值 — 如果你运行的是 SigLIP 配置档，请重新调校它们。

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
| `default_event_type` | `"general"` | 当前生效的 `event_types` 词表。`general` = 20 个与题材无关的场景/活动时刻；`wedding` 作为可选题材随附 |
| `pooling` | `"max"` | 每个时刻的得分 = 单条提示词余弦的最大值（最大池化），比取平均更有区分度 |
| `caption_min_confidence` | `0` | 描述质量门槛：大于 0 时，`--generate-captions` 和按需生成描述的端点会跳过未标注、标为 `other`、或存储的时刻置信度低于此值的照片。`0` = 不设门槛 |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`，image `0.20`/`0.10` | top-1 余弦低于此值的照片记为 `other`。先按**信号**（`caption` 与 `image`）再按后端取值 — 描述的余弦值大约高 2.4 倍 |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`，image `0.01`/`0.01` | top-1 与 top-2 余弦的最小差距；低于它这一帧记为 `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | 只在接近平局时起作用的 L1 人脸/标签微调；`weight` 把每项提升限制在余弦尺度内 |
| `priors.caption_tag_scale` | `0.25` | 在描述信号上把**标签**规则按比例缩小（L0 本就已经编码了描述）；结构性规则在两种信号上都保持完整权重 |
| `priors.rules` | （通用规则集） | 声明式的 `{kind, when, boost}` 列表，与词表无关。`kind`：`structural`（人脸几何）或 `tag`。`when` 谓词（全部按与关系组合）：`is_group_portrait`、`face_count_min`/`face_count_max`、`face_ratio_min`/`face_ratio_max`、`tags_any`、`tags_all`。`boost`：`{moment: amount}` — 当前词表中不存在的时刻会被静默跳过，因此同一套规则可以在不同词表之间优雅降级 |
| `priors.event_types.<et>.rules` | `wedding` 覆盖 | 按事件类型给出的规则，在该词表生效时会**替换**全局的 `rules`，从而让共享列表保持与词表无关 |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | L2 时间线平滑（Viterbi）：偏向停留、不做向前推进（与题材无关的词表没有固定顺序），且施加得很轻（`weight=0` = 不平滑） |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | L3 平局裁决（现已可用）：在 16gb/24gb 配置档上启用后，只有后验概率偏低（低于 `min_confidence`）或差距偏小（低于 `min_margin`）的帧，才会在 `--detect-moments` / `--recompute-moments` 期间由该配置档的 VLM 重新分类 |
| `event_types` | `general` + `wedding` | 按事件类型给出的 `{moment: [提示词同义表]}`；改动 `default_event_type` 即可切换题材，也可以添加你自己的 |

> **描述回填的成本。** 描述嵌入只计算一次并存储下来，因此之后每张照片的余弦计算都是免费的。一次扫描只需编码它新增的那寥寥几条描述（便宜、增量），但在已有图库上第一次完整跑一遍会编码全部描述 — 每条描述一次文本塔前向传播，在 GPU 上很快，在 CPU 上则要数小时。请运行一次 `python facet.py --detect-moments`（推荐用 GPU）来完成这次回填；加上 `--limit N` 可以先在样本上验证。

**发现属于你图库的专属词表。** `general` 这套词表是个合理的默认值，但你也可以用 `python facet.py --discover-moments` 提出一套贴合*你自己*图库的词表：它会对存储的 `caption_embedding` 向量做聚类（HDBSCAN），依据各簇的描述为其命名（一个关键词，加上离质心最近的那些描述作为现成的提示词），并把结果作为一个 `event_types.discovered` 块写入 `scoring_config.discovered.json`。请检查它，把 `discovered` 复制到上文的 `event_types` 中，把 `default_event_type` 设为 `discovered`，再运行 `--recompute-moments` 采纳它 — 发现功能只提出建议，绝不会改写正在生效的配置。`--discover-min-cluster-size N` 控制粒度（越小 = 时刻越多、越细）。

## OCR

照片内文字搜索：把你照片*里面*的文字 — 路牌、店招、比赛号码布、书脊、幻灯片、白板、扫描文档 — 读入 `photos.ocr_text`，它是 `photos_fts` 全文索引的覆盖列。填充之后，这些文字就能像任何描述或标签一样在照片库搜索框中被检索到，而 `GET /api/search?scope=text` 会把查询限定在承载文字的列上。

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
| `enabled` | `false` | 总开关。为 `false` 时 `--detect-text` 会拒绝运行，因此这个遍次绝不会被意外触发 |
| `languages` | `["en", "fr"]` | 传给引擎的语言代码。拉丁字母语言可以自由组合；混用不同书写系统（例如 `en` + `ja`）会被 easyocr 拒绝，所以每次运行只用一个书写系统族 |
| `min_confidence` | `0.4` | 丢弃引擎评分低于此值的检测结果（0–1）。如果 OCR 噪声污染了搜索结果就调高它，想抓住模糊或远处的文字则调低它 |
| `full_resolution` | `false` | 对原始文件而不是存储的 640px 缩略图做 OCR。慢得多，只有在文字很小或很远时才值得 — 640px 已经足以辨认路牌、海报和文档标题。原图不可用时会回退到缩略图 |

**哨兵值语义。** 照片从未被评估时 `ocr_text` 为 `NULL`，而一旦读取过并确认其中没有文字，它就是 `''`。正是这个区分让 `--detect-text` 能把范围限定在真正的新照片上，而不必每次运行都重读每一张没有文字的照片；`--recompute-text` 会忽略这个区分并重读全部。FTS5 把 `''` 索引为零个词元，因此没有文字的照片永远不会匹配任何查询。

**无需 `--rebuild-fts`。** `ocr_text` 位于 FTS 同步触发器的 `UPDATE OF` 列表中，因此这个遍次自身的写入会随写随重建每一行的索引。只有当数据库是在 `ocr_text` 加入覆盖索引之前创建的，才需要 `python database.py --rebuild-fts` — `init_database` 会检测到这种旧索引并替你重建。

**引擎。** `easyocr`（Apache-2.0，基于 PyTorch）是默认选择，它复用了 Facet 本就安装的技术栈 — 不会引入第二个 OpenCV，也不会锁定 numpy/torch 的版本。它的权重（约 113MB）在首次运行时从项目自己的 GitHub 发布页下载。`tesseract` 二进制文件加上 `pytesseract` 可作为另一个可选外部工具（就像 `exiftool`），在没有 easyocr 时会被使用，但它是针对扫描页面调优的，识别自然场景文字的效果明显更差。两者都没有安装时，这个遍次会报错退出，而不是悄无声息地什么都不写。

**成本。** 一张 640px 缩略图在 CPU 上大约耗时 0.4 秒，因此 5 万张照片的图库是一个通宵的 CPU 作业 — 它是一次性的回填，之后的扫描只会处理新照片。当 torch 报告有 GPU 时会自动使用 GPU。

## 导出与选片目标位置

任何会把照片文件复制、软链接或移出图库的端点 — 相册“购物篮”导出（`POST /api/albums/{id}/export`，模式 `copy`/`symlink`）以及选片后导出／清理（`POST /api/cull/apply`，动作 `copy_keeps` / `move_rejects`）— 都会写入一个 `target_dir`，而它必须解析到某个被允许的根目录之下，否则请求会在触碰任何文件之前就被拒绝。

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
| `allowed_target_dirs` | *（键不存在）* | 除扫描目录（始终允许）之外，复制/软链接导出或选片后导出／清理还可以写入的额外根目录。**默认不存在** — 开箱状态下，唯一可写的导出目标就是你配置的扫描目录 |
| `cull.allow_trash` | `false` | 选片后导出／清理的 `trash_rejects` 动作是否可以把文件送入操作系统回收站（可恢复，经由 `send2trash`，它是随 Docker 镜像一同提供的基础依赖，因此一旦启用该动作即可使用），而不是只支持 `copy_keeps`/`move_rejects`。默认关闭；查看器会隐藏“丢弃已淘汰照片”选项，而不是提供一个必然返回 403 的选项 |

**多帧照片组与批量操作。** `hide_brackets` / `hide_panoramas`（见[网页查看器 — 默认筛选](VIEWER.md#默认筛选条件)，两者默认都是 `true`）限定了任何*基于选择*的批量操作能触及的范围，包括选片后导出／清理以及从选择项导出相册：当一组被折叠为其代表帧时，对选择项的操作默认只作用于那一帧，而不是该组的其余照片。选片后导出／清理自己的 `include_sequence_siblings` 选项则会把匹配到的照片扩展到它所在的整组，与选择无关；关于它以及其他应急出口，见[网页查看器 — 选片后导出／清理 § 多帧照片组](VIEWER.md#选片后导出清理)。

**解析顺序。** 白名单先取 `allowed_target_dirs`，再取每一个扫描目录（各用户的、共享的，以及 `path_mapping` 的目标）— 因此导出到照片树*内部*无需任何配置，但目标位于其外部时就需要在这里加一条。请求的 `target_dir` 和每一个被允许的根目录在比较之前都会用 `os.path.realpath()` 规范化（解析软链接、折叠 `..`），因此即便软链接本身位于某个被允许的根目录内，只要它解析到根目录之外就会被拒绝。

**按设计失败即关闭。** 当完全没有任何根目录时 — 既没有 `allowed_target_dirs`，也没有配置扫描目录 — 复制/软链接/移动导出会被直接拒绝，而不会退化成可以往任何地方写。实际上，一旦你扫描过图库，这种情形就很罕见，因为扫描目录始终在白名单中。

**排查“拒绝访问”。** 这项检查发生在任何文件系统访问之前，因此被拒绝的目标位置不会碰到磁盘，也不会在服务器日志中产生栈回溯 — 这里的 `403` 是一次有意检查给出的正常 HTTP 响应，而不是服务器错误。目前网页界面对这些端点上的*任何* `403` 都只显示一条通用的“拒绝访问”提示，并不说明原因；请打开浏览器的网络面板，找到失败的 `/api/cull/apply` 或 `/api/albums/{id}/export` 请求，读取其响应体的 `detail` 字段以获知真正的原因（要么是这个白名单，要么是编辑会话已过期）。真正的文件系统/权限失败看起来则不同：请求本身成功（`200`），响应中的 `errors` 计数不为零，而且服务器会为每个失败的文件记录完整的栈回溯 — 容器场景见[部署 — 容器路径语义](DEPLOYMENT.md#容器路径语义)，那里的问题常被误认为是 UID 不匹配。

见[网页查看器 — 选片后导出／清理](VIEWER.md#选片后导出清理)和[网页查看器 — 导出到后期软件](VIEWER.md#导出到后期软件)。

## 社交平台导出

按社交比例、感知主体位置的裁切预设（`GET /api/photo/social_crop`，受编辑权限限制）。每个预设都会把全分辨率原图裁切为目标比例，并以检测到的主体为中心取景 — 也就是能放进图像内部的该比例最大矩形，以主体为中心并在边缘处夹紧。主体框遵循一条回退链：持久化的 BiRefNet 主体框（`photos.subject_bbox`）→ 检测到的人脸框并集 → 普通的居中裁切。见[网页查看器 — 下载](VIEWER.md#下载)。

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

受 `viewer.features.show_social_export`（默认 `true`）控制。`photos.subject_bbox` 列由扫描时的显著性遍次以及 `--recompute-saliency` 写入；在该列出现之前扫描的行会自动回退到人脸并集或居中裁切。

## 作品集导出

把一个相册导出为自包含的静态 HTML 图库，摄影师可以把它直接放到任意网页主机上 — 不需要任何外部工具（thumbsup/sigal）（`POST /api/albums/{album_id}/export-portfolio`，受编辑权限限制）。生成的目录包含 `index.html`（一个纯 CSS 的响应式缩略图网格，加上一个内联的原生 JS 灯箱，**零**外部/CDN 引用 — 完全可离线使用）、一个存放按序命名 JPEG 的 `assets/` 文件夹（不泄露图库路径），以及一个 `manifest.json`。每张照片在磁盘上的**原图**可读时使用原图（缩放到 `max_edge`），原图不可达时（离线的网络共享）回退到存储的 640px 缩略图 BLOB；每张照片实际使用的来源都会记录在清单中。生成过程是确定性且幂等的 — 再次导出只会改写它自己的文件。

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
| `max_photos` | `500` | 超过此规模的相册会被以 400 拒绝（导出是同步的） |
| `max_edge` | `2048` | 导出原图的长边上限（像素）；请求中可以覆盖它（限制在 256–8000 之间） |
| `jpeg_quality` | `88` | 导出图像的 JPEG 质量 |

`target_dir` 会经过与复制/移动导出端点完全相同的白名单（`viewer.export.allowed_target_dirs` 加上扫描目录 — 见[导出与选片目标位置](#导出与选片目标位置)）。受 `viewer.features.show_portfolio_export`（默认 `true`）控制。见[网页查看器 — 作品集导出](VIEWER.md#作品集导出)。

## 照片相框／展示模式

通过三个匿名的静态令牌端点（`GET /api/frame/photos`、`GET /api/frame/image/{id}`、`GET /api/frame/next`），把精选的“最佳照片”提供给无需登录的展示设备 — 智能相框、Home Assistant 仪表盘、ImmichFrame / Immich-Kiosk 风格的展示屏。访问凭据是一个长期有效的不透明**相框令牌**；`tokens` 列表为空即禁用整个功能（每个端点都返回 404）。响应中绝不包含文件系统路径 — 照片是通过由行 `rowid` 派生的不透明签名 id 来寻址的。

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
| `tokens` | `[]` | 不透明的相框令牌（列表）。**为空 = 功能禁用（404）。** 请使用长随机字符串，每台设备一个；删掉某一个即可吊销它。可用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成 |
| `count` | `20` | `/api/frame/photos` 默认返回的照片数 |
| `max_count` | `100` | `count` 查询参数的硬上限 |
| `min_aggregate` | `7.0` | 照片被选入所需的最低聚合分 |
| `max_edge` | `1920` | 提供的 JPEG 的长边上限（像素）；`max_edge` 查询参数可以调低它，但绝不能高于此值 |
| `favorites_only` | `false` | 为 `true` 时只选入已收藏的照片 |
| `categories` | `[]` | 类别名白名单（为空 = 所有类别） |

令牌以 UTF-8 字节做常量时间比较，因此缺少令牌返回 401，而错误或非 ASCII 的令牌返回 403（绝不会是 500）。精选过程会排除已淘汰、废片（`junk_kind`）和闭眼照片，再套用分数下限／收藏／类别筛选；返回的集合是一次按分数加权的随机抽样。Home Assistant 的配方见[网页查看器 — 照片相框／展示模式端点](VIEWER.md#数码相框与展示屏端点)。

相框令牌不是用户登录凭据：它不携带 `user_id`，而且是针对整个图库校验的，因此在[多用户模式](#用户)下它会忽略每个用户的私有 `directories`，并授予对所有用户照片的读取权限，而不只是 `shared_directories`。只有当所配置的每一位用户都能接受这一点时，才签发相框令牌。

## 手机自动上传

在 `/dav` 下提供一个极简的 **WebDAV** 端点，让手机自动上传应用（PhotoSync 之类）可以把照片推送到一个**收件目录**，随后由 `facet.py --watch` 自动评分 — 也就是 PhotoPrism 的移动同步模式。它只是上传管道：绝不触碰用户会话或 JWT。访问方式是 HTTP Basic，使用**共享设备凭据**（`username` / `password`），而不是用户账号。整个 `/dav` 树在**禁用时返回 404** — 只有当 `username`、`password` 和 `inbox_dir` 都设置了，该功能才启用。所有操作都被限制在 `inbox_dir` 之内（目录穿越／绝对路径／软链接逃逸都会被拒绝），上传以流式方式原子写入磁盘，并受 `max_file_mb` 上限约束。

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
| `username` | `""` | HTTP Basic 用户名（共享设备凭据）。**为空 = 功能禁用（404）。** |
| `password` | `""` | HTTP Basic 密码（共享设备凭据）。**为空 = 功能禁用（404）。** 请使用长随机字符串。 |
| `inbox_dir` | `""` | 上传收件目录的绝对路径。**为空 = 功能禁用（404）。** 请把它指向某个被扫描的目录（或其子目录），这样 `facet.py --watch` 就能在上传落地时为其评分。目录会按需创建。 |
| `max_file_mb` | `500` | 单个文件的大小上限（MB）；超出上限的上传会以 `413` 中止，且不会留下部分文件。 |

凭据以 UTF-8 字节做常量时间比较；缺失或错误的 `Authorization` 头会得到 `401`，并带 `WWW-Authenticate: Basic realm="Facet upload"`。已实现的方法：`OPTIONS`、`PROPFIND`（深度 0/1）、`MKCOL`、`PUT`、`MOVE`、`DELETE`、`GET`、`HEAD`（`LOCK`/`UNLOCK` 未实现）。PhotoSync 的配置方法以及一个 `curl` 冒烟测试见[网页查看器 — 手机自动上传](VIEWER.md#手机自动上传)。

## 废片清理

针对非照片“废片”的零样本检测器 — 截图、扫描文档、收据、表情包、演示幻灯片 — 基于**存储的图像嵌入**（不解码图像，也不为每张图片跑一次模型；与叙事时刻同构，只是没有时间平滑）。每种类型都带有一组文本提示词；照片的嵌入会与每条提示词计算余弦值，并按类型做**最大池化**。一组 `not_junk` 对照提示词把关最终判定：只有当最佳废片类型既越过 `min_confidence`、又比最好的 `not_junk` 提示词高出 `min_margin` 时，照片才会被标记 — 否则就存为 `not_junk` 哨兵值（已评估且干净）。`NULL` 表示“未评估”：`--detect-junk` 只标注 `NULL` 的行（并在扫描结束时自动运行），而 `--recompute-junk` 会重新评估整个图库。它填充 `photos.junk_kind`；查看器的**废片清理**复核队列（[VIEWER.md](VIEWER.md#废片清理)）会读取它。

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
| `prompt_template` | `"{desc}"` | 施加于每条提示词的格式串（`{desc}` = 提示词本身）；由于提示词本身就是完整句子，默认是恒等变换 |
| `pooling` | `"max"` | 把各提示词的余弦值汇总回类型的方式：`max`（最好的单条提示词，更有区分度）或 `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`，transformers `0.1` | 最佳废片类型要被纳入考虑所需的最低最大池化余弦值（CLIP/`open_clip` 的余弦值低于 SigLIP/`transformers`，因此每个后端各有一道门槛） |
| `thresholds.<backend>.min_margin` | open_clip `0.06`，transformers `0.02` | 最佳废片类型必须比最好的 `not_junk` 对照提示词高出多少，照片才会被标记 |
| `kinds` | screenshot/document/receipt/meme/slide | `{kind: [提示词同义表]}`；可以自由添加、删除或重命名类型 — 数据库列和查看器队列都会跟随配置 |
| `not_junk_prompts` | 8 条照片提示词 | 描述真实照片的对照集合；正是这道门槛把真正的照片挡在队列之外 |

## AI 点评

由 VLM 驱动的点评（16gb/24gb 配置档）的提示词配置。点评会把完整的规则拆解、扣分项和 EXIF 注入一条可配置的阶梯式提示词，把回复渲染为观察／评价／建议三段，并按照片缓存在 `photos.vlm_critique` 中（按需翻译到 `vlm_critique_translated`）。它针对存储的缩略图运行，因此 RAW 文件也能正确点评，而不会悄无声息地失败；`refresh` 可重新生成。默认的阶梯遵循 AesBench 的四能力结构（感知 → 感受 → 判断 → 建议）：其评价部分会就构图、色彩与光线、对焦/景深与技术执行、主体与瞬间各给出一句简短论断，并与注入的指标相互印证，而不是复述这些数字。

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

选择用于生成描述/标签的视觉语言模型在哪里运行。`local`（默认）使用随 16gb/24gb 显存配置档一同提供的进程内 transformers Qwen 路径 — 对已有安装没有任何改变。两种远程后端则把 Facet 指向一台外部服务器，从而让**本身不带本地 VLM 的 legacy/8gb 配置档**也能生成描述和做 VLM 打标签：选择远程后端之后，VLM 相关功能就不再受显存配置档限制。

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
| `type` | `"local"` | 后端：`local`（进程内 transformers Qwen）、`ollama`（Ollama 原生 REST API），或 `openai_compatible`（任何 OpenAI chat-completions 端点 — LM Studio、vLLM、OpenRouter） |
| `ollama.base_url` | `"http://localhost:11434"` | Ollama 服务器的基础 URL；图片以 base64 形式发送到 `POST /api/generate` |
| `ollama.model` | `"qwen2.5vl:7b"` | Ollama 模型标签（必须是服务器上已拉取的视觉模型） |
| `ollama.timeout_seconds` | `120` | Ollama 调用的单次请求超时 |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | OpenAI 兼容端点的基础 URL，**需包含 `/v1` 后缀**；请求发往 `{base_url}/chat/completions`，图片作为 `image_url` 的 data URI 传入 |
| `openai_compatible.api_key` | `""` | 以 `Authorization: Bearer <key>` 发送的 Bearer 令牌；本地无密钥服务器可留空 |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | 传给端点的模型名 |
| `openai_compatible.timeout_seconds` | `120` | OpenAI 兼容调用的单次请求超时 |

这个共享后端驱动照片描述生成（`--generate-captions` 和按需的 `/api/caption`）、VLM 点评（`/api/critique?mode=vlm`）、VLM 重新打标签（`--recompute-tags-vlm`），以及叙事时刻的 VLM 平局裁决。远程请求失败会作为单张照片的失败呈现（记入日志，标签为空／没有描述），绝不会让整次运行崩溃。扫描过程中的打标签仍使用配置档自带的标签模型；要把远程后端应用到已有图库，请运行 `--recompute-tags-vlm`。

## 成像缺陷属性

零样本的、仅供参考的成像缺陷标注。`--recompute-distortions` 会基于每张照片存储的 CLIP/SigLIP 嵌入，对照 ExIQA 式的对比提示词打分，并把可能存在的缺陷（运动模糊、偏色、过度锐化……）存入一个仅供参考的 JSON 列。它绝不参与聚合分；这些标签会在点评对话框中以警告标签的形式呈现。

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
| `thresholds.<backend>.temperature` | open_clip `0.02`，transformers `0.05` | 施加于对比提示词得分的 softmax 温度，按嵌入后端分别取值（与 `narrative_moments` 一样，open_clip 和 transformers 的余弦值处在不同尺度上） |
| `thresholds.<backend>.min_confidence` | `0.6` | 缺陷标签被保留所需的最低概率 |
| `vocabulary` | `{}` | 对内置缺陷提示词集合的可选覆盖（`{attribute: [提示词同义表]}`）；为空 = 使用模块默认值 |

## 肤色

人像肤色自然度（仅供参考）。`--recompute-skin-tone` 会从存储的人脸缩略图 + 关键点中采样脸颊的 CIELAB 色度，并测量它与相关色温肤色轨迹之间的 CIEDE2000 距离，从而标出肤色偏绿／偏品红／偏蓝／偏黄的人像。它绝不参与聚合分；结果会在点评对话框中以一条肤色说明的形式呈现。

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| 设置 | 默认值 | 说明 |
|---------|---------|-------------|
| `cast_delta_threshold` | `12.0` | 实测肤色色度与肤色轨迹之间的最小 CIEDE2000 差值，超过它才会判定为偏色 |

## Immich 同步

通过 REST API 把 Facet 的星级和收藏单向同步到 [Immich](https://immich.app/) 服务器。资源在一次批量搜索遍次中，经由配置的路径前缀映射按 `originalPath` 解析。用 `--immich-sync` 运行它（先用 `--immich-test` 检查）；见[命令 — Immich 同步](COMMANDS.md#immich-同步)。

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
| `path_map` | `[{facet_prefix, immich_prefix}]` | 从 Facet 路径到 Immich `originalPath` 取值的前缀改写；解析资源时，第一个匹配的 `facet_prefix` 会被换成它对应的 `immich_prefix` |
| `push.ratings` | `true` | 推送星级。会遵循 Immich 的版本安全策略 — 只写入 1–5，绝不写 0/−1 |
| `push.favorites` | `true` | 推送收藏标记 |
| `push.rejected` | `false` | 为在 Facet 选片暗房中被淘汰的照片推送 `rating: -1`。需要 `push.ratings` |
| `push.top_picks_album` | `""` | 可选的 Immich 相册名，用于收集推送时星级超过阈值的照片。留空 = 不建相册 |
| `push.top_picks_min_rating` | `4` | 照片被加入 `top_picks_album` 所需的最低星级 |
| `webhook.token_env` | `""` | 存放入站 webhook 共享密钥的环境变量名。留空（或变量未设置/为空）会禁用该端点 — 它会返回 404 |
| `webhook.header` | `"x-facet-token"` | Immich 工作流在哪个头中发送该令牌 |
| `webhook.max_pending` | `500` | 已记住但尚未评分的路径列表的数量上限，下一次同步会报告它 |
| `timeout_seconds` | `30` | 单次 REST 请求的超时 |

`--immich-sync` 支持 `--dry-run`（解析每一个资源但什么都不写）和 `--user`（在多用户模式下推送该用户 `user_preferences` 中的星级）。只走 REST — Facet 绝不触碰 Immich 的数据库。

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
| `photos_per_group` | `30` | 时间线视图中每个日期分组载入的照片数。数值越大每个日期显示的照片越多，但页面也越重。 |

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
| `cluster_zoom_threshold` | `10` | 从聚合点切换为单个标记的缩放级别。数值越小越早显示单个标记（在更大的视野下就有更多细节）。取值范围：1（世界）到 18（街道）。 |

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
| `target_language` | `"fr"` | `--translate-captions` 的目标语言代码。支持：`fr`（法语）、`de`（德语）、`es`（西班牙语）、`it`（意大利语）、`pt`（巴西葡萄牙语）。使用 Helsinki-NLP 的 MarianMT 模型（CPU，无需 GPU）。 |

## 美学 CLIP（R2）

由缓存的 CLIP/SigLIP 嵌入经文本投影得出的补充性美学评分。提示词可由用户调整以便做 AVA 基准测试 — 衡量任何改动对 SRCC 的影响见 `scripts/benchmark_aesthetic.py`。

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

空数组会回退到烘焙在 `analyzers/aesthetic_clip.py` 中的模块默认值。不要在没有重新跑一遍 AVA 基准测试的情况下调整它们 — 默认值在 `ava_test/` 上的 SRCC 约为 0.52，而改动很容易让它退化到 0.30 左右。

## 添加其他 VLM 标签／点评模型（R3）

每个显存配置档的 `tagging_model` 键（例如 `qwen3.5-2b`）都映射到同一个 `models` 小节中的一个模型条目。若想试用别的 VLM（Pixtral-12B、InternVL-2.5 等）：

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

无需改动任何代码。在把它提升为默认之前，请在约 30 张照片上做一次并排抽查来验证质量。

## 服务器密钥

用来签发会话令牌和照片相框链接的密钥**不是**本文件中的一个键。它位于 `scoring_config.json` 旁边的 `.facet_secret` 中（权限 `0600`，已加入 gitignore），并在首次运行时生成。

- 覆盖方式：`FACET_JWT_SECRET` 环境变量。
- 轮换方式：`python database.py --rotate-secret`。

旧版安装遗留下来的 `share_secret` 会在下一次启动时被移入该文件，并从 `scoring_config.json` 中移除。见[密钥的存放与轮换](DEPLOYMENT.md#密钥的存放与轮换)。
