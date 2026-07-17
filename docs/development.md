# 开发与发布

## 1. 技术栈

- Python 3.11+，CI 与镜像使用 Python 3.12；
- FastAPI、SQLAlchemy Async、Alembic；
- Telethon 用户接收、aiogram Bot 发布；
- PostgreSQL / SQLite、Redis Streams；
- React 19、TypeScript、Vite、Mantine、TanStack Query；
- pytest、Ruff、Mypy、oxlint。

## 2. 后端开发环境

Linux/macOS：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env` 后初始化：

```bash
alembic upgrade head
python -m scripts.create_session
python -m scripts.create_admin
python -m app.main
```

单进程使用 SQLite 即可开发。涉及 PostgreSQL 方言、Redis 消费、容器心跳或进程拆分时，
应使用 Compose 做集成验证。

## 3. 前端开发环境

```bash
cd web
npm ci
npm run dev
```

默认 Vite 页面需要连接后端 API。可以先运行 `python -m app.main`，并根据 Vite 配置或
`WEB_ALLOWED_ORIGINS` 允许开发 Origin。

生产构建：

```bash
npm run lint
npm run build
```

应用 Dockerfile 会在 Node 构建阶段生成 `web/dist`，再复制进 Python 运行镜像，由 FastAPI
提供静态资源和 SPA fallback。

## 4. 项目结构

```text
app/
  api/                 FastAPI 应用、路由、依赖与响应模型
  auth/                Web 用户认证、角色与密码
  database/            SQLAlchemy 模型、Session 与 Repository
  entrypoints/         Compose 拆分进程入口
  listeners/           Telegram、SafeW 通知接收
  messaging/           Redis Streams 事件模型与总线
  processors/          消息处理管线
  publishers/          Telegram Bot 发布
  review/              审核状态机、版本与发布
  rules/               规则匹配和执行
  services/            频道、消息、API delivery 等业务服务
migrations/versions/   Alembic 迁移
web/src/               React 管理后台
docker/                应用与 SafeW 镜像
scripts/               Session、管理员与密码辅助脚本
tests/                 后端测试
docs/                  项目文档
```

## 5. 质量检查

提交前运行：

```bash
ruff check app scripts tests
ruff format --check app scripts tests
mypy app
pytest -q

cd web
npm run lint
npm run build
```

自动修复格式：

```bash
ruff check app scripts tests --fix
ruff format app scripts tests
```

不要为了通过测试修改或删除无关用户数据、`.env`、Session 或 Docker 卷。

## 6. 测试策略

测试使用临时 SQLite 数据库和模拟 Telegram Bot。新增功能至少覆盖：

- 成功路径；
- 权限/RBAC；
- 禁用、过期、解绑等边界；
- 幂等和重复请求；
- 旧状态恢复；
- API 响应和数据库最终状态。

涉及消息路由时，应分别覆盖：

- 只有 Telegram 目标；
- 只有 API 目标；
- Telegram + API 多目标；
- auto、review、rule_based、paused；
- SafeW 与 Telegram 来源标识。

涉及 Compose/SafeW 的功能还需要真实 Linux 环境手工验证，因为单元测试无法模拟完整桌面
通知栈和第三方客户端行为。

## 7. 数据库迁移

修改 ORM 模型时必须新增 Alembic migration：

```bash
alembic revision -m "describe change"
```

检查并手工完善生成内容，设置正确的 `down_revision`。至少验证：

```bash
alembic upgrade head
alembic current
alembic heads
```

还应在一个全新临时数据库上从 0001 连续升级到 head。SQLite 与 PostgreSQL 对 DDL 的支持
不同，复杂字段修改应使用 Alembic batch 或在 PostgreSQL 中额外验证。

迁移原则：

- 不在 migration 中依赖当前 ORM 模型；
- 新增非空列时提供安全默认或分阶段迁移；
- 先迁移 Schema，再启用依赖新列的代码；
- downgrade 不应伪造无法重建的数据；
- 不修改已经发布的旧 migration。

## 8. API 变更

新增路由时：

1. 使用统一 `Envelope` 或项目错误格式；
2. 明确最低角色；
3. 给列表接口加分页与上限；
4. 不在响应中泄露密钥、本地路径或内部异常栈；
5. 添加 API 测试；
6. 更新 [API 文档](api.md)；
7. 若前端依赖，更新 `web/src/api/` 类型和页面。

公开 API 需要特别考虑 Token 轮换、过期、来源隔离、重试与客户端幂等。

## 9. Docker 验证

应用镜像：

```bash
docker build -f docker/app.Dockerfile -t tg-forwarder:dev .
```

SafeW 镜像：

```bash
test -f image/tsetup.3.6.2.tar.xz
docker build -f docker/safew.Dockerfile -t tg-forwarder-safew:dev .
```

Compose：

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

不要把 SafeW 安装包或构建产生的登录资料提交到 Git。

## 10. 提交规范

项目使用 Conventional Commits。常见前缀：

- `feat:` 新功能；
- `fix:` 修复；
- `docs:` 文档；
- `refactor:` 不改变行为的重构；
- `test:` 测试；
- `ci:` 工作流；
- `chore:` 维护任务。

一次提交应保持主题单一，并包含必要测试和文档。

## 11. CI

`.github/workflows/ci.yml` 在 PR 和 main push 上执行：

- Python 3.12 安装；
- Ruff lint 与格式检查；
- Mypy；
- pytest；
- Node 22 安装；
- 前端 TypeScript 与生产构建。

本地通过不代表容器一定可运行；依赖文件、Docker build context 和迁移仍需单独验证。

## 12. release-please

`.github/workflows/release-please.yml` 监听 `main`：

1. 普通 Conventional Commit 合并到 main 后，release-please 创建或更新 Release PR；
2. Release PR 汇总版本和 `CHANGELOG.md`；
3. 合并 Release PR 后创建 GitHub Release/tag；
4. `release_created=true` 触发镜像构建。

应用镜像自动发布到：

```text
ghcr.io/<owner>/<repo>:<tag>
```

生成 Release tag、纯版本、主次版本和 `latest` 标签，平台为 `linux/amd64`。

## 13. SafeW Release 镜像

SafeW 包不提交仓库。仓库维护者需要配置：

| 类型 | 名称 | 内容 |
| --- | --- | --- |
| Repository variable | `BUILD_SAFEW_IMAGE` | `true` 才构建 SafeW 镜像 |
| Actions secret | `SAFEW_PACKAGE_URL` | 安装包 HTTPS 下载地址 |
| Actions secret | `SAFEW_PACKAGE_SHA256` | 安装包 SHA-256 |

注意：`BUILD_SAFEW_IMAGE` 放在 **Repository variables**，下载 URL 和 SHA-256 放在
**Actions secrets**。工作流下载后先校验哈希，再构建
`ghcr.io/<owner>/<repo>-safew:<tag>`。

发布前必须确认安装包来源、版本、架构和再分发许可。

## 14. 文档维护

代码行为变化时同步更新：

- 根目录 README 的项目定位与入口；
- 对应专题文档；
- 环境变量模板；
- OpenAPI/API 示例；
- 故障排查中的旧错误信息；
- 架构图和容器职责。

文档中的命令应从仓库根目录可执行，示例密钥必须是明显的占位值。
