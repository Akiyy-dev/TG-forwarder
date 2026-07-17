# 部署文档

推荐使用 Docker Compose 部署。Compose 将四个业务职责拆为 `web`、`sender`、
`telegram-receiver` 和 `safew-receiver`，并使用 PostgreSQL、Redis 与一次性 `migrate`
服务提供基础设施。

## 1. 部署模式

| 模式 | 接收来源 | 适用场景 |
| --- | --- | --- |
| 完整 Compose | Telegram + SafeW | Linux 云服务器、需要 SafeW 私密群通知监听 |
| Telegram-only Compose | Telegram | 不需要 SafeW 或暂时没有 SafeW 安装包 |
| 单进程 Python | Telegram | 本地开发、调试、小规模自托管 |

SafeW 接收必须运行 Linux 图形环境。本项目在 SafeW 容器内提供 Xvfb、Openbox、x11vnc、
noVNC 与通知桥，服务器本身不需要安装桌面环境。

## 2. 服务器要求

完整 Compose 建议：

- x86_64 Linux；
- 2 核 CPU、4 GB 内存或以上；
- 至少 10 GB 可用磁盘，媒体量较大时需要更多；
- Docker Engine 与 Docker Compose 插件；
- 可以访问 Telegram、镜像仓库和必要的软件源；
- SafeW Release 镜像，或合法取得的 `image/tsetup.3.6.2.tar.xz`。

仅 Telegram 模式通常可降低资源需求。部署前确认：

```bash
docker version
docker compose version
uname -m
```

## 3. 获取项目与选择环境文件

```bash
git clone https://github.com/Akiyy-dev/TG-forwarder.git
cd TG-forwarder
cp .env.compose.example .env
chmod 600 .env
```

Compose **只使用仓库根目录的 `.env`**，它应来自 `.env.compose.example`。
`.env.example` 是单进程 Python 模式模板，不适合直接用于 Compose。两者的完整区别见
[配置参考](configuration.md)。

## 4. 必填配置

至少修改：

```dotenv
POSTGRES_PASSWORD=足够长且只含字母数字的随机值
WEB_SECRET_KEY=足够长的随机值
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD_HASH=

TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+8613800000000
BOT_TOKEN=123456:your_bot_token

NOVNC_PASSWORD=另一个强密码
```

`TELEGRAM_API_ID` 与 `TELEGRAM_API_HASH` 来自
[my.telegram.org](https://my.telegram.org)。Bot 必须在每个 Telegram 目标频道拥有发消息权限。

数据库密码会嵌入连接 URL，建议使用长字母数字字符串，避免 `@`、`:`、`/`、`#` 等需要
URL 编码的字符。

### 4.1 生成 Web 管理员密码哈希

先确保应用镜像可用，然后运行：

```bash
docker compose run --rm --no-deps web python -m scripts.hash_password
```

输出示例：

```dotenv
WEB_ADMIN_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...'
```

把输出的整行填入 `.env`，**保留单引号**。如果删除引号，Compose 会把哈希中的 `$argon2id`、
`$v`、`$m` 等当作环境变量，从而出现 “variable is not set” 警告并破坏哈希。

只有数据库中还没有任何用户时，Web 才会用该哈希创建首个 `super_admin`。

## 5. 获取或构建镜像

### 5.1 使用 Release 镜像

`.env.compose.example` 默认使用：

```text
ghcr.io/akiyy-dev/tg-forwarder:<IMAGE_TAG>
ghcr.io/akiyy-dev/tg-forwarder-safew:<IMAGE_TAG>
```

建议固定版本，而不是长期使用 `latest`：

```dotenv
IMAGE_TAG=v1.2.3
```

拉取：

```bash
docker compose pull
```

若出现 `unauthorized`：

1. 在 GitHub Packages 中确认镜像是否公开；或
2. 使用具有 `read:packages` 权限的 Personal Access Token 登录：

```bash
echo 'YOUR_GITHUB_TOKEN' | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
docker compose pull
```

### 5.2 本地构建

应用镜像：

```bash
docker compose build web sender telegram-receiver migrate
```

SafeW 镜像要求仓库中存在：

```text
image/tsetup.3.6.2.tar.xz
```

然后执行：

```bash
docker compose build safew-receiver
```

安装包不属于本仓库。请从合法来源取得，并确认构建与再分发许可。

## 6. 首次部署

### 6.1 检查 Compose

```bash
docker compose config --quiet
```

如果该命令有 `$argon2id` 等警告，先修复密码哈希引号，不要继续启动。

### 6.2 创建 Telegram Session

```bash
docker compose run --rm telegram-receiver python -m scripts.create_session
```

根据提示输入手机号、验证码和可选的两步验证密码。不要把验证码或两步验证密码写入
`.env`。Session 保存在 `telegram-session` 卷，容器重建不会要求重新登录。

### 6.3 启动完整服务

使用 Release 镜像：

```bash
docker compose up -d --no-build
docker compose ps
```

使用本地构建镜像：

```bash
docker compose up -d
docker compose ps
```

`migrate` 正常完成后状态为 `Exited (0)`，这是预期行为，不是故障。

### 6.4 只启动 Telegram

没有 SafeW 镜像或安装包时：

```bash
docker compose up -d postgres redis migrate web sender telegram-receiver
```

不要启动 `safew-receiver`。

## 7. 访问 Web 与 SafeW

Compose 默认只映射到服务器回环地址：

- Web：`127.0.0.1:${WEB_PORT:-8000}`
- noVNC：`127.0.0.1:${NOVNC_PORT:-6080}`

从本机建立隧道：

```bash
ssh -L 8000:127.0.0.1:8000 -L 6080:127.0.0.1:6080 your-user@your-server
```

访问：

- `http://127.0.0.1:8000`
- `http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`

在 noVNC 中输入 `NOVNC_PASSWORD`，登录 SafeW 并打开桌面消息通知。确认需要监听的会话
没有静音。关闭浏览器和 SSH 隧道后，SafeW 仍会在容器内运行。

noVNC 不应直接暴露到公网。

## 8. 首次业务配置

进入 Web 后：

1. 在“频道管理”添加 Telegram 目标；
2. 检测 Bot 权限并发送测试消息；
3. 添加 Telegram 来源，或等待 SafeW 新会话自动登记；
4. 为来源绑定 Telegram/API 目标；
5. 选择发布模式；
6. 配置规则并用测试功能验证；
7. 从审核队列或消息历史确认处理结果。

频道 ID、来源与目标绑定只保存在 PostgreSQL/SQLite，环境变量不会提供回退目标。详细操作
见[使用指南](user-guide.md)。

## 9. SafeW 捕获验证

首次建议保持：

```dotenv
SAFEW_ALLOWED_CHATS=
SAFEW_CAPTURE_ALL_APPS=false
```

监听日志：

```bash
docker compose logs -f safew-receiver sender
```

向测试会话发送文字消息。正常情况下 SafeW 接收端会发布进入 Redis 的事件，sender 会自动
登记 SafeW 来源并按默认 `review` 模式创建审核任务。

确认实际会话标题后，可以限制为精确标题：

```dotenv
SAFEW_ALLOWED_CHATS=私密群A,私密群B
```

应用变更：

```bash
docker compose up -d --force-recreate safew-receiver
```

如果日志中的应用名称不是 `SafeW`，可短暂启用 `SAFEW_CAPTURE_ALL_APPS=true` 采样通知；
确认后填写 `SAFEW_APP_NAMES` 并恢复为 `false`，避免捕获其他应用的通知。

## 10. HTTPS 反向代理

生产环境建议只代理 Web，不直接代理 noVNC。Nginx 示例：

```nginx
server {
    listen 443 ssl http2;
    server_name forwarder.example.com;

    ssl_certificate     /etc/letsencrypt/live/forwarder.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/forwarder.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
    }
}
```

同时设置：

```dotenv
WEB_SECURE_COOKIES=true
```

如需让应用信任代理来源信息，再评估并设置 `WEB_TRUST_PROXY=true`。公网部署还应配置防火墙、
登录限速、备份和日志策略。

## 11. 更新与回滚

### 11.1 更新 Release 镜像

```bash
# 修改 .env 中的 IMAGE_TAG
docker compose pull
docker compose up -d --no-build
docker compose ps
```

`migrate` 会在业务容器启动前执行 `alembic upgrade head`。

### 11.2 更新单个容器

```bash
docker compose pull web
docker compose up -d --no-build web

docker compose pull sender
docker compose up -d --no-build sender

docker compose pull telegram-receiver
docker compose up -d --no-build telegram-receiver

docker compose pull safew-receiver
docker compose up -d --no-build safew-receiver
```

应用镜像实际由多个服务共享。数据库迁移变更时，建议执行完整 `docker compose up -d`。

回滚前必须确认旧版本是否兼容当前数据库 Schema。优先先备份数据库，再固定回上一版本
`IMAGE_TAG`。不要随意执行 Alembic downgrade。

## 12. 持久化与备份

| 卷 | 内容 | 重要性 |
| --- | --- | --- |
| `postgres-data` | 用户、频道、规则、审核、历史、API Token 哈希与投递记录 | 必须备份 |
| `redis-data` | Redis Streams 与未处理事件 | 建议备份或确保可接受丢失 |
| `media-data` | Telegram 临时媒体与审核预览文件 | 建议备份活动审核所需文件 |
| `telegram-session` | Telegram 用户登录会话 | 必须保护 |
| `safew-profile` / `safew-home` | SafeW 登录与桌面资料 | 必须保护 |
| `history-data` | 可选 JSON 历史落盘 | 按需备份 |
| `safew-novnc` | noVNC 运行资料 | 可重建 |

PostgreSQL 逻辑备份示例：

```bash
docker compose exec -T postgres \
  pg_dump -U forwarder -d forwarder -Fc > forwarder-$(date +%F).dump
```

恢复应先在测试环境验证。普通更新不要执行：

```bash
docker compose down -v
```

`-v` 会删除数据库、Telegram Session 和 SafeW 登录资料。

如在 Compose 中启用设置页的“历史落盘”，请同时把历史目录设置为 `/data/history`，否则
相对路径写入容器文件系统，不会进入 `history-data` 持久卷。

## 13. 单进程 Python 模式

该模式仅包含 Telegram 接收，不包含 SafeW 桌面容器。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# 编辑 .env
alembic upgrade head
python -m scripts.hash_password
# 将输出的 WEB_ADMIN_PASSWORD_HASH 写入 .env
python -m scripts.create_session
python -m app.main
```

也可以用 `python -m scripts.create_admin` 直接在数据库中创建或更新用户。生产环境仍建议
使用 PostgreSQL、进程管理器和 HTTPS 反向代理。

## 14. 部署后检查

```bash
docker compose ps
docker compose logs --tail=100 web sender telegram-receiver safew-receiver
curl http://127.0.0.1:8000/api/v1/health
```

预期：

- `postgres`、`redis`、`web`、`sender`、需要的接收端为运行状态；
- `migrate` 为 `Exited (0)`；
- 健康检查返回 `ok: true`；
- Web“系统状态”能看到业务进程心跳；
- Telegram 测试目标可成功发送消息。

遇到问题请参考[故障排查](troubleshooting.md)。
