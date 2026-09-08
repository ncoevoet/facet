# Immich 集成

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · [Deutsch](../de/IMMICH.md) · [Italiano](../it/IMMICH.md) · [Español](../es/IMMICH.md) · [Português](../pt/IMMICH.md) · **简体中文**

Facet 和 [Immich](https://immich.app/) 在同一批照片上做的是不同的工作。Immich 是照片库：它负责导入、备份，并把照片送到你的手机上。Facet 负责判断：它给照片打分、排序并完成选片。本页把两者接在一起，让 Facet 得出的结论以星级和收藏的形式出现在 Immich 里，也让一次上传到 Immich 的操作告诉 Facet 有新的工作在等着。

两个方向的连接都只走 REST。Facet 从不碰 Immich 的数据库，Immich 也从不碰 Facet 的数据库。

**Facet 要求 Immich ≥ 3.0。** 更旧的服务器会拒绝 Facet 所依赖的星级语义：用 `null` 清除星级，用 `-1` 标记淘汰。在 2.x 服务器上，清除会被拒绝，过期的星级会永远卡在你的资产上。

---

## 目录

- [两者如何看待同一个文件](#两者如何看待同一个文件)
- [第 1 步 —— 与 Immich 共享照片库](#第-1-步--与-immich-共享照片库)
- [第 2 步 —— 创建 API 密钥](#第-2-步--创建-api-密钥)
- [第 3 步 —— 映射路径](#第-3-步--映射路径)
- [第 4 步 —— 先测试，再推送](#第-4-步--先测试再推送)
- [推送淘汰标记](#推送淘汰标记)
- [入站 webhook](#入站-webhook)
- [配置参考](#配置参考)
- [故障排查](#故障排查)

---

## 两者如何看待同一个文件

这里的一切都建立在一个想法上：**磁盘上的同一张照片，从两个容器里看到的样子**。

Facet 通过照片在执行扫描的那台机器上的绝对路径来认识它——`/mnt/photos/2026/07/IMG_1234.jpg`。Immich 通过自己的 `originalPath` 认识同一个文件，那是这个文件*从 Immich 容器内部*看上去的样子——上传的资产通常是 `/usr/src/app/upload/…`，外部库则是你给它指定的挂载点。

两边都猜不到对方的视角，所以你只需把前缀改写规则告诉 Facet 一次（`immich.path_map`），两个方向上的每一次查找都会经过它。这一步做对了，其余的都是机械的；做错了，所有内容都会悄悄地报告为“unmatched”——见[故障排查](#故障排查)。

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

这个映射双向都用得上：出站时（`--immich-sync` 把 Facet 路径翻译过去以找到资产）和入站时（webhook 把 Immich 的 `originalPath` 翻译回来以找到照片）。

## 第 1 步 —— 与 Immich 共享照片库

最干净的方案是**外部库**：Immich 就在照片原本所在的位置读取它们，而不是自己再持有一份副本。Facet 从自己这一侧扫描同一个目录。

1. 在 Immich 中进入 **Administration → External Libraries → Create Library**，选择所有者，并添加一个导入路径，指向 Immich 容器所看到的那个目录。
2. 确保该目录以只读方式绑定挂载进 Immich 容器。在 `docker-compose.yml` 中：

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. 从 Immich 的界面扫描该库（**Scan All Libraries**），并用 Facet 扫描同一个目录：

   ```bash
   python facet.py /mnt/photos
   ```

两个工具现在都为每个文件保存了一行记录。磁盘上没有任何重复。

如果你改为按常规方式上传到 Immich（手机自动备份、网页上传器），并把 Facet 指向 Immich 自己的上传目录，集成的工作方式完全相同——只是前缀不同。这种情况下由 Immich 掌管文件的组织方式，所以每次上传之后要重新运行 Facet 扫描（或者使用 `--watch`）。

## 第 2 步 —— 创建 API 密钥

在 Immich 中：**点击你的头像 → Account Settings → API Keys → New API Key**。

Immich ≥ 3.0 允许你限定密钥的权限范围，而不必把一切都授予它。Facet 恰好需要六个范围：

| 范围 | Facet 用它做什么 |
|-------|-------------------------|
| `server.about` | `--immich-test` 的连通性／认证检查 |
| `asset.read` | 通过 `originalPath` 解析资产 |
| `asset.update` | 写入 `rating` 和 `isFavorite` |
| `album.read` | 按名称查找已有的精选照片相册 |
| `album.create` | 首次创建精选照片相册 |
| `albumAsset.create` | 把照片添加到精选照片相册 |

如果你把 `push.top_picks_album` 留空，后三个就可以省略——只有设置了这个名称，Facet 才会碰相册。

密钥以 `x-api-key` 请求头随每一次请求发送。把它放进 `scoring_config.json`：

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **关于 `PUT /api/assets` 的一点说明。** Facet 用 `PUT /api/assets` 写入星级，而 Immich 的 OpenAPI 文档把它标记为 *deprecated*。作为替代的 `PATCH` 别名虽已宣布，却**不在已发布的规范里**，所以目前还没有可以迁移过去的目标——`PUT` 仍是唯一真实存在的端点，Facet 继续使用它。Facet 碰到的每一条 Immich 路径都位于 `ImmichClient`（`sync/immich.py`）中，所以等 `PATCH` 路由发布的那天，改动只涉及一个类。

## 第 3 步 —— 映射路径

你共享的每个根目录添加一对。第一个 `facet_prefix` 与照片匹配的配对胜出：

```json
"immich": {
  "path_map": [
    { "facet_prefix": "/mnt/photos/", "immich_prefix": "/usr/src/app/external/" }
  ]
}
```

两个根目录，两对配置：

```json
"path_map": [
  { "facet_prefix": "/mnt/photos/",  "immich_prefix": "/usr/src/app/external/" },
  { "facet_prefix": "/mnt/archive/", "immich_prefix": "/usr/src/app/archive/" }
]
```

保留随附的占位配置（`{"facet_prefix": "", "immich_prefix": ""}`）不动，路径就会原样通过——只有当 Facet 和 Immich 真的看到完全相同的绝对路径时这才正确，也就是你在 Immich 容器的命名空间内运行 Facet 的情况，除此之外几乎从不成立。

要读出真实的值，在 Immich 中打开任意一张照片，按 `i` 调出信息面板，把那里显示的文件路径与 Facet 为同一张照片报告的路径作比较。

## 第 4 步 —— 先测试，再推送

```bash
# 仅连通性 + 认证。不做任何写入。
python facet.py --immich-test

# 解析每一个资产并报告哪些内容将会改变。仍然不做任何写入。
python facet.py --immich-sync --dry-run

# 来真的。
python facet.py --immich-sync
```

同步会报告 `matched` / `unmatched` / `updated` / `skipped (unrated)` 以及创建的相册数。首次运行时 `unmatched` 数量很大，几乎总是意味着路径映射有误——见[故障排查](#故障排查)。

会被推送的内容：

- **1–5 星的星级** → Immich 的 `rating`。你从未评过星的照片什么也不会推送。
- **收藏** → Immich 的 `isFavorite`。
- **清除。** 如果你把一张照片评为 5 星、同步过，然后又把它重置为未评星，下一次同步会发送 `rating: null`，让 Immich 也把它忘掉。Facet 会记住自己上一次推送的内容（放在 `stats_cache` 辅助表里），正是为了不让这个变化丢失。它是 `null` 而绝不是 `0`——Immich v3 会直接拒绝 `0`，而一个批次被拒就会中止整次同步。
- **一个可选的精选照片相册**，当 `push.top_picks_album` 指定了名称时，按 `push.top_picks_min_rating` 填充。

在多用户模式下，`--immich-sync --user alice` 推送的是 Alice 在 `user_preferences` 中的星级，而不是全局列，并在她自己的范围下跟踪状态。

## 推送淘汰标记

默认关闭。打开之后，你在 Facet 的选片暗房里淘汰掉的照片会获得 Immich 自己的淘汰标记：

```json
"immich": {
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": true
  }
}
```

开启 `push.rejected` 之后：

- 被淘汰的照片会推送 `rating: -1`，这是 Immich v3 表示“已淘汰”的值。
- **淘汰高于星级。** 一张被淘汰的 5 星照片推送的是 `-1` 而不是 `5`——你把它扔掉了，这才是值得镜像过去的事实。
- **取消淘汰会清除它。** 一张推送过 `-1` 后又被取消淘汰的照片，会改为推送它当前的星级，如果没有星级则推送 `rating: null`。用的是与其他任何清除相同的状态跟踪机制。
- 被淘汰的照片永远不会进入精选照片相册。
- `push.ratings: false` 会抑制它。`-1` 也是一次星级写入，所以一份禁用了星级推送的配置不会被偷偷塞回一个。

如果还有其他人（或者你的手机）会看这个 Immich 照片库，就让它保持关闭：`-1` 在那边是可见的，而“在 Facet 里淘汰”是一个你未必想广而告之的工作判断。

## 入站 webhook

上面的一切都是 Facet → Immich。webhook 是另一个方向：Immich 告诉 Facet 某个资产刚刚发生了变化，而 Facet 立刻用它所知道的内容作出回应。

**它默认关闭，并且从不启动扫描。** webhook 是来自另一个守护进程、不带会话认证的调用；让它能够触发 GPU 工作，就等于给任何持有令牌的人一条压垮你机器的路。它实际做的是：

- **照片已知且已评分** → 它的星级／收藏会当场作为单资产更新直接推回 Immich。这正是扫描之后闭合回路的一环：给一张照片打分，上传它，星级就会落到 Immich 里，无需等待下一次 `--immich-sync`。
- **照片未知或尚未评分** → 该路径会被记入一个有上限、去重过的待处理列表，下一次 `--immich-sync` 会把它记录到日志中。不会扫描任何东西。

### 启用它

令牌是一个共享密钥，所以它存放在环境变量里，绝不放进 `scoring_config.json`（那个文件会被多个端点就地重写，而且在大多数安装中是全局可读的）。配置里写的是*变量名*，变量里存的是*值*。

1. 生成一个令牌，并在启动查看器的任何地方导出它——你的 systemd 单元、`docker-compose.yml` 或 shell 配置文件：

   ```bash
   export FACET_IMMICH_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
   ```

2. 在 `scoring_config.json` 中写明该变量名：

   ```json
   "immich": {
     "webhook": {
       "token_env": "FACET_IMMICH_WEBHOOK_TOKEN",
       "header": "x-facet-token",
       "max_pending": 500
     }
   }
   ```

3. 重启查看器（`python viewer.py`）。

`token_env` 为空，或者它指向的变量未设置或为空，都会彻底禁用该端点——它会返回 **404**，和 `frame.tokens` 与 `upload.username` 的行为完全一样。不存在半开状态。

### 让 Immich 指向它

在 Immich ≥ 3.0 中：**Administration → Workflows → Create Workflow**。

1. **触发器** —— 选择你想镜像的资产事件。`Asset uploaded` 是有用的那个；如果你也希望编辑操作重新触发，再加上 `Asset updated`。
2. **动作** —— 选择 **Webhook**。
3. **URL** —— `http://facet.local:5000/api/immich/webhook`，使用一个 Immich 容器真正能访问到的地址。如果两者都在同一台主机的 Docker 中运行，那就是服务名（`http://facet:5000/…`），而不是 `localhost`。
4. **请求头** —— 名称填 `x-facet-token`，值填你生成的令牌。名称必须与 `webhook.header` 一致；如果你的环境需要另一个名称，就把两处一起改。`Authorization: Bearer <token>` 也可以接受，供那些只提供这种方式的代理使用。
5. 保存，然后上传一张照片来确认。

### 端点的响应

| 状态码 | 含义 |
|--------|---------|
| `202` | 请求体已理解。JSON 计数统计的是*这一次*投递中的资产：`received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`。 |
| `204` | JSON 有效，但没有 Facet 认得的资产。会被记录，但不算错误——载荷的结构由 Immich 决定，随时可能改变。 |
| `400` | 请求体根本不是 JSON。 |
| `401` | 请求中没有令牌。 |
| `403` | 令牌不正确。 |
| `404` | 功能已禁用（未配置令牌）。 |

Facet 从载荷中读取 `originalPath`，并且有意对它出现的位置保持宽容——一个裸的资产对象、`{"asset": {…}}`、一个列表，或者以上任意一种嵌套在 `data` / `items` / `assets` 之下，都能正常工作。如果载荷携带了资产 `id`，Facet 会使用它，省下一次查询往返。

待处理的路径会由下一次同步报告：

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

扫描这些照片（`python facet.py /mnt/photos`），它们就会在随后的一次同步中从列表里消失。该列表以 `max_pending` 条为上限，最旧的先被丢弃，所以一个话多的 Immich 永远无法让它无限增长。

### 安全提示

- 令牌采用常量时间比较。错误的令牌只会得到一个干脆的 `403`，不带任何时序信号。
- 如果 Immich 要通过比私有桥接网络更不可信的链路访问查看器，请用 HTTPS 提供服务——令牌随每一次投递都在请求头里传输。
- 轮换时要同时修改环境变量和 Immich 工作流的请求头值，然后重启查看器。
- webhook 读取的是全局星级列，所以在多用户模式下它镜像的是共享／全局星级，而不是某一个用户的覆盖值。如果你想要的是 Immich 中的按用户星级，就别开 webhook，改为定期运行 `--immich-sync --user <name>`。

## 配置参考

完整的 `immich` 配置块，附随附的默认值：

```json
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
```

| 键 | 默认值 | 含义 |
|-----|---------|---------|
| `url` | `""` | Immich 的基础 URL，`http` 或 `https`。末尾的斜杠会被去掉。 |
| `api_key` | `""` | API 密钥，以 `x-api-key` 发送。为空时任何同步都会带着明确的错误中止。 |
| `path_map` | 一对空配置 | Facet 路径与 Immich `originalPath` 值之间的前缀改写。第一个匹配的胜出；双向都会用到。 |
| `push.ratings` | `true` | 推送 1–5 星的星级（以及它们的清除）。 |
| `push.favorites` | `true` | 推送 `isFavorite`（以及它的清除）。 |
| `push.rejected` | `false` | 为在 Facet 中被淘汰的照片推送 `rating: -1`。需要 `push.ratings`。 |
| `push.top_picks_album` | `""` | 要填充的相册名称。为空表示 Facet 绝不碰相册。 |
| `push.top_picks_min_rating` | `4` | 进入该相册的最低星级。 |
| `webhook.token_env` | `""` | 存放 webhook 密钥的环境变量的名称。为空 ⇒ 该端点返回 404。 |
| `webhook.header` | `"x-facet-token"` | Immich 用来发送令牌的请求头。 |
| `webhook.max_pending` | `500` | 已记住但尚未评分的路径列表的上限。 |
| `timeout_seconds` | `30` | 单次请求的 HTTP 超时。 |

## 故障排查

### 所有结果都是 `unmatched`

路径映射错了——这是遥遥领先的头号故障。

1. 在 Immich 中打开一张照片并按 `i`。记下信息面板中的路径。
2. 在 Facet 中找到同一张照片的路径（照片库的详情面板，或 `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`）。
3. 两者共享同一个*后缀*。不同的是前缀，而那两个前缀正是 `facet_prefix` 和 `immich_prefix`。

常见陷阱：

- **缺少末尾斜杠。** `"/mnt/photos"` → `"/usr/src/app/external"` 也会改写 `/mnt/photosXYZ/a.jpg`。两个前缀都要以 `/` 结尾。
- **主机路径与容器路径。** Immich 的路径是*容器*看到的那个。`docker compose exec immich-server ls /usr/src/app/external` 可以一锤定音。
- **符号链接与绑定挂载。** Immich 存的是它实际走过的路径。如果你的照片库在某一侧是通过符号链接访问的，即使文件只有一个，两个字符串也会不同。
- **大小写与 Unicode。** 比较是精确匹配。位于大小写不敏感共享盘上的照片库可以同时存在 `/Photos/` 和 `/photos/`；只有实际存下来的那种写法才匹配。
- **Immich 还没有索引这个文件。** 先运行 **Scan All Libraries**，确认资产确实存在于 Immich 中，再去怪罪映射。

`--immich-sync --dry-run` 会在日志里列出前 20 条未匹配的路径；这份列表通常一眼就能指认出错误的前缀。

### `--immich-test` 失败

- `Unsupported Immich URL scheme`——`url` 需要 `http://` 或 `https://`。
- `HTTP 401`——API 密钥错误或已被吊销。
- `HTTP 403`——密钥有效，但缺少 `server.about`。用上面那六个范围重新创建它。
- 连接被拒绝／超时——端口不对，或者 Facet 访问不到容器。在运行 Facet 的那台机器上用 `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` 测试。

### webhook 返回 404

功能被禁用了。要么 `webhook.token_env` 是空的，要么它指向的变量*在查看器自己的环境中*未设置或为空。在你的交互式 shell 里导出它，对由 systemd 或 Docker 管理的查看器毫无作用——请在单元文件或 compose 文件中设置，然后重启。

### webhook 返回 401 或 403

`401` 表示没有令牌送达：Immich 发送的请求头名称与 `webhook.header` 不一致。`403` 表示令牌送达了但不正确——把工作流中的请求头值与环境变量逐字符比对。

### `ModuleNotFoundError: No module named 'sync'`

服务器启动了、看上去也很健康，但 webhook 只有在 Immich 真的调用它时才失败，而 `--immich-sync` 会直接失败。用下面的命令确认：

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

出现 `ModuleNotFoundError: No module named 'sync'` 说明你的镜像早于这个修复——`sync/` 当时没有被打进 Docker 构建。拉取当前镜像，或从包含该修复的检出重新构建。

### 星级推送成功，但清除不生效

Facet 只会为它确实推送过的照片发送清除；这份记忆保存在 Facet 数据库的 `stats_cache` 中。恢复一个较旧的数据库（或者对着一个全新的数据库运行）会丢失它，在这段空档里被清除的星级不会在 Immich 中被取消。重新给照片评星再清除一次，或者直接在 Immich 里改。

### 星级出现在错误的照片上

Immich 内部不可能出现两个 `originalPath` 相同的文件，但两个 *Facet* 根目录映射到同一个 Immich 前缀是可能冲突的。检查你的 `path_map` 各对配置没有重叠：第一个匹配的配对胜出，所以一个宽泛的配对排在一个狭窄的配对前面，就会把后者吞掉。

### `rating: 0 is not valid`

Immich 服务器版本低于 3.0。请升级——Facet 的清除语义需要 `null`，`push.rejected` 需要 `-1`；在 2.x 上没有任何可行的回退方案。

---

**参见：**[命令 —— Immich 同步](COMMANDS.md#immich-同步) · [配置](CONFIGURATION.md) · [编辑器互操作方案](INTEROP.md)，了解与 Lightroom、darktable 和 digiKam 的 XMP 往返。
