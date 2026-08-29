# WhaleGuard 内置安全测试集

`builtin-safe.yaml` 只包含面向本地模拟目标的无破坏性测试数据。所有秘密、凭据、工具和文档均为虚构演示内容；模板不得直接用于未授权目标。

每条用例均包含 `id`、`name`、`category`、`severity`、`description`、`input`、`context`、`expected_behavior`、`forbidden_behavior`、`evaluator`、`tags` 和 `references`。默认先执行规则评估器，只有显式启用且项目已配置模型渠道时才使用可选的 LLM Judge。
