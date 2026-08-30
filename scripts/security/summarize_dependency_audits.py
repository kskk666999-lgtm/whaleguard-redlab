from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"audit report is missing or invalid JSON: {path}: {exc}") from exc


def _pip_summary(path: Path) -> None:
    report = _load(path)
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        raise SystemExit("pip-audit report does not contain a dependencies list")
    vulnerable = [item for item in dependencies if item.get("vulns")]
    findings = sum(len(item.get("vulns", [])) for item in vulnerable)
    print(
        "pip-audit report: "
        f"dependencies={len(dependencies)} vulnerable_dependencies={len(vulnerable)} "
        f"findings={findings}"
    )


def _pip_exit_status(path: Path) -> int:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        status = int(raw)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"pip-audit exit status is missing or invalid: {path}") from exc
    if status not in {0, 1}:
        raise SystemExit(f"pip-audit failed operationally with exit status {status}")
    return status


def _npm_summary(path: Path) -> None:
    report = _load(path)
    if report.get("error"):
        raise SystemExit(f"npm audit returned an operational error: {report['error']}")
    counts = report.get("metadata", {}).get("vulnerabilities")
    if not isinstance(counts, dict):
        raise SystemExit("npm audit report does not contain vulnerability metadata")
    fields = ("info", "low", "moderate", "high", "critical", "total")
    rendered = " ".join(f"{field}={int(counts.get(field, 0))}" for field in fields)
    print(f"npm audit report: {rendered}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate dependency-audit reports without hiding reported vulnerabilities."
    )
    parser.add_argument("--pip-report", type=Path)
    parser.add_argument("--pip-exit-code", type=Path)
    parser.add_argument("--npm-report", type=Path)
    args = parser.parse_args()
    if not args.pip_report and not args.npm_report:
        raise SystemExit("at least one audit report is required")
    if args.pip_exit_code and not args.pip_report:
        raise SystemExit("--pip-exit-code requires --pip-report")
    if args.pip_report:
        _pip_summary(args.pip_report)
        if args.pip_exit_code:
            status = _pip_exit_status(args.pip_exit_code)
            if status == 1:
                print(
                    "pip-audit findings are retained; Python High/Critical gating is "
                    "performed by the Trivy filesystem vulnerability scan"
                )
    if args.npm_report:
        _npm_summary(args.npm_report)


if __name__ == "__main__":
    main()
