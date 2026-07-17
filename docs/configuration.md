# 配置参考

TG-forwarder 有三类配置来源：

1. 环境变量：进程启动配置和密钥；
2. Web/数据库：频道、目标、绑定、规则、用户、审核和 API 目标；
3. `config/runtime.yaml`：Web“设置”页面写入的非敏感运行时设置。

## 1. 两个 `.env` 模板的区别

| 模板 | 用途 | 数据库 | 进程模型 |
| --- | --- | --- | --- |
| `.env.compose.example` | Docker Compose | PostgreSQL | 四个业务容器 + 基础设施 |
| `.env.example` | `python -m app.main` | 默认 SQLite | 单进程 Telegram 模式 |

部署 Compose 时执行：

```bash
cp .env.compose.example .env
```

不要把 `.env.example` 复制给 Compose。Compose 会自动读取仓库根目录 `.env`，容器内的
`DATABASE_URL`、`REDIS_URL` 等由 `compose.yaml` 统一设置。

## 2. Compose 变量

### 2.1 镜像

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_IMAGE` | `ghcr.io/akiyy-dev/tg-forwarder` | Web、sender、Telegram 接收端和迁移镜像 |
| `SAFEW_IMAGE` | `ghcr.io/akiyy-dev/tg-forwarder-safew` | SafeW 桌面接收镜像 |
| `IMAGE_TAG` | `latest` | 镜像标签，生产建议固定 Release tag |

### 2.2 数据库与 Web

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | 是 | PostgreSQL 密码；建议只用长字母数字字符串 |
| `WEB_SECRET_KEY` | 是 | Web Token 签名密钥，应使用高熵随机值 |
| `WEB_ADMIN_USERNAME` | 否 | 首个管理员用户名，默认 `admin` |
| `WEB_ADMIN_PASSWORD_HASH` | 首次部署是 | 首个管理员 Argon2 哈希，必须保留单引号 |
| `WEB_SECURE_COOKIES` | 生产是 | HTTPS 部署设为 `true` |
| `WEB_PORT` | 否 | 主机回环地址上的 Web 端口，默认 `8000` |

生成哈希：

```bash
docker compose run --rm --no-deps web python -m scripts.hash_password
```

正确：

```dotenv
WEB_ADMIN_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...'
```

错误：

```dotenv
WEB_ADMIN_PASSWORD_HASH=$argon2id$v=19$m=65536,t=3,p=4$...
```

错误写法会触发 Compose 变量插值警告。

### 2.3 Telegram

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `TELEGRAM_API_ID` | Telegram 接收端是 | my.telegram.org 的 API ID |
| `TELEGRAM_API_HASH` | Telegram 接收端是 | my.telegram.org 的 API Hash |
| `TELEGRAM_PHONE` | 否 | 创建 Session 时的默认手机号 |
| `BOT_TOKEN` | sender 是 | Telegram Bot Token，用于目标发布 |
| `BOT_ADMIN_IDS` | 见下 | 允许使用 Bot 管理命令的 Telegram 用户 ID，逗号分隔 |
| `BOT_POLLING_ENABLED` | 否 | 是否轮询 Bot 管理命令，默认 `true` |

当 `BOT_POLLING_ENABLED=true` 时，`BOT_ADMIN_IDS` 至少需要一个 ID。如果同一个 Bot Token
被其他程序调用 `getUpdates`，应设为 `false`；这只关闭 Bot 管理命令，不影响向目标发布。

### 2.4 SafeW

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NOVNC_PASSWORD` | 无 | noVNC 登录密码，完整部署必填 |
| `NOVNC_PORT` | `6080` | 主机回环地址上的 noVNC 端口 |
| `SAFEW_APP_NAMES` | `SafeW` | 允许的桌面通知应用名称，逗号分隔 |
| `SAFEW_ALLOWED_CHATS` | 空 | 精确允许的会话标题，空表示不过滤标题 |
| `SAFEW_CAPTURE_ALL_APPS` | `false` | 调试时捕获所有应用通知，常态应关闭 |
| `SAFEW_AUTO_REGISTER_SOURCES` | `true` | sender 是否自动登记新 SafeW 来源 |

`SAFEW_ALLOWED_CHATS` 使用通知中显示的会话标题，不是 Telegram ID，也不是 SafeW 内部 ID。

### 2.5 日志

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Python 日志级别，如 `DEBUG`、`INFO`、`WARNING` |

生产环境通常使用 `INFO`。排障时临时改为 `DEBUG`，完成后恢复，避免日志过量或包含不必要
的消息元数据。

## 3. 单进程变量

`.env.example` 包含完整 `Settings` 配置。主要分组如下。

### 3.1 基础与存储

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `production` | `development` 时使用开发日志格式 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `DATABASE_URL` | SQLite 路径 | SQLAlchemy 异步连接 URL |
| `RULES_CONFIG_PATH` | `./config/rules.yaml` | 启动时按名称 upsert 的规则种子文件 |
| `DOWNLOAD_DIR` | `./data/downloads` | Telegram 媒体临时目录 |
| `MAX_DOWNLOAD_SIZE_MB` | `100` | 单文件最大下载大小 |
| `TEMP_FILE_TTL_MINUTES` | `60` | 临时媒体清理时间 |

### 3.2 队列与重试

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ALBUM_WAIT_SECONDS` | `2.5` | Telegram 相册初始等待时间 |
| `ALBUM_MAX_WAIT_SECONDS` | `20.0` | 相册最大等待时间 |
| `QUEUE_MAXSIZE` | `1000` | 单进程内存队列上限 |
| `MAX_CONCURRENCY` | `3` | 全局并发处理数 |
| `MAX_RETRIES` | `3` | 发布最大重试次数 |
| `RETRY_BASE_DELAY_SECONDS` | `2` | 重试退避基数 |

Compose 模式还使用 `REDIS_URL`、stream 名称、consumer group、block/claim 时间等 Redis
配置。默认值已适配 `compose.yaml`，一般无需修改。

### 3.3 处理器

| 变量 | 说明 |
| --- | --- |
| `ENABLE_KEYWORD_FILTER` | 启用环境变量关键词过滤器 |
| `BLOCKED_KEYWORDS` / `ALLOWED_KEYWORDS` | 逗号分隔关键词 |
| `KEYWORD_CASE_SENSITIVE` | 是否区分大小写 |
| `ALLOW_EMPTY_TEXT` | 处理后空文本是否允许继续 |
| `ENABLE_TEXT_REPLACE` | 启用文本替换 |
| `TEXT_REPLACEMENTS` | `旧文本=>新文本|另一个=>替换` |
| `ENABLE_LINK_FILTER` | 启用链接处理 |
| `REMOVE_SOURCE_LINKS` | 删除来源频道链接 |
| `REMOVE_ALL_LINKS` | 删除所有链接 |
| `REMOVE_TELEGRAM_INVITES` | 删除 Telegram 邀请链接 |
| `BLOCKED_LINK_DOMAINS` / `ALLOWED_LINK_DOMAINS` | 逗号分隔域名 |
| `ENABLE_FOOTER` / `MESSAGE_FOOTER` | 启用并设置统一页脚 |
| `ENABLE_DUPLICATE_FILTER` | 启用内容去重 |
| `DUPLICATE_CONTENT_WINDOW_HOURS` | 已发布内容去重时间窗口 |

Web“规则管理”中的数据库规则与这些基础处理器共同作用。规则种子文件只会按名称 upsert，
不会删除在 Web 中新建的规则。

### 3.4 Web

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_ENABLED` | `true` | 单进程是否启动 Web |
| `WEB_HOST` | `0.0.0.0` | 容器/进程监听地址 |
| `WEB_PORT` | `8000` | 监听端口 |
| `WEB_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | 访问 Cookie 有效时间 |
| `WEB_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | 刷新 Cookie 有效时间 |
| `WEB_ALLOWED_ORIGINS` | localhost | CORS Origin，逗号分隔 |
| `WEB_SECURE_COOKIES` | `false` | 仅通过 HTTPS 发送 Cookie |
| `WEB_TRUST_PROXY` | `false` | 是否信任反向代理信息 |
| `WEB_DOCS_ENABLED` | `true` | 是否开放 Swagger/ReDoc/OpenAPI |
| `WEB_LOGIN_RATE_LIMIT` | `10` | 登录窗口内最大尝试次数 |
| `WEB_LOGIN_RATE_WINDOW_SECONDS` | `60` | 登录限速窗口秒数 |

## 4. Web 与数据库配置

以下内容不应写进 `.env`：

- Telegram 来源频道；
- Telegram 目标频道；
- 来源与目标的多对多绑定；
- API 目标及其来源绑定；
- 来源启用状态与发布模式；
- Web 用户和角色；
- Web 规则、审核任务和消息历史。

这些内容统一在 Web 管理，并保存到数据库。SafeW 捕获到的新会话可自动添加来源，但仍需
在 Web 中确认发布模式与目标绑定。

## 5. `config/runtime.yaml`

Web“设置”页面将非敏感覆盖值写入 `config/runtime.yaml`。Compose 将宿主机 `./config`
挂载给应用容器，因此文件能跨容器重建保留。

当前常用项包括：

- 审核自动批准开关与时间；
- 审核批准后的自动发布时间；
- 可选 JSON 历史落盘开关、目录与每来源上限；
- 相册等待、临时文件时间、页脚和基础处理器开关；
- Web 主机、端口和数据库 URL 等需要重启的项目。

设置页会显示 `hot` 或 `restart` 提示。标记为 `restart` 的项目必须重启相关服务。密钥只读
展示，不能从 Web 回写。

“消息历史”导航读取数据库中的 `processed_messages`，与 `history_enabled` 无关；后者只
控制额外的 JSON 文件落盘。Compose 启用 JSON 落盘时，应把 `history_dir` 设置为
`/data/history`，该路径对应 `history-data` 持久卷；默认相对路径更适合单进程运行。

## 6. 配置检查

Compose：

```bash
docker compose config --quiet
docker compose config | sed -n '/services:/,$p'
```

不要把完整 `docker compose config` 输出贴到公开 Issue，它可能包含展开后的密钥。

单进程：

```bash
python -c "from app.config import Settings; print(Settings())"
```

`Settings.__repr__` 会掩码主要密钥，但仍应谨慎处理日志和截图。
