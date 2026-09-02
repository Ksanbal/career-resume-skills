#!/usr/bin/env python3
"""Compile validated semantic resume data with the immutable renderer."""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from pathlib import Path

import fitz
from playwright.sync_api import sync_playwright

from compiler_common import (
    chromium_revision, find_chromium, load_runtime_lock, sha256,
    synthetic_relabel_guard, write_json,
)
from renderer_components import build_html
from validate_resume_data import validate
from verify_design import verify


def fail(code: str, detail: str) -> int:
    print(json.dumps({"status": "FAIL", "issues": [{"code": code, "detail": detail}]}, ensure_ascii=False, indent=2))
    return 1


def approval_hash(path: Path, data_hash: str) -> str:
    approval = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(approval, dict):
        raise ValueError("approval must be a JSON object")
    if approval.get("approved") is not True:
        raise ValueError("approved must be true")
    reviewed_path = approval.get("reviewed_path")
    if reviewed_path != "content_review.md":
        raise ValueError("reviewed_path must be exactly the safe relative path content_review.md")
    approval_directory = path.parent.resolve()
    reviewed = approval_directory / reviewed_path
    try:
        reviewed.resolve().relative_to(approval_directory)
    except (OSError, ValueError) as exc:
        raise ValueError("reviewed_path escapes the approval directory") from exc
    if reviewed.is_symlink() or not reviewed.is_file():
        raise ValueError("reviewed_path must identify a regular content_review.md file")
    if reviewed.stat().st_size == 0:
        raise ValueError("content_review.md must be nonempty")
    if approval.get("reviewed_sha256") != sha256(reviewed):
        raise ValueError("reviewed_sha256 does not match current content_review.md")
    approved_hash = approval.get("resume_data_sha256") or approval.get("approved_resume_data_sha256")
    if approved_hash != data_hash:
        raise ValueError("approval does not match current resume data hash")
    if not approval.get("approval_quote") or not approval.get("approved_at"):
        raise ValueError("approval_quote and approved_at are required")
    return sha256(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--content-approval", "--approval", dest="approval", type=Path)
    parser.add_argument("--evaluation-fixture", action="store_true")
    parser.add_argument("--synthetic-source-digest")
    parser.add_argument("--chromium")
    parser.add_argument("--maintainer-unlock-chromium", action="store_true")
    args = parser.parse_args()

    skill = Path(__file__).resolve().parents[1]
    data_path = args.data.resolve()
    output = args.output_dir.resolve()
    design_issues = verify(skill)
    if design_issues:
        print(json.dumps({"status": "FAIL", "issues": design_issues}, ensure_ascii=False, indent=2))
        return 1
    data, schema_errors = validate(data_path, skill / "schemas" / "resume-content.schema.json")
    if schema_errors:
        return fail("SCHEMA_INVALID", json.dumps(schema_errors, ensure_ascii=False))

    try:
        runtime_lock = load_runtime_lock(skill)
        fixture_lock = json.loads((skill / "manifests" / "evaluation-fixtures.json").read_text(encoding="utf-8"))
        locked_fixture_hashes = set(fixture_lock["fixtures"].values())
        relabel_guards = set(fixture_lock["relabel_guard_sha256"].values())
    except Exception as exc:
        return fail("TRUST_MANIFEST_INVALID", str(exc))

    purpose = data["meta"]["document_purpose"]
    data_digest = sha256(data_path)
    relabel_guard = synthetic_relabel_guard(data)
    if args.evaluation_fixture:
        if purpose != "evaluation_fixture":
            return fail("EVALUATION_MODE_INVALID", "--evaluation-fixture requires document_purpose=evaluation_fixture")
        if data_digest not in locked_fixture_hashes and args.synthetic_source_digest not in locked_fixture_hashes:
            return fail(
                "SYNTHETIC_PROVENANCE_INVALID",
                "evaluation data must be the exact locked fixture or carry its locked --synthetic-source-digest",
            )
        approval_digest = None
    else:
        if args.maintainer_unlock_chromium:
            return fail("UNLOCKED_PRODUCTION_FORBIDDEN", "an unlocked Chromium can only create evaluation output")
        if data_digest in locked_fixture_hashes or relabel_guard in relabel_guards:
            return fail("SYNTHETIC_CONTENT_FORBIDDEN", "production compilation rejects locked synthetic fixture content, including relabelled copies")
        if purpose != "application":
            return fail("NON_PRODUCTION_CONTENT", "synthetic fixtures require --evaluation-fixture and cannot be production artifacts")
        if not args.approval:
            return fail("CONTENT_APPROVAL_INVALID", "production compilation requires --content-approval")
        try:
            approval_digest = approval_hash(args.approval.resolve(), sha256(data_path))
        except Exception as exc:
            return fail("CONTENT_APPROVAL_INVALID", str(exc))

    output.mkdir(parents=True, exist_ok=True)
    for name in ("resume.html", "resume.pdf", "render_manifest.json", "layout_audit.json"):
        target = output / name
        if target.exists():
            target.unlink()
    shutil.rmtree(output / "output_render", ignore_errors=True)

    css_path = skill / "assets" / "resume.css"
    font_path = skill / "assets" / "fonts" / "PretendardVariable.woff2"
    css = css_path.read_text(encoding="utf-8")
    encoded_font = base64.b64encode(font_path.read_bytes()).decode("ascii")
    marker = 'url("fonts/PretendardVariable.woff2")'
    if marker not in css:
        return fail("FONT_EMBED_FAILED", "locked stylesheet font URL marker is missing")
    css = css.replace(marker, f'url("data:font/woff2;base64,{encoded_font}")')
    html_path, pdf_path = output / "resume.html", output / "resume.pdf"
    html_path.write_text(build_html(data, css), encoding="utf-8")

    try:
        browser_path = Path(find_chromium(
            args.chromium,
            expected_revision=runtime_lock["chromium"]["revision"],
            allow_unlocked=args.maintainer_unlock_chromium and args.evaluation_fixture,
        ))
        revision = chromium_revision(browser_path)
        with sync_playwright() as driver:
            launched_browser = driver.chromium.launch(
                executable_path=str(browser_path),
                headless=True,
                args=[
                    "--disable-background-networking",
                    "--disable-extensions",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--no-first-run",
                ],
            )
            try:
                version = launched_browser.version
                context = launched_browser.new_context(offline=True)
                context.route("http://**/*", lambda route: route.abort())
                context.route("https://**/*", lambda route: route.abort())
                page = context.new_page()
                page.set_content(html_path.read_text(encoding="utf-8"), wait_until="load")
                font_status = page.evaluate(
                    "async () => { await document.fonts.ready; return document.fonts.status; }"
                )
                if font_status != "loaded":
                    raise RuntimeError(f"document fonts did not load: {font_status}")
                page.pdf(
                    path=str(pdf_path),
                    prefer_css_page_size=True,
                    print_background=True,
                )
                context.close()
            finally:
                launched_browser.close()
        if not pdf_path.is_file() or pdf_path.stat().st_size < 100:
            raise RuntimeError("Playwright Chromium did not produce a PDF")
        with fitz.open(pdf_path) as document:
            page_count = document.page_count
    except Exception as exc:
        pdf_path.unlink(missing_ok=True)
        code = "CHROMIUM_LOCK_MISMATCH" if "CHROMIUM_LOCK_MISMATCH" in str(exc) else "PDF_RENDER_FAILED"
        return fail(code, str(exc))

    design_manifest = skill / "manifests" / "design-manifest.json"
    locked = json.loads(design_manifest.read_text(encoding="utf-8"))
    manifest = {
        "manifest_version": "1.0.0",
        "status": ("EVALUATION_ONLY_UNLOCKED" if args.maintainer_unlock_chromium else "EVALUATION_ONLY") if args.evaluation_fixture else "PRODUCTION",
        "design_version": locked["design_version"],
        "design_manifest_sha256": sha256(design_manifest),
        "locked_design_files": locked["locked_files"],
        "inputs": {
            "resume_data_sha256": data_digest,
            "content_approval_sha256": approval_digest,
            "synthetic_source_sha256": (data_digest if data_digest in locked_fixture_hashes else args.synthetic_source_digest) if args.evaluation_fixture else None,
        },
        "renderer": {
            "engine": "Chromium",
            "browser_version": version,
            "browser_executable_path": str(browser_path),
            "browser_executable_sha256": sha256(browser_path),
            "browser_revision": revision,
            "locked_revision": runtime_lock["chromium"]["revision"],
            "maintainer_unlocked": bool(args.maintainer_unlock_chromium),
            "route": "playwright-sync-api-page-pdf",
        },
        "page_count": page_count,
        "artifacts": {
            "resume.html": sha256(html_path),
            "resume.pdf": sha256(pdf_path),
        },
    }
    write_json(output / "render_manifest.json", manifest)
    print(json.dumps({"status": "PASS", "output_dir": str(output), "page_count": page_count}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
