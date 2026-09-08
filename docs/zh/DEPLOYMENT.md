# 部署指南

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md) · **简体中文**

在远程服务器或 NAS 上运行 Facet 查看器。

> **第一次接触？** 本指南讲的是如何把 Facet 提供给其他机器访问。若只是想在
> 自己的电脑上把它跑起来，请先看[安装](INSTALLATION.md)。

## 概览

Facet 有两类工作负载：

| 组件 | 硬件 | 用途 |
|-----------|----------|---------|
| **评分**（`facet.py`） | GPU（6-24 GB 显存）或 CPU（最低 8 GB 内存，推荐 12 GB，`16gb`/`24gb` 配置档还要更多 —— 见[容器内存限制](#容器内存限制)） | 分析照片并给出评分 |
| **查看器**（`viewer.py`） | 任意机器（资源占用低） | 提供网页照片库服务 |

只有查看器需要跑在服务器上。在工作站上完成评分，然后把数据库同步过去。

## 路径映射

当评分机器和查看器服务器通过不同的挂载点访问照片时，请在 `scoring_config.json` 中配置 `viewer.path_mapping`，把数据库里的路径翻译成本地磁盘路径。

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

配置键里请用**正斜杠**，可读性更好 —— 反斜杠会被自动规范化。这会把 `\\NAS\share\Photos\2024\IMG_001.jpg` 这样的数据库路径映射为 `/volume1/Photos/2024/IMG_001.jpg`。

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

**工作原理：**
- 数据库中保存的是扫描时的原始路径（例如 `\\NAS\share\Photos\2024\IMG_001.jpg`）
- 缩略图以 BLOB 形式存放在数据库里，因此浏览时完全不需要访问磁盘
- 只要查看器要打开原始文件，就会应用路径映射：下载、全分辨率查看、生成图注和点评
- UNC 路径（`\\server\share`）和盘符（`Z:\`）都支持
- 第一个匹配上的前缀胜出

## 容器路径语义

你在查看器的任何文件夹输入框里填写的内容 —— “选片后导出／清理”的目标文件夹、相册的复制／符号链接导出目标，或 `scoring_config.json` 里的 `viewer.export.allowed_target_dirs` —— 都由 Facet 进程自己解析。**在 Docker/Podman 下，这个进程运行在容器内部**，因此每个路径都是*容器*所看到的路径：挂载点，而绝不是宿主机一侧的路径。

**示例。** 随附的 `docker-compose.yml` 把你的照片目录挂载到 `/data/photos`：

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

要在选片时把淘汰照片归入 `rejects` 子目录，请在对话框里填 `/data/photos/rejects`，绝不要填宿主机路径（`/home/you/Pictures`、`D:\Photos` 等），容器根本看不到它们。`viewer.export.allowed_target_dirs` 同理：写容器一侧的路径。

如果要写到被扫描的照片目录树之外 —— 比如一个单独的导出卷 —— 请先把它挂载进容器，再把它在容器一侧的路径加进 `viewer.export.allowed_target_dirs`：

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

解析结果落在所有已挂载卷之外的目标会被拒绝（`403`）—— Facet 的目标目录检查会对请求*以及*每个允许的根目录执行 `os.path.realpath()`，在比较之前解析符号链接和 `..`，所以一个只有从容器外部看才正确的路径（或指向挂载点之外的符号链接）仍然过不了包含性检查。完整的允许清单参考见[配置 — 导出与选片目标位置](CONFIGURATION.md#导出与选片目标位置)。

**这不是容器用户权限的问题。** 容器内 `facet` 用户的 UID 通常与你宿主机账号的 UID 不同，这确实会在绑定挂载上引发另一类真实的文件系统权限失败 —— 但那发生在上述路径检查通过*之后*，即真正执行复制／符号链接／移动的时候，并且会连同失败文件的底层操作系统错误一起记入服务端日志。而 `403 target_dir is not an allowed export location`（或界面上笼统的“拒绝访问”）发生在任何文件被触碰*之前*，与 UID 毫无关系。

### 容器的回收站在哪里

当 `viewer.cull.allow_trash` 打开时，`trash_rejects` 会调用 `send2trash`，它实现了 freedesktop.org 的回收站规范，并根据文件与你的 `$HOME` 是否位于同一文件系统，在两个目标位置中选择其一。在随附的容器布局里 —— 照片绑定挂载在 `/data/photos`，以 uid 1000 运行，`HOME=/home/facet` —— 两者从不相同：`/data/photos` 在容器内是它自己的挂载点（对它调用 `os.path.ismount()` 返回 `True`），并且与容器 overlay 上的 `$HOME` 位于不同的设备上 —— 如果想在自己的部署上确认，可以比较一张照片和 `$HOME` 的 `os.stat(...).st_dev`；具体数值因宿主机而异，重要的只是二者不同。因此 `send2trash` 走的是规范里的*卷内回收站*分支，而不是家目录回收站分支：被淘汰的文件会落在 `/data/photos/.Trash-1000/files/<name>`，并在 `/data/photos/.Trash-1000/info/` 下生成对应的 `<name>.trashinfo`，记录 `Path=` 和 `DeletionDate=`。该目录以 `0700` 权限创建。

因为 `/data/photos` 本身就是绑定挂载点，`.Trash-1000` 在挂载的**宿主机**一侧同样可见且完整 —— 直接用 `mv` 把文件移出 `files/` 就能恢复一张被丢进回收站的照片，完全不需要访问容器。Facet 自己的扫描器也不会再撞见它：当 `scanning.skip_hidden_directories` 为真时（默认值），`os.walk` 会剪掉以点开头的目录，因此只要开着这个开关，回收站里的文件在重新扫描时是不可见的；关掉它则会被重新找到。

有两种情况表现不同：

- **照片目录树没有绑定挂载**（例如用 `docker run` 把照片存在容器自己的文件系统上）会让照片与 `$HOME` 位于同一设备上，于是 `send2trash` 改用容器内的家目录回收站（`~/.local/share/Trash`）—— 容器被删除时它也就没了。
- **Rootless Podman** 会把容器的 uid 1000 映射到宿主机的一个 subuid，因此 `.Trash-1000` 在宿主机一侧的属主是那个映射后的 id，而不是你自己的账号；在宿主机上读取或恢复其中的文件可能需要 `podman unshare`。

如果你希望被丢弃的文件进到自己指定的位置，而不是每个卷里那个隐藏的回收站目录，那么用 `move_rejects` 移到一个明确的子目录（见[选片后导出／清理](VIEWER.md#选片后导出清理)）仍是可选方案 —— 它在容器里同样安全，目标就是你所指定的 `target_dir`。

### 配置文件的归属

同样的 UID 边界也适用于 `/config/scoring_config.json` 本身。Facet 只会接管由它自己创建的配置文件；已经存在的文件会保留你赋予它的属主和权限模式，而且 Facet 自己的配置写入现在会尽量保持这一点，而不是把文件交给容器所使用的那个 uid。关于哪些行为是有保证的、Facet 仍会接管归属的唯一情形（一个容器内 `facet` 用户读不到的、事先就存在的配置文件），以及如何让一个由 rootless Podman 挂载的配置文件既归你所有又能被容器写入，请见[安装 — 容器内的文件归属](INSTALLATION.md#容器内的文件归属)。

## 构建 Angular 客户端

FastAPI 服务器从 `client/dist/client/browser/` 提供预先构建好的 SPA。请在部署前构建它：

```bash
cd client && npm install && npx ng build && cd ..
```

这只在构建时需要 Node.js 20+。构建产物是静态资源 —— 服务器运行时并不需要 Node.js。

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
- 剥离 CLIP 特征向量、图注特征向量和人脸特征向量
- 保留每张照片的直方图（各约 2 KB），查看器的 RGB 直方图控件要读取它
- 把缩略图从 640px 缩小到 320px
- 通常能把 14 GB 的数据库压到约 4-5 GB

导出是增量的：如果 `photo_scores_viewer.db` 已存在，只会同步新增和有变化的照片。用 `--force-export` 可完整重建：

```bash
python database.py --export-viewer-db --force-export
```

“查找相似照片”功能在导出的数据库上无法使用（CLIP 特征向量已被剥离）。请在评分机器上使用该功能。

### 同步文件

在评分机器上，先构建 Angular 客户端（见[构建 Angular 客户端](#构建-angular-客户端)）。

然后把查看器和导出的数据库同步到 NAS：

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` 里带着随附的默认配置，因此不会同步 `scoring_config.json`：除非你在查看器旁边放上自己的覆盖文件，否则 NAS 就跑在这些默认值上。如果评分机器上有一份，请把它加进 `rsync` 列表 —— 它是逐个安装实例独有的文件，所以先检查一遍（里面以明文保存着查看器密码和各种 API 密钥）。

查看器默认打开 `photo_scores_pro.db`（可用 `DB_PATH` 环境变量覆盖）。在 NAS 上，要么设置 `DB_PATH=/volume1/facet/photo_scores_viewer.db`，要么做个符号链接：
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

要让下载功能可用，原始照片必须能在 NAS 上通过 `path_mapping` 里配置的路径访问到。

### 低内存配置

在 NAS 的 `scoring_config.json` 中加入 `viewer.performance`，以降低内存占用：

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

这会用适合 1 GB 内存的取值，覆盖全局 `performance` 设置（后者是按评分场景调优的）。详见[配置](CONFIGURATION.md#查看器性能)。

### 运行

```bash
cd /volume1/facet

# 测试
python3 viewer.py

# 生产环境（1 GB 内存用 1 个 worker）
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

通过 `http://your-synology-ip:5000` 访问

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

使用群晖内置的反向代理：

DSM > 控制面板 > 登录门户 > 高级 > 反向代理：

| 来源 | 目标 |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

再配合 DSM > 控制面板 > 安全性 > 证书 中申请的 Let's Encrypt 证书。

## Synology NAS（Plus / x86 系列）

Plus 系列 NAS 支持 Docker（Container Manager）。

### 运行已发布的镜像

安装方式与[安装 › 使用 Docker 安装](INSTALLATION.md#使用-docker-安装)完全一致：CPU 型 NAS 用 `docker compose up -d`，若机器上有 NVIDIA 显卡则用对应配置档的命令块。`.env` 里的可调项和配置文件挂载记录在[安装 › 可修改的 Docker 设置](INSTALLATION.md#可修改的-docker-设置)。下面只讲 NAS 上不一样的地方。

**发布的三个镜像都只有 `linux/amd64`（x86_64）版本。** 这覆盖了 x86 架构的 NAS 硬件（群晖 Plus/x86、UGREEN、UnifyDrive，以及任何在 Intel/AMD CPU 上跑 Coolify、Portainer 或原生 Docker 的设备）。没有 `arm64` 镜像：在 QEMU 下交叉构建一套几 GB 的机器学习技术栈，每个标签都要耗时数小时，而且 CUDA 变体本来就只有 x86 版。在 ARM 架构的 NAS 或树莓派上，请用 `docker compose build` 本地构建，而不是拉取镜像 —— `docker compose up` 在 `image:` 键下面保留了 `build: .`，正是为了应对这种情况。

**规划好磁盘空间。** 解压后，CPU 镜像在磁盘上约占 3.34 GB，CUDA 镜像（`latest-cuda`，`sm_75`-`sm_120`）约 13.1 GB，旧版 CUDA 镜像（`latest-cuda-legacy`，`sm_50`-`sm_90`）约 13.8 GB —— 这些数字如何测得见下文[镜像大小](#镜像大小)；`docker pull` 传输的是压缩数据，比这更小。除镜像外，还要**加上**每个配置档首次运行时下载的模型权重（`legacy` 4.69 GB、`8gb` 6.93 GB、`16gb` 14.55 GB、`24gb` 19.13 GB —— 完整表格见[安装 › 下载体积](INSTALLATION.md#下载体积)）。`docker compose down -v` 会删除模型卷并强制重新下载。

**版本化标签。** `:latest`、`:latest-cuda` 和 `:latest-cuda-legacy` 每次发版都会移动；如果你不希望 NAS 上的镜像悄悄变化，请固定到某个版本（`:1.7.2`、`:1.7`、`:1.7.2-cuda`、`:1.7.2-cuda-legacy` 等）。三个变体都由同一个 `Dockerfile` 构建，通过 `BASE_IMAGE`、`STRIP_TORCH`、`INSTALL_CUML` 和 `REQUIREMENTS_LOCK` 这几个构建参数区分，具体取值在 `.github/workflows/docker-publish.yml` 里按变体设置。该工作流还接受手动的 `workflow_dispatch` 运行，可以基于 `master` 重新发布 `latest` / `latest-cuda` / `latest-cuda-legacy`，而不必发布正式版本或生成版本化标签。

如果是只跑查看器、镜像必须尽量小（不带 CUDA）的 NAS，可以改为构建一个精简镜像。注意 CI 守卫要求每个 `COPY` 源都被 git 跟踪，因此构建上下文必须包含所列的文件 —— 这也是这里不复制 `scoring_config.json` 的原因：那是逐个安装实例独有的覆盖文件，不纳入版本控制，它缺席只意味着容器跑在 `config/` 里的默认值上。

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite
COPY viewer.py config_resolve.py database.py tagger.py ./
COPY api/ api/
COPY config/ config/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

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

## 容器内存限制

Facet 现在读取的是容器的 cgroup 内存限制（cgroup v2 上是 `memory.max`，v1 上是
`memory.limit_in_bytes`），而不是宿主机的总内存，并据此确定分批分组（哪些模型一起
加载）、内存分块大小、模型的 CPU 缓存以及 RAW 解码并发度。在这个修复之前，上述这些
全都是按宿主机内存来定的：`psutil.virtual_memory()` 读的是 `/proc/meminfo`，而
Docker 并不虚拟化它，于是 `mem_limit` 会被悄悄忽略 —— 一个内存上限远低于宿主机内存
的容器仍然会按整台宿主机都可用来做规划，最后被 OOM 杀掉
（[issue #111](https://github.com/ncoevoet/facet/issues/111)）。

在修复之前发布的镜像（v1.7.2）上复现这个问题，可以看清它的机制：在一台 47 GB 内存的
宿主机上，把 `8gb` 配置档的容器限制为 `--memory=8g`，日志里打印的是
`Mode: CPU-only (47GB RAM)` —— 那是宿主机的内存，不是容器的 —— 并规划出单独一趟
`clip + topiq_iaa + topiq_nr_face + liqe + saliency + samp_net +
insightface [~15.0GB RAM]`。它在跑完第一块 200 张照片之前就被杀掉（`OOMKilled`，
退出码 137）。而在 512 MB 的 cgroup 限制下，修复后的读取器报告 0.500 GB，而
`/proc/meminfo` 仍然报告宿主机的 46.8 GB。

### 各配置档的推荐最低内存

模型权重只占峰值内存的一部分 —— torch 运行时、解码后的图像分块以及各层的激活值都会
叠加上去 —— 所以请把这些数字当作下限，而不是预算。`legacy`/`8gb` 这一行现在有真实的
容器测试支撑：两个配置档都在 `--memory=8g` 下完成了 50 张照片的扫描（见下文）；`16gb`
和 `24gb` 两行仍是暂定的占位数字，背后没有任何实测。

| VRAM 配置档 | 模型权重（合计） | 推荐容器内存 |
|---|---|---|
| `legacy` / `8gb` | 15.0 GB | 12 GB（GPU）／最低 8 GB、推荐 12 GB（CPU） |
| `16gb` | 22.0 GB | 至少 18 GB（暂定） |
| `24gb` | 25.0 GB | 至少 18 GB（暂定） |

**GPU 和 CPU 在这里不能互换，上面的 12 GB 是 GPU 的数字。** 在一块 RTX 3080 上，issue
作者的 `8gb` 配置档处理 405 张照片时，即便设了 `ram_chunk_size: 12` 和
`num_workers: 2`，系统内存峰值仍达 9.23 GB，并在 `mem_limit: 12g` 下跑通。在 GPU
上，模型权重待在显存里；容器的内存主要装解码后的图像分块，这就是这个数字比纯 CPU
所需小得多的原因。

同一个 `8gb` 配置档跑在 CPU 上时，整套模型阵容改为加载进容器的内存。在 issue #111
的后续修复加上上限之前，规划器每趟的容量会随容器限制线性增长，于是限制越大，方案反而
越糟：8 GB 限制下规划出 4 趟，最高一趟 6.0 GB，在包含
`topiq_nr_face + liqe + saliency` 的那趟被 OOM 杀掉（声明 6.0 GB，峰值 RSS
10.46 GB）；12 GB 限制下反而塌缩成只有 2 趟，最高一趟 10.0 GB，同样被 OOM 杀掉。
在 12 GB 限制下内存调控器确实触发过 —— `Evicted 1 model(s) from RAM cache:
topiq_iaa` 是真实的日志行 —— 但那只是调控器介入而仍然不够，并不是救回这次运行的
原因。

现在的上限把每趟的容量压在 5.0 GB，无论容器限制报出多大都不再增长：CPU 上的 `8gb`
配置档不管限制多少，永远规划出同样的 5 趟 —— `Pass 1: qrealign [~5.0GB RAM]`、
`Pass 2: clip + topiq_iaa [~5.0GB RAM]`、`Pass 3: topiq_nr_face + liqe [~4.0GB
RAM]`、`Pass 4: saliency + samp_net [~4.0GB RAM]`、
`Pass 5: insightface [~2.0GB RAM]`。

光有这个扁平的形状仍然不够，因为还有两件分批计划之外的事在消耗预算。分块自动调优器会
在两趟之间的内存低谷里往上长 —— 每次卸载模型都会让占用几乎跌到底，连续三次这样的读数
就被当成余量 —— 于是 `ram_chunk_size` 在第一块期间就从 10 涨到 500，第二块试图一次
性解码剩下的全部照片。而且卸载模型什么也没还给内核：glibc 把释放的块留在自己的 arena
里，于是进程一直保持着第一趟设下的高水位，之后每一趟都跑在自己用不上的内存之上。现在
增长改由每块的峰值来决定，释放的堆也会被显式交还，于是在 `--memory=8g` 下的 50 张
照片扫描在两个配置档上都能跑完 —— `legacy` 的匿名内存峰值 7.26 GB，`8gb` 为
7.56 GB，五块各十张，退出码 0，没有 OOM 杀进程，也没有记录到扫描失败。

**8 GB 是下限，不是宽裕的预算。** 两次运行都只比上限低半个 GB 左右，而且用的是
18-20 MP 的 JPEG；更大的画幅、RAW 解码或更繁忙的宿主机都会侵蚀这点余量，这也是推荐
值是 12 GB 而不是最低值的原因。要盯的数字是匿名内存 —— 不是 `docker stats` 的
MemUsage，也不是 cgroup 的 `memory.current`，这两者都把可回收的页缓存算了进去，所以
前者低估了真实风险，后者则无论实际还剩多少余量都一直贴着容器限制。实测一个 16 GB 的
容器至少带着 12.55 GB 的匿名内存，这也是为什么在这两个修复落地之前，早先一次 12 GB
的运行会被杀掉；这个数字与 issue 作者在 GPU 上 9.23 GB 的峰值也对得上 —— 同一套模型
阵容，减去待在显存而非容器内存里的那部分。GPU 用户按这里的 CPU 数字来配就会配得过多；CPU
用户按 GPU 数字来配则会配得不足 —— 请按你的容器实际的运行方式来选。

更一般地说：`MODEL_RAM_REQUIREMENTS` 只计算模型权重的开销。真实的峰值 RSS 还额外
背着 torch 运行时、解码后的图像分块和各层激活值，这些都不在那个数字里 —— 只看“模型
权重（合计）”这一列来给容器定容量，一定会配得不足。

`16gb` 和 `24gb` 的估算无论在 GPU 还是 CPU 上都完全没有实测支撑；请把 18 GB 当作
暂定占位值，而不是经过验证的下限。

在 `docker-compose.yml`（或一个覆盖文件）里设置这个限制：

```yaml
services:
  facet:
    mem_limit: 16g
```

### 分批分组有上限，却完全没有下限

Facet 的分批规划器把每趟 CPU 分批的预算定为容器的 cgroup 内存限制减去给 torch 运行
时预留的 2 GB，并压在 5 GB 的上限之下，无论限制多大都不让一趟继续变大。这个限制之下
没有任何下限：一个在扣除预留后几乎没有余量的容器会拿到很小的预算，一路缩向零，结果就
是每趟只装一个模型。

如果完全没有设置容器内存限制，预算改从系统内存得出 —— 机器上除操作系统之外的部分
（为它预留 1 GB），再除以 1.6，也就是实测的真实 RSS 与声明模型权重之比。这条路径同样
没有下限：4 GB 的宿主机每趟预算 1.9 GB，2 GB 的宿主机则是 0.6 GB。更早的版本在这里
保留了一个乐观的 4 GB 最小值，那正是本页所描述的同一个缺陷换上了裸机的外衣 —— 它会
在一台 4 GB 的机器里规划出一趟 5 GB 的分批。

比预算还大的单个模型仍然会独占一趟，而不是被拆开，并且**每一个**这样的分批都会在警告
里被点名，而不只是最重的那个：在 4 GB 的容器限制下，容量是 2 GB，而 `24gb` 配置档
仍然会规划出一趟 8.0 GB，因为光是 `qwen3_5_4b_tagger` 就需要 8 GB，无论预算多小都
无法拆分。永远不要把容器配到比你所用配置档中最大的单个模型还小。

## Windows（WSL2）搭配 NVIDIA GPU

通过 WSL2 在 Windows 上用 Docker 跑完整的 GPU 评分 + 查看器技术栈 —— 不需要
Docker Desktop。这样所有东西（Linux 发行版、它的 Docker 镜像，以及
`/var/lib/docker`）都留在**数据盘**（例如 `D:`）上，当系统盘 `C:` 空间紧张时这一点
很重要。

**前置条件：** Windows 上装有较新的 NVIDIA 驱动（在 Windows 命令提示符里
`nvidia-smi` 可用 —— 驱动负责提供 WSL2 的 CUDA 直通；**不要**在 WSL 内部再装一次
驱动）。

### 1. 安装 WSL2（管理员权限，一次性）

在**以管理员身份运行**的 PowerShell 中执行，如提示则重启：

```powershell
wsl --install --no-distribution   # 只装 WSL2 平台，不在 C: 上放发行版
```

### 2. 安装一个磁盘位于数据盘上的发行版

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` 会把发行版的 `ext4.vhdx` 放到 `D:\wsl\facet` 下，这样 Docker 的镜像
存储就不占 `C:`。`--no-launch` 会跳过首次运行时交互式创建用户的提示；下面的命令都以
`root` 身份运行，对一台专用机器来说没问题。

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

Windows 盘上的仓库在 WSL 内部可以通过 `/mnt/d/...` 访问。在那里执行
[安装 › 使用 Docker 安装](INSTALLATION.md#使用-docker-安装)中对应你显卡的
命令块：

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # 或你显卡对应的文件
curl -s localhost:5000/health          # -> ok
```

加上 `--build` 可以从当前签出的代码构建，而不是拉取已发布的镜像。GPU 配置档
（`8gb`/`16gb`/`24gb`）借助内置的 RAPIDS cuML 在 GPU 上做人脸聚类；`legacy` 配置档
始终在 CPU 上聚类。首次运行会把该配置档的模型下载到命名卷里；用
`docker compose down -v` 可以重置它们。

### 可复现、自包含的镜像

- **版本被钉死。** 镜像基于 `requirements.lock.txt` 构建 —— 那是一个经过验证的容器的
  完整 `pip freeze`，并剥掉了 `torch`/`torchvision` 和 `nvidia-*`（这些由 CUDA 基础
  镜像提供）。这可以避免悄无声息地漂移到未经测试的版本。（它防的正是这种事：
  transformers 5.3 改了 Qwen3.5 的视觉批处理，把 VLM 标签器搞坏了，直到补上 padding
  修复才恢复；`kornia` 是 BiRefNet 必需的，
  但 transformers 不会把它带进来，必须固定版本。）在有意升级之后重新生成：
  `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`。
- **内置 GPU 人脸聚类。** 镜像里带着 RAPIDS cuML（`cuml-cu12`），因此 GPU 配置档
  （8gb/16gb/24gb）会在 GPU 上做人脸聚类（通过
  `face_clustering.use_gpu="auto"` 使用 HDBSCAN）；legacy 配置档 —— 以及任何没有 CUDA
  设备的宿主机 —— 始终在 CPU 上聚类。cuML 是体积最大的单个依赖（约 5.75 GB；
  见下面的体积明细）。
- **不与宿主机耦合。** 模型缓存放在命名卷里，而不是宿主机绑定挂载；容器以非特权方式
  运行（默认入口点会降权到 `facet` 用户）。
- **精简的构建上下文。** `.dockerignore` 排除了只存在于本地的大块内容（`conda/`、
  样例数据集、`*.db`、各种缓存、开发产物）—— 新增的大型本地目录请也加进去，
  别让它们进入构建上下文。

### 镜像大小

发布的三个镜像都不含模型权重 —— 它们在首次运行时下载到命名卷里
（[各配置档的合计体积](INSTALLATION.md#下载体积)）。规划磁盘时要把镜像**加上**
这些卷一起算。

| 镜像 | 磁盘占用（实测） | 基础镜像 |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest`（CPU） | 3.34 GB | `python:3.12-slim` + CPU wheel 版 PyTorch |
| `ghcr.io/ncoevoet/facet:latest-cuda`（GPU） | 13.1 GB | CUDA 12.8 版 PyTorch（`sm_75`-`sm_120`，Turing 到 Blackwell）+ RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy`（GPU） | 13.8 GB | CUDA 12.6 版 PyTorch（`sm_50`-`sm_90`，Maxwell 到 Hopper）+ RAPIDS cuML |

这三个基础镜像在本次发布中都换过（issue #119）。“磁盘占用”指解压后镜像展开的体积，
是在本地（`docker images`）针对从本分支构建出的镜像测得的 —— 本轮没有重新测量按组件
拆分的明细（RAPIDS cuML、CUDA 运行时、PyTorch 与基础操作系统各占多少）。`docker pull`
传输的是压缩包，比这些数字更小；等这些镜像发布、有了真实的镜像仓库清单可供测量之后，
“压缩下载大小”这一列会重新加回来。

## 通用 Linux 服务器

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

或者用封装脚本（默认 1 个 worker；要更多请传 `--workers N`）：

```bash
python viewer.py --production --workers 4
```

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
}
```

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

每次评分之后重新执行导出和 `rsync`，即可更新服务器上的数据库。如果服务器内存充足，也可以直接同步完整的 `photo_scores_pro.db`，而不必导出。

### 同一时间只跑一个库任务

一次扫描、`--recompute-average`、`--upgrade-db` 以及一次排序器训练都会重写整个数据库，因此 Facet 同一时间只允许其中一个运行：每一个都会在 `<db_dir>/.facet_cache/library.lock` 上取一个锁文件，第二个任务会拒绝启动，并指出已经在跑的那个。

那个锁是内核文件锁，因此它**只在一台机器内**互斥。当数据库通过 SMB/CIFS 访问时 —— 例如一台 Windows 工作站给 NAS 共享上的照片评分 —— 每台机器各自取到自己的一份锁，谁也看不见谁。Facet 会检测到这类挂载，并在取锁时打印一条警告，但它无法跨主机强制任何约束：请一次只从一台机器上运行库任务。Linux 客户端之间的 NFS 不受影响 —— 在那里 `flock` 会变成由服务器仲裁的 POSIX 记录锁。

## 密钥的存放与轮换

有一个密钥同时用于签发每一次登录会话（JWT）和每一个相框链接。它**不是** `scoring_config.json` 里的键：它保存在配置文件旁边的 `.facet_secret` 中，首次运行时以 `0600` 权限创建，并已加入 gitignore。

它过去是 `scoring_config.json` 里的 `share_secret` 键。那个文件纳入了 git 版本控制，因此首次启动时生成的值被提交并公开了 —— 本项目曾经随代码发布的那个密钥是公开的，必须视为已泄露。下次启动时，Facet 会把残留的 `share_secret` 迁移进密钥文件，从配置中删除该键，并打印一条警告。凡是 Facet 自己公开过的值都会被替换而不是沿用，这会有意地把所有人都登出。

| 位置 | 方式 |
|-------|-----|
| 默认 | `scoring_config.json` 旁边的 `.facet_secret`，权限 `0600` |
| 容器／编排系统 | `FACET_JWT_SECRET` 环境变量 —— 优先读取，且永不写入磁盘 |
| 轮换 | 执行 `python database.py --rotate-secret`，然后重启查看器 |

在 Docker 里，`/app` 是容器的可写层，因此在那里创建的密钥会随容器重建而丢失 —— 每次更新镜像所有人都会被登出。请在 `docker-compose.yml` 中设置 `FACET_JWT_SECRET`，或用 `- ./.facet_secret:/app/.facet_secret` 绑定挂载该文件。

只要密钥可能被别人读到过就应该轮换：曾经被提交过的配置文件、泄露的备份、离职的管理员。轮换会让每一个会话和每一个签名过的相框 URL 失效，所以用户需要重新登录，展示设备也会重新获取链接。

在 `--workers > 1` 时，每个 worker 读的是同一个文件，因此某一个 worker 签发的 JWT 在所有 worker 上都能验证 —— **前提是那个文件已经存在**。例外情形是首次启动时就用了 `--workers > 1` 而 `.facet_secret` 尚不存在：每个 worker 都会各自生成一个密钥，最终只有一个写入成功，于是在某个 worker 上打开的会话会被其他 worker 拒绝，直到服务器重启为止。请在首次多 worker 启动之前先把密钥创建出来 —— 执行一次 `python database.py --rotate-secret`，或先用 `--workers 1` 启动一次，或设置 `FACET_JWT_SECRET`。

当安装目录不可写时，同样的分歧会变成永久性的：服务器会记录一条错误，并使用一个内存中的密钥运行，于是每次重启所有会话都会失效，而且每个 worker 用的签名密钥都不一样。这种情况下请设置 `FACET_JWT_SECRET`。

请把这个文件和数据库一起备份 —— 只恢复数据库而没有它，会把所有人都登出。

## 多用户配置

要给每个用户一组私有的照片目录，请在 `scoring_config.json` 中加入 `users` 段。完整参考见[配置](CONFIGURATION.md#用户)。

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

目录路径必须与数据库中保存的照片路径一致。如果你用了 `viewer.path_mapping`，这些目录应当使用**映射之后**的路径（也就是它们在查看器主机上的样子）。

### 迁移已有的评级

如果你在单用户模式下已经打过星级，可以把它们迁移给某个用户：

```bash
python database.py --migrate-user-preferences --user alice
```

### 扫描按钮

要允许超级管理员从查看器界面触发照片扫描（只有查看器跑在 GPU 机器上时才有意义）：

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

SQLite 数据库可能会涨到几十 GB（评分 2 万张以上照片后，`photo_scores_pro.db` 会达到约 14 GB），而重新扫描要耗费 GPU 时间。[Litestream](https://litestream.io/) 会把 WAL 持续流式复制到 S3、B2、GCS、SFTP 或另一块本地磁盘，并支持精确到几秒的时间点恢复。

Facet 并不捆绑 Litestream。请在运行查看器／评分的主机上安装一次；它作为附属进程运行，对应用完全透明。

Facet 本来就使用 WAL 模式（`db/connection.py:apply_pragmas`），周期性的检查点线程（默认每 30 分钟一次，可通过 `performance.wal_checkpoint_minutes` 配置）会把 WAL 控制在有限大小内。复制期间读取不会被阻塞。

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

对于 14 GB 的数据库，评分活跃期每天约有 50 MB 的 WAL 变动，预计：
- S3 标准存储约每月 0.30 美元
- PUT 操作约每月 0.05 美元
与重新扫描相比可以忽略不计：那需要在一块 16 GB 的 RTX 上跑约 50 个 GPU 小时。
