# WhaleGuard AI RedLab 最终状态

更新时间：2026-08-30（Asia/Shanghai）

## 交付结论

WhaleGuard AI RedLab 已完成为可运行、可验证、可继续扩展的开源 monorepo。当前机器已用本地 SQLite、受限内联任务后端和三个回环 Mock 服务实际完成登录、项目/Scope、15 用例 Agent 测试、2 次人工审批、Finding、证据、模型适配、LLM Judge、MCPShield、审计及三种报告的端到端闭环。

安全边界保持不变：平台只用于本地、自有或明确授权目标；不包含 C2、WebShell、爆破、凭据窃取、恶意 Payload、持久化、规避、任意 Shell、未授权公网扫描或自动利用。

## 已完成的功能

- 17 个产品页面（登录 + 16 个业务控制台页面），中文默认、原创暗色安全控制台、亮色主题、移动端导航。
- FastAPI / SQLAlchemy 2 / Alembic / Pydantic 2 后端，20 个要求的核心模型和完整 CRUD/工作流 API。
- Admin、Security Engineer、Reviewer、Viewer 四类 RBAC；Argon2、JWT、CSRF、CORS、加密模型密钥和不可变审计读取面。
- OpenAI-compatible 渠道、连接测试、规则优先评分、显式可选 LLM Judge 和 Token/费用/延迟指标。
- 独立 Scope Guard、DNS/重定向逐跳复检、授权到期和人工审批策略日志。
- MCPShield 配置/Tool 元数据静态分析，不执行未知 Tool。
- mock-llm、mock-agent、mock-mcp-server AgentArena，五个无破坏性 Tool 和敏感演示审批围栏。
- 异步运行状态机、暂停/恢复/取消/重试/超时/并发/进度/SSE。
- Finding 生命周期、证据哈希、HTML/Markdown/JSON 报告和 GitHub 示例报告。
- 8 服务 Compose、非 root 容器、内部 arena/backend 网络、Windows BAT/PowerShell 与 Linux/WSL 文档。

## 项目目录

```text
whaleguard-redlab/
├─ apps/{web,api,worker}
├─ packages/{shared,policy-engine}
├─ test-cases/
├─ labs/{mock-llm,mock-agent,mock-mcp-server}
├─ infra/docker/
├─ docs/{examples,screenshots}
├─ scripts/
├─ docker-compose.yml
├─ .env.example
├─ Makefile
├─ README.md
├─ LICENSE
└─ NOTICE
```

## 启动命令

Windows 11 + Docker Desktop：

```powershell
.\START_WHALEGUARD.bat
```

Linux / WSL2：

```bash
python3 scripts/bootstrap_env.py
docker compose up --build
```

等价 Make 命令：`make dev`、`make docker-up`、`make docker-down`、`make seed`、`make reset`、`make test`、`make lint`、`make format`、`make verify`。

## 默认访问地址

- Web：<http://127.0.0.1:3000>
- API：<http://127.0.0.1:8000>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>、<http://127.0.0.1:8000/ready>

Docker 中的三个 Mock 服务只位于私有 arena 网络，不发布宿主端口。本次本地进程验收临时绑定 `127.0.0.1:8101-8103`。

## 初始账号获取方式

用户名为 `admin`（也可用 `admin@whaleguard.local`）。密码每次首次初始化安全随机生成，不在仓库、日志或本文件中展示：

- Docker：`.local/first-run-credentials.txt`
- 本机 SQLite 开发：`.local/local-first-run-credentials.txt`

两个凭据文件均被 Git 忽略且不可混用。Docker 启动日志只提示文件路径。

## 测试结果

- Python：88 passed（policy 19、worker 16、API 19、mock-llm 9、mock-agent 16、mock-mcp 9）。
- 前端：Vitest 11 passed；Playwright 3 passed；ESLint、TypeScript、Next.js production build 通过。
- 自动化合计：102 passed。
- 数据库：Alembic upgrade → downgrade → upgrade 通过，SQLite 实际创建 23 张表。
- API：OpenAPI 53 paths / 81 operations / 72 schemas。
- 产品烟测：11/11 通过；生成 Agent run、Model/Judge run、Finding、证据和 HTML/Markdown/JSON Report。
- 浏览器实机：暗/亮主题、390px 响应式导航和关键页面通过，检查页面无 console warning/error。
- Compose：仓库安全不变量通过；官方 Compose v5.5.0 `config --quiet` 通过。

## 实测截图

![系统总览](docs/screenshots/dashboard-dark.png)

![MCPShield Tool 元数据](docs/screenshots/mcpshield.png)

![测试运行详情](docs/screenshots/runs.png)

## 尚未实现或未验证的非关键项

- 当前主机没有 Docker Engine，未执行镜像 build/up；因此 PostgreSQL、Redis、RQ 的容器运行时仍需在有 Engine 的主机补验。Compose 语义和安全拓扑已经验证。
- 未接入任何真实第三方模型 API；兼容适配和 LLM Judge 使用本地 Mock 验证，用户应自行添加明确授权渠道。
- PDF 报告、SSO、S3 兼容对象存储、多节点 worker 属于下一阶段增强，不阻塞当前闭环。

## 下一阶段建议

1. 在装有 Docker Engine 的 CI/主机执行 `powershell -File scripts/verify-all.ps1` 或 `make verify`，补齐 8 服务运行时证据。
2. 增加 PostgreSQL/Redis/RQ 的 CI 服务矩阵和容器镜像漏洞/SBOM 检查。
3. 为经过授权的真实 provider 建立协议兼容矩阵、速率限制和预算上限。
4. 增加团队级项目隔离、OIDC/SSO、证据对象存储与签名报告。
