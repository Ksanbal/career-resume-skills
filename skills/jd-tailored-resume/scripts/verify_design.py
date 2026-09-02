#!/usr/bin/env python3
"""Verify every immutable renderer/design asset against the design manifest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from compiler_common import sha256


def verify(skill_dir: Path) -> list[dict[str, str]]:
    manifest_path = skill_dir / "manifests" / "design-manifest.json"
    issues: list[dict[str, str]] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        locked = manifest["locked_files"]
        if not isinstance(locked, dict) or not locked:
            raise ValueError("locked_files must be a non-empty object")
    except Exception as exc:
        return [{"code": "MANIFEST_INVALID", "detail": str(exc)}]
    root = skill_dir.resolve()
    for relative, expected in sorted(locked.items()):
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            issues.append({"code": "MANIFEST_INVALID", "detail": f"path escapes skill: {relative}"})
            continue
        if not candidate.is_file():
            issues.append({"code": "MISSING_DESIGN_FILE", "detail": relative})
        else:
            actual = sha256(candidate)
            if actual != expected:
                issues.append({"code": "HASH_MISMATCH", "detail": f"{relative}: expected={expected} actual={actual}"})
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    issues = verify(args.skill_dir.resolve())
    print(json.dumps({"status": "PASS" if not issues else "FAIL", "issues": issues}, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
