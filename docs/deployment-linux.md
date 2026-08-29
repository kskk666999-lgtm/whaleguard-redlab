# Linux 部署

支持现代 x86_64/arm64 Linux、Docker Engine 24+、Compose v2。

在已检出的仓库根目录运行：

```bash
python3 scripts/bootstrap_env.py
```

默认镜像内用户使用 UID/GID `1000:1000`。若当前非 root 用户的 `id -u` 或 `id -g` 不是 `1000`，先把 `.env` 中两项改为命令返回值，以确保 API 对 bind mount 的 `.local` 目录有写权限：

```bash
sed -i "s/^WHALEGUARD_APP_UID=.*/WHALEGUARD_APP_UID=$(id -u)/" .env
sed -i "s/^WHALEGUARD_APP_GID=.*/WHALEGUARD_APP_GID=$(id -g)/" .env
```

不要以 root（UID 0）构建此映射；请改用普通用户。然后启动：

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

默认仅监听 `127.0.0.1`。如需团队访问，推荐在同机反向代理后启用 HTTPS、受信任身份代理和主机防火墙；不要直接把 3000/8000 改为 `0.0.0.0` 暴露公网。

备份 PostgreSQL volume、附件 volume 与本地 `.env` 密钥。丢失 `WHALEGUARD_ENCRYPTION_SECRET` 会导致已保存的模型密钥无法解密。
