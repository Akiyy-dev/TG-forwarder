# TG-forwarder

TG-forwarder 是一个带 Web 管理后台的消息处理与转发系统。它使用 Telegram 用户账号或
SafeW Linux 客户端接收消息，依次执行去重、文本处理、关键词规则和人工审核，最终发布
到 Telegram 或 SafeW 频道，也可交付给带 Token 的对外拉取 API。

## 主要能力

- Telegram 用户账号监听：支持账号本身有权访问的公开或私密频道、群组；
- SafeW 通知监听：在 Linux 轻量桌面中运行 SafeW，通过桌面通知获取新消息；
- Web 管理：来源与目标绑定、规则管理、审核、消息历史、API 目标和系统状态；
- 多种发布模式：自动发布、人工审核、规则决定和暂停；
- 多目标路由：一个来源可同时绑定多个 Telegram、SafeW Bot 和 API 目标；
- 对外 API：独立 Token、来源白名单、启停和过期时间，支持游标增量拉取；
- Docker Compose：Web、发送端、Telegram 接收端和 SafeW 接收端独立维护；
- 持久化与恢复：PostgreSQL、Redis Streams、Alembic 迁移及处理状态恢复。

## 消息流

```text
Telegram 用户账号 ─> telegram-receiver ─┐
                                         ├─> Redis Streams ─> sender
SafeW 桌面通知 ─────> safew-receiver ────┘                    │
                                                               ├─> 规则 / 审核
浏览器 ─> web ─> PostgreSQL <──────────────────────────────────┤
                                                               ├─> Telegram Bot 目标
                                                               ├─> SafeW Bot 目标
                                                               └─> Token API 队列
```

频道路由只以 Web 和数据库中的配置为准。`.env` 与 `config/channels.yaml` 不再配置来源
频道或目标频道。SafeW 新会话可自动登记为来源，默认进入人工审核模式。

## 快速开始

推荐在 Linux 服务器上使用 Docker Compose。完整前置条件、镜像选择、SafeW 安装包、
反向代理和升级步骤见[部署文档](docs/deployment.md)。

```bash
git clone https://github.com/Akiyy-dev/TG-forwarder.git
cd TG-forwarder
cp .env.compose.example .env
chmod 600 .env

# 编辑 .env 后检查 Compose 展开结果
docker compose config --quiet

# 使用可访问的 Release 镜像；本地构建则改用 docker compose build
docker compose pull

# 生成 Web 管理员密码哈希，并将输出整行填回 .env
docker compose run --rm --no-deps web python -m scripts.hash_password

# 首次创建 Telegram 用户会话
docker compose run --rm telegram-receiver python -m scripts.create_session

docker compose up -d --no-build
docker compose ps
```

Web 和 noVNC 默认只监听服务器 `127.0.0.1`。可通过 SSH 隧道访问：

```bash
ssh -L 8000:127.0.0.1:8000 -L 6080:127.0.0.1:6080 your-user@your-server
```

- Web：`http://127.0.0.1:8000`
- SafeW noVNC：`http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`

首次登录 Web 后，按“发送目标 → 来源频道 → 统一目标绑定 → 规则/审核”的顺序配置。SafeW
发送目标还需要在 sender 环境中设置 `SAFEW_BOT_TOKEN`。
详见[使用指南](docs/user-guide.md)。

## 对外 API

在 Web 的“对外 API”页面创建 API 目标并绑定来源。Token 只显示一次，服务器只保存哈希。

```bash
curl -H 'Authorization: Bearer YOUR_TOKEN' \
  'https://example.com/api/public/v1/messages?cursor=0&limit=50'
```

客户端应保存响应中的 `next_cursor`，下次从该游标继续拉取。接口只暴露已经完成规则与
审核流程的消息。当前返回处理后的文本与媒体元数据，不提供媒体文件二进制下载。

完整请求、响应、认证和错误说明见 [API 文档](docs/api.md)。

## 文档

1. [API 文档](docs/api.md)：公开消息 API、Web 管理 API、认证和响应格式；
2. [部署文档](docs/deployment.md)：Compose、本地运行、SafeW、升级、备份和反向代理；
3. [使用指南](docs/user-guide.md)：频道、发布模式、规则、审核、历史和 API 目标；
4. [配置参考](docs/configuration.md)：两个环境变量模板的区别及各配置项；
5. [架构说明](docs/architecture.md)：容器职责、消息生命周期和持久化边界；
6. [故障排查](docs/troubleshooting.md)：镜像、Session、Compose、SafeW 和 API 常见问题；
7. [开发与发布](docs/development.md)：本地开发、测试、迁移和 release-please。

也可从 [docs/README.md](docs/README.md) 进入文档目录。

## SafeW 限制

SafeW 当前通过 Linux 桌面通知获取消息，不使用官方 User API，因此：

- 只能读取当前 SafeW 账号本来有权查看、且确实产生桌面通知的新消息；
- 无法补取历史消息；静音会话、应用未运行期间的消息可能无法捕获；
- 通知未展示正文时无法还原正文；
- 当前不获取媒体原文件、编辑事件或删除事件。

以上限制只影响普通账号接收。SafeW 目标发送使用官方 Bot API，与桌面通知接收链路独立。

Telegram 接收端仍支持原有的文本和媒体下载流程。

## 安全提示

- 不要提交 `.env`、Telegram Session、手机号、验证码、Token 或 SafeW 登录资料；
- 生产环境应使用 HTTPS，并设置 `WEB_SECURE_COOKIES=true`；
- 不要把 noVNC 直接暴露到公网，优先使用 SSH 隧道或带认证的反向代理；
- 仅监听账号本身有权访问的内容，并遵守平台条款、版权要求和适用法律。

## 许可证与发布

项目使用 release-please 与 Conventional Commits 管理版本发布。SafeW 客户端安装包不包含
在仓库中；构建或分发 SafeW 镜像前，请自行确认客户端许可。
