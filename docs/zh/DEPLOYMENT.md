# 部署指南

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md) · **简体中文**

在远程服务器或 NAS 上运行 Facet 查看器。

> **第一次接触？** 本指南讲的是如何把 Facet 提供给其他机器访问。若只是想在
> 自己的电脑上把它跑起来，请先看[安装](INSTALLATION.md)。

## 概览

Facet 有两类工作负载：

| 组件 | 硬件 | 用途 |
|-----------|----------|---------|
| **评分**（`facet.py`） | GPU（6-24 GB 显存）或 CPU（最低 8 GB 内存，推荐 12 GB，`12gb`/`16gb`/`24gb` 配置档还要更多 —— 见[容器内存限制](#容器内存限制)） | 分析照片并给出评分 |
| **查看器**（`viewer.py`） | 任意机器（资源占用低） | 提供网页照片库服务 |

只有查看器需要跑在服务器上。在工作站上完成评分，然后把数据库同步过去。

> **警告：** 当 `viewer.password` 为空（出厂默认）时，任何能够访问查看器端口的人都可以浏览整个照片库并下载原始照片。在将端口暴露到本机之外之前，请先设置
> `viewer.password`；参见[单用户模式](VIEWER.md#单用户模式默认)。

在开放安装（没有 `viewer.password`）上，助手令牌（**连接助手**）只能在运行 Facet 的电脑上管理。在 Docker 或反向代理之后，请设置
`viewer.password`，或在主机上运行请求
（`docker compose exec facet python -c "import urllib.request ..."`）。反向代理必须发送 `X-Forwarded-For` 或 `Forwarded`，否则会被当作本机。

## 路径映射

当评分机器和查看器通过不同的路径访问照片时，请在 `scoring_config.json` 中配置
`viewer.path_mapping`，把数据库里的路径翻译成本地路径。

**示例：** 照片在 Windows 上通过 UNC/NFS 评分，由一台 Linux NAS 提供服务：

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

这会把 `\\NAS\share\Photos\2024\IMG_001.jpg` 映射为 `/volume1/Photos/2024/IMG_001.jpg`。
配置键里请用正斜杠；反斜杠会被自动规范化。

支持配置多条映射（先匹配到的胜出）：

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos",
      "//NAS/share/Archive": "/volume1/Archive"
    }
  }
}
```

- 数据库中保存的是扫描时的原始路径（例如 `\\NAS\share\Photos\2024\IMG_001.jpg`）。
- 缩略图存放在数据库里，因此浏览时不需要访问磁盘。
- 只要查看器要打开原始文件，就会应用路径映射：下载、全分辨率查看、
  生成图注和点评。
- UNC 路径（`\\server\share`）和盘符（`Z:\`）都支持。

## 容器路径语义

在 Docker/Podman 中，你在查看器里输入的每个文件夹都是**容器内部**的路径。
这包括“选片后导出／清理”的目标文件夹、相册的导出目标和
`viewer.export.allowed_target_dirs`。请使用挂载点，而不是宿主机路径。

**示例。** 随附的 `docker-compose.yml` 把你的照片目录挂载到 `/data/photos`：

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

要把淘汰的照片归入 `rejects` 子目录，请填 `/data/photos/rejects`，而不是容器看不到的
`/home/you/Pictures` 或 `D:\Photos`。

要写到照片目录树之外，请先挂载目标，再把它在容器内的路径加进
`viewer.export.allowed_target_dirs`：

```yaml
services:
  facet:
    volumes:
      - ${PHOTOS_DIR:-./photos}:/data/photos
      - /volume1/Exports:/data/exports   # 供选片／导出输出使用的额外卷
```

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    }
  }
}
```

在解析符号链接和 `..` 之后，位于所有允许根目录之外的目标会被拒绝。
参见[配置 — 导出与选片目标位置](CONFIGURATION.md#导出与选片目标位置)。

**这种拒绝不是权限问题。** 它发生在任何文件被触碰之前。容器内 `facet` 用户与你宿主机账号之间的 UID 不一致是另一类失败：
它发生在复制／移动期间，并会连同操作系统错误一起记入日志。

### 容器的回收站在哪里

当 `viewer.cull.allow_trash` 打开时，`trash_rejects` 使用 `send2trash`。在随附的容器布局里
（照片绑定挂载在 `/data/photos`，uid 1000，`HOME=/home/facet`），照片与
`$HOME` 位于不同的文件系统，因此被丢弃的文件会进入照片卷自己的回收站：

- 文件：`/data/photos/.Trash-1000/files/<name>`
- 元数据：`/data/photos/.Trash-1000/info/` 下的 `<name>.trashinfo`（含 `Path=` 和 `DeletionDate=`）
- 该目录以 `0700` 权限创建

`.Trash-1000` 在**宿主机**上可见，因此直接用 `mv` 把文件移出 `files/` 就能恢复照片。
当 `scanning.skip_hidden_directories` 为真时（默认值），重新扫描会跳过它。

有两种例外：

- **照片没有绑定挂载**（例如用 `docker run` 把照片放在容器内部）：
  回收站位于容器内的 `~/.local/share/Trash`，**容器被删除时它也就没了**。
- **Rootless Podman**：`.Trash-1000` 的属主是映射后的宿主机 subuid，而不是你的账号；
  恢复时可能需要 `podman unshare`。

如果想自己指定目标位置，请改用 `move_rejects` 移到某个 `target_dir`
（[选片后导出／清理](VIEWER.md#选片后导出清理)）。

### 配置文件的归属

Facet 只会接管由它自己创建的 `/config/scoring_config.json`；已经存在的文件
会保留它的属主和权限模式。唯一的例外（容器内 `facet` 用户读不到的配置）以及 rootless Podman 的做法见
[安装 — 容器内的文件归属](INSTALLATION.md#容器内的文件归属)。

配合 compose 的 `group_add`（见[仅可通过某个用户组读取的照片共享](#仅可通过某个用户组读取的照片共享group_add)），
可读性检查也会带上这些用户组，因此仅通过此类用户组可读的配置会被原样保留。
若 `setpriv` 检查本身失败，该文件会被视为不可读。

## 构建 Angular 客户端

服务器从 `client/dist/client/browser/` 提供预先构建好的 SPA。请在
部署前构建它：

```bash
cd client && npm ci && npm run build && cd ..
```

这只在构建时需要 Node.js 24.15.0 或更高版本（限 24.x 系列），服务器上不需要。

## Synology NAS（DS420j / J 系列）

J 系列使用 ARM CPU、1 GB 内存，且不支持 Docker。查看器直接用 Python 运行。

### 前置条件

1. **启用 SSH：** DSM > 控制面板 > 终端机和 SNMP > 启用 SSH
2. **安装 Python3：** 通过 DSM 套件中心，或通过 SSH：
   ```bash
   # 检查是否已安装
   python3 --version
   pip3 --version
   ```

### 安装

```bash
ssh admin@your-synology-ip

# 创建目录
mkdir -p /volume1/facet

# 安装依赖（仅查看器需要）
pip3 install fastapi uvicorn pyjwt pillow aiosqlite
```

### 导出轻量数据库

在评分工作站上，导出一个精简版数据库用于 NAS 部署：

```bash
python database.py --export-viewer-db
```

这会生成 `photo_scores_viewer.db`，它会：

- 剥离 CLIP 特征向量、图注特征向量和人脸特征向量；
- 保留每张照片的直方图（各约 2 KB），供 RGB 直方图控件使用；
- 把缩略图从 640px 缩小到 320px；
- 以空的已保存地点和最近位置列表开始；评分机器上的私有地点不会被复制；
- 通常能把 14 GB 的数据库压到约 4-5 GB。

导出是增量的：只会同步新增和有变化的照片。要完整重建：

```bash
python database.py --export-viewer-db --force-export
```

> **警告：** `--force-export` 会丢弃 NAS 上在查看器中设置的评分、位置、手动标签以及私有的已保存/最近地点。
> 只有增量导出会保留它们。

**完成与重试。** 完整导出会先在目标旁的仅所有者可访问的临时目录中准备，剥离源端的私有状态，压缩，并在发布前检查 SQLite 与外键的一致性。新的输出只有在就绪后才会出现。替换已有输出时使用 SQLite 的备份事务，为已打开的读取者和 WAL 连接保留其 inode；失败时保留之前的数据库。已存在但不是 SQLite 数据库的输出会作为文件被替换。新输出和备份快照要求文件系统支持硬链接。若不支持，命令会失败且不会发布不完整的文件；请选择兼容的输出目录。

增量导出先升级目标端架构，然后在目标端的一个事务中同步源端的一份快照。新照片的缩略图会先被缩小，并在该事务开始前检查目标端的完整性，因此查看器的写入只在应用更改期间等待。数据同步失败或被中断时，照片、人脸、标签、向量和审阅回执的更改会一并回滚；架构升级可能保留。请修复所报告的原因，再重新运行同一命令。新照片的缩略图损坏属于错误，因此在源端修复后重试，也会生成其缩略图。已有缩略图保持不变。目标端的审阅编辑、手动标签以及已保存/最近的地点保持在本地，并会被增量同步保留。

输出路径是字面文件名，在支持的文件系统上包括以 `file:` 开头的名称；不接受 SQLite URI 参数。

导出会为暂存或回滚日志预留可用空间，如果估算放不下，会在复制前失败。异常和正常中断会删除临时副本；被强制终止的进程可能在输出旁留下隐藏的、仅所有者可访问的 `.*.export-*` 目录。导出程序停止后，请删除该临时目录并重试。之前发布的旧数据库仍是恢复点。SQLite 的锁定依然适用：当目标端的写入者空闲时，请重试锁定错误。

如果输出的主文件缺失，但仍残留 `-wal`、`-shm` 或 `-journal` 附属文件，导出会停止且不会删除它们。请关闭该数据库的所有使用者并先恢复它，再重试；残留的 WAL 可能包含属于之前数据库的数据。

“查找相似照片”功能在导出的数据库上无法使用（没有特征向量）。请在评分机器上使用该功能。

**手动标签。** 导出包含[手动标签](VIEWER.md#手动标签)
（`photo_manual_tags`）。增量导出只会追加评分数据库的标签：

- 你在 NAS 上移除的标签，只要评分数据库里仍有它，就会回来。
- 在 NAS 上添加的标签不会复制回去；请也在评分机器上添加。
- 在评分机器上移除的标签会一直留在 NAS 上，直到 `--force-export`。
- 合并时不会强制每张照片 50 个标签的上限，因此照片可能超出该上限。

### 同步文件

先构建 Angular 客户端（[构建 Angular 客户端](#构建-angular-客户端)），
再同步到 NAS：

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` 里带着随附的默认配置，因此 NAS 就跑在这些默认值上。要使用你自己的
`scoring_config.json`，请把它加进 `rsync` 列表。先检查一遍：里面以明文保存着查看器
密码和 API 密钥。

查看器默认打开 `photo_scores_pro.db`（可用 `DB_PATH` 覆盖）。在 NAS 上，
设置 `DB_PATH=/volume1/facet/photo_scores_viewer.db`，或做个符号链接：

```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

要让下载功能可用，原始照片必须能在 NAS 上通过 `path_mapping` 里的路径访问到。

### 低内存配置

在 NAS 的 `scoring_config.json` 中加入 `viewer.performance`：

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

这会用适合 1 GB 内存的取值，覆盖全局 `performance` 设置（后者是按评分场景调优的）。
详见[配置](CONFIGURATION.md#查看器性能)。

### 运行

```bash
cd /volume1/facet

# 测试
python3 viewer.py

# 生产环境（1 GB 内存用 1 个 worker）
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

通过 `http://your-synology-ip:5000` 访问。

### 开机自启

DSM > 控制面板 > 任务计划 > 新增 > 触发的任务 > 用户自定义脚本：

- **事件：** 开机
- **用户：** root
- **脚本：**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

使用群晖内置的反向代理：DSM > 控制面板 > 登录门户 > 高级 > 反向代理：

| 来源 | 目标 |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

再配合 DSM > 控制面板 > 安全性 > 证书 中申请的 Let's Encrypt 证书。

对于智能体标签页桥接（[AI 智能体](AGENTS.md)），请打开该规则的**自定义标头**选项卡
并选择**创建 > WebSocket**。这会添加 `/api/mcp/bridge` 所需的 `Upgrade` 和 `Connection` 头。
如果该规则改写了 `Host` 头，请把你的公开来源写入
`viewer.mcp.allowed_origins`。

## Synology NAS（Plus / x86 系列）

Plus 系列 NAS 支持 Docker（Container Manager）。

### 运行已发布的镜像

安装方式与[安装 › 使用 Docker 安装](INSTALLATION.md#使用-docker-安装)一致：
CPU 型 NAS 用 `docker compose up -d`，若有 NVIDIA 显卡则用对应配置档的命令块。
`.env` 里的设置和配置文件挂载见
[安装 › 可修改的 Docker 设置](INSTALLATION.md#可修改的-docker-设置)。
下面只讲 NAS 上不一样的地方。

**镜像只有 `linux/amd64`（x86_64）版本。** 这覆盖了 x86 架构的 NAS 硬件（群晖
Plus/x86、UGREEN、UnifyDrive，以及在 Intel/AMD 上运行的 Coolify、Portainer 或原生 Docker）。
没有 `arm64` 镜像。在 ARM 架构的 NAS 或树莓派上，请用
`docker compose build` 本地构建；为此 compose 文件在 `image:` 键下保留了 `build: .`。

**规划好磁盘空间：** 镜像，加上每个配置档首次运行时下载的模型。

- 解压后的镜像：CPU 约 3.34 GB，`latest-cuda`（`sm_75`-`sm_120`）约 13.1 GB，
  `latest-cuda-legacy`（`sm_50`-`sm_90`）约 13.8 GB（[镜像大小](#镜像大小)）。
  `docker pull` 传输的是压缩数据，比这更小。
- 模型：`legacy` 4.69 GB、`8gb` 6.93 GB、`12gb`/`16gb` 14.55 GB、`24gb` 19.32 GB
  （[下载体积](INSTALLATION.md#下载体积)）。
- `docker compose down -v` 会删除模型卷并强制重新下载。

**版本化标签。** `:latest`、`:latest-cuda` 和 `:latest-cuda-legacy` 每次发版都会移动。
如果你不希望 NAS 上的镜像悄悄变化，请固定到某个版本（`:1.7.2`、`:1.7`、`:1.7.2-cuda`、`:1.7.2-cuda-legacy` 等）。这些变体由同一个 `Dockerfile` 通过
`BASE_IMAGE`、`STRIP_TORCH`、`INSTALL_CUML` 和 `REQUIREMENTS_LOCK` 这几个构建参数构建，取值在
`.github/workflows/docker-publish.yml` 中设置。手动运行该工作流的 `workflow_dispatch`
可以基于 `master` 重新发布 `latest` / `latest-cuda` / `latest-cuda-legacy`，而不必发布正式版本。

**商业构建。** 添加 `--build-arg FACET_LICENSING=commercial`（compose：
`build.args.FACET_LICENSING: commercial`）。这会跳过受限 lock（`insightface`、
`pyiqa` 及其依赖），并设置 `FACET_LICENSING_MODE=commercial`。默认的
`FACET_LICENSING=default` 保持已发布镜像的行为。受限 lock 由
`REQUIREMENTS_LOCK` 推导而来（legacy lock 对应 `requirements.legacy.restricted.lock.txt`）。参见
[安装](INSTALLATION.md#商业安装与受限软件包)。

如果需要只跑查看器的小镜像（不带 CUDA），可以构建一个精简镜像。每个 `COPY` 源都必须被
git 跟踪，这也是这里不复制 `scoring_config.json` 的原因；没有它，容器
就跑在 `config/` 里的默认值上。

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
COPY viewer.py config_resolve.py database.py tagger.py ./
COPY api/ api/
COPY config/ config/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

> **智能体标签页桥接需要单个 worker。** worker 多于一个时，`ui_*` 调用可能落到
> 不认识你标签页的进程并返回 `no_tab`。如果使用
> [AI 智能体](AGENTS.md)，请使用 `--workers 1`。

```yaml
services:
  facet:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./photo_scores_pro.db:/app/photo_scores_pro.db
      - /volume1/Photos:/volume1/Photos:ro  # 挂载照片以便下载
    restart: always
```

### 仅可通过某个用户组读取的照片共享（`group_add`）

在 NAS 上，照片共享通常只能通过某个用户组读取（Synology 上一般是
`users`，gid 100）。请用 `group_add` 把该组加给容器，gid 取自 NAS 上
`id <你的用户名>` 输出的数字：

```yaml
services:
  facet:
    group_add:
      - "100"
```

入口脚本用 `setpriv` 从 root 降权为 `facet`，并保留这些 gid。可用
`docker compose exec facet grep Groups /proc/1/status` 验证：输出包含 `1000` 以及你的 gid。

替代方案：设置 `user: "1000:1000"` 并加上 `group_add`。此时入口脚本既不会 chown，
也不会初始化 `/config`，所以每个挂载都必须已可被 uid 1000 写入。

## 容器内存限制

Facet 读取的是容器的内存限制（cgroup v2 上是 `memory.max`，
v1 上是 `memory.limit_in_bytes`），而不是宿主机的内存。它据此确定哪些模型一起
加载、内存分块大小、模型缓存以及 RAW 解码。较早的版本
（v1.7.2 及之前）会忽略 `mem_limit`，因而可能被 OOM 杀掉
（[issue #111](https://github.com/ncoevoet/facet/issues/111)）。

### 各配置档的推荐最低内存

模型权重只占峰值内存的一部分：torch 运行时、解码后的图像和
激活值都会叠加上去。请把这些数字当作下限。

| VRAM 配置档 | 模型权重（合计） | 推荐容器内存 |
|---|---|---|
| `legacy` / `8gb` | 15.0 GB | 12 GB（GPU）／最低 8 GB、推荐 12 GB（CPU） |
| `12gb` / `16gb` | 22.0 GB | 至少 18 GB（暂定） |
| `24gb` | 25.0 GB | 至少 18 GB（暂定） |

- **GPU 和 CPU 不同。** 在 GPU 上，权重待在显存里，内存主要装解码后的
  图像：在一块 RTX 3080 上跑 `8gb`（405 张照片，`ram_chunk_size: 12`，`num_workers: 2`）峰值为
  9.23 GB，并在 `mem_limit: 12g` 下跑通。在
  CPU 上，所有模型都加载进内存。请按与你的运行方式相符的那一行来配置。
- **在 CPU 上，8 GB 是下限。** 在 `--memory=8g` 下扫描 50 张照片，`legacy`（峰值 7.26 GB）和
  `8gb`（7.56 GB）都跑完了，对于 18-20 MP 的 JPEG，离上限只差约半个 GB。更大的画幅、RAW
  解码或更繁忙的宿主机需要更多，所以推荐 12 GB。
- **`12gb`、`16gb` 和 `24gb` 没有实测。** 18 GB 是暂定的占位值。
- **`12gb` 显存峰值：9.4–11.3 GiB（模拟）。** 在 11.7 与 12.0 GiB 上限下的整卡峰值，含约 2 GiB 桌面占用；PyTorch 峰值为已分配 6.3 GiB、已预留 8.8 GiB（Qwen3.5 标签 VLM 阶段）。 在 16 GB 显卡上以模拟的 12 GiB 上限测得；ONNX Runtime 模型（InsightFace）不受该上限约束；未在真实的 12 GB 显卡上测量。
- **留意匿名内存。** `docker stats` 的 MemUsage 和 cgroup 的 `memory.current`
  都把可回收的页缓存算了进去，因此会产生误导。
- **模型缓存。** 当 `models.keep_in_ram` 为 `"auto"` 时，只有该模型的大小加上
  `models.ram_cache_reserve_gb`（默认 4 GB）的内存可用时，模型才会在
  分块之间留在内存中。预留量越小，缓存越多（[配置](CONFIGURATION.md#模型)）。

在 CPU 上，`8gb` 配置档无论限制多少，永远规划出同样的 5 趟：
`Pass 1: qrealign [~5.0GB RAM]`、`Pass 2: clip + topiq_iaa [~5.0GB RAM]`、
`Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`、`Pass 4: saliency + samp_net [~4.0GB RAM]`、
`Pass 5: insightface [~2.0GB RAM]`。

在 `docker-compose.yml`（或一个覆盖文件）里设置这个限制：

```yaml
services:
  facet:
    mem_limit: 16g
```

### 分批分组有上限，却完全没有下限

- **有容器限制时**，每趟 CPU 分批的预算是该限制减去 2 GB 预留，并压在
  5 GB 的上限之下。限制很紧时，每趟只装一个模型。
- **没有限制时**，预算是（系统内存 − 1 GB）÷ 1.6。4 GB 的宿主机每趟预算 1.9 GB，
  2 GB 的宿主机则是 0.6 GB。
- **比预算还大的模型**仍然会独占一趟，并在警告里点名。例如
  仅 `qwen3_5_4b_tagger`（`24gb`）就会规划出一趟 8.0 GB。

> **警告：** 永远不要把容器配到比你所用配置档中最大的单个模型还小。

## Windows（WSL2）搭配 NVIDIA GPU

通过 WSL2 在 Windows 上用 Docker 跑完整的 GPU 评分 + 查看器技术栈，不需要
Docker Desktop。所有东西（发行版、它的镜像、`/var/lib/docker`）都留在**数据盘**
（例如 `D:`）上，当 `C:` 空间紧张时很有用。

**前置条件：** Windows 上装有较新的 NVIDIA 驱动（在 Windows 命令提示符里
`nvidia-smi` 可用）。**不要**在 WSL 内部安装驱动。

### 1. 安装 WSL2（管理员权限，一次性）

在**以管理员身份运行**的 PowerShell 中执行，如提示则重启：

```powershell
wsl --install --no-distribution   # 只装 WSL2 平台，不在 C: 上放发行版
```

### 2. 安装一个磁盘位于数据盘上的发行版

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` 会把发行版的 `ext4.vhdx` 放到 `D:\wsl\facet` 下。`--no-launch` 会跳过
首次运行时的用户创建提示；下面的命令都以 `root` 身份运行。

### 3. 启用 systemd（docker 服务需要）

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # 下次启动时生效
```

### 4. 安装 Docker CE + NVIDIA Container Toolkit（在发行版内部）

```bash
wsl -d facet -u root
# --- 在发行版内部 ---
apt-get update && apt-get install -y ca-certificates curl gnupg
# Docker 仓库（如果你的代号太新，就回退到最新受支持的代号）：
. /etc/os-release; CODE=$VERSION_CODENAME
curl -fsSL -o /dev/null "https://download.docker.com/linux/ubuntu/dists/$CODE/Release" || CODE=noble
install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODE stable" > /etc/apt/sources.list.d/docker.list
# NVIDIA toolkit 仓库（与发行版无关）：
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
nvidia-ctk config --set nvidia-container-cli.no-cgroups=true --in-place   # WSL2 没有 nvidia cgroup
systemctl enable --now docker
# 验证 GPU 直通：
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi --query-gpu=name,memory.total --format=csv
```

### 5. 运行 Facet

Windows 盘上的仓库在 WSL 内部位于 `/mnt/d/...`。请执行
[安装 › 使用 Docker 安装](INSTALLATION.md#使用-docker-安装)中对应你显卡的
命令块：

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # 或你显卡对应的文件
curl -s localhost:5000/health          # -> ok
```

加上 `--build` 可以从当前签出的代码构建，而不是拉取镜像。GPU 配置档
（`8gb`/`12gb`/`16gb`/`24gb`）借助内置的 RAPIDS cuML 在 GPU 上做人脸聚类；`legacy`
在 CPU 上聚类。首次运行会把模型下载到命名卷里；用
`docker compose down -v` 可以重置它们。

### 可复现、自包含的镜像

- **版本被钉死。** 镜像基于 `requirements.lock.txt` 构建，那是一个经过验证的容器的
  `pip freeze`，不含 `torch`/`torchvision` 和 `nvidia-*`（由 CUDA 基础镜像
  提供）。BiRefNet 需要的 `kornia` 也固定在其中。在有意升级之后重新生成：
  `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`。
- **内置 GPU 人脸聚类。** RAPIDS cuML（`cuml-cu12`，约 5.75 GB）让 GPU 配置档
  在 GPU 上做人脸聚类（`face_clustering.use_gpu="auto"`）。`legacy` 以及没有 CUDA 的宿主机
  在 CPU 上聚类。
- **不与宿主机耦合。** 模型缓存放在命名卷里；容器以非特权的
  `facet` 用户运行。
- **精简的构建上下文。** `.dockerignore` 排除了只存在于本地的大块内容（`conda/`、样例数据集、
  `*.db`、各种缓存）；新增的大型本地目录请也加进去。

### 镜像大小

所有镜像都不含模型权重；它们在首次运行时下载到命名卷里
（[各配置档的合计体积](INSTALLATION.md#下载体积)）。规划磁盘时两者都要算上。

| 镜像 | 磁盘占用（实测） | 基础镜像 |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest`（CPU） | 3.34 GB | `python:3.12-slim` + CPU wheel 版 PyTorch |
| `ghcr.io/ncoevoet/facet:latest-cuda`（GPU） | 13.1 GB | CUDA 12.8 版 PyTorch（`sm_75`-`sm_120`，Turing 到 Blackwell）+ RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy`（GPU） | 13.8 GB | CUDA 12.6 版 PyTorch（`sm_50`-`sm_90`，Maxwell 到 Hopper）+ RAPIDS cuML |

“磁盘占用”指解压后的大小（`docker images`）。`docker pull` 传输的更少；压缩后的
大小尚未测量。

## 通用 Linux 服务器

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

或者用封装脚本（默认 1 个 worker；要更多请传 `--workers N`）：

```bash
python viewer.py --production --workers 4
```

智能体标签页桥接需要 `--workers 1`（参见
[运行已发布的镜像](#运行已发布的镜像)）。

### Uvicorn + Nginx

```nginx
server {
    listen 80;
    server_name photos.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 50M;
    }

    location /api/mcp/bridge {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $http_host;
        proxy_read_timeout 3600s;
    }
}
```

智能体标签页桥接（`/api/mcp/bridge`，参见 [AI 智能体](AGENTS.md)）是 WebSocket。它
需要第二个 `location` 块中的 `Upgrade` 和 `Connection` 头，以及单个 worker
（`--workers 1`，默认值）；否则 `ui_*` 智能体工具会返回 `no_tab`。

启用 HTTPS：

```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Systemd 服务

```ini
# /etc/systemd/system/facet.service
[Unit]
Description=Facet Viewer
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/facet
ExecStart=/usr/local/bin/uvicorn api:create_app --factory --host 127.0.0.1 --port 5000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

如果使用智能体标签页桥接，请使用 `--workers 1`。

```bash
sudo systemctl enable --now facet
```

### Caddy（自动 HTTPS）

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## 工作流程

```
 Scoring Machine (GPU)                      Server / NAS
 ─────────────────────                      ─────────────
 python facet.py /photos
         │
         ├─ database.py --export-viewer-db
         │       │
         │       └─ photo_scores_viewer.db ──rsync──▶ viewer.py serves gallery
         └─ scoring_config.json ────────────────────▶ (with path_mapping +
                                                       viewer.performance)
                                                        │
                                                 http://nas:5000
```

每次评分之后重新执行导出和 `rsync`。如果服务器内存充足，
也可以直接同步完整的 `photo_scores_pro.db`。

### 同一时间只跑一个库任务

一次扫描、`--recompute-average`、`--upgrade-db` 以及一次排序器训练都会重写
数据库，因此同一时间只运行其中一个。第二个任务会拒绝启动，指出正在运行的那个，
并以退出码 75 结束（如果 `<db_dir>/.facet_cache/library.lock` 处的锁文件
不可用，则退出码为 1）。

> **警告：** 这把锁**只在一台机器内**有效。通过 SMB/CIFS（例如
> 一台 Windows 工作站给 NAS 共享上的照片评分）访问时，每台机器各有自己的锁。Facet 会记录一条
> 警告，但无法阻止这种情况：请一次只从一台机器上运行库任务。Linux 客户端之间的
> NFS 不受影响。

### 查看器启动与图库索引

从 1.20 升级后的第一次启动会构建缺失的图库索引
（[详情](VIEWER.md#图库索引与计数缓存)）。在约 13 万张照片的图库上，
这需要几分钟，并使数据库增大约 130 MB。

**建议：** 升级后，在启动查看器**之前**运行一次 `python database.py`（Docker：
`docker compose exec facet python database.py`）。一次
`python facet.py` 扫描也会在启动时构建它们。

如果改由查看器来构建：

- 它在构建期间仍提供服务，但图库较慢，并且**保存（评分、拒绝、相册
  修改等）可能被拒绝**，并提示“图库正忙，请稍后重试”。
- 日志中每个索引会显示 `Creating index ...` 和 `Created index ... in N s`，随后是
  `Gallery indexes ready`。`/health` 以 `gallery_indexes` 报告进度（`state`：
  `building`、`ready`、`deferred`、`failed` 或 `stopped`；`total` 个中已完成的 `done` 个）。
- 停止查看器会保留已完成的索引；下一次启动继续构建。
- 如果扫描或其他图库任务正在运行，查看器会在没有这些索引的情况下提供服务，并
  记录一条警告。请在该任务结束后重启它，或运行 `python database.py`。
- 如果数据库旁的 `.facet_cache/library.lock` 不可用（权限问题、只读
  挂载），查看器不会构建。请修复路径后重启。
- 使用 `--workers N` 时，一个 worker 负责构建，其余的提供服务。
- 在 Docker 中，健康检查 30 秒的 `start_period` 无需改动：构建期间 `/health` 仍会应答。

在低于 3.48.0 的 SQLite 上（CPU 镜像自带 3.46.1），全景检测无法仅从新索引读取；
那里的速度没有测量过。在 3.51 以外的 SQLite 上，
升级后的第一次连拍遍次中，时间戳完全相同的照片可能被分到不同的组
（参见 CHANGELOG）。

> **警告：** 请在停止查看器之后再复制或替换数据库。它运行期间，
> 最近的更改位于 `-wal` 和 `-shm` 文件中，而不只是 `.db`；一次正常关闭
> 会合并它们（即使设置了 `performance.wal_checkpoint_minutes: 0`）。在 Windows 上，只要查看器打开着数据库文件，
> 就完全无法替换它。

## 密钥的存放与轮换

有一个密钥同时用于签发每一次登录会话（JWT）和每一个相框链接。它保存在
配置文件旁边的 `.facet_secret` 中（权限 `0600`，已加入 gitignore），而不是 `scoring_config.json`。

旧版本把它作为 `share_secret` 存放在配置中，而随附的值是公开的。
启动时，Facet 会把残留的 `share_secret` 迁移进密钥文件并删除该键。
凡是 Facet 自己公开过的值都会被替换，这会让所有人登出一次。

| 位置 | 方式 |
|-------|-----|
| 默认 | `scoring_config.json` 旁边的 `.facet_secret`，权限 `0600` |
| 容器／编排系统 | `FACET_JWT_SECRET` 环境变量 —— 优先读取，且永不写入磁盘 |
| 轮换 | 执行 `python database.py --rotate-secret`，然后重启查看器 |

- **Docker：** `/app` 是容器的可写层，因此在那里创建的密钥会随容器重建而丢失，
  每次更新镜像所有人都会被登出。请在 `docker-compose.yml` 中设置 `FACET_JWT_SECRET`，
  或用 `- ./.facet_secret:/app/.facet_secret` 绑定挂载该文件。
- **轮换**：只要密钥可能泄露（被提交过的配置、泄露的备份、离职的
  管理员）就应轮换。所有人需要重新登录，展示设备也会重新获取其相框链接。
- **多个 worker：** 请在首次 `--workers > 1` 启动之前先创建密钥（执行一次
  `python database.py --rotate-secret`，或先用 `--workers 1` 启动一次，或设置
  `FACET_JWT_SECRET`）。否则每个 worker 会各自生成一个，会话会失效，直到重启。
- **只读的安装目录：** 服务器会使用内存中的密钥运行，因此每次重启会话都会失效。
  请设置 `FACET_JWT_SECRET`。
- **请和数据库一起备份它**；只恢复数据库而没有它，会把所有人都登出。

## 多用户配置

要给每个用户一组私有的照片目录，请在
`scoring_config.json` 中加入 `users` 段。参见[配置](CONFIGURATION.md#用户)。

### 快速上手

```bash
# 在评分机器上添加用户
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

然后编辑 `scoring_config.json`：

```json
{
  "users": {
    "alice": {
      "password_hash": "...",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "...",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family"
    ]
  }
}
```

目录路径必须与数据库中保存的照片路径一致。如果用了 `viewer.path_mapping`，
请使用**映射之后**的路径（也就是它们在查看器主机上的样子）。

### 迁移已有的评级

要把单用户模式下的评级迁移给某个用户：

```bash
python database.py --migrate-user-preferences --user alice
```

### 扫描按钮

要允许查看器触发扫描（多用户模式下为超级管理员；已设置非空 `viewer.edition_password` 的单用户安装则为编辑会话），请启用它。扫描在
运行查看器的机器上执行，无需 GPU（[没有显卡](INSTALLATION.md#没有显卡)）：

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## 使用 Litestream 做持续备份

数据库可能会涨到几十 GB（评分 2 万张以上照片后约 14 GB），而重新扫描
要耗费 GPU 时间。[Litestream](https://litestream.io/) 会把变更持续流式复制到 S3、
B2、GCS、SFTP 或另一块磁盘，并支持精确到几秒的时间点恢复。

Facet 并不捆绑 Litestream。请在运行 Facet 的主机上安装它；它作为附属进程运行，
无需改动 Facet。Facet 的周期性 WAL 检查点（默认每 30 分钟一次，
`performance.wal_checkpoint_minutes`；`0` 会禁用它，查看器正常关闭时仍会
执行检查点）会把 WAL 控制在较小的体积。

### 最小 Litestream 配置

```yaml
# /etc/litestream.yml
dbs:
  - path: /opt/facet/photo_scores_pro.db
    replicas:
      # 廉价对象存储；请替换成你自己的存储桶。
      - type: s3
        bucket: my-facet-backups
        path: photo_scores_pro
        region: us-east-1
        access-key-id:     $LITESTREAM_AWS_KEY
        secret-access-key: $LITESTREAM_AWS_SECRET
        retention: 72h               # 保留 3 天的时间点历史
        snapshot-interval: 24h        # 每天做一次完整快照
        validation-interval: 6h       # 尽早发现损坏
```

### Systemd 单元

```ini
# /etc/systemd/system/litestream.service
[Unit]
Description=Litestream continuous SQLite replication
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/litestream replicate -config /etc/litestream.yml
Restart=always
User=facet
EnvironmentFile=/etc/litestream.env

[Install]
WantedBy=multi-user.target
```

`litestream.env` 保存 AWS / B2 的凭据，让它们不出现在 YAML 里。

### 恢复演练

请在真正需要之前先演练一遍：

```bash
sudo systemctl stop facet
sudo systemctl stop litestream
litestream restore -o /tmp/restored.db s3://my-facet-backups/photo_scores_pro
# 校验
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM photos;"
# 换上去
sudo mv /opt/facet/photo_scores_pro.db /opt/facet/photo_scores_pro.bad
sudo mv /tmp/restored.db /opt/facet/photo_scores_pro.db
sudo chown facet:facet /opt/facet/photo_scores_pro.db
sudo systemctl start litestream
sudo systemctl start facet
```

### 费用大致估算

对于 14 GB 的数据库，评分活跃期每天约有 50 MB 的 WAL 变动：

- S3 标准存储约每月 0.30 美元
- PUT 操作约每月 0.05 美元

与重新扫描相比可以忽略不计：那需要在一块 16 GB 的 RTX 上跑约 50 个 GPU 小时。
