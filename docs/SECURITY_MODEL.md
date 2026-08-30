# 安全模型

## 安全目标

1. 未明确授权的公网目标默认不可达。
2. 模型 API Key、JWT 密钥和数据库凭据不以明文进入仓库、响应或审计日志。
3. 高风险 Tool 在人工批准前不得执行。
4. 每次策略允许/拒绝、运行状态变化、审批和导出均可审计。
5. 不可信模型输出、MCP 描述和上传内容不能成为代码、命令或 HTML 执行。

## Scope Guard 判定顺序

1. 仅接受 `http` / `https`；拒绝 `file`、`gopher`、`ftp`、`dict` 等协议和 URL userinfo。
2. 校验项目、授权状态、到期时间和请求类型。
3. 解析全部 A/AAAA 记录，将 IPv4-mapped IPv6 归一化为 IPv4。
4. 任一解析结果不符合授权则整体失败关闭，防止混合 DNS/DNS rebinding 绕过。
5. 默认只允许 loopback、RFC1918 和 ULA；link-local、组播、保留地址及未授权公网地址失败关闭。公网域名/IP 必须显式添加并确认 `allow_public`。
6. 每一个重定向目标重新执行完整校验并限制跳数。
7. high/critical Tool 要求人工审批；critical Tool 还可由部署策略永久禁用。
8. 记录结构化 PolicyDecision，不记录凭据和完整敏感内容。

应用必须使用受控 HTTP client，不能绕过 Scope Guard 直接实例化通用客户端。受控客户端把连接固定到已检查的解析地址，并对每次重定向重新判定；生产部署仍建议叠加出口代理/防火墙，形成网络层 deny-by-default 的纵深防御。

## 身份与密钥

- 密码：Argon2id 哈希，永不返回。
- 登录：短期 JWT；浏览器同时使用 CSRF 双提交令牌进行状态变更保护。
- 模型密钥：Fernet/AES 级别的认证加密，列表和详情只返回掩码。
- 初始管理员：密码由安全随机数生成，只写入权限受限且被忽略的首次启动凭据文件；日志仅打印文件路径。
- 日志：Authorization、Cookie、API Key、token-like 值、带认证信息的 URL 和异常内容先脱敏再写入 `.local/logs/`；脚本不读取或记录 `.env` 与首次凭据文件内容。

## 输入与输出

- ORM 参数绑定避免 SQL 注入；Pydantic/Zod 执行类型与长度校验。
- 上传限制大小、MIME、扩展名；服务端生成存储名并校验最终路径在上传根内。
- 报告模板开启 autoescape，CSP 禁止内联脚本；附件提供哈希与下载白名单。
- MCP JSON 只作为数据解析，绝不启动其中的 command/args。

## 异步投递与回调

- 测试完成与 Outbox 写入处于同一数据库事务；未提交的结果不能提前入队。
- Worker 只消费 allowlist 中的数据型评分函数，RQ 使用 JSON serializer，禁止任意函数、实例方法和回调对象。
- 每次投递使用 UUID `delivery_id`；`DeliveryReceipt` 的数据库唯一约束保证同一运行只应用一次业务结果，进程锁不作为生产安全边界。
- 回调的 `delivery_id` 必须来自同一 Run 已处理的 Outbox；任意新 UUID 即使携带 Worker Token 也不能写入业务状态。Outbox 对 Run 使用级联外键，并在入队前复核所属对象。
- 重复 ID 携带不同内容时失败关闭并记录拒绝审计；Worker 执行耗时等非业务抖动字段不参与内容一致性哈希。
- 运行事件只保存有界、递归脱敏的 payload。Authorization、Cookie、凭据、密码、secret 和 token-like 键值均替换为 `[REDACTED]`。

## Windows Docker 执行边界

- 只接受 Docker Desktop 的本机 Windows named pipe；远程 TCP/SSH context 和 Docker 客户端覆盖变量失败关闭。
- Desktop、CLI 与 Compose 插件必须来自同一个当前用户安装根，并通过 Docker Inc. 签名、产品名和最低版本门禁。
- Compose 使用隔离、无 BOM 的受管 CLI 配置；高优先级插件目录、`.env`/进程环境中的 `COMPOSE_BAKE` 与 `BUILDX_BAKE_*` 均被拒绝。
- Compose project name 包含规范仓库根路径的稳定 SHA-256 短后缀，避免不同检出目录复用同名容器、卷或网络；已有容器还必须带有匹配的 Compose working-directory 标签。
- 安装流程不执行全局 `wsl --shutdown`；安装、修复或升级前若发现活动 Docker Desktop、Engine 或容器，会要求显式决策，不会静默中断其他工作负载。
- UAC 提升阶段使用父进程内存中构造、Parser 校验的 EncodedCommand；高完整性进程只调用真实 System32 的 DISM/WSL，不读取或写入用户可修改的仓库脚本。

## 非目标

平台不是渗透测试自动利用框架，不支持任意 Shell、恶意载荷、凭据采集、爆破、C2、持久化或防检测。发现此类扩展请求时应拒绝并保留审计记录。
