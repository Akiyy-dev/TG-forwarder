# API 文档

TG-forwarder 提供两类 HTTP API：

- **公开消息 API**：供外部客户端使用独立 Token 拉取处理后的消息；
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

来源也可以在“频道管理 → 来源频道 → 目标（TG / API）”中绑定 API 目标。

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
| `source_backend` | `telegram` 或 `safew` |
| `source_chat_id` | TG-forwarder 内部使用的来源聊天 ID |
| `source_message_id` | 来源消息 ID；SafeW 通知会生成稳定的内部 ID |
| `source_chat_username` | Telegram 用户名；没有时为 `null` |
| `grouped_id` | Telegram 相册分组 ID；没有时为 `null` |
| `text` | 经过替换、链接处理、页脚和审核编辑后的最终文本 |
| `media_type` | `text`、`photo`、`video`、`document` 等 |
| `media_items` | 媒体元数据数组 |
| `processed_at` | API 投递快照生成时间 |

`media_items` 可能包含：`media_type`、`original_filename`、`mime_type`、`file_size`、
`source_message_id`、`order` 和 `file_unique_id`。出于存储与访问控制考虑，公开 API 当前不
返回本地文件路径，也不提供媒体二进制下载。

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

管理 API 的 Web 登录凭据与公开消息 API Token 完全独立，不能混用。

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
- API 目前没有业务级确认/删除接口，客户端必须可靠保存 cursor；
- 反向代理可增加请求频率限制、IP 白名单和访问日志脱敏。
