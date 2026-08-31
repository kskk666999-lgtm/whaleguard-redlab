# WhaleGuard AI RedLab v0.2.0 Beginner Experience

<!--
仅在 docs/RELEASE.md 的全部阻断门禁通过后使用。
发布前删除所有 REQUIRED/TODO/HTML 注释，并用同一最终 commit 的真实证据替换。
不得继承旧版本测试数字，不得把“workflow 存在”写成“CI 已通过”。
-->

WhaleGuard AI RedLab 是一个 local-first、safe-by-default 的 AI 安全学习与授权评估平台。v0.2.0 让新手无需先理解 Project、Scope、Queue 或 API Key，也能开始本地课程；高级模式继续保留完整安全工作台。

## Beginner Experience

- 四步首次引导，模型可跳过。
- 新手首页提供“继续学习 / 检查我的网站 / 查看最近结果”三条真实路径。
- 新手/高级模式保存到账户偏好；切换只改变信息密度，不放宽 RBAC 或 Scope Guard。
- 系统状态用“正常 / 未启动 / 可选 / 异常”解释 API、数据库、任务服务、Labs 与模型。

## WhaleGuard Academy

- 10 个 3–5 分钟中文微课程，以及 Beginner → Intermediate → Advanced Roadmap。
- 17 个本地 Scenario 采用“学 → 猜 → 做 → 看 → 修 → 再测 → 总结”闭环。
- 三级 Hint、独立完整解法、Attack Story、Vulnerable/Hardened 对比、技能进度、知识回顾和下一课。
- 映射 OWASP GenAI LLM Top 10 2026 与 OWASP Top 10 for Agentic Applications 2026。

## Website Check

- 三步向导：网址 → 授权与安全只读级别 → 可选 AI。
- 自动创建或复用“我的网站体检”项目，并建立 24 小时精确 URL Scope。
- 13 项低风险只读检查生成确定性得分、Finding、Evidence 与 HTML Report。

## AI Analysis

- DeepSeek/OpenAI-compatible JSON Mode 和严格 Schema 解析。
- 支持普通 JSON、代码围栏和 JSON 前后少量说明文字。
- AI 失败不会覆盖或作废规则结果；可只重试 AI 解读，不再次访问目标。

## Reliability

- Windows 双击入口可安全恢复 Docker Desktop、识别同仓库历史 Compose 项目并保留 volume。
- Docker 4.88.x 陈旧零字节 runtime socket 只在严格归属验证后可恢复隔离，不执行广泛删除。
- <!-- REQUIRED: 其他已验证可靠性结果；没有则删除本项。 -->

## Security

- 新手模式继续执行明确授权、RBAC、逐跳 Scope Guard、加密 API Key、Evidence SHA-256 和审计。
- 默认仅绑定 `127.0.0.1`；Mock 服务留在 Docker 私有网络。
- 不提供 C2、WebShell、恶意载荷、凭据窃取、爆破、持久化、免杀、任意 Shell、未授权公网扫描或自动利用。

## Breaking Changes

<!-- REQUIRED: 明确写“无”，或列出真实破坏性变化和迁移方式。 -->

## Known Issues

<!-- REQUIRED: 列出仍存在的限制；至少说明是否缺少 Sigstore/Artifact Attestation，以及是否没有新增 v0.2.0 Beginner/Academy/Website 截图。 -->

## Verification

> 每条证据必须属于 tag 解引用后的同一个 commit。“未运行”或旧结果不等于通过。

| 门禁 | 结果 |
| --- | --- |
| Release commit | `<!-- REQUIRED: 40-character SHA -->` |
| CI workflow | <!-- REQUIRED: green run URL --> |
| Supply Chain Security | <!-- REQUIRED: green run URL --> |
| Release Candidate Artifacts | <!-- REQUIRED: successful run URL --> |
| Python / Scope / Worker / Mock / Windows tests | <!-- REQUIRED: counts --> |
| Frontend test / lint / typecheck / build | <!-- REQUIRED --> |
| Playwright Beginner flow | <!-- REQUIRED --> |
| 17 Academy V/H matrix | <!-- REQUIRED --> |
| 13 website checks + report | <!-- REQUIRED --> |
| Alembic round trip | <!-- REQUIRED --> |
| Docker 8/8 + health + ready | <!-- REQUIRED --> |
| restart / down-up persistence | <!-- REQUIRED --> |
| Windows cold start | <!-- REQUIRED --> |
| Secret / dependency / Trivy / SBOM | <!-- REQUIRED --> |

## Real Screenshots

<!-- REQUIRED: 只保留真实存在、已脱敏并在 docs/screenshots/README.md 登记的图片。以下六张是当前已验证资产；没有新增 v0.2.0 页面截图时不要另造链接。 -->

- [Dashboard](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.2.0/docs/screenshots/dashboard-dark.png)
- [AgentArena](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.2.0/docs/screenshots/agentarena.png)
- [MCPShield](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.2.0/docs/screenshots/mcpshield.png)
- [Finding Detail](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.2.0/docs/screenshots/finding-detail.png)
- [Report Preview](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.2.0/docs/screenshots/report-preview.png)
- [Run Events](https://raw.githubusercontent.com/kskk666999-lgtm/whaleguard-redlab/v0.2.0/docs/screenshots/runs.png)

## Quick Start

Windows 11 + Docker Desktop：

```powershell
.\START_WHALEGUARD.bat
```

Linux / WSL2：

```bash
make docker-up
```

然后访问 <http://127.0.0.1:3000>。首次随机凭据只写入被 Git 忽略的 `.local/first-run-credentials.txt`。学习内置 Academy 不需要 API Key。

## Upgrade Notes

<!-- REQUIRED: 描述 0004/0005/0006 迁移、备份、回滚限制和历史 Compose 项目接管结果。 -->

升级前备份 PostgreSQL 数据和 `.env`。不要删除 volume 或创建空数据库来绕过迁移失败。

## Release Assets

| 文件 | SHA-256 |
| --- | --- |
| `whaleguard-ai-redlab-v0.2.0.tar.gz` | `<!-- REQUIRED -->` |
| `release-metadata.json` | `<!-- REQUIRED -->` |
| `whaleguard-source.spdx.json` | `<!-- REQUIRED -->` |
| `whaleguard-source.cyclonedx.json` | `<!-- REQUIRED -->` |
| `sbom-manifest.json` | `<!-- REQUIRED -->` |
| `trivy-source.json` | `<!-- REQUIRED -->` |
| `SHA256SUMS` | 见文件内容 |

完整变更见 [CHANGELOG](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.2.0/CHANGELOG.md)，安全边界见 [SECURITY_MODEL](https://github.com/kskk666999-lgtm/whaleguard-redlab/blob/v0.2.0/docs/SECURITY_MODEL.md)。
