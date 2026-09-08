# 后期软件互操作实用指南

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md) · **简体中文**

实用的分步指南，帮助你在 Facet 与摄影师真正在用的外部后期软件和数字资产管理（DAM）工具之间双向流转 Facet 的星级、颜色标签和标签。本页假设你已经知道 Facet *确实* 会写出 XMP —— `--export-sidecars` / `--import-sidecars` 选项的完整说明和字段对应关系（`xmp:Rating`、`xmp:Label`、`dc:subject`）请见[命令 — 预览与导出](COMMANDS.md#预览与导出)。

## RAW 附属文件命名陷阱

Facet 把附属文件命名为 `<image><ext>.xmp` —— 例如 `IMG_1234.CR2.xmp` 紧挨着 `IMG_1234.CR2` —— 与 darktable 和 digiKam 使用的约定相同。**Lightroom Classic 和 Capture One 的期望恰好相反：`IMG_1234.xmp`，去掉 RAW 扩展名。** 这两个软件都不会发现 Facet 为专有 RAW 文件（CR2、CR3、NEF、ARW、RAF、RW2、ORF、SRW、PEF —— 除 DNG 以外的全部格式）写出的附属文件，而 Facet 自己的 `--import-sidecars` 同样找不到 Adobe 生态的软件为同一个 RAW 文件写出的附属文件。这是两个生态之间的命名不一致，不是任何一方的 bug。

它**不**影响：
- **JPEG、HEIC、TIFF、PNG、DNG** —— 加上 `--embed-originals`，Facet 就会（通过 exiftool）把元数据*直接写入文件本身*，这样也就不存在 Lightroom／Capture One 会漏掉的附属文件名了。
- **digiKam** —— 两种命名约定都会检查，无论哪一种都能找到 Facet 的附属文件（见下文 [digiKam](#digikam)）。
- **darktable** —— 使用与 Facet 相同的 `<image><ext>.xmp` 约定（见下文 [darktable](#darktable)）。

所以，对于 Lightroom 或 Capture One 的工作流：凡是非专有 RAW 的文件都用 `--embed-originals`，而对于纯 RAW 文件，要预料到附属文件的往返是静默的（不报错，只是什么都没读到）。如果你拍摄 RAW+JPEG，配套的 JPEG 就是实际可用的互操作载体 —— RAW 原封不动地留在磁盘上，而 Facet 的数据库保留具有权威性的星级。

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars`（加上路径可限定范围，例如 `--export-sidecars /photos/2026-wedding`）。加上 `--embed-originals` 还会直接写入 JPEG/HEIC/TIFF/PNG/DNG 文件。
2. 在 Lightroom Classic 的图库模块中选中照片（Ctrl/Cmd+A 全选），然后选择**元数据 → 从文件中读取元数据**。Lightroom 会用附属文件（或上述格式的内嵌元数据）中的内容覆盖其目录里的星级、颜色标签和关键字。

Facet 的淘汰标记（`xmp:Rating = -1`）会被读回为 Lightroom 的排除（Reject）旗标。Facet 的收藏会写出 `xmp:Label = Yellow`，Lightroom 把它显示为**黄色的颜色标签** —— 而不是留用（Pick）旗标。如果你的 Lightroom 工作流依据的是留用旗标而不是颜色标签，请加一个“颜色标签转留用旗标”的步骤，或者改为按黄色标签筛选。

现在还有 `python facet.py --export-manifest` 这条数据源（路径、类别、全部评分、标签，以及与 `--export-sidecars` 相同的星级列 —— 在多用户安装上还可通过 `--export-manifest --user alice` 导出按用户区分的星级），供那些希望拿到 Facet 数据又不想解析 XMP 的工具使用 —— 见[命令 — 预览与导出](COMMANDS.md#预览与导出)。下文的 Facet 增效工具消费的正是这份数据。

### Facet 增效工具（星级与留用旗标）

Facet 仓库里的 `facet.lrplugin/` 是一个 Lightroom Classic 增效工具，它把 Facet 的星级和收藏／淘汰状态**直接写进目录**。它之所以存在，是因为上文提到的两件事无法从 XMP 一侧解决：Lightroom 永远找不到专有 RAW 文件对应的 Facet 附属文件，而 XMP 根本没有承载 Lightroom 留用旗标的通道。该增效工具读取的是一个清单文件，因此它从不与 Facet 服务器通信，不需要密码，即使 Facet 没有运行也能工作 —— 而且因为它按路径而不是按附属文件匹配照片，**纯 RAW 照片库的表现与 JPEG 照片库完全一样**。

**安装**（只需一次）：

1. 把 `facet.lrplugin` 文件夹复制到运行 Lightroom 的机器上。在 macOS 上请先压缩成 zip —— 访达会把 `.lrplugin` 文件夹当作程序包。
2. 在 Lightroom Classic 中：**文件 → 增效工具管理器 → 添加**，选择 `facet.lrplugin` 文件夹，然后点击**完成**。

**使用**（每当你想把 Facet 的判断带进目录时）：

1. `python facet.py --export-manifest /photos/2026-wedding`（路径用于限定导出范围；文件始终以 `facet_manifest.json` 的名字落在当前目录）。如果 Facet 运行在别的机器上，请把它复制到 Lightroom 所在的机器。
2. 在图库模块中选中照片，然后选择**图库 → 增效工具附加功能 → Facet: Apply ratings and flags...**（增效工具界面为英文）。
3. 在对话框中指向 `facet_manifest.json`。该路径会被记住，下次直接可用。
4. **如果 Facet 是在另一台机器上扫描这些照片的，请填写两个路径前缀。** 清单里保存的是执行扫描那台机器的路径（NAS 上是 `/volume1/photos/...`），而 Lightroom 记录的是桌面电脑的路径（`Z:\photos\...`）。请输入指向同一个文件夹的 Lightroom 前缀和 Facet 前缀；两者一致时就都留空。填错这里是首次运行中唯一真正要紧的失败 —— 它只会导致一张照片都匹配不上。
5. 选择范围：选中的照片（默认），或当前文件夹里的全部照片。
6. 点击 **Preview...**（预览）。**此时还什么都没有写入。** 增效工具会报告它在清单中匹配到了多少张照片、有多少张没匹配上，以及会设置多少个星级和旗标。如果匹配数为 0，它会把一个 Lightroom 路径样例和一个清单路径样例并排显示，让你看清前缀应该是什么。
7. 点击 **Apply**（应用）。过程中会显示进度并可以取消；结束时会有一个汇总对话框，说明哪些被设置、哪些被跳过、哪些没有找到。

**它写入什么** —— 仅此而已，并且从不写入你的图像文件：

| Facet 状态 | Lightroom 字段 |
|---|---|
| `star_rating` 1-5 | 星级 |
| 收藏 | 留用（Pick）旗标 |
| 已淘汰 | 排除（Reject）旗标 |

Facet 的星级为 0 表示“没有意见”（见 `xmp_export.score_to_rating`），永远不会被写出。

**覆盖语义** —— 默认情况下，增效工具绝不与你争辩：只有当照片在 Lightroom 中*没有星级*时它才设置星级，只有当照片*没有旗标*时它才设置留用／排除旗标。你手动评过星或打过旗标的内容一律原样保留，并在预览中计入“kept as they are”（保持原样）。勾选 **Overwrite ratings and flags that are already set in Lightroom** 才会改为覆盖它们。这与 `xmp_export.score_to_rating` 中的 `only_when_unrated` 一致，因此增效工具和附属文件这两条路径对待你的手动修改的方式完全相同。

**局限**，实话实说：

- **留用旗标只存在于目录中。** 这是 Lightroom 的设计，不是增效工具的问题：Lightroom 从不把留用旗标写进 XMP，因此它到不了任何其他应用，一旦你从文件重建目录就会丢失。星级则可以通过**元数据 → 将元数据存储到文件**保留下来。
- **Facet 的评分不会作为 Lightroom 的元数据字段加入**，所以没有“aggregate > 8”这样的智能收藏夹。Adobe 的 SDK 只允许增效工具自有的字段以文本或枚举（`sdktext:`）的形式进入搜索词汇表；数值运算符（`>`、`<`、“在范围内”）只属于 Lightroom 内置的条件。把评分经由**星级**传递是有意为之：星级是 Lightroom 自身唯一会按数值筛选和排序的通道。
- **单向。** 之后你在 Lightroom 中改动的星级，要通过上文的 XMP 往返回到 Facet，而不是通过增效工具。
- **撤销**一次只作用于一批：增效工具按每 200 张照片为一块写入，因此按一次 Ctrl/Cmd+Z 会撤销 200 张照片。
- 如果你需要逐行查看哪些路径匹配上了、写入了什么，请在运行前勾选 **Write facet-apply.log next to the manifest**（在清单旁写出 facet-apply.log）。

### Lightroom → Facet

1. 在 Lightroom 中选中照片，选择**元数据 → 将元数据存储到文件**（Ctrl/Cmd+S）。这会把目录中的星级／颜色标签／关键字刷写进 XMP 附属文件（RAW），或直接嵌入文件本身（DNG/JPEG/PSD/TIFF）。
2. `python facet.py --import-sidecars`（可选择限定到某个路径）把它们读回 Facet 的数据库。

### 冲突规则

- **星级和颜色标签遵循“最新者胜”**，比较的是附属文件的 `xmp:MetadataDate` 与照片的 `scanned_at`（Facet 最后一次为它评分的时间）—— 而不是逐条评分的编辑时间戳。比上次扫描更新的附属文件，可能覆盖你在那次扫描*之后*在 Facet 里改过的星级。请让往返保持简单：导出 → Lightroom 读取 → 在 Lightroom 中编辑 → Lightroom 保存 → 导入，中间不要在 Facet 里重新评星。
- **标签和关键字在两个方向上始终合并**（求并集并去重）—— Lightroom 的关键字永远不会抹掉 Facet 的自动标签，反之亦然。
- **多用户**（`--export-sidecars --user alice` / `--import-sidecars --user alice`）：星级会写入 Alice 的 `user_preferences` 行，而不是全局列。无论是否使用 `--user`，关键字都保持全局 —— 它们在用户之间共享。
- 如果你依赖 `photo_tags` 查找表，请在 `--import-sidecars` 之后运行 `python database.py --migrate-tags`，让标签筛选立即看到合并后的关键字。

## Capture One

Capture One 从不像 Lightroom 的自动保存那样写入原始文件或写入持续同步的 XMP 附属文件 —— 它把自己的调整保存在 `.cos` 设置文件（Sessions）或它的目录数据库里，而它的 **Sync Metadata** 首选项有一个双向的“Full Sync”模式，可能会静默覆盖后写入的那一方。通过这个设置来跑双向循环，有丢失 Facet 或 Capture One 任一方修改的风险。安全的做法是**单向，Facet → Capture One**：

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`。
2. 在 Capture One 中，把 **Preferences → General → Sync Metadata** 保持为默认值（不要选“Full Sync”）。
3. 选中导入的图像，右键点击，选择 **Load Metadata**，把附属文件（或内嵌元数据）里的星级／颜色标签／关键字一次性拉进 Capture One 的目录字段。

就那次拍摄而言，请把 Facet 当作 AI 生成的星级和标签的上游权威来源：做一次性的 `Load Metadata` 拉取，之后在 Capture One 内部继续选片，不要把它的元数据同步再接回 Facet 的附属文件。如果你想把 Capture One 的选片结果带回 Facet，请从 Capture One 显式导出为 XMP，再对那个文件夹运行 `--import-sidecars`，把它当成一个独立而有意为之的步骤，而不是自动同步 —— 并且别忘了上文的 [RAW 附属文件命名陷阱](#raw-附属文件命名陷阱)：这只对 JPEG/HEIC/TIFF/PNG/DNG 有效，因为 Capture One 同样把 RAW 附属文件命名为 `<image>.xmp`，而不是 Facet 的 `<image><ext>.xmp`。

## digiKam

从 digiKam 9.1.0（2026-06-07 发布）起，digiKam 原生读取 XMP 附属文件 —— digiKam 这一侧不需要 exiftool —— 而且它会查找两种命名约定（先找 `<image><ext>.xmp`，再回退到 `<image>.xmp`），因此它能找到 Facet 为 RAW 文件写出的附属文件，不受上文那个陷阱影响。运行 `python facet.py --export-sidecars` 之后，在 digiKam 中打开（或刷新）该文件夹，只要 **Settings → Configure digiKam → Metadata → Read from sidecar files** 处于启用状态（默认如此），它就会自动取到星级、颜色标签、关键字和命名的人脸区域。

### Batch Queue Manager 挂钩

你可以用 **Custom Script** 工具，把 Facet 的重新导入折进 digiKam 的批处理队列管理器（Batch Queue Manager，BQM）流程，这样你在 digiKam 中评星或打颜色标签的照片就能回流到 Facet 的数据库，全程不用离开 digiKam。请启用 **Settings → Configure digiKam → Metadata → Write to sidecar files**，让 digiKam 立刻把你的修改持久化到 `<image>.xmp`，然后新建一个队列，其中唯一的工具就是 Custom Script：

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` 是 digiKam 的按文件占位符（在 Linux／macOS 上，BQM 通过 `/bin/bash` 执行脚本并期望有一个输出文件，因此需要 `cp` 透传）。由于 `--import-sidecars` 会扫描整个文件夹，在大批量任务中对每张照片都执行一次是多余的，尽管无害（它是幂等的 —— 未改变的照片会被跳过）。批量很大时，跳过 BQM 挂钩，等队列跑完后手动执行一次 `python facet.py --import-sidecars /path/to/folder` 即可。

## darktable

darktable 在[配置 — 查看器](CONFIGURATION.md#查看器)（`viewer.raw_processor.darktable` 导出配置文件／样式）和[查看器 — 下载](VIEWER.md#api-端点)（`type=darktable` 转换）中已经享有一等公民的待遇。在 XMP 一侧：darktable 会自己写出 `<image><ext>.xmp` 来保存它的编辑历史，而 Facet 由 exiftool 驱动的附属文件写入器会就地合并进同一个文件 —— `darktable:history`／蒙版节点会被保留，绝不会被覆盖。这里不需要单独的操作指南：上文为 Lightroom 描述的双向附属文件行为（导出／导入、最新者胜、标签求并集）同样适用，而且没有 RAW 命名不一致的问题，因为 darktable 和 Facet 在 `<image><ext>.xmp` 上是一致的。

**注意：darktable 自己的 XMP 重新加载并不可靠。** 与 Facet 的写入路径无关，重新导入一张 darktable 已经编辑过的图像，可能会让 darktable 用一份空白历史覆盖附属文件里的编辑历史，而不是把它加载回来 —— 这是一个仍未解决的上游 bug（[darktable#20537](https://github.com/darktable-org/darktable/issues/20537)，报告于 2026-03-15），“check for new/updated xmp files on start”这个首选项并不能防住它。Facet 不是原因（上文经由 exiftool 的合并已经保留了 `darktable:history`），但风险恰恰落在本页的往返流程所依赖的回读步骤上。实用的规避办法，遵循与上文 Capture One 指南相同的“一次性”纪律：执行 `--export-sidecars` 之后，不要对已经编辑过的文件夹做批量重新导入 —— 只为 Facet 刚刚触及的那些图像重新加载附属文件，确认编辑历史还在，再去信任这一批的其余部分。

## Facet 如何合并

| 字段 | Facet 写入 | Facet 读回 | 冲突规则 |
|---|---|---|---|
| 星级／淘汰 | `xmp:Rating`（`-1` = 已淘汰） | `xmp:Rating` | 最新者胜，对比 `scanned_at` |
| 颜色标签 | `xmp:Label`（`Red` = 已淘汰，`Yellow` = 收藏） | `xmp:Label` | 最新者胜，对比 `scanned_at` |
| 标签／关键字 | `dc:subject`（扁平结构，包含命名人脸的人物姓名） | `dc:subject` | 始终合并（求并集并去重） |
| 层级标签 | `lr:hierarchicalSubject`（`Category\|<cat>`、`People\|<name>`） | 不再导入 | 仅导出 |
| 照片描述 | `dc:description`（+ 经由 exiftool 的 `IPTC:Caption-Abstract`） | 不再导入 | 仅导出 |
| 命名的人脸区域 | MWG `mwg-rs:RegionList`（中心归一化，`Type=Face`） | 不再导入 | 仅导出；由 digiKam 原生读取，Lightroom **不**读取（一个已知的 Adobe 限制 —— Lightroom 只消费它自己写出的 MWG 区域） |

完整的 CLI 参考（`--export-sidecars`、`--import-sidecars`、`--embed-originals`、`--score-to-stars`、`--user`）请见[命令 — 预览与导出](COMMANDS.md#预览与导出)。
