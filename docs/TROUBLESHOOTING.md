# 故障排查

## 找不到初始管理员密码

Docker Compose 首次凭据位于仓库根目录的 `.local/first-run-credentials.txt`；本机 `make seed` 的 SQLite 凭据位于 `.local/local-first-run-credentials.txt`，两者对应不同数据库。服务日志不会输出密码；可用 `docker compose logs api` 查找 `WHALEGUARD_INITIAL_CREDENTIALS_FILE`，确认容器写入的文件位置。

凭据文件只在首次创建管理员时生成且不会覆盖。若数据库已有管理员但文件已丢失，请不要尝试从日志恢复密码：开发演示环境可使用 `RESET_DEMO.bat` 重新创建数据与随机凭据；需要保留数据时应由管理员使用受控的账户恢复流程。

## 模型连接测试被 Scope Guard 拒绝

查看策略判定中的 `code`、解析 IP 和 matched scope。公网渠道必须在项目 Scope 中明确授权域名/IP、确认授权且未过期。不要添加 `0.0.0.0/0` 或关闭 DNS 检查。

## Redis/RQ 不可用

```bash
docker compose ps redis worker
docker compose logs redis worker
```

确认 `.env` 中 `REDIS_URL` 与 `REDIS_PASSWORD` 同源生成；不要把密码贴到 issue 或日志中。

## 前端无法访问 API

确认构建时 `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1`，且 CORS 只包含实际的本地 Web origin。用 `/health` 区分 API 未启动与浏览器 CORS 问题。

## 数据库迁移失败

先运行 `docker compose logs db` 并核对数据库健康状态，再运行 `docker compose run --rm api alembic upgrade head`。不要删除 production volume 来掩盖迁移问题。

## Docker 不存在

源码级单元/集成测试仍可使用本地 Python/Node 环境运行，但 Compose 配置校验和完整私有网络验收必须在安装 Docker/Compose 后执行；不能以 YAML 解析替代真实启动验收。
