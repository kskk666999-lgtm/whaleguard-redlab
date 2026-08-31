# 故障排查

## 新手先看哪里

登录后在新手首页查看“本地系统状态”。API、数据库、Redis、后台任务、本地靶场和 AI 模型会显示为“正常 / 未启动 / 可选 / 异常”。AI 模型是可选项；它未配置时，安全学院和规则网站体检仍可使用。

如果只有后台任务显示“未启动”，扫描暂时不能运行，但历史 Finding 和报告仍可查看。先运行 `DIAGNOSE_WHALEGUARD.bat`，再按输出中的建议处理；不要通过删除数据卷重置系统。

## 找不到初始管理员密码

Docker Compose 首次凭据位于仓库根目录的 `.local/first-run-credentials.txt`；本机 `make seed` 的 SQLite 凭据位于 `.local/local-first-run-credentials.txt`，两者对应不同数据库。服务日志不会输出密码；可用 `docker compose logs api` 查找 `WHALEGUARD_INITIAL_CREDENTIALS_FILE`，确认容器写入的文件位置。

凭据文件只在首次创建管理员时生成且不会覆盖。若数据库已有管理员但文件已丢失，请不要尝试从日志恢复密码：开发演示环境可使用 `RESET_DEMO.bat` 重新创建数据与随机凭据；需要保留数据时应由管理员使用受控的账户恢复流程。

## 模型连接测试被 Scope Guard 拒绝

查看策略判定中的 `code`、解析 IP 和 matched scope。公网渠道必须在项目 Scope 中明确授权域名/IP、确认授权且未过期。不要添加 `0.0.0.0/0` 或关闭 DNS 检查。

## 规则检查完成，但 AI 解读失败

这不代表网站体检失败。确定性规则结果、Finding、Evidence 和报告仍然有效。结果页会显示脱敏后的失败类别；点击“重新生成 AI 解读”只会重新调用模型，不会再次请求被测网站。常见原因包括模型超时、Provider 错误或返回结构未通过 Schema 验证。

## Redis/RQ 不可用

```bash
WG_PROJECT="$(python3 scripts/migrate_redis_volume.py --print-project-name)"
docker compose --project-name "$WG_PROJECT" --file docker-compose.yml --env-file .env ps redis worker
docker compose --project-name "$WG_PROJECT" --file docker-compose.yml --env-file .env logs redis worker
```

确认 `.env` 中 `REDIS_URL` 与 `REDIS_PASSWORD` 同源生成；不要把密码贴到 issue 或日志中。

## 前端无法访问 API

确认构建时 `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1`，且 CORS 只包含实际的本地 Web origin。用 `/health` 区分 API 未启动与浏览器 CORS 问题。

## 数据库迁移失败

先用 `python3 scripts/migrate_redis_volume.py --print-project-name` 取得 `WG_PROJECT`，再以 `docker compose --project-name "$WG_PROJECT" --file docker-compose.yml --env-file .env logs db` 核对数据库健康状态，并用同一组 Compose 参数执行 `run --rm api alembic upgrade head`。不要删除 production volume 来掩盖迁移问题。

## Docker 不存在

源码级单元/集成测试仍可使用本地 Python/Node 环境运行，但 Compose 配置校验和完整私有网络验收必须在安装 Docker/Compose 后执行；不能以 YAML 解析替代真实启动验收。

## Docker 本地 endpoint 未就绪

Windows 启动、检查、停止、重置和验证脚本只允许 Docker Desktop 的本机 `npipe://` endpoint，并忽略可变的用户 Docker context。若设置了 `DOCKER_HOST`、`DOCKER_CONTEXT` 或其他 Docker 客户端覆盖，脚本会在任何 Compose 变更前失败关闭；请先清除这些覆盖。若提示没有可信本地 endpoint 就绪，请确认 Docker Desktop 已启动且处于 Linux containers 模式。不要通过 TCP/SSH context 或修改脚本绕过此保护。

若错误指出 `COMPOSE_BAKE`、`BUILDX_BAKE_*` 或 `cli-plugins` shadowing，请从当前进程环境或本项目 `.env` 移除对应覆盖，并删除受管 `.local/docker-cli-config/cli-plugins` 影子目录；不要通过放宽门禁启用未验证插件。若安装/升级提示 Docker 工作负载仍在运行，先自行保存并正常停止相关项目；自动脚本不会替你中断无关容器或全部 WSL 发行版。

## Docker Desktop 提示 sailor-ingest socket 无法访问

Docker Desktop 4.88.x 在 Windows 更新或异常退出后，偶尔会留下零字节的 AF_UNIX runtime socket，启动窗口可能显示 `sailor-ingest.sock` 或 `docker-secrets-engine` 无法访问。

最新版 `START_WHALEGUARD.bat` 会先验证 Docker Desktop 官方安装路径、进程归属、目录位置和文件特征；只有符合受管陈旧 socket 条件时才把整个 runtime 目录**改名隔离**后重试。它不会删除目录、镜像、容器或 volume，也不会处理不满足归属条件的文件。不要手工运行网上的广泛删除命令；若自动恢复拒绝执行，请保留提示并运行 `DIAGNOSE_WHALEGUARD.bat`。

## 启动时发现两个 WhaleGuard Compose 项目

旧版本可能使用固定项目名 `whaleguard-redlab`，新脚本也可能按仓库路径计算受管项目名。启动器会核对 Compose 标签、工作目录、配置文件、服务清单和 volume 归属：只有唯一候选属于当前仓库时才安全接管历史项目，以继续使用原数据库和报告。

如果多个候选都无法唯一确认，脚本会失败关闭，不会猜测、停止未知项目或删除 volume。此时运行 `DIAGNOSE_WHALEGUARD.bat` 并查看脱敏报告；不要直接执行带 `-v` 的 `docker compose down`。

## 服务没有全部 healthy

`START_WHALEGUARD.bat` 会等待 db、redis、api、worker、web、mock-llm、mock-agent、mock-mcp-server 全部 healthy，并额外要求 API `/ready` 的数据库状态为 `ok`。运行 `CHECK_WHALEGUARD.bat` 可查看每个服务的 state/health、端口 PID 和针对性建议。

启动、检查、验证和烟测会把经过脱敏的状态写入 `.local/logs/`，每类操作最多保留最近 20 份。失败时启动脚本还会采集全部 8 个服务的有限尾部日志，并遮罩密码、Authorization、Cookie、Token、API Key 和带认证信息的 URL；日志不会读取 `.env` 或首次凭据文件内容。
