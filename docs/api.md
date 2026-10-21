# API 文档

TG-forwarder 提供三类 HTTP API：

- **公开消息 API**：供外部客户端使用独立 Token 拉取处理后的消息；
- **消息接入 API**：供采集软件使用独立接入 Token 提交文字消息；
- **Web 管理 API**：供内置管理后台使用，采用 Web 用户、角色和 Cookie 认证。

默认服务地址为 `http://127.0.0.1:8000`。生产环境建议通过 HTTPS 反向代理提供服务。

## 1. 公开消息 API

### 1.1 创建 API 目标

使用 `super_admin` 登录 Web，进入“对外 API”：

1. 创建 API 目标；
2. 选择允许接收的来源频道；
3. 按需设置过期时间；
4. 立即保存创建结果中显示的 Token。

Token 只在创建或重置时显示一次。服务器只保存 SHA-256 哈希，之后无法找回原 Token。
遗失后只能重置，重置会立即使旧 Token 失效。

来源也可以在“频道管理 → 来源频道 → 目标（TG / SafeW / API）”中绑定 API 目标。

### 1.2 拉取消息

```http
GET /api/public/v1/messages?cursor=0&limit=50 HTTP/1.1
Host: example.com
Authorization: Bearer tgf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

参数：

| 参数 | 类型 | 默认值 | 范围 | 说明 |
| --- | --- | --- | --- | --- |
| `cursor` | integer | `0` | `>= 0` | 只返回 `delivery_id` 大于该值的记录 |
| `limit` | integer | `50` | `1..100` | 本次最多返回的记录数 |

成功响应：

```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "delivery_id": 41,
        "created_at": "2026-07-17T12:00:01Z",
        "source_backend": "telegram",
        "source_chat_id": -1001234567890,
        "source_message_id": 321,
        "source_chat_username": "example_channel",
        "grouped_id": null,
        "text": "规则处理后的正文",
        "media_type": "text",
        "media_items": [],
        "processed_at": "2026-07-17T12:00:01.123456+00:00"
      }
    ],
    "next_cursor": 41,
    "has_more": false
  },
  "meta": {}
}
```

客户端处理建议：

1. 第一次使用 `cursor=0`；
2. 按顺序处理 `items`；
3. 只有在本地处理成功后，才持久化响应中的 `next_cursor`；
4. `has_more=true` 时可立即继续请求，否则按业务需要轮询；
5. 超时或网络错误时使用原 cursor 重试。

`delivery_id` 是持久化游标，不保证连续。不同 API 目标拥有独立可见数据集合，即使全局
ID 中间有跳号也属于正常情况。空响应会原样返回请求 cursor。

示例客户端：

```python
import requests

base_url = "https://example.com"
token = "tgf_xxx"
cursor = 0

response = requests.get(
    f"{base_url}/api/public/v1/messages",
    params={"cursor": cursor, "limit": 50},
    headers={"Authorization": f"Bearer {token}"},
    timeout=30,
)
response.raise_for_status()
data = response.json()["data"]

for item in data["items"]:
    print(item["source_chat_id"], item["text"])

cursor = data["next_cursor"]
```

### 1.3 哪些消息会进入 API

- 自动发布或规则决定为发布：规则处理完成后进入 API；
- 人工审核：只有审核任务执行“发布”后才进入 API；
- 被过滤、规则拒绝、人工拒绝或处理失败：不会进入 API；
- API 目标停用、过期或已从来源解绑：不会接收新的消息；
- 绑定 API 目标之前的历史消息不会自动回填。

Telegram/SafeW 目标发布失败但 API 投递成功时，处理结果可能属于“部分成功”；反之亦然。系统会
尽量避免一个目标故障阻断其他目标，具体结果应结合消息历史和 sender 日志核对。

### 1.4 消息字段

| 字段 | 说明 |
| --- | --- |
| `delivery_id` | 当前 API 目标的增量游标 |
| `created_at` | 投递记录创建时间 |
| `source_backend` | `telegram`、`safew` 或 `api` |
| `source_chat_id` | TG-forwarder 内部使用的来源聊天 ID |
| `source_message_id` | 来源消息内部 ID；API 接入使用接收回执 ID，外部消息 ID 见 `external_message_id` |
| `source_chat_username` | Telegram 用户名；没有时为 `null` |
| `sender` | 采集软件提供的发送者；未提供时为 `null` |
| `conversation_id` | 采集软件提供的会话 ID；API 接入省略时为 `default`，其他来源可为 `null` |
| `conversation_name` | 会话显示名称；未提供时为 `null` |
| `external_message_id` | API 接入请求中的 `message_id`；其他来源可为 `null` |
| `grouped_id` | Telegram 相册分组 ID；没有时为 `null` |
| `text` | 经过替换、链接处理、页脚和审核编辑后的最终文本 |
| `media_type` | `text`、`photo`、`video`、`document` 等 |
| `media_items` | 媒体元数据数组 |
| `processed_at` | API 投递快照生成时间 |

`media_items` 可能包含：`media_type`、`original_filename`、`mime_type`、`file_size`、
`source_message_id`、`order` 和 `file_unique_id`。出于存储与访问控制考虑，公开 API 当前不
返回本地文件路径，也不提供媒体二进制下载。

发送者与会话身份以独立字段保存，并在处理恢复、人工审核发布和 API 投递中保留。身份信息
不会自动拼接到 `text` 正文中；客户端可自行决定如何显示。

### 1.5 认证与错误

以下情况统一返回 `401`，不会说明 Token 是否真实存在：

- 缺少 `Authorization`；
- 认证方案不是 `Bearer`；
- Token 不匹配；
- API 目标已停用；
- API 目标已过期。

```json
{
  "ok": false,
  "error": {
    "code": "unauthorized",
    "message": "A valid API token is required",
    "details": {},
    "request_id": "..."
  }
}
```

常见状态码：

| 状态码 | 说明 |
| --- | --- |
| `200` | 成功，包括暂时没有新消息 |
| `401` | Token 无效、停用或过期 |
| `422` | cursor/limit 参数不合法 |
| `500` | 服务端异常，保留原 cursor 后重试 |

## 2. Web 管理 API

### 2.1 路径与 OpenAPI

管理 API 前缀为 `/api/v1`。当 `WEB_DOCS_ENABLED=true` 时可访问：

- Swagger UI：`/api/docs`
- ReDoc：`/api/redoc`
- OpenAPI JSON：`/api/openapi.json`

生产环境若不需要在线接口说明，建议设置 `WEB_DOCS_ENABLED=false`。

### 2.2 登录认证

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "your-password"
}
```

登录成功后服务器设置 HttpOnly 的访问与刷新 Cookie。浏览器或脚本应保存 Cookie：

```bash
curl -c cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your-password"}' \
  https://example.com/api/v1/auth/login

curl -b cookies.txt https://example.com/api/v1/channels
```

管理 API 的 Web 登录凭据、公开消息 API Token 与消息接入 Token 完全独立，不能混用。

角色：

| 角色 | 权限 |
| --- | --- |
| `viewer` | 查看仪表盘、频道、历史、审核内容和日志 |
| `reviewer` | viewer 权限，并可编辑、批准、拒绝和发布审核任务 |
| `super_admin` | 全部权限，包括用户、规则、频道、设置和 API 目标管理 |

### 2.3 统一响应格式

成功：

```json
{"ok": true, "data": {}, "meta": {}}
```

失败：

```json
{
  "ok": false,
  "error": {
    "code": "validation_error",
    "message": "...",
    "details": {},
    "request_id": "..."
  }
}
```

分页接口在 `data` 中返回 `items` 和 `meta`：

```json
{
  "items": [],
  "meta": {"page": 1, "page_size": 20, "total": 0, "total_pages": 0}
}
```

### 2.4 API 目标管理

所有写操作需要 `super_admin`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/api-endpoints` | 列出 API 目标 |
| `POST` | `/api/v1/api-endpoints` | 创建 API 目标并返回一次性 Token |
| `PATCH` | `/api/v1/api-endpoints/{id}` | 修改名称、启用状态或过期时间 |
| `POST` | `/api/v1/api-endpoints/{id}/rotate-token` | 重新生成或设置 Token |
| `PUT` | `/api/v1/api-endpoints/{id}/sources` | 替换允许接收的来源列表 |
| `DELETE` | `/api/v1/api-endpoints/{id}` | 删除目标及其未拉取/历史投递记录 |
| `PUT` | `/api/v1/channels/{source_id}/api-endpoints` | 从来源侧替换 API 目标绑定 |
| `PUT` | `/api/v1/channels/{source_id}/destinations` | 一次替换机器人与 API 目标绑定 |

统一绑定请求：

```json
{
  "target_ids": [1, 2],
  "api_endpoint_ids": [3]
}
```

`target_ids` 可同时引用 `target_backend=telegram` 与 `target_backend=safew` 的发送目标；旧的
`/targets` 和 `/api-endpoints` 绑定接口继续保留兼容。

创建示例：

```json
{
  "name": "downstream-service",
  "enabled": true,
  "expires_at": "2026-12-31T16:00:00Z",
  "source_ids": [1, 3]
}
```

也可在创建或重置请求中传入长度为 24–256 的自定义 `token`；Web 默认生成高熵随机 Token。

修改示例：

```json
{
  "name": "downstream-service-v2",
  "enabled": true,
  "expires_at": null
}
```

`expires_at=null` 表示永不过期。

### 2.5 管理端点索引

| 分组 | 主要路径 | 最低角色 |
| --- | --- | --- |
| 健康检查 | `GET /api/v1/health` | 无 |
| 登录 | `/api/v1/auth/*` | 无/已登录用户 |
| 仪表盘 | `GET /api/v1/dashboard` | viewer |
| 消息历史 | `GET /api/v1/history` | viewer |
| 来源频道 | `/api/v1/channels*` | 查看 viewer，修改 super_admin |
| Telegram/SafeW 目标 | `/api/v1/targets*` | 查看 viewer，修改 super_admin |
| 审核任务 | `/api/v1/reviews*` | 查看 viewer，操作 reviewer |
| 媒体预览 | `/api/v1/reviews/{id}/preview`、`/api/v1/media/*` | viewer |
| 规则与规则组 | `/api/v1/rules*`、`/api/v1/rule-groups*` | super_admin |
| API 目标 | `/api/v1/api-endpoints*` | 查看 viewer，修改 super_admin |
| 消息接入 | `/api/v1/ingest-sources*` | 查看 viewer，修改 super_admin |
| 设置 | `/api/v1/settings` | 查看 viewer，修改 super_admin |
| 系统控制 | `/api/v1/system/*` | 查看 viewer，操作 super_admin |
| 日志 | `/api/v1/logs/*`、`/api/v1/rule-execution-logs` | viewer/super_admin |
| 用户 | `/api/v1/users` | super_admin |

精确请求字段和响应 Schema 以当前版本的 `/api/openapi.json` 为准。

## 3. 安全建议

- 公开 API Token 应至少具有 128 位随机熵，不要使用常见密码；
- 为不同客户端创建不同 API 目标，不要共用 Token；
- 只绑定客户端实际需要的来源；
- 设置合理的过期时间并定期轮换；
- 仅通过 HTTPS 传输 Token；
- 不要把 Token 写进 URL、日志、Git 或前端公开代码；
- 对外拉取 API 目前没有业务级确认/删除接口，客户端必须可靠保存 cursor；
- 反向代理可增加请求频率限制、IP 白名单和访问日志脱敏。

## 4. 消息接入 API

### 4.1 创建来源与配置路由

使用 `super_admin` 登录 Web 的“消息接入”页面，创建接入来源并立即保存 Token。新来源默认
启用，发布模式为 `review`。通过“配置来源路由”进入频道管理，为该来源绑定 Telegram、
SafeW 或对外 API 目标，并选择发布模式。可以只绑定对外 API 目标。

请在提交消息前配置有效目标。接入成功只表示已进入队列，不表示规则、审核或下游发布已经
成功；未配置目标的消息会在消息历史中显示路由失败。排查及重试方式见 4.4。

每个接入 Token 仅对应一个 API 来源；路由由该 Token 对应的来源配置决定。接入 JSON 不接受
内部 `source_id`、`source_chat_id`、目标 ID 或其他路由字段。接入 Token 使用 `tgfi_` 前缀，
与用于拉取消息的 `tgf_` Token 独立，Web 管理员登录凭据也不能用于提交消息。

### 4.2 提交文字消息

```http
POST /api/ingest/v1/messages HTTP/1.1
Host: example.com
Authorization: Bearer tgfi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Content-Type: application/json

{
  "message_id": "capture-000001",
  "conversation_id": "group-001",
  "conversation_name": "项目讨论群",
  "sender": "Alice",
  "text": "采集到的消息内容",
  "timestamp": "2026-10-21T01:30:00+08:00"
}
```

| 字段 | 必填 | 约束与含义 |
| --- | --- | --- |
| `message_id` | 是 | 非空白字符串，最长 128 字符；在同一来源、同一会话内保持唯一 |
| `conversation_id` | 否 | 非空白字符串，最长 128 字符，默认 `default`；多个会话必须使用稳定且不同的 ID |
| `conversation_name` | 否 | 会话显示名称，最长 256 字符 |
| `sender` | 否 | 发送者显示名称或标识，最长 256 字符 |
| `text` | 是 | 非空白字符串，最长 65,536 字符；原文进入现有处理流程 |
| `timestamp` | 否 | 包含时区的 ISO 8601 时间；省略时使用服务器接收时间 |

v1 只接收 JSON 文字消息。不支持图片、附件或未知字段；缺少时区的时间也会被拒绝。
发送者、会话名称、会话 ID 和外部消息 ID 保存为结构化元数据，不会自动加到转发正文前面。
接收上限不等于目标发送上限：现有正文处理器和 Bot 目标仍可能按 4,096 字符截断长文本。
需要保留完整长文本时，请核对处理器配置并使用对外 API 目标验证实际输出。

成功入队的新消息返回 `202 Accepted`：

```json
{
  "ok": true,
  "data": {
    "receipt_id": 42,
    "source_id": 7,
    "message_id": "capture-000001",
    "conversation_id": "group-001",
    "status": "queued",
    "duplicate": false
  },
  "meta": {}
}
```

`receipt_id` 同时作为处理管线的内部 `source_message_id`；请求中的 `message_id` 在历史、
审核详情及公开消息 API 中以 `external_message_id` 暴露。请保留回执用于排查。

### 4.3 幂等、冲突与安全重试

幂等键为 `(API 来源, conversation_id, message_id)`。不同来源或不同会话可以使用相同的外部
消息 ID；来自不同会话或发送者的独立消息不会仅因正文相同而被内容去重合并。

- 相同幂等键和相同提交内容再次请求时，返回原回执；已入队的重复请求为 `200`，且 `duplicate=true`；
- 相同幂等键下，正文、发送者、会话名称或提供的时间发生变化，返回 `409`；
- 首次省略 `timestamp` 的请求，重试时继续省略，不会因服务器接收时间变化而发生冲突；
- `503` 表示队列暂不可用或入队结果不确定。等待后使用相同幂等键、相同内容重试，未成功入队的回执可继续入队；
- 网络断开或响应丢失时，同样使用原请求重试，不要为了重试生成新 `message_id`。

| 状态码 | 说明 |
| --- | --- |
| `202` | 新消息或此前未入队的回执已被队列接受 |
| `200` | 相同消息已入队，返回原回执及 `duplicate=true` |
| `401` | 接入 Token 无效、停用、过期、已撤销，或对应来源被停用 |
| `409` | 幂等键相同，但提交内容冲突 |
| `422` | JSON 字段、长度、文字或时区不合法 |
| `503` | 无法确认入队成功，可使用原请求安全重试 |

`queued` 是接收阶段状态，不是发布状态。系统通过持久化回执、消息登记和目标投递约束抑制
重复处理；数据库与外部 Bot 发送之间没有分布式事务，不能保证外部副作用严格恰好一次。

### 4.4 查看结果与处理失败

消息历史和审核详情显示 `sender`、`conversation_id`、`conversation_name`、`external_message_id`。
管理 API `GET /api/v1/history` 支持 `sender` 和 `conversation_id` 精确匹配过滤，例如：

```http
GET /api/v1/history?sender=Alice&conversation_id=group-001
```

若接入已成功但路由配置错误，应先修复来源启用状态和有效目标，再重试下游处理。
已入队回执的重复提交只返回原回执，不会重新执行已经失败的处理。对 `failed`/`retrying`
任务，可由配置了 Bot 管理权限的管理员执行现有 `/retry_failed` 命令；系统页“仅重入队”用于
恢复 `retrying`、`pending_publish` 等可恢复状态，不包含已终止的 `failed`。重试后核对消息历史、
审核状态和实际下游结果，不要以 HTTP `200`/`202` 判断已经发布。

### 4.5 接入凭据管理 API

读取需要 `viewer` 或以上角色，所有写操作需要 `super_admin`，使用 Web 登录 Cookie 认证。

| 方法 | 路径 | 请求与行为 |
| --- | --- | --- |
| `GET` | `/api/v1/ingest-sources` | 返回 `data.items` 列表，不返回完整 Token |
| `POST` | `/api/v1/ingest-sources` | `{name, enabled?, expires_at?}`，创建来源和凭据，返回来源字段及一次性 `token` |
| `PATCH` | `/api/v1/ingest-sources/{id}` | 修改 `name`、`enabled`、`expires_at`；`expires_at=null` 清除过期时间 |
| `POST` | `/api/v1/ingest-sources/{id}/rotate-token` | 生成新 Token，旧 Token 立即失效；返回来源字段及一次性 `token` |
| `DELETE` | `/api/v1/ingest-sources/{id}` | 撤销接入凭据，保留来源配置、历史与接收回执 |

来源字段为 `id`、`name`、`source_id`、`source_chat_id`、`token_prefix`、`enabled`、`expires_at`、
`last_access_at`、`created_at`。`source_id` 用于现有频道路由管理；`id` 用于上述凭据管理路径。
`name` 为非空白字符串，最长 128 字符；`expires_at` 为带时区的时间或 `null`。v1 不接受自定义 Token。

Token 仅在创建或轮换时返回一次，服务器只保存 SHA-256 哈希与显示前缀。凭据启用状态与
频道来源启用状态分别控制；两者均启用且凭据未过期时才能接收新消息。

### 4.6 升级数据库

消息接入依赖 Alembic 迁移 `0010_api_ingest`。升级应用前备份数据库，启动新版 Web/sender 前
完成 `alembic upgrade head`。Compose 可使用 `docker compose run --rm migrate` 执行迁移，再
启动业务服务；检查迁移成功后再测试接入。完整升级步骤见[部署文档](deployment.md)。
