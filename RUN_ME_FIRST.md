# 第一次运行 WhaleGuard

本指南使用 Docker Compose；对应的首次凭据文件是 `.local\first-run-credentials.txt`。本机 `make seed` 的 SQLite 凭据另存为 `.local\local-first-run-credentials.txt`，不能用于 Docker 数据库。

## 当前验证状态

`v0.1.0` 基线已于 2026-08-31 在当前 Windows 主机完成 Docker 验收：8 个 Compose 服务全部 healthy，API `/ready` 数据库状态为 `ok`，产品 smoke、真实 RQ callback、`restart` 和完整 `down/up` 持久化均已通过。稳定 tag 指向隐私化公开历史中的 `6438ff2975eabe3059297ba1fb0d0728b9d78464`。

`v0.1.1 Hardening` 正在开发，必须在最终 commit 上重新执行全部 [发布门禁](docs/RELEASE.md)；上述 v0.1.0 结果不能直接继承为新版本证据。

## Windows 首次一键安装

双击项目根目录的：

```powershell
.\INSTALL_WHALEGUARD_DOCKER.bat
```

脚本先做只读兼容预检，通过后申请一次 UAC。它不会自动重启；只有提升阶段成功完成且确实需要重启时，才会注册当前用户 Startup 中有三次硬上限的一次性快捷方式。保存工作并由用户自行重启后，脚本会在登录时续作；手工恢复入口是：

```powershell
.\RESUME_AFTER_REBOOT.bat
```

如果提升阶段失败且没有自动续作入口，请先修复日志所示阻塞，再重新运行安装入口，不要直接假设恢复阶段可以继续。安装与续作日志位于 `.local\setup-logs\`。

## 已有 Docker 的启动

若当前 PowerShell 已能找到 Docker CLI，可先执行以下只读检查：

```powershell
docker version
docker compose version
```

两条命令成功时应同时显示 Server 和 Compose 版本。项目的一键脚本也支持经过签名验证的当前用户 Docker Desktop 安装，因此普通终端暂时找不到 `docker` 命令时，不应仅凭 PATH 结果判断 Docker 未安装；先运行 `CHECK_WHALEGUARD.bat` 或直接使用下方受控启动入口。若只有 Client、没有 Server，应启动 Docker Desktop 并等待 WSL2 Engine 就绪。不要把 Compose 配置解析通过当成完整启动成功。

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
