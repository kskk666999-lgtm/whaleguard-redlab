# 演示操作指南

## 目标

在不配置真实 API Key、不下载模型、不使用 GPU 的情况下完成：登录 → 运行本地安全测试 → 查看 Finding/证据 → MCPShield 分析 → 生成报告。

## 最短流程

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
