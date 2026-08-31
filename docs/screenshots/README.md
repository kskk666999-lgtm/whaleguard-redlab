# 实机截图资产清单

此目录只接收 WhaleGuard 在本地授权演示环境中实际运行时捕获的界面。设计稿、AI 生成图、空白框和包含真实凭据/个人数据的图片不得作为产品截图提交。

## 当前资产

| 场景 | 文件 | 尺寸 | 状态 | SHA-256 |
| --- | --- | ---: | --- | --- |
| Dashboard / 系统总览 | [`dashboard-dark.png`](dashboard-dark.png) | 1270×1542 | 已有真实截图 | `6aefc464151dac44df53369106ac54e8cca8d8d17aea158131bed74d76185d56` |
| AgentArena | [`agentarena.png`](agentarena.png) | 1270×714 | 已有真实截图 | `b94b8b727f11d81c94d1276ca025b7f6719d01820a149c67d71bc871d0b39f13` |
| MCPShield Tool 元数据 | [`mcpshield.png`](mcpshield.png) | 1280×720 | 已有真实截图 | `6b6c367fa486ebb50e644c7df78eda0018bd2450c4808e1cc57fee526548574b` |
| Finding 详情与证据 | [`finding-detail.png`](finding-detail.png) | 1280×720 | 已有真实截图 | `65a802b0b6c25f2bf5be17fe08156e9a83afa299aa368f90f2aa3c9b95a911ec` |
| HTML 报告预览 | [`report-preview.png`](report-preview.png) | 1280×720 | 已有真实截图 | `b247ee43be5a2632ac799fa788bd2f6ec6bec2ce72c64a45666f9c4ccc678d5f` |
| 测试运行详情 / SSE 事件 | [`runs.png`](runs.png) | 1280×720 | 已有真实截图 | `4fce2a9525fa11d1bb6bbb191d7bf5a653fe786fb3b0e3ef17bc6c2a3973bf08` |

六张图片均已人工查看，内容与文件名一致，并已验证为具有标准 PNG 文件签名的真实捕获。仓库其他位置发现的 Windows 更新页面图片属于本机安装日志，不是产品界面，也不得复制到公开文档。

v0.2.0 继续引用上述六张已登记的高级工作台实机截图；本次发布没有新增 Beginner Home、Academy 或 Website Wizard 截图，因此 Release Notes 不得声称这些新页面已经重新截图。新手流程由真实栈 Playwright 验证，截图缺失不应以设计稿、空白框或破图链接补齐。

## 已捕获画面

### AgentArena

- 页面：`http://127.0.0.1:3000/arena`
- 捕获状态：展示 Mock Agent、Mock MCP Server 与敏感 Tool 的 `approval_required` 权限围栏。
- 固定文件名：`agentarena.png`

### Finding 详情

- 页面：`http://127.0.0.1:3000/findings`
- 捕获状态：打开由内置演示测试生成的 Finding，画面同时包含严重度、复现摘要、修复建议与 Evidence 入口。
- 固定文件名：`finding-detail.png`

### 报告预览

- 页面：`http://127.0.0.1:3000/reports`
- 捕获状态：预览由虚构演示运行生成的 HTML 报告，展示 Security Score 94.33、Finding 与 Evidence 摘要，不展示本地绝对路径。
- 固定文件名：`report-preview.png`

## 捕获与验收要求

1. 使用当前准备发布的 commit 启动真实 Web/API/Worker 和演示数据，不使用静态 HTML 拼图。
2. 只使用仓库内置虚构项目、目标、Canary、Finding 和用户；不得出现真实姓名、邮箱、Token、API Key、Cookie、内网地址或文件路径。
3. 截图前关闭浏览器开发者工具、密码管理器提示和桌面通知；保留应用自身导航与版本上下文。
4. 建议视口至少 1280×720，优先 PNG；同一 Release 保持主题与缩放一致，不做会改变功能含义的后期编辑。
5. 人工查看图片内容，再记录像素尺寸和 SHA-256。确认无敏感信息后才能将清单状态改为“已有真实截图”。
6. 缺失图片时让 README 显示“待真实捕获”链接到本清单，不创建破图链接，也不拿设计稿冒充。

README 的“实机界面”按 Dashboard → AgentArena → MCPShield → Finding → 报告展示；测试运行详情作为补充截图保留。
