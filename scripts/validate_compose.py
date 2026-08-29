from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _service_networks(service: dict) -> set[str]:
    configured = service.get("networks", [])
    return set(configured) if not isinstance(configured, dict) else set(configured)


def main() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose.get("services", {})
    required = {
        "db",
        "redis",
        "api",
        "worker",
        "web",
        "mock-llm",
        "mock-agent",
        "mock-mcp-server",
    }
    missing = required.difference(services)
    if missing:
        raise SystemExit(f"missing services: {sorted(missing)}")
    for name, service in services.items():
        if service.get("privileged"):
            raise SystemExit(f"{name}: privileged containers are forbidden")
        for published in service.get("ports", []):
            if not str(published).startswith("127.0.0.1:"):
                raise SystemExit(f"{name}: published port must bind 127.0.0.1: {published}")
        build = service.get("build")
        if isinstance(build, dict):
            if "no-new-privileges:true" not in service.get("security_opt", []):
                raise SystemExit(f"{name}: no-new-privileges is required")
            if "ALL" not in service.get("cap_drop", []):
                raise SystemExit(f"{name}: all Linux capabilities must be dropped")
            context = (ROOT / build["context"]).resolve()
            dockerfile = context / build.get("dockerfile", "Dockerfile")
            if not dockerfile.is_file():
                raise SystemExit(f"{name}: Dockerfile not found: {dockerfile}")
            user_lines = [
                line.split(maxsplit=1)[1].strip()
                for line in dockerfile.read_text(encoding="utf-8").splitlines()
                if line.strip().upper().startswith("USER ")
            ]
            if not user_lines or user_lines[-1].casefold() in {"root", "0", "0:0"}:
                raise SystemExit(f"{name}: final Docker image user must be non-root")
    for name in ("db", "redis", "worker"):
        if services[name].get("env_file"):
            raise SystemExit(f"{name}: must not inherit the complete secret environment")
    for name in ("worker", "web", "mock-llm", "mock-agent", "mock-mcp-server"):
        if services[name].get("read_only") is not True:
            raise SystemExit(f"{name}: root filesystem must be read-only")
    redis_healthcheck = " ".join(str(item) for item in services["redis"]["healthcheck"]["test"])
    if " -a " in redis_healthcheck or "--pass" in redis_healthcheck:
        raise SystemExit("redis: healthcheck must not expose its password as an argument")
    for name in ("mock-llm", "mock-agent", "mock-mcp-server"):
        if services[name].get("ports"):
            raise SystemExit(f"{name}: AgentArena services cannot publish host ports")
        if "arena" not in _service_networks(services[name]):
            raise SystemExit(f"{name}: AgentArena service must use arena network")
    networks = compose.get("networks", {})
    for isolated_network in ("backend", "arena"):
        if not networks.get(isolated_network, {}).get("internal"):
            raise SystemExit(f"{isolated_network} network must be internal")

    expected_members = {
        "edge": {"api", "web"},
        "backend": {"db", "redis", "api", "worker"},
        "arena": {"api", "mock-llm", "mock-agent", "mock-mcp-server"},
    }
    for network, expected in expected_members.items():
        actual = {
            name for name, service in services.items() if network in _service_networks(service)
        }
        if actual != expected:
            raise SystemExit(
                f"{network}: expected isolated members {sorted(expected)}, got {sorted(actual)}"
            )

    api_environment = services["api"].get("environment", {})
    worker_environment = services["worker"].get("environment", {})
    web_environment = services["web"].get("environment", {})
    web_build_args = services["web"].get("build", {}).get("args", {})
    expected_api_url = "http://127.0.0.1:${API_PORT:-8000}/api/v1"
    expected_origins = "http://127.0.0.1:${WEB_PORT:-3000},http://localhost:${WEB_PORT:-3000}"
    if web_environment.get("NEXT_PUBLIC_API_URL") != expected_api_url:
        raise SystemExit("web: runtime API URL must follow the published API_PORT")
    if web_build_args.get("NEXT_PUBLIC_API_URL") != expected_api_url:
        raise SystemExit("web: build-time API URL must follow the published API_PORT")
    if api_environment.get("WHALEGUARD_ALLOWED_ORIGINS") != expected_origins:
        raise SystemExit("api: CORS origins must follow the published WEB_PORT")
    expected_queue = "${RQ_QUEUE:-whaleguard}"
    if api_environment.get("RQ_QUEUE") != expected_queue:
        raise SystemExit("api: RQ_QUEUE must use the shared Compose setting")
    if worker_environment.get("RQ_QUEUE") != expected_queue:
        raise SystemExit("worker: RQ_QUEUE must use the shared Compose setting")
    print(f"validated {len(services)} compose services and private-network invariants")


if __name__ == "__main__":
    main()
