# WhaleGuard 发布手册

本文定义 WhaleGuard AI RedLab 的发布门禁、证据和 GitHub Release 操作。它不是“建议测试列表”：任何阻断项未通过时，版本状态都必须保持 **NOT READY TO TAG**。

## 当前发布状态

| 项目 | 状态 |
| --- | --- |
| 稳定基线 | `v0.1.0`（annotated tag） |
| 基线提交 | `a9746d65800e9ff5d590123d589282ecde09c409` |
| 开发版本 | `v0.1.1 Hardening` |
| v0.1.1 tag | **不得创建，等待本页所有阻断项通过** |
| 当前发布结论 | **NOT READY TO TAG** |

2026-08-31 对 v0.1.0 基线的现场复核看到 8 个 Compose 服务均为 `healthy`，API `/ready` 返回 `database: ok`，并存在 smoke、RQ callback、`restart` 和 `down/up` 持久化证据。它们证明 v0.1.0 基线可运行，**不能替代 v0.1.1 最终提交上的全量重跑**。

截至 2026-08-31，当前 checkout 尚未配置 Git remote。正式发布前必须由维护者确认官方仓库地址、GitHub Actions 结果和发布权限，并更新本段状态；不得为了填充文档而虚构仓库 URL、CI 徽章或 Release 链接。

当前明确阻断项：候选 commit 尚未冻结、v0.1.1 全量门禁尚未在同一 commit 上完成、Windows 原生 `START_WHALEGUARD.bat` 尚未对真实旧版 named volume 完成入口级验收，且 GitHub Actions 尚无远端 run 证据。因此即使局部测试或 PowerShell 仿真通过，当前结论仍为 **NOT READY TO TAG**。

## v0.1.1 阻断式 Checklist

以下清单是唯一的 ready 判定。结果、日志、报告和哈希必须来自准备打 tag 的同一个 commit；不能继承 v0.1.0 或更早提交的测试数字。

### 1. 版本与变更范围

- [ ] HEAD 是计划发布的唯一提交，`git status --short` 为空。
- [ ] `git tag --list v0.1.1` 无输出，确认不存在同名 tag。
- [ ] API/应用版本元数据已统一为 `0.1.1`，且没有把开发分支误标为已发布。
- [ ] 本轮只包含可靠性、持续集成、安全供应链和必要文档，没有混入 v0.2 产品功能。
- [ ] 数据库迁移支持 `upgrade -> downgrade -> upgrade`，且兼容策略已记录。
- [ ] `CHANGELOG.md` 已按实际合入内容更新，没有 TODO、TBD 或未验证的完成声明。

### 2. 自动化测试与数据库

- [ ] Python 后端、Scope Guard、Worker 和 Mock 服务测试全通过，无 skip 增量。
- [ ] 前端 lint、typecheck、组件测试和生产构建全通过。
- [ ] Playwright 确定性 Mock UI 流程与 Docker 真实栈流程均通过；真实栈证据必须包含随机凭据登录、项目与回环 Scope 创建、AgentArena 运行、人工审批、完成态和 15 条 RQ delivery receipt。
- [ ] Alembic 往返迁移和必需表/约束核对通过。
- [ ] Outbox 场景通过：事务提交前不投递、提交后投递、周期泵补投、Redis 失败保持 pending、有界退避和稳定 `delivery_id`。
- [ ] RQ 幂等性场景全通过：顺序重复、20 路并发、超过 Worker 进程内 25 秒窗口后观察到 retry 次数递减，且任务进入 RQ `scheduled` / `queued` 或已开始第二次 `started` 执行、Redis 重连、断连重投、不同 delivery、内容冲突 `409`、回滚重试、重启重复、receipt 查询。
- [ ] RunEvent 场景通过：sequence 唯一/单调、SSE cursor、`Last-Event-ID`、分页 history、64 KiB 上限、递归脱敏和旧 `event_log` 兼容。
- [ ] PostgreSQL + Redis + 2–4 Worker 并发专项通过，最终业务状态只应用一次。
- [ ] 没有通过删除断言、吞异常、移除 health check、关闭扫描或跳过测试来获得绿色结果。

### 3. Docker 与真实业务链路

- [ ] 候选 commit 冻结且工作树无非忽略变更后，Linux/WSL 运行 `python3 scripts/test_docker_resilience.py --require-clean-git`；Windows 必须从仓库根目录显式锁定受信 CLI、本地 Engine 和受管插件目录并加同一 Git 门禁运行以下命令。两者都退出码为 0、在报告记录相同的完整 commit SHA 与 `source_git_clean: true`、输出最终成功标记，且失败或中断后已确认恢复标准单 Worker/八服务拓扑。

  ```powershell
  py -3 scripts/test_docker_resilience.py `
    --require-clean-git `
    --docker "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe" `
    --docker-host "npipe:////./pipe/docker_engine" `
    --docker-config "$PWD\.local\docker-cli-config"
  ```
- [ ] `docker compose config` 和仓库安全不变量检查通过。
- [ ] 从干净构建启动后，db、redis、api、worker、web、mock-llm、mock-agent、mock-mcp-server 共 8 个服务全部 `healthy`。
- [ ] 用真实 root-owned v0.1.0 AOF/RDB 隔离卷验证自动升级：一次性 helper 只持有 `CHOWN` 与只读目录遍历所需的 `DAC_READ_SEARCH`，主 Redis PID 以非 root、零有效能力运行，数据跨升级和重启保持一致。
- [ ] 在 Windows 11 / Windows PowerShell 5.1 上从真实旧版 named volume 直接运行 `START_WHALEGUARD.bat`：入口不调用宿主 Python，自动迁移后数据和原卷身份保持、8 个服务健康；Python helper 的实栈结果和 PowerShell 单元仿真都不能替代这项入口级门禁。
- [ ] API `/health` 与 `/ready` 通过，数据库 readiness 为 `ok`。
- [ ] 完整 smoke test 全通过，并生成本轮报告及 SHA-256。
- [ ] 真实 RQ 消费和 callback 验证通过；`docker-resilience-report.json` 的 `rq_outer_retry` 记录同一 `job_id` / `delivery_id` 的 retry 次数递减、观察到的 `scheduled` / `queued` / 第二次 `started` 状态及相应注册表归属、API 断开时长和最终唯一 receipt。
- [ ] Worker crash/restart、Redis 临时断开、API restart 和 Worker restart 场景通过。
- [ ] `docker compose restart` 后项目、Run、Finding、Evidence、审计和报告数据保持一致；Evidence 必须逐条匹配同一 ID 集合、`project_id` / `run_id` / `finding_id` 关联、`evidence_type` 与 SHA-256，不得只比较数量。
- [ ] 完整 `down/up` 后同一批持久化对象和报告哈希保持一致；只接受当前 smoke 生成的 schema v2 checkpoint，旧 schema v1 checkpoint 不得作为 v0.1.1 发布证据。

### 4. CI 与安全供应链

- [ ] PR 和目标分支上的 GitHub Actions 均为绿色；本地 workflow 文件存在不算 CI 已通过。
- [ ] Workflow 使用最小权限、合理超时，来自 fork 的 PR 默认拿不到 secrets。
- [ ] Python `pip-audit` 完整报告已保留且无运行/报告错误；Python High/Critical 由 Trivy filesystem vulnerability gate 统一阻断，npm 继续以 `audit-level=high` 阻断。
- [ ] Dependency Review 与 secret scan 兼容检查已完成。
- [ ] Syft 已从发布 commit 的 `git archive`（而非可能含 `.env`、`.local`、`artifacts` 或 `node_modules` 的工作目录）生成 CycloneDX 与 SPDX SBOM，`sbom-manifest.json` 的完整 commit SHA 与候选一致。
- [ ] Trivy 文件系统和容器镜像扫描完成；Critical/High 为零，或每条例外都有负责人、理由、影响和到期日。
- [ ] Windows 最终镜像 SBOM/Trivy 扫描为 `generate_sbom.py` 与 `scan_compose_images.py` 同时显式传入 `--docker`、`--docker-host`、`--docker-config` 和 `--require-running-match`；两个 `compose-image-inventory.json` 的 CLI、endpoint、config、Compose plugin 路径及 SHA-256 与同一候选 commit 的 `docker-resilience-report.json` 完全一致。Linux/CI 可以使用默认本地 Engine，但仍必须验证运行容器与所扫不可变 image ID 一致。
- [ ] Medium/Low 保留在报告中，没有通过关闭扫描隐藏。
- [ ] 手工触发的 `Build Release Candidate Artifacts` 成功，`release-metadata.json` 中的 commit 与候选 SHA 完全一致。
- [ ] Release 附件已生成 `SHA256SUMS`，并在独立命令中复核。

### 5. 文档、演示与截图

- [x] Dashboard 真实截图已入库。
- [x] MCPShield 真实截图已入库。
- [x] 测试运行详情真实截图已入库。
- [x] AgentArena 真实截图已捕获并脱敏。
- [x] Finding 详情真实截图已捕获并脱敏。
- [x] HTML 报告预览真实截图已捕获并脱敏。
- [ ] [5 分钟演示](DEMO_GUIDE.md)、[架构图](ARCHITECTURE.md)、README 和截图清单与最终版本一致。
- [ ] GitHub Release 正文已从 [Release 模板](../.github/RELEASE_TEMPLATE.md) 填写，所有占位符均已替换。

固定文件名、尺寸、SHA-256 和捕获要求见 [截图资产清单](screenshots/README.md)。不要提交设计稿、AI 生成图或空白占位图冒充实测界面。

## 发布附件

正式 v0.1.1 Release 至少包含：

| 附件 | 要求 |
| --- | --- |
| `whaleguard-ai-redlab-v0.1.1.tar.gz` | `git archive` 生成的无签名源码候选包 |
| `release-metadata.json` | 版本、完整 commit SHA、生成时间和 `published: false` |
| `whaleguard-source.spdx.json` / `whaleguard-source.cyclonedx.json` | Syft 生成并由脚本验证结构的源码 SBOM |
| `sbom-manifest.json` | SBOM 格式和文件清单 |
| `trivy-source.json` | 完整源码漏洞、错误配置、Secret 与许可证扫描结果 |
| `SHA256SUMS` | 覆盖全部手工上传附件，不覆盖其自身 |
| Release notes | Highlights、升级说明、已知限制、验证结果和安全使用边界 |

GitHub 自动生成的 Source code ZIP/TAR 也必须解引用到同一 tag commit。pip/npm 审计和八服务镜像 Trivy/SBOM 保留在 `Supply Chain Security` workflow artifact 中，并在 Release 正文给出对应 run URL 与结论。

不要把 `.env`、`.local/first-run-credentials.txt`、日志、数据库、Cookie、Token、API Key 或任何用户数据加入附件。

## Release 流程

### v0.1.0 本地卷升级

Windows 的 `START_WHALEGUARD.bat` 以及 Linux/WSL 的 `make dev`、`make docker-up` 会在启动 Redis 前自动运行幂等迁移。Windows 受管流程继续使用仓库路径哈希项目名；Linux/WSL 保留 v0.1.0 的固定 `whaleguard-redlab` identity，避免升级后误连空卷。迁移只接受名称与 `com.docker.compose.project` / `com.docker.compose.volume=redis_data` 标签同时匹配、`Scope=local` 且没有 local-driver bind 选项的唯一 volume；若发现其他容器挂载或归属不一致会直接失败。迁移 helper 无网络、只读根文件系统、`cap_drop=ALL`，仅临时增加 `CHOWN` 与只读目录遍历所需的 `DAC_READ_SEARCH`，不会删除卷。随后常驻 Redis 始终以 `redis` 用户和零有效能力运行。

直接使用 Compose 的 Linux/WSL 用户必须先执行：

```bash
python scripts/bootstrap_env.py
WG_PROJECT="$(python scripts/migrate_redis_volume.py --print-project-name)"
python scripts/migrate_redis_volume.py --project-name "$WG_PROJECT"
docker compose --project-name "$WG_PROJECT" --file docker-compose.yml --env-file .env up --build
```

迁移输出 `status=not_needed`、`already_compatible` 或 `migrated` 都是正常且可重复执行的结果；任何 `FAILED` 都必须先排查归属冲突，禁止用宽权限容器绕过。

### A. 冻结候选提交

1. 从 `dev` 创建短生命周期 release PR，只允许阻断性修复和文档校正。
2. 记录候选 commit SHA；后续任何代码变化都会使既有验收证据失效。
3. 在候选 commit 上完成上方所有门禁，并保存 CI URL、测试计数、扫描摘要、SBOM 哈希和 Docker 状态。
4. 由维护者复核 `git diff --check`、工作区、Changelog、迁移和 Release 正文。

最低限度的只读检查：

```powershell
git status --short
git log -1 --format="%H %cs %s"
git diff --check
git tag --list v0.1.1
git remote -v
```

### B. 生成并核对校验文件

在候选 commit 上手工触发 GitHub Actions `Build Release Candidate Artifacts`，输入 `v0.1.1`。该 workflow 只生成无签名候选附件，不创建 tag、GitHub Release 或任何发布状态。下载 `whaleguard-v0.1.1-release-candidate` 后，先核对 `release-metadata.json` 的 commit 和附件清单。

本地等价的源码打包与校验入口：

```powershell
py -3 scripts/security/package_release.py --version v0.1.1 --output-dir artifacts/release
# 安装并验证 Syft/Trivy 后生成 SBOM 与 trivy-source.json。
py -3 scripts/security/generate_checksums.py artifacts/release
```

如果需要独立复算，不要覆盖候选文件；将所有准备上传的附件放进隔离目录后计算哈希。PowerShell 示例：

```powershell
$releaseDir = Resolve-Path .\dist\v0.1.1
Get-ChildItem -LiteralPath $releaseDir -File |
  Where-Object Name -ne 'SHA256SUMS' |
  Sort-Object Name |
  ForEach-Object {
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    "$hash  $($_.Name)"
  } | Set-Content -LiteralPath (Join-Path $releaseDir 'SHA256SUMS') -Encoding ascii
```

随后在新的终端或 CI job 中独立复算并逐项比对。`SHA256SUMS` 只能证明文件完整性，不能代替来源签名、SBOM 或漏洞扫描。

### C. 创建不可变 tag

只有所有阻断项勾选且 release PR 已合入稳定分支后，才允许执行：

```powershell
git tag -a v0.1.1 -m "WhaleGuard AI RedLab v0.1.1 Hardening"
git show --no-patch --format=fuller v0.1.1
git rev-parse 'v0.1.1^{}'
```

推送前再次确认 tag 解引用后的 commit 与已验收 SHA 完全一致。若发布后发现问题，不得移动或覆盖 tag；应撤下有问题的附件、说明影响，并发布新的补丁版本。

### D. 发布与回读

1. 从 `.github/RELEASE_TEMPLATE.md` 填写 Release 正文，删除所有注释占位符。
2. 使用 GitHub 的 annotated tag 创建 Release，上传 SBOM、扫描摘要和 `SHA256SUMS`。
3. 下载已发布附件，重新核对 SHA-256。
4. 从未登录窗口检查 README 图片、架构图、Changelog、Release 正文和附件均可访问。
5. 记录 Release URL、tag commit、CI run URL、附件列表和最终校验结果。

## 版本判定规则

- **READY**：所有阻断项通过，证据来自同一候选 commit，维护者完成回读。
- **NOT READY**：任一阻断项失败、未运行、结果未知、证据属于旧 commit，或 GitHub CI/Release 无法回读。
- **BLOCKED**：明确记录外部阻塞和下一步，但仍不得创建 tag。

WhaleGuard 仅用于本地实验、自有系统或获得明确授权的目标。Release 不能扩大这一安全边界，也不能通过默认配置开放公网服务、真实凭据或未知 MCP Tool 执行能力。
