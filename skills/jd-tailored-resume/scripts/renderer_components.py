"""Pure resume HTML components: no filesystem, subprocess, or network I/O."""
from __future__ import annotations

import html
from typing import Any, Iterable


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def bullets(items: Iterable[dict[str, Any]]) -> str:
    rows = []
    for item in items:
        prefix = f"<strong>{esc(item.get('title'))}</strong> " if item.get("title") else ""
        rows.append(f"<li>{prefix}{esc(item.get('text'))}</li>")
    return "<ul>" + "".join(rows) + "</ul>" if rows else ""


def project(project_data: dict[str, Any]) -> str:
    meta = " · ".join(esc(x) for x in (project_data.get("organization"), project_data.get("role")) if x)
    return (
        '<article class="project-card">'
        '<div class="item-head"><div>'
        f"<h4>{esc(project_data['name'])}</h4><div class=\"meta\">{meta}</div>"
        f"</div><time>{esc(project_data['period'])}</time></div>"
        f"<p class=\"project-summary\">{esc(project_data['summary'])}</p>"
        f"{bullets(project_data['bullets'])}</article>"
    )


def support(item: dict[str, Any]) -> str:
    detail = f"<p>{esc(item['detail'])}</p>" if item.get("detail") else ""
    return (
        '<article class="support-item"><div>'
        f"<h3>{esc(item['name'])}</h3><div class=\"meta\">{esc(item['organization'])}</div>{detail}"
        f"</div><time>{esc(item['period'])}</time></article>"
    )


def section(label: str, body: str, extra_class: str = "") -> str:
    class_name = "section-grid" + (f" {extra_class}" if extra_class else "")
    return (
        f'<section class="{class_name}" data-section="{esc(label)}">'
        f'<div class="section-label">{esc(label)}</div><div class="section-body">{body}</div></section>'
    )


def build_html(data: dict[str, Any], css: str) -> str:
    """Return complete self-contained HTML from validated semantic content."""
    header = data["header"]
    contacts = []
    if header["email"]:
        contacts.append(f"<span>{esc(header['email'])}</span>")
    if header["phone"]:
        contacts.append(f"<span>{esc(header['phone'])}</span>")
    contacts.extend(f'<a href="{esc(url)}">{esc(url)}</a>' for url in header["links"])
    body = []
    if data["meta"]["document_purpose"] == "evaluation_fixture":
        body.append('<div class="evaluation-banner">평가 전용 허구 이력서 · 실제 지원 사용 금지 · EVALUATION ONLY</div>')
    body.append(
        '<header class="hero"><div>'
        f"<h1>{esc(header['name'])}</h1><div class=\"target\">{esc(header['title'])}</div>"
        f"</div><div class=\"contact\">{''.join(contacts)}</div></header>"
    )
    profile = "".join(f"<p>{esc(p)}</p>" for p in data["profile"]["paragraphs"])
    body.append(section("PROFILE", profile))
    stack = "".join(
        f'<div class="stack-row"><strong>{esc(group["category"])}</strong>'
        f'<span>{" · ".join(esc(item) for item in group["items"])}</span></div>'
        for group in data["skills"]
    )
    body.append(section("CORE STACK", f'<div class="stack-grid">{stack}</div>', "core-stack"))
    for index, career in enumerate(data["career"]):
        kicker = '<div class="section-kicker">CAREER</div>' if index == 0 else ""
        project_html = "".join(project(item) for item in career["projects"])
        role = f'<article class="role-card"><p>{esc(career["summary"])}</p>{bullets(career["role_bullets"])}</article>'
        body.append(
            '<section class="career-entry" data-section="CAREER">'
            f'<aside class="company-side">{kicker}<h3>{esc(career["company"])}</h3>'
            f'<div class="employment">{esc(career["employment"])}</div><time>{esc(career["period"])}</time></aside>'
            f'<div class="role-main">{role}<div class="career-projects">{project_html}</div></div></section>'
        )
    if data["side_projects"]:
        body.append(section("SIDE PROJECT", '<div class="side-projects">' + "".join(project(x) for x in data["side_projects"]) + "</div>"))
    if data["education"]:
        body.append(section("EDUCATION", "".join(support(x) for x in data["education"])))
    if data["certifications"]:
        body.append(section("CERTIFICATIONS", "".join(support(x) for x in data["certifications"])))
    if data["activities"]:
        body.append(section("AWARDS & ACTIVITIES", "".join(support(x) for x in data["activities"])))
    language = esc(data["meta"]["locale"][:2])
    title = esc(f"{header['name']} — {header['title']}")
    return (
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
        f"<style>{css}</style></head><body><main class=\"resume-doc\">{''.join(body)}</main></body></html>"
    )
