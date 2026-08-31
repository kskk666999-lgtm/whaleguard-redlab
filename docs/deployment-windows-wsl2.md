# Windows 11 + WSL2

## 推荐：Windows 双击启动

Docker Desktop 已安装后，在仓库根目录双击：

- `START_WHALEGUARD.bat`：按需启动 Docker Desktop、恢复当前仓库的历史 Compose 项目、等待 8 个服务健康并打开浏览器。
- `STOP_WHALEGUARD.bat`：停止 WhaleGuard 容器但保留数据库和其他 volume。
- `DIAGNOSE_WHALEGUARD.bat`：只读检查 Docker、服务、端口和健康状态，生成脱敏诊断。
- `CREATE_DESKTOP_SHORTCUT.bat`：可选创建桌面快捷方式；不会配置开机自启动。

入口只允许官方签名的本机 Docker Desktop CLI 和 Linux Engine，不使用远程 context，不停止无关 WSL/Docker 工作负载。若发现多个归属不明确的 Compose 项目会停止并要求诊断，不会猜测或删除 volume。

首次启动成功后访问 <http://127.0.0.1:3000>。随机管理员凭据在 `.local/first-run-credentials.txt`，该文件已被 Git 忽略且不得上传。

如果尚未安装 Docker Desktop，可使用 `INSTALL_WHALEGUARD_DOCKER.bat` 运行项目的受控安装流程；它不会在未确认兼容性时自动重启 Windows。

## 高级：从 WSL2 开发

1. 在 Windows 功能中启用 WSL2 与虚拟机平台，安装 Ubuntu LTS。
2. 安装 Docker Desktop 并启用 WSL2 backend / 对所用 Ubuntu 发行版的集成。
3. 建议把仓库放在 WSL 的 Linux 文件系统中以提高容器构建速度；若保留在 `C:`，从 `/mnt/c/...` 进入。
4. 在 WSL 终端运行：

```bash
python3 scripts/bootstrap_env.py
```

WSL 中先运行 `id -u` 和 `id -g`。若任一结果不是 `1000`，把 `.env` 的 `WHALEGUARD_APP_UID`、`WHALEGUARD_APP_GID` 改为当前非 root 用户的实际值（不要设为 `0`）：

```bash
sed -i "s/^WHALEGUARD_APP_UID=.*/WHALEGUARD_APP_UID=$(id -u)/" .env
sed -i "s/^WHALEGUARD_APP_GID=.*/WHALEGUARD_APP_GID=$(id -g)/" .env
```

随后运行：

```bash
make compose-check
make dev
```

5. Windows 浏览器访问 <http://127.0.0.1:3000>。只有 Web/API 绑定回环地址，Mock 服务不会暴露到 Windows 网络。

若公司 VPN 改写 Docker DNS，请先查看 `docker compose logs api` 中的 Scope Guard 判定；不要通过关闭 Scope Guard 解决网络问题，应显式添加获授权域名并核对解析 IP。
