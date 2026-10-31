# 安装

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md) · **简体中文**

Facet 在你自己的机器上运行。挑选与你的情况相符的章节，复制其中的命令块即可。
[进阶](#进阶)部分只在你确实需要时才用得上。

## 我该选哪种安装方式？

两种方式运行的是同一个 Facet，区别在于安装的简便程度与性能之间的取舍。请选择适合你的那一种。

| | Docker | 不使用 Docker |
|---|---|---|
| 安装 | 一条命令：所有内容都在镜像里 | `install.sh`（Linux、macOS）或 Windows 安装程序在本机建立 Python 环境 |
| 更新 | 拉取新镜像 | 更新代码后重新运行 `install.sh`，或安装新的 Windows 安装程序 |
| 性能 | Facet 与你的文件和显卡之间隔着一层容器；在 Windows 上它运行在 WSL2 里 | Facet 直接使用本机的显卡和文件 |

| 你的情况 | 前往 |
|----------------|-------|
| Windows、macOS 或 Linux，使用容器 | [使用 Docker 安装](#使用-docker-安装) |
| Windows、macOS 或 Linux，不使用容器 | [不使用 Docker 安装](#不使用-docker-安装) |
| NAS，或一台希望从其他机器访问的服务器 | [部署](DEPLOYMENT.md) |

## 哪种配置档适合我的硬件？

*配置档*就是一组按你机器规格挑选的 AI 模型。安装时选定
一个，之后随时可以更换。

| 你的硬件 | 配置档 | 你会得到什么 |
|---------------|---------|--------------|
| 没有显卡 | `legacy` | 所有功能都可用，只是慢一些。 |
| NVIDIA 显卡，6–14 GB | `8gb` | 与 `legacy` 相同的模型，只是跑在显卡上。 |
| NVIDIA 显卡，14–20 GB | `16gb` | 最强的照片评分，外加 AI 标签和照片描述。 |
| NVIDIA 显卡，20 GB 或更多 | `24gb` | 最大的模型，外加对构图的文字解读。 |
| Apple Silicon Mac（M1–M4） | 自动为你选择 | 使用 Mac 的图形核心；按内存容量选定配置档。 |

不确定自己的显卡有多少显存？请使用下面的*自动检测*命令块。

## 使用 Docker 安装

你需要 [Docker](https://docs.docker.com/get-started/get-docker/)。如果有 NVIDIA 显卡，
还需要
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)。
在 Windows 上，这意味着要在 WSL2 里运行 Facet
（[分步指南](DEPLOYMENT.md#windowswsl2搭配-nvidia-gpu)）。

下面每个命令块都从零开始。只挑**一个**。

### 自动检测我的硬件

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # 打开 .env，把 PHOTOS_DIR 设为你的照片文件夹
docker compose up -d
```

打开 <http://localhost:5000>。

### 没有显卡

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # 打开 .env，把 PHOTOS_DIR 设为你的照片文件夹
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d
```

打开 <http://localhost:5000>。

### 8 GB 显卡

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # 打开 .env，把 PHOTOS_DIR 设为你的照片文件夹
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d
```

打开 <http://localhost:5000>。

### 16 GB 显卡

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # 打开 .env，把 PHOTOS_DIR 设为你的照片文件夹
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

打开 <http://localhost:5000>。

### 24 GB 显卡

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # 打开 .env，把 PHOTOS_DIR 设为你的照片文件夹
docker compose -f docker-compose.yml -f docker-compose.24gb.yml up -d
```

打开 <http://localhost:5000>。

### 较旧的 NVIDIA 显卡 (Maxwell, Pascal, Volta)

上面的 GPU 命令块和 `docker-compose.gpu.yml` 拉取的是 `ghcr.io/ncoevoet/facet:latest-cuda`，
它覆盖 `sm_75`-`sm_120`（从 Turing 到 Blackwell）。

对于 Maxwell、Pascal（GTX 900/10 系列）或 Volta（例如 Titan V）显卡，请在执行
`docker compose up -d` 之前，修改你所用 compose 文件（`docker-compose.8gb.yml`、
`.16gb.yml`、`.24gb.yml` 或 `.gpu.yml`）中的 `image:` 行：

- 由 `ghcr.io/ncoevoet/facet:latest-cuda`
- 改为 `ghcr.io/ncoevoet/facet:latest-cuda-legacy`（`sm_50`-`sm_90`，Maxwell 到 Hopper）

这个 `-cuda-legacy` 镜像标签与 `docker-compose.legacy.yml` 毫无关系，后者选择的是纯 CPU 的
`legacy` 配置档。比 Maxwell 更旧的显卡（Kepler、Fermi）没有 CUDA
镜像：请使用[没有显卡](#没有显卡)命令块。

### 日常命令

在你给照片评分之前，照片库都是空的。在 Docker 内部，你的照片文件夹一律叫
`/data/photos`：

```bash
docker compose exec facet python facet.py /data/photos   # 给照片评分
docker compose logs -f                                   # 查看它正在做什么
docker compose down                                      # 停止运行
```

想再次启动，重新执行你上面用过的那一行 `docker compose … up -d` 即可。

## 不使用 Docker 安装

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` 会检测你的显卡，安装与之匹配的软件包，并构建网页照片库。之后每次使用时：

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # 给照片评分
python viewer.py                       # 启动照片库
```

打开 <http://localhost:5000>。

### macOS

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

在 Apple Silicon 上，这会自动使用图形核心。之后每次使用时：

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # 给照片评分
python viewer.py                       # 启动照片库
```

打开 <http://localhost:5000>。

> **5000 端口已被占用？** macOS 用它来跑 AirPlay。运行
> `python viewer.py --port 5001`，然后打开 <http://localhost:5001>。

### Windows

按用户安装的安装程序（MSI）无需管理员权限即可安装 Facet：

| 文件夹 | 内容 |
|---|---|
| `%LOCALAPPDATA%\Facet\app` | 程序本身，每次升级时替换 |
| `%LOCALAPPDATA%\Facet\venv` | Python 环境，安装程序完成时建立 |
| `%LOCALAPPDATA%\Facet\data` | 数据库（`photo_scores_pro.db`）和日志 |
| `%LOCALAPPDATA%\Facet\config` | `scoring_config.json` |

**获取安装程序。** 目前还没有发布版本附带它。可以在克隆的仓库中用 `installer\build-msi.ps1`
构建（需要 WiX 3.14、`uv` 和已构建的前端，脚本会说明从哪里获取 WiX），或从
*Windows install (MSI)* 工作流的一次运行中下载 `facet-msi` 产物。
构建时，前端需要 Node.js 22.22.3 或更新版本（22.14 会使 `npm run build` 失败）。

**首次启动。** 安装程序一结束就会开始建立 Python 环境。
环境约 6 GB，uv 的下载缓存（`%LOCALAPPDATA%\uv\cache`）还要再占用差不多同样的空间。
如果从未完成，或升级更改了 Facet 的依赖，开始菜单中的 *Facet* 会运行这一步。
它会像 `install.sh` 一样根据你的 NVIDIA 显卡及其
驱动选择 PyTorch 版本，没有 NVIDIA 显卡时则选择 CPU 版本。如果装好的 GPU 版本无法使用显卡，
安装会停止并说明原因：请更新驱动，或运行 `Setup-Facet.ps1 -Force -Cpu`。

如果图库无法启动（端口被占用、安装失败、90 秒内无响应），开始菜单窗口会显示错误并等待回车。
90 秒内无响应时，图库会继续运行，之后仍可能启动成功。

**日常使用：**

```powershell
cd "$env:LOCALAPPDATA\Facet\app\installer"
.\Scan-Facet.ps1 "\\NAS\Photos"   # 为照片评分；其余参数会传给 facet.py
.\Start-Facet.ps1                # 图库，地址 http://localhost:5000
.\Stop-Facet.ps1                 # 停止图库和正在进行的扫描
```

图库只在本机上响应。`Start-Facet.ps1 -Lan` 会向其他设备开放，在配置中设置 `viewer.password`
之前它会拒绝启动。

**每个文件夹只用一种写法。** Facet 按扫描时使用的路径保存每张照片，所以 `\\NAS\Photos` 和映射为
`Z:\` 的同一个共享对它来说是两个不同的文件夹：两个都扫描会让每张照片出现两次。请选定一种写法并一直使用。

**受管理的计算机。** 快捷方式以 `-ExecutionPolicy Bypass` 运行 Facet 未签名的 PowerShell 脚本。通过组策略设置的执行策略优先于此参数，因此在受管理的电脑上这些脚本可能无法运行；请联系管理员允许它们运行。

**卸载**（设置 → 应用）会停止 Facet，移除程序、快捷方式、Python 环境和 ExifTool（自定义的
`FACET_HOME` 下同样会移除），保留 `data` 和 `config`。无法删除的内容会记录在
`data\logs\uninstall.log` 中。uv 的下载缓存（`%LOCALAPPDATA%\uv\cache`）和已下载的模型会保留
（用户文件夹中的 `.cache`、`.insightface`）。升级会保留自定义的安装文件夹，只有在 Facet 的依赖
发生变化时才会重新建立环境。

**从 Docker 迁移图库。** 数据库保存每张照片的完整路径，而 Windows 安装看到的是另一个路径下的
同一批照片（`\\NAS\Photos\...` 而不是 `/data/photos/...`）。把数据库复制到 `data`，停止 Facet，
然后改写路径，先做一次试运行：

```powershell
cd "$env:LOCALAPPDATA\Facet\app"
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos" --dry-run
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos"
```

该工具会保留数据库副本（`photo_scores_pro.db.before-rewrite-<时间>`），拒绝合并已在新路径下扫描过
的照片，并清空向量索引，可用 `..\venv\Scripts\python.exe database.py --db ..\data\photo_scores_pro.db --populate-vec` 重建。迁移之前的撤销历史之后
不再适用。
这些命令假定使用默认安装文件夹。旧前缀和新前缀若一个位于另一个之内（例如 `D:\Photos` 改为 `D:\Photos\new`），会被拒绝；请经由一个临时前缀中转。

Docker 同样可以在 Windows 上使用；如需使用 NVIDIA 显卡，请按 [WSL2 指南](DEPLOYMENT.md#windowswsl2搭配-nvidia-gpu)操作。

## 首次运行会遇到什么

- **一次下载。** 首次扫描会拉取你所选配置档的模型：`legacy` 约 4.7 GB、
  `8gb` 约 6.9 GB、`16gb` 约 14.6 GB、`24gb` 约 19.3 GB
  （[下载体积](#下载体积)）。这只发生一次。
- **扫描无需设置。** Facet 会在首次扫描时创建数据库。
- **设置密码之前为只读。** 若要编辑（评分、选片、相册、人物），请在 `scoring_config.json` 中设置
  `viewer.edition_password` 并重启查看器。使用随附的
  `docker-compose.yml` 时，镜像会在首次启动时为你生成一个。
- **你的照片不会被修改。** 扫描只读取照片。把星级和关键词
  写回文件是另一项需要你主动开启的操作（[互操作](INTEROP.md)）。
- **时间。** 首次扫描大型照片库需要一段时间，在处理器上比在显卡上更慢。
  扫描期间你也可以浏览照片库。

## 确认安装成功

```bash
python facet.py --doctor                             # 不使用 Docker 时
docker compose exec facet python facet.py --doctor   # 使用 Docker 时
```

这会打印你的显卡、选定的配置档以及任何缺失项。照片库
运行时，<http://localhost:5000/health> 会回答 `ok`。

有什么不正常？请看[排查依赖冲突](#排查依赖冲突)
和 [GPU 检测问题](#gpu-检测问题)。

---

# 进阶

可选内容：安装过程做了什么、如何修改它，以及依赖参考。

- [可修改的 Docker 设置](#可修改的-docker-设置)
- [自行选择配置档](#自行选择配置档)
- [手动安装，不使用 install.sh](#手动安装不使用-installsh)
- [install.sh 选项与 Makefile 快捷命令](#installsh-选项与-makefile-快捷命令)
- [exiftool](#exiftool)
- [用于人脸检测的 ONNX Runtime](#用于人脸检测的-onnx-runtime)
- [OpenCV headless 版本](#opencv-headless-版本)
- [使用 RAPIDS cuML 在 GPU 上做人脸聚类](#使用-rapids-cuml-在-gpu-上做人脸聚类)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [下载体积](#下载体积)
- [依赖](#依赖)
- [各功能的要求](#各功能的要求)
- [排查依赖冲突](#排查依赖冲突)
- [Angular 客户端](#angular-客户端)

## 可修改的 Docker 设置

部署相关的设置都在 `.env` 里（复制 `.env.example` 即可）：

| 键 | 默认值 | 用途 |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | 以读写方式挂载到 `/data/photos` 的宿主机文件夹（这样才能写入 XMP 附属文件） |
| `PORT` | `5000` | 照片库使用的宿主机端口 |
| `FACET_VRAM_PROFILE` | `auto` | `auto`、`legacy`、`8gb`、`16gb`、`24gb`；覆盖 `models.vram_profile` |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | 容器内的数据库路径，保存在 `./data` 绑定挂载上 |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | 配置中的 `auto_retrain` | 个人排序模型的重训练触发条件，面向高频评分的用户 |

`scoring_config.json` 是你的**覆盖文件**。Facet 出厂的取值
在镜像内的 `config/scoring_config.default.json` 里。你的文件只保存
你改过的内容；其余部分沿用出厂值，并随升级而更新。参见
[配置](CONFIGURATION.md#默认值与你的覆盖配置)和
[完整键值参考](CONFIGURATION.md)。

首次运行时，`docker-entrypoint.sh` 会创建 `./facet-config/scoring_config.json`：

- `docker-compose.yml` 把它以 `FACET_CONFIG=/config/scoring_config.json` 绑定挂载，因此
  在查看器中所做的配置更改能在 `docker compose down && up` 之后保留。
- 在 compose 下，它包含一个生成的 `viewer.edition_password`，在
  `docker compose logs facet` 中只打印一次。不带 `FACET_CONFIG` 的普通 `docker run` 会创建一个空的
  覆盖文件，且不生成密码。
- 已存在的文件绝不会被覆盖，它的属主和权限模式也不会被改动。

### 容器内的文件归属

Facet 只会对自己创建的 `scoring_config.json` 执行 `chown` 和 `chmod`。

只有一个例外：如果一个既有配置对容器的 `facet` 用户
（uid 1000）**不可读**，入口脚本会接管它的归属并在 stderr 上说明。
不可读的配置会让你无法进入界面。要保留归属，请改为让它可读：
`chmod o+r facet-config/scoring_config.json`。

在 rootless Podman/Docker 下，你的文件属于一个容器内 `facet` 用户
无法变成的 uid。请让它**在你保留所有权的前提下可被容器用户写入**：

```bash
# 100999 = 容器内 facet 用户（uid 1000）映射到的宿主机 subuid；
# 用容器已创建的文件查出你自己的值：stat -c %u facet-config/.facet_secret
chown "$USER":100999 facet-config/scoring_config.json
chmod 664 facet-config/scoring_config.json
```

这样文件仍属于你、仍可编辑，而 Facet 的写入也会保持这一状态。其他方案：
用 `podman unshare chown` 编辑属于容器的文件，或使用 `--userns=keep-id`（或在 compose 中加
`user:` 覆盖），让容器用户*就是*你。

> **警告 — 从较旧的 compose 文件升级。** 早期版本挂载的是
> `- ./scoring_config.json:/app/scoring_config.json`。随附的 compose 文件已不再
> 这样做。如果你采用新的 compose 文件，请**先把已有配置搬过去**，否则你的权重、
> 类别和查看器密码将不再被读取：
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> 如果你保留了自己那份仍带旧挂载的 `docker-compose.yml`，`./facet-config` 会
> 用那个文件来初始化，就不会丢失任何东西。
>
> 搬过去的配置是旧默认值的完整副本。它照样能用，但你自己的
> 改动很难辨认。运行 `python database.py --compact-config`（在 Docker 中则是
> `docker compose exec facet python database.py --compact-config`），把它精简为
> 只剩你改过的部分。该命令会先做一份 `0600` 权限的备份，并且解析出的配置与之前完全一致。

模型缓存放在具名卷里（`facet-hf-cache`、`facet-torch-cache`、
`facet-insightface`、`facet-pretrained`），重启后依然保留。`docker compose down -v`
会删除它们并强制重新下载。

镜像内置了 `exiftool`，但**不含** darktable。除非你在镜像里加入
`darktable-cli` 可执行文件，否则查看器的 RAW/darktable 配置文件下载功能会保持关闭。

## 自行选择配置档

- `docker-compose.legacy.yml`、`docker-compose.8gb.yml`、`docker-compose.16gb.yml`、
  `docker-compose.24gb.yml` 各自设置 `FACET_VRAM_PROFILE`；GPU 的那几个还会预留
  NVIDIA 设备。
- `docker-compose.gpu.yml` 预留 GPU，并把配置档交给配置文件自身的
  `vram_profile` 决定（默认为 `auto`）。

发布了三个镜像：

| 镜像 | 内容 | 解包后 |
|-------|----------|----------|
| `ghcr.io/ncoevoet/facet:latest` | 精简的 CPU 构建 | 3.34 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda` | CUDA 12.8、RAPIDS cuML、PyTorch `sm_75`-`sm_120`（Turing–Blackwell，含 RTX 50 系列）；`8gb`/`16gb`/`24gb` 的默认镜像 | 13.1 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` | CUDA 12.6、PyTorch `sm_50`-`sm_90`（Maxwell、Pascal、Volta–Hopper）；参见[较旧的 NVIDIA 显卡](#较旧的-nvidia-显卡-maxwell-pascal-volta) | 13.8 GB |

- 两个 CUDA 镜像都内置 `onnxruntime-gpu`（1.26.0，CUDA 12）来取代 `onnxruntime`，因此
  人脸检测运行在 GPU 上。CPU 镜像保留 `onnxruntime`。
- 这三个镜像都只有 `linux/amd64` 版本。在 ARM 上请用 `docker compose build` 本地构建。
- `docker compose build`（或 `up --build`）基于本仓库构建。构建参数：
  `BASE_IMAGE`、`STRIP_TORCH`、`INSTALL_CUML`、`REQUIREMENTS_LOCK`、`ORT_GPU_VERSION`
  （见 `Dockerfile`）。

不使用 Docker 时，请用环境变量或配置键：

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

`auto` 具体采用的阈值见
[配置 › 显存自动检测](CONFIGURATION.md#显存自动检测)。

## 商业安装与受限软件包

`insightface` 和 `pyiqa`（以及仅由它们使用的 `openai-clip`、`facexlib` 和 `onnxruntime`）附带的模型权重采用非商业条款。它们不属于基础安装。它们位于 `faces-insightface` 和 `iqa` 这两个 extra 中，以及 `requirements.restricted.txt`（Docker 另有 `requirements.restricted.lock.txt` 和 `requirements.legacy.restricted.lock.txt`）。

> **不兼容变更。** 单独执行 `pip install -e .` 或 `pip install -r requirements.txt` 不再包含 insightface 和 pyiqa。请使用 `pip install -e .[all]` 或 `pip install -r requirements.txt -r requirements.restricted.txt`。`install.sh` 和默认 Docker 镜像两者都会安装。

| 目标 | 命令 |
|------|------|
| 全部（默认） | `bash install.sh` 或 `pip install -e .[all]` |
| 可用于商业用途 | `bash install.sh --commercial` |
| 商业用途，手动 | `pip install -r requirements.txt`，然后 `pip install -e .[commercial]` 和 `pip install mediapipe==0.10.35 --no-deps` |
| 商业用途，Docker | `docker build --build-arg FACET_LICENSING=commercial .` |

- `pip install -e .[all]` 和 `faces-insightface` extra 安装的是 CPU 版 `onnxruntime`。
  在 CUDA 机器上，请随后执行[用于人脸检测的 ONNX Runtime](#用于人脸检测的-onnx-runtime)
  中的 GPU 命令。`bash install.sh` 和 CUDA 镜像已经替你做了。
- `mediapipe` 必须始终使用 `--no-deps` 安装，否则它自带的 `opencv-contrib-python` 会让
  `cv2` 命名空间被重复安装。`commercial` extra 声明了其运行时依赖（`absl-py`、
  `flatbuffers`）。
- `python-ofiq`（OFIQ 人脸质量绑定）只提供 Linux x86-64 和 macOS arm64 的 wheel。
  在有 wheel 的平台上请手动 `pip install python-ofiq`。

商业安装本身不会切换模式。请在你的覆盖文件中设置：
`{ "licensing": { "mode": "commercial" } }`。Docker 构建参数还会设置
`FACET_LICENSING_MODE=commercial`。`python facet.py --doctor` 会显示当前生效的许可
模式，在商业模式下还会列出扫描实际会加载的组件（YuNet、SFace、Q-ReAlign）。

## 手动安装，不使用 install.sh

需要 Python 3.12（3.10+ 亦可），以及用于构建照片库的 Node.js 20+。

```bash
# 1. 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 先安装 PyTorch，index URL 要与你的 CUDA 版本匹配：
#    cu128 = CUDA 12.8+/13.x，cu126 = 12.6-12.7，cu124 = 12.4-12.5，cu118 = 11.8-12.3。
#    你的显卡同样重要：Maxwell/Pascal/Volta（GTX 900/10 系列、Titan V）需要 cu126，
#    即使配 CUDA 12.8 驱动也一样。检查：`nvidia-smi --query-gpu=compute_cap --format=csv`
#    拿不准？从 https://pytorch.org/get-started/locally/ 复制命令
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. 其余依赖一次性装完，让 pip 解算整张依赖图
pip install -r requirements.txt -r requirements.restricted.txt

# 4. 仅 CUDA，在第 3 步之后：换成 GPU 版 ONNX Runtime（与你的 PyTorch CUDA 构建匹配）
pip uninstall -y onnxruntime onnxruntime-gpu
pip install "onnxruntime-gpu>=1.19.0,<1.27"   # CUDA 12.x 版 PyTorch（cu124、cu126、cu128）
# 仅 CPU，或 CUDA 11.8（cu118）：保留第 3 步装好的版本，或用下面的命令重装
# pip install "onnxruntime>=1.15.0"

# 5. 在第 3、4 步之后：只保留 headless 版 OpenCV（图形界面版需要 libGL.so.1）
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"

# 6. 构建网页照片库
cd client && npm install && npx ng build && cd ..

# 7. 运行
python facet.py /path/to/photos
python viewer.py
```

步骤顺序很重要：共用文件的软件包（`onnxruntime`/`onnxruntime-gpu`、
`opencv-python`/`opencv-python-headless`）由最后安装的那个生效。
`install.sh` 会自动应用显卡下限和两次替换。

验证环境：

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

遇到报错？请看[排查依赖冲突](#排查依赖冲突)。

## install.sh 选项与 Makefile 快捷命令

`install.sh`：

1. 找到一个 Python 3.10+ 并创建 `venv`；
2. 检测操作系统和 GPU（Apple Silicon → Metal，否则用 `nvidia-smi` → 匹配的 CUDA 构建）；
3. 安装 PyTorch、`requirements.txt`、`transformers` 和 `accelerate`；
4. 换上对应的 [ONNX Runtime](#用于人脸检测的-onnx-runtime) 和
   [headless 版 OpenCV](#opencv-headless-版本)；
5. 检查 `exiftool`，构建 Angular 客户端，并验证每一处导入（任何一处失败时以状态码 1 退出）。

| 参数 | 作用 |
|------|--------|
| `--cpu` | 强制使用纯 CPU 的 PyTorch（不带 CUDA） |
| `--cuda VERSION` | 覆盖检测到的 CUDA 版本（例如 `--cuda 12.8`） |
| `--skip-client` | 跳过 Angular 前端构建 |
| `--no-uv` | 使用 pip 而不是 uv |
| `--commercial` | 可用于商业用途的安装：跳过 insightface、pyiqa 和 ONNX Runtime，以 `--no-deps` 安装 mediapipe；需自行将 `licensing.mode` 设为 `commercial` |

| Make 目标 | 执行内容 |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`，自动检测或纯 CPU |
| `make client` | 重新构建 Angular 前端 |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`，CPU 或 NVIDIA |
| `make test` / `make test-cov` | pytest，带或不带覆盖率 |
| `make clean` | 删除 `venv`、`client/dist`、`client/node_modules` |

## exiftool

exiftool 对每种格式都能给出最好的 EXIF 提取效果。没有它时，Facet 会回退到
`exifread`（支持所有 RAW 格式），再回退到 PIL（仅 JPEG/TIFF/DNG）。

| 操作系统 | 命令 |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | 从 [exiftool.org](https://exiftool.org/) 下载 |

## 用于人脸检测的 ONNX Runtime

人脸检测（InsightFace）运行在 ONNX Runtime 上：`onnxruntime`（CPU）或
`onnxruntime-gpu`（CUDA）。两者共用 `onnxruntime/` 目录，因此只能安装一个；pip 最后安装的那个生效。`insightface` 依赖 CPU 版，所以安装它
（`requirements.restricted.txt`、`pip install -e .[all]`、`faces-insightface` extra）
会把 CPU 版带回来。在 CUDA 机器上，请在这些依赖**之后**安装 GPU 包，
并且先把两个名称都卸载。

`bash install.sh` 在 x86_64 上安装 CUDA 12 版 PyTorch 时会替你完成这件事，然后测试一个真实的 CUDA
会话（与 `--doctor` 相同）。重新运行它即可修复被破坏的 `venv`，或在 CPU 与 GPU 之间切换。
CUDA Docker 镜像也是如此。CPU 安装、CUDA 11.8（cu118）、macOS、CPU 镜像和
aarch64（没有适用于 CUDA 12 的 `onnxruntime-gpu` wheel）保留 `onnxruntime`。

手动安装时，请按你的 **PyTorch** CUDA 构建选择对应的一行：

| PyTorch 构建 | 命令 |
|---------------|---------|
| 仅 CPU，或 CUDA 11.8（cu118） | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"` |
| CUDA 12.x（cu124、cu126、cu128） | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"` |

- **按 PyTorch 选，而不是按驱动。** `nvidia-smi` 显示的 CUDA 版本是驱动支持的最新版本；
  CUDA 13 的驱动仍然运行 cu128 版 PyTorch。`python facet.py --doctor`
  会在 `CUDA (compiled)` 一行显示 PyTorch 的构建。
- **保留版本范围。** `onnxruntime-gpu` 的 1.19–1.26 是 CUDA 12 构建；1.27 及以后需要
  CUDA 13 库。不加上限的安装看起来正常，实际却悄悄跑在 CPU 上。对于手动安装的 CUDA
  13 版 PyTorch，对应的是 `"onnxruntime-gpu>=1.27.0"`（未经测试）。
- **CUDA 11.8 没有可用的 GPU 构建。** 适用于 CUDA 11 的旧版 `onnxruntime-gpu` 需要 cuDNN 8，
  而 cu118 版 PyTorch 使用 cuDNN 9。若想用 GPU 做人脸检测，请把驱动更新到报告
  CUDA 12.4 或更新版本的驱动，然后重新运行 `install.sh`。
- **要给版本要求加引号。** 不加引号时，`pip install onnxruntime-gpu>=1.19.0,<1.27` 会创建一个名为
  `=1.19.0,` 的空文件，并以 `1.27: No such file or directory` 失败。请删除那个文件。
- **两个名称都要卸载。** 先 `pip uninstall onnxruntime` 再 `pip install onnxruntime-gpu`
  会让 `import onnxruntime` 只剩一个空包，InsightFace 会报错
  `module 'onnxruntime' has no attribute 'InferenceSession'`。

替换之后，`pip check` 会报告 "insightface ... requires onnxruntime, which is not
installed"（`uv pip check`："The package `insightface` requires `onnxruntime`, but it's not
installed"）。这无害：`onnxruntime-gpu` 提供的是同一个模块。同样，在
OpenCV 替换之后，`insightface` 和 `facexlib` 需要 `opencv-python` 的提示也无害。之后执行
`pip install -r requirements.txt` 会把带图形界面的 OpenCV 装回来；请重做
[OpenCV 替换](#opencv-headless-版本)，或重新运行 `install.sh`。

**检查结果：** `python facet.py --doctor` 的 **ONNX Runtime** 一节会列出包、
版本和执行提供程序，并在两个包同时安装或导入失败时给出警告（附修复方法）。在 CUDA 上它会运行一个测试会话；只有该会话确实运行在 `CUDAExecutionProvider` 上时，`CUDA session` 一行才是 OK。该测试需要 `onnx` 包，在 CPU 上和商业模式下会被跳过。在 CUDA 上扫描时，若 InsightFace 运行在 CPU 上，也会警告一次。

在 Docker 中，容器内的修复会在下一次 `docker run` 时丢失：请拉取最新
镜像或重新构建。CUDA 镜像通过 `ORT_GPU_VERSION`
构建参数内置 `onnxruntime-gpu` 1.26.0；切勿设成 1.27 及更高版本（CUDA 13）。

## OpenCV headless 版本

`opencv-python`（带图形界面）和 `opencv-python-headless` 共用 `cv2/` 目录；最后安装的那个生效。Facet 的依赖会把两者都带进来。图形界面版需要 `libGL.so.1`，而
Debian、WSL 和精简主机没有它，于是 `import cv2` 会失败，报
`ImportError: libGL.so.1: cannot open shared object file`。Facet 不打开任何 OpenCV 窗口，
所以 headless 版就够用了。

`bash install.sh` 在所有模式（包括 `--commercial`）下都只保留 headless 版。
Docker 镜像不受影响（它们安装了 `libgl1`）。要手动修复 `venv`，
请把 `<version>` 换成 `pip list` 为这两个包之一显示的版本：

```bash
pip uninstall -y opencv-python opencv-python-headless && pip install --no-deps "opencv-python-headless==<version>"
```

`python facet.py --doctor` 的 **OpenCV** 一节在 `cv2` 能导入时显示 `[OK]`，否则显示
导入错误，以及已填入你版本的修复命令。两个包都已安装但导入正常也没问题
（Docker 镜像同时包含两者，并带有 `libgl1`）。如果 `cv2` 之类的核心导入失败，
`install.sh` 会打印 "Installation finished with errors" 并以
状态码 1 退出。

## 使用 RAPIDS cuML 在 GPU 上做人脸聚类

对于大型人脸数据库（8 万张人脸以上），cuML 能显著加快聚类速度。它需要 conda：

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# 或：pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
# requirements.txt 会安装 opencv-python，即带图形界面的版本（需要 libGL.so.1）：只保留 headless 版
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"
```

安装了 cuML 后，聚类会自动使用 GPU（`scoring_config.json` 中的
`face_clustering.use_gpu`）。CUDA Docker 镜像已内置它，因此 `8gb`/`16gb`/`24gb` 容器
在 GPU 上聚类。`legacy` 始终在处理器上聚类。

## Apple Silicon (Metal/MPS)

不需要额外的 GPU 软件包。用 `bash install.sh` 安装，然后确认
`python facet.py --doctor` 报告 `Facet runtime device: mps`。对于不受支持的算子，
Facet 会启用 PyTorch 的 CPU 回退。想做对比：

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

- `FACET_DEVICE=cpu` 关闭加速；`FACET_DEVICE=mps` 则强制要求使用它，不可用时会报错。
  当 PyTorch 看不到任何 CUDA 设备时（例如 `CUDA_VISIBLE_DEVICES=''`），
  `FACET_DEVICE=cuda` 也会以同样方式报错。
- InsightFace 仍留在处理器上（它是 ONNX Runtime 模型）。
- TOPIQ 的分数可能与 CPU/CUDA 略有差异。在 MPS 上，任一边不是 32 的倍数的照片
  会先居中裁切（1024×682 变成 1024×672）。

`vram_profile: "auto"` 按统一内存总量选定配置档：

| 统一内存总量 | `auto` 选定的配置档 |
|----------------------|----------------------------|
| 低于 16GB | `legacy` |
| 16-31GB | `8gb` |
| 32-47GB | `16gb` |
| 48GB 及以上 | `24gb` |

每档阈值大约是配置档模型占用量的两倍，因为 macOS 和其他应用
共享这部分内存。开始交换内存的 Mac 比使用较小配置档的 Mac 更慢。显式
设置的配置档始终按你写的执行。

### Mac 上的内存

如果活动监视器显示 Facet 占用的内存超过了 Mac 本身的内存，或者扫描过程中交换内存
持续增长，请按顺序尝试以下方法。

**1. 限制 PyTorch 的内存池：**

```bash
PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.0 python facet.py /path/to/photos
```

`1.0` 表示"Mac 推荐的工作集大小，不多不少"。这样一来，某个处理阶段可能会以"内存不足"
停止，而不是继续交换内存，这比让 Mac 陷入卡顿要好。

**权重逐个加载。** 在 macOS 上，Facet 默认设置 `HF_DEACTIVATE_ASYNC_LOAD=1`，
因为并发加载可能导致 MPS 上的扫描崩溃。无需任何配置；自行设置
`HF_DEACTIVATE_ASYNC_LOAD=0` 即可恢复并发加载。

**2. 关闭两个最耗资源的可选模型。** 只需在
`scoring_config.json` 中添加这些键：

```json
{
  "models": { "profiles": { "16gb": { "saliency_enabled": false } } },
  "iqa_extended": { "qrealign": false }
}
```

`saliency_enabled` 关闭主体检测；`qrealign` 关闭一个额外的图像质量
模型。美感、构图、人脸和技术质量仍会照常评分。请使用你的
Mac 对应的配置档键名：32-47GB 用 `"16gb"`，48GB 及以上用 `"24gb"`。

**3. 每次处理更少的照片：**

```json
{ "processing": { "ram_chunk_size": 4,
                  "auto_tuning": { "min_ram_chunk_size": 4, "max_ram_chunk_size": 4 } } }
```

三个键都要设置，否则自动调优会在 `min_ram_chunk_size` 与
`max_ram_chunk_size` 之间调整该值。

## 下载体积

模型在首次使用时下载到：

- `~/.cache/huggingface/`（Hugging Face 模型）
- `~/.cache/torch/hub/`（PyIQA 权重）
- `~/.insightface/`（人脸检测/识别）
- 仓库根目录下的 `pretrained_models/`：`samp_net.pth`、`u2netp.pth`、
  `face_landmarker.task`，以及 `aesthetic_predictor_weights.pth`（仅 `legacy`/`8gb`）

在 Docker 中这些都是具名卷（`pretrained_models/` 对应 `facet-pretrained`），所以重建容器时
不会重新下载。镜像中没有烘焙任何模型权重。

下面的体积按十进制计（GB = 10⁹ 字节，MB = 10⁶ 字节）。

| 模型 | 体积 | 配置档 |
|-------|------|----------|
| CLIP ViT-L-14 laion2b（嵌入向量 + CLIP 标签 + CLIP-MLP 美学评分） | 1.711 GB | `legacy`/`8gb` |
| 美学 MLP 头（`sac+logos+ava1-l14-linearMSE.pth`） | 3.7 MB | 仅 `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M（嵌入向量） | 4.581 GB | `16gb`/`24gb` |
| Qwen3.5-2B（VLM 标签） | 4.571 GB | `16gb` |
| Qwen3.5-4B（VLM 标签） | 9.343 GB | `24gb` |
| Qwen2-VL-2B（构图） | 4.430 GB | 默认不使用；见注 1 |
| InsightFace buffalo_l（人脸） | 下载 289 MB / 磁盘 630 MB（zip 包会与解压出的 `.onnx` 文件一同保留） | 全部 |
| SAMP-Net 权重（构图） | 183 MB | 全部 |
| U2-Net-P（SAMP-Net 的显著性子模型） | 4.7 MB | 与 SAMP-Net 相同 |
| BiRefNet_dynamic（主体显著性） | 445 MB | 全部 |
| TOPIQ NR（美学模型） | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA（补充美学评分） | 873 MB | 全部 |
| TOPIQ NR-Face（补充人脸画质） | 376 MB | 全部 |
| LIQE（补充画质/失真诊断） | 708 MB | 全部 |
| timm resnet50.a1_in1k（PyIQA 共用骨干网络） | 102 MB | 全部 |
| Q-ReAlign-Mini-0.8B（`iqa_extended.qrealign`） | 2.235 GB | `8gb`/`16gb`/`24gb`，**默认开启**（`"auto"`） |

1. 只有当你设置 `composition_model: "qwen2-vl-2b"` **并且**
   `processing.mode: "single-pass"` 时才会加载 Qwen2-VL-2B，它会取代 SAMP-Net/U2-Net-P。在非商业模式下，
   这只在 `legacy`/`8gb` 上可行：在 `16gb`/`24gb` 上单阶段会回退到多阶段，
   而多阶段没有 Qwen2-VL 阶段。

各配置档的下载总量：`legacy` 4.69 GB · `8gb` 6.93 GB · `16gb` 14.55 GB ·
`24gb` 19.32 GB · `24gb` 搭配 Qwen2-VL 构图为 23.56 GB（仅限商业模式，见注 1）。

Docker 镜像本身（尚未下载任何模型时）解包后：`latest` 为 3.34 GB、
`latest-cuda` 为 13.1 GB、`latest-cuda-legacy` 为 13.8 GB
（[部署 › 镜像大小](DEPLOYMENT.md#镜像大小)）。压缩后的下载体积尚未
测量。

未计入上述总量的可选模型：

| 模型 | 体积 | 触发条件 |
|-------|------|---------|
| DeQA-Score-Mix3（`iqa_extended.deqa`） | 16.41 GB | 默认关闭 |
| SigLIP so400m-patch14-384 骨干网络（`iqa_extended.aesthetic_v25`） | 3.515 GB | 默认关闭，且**已弃用**（建议改用 `qrealign`） |
| Helsinki-NLP OPUS-MT，按目标语言各一份（照片描述翻译） | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | 仅限你启用的语言 |
| MediaPipe `face_landmarker.task` | 3.76 MB | 仅当安装了 `mediapipe` 时 |

`reverse_geocoder` 无需下载；它的数据随 wheel 一起分发。

SAMP-Net 权重来自
[model-weights-v1 发布](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth)。
如果你看到 `Failed to download SAMP-Net weights: HTTP Error 404: Not Found`（离线或
网络受限），请下载该文件并放到 `pretrained_models/samp_net.pth`。

## 依赖

### 必需的软件包

| 软件包 | 用途 |
|---------|---------|
| `torch`、`torchvision` | 深度学习框架（单独安装，见上文） |
| `open-clip-torch` | CLIP 嵌入向量/标签（legacy/8gb 配置档） |
| `pyiqa` | TOPIQ 及其他画质/美学模型 |
| `opencv-python` | 图像处理 |
| `pillow` | 图像加载，包括 PNG/GIF/WebP/BMP/TIFF/AVIF（AVIF 需要 pillow>=11.3） |
| `imagehash` | 用于连拍检测的感知哈希 |
| `rawpy` | RAW 文件支持 |
| `fastapi`、`uvicorn` | API 服务器 |
| `pyjwt` | JWT 认证 |
| `numpy` | 数值运算 |
| `tqdm` | 进度条 |
| `exifread` | EXIF 元数据提取 |
| `insightface` | 人脸检测与识别 |
| `transformers`、`accelerate` | SigLIP/BiRefNet/VLM 模型（8gb 及以上配置档） |
| `scipy` | 科学计算 |
| `hdbscan` | 人脸聚类（会一并带入 scikit-learn） |
| `reverse_geocoder` | 针对 GPS 的反向地理编码 |
| `psutil` | 批处理自动调优（系统监控） |
| `aiosqlite` | 供 FastAPI 读取端点使用的异步 SQLite |
| `sqlite-vec` | 磁盘上的语义搜索（缺失时回退到内存中的 NumPy 缓存）；`pip install -e .[vec]` |
| `tifffile`、`imagecodecs` | JPEG XL 照片及 Lightroom Classic 13+ 合并 DNG（HDR/全景/增强）的预览 |

以上全部都在 `requirements.txt` 里，除了 `pyiqa` 和 `insightface`，它们在 `requirements.restricted.txt` 中（参见[商业安装与受限软件包](#商业安装与受限软件包)）。没有哪个配置档需要额外的基础软件包。

### 可选的软件包

每一个都能解锁一项功能；没有它时，该功能会被跳过，或者改用回退方案。

| 软件包 | 解锁的功能 | 没有它时 |
|---------|----------|-----------|
| `watchdog` | 监视模式（`--watch`）；**不在 `requirements.txt` 中**，请用 `pip install .[watch]` 安装 | `--watch` 不可用 |
| `pillow-heif` | HEIF/HEIC 解码 | 跳过 HEIF/HEIC 文件 |
| `rawpy` | RAW 解码（CR2/CR3/NEF/ARW/……），已包含在 `requirements.txt` 中 | 跳过 RAW 文件 |
| `cuml`、`cupy` | GPU 人脸聚类（conda + CUDA） | 聚类通过 `hdbscan` 在 CPU 上运行（默认） |
| `onnxruntime-gpu` | GPU 人脸检测，**替换** `onnxruntime`（[详情](#用于人脸检测的-onnx-runtime)） | 使用 CPU 版 `onnxruntime`（较慢） |
| `aesthetic-predictor-v2-5` | `aesthetic_v25` 评分器（`pip install -e .[iqa-extended]`，`iqa_extended.aesthetic_v25`，默认关闭）。**已弃用**（AGPL-3.0，自 2024-12-18 起无人维护）；建议改用 `qrealign`，它不需要额外软件包 | `aesthetic_v25` 不可用 |
| `darktable-cli`（系统） | 从查看器导出 RAW/darktable 配置文件 | 只提供原图/内嵌图下载 |
| `exiftool`（系统） | 最佳的 EXIF/GPS 提取 | 回退到 `exifread`，再回退到 PIL |

## 各功能的要求

Facet 的大部分功能在哪里都能跑（CPU、任意配置档）。少数功能需要 GPU、更高的**显存
配置档**、某个可选软件包，或查看器的**编辑密码** / **超级管理员**
角色。文档中使用的标记：
`[GPU]` · `[16gb/24gb]`（显存配置档）· `[Edition]` · `[Superadmin]` · `[Optional: pkg]`。

| 功能 | GPU | 配置档 | 权限 | 可选软件包 |
|---------|:---:|---------|:----:|------------------|
| 评分/扫描（基础） | 可选 | 任意（`legacy` = CPU） | — | — |
| TOPIQ 美学评分 | 是 | `16gb`/`24gb` | — | — |
| 补充 IQA（TOPIQ IAA、NR-Face、LIQE） | 可选 | 任意（`legacy` = CPU） | — | — |
| SigLIP 2 嵌入向量 | 是 | `16gb`/`24gb` | — | — |
| VLM 标签（Qwen3.5） | 是 | `16gb`/`24gb` | — | — |
| 构图模式（SAMP-Net） | 可选 | 任意（`legacy` = CPU） | — | — |
| 主体显著性（BiRefNet） | 可选 | 任意（`legacy` = CPU） | — | — |
| AI 照片描述（生成/查看） | 是 | `16gb`/`24gb` | 编辑模式 (生成) | — |
| AI 照片描述（编辑） | 是 | `16gb`/`24gb` | 编辑模式 | — |
| VLM 点评 | 是 | `16gb`/`24gb` | 编辑模式 (生成) | — |
| 人脸检测/提取（InsightFace） | 推荐（CPU 也行，但慢） | 任意 | — | — |
| 人脸聚类（HDBSCAN） | 否（CPU） | 任意 | — | `cuml`/`cupy`（可选的 GPU 加速） |
| 语义搜索 | 否 | 任意 | — | `sqlite-vec`（可回退到 NumPy） |
| RAW / HEIF 解码 | 否 | 任意 | — | `rawpy` / `pillow-heif` |
| 监视模式（`--watch`） | 否 | 任意 | — | `watchdog` |
| GPS 提取 / darktable 导出 | 否 | 任意 | — | `exiftool` / `darktable-cli` |
| 星级、收藏、人脸与人物编辑、选片 | 否 | 任意 | 编辑模式 | — |
| 从网页界面触发扫描 | 否 | 任意 | 编辑（单用户）/ 超级管理员（多用户） | — |
| 多用户（按用户区分的星级与角色） | 否 | 任意 | 按角色 | — |

编辑密码和用户角色在 `scoring_config.json` 中配置；参见
[配置](CONFIGURATION.md)。

> 本地没有 GPU？用 `scoring_config.json` 里的 `vlm_backend` 把 VLM 标签、照片描述和
> 点评指向远程的 Ollama 或兼容 OpenAI 的服务器。这样这些功能在
> `legacy`/`8gb` 配置档上也能用。

## 排查依赖冲突

Facet 的机器学习软件包（`torch`、`open-clip-torch`、`insightface` 等）会带入大量
依赖，逐个安装它们可能会互相破坏。

**症状：** 每次安装都会提示还需要另一个包；`torch`、`numpy`、`huggingface-hub` 或
`open-clip-torch` 之间出现版本冲突；`pip install` 成功了，但
`import` 失败。

**1. 一次性全部安装：** `pip install -r requirements.txt`，让 pip 解算
完整的依赖图。不要逐个安装
（`pip install open-clip-torch && pip install insightface && ...`）。

**2. 使用 [uv](https://docs.astral.sh/uv/)：** `uv` 会在安装之前先解算完整的依赖图：

```bash
pip install uv
uv pip install -r requirements.txt
# 为 PyTorch 加上 CUDA 索引：
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. 推倒重来：** 执行 `deactivate`、`rm -rf venv`，然后重做
[手动安装](#手动安装不使用-installsh)（或重新运行 `install.sh`）。

### GPU 检测问题

如果你的 GPU 没有被检测到（较新的显卡上比较常见），运行：

```bash
python facet.py --doctor
```

它会检查 PyTorch 的 CUDA 支持与驱动，并给出正确的 pip 命令。它还能捕获 `torch.cuda.is_available()` 发现不了的情况：已安装的 PyTorch 没有为该 GPU 提供内核（例如在 CUDA 12.8 之前的构建上使用 RTX 50 系列）。这时 Facet 会回退到 CPU 而不是崩溃，`--doctor` 会指出
修复办法：在 Docker 中是对应的镜像标签（Maxwell/Pascal/Volta 显卡用
`ghcr.io/ncoevoet/facet:latest-cuda-legacy`）；裸机上则是正确的 `--index-url`。

要模拟硬件来做测试：

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Angular 客户端

只有开发或自定义构建时才需要；`install.sh` 和 Docker 镜像已经帮你构建好了。

```bash
cd client
npm install
npm run build    # 生产构建 → client/dist/
npm start        # 开发服务器，运行在 http://localhost:4200（把 API 代理到 :5000）
```

> **`npm audit` 警告：** 多数问题都在构建期的开发依赖里，永远不会进入浏览器。
> 运行 `npm audit fix` 之前请先审阅清单，它可能会降级或移除某些软件包。
