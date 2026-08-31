#!/usr/bin/env python3
"""Validate the question -> content approval -> generation gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

COMMON_FILES = (
    "jd_snapshot.md",
    "company_role_research.md",
    "requirement_matrix.json",
    "baseline_inventory.json",
    "evidence_match_matrix.json",
    "user_context.json",
    "selection_plan.json",
    "baseline_comparison.md",
    "content_review.md",
)
GENERATED_FILES = ("resume_data.json", "claim_trace.json", "resume.html", "resume.pdf")
COMPARISON_SECTIONS = (
    "Key emphasis",
    "Reason",
    "Baseline changes",
    "Preserved content",
    "Remaining uncertainty",
)
CONTENT_SECTIONS = ("Profile", "Skills", "Career", "Projects")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add(issues: list[dict], code: str, detail: str) -> None:
    issues.append({"code": code, "detail": detail})


def validate(run: Path, stage: str) -> list[dict]:
    issues: list[dict] = []
    for rel in COMMON_FILES:
        path = run / rel
        if not path.is_file() or path.stat().st_size == 0:
            add(issues, "MISSING_ARTIFACT", rel)

    try:
        context = load_json(run / "user_context.json")
        questions = context.get("questions", [])
        responses = context.get("responses", [])
        question_ids = [item["id"] for item in questions]
        response_ids = [item["question_id"] for item in responses]
        allowed = {"answered", "unknown", "declined"}
        if not question_ids:
            raise ValueError("at least one question is required")
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question IDs must be unique")
        if len(response_ids) != len(set(response_ids)) or set(question_ids) != set(response_ids):
            raise ValueError("every question requires exactly one response")
        if any(item.get("status") not in allowed for item in responses):
            raise ValueError("invalid response status")
        if any(not item.get("reason") or not item.get("requirement_ids") for item in questions):
            raise ValueError("each question needs a reason and requirement IDs")
    except Exception as exc:
        add(issues, "USER_CONTEXT_INVALID", str(exc))

    try:
        comparison = (run / "baseline_comparison.md").read_text(encoding="utf-8")
        missing = [name for name in COMPARISON_SECTIONS if name not in comparison]
        if missing or "→" not in comparison:
            raise ValueError(f"missing sections={missing}; baseline → tailored entry required")
    except Exception as exc:
        add(issues, "BASELINE_COMPARISON_INVALID", str(exc))

    try:
        content = (run / "content_review.md").read_text(encoding="utf-8")
        missing = [name for name in CONTENT_SECTIONS if name not in content]
        if missing:
            raise ValueError(f"missing sections={missing}")
    except Exception as exc:
        add(issues, "CONTENT_REVIEW_INVALID", str(exc))

    if stage == "preflight":
        present = [rel for rel in GENERATED_FILES if (run / rel).exists()]
        if present:
            add(issues, "GENERATED_BEFORE_APPROVAL", ", ".join(present))
    else:
        try:
            approval = load_json(run / "content_approval.json")
            reviewed_path = approval.get("reviewed_path")
            if approval.get("approved") is not True:
                raise ValueError("approved must be true")
            if reviewed_path != "content_review.md":
                raise ValueError("reviewed_path must be content_review.md")
            reviewed = run / reviewed_path
            if sha256(reviewed) != approval.get("reviewed_sha256"):
                raise ValueError("approval hash does not match current content")
            if not approval.get("approval_quote") or not approval.get("approved_at"):
                raise ValueError("approval quote and time are required")
        except Exception as exc:
            add(issues, "CONTENT_APPROVAL_INVALID", str(exc))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=("preflight", "generation"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    run = args.run_dir.resolve()
    issues = validate(run, args.stage)
    result = {"status": "PASS" if not issues else "FAIL", "stage": args.stage, "issues": issues}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
