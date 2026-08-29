from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    document = yaml.safe_load(
        (ROOT / "test-cases" / "builtin-safe.yaml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "packages" / "shared" / "schemas" / "test-case.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    cases = document.get("cases", [])
    errors = []
    for index, case in enumerate(cases):
        for error in validator.iter_errors(case):
            errors.append(f"case[{index}] {'.'.join(map(str, error.path))}: {error.message}")
    if len(cases) != 15:
        errors.append(f"expected 15 built-in cases, found {len(cases)}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"validated {len(cases)} safe built-in test cases")


if __name__ == "__main__":
    main()
