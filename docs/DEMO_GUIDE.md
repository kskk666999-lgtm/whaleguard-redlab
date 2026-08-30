# 演示操作指南

## 目标

在不配置真实 API Key、不下载模型、不使用 GPU 的情况下完成：登录 → 运行本地安全测试 → 查看 Finding/证据 → MCPShield 分析 → 生成报告。

## 演示前准备

1. 按 [RUN_ME_FIRST](../RUN_ME_FIRST.md) 启动环境，确认 8 个服务 healthy，API `/ready` 的数据库状态为 `ok`。
2. 使用 `.local/first-run-credentials.txt` 中的本地一次性凭据登录；不要投屏或复制凭据内容。
3. 确认演示数据中已有一条 `completed` Run、至少一条 Finding 和一份 HTML 报告。现场新 Run 如果尚未完成，可以明确展示队列状态，再切到这条已完成的演示记录。
4. 浏览器只保留 WhaleGuard 标签页，关闭开发者工具、密码管理器提示和桌面通知。

## 5 分钟 Demo 流程

| 时间 | 页面 | 展示重点 |
| --- | --- | --- |
| 0:00–0:35 | 系统总览 | 一句话定位：local-first、可审计的 LLM/Agent/MCP 安全评估工作台；指出 Scope Guard 已启用、Docker 演示靶场为私有网络。 |
| 0:35–1:25 | 测试运行中心 | 选择 `WhaleGuard Demo Lab`、内置安全测试套件和 Mock Agent，发起新 Run；说明每个请求先过授权 Scope。 |
| 1:25–2:10 | 已完成 Run | 打开预先完成的 Run，展示状态、进度、Security Score、增量事件和规则解释；不要把排队中的 Run 说成已完成。 |
| 2:10–2:50 | Findings / Evidence | 打开一条虚构 Finding，展示严重度、复现摘要、证据 SHA-256 和修复建议。 |
| 2:50–3:30 | MCPShield | 对 Mock MCP Server 做元数据分析，指出 `execution_performed: false`：默认不执行未知 Tool。 |
| 3:30–4:10 | AgentArena | 展示普通演示 Tool 和敏感 Tool；敏感操作必须停在 `waiting_approval`。 |
| 4:10–4:45 | 报告中心 | 打开已生成的 HTML 报告，展示摘要、Finding 和报告哈希；说明同时支持 Markdown/JSON。 |
| 4:45–5:00 | 审计日志 | 展示登录、Run、审批、MCP 分析和报告操作的审计记录，用授权边界收尾。 |

推荐开场：**“WhaleGuard 不替你攻击公网目标；它把经过授权的 AI 安全测试、证据和审计收进一个本地工作台。”**

推荐收尾：**“所有演示目标和数据都是虚构的，未知 MCP Tool 默认不执行，v0.1.1 只有在完整发布门禁通过后才会打 tag。”**

## 完整操作流程

1. 按 [RUN_ME_FIRST](../RUN_ME_FIRST.md) 启动并登录。
2. 总览确认项目、Mock Agent、Mock MCP Server 和内置测试套件已初始化。
3. 进入 **测试运行中心**，选择 `WhaleGuard Demo Lab` 和 `AgentArena 基础安全测试`，目标选择 Mock Agent。
4. 运行状态从 `queued` 进入 `running`，最终到 `completed` 或明确的失败状态。详情中可查看 SSE 事件、规则评分和解释。
5. 在 **Findings** 打开本次运行生成的 Finding，核对复现摘要、影响、证据和修复建议；可更新状态。
6. 在 **MCPShield** 选择演示 MCP Server 并点击静态分析。结果必须显示 `execution_performed: false`，且包含风险分、依据和建议。
7. 在 **AgentArena** 运行天气工具；敏感演示工具必须停在 `waiting_approval`。
8. 在 **报告中心** 创建报告、生成并下载 HTML；Markdown/JSON 也可导出。
9. 在 **审计日志** 验证登录、运行、MCP 分析和报告操作均已记录。

## 演示数据声明

所有文档、Canary、天气、工具输出和 Finding 均为虚构演示数据。Mock 结果会明确标识为模拟，不能当作真实模型评估结论。
