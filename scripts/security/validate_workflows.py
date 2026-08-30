from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
SHA_PIN = re.compile(r"(?m)^\s*uses:\s*[^\s#]+@([0-9a-f]{40})(?:\s*#.*)?$")
USES_LINE = re.compile(r"(?m)^\s*uses:\s*([^\s#]+)@([^\s#]+)(?:\s*#.*)?$")


def _validate_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return [f"{path.name}: workflow root must be a mapping"]
    if "pull_request_target" in text:
        errors.append(f"{path.name}: pull_request_target is forbidden")
    if "${{{{ secrets.".replace("{{{{", "{{") in text:
        errors.append(f"{path.name}: workflows must not reference repository secrets")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "docker compose " in line and "--project-name" not in line:
            errors.append(
                f"{path.name}:{line_number}: docker compose must use the canonical project name"
            )
    trivy_filesystem_scans = text.count("trivy fs")
    artifact_skips = text.count("--skip-dirs artifacts")
    if trivy_filesystem_scans != artifact_skips:
        errors.append(f"{path.name}: every Trivy filesystem scan must skip generated artifacts")
    if "package_release.py" in text and "generate_sbom.py" in text:
        if text.index("generate_sbom.py") > text.index("package_release.py"):
            errors.append(f"{path.name}: source SBOM must be generated before candidate artifacts")
        if "$RUNNER_TEMP/whaleguard-source-sbom" not in text:
            errors.append(f"{path.name}: clean source SBOM must be staged outside the checkout")

    permissions = data.get("permissions")
    if permissions != {"contents": "read"}:
        errors.append(f"{path.name}: top-level permissions must be exactly contents: read")

    jobs = data.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        errors.append(f"{path.name}: at least one job is required")
    else:
        for name, job in jobs.items():
            if not isinstance(job, dict) or "timeout-minutes" not in job:
                errors.append(f"{path.name}: job {name} has no timeout-minutes")
                continue
            for step in job.get("steps", []):
                if not isinstance(step, dict):
                    continue
                command = str(step.get("run", ""))
                if "generate_sbom.py" in command and "--skip-source" not in command:
                    if "$RUNNER_TEMP/whaleguard-source-sbom" not in command:
                        errors.append(
                            f"{path.name}: source SBOM must be written outside the source tree"
                        )

    for match in USES_LINE.finditer(text):
        target, revision = match.groups()
        if target.startswith("./"):
            continue
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            errors.append(f"{path.name}: action is not pinned to a full commit SHA: {target}")
    pinned_count = len(SHA_PIN.findall(text))
    if "uses:" in text and pinned_count == 0:
        errors.append(f"{path.name}: no immutable action pins were found")
    return errors


def main() -> None:
    workflows = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
    if not workflows:
        raise SystemExit("no GitHub Actions workflows were found")
    errors = [error for path in workflows for error in _validate_workflow(path)]
    if errors:
        raise SystemExit("workflow policy violations:\n- " + "\n- ".join(errors))
    print(f"validated {len(workflows)} workflows: SHA pins, timeouts, minimal permissions")


if __name__ == "__main__":
    main()
