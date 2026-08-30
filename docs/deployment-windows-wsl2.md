# Windows 11 + WSL2

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
