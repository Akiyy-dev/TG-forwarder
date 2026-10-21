# 架构说明

## 1. 设计目标

TG-forwarder 将“接收消息”“处理与发布”“管理界面”分开，使 Telegram、SafeW 和 Web/API 接入
可以独立升级或重启。系统同时保证：

- 接收端尽快把事件持久化到 Redis，避免长时间处理阻塞监听；
- 同一来源内按顺序处理，跨来源可并发；
- 规则、审核和目标路由以数据库为准；
- Telegram、SafeW Bot 与 API 目标互不依赖，支持部分成功；
- 已处理消息、审核操作和规则执行均可追溯。

## 2. 组件

### 2.1 业务容器

| 服务 | 职责 | 不能做的事 |
| --- | --- | --- |
| `web` | FastAPI、React 静态页面、用户认证、管理 API、文字接入认证与入队、发布命令 | 不直接监听 Telegram，不直接调用 Bot 发布 |
| `sender` | 处理器、规则、审核发布、Telegram/SafeW Bot、API 投递、恢复任务 | 不运行 SafeW 桌面，不维护 Telegram 用户监听连接 |
| `telegram-receiver` | Telethon 用户会话、来源过滤、相册聚合、媒体下载 | 不执行最终规则和目标发布 |
| `safew-receiver` | SafeW 桌面、D-Bus 通知捕获、来源标题和正文提取 | 不读取 SafeW 历史或官方 User API |

`sender` 是唯一执行最终发布的容器。当前 Compose 应保持一个 sender 副本，以维持来源内
顺序并避免 Bot 发布竞争。

### 2.2 基础设施

| 服务 | 职责 |
| --- | --- |
| PostgreSQL | 用户、频道、目标、规则、处理状态、审核、历史、API 接入凭据/回执和 API 投递 |
| Redis | 接收事件 Stream、Web 命令 Stream、业务进程心跳 |
| `migrate` | 业务服务启动前执行 `alembic upgrade head`，成功后正常退出 |

### 2.3 共享卷

- `media-data`：Telegram 接收端下载，sender 处理，Web 审核预览；
- `telegram-session`：Telethon 用户登录会话；
- `safew-profile` / `safew-home`：SafeW 登录和桌面资料；
- `history-data`：可选 JSON 历史落盘。

## 3. 数据流

```text
                         ┌──────────────────────────┐
Telegram ── Telethon ───>│ telegram-receiver        │──┐
                         └──────────────────────────┘  │ incoming stream
                                                       ├──────────────┐
                         ┌──────────────────────────┐  │              v
SafeW ── D-Bus 通知 ────>│ safew-receiver           │──┘       ┌──────────┐
                         └──────────────────────────┘          │  Redis   │
                                                               └────┬─────┘
                                                                    v
Browser ── HTTP ──> web ── command stream ───────────────────> sender
                    │                                               │
                    v                                               v
               PostgreSQL <── 状态 / 规则 / 审核 / 历史 ─── 处理管线
                                                                    │
                                      ┌─────────────────────────────┴────────┐
                                      v                                      v
                         Telegram / SafeW Bot 目标                      API deliveries
```

Redis consumer group 使用显式确认。sender 处理失败时事件留在 pending 状态；超过 claim idle
时间后可被重新认领。处理完成后事件才会 `XACK` 并从 Stream 删除。

采集软件通过 `POST /api/ingest/v1/messages` 直接进入 `web`：验证独立接入 Token，持久化
接收回执和规范化消息，再使用 `publish_incoming("api", ...)` 写入 incoming stream。单进程
模式则交给 `MessageService.enqueue`。两种模式都复用现有规则、审核和发布管线。

## 4. 来源与路由

### 4.1 Telegram 来源

Telegram 来源必须先存在于数据库并启用。接收端根据这些来源构建 Telethon 过滤器；Web
修改来源后，Compose 模式下接收端会在约 5 秒内退出并由 `restart: unless-stopped` 拉起，
重新加载过滤器。

如果所有 Telegram 来源都停用，接收端保持空闲，不会自动退化为监听账号中的全部频道。

### 4.2 SafeW 来源

SafeW 通知以会话标题映射为内部来源。启用 `SAFEW_AUTO_REGISTER_SOURCES` 时，sender 会为
首次出现的 SafeW 会话创建来源，默认：

- `enabled=true`
- `publish_mode=review`
- 尚未绑定任何目标

管理员必须在 Web 中确认标题和目标。

### 4.3 API 来源

超级管理员在“消息接入”创建凭据时同步创建独立来源，默认 `enabled=true`、
`publish_mode=review`，尚未绑定目标。凭据与来源一对一，Token 决定来源；请求体不能指定
内部来源或路由。凭据停用、过期、撤销或来源停用时均拒绝提交。

API 来源聊天 ID 使用 `-2_000_000_000_000_000 < chat_id <= -1_000_000_000_000_000`
命名空间，随机生成 48 位偏移，和 Telegram/SafeW 来源隔离。API 来源不会进入 Telegram
订阅与可达性检查。sender 处理 API 事件时刷新来源配置，避免新来源因缓存过期而被忽略。

### 4.4 目标

一个来源可绑定：

- 零个或多个 Telegram/SafeW Bot 目标；
- 零个或多个 API 目标。

目标在真正发布前会再次从数据库验证。已停用、已解绑、过期或来源被停用的目标不会接收
消息。来源至少需要一个当前有效目标，否则消息被标记为路由失败。

## 5. 消息生命周期

`processed_messages.status` 的主要状态：

```text
received
   │
   v
processing ───────────────> filtered
   │                         failed
   ├─ 需要审核 ───────────> pending_review
   │                           │
   │                           ├─ reject ─> 审核 rejected
   │                           └─ publish
   v                               │
pending_publish <──────────────────┘
   │
   v
publishing ───────────────> published
   │
   └──────────────────────> retrying / failed
```

消息历史页面直接读取该表，因此自动发布、规则决定、过滤和失败消息都可见，不依赖审核队列，
也不依赖可选 JSON 历史落盘。

## 6. 处理管线与规则

标准管线包含：

1. 关键词基础过滤；
2. 文本替换；
3. 链接处理；
4. 数据库规则；
5. 页脚；
6. 内容去重；
7. 根据处理结果与来源发布模式作出发布决策。

数据库规则支持来源、Telegram 目标、消息类型和优先级等条件。规则可以继续、标记、替换、
要求审核或拒绝。具体可用字段以 Web 规则编辑器和 OpenAPI Schema 为准。

来源发布模式：

| 模式 | 行为 |
| --- | --- |
| `auto` | 管线未拒绝时自动发布 |
| `review` | 管线未拒绝时也强制进入审核 |
| `rule_based` | 由规则决定；没有要求审核或拒绝时继续发布 |
| `paused` | 完成处理后停在待发布状态 |

## 7. 审核一致性

审核任务创建时保存：

- 原文、规则处理文本和最终文本；
- 媒体快照；
- Telegram/SafeW 目标记录 ID 与聊天 ID 快照；
- API 目标快照；
- API 接入的发送者、会话 ID/名称与外部消息 ID；
- 规则匹配、关键词和决策原因；
- revision 版本号。

编辑、批准、拒绝和发布使用乐观并发控制。客户端必须提交 `expected_revision`，过期 revision
返回冲突，防止两个审核员互相覆盖。

发布时不仅使用快照，还会与当前路由取交集。审核期间被解绑或停用的目标不会继续发布；
后来新增的目标也不会自动收到旧审核任务。

## 8. API 交付

每个 API 目标保存：

- 名称、启用状态与过期时间；
- Token SHA-256 哈希与可识别前缀；
- 来源绑定；
- 独立的 delivery 记录。

`api_deliveries` 对 `(api_endpoint_id, processed_message_id)` 设置唯一约束，确保重试不会重复
创建同一目标的同一消息。客户端按 delivery ID 游标读取，服务器不会因为客户端读取而删除
记录。

API payload 是处理完成时的快照，并主动排除本地文件路径。当前媒体只提供元数据。
API 接入的 `sender`、`conversation_id`、`conversation_name`、`external_message_id` 作为可空
独立字段随历史、审核详情和公开投递返回；它们不会自动拼接到 `text` 中。

## 9. 幂等与恢复

- 来源消息以 `(source_chat_id, source_message_id)` 唯一；
- 已发布记录再次入队时会被跳过；
- 内容哈希只把已发布消息作为去重依据；
- API delivery 有唯一约束；
- API 接收回执以 `(接入来源, conversation_id, message_id)` 唯一；
- 审核发布先原子 claim，减少并发重复发布；
- sender 启动时恢复 `pending_publish`、`retrying`、`publishing` 等可恢复状态；
- Redis 未确认事件会被重新认领。

Telegram 外部 API 无法提供跨数据库与 Telegram 的分布式事务，因此极端崩溃窗口仍需要
依靠幂等检查和人工历史核对。目标间采用尽力而为的部分成功策略。

API 接收回执保留原始规范化负载及内容指纹。相同幂等键、相同内容返回原回执；改变正文、
发送者、会话名称或提供的时间会冲突。省略的时间以“未提供”参与指纹计算，避免重试时
服务器接收时间变化导致冲突。不同会话/发送者的独立 API 消息不因正文相同而合并。

回执整数主键是管线内部 `source_message_id`，外部 `message_id` 留在 `raw_metadata` 中。
结构化身份和规范化负载经过序列化、失败重试、恢复和人工批准后继续保留。

只有队列接受事件才返回 `202`。已入队的相同请求返回 `200` 和 `duplicate=true`；队列不可用
或结果不确定返回 `503`，客户端用原幂等键和内容重试。已保存但未成功入队的回执可重试入队；
入队确认不确定时允许安全重投，后续消息登记负责抑制重复处理。回执的 `queued` 状态不表示
已经发布，也不会因为下游路由失败而改变；修复路由后仍需使用现有失败任务重试流程。

## 10. 健康状态

三个后台业务角色每 5 秒刷新 Redis 心跳，TTL 为 15 秒：

- `sender`
- `telegram-receiver`
- `safew-receiver`

Web 的系统状态读取这些心跳，并区分“队列确实为空”和“Redis 无法读取”。容器健康检查
只代表进程/HTTP 基本可用，业务账号权限仍需通过频道权限测试和实际消息验证。

## 11. 安全边界

- Telegram 用户 Session 只在接收端使用；
- Telegram Bot Token 与 SafeW Bot Token 只在 sender 使用；
- SafeW 登录资料只在 SafeW 卷中；
- Web 密钥与管理员哈希只在 Web 使用；
- 对外拉取 Token 与 API 接入 Token 相互独立，均只以 SHA-256 哈希和显示前缀保存在 PostgreSQL；
- 接入 Token 只在创建/轮换时返回一次，Web 登录凭据不能替代接入认证；
- Web/noVNC 默认只映射到宿主机回环地址。

Compose 的职责拆分减少了密钥扩散，但宿主机 root、Docker daemon 与数据库管理员仍属于
高权限安全边界，必须限制访问并定期备份。

消息接入的持久化结构通过 Alembic `0010_api_ingest` 创建。升级时必须先完成
`alembic upgrade head`，再启动新版 Web/sender；Compose 的 migrate 服务承担该步骤。
撤销接入只删除凭据，保留来源、历史和接收回执。
