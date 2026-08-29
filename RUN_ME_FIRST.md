# 第一次运行 WhaleGuard

本指南使用 Docker Compose；对应的首次凭据文件是 `.local\first-run-credentials.txt`。本机 `make seed` 的 SQLite 凭据另存为 `.local\local-first-run-credentials.txt`，不能用于 Docker 数据库。

1. 安装并启动 Docker Desktop，等待状态显示 Engine running。
2. 双击项目根目录的 `START_WHALEGUARD.bat`。
3. 等待构建和健康检查完成；成功后浏览器会自动打开。
4. 按启动终端显示的路径打开 `.local\first-run-credentials.txt`。用户名默认为 `admin`（也可使用 `admin@whaleguard.local`），密码为首次启动随机生成值；服务日志不会输出密码，这个文件也不会提交到 Git。
5. 登录后进入 **WhaleGuard Demo Lab**。
6. 打开 **测试运行中心**，运行 **AgentArena 基础安全测试**。
7. 在 **Findings** 查看证据与修复建议，在 **MCPShield** 分析演示 Server，在 **报告中心** 生成 HTML 报告。
8. 使用完毕后双击 `STOP_WHALEGUARD.bat`；它会保留数据。

遇到问题先双击 `CHECK_WHALEGUARD.bat`。需要重新生成全部演示数据和首次凭据时使用 `RESET_DEMO.bat`，它会要求输入 `RESET`，并且只删除当前 `whaleguard-redlab` Compose 项目的数据卷与本项目凭据文件；`.env` 中的加密密钥会保留。

默认地址：<http://127.0.0.1:3000>。默认演示不需要 API Key、模型下载或 GPU。
