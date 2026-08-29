# 第一次运行 WhaleGuard

本指南使用 Docker Compose；对应的首次凭据文件是 `.local\first-run-credentials.txt`。本机 `make seed` 的 SQLite 凭据另存为 `.local\local-first-run-credentials.txt`，不能用于 Docker 数据库。

## 当前验证主机状态

当前主机是 Windows 11 家庭中文版 23H2 build 22631，并安装了 VirtualBox 5.2.30。两者均未通过仓库当前的一键安装兼容门禁。首轮 UAC 已接受，但 WSL web-download 返回 HTTP 403；VirtualMachinePlatform 仅暂存、尚未重启，没有注册自动续作入口，Docker CLI/Desktop/Engine 也未安装。因此当前主机尚未运行 Docker build/up、产品 smoke 或持久化测试。代码侧 136 项自动化回归已通过，但不能替代 Docker 运行证据。

请先升级 Windows，并升级或卸载 VirtualBox 5.2.30。不要绕过门禁，也不要把 VMP 已暂存当作 WSL2/Docker 已可用。

## Windows 首次一键安装

通过兼容门禁后，双击项目根目录的：

```powershell
.\INSTALL_WHALEGUARD_DOCKER.bat
```

脚本先做只读兼容预检，通过后申请一次 UAC。它不会自动重启；只有提升阶段成功完成且确实需要重启时，才会注册当前用户 Startup 中有三次硬上限的一次性快捷方式。保存工作并由用户自行重启后，脚本会在登录时续作；手工恢复入口是：

```powershell
.\RESUME_AFTER_REBOOT.bat
```

如果提升阶段失败且没有自动续作入口，请先修复日志所示阻塞，再重新运行安装入口，不要直接假设恢复阶段可以继续。安装与续作日志位于 `.local\setup-logs\`。

## 已有 Docker 的运行门槛

先在 PowerShell 执行：

```powershell
docker version
docker compose version
```

两条命令都必须成功并显示 Server/Compose 版本。若提示 `docker` 命令不存在，需先安装 Docker Desktop；若只有 Client、没有 Server，应启动 Docker Desktop 并等待 WSL2 Engine 就绪。不要在这两项失败时把后续 Compose 配置校验当成完整启动成功。

1. 安装并启动本地 Docker Desktop，等待状态显示 Engine running；远程 Docker context 会被默认拒绝。
2. 双击项目根目录的 `START_WHALEGUARD.bat`。
3. 等待 db、redis、api、worker、web、mock-llm、mock-agent、mock-mcp-server 全部 `running/healthy`，且 API `/ready` 数据库状态为 `ok`；成功后浏览器才会打开。首次生成 `.env` 不需要另装 Python，失败诊断的脱敏日志保存在 `.local\logs\`。
4. 按启动终端显示的路径打开 `.local\first-run-credentials.txt`。用户名默认为 `admin`（也可使用 `admin@whaleguard.local`），密码为首次启动随机生成值；服务日志不会输出密码，这个文件也不会提交到 Git。
5. 登录后进入 **WhaleGuard Demo Lab**。
6. 打开 **测试运行中心**，运行 **AgentArena 基础安全测试**。
7. 在 **Findings** 查看证据与修复建议，在 **MCPShield** 分析演示 Server，在 **报告中心** 生成 HTML 报告。
8. 使用完毕后双击 `STOP_WHALEGUARD.bat`；它只停止由当前仓库规范路径哈希隔离的 Compose 项目并保留数据卷。

遇到问题先双击 `CHECK_WHALEGUARD.bat`。需要重新生成全部演示数据和首次凭据时使用 `RESET_DEMO.bat`，它会要求输入 `RESET`，并且只删除当前仓库路径哈希隔离的 WhaleGuard Compose 数据卷与本项目凭据文件；`.env` 中的加密密钥会保留。

默认地址：<http://127.0.0.1:3000>。默认演示不需要 API Key、模型下载或 GPU。
