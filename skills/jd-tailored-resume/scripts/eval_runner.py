#!/usr/bin/env python3
"""Run and grade synthetic clean-agent and prompt-corpus evaluations."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SKILL_DIR = Path(__file__).resolve().parents[1]
REQUIRED_ARTIFACTS = (
    "jd_snapshot.md",
    "resume_data.json",
    "resume.html",
    "resume.pdf",
    "render_manifest.json",
    "layout_audit.json",
)
PRESENTATION_ARTIFACTS = (
    "resume.html",
    "resume.pdf",
    "render_manifest.json",
    "layout_audit.json",
    "output_render",
)
AGENT_SEMANTIC_ARTIFACTS = (
    "run/jd_snapshot.md",
    "run/resume_data.json",
)
LOCKED_FIXTURE_RELATIVE = "fixtures/evaluation/fictional_korean_resume.json"
CODEX_FLAGS = (
    "exec",
    "--json",
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--config",
    "sandbox_workspace_write.network_access=true",
    "--sandbox",
    "workspace-write",
    "--skip-git-repo-check",
)
CORPUS_CODEX_FLAGS = tuple(
    "sandbox_workspace_write.network_access=false"
    if flag == "sandbox_workspace_write.network_access=true" else flag
    for flag in CODEX_FLAGS
)
CASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def skill_snapshot(skill: Path) -> dict[str, str]:
    return {
        path.relative_to(skill).as_posix(): sha256(path)
        for path in sorted(skill.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def validate_public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("--jd-url must be a public HTTP(S) URL without credentials")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".invalid", ".test")):
        raise ValueError("--jd-url must identify a public JD, not a local or fictional host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("--jd-url must not use a private, loopback, or reserved IP address")
    return value


def build_prompt(jd_url: str) -> str:
    return "\n".join((
        "Use $jd-tailored-resume.",
        f"Public JD URL: {jd_url}",
        "Synthetic evaluation mode: write only the verified JD snapshot and exact locked semantic fixture; the trusted controller renders.",
        "Output path: run/",
    )) + "\n"


def build_corpus_prompt(case: dict[str, Any]) -> str:
    return "\n".join((
        "Use $jd-tailored-resume for a policy-control corpus evaluation only.",
        f"Public JD URL: {case['jd_url']}",
        f"Corpus case ID: {case['id']}",
        f"Corpus control category: {case['category']}",
        f"Case instruction: {case['prompt']}",
        "Create no files and perform no external action.",
        "Return only one JSON object with exactly the keys case_id and decision; do not add prose or Markdown.",
    )) + "\n"


def make_scratch(*, corpus_mode: bool = False) -> tuple[Path, Path, dict[str, str]]:
    scratch = Path(tempfile.mkdtemp(prefix="jd-resume-clean-agent-"))
    init = subprocess.run(["git", "init", "--quiet"], cwd=scratch, capture_output=True, text=True)
    if init.returncode != 0:
        raise RuntimeError(f"git init failed: {init.stderr.strip()}")
    scoped_skill = scratch / ".agents" / "skills" / SKILL_DIR.name
    scoped_skill.parent.mkdir(parents=True)
    shutil.copytree(SKILL_DIR, scoped_skill, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if corpus_mode:
        (scoped_skill / "fixtures" / "evaluation" / "eval_prompts.jsonl").unlink(missing_ok=True)
    return scratch, scoped_skill, skill_snapshot(scoped_skill)


def codex_command(codex_bin: str, prompt: str, *, corpus_mode: bool = False) -> list[str]:
    flags = CORPUS_CODEX_FLAGS if corpus_mode else CODEX_FLAGS
    return [codex_bin, *flags, prompt]


def run_codex(codex_bin: str, scratch: Path, prompt: str, *, corpus_mode: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        codex_command(codex_bin, prompt, corpus_mode=corpus_mode),
        cwd=scratch, capture_output=True, text=True,
    )


def unexpected_scratch_files(scratch: Path) -> list[str]:
    """List agent-created files outside installed skill and git metadata."""
    return sorted(
        path.relative_to(scratch).as_posix()
        for path in scratch.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.relative_to(scratch).parts[0] not in {".agents", ".git"}
    )


def presentation_scratch_artifacts(scratch: Path) -> list[str]:
    return sorted(
        path.relative_to(scratch).as_posix()
        for path in scratch.rglob("*")
        if path.relative_to(scratch).parts[0] not in {".agents", ".git"}
        and path.name in PRESENTATION_ARTIFACTS
    )


def parse_trace(raw: str) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: {exc.msg}")
            continue
        if not isinstance(event, dict):
            errors.append(f"line {line_number}: JSON value is not an object")
            continue
        events.append(event)
    if not events:
        errors.append("trace contains no JSON events")
    return events, errors


def agent_messages(events: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for event in events:
        if event.get("type") == "agent_message" and isinstance(event.get("text"), str):
            messages.append(event["text"])
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            messages.append(item["text"])
    return messages


def check(passed: bool, detail: str, **evidence: Any) -> dict[str, Any]:
    return {"pass": bool(passed), "detail": detail, **evidence}


def process_result(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        return {
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    except OSError as exc:
        return {"command": command, "returncode": None, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}


def skipped_result(command: list[str], reason: str) -> dict[str, Any]:
    return {"command": command, "returncode": None, "stdout": "", "stderr": f"skipped: {reason}"}


def remove_agent_presentation(run_dir: Path) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    errors: list[str] = []
    for name in PRESENTATION_ARTIFACTS:
        path = run_dir / name
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed.append(name)
            elif path.is_dir():
                shutil.rmtree(path)
                removed.append(name)
            elif path.exists():
                path.unlink()
                removed.append(name)
        except OSError as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    return removed, errors


def controller_materialization(
    scratch: Path,
    scoped_skill: Path,
    before: dict[str, str],
    source_before: dict[str, str],
) -> dict[str, Any]:
    """Validate agent semantics, then render with the trusted scoped compiler."""
    run_dir = scratch / "run"
    run_safe = run_dir.is_dir() and not run_dir.is_symlink()
    handoff_paths = unexpected_scratch_files(scratch)
    expected_handoff_paths = set(AGENT_SEMANTIC_ARTIFACTS)
    unexpected_paths = sorted(set(handoff_paths) - expected_handoff_paths)
    missing_paths = sorted(expected_handoff_paths - set(handoff_paths))
    non_regular_paths = sorted(
        relative for relative in AGENT_SEMANTIC_ARTIFACTS
        if not (scratch / relative).is_file() or (scratch / relative).is_symlink()
    )
    agent_semantic_only = not unexpected_paths and not missing_paths and not non_regular_paths
    removed, removal_errors = remove_agent_presentation(run_dir) if run_safe else ([], ["run/ is missing, not a directory, or a symlink"])

    installed_unchanged = skill_snapshot(scoped_skill) == before
    source_unchanged = skill_snapshot(SKILL_DIR) == source_before
    trusted_skill = installed_unchanged and source_unchanged

    fixture_path = scoped_skill / LOCKED_FIXTURE_RELATIVE
    expected_hash: str | None = None
    lock_error: str | None = None
    if trusted_skill:
        try:
            lock = json.loads((scoped_skill / "manifests" / "evaluation-fixtures.json").read_text(encoding="utf-8"))
            fixtures = lock["fixtures"]
            if set(fixtures) != {LOCKED_FIXTURE_RELATIVE}:
                raise ValueError("fixture manifest must lock exactly the installed evaluation fixture")
            candidate = fixtures[LOCKED_FIXTURE_RELATIVE]
            if not isinstance(candidate, str) or len(candidate) != 64 or any(char not in "0123456789abcdef" for char in candidate):
                raise ValueError("locked fixture SHA-256 is invalid")
            expected_hash = candidate
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            lock_error = f"{type(exc).__name__}: {exc}"
    else:
        lock_error = "installed or source skill changed after Codex execution"

    fixture_regular = fixture_path.is_file() and not fixture_path.is_symlink()
    fixture_actual = sha256(fixture_path) if fixture_regular else None
    fixture_source_ok = expected_hash is not None and fixture_actual == expected_hash

    jd_path = run_dir / "jd_snapshot.md"
    jd_ok = run_safe and jd_path.is_file() and not jd_path.is_symlink() and jd_path.stat().st_size > 0
    data_path = run_dir / "resume_data.json"
    data_regular = run_safe and data_path.is_file() and not data_path.is_symlink()
    data_actual = sha256(data_path) if data_regular else None
    fixture_exact = expected_hash is not None and data_actual == expected_hash

    schema_command = [
        sys.executable, str(scoped_skill / "scripts" / "validate_resume_data.py"),
        "--data", str(data_path),
    ]
    schema = process_result(schema_command, scratch) if trusted_skill and data_regular else skipped_result(schema_command,
        "trusted validator or regular resume_data.json unavailable"
    )

    prerequisites = (
        agent_semantic_only and run_safe and not removal_errors and trusted_skill and lock_error is None
        and fixture_source_ok and jd_ok and fixture_exact and schema["returncode"] == 0
    )
    compile_command = [
        sys.executable, str(scoped_skill / "scripts" / "compile_resume.py"),
        "--data", str(fixture_path),
        "--output-dir", str(run_dir),
        "--evaluation-fixture",
    ]
    compiled = process_result(compile_command, scratch) if prerequisites else skipped_result(compile_command,
        "semantic or trust prerequisite failed"
    )
    audit_command = [
        sys.executable, str(scoped_skill / "scripts" / "audit_resume.py"),
        "--output-dir", str(run_dir),
    ]
    audited = process_result(audit_command, scratch) if compiled["returncode"] == 0 else skipped_result(audit_command,
        "controller compilation failed or was skipped"
    )

    passed = prerequisites and compiled["returncode"] == 0 and audited["returncode"] == 0
    return check(
        passed,
        "trusted controller must enforce a semantic-only agent handoff before compiling and auditing",
        run_directory=check(run_safe, "run/ must be a real directory, not a symlink"),
        agent_semantic_only=check(
            agent_semantic_only,
            "agent handoff must contain exactly two regular files and no other files or symlinks",
            expected_paths=list(AGENT_SEMANTIC_ARTIFACTS),
            observed_paths=handoff_paths,
            unexpected_paths=unexpected_paths,
            missing_paths=missing_paths,
            non_regular_paths=non_regular_paths,
        ),
        presentation_reset=check(not removal_errors, "agent-authored presentation artifacts must be removed", removed=removed, errors=removal_errors),
        trusted_skill=check(trusted_skill, "installed and source skill must be unchanged before trusted execution", installed_unchanged=installed_unchanged, source_unchanged=source_unchanged),
        fixture_source=check(fixture_source_ok, "installed fixture must match its exact locked SHA-256", expected=expected_hash, actual=fixture_actual, manifest_error=lock_error),
        jd_snapshot=check(jd_ok, "agent must provide a nonempty regular run/jd_snapshot.md"),
        fixture_exact=check(fixture_exact, "agent resume_data.json must be byte-identical to the locked fixture", expected=expected_hash, actual=data_actual),
        schema_validation={"pass": schema["returncode"] == 0, "detail": "agent resume_data.json must pass the scoped schema", **schema},
        compile={"pass": compiled["returncode"] == 0, "detail": "trusted scoped compiler must materialize presentation artifacts", **compiled},
        audit={"pass": audited["returncode"] == 0, "detail": "trusted scoped auditor must pass", **audited},
    )


def independent_verification(run_dir: Path, scoped_skill: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[str]]:
    audit_path = run_dir / "layout_audit.json"
    try:
        audit_path.unlink()
    except FileNotFoundError:
        pass

    commands = {
        "schema_validation": [
            sys.executable, str(scoped_skill / "scripts" / "validate_resume_data.py"),
            "--data", str(run_dir / "resume_data.json"),
        ],
        "design_verification": [
            sys.executable, str(scoped_skill / "scripts" / "verify_design.py"),
            "--skill-dir", str(scoped_skill),
        ],
        "independent_audit": [
            sys.executable, str(scoped_skill / "scripts" / "audit_resume.py"),
            "--output-dir", str(run_dir),
        ],
    }
    results: dict[str, dict[str, Any]] = {}
    for name, command in commands.items():
        try:
            proc = subprocess.run(command, cwd=run_dir.parent, capture_output=True, text=True)
            results[name] = {
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
        except OSError as exc:
            results[name] = {"returncode": None, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}

    audit: dict[str, Any] = {}
    errors: list[str] = []
    if not audit_path.is_file() or audit_path.stat().st_size == 0:
        errors.append("layout_audit.json was not freshly generated by audit_resume.py")
    else:
        try:
            value = json.loads(audit_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("root must be an object")
            audit.update(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"layout_audit.json: {exc}")

    checks = {
        "schema_validation": check(
            results["schema_validation"]["returncode"] == 0,
            "scoped validate_resume_data.py must accept run/resume_data.json",
            **results["schema_validation"],
        ),
        "design_verification": check(
            results["design_verification"]["returncode"] == 0,
            "scoped verify_design.py must verify the installed skill",
            **results["design_verification"],
        ),
        "independent_audit": check(
            results["independent_audit"]["returncode"] == 0 and not errors and audit.get("status") == "PASS",
            "scoped audit_resume.py must structurally audit the PDF and freshly report PASS",
            report_status=audit.get("status"), report_errors=errors, **results["independent_audit"],
        ),
    }
    return checks, audit, errors


def grade_bundle(
    scratch: Path,
    scoped_skill: Path,
    before: dict[str, str],
    source_before: dict[str, str],
    proc: subprocess.CompletedProcess[str],
    materialization: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    events, trace_errors = parse_trace(proc.stdout)
    messages = agent_messages(events)
    run_dir = scratch / "run"
    paths = {name: run_dir / name for name in REQUIRED_ARTIFACTS}

    render: dict[str, Any] = {}
    json_errors: list[str] = []
    for name, target in (("render_manifest.json", render),):
        path = paths[name]
        if not path.is_file() or path.stat().st_size == 0:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("root must be an object")
            target.update(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            json_errors.append(f"{name}: {exc}")

    independent_checks, audit, audit_errors = independent_verification(run_dir, scoped_skill)
    json_errors.extend(audit_errors)
    missing = [name for name, path in paths.items() if not path.is_file()]
    empty = [name for name, path in paths.items() if path.is_file() and path.stat().st_size == 0]
    hashes = {name: sha256(path) for name, path in paths.items() if path.is_file()}

    expected_hashes = {
        "resume_data.json": render.get("inputs", {}).get("resume_data_sha256")
        if isinstance(render.get("inputs"), dict) else None,
        "resume.html": render.get("artifacts", {}).get("resume.html")
        if isinstance(render.get("artifacts"), dict) else None,
        "resume.pdf": render.get("artifacts", {}).get("resume.pdf")
        if isinstance(render.get("artifacts"), dict) else None,
    }
    mismatches = {
        name: {"expected": expected, "actual": hashes.get(name)}
        for name, expected in expected_hashes.items()
        if not isinstance(expected, str) or expected != hashes.get(name)
    }
    after = skill_snapshot(scoped_skill)
    source_after = skill_snapshot(SKILL_DIR)
    mutation = {
        "installed_added": sorted(set(after) - set(before)),
        "installed_removed": sorted(set(before) - set(after)),
        "installed_changed": sorted(name for name in set(before) & set(after) if before[name] != after[name]),
        "source_added": sorted(set(source_after) - set(source_before)),
        "source_removed": sorted(set(source_before) - set(source_after)),
        "source_changed": sorted(name for name in set(source_before) & set(source_after) if source_before[name] != source_after[name]),
    }
    unchanged = not any(mutation.values())
    checks = {
        "git_repository": check((scratch / ".git").is_dir(), "scratch was initialized with git init"),
        "codex_exit": check(proc.returncode == 0, f"Codex exit code {proc.returncode}"),
        "trace_valid": check(not trace_errors, "every non-empty trace line is a JSON object", errors=trace_errors, event_count=len(events)),
        "agent_message": check(bool(messages), "trace contains at least one agent message", count=len(messages)),
        "controller_materialization": materialization,
        "required_artifacts": check(not missing, "all six required run/ artifacts exist", missing=missing),
        "artifacts_nonempty": check(not missing and not empty, "all required artifacts are nonempty", empty=empty),
        "render_status": check(not json_errors and render.get("status") == "EVALUATION_ONLY", "render status must be EVALUATION_ONLY", actual=render.get("status"), json_errors=json_errors),
        "audit_status": check(not json_errors and audit.get("status") == "PASS", "layout audit status must be PASS", actual=audit.get("status"), json_errors=json_errors),
        "artifact_hashes": check(not missing and not mismatches, "render manifest hashes must match resume data, HTML, and PDF", mismatches=mismatches),
        "skill_unchanged": check(unchanged, "every source and installed skill file hash must remain unchanged", mutation=mutation),
        **independent_checks,
    }
    return checks, hashes


def copy_scratch_artifacts(scratch: Path, destination: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Copy inert scratch artifacts without following links or special files."""
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
    elif destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    scratch_root = scratch.resolve(strict=True)
    copied: list[str] = []
    skipped: list[dict[str, str]] = []

    def skip(source: Path, reason: str) -> None:
        skipped.append({"path": source.relative_to(scratch_root).as_posix(), "reason": reason})

    def copy_entry(source: Path, target: Path) -> None:
        relative = source.relative_to(scratch_root).as_posix()
        try:
            source_stat = source.lstat()
        except OSError as exc:
            skip(source, f"lstat failed: {type(exc).__name__}")
            return
        if stat.S_ISLNK(source_stat.st_mode):
            skip(source, "symlink")
            return
        try:
            resolved = source.resolve(strict=True)
        except OSError as exc:
            skip(source, f"resolve failed: {type(exc).__name__}")
            return
        if not resolved.is_relative_to(scratch_root):
            skip(source, "resolved path escapes scratch")
            return
        if stat.S_ISDIR(source_stat.st_mode):
            target.mkdir()
            try:
                children = sorted(source.iterdir(), key=lambda path: path.name)
            except OSError as exc:
                skip(source, f"directory read failed: {type(exc).__name__}")
                target.rmdir()
                return
            for child in children:
                copy_entry(child, target / child.name)
            return
        if not stat.S_ISREG(source_stat.st_mode):
            skip(source, "not a regular file or directory")
            return
        try:
            descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as source_handle, target.open("xb") as target_handle:
                if not stat.S_ISREG(os.fstat(source_handle.fileno()).st_mode):
                    raise OSError("source changed to a non-regular file")
                shutil.copyfileobj(source_handle, target_handle)
        except OSError as exc:
            target.unlink(missing_ok=True)
            skip(source, f"secure copy failed: {type(exc).__name__}")
            return
        copied.append(relative)

    for source in sorted(scratch_root.iterdir(), key=lambda path: path.name):
        if source.name not in {".agents", ".git"}:
            copy_entry(source, destination / source.name)
    return sorted(copied), sorted(skipped, key=lambda item: item["path"])


def write_manifest(output: Path, manifest: dict[str, Any]) -> None:
    (output / "evaluation_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


def run_bundle(args: argparse.Namespace, output: Path) -> int:
    jd_url = validate_public_url(args.jd_url)
    source_before = skill_snapshot(SKILL_DIR)
    scratch, scoped_skill, before = make_scratch()
    prompt = build_prompt(jd_url)
    prompt_path = output / "codex-prompt.txt"
    trace_path = output / "codex-trace.jsonl"
    stderr_path = output / "codex-stderr.txt"
    try:
        prompt_path.write_text(prompt, encoding="utf-8")
        proc = run_codex(args.codex_bin, scratch, prompt)
        trace_path.write_text(proc.stdout, encoding="utf-8")
        stderr_path.write_text(proc.stderr, encoding="utf-8")
        materialization = controller_materialization(scratch, scoped_skill, before, source_before)
        checks, hashes = grade_bundle(scratch, scoped_skill, before, source_before, proc, materialization)
        artifacts, skipped_artifacts = copy_scratch_artifacts(scratch, output / "scratch-artifacts")
        status = "PASS" if all(item["pass"] for item in checks.values()) else "FAIL"
        manifest = {
            "status": status,
            "mode": "synthetic_non_production",
            "jd_url": jd_url,
            "scratch_directory": str(scratch),
            "repository_scoped_skill": ".agents/skills/jd-tailored-resume",
            "codex_command": [args.codex_bin, *CODEX_FLAGS, "<prompt>"],
            "codex_returncode": proc.returncode,
            "trace": trace_path.name,
            "stderr": stderr_path.name,
            "checks": checks,
            "artifact_sha256": hashes,
            "skill_sha256_before": before,
            "skill_sha256_after": skill_snapshot(scoped_skill),
            "scratch_artifacts": artifacts,
            "scratch_artifacts_skipped": skipped_artifacts,
        }
        write_manifest(output, manifest)
        return 0 if status == "PASS" else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def load_corpus(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"corpus line {line_number}: {exc.msg}") from exc
        required = {"id", "category", "jd_url", "prompt", "expected_decision"}
        if not isinstance(case, dict) or not required.issubset(case):
            raise ValueError(f"corpus line {line_number}: required fields are {sorted(required)}")
        case_id = case["id"]
        if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id) or case_id in {".", ".."}:
            raise ValueError(
                f"corpus line {line_number}: invalid id {case_id!r}; expected a 1-64 character portable slug"
            )
        if case_id in seen:
            raise ValueError(f"corpus line {line_number}: duplicate id {case_id}")
        seen.add(case_id)
        validate_public_url(case["jd_url"])
        cases.append(case)
    if not 10 <= len(cases) <= 20:
        raise ValueError(f"corpus must contain 10-20 cases; found {len(cases)}")
    categories = {case["category"] for case in cases}
    required_categories = {"explicit", "implicit", "context", "negative"}
    if not required_categories.issubset(categories):
        raise ValueError(f"corpus must include categories {sorted(required_categories)}")
    return cases


def corpus_case_output(output: Path, case_id: str) -> Path:
    """Return a case output path only when it remains inside output/corpus."""
    output_root = output.resolve(strict=True)
    corpus_root = output_root / "corpus"
    if corpus_root.is_symlink():
        raise ValueError("corpus output directory must not be a symlink")
    corpus_root.mkdir(parents=True, exist_ok=True)
    resolved_corpus = corpus_root.resolve(strict=True)
    if not resolved_corpus.is_relative_to(output_root):
        raise ValueError("corpus output directory escapes output root")
    candidate = corpus_root / case_id
    if candidate.is_symlink():
        raise ValueError(f"corpus case output must not be a symlink: {case_id!r}")
    resolved_candidate = candidate.resolve(strict=False)
    if not resolved_candidate.is_relative_to(resolved_corpus):
        raise ValueError(f"corpus case output escapes corpus root: {case_id!r}")
    return candidate


def run_corpus(args: argparse.Namespace, output: Path) -> int:
    cases = load_corpus(args.corpus.resolve())
    results: list[dict[str, Any]] = []
    for case in cases:
        case_output = corpus_case_output(output, case["id"])
        case_output.mkdir(parents=True, exist_ok=True)
        source_before = skill_snapshot(SKILL_DIR)
        scratch, scoped_skill, before = make_scratch(corpus_mode=True)
        prompt = build_corpus_prompt(case)
        try:
            (case_output / "codex-prompt.txt").write_text(prompt, encoding="utf-8")
            proc = run_codex(args.codex_bin, scratch, prompt, corpus_mode=True)
            (case_output / "codex-trace.jsonl").write_text(proc.stdout, encoding="utf-8")
            (case_output / "codex-stderr.txt").write_text(proc.stderr, encoding="utf-8")
            events, trace_errors = parse_trace(proc.stdout)
            messages = agent_messages(events)
            response: dict[str, Any] | None = None
            response_error: str | None = None
            if messages:
                try:
                    candidate = json.loads(messages[-1])
                    if not isinstance(candidate, dict):
                        raise ValueError("agent response is not an object")
                    response = candidate
                except (json.JSONDecodeError, ValueError) as exc:
                    response_error = str(exc)
            after = skill_snapshot(scoped_skill)
            source_after = skill_snapshot(SKILL_DIR)
            installed_unchanged = before == after
            source_unchanged = source_before == source_after
            unchanged = installed_unchanged and source_unchanged
            unexpected_files = unexpected_scratch_files(scratch)
            presentation_artifacts = presentation_scratch_artifacts(scratch)
            response_shape_valid = response is not None and set(response) == {"case_id", "decision"}
            actual_case_id = response.get("case_id") if response else None
            actual_decision = response.get("decision") if response else None
            passed = (
                proc.returncode == 0
                and not trace_errors
                and len(messages) == 1
                and response_shape_valid
                and actual_case_id == case["id"]
                and actual_decision == case["expected_decision"]
                and unchanged
                and not unexpected_files
                and not presentation_artifacts
            )
            artifacts, skipped_artifacts = copy_scratch_artifacts(scratch, case_output / "scratch-artifacts")
            results.append({
                "id": case["id"],
                "category": case["category"],
                "expected_decision": case["expected_decision"],
                "actual_decision": actual_decision,
                "executed": True,
                "pass": passed,
                "codex_returncode": proc.returncode,
                "trace_errors": trace_errors,
                "response_error": response_error,
                "response_shape_valid": response_shape_valid,
                "agent_message_count": len(messages),
                "skill_unchanged": unchanged,
                "installed_skill_unchanged": installed_unchanged,
                "source_skill_unchanged": source_unchanged,
                "unexpected_files": unexpected_files,
                "presentation_artifacts": presentation_artifacts,
                "scratch_artifacts": artifacts,
                "scratch_artifacts_skipped": skipped_artifacts,
            })
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    passed_count = sum(item["pass"] for item in results)
    status = "PASS" if passed_count == len(results) else "FAIL"
    manifest = {
        "status": status,
        "mode": "policy_control_corpus",
        "codex_command": [args.codex_bin, *CORPUS_CODEX_FLAGS, "<prompt>"],
        "corpus": {
            "path": str(args.corpus.resolve()),
            "case_count": len(results),
            "passed": passed_count,
            "failed": len(results) - passed_count,
            "results": results,
        },
    }
    write_manifest(output, manifest)
    return 0 if status == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--jd-url")
    mode.add_argument("--corpus", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--codex-bin", default="codex")
    args = parser.parse_args()

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        return run_corpus(args, output) if args.corpus else run_bundle(args, output)
    except Exception as exc:
        manifest = {
            "status": "FAIL",
            "mode": "policy_control_corpus" if args.corpus else "synthetic_non_production",
            "error": f"{type(exc).__name__}: {exc}",
        }
        write_manifest(output, manifest)
        return 1


if __name__ == "__main__":
    sys.exit(main())
