# TG-forwarder 文档

本文档目录对应当前 `main` 分支实现。频道来源、Telegram/SafeW 发送目标、API 目标及绑定关系均由
Web 和数据库管理，不再从环境变量或 `config/channels.yaml` 读取。

## 文档索引

| 文档 | 适合读者 | 内容 |
| --- | --- | --- |
| [API 文档](api.md) | API 客户端开发者、管理员 | 公开拉取 API、管理 API、认证、游标与错误 |
| [部署文档](deployment.md) | 运维人员 | Compose、本地运行、SafeW、升级、备份和 HTTPS |
| [使用指南](user-guide.md) | 管理员、审核员 | 频道、发布模式、规则、审核、历史和 API 目标 |
| [配置参考](configuration.md) | 运维人员、开发者 | `.env` 模板、必填项、运行时设置与安全配置 |
| [架构说明](architecture.md) | 开发者、运维人员 | 容器职责、消息流、数据模型和故障边界 |
| [故障排查](troubleshooting.md) | 运维人员 | 常见日志、诊断命令和修复方法 |
| [开发与发布](development.md) | 贡献者、仓库维护者 | 开发环境、测试、迁移、CI 与 release-please |

## 建议阅读顺序

- 第一次部署：部署文档 → 配置参考 → 使用指南；
- 接入外部系统：API 文档 → 架构说明；
- 线上异常：故障排查 → 架构说明；
- 参与开发：开发与发布 → API 文档。
