# WhaleGuard AI RedLab v0.1.1 Hardening

<!--
仅在 docs/RELEASE.md 的所有阻断项通过后使用本模板。
发布前删除全部 REQUIRED/TODO 注释，并把每个证据字段替换为真实结果。
不要继承 v0.1.0 的测试数字，不要把 workflow 文件存在写成 GitHub CI 已通过。
-->

WhaleGuard AI RedLab 是一个 local-first、可审计的 LLM / Agent / MCP 安全评估工作台。v0.1.1 聚焦可靠性、持续集成与安全供应链，不增加新的产品模块。

## 本版重点 / Highlights

- 事务型 Outbox + 稳定 `delivery_id` + `DeliveryReceipt` 唯一约束，让 RQ at-least-once 投递可以安全重试而不重复改变业务状态。
- `RunEvent` 成为 SSE 与历史分页的权威来源，支持 cursor/`Last-Event-ID`、递归脱敏和 64 KiB payload 上限；旧 `event_log` 暂时兼容并标记 deprecated。
- 三条最小权限 GitHub Actions 覆盖 CI、供应链安全和无签名 Release Candidate 附件生成；正式 tag 仍由完整发布门禁控制。

完整变更见 [`CHANGELOG.md`](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.1.1/CHANGELOG.md)。

## 实机界面 / Screenshots

![WhaleGuard Dashboard](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.1.1/docs/screenshots/dashboard-dark.png)

![AgentArena private lab](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.1.1/docs/screenshots/agentarena.png)

![MCPShield Tool metadata](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.1.1/docs/screenshots/mcpshield.png)

![Finding detail and evidence](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.1.1/docs/screenshots/finding-detail.png)

![Generated HTML report](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.1.1/docs/screenshots/report-preview.png)

补充画面：[测试运行与 SSE 事件](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.1.1/docs/screenshots/runs.png)。所有图片的尺寸与 SHA-256 见截图资产清单。

## 验证结果 / Verification

> 以下结果必须来自 tag 解引用后的同一 commit。`未运行`、`未知` 或旧提交结果均不等于通过。

| 门禁 | 结果 |
| --- | --- |
| Release commit | `<!-- REQUIRED: 40-character SHA -->` |
| `CI` workflow | <!-- REQUIRED: green run URL --> |
| `Supply Chain Security` workflow | <!-- REQUIRED: green run URL --> |
| Release Candidate artifact workflow | <!-- REQUIRED: successful run URL --> |
| Python / Scope Guard / Worker / Mock tests | <!-- REQUIRED: passed/failed counts + CI link --> |
| Frontend lint / typecheck / component / build | <!-- REQUIRED --> |
| Playwright | <!-- REQUIRED --> |
| Alembic round trip | <!-- REQUIRED --> |
| RQ idempotency tests | <!-- REQUIRED --> |
| PostgreSQL multi-worker concurrency | <!-- REQUIRED --> |
| Docker Compose | <!-- REQUIRED: 8/8 healthy + /ready --> |
| Product smoke | <!-- REQUIRED --> |
| restart / down-up persistence | <!-- REQUIRED --> |
| Dependency audit | <!-- REQUIRED --> |
| Trivy filesystem + images | <!-- REQUIRED: include exceptions --> |
| SBOM | <!-- REQUIRED: format + filename --> |

## 快速启动 / Quick start

Windows 11 + Docker Desktop：

```powershell
.\START_WHALEGUARD.bat
```

Linux / WSL2：

```bash
make docker-up
```

`make docker-up` 会先生成本地配置，再以同一个受控 Compose 项目名执行
v0.1.0 Redis 卷的幂等所有权迁移；升级用户不要改回裸 `docker compose up`。

启动后访问 <http://127.0.0.1:3000>。随机首次凭据只写入被 Git 忽略的 `.local/first-run-credentials.txt`；不要把该文件上传到 Issue、日志或 Release。

完整步骤见 [`README.md`](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.1.1/README.md) 与 [`docs/RELEASE.md`](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.1.1/docs/RELEASE.md)。

## Demo 与架构

- [5 分钟 Demo 流程](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.1.1/docs/DEMO_GUIDE.md)
- [系统架构与安全边界](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.1.1/docs/ARCHITECTURE.md)
- [真实截图资产清单](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.1.1/docs/screenshots/README.md)

## Release 附件 / Assets

| 文件 | 用途 | SHA-256 |
| --- | --- | --- |
| `whaleguard-ai-redlab-v0.1.1.tar.gz` | 无签名源码候选包 | `<!-- REQUIRED -->` |
| `release-metadata.json` | 版本与完整 commit SHA | `<!-- REQUIRED -->` |
| `whaleguard-source.spdx.json` | SPDX JSON SBOM | `<!-- REQUIRED -->` |
| `whaleguard-source.cyclonedx.json` | CycloneDX JSON SBOM | `<!-- REQUIRED -->` |
| `sbom-manifest.json` | SBOM 文件清单 | `<!-- REQUIRED -->` |
| `trivy-source.json` | 完整源码扫描报告 | `<!-- REQUIRED -->` |
| `SHA256SUMS` | 全部手工上传附件的校验值 | 见文件内容 |

GitHub 自动生成的 Source code ZIP/TAR 应解引用到上表中的 Release commit。下载附件后请独立复核 `SHA256SUMS`。依赖审计、文件系统扫描、八服务镜像扫描和镜像 SBOM 的完整 artifact：<!-- REQUIRED: Supply Chain Security run URL -->

## 升级与兼容性 / Upgrade notes

<!-- REQUIRED: 数据库迁移、兼容字段、回滚限制；无特殊步骤时明确写“无需额外步骤”。 -->

升级前请备份 PostgreSQL 数据卷和 `.env`，并限制凭据文件权限。不要用旧版数据库备份覆盖已迁移的数据卷。

## 已知限制 / Known limitations

- MCPShield 默认只分析配置和 Tool 元数据，不执行未知 Tool。
- SQLite 仅用于本地单进程开发；多 Worker 和发布验收使用 PostgreSQL。
- <!-- REQUIRED: 列出本版仍存在的已知限制；没有则写“无新增已知限制”。 -->

## 安全使用边界 / Authorized use only

本项目仅用于本地实验、自有系统或获得明确授权的目标。它不提供 C2、WebShell、恶意载荷、凭据窃取、爆破、持久化、免杀、任意 Shell、未授权公网扫描或自动利用。发现安全问题请遵循 [`SECURITY.md`](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.1.1/SECURITY.md)，不要在公开 Issue 中披露凭据或可利用细节。

## 致谢 / Thanks

<!-- 可选：列出贡献者或相关 PR。不要填写未经同意的个人信息。 -->
