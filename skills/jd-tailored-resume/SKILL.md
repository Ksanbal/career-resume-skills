---
name: jd-tailored-resume
description: Tailor evidence-backed resumes to verified JDs.
version: 1.0.0
author: Ksanbal, Codex
license: MIT
platforms: [linux, macos, windows]
metadata:
  tags: [career, resume, job-description, recruiting]
---

# JD-Tailored Resume

Create a job-specific resume from a verified job description and a user-supplied, verified baseline. Preserve the candidate's full history by default, ask targeted questions before drafting, obtain explicit approval of content before rendering, and never invent experience, metrics, credentials, proficiency, compensation, or application history.

## When to Use

- The user provides a JD URL, text, or PDF and wants a tailored resume.
- The user wants evidence-based matching, content review, HTML/PDF rendering, or an independent hiring review.
- The user has a verified standard resume or publication baseline.

Do not use for broad job discovery, application submission, recruiter contact, profile publication, or modifying a canonical baseline.

## Prerequisites

- Obtain a local verified baseline: structured resume data plus its evidence/trace file, or an immutable published resume whose visible claims can be traced.
- Use the user's canonical career source read-only. Never copy private source IDs, tokens, contact data, or evidence into the skill repository.
- Verify live JDs on the company careers page when possible. Record URL, status, and checked time.
- For logged-in or interactive browser work, use the browser route explicitly approved by the user. If the user requires Aside Browser, use `aside`; do not silently switch browsers.
- Create a unique local run directory outside this skill. All candidate data and generated files stay there.
- Use `scripts/validate_workflow.py` before content approval and before rendering.

## Required Run Artifacts

```text
<run>/
  jd_snapshot.md
  company_role_research.md
  requirement_matrix.json
  baseline_inventory.json
  evidence_match_matrix.json
  user_context.json
  selection_plan.json
  baseline_comparison.md
  content_review.md
  content_approval.json          # only after explicit approval
  resume_data.json               # only after approval
  claim_trace.json               # only after approval
  resume.html                    # only after approval
  resume.pdf                     # only after approval
  reviewer_report.json
  review_decisions.md
  validation_report.md
```

`content_approval.json` binds the user's approval to `content_review.md`. After
generation, add `resume_data_sha256` and a `generated_artifact_hashes` mapping for
all four generated files. These fields are integrity records, not a substitute
for the user's approval quote.

## Procedure

### 1. Verify and freeze the JD

Capture the exact JD text, company, role, posting ID, work arrangement, deadline, source URL, open/closed status, authority level, and checked timestamp in `jd_snapshot.md`. Prefer the company careers page. Label blocked, stale, cached, syndicated, or conflicting copies.

Completion criterion: the authoritative source and current status are explicit; no search snippet is treated as the JD.

### 2. Research only decision-changing context

Research product, customers, operating constraints, team responsibilities, required capabilities, preferred capabilities, leadership expectations, and likely screening signals. Separate verified facts, interpretation, and resume implications in `company_role_research.md`, with source URLs and checked times.

Completion criterion: every external fact has a source; unsupported praise and hiring-intent speculation are absent.

### 3. Decompose requirements

Write `requirement_matrix.json`. Give every must-have, preference, responsibility, competency, and domain signal a stable requirement ID, original text, importance, expected evidence, ATS terms, resume surface, and uncertainty.

Completion criterion: every material JD statement maps to one requirement ID.

### 4. Freeze the verified baseline

Inventory every visible baseline unit: title, profile sentence, role, role bullet, project summary, project bullet, skill, education, activity, certification, and award. Record source hashes and trace IDs in `baseline_inventory.json`. Do not reconstruct a baseline from unverified notes.

Default to 100% visible-unit preservation. Reordering and emphasis are allowed; deletion or lossy merging requires the user's exact approval.

Completion criterion: the baseline remains unchanged and every visible unit is accounted for.

### 5. Match evidence conservatively

For each requirement, classify the candidate evidence as `direct`, `transferable`, `partial`, `gap`, or `unknown`. Record evidence references, publication boundaries, and forbidden extrapolations in `evidence_match_matrix.json`. Missing resume text is not proof that the candidate lacks the experience.

Completion criterion: every positive match is traceable and `gap` is kept distinct from `unknown`.

### 6. Ask the candidate before writing resume copy

After research and evidence matching—but before writing proposed resume copy—ask 1–5 independent, high-impact questions in one batch. Ask only what the canonical source does not answer, such as:

- actual scope and decision authority;
- technical depth, constraints, and trade-offs;
- collaboration, leadership, and stakeholder communication;
- operational validation or evidence-backed outcomes;
- public disclosure boundaries;
- what the candidate wants emphasized or avoided for this application.

For each question, state why it matters and which requirement IDs it affects. Ask dependent follow-ups only after the first answer. Accept `unknown` and `declined`; never pressure the user to provide a metric.

Save the exact questions and responses in `user_context.json` using `templates/user_context.example.json` as the shape. Do not automatically promote a user's new answer to canonically verified evidence.

Completion criterion: at least one real user question was answered, declined, or marked unknown; every question has exactly one response; no resume copy or rendered artifact exists yet.

### 7. Prepare content only and request approval

Create:

- `selection_plan.json`: preservation, emphasis, order, and any proposed omission;
- `baseline_comparison.md`: `baseline → tailored`, change type, JD reason, evidence level, expected screening effect, unchanged core history, and uncertainties;
- `content_review.md`: the exact proposed visible content and order for Profile, Skills, Career, Projects, Side Projects, Education, Activities/Certifications/Awards. Write `None` for genuinely absent sections.

Send the important content in the user message, not only as a file. Ask for one explicit decision:

1. **Generate the resume as reviewed**
2. **Revise and show the content again**
3. **Stop**

Do not create `resume_data.json`, `claim_trace.json`, HTML, PDF, or layout images before approval. After approval, write `content_approval.json` with `approved: true`, `reviewed_path: content_review.md`, the current SHA-256, the user's exact approval quote, and approval time.

Run:

```bash
python scripts/validate_workflow.py --run-dir <run> --stage generation
```

Completion criterion: validation passes and the approval hash matches the current content. Any content or order change invalidates approval.

### 8. Generate only the approved content

Build structured data and trace, then render HTML/PDF using the baseline's visual system. Do not silently add meaning, metrics, skills, experience, or ownership beyond the approved content. Keep readable A4 typography; increase page count instead of shrinking or deleting content.

Record the SHA-256 of `resume_data.json`, `claim_trace.json`, `resume.html`, and
`resume.pdf` under `generated_artifact_hashes` in `content_approval.json`. Set
`resume_data_sha256` to the same value as the `resume_data.json` entry. Then run:

```bash
python scripts/validate_workflow.py --run-dir <run> --stage final
```

Completion criterion: the final gate passes; every generated file is present and
matches its recorded hash; the PDF has searchable text and no blank pages,
clipping, overlap, missing glyphs, orphan headings, or unapproved content changes.

### 9. Run an independent hiring review

Use a separate review context or agent when available. Give it the JD, research, matrices, approved content, generated artifacts, and hashes—but not raw private evidence unless necessary. Review from HR 10-second-screen and hiring-manager perspectives. Require exact P0/P1/P2 findings with current text, problem, proposed change, reason, and evidence risk.

If a recommendation changes visible wording or order, update `content_review.md`, invalidate `content_approval.json`, and ask the user to approve the revised content before rerendering. Never treat reviewer prose as evidence.

Completion criterion: no unresolved P0; all semantic changes were re-approved.

### 10. Validate and deliver

Deliver PDF, HTML, validation report, and a concise message containing:

- **Key emphasis:** what became more prominent than in the baseline;
- **Reason:** the exact JD or company/role context behind it;
- **Baseline changes:** important `before → after` changes;
- **Preserved content:** what intentionally stayed unchanged;
- **Remaining uncertainty:** partial matches, gaps, unknowns, and user decisions.

Do not submit an application, contact anyone, publish a profile, or write to external systems without separate explicit approval.

## Synthetic Evaluation

`fixtures/evaluation/` is synthetic and non-production. The **candidate fixture**
is fictional; the supplied JD is a real public source and must not be described as
fictional. Never remove the fixture's visible evaluation labeling or use it for a
real application.

### Synthetic evaluation protocol (evaluation mode only)

Use this contextless protocol for the clean-agent run; it is an evaluation-only
exception to the production questions and approval flow:

1. Verify the public JD Aside-first. If and when `aside` exists, inspect its current
   one-shot interface with `aside repl --help`, then use an Aside one-shot snapshot
   before trying any other network route:

   ```bash
   aside repl "const p = await openTab('<public-jd-url>'); const s = await snapshot(p); console.log(s.tree);"
   ```

   Do not stop at a redirect, aggregator, or syndicated copy. If the page names or
   links an original careers source, follow it and record that original source URL,
   status, and checked time in `run/jd_snapshot.md`. Only after this Aside attempt
   may you try `curl` or web search. A snippet alone is not verification; fail closed
   and do not render if the JD and its source remain blocked or unverifiable.
2. The exact locked
   `.agents/skills/jd-tailored-resume/fixtures/evaluation/fictional_korean_resume.json`
   is pre-authorized evaluation-only input. Do not ask a real user question. Do not
   request production content approval. Do not alter or relabel the fixture, and do
   not convert its claims into candidate-specific content.
3. The agent must create only `run/jd_snapshot.md` and `run/resume_data.json`.
   At handoff, these must be regular, non-symlink files, and no other file or
   symlink may exist anywhere in the scratch workspace outside `.agents/` and
   `.git/`. Put any network, retrieval, or browser temporary files under
   `$TMPDIR`, never in the scratch root or `run/`, and delete them before
   handoff so they do not survive the agent run. Copy the locked fixture
   byte-for-byte; do not parse and rewrite it:

   ```bash
   mkdir -p run
   cp .agents/skills/jd-tailored-resume/fixtures/evaluation/fictional_korean_resume.json run/resume_data.json
   ```

   Do not create or modify `resume.html`, `resume.pdf`, `render_manifest.json`,
   `layout_audit.json`, or `output_render/`. After the agent exits, the trusted
   evaluation controller first verifies the semantic-only handoff boundary, then
   verifies the JD snapshot, schema, exact locked fixture hash, and skill
   immutability. Any extra file or symlink fails the run before compilation. The
   controller removes presentation artifacts defensively, then runs the fixed
   scoped compiler and auditor outside the agent sandbox only after every
   prerequisite passes.

Production mode remains governed by the approval requirements above; this protocol
does not waive or weaken them for any real candidate resume.

Run the clean-agent grader with:

```bash
python scripts/eval_runner.py \
  --jd-url https://jobs.example.com/roles/platform-lead \
  --output-dir evaluation-output/run-001
```

The runner uses a real temporary `git init`, installs only this skill at
`.agents/skills/jd-tailored-resume`, and invokes:

```text
codex exec --json --ephemeral --ignore-user-config --ignore-rules --config sandbox_workspace_write.network_access=true --sandbox workspace-write --skip-git-repo-check <prompt>
```

Its primary prompt contains only the skill invocation, public JD URL, semantic-only
synthetic mode declaration, and `run/` output path. The agent supplies only a
nonempty `run/jd_snapshot.md` and byte-identical locked `resume_data.json`. The
controller then materializes and grades all six artifacts. PASS requires a fully
valid JSONL trace with an agent message; exact fixture provenance and schema;
`EVALUATION_ONLY` render status; a fresh independent `PASS` audit; matching artifact
hashes; and no source or installed skill mutation. Controller command evidence and
per-check grades are copied to `evaluation_manifest.json` and `scratch-artifacts/`.

Corpus mode is a policy-control evaluation, separate from the full clean-agent E2E.
It installs this skill without `eval_prompts.jsonl`; prompts include case data but no
expected label, disable network access, require no files or external actions, and
accept only JSON with `case_id` and `decision`. Execute all 12 explicit, implicit,
context, and negative controls deterministically:

```bash
python scripts/eval_runner.py \
  --corpus fixtures/evaluation/eval_prompts.jsonl \
  --output-dir evaluation-output/corpus-001
```

Live Codex corpus evaluation is opt-in. CI executes every control with a
label-independent deterministic fake and never makes a live model or network call.
Use the clean-agent E2E above to evaluate rendering and artifact provenance.

## Pitfalls

- Do not ask generic questions already answered by the baseline or career source.
- Do not draft first and ask questions afterward.
- Do not interpret “please review” as approval to generate.
- Do not reuse an approval after changing `content_review.md`.
- Do not deliver generated files with absent, stale, or mismatched artifact hashes.
- Do not treat synthetic evaluation output as a production resume.
- Do not optimize by deleting history, repeating JD keywords, or inventing metrics.
- Do not expose internal evidence IDs, private notes, tokens, source IDs, or workflow labels in public resume files.
- Do not silently fall back from a user-required browser or data route.

## Verification

- [ ] Authoritative JD source, status, and checked time recorded
- [ ] Facts, interpretation, and advice separated
- [ ] Every material JD requirement normalized
- [ ] Verified baseline frozen and all visible units inventoried
- [ ] Evidence classified as direct/transferable/partial/gap/unknown
- [ ] Candidate asked at least one high-impact question before drafting
- [ ] Every question has exactly one response state
- [ ] Exact proposed content shown before generation
- [ ] Current content hash explicitly approved
- [ ] No structured resume, HTML, or PDF created before approval
- [ ] Final generated files exist and match every recorded SHA-256
- [ ] Any post-review semantic change re-approved
- [ ] Baseline comparison and uncertainty included in delivery message
- [ ] No invented facts or unapproved external action
