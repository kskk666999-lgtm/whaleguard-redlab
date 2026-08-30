## 这次解决什么 / Purpose

<!-- 用 2–4 句话说明问题、用户影响和本 PR 的边界。 -->

## 变更类型 / Change type

- [ ] 可靠性 / Reliability
- [ ] 安全修复或加固 / Security
- [ ] 数据库迁移 / Database migration
- [ ] CI 或供应链 / CI & supply chain
- [ ] 文档 / Documentation
- [ ] 其他（请说明）

## 主要变化 / What changed

-

## 安全边界 / Safety boundary

- [ ] 仍然只面向本地实验、自有系统或获得明确授权的目标。
- [ ] 没有新增未授权公网扫描、爆破、恶意载荷、任意 Shell 或未知 MCP Tool 自动执行。
- [ ] Web/API 端口仍默认只绑定回环地址，Mock 服务仍留在 Docker 私有网络。
- [ ] 没有提交 `.env`、凭据、Token、Cookie、API Key、用户数据或未脱敏日志/截图。
- [ ] 新增网络、文件、命令或工具能力已经过 Scope Guard/审批边界审查，或本 PR 不涉及这些能力。

## 数据与兼容性 / Data & compatibility

- [ ] 不涉及数据库 Schema。
- [ ] 涉及 Schema：已提供 Alembic upgrade/downgrade，并验证 `upgrade -> downgrade -> upgrade`。
- [ ] 保持现有 API/SSE/报告兼容，或已在下方明确列出破坏性变化和迁移方式。

兼容性说明：

<!-- 不适用时写“不适用”，不要留空。 -->

## 实际验证 / Verification

| 检查 | 结果与证据 |
| --- | --- |
| Python / Scope Guard / Worker / Mock tests |  |
| Frontend lint / typecheck / component / build |  |
| Playwright |  |
| Alembic |  |
| Docker 8-service health + smoke |  |
| RQ idempotency / multi-worker（如适用） |  |
| Dependency / secret / image scan（如适用） |  |

- [ ] 没有 skip 新增、断言删除、异常吞没、health check 移除或扫描关闭。
- [ ] 所有结果来自本 PR 最新 commit；push 新提交后已重新执行受影响的验证。
- [ ] 未运行的项目已在下方说明原因和发布影响。

未运行或已知限制：

<!-- “未运行”不是“通过”。如果影响发布门禁，请明确标为阻断。 -->

## 截图或输出 / Screenshots or output

<!-- 仅附真实、已脱敏的界面或短日志；文档专用/无界面变化可写“不适用”。 -->

## Release 影响

- [ ] 不需要 Changelog。
- [ ] 已更新 `CHANGELOG.md` 的 `[Unreleased]`。
- [ ] 已同步 README、发布手册、架构/API/部署文档中的受影响内容。
- [ ] 本 PR 完成后仍有 v0.1.1 阻断项，**不得打 tag**。
- [ ] 本 PR 连同其他证据满足发布门禁；最终 ready 判定仍由维护者按 `docs/RELEASE.md` 完成。

## Reviewer 重点

<!-- 指出最希望复核的事务边界、并发路径、权限、迁移或失败模式。 -->
