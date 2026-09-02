from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "jd-tailored-resume"
SCRIPTS = SKILL / "scripts"
FIXTURE = SKILL / "fixtures" / "evaluation" / "fictional_korean_resume.json"
FIXTURE_MANIFEST = SKILL / "manifests" / "evaluation-fixtures.json"
CORPUS = SKILL / "fixtures" / "evaluation" / "eval_prompts.jsonl"
CORPUS_DECISIONS = {
    row["id"]: row["expected_decision"]
    for row in (json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip())
}


def run(*args: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(x) for x in args)], cwd=cwd or REPO,
        capture_output=True, text=True,
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluation_compile_args(data: Path) -> tuple[object, ...]:
    args: list[object] = ["--evaluation-fixture"]
    if data.resolve() != FIXTURE.resolve():
        locked = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
        args.extend(["--synthetic-source-digest", locked["fixtures"]["fixtures/evaluation/fictional_korean_resume.json"]])
    return tuple(args)


class ResumeCompilerTests(unittest.TestCase):
    def test_synthetic_protocol_and_runtime_contract_are_explicit(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        skill_contract = " ".join(skill_text.split())
        readme_text = (REPO / "README.md").read_text(encoding="utf-8")
        requirements = (REPO / "requirements.lock").read_text(encoding="utf-8").splitlines()
        runtime_lock = json.loads((SKILL / "manifests" / "runtime-lock.json").read_text(encoding="utf-8"))

        aside_help = "aside repl --help"
        aside_snapshot = (
            "aside repl \"const p = await openTab('<public-jd-url>'); "
            "const s = await snapshot(p); console.log(s.tree);\""
        )
        fallback = "Only after this Aside attempt may you try `curl` or web search"
        for required in (
            "Synthetic evaluation protocol (evaluation mode only)",
            "when `aside` exists", aside_help, aside_snapshot, fallback,
            "follow it and record that original source", "fail closed",
            "pre-authorized evaluation-only input", "Do not ask a real user question",
            "Do not request production content approval", "Do not alter or relabel the fixture",
            "The agent must create only `run/jd_snapshot.md` and `run/resume_data.json`",
            "regular, non-symlink files", "temporary files under `$TMPDIR`",
            "never in the scratch root or `run/`", "Any extra file or symlink fails the run before compilation",
            "cp .agents/skills/jd-tailored-resume/fixtures/evaluation/fictional_korean_resume.json run/resume_data.json",
            "Do not create or modify `resume.html`, `resume.pdf`, `render_manifest.json`, `layout_audit.json`, or `output_render/`",
            "trusted evaluation controller",
            "Production mode remains governed by the approval requirements above",
        ):
            self.assertIn(" ".join(required.split()), skill_contract)
        self.assertLess(skill_contract.index(aside_help), skill_contract.index(fallback))
        self.assertLess(skill_contract.index(aside_snapshot), skill_contract.index(fallback))

        self.assertIn("contains no real candidate resume", readme_text)
        self.assertNotIn("contains no resume,", readme_text)
        self.assertIn("Python 3.11", readme_text)
        self.assertNotIn("Python 3.9+", readme_text)
        self.assertEqual(runtime_lock["python"], "3.11")
        self.assertEqual(runtime_lock["packages"], {
            line.split("==", 1)[0]: line.split("==", 1)[1] for line in requirements
        })
        self.assertEqual(requirements, [
            "attrs==26.1.0",
            "greenlet==3.2.5",
            "jsonschema==4.23.0",
            "jsonschema-specifications==2025.9.1",
            "Pillow==11.3.0",
            "playwright==1.55.0",
            "pyee==13.0.1",
            "PyMuPDF==1.25.5",
            "referencing==0.36.2",
            "rpds-py==0.27.1",
            "typing_extensions==4.16.0",
        ])

        spec = importlib.util.spec_from_file_location("resume_eval_runner", SCRIPTS / "eval_runner.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        assert spec is not None and spec.loader is not None
        eval_runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(eval_runner)
        self.assertEqual(eval_runner.build_prompt("https://example.com/jobs/42").splitlines(), [
            "Use $jd-tailored-resume.",
            "Public JD URL: https://example.com/jobs/42",
            "Synthetic evaluation mode: write only the verified JD snapshot and exact locked semantic fixture; the trusted controller renders.",
            "Output path: run/",
        ])

    def test_design_manifest_verifies_and_tampering_fails(self) -> None:
        ok = run(SCRIPTS / "verify_design.py", "--skill-dir", SKILL)
        self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
        for relative in (
            "assets/resume.css", "assets/design_tokens.json", "scripts/renderer_components.py",
            "scripts/compile_resume.py", "scripts/compiler_common.py",
            "schemas/resume-content.schema.json", "manifests/runtime-lock.json",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                clone = Path(tmp) / "skill"
                shutil.copytree(SKILL, clone)
                with (clone / relative).open("a", encoding="utf-8") as handle:
                    handle.write("\n/* tampered */\n" if relative.endswith(".css") else "\n# tampered\n")
                bad = run(clone / "scripts/verify_design.py", "--skill-dir", clone)
                self.assertNotEqual(bad.returncode, 0)
                self.assertIn("HASH_MISMATCH", bad.stdout)

    def test_strict_schema_rejects_style_fields_at_every_level(self) -> None:
        base = json.loads(FIXTURE.read_text(encoding="utf-8"))
        mutations = [
            (base, "css"),
            (base["header"], "html"),
            (base["career"][0], "style"),
            (base["career"][0]["projects"][0], "page_break_before"),
            (base["career"][0]["projects"][0]["bullets"][0], "class"),
        ]
        for target, field in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                data = json.loads(json.dumps(base))
                # Find the corresponding object again in the copy.
                if target is base:
                    copied = data
                elif target is base["header"]:
                    copied = data["header"]
                elif target is base["career"][0]:
                    copied = data["career"][0]
                elif target is base["career"][0]["projects"][0]:
                    copied = data["career"][0]["projects"][0]
                else:
                    copied = data["career"][0]["projects"][0]["bullets"][0]
                copied[field] = "forbidden"
                path = Path(tmp) / "resume.json"
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                proc = run(SCRIPTS / "validate_resume_data.py", "--data", path)
                self.assertNotEqual(proc.returncode, 0, proc.stdout)
                self.assertIn("SCHEMA_INVALID", proc.stdout)

    def test_schema_rejects_active_markup_in_every_semantic_text_field(self) -> None:
        semantic_paths = (
            ("header", "name"), ("header", "title"), ("header", "email"), ("header", "phone"),
            ("profile", "paragraphs", 0),
            ("skills", 0, "category"), ("skills", 0, "items", 0),
            ("career", 0, "company"), ("career", 0, "employment"), ("career", 0, "period"),
            ("career", 0, "summary"), ("career", 0, "role_bullets", 0, "title"),
            ("career", 0, "role_bullets", 0, "text"),
            ("career", 0, "projects", 0, "name"), ("career", 0, "projects", 0, "organization"),
            ("career", 0, "projects", 0, "role"), ("career", 0, "projects", 0, "period"),
            ("career", 0, "projects", 0, "summary"),
            ("career", 0, "projects", 0, "bullets", 0, "title"),
            ("career", 0, "projects", 0, "bullets", 0, "text"),
            ("side_projects", 0, "name"), ("side_projects", 0, "organization"),
            ("side_projects", 0, "role"), ("side_projects", 0, "period"),
            ("side_projects", 0, "summary"), ("side_projects", 0, "bullets", 0, "text"),
            ("education", 0, "name"), ("education", 0, "organization"),
            ("education", 0, "period"), ("education", 0, "detail"),
            ("certifications", 0, "detail"), ("activities", 0, "detail"),
        )
        attack = "<style>body{display:none}</style><img src=https://evil.invalid/x>"
        for path_parts in semantic_paths:
            with self.subTest(path=path_parts), tempfile.TemporaryDirectory() as tmp:
                data = json.loads(FIXTURE.read_text(encoding="utf-8"))
                target = data
                for part in path_parts[:-1]:
                    target = target[part]
                target[path_parts[-1]] = attack
                path = Path(tmp) / "resume.json"
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                proc = run(SCRIPTS / "validate_resume_data.py", "--data", path)
                self.assertNotEqual(proc.returncode, 0, proc.stdout)
                self.assertIn("SCHEMA_INVALID", proc.stdout)

    def test_schema_rejects_active_text_payloads_but_allows_plain_html_css_words(self) -> None:
        payloads = (
            "<b>markup</b>", 'class="hidden"', "style = 'display:none'", "@import 'https://evil.invalid/x.css'",
            "background:url(https://evil.invalid/x)", "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>", "<iframe src=//evil.invalid></iframe>",
            "<object data=//evil.invalid/x></object>", "<embed src=//evil.invalid/x>", "<svg onload=alert(1)>",
        )
        for payload in payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                data = json.loads(FIXTURE.read_text(encoding="utf-8"))
                data["profile"]["paragraphs"][0] = payload
                path = Path(tmp) / "resume.json"
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                proc = run(SCRIPTS / "validate_resume_data.py", "--data", path)
                self.assertNotEqual(proc.returncode, 0, proc.stdout)

        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads(FIXTURE.read_text(encoding="utf-8"))
            data["profile"]["paragraphs"][0] = (
                "HTML/CSS 경험: 접근성, A/B 테스트와 99.9% 안정성을 개선했습니다 — (정상 문장)."
            )
            data["header"]["links"] = ["https://example.invalid/profile?class=backend&style=plain"]
            path = Path(tmp) / "resume.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            proc = run(SCRIPTS / "validate_resume_data.py", "--data", path)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)

    def test_compile_and_audit_fixture_and_detect_direct_html_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            compiled = run(SCRIPTS / "compile_resume.py", "--data", FIXTURE, "--output-dir", out,
                           "--evaluation-fixture")
            self.assertEqual(compiled.returncode, 0, compiled.stderr + compiled.stdout)
            for name in ("resume.html", "resume.pdf", "render_manifest.json"):
                self.assertTrue((out / name).is_file(), name)
                self.assertGreater((out / name).stat().st_size, 100)
            audited = run(SCRIPTS / "audit_resume.py", "--output-dir", out)
            self.assertEqual(audited.returncode, 0, audited.stderr + audited.stdout)
            report = json.loads((out / "layout_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["checks"]["a4"])
            self.assertTrue(report["checks"]["searchable_korean"])
            self.assertTrue(report["checks"]["section_order"])
            self.assertTrue(report["checks"]["minimum_typography"])
            self.assertTrue(report["checks"]["no_dom_horizontal_overflow"])
            self.assertTrue(report["checks"]["no_meaningful_overlap"])
            self.assertTrue(report["checks"]["evaluation_layout_regression"])
            self.assertTrue((out / "output_render" / "page-001.png").is_file())
            self.assertTrue((out / "output_render" / "contact-sheet.png").is_file())
            with (out / "resume.html").open("a", encoding="utf-8") as handle:
                handle.write("<!-- direct edit -->")
            edited = run(SCRIPTS / "audit_resume.py", "--output-dir", out)
            self.assertNotEqual(edited.returncode, 0)
            self.assertIn("ARTIFACT_HASH_MISMATCH", edited.stdout)

    def test_long_korean_token_and_long_content_render_without_overflow(self) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        token = "초장문한글토큰" * 80
        data["profile"]["paragraphs"] = [token]
        data["career"][0]["projects"][0]["bullets"] *= 18
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "long.json", Path(tmp) / "out"
            src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            compiled = run(SCRIPTS / "compile_resume.py", "--data", src, "--output-dir", out,
                           *evaluation_compile_args(src))
            self.assertEqual(compiled.returncode, 0, compiled.stderr + compiled.stdout)
            audited = run(SCRIPTS / "audit_resume.py", "--output-dir", out)
            self.assertEqual(audited.returncode, 0, audited.stderr + audited.stdout)
            report = json.loads((out / "layout_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(report["overflow_count"], 0)
            self.assertEqual(report["blank_pages"], [])
            self.assertGreater(report["page_count"], 1)
            baseline = json.loads((SKILL / "manifests" / "evaluation-layout-golden.json").read_text(encoding="utf-8"))
            self.assertGreater(report["page_count"], baseline["page_count"])

    def test_malicious_jd_derived_text_is_rejected_before_render(self) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        attack = '<script>globalThis.PWNED=true</script><img src="https://evil.invalid/x">'
        data["profile"]["paragraphs"] = [attack]
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "attack.json", Path(tmp) / "out"
            src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            compiled = run(SCRIPTS / "compile_resume.py", "--data", src, "--output-dir", out,
                           *evaluation_compile_args(src))
            self.assertNotEqual(compiled.returncode, 0, compiled.stderr + compiled.stdout)
            self.assertIn("SCHEMA_INVALID", compiled.stdout)
            self.assertFalse((out / "resume.html").exists())

    def test_fixture_provenance_rejects_unlocked_and_relabelled_content(self) -> None:
        original = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed = json.loads(json.dumps(original))
            changed["profile"]["paragraphs"].append("unlocked derivative")
            changed_path = root / "changed.json"
            changed_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            unlocked = run(SCRIPTS / "compile_resume.py", "--data", changed_path,
                           "--output-dir", root / "unlocked", "--evaluation-fixture")
            self.assertNotEqual(unlocked.returncode, 0)
            self.assertIn("SYNTHETIC_PROVENANCE_INVALID", unlocked.stdout)

            relabelled = json.loads(json.dumps(original))
            relabelled["meta"]["document_purpose"] = "application"
            relabelled_path = root / "relabelled.json"
            relabelled_path.write_text(json.dumps(relabelled, ensure_ascii=False), encoding="utf-8")
            approval = root / "approval.json"
            approval.write_text(json.dumps({
                "approved": True, "resume_data_sha256": digest(relabelled_path),
                "approval_quote": "approved", "approved_at": "2026-01-01T00:00:00Z",
            }), encoding="utf-8")
            production = run(SCRIPTS / "compile_resume.py", "--data", relabelled_path,
                             "--output-dir", root / "production", "--content-approval", approval)
            self.assertNotEqual(production.returncode, 0)
            self.assertIn("SYNTHETIC_CONTENT_FORBIDDEN", production.stdout)

    def test_production_compile_requires_exact_review_provenance(self) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["meta"]["document_purpose"] = "application"
        data["profile"]["paragraphs"].append("Verified production-only content.")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "resume_data.json"
            data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            approval = root / "content_approval.json"
            approval.write_text(json.dumps({
                "approved": True,
                "resume_data_sha256": digest(data_path),
                "approval_quote": "Generate the resume as reviewed.",
                "approved_at": "2026-01-01T00:00:00Z",
            }), encoding="utf-8")

            proc = run(SCRIPTS / "compile_resume.py", "--data", data_path,
                       "--output-dir", root / "out", "--content-approval", approval)
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn("CONTENT_APPROVAL_INVALID", proc.stdout)
            self.assertIn("reviewed_path", proc.stdout)

    def test_production_compile_rejects_stale_review_hash(self) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["meta"]["document_purpose"] = "application"
        data["profile"]["paragraphs"].append("Verified production-only content.")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "resume_data.json"
            data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            review = root / "content_review.md"
            review.write_text("# Approved content\n", encoding="utf-8")
            approval = root / "content_approval.json"
            approval.write_text(json.dumps({
                "approved": True,
                "reviewed_path": "content_review.md",
                "reviewed_sha256": "0" * 64,
                "resume_data_sha256": digest(data_path),
                "approval_quote": "Generate the resume as reviewed.",
                "approved_at": "2026-01-01T00:00:00Z",
            }), encoding="utf-8")

            proc = run(SCRIPTS / "compile_resume.py", "--data", data_path,
                       "--output-dir", root / "out", "--content-approval", approval)
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn("CONTENT_APPROVAL_INVALID", proc.stdout)
            self.assertIn("reviewed_sha256", proc.stdout)

    def test_production_compile_accepts_current_review_and_data_hashes(self) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["meta"]["document_purpose"] = "application"
        data["profile"]["paragraphs"].append("Verified production-only content.")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "resume_data.json"
            data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            review = root / "content_review.md"
            review.write_text("# Approved content\n", encoding="utf-8")
            approval = root / "content_approval.json"
            approval.write_text(json.dumps({
                "approved": True,
                "reviewed_path": "content_review.md",
                "reviewed_sha256": digest(review),
                "resume_data_sha256": digest(data_path),
                "approval_quote": "Generate the resume as reviewed.",
                "approved_at": "2026-01-01T00:00:00Z",
            }), encoding="utf-8")

            proc = run(SCRIPTS / "compile_resume.py", "--data", data_path,
                       "--output-dir", root / "out", "--content-approval", approval)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((root / "out" / "render_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "PRODUCTION")

    def test_arbitrary_chromium_requires_unlock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rejected = run(SCRIPTS / "compile_resume.py", "--data", FIXTURE,
                           "--output-dir", Path(tmp) / "out", "--evaluation-fixture",
                           "--chromium", sys.executable)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("CHROMIUM_LOCK_MISMATCH", rejected.stdout)

    def test_evaluation_golden_is_bound_to_exact_fixture(self) -> None:
        fixture_manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture_manifest["fixtures"]["fixtures/evaluation/fictional_korean_resume.json"],
            digest(FIXTURE),
        )
        golden = json.loads((SKILL / "manifests" / "evaluation-layout-golden.json").read_text(encoding="utf-8"))
        self.assertEqual(golden["fixture_sha256"], digest(FIXTURE))
        self.assertEqual(golden["chromium_revision"], "1187")

    def test_workflow_stale_approval_and_generated_artifact_requirement(self) -> None:
        self_test = run(SCRIPTS / "self_test.py")
        self.assertEqual(self_test.returncode, 0, self_test.stderr + self_test.stdout)
        payload = json.loads(self_test.stdout)
        tests = {item["test"]: item["pass"] for item in payload["tests"]}
        self.assertTrue(tests["stale_approval_is_rejected"])
        self.assertTrue(tests["final_requires_generated_artifacts"])

    @staticmethod
    def _fake_codex(path: Path, mode: str = "valid", external_secret: Path | None = None) -> None:
        argv_path = path.with_name("codex-argv.json")
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, re, sys\n"
            f"MODE={mode!r}\n"
            "cwd=pathlib.Path.cwd(); prompt=sys.argv[-1]\n"
            "match=re.search(r'Corpus case ID: ([a-z0-9_-]+)', prompt)\n"
            "if match:\n"
            f"  case=match.group(1); decisions={CORPUS_DECISIONS!r}\n"
            "  assert not (cwd/'.agents/skills/jd-tailored-resume/fixtures/evaluation/eval_prompts.jsonl').exists()\n"
            "  decision=decisions[case]\n"
            "  if MODE == 'corpus_write': (cwd/'leaked.txt').write_text('unexpected', encoding='utf-8')\n"
            "  text=json.dumps({'case_id':case,'decision':decision})\n"
            "  print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}))\n"
            "  raise SystemExit(0)\n"
            f"pathlib.Path({str(argv_path)!r}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'graded bundle ready'}}))\n"
            "if MODE == 'proof':\n"
            "  (cwd/'agent-proof.txt').write_text('generated', encoding='utf-8'); raise SystemExit(0)\n"
            + (f"if MODE == 'external_symlink': (cwd/'secret-link').symlink_to(pathlib.Path({str(external_secret)!r})); raise SystemExit(0)\n"
               if external_secret is not None else "") +
            "skill=cwd/'.agents/skills/jd-tailored-resume'; run=cwd/'run'; run.mkdir()\n"
            "if MODE == 'fabricated':\n"
            "  files={'jd_snapshot.md':'# Public JD snapshot\\n', 'resume_data.json':'{}\\n', "
            "'resume.html':'<html>evaluation</html>\\n', 'resume.pdf':'%PDF synthetic evaluation\\n'}\n"
            "  for name,value in files.items(): (run/name).write_text(value, encoding='utf-8')\n"
            "  (run/'render_manifest.json').write_text(json.dumps({'status':'EVALUATION_ONLY'}), encoding='utf-8')\n"
            "  (run/'layout_audit.json').write_text(json.dumps({'status':'PASS'}), encoding='utf-8')\n"
            "else:\n"
            "  fixture=skill/'fixtures/evaluation/fictional_korean_resume.json'\n"
            "  (run/'resume_data.json').write_bytes(fixture.read_bytes())\n"
            "  (run/'jd_snapshot.md').write_text('# Public JD snapshot\\n', encoding='utf-8')\n"
            "if MODE == 'root_extra': (cwd/'unexpected.txt').write_text('unexpected', encoding='utf-8')\n"
            "if MODE == 'run_extra': (run/'extra.txt').write_text('unexpected', encoding='utf-8')\n"
            "if MODE == 'jd_symlink': (run/'jd_snapshot.md').unlink(); (run/'jd_snapshot.md').symlink_to(fixture)\n"
            "if MODE == 'data_symlink': (run/'resume_data.json').unlink(); (run/'resume_data.json').symlink_to(fixture)\n"
            "if MODE == 'spoof':\n"
            "  (run/'resume.html').write_text('<html>agent spoof</html>', encoding='utf-8')\n"
            "  (run/'resume.pdf').write_text('%PDF agent spoof', encoding='utf-8')\n"
            "  (run/'render_manifest.json').write_text(json.dumps({'status':'EVALUATION_ONLY'}), encoding='utf-8')\n"
            "  (run/'layout_audit.json').write_text(json.dumps({'status':'PASS'}), encoding='utf-8')\n"
            "if MODE == 'fixture_mutated':\n"
            "  data=json.loads((run/'resume_data.json').read_text(encoding='utf-8')); data['header']['name']='Mutated'\n"
            "  (run/'resume_data.json').write_text(json.dumps(data), encoding='utf-8')\n"
            "if MODE == 'mutate':\n"
            "  (cwd/'.agents/skills/jd-tailored-resume/SKILL.md').write_text('mutated', encoding='utf-8')\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def test_eval_runner_rejects_exit_zero_without_graded_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_codex.py"
            self._fake_codex(fake, "proof")
            out = root / "evaluation"
            proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                       "--output-dir", out, "--codex-bin", fake)
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "FAIL")
            self.assertFalse(manifest["checks"]["required_artifacts"]["pass"])

    def test_eval_runner_never_dereferences_external_scratch_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = root / "external-secret.txt"
            secret.write_text("DO-NOT-COPY-THIS-SECRET", encoding="utf-8")
            fake = root / "fake_codex.py"
            self._fake_codex(fake, "external_symlink", secret)
            out = root / "evaluation"
            proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                       "--output-dir", out, "--codex-bin", fake)
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            copied_link = out / "scratch-artifacts" / "secret-link"
            self.assertFalse(copied_link.exists())
            self.assertFalse(copied_link.is_symlink())
            output_bytes = b"".join(path.read_bytes() for path in out.rglob("*") if path.is_file())
            self.assertNotIn(b"DO-NOT-COPY-THIS-SECRET", output_bytes)
            self.assertEqual(manifest["scratch_artifacts_skipped"], [
                {"path": "secret-link", "reason": "symlink"},
            ])

    def test_copy_scratch_artifacts_rejects_symlink_before_resolve(self) -> None:
        spec = importlib.util.spec_from_file_location("resume_eval_runner_copy", SCRIPTS / "eval_runner.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        assert spec is not None and spec.loader is not None
        eval_runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(eval_runner)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scratch = root / "scratch"
            scratch.mkdir()
            link = scratch / "dangling-link"
            link.symlink_to(root / "missing-external-target")
            destination = root / "artifacts"
            original_realpath = os.path.realpath

            def guarded_realpath(path: str | os.PathLike[str], *, strict: bool = False) -> str:
                if os.fspath(path) == os.fspath(link):
                    raise AssertionError("symlink must be rejected before resolve")
                return original_realpath(path, strict=strict)

            with mock.patch.object(eval_runner.os.path, "realpath", side_effect=guarded_realpath) as realpath_mock:
                copied, skipped = eval_runner.copy_scratch_artifacts(scratch, destination)

            resolved_paths = [os.fspath(call.args[0]) for call in realpath_mock.call_args_list]
            self.assertNotIn(os.fspath(link), resolved_paths)
            self.assertEqual(copied, [])
            self.assertEqual(skipped, [{"path": "dangling-link", "reason": "symlink"}])
            self.assertFalse((destination / link.name).exists())
            self.assertFalse((destination / link.name).is_symlink())

    def test_eval_runner_grades_bundle_trace_flags_and_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_codex.py"
            self._fake_codex(fake)
            out = root / "evaluation"
            proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                       "--output-dir", out, "--codex-bin", fake)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "PASS")
            self.assertTrue(all(check["pass"] for check in manifest["checks"].values()))
            self.assertTrue((out / "scratch-artifacts" / "run" / "resume.pdf").is_file())
            self.assertTrue((out / "scratch-artifacts" / "run" / "render_manifest.json").is_file())
            self.assertTrue((out / "scratch-artifacts" / "run" / "layout_audit.json").is_file())
            materialization = manifest["checks"]["controller_materialization"]
            semantic_only = materialization["agent_semantic_only"]
            self.assertTrue(semantic_only["pass"])
            self.assertEqual(semantic_only["observed_paths"], [
                "run/jd_snapshot.md", "run/resume_data.json",
            ])
            self.assertEqual(semantic_only["unexpected_paths"], [])
            self.assertEqual(semantic_only["non_regular_paths"], [])
            self.assertEqual(materialization["compile"]["returncode"], 0)
            self.assertEqual(materialization["audit"]["returncode"], 0)
            self.assertEqual(materialization["compile"]["command"][0], sys.executable)
            self.assertEqual(
                Path(materialization["compile"]["command"][3]).relative_to(Path(manifest["scratch_directory"])).as_posix(),
                ".agents/skills/jd-tailored-resume/fixtures/evaluation/fictional_korean_resume.json",
            )
            self.assertNotEqual(Path(manifest["scratch_directory"]), REPO)
            prompt = (out / "codex-prompt.txt").read_text(encoding="utf-8")
            self.assertNotIn(str(Path.home()), prompt)
            self.assertIn("exact locked semantic fixture", prompt)
            self.assertIn("trusted controller renders", prompt)
            self.assertFalse((out / "scratch-artifacts" / "codex-argv.json").exists())
            argv = json.loads((root / "codex-argv.json").read_text(encoding="utf-8"))
            expected_flags = [
                "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
                "--config", "sandbox_workspace_write.network_access=true",
                "--sandbox", "workspace-write", "--skip-git-repo-check",
            ]
            self.assertEqual(argv[:-1], expected_flags)
            self.assertEqual(manifest["codex_command"], [str(fake), *expected_flags, "<prompt>"])
            self.assertTrue(manifest["checks"]["git_repository"]["pass"])

    def test_eval_runner_rejects_fabricated_bundle_with_fake_hashes_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_codex.py"
            self._fake_codex(fake, "fabricated")
            out = root / "evaluation"
            proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                       "--output-dir", out, "--codex-bin", fake)
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "FAIL")
            self.assertFalse(manifest["checks"]["controller_materialization"]["pass"])
            self.assertFalse((out / "scratch-artifacts" / "run" / "resume.html").exists())
            self.assertFalse((out / "scratch-artifacts" / "run" / "resume.pdf").exists())

    def test_eval_runner_rejects_agent_authored_presentation_artifacts_before_compilation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_codex.py"
            self._fake_codex(fake, "spoof")
            out = root / "evaluation"
            proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                       "--output-dir", out, "--codex-bin", fake)
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            materialization = manifest["checks"]["controller_materialization"]
            semantic_only = materialization["agent_semantic_only"]
            self.assertFalse(semantic_only["pass"])
            self.assertEqual(set(semantic_only["unexpected_paths"]), {
                "run/layout_audit.json", "run/render_manifest.json", "run/resume.html", "run/resume.pdf",
            })
            self.assertIsNone(materialization["compile"]["returncode"])
            reset = materialization["presentation_reset"]
            self.assertEqual(set(reset["removed"]), {
                "resume.html", "resume.pdf", "render_manifest.json", "layout_audit.json",
            })
            self.assertFalse((out / "scratch-artifacts" / "run" / "resume.html").exists())

    def test_eval_runner_rejects_nonsemantic_handoff_files(self) -> None:
        cases = {
            "root_extra": ["unexpected.txt"],
            "run_extra": ["run/extra.txt"],
        }
        for mode, unexpected_paths in cases.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake = root / "fake_codex.py"
                self._fake_codex(fake, mode)
                out = root / "evaluation"
                proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                           "--output-dir", out, "--codex-bin", fake)
                self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
                materialization = manifest["checks"]["controller_materialization"]
                self.assertFalse(materialization["agent_semantic_only"]["pass"])
                self.assertEqual(materialization["agent_semantic_only"]["unexpected_paths"], unexpected_paths)
                self.assertIsNone(materialization["compile"]["returncode"])

    def test_eval_runner_rejects_symlinked_semantic_handoff_files(self) -> None:
        cases = {
            "jd_symlink": ["run/jd_snapshot.md"],
            "data_symlink": ["run/resume_data.json"],
        }
        for mode, non_regular_paths in cases.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake = root / "fake_codex.py"
                self._fake_codex(fake, mode)
                out = root / "evaluation"
                proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                           "--output-dir", out, "--codex-bin", fake)
                self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
                materialization = manifest["checks"]["controller_materialization"]
                semantic_only = materialization["agent_semantic_only"]
                self.assertFalse(semantic_only["pass"])
                self.assertEqual(semantic_only["unexpected_paths"], [])
                self.assertEqual(semantic_only["non_regular_paths"], non_regular_paths)
                self.assertIsNone(materialization["compile"]["returncode"])

    def test_eval_runner_rejects_mutated_semantic_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_codex.py"
            self._fake_codex(fake, "fixture_mutated")
            out = root / "evaluation"
            proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                       "--output-dir", out, "--codex-bin", fake)
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            materialization = manifest["checks"]["controller_materialization"]
            self.assertFalse(materialization["pass"])
            self.assertFalse(materialization["fixture_exact"]["pass"])
            self.assertIsNone(materialization["compile"]["returncode"])

    def test_eval_runner_rejects_skill_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_codex.py"
            self._fake_codex(fake, "mutate")
            out = root / "evaluation"
            proc = run(SCRIPTS / "eval_runner.py", "--jd-url", "https://example.com/jobs/42",
                       "--output-dir", out, "--codex-bin", fake)
            self.assertNotEqual(proc.returncode, 0)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["checks"]["skill_unchanged"]["pass"])

    def test_eval_runner_executes_and_grades_prompt_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_codex.py"
            self._fake_codex(fake)
            out = root / "corpus"
            proc = run(SCRIPTS / "eval_runner.py", "--corpus", CORPUS,
                       "--output-dir", out, "--codex-bin", fake)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "PASS")
            self.assertGreaterEqual(manifest["corpus"]["case_count"], 10)
            self.assertEqual(manifest["corpus"]["case_count"], manifest["corpus"]["passed"])
            self.assertTrue(all(item["executed"] and item["pass"] for item in manifest["corpus"]["results"]))
            self.assertTrue(all(item["unexpected_files"] == [] for item in manifest["corpus"]["results"]))
            prompts = [
                path.read_text(encoding="utf-8")
                for path in (out / "corpus").glob("*/codex-prompt.txt")
            ]
            self.assertEqual(len(prompts), 12)
            self.assertTrue(all("expected_decision" not in prompt for prompt in prompts))
            self.assertTrue(all("create no files" in prompt.lower() for prompt in prompts))
            self.assertTrue(all("perform no external action" in prompt.lower() for prompt in prompts))

    def test_eval_runner_rejects_unsafe_corpus_case_ids(self) -> None:
        invalid_ids = {
            "traversal": "../../escaped-0",
            "absolute": "/tmp/escaped-0",
            "forward_separator": "nested/case",
            "backslash_separator": r"nested\case",
            "dot": ".",
            "dotdot": "..",
        }
        source_cases = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
        for label, invalid_id in invalid_ids.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                cases = [dict(case) for case in source_cases]
                cases[0]["id"] = invalid_id
                corpus = root / "corpus.jsonl"
                corpus.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8")
                out = root / "evaluation"
                proc = run(SCRIPTS / "eval_runner.py", "--corpus", corpus,
                           "--output-dir", out, "--codex-bin", root / "must-not-run")
                self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
                self.assertIn("invalid id", manifest["error"])
                self.assertFalse((root / "escaped-0").exists())

    def test_eval_runner_rejects_duplicate_corpus_case_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
            cases[1]["id"] = cases[0]["id"]
            corpus = root / "corpus.jsonl"
            corpus.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8")
            out = root / "evaluation"
            proc = run(SCRIPTS / "eval_runner.py", "--corpus", corpus,
                       "--output-dir", out, "--codex-bin", root / "must-not-run")
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("duplicate id", manifest["error"])

    def test_corpus_correct_decision_with_file_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_codex.py"
            self._fake_codex(fake, "corpus_write")
            out = root / "corpus"
            proc = run(SCRIPTS / "eval_runner.py", "--corpus", CORPUS,
                       "--output-dir", out, "--codex-bin", fake)
            self.assertNotEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            manifest = json.loads((out / "evaluation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "FAIL")
            self.assertTrue(all(not item["pass"] for item in manifest["corpus"]["results"]))
            self.assertTrue(all(item["actual_decision"] == item["expected_decision"] for item in manifest["corpus"]["results"]))
            self.assertTrue(all(item["unexpected_files"] == ["leaked.txt"] for item in manifest["corpus"]["results"]))


if __name__ == "__main__":
    unittest.main()
