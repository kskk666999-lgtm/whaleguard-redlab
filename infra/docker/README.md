# Container hardening

- 应用容器均以非 root 用户运行、设置 `no-new-privileges`、删除 Linux capabilities，且未启用 `privileged`。
- `mock-llm`、`mock-agent`、`mock-mcp-server` 只连接 `arena` 私有网络，没有宿主机端口。
- PostgreSQL、Redis 和 worker 只连接 `backend` 私有网络，且只有 API 能同时连接 `edge`、`backend` 与 `arena`。
- PostgreSQL 与 Redis 不发布宿主机端口；二者使用本地随机密码。
- 只有 Web (`127.0.0.1:3000`) 与 API (`127.0.0.1:8000`) 对宿主机开放。
- 所有应用层外部请求仍必须经过 Scope Guard。
