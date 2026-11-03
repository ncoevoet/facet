# 后期软件互操作实用指南

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md) · **简体中文**

分步指南，帮助你把 Facet 的星级、标签和关键字与 Lightroom、Capture One、digiKam 和 darktable 双向流转。`--export-sidecars` / `--import-sidecars` 选项的完整说明和字段对应关系（`xmp:Rating`、`xmp:Label`、`dc:subject`）请见[命令 — 预览与导出](COMMANDS.md#预览与导出)。

除非你要求嵌入，否则原始文件不会被修改：命令行用 `--embed-originals`，查看器中用**写入元数据到文件**。

## 哪些内容会流转

手动位置和审阅决定只有在你于查看器中导出元数据或运行 `--export-sidecars` 时才会流转。

- **GPS** 使用 `exif:GPSLatitude` / `exif:GPSLongitude`。只导出手动设置的位置，因此扫描得到的 GPS 不会取代文件中的 GPS。`--embed-originals` 还会将 EXIF GPS 写入支持的原始文件。清除位置会导出明确的清除标记；导入时缺失字段绝不会清除位置。
- **拍摄日期。** 更正后的日期会导出为 `exif:DateTimeOriginal`（使用 `--embed-originals` 时还会作为 EXIF `DateTimeOriginal` 写入）。点击**使用文件日期**后，下一次导出会将其从 sidecar 中移除，但不会触碰其他编辑器写入的日期。
- **保留与淘汰。** 保留独立于星级和收藏。淘汰会清除保留、星级和收藏。

Facet 自己的 XMP 命名空间 `https://github.com/ncoevoet/facet/ns/1.0/` 增加了：

| 标签 | 取值 | 用途 |
|---|---|---|
| `facet:ReviewDecision` | `kept`、`rejected`、`undecided` | Facet 的审阅决定 |
| `facet:GPSState` | `set`、`cleared` | 位置是由 Facet 设置还是清除 |
| `facet:DateState` | `set` | sidecar 中的拍摄日期来自 Facet |
| `facet:KeywordState` | JSON（`version` 为 1；`owned`、`deleted`、`ai`、`manual` 列表） | Facet 写入了哪些关键字 |
| `facet:RegionOwner` | `Facet` | Facet 写入的 MWG 人脸区域 |

`facet:KeywordState` 让 `--reconcile-keywords` 只移除 Facet 拥有的名称，并避免导入时旧的 AI 标签变成手动标签。`facet:RegionOwner` 让 ExifTool 只替换 Facet 的人脸区域。

`--import-sidecars` 如何应用 Facet 的决定：

- 当标准审阅字段与决定一致或缺失时，应用该决定。
- 如果标准淘汰状态与之不一致，说明其他编辑器更改了标准字段。Facet 忽略自己的私人决定，改用标准字段的“较新者优先”扫描时间检查。
- 与标准审阅字段一同导出的决定同样采用“较新者优先”检查，因此较旧的导出无法撤销较新的决定。例外是尚无审阅状态的照片（无星级、收藏、保留或淘汰）：重新扫描的照片库仍能恢复其决定。
- 只包含决定的导入仍须明确执行（由你请求），应用时不做扫描时间检查。

其他规则：

- Facet 中已有的手动 GPS 默认保留，除非加上 `--overwrite-manual-gps`。无效或不完整的坐标会被忽略。
- `--user alice` 将导入和导出限定在该用户可见的目录和私人决定内。GPS 仍为共享数据。不带 `--user` 时，CLI 使用全局状态。
- 全局导入（不带 `--user`），包括 `--dry-run` 预览，无需查看器的登录密钥。
- 使用 ExifTool 时，导出会合并进现有 sidecar。没有它时，导出会保留现有的编辑器 sidecar，并写入回退文件。
- ExifTool 导出需要 Facet 随附的标签定义。如果缺失，导出会在修改任何内容之前停止；请重新安装 Facet。

## RAW 附属文件命名陷阱

Facet 在 `IMG_1234.CR2` 旁导出 `IMG_1234.CR2.xmp`（darktable 的完整文件名约定）。Lightroom Classic 和 Capture One 通常为专有 RAW 使用 `IMG_1234.xmp`。导出文件名永远不会改变。

对于 JPEG/HEIC/TIFF/PNG/DNG，`--embed-originals` 改为写入文件内部。GIF/WebP/BMP/AVIF/JPEG XL 和专有 RAW 仍需要命名匹配的附属文件。

导入时，用 `--import-sidecars --sidecar-naming full|basename|auto` 选择命名方式：

- `full`（默认）：读取 `<image.ext>.xmp` 或 `<image.ext>.facet.xmp` 中最后修改的一个；时间相同时优先使用前者。
- `basename`：读取 `<image>.xmp`（只去掉最后一个扩展名）。忽略完整名称的附属文件。
- `auto`：接受存在的任一种。若两种同时存在，则该照片因歧义被跳过；请改选 `full` 或 `basename`。

在 `basename` 和 `auto` 下，若多张图像共享同一基本名（例如 `same.CR3` 和 `same.jpg`），即使范围内只有其中一张，也会被拒绝。请为它们使用完整名称的附属文件。`same_v1.jpg` 的基本名不同，没有问题。

- 双扩展名文件（如 `IMG.CR2.jpg`）绝不会读取属于 `IMG.CR2` 的 `IMG.CR2.xmp`。其他图像的 `.facet.xmp` 回退文件也同样如此。
- 命名不匹配、歧义和不可读的附属文件都会报告。解析失败后，Facet 不会尝试另一种命名。
- 汇总会统计所有受影响的照片，包括因所选命名而被忽略的附属文件。提示每类只显示一个示例。
- 不会重命名任何文件。

导入不需要 ExifTool。导出合并、嵌入和 MWG 人脸矩形需要 ExifTool。没有它时，Facet 保留现有的编辑器附属文件，并写入不含人脸矩形的 `<image.ext>.facet.xmp`。其他编辑器不会查找这个名称，因此需要你明确交接。

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars`（加上路径可限定范围，例如 `--export-sidecars /photos/2026-wedding`）。加上 `--embed-originals` 还会直接写入 JPEG/HEIC/TIFF/PNG/DNG 文件。
2. 在 Lightroom Classic 的图库模块中选中照片（Ctrl/Cmd+A 全选），然后选择**元数据 → 从文件中读取元数据**。Lightroom 会用附属文件（或内嵌元数据）中的内容替换其星级、颜色标签和关键字。

Facet 的淘汰标记（`xmp:Rating = -1`）会被读回为 Lightroom 的排除（Reject）旗标。Facet 的收藏会写出 `xmp:Label = Yellow`，Lightroom 把它显示为**黄色的颜色标签**，而不是留用（Pick）旗标。要得到留用旗标，请使用下面的增效工具，或按黄色标签筛选。

`python facet.py --export-manifest` 会写出不含 XMP 的 Facet 数据：路径、类别、全部评分、标签，以及与 `--export-sidecars` 相同的星级列。按用户区分的星级请使用 `--export-manifest --user alice`。见[命令 — 预览与导出](COMMANDS.md#预览与导出)。下面的 Facet 增效工具读取的就是它。

**清单版本 2** 增加了 `burst_group_id`、`sequence_kind`、`sequence_group_id`、`score_stars`，以及一个顶层的 `pending_corrections` 计数。该计数是尚未应用的曝光包围／全景手动修正数量；重新运行 `--detect-panoramas` 即可应用。增效工具会在预览中将其显示为警告。版本 2 的增效工具会拒绝版本 1 的清单（反之亦然）；如果看到那个对话框，重新运行 `--export-manifest` 即可。

在查看器中，图库的 **Export to editor**（导出到编辑器）对话框提供 **Download Lightroom manifest**（下载 Lightroom 清单）按钮，作用于同一份选择或筛选条件，见[导出到编辑器](VIEWER.md#导出到后期软件)。它生成的 `facet_manifest.json` 与 `--export-manifest` 完全相同。

### Facet 增效工具（星级、留用旗标、元数据字段与关键字）

Facet 仓库里的 `facet.lrplugin/` 是一个 Lightroom Classic 增效工具。它把 Facet 的星级和收藏／淘汰状态**直接写进目录**。这解决了 XMP 无法解决的两件事：Lightroom 永远找不到专有 RAW 对应的 Facet 附属文件，而 XMP 也无法承载 Lightroom 的留用旗标。

该增效工具读取一个清单文件。它从不与 Facet 服务器通信，不需要密码，Facet 停止运行时也能工作。它按路径匹配照片，因此**纯 RAW 照片库的表现与 JPEG 照片库一样**。

它在**图库 → 增效工具附加功能**下增加了两个菜单项：

- **Facet: Apply ratings and flags...** —— 清单 → 目录（本节介绍）。
- **Facet: Export Lightroom State to Facet...** —— 目录 → Facet，见 [Lightroom → Facet](#lightroom--facet)。

**安装**（只需一次）：

1. 把 `facet.lrplugin` 文件夹复制到运行 Lightroom 的机器上。在 macOS 上请先压缩成 zip：访达会把 `.lrplugin` 文件夹当作程序包。
2. 在 Lightroom Classic 中：**文件 → 增效工具管理器 → 添加**，选择 `facet.lrplugin` 文件夹，然后点击**完成**。

**使用：**

1. `python facet.py --export-manifest /photos/2026-wedding`（路径用于限定导出范围；文件始终以 `facet_manifest.json` 的名字落在当前目录）。如有需要，把它复制到 Lightroom 所在的机器。
2. 在图库模块中选中照片，然后选择**图库 → 增效工具附加功能 → Facet: Apply ratings and flags...**
3. 在对话框中指向 `facet_manifest.json`。该路径会被记住。
4. **如果 Facet 是在另一台机器上扫描的，请填写两个路径前缀。** 清单里保存的是执行扫描那台机器的路径（例如 NAS 上的 `/volume1/photos/...`），而 Lightroom 记录的是桌面电脑的路径（例如 `Z:\photos\...`）。请为同一个文件夹输入 Lightroom 前缀和 Facet 前缀。路径一致时两者都留空。填错的话，一张照片都匹配不上。
5. 选择范围：选中的照片（默认），或当前整个文件夹。
6. 点击 **Preview...**（预览）。**此时还什么都没有写入。** 它会显示匹配了多少张照片、有多少张没匹配上，以及会设置什么。如果一张都没匹配上，它会把一个 Lightroom 路径样例和一个清单路径样例并排显示，方便你修正前缀。
7. 点击 **Apply**（应用）。进度中可以取消。汇总会说明哪些被设置、哪些被跳过、哪些没有找到。

**它写入什么**（从不写入你的图像文件）：

| Facet 状态 | Lightroom 字段 |
|---|---|
| `star_rating` 1-5 | 星级 |
| 收藏 | 留用（Pick）旗标 |
| 已淘汰 | 排除（Reject）旗标 |

Facet 的星级为 0 表示“没有意见”，永远不会被写出。

**覆盖规则。** 默认情况下，增效工具只给在 Lightroom 中*没有星级*的照片设置星级，只给*没有旗标*的照片设置旗标。你自己评的星级和打的旗标会保留，并计为“kept as they are”（保持原样）。勾选 **Overwrite ratings and flags that are already set in Lightroom** 才会替换它们。附属文件导出遵循同样的规则（`xmp_export.score_to_rating.only_when_unrated`，默认 `true`）。

**对话框选项**（默认全部关闭，各自会记住到下次）：

- **Fill in star ratings from Facet scores for photos you have not rated** —— 如果清单里没有 `star_rating`（或为 0），则把 `aggregate` 分数映射为星级。这个兜底**永远不会覆盖 Lightroom 里已有的星级，即便勾选了 Overwrite 也不会。**
- **Pick the recommended frame of each burst** —— 在每个至少有 2 个成员的连拍组中，把每个标记为 `is_burst_lead` 的成员设为留用（一组连拍可以保留不止一张）。孤立帧和没有首选帧的组会被跳过。你自己的留用／淘汰旗标和 Facet 的收藏／淘汰永远优先。
- **Reject the other frames**（仅与留用选项一起使用）—— 把每个非首选帧的连拍成员设为淘汰。曝光包围、全景或 HDR 全景的成员永远不会被淘汰，没有首选帧的组也不会有任何淘汰。
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** —— 对范围内至少匹配到 2 张照片的每个组，在 `Facet › Bursts`、`Facet › Brackets`、`Facet › Panoramas` 或 `Facet › HDR panoramas` 之下创建或复用一个收藏集。
  - 名称：`<yyyy-mm-dd HH:MM:SS> – <filename>`，取最早成员的信息；若它没有拍摄时间，则为 `~ (no date) – <filename>`。
  - 如果一个连拍组的成员全部属于同一个曝光包围或全景集合，就不会再单独建 Bursts 收藏集。
  - **重新运行只会新增照片。** 之后离开某个集合的照片仍留在它的收藏集中。
  - 已知局限：两个组的最早成员若拍摄时间精确到秒相同且文件名相同（例如两台相机都写出 `IMG_0001`），会共用一个收藏集。
  - **Rebuild (clear and refill) Facet collections fully covered by this run**（仅与上一个选项一起使用）—— 清空并重新填充收藏集，但仅当该收藏集及其整个组都在当前范围内时才会这样做。只被部分覆盖的收藏集和智能收藏集会被跳过。
    - 它还会清空并删除本次运行中已解散的组所对应的收藏集，但仅当其中的每张照片都是本次运行匹配到的。
    - 它只触及名称符合 Facet 自身格式的收藏集（日期时间或 `~ (no date)`，后接 ` – <filename>`）。你自己命名的收藏集永远不会被触及。
    - 有内容可删除时，预览会显示一行 `Facet collections to delete: N`。汇总会报告重建、删除、跳过和失败的收藏集数量。
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** —— 把 aggregate 分数（例如 `8.4`）、整数档位（`0`-`10`）、类别和集合类型写入 Facet 自己的元数据字段。它们会显示在“元数据”面板中，并可作为文本（`sdktext:`）条件用于图库筛选器和智能收藏集，例如档位“任意为 8、9、10”。不再适用的字段会被清空。另有两个隐藏的记账字段（本次运行推算出的星级和留用值）也会被写入；它们不参与搜索，但在某些 Lightroom Classic 版本中仍可能可见（未经验证）。
- **Create "Facet" keywords from Facet tags (never included on export)** —— 创建一个 `Facet` 根关键字，为每个标签（AI 标签和[手动标签](#手动标签与-xmp-关键字)）建一个子关键字。每张照片的 `Facet ›` 子关键字会与其标签保持一致，因此在 Facet 中移除的标签会在下一次 Apply 时消失。它们全部关闭了 `Include on Export`，所以绝不会泄露到导出或客户画廊中。你在 `Facet` 根之外的关键字不会被更改。已有的顶层 `Facet` 关键字会被采用为根，你自己在其下添加的任何子关键字都会被移除。

**为什么是收藏集，不是堆叠。** Lightroom 的 SDK 无法创建堆叠。要堆叠某个收藏集里的照片，请选中它们，使用**照片 → 堆叠 → 编为堆叠**（Ctrl/Cmd+G）。

**局限：**

- **留用旗标只存在于目录中。** Lightroom 从不把它们写进 XMP，因此没有其他应用能看到，从文件重建目录时也会丢失。星级可以通过**元数据 → 将元数据存储到文件**保留下来。
- **Facet 字段上没有数值型智能收藏集。** 增效工具字段只支持文本（`sdktext:`）；数值运算符（`>`、`<`、“在范围内”）只适用于 Lightroom 内置字段。请使用档位字段，或星级兜底选项 —— Lightroom 会按数值对星级排序和筛选。
- **撤销**每按一次 Ctrl/Cmd+Z 只撤销一批 200 张照片。
- 勾选 **Write facet-apply.log next to the manifest** 可记录哪些路径匹配上了、写入了什么。

### Lightroom → Facet

**星级、留用与淘汰 —— Lightroom 说了算（通过增效工具）。**

1. **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** 会打开一个保存面板。文件中每张照片一条记录：`path`，以及需要传递时才出现的 `rating`／`pick`。
2. 用 `python facet.py --import-lightroom facet_lightroom_state.json` 导入（多用户安装上必须加 `--user alice`），或使用图库 **Export to editor** 对话框里的 **Import Lightroom state…**。

对于记录中的每个字段，Lightroom 的值都胜出。导入会报告 `matched`／`unmatched`／`changed` 计数。

| Lightroom 状态 | Facet 结果 |
|---|---|
| 留用旗标 = 已选中（`pick = 1`） | 收藏 = 开，淘汰 = 关 |
| 留用旗标 = 已淘汰（`pick = -1`） | 收藏 = 关，淘汰 = 开 |
| 留用旗标 = 无（`pick = 0`） | 收藏 = 关，淘汰 = 关 |
| 星级（`rating`，0-5） | `star_rating`（`0` 会清空它） |

- 省略了 `rating` 或 `pick` 的记录会让 Facet 对应的值保持不变。只有当 Lightroom 的值与上一次 Apply 设置的值不同时，导出才会包含该字段，因此未被触碰的照片不会有任何变化。
- 虚拟副本会在导出前合并到其母版。
- 一次改变了任何内容的成功导入，会像其他任何星级更改一样，刷新训练对并触发自动再训练。

> **警告：** 因为 Lightroom 说了算，一张从未被 Apply 步骤触碰过、且在 Lightroom 中未评级未标记的照片（`pick = 0`，没有 `rating`），在导入时会清除它在 Facet 中的星级、收藏和淘汰状态。

**通过 XMP 的星级、标签和关键字**（单向）：

1. 在 Lightroom 中选中照片，选择**元数据 → 将元数据存储到文件**（Ctrl/Cmd+S）。这会把星级、标签和关键字写入 XMP 附属文件（RAW），或直接写入文件本身（DNG/JPEG/PSD/TIFF）。
2. `python facet.py --import-sidecars /path --sidecar-naming basename` 读取 RAW 附属文件。共享基本名的 RAW/JPEG 会被拒绝。此命令不读取内嵌元数据。导入的关键字会成为手动标签。

### 冲突规则

- **标签和关键字默认合并。** 导出会添加 Facet 关键字；`--reconcile-keywords` 还会移除过时的、属于 Facet 的名称。导入会添加手动标签，不会替换 AI 标签。见[手动标签与 XMP 关键字](#手动标签与-xmp-关键字)。
- **多用户**（`--export-sidecars --user alice` / `--import-sidecars --user alice`）：星级写入 Alice 自己的评分（`user_preferences`），而不是全局评分。关键字始终是全局的：手动标签由所有用户共享。
- 导入的关键字存放在 `photo_manual_tags` 中，标签筛选直接读取该表，因此 `--import-sidecars` 之后无需运行 `python database.py --migrate-tags`。

## Capture One

Capture One 把设置保存在 `.cos` 文件（Sessions）或它的目录中。它的 **Sync Metadata** “Full Sync”模式可能覆盖后写入的那一方，所以双向循环可能丢失修改。请使用**单向，Facet → Capture One**：

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`。
2. 在 Capture One 中，把 **Preferences → General → Sync Metadata** 保持为默认值（不要选“Full Sync”）。
3. 选中图像，右键点击，选择 **Load Metadata**，一次性拉入星级、标签和关键字。

之后在 Capture One 中继续工作，不启用自动同步。要把保存的 XMP 带回 Facet，对于去掉扩展名的 RAW 附属文件运行 `--import-sidecars /path/to/shoot --sidecar-naming basename`，完整文件名则用 `full`。共享基本名的 RAW/JPEG 会被拒绝。此命令读取附属文件，不读取内嵌元数据。

## digiKam

digiKam 的[附属文件设置](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings)只使用一种命名：默认为 `filename.ext.xmp`，启用 **Sidecar file names are compatible with commercial programs** 后为 `filename.xmp`。它不会两种都尝试。

- **Facet → digiKam：** 使用完整名称设置，启用 **Read from sidecar files**，从文件重新读取元数据，并核对各字段。
- **digiKam → Facet：** 按你的 digiKam 设置传入 `--sidecar-naming full` 或 `basename`。

星级、颜色标签和选片标记在各个应用中含义略有不同，请核对结果。

### Batch Queue Manager 挂钩

你可以在 digiKam 批处理队列管理器（BQM）的 **Custom Script** 工具中运行 Facet 导入。先启用附属文件写入，保存命名设置，并应用待处理的元数据更改（digiKam 可能延迟写入）。下面示例假设使用完整名称的附属文件；只有照片集合中不存在共享基本名时，才改用 `basename`：

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` 是 digiKam 的按文件占位符。BQM 期望有一个输出文件，因此需要 `cp`。`--import-sidecars` 会扫描整个文件夹，所以对每张照片都执行一次是多余的，但无害。大批量任务时，等队列跑完后手动执行一次 `python facet.py --import-sidecars /path/to/folder` 即可。

## darktable

见[配置 — 查看器](CONFIGURATION.md#查看器)（`viewer.raw_processor.darktable` 导出配置文件和样式）和[查看器 — 下载](VIEWER.md#下载)（`type=darktable` 转换）。

darktable 把编辑历史保存在自己的 `<image><ext>.xmp` 中。Facet 的 ExifTool 写入器会合并进该文件，并保留 `darktable:history` 和蒙版节点。上文 Lightroom 的附属文件行为（导出／导入、较新者优先、标签求并集）原样适用，而且没有 RAW 命名不一致的问题：两者都使用 `<image><ext>.xmp`。

**ExifTool 版本：**

- 建议使用 **13.28 或更高版本**。
- 人脸变更需要 **12.65 或更高版本**。较旧或未知的版本会警告并跳过人脸变更，仍导出其余内容。
- **13.23 至 13.27** 会损坏带有 darktable 历史的 sidecar，因此 Facet 拒绝使用它们写入，并要求你升级。Docker 镜像内置了安全的版本。发行版软件包则可能不是（Debian trixie 的 `libimage-exiftool-perl` 为 13.25）。

> **警告：** darktable 自己在重新导入已编辑过的图像时，可能会清掉编辑历史：它可能用一份空白历史覆盖 sidecar 里的历史。这是一个仍未解决的上游 bug（[darktable#20537](https://github.com/darktable-org/darktable/issues/20537)，报告于 2026-03-15），“check for new/updated xmp files on start”这个首选项并不能防住它。执行 `--export-sidecars` 之后，不要对已编辑的文件夹做批量重新导入。只重新加载 Facet 刚刚触及的图像，并先检查它们的历史。

## 手动标签与 XMP 关键字

Facet 把你自己输入的标签（参见[查看器 — 手动标签](VIEWER.md#手动标签)）保存在 `photo_manual_tags` 中，与 `photos.tags` 里的 AI 标签分开。重新扫描或重新打标不会动到它们。

- **导出。** 每个写关键字的环节都按先 AI 标签、再手动标签、最后人物姓名的顺序输出，并且不区分大小写地去重。这涵盖 `--export-sidecars`、图库的 XMP 导出和“将元数据写入文件”操作，以及 Lightroom 清单（`--export-manifest`、`/api/lightroom/manifest`）。
- **导入。** `--import-sidecars` 从 `dc:subject` 读取扁平关键字，并从 `lr:hierarchicalSubject` 单独读取层级路径。每个扁平关键字都会像手动输入的标签一样被规范化：去除首尾空白、转小写、最多 64 个字符、每张照片最多 50 个手动标签。每个关键字都会成为来源为 `xmp` 的手动标签，除非它：
  - 已经是照片的某个 AI 标签或人物姓名，
  - 与 `lr:hierarchicalSubject` 中明确存在的路径重复，
  - 含逗号或控制字符，或
  - 会超出上限。
- **删除必须明确选择。** 默认导出只添加。`--export-sidecars /path --reconcile-keywords`（需要 ExifTool）还会移除 Facet 之前写入、而现在已不在 Facet 中的名称。Facet 从未写入的关键字绝不会被移除，即使名称相同；没有标记的旧 sidecar 不授予 Facet 任何归属。如果你在其他编辑器中重新添加了被移除的关键字，Facet 可以再次导入它，此后将其视为外部名称。使用 `--user` 时关键字仍是共享的。
- **导出以 Facet 的关键字为准。** 仍在 Facet 中的关键字会被写回，即使其他编辑器已将其从文件中移除。要彻底移除，请在 Facet 中移除该标签。协调操作绝不会删除 Facet 中的标签。
- `2024`、`1.50`、`1e3`、`true`、`false` 和 `null` 等名称保留原有拼写。
- 如果 Facet 无法读取现有文件的元数据，导出会在写入前停止。
- **Lightroom 清单则会传播移除。** 增效工具的关键字选项会在每次 Apply 时改写每张照片的 `Facet ›` 子关键字。
- **AI 标签仍是 AI 标签。** Sidecar 会记录哪些关键字来自 AI、哪些是手动的，因此重新打标不会把旧的 AI 关键字变成手动标签。旧版 Facet 的 sidecar 保持原来的只添加行为。
- **层级。** 导入的路径会添加到共享关键字层级；仅在扁平名称中包含 `|` 或 `/` 不会创建层级。标记为 Facet 生成的路径不会导入为手动分配，除非也标记为手动。导出包含明确分配的路径及自动生成的类别／人物路径。导出默认只添加；`--reconcile-keywords` 仅移除属于 Facet 的过时路径，并保留外部路径。
- **归属上限：** 每份列表最多 10,000 个名称，每个名称最多 1,024 个字符。会超出上限的导出会在写入前停止。请手动归档并清理这样的 sidecar，再重新开始。
- **旧版 Facet 导入的关键字留在原处。** 旧版本把关键字合并进 `photos.tags`，在那里它们看起来像 AI 标签，也没有任何迁移会移动它们。要把其中一个变成手动标签，请先清空或重新打标 `photos.tags`，再重新运行 `--import-sidecars`；或者直接手动添加该标签。
- **移动或重命名的文件。** 手动标签与目录中的路径关联。自行移动文件后，请使用需要先审核的[重新关联流程](RELINK.md)更新路径并保留标签；仅扫描新位置不会转移这些标签。
- **`--export-csv` 和 `--export-json` 仍然只含 AI 数据。** 它们的 `tags` 值不含手动标签。

## Facet 如何合并

| 字段 | Facet 写入 | Facet 读回 | 冲突规则 |
|---|---|---|---|
| 星级／淘汰 | `xmp:Rating`（`-1` = 已淘汰） | `xmp:Rating` | 审核字段编辑时间；旧数据使用扫描时间 |
| 颜色标签 | `xmp:Label`（`Red` = 已淘汰，`Yellow` = 收藏） | `xmp:Label` | 审核字段编辑时间；旧数据使用扫描时间 |
| 标签／关键字 | `dc:subject`（扁平，AI 标签 + 手动标签，包含已命名人脸的人物姓名） | `dc:subject`（存为手动标签） | 默认只添加；`--reconcile-keywords` 仅移除属于 Facet 的过时名称；导入仍只添加 ([手动标签与 XMP 关键字](#手动标签与-xmp-关键字)) |
| 层级标签 | `lr:hierarchicalSubject`（明确分配及生成的类别／人物路径） | `lr:hierarchicalSubject`（共享层级分配） | 导入只添加；导出协调仅移除属于 Facet 的过时路径 |
| 照片描述 | `dc:description` 默认语言（+ 经由 exiftool 的 `IPTC:Caption-Abstract`） | 不再导入 | 仅导出 |
| 命名的人脸区域 | MWG `mwg-rs:RegionList` + `facet:RegionOwner=Facet`（中心归一化，`Type=Face`） | 不再导入 | 仅导出；由 digiKam 原生读取，Lightroom **不**读取（一个已知的 Adobe 限制 —— Lightroom 只消费它自己写出的 MWG 区域） |

完整的 CLI 参考（`--export-sidecars`、`--import-sidecars`、`--embed-originals`、`--score-to-stars`、`--user`）请见[命令 — 预览与导出](COMMANDS.md#预览与导出)。

**GPS 清除。** 如果 sidecar 同时含有标准 GPS 字段和旧的 `facet:GPSState=cleared`，以完整且有效的经纬度为准。不完整或无效的坐标会被忽略，绝不会清除位置。只有坐标缺失或为空且带有清除标记时才会清除 GPS。手动 GPS 仍受保护，除非你要求覆盖。

**说明（Caption）。** 使用 ExifTool 时，导出只更新 `dc:description` 的默认（`x-default`）语言，并保留其他语言。Facet 的说明为空时，现有说明保持不变。没有 ExifTool 时，Facet 写入默认语言的说明；若已有编辑器 sidecar，则改写到 `<image>.facet.xmp`。

**人脸区域。** 使用 ExifTool 时，导出只替换带 `facet:RegionOwner=Facet` 标记的 MWG 矩形。

- 未标记的区域（包括旧版 Facet 导出的）会保留。升级后，旧的未标记人脸可能与新的带标记副本同时出现，清除人脸时也会留下旧副本。
- 重复导出会替换带标记的副本，不会累积。
- 如果图像尺寸与现有区域绘制时的尺寸不同（或未知），会警告并跳过人脸变更。星级、标签、关键字和 GPS 仍会导出。
- 无法读取或无效的人脸元数据会在写入前拒绝单张照片的导出或嵌入。
- 回退写入器（没有 ExifTool）不导出人脸矩形。
- 带标记的区域即使在别处被编辑，仍归 Facet 管理。如要保留为你自己的区域，请移除其归属标记。

> **警告：** 写入多个独立文件不是原子操作。导出期间的 I/O 故障或外部修改，可能导致部分文件已更新而其他文件未更新。

如果 ExifTool 版本检查失败，Facet 会在下一次重试。版本未知期间，会跳过人脸区域，其余内容照常导出。已知有缺陷的版本始终会被拒绝。

## 附属文件导入预览与冲突

运行 `--import-sidecars /path --dry-run` 可在写入前查看 JSON 计划：所选附属文件、前后字段值、要添加的关键字、来源时间以及跳过／冲突原因。预览以只读方式打开数据库，绝不更改它。正式应用会重新读取一切，因此预览不是可重放的令牌。

如果数据库不存在、无法读取或无效，预览会以退出码 1 结束，且不会创建或修复数据库。`--dry-run-count` 仅限制扫描样本数，不限制导入预览。

`--sidecar-fields review,gps,keywords` 选择要导入的字段组；省略某个组即跳过它。

- **review** 将星级、收藏、淘汰和保留作为整体导入，因此冲突不会只应用半个决定。
- **gps** 保护手动位置，除非给出 `--overwrite-manual-gps`。
- **keywords** 只添加且共享，使用 `--user` 时也是如此。

**编辑时间。** Facet 按照片和账户记录每个审阅字段上次更改的时间，包括重置。比该更改更旧的 sidecar 属于 `newer_local_edit` 冲突，该审阅组保持不变。`--overwrite-sidecar-review` 会覆盖此检查和扫描时间检查。`local` 来源表示未知的写入者，不一定是人。说明、人脸和无标记的外部 GPS 绝不会被导入。

- Facet 开始记录编辑之前更改的字段没有已知的编辑时间。此时适用扫描时间规则，报告为 `untracked_legacy_edit`。
- 预览也能打开较旧的数据库而不升级它；缺少保留字段时视为未决定。
- sidecar 的时间取 `xmp:MetadataDate`，缺失或无效时取文件修改时间。
- 详情最多列出范围内的前 1,000 张照片和每张照片 100 条备注，并给出被省略部分的计数。

编辑时间保存在各自的数据库中。新导出的查看器数据库不会复制扫描端的编辑时间或 sidecar 路径。增量导出会保留查看器自己的编辑时间，因此在查看器中所做的重置（包括删除的用户评分）会保留。查看器从未编辑过的扫描端值继续更新。

> **警告：** 由 1.24.0 之前未发布的构建创建的查看器数据库，可能含有复制来的扫描端编辑时间。它们现在按查看器编辑计算，因此这些字段不再跟随扫描端更新。重建前请备份并检查该数据库：完整重建会丢弃查看器本地的修改。
