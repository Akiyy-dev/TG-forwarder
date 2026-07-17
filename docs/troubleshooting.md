# 故障排查

先执行以下只读检查：

```bash
docker compose config --quiet
docker compose ps
docker compose logs --tail=200 migrate web sender telegram-receiver safew-receiver
curl -sS http://127.0.0.1:8000/api/v1/health
```

不要把完整 `.env`、`docker compose config`、Telegram Session、验证码、Token 或 Cookie
发送到公开渠道。

## 1. Compose 与镜像

### 1.1 Argon2 变量未设置

现象：

```text
The "argon2id" variable is not set
The "v" variable is not set
The "m" variable is not set
```

原因：`WEB_ADMIN_PASSWORD_HASH` 中的 `$` 被 Compose 当成变量插值。

修复：重新生成哈希，并保留输出的单引号：

```bash
docker compose run --rm --no-deps web python -m scripts.hash_password
```

```dotenv
WEB_ADMIN_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...'
```

然后验证：

```bash
docker compose config --quiet
```

### 1.2 GHCR unauthorized / No such image

现象：

```text
error from registry: unauthorized
No such image: ghcr.io/akiyy-dev/tg-forwarder-safew:latest
```

处理：

1. 确认 `.env` 的 `APP_IMAGE`、`SAFEW_IMAGE`、`IMAGE_TAG` 拼写；
2. 确认对应 GitHub Package 和标签存在；
3. 私有包使用 `read:packages` Token 登录；
4. 或在本地构建镜像。

```bash
echo 'TOKEN' | docker login ghcr.io -u USER --password-stdin
docker compose pull
```

本地 SafeW 构建还必须存在 `image/tsetup.3.6.2.tar.xz`。

### 1.3 migrate 自动停止

如果日志最后是：

```text
Running upgrade ...
```

且容器状态为 `Exited (0)`，说明迁移成功。`migrate` 是一次性任务，成功后本来就会停止。

只有非 0 退出、SQL 错误或业务容器一直等待 migrate 时才需要处理：

```bash
docker compose logs migrate
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic heads
```

### 1.4 修改了代码但容器仍是旧版本

- Release 模式：确认 `IMAGE_TAG` 已更新并执行 `docker compose pull`；
- 本地构建：执行 `docker compose build <service>`；
- 然后重建容器：

```bash
docker compose up -d --force-recreate web sender telegram-receiver
```

浏览器仍显示旧页面时强制刷新或清除站点缓存。

## 2. Telegram

### 2.1 Telegram session is not authorized

现象：

```text
RuntimeError: Telegram session is not authorized; create the session first
```

重新创建 Session：

```bash
docker compose run --rm telegram-receiver python -m scripts.create_session
docker compose up -d telegram-receiver
```

确认命令与正常接收端使用同一个 `telegram-session` 卷。不要只在宿主机生成一个没有挂载进
容器的 `.session` 文件。

如果账号开启两步验证，除了验证码还需输入密码。连续失败可能触发 Telegram 风控，应停止
频繁尝试并稍后再试。

### 2.2 Telegram 接收端运行但没有消息

检查：

1. Web 中来源确实存在且启用；
2. 来源聊天 ID 正确；
3. 登录账号是该群/频道成员；
4. 修改来源后接收端已经重启并重新加载过滤器；
5. 没有把 SafeW 内部 ID 当成 Telegram ID。

```bash
docker compose logs --tail=200 telegram-receiver
docker compose restart telegram-receiver
```

如果所有 Telegram 来源都停用，接收端不会监听账号全部频道，这是安全设计。

### 2.3 目标权限检测失败

确认：

- Bot 已加入目标频道；
- Bot 是管理员或至少拥有发消息权限；
- 目标聊天 ID 正确；
- sender 正常运行并能访问 Telegram；
- `BOT_TOKEN` 属于预期 Bot。

先在 Web 发送测试消息，再查看：

```bash
docker compose logs --tail=200 sender
```

### 2.4 getUpdates 冲突

同一个 Bot Token 只能由一个长轮询消费者稳定调用 `getUpdates`。如果已有其他程序监听该
Bot，设置：

```dotenv
BOT_POLLING_ENABLED=false
```

重新创建 sender。该选项不影响 Bot 向目标频道发送消息。

## 3. SafeW 与 noVNC

### 3.1 noVNC 无法访问

Compose 默认只监听服务器 `127.0.0.1`，远程直接访问失败是预期行为。使用 SSH 隧道：

```bash
ssh -L 6080:127.0.0.1:6080 your-user@your-server
```

打开：

```text
http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale
```

若本机端口被占用，可改为 `-L 16080:127.0.0.1:6080` 并访问 16080。

### 3.2 noVNC 打开但 SafeW 没启动

```bash
docker compose ps safew-receiver
docker compose logs --tail=300 safew-receiver
docker compose exec safew-receiver pgrep -af SafeW
```

常见原因：安装包架构/版本不匹配、共享内存不足、客户端依赖变化、资料卷权限问题。不要先
删除资料卷；先备份并查看日志。

### 3.3 SafeW 能看到消息但没有捕获

检查：

- SafeW 桌面通知已开启；
- 会话未静音；
- 通知确实展示正文；
- `SAFEW_APP_NAMES` 与通知的应用名匹配；
- `SAFEW_ALLOWED_CHATS` 使用精确会话标题；
- `safew-receiver` 和 Redis 正常。

临时采样：

```dotenv
SAFEW_CAPTURE_ALL_APPS=true
```

```bash
docker compose up -d --force-recreate safew-receiver
docker compose logs -f safew-receiver
```

确认真实应用名后立即恢复 `false`，避免捕获其他桌面通知。

### 3.4 捕获了通知但 Web 没有来源

确认 sender 正常、`SAFEW_AUTO_REGISTER_SOURCES=true`，并查看：

```bash
docker compose logs --tail=200 safew-receiver sender
```

新 SafeW 来源默认进入 `review` 且没有目标。自动登记成功不等于已经发布，仍需在 Web 绑定
Telegram 或 API 目标。

## 4. Web、频道与审核

### 4.1 无法登录 Web

检查 `WEB_ADMIN_PASSWORD_HASH` 是否正确、是否在数据库已有用户之前生成。查看：

```bash
docker compose logs --tail=100 web
```

如果数据库已经有用户，修改环境变量哈希不会覆盖现有密码。可以交互创建或更新管理员：

```bash
docker compose run --rm web python -m scripts.create_admin --username admin
```

### 4.2 HTTPS 后登录成功又立即退出

确认：

```dotenv
WEB_SECURE_COOKIES=true
```

反向代理必须传递正确的 Host 和 `X-Forwarded-Proto`。如果在纯 HTTP 环境误设为 `true`，
浏览器不会发送 Secure Cookie。

### 4.3 来源开关无法重新打开

Telegram 来源如果已确认不可达，Web 会阻止直接启用。先确认登录账号仍能访问该聊天，刷新
频道状态后再启用。SafeW 来源不执行 Telegram 可达性检测。

### 4.4 来源有消息但没有发布

按顺序检查：

1. 来源是否启用；
2. 发布模式是否为 `paused`；
3. 是否至少绑定一个当前有效的 Telegram/API 目标；
4. 是否命中 reject/require_review 规则；
5. 全局是否暂停；
6. 审核队列是否存在任务；
7. 消息历史的状态、原因和错误；
8. sender 日志。

环境变量中的旧来源/目标配置不会生效，必须在 Web 频道管理中绑定。

### 4.5 规则决定的消息不在审核队列

`rule_based` 在没有规则要求审核时会直接发布，这是正常行为。请到“消息历史”查看全部处理
记录；审核队列只展示进入过人工审核的任务。

### 4.6 历史落盘开关导致前端异常

该问题已在加入独立消息历史与 API 目标的版本中修复。升级 Web 镜像后强制刷新浏览器。
“历史落盘”控制 JSON 文件，“消息历史”读取数据库，两者互不依赖。

### 4.7 审核发布提示 revision conflict

任务已被另一个审核员或自动任务修改。刷新审核详情，检查最新文本和操作历史，再重新执行。
不要重复提交旧 revision。

## 5. 公开 API

### 5.1 始终返回 401

确认：

- 使用 `Authorization: Bearer TOKEN`，不是 Cookie 或 Web 密码；
- Token 没有多余空格/换行；
- API 目标启用；
- 过期时间仍有效；
- Token 没被重置；
- 请求的是 `/api/public/v1/messages`。

服务器对错误、停用和过期 Token 都统一返回 401，不会泄露目标是否存在。

### 5.2 API 返回空 items

检查：

- API 目标已绑定正确来源；
- 消息发生在绑定之后；
- 消息已经完成发布，而不是仍在审核；
- 消息没有被过滤或拒绝；
- cursor 没有大于最新 delivery ID；
- 消息历史中的 API 投递数是否大于 0。

API 不会回填绑定前的历史消息。

### 5.3 重复收到消息

服务端对同一 API 目标和处理消息设置唯一约束。客户端看到重复通常是因为没有在本地处理
成功后持久化 `next_cursor`。消费逻辑应按 `delivery_id` 幂等。

### 5.4 收不到媒体文件

当前公开 API 只返回处理后文本和媒体元数据，不提供媒体二进制或本地路径。这是当前实现
范围，不是 Token 权限问题。

## 6. Redis、数据库与队列

### 6.1 sender 不消费消息

```bash
docker compose ps redis sender
docker compose logs --tail=200 redis sender
docker compose exec redis redis-cli ping
docker compose exec redis redis-cli xlen forwarder:incoming
```

Redis 返回 `PONG` 但队列持续增长时，重点检查 sender 的数据库、Bot Token、规则或媒体
错误。不要直接删除 Stream，除非已确认可以丢弃未处理消息并完成备份。

### 6.2 数据库连接失败

检查 PostgreSQL 健康状态与 `.env` 密码：

```bash
docker compose ps postgres
docker compose logs --tail=200 postgres migrate web sender
docker compose exec postgres pg_isready -U forwarder -d forwarder
```

如果修改了 `POSTGRES_PASSWORD`，已有 PostgreSQL 卷中的用户密码不会自动跟随环境变量修改。
应恢复原密码或在数据库内明确更新用户密码，不能只改 `.env`。

### 6.3 磁盘增长

检查：

```bash
docker system df
docker volume ls
docker compose exec postgres psql -U forwarder -d forwarder -c \
  "select pg_size_pretty(pg_database_size('forwarder'));"
```

API delivery 与消息历史存于 PostgreSQL，当前不会在客户端读取后自动删除。应按业务审计和
保留要求制定数据库清理、归档与备份策略。

## 7. 收集诊断信息

可以安全提供：

- 项目版本或 `IMAGE_TAG`；
- `docker compose ps`；
- 已脱敏的相关容器日志；
- 错误发生时间和操作步骤；
- 来源平台、发布模式和目标类型；
- 浏览器控制台错误（删除 Cookie、Token 和正文）。

必须删除：

- `.env` 中的全部密钥；
- Telegram 手机号、验证码、Session；
- Bot Token、API Token、Cookie；
- SafeW 登录资料；
- 私密群名称和敏感正文。
