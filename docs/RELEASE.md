# WhaleGuard 发布手册

本手册定义阻断式发布门禁。任何必需项未通过、未运行或证据不属于同一个最终 commit 时，都不得创建或发布 tag。

## 当前发布目标

| 项目 | 说明 |
| --- | --- |
| 当前正式版本 | `v0.2.0 Beginner Experience / Academy` |
| 上一稳定基线 | `v0.1.1 Hardening`，commit `dbbbd000067b4c161d6ff9029882c77a226d8101` |
| 发布身份 | annotated tag `v0.2.0^{}` 解引用后的完整 commit |
| 官方仓库 | <https://github.com/kskk666999-lgtm/whaleguard-redlab> |

`CHANGELOG.md` 的 `[Unreleased]` 只保留后续开发内容，不代表已经发布。最终测试数字、CI URL、附件 SHA-256 和 Known Issues 写入 GitHub Release 正文，避免更新证据反过来改变发布 commit。

## v0.2.0 阻断式 Checklist

以下项目必须在冻结的最终 commit 上重新运行；不能继承 v0.1.1 或开发过程中的结果。

### 1. 版本、范围与数据保护

- [ ] 应用、API、Worker、Policy Engine、Web 与三个 Mock 服务版本均为 `0.2.0`。
- [ ] README、CHANGELOG、Quick Start、API、架构、安全、学院、网站体检、DeepSeek、Windows 和故障排查文档与实现一致。
- [ ] Alembic `upgrade -> downgrade -> upgrade` 通过；升级前已有 PostgreSQL 数据已备份。
- [ ] 历史 Project、Academy progress、Finding、Evidence、Report 与 Docker volume 未被删除或静默替换。
- [ ] `git diff --check` 通过，最终提交前工作树只包含计划发布内容。

### 2. 自动化测试

- [ ] API、Scope Guard、Worker、Policy Engine、Mock 服务和 Windows 脚本测试全通过。
- [ ] DeepSeek 解析覆盖普通 JSON、代码围栏、JSON 前后文字、缺字段、错误类型、损坏 JSON、超时和 Provider 错误。
- [ ] Alembic 往返迁移和必需表/索引/外键核对通过。
- [ ] 前端组件测试、ESLint、TypeScript 和 Next.js 生产构建全通过。
- [ ] Playwright 新手流程通过：登录 → Onboarding → B01 → Hint → 完成 → Attack Story → Hardened → V/H 对比 → 下一课。
- [ ] 没有通过删除断言、吞异常、移除 health check、关闭扫描或跳过测试换取绿色结果。

### 3. Academy 与网站体检

- [ ] 10 个“开始之前”微课程可读取并包含人话解释、类比、图示和小交互。
- [ ] 17 个 Scenario 的 Vulnerable 版本可命中，Hardened 版本可阻断。
- [ ] 三级 Hint、独立完整解法、Attack Story、V/H 对比、技能进度、知识回顾和下一课都连接真实数据。
- [ ] 重置本关只清理易失实验状态，不删除总进度、Session、Finding、Evidence、Report、Project 或 volume。
- [ ] Mock Agent 网站体检执行 13 项低风险只读检查并生成 Finding、Evidence 和 HTML Report。
- [ ] AI 增强失败时规则结果仍完成；“重新生成 AI 解读”不再次访问被测网站。

### 4. Docker、Scope 与持久化

- [ ] `docker compose config --quiet` 和 Compose 安全不变量校验通过。
- [ ] db、redis、api、worker、web、mock-llm、mock-agent、mock-mcp-server 8/8 healthy，`/health` 与 `/ready` 通过。
- [ ] Scope Guard 拒绝非 HTTP(S)、未授权 host/port/path/query、DNS 解析到范围外地址和范围外重定向。
- [ ] 网站向导必须确认所有权/授权，默认仅允许 `safe_read_only`；新手模式不放宽 RBAC 或 Scope。
- [ ] `docker compose restart` 后 Project、Academy progress、Finding、Evidence、Report 和报告哈希保持一致。
- [ ] `down -> up` 后同一批对象、关联 ID、Evidence SHA-256 和报告文件保持一致。
- [ ] Windows 冷启动实测只双击 `START_WHALEGUARD.bat`：Docker Desktop 从停止状态安全恢复、历史 Compose 项目被唯一识别、8 服务 healthy、浏览器打开且历史报告可见。
- [ ] 冷启动不会停止无关 WSL/Docker 工作负载，不删除 volume；异常归属或多个候选项目时 fail closed。

### 5. UI、截图与可访问性

- [ ] Beginner/Advanced 切换保存到账户偏好；高级功能没有被删除。
- [ ] 首次引导最多 4 步且模型可跳过；无 API Key 也能开始第一课。
- [ ] 所有按钮执行真实动作或明确禁用，没有点击无反应的占位控件。
- [ ] Release 与 README 只引用仓库中真实存在、已脱敏且在 `docs/screenshots/README.md` 登记尺寸与 SHA-256 的截图，不创建破图链接或用设计稿冒充实机画面。
- [ ] 若发布新的 v0.2.0 页面截图，必须来自当前真实运行环境并完成同样登记；没有可复用的已登录浏览器会话时可沿用已验证的高级工作台截图，但 Release Notes 必须明确没有新增 Beginner/Academy/Website 页面截图。

### 6. 安全与供应链

- [ ] `git ls-files`、diff 和 Secret 扫描确认没有 `.env`、API Key、管理员密码、Cookie、Token、数据库、用户扫描数据或未脱敏日志。
- [ ] API Key 始终加密保存、查询只返回掩码；AI 内容不能覆盖 deterministic Finding。
- [ ] CI、Supply Chain Security 与 Release Candidate Artifacts workflow 在最终 commit 上通过。
- [ ] pip/npm 审计、Trivy 源码/镜像扫描、Syft SPDX/CycloneDX SBOM 和 `SHA256SUMS` 已生成并复核。
- [ ] 所有服务继续默认只绑定 `127.0.0.1`；Mock 服务只在 Docker 私有网络。

## 冷启动和本地最终验收

Windows 用户的正式入口是：

```powershell
.\START_WHALEGUARD.bat
```

发布验收时先正常停止 WhaleGuard 和 Docker Desktop，保留所有 volume，只运行该入口。成功条件不是“脚本没有报错”，而是 8 个服务均健康、`http://127.0.0.1:3000` 可登录、旧报告可打开。

Linux/WSL2 使用：

```bash
make docker-up
```

不要用删除 volume、重置数据库或新建空 Compose 项目来掩盖升级问题。

## 候选附件

正式 v0.2.0 Release 至少包含：

| 附件 | 要求 |
| --- | --- |
| `whaleguard-ai-redlab-v0.2.0.tar.gz` | 从冻结 commit 的 `git archive` 生成 |
| `release-metadata.json` | 版本、完整 commit SHA、生成时间、`published: false` |
| `whaleguard-source.spdx.json` | SPDX JSON SBOM |
| `whaleguard-source.cyclonedx.json` | CycloneDX JSON SBOM |
| `sbom-manifest.json` | SBOM 清单且 source commit 与候选一致 |
| `trivy-source.json` | 完整源码扫描结果 |
| `SHA256SUMS` | 覆盖所有手工上传附件，不覆盖自身 |

不得把 `.env`、`.local`、管理员凭据、日志、数据库、Cookie、Token、API Key 或用户数据加入附件。

## 发布流程

1. 在 `dev` 完成功能和本地验收，整理语义化提交并推送。
2. 通过项目既有流程把候选合入稳定分支；记录唯一候选 commit SHA。
3. 在该 SHA 上重新运行所有门禁，并等待 GitHub `CI` 与 `Supply Chain Security` 通过。
4. 手工运行 `Build Release Candidate Artifacts`，输入 `v0.2.0`；核对 workflow head SHA、metadata commit 与 SBOM source commit。
5. 在仓库外填写 `.github/RELEASE_TEMPLATE.md`，删除全部占位符并写入真实证据。
6. 只有全部通过后创建 annotated tag：

   ```powershell
   git tag -a v0.2.0 -m "WhaleGuard AI RedLab v0.2.0 Beginner Experience"
   git rev-parse 'v0.2.0^{}'
   ```

7. 推送 tag，创建 GitHub Release，上传附件；再从 GitHub 下载并复核 SHA-256。
8. 在未登录浏览器回读 README、截图、Release 正文、附件和最终访问地址。

Tag 发布后不得移动或覆盖。若发现问题，应记录影响并发布后续补丁版本。

## Release Notes 必含章节

- Beginner Experience
- WhaleGuard Academy
- Website Check
- AI Analysis
- Reliability
- Security
- Breaking Changes
- Known Issues
- Verification（commit、测试、CI、Docker、持久化、冷启动、附件哈希）

## 判定规则

- **READY**：所有阻断项通过，证据属于同一最终 commit，GitHub Release 与附件已回读。
- **NOT READY**：任一必需项失败、未运行、结果未知或证据属于旧 commit。
- **BLOCKED**：明确记录外部阻塞与下一步，但仍不得创建 tag。

WhaleGuard 只用于本地实验、自有系统或获得明确授权的目标。Release 不得扩大这一边界，也不得加入 C2、WebShell、恶意载荷、凭据窃取、爆破、持久化、免杀、任意 Shell、未授权公网扫描或自动利用。
