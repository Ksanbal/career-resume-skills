#!/usr/bin/env python3
"""Audit provenance, DOM layout, PDF structure, and evaluation regressions."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, cast

import fitz
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright

from compiler_common import find_chromium, load_runtime_lock, sha256, write_json
from verify_design import verify

A4_WIDTH_POINTS = 595.276
A4_HEIGHT_POINTS = 841.890
A4_TOLERANCE_POINTS = 1.0
BOUNDS_TOLERANCE_POINTS = 1.0
MIN_BODY_PT = 10.5
MIN_LINE_HEIGHT_RATIO = 1.48


def add(issues: list[dict[str, str]], code: str, detail: Any) -> None:
    issues.append({"code": code, "detail": str(detail)})


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def hamming(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def perceptual_digest(image: Image.Image) -> str:
    sample = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(sample.getdata())
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return f"{bits:016x}"


def render_pages(pdf_path: Path, render_dir: Path) -> list[str]:
    shutil.rmtree(render_dir, ignore_errors=True)
    render_dir.mkdir(parents=True, exist_ok=True)
    images: list[Image.Image] = []
    digests: list[str] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            path = render_dir / f"page-{index + 1:03d}.png"
            pixmap.save(path)
            image = Image.open(path).convert("RGB")
            image.load()
            images.append(image)
            digests.append(perceptual_digest(image))
    if images:
        gap = 24
        width = max(image.width for image in images)
        height = sum(image.height for image in images) + gap * (len(images) - 1)
        sheet = Image.new("RGB", (width, height), "#d9dde3")
        y = 0
        for image in images:
            sheet.paste(image, ((width - image.width) // 2, y))
            y += image.height + gap
        sheet.save(render_dir / "contact-sheet.png", optimize=False)
    return digests


def pdf_metrics(pdf_path: Path) -> dict[str, Any]:
    blank_pages: list[int] = []
    overflow_count = 0
    searchable_text: list[str] = []
    a4 = True
    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            rect = page.rect
            if (abs(rect.width - A4_WIDTH_POINTS) > A4_TOLERANCE_POINTS or
                    abs(rect.height - A4_HEIGHT_POINTS) > A4_TOLERANCE_POINTS):
                a4 = False
            text = cast(str, page.get_text("text"))
            searchable_text.append(text)
            if not text.strip() and not page.get_drawings() and not page.get_images(full=True):
                blank_pages.append(page_index + 1)
            for block in page.get_text("blocks"):
                x0, y0, x1, y1 = block[:4]
                if (x0 < rect.x0 - BOUNDS_TOLERANCE_POINTS or
                        y0 < rect.y0 - BOUNDS_TOLERANCE_POINTS or
                        x1 > rect.x1 + BOUNDS_TOLERANCE_POINTS or
                        y1 > rect.y1 + BOUNDS_TOLERANCE_POINTS):
                    overflow_count += 1
    return {
        "page_count": page_count,
        "blank_pages": blank_pages,
        "overflow_count": overflow_count,
        "a4": a4,
        "searchable_korean": any("가" <= char <= "힣" for char in "\n".join(searchable_text)),
    }


def dom_metrics(html_text: str, browser_path: Path) -> dict[str, Any]:
    with sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=str(browser_path), headless=True,
            args=["--disable-background-networking", "--disable-extensions", "--disable-sync", "--no-first-run"],
        )
        try:
            context = browser.new_context(offline=True, viewport={"width": 794, "height": 1123})
            context.route("http://**/*", lambda route: route.abort())
            context.route("https://**/*", lambda route: route.abort())
            page = context.new_page()
            page.emulate_media(media="print")
            page.set_content(html_text, wait_until="load")
            page.evaluate("async () => { await document.fonts.ready; }")
            return page.evaluate("""() => {
                const round = value => Math.round(value * 100) / 100;
                const bodyStyle = getComputedStyle(document.body);
                const fontPx = parseFloat(bodyStyle.fontSize);
                const linePx = parseFloat(bodyStyle.lineHeight);
                const all = [...document.querySelectorAll('body *')].filter(el => {
                  const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                  return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                });
                const viewportWidth = document.documentElement.clientWidth;
                const horizontal = all.filter(el => {
                  const r = el.getBoundingClientRect();
                  return r.left < -0.75 || r.right > viewportWidth + 0.75 || el.scrollWidth > el.clientWidth + 1;
                }).map(el => ({tag: el.tagName, class: el.className, left: round(el.getBoundingClientRect().left), right: round(el.getBoundingClientRect().right)}));
                const selector = 'h1,h2,h3,h4,p,li,time,a,.target,.meta,.employment,.section-label,.section-kicker,.evaluation-banner,.stack-row strong,.stack-row span';
                const nodes = [...document.querySelectorAll(selector)].filter(el => {
                  const r = el.getBoundingClientRect(); return r.width > 1 && r.height > 1;
                });
                const overlaps = [];
                for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
                  const a = nodes[i], b = nodes[j];
                  if (a.contains(b) || b.contains(a)) continue;
                  const x = Math.min(a.getBoundingClientRect().right, b.getBoundingClientRect().right) - Math.max(a.getBoundingClientRect().left, b.getBoundingClientRect().left);
                  const y = Math.min(a.getBoundingClientRect().bottom, b.getBoundingClientRect().bottom) - Math.max(a.getBoundingClientRect().top, b.getBoundingClientRect().top);
                  if (x > 1 && y > 1) overlaps.push({a: a.tagName + '.' + a.className, b: b.tagName + '.' + b.className, area: round(x*y)});
                }
                const geometry = [...document.querySelectorAll('[data-section],.hero,.evaluation-banner,h1,.target,.contact,.project-card,.support-item')].map(el => {
                  const r = el.getBoundingClientRect();
                  return [el.tagName, el.getAttribute('data-section') || '', String(el.className), round(r.x), round(r.y), round(r.width), round(r.height)];
                });
                return {
                  body_font_pt: round(fontPx * 0.75), line_height_ratio: round(linePx / fontPx),
                  horizontal_overflow: horizontal, overlaps,
                  section_order: [...document.querySelectorAll('[data-section]')].map(el => el.getAttribute('data-section')),
                  active_content_count: document.querySelectorAll('script,iframe,object,embed,img').length,
                  geometry,
                  document: {width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight}
                };
            }""")
        finally:
            browser.close()


def collapsed_sections(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return result


def audit(output_dir: Path, *, write_golden: bool = False) -> tuple[dict[str, Any], list[dict[str, str]]]:
    output = output_dir.resolve()
    skill = Path(__file__).resolve().parents[1]
    issues: list[dict[str, str]] = []
    required = [output / "resume.html", output / "resume.pdf", output / "render_manifest.json"]
    for path in required:
        if not path.is_file():
            add(issues, "MISSING_ARTIFACT", path.name)
    if issues:
        return {}, issues
    try:
        manifest = json.loads((output / "render_manifest.json").read_text(encoding="utf-8"))
        runtime_lock = load_runtime_lock(skill)
    except Exception as exc:
        return {}, [{"code": "RENDER_MANIFEST_INVALID", "detail": str(exc)}]

    for name in ("resume.html", "resume.pdf"):
        expected, actual = manifest.get("artifacts", {}).get(name), sha256(output / name)
        if expected != actual:
            add(issues, "ARTIFACT_HASH_MISMATCH", f"{name}: expected={expected} actual={actual}")

    design_manifest = skill / "manifests" / "design-manifest.json"
    actual_design_hash = sha256(design_manifest) if design_manifest.is_file() else None
    if manifest.get("design_manifest_sha256") != actual_design_hash:
        add(issues, "DESIGN_MANIFEST_HASH_MISMATCH", f"expected={manifest.get('design_manifest_sha256')} actual={actual_design_hash}")
    issues.extend(verify(skill))

    locked_revision = runtime_lock["chromium"]["revision"]
    renderer = manifest.get("renderer", {})
    if renderer.get("browser_revision") != locked_revision or renderer.get("locked_revision") != locked_revision:
        add(issues, "CHROMIUM_LOCK_MISMATCH", f"required={locked_revision} renderer={renderer.get('browser_revision')}")
    if renderer.get("maintainer_unlocked") and manifest.get("status") == "PRODUCTION":
        add(issues, "UNLOCKED_PRODUCTION_FORBIDDEN", "production render used an unlocked browser")

    try:
        browser_path = Path(find_chromium(expected_revision=locked_revision))
        dom = dom_metrics((output / "resume.html").read_text(encoding="utf-8"), browser_path)
    except Exception as exc:
        add(issues, "DOM_AUDIT_FAILED", exc)
        dom = {"body_font_pt": 0, "line_height_ratio": 0, "horizontal_overflow": [], "overlaps": [], "section_order": [], "active_content_count": 0, "geometry": [], "document": {}}

    tokens = json.loads((skill / "assets" / "design_tokens.json").read_text(encoding="utf-8"))
    actual_sections = collapsed_sections(dom["section_order"])
    expected_sections = [name for name in tokens["required_section_order"] if name in actual_sections]
    section_order = actual_sections == expected_sections
    if not section_order:
        add(issues, "SECTION_ORDER_INVALID", actual_sections)
    typography_ok = dom["body_font_pt"] >= MIN_BODY_PT - 0.01 and dom["line_height_ratio"] >= MIN_LINE_HEIGHT_RATIO - 0.001
    if not typography_ok:
        add(issues, "TYPOGRAPHY_BELOW_FLOOR", f"body={dom['body_font_pt']}pt ratio={dom['line_height_ratio']}")
    if dom["horizontal_overflow"]:
        add(issues, "DOM_HORIZONTAL_OVERFLOW", dom["horizontal_overflow"][:10])
    if dom["overlaps"]:
        add(issues, "MEANINGFUL_ELEMENT_OVERLAP", dom["overlaps"][:10])
    if dom["active_content_count"]:
        add(issues, "ACTIVE_CONTENT_FORBIDDEN", dom["active_content_count"])

    metrics = pdf_metrics(output / "resume.pdf")
    if manifest.get("page_count") != metrics["page_count"]:
        add(issues, "PAGE_COUNT_MISMATCH", f"manifest={manifest.get('page_count')} pdf={metrics['page_count']}")
    if not metrics["a4"]:
        add(issues, "PAGE_SIZE_INVALID", "one or more PDF pages are not A4")
    if not metrics["searchable_korean"]:
        add(issues, "SEARCHABLE_KOREAN_MISSING", "no searchable Hangul found in PDF")
    if metrics["overflow_count"]:
        add(issues, "LAYOUT_OVERFLOW", metrics["overflow_count"])
    if metrics["blank_pages"]:
        add(issues, "BLANK_PAGES", metrics["blank_pages"])

    raster_digests = render_pages(output / "resume.pdf", output / "output_render")
    geometry_signature = canonical_hash(dom["geometry"])
    fixture_hash = manifest.get("inputs", {}).get("resume_data_sha256")
    source_hash = manifest.get("inputs", {}).get("synthetic_source_sha256")
    exact_evaluation = manifest.get("status") == "EVALUATION_ONLY" and fixture_hash == source_hash
    regression_ok = True
    golden_path = skill / "manifests" / "evaluation-layout-golden.json"
    if exact_evaluation:
        candidate = {
            "golden_version": "1.0.0", "rationale": "Geometry is exact under the locked browser/font; 64-bit dHash allows minor raster portability variance.",
            "fixture_sha256": fixture_hash, "chromium_revision": locked_revision,
            "page_count": metrics["page_count"], "geometry_sha256": geometry_signature,
            "page_perceptual_dhash": raster_digests, "max_hamming_distance": 4,
        }
        if write_golden:
            write_json(golden_path, candidate)
        try:
            golden = json.loads(golden_path.read_text(encoding="utf-8"))
            distances = [hamming(a, b) for a, b in zip(raster_digests, golden["page_perceptual_dhash"])]
            regression_ok = (
                golden["fixture_sha256"] == fixture_hash and golden["chromium_revision"] == locked_revision and
                golden["page_count"] == metrics["page_count"] and golden["geometry_sha256"] == geometry_signature and
                len(raster_digests) == len(golden["page_perceptual_dhash"]) and
                all(distance <= golden["max_hamming_distance"] for distance in distances)
            )
            if not regression_ok:
                add(issues, "EVALUATION_LAYOUT_REGRESSION", {"geometry": geometry_signature, "distances": distances})
        except Exception as exc:
            regression_ok = False
            add(issues, "EVALUATION_LAYOUT_GOLDEN_INVALID", exc)

    checks = {
        "a4": metrics["a4"],
        "artifact_hashes": not any(item["code"] == "ARTIFACT_HASH_MISMATCH" for item in issues),
        "design_integrity": not any(item["code"] in {"DESIGN_MANIFEST_HASH_MISMATCH", "HASH_MISMATCH", "MISSING_DESIGN_FILE", "MANIFEST_INVALID"} for item in issues),
        "evaluation_layout_regression": regression_ok,
        "minimum_typography": typography_ok,
        "no_active_content": dom["active_content_count"] == 0,
        "no_blank_pages": not metrics["blank_pages"],
        "no_dom_horizontal_overflow": not dom["horizontal_overflow"],
        "no_meaningful_overlap": not dom["overlaps"],
        "no_overflow": metrics["overflow_count"] == 0,
        "searchable_korean": metrics["searchable_korean"],
        "section_order": section_order,
    }
    report = {
        "audit_version": "2.0.0", "status": "PASS" if not issues else "FAIL", "checks": checks,
        "page_count": metrics["page_count"], "overflow_count": metrics["overflow_count"],
        "blank_pages": metrics["blank_pages"], "body_font_pt": dom["body_font_pt"],
        "line_height_ratio": dom["line_height_ratio"], "dom_horizontal_overflow": dom["horizontal_overflow"],
        "meaningful_overlaps": dom["overlaps"], "geometry_sha256": geometry_signature,
        "page_perceptual_dhash": raster_digests, "issues": issues,
    }
    return report, issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--write-evaluation-golden", action="store_true", help="maintainer-only: replace the locked evaluation baseline")
    args = parser.parse_args()
    report, issues = audit(args.output_dir, write_golden=args.write_evaluation_golden)
    if not report:
        report = {"audit_version": "2.0.0", "status": "FAIL", "checks": {}, "page_count": 0, "overflow_count": 0, "blank_pages": [], "issues": issues}
    write_json(args.output_dir.resolve() / "layout_audit.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
