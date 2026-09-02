#!/usr/bin/env python3
"""Self-test the public JD resume workflow validator."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_workflow.py"
GENERATED_FILES = ("resume_data.json", "claim_trace.json", "resume.html", "resume.pdf")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_validator(run: Path, stage: str):
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--run-dir", str(run), "--stage", stage],
        capture_output=True,
        text=True,
    )
    return proc, json.loads(proc.stdout)


def make_run(run: Path) -> None:
    run.mkdir()
    for name in (
        "jd_snapshot.md",
        "company_role_research.md",
        "requirement_matrix.json",
        "baseline_inventory.json",
        "evidence_match_matrix.json",
        "selection_plan.json",
    ):
        (run / name).write_text("{}\n" if name.endswith(".json") else "verified\n", encoding="utf-8")
    context = {
        "questions": [{"id": "Q1", "question": "Scope?", "reason": "R1 ownership", "requirement_ids": ["R1"]}],
        "responses": [{"question_id": "Q1", "status": "answered", "answer": "API design", "received_at": "2026-01-01T09:00:00+09:00"}],
    }
    (run / "user_context.json").write_text(json.dumps(context), encoding="utf-8")
    (run / "baseline_comparison.md").write_text(
        "# Key emphasis\nAPI design\n# Reason\nR1\n# Baseline changes\nbaseline → tailored\n# Preserved content\nAll history\n# Remaining uncertainty\nNone\n",
        encoding="utf-8",
    )
    (run / "content_review.md").write_text(
        "# Profile\nCandidate copy\n# Skills\nSkills copy\n# Career\nCareer copy\n# Projects\nProjects copy\n",
        encoding="utf-8",
    )


def approval_for(run: Path) -> dict:
    return {
        "approved": True,
        "reviewed_path": "content_review.md",
        "reviewed_sha256": digest(run / "content_review.md"),
        "approval_quote": "Generate the resume as reviewed.",
        "approved_at": "2026-01-01T09:05:00+09:00",
    }


def main() -> int:
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run"
        make_run(run)

        preflight, data = run_validator(run, "preflight")
        results.append({"test": "preflight_passes_without_generated_files", "pass": preflight.returncode == 0 and data["status"] == "PASS"})

        generation, data = run_validator(run, "generation")
        results.append({"test": "generation_requires_approval", "pass": generation.returncode != 0 and any(x["code"] == "CONTENT_APPROVAL_INVALID" for x in data["issues"])})

        approval = approval_for(run)
        (run / "content_approval.json").write_text(json.dumps(approval), encoding="utf-8")
        generation, data = run_validator(run, "generation")
        results.append({"test": "generation_passes_with_current_approval", "pass": generation.returncode == 0 and data["status"] == "PASS"})

        final, data = run_validator(run, "final")
        results.append({"test": "final_requires_generated_artifacts", "pass": final.returncode != 0 and any(x["code"] == "MISSING_GENERATED_ARTIFACT" for x in data["issues"])})

        for name in GENERATED_FILES:
            (run / name).write_text(f"synthetic {name}\n", encoding="utf-8")
        approval["resume_data_sha256"] = digest(run / "resume_data.json")
        approval["generated_artifact_hashes"] = {name: digest(run / name) for name in GENERATED_FILES}
        (run / "content_approval.json").write_text(json.dumps(approval), encoding="utf-8")
        final, data = run_validator(run, "final")
        results.append({"test": "final_accepts_current_generated_artifact_hashes", "pass": final.returncode == 0 and data["status"] == "PASS"})

        with (run / "resume.pdf").open("a", encoding="utf-8") as handle:
            handle.write("tampered\n")
        tampered, data = run_validator(run, "final")
        results.append({"test": "final_rejects_generated_artifact_hash_mismatch", "pass": tampered.returncode != 0 and any(x["code"] == "GENERATED_ARTIFACT_HASH_INVALID" for x in data["issues"])})

        (run / "resume.pdf").write_text("synthetic resume.pdf\n", encoding="utf-8")
        with (run / "content_review.md").open("a", encoding="utf-8") as handle:
            handle.write("changed\n")
        stale, data = run_validator(run, "final")
        results.append({"test": "stale_approval_is_rejected", "pass": stale.returncode != 0 and any(x["code"] == "CONTENT_APPROVAL_INVALID" for x in data["issues"])})

    status = "PASS" if all(item["pass"] for item in results) else "FAIL"
    print(json.dumps({"status": status, "tests": results}, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
