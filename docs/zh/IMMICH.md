# Immich 集成

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · [Deutsch](../de/IMMICH.md) · [Italiano](../it/IMMICH.md) · [Español](../es/IMMICH.md) · [Português](../pt/IMMICH.md) · **简体中文**

[Immich](https://immich.app/) 负责存储、备份并提供你的照片。Facet 负责给照片打分、排序并完成选片。本页把两者接在一起：

- Facet 的星级和收藏会出现在 Immich 里。
- 一次上传到 Immich 的操作会告诉 Facet 有新的工作在等着。

两个方向的连接都只走 Immich 的 REST API。两个工具都不会碰对方的数据库。

**Facet 要求 Immich ≥ 3.0。** Facet 用 `null` 清除星级，用 `-1` 标记淘汰。2.x 服务器会拒绝清除，过期的星级会留在你的资产上。

---

## 目录

- [两者如何看待同一个文件](#两者如何看待同一个文件)
- [第 1 步 —— 与 Immich 共享照片库](#第-1-步--与-immich-共享照片库)
- [第 2 步 —— 创建 API 密钥](#第-2-步--创建-api-密钥)
- [第 3 步 —— 映射路径](#第-3-步--映射路径)
- [第 4 步 —— 先测试，再推送](#第-4-步--先测试再推送)
- [推送淘汰标记](#推送淘汰标记)
- [手动堆叠导入和推送](#手动堆叠导入和推送)
- [入站 webhook](#入站-webhook)
- [查看器中的诊断](#查看器中的诊断)
- [配置参考](#配置参考)
- [故障排查](#故障排查)

---

## 两者如何看待同一个文件

Facet 和 Immich 在磁盘上看到的是同一个文件，只是路径不同：

- **Facet** 使用执行扫描的那台机器上的绝对路径，例如 `/mnt/photos/2026/07/IMG_1234.jpg`。
- **Immich** 使用它自己的 `originalPath`：即*从 Immich 容器内部*看到的路径。上传的资产通常是 `/usr/src/app/upload/…`，外部库则是它的挂载点。

你只需把前缀改写规则告诉 Facet 一次（`immich.path_map`），每一次查找都会经过它。如果写错了，所有内容都会报告为“unmatched”——见[故障排查](#故障排查)。

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

这个映射双向都用得上。`--immich-sync` 用它为 Facet 路径找到对应的 Immich 资产；webhook 用它为 Immich 的 `originalPath` 找到对应的 Facet 照片。

## 第 1 步 —— 与 Immich 共享照片库

最简单的方案是 Immich 的**外部库**：Immich 就在照片原本所在的位置读取它们，Facet 扫描同一个目录。

1. 在 Immich 中进入 **Administration → External Libraries → Create Library**，选择所有者，并添加一个导入路径，指向 Immich 容器所看到的那个目录。
2. 把该目录以只读方式绑定挂载进 Immich 容器。在 `docker-compose.yml` 中：

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. 在 Immich 中扫描该库（**Scan All Libraries**），并用 Facet 扫描同一个目录：

   ```bash
   python facet.py /mnt/photos
   ```

磁盘上没有任何文件被复制。

你也可以照常上传到 Immich（手机自动备份、网页上传器），并把 Facet 指向 Immich 的上传目录。只是前缀不同。上传之后请重新运行 Facet 扫描，或者使用 `--watch`。

## 第 2 步 —— 创建 API 密钥

在 Immich 中：**点击你的头像 → Account Settings → API Keys → New API Key**。

Immich ≥ 3.0 允许把密钥限定在某些权限范围内。星级和收藏同步需要以下范围（手动堆叠需要更多，见下文）：

| 范围 | Facet 用它做什么 |
|-------|-------------------------|
| `server.about` | `--immich-test` 的连通性／认证检查 |
| `asset.read` | 通过 `originalPath` 解析资产 |
| `asset.update` | 写入 `rating` 和 `isFavorite` |
| `album.read` | 按名称查找精选照片相册并读取其成员列表 |
| `album.create` | 首次创建精选照片相册 |
| `albumAsset.create` | 把照片添加到精选照片相册 |
| `albumAsset.delete` | 移除评分跌破精选阈值的照片 |

如果 `push.top_picks_album` 为空，就可以省略四个相册范围。只有设置了这个名称，Facet 才会碰相册。 缺少 `albumAsset.delete` 时同步仍会继续：被拒绝的移除会跳过并计入同步摘要，试运行也会预览它们。

Facet 以 `x-api-key` 请求头发送密钥。把它放进 `scoring_config.json`：

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **注意：** Facet 用 `PUT /api/assets` 写入星级。Immich 把它标记为 deprecated，但其替代方案尚未发布，所以 Facet 继续使用它。

## 第 3 步 —— 映射路径

你共享的每个根目录添加一对。规则：

- 第一个匹配的前缀胜出。这是纯字符串匹配，不是目录匹配。
- 目录前缀请以 `/` 结尾。
- 将较窄的映射放在较宽的映射之前。

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

随附的占位配置（`{"facet_prefix": "", "immich_prefix": ""}`）会让路径原样通过。只有当 Facet 和 Immich 看到完全相同的绝对路径时这才有效，除非 Facet 就在 Immich 容器内运行，否则这很少见。

要找到真实的值，在 Immich 中打开一张照片并按 `i` 调出信息面板。把那里的文件路径与 Facet 为同一张照片显示的路径作比较。

## 第 4 步 —— 先测试，再推送

```bash
# 仅连通性 + 认证。不做任何写入。
python facet.py --immich-test

# 解析每一个资产并报告哪些内容将会改变。仍然不做任何写入。
python facet.py --immich-sync --dry-run

# 来真的。
python facet.py --immich-sync
```

同步会报告 `matched` / `unmatched` / `updated` / `skipped (unrated)` / `identity_conflicts` 以及创建的相册数。试运行中，`updated` 统计的是将会改变的资产数，不会写入任何内容。首次运行时 `unmatched` 数量很大，几乎总是意味着路径映射有误——见[故障排查](#故障排查)。

会被推送的内容：

- **1–5 星的星级** → Immich 的 `rating`。未评星的照片什么也不会推送。
- **收藏** → Immich 的 `isFavorite`。
- **清除。** 如果你给一张照片评了星、同步过，然后又把它重置为未评星，下一次同步会发送 `rating: null`，让 Immich 也把它清除。Facet 为此会记住自己上一次推送的内容（放在 `stats_cache` 中）。它发送的是 `null` 而绝不是 `0`：Immich v3 会拒绝 `0`，而一个批次被拒就会中止整次同步。
- **一个可选的精选照片相册**，当设置了 `push.top_picks_album` 时：评分不低于 `push.top_picks_min_rating` 的照片是成员；跌破阈值的成员会在全局同步时被移除，前提是 Facet 仍能归因它（已删除的照片或其他应用的资产保持原样）；已有成员不会被重复添加。

在多用户模式下，`--immich-sync --user alice` 推送的是 Alice 自己的星级（`user_preferences`），而不是全局星级，并单独跟踪她的同步状态。

## 推送淘汰标记

默认关闭。打开之后，你在 Facet 的选片视图里淘汰掉的照片会获得 Immich 的淘汰标记：

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
- **淘汰高于星级。** 一张被淘汰的 5 星照片推送的是 `-1` 而不是 `5`。
- **取消淘汰会清除它。** 该照片随后会推送它当前的星级，如果没有星级则推送 `rating: null`。
- 被淘汰的照片永远不会进入精选照片相册。
- `push.ratings: false` 也会关闭它，因为 `-1` 也是一个星级。

如果还有其他人（或者你的手机）会浏览这个 Immich 照片库，就让它保持关闭：他们会看到那个 `-1`。

## 手动堆叠导入和推送

手动堆叠有自己的**本地 CLI 计划/应用**流程，沿用常规的 `--config`、`--db` 和 `--user` 选项。星级和收藏同步不受影响。

要求：

- Immich **≥ 3.0**（Facet 也会在运行时检查堆叠支持）。
- 密钥权限：在 `asset.read` 之外增加 `user.read` 和 `stack.read`；推送还需 `stack.create` 和 `asset.update`。不需要 `stack.update` 和 `stack.delete`。
- 多用户安装必须指定一个已有用户。
- 网页查看器、助手（MCP）或上传 webhook 的堆叠操作从不使用 Immich 密钥。

流程：

1. 预览。两端都只读，也不迁移数据库。
2. 检查计划及其 SHA-256 摘要。
3. 明确应用。

选项与限制：

- `--stack-id UUID`（可重复）将本次运行限定在这些来源堆叠上。
- `--stack-plan-out` 写入一个新的私有 JSON 文件（POSIX 权限 `0600`），拒绝覆盖。
- 一份计划最多 **1000 组、每组 1000 个成员、总计 20000 个成员、16 MiB**。用 `--stack-id` 缩小范围。
- 在 Windows 上，请选择访问控制列表（ACL）仅允许你的账户访问的输出目录；POSIX 权限位在那里不保护该文件。

匹配规则：

- 每个成员必须唯一映射到已索引、可见、在线且属于远程账户的照片。一个缺失或有歧义的成员就会跳过整组。
- 推送只会用尚未堆叠的远程资产创建堆叠。
- 成员与封面完全相同时，应用时会把两个堆叠链接起来。
- 部分重叠、封面不同、成员变化以及一侧已取消堆叠的情况，都作为冲突跳过。已有的堆叠绝不会被更新。
- 只有封面能往返；其他成员的顺序不能。
- 没有自动双向同步、轮询或取消堆叠传播。

计划、链接和回执绑定服务器、远程账户、本地所有者及路径映射。其中任何一项变化，旧计划就不再适用。回执保存结果和远程资源 ID，不保存凭据。

应用在写入前重新检查每一组，并在写入后重读。创建响应丢失时，Facet 会先核对再重试，而不是再次发送。取消在组与组之间停止；之后再次应用会根据回执继续。

> **警告：** Immich 无法按条件创建堆叠。其他客户端可能在 Facet 最后一次检查和写入之间改动这些资产，而 Facet 无法回滚。

## 入站 webhook

webhook 是反向的：Immich 告诉 Facet 某个资产发生了变化，而 Facet 用它所知道的内容作出回应。

**它默认关闭，并且从不启动扫描。** 它的做法是：

- **照片已知且已评分** → Facet 立刻把它的星级和收藏推回 Immich。给一张照片打分、上传它，星级就会落到 Immich 里，无需等待 `--immich-sync`。
- **照片未知或尚未评分** → Facet 把该路径加入一个有上限的待处理列表，下一次 `--immich-sync` 会把它记录到日志中。

### 启用它

令牌是一个密钥，所以它存放在环境变量里，而不是 `scoring_config.json`（在大多数安装中，该文件人人可读）。配置里写的是变量名，变量里存的是值。

1. 生成一个令牌，并在启动查看器的地方导出它——systemd 单元、`docker-compose.yml` 或 shell 配置文件：

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

如果 `token_env` 为空，或者该变量未设置或为空，端点就会被禁用并返回 **404**（与 `frame.tokens` 和 `upload.username` 一样）。

### 让 Immich 指向它

在 Immich ≥ 3.0 中：**Administration → Workflows → Create Workflow**。

1. **触发器** —— `Asset uploaded`。如果编辑操作也应触发，再加上 `Asset updated`。
2. **动作** —— **Webhook**。
3. **URL** —— `http://facet.local:5000/api/immich/webhook`，使用 Immich 容器能访问到的地址。如果两者都在同一台主机的 Docker 中运行，请用服务名（`http://facet:5000/…`），而不是 `localhost`。
4. **请求头** —— 名称填 `x-facet-token`，值填你的令牌。名称必须与 `webhook.header` 一致。`Authorization: Bearer <token>` 也可以，供那些只提供这种方式的代理使用。
5. 保存，然后上传一张照片来确认。

### 端点的响应

| 状态码 | 含义 |
|--------|---------|
| `202` | 已接受。JSON 计数统计的是这一次投递中的资产：`received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`。 |
| `204` | JSON 有效，但没有 Facet 认得的资产。会被记录，不算错误。 |
| `400` | 请求体不是 JSON。 |
| `401` | 请求中没有令牌。 |
| `403` | 令牌不正确。 |
| `404` | 功能已禁用（未配置令牌）。 |

Facet 从载荷中读取 `originalPath`，无论它在哪里：单个资产、`{"asset": {…}}`、列表，或位于 `data` / `items` / `assets` 之下的上述任意一种。如果载荷带有资产 `id`，Facet 会从 Immich 取回该资产，并在更新前核对其路径以及所有者／图库。不一致计为 `failed`。

待处理的路径会由下一次同步记录到日志：

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

扫描这些照片（`python facet.py /mnt/photos`），它们就会在随后的一次同步中从列表里消失。该列表最多保留 `max_pending` 条，最旧的先被丢弃。

### 安全提示

- 令牌采用常量时间比较；错误的令牌只会得到一个干脆的 `403`，不带任何时序信号。
- 除非 Immich 通过私有网络访问查看器，否则请用 HTTPS 提供服务：令牌随每一次投递都在请求头里传输。
- 轮换令牌时，要同时修改环境变量和 Immich 工作流的请求头，然后重启查看器。
- webhook 推送的是全局星级，而不是某一个用户的星级。如果想要 Immich 中的按用户星级，就别开 webhook，改为定期运行 `--immich-sync --user <name>`。

## 查看器中的诊断

在用户菜单的**任务与诊断**子菜单中打开 **Immich 诊断**。多用户模式需要超级管理员权限；单用户模式需要编辑权限（或可信本地编辑）。

- 在你点击**测试连接**之前，不会从 Immich 读取任何内容。该测试读取服务器版本和账户访问权限，不做任何写入。
- 路径覆盖最多检查 200 张已索引照片。它不验证每一张是否都匹配某个 Immich 资产。
- 上次同步的时间可能早于对所配置服务器的更改。
- 版本检查不验证堆叠权限。
- 凭据和服务器路径绝不会显示。

## 配置参考

完整的 `immich` 配置块，附随附的默认值：

```json
"immich": {
  "url": "",
  "api_key": "",
  "owner_id": "",
  "library_id": "",
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
| `owner_id` | `""` | 只匹配具有这个精确 Immich `ownerId` 的资产。 |
| `library_id` | `""` | 只匹配具有这个精确 Immich `libraryId` 的资产。为空表示任意图库。 |
| `path_map` | 一对空配置 | Facet 路径与 Immich `originalPath` 之间的前缀改写。第一个匹配的胜出；双向都会用到。 |
| `push.ratings` | `true` | 推送 1–5 星的星级（以及它们的清除）。 |
| `push.favorites` | `true` | 推送 `isFavorite`（以及它的清除）。 |
| `push.rejected` | `false` | 为在 Facet 中被淘汰的照片推送 `rating: -1`。需要 `push.ratings`。 |
| `push.top_picks_album` | `""` | 要持续填充的相册名称：低于 `push.top_picks_min_rating` 的成员会在全局同步时被移除，前提是 Facet 仍能归因它们。为空表示 Facet 绝不碰相册。 |
| `push.top_picks_min_rating` | `4` | 进入该相册的最低星级。 |
| `webhook.token_env` | `""` | 存放 webhook 密钥的环境变量。为空表示禁用该端点。 |
| `webhook.header` | `"x-facet-token"` | Immich 用来发送令牌的请求头。 |
| `webhook.max_pending` | `500` | 待处理（未评分）路径列表的最大长度。 |
| `timeout_seconds` | `30` | 单次请求的 HTTP 超时。 |

## 故障排查

### 所有结果都是 `unmatched`

路径映射错了。这是迄今为止最常见的故障。

1. 在 Immich 中打开一张照片并按 `i`。记下信息面板中的路径。
2. 在 Facet 中找到同一张照片的路径（照片库的详情面板，或 `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`）。
3. 两条路径的结尾相同。不同的部分就是你的 `facet_prefix` 和 `immich_prefix`。

常见陷阱：

- **缺少末尾斜杠。** `"/mnt/photos"` → `"/usr/src/app/external"` 也会改写 `/mnt/photosXYZ/a.jpg`。两个前缀都要以 `/` 结尾。
- **主机路径与容器路径。** Immich 的路径是*容器*看到的那个。用 `docker compose exec immich-server ls /usr/src/app/external` 检查。
- **符号链接与绑定挂载。** Immich 存的是它实际走过的路径。某一侧的符号链接会让两个字符串不同。
- **大小写与 Unicode。** 比较是精确匹配。在大小写不敏感的共享盘上，`/Photos/` 和 `/photos/` 互不匹配。
- **Immich 还没有索引这个文件。** 运行 **Scan All Libraries**，并确认资产确实存在于 Immich 中。

`--immich-sync --dry-run` 会在日志里列出前 20 条未匹配的路径，这通常能显示出错误的前缀。

### `--immich-test` 失败

- `Unsupported Immich URL scheme`——`url` 需要 `http://` 或 `https://`。
- `HTTP 401`——API 密钥错误或已被吊销。
- `HTTP 403`——密钥缺少 `server.about`。用上面那七个范围重新创建它。
- 连接被拒绝／超时——端口不对，或者 Facet 访问不到容器。在 Facet 所在的机器上用 `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` 测试。

### webhook 返回 404

功能被禁用了：`webhook.token_env` 是空的，或者它指向的变量*在查看器自己的环境中*未设置或为空。在你的 shell 里导出它，对由 systemd 或 Docker 运行的查看器没有作用。请在单元文件或 compose 文件中设置，然后重启。

### webhook 返回 401 或 403

`401`：没有令牌送达，说明 Immich 发送的请求头名称与 `webhook.header` 不一致。`403`：令牌不正确。把工作流中的请求头值与环境变量作比较。

### `ModuleNotFoundError: No module named 'sync'`

服务器看上去很健康，但 Immich 调用 webhook 时会失败，而 `--immich-sync` 会直接失败。用下面的命令确认：

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

如果出现 `ModuleNotFoundError: No module named 'sync'`，说明你的 Docker 镜像太旧。拉取当前镜像，或从当前检出重新构建。

### 星级推送成功，但清除不生效

Facet 只会清除它之前推送过的星级，这份记忆保存在 Facet 数据库的 `stats_cache` 中。恢复一个较旧的数据库，或使用全新的数据库，都会丢失它：在这段空档里被清除的星级会留在 Immich 中。重新给照片评星再清除一次，或者直接在 Immich 里改。

### 星级出现在错误的照片上

Facet 会跳过有歧义的匹配，并把它们报告为 `identity_conflicts`：

- 一个 Facet 路径匹配多个 Immich 资产
- 多个 Facet 路径映射到同一个 Immich 路径

这些路径不会写入任何内容；其他照片仍可同步。

Webhook 批次更严格：如果多个 Facet 路径指向同一目标或资产 ID，批次中所有符合条件的条目都会被拒绝并计为 `failed`。请修正 `path_map` 中重叠的根目录，或设置 `owner_id` 和 `library_id`，然后重试。不要根据人名或路径猜测所有者。

Immich 的响应必须包含 `id` 和 `originalPath`，并且必须符合已配置的所有者和图库。更新成功只表示 Immich 已接受；它自己的后台元数据任务可能仍在运行。

### `rating: 0 is not valid`

Immich 服务器版本低于 3.0。请升级：Facet 需要 `null` 来清除、需要 `-1` 用于 `push.rejected`，在 2.x 上没有任何变通办法。

---

**参见：**[命令 —— Immich 同步](COMMANDS.md#immich-同步) · [配置](CONFIGURATION.md) · [编辑器互操作方案](INTEROP.md)，了解与 Lightroom、darktable 和 digiKam 的 XMP 往返。
