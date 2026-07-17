# TG-forwarder

将 Telegram 或 SafeW 中当前账号有权读取的新消息，经规则处理、审核和去重后，由
Telegram Bot 发布到目标频道。

> SafeW 接收目前基于 Linux 桌面通知，只能获取通知中实际显示的会话标题和正文；
> 不支持历史消息、静音会话和媒体原文件。

## 运行方式

| 方式 | 适用场景 | 说明 |
| --- | --- | --- |
| 单进程 | 只监听 Telegram | Telethon 用户账号接收，aiogram Bot 发布，可选 Web 管理面板 |
| Docker Compose | Telegram + SafeW | Web、发送端、Telegram 接收端、SafeW 接收端分开维护 |

Compose 架构：

```text
Telegram 用户账号 ─┐                         ┌─> Telegram 目标频道
                   ├─> Redis ─> sender ─────┤
SafeW 桌面通知 ────┘               ↑         └─> 带 Token 的对外 API
                                   │
浏览器 ─> web ─> PostgreSQL ───────┘
```

## 快速开始：Docker Compose

适用于仅有 Linux 云服务器、需要登录 SafeW 私密群账号的场景。服务器建议至少
2 核 CPU、4 GB 内存，并安装 Docker Engine 与 Docker Compose。

```bash
cp .env.compose.example .env
# 编辑 .env，填写 Telegram、Bot、Web、数据库和 noVNC 配置

docker compose build
docker compose run --rm --no-deps web python -m scripts.hash_password
# 将生成的密码哈希填回 .env

docker compose run --rm telegram-receiver python -m scripts.create_session
docker compose up -d
```

SafeW 首次登录通过 SSH 隧道访问 noVNC：

```bash
ssh -L 6080:127.0.0.1:6080 your-user@your-server
```

然后打开
`http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`，登录 SafeW 并开启消息通知。

完整部署、来源筛选、单容器更新和排障说明见
[SafeW + Telegram Compose 部署指南](docs/safew-compose.md)。

正式 Release 会将应用镜像发布到 GHCR；SafeW 镜像需要先配置受保护的安装包下载地址和
SHA-256 校验值。镜像名称、标签和拉取方式也在上述部署指南中说明。

## 快速开始：仅 Telegram

需要 Python 3.11+，推荐 Python 3.12。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env

python -m scripts.create_session
python -m app.main
```

Windows 激活虚拟环境使用 `.venv\Scripts\activate`。

主要配置：

| 变量 | 用途 |
| --- | --- |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | [my.telegram.org](https://my.telegram.org) 应用凭据 |
| `BOT_TOKEN` | 发布到 Telegram 目标频道的 Bot |
| `BOT_ADMIN_IDS` | 可使用 Bot 管理命令的 Telegram 用户 ID |
| `BOT_POLLING_ENABLED` | 是否启用 Bot 管理命令轮询；设为 `false` 仍可正常发布 |
| `SAFEW_ALLOWED_CHATS` | 允许监听的 SafeW 会话标题，留空表示全部 |

所有可用变量与示例值见 [.env.example](.env.example) 和
[.env.compose.example](.env.compose.example)。

## 管理与开发

Bot 管理命令包括 `/status`、`/sources`、`/stats`、`/retry_failed`、
`/pause` 和 `/resume`。Web 面板提供来源、规则、审核队列和运行状态管理。
Telegram 来源、Telegram 目标以及二者的绑定关系只保存在 PostgreSQL/SQLite 中，统一在
Web 的“频道管理”页面配置；`.env` 与 `config/channels.yaml` 不再参与频道路由。SafeW
捕获到的新会话会自动加入来源列表，但仍需在 Web 中绑定目标。“消息历史”显示所有处理
记录，不受审核队列或可选历史落盘开关影响。

“对外 API”可创建带独立 Token、启用状态和过期时间的拉取目标，并绑定允许接收的来源。
也可以在“频道管理”的来源行中绑定 API 目标。客户端使用以下方式增量读取已经完成规则
与审核流程的消息；`next_cursor` 应由客户端持久化并用于下一次请求：

```bash
curl -H 'Authorization: Bearer YOUR_TOKEN' \
  'https://your-host/api/public/v1/messages?cursor=0&limit=50'
```

Token 只在创建或重置时显示一次，服务端仅保存 SHA-256 哈希。重置 Token 会立即使旧
Token 失效；停用或到期的 API 目标不能继续拉取，也不会接收新的消息。
如果同一个 Bot Token 还被其他程序监听，请设置 `BOT_POLLING_ENABLED=false`，避免
Telegram `getUpdates` 冲突；这只会关闭上述管理命令，不影响消息发布。

Compose 模式下，Web 对 Telegram 来源的启用或停用会在约 5 秒内由接收端自动加载；
接收端会短暂重启以更新 Telethon 的频道过滤器。直接运行独立接收端时没有 Compose
自动拉起能力，应由 systemd 等进程管理器托管，或在来源变更后手动重启。

```bash
# 后端检查
ruff check app scripts tests
ruff format --check app scripts tests
mypy app
pytest -q

# 前端检查
cd web
npm ci
npm run build
```

## 安全与限制

- 仅监听账号本身有权访问的群组或频道，不会绕过私密群权限。
- 不要提交 `.env`、Telegram Session、Token、手机号、验证码或 SafeW 登录资料。
- noVNC 和 Web 默认只绑定服务器的 `127.0.0.1`，建议通过 SSH 隧道访问。
- 请遵守平台条款、来源频道规则、版权要求及适用法律。

项目使用 release-please 与 Conventional Commits 管理版本发布。
