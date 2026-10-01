# 快速入门

> 🌐 [English](../GETTING_STARTED.md) · [Français](../fr/GETTING_STARTED.md) · [Deutsch](../de/GETTING_STARTED.md) · [Italiano](../it/GETTING_STARTED.md) · [Español](../es/GETTING_STARTED.md) · [Português](../pt/GETTING_STARTED.md) · **简体中文**

这是一份面向首次使用的流程指引，针对最常见的场景：你刚拍完或刚导入一批照片，希望最终得到一组精选照片。
流程共六步——导入、归并相似照片、让 Facet 了解你的品味、淘汰、打标签、导出——每一步都链接到对应的详细页面，
而不在此重复说明。

![Facet 图库操作演示](../screenshots/walkthrough.gif)

## 开始之前

### 1. 设置编辑密码

全新安装默认为**只读**。你可以浏览（若设置了 `viewer.password`，则需先通过其验证），
但所有编辑操作——评分、选片、人脸、相册、标签以及“扫描”按钮——都会被拒绝，
直到你在 `scoring_config.json` 中设置 `viewer.edition_password` 并重启查看器（配置不会热重载）。

使用随附的 `docker-compose.yml` 时无需自己想密码：镜像会在首次启动时生成一个密码并只打印一次。
可用以下命令读取：

```bash
docker compose logs facet
```

然后在图库中以编辑者身份登录。详情见：
[单用户模式](VIEWER.md#单用户模式默认)和[可修改的 Docker 设置](INSTALLATION.md#可修改的-docker-设置)。

![编辑者登录](../screenshots/getting-started-edition-login.jpg)

### 2. 选择安装方式

Docker 是 Windows、macOS 和 Linux 上最快捷的途径；原生安装则适合不想使用容器的用户。
[我该选哪种安装方式？](INSTALLATION.md#我该选哪种安装方式)中有对比表。

使用容器时有两点容易出错：

- **配置与文件归属。** 容器以 uid 1000 运行，
  而无根 Podman 会将其映射到宿主机的某个 subuid，
  因此它在 `./facet-config` 中创建的文件可能不属于你的用户。
  参见[容器内的文件归属](INSTALLATION.md#容器内的文件归属)。
- **路径是容器内的路径，而非宿主机路径。** 你扫描的是 `/data/photos`，
  而不是 `~/Pictures`。参见[容器路径语义](DEPLOYMENT.md#容器路径语义)。

### 3. 没有 GPU？没问题

一切功能——评分、人脸、标签、选片、“扫描”按钮——都能在仅有处理器的 CPU `legacy` 配置档下运行，
只是速度较慢。
请阅读[没有显卡](INSTALLATION.md#没有显卡)和[哪种配置档适合我的硬件？](INSTALLATION.md#哪种配置档适合我的硬件)。
“扫描”按钮的出现从不以拥有显卡为条件。

### 4. 留意内存

在较大的配置档下，设置了内存上限的容器可能在扫描途中被终止。
设置上限之前请先查看[容器内存限制](DEPLOYMENT.md#容器内存限制)；
在 Mac 上请参见 [Mac 上的内存](INSTALLATION.md#mac-上的内存)。

## 工作流程

### 第 1 步：导入图像

把照片放进 Facet 所指向的文件夹（JPEG、HEIF/HEIC、PNG 以及常见 RAW 格式——参见[支持的文件类型](README.md#支持的文件类型)），
然后扫描。你可以在终端中完成（[扫描](COMMANDS.md#扫描)），也可以在浏览器中完成：

- 将 `viewer.features.show_scan_button` 设为 `true`（默认关闭）。
- 单用户：需要编辑密码，**并且**已以编辑者身份登录。多用户：需要超级管理员角色。
- 将文件夹添加到 `viewer.scan_directories`，以便启动器有可选的目录。

此后，图库网格上方在任何屏幕宽度下都会出现一个**扫描新照片**按钮，而不仅仅是在空图库中。完整规则：
[触发扫描](VIEWER.md#触发扫描)。
首次扫描会一次性下载 AI 模型（[首次运行会遇到什么](INSTALLATION.md#首次运行会遇到什么)）。

![图库网格上方的扫描按钮](../screenshots/getting-started-scan-button.jpg)

### 第 2 步：找出重复、连拍和相似照片

Facet 会自动归并连拍帧、近似重复照片、包围曝光和全景照片，而图库**默认会隐藏一组照片中的大部分**，
让你只看到一张代表图。如果照片数量比预期少，那是隐藏开关的作用，
而不是文件丢失——参见[显示选项](VIEWER.md#显示选项)和[默认筛选条件](VIEWER.md#默认筛选条件)。
若要并排查看整组照片，请打开[相似照片](VIEWER.md#相似照片)或[选片](VIEWER.md#选片)暗房；
必须保持完整的照片组见[全景照片与包围曝光](VIEWER.md#全景照片与包围曝光)。

![连拍选片](../screenshots/burst-culling.jpg)

### 第 3 步：告诉 Facet 你更喜欢哪一张

你在选片时做出的每一次挑选，以及比较模式下的每一次 A/B 选择，都是一个信号。Facet 会据此学习个人排名，
并以**我的偏好**（[我的偏好](VIEWER.md#我的偏好)）的形式呈现。
你可以在[两两比较模式](VIEWER.md#两两比较模式)中选择“这张胜过那张”，
或者直接选片——[选片](VIEWER.md#选片)界面会记录你的保留与淘汰。累积足够多的新选择后，
排序器会自动重新训练，且仅在你暂停操作之后才开始（[自动重训练](CONFIGURATION.md#自动重训练)）。

![比较两张照片](../screenshots/getting-started-teach.jpg)

### 第 4 步：淘汰不想要的照片

在选片时淘汰照片，或选中一组照片后对其执行操作（[多选与批量操作](VIEWER.md#多选与批量操作)）：
[保留前 N%](VIEWER.md#保留前-n)、[选片后导出／清理](VIEWER.md#选片后导出清理)或[删除](VIEWER.md#删除)。
“选片后导出／清理”在你应用之前只做试运行预览。“删除”会立即将文件送入系统回收站，
且仅在 `viewer.cull.allow_trash` 开启时可用（默认为 `false`）。
[撤销](VIEWER.md#撤销)涵盖批量标记变更和选片确认，不包括这些文件操作。
选片可写入的文件夹是一份允许列表：
你的扫描目录加上 `viewer.export.allowed_target_dirs`，
因此照片目录树下的子文件夹无需任何设置即可使用，而目录树之外的文件夹则会被拒绝，直到你将其添加进来。
参见[导出与选片目标位置](CONFIGURATION.md#导出与选片目标位置)。若要无界面选片：
[在终端中对一次拍摄选片](COMMANDS.md#在终端中对一次拍摄选片)。

你在 Facet 之外删除的照片，其数据库行会一直保留，
直到你运行[数据库维护](COMMANDS.md#数据库维护)中的清理。

![对选中照片执行批量操作](../screenshots/getting-started-discard.jpg)

### 第 5 步：为入选照片添加标签和元数据

Facet 会自动为照片打标签，你也可以添加**自己的标签**：单张照片在照片详情视图中添加，
一组选中照片则通过批量操作添加。手动标签在重新扫描后仍会保留，标签筛选和搜索都能找到它们，并且在分享链接中会被隐藏。
来自外部 XMP 边车文件的关键字会作为手动标签导入；在 Facet 中移除标签，
不会将其从 Facet 已写入的边车文件中移除。
参见[手动标签](VIEWER.md#手动标签)和[手动标签与 XMP 关键字](INTEROP.md#手动标签与-xmp-关键字)。
若要把评分和关键字带入 Lightroom、Capture One、digiKam 或 darktable，
请参见[互操作](INTEROP.md)（嵌入需要 [exiftool](INSTALLATION.md#exiftool)）。

![照片详情视图中的手动标签](../screenshots/getting-started-manual-tags.jpg)

### 第 6 步：导出精选照片

将入选照片放入相册并从那里导出，或使用[导出到后期软件](VIEWER.md#导出到后期软件)交给编辑器处理，
或用[选片后导出／清理](VIEWER.md#选片后导出清理)把入选照片复制到文件夹。
适用与第 4 步相同的目标位置允许列表（[导出与选片目标位置](CONFIGURATION.md#导出与选片目标位置)）。

![导出到编辑器](../screenshots/getting-started-export.jpg)

## 下一步

[查看器](VIEWER.md)介绍图库的全部功能，[命令](COMMANDS.md)介绍终端用法，
[评分](SCORING.md)用于调整什么算好照片，
[部署](DEPLOYMENT.md)适用于 NAS 或共享服务器。
