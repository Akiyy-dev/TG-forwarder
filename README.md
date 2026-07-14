# TG-forwarder

Telegram 频道消息转发与处理系统：用 **Telethon 普通用户账号** 监听已加入的来源频道，经可插拔规则管道处理后，再用 **aiogram Bot** 发布到目标频道（重新发送，不显示原始转发来源）。

## 工作流程

```text
来源频道 → Telethon 监听 → 消息标准化 → 过滤/替换/链接/Footer/去重
        → 异步队列 Worker → aiogram Bot 发布 → 目标频道
```

## 为什么需要用户账号 + Bot

| 角色 | 原因 |
|------|------|
| Listener（用户账号） | Bot 无法可靠监听任意你「已加入」的频道帖子；用户账号可以读取其有权访问的频道更新 |
| Publisher（Bot） | 以频道管理员身份稳定发帖，支持文本/媒体/相册，并提供管理命令 |

本项目**不会**绕过私有频道权限、付费限制或 Telegram 访问控制。请仅监听你有权查看的内容，并遵守来源频道转载规则、Telegram 平台条款与版权要求。

## 准备 Telegram API 凭据

1. 打开 [https://my.telegram.org](https://my.telegram.org)
2. 使用手机号登录
3. 创建应用，获得 `api_id` 与 `api_hash`
4. 填入 `.env`（切勿提交到 Git）

## 创建 Bot 并配置目标频道

1. 与 [@BotFather](https://t.me/BotFather) 对话创建 Bot，获得 `BOT_TOKEN`
2. 将 Bot 添加为目标频道**管理员**，并授予「发布消息」权限
3. 将你的 Telegram 数字用户 ID 填入 `BOT_ADMIN_IDS`（可用 `@userinfobot` 等工具查询）

## 配置说明

复制示例文件：

```bash
cp .env.example .env
```

关键变量：

| 变量 | 说明 |
|------|------|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | my.telegram.org 凭据 |
| `TELEGRAM_PHONE` | 仅用于首次 Session 登录提示；验证码不要写入 `.env` |
| `TELEGRAM_SESSION_PATH` | Session 路径（不含 `.session` 后缀亦可，Telethon 会自动追加） |
| `BOT_TOKEN` | BotFather Token |
| `BOT_ADMIN_IDS` | 逗号分隔的管理员用户 ID |
| `TARGET_CHANNEL_ID` | 目标频道 ID（通常为 `-100...`） |
| `SOURCE_CHANNELS` | 来源：`@username` 或数字 ID，逗号分隔 |
| `TEXT_REPLACEMENTS` | `旧=>新` 多组用 `\|` 分隔 |
| `MESSAGE_FOOTER` | 文末尾注 |
| 过滤开关 | `ENABLE_*` 系列 |

完整示例见 [.env.example](.env.example)。

## 如何查询频道 ID

```bash
python -m scripts.resolve_channels
```

脚本会：

1. 列出当前用户账号可访问的频道
2. 解析 `SOURCE_CHANNELS` 中的 username / ID
3. 检查来源是否可读
4. 检查 Bot 对目标频道是否具备发布权限
5. 输出建议写入 `.env` 的频道 ID（不打印 Token / api_hash）

## 首次生成 Telethon Session

**切勿**把验证码或两步验证密码写入 `.env`。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env 填入 api_id / api_hash / bot_token 等

python -m scripts.create_session
```

按提示输入手机号、验证码、（如有）两步验证密码。Session 写入 `data/sessions/`。

## 安装与运行（Linux 服务器）

推荐使用 Python 3.12（兼容 3.11+），在服务器上直接运行进程（可用 `systemd` / `tmux` / `supervisord` 保活）。

```bash
git clone https://github.com/Akiyy-dev/TG-forwarder.git
cd TG-forwarder
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env

python -m scripts.create_session
alembic upgrade head   # 可选；首次启动也会 create_all
python -m app.main
```

开发时可设 `APP_ENV=development` 获得更易读的控制台日志。

数据目录（请定期备份）：

- `./data/sessions` — Telethon Session
- `./data/database` — SQLite
- `./data/downloads` — 临时媒体

### systemd 示例

```ini
# /etc/systemd/system/tg-forwarder.service
[Unit]
Description=TG-forwarder
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tgforwarder
WorkingDirectory=/opt/TG-forwarder
Environment=PATH=/opt/TG-forwarder/.venv/bin
ExecStart=/opt/TG-forwarder/.venv/bin/python -m app.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tg-forwarder
sudo journalctl -u tg-forwarder -f
```

## 更新与数据库迁移

```bash
git pull
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
# 若用 systemd：sudo systemctl restart tg-forwarder
```

## Bot 管理命令

仅 `BOT_ADMIN_IDS` 中的用户可用：

| 命令 | 作用 |
|------|------|
| `/status` | 监听器 / 队列 / 暂停 / 最近错误 |
| `/sources` | 来源频道列表 |
| `/stats` | 过滤 / 发布 / 失败计数 |
| `/retry_failed` | 重试失败任务 |
| `/pause` / `/resume` | 暂停/恢复发布（仍可记录收到的消息） |
| `/help` | 帮助 |

## 常见错误

| 现象 | 处理 |
|------|------|
| Session not authorized | 重新运行 `python -m scripts.create_session` |
| FloodWait | 程序会按 Telegram 要求等待；降低并发与频率 |
| Bot 无法发帖 | 确认 Bot 是目标频道管理员且有发帖权 |
| 相册被拆成多条 | 检查 `grouped_id` 是否正常；查看日志 `album_flushed` |
| 重复发布 | 查库 `processed_messages` 唯一约束与状态；勿清空 DB 后重放 |
| 队列积压 | 调高 `MAX_CONCURRENCY` 或检查发布错误 |

## 安全事项

- 不要把 `.env`、`*.session`、Token、手机号、验证码提交到 Git
- 日志已对 Token / api_hash / 密码等字段脱敏
- Session 文件权限尽量限制为仅所有者可读写
- 管理命令会校验管理员 ID
- 下载文件名会做安全化，防止路径穿越

## 备份

定期备份：

```bash
cp -a data/sessions data/sessions.bak
cp -a data/database data/database.bak
```

丢失 Session 需要重新登录；丢失数据库可能导致历史幂等信息丢失并存在重复发布风险。

## 如何新增 Processor

1. 在 `app/processors/` 实现带 `name` 与 `async def process(message, context)` 的类
2. 在 `build_default_pipeline()` 中按顺序注册
3. 用配置开关控制启用
4. 添加单元测试

处理器应只依赖 `NormalizedMessage`，不要直接依赖 Telethon / aiogram 类型。

## 日志与健康状态

- 生产环境结构化 JSON 日志输出到 stdout（可用 journald / 进程管理器采集）
- 健康检查：`python -m scripts.healthcheck`
- Bot：`/status`

## 发布

本仓库使用 [release-please](https://github.com/googleapis/release-please) 与 [Conventional Commits](https://www.conventionalcommits.org/)。

推送到 `main` 且包含 `feat:` / `fix:` 等可发布提交后，会自动维护 Release PR；合并该 PR 后会打 tag、更新 `CHANGELOG.md` 与版本号并创建 GitHub Release。

## 开发与质量检查

```bash
ruff check app scripts tests
ruff format --check app scripts tests
mypy app
pytest
```

## 许可证与合规

使用本软件时请自行确保：

- 你有权读取并转发相关内容
- 遵守 Telegram ToS 与适用法律
- 尊重版权与来源频道规定
