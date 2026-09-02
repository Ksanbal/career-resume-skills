from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def synthetic_relabel_guard(data: dict[str, Any]) -> str:
    """Hash content while making the mutable purpose label irrelevant."""
    normalized = json.loads(json.dumps(data, ensure_ascii=False))
    normalized["meta"]["document_purpose"] = "<purpose-ignored>"
    return canonical_json_hash(normalized)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def chromium_revision(executable: str | Path) -> str | None:
    """Extract Playwright's browser revision from its immutable cache path."""
    for part in Path(executable).resolve().parts:
        match = re.fullmatch(r"chromium(?:_headless_shell)?-(\d+)", part)
        if match:
            return match.group(1)
    return None


def load_runtime_lock(skill_dir: Path) -> dict[str, Any]:
    path = skill_dir / "manifests" / "runtime-lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    revision = lock.get("chromium", {}).get("revision")
    if not isinstance(revision, str) or not revision.isdigit():
        raise ValueError("runtime lock requires an exact numeric chromium.revision")
    return lock


def find_chromium(
    explicit: str | None = None,
    *,
    expected_revision: str,
    allow_unlocked: bool = False,
) -> str:
    """Return exact locked Playwright Chromium, or an explicitly unlocked binary."""
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"Chromium executable not found: {explicit}")
        actual = chromium_revision(candidate)
        if actual != expected_revision and not allow_unlocked:
            raise ValueError(
                f"CHROMIUM_LOCK_MISMATCH: required revision {expected_revision}, got {actual or 'unversioned'}"
            )
        return str(candidate)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as driver:
            candidate = Path(driver.chromium.executable_path).resolve()
            if not candidate.is_file():
                raise FileNotFoundError(str(candidate))
    except Exception as exc:
        raise FileNotFoundError(
            "Playwright's pinned Chromium is unavailable; run `playwright install chromium`"
        ) from exc
    actual = chromium_revision(candidate)
    if actual != expected_revision:
        raise ValueError(
            f"CHROMIUM_LOCK_MISMATCH: required revision {expected_revision}, got {actual or 'unversioned'}"
        )
    return str(candidate)
