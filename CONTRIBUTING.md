# Contributing

感谢你改进 WhaleGuard。提交前请确认：

1. 改动只服务于本地、自有或明确授权的 AI 安全评估，不新增项目禁止能力。
2. 新外部请求点经过 Scope Guard；新高风险 Tool 需要服务端强制审批。
3. 测试数据使用虚构值，不提交 API Key、token、Cookie 或真实客户数据。
4. 新 MCP 分析默认只读元数据，不自动启动或调用未知 Tool。
5. 运行 `make lint`、`make test`、前端构建和相关 E2E；在 PR 中如实列出无法执行的环境验收。

Bug 修复请包含回归测试。数据库模型变更必须提供可向前执行的 Alembic migration，不通过删除开发数据库掩盖迁移问题。

Pull Request 会自动加载仓库模板；请填写最新 commit 的实际结果，并把“未运行”与“通过”严格区分。影响用户可见行为、兼容性或发布门禁的改动应同步 `CHANGELOG.md` 的 `[Unreleased]`。版本 ready 判定见 [发布手册](docs/RELEASE.md)，任何阻断项未通过时都不得创建正式 tag。
