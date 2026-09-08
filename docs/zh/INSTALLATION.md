# 安装

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md) · **简体中文**

Facet 在你自己的机器上运行。挑选与你的情况相符的章节，复制其中的命令块，
就完成了。底部的[进阶](#进阶)部分只在你确实需要时才用得上。

## 我该选哪种安装方式？

| 你的情况 | 前往 |
|----------------|-------|
| Windows、macOS 或 Linux，只想让它跑起来 | [使用 Docker 安装](#使用-docker-安装) |
| Linux 或 macOS，且不想用容器 | [不使用 Docker 安装](#不使用-docker-安装) |
| NAS，或一台希望从其他机器访问的服务器 | [部署](DEPLOYMENT.md) |

## 哪种配置档适合我的硬件？

Facet 提供四种*配置档*。配置档就是一组按你机器规格挑选的 AI 模型 —— 安装时选定
一个，之后随时可以更换。

| 你的硬件 | 配置档 | 你会得到什么 |
|---------------|---------|--------------|
| 没有显卡 | `legacy` | 所有功能都可用 —— 评分、人脸、标签、选片、照片库 —— 只是慢一些。 |
| NVIDIA 显卡，6–14 GB | `8gb` | 与 `legacy` 相同的模型，只是跑在显卡而不是处理器上。 |
| NVIDIA 显卡，14–20 GB | `16gb` | 最强的照片评分，外加由机器撰写的 AI 标签和照片描述。 |
| NVIDIA 显卡，20 GB 或更多 | `24gb` | 最大的模型，外加对照片构图的文字解读。 |
| Apple Silicon Mac（M1–M4） | 自动为你选择 | Facet 使用 Mac 的图形核心，并按你的内存容量选定配置档。 |

不确定自己的显卡有多少显存？那就跳过这一步 —— 下面的*自动检测*命令块会替你判断。

## 使用 Docker 安装

你需要 [Docker](https://docs.docker.com/get-started/get-docker/)。如果你的机器装有
NVIDIA 显卡，还需要
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)，
Docker 才能访问显卡 —— 在 Windows 上，这意味着要在 WSL2 里运行 Facet
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

上面的 8 GB、16 GB 和 24 GB 命令块，以及通用的 `docker-compose.gpu.yml` 叠加文件，
拉取的都是 `ghcr.io/ncoevoet/facet:latest-cuda`，其 PyTorch 构建覆盖
`sm_75`-`sm_120` —— 从 Turing 到 Blackwell。Maxwell、Pascal（GTX 900/10 系列）或
Volta（例如 Titan V）显卡必须改用另一个 CUDA 镜像：在执行 `docker compose up -d`
之前，把你上面用到的 compose 文件（`docker-compose.8gb.yml`、`.16gb.yml`、
`.24gb.yml` 或 `.gpu.yml`）中的 `image:` 行由
`ghcr.io/ncoevoet/facet:latest-cuda` 改为 `ghcr.io/ncoevoet/facet:latest-cuda-legacy`
（`sm_50`-`sm_90`，Maxwell 到 Hopper）。不要把这个镜像标签与
`docker-compose.legacy.yml` 混为一谈：后者选择的是纯 CPU 的 `legacy`
**显存配置档**，与上面的 `-cuda-legacy` **架构**标签毫无关系。比 Maxwell 更旧的
显卡（Kepler、Fermi —— `sm_50` 正是 legacy 镜像自身的下限）没有受支持的 CUDA
镜像；请改用 CPU 上的 `legacy` 显存配置档 —— 也就是上面的
[「没有显卡」](#没有显卡)命令块。

### 日常命令

在你给照片评分之前，照片库都是空的。在 Docker 内部，你的照片文件夹一律叫
`/data/photos`，不管它在你机器上叫什么名字：

```bash
docker compose exec facet python facet.py /data/photos   # 给照片评分
docker compose logs -f                                   # 查看它正在做什么
docker compose down                                      # 停止运行
```

想稍后再次启动，重新执行你上面用过的那一行 `docker compose … up -d` 即可。

## 不使用 Docker 安装

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` 会找到你的显卡，安装与之匹配的一切，并构建网页照片库。之后每次使用
Facet 时：

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

在 Apple Silicon Mac 上，这会自动使用 Mac 的图形核心。之后每次使用 Facet 时：

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # 给照片评分
python viewer.py                       # 启动照片库
```

打开 <http://localhost:5000>。

> **5000 端口已被占用？** macOS 用它来跑 AirPlay。改用
> `python viewer.py --port 5001` 启动照片库，然后打开 <http://localhost:5001>。

### Windows

请使用 [Docker](#使用-docker-安装)。要在 Windows 上使用 NVIDIA 显卡，请按
[WSL2 指南](DEPLOYMENT.md#windowswsl2搭配-nvidia-gpu)操作 —— 那是经过验证的路径。

## 首次运行会遇到什么

- **一次下载。** 首次扫描会拉取你所选配置档的 AI 模型 —— `legacy` 约 4.7 GB、
  `8gb` 约 6.9 GB、`16gb` 约 14.6 GB、`24gb` 约 19.1 GB（完整明细见
  [下载体积](#下载体积)）。这只发生一次，之后的运行会立即开始。
- **无需设置。** 没有任何东西需要配置。Facet 会在首次扫描时创建数据库，并自带
  一套可用的设置。
- **你的照片不会被修改。** 扫描只读取照片，结果写入 Facet 自己的数据库。把星级和
  关键词写回文件是另一项需要你主动开启的操作（[互操作](INTEROP.md)）。
- **时间。** 首次扫描大型照片库需要一段时间，而且在处理器上明显比在显卡上慢。
  进度会实时打印，扫描期间你也可以浏览照片库。

## 确认安装成功

```bash
python facet.py --doctor                             # 不使用 Docker 时
docker compose exec facet python facet.py --doctor   # 使用 Docker 时
```

这会打印 Facet 找到的东西：你的显卡、它选定的配置档，以及任何缺失项。如果照片库
正在运行，<http://localhost:5000/health> 会回答 `ok`。

有什么不正常？请看下面的[排查依赖冲突](#排查依赖冲突)和
[GPU 检测问题](#gpu-检测问题)。

---

# 进阶

从这里往后的内容都是可选的：安装过程究竟做了什么、如何修改它，以及完整的依赖
参考。

- [可修改的 Docker 设置](#可修改的-docker-设置)
- [自行选择配置档](#自行选择配置档)
- [手动安装，不使用 install.sh](#手动安装不使用-installsh)
- [install.sh 选项与 Makefile 快捷命令](#installsh-选项与-makefile-快捷命令)
- [exiftool](#exiftool)
- [用于人脸检测的 ONNX Runtime](#用于人脸检测的-onnx-runtime)
- [使用 RAPIDS cuML 在 GPU 上做人脸聚类](#使用-rapids-cuml-在-gpu-上做人脸聚类)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [下载体积](#下载体积)
- [依赖](#依赖)
- [各功能的要求](#各功能的要求)
- [排查依赖冲突](#排查依赖冲突)
- [Angular 客户端](#angular-客户端)

## 可修改的 Docker 设置

部署相关的开关都在 `.env` 里（复制 `.env.example` 即可）：

| 键 | 默认值 | 用途 |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | 以读写方式挂载到 `/data/photos` 的宿主机文件夹（必须可写，XMP 附属文件才能写到原文件旁边） |
| `PORT` | `5000` | 照片库使用的宿主机端口 |
| `FACET_VRAM_PROFILE` | `auto` | `auto`、`legacy`、`8gb`、`16gb`、`24gb` —— 覆盖 `models.vram_profile`，无需编辑任何 JSON |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | 容器内的数据库路径，保存在 `./data` 绑定挂载上 |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | 配置中的 `auto_retrain` | 个人排序模型的重训练触发条件，面向高频评分的用户 |

`scoring_config.json` 是你的**覆盖文件**，而不是整份配置。Facet 出厂的每一个取值
都在镜像内的 `config/scoring_config.default.json` 里，你的文件叠加在它之上解析
—— 所以它只需要保存你真正改过的那几项设置；凡是你没写的都会沿用出厂值
（升级时还会自动获得对这些默认值的改进）。

因此 `docker-entrypoint.sh` 会在首次运行时，用一个空的 `{}` 初始化持久化的
`./facet-config/scoring_config.json`。该文件由 `docker-compose.yml` 绑定挂载
（在容器内为 `FACET_CONFIG=/config/scoring_config.json`），因此容器无需你在宿主机
上做任何准备就能运行，而且运行期间写入的每一项配置（照片库密码升级、权重、
优先级、拍摄场景评分方案）都能在 `docker compose down && up` 之后保留下来。
你可以直接编辑它来手工调整权重、照片库密码或类别 —— 该写些什么见
[配置](CONFIGURATION.md#默认值与你的覆盖配置)，可用的键的完整清单见
[完整键值参考](CONFIGURATION.md)。已存在的文件绝不会被覆盖 —— 它的属主和权限
模式也不会被改动。Facet 只会对自己创建的配置文件重新设置权限和属主。

### 容器内的文件归属

Facet 只会对自己创建的 `scoring_config.json` 执行 `chown` 和 `chmod` —— 已存在的
文件会一直保留你给它的属主和权限模式。唯一的例外：如果一个既有配置对容器的
`facet` 用户（uid 1000）**不可读**，入口脚本仍会接管它的归属并在 stderr 上说明
原因，因为不可读的配置会锁死每一条路由，让你无从进入界面修复。更好的做法是把
文件改为可读 —— `chmod o+r facet-config/scoring_config.json` —— 这样下次启动时
Facet 就不会去动它。

Facet 自己的配置写入（权重、类别优先级、拍摄场景评分方案、照片库密码升级……）
同样会尽量保留文件的属主和权限模式，在无法直接接管目标文件属主时改为原地重写。
在普通的 rootless Podman/Docker 环境下，仅有这一点还不够，因为你的文件属于一个
容器内 `facet` 用户无法变成的 uid —— 你还需要让它**在不放弃你自己所有权的前提下
可被容器用户写入**：

```bash
# 100999 = 容器内 facet 用户（uid 1000）映射到的宿主机 subuid；
# 用容器已创建的文件查出你自己的值：stat -c %u facet-config/.facet_secret
chown "$USER":100999 facet-config/scoring_config.json
chmod 664 facet-config/scoring_config.json
```

这样文件仍属于你、仍可编辑，而 Facet 的写入也会保持这一状态。其他方案：用
`podman unshare chown` 原地编辑属于容器的文件，或使用 `--userns=keep-id`
（或在 compose 中加 `user:` 覆盖），让容器用户*就是*你。

> **正从此项变更之前的版本升级？** 早期版本告诉你把默认配置文件复制成
> `scoring_config.json`，并在 `docker-compose.yml` 中取消注释一行
> `- ./scoring_config.json:/app/scoring_config.json`。该挂载已从随附的 compose
> 文件中移除。如果你采用新的 compose 文件，请**先把已有配置搬过去**：
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> 否则入口脚本会初始化一个空的覆盖文件，而你的权重、类别和**照片库密码就会被
> 悄悄地不再读取** —— 而空的 `viewer.edition_password` 会彻底关闭编辑模式的
> 访问控制。如果你保留了自己那份仍带旧挂载的 `docker-compose.yml`，入口脚本会
> 用*那个*文件来初始化 `./facet-config`，就不会丢失任何东西。
>
> 搬过去的配置是旧的随附文件的完整副本。它照样能用 —— 一份完整配置解析后就是
> 它自己 —— 但你自己的改动在其中无从辨认。运行
> `python database.py --compact-config`（在 Docker 中则是
> `docker compose exec facet python database.py --compact-config`），可以把它精简
> 为只剩你改过的部分。该命令会先做一份 `0600` 权限的备份，并且是无损的：处理后
> 文件解析出的配置与之前完全一致。

模型缓存放在 Docker 管理的具名卷里（`facet-hf-cache`、`facet-torch-cache`、
`facet-insightface`、`facet-pretrained`），因此镜像永远不会读取你机器上自己的缓存，
模型也能在重启后保留。`docker compose down -v` 会删除它们并强制重新下载。

镜像内置了 `exiftool`，但**不含** darktable，所以照片库中可选的
RAW/darktable 配置文件下载功能会保持不可用，除非你自行在镜像里加入
`darktable-cli` 可执行文件。其余功能不受影响。

## 自行选择配置档

各配置档专用的文件（`docker-compose.legacy.yml`、`docker-compose.8gb.yml`、
`docker-compose.16gb.yml`、`docker-compose.24gb.yml`）各自设置
`FACET_VRAM_PROFILE`，并且在 GPU 配置档中预留 NVIDIA 设备。
`docker-compose.gpu.yml` 是通用的替代方案：它只预留 GPU，把配置档交给配置文件
自身的 `vram_profile` 决定（默认为 `auto`）。

同一份 `Dockerfile` 发布了三个镜像：`ghcr.io/ncoevoet/facet:latest` 是精简的 CPU
构建（解包后占用磁盘 3.34 GB，见[下载体积](#下载体积)）。
`ghcr.io/ncoevoet/facet:latest-cuda` 带有 CUDA 12.8、RAPIDS cuML 以及 PyTorch 的
`sm_75`-`sm_120` 构建 —— 从 Turing 到 Blackwell，含 RTX 50 系列（解包后
13.1 GB）—— 也是 `8gb`/`16gb`/`24gb` compose 文件默认拉取的镜像。
`ghcr.io/ncoevoet/facet:latest-cuda-legacy` 带有 CUDA 12.6 和 PyTorch 的
`sm_50`-`sm_90` 构建 —— Maxwell、Pascal（GTX 900/10 系列）以及从 Volta 到 Hopper
（解包后 13.8 GB）—— 面向 `latest-cuda` 不再覆盖的显卡；见上面的
[较旧的 NVIDIA 显卡](#较旧的-nvidia-显卡-maxwell-pascal-volta)。这三个镜像都只有
`linux/amd64` 版本 —— 在 ARM 机器上请改用 `docker compose build` 本地构建，而不是
拉取。`docker compose build`（或 `up --build`）始终基于本仓库构建；相关的
`BASE_IMAGE`、`STRIP_TORCH`、`INSTALL_CUML` 和 `REQUIREMENTS_LOCK` 构建参数见
`Dockerfile`。

不使用 Docker 时，同样的选择由一个环境变量或一个配置键完成：

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

`auto` 具体采用的阈值见
[配置 › 显存自动检测](CONFIGURATION.md#显存自动检测)。

## 手动安装，不使用 install.sh

需要 Python 3.12（3.10+ 亦可），以及用于构建照片库的 Node.js 20+。

```bash
# 1. 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 先安装 PyTorch，index URL 要与你的 CUDA 版本匹配。
#    cu128 面向 CUDA 12.8+/13.x；CUDA 12.6-12.7 用 cu126，CUDA 12.4-12.5 用 cu124，
#    CUDA 11.8-12.3 用 cu118。
#    重要的不只是驱动，还有你的显卡：cu128 不提供 sm_75 以下的内核，
#    因此 Maxwell、Pascal 或 Volta 显卡（GTX 900/10 系列、Titan V）
#    即使配 CUDA 12.8 驱动也必须用 cu126。install.sh 会自动应用这个下限；
#    用 `nvidia-smi --query-gpu=compute_cap --format=csv` 查看你自己的算力。
#    拿不准时，就从 https://pytorch.org/get-started/locally/ 复制命令。
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. 其余依赖一次性装完，让 pip 能一次性解算整张依赖图。
#    requirements.txt 已经包含 transformers 和 accelerate，8gb 及以上配置档
#    使用的 SigLIP/BiRefNet/VLM 模型需要它们。
pip install -r requirements.txt

# 4. 只安装一个用于人脸检测的 ONNX Runtime（见下表）
pip install onnxruntime-gpu>=1.17.0   # 或：pip install onnxruntime>=1.15.0

# 5. 构建网页照片库
cd client && npm install && npx ng build && cd ..

# 6. 运行
python facet.py /path/to/photos
python viewer.py
```

用一行命令验证环境：

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

遇到报错？请看[排查依赖冲突](#排查依赖冲突)。

## install.sh 选项与 Makefile 快捷命令

`install.sh` 会定位一个 Python 3.10+，创建 `venv`，检测操作系统和 GPU（Apple
Silicon → Metal，否则用 `nvidia-smi` → 匹配的 CUDA 构建），安装 PyTorch、对应的
ONNX Runtime、`requirements.txt`、`transformers` 和 `accelerate`，检查
`exiftool`，构建 Angular 客户端，并验证每一处导入。

| 参数 | 作用 |
|------|--------|
| `--cpu` | 强制使用纯 CPU 的 PyTorch（不带 CUDA） |
| `--cuda VERSION` | 覆盖检测到的 CUDA 版本（例如 `--cuda 12.8`） |
| `--skip-client` | 跳过 Angular 前端构建 |
| `--no-uv` | 使用 pip 而不是 uv |

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
`exifread`（一个支持所有 RAW 格式的 Python 库），再回退到 PIL（仅
JPEG/TIFF/DNG）。

| 操作系统 | 命令 |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | 从 [exiftool.org](https://exiftool.org/) 下载 |

## 用于人脸检测的 ONNX Runtime

人脸检测（InsightFace）运行在 ONNX Runtime 上，它有 CPU 和 GPU 两种版本。
请只安装其中一个：

| 环境 | 命令 |
|--------|---------|
| 仅 CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

用 `nvidia-smi` 查看你的 CUDA 版本 —— 它印在右上角。要把已有的安装从 CPU 版
切换到 GPU 版：

```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

## 使用 RAPIDS cuML 在 GPU 上做人脸聚类

对于大型人脸数据库（8 万张人脸以上），cuML 能显著加快聚类速度。它需要一个 conda
环境：

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# 或：pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
```

只要 cuML 可用，聚类就会自动使用 GPU（`scoring_config.json` 中的
`face_clustering.use_gpu`）。Docker 的 CUDA 镜像已经内置了它，因此容器化的
`8gb`/`16gb`/`24gb` 配置档无需额外步骤即可在 GPU 上聚类；`legacy` 始终在处理器上
聚类。

## Apple Silicon (Metal/MPS)

不需要单独的 GPU 软件包。用 `bash install.sh` 安装，然后确认
`python facet.py --doctor` 报告 `Facet runtime device: mps`。对于不受支持的算子，
Facet 默认启用 PyTorch 的 CPU 回退。想做对比：

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

设置 `FACET_DEVICE=cpu` 可关闭加速，设置 `FACET_DEVICE=mps` 则强制要求使用它
（不可用时明确报错）。InsightFace 仍留在处理器上，因为它是 ONNX Runtime 模型，
不是 PyTorch 模型。

Metal 没有专用显存，所以 `vram_profile: "auto"` 是按统一内存总量来选定的：

| 统一内存总量 | `auto` 选定的配置档 |
|----------------------|----------------------------|
| 低于 16GB | `legacy` |
| 16-31GB | `8gb` |
| 32-47GB | `16gb` |
| 48GB 及以上 | `24gb` |

每档阈值大约要求配置档模型占用量的两倍，因为统一内存是与 macOS、窗口服务器以及
其他所有正在运行的程序共享的 —— 一台开始交换内存的 Mac，比一台用较小配置档的
Mac 更慢。显式配置的配置档始终按你写的执行，所以设定一个即可在任一方向上覆盖
这些阈值。

## 下载体积

模型在首次使用时下载到 `~/.cache/huggingface/`（Hugging Face 模型）、
`~/.cache/torch/hub/`（PyIQA 权重）和 `~/.insightface/`（人脸检测/识别），或者
Docker 的具名卷中。`samp_net.pth`、`u2netp.pth`、`face_landmarker.task` 以及
CLIP-MLP 美学评分头的 `aesthetic_predictor_weights.pth`（仅 `legacy`/`8gb`）全都
落在 `pretrained_models/` 里，该路径是相对仓库根目录解析的，而不是相对进程的工作
目录 —— 在 Docker 中它就是映射出来的 `facet-pretrained` 卷，所以重建容器时它们都
不会重新下载。镜像中没有烘焙任何模型权重。

下面的体积按十进制计（GB = 10⁹ 字节，MB = 10⁶ 字节），取自本地模型缓存和
Hugging Face API。

| 模型 | 体积 | 配置档 |
|-------|------|----------|
| CLIP ViT-L-14 laion2b（嵌入向量 + CLIP 标签 + CLIP-MLP 美学评分） | 1.711 GB | `legacy`/`8gb` |
| 美学 MLP 头（`sac+logos+ava1-l14-linearMSE.pth`） | 3.7 MB | 仅 `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M（嵌入向量） | 4.581 GB | `16gb`/`24gb` |
| Qwen3.5-2B（VLM 标签） | 4.571 GB | `16gb` |
| Qwen3.5-4B（VLM 标签） | 9.343 GB | `24gb` |
| Qwen2-VL-2B（构图） | 4.430 GB | 默认不使用 —— 只有当你手动设置 `composition_model: "qwen2-vl-2b"` **并且** `processing.mode: "single-pass"` 时才会用到 |
| InsightFace buffalo_l（人脸） | 下载 289 MB / 磁盘 630 MB（zip 包会与解压出的 `.onnx` 文件一同保留） | 全部 |
| SAMP-Net 权重（构图） | 183 MB | 全部 |
| U2-Net-P（SAMP-Net 的显著性子模型） | 4.7 MB | 与 SAMP-Net 相同 |
| BiRefNet_dynamic（主体显著性） | 445 MB | 全部 |
| TOPIQ NR（美学模型） | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA（补充美学评分） | 873 MB | 全部 |
| TOPIQ NR-Face（补充人脸画质） | 376 MB | 全部 |
| LIQE（补充画质/失真诊断） | 708 MB | 全部 |
| timm resnet50.a1_in1k（PyIQA 共用骨干网络） | 102 MB | 全部 |
| Q-ReAlign-Mini-0.8B（`iqa_extended.qrealign`） | 2.235 GB | `8gb`/`16gb`/`24gb`，**默认开启**（`"auto"` 在除 `legacy` 以外的每个配置档上都解析为启用） |

各配置档的下载总量：`legacy` 4.69 GB · `8gb` 6.93 GB · `16gb` 14.55 GB ·
`24gb` 19.32 GB · `24gb` 搭配 `composition_model: "qwen2-vl-2b"` 与
`processing.mode: "single-pass"` 为 23.56 GB（这项手动覆盖是替换掉
SAMP-Net/U2-Net-P，而不是在它们之外追加）。

作为参考，Docker 镜像本身（尚未下载任何模型时）解包后：`latest` 为 3.34 GB、
`latest-cuda` 为 13.1 GB、`latest-cuda-legacy` 为 13.8 GB —— 这些数字的测量方式见
[部署 › 镜像大小](DEPLOYMENT.md#镜像大小)。本次发布中三个镜像都更换了基础镜像
（issue #119）；等这些基础镜像发布、有清单可供测量之后，会补上它们的压缩下载
体积。

未计入上述总量的可选模型：

| 模型 | 体积 | 触发条件 |
|-------|------|---------|
| DeQA-Score-Mix3（`iqa_extended.deqa`） | 16.41 GB | 默认关闭 |
| SigLIP so400m-patch14-384 骨干网络（`iqa_extended.aesthetic_v25`） | 3.515 GB | 默认关闭，且**已弃用**（AGPL-3.0，上游已无人维护 —— 建议改用 `qrealign`） |
| Helsinki-NLP OPUS-MT，按目标语言各一份（照片描述翻译） | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | 仅限你启用的语言 |
| MediaPipe `face_landmarker.task` | 3.76 MB | 仅当安装了 `mediapipe` 时 |

`reverse_geocoder` 无需下载 —— 它的数据随 wheel 一起分发。

SAMP-Net 权重来自本项目的
[model-weights-v1 发布](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth)。
如果该下载失败（离线或网络受限），你会看到
`Failed to download SAMP-Net weights: HTTP Error 404: Not Found` —— 请手动获取该
文件并放到 `pretrained_models/samp_net.pth`。

## 依赖

### 必需的软件包

| 软件包 | 用途 |
|---------|---------|
| `torch`、`torchvision` | 深度学习框架（单独安装，见上文） |
| `open-clip-torch` | CLIP 嵌入向量/标签（legacy/8gb 配置档） |
| `pyiqa` | TOPIQ 及其他画质/美学模型 |
| `opencv-python` | 图像处理 |
| `pillow` | 图像加载 |
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
| `sqlite-vec` | 用于语义搜索与相似照片的磁盘 KNN（缺失时回退到内存中的 NumPy 缓存） |

以上全部都在 `requirements.txt` 里；没有哪个配置档需要额外的基础软件包。

### 可选的软件包

每一个都能解锁一项功能；没有它时，该功能会被跳过，或者改用回退方案。

| 软件包 | 解锁的功能/用途 | 没有它时 |
|---------|-------------------|-----------|
| `watchdog` | 监视模式（`--watch` 守护进程会重新扫描新文件）—— **不在 `requirements.txt` 中**；只能通过 `pip install .[watch]` 引入，所以直接使用 `requirements.txt` 的用户没有 `--watch` | `--watch` 不可用 |
| `pillow-heif` | HEIF/HEIC 解码 | 跳过 HEIF/HEIC 文件 |
| `rawpy` | RAW 解码（CR2/CR3/NEF/ARW/……） | 跳过 RAW 文件（已包含在基础的 `requirements.txt` 中） |
| `cuml`、`cupy` | GPU 加速的人脸聚类（conda + CUDA） | 聚类通过 `hdbscan` 在 CPU 上运行（默认） |
| `onnxruntime-gpu` | GPU 加速的人脸检测 | 使用 CPU 版 `onnxruntime`（较慢） |
| `aesthetic-predictor-v2-5` | 扩展 IQA 层 —— `aesthetic_v25` 评分器（`pip install -e .[iqa-extended]`；对应 `scoring_config.json` 中的 `iqa_extended.aesthetic_v25`，默认关闭）。**已弃用** —— AGPL-3.0，上游自 2024-12-18 起无人维护；建议改用 `qrealign`，它不需要额外软件包（随基础依赖 `pyiqa` 一同提供） | `aesthetic_v25` 不可用 |
| `darktable-cli`（系统） | 从照片库导出 RAW/darktable 配置文件 | 只提供原图/内嵌图下载 |
| `exiftool`（系统） | 最佳的 EXIF/GPS 提取 | 回退到 `exifread`，再回退到 PIL |

## 各功能的要求

Facet 的大部分功能在哪里都能跑（CPU、任意配置档）。少数功能需要 GPU、更高的**显存配置档**、某个可选软件包，或照片库的**编辑密码** / **超级管理员**角色。文档中通用的标记：
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
| AI 照片描述（生成/查看） | 是 | `16gb`/`24gb` | — | — |
| AI 照片描述（编辑） | 是 | `16gb`/`24gb` | 编辑模式 | — |
| VLM 点评 | 是 | `16gb`/`24gb` | — | — |
| 人脸检测/提取（InsightFace） | 推荐（CPU 也行，但慢） | 任意 | — | — |
| 人脸聚类（HDBSCAN） | 否（CPU） | 任意 | — | `cuml`/`cupy`（可选的 GPU 加速） |
| 语义搜索 | 否 | 任意 | — | `sqlite-vec`（可回退到 NumPy） |
| RAW / HEIF 解码 | 否 | 任意 | — | `rawpy` / `pillow-heif` |
| 监视模式（`--watch`） | 否 | 任意 | — | `watchdog` |
| GPS 提取 / darktable 导出 | 否 | 任意 | — | `exiftool` / `darktable-cli` |
| 星级、收藏、人脸与人物编辑、选片 | 否 | 任意 | 编辑模式 | — |
| 从网页界面触发扫描 | 否 | 任意 | 超级管理员 | — |
| 多用户（按用户区分的星级与角色） | 否 | 任意 | 按角色 | — |

> 人脸*聚类*默认在 CPU 上运行（独立的 `hdbscan`）；`cuml`/`cupy` 只是额外提供可选的 GPU 加速 —— 它们**不是**必需的。编辑密码和用户角色在 `scoring_config.json` 中配置 —— 认证相关内容见[配置](CONFIGURATION.md)。

> 本地没有 GPU？用 `scoring_config.json` 里的 `vlm_backend` 把 VLM 标签、照片描述和
> 点评指向远程的 Ollama 或兼容 OpenAI 的服务器 —— 这样这些功能在 CPU 的
> `legacy`/`8gb` 配置档上也能用。

## 排查依赖冲突

Facet 有大量机器学习依赖（`torch`、`open-clip-torch`、`insightface` 等），它们各自又会带入自己的传递依赖。pip 是逐个解析依赖的，这会导致连锁报错：装上一个包，却把另一个包弄坏了。

**症状：** 一个个地装包，会不断冒出「还需要另一个包」的错误；`torch`、`numpy`、
`huggingface-hub` 或 `open-clip-torch` 之间出现版本冲突；`pip install` 成功了，但
运行时 `import` 失败。

**1. 一次性全部安装** —— `pip install -r requirements.txt` 会把完整的依赖图交给 pip 去解算。不要逐个安装（`pip install open-clip-torch && pip install insightface && ...`），那会让 pip 无法解算整张依赖图。

**2. 用 [uv](https://docs.astral.sh/uv/) 代替 pip** —— `uv` 会在安装任何东西之前先解算完整的依赖图，从而避免连锁冲突：

```bash
pip install uv
uv pip install -r requirements.txt
# 为 PyTorch 加上 CUDA 索引：
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. 推倒重来** —— 如果你的环境已经坏掉了，执行 `deactivate`、`rm -rf venv`，
然后重做[手动安装](#手动安装不使用-installsh)（或者干脆再跑一次 `install.sh`）。

### GPU 检测问题

如果你的 GPU 没有被检测到（较新的显卡上比较常见），运行诊断命令：

```bash
python facet.py --doctor
```

它会检查 PyTorch 的 CUDA 支持与驱动兼容性，并给出正确的 pip 命令。它还能捕获
`torch.cuda.is_available()` 无法发现的一种情况：驱动能看到 GPU，但已安装的
PyTorch 构建根本没有为它提供内核 —— 在 CUDA 12.8 之前的构建上使用 RTX 50 系列
（Blackwell，`sm_120`）正是这种情况。Facet 会把设备的算力与该构建的架构清单做
比对，并在确定显存配置档之前启动一个一次性内核；一旦不匹配，它会回退到 CPU，而
不是在第一个真正的算子上崩溃，`--doctor` 也会指出不匹配之处和修复办法 —— 在
Docker 中是对应的镜像标签（Maxwell/Pascal/Volta 显卡用
`ghcr.io/ncoevoet/facet:latest-cuda-legacy`），裸机上则是正确的 `--index-url`。

你也可以模拟硬件来做测试：

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Angular 客户端

只有开发或自定义构建时才需要 —— `install.sh` 和 Docker 镜像已经帮你构建好了。

```bash
cd client
npm install
npm run build    # 生产构建 → client/dist/
npm start        # 开发服务器，运行在 http://localhost:4200（把 API 代理到 :5000）
```

> **`npm audit` 警告：** Angular 会带入一棵很深的传递依赖树，`npm audit` 必然会
> 报出一些问题，其中多数都在构建期的开发依赖里，永远不会进入浏览器。运行
> `npm audit fix` 之前请先审阅清单 —— 它可能会悄悄降级或移除某些软件包。
