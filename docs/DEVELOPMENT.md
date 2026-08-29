# 开发指南

## 本机开发

Python 3.11+ 与 Node.js 20+：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e "apps/api[dev]" -e "apps/worker[test]" -e "packages/policy-engine[test]" pyyaml jsonschema
pip install -r labs/mock-llm/requirements-dev.txt -r labs/mock-agent/requirements-dev.txt -r labs/mock-mcp-server/requirements-dev.txt
(cd apps/web && npm ci && npx playwright install chromium)
```

Windows PowerShell 激活命令为 `.venv\Scripts\Activate.ps1`。

开发环境可把 `DATABASE_URL` 设置为 `sqlite:///./whaleguard.db`，Redis 不可用时 API 的演示执行器可以采用受限的本地任务后端；Compose 默认使用 PostgreSQL 与 RQ。

从仓库根目录执行 `make seed` 会创建 `.local/whaleguard-dev.db`，首次随机凭据写入 `.local/local-first-run-credentials.txt`。这是本机 SQLite 开发状态；Docker Compose 的凭据文件是 `.local/first-run-credentials.txt`，不要交叉使用。

## 验证

```bash
make lint
make test
python scripts/test_migrations.py
(cd apps/web && npm run build)
(cd apps/web && npx playwright test)
docker compose config --quiet
```

Windows 上的完整 Docker 验收使用显式运行模式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\verify-all.ps1 -RuntimeMode Docker
```

验证已经启动的本机 SQLite/回环 Mock 进程时必须显式选择 Local，并使用独立凭据：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\verify-all.ps1 -RuntimeMode Local -CredentialPath .local\local-first-run-credentials.txt
```

脚本不会在两份凭据之间猜测；任一验收失败都会返回非零退出码。Docker 模式在烟测前等待全部 8 个服务 healthy 并要求 `/ready` 返回数据库可用，Local 模式要求 API/Web 已经运行。Linux/WSL 可运行 `make verify` 完成静态检查、测试、构建、Playwright 模拟浏览器流程与 Compose 配置校验。

完整业务烟测覆盖健康检查、登录、项目/Scope 创建、Mock Agent 运行、Finding 和 HTML 报告。测试必须使用虚构数据与本地地址。

## 代码约定

- Python：Ruff、类型化 Pydantic/SQLAlchemy 2，不在路由中拼 SQL。
- TypeScript：strict 模式；所有 API 输入先过 Zod。
- 时间统一存 UTC，前端按浏览器区域格式化。
- 删除操作需要权限与审计；AuditLog 没有普通 CRUD 写接口。
- 新增外部请求点必须集成 Scope Guard，并添加允许、拒绝、重定向和混合 DNS 测试。
