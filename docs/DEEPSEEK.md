# DeepSeek 连接与 AI 解读

DeepSeek 是 WhaleGuard 的**可选增强能力**。不配置 API Key，也可以完整使用安全学院、Scope Guard、规则评分和网站的 13 项只读检查。

## 最简单的连接方法

1. 打开 WhaleGuard，进入“网站体检”或高级模式的“模型渠道”。
2. 选择 `DeepSeek Compatible`。
3. API 地址填写 `https://api.deepseek.com/v1`，模型填写 `deepseek-chat`。
4. 粘贴自己的 API Key，然后点击“保存并测试真实连接”。
5. 页面显示“连接成功”后即可在网站体检中选择该渠道。

API Key 只在本次提交时从输入框发送给本机 API，不写入浏览器存储；后端加密保存，之后的查询接口只返回掩码。不要把真实 Key 写入 `.env`、截图、Issue、日志或仓库。

同一项目中最近一次连接测试成功的 DeepSeek/OpenAI-compatible 渠道，也可以自动增强 Academy 的“问鲸鱼导师”。导师只接收课程元数据和 allow-list 事件类型摘要；没有合格渠道或模型失败时会自动使用本地确定性解释。

## 安全边界

- 只有用户明确确认模型服务授权时，系统才为模型的 `/models` 与 `/chat/completions` 端点建立短期精确 Scope。
- 模型请求仍经过 Scope Guard；DNS 解析、实际 IP、协议、端口、路径和重定向都会重新检查。
- 网站体检只把已经收集并脱敏的规则结果交给模型解释，不允许模型覆盖确定性 Finding。
- AI 解读不是漏洞证明，也不会扩大网站扫描范围。

## 结构化结果兼容

WhaleGuard 会优先请求 JSON 结构化输出，并对结果进行严格 Schema 验证。解析器可以处理普通 JSON、Markdown JSON 代码块以及 JSON 前后的少量说明文字。

如果 DeepSeek 超时、返回服务错误或结构不符合 Schema：

- 13 项规则检查、Finding、Evidence 和报告仍然有效；
- 页面显示“规则分析已完成，AI 增强结果解析失败”；
- 可以点击“重新生成 AI 解读”，只重新调用模型，不会再次访问被检查网站。

## 常见问题

### 连接测试成功，但体检显示 AI 解读失败

先打开结果中的失败原因。它只保留脱敏后的错误类别，不记录 Key 或完整上游响应。可以直接重试 AI 解读；无需重新扫描目标。

### 不想产生模型费用

在网站体检第三步选择“不使用 AI”，或完全不配置模型。规则引擎会照常生成得分、Finding、Evidence 和报告。

### Key 泄露了怎么办

立即在 DeepSeek 控制台撤销该 Key，再在 WhaleGuard 中保存新 Key。不要把旧 Key 发到聊天、日志或 Git 历史中。
