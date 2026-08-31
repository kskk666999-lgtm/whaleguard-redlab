# 第一次运行 WhaleGuard

本指南使用 Docker Compose；对应的首次凭据文件是 `.local\first-run-credentials.txt`。本机 `make seed` 的 SQLite 凭据另存为 `.local\local-first-run-credentials.txt`，不能用于 Docker 数据库。

## 先看版本状态

- `v0.2.0 Beginner Experience / Academy` 是当前正式版本，包含本文所述的新手引导、简化首页、Academy 学习体验和网站三步体检；正式身份以 annotated tag `v0.2.0` 解引用的 commit 为准。
- `v0.1.1 Hardening` 是上一稳定基线，正式发布 commit 为 `dbbbd000067b4c161d6ff9029882c77a226d8101`。
- 当前工作区的真实运行状态以 `CHECK_WHALEGUARD.bat`、API `/ready` 和登录后的“系统检查”结果为准，不沿用旧版本验收结论。

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
2. 双击项目根目录的 `START_WHALEGUARD.bat`。这是日常启动入口；不需要先打开终端运行 Compose 命令。
3. 等待 db、redis、api、worker、web、mock-llm、mock-agent、mock-mcp-server 全部 `running/healthy`，且 API `/ready` 数据库状态为 `ok`；成功后浏览器才会打开。首次生成 `.env` 不需要另装 Python，失败诊断的脱敏日志保存在 `.local\logs\`。
4. 按启动终端显示的路径打开 `.local\first-run-credentials.txt`。用户名默认为 `admin`（也可使用 `admin@whaleguard.local`），密码为首次启动随机生成值；服务日志不会输出密码，这个文件也不会提交到 Git。
5. 首次登录会进入四步新手引导：选择目标、检查系统、选择模型、开始使用。模型和 API Key 都可以跳过；Academy 与网站规则体检不依赖外部模型。
6. 新手首页提供三条真实路径：**学习 AI 安全**、**检查我的网站**、**查看已有结果**。它们分别进入 Academy、网站体检和 Findings，不会在后台偷偷发起其他测试。
7. 右上角可以在新手模式与高级模式之间切换。切换只改变首页和导航密度，不会放宽 Scope Guard、RBAC 或审计边界；“帮助”页可以重新打开新手引导。
8. 使用完毕后双击 `STOP_WHALEGUARD.bat`；它只停止由当前仓库规范路径哈希隔离的 Compose 项目并保留数据卷。

## 第一次建议走哪条路

- 想从零学习：进入 **安全学院**，先看 10 个短微课，再从 B01 开始；全部使用本地虚构数据，不需要 API Key。
- 想检查自己的站点：进入 **网站体检**，按“输入精确网址 → 确认授权 → 可选 AI”三步操作。平台会在需要时自动创建“我的网站体检”项目，并建立 24 小时精确 URL Scope。
- 已经运行过测试：进入 **Findings** 或 **报告** 查看本地已保存结果；这个入口不会重新请求目标。

详细说明见 [Academy Range](docs/ACADEMY_RANGE.md) 与 [网站一键体检](docs/WEBSITE_SCAN_QUICKSTART.md)。

遇到问题先双击 `CHECK_WHALEGUARD.bat`。需要重新生成全部演示数据和首次凭据时使用 `RESET_DEMO.bat`，它会要求输入 `RESET`，并且只删除当前仓库路径哈希隔离的 WhaleGuard Compose 数据卷与本项目凭据文件；`.env` 中的加密密钥会保留。

默认地址：<http://127.0.0.1:3000>。默认演示不需要 API Key、模型下载或 GPU。
