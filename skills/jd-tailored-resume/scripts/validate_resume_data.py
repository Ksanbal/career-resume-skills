#!/usr/bin/env python3
"""Validate agent-authored resume content against the closed JSON contract."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def validate(data_path: Path, schema_path: Path) -> tuple[dict, list[dict[str, str]]]:
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [{"path": "$", "message": str(exc)}]
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.absolute_path)):
        location = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
        errors.append({"path": location, "message": error.message})
    return data, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas" / "resume-content.schema.json")
    args = parser.parse_args()
    _, errors = validate(args.data.resolve(), args.schema.resolve())
    status = "PASS" if not errors else "SCHEMA_INVALID"
    print(json.dumps({"status": status, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
