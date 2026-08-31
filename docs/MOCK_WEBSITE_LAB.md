# 本地网站被动体检靶页

WhaleGuard 在现有 `mock-agent` 容器中提供一个无破坏性的静态网站样本：

```text
http://mock-agent:8102/demo-site
```

该地址仅能从 Compose 的 `arena` 私有网络访问，不映射宿主机端口。API 与其他已加入 `arena` 的授权组件可以访问它；浏览器不能直接把该容器域名当作公网网站打开。

## 可观察项

靶页只提供 `GET /demo-site`，内容和 Cookie 都是固定虚构数据。它刻意保留下列适合被动规则识别的加固缺失：

- 使用 Docker 私网中的 HTTP；
- 未设置 CSP、HSTS、`X-Frame-Options`、`Referrer-Policy` 和 `Permissions-Policy`；
- 非敏感主题偏好 Cookie 没有 `Secure` 与 `HttpOnly`，但不承载身份、会话或权限。

`GET /health` 仍是容器健康检查入口。靶页不包含登录、认证、上传、命令执行、重定向、用户输入反射、真实凭据或敏感数据，也没有用于主动利用的接口。

## 安全边界

只把目标填写为 `http://mock-agent:8102/demo-site`，并保持项目授权 Scope、Scope Guard 与私有网络限制开启。第一版只应做响应状态、响应头、Cookie 属性和页面元数据等只读检查；不要将该示例扩展为漏洞利用或任意请求代理。
