"""Destructive-to-containers, non-destructive-to-data Docker resilience acceptance.

This script only manipulates containers owned by the ``whaleguard-redlab``
Compose project. It never removes managed project data volumes. One isolated,
uniquely labeled Redis upgrade fixture volume is removed after its test. The
normal one-worker/eight-service topology is always restored before exit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

PROJECT_PREFIX = "whaleguard-redlab"
EXPECTED_SERVICES = {
    "api",
    "db",
    "mock-agent",
    "mock-llm",
    "mock-mcp-server",
    "redis",
    "web",
    "worker",
}
REDIS_MIGRATION_IMAGE = (
    "redis:7.4.11-alpine3.21@"
    "sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf"
)
LOCAL_DOCKER_HOSTS = frozenset(
    {
        "npipe:////./pipe/docker_engine",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
        "unix:///var/run/docker.sock",
    }
)
RQ_RETRY_MAX = 5
RQ_RETRY_INTERVALS = [1, 2, 5, 10, 30]
CALLBACK_RETRY_WINDOW_SECONDS = 25.0


class AcceptanceFailure(RuntimeError):
    """Raised when a resilience invariant is not observed."""


def _parse_compose_ps(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    raise AcceptanceFailure("Docker Compose returned an unexpected status document.")


def _as_uuid(value: str) -> str:
    return str(UUID(str(value)))


def _outer_rq_retry_observed(state: dict[str, Any]) -> bool:
    retries_left = state.get("retries_left")
    if (
        not isinstance(retries_left, int)
        or isinstance(retries_left, bool)
        or not 0 <= retries_left < RQ_RETRY_MAX
        or state.get("retry_intervals") != RQ_RETRY_INTERVALS
    ):
        return False
    return bool(
        (state.get("status") == "scheduled" and state.get("in_scheduled_registry") is True)
        or (state.get("status") == "queued" and state.get("in_queue") is True)
        or state.get("status") == "started"
    )


def _read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    return values


def _resolve_docker() -> str:
    discovered = shutil.which("docker")
    if discovered:
        return discovered
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = (
            Path(local_app_data) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
        )
        if candidate.is_file():
            return str(candidate)
    raise AcceptanceFailure("Docker CLI was not found.")


def _resolve_docker_path(value: str | None) -> str:
    candidate = Path(value) if value is not None else Path(_resolve_docker())
    if value is not None and not candidate.is_absolute():
        raise AcceptanceFailure("Explicit Docker CLI path must be absolute.")
    if not candidate.is_file():
        raise AcceptanceFailure("Docker CLI path is not a local file.")
    return str(candidate.resolve())


def _resolve_docker_config(value: str | None) -> Path | None:
    configured = value or os.environ.get("DOCKER_CONFIG", "").strip() or None
    if configured is None:
        return None
    candidate = Path(configured)
    if not candidate.is_absolute() or not candidate.is_dir():
        raise AcceptanceFailure("Docker config must be an existing absolute directory.")
    return candidate.resolve()


def _validate_docker_host(value: str) -> str:
    if value not in LOCAL_DOCKER_HOSTS:
        raise AcceptanceFailure("Only a known local Docker Engine endpoint is allowed.")
    return value


def _probe_docker_host(root: Path, docker: str, docker_config: Path | None) -> str:
    configured = os.environ.get("DOCKER_HOST", "").strip()
    if configured:
        return _validate_docker_host(configured)
    arguments = [docker]
    if docker_config is not None:
        arguments.extend(["--config", str(docker_config)])
    arguments.extend(
        [
            "context",
            "inspect",
            "--format",
            '{{(index .Endpoints "docker").Host}}',
        ]
    )
    completed = subprocess.run(  # noqa: S603 - executable was resolved to a local file
        arguments,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode != 0:
        raise AcceptanceFailure("Docker's active local endpoint could not be verified.")
    return _validate_docker_host(completed.stdout.strip())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_git_state(root: Path) -> dict[str, Any]:
    """Capture release provenance without exposing changed path names."""

    git = shutil.which("git")
    if git is None:
        return {"commit": None, "clean": False, "error": "git_not_found"}
    try:
        commit_result = subprocess.run(  # noqa: S603 - Git is resolved from the local PATH
            [git, "rev-parse", "--verify", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        status_result = subprocess.run(  # noqa: S603 - Git is resolved from the local PATH
            [git, "status", "--porcelain=v1", "--untracked-files=normal"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "clean": False, "error": "git_probe_failed"}
    commit = commit_result.stdout.strip().lower()
    if (
        commit_result.returncode != 0
        or status_result.returncode != 0
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        return {"commit": None, "clean": False, "error": "git_probe_invalid"}
    return {
        "commit": commit,
        "clean": not bool(status_result.stdout),
        "error": None,
    }


def _source_git_provenance(start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any]:
    commit = start.get("commit")
    unchanged = bool(commit and commit == end.get("commit"))
    clean = bool(start.get("clean") and end.get("clean") and unchanged)
    return {
        "source_git_commit": commit,
        "source_git_clean": clean,
        "source_git_unchanged_during_run": unchanged,
        "source_git_start": start,
        "source_git_end": end,
    }


def _compose_project_name(root: Path) -> str:
    canonical = str(root.resolve()).rstrip("\\/").lower()
    suffix = hashlib.sha256(canonical.encode("utf-8")).digest()[:6].hex()
    return f"{PROJECT_PREFIX}-{suffix}"


@dataclass
class Harness:
    root: Path
    docker: str
    docker_host: str
    docker_config: Path | None
    docker_controls_explicit: bool
    timeout: int
    api_port: int
    web_port: int
    worker_token: str
    username: str
    password: str
    auth_headers: dict[str, str] = field(default_factory=dict)
    paused_containers: set[str] = field(default_factory=set)

    @property
    def api_root(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def api_base(self) -> str:
        return f"{self.api_root}/api/v1"

    @property
    def project_name(self) -> str:
        return _compose_project_name(self.root)

    def log(self, message: str) -> None:
        print(f"[docker-resilience] {message}", flush=True)

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(  # noqa: S603 - executable and argv are locally controlled
            args,
            cwd=self.root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout or self.timeout,
            check=False,
        )
        if check and completed.returncode != 0:
            stderr = completed.stderr.strip()[-2000:]
            raise AcceptanceFailure(
                f"Command failed with exit code {completed.returncode}: {stderr}"
            )
        return completed

    def docker_run(
        self,
        *args: str,
        check: bool = True,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [self.docker]
        if self.docker_config is not None:
            command.extend(["--config", str(self.docker_config)])
        command.extend(["--host", self.docker_host, *args])
        return self.run(command, check=check, timeout=timeout)

    def compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.docker_run(
            "compose",
            "--project-name",
            self.project_name,
            "--file",
            str(self.root / "docker-compose.yml"),
            "--env-file",
            str(self.root / ".env"),
            *args,
            check=check,
        )

    def compose_status(self) -> list[dict[str, Any]]:
        result = self.compose("ps", "--all", "--format", "json")
        return _parse_compose_ps(result.stdout)

    def docker_toolchain_evidence(self) -> dict[str, Any]:
        """Prove which local CLI and Compose plugin produced this acceptance."""

        docker_path = Path(self.docker)
        docker_version = self.docker_run(
            "version", "--format", "{{.Client.Version}}"
        ).stdout.strip()
        if not docker_version:
            raise AcceptanceFailure("Docker CLI version evidence is empty.")

        plugins_raw = self.docker_run(
            "info", "--format", "{{json .ClientInfo.Plugins}}"
        ).stdout.strip()
        try:
            plugins = json.loads(plugins_raw)
            compose_plugin = next(
                item
                for item in plugins
                if isinstance(item, dict) and str(item.get("Name", "")).casefold() == "compose"
            )
            plugin_path = Path(str(compose_plugin["Path"]))
        except (KeyError, StopIteration, TypeError, json.JSONDecodeError) as exc:
            raise AcceptanceFailure("Docker did not expose Compose plugin provenance.") from exc
        if not plugin_path.is_absolute() or not plugin_path.is_file():
            raise AcceptanceFailure("Docker Compose plugin path is not an absolute local file.")
        plugin_path = plugin_path.resolve()

        configured_plugin_directories: list[str] = []
        docker_config_sha256: str | None = None
        if self.docker_config is not None:
            config_path = self.docker_config / "config.json"
            if not config_path.is_file():
                raise AcceptanceFailure("Explicit Docker config has no config.json.")
            docker_config_sha256 = _sha256_file(config_path)
            try:
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                extra_directories = config.get("cliPluginsExtraDirs") or []
                if not isinstance(extra_directories, list):
                    raise TypeError("cliPluginsExtraDirs must be a list")
                allowed_directories = [self.docker_config / "cli-plugins"] + [
                    Path(str(item)) for item in extra_directories
                ]
                resolved_directories = [
                    directory.resolve()
                    for directory in allowed_directories
                    if directory.is_absolute() and directory.is_dir()
                ]
            except (OSError, TypeError, json.JSONDecodeError) as exc:
                raise AcceptanceFailure("Explicit Docker plugin policy is invalid.") from exc
            configured_plugin_directories = [str(item) for item in resolved_directories]
            normalized_parent = os.path.normcase(str(plugin_path.parent))
            if normalized_parent not in {
                os.path.normcase(str(item)) for item in resolved_directories
            }:
                raise AcceptanceFailure(
                    "Loaded Compose plugin is outside the explicit Docker config policy."
                )

        compose_command_version = self.docker_run("compose", "version", "--short").stdout.strip()
        compose_reported_version = str(compose_plugin.get("Version", "")).strip()
        if not compose_command_version or not compose_reported_version:
            raise AcceptanceFailure("Docker Compose version evidence is incomplete.")
        return {
            "controls_explicit": self.docker_controls_explicit,
            "docker_cli_path": str(docker_path),
            "docker_cli_sha256": _sha256_file(docker_path),
            "docker_cli_version": docker_version,
            "docker_host": self.docker_host,
            "docker_config": str(self.docker_config) if self.docker_config is not None else None,
            "docker_config_sha256": docker_config_sha256,
            "configured_plugin_directories": configured_plugin_directories,
            "compose_plugin_path": str(plugin_path),
            "compose_plugin_sha256": _sha256_file(plugin_path),
            "compose_plugin_version": compose_reported_version,
            "compose_command_version": compose_command_version,
        }

    def _assert_owned(self, container_id: str) -> None:
        canonical = container_id.strip()
        if not canonical:
            raise AcceptanceFailure("A required Compose container is missing.")
        labels_text = self.docker_run(
            "inspect",
            "--format",
            "{{json .Config.Labels}}",
            canonical,
        ).stdout.strip()
        try:
            labels = json.loads(labels_text)
            project = str(labels.get("com.docker.compose.project", ""))
            working_directory_text = str(
                labels.get("com.docker.compose.project.working_dir", "")
            ).strip()
            if not working_directory_text:
                raise ValueError("missing Compose working directory label")
            working_directory_path = Path(working_directory_text)
            if not working_directory_path.is_absolute():
                raise ValueError("Compose working directory label is not absolute")
            working_directory = working_directory_path.resolve()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AcceptanceFailure("Container ownership labels are invalid.") from exc
        if project != self.project_name or working_directory != self.root.resolve():
            raise AcceptanceFailure("Refusing to manipulate a container outside this project.")

    def service_ids(self, service: str) -> list[str]:
        if service not in EXPECTED_SERVICES:
            raise AcceptanceFailure(f"Unexpected service requested: {service}")
        output = self.compose("ps", "-q", service).stdout
        ids = [line.strip() for line in output.splitlines() if line.strip()]
        for container_id in ids:
            self._assert_owned(container_id)
        return ids

    def pause(self, container_id: str) -> None:
        self._assert_owned(container_id)
        self.docker_run("pause", container_id)
        self.paused_containers.add(container_id)

    def unpause(self, container_id: str) -> None:
        self._assert_owned(container_id)
        result = self.docker_run("unpause", container_id, check=False)
        if result.returncode not in {0, 1}:
            raise AcceptanceFailure("Docker could not unpause a project container.")
        self.paused_containers.discard(container_id)

    def restart_container(self, container_id: str) -> None:
        self._assert_owned(container_id)
        self.docker_run("restart", container_id)

    def stop_containers(self, container_ids: list[str]) -> None:
        if not container_ids:
            return
        for container_id in container_ids:
            self._assert_owned(container_id)
        self.docker_run("stop", "--time", "5", *container_ids)

    def start_containers(self, container_ids: list[str]) -> None:
        if not container_ids:
            return
        for container_id in container_ids:
            self._assert_owned(container_id)
        self.docker_run("start", *container_ids)

    def wait_for(
        self,
        description: str,
        predicate: Callable[[], bool],
        *,
        timeout: int | None = None,
        interval: float = 1.0,
    ) -> None:
        deadline = time.monotonic() + (timeout or self.timeout)
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except Exception as exc:  # transient failures are expected here
                last_error = exc
            time.sleep(interval)
        detail = f" Last error: {type(last_error).__name__}." if last_error else ""
        raise AcceptanceFailure(f"Timed out waiting for {description}.{detail}")

    def http_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
        timeout: float = 20,
    ) -> tuple[int, dict[str, Any]]:
        request_headers = {"Accept": "application/json"}
        if authenticated:
            request_headers.update(self.auth_headers)
        if headers:
            request_headers.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(  # noqa: S310 - URL is fixed to loopback api_base
            f"{self.api_base}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - request is fixed to loopback
                request, timeout=timeout
            ) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw).get("detail", "HTTP request failed")
            except json.JSONDecodeError:
                detail = "HTTP request failed"
            raise AcceptanceFailure(f"API returned HTTP {exc.code}: {detail}") from exc

    def _url_ok(self, url: str, *, ready: bool = False) -> bool:
        if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise AcceptanceFailure("Health checks are restricted to loopback HTTP URLs.")
        try:
            with urllib.request.urlopen(  # noqa: S310 - URL is validated as loopback HTTP
                url, timeout=3
            ) as response:
                if not 200 <= response.status < 400:
                    return False
                if not ready:
                    return True
                payload = json.loads(response.read().decode("utf-8"))
                return payload.get("status") == "ok" and payload.get("database") == "ok"
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def wait_stack(self, worker_count: int) -> None:
        def healthy() -> bool:
            status = self.compose_status()
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in status:
                grouped.setdefault(str(item.get("Service", "")), []).append(item)
            if set(grouped) != EXPECTED_SERVICES:
                return False
            for service in EXPECTED_SERVICES:
                expected = worker_count if service == "worker" else 1
                entries = grouped.get(service, [])
                if len(entries) != expected:
                    return False
                if any(
                    str(item.get("State", "")).lower() != "running"
                    or str(item.get("Health", "")).lower() != "healthy"
                    for item in entries
                ):
                    return False
            return self._url_ok(f"{self.api_root}/ready", ready=True) and self._url_ok(
                f"http://127.0.0.1:{self.web_port}"
            )

        self.wait_for(f"all services and {worker_count} healthy worker(s)", healthy)

    def worker_info(self, container_id: str) -> dict[str, Any]:
        self._assert_owned(container_id)
        code = (
            "import json,os; from redis import Redis; from rq import Worker; "
            "from rq.serializers import JSONSerializer; "
            "from whaleguard_worker.healthcheck import current_worker_name; "
            "c=Redis.from_url(os.environ['REDIS_URL'],socket_connect_timeout=2,socket_timeout=2); "
            "n=current_worker_name(); "
            "w=Worker.find_by_key(f'{Worker.redis_worker_namespace_prefix}{n}',"
            "connection=c,serializer=JSONSerializer); "
            "print(json.dumps({'name':n,'state':w.get_state() if w else None,"
            "'current_job_id':w.get_current_job_id() if w else None,"
            "'successful':int(c.hget(w.key,'successful_job_count') or 0) if w else -1}))"
        )
        result = self.docker_run("exec", container_id, "python", "-c", code)
        info = json.loads(result.stdout.strip())
        if not info.get("name") or info.get("state") not in {"started", "idle", "busy"}:
            raise AcceptanceFailure("Worker registration is missing or stale.")
        return info

    def kill_worker_work_horse(self, container_id: str, expected_job_id: str) -> dict[str, Any]:
        """Terminate only the active RQ work horse, leaving PID 1 to retry it."""

        self._assert_owned(container_id)
        expected = _as_uuid(expected_job_id)
        current = self.worker_info(container_id)
        if (
            current.get("state") != "busy"
            or _as_uuid(str(current.get("current_job_id", ""))) != expected
        ):
            raise AcceptanceFailure("Worker is not busy with the expected crash probe.")
        code = (
            "import json,os,sys; from redis import Redis; "
            "from rq.command import send_kill_horse_command; "
            "c=Redis.from_url(os.environ['REDIS_URL'],socket_connect_timeout=2,socket_timeout=2); "
            "send_kill_horse_command(c,sys.argv[1]); "
            "print(json.dumps({'command':'kill-horse','worker_name':sys.argv[1]}))"
        )
        result = self.docker_run("exec", container_id, "python", "-c", code, str(current["name"]))
        try:
            evidence = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise AcceptanceFailure("Worker crash probe returned no valid evidence.") from exc
        if evidence != {"command": "kill-horse", "worker_name": current["name"]}:
            raise AcceptanceFailure("Worker crash probe did not target the expected work horse.")
        return evidence

    def rq_job_state(self, container_id: str, job_id: str) -> dict[str, Any]:
        """Read one allow-listed RQ job through the worker's trusted Redis settings."""

        self._assert_owned(container_id)
        canonical_job_id = _as_uuid(job_id)
        code = (
            "import json,os,sys; from redis import Redis; from rq import Queue; "
            "from rq.job import Job; from rq.serializers import JSONSerializer; "
            "c=Redis.from_url(os.environ['REDIS_URL'],socket_connect_timeout=2,socket_timeout=2); "
            "q=Queue(os.getenv('RQ_QUEUE','whaleguard'),connection=c,serializer=JSONSerializer); "
            "j=Job.fetch(sys.argv[1],connection=c,serializer=JSONSerializer); "
            "s=j.get_status(refresh=True); status=getattr(s,'value',str(s)); "
            "print(json.dumps({'job_id':j.id,'status':status,'retries_left':j.retries_left,"
            "'retry_intervals':j.retry_intervals,'in_queue':j.id in q.get_job_ids(),"
            "'in_scheduled_registry':j.id in "
            "q.scheduled_job_registry.get_job_ids(cleanup=False)},separators=(',',':')))"
        )
        result = self.docker_run(
            "exec",
            container_id,
            "python",
            "-c",
            code,
            canonical_job_id,
        )
        try:
            state = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise AcceptanceFailure("Could not read the RQ job state.") from exc
        if _as_uuid(str(state.get("job_id", ""))) != canonical_job_id:
            raise AcceptanceFailure("RQ returned state for an unexpected job.")
        return state

    def wait_for_outer_rq_retry(
        self,
        container_id: str,
        job_id: str,
        *,
        timeout: int,
    ) -> dict[str, Any]:
        """Observe RQ itself reschedule a job after callback retry exhaustion."""

        self._assert_owned(container_id)
        canonical_job_id = _as_uuid(job_id)
        code = (
            "import json,os,sys,time; from redis import Redis; from rq import Queue; "
            "from rq.job import Job; from rq.serializers import JSONSerializer; "
            "jid=sys.argv[1]; initial=int(sys.argv[2]); timeout=float(sys.argv[3]); "
            "c=Redis.from_url(os.environ['REDIS_URL'],socket_connect_timeout=2,socket_timeout=2); "
            "q=Queue(os.getenv('RQ_QUEUE','whaleguard'),connection=c,serializer=JSONSerializer); "
            "deadline=time.monotonic()+timeout; last={}; "
            'exec("while time.monotonic()<deadline:\\n'
            " j=Job.fetch(jid,connection=c,serializer=JSONSerializer)\\n"
            " s=j.get_status(refresh=True); status=getattr(s,'value',str(s))\\n"
            " queued=jid in q.get_job_ids()\\n"
            " scheduled=jid in q.scheduled_job_registry.get_job_ids(cleanup=False)\\n"
            " last={'job_id':jid,'status':status,'retries_left':j.retries_left,"
            "'retry_intervals':j.retry_intervals,'in_queue':queued,"
            "'in_scheduled_registry':scheduled}\\n"
            " if j.retries_left is not None and j.retries_left<initial and "
            "((status=='scheduled' and scheduled) or (status=='queued' and queued) "
            "or status=='started'):\\n"
            "  print(json.dumps(last,separators=(',',':'))); raise SystemExit(0)\\n"
            ' time.sleep(0.1)") ; '
            "print(json.dumps(last,separators=(',',':'))); raise SystemExit(3)"
        )
        result = self.docker_run(
            "exec",
            container_id,
            "python",
            "-c",
            code,
            canonical_job_id,
            str(RQ_RETRY_MAX),
            str(timeout),
            check=False,
            timeout=timeout + 15,
        )
        try:
            state = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise AcceptanceFailure("RQ outer-retry watcher returned no valid state.") from exc
        if result.returncode != 0 or not _outer_rq_retry_observed(state):
            raise AcceptanceFailure("RQ did not enter its configured outer retry path.")
        if _as_uuid(str(state.get("job_id", ""))) != canonical_job_id:
            raise AcceptanceFailure("RQ outer-retry watcher observed an unexpected job.")
        return state

    def wait_workers(self, expected: int = 3) -> dict[str, dict[str, Any]]:
        observed: dict[str, dict[str, Any]] = {}

        def ready() -> bool:
            nonlocal observed
            ids = self.service_ids("worker")
            if len(ids) != expected:
                return False
            current: dict[str, dict[str, Any]] = {}
            try:
                for container_id in ids:
                    current[container_id] = self.worker_info(container_id)
            except (AcceptanceFailure, subprocess.SubprocessError, json.JSONDecodeError):
                return False
            names = [str(item["name"]) for item in current.values()]
            if len(set(names)) != expected:
                return False
            observed = current
            return True

        self.wait_for(f"{expected} unique live RQ worker registrations", ready)
        return observed

    def sql_scalar(
        self,
        sql: str,
        *,
        run_id: str,
        delivery_id: str = "",
        status: str = "",
    ) -> int:
        command = (
            'printf "%s\\n" "$1" | psql -v ON_ERROR_STOP=1 '
            '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA '
            '-v run_id="$2" -v delivery_id="$3" -v status="$4"'
        )
        result = self.compose(
            "exec",
            "-T",
            "db",
            "sh",
            "-ec",
            command,
            "wg-query",
            sql,
            _as_uuid(run_id),
            _as_uuid(delivery_id) if delivery_id else "",
            status,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise AcceptanceFailure("Database verification returned no rows.")
        try:
            return int(lines[-1])
        except ValueError as exc:
            raise AcceptanceFailure("Database verification returned a non-integer.") from exc

    def sql_json(self, sql: str, *, run_id: str) -> dict[str, Any]:
        command = (
            'printf "%s\\n" "$1" | psql -v ON_ERROR_STOP=1 '
            '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -v run_id="$2"'
        )
        result = self.compose(
            "exec",
            "-T",
            "db",
            "sh",
            "-ec",
            command,
            "wg-query",
            sql,
            _as_uuid(run_id),
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        try:
            payload = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise AcceptanceFailure("Database verification returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise AcceptanceFailure("Database verification did not return an object.")
        return payload

    def receipt_count(self, run_id: str, delivery_id: str | None = None) -> int:
        return self.sql_scalar(
            "SELECT count(*) FROM delivery_receipts "
            "WHERE run_id = :'run_id'::uuid "
            "AND (NULLIF(:'delivery_id', '') IS NULL "
            "OR delivery_id = NULLIF(:'delivery_id', '')::uuid);",
            run_id=run_id,
            delivery_id=delivery_id or "",
        )

    def outbox_count(self, run_id: str, status: str) -> int:
        if status not in {"pending", "processed"}:
            raise AcceptanceFailure("Unexpected outbox status requested.")
        return self.sql_scalar(
            "SELECT count(*) FROM outbox_events "
            "WHERE aggregate_id = :'run_id'::uuid AND status = :'status';",
            run_id=run_id,
            status=status,
        )

    def event_count(self, run_id: str, delivery_id: str) -> int:
        return self.sql_scalar(
            "SELECT count(*) FROM run_events WHERE run_id = :'run_id'::uuid "
            "AND event_type = 'evaluation.completed' "
            "AND payload->'data'->>'delivery_id' = :'delivery_id';",
            run_id=run_id,
            delivery_id=delivery_id,
        )

    def run_integrity_evidence(self, run_id: str) -> dict[str, Any]:
        evidence = self.sql_json(
            """
            WITH run_row AS (
              SELECT status, progress, json_array_length(event_log) AS legacy_events
              FROM test_runs WHERE id = :'run_id'::uuid
            ), event_counts AS (
              SELECT count(*) AS events,
                     count(DISTINCT sequence) AS unique_sequences,
                     coalesce(min(sequence), 0) AS min_sequence,
                     coalesce(max(sequence), 0) AS max_sequence,
                     count(*) FILTER (WHERE event_type = 'run.queued') AS run_queued,
                     count(*) FILTER (WHERE event_type = 'run.started') AS run_started,
                     count(*) FILTER (WHERE event_type = 'run.waiting_approval') AS waiting,
                     count(*) FILTER (WHERE event_type = 'approval.approved') AS approved,
                     count(*) FILTER (WHERE event_type = 'run.completed') AS run_completed,
                     count(*) FILTER (
                       WHERE event_type IN ('run.failed', 'run.cancelled')
                     ) AS failed_terminal,
                     count(*) FILTER (WHERE event_type = 'case.started') AS case_started,
                     count(*) FILTER (WHERE event_type = 'case.completed') AS case_completed,
                     count(*) FILTER (WHERE event_type = 'evaluation.queued') AS eval_queued,
                     count(*) FILTER (WHERE event_type = 'evaluation.completed') AS eval_completed
              FROM run_events WHERE run_id = :'run_id'::uuid
            ), result_counts AS (
              SELECT count(*) AS results, count(DISTINCT test_case_id) AS unique_cases
              FROM test_results WHERE run_id = :'run_id'::uuid
            ), finding_counts AS (
              SELECT count(*) AS findings,
                     count(DISTINCT (title, category, affected_target)) AS unique_findings
              FROM findings WHERE run_id = :'run_id'::uuid
            ), evidence_counts AS (
              SELECT count(*) AS evidence,
                     count(DISTINCT sha256) AS unique_evidence_hashes,
                     count(*) FILTER (WHERE sha256 ~ '^[0-9a-f]{64}$') AS valid_hashes
              FROM evidence WHERE run_id = :'run_id'::uuid
            ), receipt_counts AS (
              SELECT count(*) AS receipts, count(DISTINCT delivery_id) AS unique_receipts
              FROM delivery_receipts WHERE run_id = :'run_id'::uuid
            ), outbox_counts AS (
              SELECT count(*) FILTER (WHERE status = 'processed') AS processed,
                     count(*) FILTER (WHERE status = 'pending') AS pending
              FROM outbox_events WHERE aggregate_id = :'run_id'::uuid
            )
            SELECT json_build_object(
              'run_status', r.status, 'progress', r.progress,
              'legacy_events', r.legacy_events,
              'events', ev.events, 'unique_sequences', ev.unique_sequences,
              'min_sequence', ev.min_sequence, 'max_sequence', ev.max_sequence,
              'run_queued', ev.run_queued, 'run_started', ev.run_started,
              'waiting_approval', ev.waiting, 'approval_approved', ev.approved,
              'run_completed', ev.run_completed, 'failed_terminal', ev.failed_terminal,
              'case_started', ev.case_started, 'case_completed', ev.case_completed,
              'evaluation_queued', ev.eval_queued,
              'evaluation_completed', ev.eval_completed,
              'test_results', tr.results, 'unique_test_cases', tr.unique_cases,
              'findings', f.findings, 'unique_findings', f.unique_findings,
              'evidence', e.evidence,
              'unique_evidence_hashes', e.unique_evidence_hashes,
              'valid_evidence_hashes', e.valid_hashes,
              'receipts', dr.receipts, 'unique_receipts', dr.unique_receipts,
              'outbox_processed', ob.processed, 'outbox_pending', ob.pending
            )
            FROM run_row r CROSS JOIN event_counts ev CROSS JOIN result_counts tr
            CROSS JOIN finding_counts f CROSS JOIN evidence_counts e
            CROSS JOIN receipt_counts dr CROSS JOIN outbox_counts ob;
            """,
            run_id=run_id,
        )
        expected_equalities = (
            (evidence["events"], evidence["unique_sequences"], "RunEvent sequence uniqueness"),
            (evidence["events"], evidence["max_sequence"], "RunEvent sequence continuity"),
            (evidence["events"], evidence["legacy_events"], "legacy event compatibility"),
            (evidence["test_results"], evidence["unique_test_cases"], "test-result identity"),
            (evidence["findings"], evidence["unique_findings"], "Finding identity"),
            (evidence["evidence"], evidence["unique_evidence_hashes"], "Evidence identity"),
            (evidence["evidence"], evidence["valid_evidence_hashes"], "Evidence hashes"),
            (evidence["receipts"], evidence["unique_receipts"], "delivery receipts"),
            (evidence["run_started"], evidence["approval_approved"] + 1, "run resumes"),
            (evidence["waiting_approval"], evidence["approval_approved"], "approvals"),
            (evidence["case_started"], evidence["test_results"], "case starts"),
            (evidence["case_completed"], evidence["test_results"], "case completions"),
            (evidence["evaluation_queued"], evidence["receipts"], "queued evaluations"),
            (evidence["evaluation_completed"], evidence["receipts"], "worker completions"),
        )
        for actual, expected, invariant in expected_equalities:
            if int(actual) != int(expected):
                raise AcceptanceFailure(f"Run integrity failed: {invariant}.")
        if (
            evidence["run_status"] != "completed"
            or int(evidence["progress"]) != 100
            or int(evidence["min_sequence"]) != 1
            or int(evidence["run_queued"]) != 1
            or int(evidence["run_completed"]) != 1
            or int(evidence["failed_terminal"]) != 0
            or int(evidence["test_results"]) != 15
            or int(evidence["findings"]) < 1
            or int(evidence["evidence"]) != 15
            or int(evidence["receipts"]) != 15
            or int(evidence["outbox_processed"]) != 15
            or int(evidence["outbox_pending"]) != 0
        ):
            raise AcceptanceFailure("Run integrity counts or terminal transitions are invalid.")
        return {"run_id": _as_uuid(run_id), **evidence}

    def login(self) -> None:
        status, payload = self.http_json(
            "POST",
            "/auth/login",
            {"username": self.username, "password": self.password},
            authenticated=False,
        )
        if status != 200 or not payload.get("access_token") or not payload.get("csrf_token"):
            raise AcceptanceFailure("Administrator login did not return both required tokens.")
        self.auth_headers = {
            "Authorization": f"Bearer {payload['access_token']}",
            "X-CSRF-Token": str(payload["csrf_token"]),
        }

    def demo_ids(self) -> tuple[str, str]:
        _, projects = self.http_json("GET", "/projects?page_size=100")
        project = next(
            (
                item
                for item in projects.get("items", [])
                if item.get("name") == "WhaleGuard Demo Lab"
            ),
            None,
        )
        if not project:
            raise AcceptanceFailure("Seeded demo project was not found.")
        project_id = _as_uuid(project["id"])
        _, suites = self.http_json("GET", f"/test-suites?project_id={project_id}&page_size=100")
        if not suites.get("items"):
            raise AcceptanceFailure("Seeded demo suite was not found.")
        return project_id, _as_uuid(suites["items"][0]["id"])

    def create_completed_run(self, project_id: str, suite_id: str, name: str) -> str:
        _, run = self.http_json(
            "POST",
            "/runs",
            {
                "project_id": project_id,
                "suite_id": suite_id,
                "target_type": "agent",
                "name": name,
                "max_concurrency": 3,
                "timeout_seconds": 30,
                "max_retries": 1,
            },
            timeout=60,
        )
        run_id = _as_uuid(run["id"])
        deadline = time.monotonic() + self.timeout
        approved_ids: set[str] = set()
        while time.monotonic() < deadline:
            _, current = self.http_json("GET", f"/runs/{run_id}")
            status = current.get("status")
            if status == "completed":
                _, results = self.http_json("GET", f"/runs/{run_id}/results?page_size=100")
                if int(results.get("total", 0)) != 15:
                    raise AcceptanceFailure("Completed resilience run does not have 15 results.")
                return run_id
            if status in {"failed", "cancelled"}:
                raise AcceptanceFailure(f"Resilience run ended in unexpected state: {status}")
            if status == "waiting_approval":
                _, approvals = self.http_json(
                    "GET",
                    f"/approvals?project_id={project_id}&status_filter=pending&page_size=100",
                )
                pending = next(
                    (
                        item
                        for item in approvals.get("items", [])
                        if str(item.get("run_id")) == run_id
                        and str(item.get("id")) not in approved_ids
                    ),
                    None,
                )
                if pending:
                    approval_id = _as_uuid(pending["id"])
                    self.http_json(
                        "POST",
                        f"/approvals/{approval_id}/decision",
                        {
                            "status": "approved",
                            "decision_reason": (
                                "Docker resilience acceptance; local safe simulation only."
                            ),
                        },
                        timeout=60,
                    )
                    approved_ids.add(approval_id)
            time.sleep(0.5)
        raise AcceptanceFailure("Timed out waiting for a resilience run to complete.")

    def worker_results_count(self, run_id: str) -> int:
        _, run = self.http_json("GET", f"/runs/{_as_uuid(run_id)}")
        explanation = run.get("score_explanation") or {}
        return len(explanation.get("worker_results") or [])

    def redis_canary(self, action: str) -> str:
        if action not in {"set", "get", "delete"}:
            raise AcceptanceFailure("Unexpected Redis canary action.")
        redis_id = self.service_ids("redis")[0]
        commands = {
            "set": (
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning '
                "SET wg:resilience:named-volume preserved >/dev/null && "
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning SAVE >/dev/null'
            ),
            "get": (
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning '
                "GET wg:resilience:named-volume"
            ),
            "delete": (
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning '
                "DEL wg:resilience:named-volume >/dev/null && "
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning SAVE >/dev/null'
            ),
        }
        return self.docker_run("exec", redis_id, "sh", "-ec", commands[action]).stdout.strip()

    def persistence_evidence(self, run_id: str) -> dict[str, Any]:
        _, run = self.http_json("GET", f"/runs/{_as_uuid(run_id)}")
        return {
            "run_id": _as_uuid(run_id),
            "run_status": str(run.get("status", "")),
            "progress": int(run.get("progress", 0)),
            "test_results": self.sql_scalar(
                "SELECT count(*) FROM test_results WHERE run_id = :'run_id'::uuid;",
                run_id=run_id,
            ),
            "outbox_processed": self.outbox_count(run_id, "processed"),
            "outbox_pending": self.outbox_count(run_id, "pending"),
            "receipts": self.receipt_count(run_id),
            "unique_delivery_ids": self.sql_scalar(
                "SELECT count(DISTINCT delivery_id) FROM delivery_receipts "
                "WHERE run_id = :'run_id'::uuid;",
                run_id=run_id,
            ),
            "valid_sha256_payload_hashes": self.sql_scalar(
                "SELECT count(*) FROM delivery_receipts "
                "WHERE run_id = :'run_id'::uuid "
                "AND payload_hash ~ '^[0-9a-f]{64}$';",
                run_id=run_id,
            ),
            "processed_receipts": self.sql_scalar(
                "SELECT count(*) FROM delivery_receipts "
                "WHERE run_id = :'run_id'::uuid AND processed_at IS NOT NULL;",
                run_id=run_id,
            ),
            "duplicate_receipt_groups": self.sql_scalar(
                "SELECT count(*) FROM (SELECT delivery_id FROM delivery_receipts "
                "WHERE run_id = :'run_id'::uuid GROUP BY delivery_id "
                "HAVING count(*) > 1) duplicate_groups;",
                run_id=run_id,
            ),
            "worker_results": self.worker_results_count(run_id),
        }

    def final_stack_evidence(self) -> dict[str, Any]:
        status = self.compose_status()
        images: dict[str, list[str]] = {}
        runtime_security: dict[str, list[dict[str, Any]]] = {}
        for service in sorted(EXPECTED_SERVICES):
            image_ids: list[str] = []
            security_entries: list[dict[str, Any]] = []
            for container_id in self.service_ids(service):
                raw_inspect = self.docker_run("inspect", container_id).stdout
                try:
                    inspection = json.loads(raw_inspect)[0]
                except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise AcceptanceFailure("Docker returned invalid container metadata.") from exc
                image_id = str(inspection.get("Image", ""))
                if image_id and image_id not in image_ids:
                    image_ids.append(image_id)
                proc_status = self.docker_run(
                    "exec",
                    container_id,
                    "sh",
                    "-ec",
                    'grep -E "^(Uid|Gid|CapEff|NoNewPrivs):" /proc/1/status',
                ).stdout
                status_fields = {
                    key: value.strip()
                    for line in proc_status.splitlines()
                    if ":" in line
                    for key, value in [line.split(":", 1)]
                }
                security_entry = {
                    "configured_user": str((inspection.get("Config") or {}).get("User", "")),
                    "pid1_uid": int(status_fields.get("Uid", "-1").split()[0]),
                    "pid1_gid": int(status_fields.get("Gid", "-1").split()[0]),
                    "cap_eff": status_fields.get("CapEff", ""),
                    "no_new_privileges": status_fields.get("NoNewPrivs") == "1",
                    "cap_add": list((inspection.get("HostConfig") or {}).get("CapAdd") or []),
                    "cap_drop": list((inspection.get("HostConfig") or {}).get("CapDrop") or []),
                    "security_opt": list(
                        (inspection.get("HostConfig") or {}).get("SecurityOpt") or []
                    ),
                    "privileged": bool((inspection.get("HostConfig") or {}).get("Privileged")),
                    "read_only_rootfs": bool(
                        (inspection.get("HostConfig") or {}).get("ReadonlyRootfs")
                    ),
                }
                if (
                    security_entry["privileged"]
                    or security_entry["pid1_uid"] == 0
                    or int(str(security_entry["cap_eff"]), 16) != 0
                    or not security_entry["no_new_privileges"]
                    or "ALL" not in security_entry["cap_drop"]
                ):
                    raise AcceptanceFailure(
                        f"Container runtime security invariant failed for service {service}."
                    )
                security_entries.append(security_entry)
            images[service] = image_ids
            runtime_security[service] = security_entries
        redis_id = self.service_ids("redis")[0]
        redis_inspection = json.loads(self.docker_run("inspect", redis_id).stdout)[0]
        redis_data_mount = next(
            (
                item
                for item in redis_inspection.get("Mounts", [])
                if item.get("Destination") == "/data"
            ),
            {},
        )
        expected_redis_volume = f"{self.project_name}_redis_data"
        if (
            redis_data_mount.get("Type") != "volume"
            or redis_data_mount.get("Name") != expected_redis_volume
            or redis_data_mount.get("Destination") != "/data"
            or not redis_data_mount.get("RW")
        ):
            raise AcceptanceFailure("Redis /data is not the expected writable project volume.")
        return {
            "service_entries": len(status),
            "running_entries": sum(
                str(item.get("State", "")).lower() == "running" for item in status
            ),
            "healthy_entries": sum(
                str(item.get("Health", "")).lower() == "healthy" for item in status
            ),
            "worker_entries": len(self.service_ids("worker")),
            "image_ids": images,
            "runtime_security": runtime_security,
            "redis_data_mount": {
                "type": redis_data_mount.get("Type"),
                "name": redis_data_mount.get("Name"),
                "destination": redis_data_mount.get("Destination"),
                "read_write": bool(redis_data_mount.get("RW")),
            },
        }

    def post_callback(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        delivery_id = _as_uuid(str(payload.get("delivery_id", "")))
        stable_payload = dict(payload)
        stable_payload["delivery_id"] = delivery_id
        _, response = self.http_json(
            "POST",
            f"/internal/runs/{_as_uuid(run_id)}/result",
            stable_payload,
            headers={"X-Worker-Token": self.worker_token},
            authenticated=False,
        )
        return response

    def queued_jobs(self, run_id: str) -> list[dict[str, str]]:
        cursor = 0
        records: list[dict[str, str]] = []
        seen_delivery_ids: set[str] = set()
        seen_job_ids: set[str] = set()
        while True:
            _, page = self.http_json(
                "GET",
                f"/runs/{_as_uuid(run_id)}/event-history?after_sequence={cursor}&page_size=200",
            )
            for item in page.get("items", []):
                if item.get("event_type") != "evaluation.queued":
                    continue
                data = (item.get("payload") or {}).get("data") or {}
                try:
                    delivery_id = _as_uuid(str(data["delivery_id"]))
                    job_id = _as_uuid(str(data["job_id"]))
                except (KeyError, TypeError, ValueError, AttributeError) as exc:
                    raise AcceptanceFailure(
                        "Canonical queue event has an invalid delivery_id/job_id pair."
                    ) from exc
                if delivery_id in seen_delivery_ids or job_id in seen_job_ids:
                    raise AcceptanceFailure("Canonical queue events contain duplicate identities.")
                seen_delivery_ids.add(delivery_id)
                seen_job_ids.add(job_id)
                records.append({"delivery_id": delivery_id, "job_id": job_id})
            if not page.get("has_more"):
                return records
            next_cursor = page.get("next_cursor")
            if not isinstance(next_cursor, int) or next_cursor <= cursor:
                raise AcceptanceFailure("Run-event pagination returned an invalid cursor.")
            cursor = next_cursor

    def queued_delivery_ids(self, run_id: str) -> list[str]:
        return [item["delivery_id"] for item in self.queued_jobs(run_id)]

    def issued_callback_payload(self, run_id: str, delivery_id: str) -> dict[str, Any]:
        code = (
            "import json,sys; from uuid import UUID; "
            "from whaleguard_api.database import SessionLocal; "
            "from whaleguard_api.models import OutboxEvent; "
            "from whaleguard_worker.evaluator import evaluate_rules; "
            "r=UUID(sys.argv[1]); d=UUID(sys.argv[2]); db=SessionLocal(); e=db.get(OutboxEvent,d); "
            "assert e and e.aggregate_id==r and e.status=='processed'; p=dict(e.payload or {}); "
            "x=evaluate_rules(dict(p['test_case']),str(p.get('output','')),"
            "trace=list(p.get('trace') or []),latency_ms=int(p.get('latency_ms') or 0),"
            "usage={'prompt_tokens':0,'completion_tokens':0,'estimated_cost':0.0}).as_dict(); "
            "x['delivery_id']=str(d); x['worker_elapsed_ms']=0.0; "
            "print(json.dumps(x,separators=(',',':'))); db.close()"
        )
        result = self.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            code,
            _as_uuid(run_id),
            _as_uuid(delivery_id),
        )
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise AcceptanceFailure("Could not derive an issued callback payload.") from exc
        if _as_uuid(str(payload.get("delivery_id", ""))) != _as_uuid(delivery_id):
            raise AcceptanceFailure("Issued callback payload changed the delivery ID.")
        return payload

    def reenqueue_issued_probe(self, run_id: str, delivery_id: str) -> str:
        code = (
            "import sys; from uuid import UUID; "
            "from whaleguard_api.database import SessionLocal; "
            "from whaleguard_api.models import OutboxEvent; "
            "from whaleguard_api.queueing import enqueue_rule_evaluation; "
            "r=UUID(sys.argv[1]); d=UUID(sys.argv[2]); db=SessionLocal(); e=db.get(OutboxEvent,d); "
            "assert e and e.aggregate_id==r and e.status=='processed'; p=dict(e.payload or {}); "
            "job=enqueue_rule_evaluation(r,d,dict(p['test_case']),str(p.get('output','')),"
            "list(p.get('trace') or []),int(p.get('latency_ms') or 0)); "
            "print(job or ''); db.close()"
        )
        result = self.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            code,
            _as_uuid(run_id),
            _as_uuid(delivery_id),
        )
        job_id = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        if not job_id:
            raise AcceptanceFailure("The API did not enqueue the targeted RQ probe.")
        return job_id

    def callback_failures_in_logs(self, container_ids: list[str], since: str) -> bool:
        markers = (
            "connecterror",
            "connection refused",
            "all connection attempts failed",
            "callback api host could not be safely resolved",
            "temporary failure in name resolution",
        )
        for container_id in container_ids:
            self._assert_owned(container_id)
            result = self.docker_run("logs", "--since", since, container_id, check=False)
            output = f"{result.stdout}\n{result.stderr}".casefold()
            if any(marker in output for marker in markers):
                return True
        return False

    def restore_standard_stack(self) -> None:
        for container_id in list(self.paused_containers):
            self.unpause(container_id)
        self.compose("start", "db", "redis", "api", check=False)
        self.compose("up", "-d", "--scale", "worker=1", check=True)
        self.wait_stack(1)
        status = self.compose_status()
        if len(status) != 8 or len(self.service_ids("worker")) != 1:
            raise AcceptanceFailure("Standard one-worker/eight-service topology was not restored.")


def _wait_run_delivery(harness: Harness, run_id: str, expected: int = 15) -> None:
    harness.wait_for(
        f"{expected} durable receipts for run {run_id}",
        lambda: (
            harness.receipt_count(run_id) == expected
            and harness.outbox_count(run_id, "processed") == expected
        ),
    )


def _verify_legacy_redis_volume_upgrade(harness: Harness) -> dict[str, Any]:
    """Prove a root-owned v0.1.0 AOF/RDB volume upgrades without manual repair."""

    token = secrets.token_hex(6)
    scope = f"{harness.project_name}-redis-upgrade-{token}"
    volume_name = f"{scope}_redis_data"
    legacy_name = f"{scope}-legacy"
    hardened_name = f"{scope}-hardened"
    test_label = "com.whaleguard.redis-upgrade-test"
    parent_label = "com.whaleguard.parent-compose-project"
    password = secrets.token_urlsafe(32)
    config_path = harness.root / "infra" / "docker" / "redis" / "redis.conf"

    def assert_test_container(container_id: str) -> dict[str, Any]:
        raw = harness.docker_run("inspect", container_id).stdout
        try:
            inspection = json.loads(raw)[0]
            labels = (inspection.get("Config") or {}).get("Labels") or {}
        except (IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AcceptanceFailure("Redis upgrade fixture metadata is invalid.") from exc
        if labels.get(test_label) != "true" or labels.get(parent_label) != harness.project_name:
            raise AcceptanceFailure("Refusing to manipulate an unowned Redis upgrade fixture.")
        return inspection

    def remove_test_container(name: str) -> None:
        result = harness.docker_run("ps", "-aq", "--filter", f"name=^/{name}$", check=False)
        container_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        for container_id in container_ids:
            assert_test_container(container_id)
            harness.docker_run("rm", "-f", container_id)

    def redis_exec(container_id: str, operation: str) -> subprocess.CompletedProcess[str]:
        commands = {
            "ping": ('REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning ping'),
            "write": (
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning '
                "SET wg:upgrade:canary preserved >/dev/null && "
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning SAVE >/dev/null'
            ),
            "read": (
                'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning GET wg:upgrade:canary'
            ),
        }
        return harness.docker_run(
            "exec", container_id, "sh", "-ec", commands[operation], check=False
        )

    def wait_redis(container_id: str) -> None:
        harness.wait_for(
            "an isolated Redis upgrade fixture",
            lambda: redis_exec(container_id, "ping").returncode == 0,
            timeout=60,
            interval=0.25,
        )

    labels = [
        "--label",
        f"{test_label}=true",
        "--label",
        f"{parent_label}={harness.project_name}",
    ]
    harness.docker_run(
        "volume",
        "create",
        *labels,
        "--label",
        "com.docker.compose.volume=redis_data",
        volume_name,
    )
    failure: Exception | None = None
    result: dict[str, Any] = {}
    try:
        legacy_id = harness.docker_run(
            "run",
            "-d",
            "--name",
            legacy_name,
            *labels,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "DAC_OVERRIDE",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "0:0",
            "--entrypoint",
            "sh",
            "-e",
            f"REDIS_PASSWORD={password}",
            "-v",
            f"{volume_name}:/data",
            REDIS_MIGRATION_IMAGE,
            "-ec",
            'exec redis-server --appendonly yes --requirepass "$REDIS_PASSWORD"',
        ).stdout.strip()
        assert_test_container(legacy_id)
        wait_redis(legacy_id)
        if redis_exec(legacy_id, "write").returncode != 0:
            raise AcceptanceFailure("Could not create the legacy Redis volume fixture.")
        legacy_uid = int(
            harness.docker_run(
                "exec", legacy_id, "sh", "-ec", "stat -c %u /data/dump.rdb"
            ).stdout.strip()
        )
        if legacy_uid != 0:
            raise AcceptanceFailure("Legacy Redis upgrade fixture was not root-owned.")
        remove_test_container(legacy_name)

        # This mirrors migrate_redis_volume.py: one isolated, short-lived root
        # helper has CHOWN plus read-only directory traversal, no network, and
        # no access outside this labeled fixture volume. The long-lived service
        # never runs as root.
        helper_cap_eff = harness.docker_run(
            "run",
            "--rm",
            *labels,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--cap-add",
            "DAC_READ_SEARCH",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "0:0",
            "--entrypoint",
            "sh",
            "-v",
            f"{volume_name}:/data",
            REDIS_MIGRATION_IMAGE,
            "-ec",
            'cap_eff="$(awk \'$1 == "CapEff:" { print $2 }\' /proc/1/status)"; '
            'nnp="$(awk \'$1 == "NoNewPrivs:" { print $2 }\' /proc/1/status)"; '
            '[ "$(id -u)" = 0 ] && [ "$cap_eff" = 0000000000000005 ] '
            '&& [ "$nnp" = 1 ] || exit 73; '
            "find /data -xdev -depth -user 0 -exec chown -h redis:redis {} +; "
            'printf "%s\\n" "$cap_eff"',
        ).stdout.strip()
        if helper_cap_eff != "0000000000000005":
            raise AcceptanceFailure("Redis migration helper capability proof is invalid.")

        hardened_id = harness.docker_run(
            "run",
            "-d",
            "--name",
            hardened_name,
            *labels,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "redis",
            "--entrypoint",
            "sh",
            "-e",
            f"REDIS_PASSWORD={password}",
            "-v",
            f"{volume_name}:/data",
            "-v",
            f"{config_path}:/usr/local/etc/redis/redis.conf:ro",
            "whaleguard-redis:7.4-alpine",
            "-ec",
            'exec redis-server /usr/local/etc/redis/redis.conf --requirepass "$REDIS_PASSWORD"',
        ).stdout.strip()
        hardened_inspection = assert_test_container(hardened_id)
        wait_redis(hardened_id)
        if redis_exec(hardened_id, "read").stdout.strip() != "preserved":
            raise AcceptanceFailure("Redis upgrade lost the legacy canary value.")
        migrated_uid = int(
            harness.docker_run(
                "exec", hardened_id, "sh", "-ec", "stat -c %u /data/dump.rdb"
            ).stdout.strip()
        )
        proc_status = harness.docker_run(
            "exec",
            hardened_id,
            "sh",
            "-ec",
            'grep -E "^(Uid|Gid|CapEff|NoNewPrivs):" /proc/1/status',
        ).stdout
        fields = {
            key: value.strip()
            for line in proc_status.splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        pid1_uid = int(fields.get("Uid", "-1").split()[0])
        cap_eff = fields.get("CapEff", "")
        no_new_privileges = fields.get("NoNewPrivs") == "1"
        host_config = hardened_inspection.get("HostConfig") or {}
        if (
            migrated_uid == 0
            or pid1_uid == 0
            or int(cap_eff, 16) != 0
            or not no_new_privileges
            or host_config.get("Privileged")
            or "ALL" not in (host_config.get("CapDrop") or [])
        ):
            raise AcceptanceFailure("Hardened Redis upgrade retained root privileges.")
        harness.docker_run("restart", hardened_id)
        wait_redis(hardened_id)
        if redis_exec(hardened_id, "read").stdout.strip() != "preserved":
            raise AcceptanceFailure("Redis canary did not survive the hardened restart.")
        result = {
            "legacy_root_owned_file_uid": legacy_uid,
            "migrated_file_uid": migrated_uid,
            "pid1_uid": pid1_uid,
            "cap_eff": cap_eff,
            "no_new_privileges": no_new_privileges,
            "cap_drop_all": "ALL" in (host_config.get("CapDrop") or []),
            "privileged": bool(host_config.get("Privileged")),
            "migration_helper_capabilities": ["CHOWN", "DAC_READ_SEARCH"],
            "migration_helper_cap_eff": helper_cap_eff,
            "long_lived_cap_add": list(host_config.get("CapAdd") or []),
            "canary_preserved_across_upgrade_and_restart": True,
            "dedicated_volume_and_fixture_labels_verified": True,
        }
    except Exception as exc:
        failure = exc
    finally:
        try:
            remove_test_container(legacy_name)
            remove_test_container(hardened_name)
            volume_raw = harness.docker_run("volume", "inspect", volume_name).stdout
            volume = json.loads(volume_raw)[0]
            volume_labels = volume.get("Labels") or {}
            if (
                volume.get("Name") != volume_name
                or volume_labels.get(test_label) != "true"
                or volume_labels.get(parent_label) != harness.project_name
            ):
                raise AcceptanceFailure("Refusing to remove an unowned Redis upgrade volume.")
            harness.docker_run("volume", "rm", volume_name)
        except Exception as cleanup_exc:
            failure = failure or cleanup_exc
    if failure is not None:
        raise failure
    return result


def run_acceptance(harness: Harness, *, build: bool) -> dict[str, Any]:
    harness.log("Starting private localhost-only Compose stack with three workers.")
    up_args = ["up", "-d"]
    if build:
        up_args.append("--build")
    up_args.extend(["--scale", "worker=3"])
    harness.compose(*up_args)
    harness.wait_stack(3)
    workers = harness.wait_workers(3)
    harness.log("PASS: three workers have unique, live RQ registrations.")

    legacy_upgrade = _verify_legacy_redis_volume_upgrade(harness)
    harness.log("PASS: a root-owned v0.1.0 Redis volume upgraded without manual repair.")

    harness.login()
    project_id, suite_id = harness.demo_ids()

    redis_id = harness.service_ids("redis")[0]
    harness.pause(redis_id)
    if not harness._url_ok(f"{harness.api_root}/ready", ready=True):
        raise AcceptanceFailure("API/database readiness should survive a Redis pause.")
    unhealthy_checks = 0
    for worker_id in workers:
        check = harness.docker_run(
            "exec", worker_id, "python", "-m", "whaleguard_worker.healthcheck", check=False
        )
        unhealthy_checks += int(check.returncode != 0)
    if unhealthy_checks != 3:
        raise AcceptanceFailure("All worker health checks should fail while Redis is paused.")
    harness.unpause(redis_id)
    workers = harness.wait_workers(3)
    harness.log("PASS: Redis pause was detected and all workers recovered after unpause.")

    harness.redis_canary("set")
    harness.compose("stop", "redis")
    disconnected_run = harness.create_completed_run(
        project_id,
        suite_id,
        f"Docker Redis recovery {int(time.time())}",
    )
    if harness.receipt_count(disconnected_run) != 0:
        raise AcceptanceFailure("A receipt appeared while Redis was unavailable.")
    if harness.outbox_count(disconnected_run, "pending") != 15:
        raise AcceptanceFailure("Redis outage did not retain all 15 outbox records as pending.")
    harness.compose("start", "redis")
    harness.wait_workers(3)
    _wait_run_delivery(harness, disconnected_run)
    if harness.redis_canary("get") != "preserved":
        raise AcceptanceFailure("Redis named-volume canary did not survive stop/start recovery.")
    harness.compose("up", "-d", "--force-recreate", "redis")
    harness.wait_stack(3)
    harness.wait_workers(3)
    if harness.redis_canary("get") != "preserved":
        raise AcceptanceFailure("Redis named-volume canary did not survive force-recreate.")
    harness.redis_canary("delete")
    harness.log("PASS: pending outbox records redelivered after Redis reconnect.")

    workers_before_queue = harness.wait_workers(3)
    worker_ids = sorted(workers_before_queue)
    harness.compose("stop", "worker")
    concurrent_started_at = time.monotonic()

    def create_concurrent_run(index: int) -> str:
        return harness.create_completed_run(
            project_id,
            suite_id,
            f"Docker concurrent run {index} {int(time.time())}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_runs = list(executor.map(create_concurrent_run, (1, 2)))
    concurrent_creation_seconds = time.monotonic() - concurrent_started_at
    if len(set(concurrent_runs)) != 2:
        raise AcceptanceFailure("Concurrent run creation did not return distinct identities.")
    api_downtime_run, concurrent_peer_run = concurrent_runs
    queued_jobs_by_run: dict[str, list[dict[str, str]]] = {}
    job_lookup: dict[str, dict[str, str]] = {}
    for run_id in concurrent_runs:
        if harness.outbox_count(run_id, "processed") != 15:
            raise AcceptanceFailure("A concurrent run did not durably enqueue all callback jobs.")
        if harness.receipt_count(run_id) != 0:
            raise AcceptanceFailure("Callbacks ran despite all worker containers being stopped.")
        run_jobs = harness.queued_jobs(run_id)
        if len(run_jobs) != 15:
            raise AcceptanceFailure("Run events did not expose all 15 issued RQ jobs.")
        queued_jobs_by_run[run_id] = run_jobs
        for record in run_jobs:
            if record["job_id"] in job_lookup:
                raise AcceptanceFailure("Concurrent runs reused an RQ job identity.")
            job_lookup[record["job_id"]] = {"run_id": run_id, **record}
    if len(job_lookup) != 30:
        raise AcceptanceFailure("Concurrent runs did not issue 30 distinct RQ jobs.")

    queued_jobs = queued_jobs_by_run[api_downtime_run]
    issued_ids = [item["delivery_id"] for item in queued_jobs]
    baseline_results = harness.worker_results_count(api_downtime_run)
    duplicate_id = issued_ids[-3]
    duplicate_payload = harness.issued_callback_payload(api_downtime_run, duplicate_id)
    with ThreadPoolExecutor(max_workers=20) as executor:
        responses = list(
            executor.map(
                lambda _index: harness.post_callback(api_downtime_run, duplicate_payload),
                range(20),
            )
        )
    duplicates = sum(bool(item.get("duplicate")) for item in responses)
    accepted_once = sum(not bool(item.get("duplicate")) for item in responses)
    if duplicates != 19 or accepted_once != 1:
        raise AcceptanceFailure("Concurrent issued callbacks were not deduplicated exactly once.")
    if (
        harness.receipt_count(api_downtime_run, duplicate_id) != 1
        or harness.event_count(api_downtime_run, duplicate_id) != 1
        or harness.worker_results_count(api_downtime_run) != baseline_results + 1
    ):
        raise AcceptanceFailure(
            "An issued duplicate callback changed durable business state more than once."
        )

    different_ids = issued_ids[-2:]
    different_responses = [
        harness.post_callback(
            api_downtime_run,
            harness.issued_callback_payload(api_downtime_run, delivery_id),
        )
        for delivery_id in different_ids
    ]
    if any(item.get("duplicate") for item in different_responses):
        raise AcceptanceFailure("A distinct issued delivery ID was treated as a duplicate.")
    if any(
        harness.receipt_count(api_downtime_run, delivery_id) != 1
        or harness.event_count(api_downtime_run, delivery_id) != 1
        for delivery_id in different_ids
    ):
        raise AcceptanceFailure("Distinct issued delivery IDs were not persisted independently.")
    if harness.worker_results_count(api_downtime_run) != baseline_results + 3:
        raise AcceptanceFailure("Distinct issued delivery IDs did not update business state.")
    harness.log("PASS: issued duplicate and distinct delivery IDs obeyed idempotency rules.")

    api_stopped_at = time.monotonic()
    harness.compose("stop", "api")
    for worker_id in worker_ids:
        harness._assert_owned(worker_id)
        harness.docker_run("start", worker_id)

    workers_after_restart = harness.wait_workers(3)
    if any(
        str(workers_after_restart[worker_id]["name"])
        == str(workers_before_queue[worker_id]["name"])
        for worker_id in worker_ids
    ):
        raise AcceptanceFailure("A restarted worker reused its previous boot registration.")
    if (
        harness.receipt_count(api_downtime_run) != 3
        or harness.receipt_count(concurrent_peer_run) != 0
    ):
        raise AcceptanceFailure("Concurrent callback state changed before worker restart checks.")

    busy_jobs: dict[str, str] = {}

    def three_busy_issued_jobs() -> bool:
        nonlocal busy_jobs
        current: dict[str, str] = {}
        for worker_id in worker_ids:
            info = harness.worker_info(worker_id)
            current_job_id = info.get("current_job_id")
            if info.get("state") != "busy" or not current_job_id:
                return False
            canonical_job_id = _as_uuid(str(current_job_id))
            if canonical_job_id not in job_lookup:
                raise AcceptanceFailure("Worker consumed a job outside the concurrent-run probe.")
            current[worker_id] = canonical_job_id
        if len(set(current.values())) != 3:
            raise AcceptanceFailure("Workers did not consume three distinct concurrent jobs.")
        busy_jobs = current
        return True

    harness.wait_for(
        "three workers to become busy with issued jobs while the API is unavailable",
        three_busy_issued_jobs,
        timeout=15,
        interval=0.1,
    )
    eligible_busy = [
        (worker_id, job_lookup[job_id])
        for worker_id, job_id in sorted(busy_jobs.items())
        if harness.receipt_count(job_lookup[job_id]["run_id"], job_lookup[job_id]["delivery_id"])
        == 0
    ]
    if len(eligible_busy) < 2:
        raise AcceptanceFailure("Could not isolate independent crash and callback retry probes.")
    (crash_worker_id, crash_probe), (outer_worker_id, outer_retry_probe) = eligible_busy[:2]
    crash_command = harness.kill_worker_work_horse(crash_worker_id, crash_probe["job_id"])
    crash_retry_state = harness.wait_for_outer_rq_retry(
        crash_worker_id,
        crash_probe["job_id"],
        timeout=max(20, min(harness.timeout - 10, 60)),
    )
    if harness.receipt_count(crash_probe["run_id"], crash_probe["delivery_id"]) != 0:
        raise AcceptanceFailure("Crashed worker probe changed state while the API was unavailable.")

    outer_retry_state = harness.wait_for_outer_rq_retry(
        outer_worker_id,
        outer_retry_probe["job_id"],
        timeout=max(40, min(harness.timeout - 10, 120)),
    )
    api_down_seconds_at_retry = time.monotonic() - api_stopped_at
    if api_down_seconds_at_retry < CALLBACK_RETRY_WINDOW_SECONDS:
        raise AcceptanceFailure("RQ retry occurred before the callback retry window elapsed.")
    if (
        harness.receipt_count(api_downtime_run) != 3
        or harness.receipt_count(concurrent_peer_run) != 0
    ):
        raise AcceptanceFailure("Callback state changed before the API was restored.")
    if harness.receipt_count(outer_retry_probe["run_id"], outer_retry_probe["delivery_id"]) != 0:
        raise AcceptanceFailure("Outer-retry probe was applied while the API was unavailable.")
    harness.compose("start", "api")
    harness.wait_stack(3)
    _wait_run_delivery(harness, api_downtime_run)
    _wait_run_delivery(harness, concurrent_peer_run)
    harness.wait_for(
        "the outer RQ retry probe to finish",
        lambda: (
            harness.rq_job_state(worker_ids[0], outer_retry_probe["job_id"]).get("status")
            == "finished"
        ),
    )
    outer_retry_final_state = harness.rq_job_state(worker_ids[0], outer_retry_probe["job_id"])
    harness.wait_for(
        "the crashed work-horse retry probe to finish",
        lambda: (
            harness.rq_job_state(worker_ids[0], crash_probe["job_id"]).get("status") == "finished"
        ),
    )
    crash_final_state = harness.rq_job_state(worker_ids[0], crash_probe["job_id"])
    if (
        harness.receipt_count(outer_retry_probe["run_id"], outer_retry_probe["delivery_id"]) != 1
        or harness.event_count(outer_retry_probe["run_id"], outer_retry_probe["delivery_id"]) != 1
    ):
        raise AcceptanceFailure("Outer RQ retry did not apply its delivery exactly once.")
    if (
        harness.receipt_count(crash_probe["run_id"], crash_probe["delivery_id"]) != 1
        or harness.event_count(crash_probe["run_id"], crash_probe["delivery_id"]) != 1
    ):
        raise AcceptanceFailure("Crashed work-horse retry did not apply exactly once.")
    concurrent_integrity = [harness.run_integrity_evidence(run_id) for run_id in concurrent_runs]
    concurrent_overlap = harness.sql_scalar(
        "SELECT CASE WHEN a.started_at <= b.finished_at "
        "AND b.started_at <= a.finished_at THEN 1 ELSE 0 END "
        "FROM test_runs a CROSS JOIN test_runs b "
        "WHERE a.id = :'run_id'::uuid AND b.id = :'status'::uuid;",
        run_id=api_downtime_run,
        status=concurrent_peer_run,
    )
    cross_run_delivery_ids = harness.sql_scalar(
        "SELECT count(DISTINCT delivery_id) FROM delivery_receipts "
        "WHERE run_id IN (:'run_id'::uuid, :'status'::uuid);",
        run_id=api_downtime_run,
        status=concurrent_peer_run,
    )
    if concurrent_overlap != 1 or cross_run_delivery_ids != 30:
        raise AcceptanceFailure("Concurrent runs did not overlap or preserve isolated deliveries.")
    harness.log(
        "PASS: concurrent runs, busy work-horse crash, and outer RQ retry recovered exactly once."
    )

    workers_after = harness.wait_workers(3)
    harness.log("PASS: all workers restarted before delivery with fresh unique registrations.")

    for worker_id, delivery_id in zip(sorted(workers_after), issued_ids[3:6], strict=True):
        baseline = int(harness.worker_info(worker_id)["successful"])
        others = [item for item in workers_after if item != worker_id]
        harness.stop_containers(others)
        try:
            harness.reenqueue_issued_probe(api_downtime_run, delivery_id)
            harness.wait_for(
                "a targeted worker to consume an issued duplicate",
                lambda worker_id=worker_id, baseline=baseline: (
                    int(harness.worker_info(worker_id)["successful"]) > baseline
                ),
            )
            current = int(harness.worker_info(worker_id)["successful"])
            if current <= baseline:
                raise AcceptanceFailure("The only active worker did not consume the probe.")
            if (
                harness.receipt_count(api_downtime_run, delivery_id) != 1
                or harness.event_count(api_downtime_run, delivery_id) != 1
            ):
                raise AcceptanceFailure("An issued duplicate changed durable callback state.")
        finally:
            harness.start_containers(others)
        harness.wait_workers(3)
    harness.log("PASS: each of the three workers consumed a real allow-listed RQ job.")

    stable_results_count = harness.worker_results_count(api_downtime_run)
    harness.compose("restart", "api")
    harness.wait_stack(3)
    harness.login()
    retry_response = harness.post_callback(api_downtime_run, duplicate_payload)
    if not retry_response.get("duplicate"):
        raise AcceptanceFailure("The delivery receipt was not durable across an API restart.")
    if (
        harness.receipt_count(api_downtime_run, duplicate_id) != 1
        or harness.worker_results_count(api_downtime_run) != stable_results_count
    ):
        raise AcceptanceFailure("Post-restart retry mutated exactly-once business state.")
    harness.log("PASS: 20-way duplicate delivery and post-restart retry remained exactly once.")

    return {
        "worker_scale": {
            "requested": 3,
            "unique_live_registrations": 3,
            "real_jobs_consumed_by_distinct_workers": 3,
        },
        "legacy_redis_volume_upgrade": legacy_upgrade,
        "redis_pause": {
            "worker_health_checks_failed_during_pause": unhealthy_checks,
            "workers_recovered": 3,
        },
        "redis_disconnect_run": harness.persistence_evidence(disconnected_run),
        "redis_named_volume_persistence": {
            "canary_survived_stop_start": True,
            "canary_survived_force_recreate": True,
            "canary_removed_after_verification": True,
        },
        "api_disconnect_run": harness.persistence_evidence(api_downtime_run),
        "concurrent_runs": {
            "creation_wall_seconds": round(concurrent_creation_seconds, 3),
            "execution_intervals_overlapped": bool(concurrent_overlap),
            "distinct_cross_run_delivery_ids": cross_run_delivery_ids,
            "integrity": concurrent_integrity,
        },
        "worker_crash_recovery": {
            "worker_container_id": crash_worker_id,
            "run_id": crash_probe["run_id"],
            "job_id": crash_probe["job_id"],
            "delivery_id": crash_probe["delivery_id"],
            "command": crash_command["command"],
            "observed_status": crash_retry_state["status"],
            "observed_retries_left": crash_retry_state["retries_left"],
            "final_status": crash_final_state["status"],
            "final_receipt_count": 1,
            "final_completion_event_count": 1,
        },
        "rq_outer_retry": {
            "run_id": outer_retry_probe["run_id"],
            "job_id": outer_retry_probe["job_id"],
            "delivery_id": outer_retry_probe["delivery_id"],
            "initial_retries": RQ_RETRY_MAX,
            "retry_intervals_seconds": RQ_RETRY_INTERVALS,
            "observed_status": outer_retry_state["status"],
            "observed_retries_left": outer_retry_state["retries_left"],
            "observed_in_queue": bool(outer_retry_state["in_queue"]),
            "observed_in_scheduled_registry": bool(outer_retry_state["in_scheduled_registry"]),
            "api_down_seconds_at_outer_retry": round(api_down_seconds_at_retry, 3),
            "receipt_count_while_api_unavailable": 0,
            "final_status": outer_retry_final_state["status"],
            "final_receipt_count": 1,
            "final_completion_event_count": 1,
        },
        "idempotency": {
            "same_issued_delivery_requests": 20,
            "same_issued_delivery_applied": accepted_once,
            "same_issued_delivery_duplicates": duplicates,
            "different_issued_delivery_ids_applied": len(different_ids),
            "post_api_restart_retry_duplicate": bool(retry_response.get("duplicate")),
        },
        "restarts": {
            "api_restart_verified": True,
            "worker_restart_fresh_registration_verified": True,
            "workers_restarted_before_delivery": 3,
        },
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _build_harness(
    root: Path,
    timeout: int,
    *,
    docker_path: str | None = None,
    docker_host: str | None = None,
    docker_config: str | None = None,
) -> Harness:
    env_path = root / ".env"
    credentials_path = root / ".local" / "first-run-credentials.txt"
    if not env_path.is_file():
        raise AcceptanceFailure(".env is missing; run the environment bootstrap first.")
    if not credentials_path.is_file():
        raise AcceptanceFailure("First-run credentials are missing; start the API once first.")
    env_values = _read_key_values(env_path)
    credentials = _read_key_values(credentials_path)
    worker_token = env_values.get("WG_WORKER_TOKEN", "")
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    if not worker_token or not username or not password:
        raise AcceptanceFailure("Required local credentials are incomplete.")
    resolved_docker = _resolve_docker_path(docker_path)
    resolved_config = _resolve_docker_config(docker_config)
    resolved_host = (
        _validate_docker_host(docker_host)
        if docker_host
        else _probe_docker_host(root, resolved_docker, resolved_config)
    )
    return Harness(
        root=root,
        docker=resolved_docker,
        docker_host=resolved_host,
        docker_config=resolved_config,
        docker_controls_explicit=all(
            value is not None for value in (docker_path, docker_host, docker_config)
        ),
        timeout=timeout,
        api_port=int(env_values.get("API_PORT", "8000")),
        web_port=int(env_values.get("WEB_PORT", "3000")),
        worker_token=worker_token,
        username=username,
        password=password,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify WhaleGuard Docker multi-worker and outage recovery invariants."
    )
    parser.add_argument("--skip-build", action="store_true", help="Reuse current images.")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--docker", help="Absolute path to the trusted Docker CLI")
    parser.add_argument("--docker-host", choices=sorted(LOCAL_DOCKER_HOSTS))
    parser.add_argument("--docker-config", help="Absolute managed Docker CLI config directory")
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Fail unless the same clean Git commit is present before and after acceptance.",
    )
    args = parser.parse_args(argv)
    if not 60 <= args.timeout <= 900:
        parser.error("--timeout must be between 60 and 900 seconds")
    explicit_controls = (args.docker, args.docker_host, args.docker_config)
    if any(value is not None for value in explicit_controls) and not all(
        value is not None for value in explicit_controls
    ):
        parser.error("--docker, --docker-host and --docker-config must be supplied together")
    if os.name == "nt" and not all(value is not None for value in explicit_controls):
        parser.error("Windows release evidence requires explicit local Docker controls")

    root = Path(__file__).resolve().parents[1]
    report_path = root / ".local" / "docker-resilience-report.json"
    source_git_start = _source_git_state(root)
    harness: Harness | None = None
    failure: Exception | None = None
    evidence: dict[str, Any] = {}
    restoration: dict[str, Any] = {}
    docker_toolchain: dict[str, Any] = {}
    try:
        if args.require_clean_git and not source_git_start["clean"]:
            raise AcceptanceFailure(
                "Release evidence requires a clean Git commit, including no untracked files."
            )
        harness = _build_harness(
            root,
            args.timeout,
            docker_path=args.docker,
            docker_host=args.docker_host,
            docker_config=args.docker_config,
        )
        docker_toolchain = harness.docker_toolchain_evidence()
        services = set(harness.compose("config", "--services").stdout.split())
        if services != EXPECTED_SERVICES:
            raise AcceptanceFailure("Compose service inventory does not match WhaleGuard.")
        migration = harness.run(
            [
                sys.executable,
                str(root / "scripts" / "migrate_redis_volume.py"),
                "--project-name",
                harness.project_name,
                "--docker",
                harness.docker,
                "--docker-host",
                harness.docker_host,
            ]
            + (
                ["--docker-config", str(harness.docker_config)]
                if harness.docker_config is not None
                else []
            )
        )
        if "REDIS_VOLUME_MIGRATION_OK" not in migration.stdout:
            raise AcceptanceFailure("Managed Redis volume migration did not report success.")
        if not args.skip_build:
            harness.log("Performing a clean no-cache rebuild of all final images.")
            harness.compose("build", "--no-cache")
        evidence = run_acceptance(harness, build=not args.skip_build)
        evidence["managed_redis_volume_migration"] = {
            "automatic": True,
            "completed": True,
        }
    except Exception as exc:
        failure = exc
        print(
            f"DOCKER_RESILIENCE_FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
    finally:
        if harness is not None:
            try:
                harness.log("Restoring the standard one-worker/eight-service topology.")
                harness.restore_standard_stack()
                restoration = harness.final_stack_evidence()
            except Exception as restore_exc:
                print(
                    "DOCKER_RESILIENCE_RESTORE_FAILED: "
                    f"{type(restore_exc).__name__}: {restore_exc}",
                    file=sys.stderr,
                    flush=True,
                )
                failure = failure or restore_exc

    source_git_end = _source_git_state(root)
    source_git = _source_git_provenance(source_git_start, source_git_end)
    if args.require_clean_git and not source_git["source_git_clean"] and failure is None:
        failure = AcceptanceFailure(
            "Git commit or working-tree state changed during release acceptance."
        )
        print(
            f"DOCKER_RESILIENCE_FAILED: {type(failure).__name__}: {failure}",
            file=sys.stderr,
            flush=True,
        )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if failure is None else "failed",
        "compose_project": harness.project_name if harness is not None else None,
        **source_git,
        "require_clean_git": args.require_clean_git,
        "docker_toolchain": docker_toolchain,
        "build_performed_this_invocation": not args.skip_build,
        "clean_no_cache_rebuild_performed": not args.skip_build,
        "safety_boundary": {
            "published_hosts": ["127.0.0.1"],
            "container_project_ownership_checked": True,
            "managed_project_data_volumes_removed": False,
            "ephemeral_labeled_upgrade_fixture_removed": bool(
                evidence.get("legacy_redis_volume_upgrade")
            ),
        },
        "evidence": evidence,
        "restoration": restoration,
        "failure_type": type(failure).__name__ if failure is not None else None,
    }
    _write_report(report_path, report)

    if failure is not None:
        print(f"DOCKER_RESILIENCE_REPORT={report_path}", file=sys.stderr, flush=True)
        return 1
    print(
        "DOCKER_RESILIENCE_OK workers=3 restored_workers=1 restored_services=8 "
        f"report={report_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
