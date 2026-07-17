# SafeW + Telegram 四容器部署

该方案把业务职责拆为四个独立容器：

```text
SafeW 桌面通知 ─→ safew-receiver ─┐
                                  ├─→ Redis Streams ─→ sender ─→ Telegram 目标频道
Telegram 用户会话 ─→ telegram-receiver ┘                 ↑
                                                         │ 发布命令
浏览器 ─→ web ────────────────────────────────────────────┘

PostgreSQL：频道、规则、审核任务、处理状态
共享媒体卷：telegram-receiver → sender → web 预览
```

`safew-receiver` 内部包含 Xvfb、Openbox、x11vnc、noVNC、SafeW 和通知桥，但对 Compose 来说仍是一个可单独维护的业务容器。`sender` 是唯一允许调用 Telegram Bot 发布消息的容器。

## 当前实现范围

第一阶段支持监听 SafeW 正常登录账号能够收到的桌面通知，并提取：

- 会话标题（映射为来源群组）；
- 通知正文；
- 通知时间和少量桌面通知元数据；
- 自动在后台登记新发现的 SafeW 来源，默认进入人工审核模式。

它不会绕过 SafeW 的账号权限。私密群必须是该 SafeW 账号本来就能查看、且会产生桌面通知的群。

当前不保证 SafeW 历史消息、编辑/删除事件、被静音会话、应用未运行期间的消息和媒体原文件。桌面通知里若只有“有新消息”而没有正文，也无法还原正文。Telegram 接收端原有的文字和媒体下载流程则继续保留。

当前 Compose 只应运行一个 `sender` 副本，以维持同一来源内的处理顺序。Web 中依赖
Telethon 客户端的“扫描账号频道”功能在拆分模式下暂不可用；来源可通过
`SOURCE_CHANNELS`、`config/channels.yaml` 或收到的 SafeW 通知自动登记。目标权限检查和
测试消息会异步交给 `sender` 执行。

## 服务器要求

- x86_64 Linux 云服务器，建议至少 2 核 CPU、4 GB 内存；
- Docker Engine 与 Docker Compose 插件；
- 仓库根目录存在 `image/tsetup.3.6.2.tar.xz`；
- 防火墙无需开放 6080，noVNC 默认只绑定服务器 `127.0.0.1`。

SafeW 镜像基于 Debian Bookworm，使用轻量 Openbox 桌面。容器为 `/dev/shm` 分配 512 MB，SafeW 账号数据保存在独立卷中，重建容器后无需重新登录。

## 首次配置

复制环境变量模板：

```bash
cp .env.compose.example .env
chmod 600 .env
```

至少填写以下值：

- `POSTGRES_PASSWORD`、`WEB_SECRET_KEY`、`NOVNC_PASSWORD`；数据库密码会嵌入连接
  URL，建议只使用足够长的字母和数字组合；
- `TELEGRAM_API_ID`、`TELEGRAM_API_HASH`；
- `BOT_TOKEN`、`TARGET_CHANNEL_ID`；如需 Bot 管理命令，再填写 `BOT_ADMIN_IDS` 并保持
  `BOT_POLLING_ENABLED=true`。同一 Bot Token 被其他程序监听时应设为 `false`，发布功能
  不受影响；
- `SOURCE_CHANNELS`，或在 `config/channels.yaml` 中填写 Telegram 来源。

先检查配置并构建镜像：

```bash
docker compose config --quiet
docker compose build
```

再在容器中生成 Web 管理员密码哈希：

```bash
docker compose run --rm --no-deps web python -m scripts.hash_password
```

把输出的整行复制到 `.env`。Argon2 哈希包含 `$`，必须保留输出中的单引号。

创建并持久化 Telegram 用户 Session：

```bash
docker compose run --rm telegram-receiver python -m scripts.create_session
```

验证码和两步验证密码只在交互提示中输入，不要写入 `.env`。Session 会保存在 `telegram-session` 卷。

Telegram 来源以 Web/PostgreSQL 中的启用状态为准；修改后接收端会在约 5 秒内正常退出，
并由 Compose 的 `restart: unless-stopped` 自动拉起，以重新加载 Telethon 过滤器。若所有
Telegram 来源均关闭，接收端会保持空闲且不会退化为监听账号内全部频道。
仍使用 `SOURCE_CHANNELS` 或 `config/channels.yaml` 作为首次导入来源时，Web 会阻止删除
最后一个 Telegram 来源；请将它关闭，或先移除旧式配置后再删除。

启动服务：

```bash
docker compose up -d
docker compose ps
```

## 使用 Release 镜像

创建 GitHub Release 后，工作流会将主应用镜像发布到：

```text
ghcr.io/akiyy-dev/tg-forwarder:<版本>
```

SafeW 客户端安装包没有提交到仓库，因此 SafeW 镜像默认不发布。仓库管理员需要配置：

- Repository variable：`BUILD_SAFEW_IMAGE=true`；
- Actions secret：`SAFEW_PACKAGE_URL`，可下载安装包的 HTTPS 地址；
- Actions secret：`SAFEW_PACKAGE_SHA256`，安装包的 SHA-256 校验值。

配置完成后，Release 工作流还会发布：

```text
ghcr.io/akiyy-dev/tg-forwarder-safew:<版本>
```

每次发布会生成 Release tag、纯版本号、主次版本号和 `latest` 标签。建议在 `.env` 中固定
Release tag，例如 `IMAGE_TAG=v1.2.3`，然后直接拉取并启动：

```bash
docker compose pull
docker compose up -d --no-build
```

若 GHCR 包为私有，请先使用有 `read:packages` 权限的令牌执行 `docker login ghcr.io`。
发布 SafeW 镜像前，请自行确认 SafeW 客户端的再分发许可。

## 登录 SafeW

从自己的电脑建立 SSH 隧道：

```bash
ssh -L 6080:127.0.0.1:6080 your-user@your-server
```

然后在本机浏览器打开：

```text
http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale
```

输入 `.env` 中的 `NOVNC_PASSWORD`，在桌面中正常登录 SafeW。保持 SafeW 的桌面消息通知开启，并确认要监听的群未被静音。完成后可以关闭浏览器和 SSH 隧道；容器中的桌面与 SafeW 会继续运行。

noVNC 不应直接暴露到公网。若必须通过反向代理访问，应额外配置 HTTPS、访问认证和 IP 白名单。

## 首次联调

先保持 `SAFEW_ALLOWED_CHATS` 为空，让通知桥观察所有 SafeW 会话。向一个测试群发送文字消息，同时查看日志：

```bash
docker compose logs -f safew-receiver sender
```

正常情况下会依次看到 `incoming_event_published`、来源自动登记和发送端处理日志。新 SafeW 来源默认是 `review`，可在 Web 后台确认标题、目标频道并审核发布。

确认标题后，可用精确会话标题收窄范围：

```dotenv
SAFEW_ALLOWED_CHATS=私密群A,私密群B
```

修改后只重启 SafeW 接收容器：

```bash
docker compose up -d --force-recreate safew-receiver
```

若日志中的 `app_name` 不是 SafeW，可临时设置 `SAFEW_CAPTURE_ALL_APPS=true` 采样一次；确认真实名称后将其写入 `SAFEW_APP_NAMES`，并恢复为 `false`，避免捕获无关桌面通知。

## 单独维护

```bash
# 只重建 Web
docker compose build web && docker compose up -d web

# 只重建发送端
docker compose build sender && docker compose up -d sender

# 只重建 Telegram 接收端
docker compose build telegram-receiver && docker compose up -d telegram-receiver

# 只重建 SafeW 桌面接收端（账号卷不删除）
docker compose build safew-receiver && docker compose up -d safew-receiver
```

不要用 `docker compose down -v` 做普通更新；`-v` 会删除 PostgreSQL、Telegram Session 和 SafeW 登录资料等持久卷。

建议备份：

- `postgres-data`：业务数据库；
- `telegram-session`：Telegram 用户登录会话；
- `safew-profile` 与 `safew-home`：SafeW 登录和桌面资料；
- `config/`：频道、规则和运行时配置。

## 常见排查

- noVNC 能打开但 SafeW 未出现：`docker compose logs safew-receiver`，检查缺失库、显示服务或 SafeW 启动错误。
- SafeW 能看到消息但没有捕获：确认系统通知开关、群静音状态、`SAFEW_APP_NAMES` 和 `SAFEW_ALLOWED_CHATS`。
- 捕获成功但未发布：新来源默认需要审核；同时检查 `sender` 日志、Bot 的目标频道管理员权限和全局暂停状态。
- Telegram 接收端提示未授权：重新运行 Session 创建命令，不要删除原卷后再启动。
- Web/noVNC 从远程无法直连：这是预期安全设置，请使用 SSH 隧道或安全反向代理。
